from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
