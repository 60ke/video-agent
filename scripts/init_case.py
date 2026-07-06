from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.skill_path import default_outro_path, default_voice_prompt_path, require_skill_root


OUTPUT_DIRS = (
    "assets",
    "assets/browser",
    "assets/browser/raw",
    "assets/browser/annotated",
    "assets/results",
    "audio",
    "hyperframes",
    "output",
    "output/versions",
    "output/qa",
    "output/reports",
)

PLACEHOLDER_JSON = {
    "website_knowledge.json": {
        "schema_version": 1,
        "status": "pending",
        "pages": [],
        "notes": [],
    },
    "feature_cards.json": {
        "schema_version": 1,
        "status": "pending",
        "features": [],
    },
    "operation_recipes.json": {
        "schema_version": 1,
        "status": "pending",
        "recipes": [],
    },
    "browser_materials.json": {
        "schema_version": 1,
        "status": "pending",
        "materials": [],
    },
    "image_resources.json": {
        "schema_version": 1,
        "status": "pending",
        "naming_policy": "kx_<feature>_<step>_<seq>_<variant>.png",
        "resources": [],
    },
    "generation_receipts.json": {
        "schema_version": 1,
        "status": "pending",
        "receipts": [],
    },
    "asset_manifest.json": {
        "schema_version": 1,
        "status": "pending",
        "assets": [],
    },
    "material_understanding.json": {
        "schema_version": 1,
        "status": "pending",
        "materials": [],
    },
    "video_script.json": {
        "schema_version": 1,
        "status": "pending",
        "segments": [],
    },
    "video_project.json": {
        "schema_version": 1,
        "status": "pending",
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _write_json(path: Path, payload: dict[str, Any], *, force: bool, touched: list[str], skipped: list[str]) -> None:
    if path.exists() and not force:
        skipped.append(str(path))
        return
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    touched.append(str(path))


def _copy_file(src: Path, dst: Path, *, force: bool, touched: list[str], skipped: list[str]) -> None:
    if dst.exists() and not force:
        skipped.append(str(dst))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    touched.append(str(dst))


def _convert_prompt_to_wav(
    src: Path,
    dst: Path,
    *,
    force: bool,
    touched: list[str],
    skipped: list[str],
) -> None:
    if dst.exists() and not force:
        skipped.append(str(dst))
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(src),
        "-t",
        "5",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(dst),
    ]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed to convert voice prompt: {proc.stderr.strip()}")
    touched.append(str(dst))


def _build_input(args: argparse.Namespace, skill_root: Path, voice_prompt: str | None) -> dict[str, Any]:
    ending_policy = args.ending_policy
    ending_track: dict[str, Any]
    if ending_policy == "default":
        outro = default_outro_path(skill_root)
        ending_track = {
            "id": "default_panda_outro",
            "type": "video",
            "policy": "default",
            "source": str(outro),
            "start_policy": "after_main_video",
            "participates_in_script": False,
            "participates_in_subtitles": False,
            "preserve_audio": True,
        }
    elif ending_policy == "custom":
        if not args.ending_video:
            raise ValueError("--ending-video is required when --ending-policy custom")
        ending_track = {
            "id": "custom_outro",
            "type": "video",
            "policy": "custom",
            "source": str(Path(args.ending_video).resolve(strict=False)),
            "start_policy": "after_main_video",
            "participates_in_script": False,
            "participates_in_subtitles": False,
            "preserve_audio": True,
        }
    else:
        ending_track = {"policy": "none"}

    return {
        "schema_version": 1,
        "created_at": _now_iso(),
        "case": {
            "case_dir": str(Path(args.case).resolve(strict=False)),
            "materials_dir": "assets/static" if args.materials else None,
            "materials_source_policy": "freeze_into_case" if args.materials else None,
            "static_materials_explicit": bool(args.materials),
            "frontend_dir": str(Path(args.frontend).resolve(strict=False)) if args.frontend else None,
        },
        "request": {
            "target_url": args.target_url,
            "video_goal": args.video_goal,
            "duration": args.duration,
            "brand_profile": args.brand_profile,
            "target_platform": args.target_platform,
            "preferred_features": args.preferred_feature,
        },
        "dependency_mode": {
            "browser": "kimi_webbridge",
            "renderer": "hyperframes",
            "asr": "funasr",
            "tts": args.tts_engine,
        },
        "voice_config": {
            "mode": "voice_clone" if args.voice_policy in ("default", "custom") else "plain_tts",
            "engine": args.tts_engine,
            "prompt_audio_policy": args.voice_policy,
            "case_prompt_audio": voice_prompt,
        },
        "ending_track": ending_track,
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def run(args: argparse.Namespace) -> dict[str, Any]:
    skill_root = require_skill_root(Path(__file__).resolve())
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    touched: list[str] = []
    skipped: list[str] = []
    warnings: list[str] = []

    if not _is_relative_to(case_dir, skill_root):
        raise ValueError(f"case directory must be inside skill project: {case_dir}")

    case_dir.mkdir(parents=True, exist_ok=True)
    for rel in OUTPUT_DIRS:
        path = case_dir / rel
        path.mkdir(parents=True, exist_ok=True)
        touched.append(str(path))

    if args.materials and not Path(args.materials).expanduser().exists():
        warnings.append(f"materials path does not exist yet: {args.materials}")
    if args.frontend and not Path(args.frontend).expanduser().exists():
        warnings.append(f"frontend path does not exist yet: {args.frontend}")

    voice_prompt_path: Path | None = None
    if args.voice_policy == "default":
        voice_prompt_path = case_dir / "audio" / "voice_prompt_5s.wav"
        _copy_file(
            default_voice_prompt_path(skill_root),
            voice_prompt_path,
            force=args.force,
            touched=touched,
            skipped=skipped,
        )
    elif args.voice_policy == "custom":
        if not args.voice_prompt:
            raise ValueError("--voice-prompt is required when --voice-policy custom")
        src = Path(args.voice_prompt).expanduser().resolve(strict=False)
        if not src.is_file():
            raise FileNotFoundError(f"custom voice prompt not found: {src}")
        voice_prompt_path = case_dir / "audio" / "voice_prompt_5s.wav"
        if src.suffix.lower() == ".wav":
            _copy_file(src, voice_prompt_path, force=args.force, touched=touched, skipped=skipped)
        else:
            _convert_prompt_to_wav(src, voice_prompt_path, force=args.force, touched=touched, skipped=skipped)
    elif args.voice_policy == "none":
        voice_prompt_path = None
    else:
        raise ValueError(f"unsupported voice policy: {args.voice_policy}")

    input_payload = _build_input(
        args,
        skill_root,
        str(voice_prompt_path.relative_to(case_dir)) if voice_prompt_path else None,
    )
    _write_json(case_dir / "input.json", input_payload, force=args.force, touched=touched, skipped=skipped)

    for filename, payload in PLACEHOLDER_JSON.items():
        _write_json(case_dir / filename, payload, force=False, touched=touched, skipped=skipped)

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "skill_root": str(skill_root),
            "case_dir": str(case_dir),
            "voice_policy": args.voice_policy,
            "voice_prompt": str(voice_prompt_path) if voice_prompt_path else None,
            "ending_policy": args.ending_policy,
            "touched": touched,
            "skipped": skipped,
            "warnings": warnings,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Initialize a video-agent case directory.")
    parser.add_argument("--case", required=True, help="Case directory to create or update.")
    parser.add_argument("--materials", help="Optional user material folder.")
    parser.add_argument("--frontend", help="Optional frontend project folder.")
    parser.add_argument("--target-url", help="Optional target website URL.")
    parser.add_argument("--video-goal", default="功能种草")
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--brand-profile", default="柯幻熊猫")
    parser.add_argument("--target-platform", default="douyin")
    parser.add_argument("--preferred-feature", action="append", default=[])
    parser.add_argument("--tts-engine", default="voice_clone_api")
    parser.add_argument("--voice-policy", choices=("default", "custom", "none"), default="default")
    parser.add_argument("--voice-prompt", help="Custom prompt audio path for --voice-policy custom.")
    parser.add_argument("--ending-policy", choices=("default", "custom", "none"), default="default")
    parser.add_argument("--ending-video", help="Custom ending video path for --ending-policy custom.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing scaffold files.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except Exception as exc:  # noqa: BLE001 - CLI must return structured errors.
        result = {
            "ok": False,
            "code": exc.__class__.__name__,
            "reason": str(exc),
            "data": {},
        }
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print(f"ERROR: {result['reason']}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Initialized case: {result['data']['case_dir']}")
        if result["data"]["warnings"]:
            for warning in result["data"]["warnings"]:
                print(f"WARNING: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
