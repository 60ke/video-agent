"""Build a Jianying draft from an existing V4 resolved timeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_agent.editors.jianying import (
    JianyingEditorBackend,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--skill-root",
        type=Path,
        help="Defaults to JY_SKILL_ROOT or an auto-discovered local Skill checkout.",
    )
    parser.add_argument("--project-name")
    parser.add_argument("--drafts-root", type=Path)
    parser.add_argument(
        "--output-subdir",
        default="jianying",
        help="Run-relative folder for blueprint media and manifest.",
    )
    parser.add_argument(
        "--motion-backend",
        choices=("keyframes", "jianying_native"),
        default="keyframes",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    run_dir = args.run_dir.resolve()
    resolved_timeline = run_dir / "render" / "compiled_timeline.resolved.json"
    if not resolved_timeline.is_file():
        raise FileNotFoundError(
            "resolved timeline missing; run V4 Stage6 compile-render with --skip-ffmpeg first: "
            f"{resolved_timeline}"
        )

    output_dir = run_dir / args.output_subdir
    backend = JianyingEditorBackend(
        repo_root=Path(__file__).resolve().parents[1],
        skill_root=args.skill_root,
        drafts_root=args.drafts_root,
        motion_backend=args.motion_backend,
    )
    result = backend.build_from_timeline(
        resolved_timeline_path=resolved_timeline,
        output_dir=output_dir,
        project_name=args.project_name,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "blueprint": result.blueprint_path.as_posix(),
                "manifest": result.manifest_path.as_posix(),
                "draft": result.draft_path.as_posix(),
                "skill_version": result.skill_version,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
