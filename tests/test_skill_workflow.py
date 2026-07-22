from pathlib import Path

from agent_test.project import SCRIPT_END, SCRIPT_START, create_project, read_locked_script
from agent_test.storyboard import align_storyboard, validate_storyboard


def test_create_project_and_read_locked_script(tmp_path: Path) -> None:
    files = create_project(tmp_path / "demo", title="Demo", script="打开网站。看结果。")
    assert files.config.is_file()
    assert read_locked_script(files.script) == "打开网站。看结果。"
    assert SCRIPT_START in files.script.read_text(encoding="utf-8")
    assert SCRIPT_END in files.script.read_text(encoding="utf-8")


def test_storyboard_aligns_beats_and_visual_windows_to_word_timing() -> None:
    script = "打开网站，输入需求。看，效果已经出来了。"
    storyboard = {
        "arc": "demo_loop",
        "video_direction": {"reveal_model": "voice-paced"},
        "beats": [
            {
                "beat_id": "beat_01",
                "role": "feature_showcase",
                "voiceover": "打开网站，输入需求。",
                "scene_kind": "website_operation",
                "recipe_id": "demo",
                "asset_paths": [],
                "visual_windows": [
                    {"cue": "打开网站", "label": "打开网站", "motion": "screen_push"},
                    {"cue": "输入需求", "label": "输入需求", "motion": "cursor_fill"},
                ],
            },
            {
                "beat_id": "beat_02",
                "role": "benefit_highlight",
                "voiceover": "看，效果已经出来了。",
                "scene_kind": "result_detail",
                "asset_paths": ["assets/result.png"],
                "visual_windows": [{"cue": "效果已经出来了", "label": "生成结果", "motion": "hero_reveal"}],
            },
        ],
    }
    errors = validate_storyboard(storyboard, script=script, recipes={"demo": {}}, result_assets=["assets/result.png"])
    assert errors == []
    tokens = [
        {"text": "打开", "start_ms": 0, "end_ms": 300},
        {"text": "网站，", "start_ms": 320, "end_ms": 700},
        {"text": "输入", "start_ms": 740, "end_ms": 1000},
        {"text": "需求。", "start_ms": 1020, "end_ms": 1400},
        {"text": "看，", "start_ms": 1500, "end_ms": 1750},
        {"text": "效果", "start_ms": 1780, "end_ms": 2050},
        {"text": "已经", "start_ms": 2080, "end_ms": 2300},
        {"text": "出来了。", "start_ms": 2320, "end_ms": 2800},
    ]
    scenes = align_storyboard(storyboard, tokens, fps=30)
    assert scenes[0]["start_frame"] == 0
    assert scenes[0]["end_frame"] == 42
    assert scenes[0]["windows"][1]["start_ms"] == 740
    assert scenes[1]["start_ms"] == 1500
    assert scenes[1]["windows"][0]["start_ms"] == 1780


def test_storyboard_rejects_unregistered_recipe_and_assets() -> None:
    storyboard = {
        "arc": "demo_loop",
        "beats": [
            {
                "beat_id": "beat_01",
                "role": "feature_showcase",
                "voiceover": "点击生成。",
                "scene_kind": "website_operation",
                "recipe_id": "invented",
                "asset_paths": ["missing.png"],
            }
        ],
    }
    errors = validate_storyboard(storyboard, script="点击生成。", recipes={}, result_assets=[])
    assert any("existing recipe_id" in error for error in errors)
    assert any("unregistered assets" in error for error in errors)
