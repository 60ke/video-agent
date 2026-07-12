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
