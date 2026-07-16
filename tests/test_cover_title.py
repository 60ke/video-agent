from __future__ import annotations

from pathlib import Path

from video_agent.ai.cover_title import plan_cover_title
from video_agent.contracts import CaseConfig, Narration, NarrationBeat


def test_cover_title_planner_receives_full_narration(tmp_path: Path, monkeypatch) -> None:
    prompt_dir = tmp_path / "video_agent" / "prompts"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "cover_title_planner.md").write_text("返回 JSON 标题。", encoding="utf-8")
    captured: dict[str, str] = {}

    def complete_json(_self, system: str, user: str, schema_name: str, **_kwargs):
        captured.update(system=system, user=user, schema_name=schema_name)
        return {"title": "广告人的AI设计神器"}

    monkeypatch.setattr("video_agent.ai.cover_title.OpenAICompatibleTextClient.__init__", lambda self, _root: None)
    monkeypatch.setattr("video_agent.ai.cover_title.OpenAICompatibleTextClient.complete_json", complete_json)
    narration = Narration(
        case_id="demo",
        beats=[
            NarrationBeat(beat_id="beat_001", spoken_text="第一句只是开场。"),
            NarrationBeat(beat_id="beat_002", spoken_text="后面介绍完整的设计和改图能力。"),
        ],
    )

    plan, _meta = plan_cover_title(
        tmp_path,
        CaseConfig(case_id="demo", goal="柯幻熊猫文生图功能种草"),
        narration,
    )

    assert plan.title == "广告人的AI设计神器"
    assert "第一句只是开场。" in captured["user"]
    assert "后面介绍完整的设计和改图能力。" in captured["user"]
    assert captured["schema_name"] == "cover_title"
