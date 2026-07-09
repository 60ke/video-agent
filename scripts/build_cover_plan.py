from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RESULT_STEPS = {"result_crop", "result_export", "result_gallery", "result_page"}
SITE_CAPTURE_TYPES = {"网站主页截图", "功能入口截图", "参数面板截图"}
DEFAULT_CANVAS = {"width": 1080, "height": 1920}
DEFAULT_SAFE_ZONE = {"x": 0, "y": 240, "width": 1080, "height": 1440, "ratio": "3:4_center"}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def asset_index(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(asset.get("id")): asset for asset in project.get("assets", []) if isinstance(asset, dict) and asset.get("id")}


def resource_by_asset(case_dir: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(case_dir / "image_resources.json", {"resources": []})
    resources = payload.get("resources", []) if isinstance(payload, dict) else []
    return {str(item.get("asset_id")): item for item in resources if isinstance(item, dict) and item.get("asset_id")}


def resolve_case_path(case_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else case_dir / path


def collect_subtitle_text(case_dir: Path, project: dict[str, Any]) -> str:
    chunks: list[str] = []
    for item in project.get("subtitle_track", []):
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("content") or "").strip()
            if text:
                chunks.append(text)
    if chunks:
        return " ".join(chunks)
    subtitle_payload = load_json(case_dir / "subtitle_track.json", [])
    subtitle_items = subtitle_payload.get("subtitle_track", subtitle_payload) if isinstance(subtitle_payload, dict) else subtitle_payload
    if isinstance(subtitle_items, list):
        for item in subtitle_items:
            if isinstance(item, dict):
                text = str(item.get("text") or item.get("content") or "").strip()
                if text:
                    chunks.append(text)
    if chunks:
        return " ".join(chunks)
    script_payload = load_json(case_dir / "video_script.json", {})
    segments = script_payload.get("segments", []) if isinstance(script_payload, dict) else []
    for item in segments:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("narration") or item.get("voiceover") or "").strip()
            if text:
                chunks.append(text)
    return " ".join(chunks)


def compact_text(text: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip("，。,. ") + "…"


def infer_subtitle_hint(text: str, explicit: str | None) -> str:
    if explicit:
        return explicit.strip()
    text = re.sub(r"\s+", "", text)
    candidates = [
        "一键生成品牌视觉",
        "上传描述就能出图",
        "快速展示功能亮点",
        "AI 生成结果直接可看",
    ]
    if any(token in text for token in ("LOGO", "logo", "标志", "品牌")):
        return "一键生成品牌视觉"
    if any(token in text for token in ("海报", "广告", "图文")):
        return "快速生成营销画面"
    if any(token in text for token in ("网站", "功能", "入口", "参数")):
        return "30 秒看懂功能亮点"
    return candidates[0]


def is_result_asset(asset: dict[str, Any], resource: dict[str, Any]) -> bool:
    image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
    step = str(resource.get("workflow_step") or image_resource.get("workflow_step") or "").lower()
    role = str(asset.get("role") or "").lower()
    origin = str(asset.get("origin") or "").lower()
    source = str(asset.get("source") or "").replace("\\", "/").lower()
    description = str(asset.get("description") or resource.get("description") or "").lower()
    return bool(step in RESULT_STEPS or "assets/results/" in source or "result" in role or "结果" in description or "效果图" in description or "generated" in origin)


def is_site_asset(asset: dict[str, Any], resource: dict[str, Any]) -> bool:
    origin = str(asset.get("origin") or resource.get("origin") or "").lower()
    source = str(asset.get("source") or resource.get("source") or "").replace("\\", "/").lower()
    capture_type = str(resource.get("capture_type") or asset.get("site_asset", {}).get("capture_type") or "")
    role = str(asset.get("role") or "").lower()
    return bool(origin == "site_screenshot_library" or "assets/sites/" in source or capture_type in SITE_CAPTURE_TYPES or "site" in role or "ui" in role)


def visual_asset_counts(project: dict[str, Any]) -> Counter[str]:
    counter: Counter[str] = Counter()
    for event in project.get("visual_track", []):
        if not isinstance(event, dict):
            continue
        for asset_id in event.get("asset_ids", []):
            counter[str(asset_id)] += 1
    return counter


def asset_source_exists(case_dir: Path, asset: dict[str, Any]) -> bool:
    source = str(asset.get("source") or asset.get("relative_source") or "")
    path = resolve_case_path(case_dir, source)
    return bool(path and path.is_file())


def score_asset(case_dir: Path, asset: dict[str, Any], resource: dict[str, Any], counts: Counter[str]) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    asset_id = str(asset.get("id") or "")
    if str(asset.get("type") or "").lower() != "image":
        return -999, ["not_image"]
    if not asset_source_exists(case_dir, asset):
        score -= 80
        reasons.append("missing_file")
    count = counts.get(asset_id, 0)
    if count:
        score += min(40, count * 8)
        reasons.append(f"visual_count={count}")
    if is_result_asset(asset, resource):
        score += 100
        reasons.append("result_asset")
    if is_site_asset(asset, resource):
        score += 25
        reasons.append("site_or_ui_asset")
    source = str(asset.get("source") or "").lower()
    if "homepage" in source or "首页" in str(asset.get("description") or ""):
        score -= 8
        reasons.append("homepage_lower_priority")
    return score, reasons


def explicit_reference_ids(raw_values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in raw_values or []:
        for item in str(value).split(","):
            item = item.strip()
            if item and item not in result:
                result.append(item)
    return result


def choose_reference_assets(case_dir: Path, project: dict[str, Any], explicit_ids: list[str], max_count: int) -> tuple[list[str], list[dict[str, Any]]]:
    assets = asset_index(project)
    resources = resource_by_asset(case_dir)
    counts = visual_asset_counts(project)
    chosen: list[str] = []
    scored: list[dict[str, Any]] = []
    for asset_id in explicit_ids:
        asset = assets.get(asset_id)
        if asset and str(asset.get("type") or "").lower() == "image":
            chosen.append(asset_id)
            scored.append({"asset_id": asset_id, "score": 1000, "reasons": ["explicit"]})
    if len(chosen) >= max_count:
        return chosen[:max_count], scored
    candidates: list[tuple[int, str, list[str]]] = []
    for asset_id, asset in assets.items():
        if asset_id in chosen:
            continue
        score, reasons = score_asset(case_dir, asset, resources.get(asset_id, {}), counts)
        if score > -50:
            candidates.append((score, asset_id, reasons))
    candidates.sort(key=lambda item: item[0], reverse=True)
    for score, asset_id, reasons in candidates:
        if len(chosen) >= max_count:
            break
        chosen.append(asset_id)
        scored.append({"asset_id": asset_id, "score": score, "reasons": reasons})
    return chosen, scored


def layout_type_for(project: dict[str, Any], asset_ids: list[str], case_dir: Path) -> str:
    assets = asset_index(project)
    resources = resource_by_asset(case_dir)
    has_result = any(is_result_asset(assets.get(asset_id, {}), resources.get(asset_id, {})) for asset_id in asset_ids)
    has_site = any(is_site_asset(assets.get(asset_id, {}), resources.get(asset_id, {})) for asset_id in asset_ids)
    if has_result and has_site:
        return "result_with_small_ui"
    if has_result:
        return "result_hero"
    if has_site:
        return "site_feature_cover"
    return "visual_subject_cover"


def reference_summary(project: dict[str, Any], case_dir: Path, asset_ids: list[str], scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    assets = asset_index(project)
    resources = resource_by_asset(case_dir)
    score_by_id = {item["asset_id"]: item for item in scored}
    result: list[dict[str, Any]] = []
    for idx, asset_id in enumerate(asset_ids):
        asset = assets.get(asset_id, {})
        resource = resources.get(asset_id, {})
        source = str(asset.get("source") or asset.get("relative_source") or "")
        result.append(
            {
                "asset_id": asset_id,
                "label": f"Image {chr(ord('A') + idx)}",
                "source": source,
                "description": str(asset.get("description") or resource.get("description") or ""),
                "purpose": "primary_result" if is_result_asset(asset, resource) else ("supporting_ui" if is_site_asset(asset, resource) else "supporting_visual"),
                "score": score_by_id.get(asset_id, {}).get("score"),
                "reasons": score_by_id.get(asset_id, {}).get("reasons", []),
            }
        )
    return result


def build_plan(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.effects.json"
    if not project_path.is_file():
        project_path = case_dir / "video_project.json"
    project = load_json(project_path, {})
    if not isinstance(project, dict):
        raise ValueError(f"project JSON is invalid: {project_path}")
    project_cover = project.get("cover", {}) if isinstance(project.get("cover"), dict) else {}
    title = str(args.title or project_cover.get("title") or "").strip()
    if not title:
        raise ValueError("cover title is required; pass --title or project.cover.title")
    subtitle_text = collect_subtitle_text(case_dir, project)
    subtitle = infer_subtitle_hint(subtitle_text, args.subtitle_hint or project_cover.get("subtitle_hint"))
    explicit_ids = explicit_reference_ids(args.reference_asset_ids or project_cover.get("reference_asset_ids") or [])
    reference_ids, scored = choose_reference_assets(case_dir, project, explicit_ids, max(1, int(args.max_refs or 3)))
    plan = {
        "schema_version": 1,
        "title": title,
        "subtitle": subtitle,
        "summary": compact_text(subtitle_text, 120),
        "style_hint": str(args.style_hint or project_cover.get("style_hint") or "short_video_feature_seed").strip(),
        "layout_type": layout_type_for(project, reference_ids, case_dir),
        "reference_asset_ids": reference_ids,
        "references": reference_summary(project, case_dir, reference_ids, scored),
        "safe_zone": {"canvas": DEFAULT_CANVAS, "core_region": DEFAULT_SAFE_ZONE, "crop_behavior": "short_video_platform_center_3x4"},
        "hard_constraints": [
            "Main title must exactly match cover.title. Do not rewrite, omit, translate, or garble it.",
            "Place main title, subject, and supporting subtitle inside the central 3:4 safe zone.",
            "Outside the safe zone, use only background extension, outline, glow, gradient, and decoration; no key information.",
            "Use reference images as visual evidence only; do not invent unrelated UI, logos, products, or results.",
        ],
        "review_required": not bool(reference_ids),
        "source_project": str(project_path),
    }
    return plan


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    plan = build_plan(args)
    output_plan = Path(args.output_plan).expanduser().resolve(strict=False) if args.output_plan else case_dir / "output" / "cover" / "cover_plan.json"
    write_json(output_plan, {"cover_plan": plan})
    report_path = case_dir / "output" / "reports" / "cover_plan_report.json"
    write_json(report_path, {"ok": True, "project": plan["source_project"], "plan": str(output_plan), "reference_count": len(plan["reference_asset_ids"]), "review_required": plan["review_required"]})
    return {"ok": True, "code": "ok", "reason": "", "data": {"plan": str(output_plan), "report": str(report_path), "reference_count": len(plan["reference_asset_ids"]), "review_required": plan["review_required"]}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a short-video cover image plan from project subtitles and referenced assets.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project")
    parser.add_argument("--title", help="Required cover title. Overrides project.cover.title.")
    parser.add_argument("--subtitle-hint")
    parser.add_argument("--style-hint")
    parser.add_argument("--reference-asset-ids", nargs="*", help="Explicit cover reference asset IDs, comma-separated or repeated.")
    parser.add_argument("--max-refs", type=int, default=3)
    parser.add_argument("--output-plan")
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
        print(f"Cover plan: {output['data']['plan']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
