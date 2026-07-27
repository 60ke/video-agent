"""Typed contracts shared by Skill tools and the Agent session."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AgentContract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ArtifactRef(AgentContract):
    kind: str
    path: str
    sha256: str | None = None


class NextAction(AgentContract):
    action: str
    reason: str | None = None
    capability_id: str | None = None


class ToolError(AgentContract):
    code: str
    message: str
    recoverable: bool
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


ToolStatus = Literal["completed", "waiting_for_tool", "waiting_for_user", "blocked"]


class ToolResult(AgentContract):
    ok: bool
    tool: str
    tool_version: str = "1"
    case_id: str | None = None
    run_id: str | None = None
    status: ToolStatus
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    next_actions: list[NextAction] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    error: ToolError | None = None


SessionStatus = Literal[
    "created",
    "inspecting",
    "planning",
    "waiting_for_tool",
    "waiting_for_user",
    "recovering",
    "draft_ready",
    "completed",
    "failed",
]


class AgentSession(AgentContract):
    session_id: str
    case_id: str
    run_id: str
    mode: Literal["interactive", "batch"]
    status: SessionStatus
    current_checkpoint: str
    completed_tools: list[str] = Field(default_factory=list)
    pending_gaps: list[str] = Field(default_factory=list)
    last_tool_call_id: str | None = None
    recoverable: bool = True
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
