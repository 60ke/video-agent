from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image

from video_agent.ai.gpt_image import edit_image
from video_agent.assets.materializer import _prompt
from video_agent.contracts import DeriveKind
from video_agent.io import load_json, sha256_file, utc_now, write_json_atomic


SUFFIX = "_功能入口截图"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}


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
        f"{nested}重新构图时拉近镜头，让展开菜单占据画面主体，并使用醒目的红色手绘双线圆圈或椭圆自然圈住“{source.target}”。"
        "根据文字长度自适应形状，目标文字位于标记视觉中心并保留呼吸空间。"
        "标记可以覆盖周围空白，但不能圈入、接触或指向相邻功能。"
        "不要使用规则矩形，不要标注首页顶部快捷按钮，不要添加箭头、鼠标、分层动画或解释文案。"
    )


def _output_name(source: SiteEntrySource) -> str:
    return source.path.name.replace("功能入口截图", "功能入口关键帧")


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
        if path.suffix.lower() in IMAGE_SUFFIXES
    ]
    if not sources:
        raise FileNotFoundError(f"no feature-entry screenshots found in {source_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    previous = load_json(manifest_path) if manifest_path.is_file() else {}
    previous_by_source = {
        item["source_path"]: item
        for item in previous.get("assets", [])
        if isinstance(item, dict) and item.get("source_path")
    }
    recipe_prompt, template_sha256 = _prompt(repo_root, DeriveKind.SITE_FEATURE_ENTRY_KEYFRAME, "{batch_instruction}")

    results: list[dict[str, Any]] = []
    pending: list[tuple[SiteEntrySource, Path, str, str, str]] = []
    for source in sources:
        instruction = _instruction(source)
        prompt = recipe_prompt.replace("{batch_instruction}", instruction)
        source_sha256 = sha256_file(source.path)
        prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        output = output_dir / _output_name(source)
        source_path = source.path.resolve().as_posix()
        old = previous_by_source.get(source_path)
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

        if not force and output.is_file() and old is None:
            try:
                with Image.open(output) as image:
                    width, height = image.size
                    image.verify()
                results.append(
                    {
                        "source_path": source_path,
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
                        "annotation_style": "gpt_image_integrated_feature_marker",
                        "prompt_sha256": prompt_sha256,
                        "prompt_template_sha256": template_sha256,
                        "provider": "recovered_interrupted_batch",
                        "model": "unknown",
                        "response_id": None,
                        "status": "recovered",
                    }
                )
                continue
            except Exception:  # noqa: BLE001
                output.unlink(missing_ok=True)
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
            "annotation_style": "gpt_image_integrated_feature_marker",
            "prompt_sha256": prompt_sha256,
            "prompt_template_sha256": template_sha256,
            "provider": result.provider,
            "model": result.model,
            "response_id": result.response_id,
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
        "schema_version": 2,
        "generated_at": utc_now(),
        "workflow": "site_feature_entry_gpt_image_batch",
        "annotation_style": "gpt_image_integrated_feature_marker",
        "source_dir": source_dir.resolve().as_posix(),
        "output_dir": output_dir.resolve().as_posix(),
        "assets": results,
        "errors": errors,
    }
    write_json_atomic(manifest_path, manifest)
    if errors:
        raise RuntimeError(f"site-entry batch completed with {len(errors)} errors; see {manifest_path}")
    return {
        "total": len(sources),
        "generated": sum(item.get("status") == "generated" for item in results),
        "cached": sum(item.get("status") == "cached" for item in results),
        "recovered": sum(item.get("status") == "recovered" for item in results),
        "manifest": manifest_path.as_posix(),
    }
