import json
from pathlib import Path

import pytest

from video_agent.agent_runtime.tooling import (
    create_agent_case,
    create_agent_session,
    execute_agent_tool,
    inspect_context,
)
from video_agent.agent_runtime.setup import setup_installation


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


def test_external_tool_returns_waiting_result_and_records_event(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    run_dir = case_dir / "runs" / "run-1"
    run_dir.mkdir(parents=True)
    (case_dir / "case.json").write_text(
        json.dumps({"case_id": "case-1", "goal": "x", "feature_path": ["文生图"], "voice": {}}),
        encoding="utf-8",
    )
    create_agent_session(run_dir, case_id="case-1", run_id="run-1")

    result = execute_agent_tool(case_dir, run_id="run-1", tool="capture_site")

    assert result.ok is True
    assert result.status == "waiting_for_tool"
    assert result.next_actions[0].capability_id == "cdp_site_capture"
    assert (run_dir / "agent_events.jsonl").is_file()


def test_execute_tool_requires_existing_session(tmp_path: Path) -> None:
    case_dir = tmp_path / "case"
    run_dir = case_dir / "runs" / "run-1"
    run_dir.mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="agent_session.json"):
        execute_agent_tool(case_dir, run_id="run-1", tool="inspect_delivery")


def test_create_agent_case_initializes_run_and_session(tmp_path: Path) -> None:
    result = create_agent_case(cases_root=tmp_path / "cases", script_text="文化墙一键生成")

    assert result.ok is True
    assert result.case_id
    assert result.run_id
    case_dir = tmp_path / "cases" / result.case_id
    assert (case_dir / "case.json").is_file()
    assert (case_dir / "input" / "source_script.txt").is_file()
    assert (case_dir / "runs" / result.run_id / "agent_session.json").is_file()


def test_setup_non_interactive_does_not_overwrite_local_provider_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    ai_path = config_dir / "ai.local.json"
    original = '{"api_key":"local-secret","custom":"keep"}'
    ai_path.write_text(original, encoding="utf-8")

    report = setup_installation(tmp_path, interactive=False)

    assert report["ok"] is True
    assert ai_path.read_text(encoding="utf-8") == original
