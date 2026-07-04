from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import subprocess
import sys
from pathlib import Path
from typing import Any


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ffprobe_json(path: Path) -> dict[str, Any]:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
    ]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return {"ok": False, "error": proc.stderr.strip()}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return {"ok": False, "error": str(exc)}
    data["ok"] = True
    return data


def media_type(path: Path) -> str | None:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return "image"
    if suffix in VIDEO_SUFFIXES:
        return "video"
    if suffix in AUDIO_SUFFIXES:
        return "audio"
    return None


def metadata_from_probe(path: Path, kind: str) -> dict[str, Any]:
    data = ffprobe_json(path)
    if not data.get("ok"):
        return {"probe_ok": False, "probe_error": data.get("error")}

    streams = data.get("streams", [])
    fmt = data.get("format", {})
    payload: dict[str, Any] = {
        "probe_ok": True,
        "duration": float(fmt["duration"]) if fmt.get("duration") else None,
        "bit_rate": int(fmt["bit_rate"]) if fmt.get("bit_rate") and str(fmt["bit_rate"]).isdigit() else None,
    }

    if kind in ("image", "video"):
        stream = next((s for s in streams if s.get("codec_type") == "video"), streams[0] if streams else {})
        width = stream.get("width")
        height = stream.get("height")
        payload.update(
            {
                "width": width,
                "height": height,
                "aspect_ratio": round(width / height, 6) if width and height else None,
                "video_codec": stream.get("codec_name"),
                "fps": stream.get("avg_frame_rate"),
            }
        )

    if kind == "audio":
        stream = next((s for s in streams if s.get("codec_type") == "audio"), streams[0] if streams else {})
        payload.update(
            {
                "audio_codec": stream.get("codec_name"),
                "sample_rate": int(stream["sample_rate"]) if stream.get("sample_rate") else None,
                "channels": stream.get("channels"),
            }
        )

    return payload


def collect_assets(materials_dir: Path, recursive: bool) -> list[dict[str, Any]]:
    pattern = "**/*" if recursive else "*"
    assets: list[dict[str, Any]] = []
    for path in sorted(materials_dir.glob(pattern), key=lambda p: str(p).lower()):
        if not path.is_file():
            continue
        kind = media_type(path)
        if not kind:
            continue
        rel = path.relative_to(materials_dir)
        asset_id = f"asset_{len(assets) + 1:03d}"
        mime, _ = mimetypes.guess_type(str(path))
        metadata = metadata_from_probe(path, kind)
        assets.append(
            {
                "id": asset_id,
                "type": kind,
                "source": str(path.resolve(strict=False)),
                "relative_source": str(rel),
                "filename": path.name,
                "mime_type": mime,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "origin": "static_material_folder",
                "role": "unclassified",
                "description": "",
                "visible_text": [],
                "supported_claims": [],
                "quality": {
                    "readable": None,
                    "contains_private_info": None,
                    "needs_review": True,
                },
                "metadata": metadata,
            }
        )
    return assets


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    materials_dir = Path(args.materials).expanduser().resolve(strict=False)

    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")
    if not materials_dir.is_dir():
        raise FileNotFoundError(f"materials directory not found: {materials_dir}")

    assets = collect_assets(materials_dir, args.recursive)
    output_path = case_dir / "asset_manifest.json"
    payload = {
        "schema_version": 1,
        "status": "registered",
        "materials_dir": str(materials_dir),
        "asset_count": len(assets),
        "assets": assets,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    understanding_path = case_dir / "material_understanding.json"
    should_write_understanding = args.force or not understanding_path.exists()
    if understanding_path.exists() and not should_write_understanding:
        try:
            existing = json.loads(understanding_path.read_text(encoding="utf-8"))
            should_write_understanding = existing.get("status") == "pending"
        except json.JSONDecodeError:
            should_write_understanding = True

    if should_write_understanding:
        understanding_payload = {
            "schema_version": 1,
            "status": "needs_vision_review",
            "materials": [
                {
                    "asset_id": asset["id"],
                    "filename": asset["filename"],
                    "type": asset["type"],
                    "vision_summary": "",
                    "page_or_scene_role": "",
                    "recommended_usage": "",
                    "needs_review": True,
                }
                for asset in assets
            ],
        }
        understanding_path.write_text(
            json.dumps(understanding_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "materials_dir": str(materials_dir),
            "asset_manifest": str(output_path),
            "material_understanding": str(understanding_path),
            "asset_count": len(assets),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register static material files into a video-agent case.")
    parser.add_argument("--case", required=True, help="Case directory created by init_case.py.")
    parser.add_argument("--materials", required=True, help="Material folder to scan.")
    parser.add_argument("--recursive", action="store_true", help="Scan material folder recursively.")
    parser.add_argument("--force", action="store_true", help="Overwrite material_understanding.json placeholder.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001 - CLI must report structured failure.
        output = {
            "ok": False,
            "code": exc.__class__.__name__,
            "reason": str(exc),
            "data": {},
        }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print(f"Registered {output['data']['asset_count']} assets")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
