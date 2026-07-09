from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from register_site_assets import (
    ascii_slug,
    case_relative,
    load_json,
    load_registry,
    normalize_label,
    registry_indexes,
    resolve_label,
    selector_keys,
    upsert_by_key,
    write_json,
)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
DEFAULT_RESULT_ASSETS = Path("assets") / "results"
DEFAULT_REGISTRY = Path("references") / "site_profiles" / "kehuanxiongmao_text_to_image_modules.json"
RESULT_CAPTURE_TYPE = "结果图"
RESULT_STEPS = {"result_crop", "result_export", "result_gallery"}
ORIGINS = {"result_asset_library", "live_generated_result"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_image(path: Path) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            width, height = image.size
        return {
            "probe_ok": True,
            "width": width,
            "height": height,
            "aspect_ratio": round(width / height, 6) if height else None,
        }
    except Exception as exc:  # noqa: BLE001
        return {"probe_ok": False, "probe_error": str(exc)}


def split_result_name(path: Path) -> tuple[list[str], str, str] | None:
    tokens = [part for part in path.stem.split("_") if part]
    if len(tokens) < 6:
        return None
    try:
        result_idx = tokens.index(RESULT_CAPTURE_TYPE)
    except ValueError:
        return None
    if result_idx < 3:
        return None
    sequence = tokens[result_idx + 1] if result_idx + 1 < len(tokens) else "01"
    if not re.fullmatch(r"[0-9A-Za-z]+", sequence):
        sequence = ascii_slug(sequence, "seq")
    before_result = tokens[:result_idx]
    industry_label = before_result[-1]
    path_tokens = before_result[:-1]
    if len(path_tokens) < 3:
        return None
    return path_tokens, industry_label, sequence


def parse_result_asset(path: Path, registry: dict[str, Any]) -> dict[str, Any] | None:
    split = split_result_name(path)
    if not split:
        return None
    path_tokens, industry_label, sequence = split
    indexes = registry_indexes(registry)
    site_label = path_tokens[0]

    if len(path_tokens) >= 4 and path_tokens[1] == "文生图" and path_tokens[2] == "图文广告":
        child_label_raw = "_".join(path_tokens[3:])
        child_id, child_label, route = resolve_label(child_label_raw, indexes["child_by_label"], fallback_id="graphic_child")
        return {
            "site_label": site_label,
            "module_label": "文生图",
            "module_id": "text_to_image",
            "parent_feature_label": "图文广告",
            "parent_feature_id": "graphic_ad",
            "feature_label": child_label,
            "feature_id": child_id,
            "feature_path": ["文生图", "图文广告", child_label],
            "route": route,
            "industry_label": industry_label,
            "industry_id": ascii_slug(industry_label, "industry"),
            "sequence": sequence,
        }

    if len(path_tokens) >= 3 and path_tokens[1] == "文生图":
        feature_label_raw = "_".join(path_tokens[2:])
        feature_id, feature_label, route = resolve_label(feature_label_raw, indexes["module_by_label"], fallback_id="text_to_image_feature")
        return {
            "site_label": site_label,
            "module_label": "文生图",
            "module_id": "text_to_image",
            "feature_label": feature_label,
            "feature_id": feature_id,
            "feature_path": ["文生图", feature_label],
            "route": route,
            "industry_label": industry_label,
            "industry_id": ascii_slug(industry_label, "industry"),
            "sequence": sequence,
        }

    return None


def asset_selection_keys(parsed: dict[str, Any]) -> set[str]:
    keys = {
        str(parsed.get("feature_id", "")).lower(),
        normalize_label(str(parsed.get("feature_label", ""))),
    }
    if parsed.get("parent_feature_id"):
        keys.add(f"{parsed['parent_feature_id']}/{parsed['feature_id']}".lower())
        keys.add(normalize_label(f"{parsed['parent_feature_label']}{parsed['feature_label']}"))
    return {key for key in keys if key}


def selected(parsed: dict[str, Any], feature_selectors: set[str], industry_selectors: set[str]) -> bool:
    if not feature_selectors and not industry_selectors:
        return False
    if feature_selectors and not (asset_selection_keys(parsed) & feature_selectors):
        return False
    if industry_selectors:
        industry_keys = {
            str(parsed.get("industry_id", "")).lower(),
            normalize_label(str(parsed.get("industry_label", ""))),
        }
        if not (industry_keys & industry_selectors):
            return False
    return True


def description_for(parsed: dict[str, Any], origin: str) -> str:
    path_text = " -> ".join(parsed.get("feature_path", []))
    industry = parsed.get("industry_label", "")
    if origin == "live_generated_result":
        return f"{path_text} 的本次真实生成结果图，行业/场景为 {industry}。"
    return f"{path_text} 的可复用结果图素材，行业/场景为 {industry}。"


def layout_plan(metadata: dict[str, Any]) -> dict[str, Any]:
    aspect = metadata.get("aspect_ratio")
    mode = "result-showcase"
    if isinstance(aspect, (int, float)) and 0.42 <= aspect <= 0.78:
        mode = "portrait-showcase"
    return {
        "primary_display_mode": mode,
        "focus_region": "primary_result_image",
        "fill_strategy": "fit_full_result_preserve_image",
        "viewport_transform": {
            "mode": "fit_full_result",
            "fill_width_when_possible": True,
            "preserve_entire_result": True,
            "allow_detail_crop": False,
        },
        "forbidden_treatments": ["arbitrary_zoompan", "local_crop", "pan_subject_out_of_frame"],
    }


def asset_id_for(parsed: dict[str, Any]) -> str:
    parts = [
        "result",
        "kehuanxiongmao",
        parsed.get("module_id") or "module",
    ]
    if parsed.get("parent_feature_id"):
        parts.append(parsed["parent_feature_id"])
    parts.extend(
        [
            parsed.get("feature_id") or "feature",
            parsed.get("industry_id") or "industry",
            parsed.get("sequence") or "01",
        ]
    )
    return "_".join(ascii_slug(str(part)) for part in parts)


def image_resource_id_for(parsed: dict[str, Any]) -> str:
    parts = ["img", parsed.get("module_id") or "module"]
    if parsed.get("parent_feature_id"):
        parts.append(parsed["parent_feature_id"])
    parts.extend(
        [
            parsed.get("feature_id") or "feature",
            parsed.get("industry_id") or "industry",
            "result",
            parsed.get("sequence") or "01",
        ]
    )
    return "_".join(ascii_slug(str(part)) for part in parts)


def build_asset(
    case_dir: Path,
    source_path: Path,
    target_path: Path,
    parsed: dict[str, Any],
    *,
    origin: str,
    ai_verified: bool,
    needs_review: bool,
    receipt_id: str,
) -> dict[str, Any]:
    metadata = probe_image(target_path if target_path.is_file() else source_path)
    metadata["source_library_path"] = str(source_path.resolve(strict=False))
    if receipt_id:
        metadata["receipt_id"] = receipt_id
    mime, _ = mimetypes.guess_type(str(target_path))
    source = case_relative(case_dir, target_path)
    return {
        "id": asset_id_for(parsed),
        "type": "image",
        "source": source,
        "relative_source": source,
        "filename": target_path.name,
        "mime_type": mime or "image/png",
        "size_bytes": target_path.stat().st_size if target_path.is_file() else source_path.stat().st_size,
        "sha256": sha256_file(target_path if target_path.is_file() else source_path),
        "origin": origin,
        "source_policy": "copied_from_assets_results" if origin == "result_asset_library" else "copied_from_live_generation",
        "role": "generated_result",
        "description": description_for(parsed, origin),
        "visible_text": [str(value) for value in parsed.get("feature_path", [])] + [str(parsed.get("industry_label", ""))],
        "supported_claims": [
            "real_result_image" if origin == "live_generated_result" else "curated_result_image",
            f"{parsed.get('feature_label')}结果展示",
            f"{parsed.get('industry_label')}场景",
        ],
        "metadata": metadata,
        "layout_plan": layout_plan(metadata),
        "result_asset": {
            "site_label": parsed["site_label"],
            "module_label": parsed["module_label"],
            "module_id": parsed["module_id"],
            "parent_feature_label": parsed.get("parent_feature_label"),
            "parent_feature_id": parsed.get("parent_feature_id"),
            "feature_label": parsed["feature_label"],
            "feature_id": parsed["feature_id"],
            "feature_path": parsed.get("feature_path", []),
            "industry_label": parsed["industry_label"],
            "industry_id": parsed["industry_id"],
            "capture_type": RESULT_CAPTURE_TYPE,
            "sequence": parsed["sequence"],
            "route": parsed.get("route", ""),
            "receipt_id": receipt_id or None,
        },
        "quality": {
            "readable": None,
            "contains_private_info": None,
            "needs_review": needs_review,
            "ai_verified": ai_verified,
        },
    }


def build_image_resource(asset: dict[str, Any], parsed: dict[str, Any], *, origin: str, receipt_id: str) -> dict[str, Any]:
    workflow_step = "result_crop" if origin == "live_generated_result" else "result_gallery"
    return {
        "id": image_resource_id_for(parsed),
        "asset_id": asset["id"],
        "filename": asset["filename"],
        "source": asset["source"],
        "type": "image",
        "feature_id": parsed["feature_id"],
        "feature_label": parsed["feature_label"],
        "feature_path": parsed.get("feature_path", []),
        "source_module_id": parsed["module_id"],
        "source_module_label": parsed["module_label"],
        "parent_feature_id": parsed.get("parent_feature_id"),
        "parent_feature_label": parsed.get("parent_feature_label"),
        "industry_id": parsed["industry_id"],
        "industry_label": parsed["industry_label"],
        "scene_id": parsed["industry_id"],
        "scene_label": parsed["industry_label"],
        "workflow_step": workflow_step,
        "source_workflow_step": "result_image",
        "capture_type": RESULT_CAPTURE_TYPE,
        "variant": f"result_{parsed['sequence']}",
        "origin": origin,
        "capture_method": "saved_result_asset",
        "page_url": parsed.get("route", ""),
        "title": f"{parsed['feature_label']} - {parsed['industry_label']}结果图",
        "description": asset["description"],
        "visible_text": asset["visible_text"],
        "prompt_inputs": {
            "industry": parsed["industry_label"],
            "scene": parsed["industry_label"],
        },
        "callouts": [],
        "relations": {
            "site_label": parsed["site_label"],
            "module_path": parsed.get("feature_path", [])[:-1],
            "same_feature_key": parsed["feature_id"],
            "same_industry_key": parsed["industry_id"],
            "receipt_id": receipt_id or "",
        },
        "supported_claims": asset["supported_claims"],
        "recommended_usage": ["result_showcase", "result_gallery", "industry_scene_result"],
        "quality": asset["quality"],
        "layout_plan": asset["layout_plan"],
    }


def collect_result_images(result_assets_dir: Path) -> list[Path]:
    if not result_assets_dir.is_dir():
        return []
    return [
        path
        for path in sorted(result_assets_dir.rglob("*"), key=lambda item: item.as_posix().lower())
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]


def build_selectors(values: list[str], indexes: dict[str, dict[str, Any]]) -> set[str]:
    merged: set[str] = set()
    for value in values:
        merged.update(selector_keys(str(value), indexes))
    return merged


def build_industry_selectors(values: list[str]) -> set[str]:
    merged: set[str] = set()
    for value in values:
        if not str(value).strip():
            continue
        merged.add(ascii_slug(str(value), "industry").lower())
        merged.add(normalize_label(str(value)))
    return merged


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    result_assets_dir = Path(args.result_assets).expanduser().resolve(strict=False)
    registry_path = Path(args.registry).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")
    if args.origin not in ORIGINS:
        raise ValueError(f"--origin must be one of {sorted(ORIGINS)}")
    registry = load_registry(registry_path)
    indexes = registry_indexes(registry)
    feature_selectors = build_selectors(args.feature, indexes)
    industry_selectors = build_industry_selectors(args.industry)

    parsed_items: list[tuple[Path, dict[str, Any]]] = []
    warnings: list[str] = []
    for path in collect_result_images(result_assets_dir):
        parsed = parse_result_asset(path, registry)
        if not parsed:
            warnings.append(f"unrecognized result asset filename: {path.name}")
            continue
        if args.all or selected(parsed, feature_selectors, industry_selectors):
            parsed_items.append((path, parsed))

    manifest_path = case_dir / "asset_manifest.json"
    image_resources_path = case_dir / "image_resources.json"
    manifest = load_json(manifest_path, {"schema_version": 1, "status": "registered", "assets": []})
    image_resources = load_json(image_resources_path, {"schema_version": 1, "status": "ready", "resources": []})
    if not isinstance(manifest.get("assets"), list):
        manifest["assets"] = []
    if not isinstance(image_resources.get("resources"), list):
        image_resources["resources"] = []

    assets_written: list[str] = []
    resources_written: list[str] = []
    for source_path, parsed in parsed_items:
        target_dir = case_dir / "assets" / "results"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / source_path.name
        if not args.dry_run and source_path.resolve(strict=False) != target_path.resolve(strict=False):
            shutil.copy2(source_path, target_path)
        asset = build_asset(
            case_dir,
            source_path,
            target_path,
            parsed,
            origin=args.origin,
            ai_verified=not args.needs_review,
            needs_review=args.needs_review,
            receipt_id=args.receipt_id,
        )
        resource = build_image_resource(asset, parsed, origin=args.origin, receipt_id=args.receipt_id)
        assets_written.append(asset["id"])
        resources_written.append(resource["id"])
        if not args.dry_run:
            upsert_by_key(manifest["assets"], asset, "id")
            upsert_by_key(image_resources["resources"], resource, "asset_id")

    if not args.dry_run:
        manifest["status"] = "registered"
        manifest["asset_count"] = len(manifest["assets"])
        image_resources["status"] = "ready" if image_resources["resources"] else "pending"
        write_json(manifest_path, manifest)
        write_json(image_resources_path, image_resources)

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "result_assets_dir": str(result_assets_dir),
            "registry": str(registry_path),
            "origin": args.origin,
            "dry_run": bool(args.dry_run),
            "selected_asset_count": len(parsed_items),
            "asset_manifest": str(manifest_path),
            "image_resources": str(image_resources_path),
            "asset_ids": assets_written,
            "resource_ids": resources_written,
            "warnings": warnings,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register reusable or live generated result images into a video-agent case.")
    parser.add_argument("--case", required=True, help="Case directory created by init_case.py.")
    parser.add_argument("--result-assets", default=str(DEFAULT_RESULT_ASSETS), help="Result image library directory.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Frontend-derived module registry JSON.")
    parser.add_argument("--feature", action="append", default=[], help="Feature id/label/path, e.g. 文化墙 or 图文广告/车贴.")
    parser.add_argument("--industry", action="append", default=[], help="Industry/scene label, e.g. 企业展厅.")
    parser.add_argument("--all", action="store_true", help="Register every recognized result image.")
    parser.add_argument("--origin", default="result_asset_library", choices=sorted(ORIGINS))
    parser.add_argument("--receipt-id", default="", help="Required by policy when origin=live_generated_result and used for fresh-result claims.")
    parser.add_argument("--needs-review", action="store_true", help="Mark registered result images as needing human/AI review.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing case files.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print(f"Registered result assets: {output['data']['selected_asset_count']}")
        for warning in output["data"]["warnings"]:
            print(f"WARNING: {warning}", file=sys.stderr)
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
