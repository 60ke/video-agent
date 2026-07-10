from __future__ import annotations

import argparse
import copy
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
MOTION_FREEZE_EFFECTS = {"drop_bounce", "tile_drop", "radial_unfurl", "perspective_push_in"}


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
        or (
            aspect
            and aspect > 1.2
            and (
                "ui" in role
                or "page" in role
                or origin in {"browser_capture", "frontend_capture", "cdp_capture"}
                or "assets/sites/" in source
            )
        )
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
    return any(token in combined for token in ("result", "效果图", "结果", "生成图", "packaging", "vi_result")) and not any(
        token in combined for token in ("ui", "界面", "首页", "菜单", "page", "browser")
    )


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
    workflow = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
    # GPT prepared keyframes set workflow_step=prepared_* and keep the real
    # capture step in source_workflow_step — prefer the latter for effects.
    source_workflow_step = str(workflow.get("source_workflow_step") or "").lower()
    workflow_step = str(workflow.get("workflow_step") or "").lower()
    routing_step = source_workflow_step or workflow_step
    # Prefer concrete capture workflow over coarse semantic labels so homepage
    # is not treated as a feature-entry shot for effect allocation.
    if routing_step in RESULT_STEPS:
        step_kind = "result"
    elif routing_step in {"home_entry"}:
        step_kind = "home"
    elif routing_step in {"feature_menu_select", "feature_entry", "menu_select"}:
        step_kind = "entry"
    elif routing_step in {"feature_page_empty", "feature_form_params", "form_filled"}:
        step_kind = "params"
    else:
        step_kind = str(semantic.get("step_kind") or "").lower()
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


def should_freeze_motion(effect_name: str, mode: str) -> bool:
    if mode == "always":
        return True
    if mode == "never":
        return False
    return effect_name in MOTION_FREEZE_EFFECTS


def hold_motion_preserving_flags(raw_motion: Any) -> dict[str, Any]:
    motion = raw_motion if isinstance(raw_motion, dict) else {}
    result: dict[str, Any] = {"name": "hold", "amount": 0.0, "anchor": "center", "avoid_flicker": True}
    for key in ("forbidden_motion", "notes", "reason"):
        if key in motion:
            result[key] = motion[key]
    return result


def visual_group_key(event: dict[str, Any]) -> tuple[str, tuple[str, ...]]:
    layout = str(event.get("layout") or event.get("display_mode") or "").strip()
    asset_ids = tuple(str(asset_id) for asset_id in event.get("asset_ids", []))
    return layout, asset_ids


def merged_visual_groups(track: Any) -> list[list[tuple[int, dict[str, Any]]]]:
    if not isinstance(track, list):
        return []
    groups: list[list[tuple[int, dict[str, Any]]]] = []
    for index, event in enumerate(track):
        if not isinstance(event, dict):
            continue
        item = (index, event)
        if groups and visual_group_key(groups[-1][-1][1]) == visual_group_key(event):
            groups[-1].append(item)
        else:
            groups.append([item])
    return groups


def merged_planning_event(items: list[tuple[int, dict[str, Any]]]) -> dict[str, Any]:
    first = items[0][1]
    merged = copy.deepcopy(first)
    starts = [float(event.get("start", 0.0)) for _, event in items]
    ends = [float(event.get("end", event.get("start", 0.0))) for _, event in items]
    merged["start"] = min(starts)
    merged["end"] = max(ends)

    for key in ("visual_intent", "material_task", "layout_intent", "camera_note", "effect_hint"):
        values = [str(event.get(key) or "").strip() for _, event in items]
        merged[key] = " ".join(value for value in values if value)

    if not isinstance(merged.get("semantic_binding"), dict) or not merged.get("semantic_binding"):
        for _, event in items:
            semantic = event.get("semantic_binding")
            if isinstance(semantic, dict) and semantic:
                merged["semantic_binding"] = copy.deepcopy(semantic)
                break
    return merged


def effect_identity(effect: Any) -> str:
    return json.dumps(effect or {}, ensure_ascii=False, sort_keys=True)


def canonical_existing_effect(items: list[tuple[int, dict[str, Any]]], duration: float) -> dict[str, Any] | None:
    existing = [event.get("effect") for _, event in items if event.get("effect")]
    if not existing:
        return None
    identities = {effect_identity(effect) for effect in existing}
    if len(identities) > 1:
        labels = [str(event.get("id") or index) for index, event in items]
        raise ValueError(f"same visual group has conflicting explicit effects: {labels}")
    return normalize_effect_config(existing[0], group_duration=duration)


def apply_group_effect(
    items: list[tuple[int, dict[str, Any]]],
    effect: dict[str, Any],
    *,
    freeze_motion: str,
    changed: list[dict[str, Any]],
    source: str,
) -> None:
    effect_name = str(effect.get("name") or "")
    motion_frozen = should_freeze_motion(effect_name, freeze_motion)
    first_motion = items[0][1].get("motion") if isinstance(items[0][1].get("motion"), dict) else None
    shared_motion = hold_motion_preserving_flags(first_motion) if motion_frozen else copy.deepcopy(first_motion)
    if isinstance(shared_motion, dict):
        shared_motion.setdefault("avoid_flicker", True)

    for index, event in items:
        previous_motion = event.get("motion") if isinstance(event.get("motion"), dict) else None
        event["effect"] = copy.deepcopy(effect)
        if motion_frozen:
            event["motion"] = hold_motion_preserving_flags(previous_motion)
        elif isinstance(shared_motion, dict):
            event["motion"] = copy.deepcopy(shared_motion)
        event.setdefault("qa_expectations", {})["effect_stable_tail"] = True
        changed.append(
            {
                "visual_index": index,
                "visual_id": event.get("id"),
                "effect": copy.deepcopy(effect),
                "motion_frozen": motion_frozen,
                "freeze_motion_policy": freeze_motion,
                "group_size": len(items),
                "effect_source": source,
            }
        )


def apply_effects(project: dict[str, Any], *, preset: str, force: bool, freeze_motion: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    assets = asset_index(project)
    changed: list[dict[str, Any]] = []
    for items in merged_visual_groups(project.get("visual_track", [])):
        merged_event = merged_planning_event(items)
        duration = max(0.0, float(merged_event["end"]) - float(merged_event["start"]))

        existing_effect = canonical_existing_effect(items, duration)
        if existing_effect and not force:
            if all(effect_identity(event.get("effect")) == effect_identity(existing_effect) for _, event in items):
                continue
            apply_group_effect(
                items,
                existing_effect,
                freeze_motion=freeze_motion,
                changed=changed,
                source="existing_group_effect",
            )
            continue

        asset_ids = [str(asset_id) for asset_id in merged_event.get("asset_ids", [])]
        asset = assets.get(asset_ids[0], {}) if asset_ids else {}
        effect = default_effect_for_event(merged_event, asset, preset)
        if not effect:
            continue
        apply_group_effect(
            items,
            effect,
            freeze_motion=freeze_motion,
            changed=changed,
            source="planned_group_effect",
        )

    project.setdefault("renderer_plan", {})["effect_policy"] = {
        "preset": preset,
        "applied_count": len(changed),
        "freeze_motion": freeze_motion,
        "planning_unit": "merged_visual_group",
    }
    return project, changed


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.json"
    project = load_json(project_path, {})
    if not isinstance(project, dict):
        raise ValueError(f"project JSON is invalid: {project_path}")
    project, changed = apply_effects(project, preset=args.preset, force=args.force, freeze_motion=args.freeze_motion)
    output_project = Path(args.output_project).expanduser().resolve(strict=False) if args.output_project else case_dir / "video_project.effects.json"
    write_json(output_project, project)
    report_path = case_dir / "output" / "reports" / "effect_plan_report.json"
    write_json(
        report_path,
        {
            "schema_version": 1,
            "project": str(output_project),
            "preset": args.preset,
            "force": bool(args.force),
            "freeze_motion": args.freeze_motion,
            "planning_unit": "merged_visual_group",
            "items": changed,
            "count": len(changed),
        },
    )
    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {"project": str(output_project), "report": str(report_path), "count": len(changed)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Apply registered programmatic image effects to video_project.json without changing the voice/subtitle timeline.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--project")
    parser.add_argument("--output-project")
    parser.add_argument("--preset", choices=("none", "minimal", "balanced"), default="balanced")
    parser.add_argument("--force", action="store_true", help="Replace existing visual_track[].effect values.")
    parser.add_argument(
        "--freeze-motion",
        choices=("auto", "always", "never"),
        default="auto",
        help="Whether to replace existing push/pull motion with hold when adding effects. auto freezes strong entrance, assembly, and perspective camera effects.",
    )
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
