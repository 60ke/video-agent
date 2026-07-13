from __future__ import annotations

from pathlib import Path

from video_agent.contracts import CaseConfig
from video_agent.io import write_json_atomic
from video_agent.orchestrator import Orchestrator
from video_agent.runtime import RunContext


def _case(path: Path, goal: str) -> None:
    write_json_atomic(path / "case.json", CaseConfig(case_id="resume_demo", goal=goal, feature_path=["文生图", "文化墙"]))


def test_resume_reuses_matching_stage_and_invalidates_changed_case(tmp_path: Path) -> None:
    _case(tmp_path, "初始目标")
    created = RunContext.create(tmp_path, run_id="fixed")
    Orchestrator(created).run(until_stage="catalog")

    resumed = RunContext.open(tmp_path, "fixed")
    runner = Orchestrator(resumed)
    runner.stage_catalog = lambda: (_ for _ in ()).throw(AssertionError("matching catalog stage should be reused"))  # type: ignore[method-assign]
    runner.run(until_stage="catalog")

    _case(tmp_path, "变更后的目标")
    changed = RunContext.open(tmp_path, "fixed")
    rerun = Orchestrator(changed)
    calls: list[bool] = []
    original = rerun.stage_catalog

    def counting_catalog() -> Path:
        calls.append(True)
        return original()

    rerun.stage_catalog = counting_catalog  # type: ignore[method-assign]
    rerun.run(until_stage="catalog")
    assert calls == [True]


def test_resume_fingerprint_tracks_locked_source_prompt_model_and_code(tmp_path: Path) -> None:
    source = tmp_path / "narration.json"
    source.write_text('{"version": 1}', encoding="utf-8")
    write_json_atomic(tmp_path / "case.json", CaseConfig(case_id="resume_demo", goal="测试", narration_source=source.name))
    context = RunContext.create(tmp_path, run_id="fingerprint")
    runner = Orchestrator(context)
    first = runner._stage_input_fingerprint("narration")
    assert first["prompt_sha256"]
    assert first["code_sha256"]
    assert set(first["provider"]) == {"provider", "base_url", "model"}
    assert "api_key" not in first["provider"]
    source.write_text('{"version": 2}', encoding="utf-8")
    second = runner._stage_input_fingerprint("narration")
    assert first["inputs"]["source"] != second["inputs"]["source"]
