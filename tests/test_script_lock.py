from __future__ import annotations

from argparse import Namespace
from pathlib import Path

from video_agent.cli import command_init, command_script_lock
from video_agent.io import load_json, load_model
from video_agent.contracts import CaseConfig, Narration
from video_agent.script_lock import locked_narration_from_text


def test_locked_narration_keeps_exact_sentences_without_visual_inference() -> None:
    text = "文化墙、门店招牌、景观小品都能一键生成。\n零基础也能上手！"
    narration = locked_narration_from_text("fixed_demo", text)

    assert [beat.spoken_text for beat in narration.beats] == [
        "文化墙、门店招牌、景观小品都能一键生成。",
        "零基础也能上手！",
    ]
    assert narration.beats[0].visual_strategy == "auto"
    assert narration.beats[0].hit_phrases == []
    assert narration.beats[0].asset_slots == []
    assert narration.beats[1].visual_strategy == "auto"


def test_init_with_script_creates_locked_case(tmp_path: Path) -> None:
    case_dir = tmp_path / "fixed_demo"
    result = command_init(
        Namespace(
            case=str(case_dir), case_id="fixed_demo", goal="测试", feature_path=["文生图"],
            script_text="文化墙、门店招牌都能一键生成。", script_file=None,
        )
    )

    config = load_model(case_dir / "case.json", CaseConfig)
    narration = load_model(case_dir / "input" / "narration.json", Narration)
    assert result["locked"] is True
    assert config.mode == "script_locked"
    assert config.ai_enabled is False
    assert config.narration_source == "input/narration.json"
    assert narration.beats[0].hit_phrases == []


def test_script_lock_updates_existing_case(tmp_path: Path) -> None:
    case_dir = tmp_path / "existing"
    case_dir.mkdir()
    (case_dir / "input").mkdir()
    from video_agent.io import write_json_atomic
    write_json_atomic(case_dir / "case.json", CaseConfig(case_id="existing", goal="测试"))

    result = command_script_lock(Namespace(case=str(case_dir), script_text="打开首页。", script_file=None))

    config = CaseConfig.model_validate(load_json(case_dir / "case.json"))
    assert result["beats"] == 1
    assert config.mode == "script_locked"
    assert config.narration_source == "input/narration.json"
