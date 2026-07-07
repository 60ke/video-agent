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
    for name in ("task.json", "timeline.json", "metadata.json", "verify.json", "recording_narration_track.json"):
        copied = copy_if_exists(recording_dir / name, frozen_dir / name)
        if copied:
            key = Path(name).stem
            companion_files[key] = case_relative(case_dir, frozen_dir / copied)

    cdp_metadata = load_json(frozen_dir / "metadata.json", {})
    narration_track = load_json(frozen_dir / "recording_narration_track.json", {"segments": []})
    if args.ends_after_generation_trigger:
        if not isinstance(cdp_metadata, dict) or cdp_metadata.get("postRecordingActionsExecuted") is not True:
            raise ValueError(
                "recording marked as ending after generation trigger, but metadata does not prove "
                "that post-recording actions continued to capture the real result. Use stopRecordingAfter "
                "on the real generate click and keep wait/result capture actions after it."
            )
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
            "ends_after_generation_trigger": bool(args.ends_after_generation_trigger),
            "post_recording_actions_executed": bool(
                isinstance(cdp_metadata, dict) and cdp_metadata.get("postRecordingActionsExecuted") is True
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
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register a cdp-capture output directory as a case recording asset.")
    parser.add_argument("--case", required=True, help="Case directory created by init_case.py.")
    parser.add_argument("--recording-dir", required=True, help="cdp-capture output task directory containing video.mp4.")
    parser.add_argument("--label", help="Stable recording label, e.g. kx_vi_entry_recording.")
    parser.add_argument("--asset-id", help="Asset id to write into asset_manifest.json.")
    parser.add_argument("--description", help="Human-readable recording description.")
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
