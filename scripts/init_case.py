from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.skill_path import default_outro_path, require_skill_root


OUTPUT_DIRS = (
    "assets",
    "assets/browser",
    "assets/browser/raw",
    "assets/browser/annotated",
    "assets/results",
    "audio",
    "output",
    "output/minimax",
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
        "auth_state": {
            "logged_in": None,
            "points_balance": None,
            "evidence_asset_id": None,
        },
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


def _build_input(args: argparse.Namespace, skill_root: Path) -> dict[str, Any]:
    ending_policy = args.ending_policy
    ending_track: dict[str, Any]
    if ending_policy == "default":
        outro = default_outro_path(skill_root)
        if not outro.is_file():
            raise FileNotFoundError(f"default ending video missing: {outro}")
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
        ending_video = Path(args.ending_video).resolve(strict=False)
        if not ending_video.is_file():
            raise FileNotFoundError(f"custom ending video missing: {ending_video}")
        ending_track = {
            "id": "custom_outro",
            "type": "video",
            "policy": "custom",
            "source": str(ending_video),
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
            "renderer": "simple_ffmpeg",
            "alignment": "minimax_t2a",
            "tts": "minimax_t2a",
        },
        "voice_config": {
            "mode": "tts",
            "engine": "minimax_t2a",
            "local_config": "config/minimax.local.json",
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

    input_payload = _build_input(args, skill_root)
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
            "voice_engine": "minimax_t2a",
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
