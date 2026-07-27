"""Persistence helpers for resumable Skill sessions."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from video_agent.agent_runtime.contracts import AgentSession, ToolResult
from video_agent.io import load_model, write_json_atomic


def create_session(
    run_dir: Path,
    *,
    case_id: str,
    run_id: str,
    mode: str = "interactive",
) -> AgentSession:
    session = AgentSession(
        session_id=f"agent-session://{uuid4().hex}",
        case_id=case_id,
        run_id=run_id,
        mode=mode,  # type: ignore[arg-type]
        status="created",
        current_checkpoint="context",
    )
    save_session(run_dir, session)
    return session


def load_session(run_dir: Path) -> AgentSession:
    return load_model(run_dir / "agent_session.json", AgentSession)


def save_session(run_dir: Path, session: AgentSession) -> None:
    session.updated_at = datetime.now(timezone.utc).isoformat()
    write_json_atomic(run_dir / "agent_session.json", session)


def append_tool_event(run_dir: Path, *, call_id: str, result: ToolResult, decision: str | None = None) -> None:
    event = {
        "event": "tool_result",
        "call_id": call_id,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "result": result.model_dump(mode="json", exclude_none=True),
    }
    if decision:
        event["decision"] = decision
    path = run_dir / "agent_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_tool_events(run_dir: Path) -> list[dict[str, Any]]:
    path = run_dir / "agent_events.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
