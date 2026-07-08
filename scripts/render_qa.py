from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

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


def resolve_case_path(case_dir: Path, value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else case_dir / path


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
    capture_origin = origin in {"browser_capture", "frontend_capture", "cdp_capture"}
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


def check_visual_asset_readiness(project: dict[str, Any]) -> tuple[list[str], list[str]]:
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
        label = event.get("id") or f"visual_track[{idx}]"
        evidence = str(event.get("evidence_binding") or "").lower()
        for asset in event_assets:
            aspect = asset_aspect(asset)
            image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
            workflow_step = str(image_resource.get("workflow_step") or "").lower()
            source = str(asset.get("source") or "").replace("\\", "/").lower()
            origin = str(asset.get("origin") or "").lower()
            asset_id = asset.get("id", "unknown")
            is_generated_claim = evidence in {"real_generated_result", "real_result"} or workflow_step in {"result_page", "result_crop", "result_export", "result_gallery"}
            is_saved_result = workflow_step in {"result_crop", "result_export", "result_gallery"} or "assets/results/" in source
            if is_generated_claim and workflow_step == "result_page":
                errors.append(f"{label}: generated result uses website result page `{asset_id}`; save/export/crop the generated result image itself")
            elif is_generated_claim and not is_saved_result:
                errors.append(f"{label}: generated result uses non-result asset `{asset_id}`; save/export/crop the generated result image itself")
            elif is_generated_claim and aspect and aspect > 1.2 and not is_saved_result:
                errors.append(f"{label}: generated result uses wide webpage screenshot `{asset_id}`; save/crop the result image first")
            is_function_screenshot = workflow_step in {"menu_select", "feature_page_empty", "form_filled", "generate_callout", "generating"} or "browser" in origin
            if is_function_screenshot and aspect and aspect > 1.2:
                errors.append(f"{label}: function screenshot `{asset_id}` is wide; capture an AI-verified 9:16 screenshot first")
    return errors, warnings


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
        combined = " ".join(
            str(asset.get(key) or "").replace("\\", "/").lower()
            for key in ("role", "source", "filename", "description")
        )
        if any(token in combined for token in ("home", "首页", "dashboard")):
            steps.add("home_entry")
        if any(token in combined for token in ("文生图", "text_to_image", "text-to-image")):
            steps.add("text_to_image_entry")
        if any(token in combined for token in ("menu", "select", "vi", "菜单", "选择")):
            steps.add("menu_select")
        if any(token in combined for token in ("form_empty", "feature_page", "功能页")):
            steps.add("feature_page_empty")
        if any(token in combined for token in ("form_filled", "filled", "表单")):
            steps.add("form_filled")
    return steps


def check_operation_path(project: dict[str, Any]) -> list[str]:
    inputs = project.get("inputs", {}) if isinstance(project.get("inputs"), dict) else {}
    request = inputs.get("request", {}) if isinstance(inputs.get("request"), dict) else {}
    if "kehuanxiongmao.com" not in str(request.get("target_url") or "").lower():
        return []
    assets = {
        asset.get("id"): asset
        for asset in project.get("assets", [])
        if isinstance(asset, dict) and asset.get("id")
    }
    events = [event for event in project.get("visual_track", []) if isinstance(event, dict)]
    has_verified_result = any(
        str(event.get("operation_status") or "").lower() == "verified_result"
        or str(event.get("evidence_binding") or "").lower() in {"real_result", "real_generated_result"}
        for event in events
    )
    if not has_verified_result:
        return []
    steps: set[str] = set()
    for event in events:
        steps.update(workflow_steps_for_event(event, assets))
    if steps & {"home_entry", "feature_card", "navigation_callout", "text_to_image_entry"} and steps & {"menu_select", "feature_menu_select", "vi_menu_select"} and steps & {"feature_page_empty", "form_filled", "generate_callout"}:
        return []
    return ["missing stepwise entry path: include annotated screenshots for 文生图 entry, target feature selection, and destination feature page"]


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    video = choose_video(case_dir, args.video)
    project_path = Path(args.project).expanduser().resolve(strict=False) if args.project else case_dir / "video_project.json"
    project = load_json(project_path)
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
        ending_path = resolve_case_path(case_dir, ending.get("source"))
        ending_duration = 0.0
        if ending_path and ending_path.is_file():
            ending_data = ffprobe(ending_path)
            ending_fmt = ending_data.get("format", {})
            ending_duration = float(ending_fmt.get("duration", 0) or 0)
        else:
            errors.append(f"ending video missing: {ending.get('source')}")
        if ending_duration and duration <= ending_duration:
            errors.append("final video duration is not longer than ending duration")

    layout_errors, layout_warnings = check_visual_asset_readiness(project)
    errors.extend(layout_errors)
    warnings.extend(layout_warnings)
    errors.extend(check_operation_path(project))

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
        "project": str(project_path),
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
    parser.add_argument("--project", help="Project JSON path. Defaults to <case>/video_project.json.")
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
