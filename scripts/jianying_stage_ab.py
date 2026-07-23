"""Build a Jianying draft from an existing V4 resolved timeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from video_agent.editors.jianying import (
    JianyingDraftAdapter,
    compile_jianying_blueprint,
)
from video_agent.editors.jianying.adapter import write_manifest


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=Path(r"C:\Users\CNGG\Desktop\jianying-editor-skill"),
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
    blueprint, blueprint_path = compile_jianying_blueprint(
        resolved_timeline,
        output_dir,
    )
    project_name = (
        args.project_name
        or f"video-agent_{blueprint.case_id}_{blueprint.run_id}"
    )
    adapter = JianyingDraftAdapter(
        skill_root=args.skill_root,
        drafts_root=args.drafts_root,
    )
    manifest = adapter.build(
        blueprint,
        blueprint_root=output_dir,
        project_name=project_name,
        motion_backend=args.motion_backend,
    )
    manifest["edit_blueprint_path"] = blueprint_path.as_posix()
    manifest_path = write_manifest(
        manifest,
        output_dir / "jianying_project_manifest.json",
    )
    print(
        json.dumps(
            {
                "ok": True,
                "blueprint": blueprint_path.as_posix(),
                "manifest": manifest_path.as_posix(),
                "draft": manifest["draft_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
