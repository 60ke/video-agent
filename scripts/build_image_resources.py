from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


WORKFLOW_STEPS = (
    "home_entry",
    "text_to_image_entry",
    "feature_card",
    "navigation_callout",
    "feature_menu_select",
    "menu_select",
    "feature_page_empty",
    "form_filled",
    "generate_callout",
    "generating",
    "result_page",
    "result_crop",
    "result_export",
    "result_gallery",
    "operation_recording",
    "quota_or_error",
    "packaging",
)


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def slug(value: str, fallback: str = "asset") -> str:
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or fallback


def rel_source(case_dir: Path, source: str | None) -> str:
    if not source:
        return ""
    path = Path(source)
    if not path.is_absolute():
        return source.replace("\\", "/")
    try:
        return str(path.resolve(strict=False).relative_to(case_dir)).replace("\\", "/")
    except ValueError:
        return str(path)


def is_image(asset: dict[str, Any]) -> bool:
    kind = str(asset.get("type") or "").lower()
    source = str(asset.get("source") or "")
    suffix = Path(source or str(asset.get("filename") or "")).suffix.lower()
    return kind == "image" or suffix in IMAGE_SUFFIXES


def infer_step(asset: dict[str, Any], insight: dict[str, Any], existing: dict[str, Any]) -> str:
    explicit = str(existing.get("workflow_step") or "").strip()
    if explicit in WORKFLOW_STEPS:
        return explicit
    text = " ".join(
        str(value or "").lower()
        for value in (
            asset.get("filename"),
            asset.get("role"),
            asset.get("description"),
            insight.get("page_or_scene_role"),
            insight.get("recommended_usage"),
            insight.get("vision_summary"),
        )
    )
    checks = (
        ("quota_or_error", ("quota", "error", "积分", "余额", "报错", "失败")),
        ("result_export", ("export", "download", "导出", "下载")),
        ("result_crop", ("result_crop", "crop", "结果裁切", "效果图")),
        ("result_page", ("result_page", "result", "结果页")),
        ("generating", ("generating", "loading", "生成中", "等待")),
        ("generate_callout", ("generate_callout", "开始生成", "button", "按钮")),
        ("form_filled", ("form_filled", "filled", "已填写", "表单")),
        ("feature_page_empty", ("form_empty", "empty", "功能页")),
        ("feature_menu_select", ("vi_select", "feature_menu_select", "功能选择")),
        ("menu_select", ("menu", "select", "logo", "菜单", "选择")),
        ("navigation_callout", ("callout", "annotated", "红框", "箭头")),
        ("text_to_image_entry", ("text_to_image", "文生图")),
        ("operation_recording", ("recording", "screen_record", "录屏")),
        ("home_entry", ("home", "entry", "首页", "入口")),
    )
    for step, tokens in checks:
        if any(token in text for token in tokens):
            return step
    return "packaging" if str(asset.get("origin")) == "generated_asset" else "feature_card"


def infer_feature(asset: dict[str, Any], insight: dict[str, Any], existing: dict[str, Any], fallback: str) -> str:
    explicit = str(existing.get("feature_id") or "").strip()
    if explicit:
        return slug(explicit, fallback)
    text = " ".join(
        str(value or "").lower()
        for value in (
            asset.get("filename"),
            asset.get("role"),
            asset.get("description"),
            insight.get("page_or_scene_role"),
            insight.get("vision_summary"),
        )
    )
    feature_map = {
        "logo": ("logo", "标志", "品牌名称"),
        "culture_wall": ("culture", "文化墙"),
        "signboard": ("signboard", "门头", "招牌"),
        "ecommerce": ("ecommerce", "电商"),
        "poster": ("poster", "海报"),
        "packaging": ("packaging", "包装"),
        "vi": ("vi", "视觉"),
    }
    for feature, tokens in feature_map.items():
        if any(token in text for token in tokens):
            return feature
    return slug(fallback, "feature")


def capture_method(origin: str, source: str) -> str:
    if origin == "browser_capture":
        return "kimi_webbridge_screenshot"
    if origin == "product_export":
        return "kimi_webbridge_product_export"
    if "assets/results" in source.replace("\\", "/"):
        return "kimi_webbridge_screenshot_crop"
    if origin == "generated_asset":
        return "local_packaging_asset"
    return "local_registered_asset"


def infer_variant(existing: dict[str, Any], filename: str, step: str) -> str:
    explicit = str(existing.get("variant") or "").strip()
    if explicit:
        return explicit
    lowered = filename.lower()
    if "callout" in lowered or "annotated" in lowered or step in {"navigation_callout", "generate_callout"}:
        return "callout"
    if step in {"result_crop", "result_export", "result_gallery"}:
        return "result"
    return "clean"


def merge_unique(*values: Any) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        for item in as_list(value):
            text = str(item).strip()
            if text and text not in seen:
                merged.append(text)
                seen.add(text)
    return merged


def existing_maps(existing_payload: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    by_asset_id: dict[str, dict[str, Any]] = {}
    by_source: dict[str, dict[str, Any]] = {}
    by_filename: dict[str, dict[str, Any]] = {}
    for item in as_list(existing_payload.get("resources")):
        if not isinstance(item, dict):
            continue
        if item.get("asset_id"):
            by_asset_id[str(item["asset_id"])] = item
        source = str(item.get("source") or "")
        if source:
            by_source[source.replace("\\", "/")] = item
        filename = str(item.get("filename") or Path(source).name or "")
        if filename:
            by_filename[filename.lower()] = item
    return by_asset_id, by_source, by_filename


def collect_manifest_assets(case_dir: Path) -> list[dict[str, Any]]:
    manifest = load_json(case_dir / "asset_manifest.json", {"assets": []})
    return [asset for asset in as_list(manifest.get("assets")) if isinstance(asset, dict) and is_image(asset)]


def collect_browser_only_assets(case_dir: Path, known_sources: set[str]) -> list[dict[str, Any]]:
    payload = load_json(case_dir / "browser_materials.json", {"materials": []})
    assets: list[dict[str, Any]] = []
    for idx, item in enumerate(as_list(payload.get("materials"))):
        if not isinstance(item, dict):
            continue
        source = rel_source(case_dir, str(item.get("source") or ""))
        if not source or source in known_sources:
            continue
        if Path(source).suffix.lower() not in IMAGE_SUFFIXES and str(item.get("type") or "") != "image":
            continue
        assets.append(
            {
                "id": item.get("asset_id") or item.get("id") or f"browser_{idx + 1:03d}",
                "type": "image",
                "source": source,
                "filename": Path(source).name,
                "origin": item.get("origin", "browser_capture"),
                "role": item.get("role", "browser_evidence"),
                "description": item.get("description", ""),
                "visible_text": item.get("visible_text", []),
                "supported_claims": item.get("supported_claims", []),
                "quality": item.get("quality", {}),
            }
        )
    return assets


def build_resource(
    case_dir: Path,
    asset: dict[str, Any],
    insight: dict[str, Any],
    existing: dict[str, Any],
    idx: int,
    default_feature: str,
) -> dict[str, Any]:
    source = rel_source(case_dir, str(asset.get("source") or ""))
    filename = str(asset.get("filename") or Path(source).name)
    origin = str(existing.get("origin") or asset.get("origin") or "static_material_image")
    if origin == "static_material_folder":
        origin = "static_material_image"
    feature = infer_feature(asset, insight, existing, default_feature)
    step = infer_step(asset, insight, existing)
    resource_id = str(existing.get("id") or f"img_{feature}_{step}_{idx + 1:03d}")
    description = (
        str(existing.get("description") or "").strip()
        or str(insight.get("vision_summary") or "").strip()
        or str(asset.get("description") or "").strip()
    )
    role = str(insight.get("page_or_scene_role") or asset.get("role") or step).strip()
    layout_plan = existing.get("layout_plan") or insight.get("layout_plan") or asset.get("layout_plan") or {}

    return {
        "id": resource_id,
        "asset_id": str(asset.get("id") or ""),
        "filename": filename,
        "source": source,
        "type": "image",
        "feature_id": feature,
        "workflow_step": step,
        "variant": infer_variant(existing, filename, step),
        "origin": origin,
        "capture_method": str(existing.get("capture_method") or capture_method(origin, source)),
        "page_url": str(existing.get("page_url") or asset.get("page_url") or ""),
        "title": str(existing.get("title") or role or filename),
        "description": description,
        "visible_text": merge_unique(existing.get("visible_text"), insight.get("visible_text"), asset.get("visible_text")),
        "prompt_inputs": existing.get("prompt_inputs") if isinstance(existing.get("prompt_inputs"), dict) else {},
        "callouts": as_list(existing.get("callouts")),
        "relations": existing.get("relations") if isinstance(existing.get("relations"), dict) else {},
        "supported_claims": merge_unique(
            existing.get("supported_claims"),
            insight.get("supported_claims"),
            asset.get("supported_claims"),
        ),
        "recommended_usage": merge_unique(
            existing.get("recommended_usage"),
            [insight.get("recommended_usage")] if insight.get("recommended_usage") else [],
        ),
        "quality": existing.get("quality") if isinstance(existing.get("quality"), dict) else asset.get("quality", {}),
        "layout_plan": layout_plan,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")

    existing_payload = load_json(case_dir / "image_resources.json", {"resources": []})
    existing_by_asset_id, existing_by_source, existing_by_filename = existing_maps(existing_payload)
    understanding = load_json(case_dir / "material_understanding.json", {"materials": []})
    insights = {
        str(item.get("asset_id")): item
        for item in as_list(understanding.get("materials"))
        if isinstance(item, dict) and item.get("asset_id")
    }

    assets = collect_manifest_assets(case_dir)
    known_sources = {rel_source(case_dir, str(asset.get("source") or "")) for asset in assets}
    assets.extend(collect_browser_only_assets(case_dir, known_sources))

    resources: list[dict[str, Any]] = []
    for idx, asset in enumerate(assets):
        source = rel_source(case_dir, str(asset.get("source") or ""))
        asset_id = str(asset.get("id") or "")
        filename = str(asset.get("filename") or Path(source).name or "").lower()
        existing = existing_by_asset_id.get(asset_id) or existing_by_source.get(source) or existing_by_filename.get(filename) or {}
        resource = build_resource(case_dir, asset, insights.get(asset_id, {}), existing, idx, args.default_feature)
        resources.append(resource)

    status = "pending" if not resources else "ready"
    warnings: list[str] = []
    for resource in resources:
        if not resource.get("description"):
            warnings.append(f"{resource['id']} has no description")
        if resource.get("workflow_step") in {"result_crop", "result_export"} and not resource.get("supported_claims"):
            warnings.append(f"{resource['id']} is a result image with no supported_claims")
    if warnings:
        status = "needs_review"

    output = {
        "schema_version": 1,
        "status": status,
        "naming_policy": existing_payload.get("naming_policy", "kx_<feature>_<step>_<seq>_<variant>.png"),
        "resources": resources,
        "warnings": warnings,
    }
    output_path = case_dir / "image_resources.json"
    write_json(output_path, output)
    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "image_resources": str(output_path),
            "resource_count": len(resources),
            "status": status,
            "warnings": warnings,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build image_resources.json for a video-agent case.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--default-feature", default="kehuanxiongmao")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001 - CLI must return structured errors.
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print(f"Image resources: {output['data']['image_resources']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
