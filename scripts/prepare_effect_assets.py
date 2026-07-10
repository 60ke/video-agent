from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from prepare_gpt_image_keyframes import (  # reuse the existing OpenAI-compatible GPT image client
    DEFAULT_CONFIG,
    GPTImageConfig,
    as_case_relative,
    dry_run_config,
    gpt_edit_image,
    load_config,
    load_json,
    normalize_to_video_canvas,
    probe_image,
    resolve_case_path,
    write_json,
)
from utils.effects.registry import effect_requires_aux

HIGHLIGHT_PROMPT_VERSION = "highlight_overlay_v1"


def asset_index(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(asset.get("id")): asset for asset in project.get("assets", []) if isinstance(asset, dict) and asset.get("id")}


def stable_id(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


def upsert_by_id(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    item_id = item.get("id")
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == item_id:
            items[idx] = item
            return
    items.append(item)


def procedural_highlight(source_path: Path, output_path: Path) -> dict[str, Any]:
    img = Image.open(source_path).convert("RGB")
    gray = ImageOps.grayscale(img)
    edges = ImageOps.autocontrast(gray.filter(ImageFilter.FIND_EDGES))
    edges = edges.point(lambda p: 255 if p > 36 else 0).filter(ImageFilter.GaussianBlur(0.5))
    pale = Image.blend(Image.new("RGB", img.size, (248, 252, 255)), gray.convert("RGB"), 0.18)
    blue = Image.new("RGB", img.size, (10, 98, 220))
    out = Image.composite(blue, pale, edges)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(output_path, "PNG")
    return probe_image(output_path)


def is_site_asset(asset: dict[str, Any]) -> bool:
    source = str(asset.get("source") or "").replace("\\", "/").lower()
    origin = str(asset.get("origin") or "").lower()
    image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
    capture_type = str(image_resource.get("capture_type") or "")
    return "assets/sites/" in source or "site" in origin or capture_type in {"网站主页截图", "功能入口截图", "参数面板截图"}


def is_result_asset(asset: dict[str, Any]) -> bool:
    source = str(asset.get("source") or "").replace("\\", "/").lower()
    role = str(asset.get("role") or "").lower()
    image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
    step = str(image_resource.get("workflow_step") or "").lower()
    return "assets/results/" in source or step in {"result_crop", "result_export", "result_gallery", "result_page"} or "result" in role


def highlight_prompt(asset: dict[str, Any]) -> str:
    visible_text = ", ".join(str(v) for v in (asset.get("visible_text") or []) if str(v).strip())
    description = str(asset.get("description") or "").strip()
    common = (
        "Use the uploaded image as the only source of truth. Create a structure-highlight overlay image for later video compositing. "
        "Preserve the original composition, subject positions, element layout, text positions, proportions, brand marks, UI state, and visual meaning. "
        "Do not redesign, do not invent new UI, do not add new marketing copy, and do not change the original Chinese or English text. "
        "Convert the key subject edges, important text blocks, icons, buttons, panels, module borders, and graphic contours into clean cyan-blue/blue-white luminous outlines. "
        "Reduce large solid fills and background noise so the image works as a semi-transparent scan/blueprint overlay above the original. "
        "Keep the result clean, readable, elegant, and aligned one-to-one with the source image for alpha blending and moving scan masks. "
    )
    if is_site_asset(asset):
        task = (
            "This source is a real website or UI screenshot. Keep the UI layout exactly aligned. Highlight main module borders, button outlines, title text, input fields, cards, and target functional areas as a polished UI structure scan. "
            "Do not fabricate new interface states. Do not cover important Chinese UI text."
        )
    elif is_result_asset(asset):
        task = (
            "This source is a generated result/design board. Preserve the result exactly and extract its main subject contours, title/text outlines, decorative element boundaries, logo/brand geometry, and important layout structure as a blueprint-like highlight."
        )
    else:
        task = "This source is a process/material image. Preserve the visible content and produce a clean design-analysis outline layer for a short product-demo video."
    context = f" Source description: {description}." if description else ""
    text = f" Visible text to preserve and align: {visible_text}." if visible_text else ""
    return common + task + context + text


def make_effect_asset(case_dir: Path, source_asset: dict[str, Any], output_path: Path, metadata: dict[str, Any]) -> dict[str, Any]:
    source_id = str(source_asset.get("id"))
    asset_id = f"asset_effect_highlight_{stable_id(source_id)}"
    return {
        "id": asset_id,
        "type": "image",
        "source": as_case_relative(case_dir, output_path),
        "relative_source": as_case_relative(case_dir, output_path),
        "filename": output_path.name,
        "mime_type": "image/png",
        "origin": "gpt_image_effect_asset",
        "source_asset_id": source_id,
        "role": "effect_highlight_overlay",
        "description": f"结构高亮解析辅助图，来源 {source_id}",
        "visible_text": source_asset.get("visible_text") or [],
        "supported_claims": source_asset.get("supported_claims") or [],
        "metadata": metadata,
        "display_risk": [],
        "layout_plan": {"effect_aux_asset_kind": "highlight_overlay"},
        "image_resource": {
            "workflow_step": "effect_highlight_overlay",
            "variant": "gpt_image_highlight_overlay",
            "source_asset_id": source_id,
            "prompt_version": HIGHLIGHT_PROMPT_VERSION,
            "ai_verified_for_video_effect": True,
        },
        "quality": {"readable": True, "contains_private_info": False, "needs_review": False, "effect_aux_ready": True},
    }


def scan_requests(project: dict[str, Any], assets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    for idx, event in enumerate(project.get("visual_track", [])):
        if not isinstance(event, dict):
            continue
        effect = event.get("effect") if isinstance(event.get("effect"), dict) else None
        if not effect or not effect_requires_aux(str(effect.get("name") or "")):
            continue
        if effect.get("aux_asset_id"):
            continue
        asset_ids = [str(asset_id) for asset_id in event.get("asset_ids", [])]
        if not asset_ids:
            continue
        source_asset = assets.get(asset_ids[0])
        if source_asset:
            requests.append({"visual_index": idx, "event": event, "asset": source_asset})
    return requests


def register_effect_assets(case_dir: Path, assets: list[dict[str, Any]], items: list[dict[str, Any]]) -> None:
    manifest_path = case_dir / "asset_manifest.json"
    manifest = load_json(manifest_path, {"schema_version": 1, "status": "registered", "assets": []})
    if not isinstance(manifest.get("assets"), list):
        manifest["assets"] = []
    for asset in assets:
        upsert_by_id(manifest["assets"], asset)
    manifest["status"] = "registered"
    manifest["asset_count"] = len(manifest["assets"])
    write_json(manifest_path, manifest)

    effect_manifest_path = case_dir / "effect_asset_manifest.json"
    effect_manifest = load_json(effect_manifest_path, {"schema_version": 1, "items": []})
    if not isinstance(effect_manifest.get("items"), list):
        effect_manifest["items"] = []
    for item in items:
        upsert_by_id(effect_manifest["items"], item)
    write_json(effect_manifest_path, effect_manifest)


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.effects.json"
    if not project_path.is_file():
        fallback = case_dir / "video_project.gpt_image.json"
        project_path = fallback if fallback.is_file() else case_dir / "video_project.json"
    project = load_json(project_path, {})
    if not isinstance(project, dict):
        raise ValueError(f"project JSON is invalid: {project_path}")
    assets = asset_index(project)
    requests = scan_requests(project, assets)
    if args.limit:
        requests = requests[: args.limit]
    config: GPTImageConfig = dry_run_config() if (args.dry_run or not requests) else load_config(Path(args.config).expanduser().resolve(strict=False))

    new_assets: list[dict[str, Any]] = []
    manifest_items: list[dict[str, Any]] = []
    report_items: list[dict[str, Any]] = []
    raw_dir = case_dir / "output" / "effect_assets" / "raw"
    final_root = case_dir / "assets" / "effects"

    for item in requests:
        source_asset = item["asset"]
        source_id = str(source_asset.get("id"))
        source_path = resolve_case_path(case_dir, source_asset.get("source"))
        if not source_path or not source_path.is_file():
            raise FileNotFoundError(f"source asset missing for effect overlay: {source_asset.get('source')}")
        asset_id = f"asset_effect_highlight_{stable_id(source_id)}"
        raw_path = raw_dir / f"{source_id}_highlight_raw.png"
        final_path = final_root / f"{source_id}_highlight_overlay.png"
        prompt = highlight_prompt(source_asset)
        if args.force or not final_path.is_file():
            if args.dry_run:
                metadata = procedural_highlight(source_path, final_path)
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                raw_path.write_bytes(final_path.read_bytes())
            else:
                gpt_edit_image(config, source_path, prompt, raw_path)
                metadata = normalize_to_video_canvas(raw_path, final_path)
        else:
            metadata = probe_image(final_path)
        new_asset = make_effect_asset(case_dir, source_asset, final_path, metadata)
        new_asset["id"] = asset_id
        new_assets.append(new_asset)
        event = item["event"]
        effect = event.setdefault("effect", {})
        effect["aux_asset_id"] = asset_id
        effect["needs_aux_asset"] = False
        effect["aux_asset_kind"] = "highlight_overlay"
        manifest_item = {
            "id": f"eff_{stable_id(source_id)}",
            "source_asset_id": source_id,
            "aux_asset_id": asset_id,
            "effect_type": "highlight_overlay",
            "path": new_asset["source"],
            "generator": "dry_run_procedural" if args.dry_run else "gpt_image",
            "prompt_version": HIGHLIGHT_PROMPT_VERSION,
            "metadata": metadata,
        }
        manifest_items.append(manifest_item)
        report_items.append({"visual_index": item["visual_index"], "visual_id": event.get("id"), "source_asset_id": source_id, "aux_asset_id": asset_id, "raw_output": as_case_relative(case_dir, raw_path), "prepared_output": new_asset["source"], "prompt": prompt, "metadata": metadata})

    existing_assets = [asset for asset in project.get("assets", []) if isinstance(asset, dict)]
    for asset in new_assets:
        upsert_by_id(existing_assets, asset)
    project["assets"] = existing_assets
    output_project = Path(args.output_project).expanduser().resolve(strict=False) if args.output_project else case_dir / "video_project.effects.json"
    write_json(output_project, project)
    if not args.dry_run:
        register_effect_assets(case_dir, new_assets, manifest_items)
    report_path = case_dir / "output" / "reports" / "effect_assets_report.json"
    write_json(report_path, {"schema_version": 1, "provider": config.provider_summary(), "project": str(output_project), "items": report_items, "count": len(report_items), "status": "ok" if report_items else "skipped_no_aux_effects"})
    return {"ok": True, "code": "ok", "reason": "", "data": {"project": str(output_project), "report": str(report_path), "count": len(report_items)}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate GPT Image auxiliary highlight overlays for scan_overlay effects.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project")
    parser.add_argument("--output-project")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--limit", type=int)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Use a procedural local highlight overlay instead of calling GPT Image.")
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
        sys.stdout.buffer.write((json.dumps(output, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    elif output["ok"]:
        print(f"Effect assets project: {output['data']['project']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
