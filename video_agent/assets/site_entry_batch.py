from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image

from video_agent.assets.site_derivatives import RENDERER_VERSION, generate_feature_entry_keyframe
from video_agent.io import load_json, sha256_file, sha256_json, utc_now, write_json_atomic


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


def _output_name(source: SiteEntrySource) -> str:
    return source.path.name.replace("功能入口截图", "功能入口关键帧")


def _build_callout_layers(output: Path) -> dict[str, Any]:
    """Compatibility helper for existing prepared keyframes and renderer tests.

    New batches emit the base and transparent callout layer directly from CDP coordinates.
    This extractor remains for legacy approved keyframes that only contain a composited red
    hand-drawn circle. It deliberately ignores red components in the brand header.
    """
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


def _target_callout(source: SiteEntrySource, callouts: dict[str, Any]) -> tuple[dict[str, float], dict[str, float] | None, dict[str, Any]]:
    item = callouts.get("items", {}).get(source.path.name, {}) if isinstance(callouts, dict) else {}
    raw = item.get("callouts", []) if isinstance(item, dict) else []
    candidates = [
        callout
        for callout in raw
        if isinstance(callout, dict)
        and isinstance(callout.get("box"), dict)
        and (
            str(callout.get("target_label") or "") == source.target
            or str(callout.get("intent") or "") == "click_target"
            or str(callout.get("target_role") or "") == "hover_menu_child"
        )
    ]
    if not candidates:
        raise ValueError(f"CDP callout registry has no target box for {source.path.name}/{source.target}")
    target = next((item for item in candidates if str(item.get("target_label") or "") == source.target), candidates[0])
    return target["box"], target.get("panel_box"), target


def generate_site_entry_keyframes(
    repo_root: Path,
    source_dir: Path,
    output_dir: Path,
    *,
    workers: int = 3,
    force: bool = False,
) -> dict[str, Any]:
    del repo_root  # kept for CLI/API compatibility
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
    callouts = load_json(source_dir / "_callouts.json")

    results: list[dict[str, Any]] = []
    pending: list[tuple[SiteEntrySource, Path, dict[str, float], dict[str, float] | None, str, str]] = []
    for source in sources:
        target_box, panel_box, callout = _target_callout(source, callouts)
        source_sha256 = sha256_file(source.path)
        recipe_sha256 = sha256_json({"renderer": RENDERER_VERSION, "target": callout})
        output = output_dir / _output_name(source)
        old = previous_by_source.get(source.path.resolve().as_posix())
        if (
            not force
            and old
            and old.get("source_sha256") == source_sha256
            and old.get("recipe_sha256") == recipe_sha256
            and output.is_file()
            and old.get("output_sha256") == sha256_file(output)
        ):
            results.append({**old, "status": "cached"})
            continue
        pending.append((source, output, target_box, panel_box, source_sha256, recipe_sha256))

    def generate(item: tuple[SiteEntrySource, Path, dict[str, float], dict[str, float] | None, str, str]) -> dict[str, Any]:
        source, output, target_box, panel_box, source_sha256, recipe_sha256 = item
        layer_metadata = generate_feature_entry_keyframe(source.path, output, target_box, panel_box)
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
            "annotation_style": "deterministic_red_hand_drawn_double_stroke_ellipse",
            "recipe_sha256": recipe_sha256,
            "provider": "deterministic_pillow",
            "model": RENDERER_VERSION,
            "response_id": None,
            "quality_status": "unreviewed",
            "status": "generated",
            **layer_metadata,
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
        "workflow": "site_feature_entry_deterministic_batch",
        "annotation_style": "deterministic_red_hand_drawn_double_stroke_ellipse",
        "renderer": RENDERER_VERSION,
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
        "manifest": manifest_path.as_posix(),
    }


def approve_site_entry_manifest(manifest_path: Path) -> dict[str, int]:
    manifest = load_json(manifest_path)
    assets = manifest.get("assets") if isinstance(manifest, dict) else None
    if not isinstance(assets, list):
        raise ValueError(f"invalid site-entry manifest: {manifest_path}")
    if manifest.get("errors"):
        raise ValueError(f"site-entry manifest still contains generation errors: {manifest_path}")
    approved = 0
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        for path_key, hash_key in (
            ("output_path", "output_sha256"),
            ("callout_base_path", "callout_base_sha256"),
            ("callout_layer_path", "callout_layer_sha256"),
        ):
            path = Path(str(asset.get(path_key) or ""))
            if not path.is_file():
                raise FileNotFoundError(f"approved feature-entry output is missing: {path}")
            if sha256_file(path) != str(asset.get(hash_key) or ""):
                raise ValueError(f"feature-entry output hash mismatch: {path}")
        asset["quality_status"] = "human_approved"
        checks = asset.setdefault("quality_checks", [])
        for check in ("human_reviewed", "deterministic_callout_layers_verified"):
            if check not in checks:
                checks.append(check)
        approved += 1
    manifest["reviewed_at"] = utc_now()
    manifest["review_status"] = "human_approved"
    write_json_atomic(manifest_path, manifest)
    return {"approved": approved}
