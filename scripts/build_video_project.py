from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_case_path(case_dir: Path, value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value)
    return str(path if path.is_absolute() else case_dir / path)


def material_map(case_dir: Path) -> dict[str, dict[str, Any]]:
    manifest = load_json(case_dir / "asset_manifest.json", {"assets": []})
    understanding = load_json(case_dir / "material_understanding.json", {"materials": []})
    insights = {
        item.get("asset_id"): item
        for item in understanding.get("materials", [])
        if isinstance(item, dict) and item.get("asset_id")
    }
    assets: dict[str, dict[str, Any]] = {}
    for asset in manifest.get("assets", []):
        if not isinstance(asset, dict) or not asset.get("id"):
            continue
        merged = dict(asset)
        insight = insights.get(asset["id"], {})
        if insight:
            merged["description"] = insight.get("vision_summary") or asset.get("description", "")
            merged["role"] = insight.get("page_or_scene_role") or asset.get("role", "unclassified")
            merged["visible_text"] = insight.get("visible_text", asset.get("visible_text", []))
            merged["supported_claims"] = insight.get("supported_claims", asset.get("supported_claims", []))
            merged["layout_advice"] = insight.get("layout_advice", "")
            merged["recommended_usage"] = insight.get("recommended_usage", "")
            merged["display_risk"] = insight.get("display_risk", [])
            merged["layout_plan"] = insight.get("layout_plan", {})
        assets[asset["id"]] = merged
    return assets


def choose_asset_ids(segment: dict[str, Any], assets: list[dict[str, Any]], idx: int) -> list[str]:
    preferred = segment.get("preferred_asset_ids") or segment.get("asset_ids") or []
    if preferred:
        task = str(segment.get("material_task") or "").lower()
        intent = str(segment.get("visual_intent") or "").lower()
        multi_tokens = ("grid", "gallery", "module", "模块", "对比", "comparison")
        if len(preferred) > 1 and any(token in task or token in intent for token in multi_tokens):
            return [str(asset_id) for asset_id in preferred[:4]]
        return [str(preferred[0])]
    if not assets:
        raise ValueError("no assets available for visual track")
    return [str(assets[min(idx, len(assets) - 1)]["id"])]


def layout_for(segment: dict[str, Any], asset: dict[str, Any], asset_count: int) -> str:
    segment_layout = str(segment.get("layout_intent") or "").strip()
    if segment_layout:
        return segment_layout
    if asset_count >= 3:
        return "grid-rebuild"
    if asset_count == 2:
        return "main-plus-reference"
    plan = asset.get("layout_plan", {}) if isinstance(asset.get("layout_plan"), dict) else {}
    planned = str(plan.get("primary_display_mode") or "").strip()
    if planned:
        return planned
    advice = str(asset.get("layout_advice") or asset.get("recommended_usage") or "").lower()
    role = str(asset.get("role") or "").lower()
    risks = " ".join(str(v).lower() for v in asset.get("display_risk", []) if isinstance(v, str))
    metadata = asset.get("metadata", {})
    aspect = metadata.get("aspect_ratio") if isinstance(metadata, dict) else None
    if "multi-section" in advice or "tall" in risks:
        return "multi-section"
    if "scroll" in advice and isinstance(aspect, (int, float)) and aspect < 0.35:
        return "multi-section"
    if isinstance(aspect, (int, float)) and aspect < 0.35:
        return "multi-section"
    if "crop" in advice or "ui" in role or "entry" in role or "wide" in risks:
        return "crop-focus"
    if isinstance(aspect, (int, float)) and aspect > 1.2:
        return "crop-focus"
    if isinstance(aspect, (int, float)) and 0.42 <= aspect <= 0.78:
        return "portrait-showcase"
    return "full-preview"


def focus_region_for(segment: dict[str, Any], asset: dict[str, Any]) -> str:
    explicit = str(segment.get("focus_region") or "").strip()
    if explicit:
        return explicit
    plan = asset.get("layout_plan", {}) if isinstance(asset.get("layout_plan"), dict) else {}
    planned = str(plan.get("focus_region") or "").strip()
    if planned:
        return planned
    combined = " ".join(
        str(value or "")
        for value in (
            asset.get("layout_advice"),
            asset.get("recommended_usage"),
            asset.get("role"),
            asset.get("description"),
            segment.get("material_task"),
        )
    ).lower()
    if any(token in combined for token in ("left", "左", "upload", "上传", "form", "表单")):
        return "left_form_area"
    if any(token in combined for token in ("right", "右", "result", "结果", "gallery", "效果")):
        return "right_result_area"
    if any(token in combined for token in ("button", "按钮", "generate", "生成")):
        return "generate_button_area"
    if any(token in combined for token in ("top", "顶部", "header", "导航")):
        return "top_area"
    return "center_functional_area"


def layout_reason_for(layout: str, asset: dict[str, Any], segment: dict[str, Any]) -> str:
    role = asset.get("role", "asset")
    task = segment.get("material_task", "")
    return f"Selected {layout} for 1080x1920 readability; asset role={role}; segment task={task}."


def subtitle_segments(case_dir: Path) -> list[dict[str, Any]]:
    subtitle_track = load_json(case_dir / "subtitle_track.json", {})
    segments = subtitle_track.get("segments", []) if isinstance(subtitle_track, dict) else []
    if segments:
        return segments
    project = load_json(case_dir / "video_project.json", {})
    track = project.get("subtitle_track", {}) if isinstance(project, dict) else {}
    return track.get("segments", []) if isinstance(track, dict) else []


def build_visual_track(script_segments: list[dict[str, Any]], subtitles: list[dict[str, Any]], assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    asset_by_id = {asset["id"]: asset for asset in assets}
    subtitle_by_seg = {sub.get("script_segment_id"): sub for sub in subtitles if isinstance(sub, dict)}
    visuals: list[dict[str, Any]] = []
    for idx, segment in enumerate(script_segments):
        sub = subtitle_by_seg.get(segment.get("id"))
        start = float(sub.get("start", idx * 3.0)) if isinstance(sub, dict) else idx * 3.0
        end = float(sub.get("end", start + float(segment.get("duration_hint") or 3.0))) if isinstance(sub, dict) else start + float(segment.get("duration_hint") or 3.0)
        asset_ids = choose_asset_ids(segment, assets, idx)
        asset = asset_by_id.get(asset_ids[0], {})
        layout = layout_for(segment, asset, len(asset_ids))
        plan = asset.get("layout_plan", {}) if isinstance(asset.get("layout_plan"), dict) else {}
        visuals.append(
            {
                "id": f"vis_{idx + 1:03d}",
                "script_segment_ids": [segment.get("id")],
                "start": round(max(start - 0.12, 0), 3),
                "end": round(end, 3),
                "asset_ids": asset_ids,
                "layout": layout,
                "display_mode": layout,
                "framing": {
                    "focus_region": focus_region_for(segment, asset),
                    "subject_min_frame_ratio": float(plan.get("min_subject_frame_ratio") or 0.45),
                    "subtitle_safe": True,
                    "target_canvas": "1080x1920",
                    "fill_strategy": plan.get("fill_strategy", "fit_or_crop_for_readability"),
                },
                "motion": {
                    "name": "stable_focus",
                    "avoid_flicker": True,
                },
                "qa_expectations": {
                    "no_black_frame": True,
                    "no_flash_if_same_asset": True,
                    "readable_ui": True,
                    "no_meaningless_empty_panel": True,
                    "no_narrow_full_page_strip": True,
                    "no_overzoom_without_focus_reason": True,
                },
                "layout_reason": layout_reason_for(layout, asset, segment),
            }
        )
    return visuals


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    input_data = load_json(case_dir / "input.json", {})
    script = load_json(case_dir / "video_script.json", {})
    voice_report = load_json(case_dir / "output" / "voice_clone" / "voice_clone_report.json", {})
    voice_plan = load_json(case_dir / "voice_plan.json", {})
    subtitles = subtitle_segments(case_dir)
    assets_map = material_map(case_dir)
    assets = list(assets_map.values())

    script_segments = script.get("segments", [])
    if not isinstance(script_segments, list) or not script_segments:
        raise ValueError("video_script.json must contain reviewed segments")

    project_assets = []
    for asset in assets:
        project_assets.append(
            {
                "id": asset["id"],
                "type": asset.get("type"),
                "source": asset.get("source"),
                "origin": asset.get("origin", "static_material_folder"),
                "role": asset.get("role", "unclassified"),
                "description": asset.get("description", ""),
                "visible_text": asset.get("visible_text", []),
                "supported_claims": asset.get("supported_claims", []),
                "metadata": asset.get("metadata", {}),
                "display_risk": asset.get("display_risk", []),
                "layout_plan": asset.get("layout_plan", {}),
                "quality": asset.get("quality", {}),
            }
        )

    ending_track = input_data.get("ending_track", {"policy": "none"})
    duration = voice_report.get("duration")
    if duration is None and subtitles:
        duration = max(float(sub.get("end", 0)) for sub in subtitles if isinstance(sub, dict))

    project = {
        "schema_version": 1,
        "meta": {
            "case_id": case_dir.name,
            "title": input_data.get("request", {}).get("video_goal", "Video Agent Render"),
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "target_platform": input_data.get("request", {}).get("target_platform", "douyin"),
            "target_duration": input_data.get("request", {}).get("duration", duration),
            "language": "zh-CN",
            "safe_area": {"top": 120, "bottom": 260, "left": 60, "right": 60},
        },
        "inputs": input_data,
        "assets": project_assets,
        "script_segments": script_segments,
        "voice_track": {
            "mode": input_data.get("voice_config", {}).get("mode", "voice_clone"),
            "engine": input_data.get("voice_config", {}).get("engine", "voice_clone_api"),
            "source_text": voice_plan.get("text") or voice_report.get("text"),
            "audio_path": "audio/voice.wav",
            "duration": duration,
            "speed_policy": voice_plan.get("speed_policy", {}),
            "high_risk_terms": voice_plan.get("high_risk_terms", []),
            "qa": {},
        },
        "subtitle_track": {
            "source": "output/funasr/funasr_alignment.json",
            "format": "asr_aligned_reviewed_text",
            "segments": subtitles,
        },
        "visual_track": build_visual_track(script_segments, subtitles, assets),
        "overlay_track": [],
        "audio_tracks": [],
        "ending_track": ending_track,
        "renderer_plan": {
            "renderer": "hyperframes",
            "composition_dir": "hyperframes",
            "main_output": "output/versions/main.mp4",
            "final_output": "output/versions/final.mp4",
            "allow_creative_layout": True,
            "must_follow_tracks": True,
        },
        "qa_rules": {
            "voice": {"require_asr_alignment": True, "require_brand_term_check": True, "max_internal_silence_seconds": 0.12},
            "visual": {"no_black_frames": True, "no_unexplained_blanks": True, "min_subject_frame_ratio": 0.35, "ui_must_be_readable": True, "subtitle_must_not_cover_key_content": True},
            "layout": {
                "dual_panel_height_must_match_media": True,
                "wide_ui_requires_crop_or_capture_if_unreadable": True,
                "tall_image_requires_scroll_or_sections": True,
                "portrait_result_should_fill_mobile_width": True,
                "no_overzoom_without_focus_reason": True,
                "same_asset_continuity_no_flash": True,
            },
        },
    }

    output_path = case_dir / "video_project.json"
    output_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "video_project": str(output_path),
            "asset_count": len(project_assets),
            "segment_count": len(script_segments),
            "visual_count": len(project["visual_track"]),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build render-ready video_project.json from case artifacts.")
    parser.add_argument("--case", required=True)
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
        print(f"Video project: {output['data']['video_project']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
