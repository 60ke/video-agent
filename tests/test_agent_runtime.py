from pathlib import Path

from video_agent.agent_runtime.tooling import create_agent_session, inspect_context


def test_inspect_context_suggests_case_creation_for_missing_case(tmp_path: Path) -> None:
    result = inspect_context(tmp_path / "missing")

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "case_not_found"
    assert result.next_actions[0].action == "create_case"


def test_inspect_context_suggests_first_missing_artifact(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    run_dir = case_dir / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text('{"case_id":"case-1"}', encoding="utf-8")
    (case_dir / "latest_run.json").write_text('{"run_id":"run-1"}', encoding="utf-8")

    result = inspect_context(case_dir)

    assert result.ok is True
    assert result.run_id == "run-1"
    assert result.next_actions[0].action == "freeze_narration"


def test_session_creation_is_idempotent(tmp_path: Path) -> None:
    first = create_agent_session(tmp_path, case_id="case-1", run_id="run-1")
    second = create_agent_session(tmp_path, case_id="case-1", run_id="run-1")

    assert first.session_id == second.session_id
