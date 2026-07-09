from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.effects.registry import EffectSuggestionInput, normalize_effect_config, suggested_effect

RESULT_STEPS = {"result_crop", "result_export", "result_gallery", "result_page"}
SEQUENCE_TYPES = {"image_sequence", "site_flow_steps", "result_gallery"}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def asset_index(project: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(asset.get("id")): asset for asset in project.get("assets", []) if isinstance(asset, dict) and asset.get("id")}


def asset_aspect(asset: dict[str, Any]) -> float | None:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata"), dict) else {}
    aspect = metadata.get("aspect_ratio")
    if isinstance(aspect, (int, float)) and aspect > 0:
        return float(aspect)
    width = metadata.get("width")
    height = metadata.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)) and height > 0:
        return float(width) / float(height)
    return None


def is_wide_ui_asset(asset: dict[str, Any]) -> bool:
    aspect = asset_aspect(asset)
    role = str(asset.get("role") or "").lower()
    origin = str(asset.get("origin") or "").lower()
    source = str(asset.get("source") or "").lower()
    risks = {str(v).lower() for v in asset.get("display_risk", []) if isinstance(v, str)}
    return bool(
        risks & {"wide_desktop_ui", "dense_desktop_ui"}
        or (aspect and aspect > 1.2 and ("ui" in role or "page" in role or origin in {"browser_capture", "frontend_capture", "cdp_capture"} or "assets/sites/" in source))
    )


def is_generated_result_asset(asset: dict[str, Any]) -> bool:
    image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
    workflow_step = str(image_resource.get("workflow_step") or "").lower()
    role = str(asset.get("role") or "").lower()
    origin = str(asset.get("origin") or "").lower()
    source = str(asset.get("source") or "").lower()
    description = str(asset.get("description") or "").lower()
    combined = " ".join((workflow_step, role, origin, source, description))
    if workflow_step in RESULT_STEPS or "assets/results/" in source:
        return True
    return any(token in combined for token in ("result", "效果图", "结果", "生成图", "packaging", "vi_result")) and not any(token in combined for token in ("ui", "界面", "首页", "菜单", "page", "browser"))


def force_scan_requested(event: dict[str, Any]) -> bool:
    text = " ".join(
        str(v or "")
        for v in (
            event.get("visual_intent"),
            event.get("material_task"),
            event.get("layout_intent"),
            event.get("camera_note"),
            event.get("effect_hint"),
        )
    ).lower()
    return any(token in text for token in ("scan", "analysis", "blueprint", "结构", "解析", "高亮", "轮廓"))


def default_effect_for_event(event: dict[str, Any], asset: dict[str, Any], preset: str) -> dict[str, Any] | None:
    start = float(event.get("start", 0.0))
    end = float(event.get("end", start))
    duration = max(0.0, end - start)
    if duration < 0.85 or preset == "none":
        return None
    clip_type = str(event.get("clip_type") or "image")
    if clip_type in SEQUENCE_TYPES:
        return None
    semantic = event.get("semantic_binding", {}) if isinstance(event.get("semantic_binding"), dict) else {}
    step_kind = str(semantic.get("step_kind") or "").lower()
    if not step_kind:
        workflow = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
        workflow_step = str(workflow.get("workflow_step") or workflow.get("source_workflow_step") or "").lower()
        if workflow_step in RESULT_STEPS:
            step_kind = "result"
        elif workflow_step in {"home_entry"}:
            step_kind = "home"
        elif workflow_step in {"feature_menu_select", "feature_entry", "menu_select"}:
            step_kind = "entry"
        elif workflow_step in {"feature_page_empty", "feature_form_params", "form_filled"}:
            step_kind = "params"
    if preset == "minimal" and step_kind not in {"result", "entry"} and not force_scan_requested(event):
        return None
    data = EffectSuggestionInput(
        step_kind=step_kind,
        layout=str(event.get("layout") or event.get("display_mode") or ""),
        clip_type=clip_type,
        duration=duration,
        is_generated_result=is_generated_result_asset(asset),
        is_wide_ui=is_wide_ui_asset(asset),
        visual_intent=str(event.get("visual_intent") or semantic.get("visual_subject") or ""),
        material_task=str(event.get("material_task") or ""),
    )
    effect = suggested_effect(data)
    if not effect:
        return None
    try:
        return normalize_effect_config(effect, group_duration=duration)
    except ValueError:
        return None


def apply_effects(project: dict[str, Any], *, preset: str, force: bool) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assets = asset_index(project)
    changed: list[dict[str, Any]] = []
    for idx, event in enumerate(project.get("visual_track", [])):
        if not isinstance(event, dict):
            continue
        if event.get("effect") and not force:
            continue
        asset_ids = [str(asset_id) for asset_id in event.get("asset_ids", [])]
        asset = assets.get(asset_ids[0], {}) if asset_ids else {}
        effect = default_effect_for_event(event, asset, preset)
        if not effect:
            continue
        event["effect"] = effect
        forbidden = event.get("motion", {}).get("forbidden_motion", []) if isinstance(event.get("motion"), dict) else []
        event["motion"] = {"name": "hold", "amount": 0.0, "anchor": "center", "avoid_flicker": True, "forbidden_motion": forbidden}
        event.setdefault("qa_expectations", {})["effect_stable_tail"] = True
        changed.append({"visual_index": idx, "visual_id": event.get("id"), "effect": effect})
    project.setdefault("renderer_plan", {})["effect_policy"] = {"preset": preset, "applied_count": len(changed)}
    return project, changed


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.json"
    project = load_json(project_path, {})
    if not isinstance(project, dict):
        raise ValueError(f"project JSON is invalid: {project_path}")
    project, changed = apply_effects(project, preset=args.preset, force=args.force)
    output_project = Path(args.output_project).expanduser().resolve(strict=False) if args.output_project else case_dir / "video_project.effects.json"
    write_json(output_project, project)
    report_path = case_dir / "output" / "reports" / "effect_plan_report.json"
    write_json(report_path, {"schema_version": 1, "project": str(output_project), "preset": args.preset, "force": bool(args.force), "items": changed, "count": len(changed)})
    return {"ok": True, "code": "ok", "reason": "", "data": {"project": str(output_project), "report": str(report_path), "count": len(changed)}}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply registered programmatic image effects to video_project.json without changing the voice/subtitle timeline.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project")
    parser.add_argument("--output-project")
    parser.add_argument("--preset", choices=("none", "minimal", "balanced"), default="balanced")
    parser.add_argument("--force", action="store_true", help="Replace existing visual_track[].effect values.")
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
        print(f"Effect project: {output['data']['project']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
