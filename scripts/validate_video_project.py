from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from utils.case_guards import kehuanxiongmao_auth_errors
from utils.skill_path import require_skill_root


MOTION_NAMES = {"hold", "push_in", "pull_out"}
MOTION_MAX_AMOUNT = 0.06
MOTION_DEFAULT_ANCHORS = {"center"}
TRANSITION_NAMES = {"cut", "crossfade"}
TRANSITION_MAX_DURATION = 0.6
MIN_VISUAL_HOLD_SECONDS = 0.6

REQUIRED_STRICT_TOP_LEVEL = (
    "schema_version",
    "meta",
    "inputs",
    "assets",
    "script_segments",
    "voice_track",
    "subtitle_track",
    "visual_track",
    "overlay_track",
    "audio_tracks",
    "ending_track",
    "renderer_plan",
    "qa_rules",
)


class ValidationContext:
    def __init__(self, case_dir: Path, skill_root: Path, strict: bool) -> None:
        self.case_dir = case_dir
        self.skill_root = skill_root
        self.strict = strict
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def resolve_path(self, value: str | None) -> Path | None:
        if not value:
            return None
        path = Path(value)
        if path.is_absolute():
            return path
        case_path = self.case_dir / path
        if case_path.exists():
            return case_path
        return self.skill_root / path


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def load_json(path: Path, ctx: ValidationContext, required: bool = True) -> dict[str, Any]:
    if not path.is_file():
        if required:
            ctx.error(f"missing JSON file: {path}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        ctx.error(f"invalid JSON in {path}: {exc}")
        return {}
    if not isinstance(data, dict):
        ctx.error(f"JSON root must be an object: {path}")
        return {}
    return data


def validate_input_json(input_data: dict[str, Any], ctx: ValidationContext) -> None:
    if not input_data:
        return

    for key in ("schema_version", "case", "request", "dependency_mode", "voice_config", "ending_track"):
        if key not in input_data:
            ctx.error(f"input.json missing key: {key}")

    case = input_data.get("case", {})
    if isinstance(case, dict):
        case_dir = case.get("case_dir")
        if case_dir and Path(case_dir).resolve(strict=False) != ctx.case_dir:
            ctx.warn(f"input.json case.case_dir differs from --case: {case_dir}")

        for optional_key in ("materials_dir", "frontend_dir"):
            value = case.get(optional_key)
            if value and not Path(value).exists():
                ctx.warn(f"input.json {optional_key} does not exist: {value}")
    else:
        ctx.error("input.json case must be an object")

    dependency_mode = input_data.get("dependency_mode", {})
    if isinstance(dependency_mode, dict):
        browser_mode = dependency_mode.get("browser", "kimi_webbridge")
        if browser_mode == "static_materials" and not (isinstance(case, dict) and case.get("static_materials_explicit") is True):
            ctx.error("dependency_mode.browser=static_materials requires input.case.static_materials_explicit=true")
        elif browser_mode not in ("kimi_webbridge", "static_materials", None):
            ctx.error(f"unsupported dependency_mode.browser: {browser_mode}")
        renderer = dependency_mode.get("renderer")
        if renderer and renderer != "simple_ffmpeg":
            ctx.error(f"unsupported dependency_mode.renderer: {renderer}")
        tts = dependency_mode.get("tts")
        if tts and tts != "minimax_t2a":
            ctx.error(f"unsupported dependency_mode.tts: {tts}")
    else:
        ctx.error("input.json dependency_mode must be an object")

    voice = input_data.get("voice_config", {})
    if isinstance(voice, dict):
        engine = voice.get("engine")
        if engine and engine != "minimax_t2a":
            ctx.error(f"unsupported voice_config.engine: {engine}")
        if "prompt_audio_policy" in voice or "case_prompt_audio" in voice:
            ctx.error("voice prompt fields are legacy and must be removed for Minimax V2")
    else:
        ctx.error("input.json voice_config must be an object")

    ending = input_data.get("ending_track", {})
    if isinstance(ending, dict):
        policy = ending.get("policy", "default")
        if policy in ("default", "custom"):
            source = ending.get("source")
            path = ctx.resolve_path(source)
            if not path or not path.is_file():
                ctx.error(f"ending video missing for policy {policy}: {source}")
            if ending.get("participates_in_script") is not False and ctx.strict:
                ctx.error("ending_track must not participate in script planning")
            if ending.get("participates_in_subtitles") is not False and ctx.strict:
                ctx.error("ending_track must not participate in subtitles")
        elif policy != "none":
            ctx.error(f"unsupported ending policy: {policy}")
    else:
        ctx.error("input.json ending_track must be an object")


def validate_placeholder_project(project: dict[str, Any], ctx: ValidationContext) -> bool:
    if project.get("status") == "pending" and not ctx.strict:
        if "schema_version" not in project:
            ctx.error("video_project.json pending project missing schema_version")
        return True
    return False


def validate_strict_project(project: dict[str, Any], ctx: ValidationContext) -> None:
    for key in REQUIRED_STRICT_TOP_LEVEL:
        if key not in project:
            ctx.error(f"video_project.json missing key: {key}")

    assets = project.get("assets", [])
    if not isinstance(assets, list):
        ctx.error("video_project.assets must be a list")
        assets = []

    asset_ids: set[str] = set()
    project_assets: dict[str, dict[str, Any]] = {}
    for idx, asset in enumerate(assets):
        if not isinstance(asset, dict):
            ctx.error(f"assets[{idx}] must be an object")
            continue
        asset_id = asset.get("id")
        if not asset_id:
            ctx.error(f"assets[{idx}] missing id")
        elif asset_id in asset_ids:
            ctx.error(f"duplicate asset id: {asset_id}")
        else:
            asset_ids.add(asset_id)
            project_assets[str(asset_id)] = asset
        source = asset.get("source")
        if source:
            path = ctx.resolve_path(source)
            if not path or not path.is_file():
                ctx.error(f"asset source missing: {source}")
            elif ctx.strict and not is_relative_to(path, ctx.case_dir):
                ctx.error(f"asset source must be inside case directory after registration: {source}")
        else:
            ctx.error(f"assets[{idx}] missing source")

    script_segments = project.get("script_segments", [])
    if not isinstance(script_segments, list):
        ctx.error("video_project.script_segments must be a list")
        script_segments = []
    script_ids = {seg.get("id") for seg in script_segments if isinstance(seg, dict) and seg.get("id")}

    validate_voice_track(project.get("voice_track", {}), ctx)
    validate_subtitles(project.get("subtitle_track", {}), script_ids, ctx)
    ctx.project_assets = project_assets
    validate_visual_track(project.get("visual_track", []), asset_ids, script_ids, ctx)
    validate_overlay_track(project.get("overlay_track", []), asset_ids, ctx)
    validate_audio_tracks(project.get("audio_tracks", []), ctx)
    validate_renderer_plan(project.get("renderer_plan", {}), ctx)
    validate_operation_path(project, project_assets, ctx)


def _validate_timed_event(event: dict[str, Any], label: str, ctx: ValidationContext) -> None:
    start = event.get("start")
    end = event.get("end")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
        ctx.error(f"{label} must have numeric start/end")
        return
    if start < 0:
        ctx.error(f"{label} start must be >= 0")
    if end <= start:
        ctx.error(f"{label} end must be greater than start")


def validate_voice_track(track: Any, ctx: ValidationContext) -> None:
    if not isinstance(track, dict):
        ctx.error("voice_track must be an object")
        return
    mode = track.get("mode")
    if not mode:
        ctx.error("voice_track.mode missing")
    audio_path = track.get("audio_path")
    if mode != "none":
        path = ctx.resolve_path(audio_path)
        if not path or not path.is_file():
            ctx.error(f"voice_track audio_path missing: {audio_path}")
    duration = track.get("duration")
    if ctx.strict and not isinstance(duration, (int, float)):
        ctx.error("voice_track.duration must be numeric in strict mode")


def validate_subtitles(track: Any, script_ids: set[str], ctx: ValidationContext) -> None:
    if not isinstance(track, dict):
        ctx.error("subtitle_track must be an object")
        return
    segments = track.get("segments", [])
    if not isinstance(segments, list):
        ctx.error("subtitle_track.segments must be a list")
        return
    if ctx.strict and script_ids and not segments:
        ctx.error("subtitle_track.segments must not be empty in strict mode")
    for idx, segment in enumerate(segments):
        if not isinstance(segment, dict):
            ctx.error(f"subtitle_track.segments[{idx}] must be an object")
            continue
        _validate_timed_event(segment, f"subtitle_track.segments[{idx}]", ctx)
        script_id = segment.get("script_segment_id")
        if script_id and script_ids and script_id not in script_ids:
            ctx.error(f"subtitle references missing script segment: {script_id}")
        if not segment.get("text"):
            ctx.error(f"subtitle_track.segments[{idx}] missing text")


def is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate_layout_contract(event: dict[str, Any], idx: int, ctx: ValidationContext) -> None:
    layout = str(event.get("layout") or "").strip()
    display_mode = str(event.get("display_mode") or "").strip()
    if layout and display_mode and layout != display_mode:
        ctx.error(
            f"visual_track[{idx}] has conflicting layout/display_mode: {layout!r} != {display_mode!r}; "
            "layout is the renderer authority, so keep display_mode equal or omit it"
        )


def visual_event_key(event: dict[str, Any]) -> tuple:
    layout = str(event.get("layout") or event.get("display_mode") or "").strip()
    asset_ids = tuple(str(asset_id) for asset_id in event.get("asset_ids", []))
    return (layout, asset_ids)


def validate_motion(event: dict[str, Any], idx: int, ctx: ValidationContext) -> None:
    motion = event.get("motion")
    if motion is None:
        return
    if not isinstance(motion, dict):
        ctx.error(f"visual_track[{idx}].motion must be an object")
        return
    name = motion.get("name", "hold")
    if name not in MOTION_NAMES:
        ctx.error(
            f"visual_track[{idx}].motion.name must be one of {sorted(MOTION_NAMES)}, got: {name!r}"
        )
    amount = motion.get("amount", 0.0)
    if not is_number(amount) or amount < 0 or amount > MOTION_MAX_AMOUNT:
        ctx.error(
            f"visual_track[{idx}].motion.amount must be a number in [0, {MOTION_MAX_AMOUNT}], got: {amount!r}"
        )
    anchor = motion.get("anchor", "center")
    if anchor not in MOTION_DEFAULT_ANCHORS:
        ctx.error(
            f"visual_track[{idx}].motion.anchor must be one of {sorted(MOTION_DEFAULT_ANCHORS)} in this renderer version, got: {anchor!r}"
        )
    if name == "hold" and amount not in (0, 0.0):
        ctx.error(f"visual_track[{idx}].motion.name=hold requires amount=0, got: {amount!r}")


def validate_transition(event: dict[str, Any], idx: int, ctx: ValidationContext) -> None:
    transition = event.get("transition_in")
    if transition is None:
        return
    if not isinstance(transition, dict):
        ctx.error(f"visual_track[{idx}].transition_in must be an object")
        return
    name = transition.get("name", "cut")
    if name not in TRANSITION_NAMES:
        ctx.error(
            f"visual_track[{idx}].transition_in.name must be one of {sorted(TRANSITION_NAMES)}, got: {name!r}"
        )
    duration = transition.get("duration", 0.0)
    if not is_number(duration) or duration < 0 or duration > TRANSITION_MAX_DURATION:
        ctx.error(
            f"visual_track[{idx}].transition_in.duration must be a number in [0, {TRANSITION_MAX_DURATION}], got: {duration!r}"
        )
    if name == "cut" and duration not in (0, 0.0):
        ctx.error(f"visual_track[{idx}].transition_in.name=cut requires duration=0, got: {duration!r}")
    if name == "crossfade" and duration <= 0:
        ctx.error(f"visual_track[{idx}].transition_in.name=crossfade requires duration > 0")


def validate_anti_flicker(track: list[dict[str, Any]], ctx: ValidationContext) -> None:
    """Guard against the flicker/re-zoom-snap patterns called out in the render redesign:
    a transition or a motion restart between two consecutive events that share the exact
    same visual (layout + asset_ids) reads as a flash or a jump-cut zoom on screen."""
    ordered = sorted(
        (event for event in track if isinstance(event, dict) and isinstance(event.get("start"), (int, float))),
        key=lambda event: event["start"],
    )
    for idx in range(1, len(ordered)):
        previous, current = ordered[idx - 1], ordered[idx]
        if visual_event_key(previous) != visual_event_key(current):
            continue
        label = current.get("id") or f"visual_track[{idx}]"
        transition = current.get("transition_in")
        if isinstance(transition, dict) and transition.get("name", "cut") != "cut":
            ctx.error(
                f"{label} reuses the same visual as the previous event but declares a "
                f"{transition.get('name')} transition; use transition_in.name=cut (or omit it) "
                "so the renderer merges them into one continuous shot instead of flashing"
            )
        prev_motion = previous.get("motion") if isinstance(previous.get("motion"), dict) else {}
        cur_motion = current.get("motion") if isinstance(current.get("motion"), dict) else {}
        if prev_motion.get("name", "hold") != cur_motion.get("name", "hold") or prev_motion.get(
            "amount", 0.0
        ) != cur_motion.get("amount", 0.0):
            ctx.error(
                f"{label} reuses the same visual as the previous event but declares a different "
                "motion; the renderer merges same-visual events into one continuous shot, so "
                "motion.name/amount must match the previous event"
            )


def validate_visual_track(track: Any, asset_ids: set[str], script_ids: set[str], ctx: ValidationContext) -> None:
    if not isinstance(track, list):
        ctx.error("visual_track must be a list")
        return
    project_assets = getattr(ctx, "project_assets", {})
    for idx, event in enumerate(track):
        if not isinstance(event, dict):
            ctx.error(f"visual_track[{idx}] must be an object")
            continue
        _validate_timed_event(event, f"visual_track[{idx}]", ctx)
        validate_layout_contract(event, idx, ctx)
        for asset_id in event.get("asset_ids", []):
            if asset_id not in asset_ids:
                ctx.error(f"visual_track[{idx}] references missing asset: {asset_id}")
        validate_visual_asset_policy(event, idx, project_assets, ctx)
        validate_motion(event, idx, ctx)
        validate_transition(event, idx, ctx)
        for script_id in event.get("script_segment_ids", []):
            if script_ids and script_id not in script_ids:
                ctx.error(f"visual_track[{idx}] references missing script segment: {script_id}")
        if not event.get("layout"):
            ctx.warn(f"visual_track[{idx}] missing layout")
        if not event.get("qa_expectations"):
            ctx.warn(f"visual_track[{idx}] missing qa_expectations")
        start, end = event.get("start"), event.get("end")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and end - start < MIN_VISUAL_HOLD_SECONDS:
            message = (
                f"visual_track[{idx}] duration {end - start:.2f}s is under the {MIN_VISUAL_HOLD_SECONDS}s "
                "minimum hold; merge with a neighbor or lengthen it"
            )
            if ctx.strict:
                ctx.error(message)
            else:
                ctx.warn(message)

    if isinstance(track, list):
        validate_anti_flicker([event for event in track if isinstance(event, dict)], ctx)


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


def validate_visual_asset_policy(event: dict[str, Any], idx: int, assets: dict[str, dict[str, Any]], ctx: ValidationContext) -> None:
    evidence = str(event.get("evidence_binding") or "").lower()
    layout = str(event.get("layout") or event.get("display_mode") or "").lower()
    is_recording_layout = layout in {"browser-recording", "browser-recording-fit-width"}
    for asset_id in event.get("asset_ids", []):
        asset = assets.get(asset_id, {})
        asset_type = str(asset.get("type") or "").lower()
        aspect = asset_aspect(asset)
        image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
        workflow_step = str(image_resource.get("workflow_step") or "").lower()
        source = str(asset.get("source") or "").replace("\\", "/").lower()
        origin = str(asset.get("origin") or "").lower()

        is_generated_claim = evidence in {"real_generated_result", "real_result"} or workflow_step in {"result_page", "result_crop", "result_export", "result_gallery"}
        is_saved_result = workflow_step in {"result_crop", "result_export", "result_gallery"} or "assets/results/" in source
        if is_generated_claim and workflow_step == "result_page":
            ctx.error(
                f"visual_track[{idx}] uses website result page screenshot for generated-result display: {asset_id}; "
                "save/export/crop the generated result image itself under assets/results"
            )
        elif is_generated_claim and not is_saved_result:
            ctx.error(
                f"visual_track[{idx}] uses non-result asset for generated-result display: {asset_id}; "
                "save/export/crop the generated result image itself under assets/results"
            )
        elif is_generated_claim and aspect and aspect > 1.2 and not is_saved_result:
            ctx.error(
                f"visual_track[{idx}] uses a wide webpage/result screenshot for generated-result display: {asset_id}; "
                "save a result image/crop under assets/results or mark workflow_step=result_crop/result_export"
            )

        is_function_screenshot = workflow_step in {"menu_select", "feature_page_empty", "form_filled", "generate_callout", "generating"} or "browser" in origin
        if is_function_screenshot and aspect and aspect > 1.2:
            if not (is_recording_layout and asset_type == "video"):
                ctx.error(
                    f"visual_track[{idx}] uses a wide function screenshot: {asset_id}; capture/verify a 9:16 screenshot before rendering"
                )


def workflow_steps_for_event(event: dict[str, Any], assets: dict[str, dict[str, Any]]) -> set[str]:
    steps: set[str] = set()
    for asset_id in event.get("asset_ids", []):
        asset = assets.get(str(asset_id), {})
        if not isinstance(asset, dict):
            continue
        image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
        for key in ("workflow_step", "source_workflow_step", "operation_step"):
            value = str(image_resource.get(key) or "").strip().lower()
            if value:
                steps.add(value)
        for key in ("role", "source", "filename", "description"):
            value = str(asset.get(key) or "").replace("\\", "/").lower()
            if not value:
                continue
            if any(token in value for token in ("home", "首页", "dashboard")):
                steps.add("home_entry")
            if any(token in value for token in ("文生图", "text_to_image", "text-to-image")):
                steps.add("text_to_image_entry")
            if any(token in value for token in ("menu", "select", "vi", "菜单", "选择")):
                steps.add("menu_select")
            if any(token in value for token in ("form_empty", "feature_page", "功能页")):
                steps.add("feature_page_empty")
            if any(token in value for token in ("form_filled", "filled", "表单")):
                steps.add("form_filled")
            if any(token in value for token in ("recording", "录屏", "screen_record")):
                steps.add("operation_recording")
        source_asset_id = str(asset.get("source_asset_id") or image_resource.get("source_asset_id") or "")
        source_asset = assets.get(source_asset_id, {}) if source_asset_id else {}
        if isinstance(source_asset, dict):
            source_resource = source_asset.get("image_resource", {}) if isinstance(source_asset.get("image_resource"), dict) else {}
            source_step = str(source_resource.get("workflow_step") or "").strip().lower()
            if source_step:
                steps.add(source_step)
    if str(event.get("evidence_binding") or "").lower() == "real_recording":
        steps.add("operation_recording")
    if str(event.get("layout") or event.get("display_mode") or "").lower() in {"browser-recording", "browser-recording-fit-width"}:
        steps.add("operation_recording")
    return steps


def validate_operation_path(project: dict[str, Any], assets: dict[str, dict[str, Any]], ctx: ValidationContext) -> None:
    inputs = project.get("inputs", {}) if isinstance(project.get("inputs"), dict) else {}
    request = inputs.get("request", {}) if isinstance(inputs.get("request"), dict) else {}
    target_url = str(request.get("target_url") or "").lower()
    if "kehuanxiongmao.com" not in target_url:
        return

    visual_track = project.get("visual_track", [])
    if not isinstance(visual_track, list):
        return
    has_verified_result = any(
        isinstance(event, dict)
        and (
            str(event.get("operation_status") or "").lower() == "verified_result"
            or str(event.get("evidence_binding") or "").lower() in {"real_result", "real_generated_result"}
        )
        for event in visual_track
    )
    if not has_verified_result:
        return

    all_steps: set[str] = set()
    for event in visual_track:
        if isinstance(event, dict):
            all_steps.update(workflow_steps_for_event(event, assets))

    if "operation_recording" in all_steps:
        return

    has_entry = bool(all_steps & {"home_entry", "feature_card", "navigation_callout", "text_to_image_entry"})
    has_selection = bool(all_steps & {"menu_select", "feature_menu_select", "vi_menu_select"})
    has_destination = bool(all_steps & {"feature_page_empty", "form_filled", "generate_callout"})
    if not (has_entry and has_selection and has_destination):
        ctx.error(
            "kehuanxiongmao verified-result video must show the stepwise entry path. "
            "Use a browser recording, or include annotated 9:16 screenshots for entry/text-to-image menu, VI/menu selection, and the destination feature page."
        )


def validate_overlay_track(track: Any, asset_ids: set[str], ctx: ValidationContext) -> None:
    if not isinstance(track, list):
        ctx.error("overlay_track must be a list")
        return
    for idx, event in enumerate(track):
        if not isinstance(event, dict):
            ctx.error(f"overlay_track[{idx}] must be an object")
            continue
        _validate_timed_event(event, f"overlay_track[{idx}]", ctx)
        asset_id = event.get("asset_id")
        if asset_id and asset_id not in asset_ids:
            ctx.error(f"overlay_track[{idx}] references missing asset: {asset_id}")


def validate_audio_tracks(track: Any, ctx: ValidationContext) -> None:
    if not isinstance(track, list):
        ctx.error("audio_tracks must be a list")
        return
    for idx, event in enumerate(track):
        if not isinstance(event, dict):
            ctx.error(f"audio_tracks[{idx}] must be an object")
            continue
        _validate_timed_event(event, f"audio_tracks[{idx}]", ctx)
        source = event.get("source")
        if source:
            path = ctx.resolve_path(source)
            if not path or not path.is_file():
                ctx.error(f"audio_tracks[{idx}] source missing: {source}")


def validate_renderer_plan(plan: Any, ctx: ValidationContext) -> None:
    if not isinstance(plan, dict):
        ctx.error("renderer_plan must be an object")
        return
    renderer = plan.get("renderer")
    if renderer and renderer != "simple_ffmpeg":
        ctx.error(f"renderer must be simple_ffmpeg, got: {renderer}")
    if not renderer:
        ctx.error("renderer_plan.renderer missing")


def validate_case(case_dir: Path, strict: bool, project_path: Path | None = None) -> dict[str, Any]:
    skill_root = require_skill_root(Path(__file__).resolve())
    ctx = ValidationContext(case_dir.resolve(strict=False), skill_root, strict)
    if strict and not is_relative_to(ctx.case_dir, skill_root):
        ctx.error(f"case directory must be inside skill project: {ctx.case_dir}")

    if not case_dir.is_dir():
        ctx.error(f"case directory does not exist: {case_dir}")
        return result(ctx)

    input_data = load_json(case_dir / "input.json", ctx)
    validate_input_json(input_data, ctx)
    if strict:
        for error in kehuanxiongmao_auth_errors(ctx.case_dir, input_data):
            ctx.error(error)

    project = load_json(project_path or case_dir / "video_project.json", ctx)
    if project and not validate_placeholder_project(project, ctx):
        validate_strict_project(project, ctx)

    return result(ctx)


def result(ctx: ValidationContext) -> dict[str, Any]:
    ok = not ctx.errors
    return {
        "ok": ok,
        "code": "ok" if ok else "validation_failed",
        "reason": "" if ok else f"{len(ctx.errors)} validation error(s)",
        "data": {
            "case_dir": str(ctx.case_dir),
            "strict": ctx.strict,
            "errors": ctx.errors,
            "warnings": ctx.warnings,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate video-agent case/project JSON.")
    parser.add_argument("--case", required=True, help="Case directory containing input.json and video_project.json.")
    parser.add_argument("--project", help="Project JSON path. Defaults to <case>/video_project.json.")
    parser.add_argument("--strict", action="store_true", help="Require complete render-ready video_project.json.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else None
        output = validate_case(Path(args.case).expanduser(), args.strict, project_path)
    except Exception as exc:  # noqa: BLE001 - CLI must report structured failure.
        output = {
            "ok": False,
            "code": exc.__class__.__name__,
            "reason": str(exc),
            "data": {"errors": [str(exc)], "warnings": []},
        }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print("Validation passed")
    else:
        print(output["reason"], file=sys.stderr)
        for error in output["data"].get("errors", []):
            print(f"- {error}", file=sys.stderr)

    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
