from __future__ import annotations

from pathlib import Path

from video_agent.contracts.v4 import FrozenNarration
from video_agent.speech.v4.narration_freeze import freeze_goal_narration, freeze_script_narration
import video_agent.v4.orchestrator as orchestrator_mod


def test_freeze_script_narration_is_verbatim() -> None:
    frozen = freeze_script_narration(text="  打开柯幻熊猫，一键出图。\r\n")
    assert isinstance(frozen, FrozenNarration)
    assert frozen.source == "script"
    assert frozen.text == "打开柯幻熊猫，一键出图。"
    assert frozen.source_fingerprint.startswith("sha256:")


def test_freeze_goal_narration_keeps_spoken_text() -> None:
    frozen = freeze_goal_narration(
        spoken_text="广告设计不用再反复改提示词。",
        goal="柯幻熊猫文生图功能种草",
        response_fingerprint="abc",
    )
    assert frozen.source == "goal"
    assert frozen.text == "广告设计不用再反复改提示词。"


def test_v4_orchestrator_has_no_legacy_import() -> None:
    source = Path(orchestrator_mod.__file__).read_text(encoding="utf-8")
    assert "LegacyOrchestrator" not in source
    assert "from video_agent.orchestrator" not in source
