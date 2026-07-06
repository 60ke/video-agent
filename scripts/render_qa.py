from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

READABLE_WIDE_UI_LAYOUTS = {"crop-focus", "multi-section", "main-plus-reference", "browser-recording"}
GENERIC_FOCUS_REGIONS = {"", "auto", "center", "whole_page", "whole-page"}


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def ffprobe(path: Path) -> dict[str, Any]:
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def choose_video(case_dir: Path, explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit).expanduser().resolve(strict=False)
        if not path.is_file():
            raise FileNotFoundError(f"video not found: {path}")
        return path
    versions = case_dir / "output" / "versions"
    candidates = sorted(
        [p for p in versions.glob("*.mp4") if p.is_file() and not p.name.endswith("_main.mp4")],
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"no final mp4 found under {versions}")
    return candidates[0]


def asset_aspect(asset: dict[str, Any]) -> float | None:
    metadata = asset.get("metadata", {})
    if not isinstance(metadata, dict):
        return None
    aspect = metadata.get("aspect_ratio")
    if isinstance(aspect, (int, float)) and aspect > 0:
        return float(aspect)
    width = metadata.get("width")
    height = metadata.get("height")
    if isinstance(width, (int, float)) and isinstance(height, (int, float)) and height > 0:
        return float(width) / float(height)
    return None


def is_wide_ui_asset(asset: dict[str, Any]) -> bool:
    risks = {str(value).lower() for value in asset.get("display_risk", []) if isinstance(value, str)}
    if risks & {"wide_desktop_ui", "dense_desktop_ui"}:
        return True
    origin = str(asset.get("origin") or "").lower()
    role = str(asset.get("role") or "").lower()
    source = str(asset.get("source") or "").lower()
    aspect = asset_aspect(asset)
    capture_origin = origin in {"browser_capture", "frontend_capture", "kimi_webbridge", "webbridge_capture"}
    source_looks_like_ui = any(
        token in source
        for token in ("homepage", "signboard", "workbench", "dropdown", "browser", "page", "kehuan")
    )
    return bool(aspect and aspect > 1.2 and (capture_origin or "ui" in role or "page" in role or aspect > 1.8 and source_looks_like_ui))


def is_generated_result_asset(asset: dict[str, Any]) -> bool:
    image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
    combined = " ".join(
        str(value or "").lower()
        for value in (
            image_resource.get("variant"),
            image_resource.get("workflow_step"),
            asset.get("origin"),
            asset.get("role"),
            asset.get("description"),
            asset.get("source"),
        )
    )
    result_tokens = ("result", "export", "crop", "效果图", "结果", "样例", "生成图", "生成样例", "代表样例")
    ui_tokens = ("ui", "界面", "表单", "首页", "菜单", "button", "按钮", "page", "browser")
    return any(token in combined for token in result_tokens) and not any(token in combined for token in ui_tokens)


def check_wide_ui_layout(project: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    assets = {
        asset.get("id"): asset
        for asset in project.get("assets", [])
        if isinstance(asset, dict) and asset.get("id")
    }
    for idx, event in enumerate(project.get("visual_track", [])):
        if not isinstance(event, dict):
            continue
        event_assets = [assets.get(asset_id, {}) for asset_id in event.get("asset_ids", [])]
        if not any(is_wide_ui_asset(asset) for asset in event_assets):
            continue
        label = event.get("id") or f"visual_track[{idx}]"
        layout = str(event.get("display_mode") or event.get("layout") or "")
        if layout not in READABLE_WIDE_UI_LAYOUTS:
            errors.append(f"{label}: wide desktop UI uses unreadable primary layout `{layout or 'missing'}`")
        framing = event.get("framing", {}) if isinstance(event.get("framing"), dict) else {}
        focus_region = str(framing.get("focus_region") or "").lower()
        if focus_region in GENERIC_FOCUS_REGIONS:
            errors.append(f"{label}: wide desktop UI must declare a named functional focus_region")
        if not isinstance(framing.get("center_safe_region"), dict):
            errors.append(f"{label}: missing center_safe_region for 9:16 readability")
        visible = framing.get("must_be_visible")
        if not isinstance(visible, list) or not visible:
            errors.append(f"{label}: missing must_be_visible labels for narrated UI content")
        viewport_transform = framing.get("viewport_transform", {})
        if not isinstance(viewport_transform, dict) or not viewport_transform.get("lock_subject_in_center_safe_region"):
            warnings.append(f"{label}: viewport_transform should lock the narrated subject inside center_safe_region")
        motion = event.get("motion", {}) if isinstance(event.get("motion"), dict) else {}
        forbidden_motion = motion.get("forbidden_motion", [])
        if not isinstance(forbidden_motion, list) or "pan_subject_out_of_frame" not in forbidden_motion:
            warnings.append(f"{label}: motion should forbid pan_subject_out_of_frame")
    return errors, warnings


def check_result_layout(project: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    assets = {
        asset.get("id"): asset
        for asset in project.get("assets", [])
        if isinstance(asset, dict) and asset.get("id")
    }
    for idx, event in enumerate(project.get("visual_track", [])):
        if not isinstance(event, dict):
            continue
        event_assets = [assets.get(asset_id, {}) for asset_id in event.get("asset_ids", [])]
        if not any(is_generated_result_asset(asset) for asset in event_assets):
            continue
        layout = str(event.get("display_mode") or event.get("layout") or "")
        if layout in {"crop-focus", "ui_operation_focus"}:
            label = event.get("id") or f"visual_track[{idx}]"
            errors.append(f"{label}: generated result image should preserve the whole result, not use `{layout}`")
    return errors


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    video = choose_video(case_dir, args.video)
    project = load_json(case_dir / "video_project.json")
    input_data = load_json(case_dir / "input.json")
    data = ffprobe(video)
    streams = data.get("streams", [])
    fmt = data.get("format", {})
    errors: list[str] = []
    warnings: list[str] = []

    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if not video_stream:
        errors.append("no video stream")
    if not audio_stream:
        errors.append("no audio stream")

    meta = project.get("meta", {})
    expected_width = int(meta.get("width", 1080)) if isinstance(meta, dict) else 1080
    expected_height = int(meta.get("height", 1920)) if isinstance(meta, dict) else 1920
    if video_stream:
        width = video_stream.get("width")
        height = video_stream.get("height")
        if width != expected_width or height != expected_height:
            warnings.append(f"resolution differs from project meta: {width}x{height}, expected {expected_width}x{expected_height}")

    duration = float(fmt.get("duration", 0)) if fmt.get("duration") else 0
    if duration <= 0:
        errors.append("video duration is zero")

    contact_sheet = None
    qa_dir = case_dir / "output" / "qa"
    sheets = sorted(qa_dir.glob("*_contact_sheet.jpg"), key=lambda p: p.stat().st_mtime, reverse=True) if qa_dir.is_dir() else []
    if sheets:
        contact_sheet = str(sheets[0])
    else:
        warnings.append("no contact sheet found")

    ending = project.get("ending_track", {})
    if isinstance(ending, dict) and ending.get("policy") in ("default", "custom"):
        if duration <= float(ending.get("duration", 0) or 0):
            errors.append("final video duration is not longer than declared ending duration")

    layout_errors, layout_warnings = check_wide_ui_layout(project)
    errors.extend(layout_errors)
    warnings.extend(layout_warnings)
    errors.extend(check_result_layout(project))

    voice_qa = load_json(case_dir / "output" / "reports" / "voice_qa_report.json")
    if voice_qa and voice_qa.get("status") != "passed":
        for error in voice_qa.get("errors", []) if isinstance(voice_qa.get("errors"), list) else []:
            errors.append(f"voice QA failed: {error}")
        if not voice_qa.get("errors"):
            errors.append("voice QA failed")

    request = input_data.get("request", {}) if isinstance(input_data.get("request"), dict) else {}
    dependency_mode = input_data.get("dependency_mode", {}) if isinstance(input_data.get("dependency_mode"), dict) else {}
    case_info = input_data.get("case", {}) if isinstance(input_data.get("case"), dict) else {}
    if request.get("target_url") and dependency_mode.get("browser") == "static_materials" and case_info.get("static_materials_explicit") is not True:
        errors.append("website task used static_materials without explicit user request")

    ok = not errors
    report = {
        "schema_version": 1,
        "status": "passed" if ok else "failed",
        "video": str(video),
        "duration": duration,
        "has_video": video_stream is not None,
        "has_audio": audio_stream is not None,
        "video_stream": video_stream,
        "audio_stream": audio_stream,
        "contact_sheet": contact_sheet,
        "errors": errors,
        "warnings": warnings,
    }
    report_path = case_dir / "output" / "reports" / f"{video.stem}_qa_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": ok,
        "code": "ok" if ok else "render_qa_failed",
        "reason": "" if ok else f"{len(errors)} render QA error(s)",
        "data": report | {"report_path": str(report_path)},
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run machine-checkable render QA.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--video")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {
            "ok": False,
            "code": exc.__class__.__name__,
            "reason": str(exc),
            "data": {},
        }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print("Render QA passed")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
