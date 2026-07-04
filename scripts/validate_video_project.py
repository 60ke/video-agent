from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from utils.skill_path import require_skill_root


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

    voice = input_data.get("voice_config", {})
    if isinstance(voice, dict):
        policy = voice.get("prompt_audio_policy", "default")
        prompt_audio = voice.get("case_prompt_audio")
        if policy in ("default", "custom"):
            path = ctx.resolve_path(prompt_audio)
            if not path or not path.is_file():
                ctx.error(f"voice prompt audio missing for policy {policy}: {prompt_audio}")
        elif policy != "none":
            ctx.error(f"unsupported voice prompt policy: {policy}")
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
        source = asset.get("source")
        if source:
            path = ctx.resolve_path(source)
            if not path or not path.is_file():
                ctx.error(f"asset source missing: {source}")
        else:
            ctx.error(f"assets[{idx}] missing source")

    script_segments = project.get("script_segments", [])
    if not isinstance(script_segments, list):
        ctx.error("video_project.script_segments must be a list")
        script_segments = []
    script_ids = {seg.get("id") for seg in script_segments if isinstance(seg, dict) and seg.get("id")}

    validate_voice_track(project.get("voice_track", {}), ctx)
    validate_subtitles(project.get("subtitle_track", {}), script_ids, ctx)
    validate_visual_track(project.get("visual_track", []), asset_ids, script_ids, ctx)
    validate_overlay_track(project.get("overlay_track", []), asset_ids, ctx)
    validate_audio_tracks(project.get("audio_tracks", []), ctx)
    validate_renderer_plan(project.get("renderer_plan", {}), ctx)


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


def validate_visual_track(track: Any, asset_ids: set[str], script_ids: set[str], ctx: ValidationContext) -> None:
    if not isinstance(track, list):
        ctx.error("visual_track must be a list")
        return
    for idx, event in enumerate(track):
        if not isinstance(event, dict):
            ctx.error(f"visual_track[{idx}] must be an object")
            continue
        _validate_timed_event(event, f"visual_track[{idx}]", ctx)
        for asset_id in event.get("asset_ids", []):
            if asset_id not in asset_ids:
                ctx.error(f"visual_track[{idx}] references missing asset: {asset_id}")
        for script_id in event.get("script_segment_ids", []):
            if script_ids and script_id not in script_ids:
                ctx.error(f"visual_track[{idx}] references missing script segment: {script_id}")
        if not event.get("layout"):
            ctx.warn(f"visual_track[{idx}] missing layout")
        if not event.get("qa_expectations"):
            ctx.warn(f"visual_track[{idx}] missing qa_expectations")


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
    if renderer and renderer != "hyperframes":
        ctx.error(f"P0 renderer must be hyperframes, got: {renderer}")
    if not renderer:
        ctx.error("renderer_plan.renderer missing")


def validate_case(case_dir: Path, strict: bool) -> dict[str, Any]:
    skill_root = require_skill_root(Path(__file__).resolve())
    ctx = ValidationContext(case_dir.resolve(strict=False), skill_root, strict)

    if not case_dir.is_dir():
        ctx.error(f"case directory does not exist: {case_dir}")
        return result(ctx)

    input_data = load_json(case_dir / "input.json", ctx)
    validate_input_json(input_data, ctx)

    project = load_json(case_dir / "video_project.json", ctx)
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
    parser.add_argument("--strict", action="store_true", help="Require complete render-ready video_project.json.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = validate_case(Path(args.case).expanduser(), args.strict)
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
