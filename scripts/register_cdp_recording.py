from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("_")
    return value or "recording"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def case_relative(case_dir: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(case_dir.resolve(strict=False)).as_posix()
    except ValueError as exc:
        raise ValueError(f"recording material must be copied inside case directory: {path}") from exc


def ffprobe_metadata(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return {"probe_ok": False, "probe_error": proc.stderr.strip()}
    data = json.loads(proc.stdout)
    stream = next((item for item in data.get("streams", []) if item.get("codec_type") == "video"), {})
    fmt = data.get("format", {})
    width = stream.get("width")
    height = stream.get("height")
    return {
        "probe_ok": True,
        "width": width,
        "height": height,
        "aspect_ratio": round(width / height, 6) if width and height else None,
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "fps": stream.get("avg_frame_rate"),
        "video_codec": stream.get("codec_name"),
        "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") and str(fmt["bit_rate"]).isdigit() else None,
    }


def copy_if_exists(src: Path, dst: Path) -> str | None:
    if not src.is_file():
        return None
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve(strict=False) != dst.resolve(strict=False):
        shutil.copy2(src, dst)
    return dst.name


def copy_tree_files(src_dir: Path, dst_dir: Path, suffixes: set[str] | None = None) -> list[Path]:
    if not src_dir.is_dir():
        return []
    copied: list[Path] = []
    for src in sorted(src_dir.rglob("*")):
        if not src.is_file():
            continue
        if suffixes and src.suffix.lower() not in suffixes:
            continue
        rel = src.relative_to(src_dir)
        dst = dst_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst)
    return copied


def upsert_by_id(items: list[dict[str, Any]], item: dict[str, Any]) -> None:
    for idx, existing in enumerate(items):
        if isinstance(existing, dict) and existing.get("id") == item.get("id"):
            items[idx] = item
            return
    items.append(item)


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    recording_dir = Path(args.recording_dir).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")
    if not recording_dir.is_dir():
        raise FileNotFoundError(f"cdp recording output directory not found: {recording_dir}")

    src_video = recording_dir / "video.mp4"
    if not src_video.is_file():
        raise FileNotFoundError(f"cdp recording video missing: {src_video}")

    label = slugify(args.label or recording_dir.name)
    asset_id = args.asset_id or f"asset_{label}_recording"
    frozen_dir = case_dir / "assets" / "recordings" / label
    frozen_video = frozen_dir / "video.mp4"
    frozen_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_video, frozen_video)

    companion_files: dict[str, str] = {}
    for name in ("task.json", "timeline.json", "metadata.json", "verify.json", "recording_narration_track.json", "recording_camera_track.json"):
        copied = copy_if_exists(recording_dir / name, frozen_dir / name)
        if copied:
            key = Path(name).stem
            companion_files[key] = case_relative(case_dir, frozen_dir / copied)
    copied_result_files = copy_tree_files(recording_dir / "results", frozen_dir / "results", IMAGE_SUFFIXES)
    if copied_result_files:
        companion_files["results_dir"] = case_relative(case_dir, frozen_dir / "results")

    cdp_metadata = load_json(frozen_dir / "metadata.json", {})
    narration_track = load_json(frozen_dir / "recording_narration_track.json", {"segments": []})
    camera_track = load_json(frozen_dir / "recording_camera_track.json", {"segments": []})
    if args.ends_after_generation_trigger:
        if (
            not isinstance(cdp_metadata, dict)
            or cdp_metadata.get("postRecordingActionsExecuted") is not True
            or cdp_metadata.get("postRecordingResultCaptured") is not True
        ):
            raise ValueError(
                "recording marked as ending after generation trigger, but metadata does not prove "
                "that post-recording actions continued to capture the real result. Use stopRecordingAfter "
                "on the real generate click and keep a required capture_element resultAsset=true action after it."
            )
        if not copied_result_files:
            raise ValueError("post-recording result capture was reported, but no result images exist in recording output/results")
    probe = ffprobe_metadata(frozen_video)
    metadata = dict(probe)
    if isinstance(cdp_metadata, dict):
        metadata.update(
            {
                "cdp_resolution": cdp_metadata.get("resolution"),
                "cdp_fps": cdp_metadata.get("fps"),
                "cdp_duration_seconds": cdp_metadata.get("durationSeconds"),
                "profile_id": cdp_metadata.get("profileId"),
                "auth_state_restored": cdp_metadata.get("authStateRestored"),
                "overlay_enabled": cdp_metadata.get("overlayEnabled"),
            }
        )

    mime, _ = mimetypes.guess_type(str(frozen_video))
    asset = {
        "id": asset_id,
        "type": "video",
        "source": case_relative(case_dir, frozen_video),
        "relative_source": f"recordings/{label}/video.mp4",
        "filename": frozen_video.name,
        "mime_type": mime or "video/mp4",
        "size_bytes": frozen_video.stat().st_size,
        "sha256": sha256_file(frozen_video),
        "origin": "cdp_browser_recording",
        "source_policy": "frozen_into_case",
        "role": "operation_recording",
        "description": args.description or "CDP browser operation recording for the feature entry and generation trigger.",
        "visible_text": [],
        "supported_claims": ["real_recording", "operation_path"],
        "metadata": metadata,
        "display_risk": [],
        "layout_plan": {
            "primary_display_mode": "browser-recording-fit-width",
            "fill_strategy": "fit_width_center_vertical",
            "preserve_entire_recording": True,
            "allow_detail_crop": False,
        },
        "recording": {
            "profile_id": metadata.get("profile_id") or "kehuanxiongmao",
            "companion_files": companion_files,
            "narration_segment_count": len(narration_track.get("segments", [])) if isinstance(narration_track, dict) else 0,
            "camera_segment_count": len(camera_track.get("segments", [])) if isinstance(camera_track, dict) else 0,
            "ends_after_generation_trigger": bool(args.ends_after_generation_trigger),
            "post_recording_actions_executed": bool(
                isinstance(cdp_metadata, dict) and cdp_metadata.get("postRecordingActionsExecuted") is True
            ),
            "post_recording_result_captured": bool(
                isinstance(cdp_metadata, dict) and cdp_metadata.get("postRecordingResultCaptured") is True
            ),
        },
        "quality": {
            "readable": None,
            "contains_private_info": None,
            "needs_review": True,
        },
    }

    manifest_path = case_dir / "asset_manifest.json"
    manifest = load_json(manifest_path, {"schema_version": 1, "status": "registered", "assets": []})
    if not isinstance(manifest.get("assets"), list):
        manifest["assets"] = []
    manifest["status"] = "registered"
    upsert_by_id(manifest["assets"], asset)

    result_assets: list[dict[str, Any]] = []
    case_result_dir = case_dir / "assets" / "results" / label
    copied_case_results: list[Path] = []
    for idx, frozen_result in enumerate(copied_result_files, start=1):
        case_result = case_result_dir / frozen_result.name
        case_result.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(frozen_result, case_result)
        result_asset_id = f"{asset_id}_result_{idx:03d}"
        result_asset = {
            "id": result_asset_id,
            "type": "image",
            "source": case_relative(case_dir, case_result),
            "relative_source": f"results/{label}/{case_result.name}",
            "filename": case_result.name,
            "mime_type": mimetypes.guess_type(str(case_result))[0] or "image/png",
            "size_bytes": case_result.stat().st_size,
            "sha256": sha256_file(case_result),
            "origin": "cdp_result_capture",
            "source_policy": "frozen_into_case",
            "role": "generated_result",
            "description": "Real generated result captured after the CDP recording boundary in the same browser task.",
            "visible_text": [],
            "supported_claims": ["real_generated_result"],
            "metadata": ffprobe_metadata(case_result),
            "display_risk": [],
            "layout_plan": {
                "primary_display_mode": "result-showcase",
                "fill_strategy": "fit_full_result",
                "preserve_entire_result": True,
                "allow_detail_crop": False,
            },
            "quality": {
                "readable": None,
                "contains_private_info": None,
                "needs_review": True,
            },
            "source_recording_asset_id": asset_id,
        }
        upsert_by_id(manifest["assets"], result_asset)
        result_assets.append(result_asset)
        copied_case_results.append(case_result)
    manifest["asset_count"] = len(manifest["assets"])
    write_json(manifest_path, manifest)

    browser_path = case_dir / "browser_materials.json"
    browser_materials = load_json(browser_path, {"schema_version": 1, "status": "registered", "materials": []})
    if not isinstance(browser_materials.get("materials"), list):
        browser_materials["materials"] = []
    browser_materials["status"] = "registered"
    upsert_by_id(
        browser_materials["materials"],
        {
            "id": f"{asset_id}_material",
            "asset_id": asset_id,
            "type": "recording",
            "workflow_step": "operation_recording",
            "source": asset["source"],
            "profile_id": asset["recording"]["profile_id"],
            "description": asset["description"],
            "companion_files": companion_files,
        },
    )
    write_json(browser_path, browser_materials)

    if result_assets:
        image_resources_path = case_dir / "image_resources.json"
        image_resources = load_json(image_resources_path, {"schema_version": 1, "status": "ready", "resources": []})
        if not isinstance(image_resources.get("resources"), list):
            image_resources["resources"] = []
        image_resources["status"] = "ready"
        for idx, result_asset in enumerate(result_assets, start=1):
            upsert_by_id(
                image_resources["resources"],
                {
                    "id": f"img_{label}_result_{idx:03d}",
                    "asset_id": result_asset["id"],
                    "filename": result_asset["filename"],
                    "source": result_asset["source"],
                    "type": "image",
                    "feature_id": args.feature_id or label,
                    "workflow_step": "result_crop",
                    "variant": "result",
                    "origin": "cdp_result_capture",
                    "capture_method": "cdp_result_crop",
                    "page_url": "",
                    "title": "真实生成结果",
                    "description": result_asset["description"],
                    "visible_text": [],
                    "prompt_inputs": {},
                    "callouts": [],
                    "relations": {
                        "source_recording_asset_id": asset_id,
                        "result_group_id": f"{label}_generation",
                    },
                    "supported_claims": ["同一次 CDP 真实生成链路获得的结果图"],
                    "recommended_usage": ["result_showcase", "hook_visual", "gallery"],
                    "quality": result_asset["quality"],
                    "layout_plan": result_asset["layout_plan"],
                },
            )
        write_json(image_resources_path, image_resources)

        receipts_path = case_dir / "generation_receipts.json"
        receipts_payload = load_json(receipts_path, {"schema_version": 1, "status": "ready", "receipts": []})
        if not isinstance(receipts_payload.get("receipts"), list):
            receipts_payload["receipts"] = []
        receipts_payload["status"] = "ready"
        upsert_by_id(
            receipts_payload["receipts"],
            {
                "id": f"receipt_{label}",
                "status": "verified_result",
                "source": "cdp_capture",
                "recording_asset_id": asset_id,
                "recording_boundary": cdp_metadata.get("recordingStop") if isinstance(cdp_metadata, dict) else {},
                "post_recording_result_actions": cdp_metadata.get("postRecordingResultActions", []) if isinstance(cdp_metadata, dict) else [],
                "result_asset_ids": [item["id"] for item in result_assets],
                "result_sources": [item["source"] for item in result_assets],
                "notes": "Recording stops at the generate click; real result capture continues in the same CDP task.",
            },
        )
        write_json(receipts_path, receipts_payload)

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "asset_id": asset_id,
            "recording_dir": str(frozen_dir),
            "video": str(frozen_video),
            "asset_manifest": str(manifest_path),
            "browser_materials": str(browser_path),
            "narration_segments": asset["recording"]["narration_segment_count"],
            "camera_segments": asset["recording"]["camera_segment_count"],
            "result_asset_count": len(result_assets),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register a cdp-capture output directory as a case recording asset.")
    parser.add_argument("--case", required=True, help="Case directory created by init_case.py.")
    parser.add_argument("--recording-dir", required=True, help="cdp-capture output task directory containing video.mp4.")
    parser.add_argument("--label", help="Stable recording label, e.g. kx_vi_entry_recording.")
    parser.add_argument("--asset-id", help="Asset id to write into asset_manifest.json.")
    parser.add_argument("--description", help="Human-readable recording description.")
    parser.add_argument("--feature-id", help="Feature id for generated image_resources entries.")
    parser.add_argument("--ends-after-generation-trigger", action="store_true")
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
        print(f"Registered CDP recording: {output['data']['asset_id']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
