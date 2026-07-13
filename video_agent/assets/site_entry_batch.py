from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from video_agent.ai.gpt_image import edit_image
from video_agent.assets.materializer import _prompt
from video_agent.contracts import DeriveKind
from video_agent.io import load_json, sha256_file, utc_now, write_json_atomic


SUFFIX = "_功能入口截图"


@dataclass(frozen=True)
class SiteEntrySource:
    path: Path
    site: str
    module: str
    feature_path: tuple[str, ...]
    target: str


def parse_site_entry_filename(path: Path) -> SiteEntrySource:
    stem = path.stem
    if not stem.endswith(SUFFIX):
        raise ValueError(f"not a feature-entry screenshot: {path.name}")
    parts = stem[: -len(SUFFIX)].split("_")
    if len(parts) < 3:
        raise ValueError(f"feature-entry filename has too few segments: {path.name}")
    site, module, *feature_parts = parts
    target_parts = feature_parts[1:] if feature_parts[0] == "图文广告" and len(feature_parts) > 1 else feature_parts
    target = "/".join(target_parts)
    return SiteEntrySource(path=path, site=site, module=module, feature_path=tuple(feature_parts), target=target)


def _instruction(source: SiteEntrySource) -> str:
    hierarchy = " -> ".join(source.feature_path)
    nested = (
        "这是图文广告的二级子菜单入口；保留左侧文生图 Hover 菜单和右侧图文广告子菜单，并只在右侧子菜单中标注目标。"
        if source.feature_path[0] == "图文广告" and len(source.feature_path) > 1
        else "这是文生图一级 Hover 菜单入口；只在左侧文生图导航展开的菜单中标注目标。"
    )
    return (
        f"文件名解析路径是 {source.site} -> {source.module} -> {hierarchy}，唯一目标文字是“{source.target}”。"
        f"{nested}使用醒目的红色手绘双线圆圈或椭圆自然圈住“{source.target}”，根据文字长度自适应形状，"
        "目标文字应位于标记视觉中心并保留呼吸空间。标记可以覆盖周围空白，但不能圈入、接触或指向相邻功能。"
        "不要使用规则矩形，不要标注首页顶部快捷按钮，不要添加箭头、鼠标或解释文案。"
    )


def _output_name(source: SiteEntrySource) -> str:
    return source.path.name.replace("功能入口截图", "功能入口关键帧")


def _build_callout_layers(output: Path) -> dict[str, Any]:
    rgba = cv2.imdecode(np.fromfile(output, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
    if rgba is None:
        raise ValueError(f"unable to read approved feature-entry image: {output}")
    if rgba.ndim == 2:
        rgba = cv2.cvtColor(rgba, cv2.COLOR_GRAY2BGRA)
    elif rgba.shape[2] == 3:
        rgba = cv2.cvtColor(rgba, cv2.COLOR_BGR2BGRA)
    b, g, r, _ = cv2.split(rgba)
    red = ((r > 175) & (r.astype(np.float32) > g * 1.55) & (r.astype(np.float32) > b * 1.55)).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(red, 8)
    if count <= 1:
        raise ValueError(f"approved feature-entry image has no isolated red callout: {output.name}")
    candidates = [
        component
        for component in range(1, count)
        if int(stats[component, cv2.CC_STAT_AREA]) >= 20
        and int(stats[component, cv2.CC_STAT_TOP]) >= round(rgba.shape[0] * 0.12)
    ]
    if not candidates:
        raise ValueError(f"approved feature-entry image has no callout outside the brand header: {output.name}")
    component_area = sum(int(stats[component, cv2.CC_STAT_AREA]) for component in candidates)
    if component_area < 300:
        raise ValueError(f"red callout components are too small: {output.name}/{component_area}px")
    mask = np.where(np.isin(labels, candidates), 255, 0).astype(np.uint8)
    mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=1)

    layer = np.zeros_like(rgba)
    layer[:, :, :3] = rgba[:, :, :3]
    layer[:, :, 3] = mask
    repair_mask = cv2.dilate(mask, np.ones((13, 13), np.uint8), iterations=1)
    base_bgr = cv2.inpaint(rgba[:, :, :3], repair_mask, 7, cv2.INPAINT_TELEA)
    base = cv2.cvtColor(base_bgr, cv2.COLOR_BGR2BGRA)

    layer_dir = output.parent / "layers"
    layer_dir.mkdir(parents=True, exist_ok=True)
    base_path = layer_dir / output.name.replace("关键帧", "无圈底图")
    layer_path = layer_dir / output.name.replace("关键帧", "圈选层")
    base_ok, base_buffer = cv2.imencode(".png", base)
    layer_ok, layer_buffer = cv2.imencode(".png", layer)
    if not base_ok or not layer_ok:
        raise OSError(f"unable to encode callout layers for {output.name}")
    base_buffer.tofile(base_path)
    layer_buffer.tofile(layer_path)
    return {
        "callout_base_path": base_path.resolve().as_posix(),
        "callout_base_sha256": sha256_file(base_path),
        "callout_layer_path": layer_path.resolve().as_posix(),
        "callout_layer_sha256": sha256_file(layer_path),
        "callout_component_area": component_area,
        "callout_layer_method": "red_stroke_components_below_brand_header_v2",
    }


def generate_site_entry_keyframes(
    repo_root: Path,
    source_dir: Path,
    output_dir: Path,
    *,
    workers: int = 3,
    force: bool = False,
) -> dict[str, Any]:
    sources = [
        parse_site_entry_filename(path)
        for path in sorted(source_dir.glob(f"*_文生图_*{SUFFIX}.*"))
        if path.suffix.lower() in {".png", ".jpg", ".jpeg"}
    ]
    if not sources:
        raise FileNotFoundError(f"no feature-entry screenshots found in {source_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    previous = load_json(manifest_path) if manifest_path.is_file() else {}
    previous_by_source = {item["source_path"]: item for item in previous.get("assets", []) if isinstance(item, dict) and item.get("source_path")}
    recipe_prompt, template_sha256 = _prompt(repo_root, DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME, "{batch_instruction}")

    results: list[dict[str, Any]] = []
    pending: list[tuple[SiteEntrySource, Path, str, str, str]] = []
    for source in sources:
        instruction = _instruction(source)
        prompt = recipe_prompt.replace("{batch_instruction}", instruction)
        source_sha256 = sha256_file(source.path)
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        output = output_dir / _output_name(source)
        old = previous_by_source.get(source.path.resolve().as_posix())
        if (
            not force
            and old
            and old.get("source_sha256") == source_sha256
            and old.get("prompt_sha256") == prompt_sha256
            and output.is_file()
            and old.get("output_sha256") == sha256_file(output)
        ):
            results.append({**old, "status": "cached"})
            continue
        pending.append((source, output, prompt, source_sha256, prompt_sha256))

    def generate(item: tuple[SiteEntrySource, Path, str, str, str]) -> dict[str, Any]:
        source, output, prompt, source_sha256, prompt_sha256 = item
        result = edit_image(repo_root, source.path, prompt)
        output.write_bytes(result.content)
        with Image.open(output) as image:
            width, height = image.size
            image.verify()
        return {
            "source_path": source.path.resolve().as_posix(),
            "source_filename": source.path.name,
            "source_sha256": source_sha256,
            "output_path": output.resolve().as_posix(),
            "output_filename": output.name,
            "output_sha256": sha256_file(output),
            "width": width,
            "height": height,
            "site": source.site,
            "module": source.module,
            "feature_path": list(source.feature_path),
            "target": source.target,
            "annotation_style": "red_hand_drawn_double_stroke_circle_or_ellipse",
            "prompt_sha256": prompt_sha256,
            "prompt_template_sha256": template_sha256,
            "provider": result.provider,
            "model": result.model,
            "response_id": result.response_id,
            "quality_status": "unreviewed",
            "status": "generated",
        }

    errors: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {executor.submit(generate, item): item[0] for item in pending}
        for future in as_completed(futures):
            source = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001
                errors.append({"source_filename": source.path.name, "type": exc.__class__.__name__, "message": str(exc)})

    results.sort(key=lambda item: item["source_filename"])
    manifest = {
        "schema_version": 1,
        "generated_at": utc_now(),
        "workflow": "site_feature_entry_gpt_image_batch",
        "annotation_style": "red_hand_drawn_double_stroke_circle_or_ellipse",
        "source_dir": source_dir.resolve().as_posix(),
        "output_dir": output_dir.resolve().as_posix(),
        "assets": results,
        "errors": errors,
    }
    write_json_atomic(manifest_path, manifest)
    if errors:
        raise RuntimeError(f"site-entry batch completed with {len(errors)} errors; see {manifest_path}")
    return {"total": len(sources), "generated": len(pending), "cached": len(sources) - len(pending), "manifest": manifest_path.as_posix()}


def approve_site_entry_manifest(manifest_path: Path) -> dict[str, int]:
    manifest = load_json(manifest_path)
    assets = manifest.get("assets") if isinstance(manifest, dict) else None
    if not isinstance(assets, list):
        raise ValueError(f"invalid site-entry manifest: {manifest_path}")
    approved = 0
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        output = Path(str(asset.get("output_path") or ""))
        if not output.is_file():
            raise FileNotFoundError(f"approved feature-entry output is missing: {output}")
        asset.update(_build_callout_layers(output))
        asset["quality_status"] = "human_approved"
        checks = asset.setdefault("quality_checks", [])
        if "human_reviewed" not in checks:
            checks.append("human_reviewed")
        if "callout_layers_generated" not in checks:
            checks.append("callout_layers_generated")
        approved += 1
    manifest["reviewed_at"] = utc_now()
    manifest["review_status"] = "human_approved"
    write_json_atomic(manifest_path, manifest)
    return {"approved": approved}
