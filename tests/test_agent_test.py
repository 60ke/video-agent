from agent_test.planner import PlannerConfig, ScenePlanner
from agent_test.subtitles import build_subtitle_cues


def test_word_tokens_compile_to_timed_subtitle_cues() -> None:
    tokens = [
        {"text": "打开", "start_ms": 0, "end_ms": 300},
        {"text": "网站，", "start_ms": 320, "end_ms": 700},
        {"text": "点击", "start_ms": 760, "end_ms": 1050},
        {"text": "生成。", "start_ms": 1070, "end_ms": 1500},
    ]
    cues = build_subtitle_cues(tokens, fps=30, max_chars=8)

    assert [cue["text"] for cue in cues] == ["打开网站，点击生成。"]
    assert cues[0]["start_frame"] == 0
    assert cues[0]["end_frame"] == 45


def test_deterministic_planner_uses_existing_recipe_for_website_scene() -> None:
    cues = [
        {
            "cue_id": "cue_001",
            "text": "打开网站，输入需求，点击开始生成。",
            "start_ms": 0,
            "end_ms": 1800,
            "start_frame": 0,
            "end_frame": 54,
        },
        {
            "cue_id": "cue_002",
            "text": "看，效果图已经出来了。",
            "start_ms": 1800,
            "end_ms": 3000,
            "start_frame": 54,
            "end_frame": 90,
        },
    ]
    planner = ScenePlanner(PlannerConfig())
    scenes = planner.plan(
        cues,
        recipes={"demo": {"steps": []}},
        result_assets=["assets/results/demo.png"],
    )

    assert scenes[0]["kind"] == "website_operation"
    assert scenes[0]["recipe_id"] == "demo"
    assert scenes[1]["kind"] == "result_detail"
    assert scenes[1]["asset_paths"] == ["assets/results/demo.png"]
