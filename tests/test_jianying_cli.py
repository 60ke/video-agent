from __future__ import annotations

from video_agent.cli import build_parser


def test_generate_video_accepts_jianying_backend() -> None:
    args = build_parser().parse_args(
        [
            "generate_video",
            "--script",
            "copy.txt",
            "--editor-backend",
            "jianying",
            "--jianying-skill-root",
            "C:/skill",
        ]
    )
    assert args.editor_backend == "jianying"
    assert args.jianying_skill_root == "C:/skill"


def test_stage6_defaults_to_remotion_backend() -> None:
    args = build_parser().parse_args(
        [
            "v4-stage6",
            "--case",
            "cases/demo",
            "--resume",
            "run_001",
        ]
    )
    assert args.editor_backend == "remotion"
