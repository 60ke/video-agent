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


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
DEFAULT_REGISTRY = Path("references") / "site_profiles" / "kehuanxiongmao_text_to_image_modules.json"
DEFAULT_SITE_ASSETS = Path("assets") / "sites"
DEFAULT_CALLOUT_FILENAMES = ("_callouts.json", "_callouts.local.json")


CAPTURE_TYPES = {
    "原始桌面截图": {
        "asset_kind": "site_home",
        "workflow_step": "home_entry",
        "role": "site_home",
        "title": "网站主页",
        "capture_method": "cdp_site_screenshot",
    },
    "功能入口截图": {
        "asset_kind": "feature_entry",
        "workflow_step": "feature_menu_select",
        "role": "feature_entry_path",
        "title": "功能入口路径",
        "capture_method": "cdp_feature_entry_screenshot",
    },
    "参数面板截图": {
        "asset_kind": "feature_form_params",
        "workflow_step": "feature_page_empty",
        "role": "feature_parameter_panel",
        "title": "功能参数面板",
        "capture_method": "cdp_feature_params_screenshot",
    },
}


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_callout_box(box: Any) -> dict[str, float] | None:
    if not isinstance(box, dict):
        return None
    try:
        x = float(box["x"])
        y = float(box["y"])
        w = float(box["w"])
        h = float(box["h"])
    except (KeyError, TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return {
        "x": max(0.0, min(1.0, x)),
        "y": max(0.0, min(1.0, y)),
        "w": max(0.01, min(1.0, w)),
        "h": max(0.01, min(1.0, h)),
    }


def normalize_callout(item: Any, source: str) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    box = normalize_callout_box(item.get("box"))
    if not box:
        return None
    callout = {
        "type": str(item.get("type") or "highlight_box"),
        "target_label": str(item.get("target_label") or item.get("text") or ""),
        "intent": str(item.get("intent") or ""),
        "target_role": str(item.get("target_role") or ""),
        "coordinate_space": str(item.get("coordinate_space") or "source_image_normalized"),
        "box": box,
        "source": source,
    }
    if item.get("text"):
        callout["text"] = str(item["text"])
    if isinstance(item.get("panel_box"), dict):
        panel_box = normalize_callout_box(item["panel_box"])
        if panel_box:
            callout["panel_box"] = panel_box
    return {key: value for key, value in callout.items() if value not in ("", None)}


def load_callout_registry(paths: list[Path]) -> tuple[dict[str, Any], list[str], str | None]:
    warnings: list[str] = []
    merged: dict[str, Any] = {}
    loaded_path: str | None = None
    for path in paths:
        if not path.is_file():
            continue
        loaded_path = str(path)
        payload = load_json(path, {})
        items = payload.get("items") if isinstance(payload, dict) else None
        if isinstance(items, dict):
            for key, value in items.items():
                if isinstance(value, dict):
                    merged[str(key)] = value.get("callouts", [])
                elif isinstance(value, list):
                    merged[str(key)] = value
        elif isinstance(payload, dict):
            for key, value in payload.items():
                if isinstance(value, list):
                    merged[str(key)] = value
        else:
            warnings.append(f"ignored invalid callout registry: {path}")
    return merged, warnings, loaded_path


def callouts_for_path(path: Path, registry: dict[str, Any]) -> list[dict[str, Any]]:
    keys = [path.name, path.stem, path.as_posix(), str(path.resolve(strict=False))]
    raw_items: Any = []
    for key in keys:
        if key in registry:
            raw_items = registry[key]
            break
    if not isinstance(raw_items, list):
        return []
    source = "assets/sites/_callouts.json"
    normalized = [normalize_callout(item, source) for item in raw_items]
    return [item for item in normalized if item]


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


def normalize_label(value: str) -> str:
    return re.sub(r"[\s_／/\\&-]+", "", str(value or "")).lower()


def ascii_slug(value: str, fallback: str = "asset") -> str:
    text = str(value or "").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if text:
        return text
    digest = hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:10]
    return f"{fallback}_{digest}"


def case_relative(case_dir: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(case_dir.resolve(strict=False)).as_posix()


def upsert_by_key(items: list[dict[str, Any]], item: dict[str, Any], key: str) -> None:
    item_key = item.get(key)
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get(key) == item_key:
            items[idx] = item
            return
    items.append(item)


def load_registry(path: Path) -> dict[str, Any]:
    registry = load_json(path, {})
    modules = registry.get("modules", []) if isinstance(registry, dict) else []
    children = (
        registry.get("graphic_ad_submenu", {}).get("children", [])
        if isinstance(registry.get("graphic_ad_submenu"), dict)
        else []
    )
    return {
        "raw": registry,
        "modules": [item for item in modules if isinstance(item, dict)],
        "children": [item for item in children if isinstance(item, dict)],
    }


def registry_indexes(registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    by_label: dict[str, dict[str, Any]] = {}
    by_id: dict[str, dict[str, Any]] = {}
    child_by_label: dict[str, dict[str, Any]] = {}
    child_by_id: dict[str, dict[str, Any]] = {}
    for item in registry["modules"]:
        if item.get("label"):
            by_label[normalize_label(str(item["label"]))] = item
        if item.get("id"):
            by_id[str(item["id"]).lower()] = item
        for alias in item.get("aliases", []) if isinstance(item.get("aliases"), list) else []:
            by_id[str(alias).lower()] = item
    for item in registry["children"]:
        if item.get("label"):
            child_by_label[normalize_label(str(item["label"]))] = item
        if item.get("id"):
            child_by_id[str(item["id"]).lower()] = item
    return {
        "module_by_label": by_label,
        "module_by_id": by_id,
        "child_by_label": child_by_label,
        "child_by_id": child_by_id,
    }


def resolve_label(label: str, lookup: dict[str, dict[str, Any]], *, fallback_id: str) -> tuple[str, str, str]:
    item = lookup.get(normalize_label(label))
    if item:
        return str(item.get("id") or fallback_id), str(item.get("label") or label), str(item.get("route") or "")
    return ascii_slug(label, fallback_id), label, ""


def selector_keys(selector: str, indexes: dict[str, dict[str, Any]]) -> set[str]:
    raw = str(selector or "").strip()
    if not raw:
        return set()
    keys = {raw.lower(), normalize_label(raw)}
    normalized_path = raw.replace("／", "/").replace("\\", "/")
    parts = [part for part in normalized_path.split("/") if part]
    if len(parts) >= 2 and normalize_label(parts[0]) == normalize_label("图文广告"):
        child = indexes["child_by_label"].get(normalize_label(parts[-1])) or indexes["child_by_id"].get(parts[-1].lower())
        if child:
            keys.add(str(child.get("id", "")).lower())
            keys.add(normalize_label(str(child.get("label", ""))))
            keys.add(f"graphic_ad/{str(child.get('id', '')).lower()}")
    module = indexes["module_by_label"].get(normalize_label(raw)) or indexes["module_by_id"].get(raw.lower())
    if module:
        keys.add(str(module.get("id", "")).lower())
        keys.add(normalize_label(str(module.get("label", ""))))
    child = indexes["child_by_label"].get(normalize_label(raw)) or indexes["child_by_id"].get(raw.lower())
    if child:
        keys.add(str(child.get("id", "")).lower())
        keys.add(normalize_label(str(child.get("label", ""))))
        keys.add(f"graphic_ad/{str(child.get('id', '')).lower()}")
    return {key for key in keys if key}


def split_capture_name(path: Path) -> tuple[list[str], str] | None:
    stem = path.stem
    tokens = [part for part in stem.split("_") if part]
    if len(tokens) < 3:
        return None
    capture_type = tokens[-1]
    if capture_type not in CAPTURE_TYPES:
        return None
    return tokens[:-1], capture_type


def parse_site_asset(path: Path, registry: dict[str, Any]) -> dict[str, Any] | None:
    split = split_capture_name(path)
    if not split:
        return None
    tokens, capture_type = split
    indexes = registry_indexes(registry)
    site_label = tokens[0]
    capture_info = CAPTURE_TYPES[capture_type]
    legacy_naming = False

    if len(tokens) >= 3 and tokens[1] == "网站" and tokens[2] == "主页":
        return {
            "site_label": site_label,
            "module_label": "网站",
            "module_id": "site",
            "feature_label": "主页",
            "feature_id": "home",
            "feature_path": ["网站", "主页"],
            "route": "/",
            "capture_type": capture_type,
            "asset_kind": capture_info["asset_kind"],
            "workflow_step": capture_info["workflow_step"],
            "role": capture_info["role"],
            "title": capture_info["title"],
            "capture_method": capture_info["capture_method"],
            "legacy_naming": False,
        }

    if len(tokens) >= 4 and tokens[1] == "文生图" and tokens[2] == "图文广告":
        child_label_raw = "_".join(tokens[3:])
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
            "capture_type": capture_type,
            "asset_kind": capture_info["asset_kind"],
            "workflow_step": capture_info["workflow_step"],
            "role": capture_info["role"],
            "title": f"图文广告-{child_label}{capture_info['title']}",
            "capture_method": capture_info["capture_method"],
            "legacy_naming": False,
        }

    if len(tokens) >= 3 and tokens[1] == "图文广告":
        legacy_naming = True
        child_label_raw = "_".join(tokens[2:])
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
            "capture_type": capture_type,
            "asset_kind": capture_info["asset_kind"],
            "workflow_step": capture_info["workflow_step"],
            "role": capture_info["role"],
            "title": f"图文广告-{child_label}{capture_info['title']}",
            "capture_method": capture_info["capture_method"],
            "legacy_naming": legacy_naming,
        }

    if len(tokens) >= 3 and tokens[1] == "文生图":
        feature_label_raw = "_".join(tokens[2:])
        feature_id, feature_label, route = resolve_label(feature_label_raw, indexes["module_by_label"], fallback_id="text_to_image_feature")
        return {
            "site_label": site_label,
            "module_label": "文生图",
            "module_id": "text_to_image",
            "feature_label": feature_label,
            "feature_id": feature_id,
            "feature_path": ["文生图", feature_label],
            "route": route,
            "capture_type": capture_type,
            "asset_kind": capture_info["asset_kind"],
            "workflow_step": capture_info["workflow_step"],
            "role": capture_info["role"],
            "title": f"{feature_label}{capture_info['title']}",
            "capture_method": capture_info["capture_method"],
            "legacy_naming": False,
        }

    return None


def asset_selection_keys(parsed: dict[str, Any]) -> set[str]:
    keys = {
        str(parsed.get("feature_id", "")).lower(),
        normalize_label(str(parsed.get("feature_label", ""))),
    }
    if parsed.get("parent_feature_id"):
        keys.add(f"{parsed['parent_feature_id']}/{parsed['feature_id']}".lower())
    return {key for key in keys if key}


def layout_plan(parsed: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    capture_type = parsed["capture_type"]
    feature_path = parsed.get("feature_path", [])
    if capture_type == "参数面板截图":
        return {
            "primary_display_mode": "portrait-showcase",
            "focus_region": "left_form_area",
            "fill_strategy": "fit_width_preserve_image",
            "must_be_visible": [str(parsed.get("feature_label", "")), "开始生成"],
            "viewport_transform": {
                "mode": "prepared_9x16_or_width_fit",
                "requires_ai_verified_asset": True,
                "allow_detail_crop": False,
            },
            "forbidden_treatments": ["arbitrary_zoompan", "local_crop", "pan_subject_out_of_frame"],
        }
    if capture_type == "功能入口截图":
        return {
            "primary_display_mode": "full-width",
            "focus_region": "feature_menu_area",
            "fill_strategy": "fit_width_center_vertical",
            "must_be_visible": [label for label in ("文生图", *feature_path[1:]) if label],
            "viewport_transform": {
                "mode": "prepared_9x16_or_width_fit",
                "requires_ai_verified_asset": True,
                "allow_detail_crop": False,
            },
            "forbidden_treatments": ["arbitrary_zoompan", "local_crop", "pan_subject_out_of_frame"],
        }
    return {
        "primary_display_mode": "full-width",
        "focus_region": "home_feature_area",
        "fill_strategy": "fit_width_center_vertical",
        "must_be_visible": ["文生图", "案例资源库"],
        "viewport_transform": {
            "mode": "prepared_9x16_or_width_fit",
            "requires_ai_verified_asset": True,
            "allow_detail_crop": False,
        },
        "forbidden_treatments": ["arbitrary_zoompan", "local_crop", "pan_subject_out_of_frame"],
    }


def description_for(parsed: dict[str, Any]) -> str:
    path_text = " -> ".join(parsed.get("feature_path", []))
    capture_type = parsed["capture_type"]
    if capture_type == "功能入口截图":
        return f"{path_text} 的网站功能入口截图，用于证明用户从首页/侧边栏进入该功能的真实路径。"
    if capture_type == "参数面板截图":
        return f"{path_text} 的参数面板截图，用于展示该功能的输入项、上传区和开始生成入口。"
    return "柯幻熊猫网站主页截图，用于展示平台首页、左侧导航和文生图入口。"


def asset_id_for(parsed: dict[str, Any]) -> str:
    site = "kehuanxiongmao"
    if parsed["asset_kind"] == "site_home":
        return f"site_{site}_home_raw_desktop"
    module = parsed.get("module_id") or "site"
    capture = {
        "feature_entry": "feature_entry",
        "feature_form_params": "params",
    }.get(parsed["asset_kind"], parsed["asset_kind"])
    parts = ["site", site, module]
    if parsed.get("parent_feature_id"):
        parts.append(str(parsed["parent_feature_id"]))
    parts.append(str(parsed.get("feature_id") or "feature"))
    parts.append(capture)
    return "_".join(ascii_slug(part) for part in parts)


def image_resource_id_for(parsed: dict[str, Any]) -> str:
    if parsed["asset_kind"] == "site_home":
        return "img_site_home_entry"
    parts = ["img", str(parsed.get("module_id") or "site")]
    if parsed.get("parent_feature_id"):
        parts.append(str(parsed["parent_feature_id"]))
    parts.extend([str(parsed.get("feature_id") or "feature"), str(parsed["workflow_step"])])
    return "_".join(ascii_slug(part) for part in parts)


def build_asset(
    case_dir: Path,
    source_path: Path,
    target_path: Path,
    parsed: dict[str, Any],
    callouts: list[dict[str, Any]],
    callout_registry_path: str | None,
) -> dict[str, Any]:
    metadata = probe_image(target_path if target_path.is_file() else source_path)
    metadata["source_library_path"] = str(source_path.resolve(strict=False))
    if callout_registry_path:
        metadata["callout_registry_path"] = callout_registry_path
        metadata["callout_count"] = len(callouts)
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
        "origin": "site_screenshot_library",
        "source_policy": "copied_from_assets_sites",
        "role": parsed["role"],
        "description": description_for(parsed),
        "visible_text": [str(value) for value in parsed.get("feature_path", [])],
        "supported_claims": ["real_website_screenshot", parsed["asset_kind"]],
        "metadata": metadata,
        "display_risk": ["wide_desktop_ui"] if parsed["capture_type"] != "参数面板截图" else [],
        "layout_plan": layout_plan(parsed, metadata),
        "site_asset": {
            "site_label": parsed["site_label"],
            "module_label": parsed["module_label"],
            "module_id": parsed["module_id"],
            "parent_feature_label": parsed.get("parent_feature_label"),
            "parent_feature_id": parsed.get("parent_feature_id"),
            "feature_label": parsed["feature_label"],
            "feature_id": parsed["feature_id"],
            "feature_path": parsed.get("feature_path", []),
            "capture_type": parsed["capture_type"],
            "asset_kind": parsed["asset_kind"],
            "route": parsed.get("route", ""),
            "legacy_naming": bool(parsed.get("legacy_naming")),
            "callout_count": len(callouts),
        },
        "quality": {
            "readable": None,
            "contains_private_info": None,
            "needs_review": True,
            "ai_verified": False,
        },
    }


def build_image_resource(asset: dict[str, Any], parsed: dict[str, Any], callouts: list[dict[str, Any]]) -> dict[str, Any]:
    feature_path = parsed.get("feature_path", [])
    recommended_usage = {
        "site_home": ["site_context", "entry_path"],
        "feature_entry": ["entry_path", "process_proof", "navigation_callout"],
        "feature_form_params": ["parameter_panel", "process_proof", "feature_explanation"],
    }.get(parsed["asset_kind"], ["process_proof"])
    return {
        "id": image_resource_id_for(parsed),
        "asset_id": asset["id"],
        "filename": asset["filename"],
        "source": asset["source"],
        "type": "image",
        "feature_id": parsed["feature_id"],
        "feature_label": parsed["feature_label"],
        "feature_path": feature_path,
        "source_module_id": parsed["module_id"],
        "source_module_label": parsed["module_label"],
        "parent_feature_id": parsed.get("parent_feature_id"),
        "parent_feature_label": parsed.get("parent_feature_label"),
        "workflow_step": parsed["workflow_step"],
        "source_workflow_step": parsed["asset_kind"],
        "capture_type": parsed["capture_type"],
        "variant": "clean",
        "origin": "site_screenshot_library",
        "capture_method": parsed["capture_method"],
        "page_url": parsed.get("route", ""),
        "title": parsed["title"],
        "description": asset["description"],
        "visible_text": asset["visible_text"],
        "prompt_inputs": {},
        "callouts": callouts,
        "relations": {
            "site_label": parsed["site_label"],
            "module_path": feature_path[:-1],
            "same_feature_key": parsed["feature_id"],
        },
        "supported_claims": asset["supported_claims"],
        "recommended_usage": recommended_usage,
        "quality": asset["quality"],
        "layout_plan": asset["layout_plan"],
    }


def collect_site_images(site_assets_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(site_assets_dir.rglob("*"), key=lambda item: item.as_posix().lower())
        if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES
    ]


def selected(parsed: dict[str, Any], selector_set: set[str], include_homepage: bool) -> bool:
    if parsed["asset_kind"] == "site_home":
        return include_homepage
    if not selector_set:
        return True
    return bool(asset_selection_keys(parsed) & selector_set)


def preferred_feature_selectors(case_dir: Path, indexes: dict[str, dict[str, Any]]) -> set[str]:
    input_data = load_json(case_dir / "input.json", {})
    request = input_data.get("request", {}) if isinstance(input_data, dict) else {}
    values = request.get("preferred_features", []) if isinstance(request, dict) else []
    if not isinstance(values, list):
        return set()
    merged: set[str] = set()
    for value in values:
        merged.update(selector_keys(str(value), indexes))
    return merged


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    site_assets_dir = Path(args.site_assets).expanduser().resolve(strict=False)
    registry_path = Path(args.registry).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")
    if not site_assets_dir.is_dir():
        raise FileNotFoundError(f"site assets directory not found: {site_assets_dir}")
    registry = load_registry(registry_path)
    indexes = registry_indexes(registry)
    callout_paths = (
        [Path(args.callouts).expanduser().resolve(strict=False)]
        if args.callouts
        else [site_assets_dir / name for name in DEFAULT_CALLOUT_FILENAMES]
    )
    callout_registry, callout_warnings, loaded_callout_registry = load_callout_registry(callout_paths)

    selector_set: set[str] = set()
    for feature in args.feature:
        selector_set.update(selector_keys(feature, indexes))
    if not selector_set and not args.all:
        selector_set.update(preferred_feature_selectors(case_dir, indexes))

    parsed_items: list[tuple[Path, dict[str, Any]]] = []
    warnings: list[str] = [*callout_warnings]
    for path in collect_site_images(site_assets_dir):
        parsed = parse_site_asset(path, registry)
        if not parsed:
            warnings.append(f"unrecognized site asset filename: {path.name}")
            continue
        if parsed.get("legacy_naming"):
            warnings.append(f"legacy graphic-ad filename detected: {path.name}")
        if selected(parsed, selector_set if not args.all else set(), not args.no_homepage):
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
        callouts = callouts_for_path(source_path, callout_registry)
        target_dir = case_dir / "assets" / "sites"
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / source_path.name
        if not args.dry_run:
            if source_path.resolve(strict=False) != target_path.resolve(strict=False):
                shutil.copy2(source_path, target_path)
        asset = build_asset(case_dir, source_path, target_path, parsed, callouts, loaded_callout_registry)
        resource = build_image_resource(asset, parsed, callouts)
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
            "site_assets_dir": str(site_assets_dir),
            "registry": str(registry_path),
            "callout_registry": loaded_callout_registry or "",
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
    parser = argparse.ArgumentParser(description="Register assets/sites screenshots into a case planner context.")
    parser.add_argument("--case", required=True, help="Case directory created by init_case.py.")
    parser.add_argument("--site-assets", default=str(DEFAULT_SITE_ASSETS), help="Flat or recursive website screenshot directory.")
    parser.add_argument("--registry", default=str(DEFAULT_REGISTRY), help="Frontend-derived module registry JSON.")
    parser.add_argument(
        "--callouts",
        default="",
        help="Optional CDP callout registry JSON. Defaults to assets/sites/_callouts.json when present.",
    )
    parser.add_argument("--feature", action="append", default=[], help="Feature id/label/path to register, e.g. 活动美陈 or 图文广告/车贴.")
    parser.add_argument("--all", action="store_true", help="Register every recognized site screenshot.")
    parser.add_argument("--no-homepage", action="store_true", help="Do not include the site homepage screenshot.")
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
        print(f"Registered site assets: {output['data']['selected_asset_count']}")
        for warning in output["data"]["warnings"]:
            print(f"WARNING: {warning}", file=sys.stderr)
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
