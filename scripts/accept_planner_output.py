from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REQUIRED_MATERIAL_KEYS = (
    "asset_id",
    "filename",
    "type",
    "vision_summary",
    "page_or_scene_role",
    "recommended_usage",
    "needs_review",
)

REQUIRED_SCRIPT_KEYS = (
    "id",
    "stage",
    "text",
    "visual_intent",
    "material_task",
    "preferred_asset_ids",
    "duration_hint",
)

REQUIRED_VISUAL_PLAN_KEYS = (
    "id",
    "stage",
    "visual_intent",
    "material_task",
    "evidence_binding",
    "locked_asset_ids",
    "duration_hint",
)

ALLOWED_DISPLAY_MODES = {
    "full-preview",
    "portrait-showcase",
    "slow-scroll",
    "multi-section",
    "dual-preview",
    "main-plus-reference",
    "grid-rebuild",
    "full-width",
    "result-showcase",
}

ALLOWED_OPERATION_STATUS = {
    "verified_result",
    "verified_entry_only",
    "blocked_login",
    "blocked_permission",
    "unsafe_action",
    "unavailable",
}

ALLOWED_EVIDENCE_BINDINGS = {
    "real_screenshot",
    "real_result",
    "error_state",
    "evidence_cover",
    "packaging_only",
}

MIN_SPEECH_UNITS_PER_SECOND = 6.0


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def asset_ids(case_dir: Path) -> set[str]:
    manifest = load_json(case_dir / "asset_manifest.json")
    assets = manifest.get("assets", [])
    if not isinstance(assets, list):
        raise ValueError("asset_manifest.assets must be a list")
    return {str(asset.get("id")) for asset in assets if isinstance(asset, dict) and asset.get("id")}


def load_reviewed_visual_plan(case_dir: Path) -> dict[str, Any]:
    path = case_dir / "visual_plan.json"
    if not path.is_file():
        return {}
    plan = load_json(path)
    if plan.get("status") != "reviewed":
        return {}
    beats = plan.get("beats")
    if not isinstance(beats, list) or not beats:
        return {}
    return plan


def visual_plan_beats(case_dir: Path) -> dict[str, dict[str, Any]]:
    plan = load_reviewed_visual_plan(case_dir)
    beats = plan.get("beats", []) if isinstance(plan, dict) else []
    return {
        str(beat.get("id")): beat
        for beat in beats
        if isinstance(beat, dict) and beat.get("id")
    }


def asset_by_id(case_dir: Path) -> dict[str, dict[str, Any]]:
    manifest = load_json(case_dir / "asset_manifest.json")
    assets = manifest.get("assets", [])
    return {
        str(asset.get("id")): asset
        for asset in assets
        if isinstance(asset, dict) and asset.get("id")
    }


def ensure_list(value: Any, label: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    return value


def ensure_object(value: Any, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def normalize_layout_plan(value: Any, label: str) -> dict[str, Any]:
    plan = ensure_object(value, label)
    if not plan:
        return {}
    mode = str(plan.get("primary_display_mode") or plan.get("display_mode") or "").strip()
    if mode and mode not in ALLOWED_DISPLAY_MODES:
        raise ValueError(f"{label}.primary_display_mode is not supported: {mode}")
    forbidden = [str(v) for v in ensure_list(plan.get("forbidden_treatments"), f"{label}.forbidden_treatments")]
    must_be_visible = [str(v) for v in ensure_list(plan.get("must_be_visible"), f"{label}.must_be_visible")]
    normalized = {
        "primary_display_mode": mode,
        "focus_region": str(plan.get("focus_region") or "").strip(),
        "fill_strategy": str(plan.get("fill_strategy") or "").strip(),
        "min_subject_frame_ratio": float(plan.get("min_subject_frame_ratio") or 0.45),
        "center_safe_region": ensure_object(plan.get("center_safe_region"), f"{label}.center_safe_region"),
        "must_be_visible": must_be_visible,
        "viewport_transform": ensure_object(plan.get("viewport_transform"), f"{label}.viewport_transform"),
        "safe_area_notes": str(plan.get("safe_area_notes") or "").strip(),
        "forbidden_treatments": forbidden,
    }
    return {key: value for key, value in normalized.items() if value not in ("", [], None)}


def normalize_material(payload: dict[str, Any], case_dir: Path) -> tuple[dict[str, Any], list[str]]:
    ids = asset_ids(case_dir)
    assets = asset_by_id(case_dir)
    materials = ensure_list(payload.get("materials"), "material_understanding.materials")
    warnings: list[str] = []
    seen: set[str] = set()
    normalized = []

    for idx, item in enumerate(materials):
        if not isinstance(item, dict):
            raise ValueError(f"materials[{idx}] must be an object")
        for key in REQUIRED_MATERIAL_KEYS:
            if key not in item:
                raise ValueError(f"materials[{idx}] missing key: {key}")
        asset_id = str(item["asset_id"])
        if asset_id not in ids:
            raise ValueError(f"materials[{idx}] references unknown asset_id: {asset_id}")
        if asset_id in seen:
            raise ValueError(f"duplicate material asset_id: {asset_id}")
        seen.add(asset_id)

        manifest_asset = assets.get(asset_id, {})
        normalized.append(
            {
                "asset_id": asset_id,
                "filename": str(item.get("filename") or manifest_asset.get("filename") or ""),
                "type": str(item.get("type") or manifest_asset.get("type") or ""),
                "vision_summary": str(item.get("vision_summary") or "").strip(),
                "page_or_scene_role": str(item.get("page_or_scene_role") or "").strip(),
                "visible_text": [str(v) for v in ensure_list(item.get("visible_text"), f"materials[{idx}].visible_text")],
                "supported_claims": [str(v) for v in ensure_list(item.get("supported_claims"), f"materials[{idx}].supported_claims")],
                "recommended_usage": str(item.get("recommended_usage") or "").strip(),
                "display_risk": [str(v) for v in ensure_list(item.get("display_risk"), f"materials[{idx}].display_risk")],
                "layout_advice": str(item.get("layout_advice") or "").strip(),
                "layout_plan": normalize_layout_plan(item.get("layout_plan"), f"materials[{idx}].layout_plan"),
                "needs_review": bool(item.get("needs_review")),
            }
        )
        if not normalized[-1]["vision_summary"]:
            warnings.append(f"materials[{idx}] has empty vision_summary")
        risks = set(normalized[-1]["display_risk"])
        if risks & {"wide_desktop_ui", "dense_desktop_ui", "tall_image_needs_scroll"} and not normalized[-1]["layout_plan"]:
            warnings.append(f"materials[{idx}] has display risk but no layout_plan")
        if risks & {"wide_desktop_ui", "dense_desktop_ui"}:
            plan = normalized[-1]["layout_plan"]
            mode = str(plan.get("primary_display_mode") or "")
            focus_region = str(plan.get("focus_region") or "").lower()
            if mode == "full-preview":
                raise ValueError(f"materials[{idx}] wide desktop UI cannot use full-preview as primary display mode")
            if mode not in {"portrait-showcase", "full-width", "main-plus-reference", "result-showcase"}:
                raise ValueError(f"materials[{idx}] wide desktop UI must use a prepared 9:16/width-fit display mode, got: {mode or 'missing'}")
            if focus_region in {"", "auto", "center", "whole_page", "whole-page"}:
                warnings.append(f"materials[{idx}] wide desktop UI should be a prepared 9:16 capture and declare a named functional focus_region")
            if not plan.get("must_be_visible"):
                warnings.append(f"materials[{idx}] wide desktop UI should declare must_be_visible labels")

    missing = ids - seen
    if missing:
        warnings.append(f"material output omitted assets: {', '.join(sorted(missing))}")

    return {
        "schema_version": 1,
        "status": "vision_reviewed" if not any(item["needs_review"] for item in normalized) else "needs_human_review",
        "materials": normalized,
    }, warnings


def normalize_visual_plan(payload: dict[str, Any], case_dir: Path) -> tuple[dict[str, Any], list[str]]:
    ids = asset_ids(case_dir)
    beats = ensure_list(payload.get("beats"), "visual_plan.beats")
    if not beats:
        raise ValueError("visual_plan.beats must not be empty")

    warnings: list[str] = []
    seen: set[str] = set()
    normalized = []
    for idx, item in enumerate(beats):
        if not isinstance(item, dict):
            raise ValueError(f"beats[{idx}] must be an object")
        for key in REQUIRED_VISUAL_PLAN_KEYS:
            if key not in item:
                raise ValueError(f"beats[{idx}] missing key: {key}")
        beat_id = normalize_segment_id(item.get("id"), idx).replace("seg_", "beat_")
        if beat_id in seen:
            raise ValueError(f"duplicate visual beat id: {beat_id}")
        seen.add(beat_id)

        locked = [str(v) for v in ensure_list(item.get("locked_asset_ids"), f"beats[{idx}].locked_asset_ids")]
        if not locked:
            raise ValueError(f"{beat_id} locked_asset_ids must not be empty")
        for asset_id in locked:
            if asset_id not in ids:
                raise ValueError(f"{beat_id} references unknown asset_id: {asset_id}")

        duration = float(item.get("duration_hint") or 0)
        if duration <= 0:
            raise ValueError(f"{beat_id} duration_hint must be > 0")

        operation_status = str(item.get("operation_status") or "").strip()
        if operation_status and operation_status not in ALLOWED_OPERATION_STATUS:
            raise ValueError(f"{beat_id} unsupported operation_status: {operation_status}")
        evidence_binding = str(item.get("evidence_binding") or "").strip()
        if evidence_binding and evidence_binding not in ALLOWED_EVIDENCE_BINDINGS:
            raise ValueError(f"{beat_id} unsupported evidence_binding: {evidence_binding}")
        if operation_status in {"verified_entry_only", "blocked_login", "blocked_permission"} and evidence_binding == "real_result":
            raise ValueError(f"{beat_id} cannot bind to real_result when operation_status is {operation_status}")

        normalized.append(
            {
                "id": beat_id,
                "stage": str(item.get("stage") or "body"),
                "feature_id": str(item.get("feature_id") or payload.get("feature_id") or ""),
                "feature_label": str(item.get("feature_label") or payload.get("feature_label") or ""),
                "visual_intent": str(item.get("visual_intent") or "").strip(),
                "material_task": str(item.get("material_task") or "").strip(),
                "evidence_binding": evidence_binding,
                "operation_status": operation_status,
                "locked_asset_ids": locked,
                "layout_intent": str(item.get("layout_intent") or "").strip(),
                "focus_region": str(item.get("focus_region") or "").strip(),
                "camera_note": str(item.get("camera_note") or "").strip(),
                "allowed_claims": [str(v) for v in ensure_list(item.get("allowed_claims"), f"beats[{idx}].allowed_claims")],
                "forbidden_claims": [str(v) for v in ensure_list(item.get("forbidden_claims"), f"beats[{idx}].forbidden_claims")],
                "duration_hint": round(duration, 3),
            }
        )

    return {
        "schema_version": 1,
        "status": "reviewed",
        "feature_id": str(payload.get("feature_id") or ""),
        "feature_label": str(payload.get("feature_label") or ""),
        "beats": normalized,
    }, warnings


def speech_units(text: str) -> int:
    compact = "".join(text.split())
    # Treat ASCII words as one spoken unit so "AI" does not look too dense.
    ascii_words = re.findall(r"[A-Za-z][A-Za-z0-9+-]*", compact)
    without_ascii = re.sub(r"[A-Za-z][A-Za-z0-9+-]*", "", compact)
    return len(without_ascii) + len(ascii_words)


def normalize_segment_id(value: Any, idx: int) -> str:
    raw = str(value or "").strip()
    if raw:
        return raw
    return f"seg_{idx + 1:03d}"


def normalize_script(payload: dict[str, Any], case_dir: Path) -> tuple[dict[str, Any], list[str]]:
    ids = asset_ids(case_dir)
    beats_by_id = visual_plan_beats(case_dir)
    segments = ensure_list(payload.get("segments"), "video_script.segments")
    if not segments:
        raise ValueError("video_script.segments must not be empty")

    warnings: list[str] = []
    seen: set[str] = set()
    normalized = []
    for idx, item in enumerate(segments):
        if not isinstance(item, dict):
            raise ValueError(f"segments[{idx}] must be an object")
        required_keys = ("id", "text", "duration_hint", "visual_beat_id") if beats_by_id else REQUIRED_SCRIPT_KEYS
        for key in required_keys:
            if key not in item:
                if key == "visual_beat_id" and str(item.get("id") or "") in beats_by_id:
                    continue
                raise ValueError(f"segments[{idx}] missing key: {key}")
        seg_id = normalize_segment_id(item.get("id"), idx)
        if seg_id in seen:
            raise ValueError(f"duplicate segment id: {seg_id}")
        seen.add(seg_id)

        visual_beat_id = str(item.get("visual_beat_id") or "").strip()
        if beats_by_id and not visual_beat_id and seg_id in beats_by_id:
            visual_beat_id = seg_id
        beat = beats_by_id.get(visual_beat_id, {}) if visual_beat_id else {}
        if beats_by_id and not beat:
            raise ValueError(f"{seg_id} must reference a reviewed visual_plan beat via visual_beat_id")

        locked = [str(v) for v in ensure_list(beat.get("locked_asset_ids"), f"visual_plan.{visual_beat_id}.locked_asset_ids")] if beat else []
        preferred = [str(v) for v in ensure_list(item.get("preferred_asset_ids"), f"segments[{idx}].preferred_asset_ids")]
        if locked:
            if preferred and preferred != locked:
                raise ValueError(f"{seg_id} preferred_asset_ids must match visual_plan.{visual_beat_id}.locked_asset_ids")
            preferred = locked
        for asset_id in preferred:
            if asset_id not in ids:
                raise ValueError(f"segments[{idx}] references unknown asset_id: {asset_id}")

        text = str(item.get("text") or "").strip()
        if not text:
            raise ValueError(f"segments[{idx}] text must not be empty")
        duration = float(item.get("duration_hint") or 0)
        if duration <= 0:
            raise ValueError(f"segments[{idx}] duration_hint must be > 0")
        density = speech_units(text) / duration
        if density < MIN_SPEECH_UNITS_PER_SECOND:
            raise ValueError(f"{seg_id} speech density {density:.2f} below minimum policy {MIN_SPEECH_UNITS_PER_SECOND:.1f} units/sec")

        stage = str(item.get("stage") or beat.get("stage") or "body")
        feature_id = str(item.get("feature_id") or beat.get("feature_id") or "")
        visual_intent = str(item.get("visual_intent") or beat.get("visual_intent") or "").strip()
        material_task = str(item.get("material_task") or beat.get("material_task") or "").strip()
        layout_intent = str(item.get("layout_intent") or beat.get("layout_intent") or "").strip()
        focus_region = str(item.get("focus_region") or beat.get("focus_region") or "").strip()
        camera_note = str(item.get("camera_note") or beat.get("camera_note") or "").strip()
        allowed_claims = [str(v) for v in ensure_list(item.get("allowed_claims") or beat.get("allowed_claims"), f"segments[{idx}].allowed_claims")]
        forbidden_claims = [str(v) for v in ensure_list(item.get("forbidden_claims") or beat.get("forbidden_claims"), f"segments[{idx}].forbidden_claims")]

        planning_text = " ".join(
            str(value or "")
            for value in (stage, visual_intent, material_task)
        ).lower()
        if any(token in planning_text for token in ("outro", "ending", "片尾", "结尾")):
            raise ValueError(f"{seg_id} appears to plan the fixed outro inside script/visual beats")

        operation_status = str(item.get("operation_status") or beat.get("operation_status") or "").strip()
        if operation_status and operation_status not in ALLOWED_OPERATION_STATUS:
            raise ValueError(f"{seg_id} unsupported operation_status: {operation_status}")
        evidence_binding = str(item.get("evidence_binding") or beat.get("evidence_binding") or "").strip()
        if evidence_binding and evidence_binding not in ALLOWED_EVIDENCE_BINDINGS:
            raise ValueError(f"{seg_id} unsupported evidence_binding: {evidence_binding}")
        if operation_status in {"verified_entry_only", "blocked_login", "blocked_permission"} and evidence_binding == "real_result":
            raise ValueError(f"{seg_id} cannot bind to real_result when operation_status is {operation_status}")
        if evidence_binding == "packaging_only" and any(token in text for token in ("生成结果", "效果图", "出图", "成品")):
            raise ValueError(f"{seg_id} uses packaging_only but contains product-result language")

        normalized.append(
            {
                "id": seg_id,
                "visual_beat_id": visual_beat_id,
                "stage": stage,
                "text": text,
                "feature_id": feature_id,
                "visual_intent": visual_intent,
                "material_task": material_task,
                "evidence_binding": evidence_binding,
                "operation_status": operation_status,
                "preferred_asset_ids": preferred,
                "locked_asset_ids": locked,
                "layout_intent": layout_intent,
                "focus_region": focus_region,
                "camera_note": camera_note,
                "allowed_claims": allowed_claims,
                "forbidden_claims": forbidden_claims,
                "keywords": [str(v) for v in ensure_list(item.get("keywords"), f"segments[{idx}].keywords")],
                "duration_hint": round(duration, 3),
                "allow_rewrite": bool(item.get("allow_rewrite", True)),
            }
        )

    all_text = "".join(seg["text"] for seg in normalized)
    high_risk = [str(v) for v in ensure_list(payload.get("high_risk_terms"), "video_script.high_risk_terms")]
    for term in ("柯幻熊猫", "AI"):
        if term in all_text and term not in high_risk:
            high_risk.append(term)

    return {
        "schema_version": 1,
        "status": "reviewed",
        "voice_style": str(payload.get("voice_style") or "快节奏、清晰、种草"),
        "high_risk_terms": high_risk,
        "segments": normalized,
    }, warnings


def should_refuse_overwrite(path: Path, force: bool) -> bool:
    if force or not path.is_file():
        return False
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return existing.get("status") in {"reviewed", "vision_reviewed"}


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")
    payload = load_json(Path(args.input).expanduser().resolve(strict=False))

    if args.kind == "material":
        normalized, warnings = normalize_material(payload, case_dir)
        output_path = case_dir / "material_understanding.json"
    elif args.kind == "visual_plan":
        normalized, warnings = normalize_visual_plan(payload, case_dir)
        output_path = case_dir / "visual_plan.json"
    elif args.kind == "script":
        normalized, warnings = normalize_script(payload, case_dir)
        output_path = case_dir / "video_script.json"
    else:
        raise ValueError(f"unsupported kind: {args.kind}")

    if should_refuse_overwrite(output_path, args.force):
        raise FileExistsError(f"{output_path.name} is already reviewed; use --force to overwrite")

    output_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "kind": args.kind,
            "output": str(output_path),
            "status": normalized.get("status"),
            "warnings": warnings,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate and accept AI planner output into case artifacts.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--kind", choices=("material", "visual_plan", "script"), required=True)
    parser.add_argument("--input", required=True, help="Planner JSON output to validate and accept.")
    parser.add_argument("--force", action="store_true", help="Overwrite reviewed outputs.")
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
        print(f"Accepted {output['data']['kind']}: {output['data']['output']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
