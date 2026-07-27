"""Small, structured tools exposed to the Video Agent Skill."""

from __future__ import annotations

from pathlib import Path

from video_agent.agent_runtime.contracts import AgentSession, ArtifactRef, NextAction, ToolError, ToolResult
from video_agent.agent_runtime.session import create_session, load_session
from video_agent.io import load_json


_CHECKPOINT_ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    ("narration", "frozen_narration.json", "freeze_narration"),
    ("speech", "speech_timing_lock.json", "build_speech"),
    ("scene", "scene_semantic_plan.json", "plan_scenes"),
    ("materials", "resolved_asset_plan.json", "resolve_materials"),
    ("anchors", "anchored_timing_plan.json", "compile_anchors"),
    ("edit", "motion_audio_plan.json", "plan_edit_intents"),
    ("blueprint", "compiled_video_timeline.resolved.json", "build_jianying_draft"),
)


def _artifact(run_dir: Path, kind: str, relative_path: str) -> ArtifactRef | None:
    path = run_dir / relative_path
    if not path.is_file():
        return None
    return ArtifactRef(kind=kind, path=relative_path)


def _latest_run(case_dir: Path) -> str | None:
    latest = case_dir / "latest_run.json"
    if latest.is_file():
        value = load_json(latest).get("run_id")
        if value:
            return str(value)
    runs = sorted((case_dir / "runs").glob("*")) if (case_dir / "runs").is_dir() else []
    return runs[-1].name if runs else None


def inspect_context(case_dir: Path, run_id: str | None = None) -> ToolResult:
    """Summarize a Case/Run and suggest the next safe Skill action."""

    case_file = case_dir / "case.json"
    if not case_file.is_file():
        return ToolResult(
            ok=False,
            tool="inspect_context",
            status="blocked",
            error=ToolError(
                code="case_not_found",
                message=f"case.json not found: {case_dir}",
                recoverable=False,
            ),
            next_actions=[NextAction(action="create_case", reason="create a new production case")],
        )

    case = load_json(case_file)
    resolved_run_id = run_id or _latest_run(case_dir)
    if not resolved_run_id:
        return ToolResult(
            ok=True,
            tool="inspect_context",
            case_id=str(case.get("case_id") or case_dir.name),
            status="waiting_for_tool",
            next_actions=[NextAction(action="create_run", reason="case has no production run")],
        )

    run_dir = case_dir / "runs" / resolved_run_id
    if not run_dir.is_dir():
        return ToolResult(
            ok=False,
            tool="inspect_context",
            case_id=str(case.get("case_id") or case_dir.name),
            run_id=resolved_run_id,
            status="blocked",
            error=ToolError(
                code="run_not_found",
                message=f"run directory not found: {run_dir}",
                recoverable=False,
            ),
        )

    artifacts: list[ArtifactRef] = []
    next_action = NextAction(action="inspect_delivery", reason="all planning artifacts are present")
    for checkpoint, relative_path, action in _CHECKPOINT_ARTIFACTS:
        found = _artifact(run_dir, checkpoint, relative_path)
        if found:
            artifacts.append(found)
            continue
        next_action = NextAction(action=action, reason=f"missing {relative_path}")
        break

    manifest = run_dir / "render" / "jianying" / "jianying_project_manifest.json"
    if manifest.is_file():
        artifacts.append(ArtifactRef(kind="jianying_project_manifest", path="render/jianying/jianying_project_manifest.json"))
        next_action = NextAction(action="inspect_delivery", reason="Jianying draft manifest is available")

    return ToolResult(
        ok=True,
        tool="inspect_context",
        case_id=str(case.get("case_id") or case_dir.name),
        run_id=resolved_run_id,
        status="waiting_for_tool",
        artifacts=artifacts,
        next_actions=[next_action],
        warnings=["context summary only; no production stage was executed"],
    )


def create_agent_session(run_dir: Path, *, case_id: str, run_id: str, mode: str = "interactive") -> AgentSession:
    """Create the persisted Skill session for a Case/Run."""

    existing = run_dir / "agent_session.json"
    if existing.is_file():
        return load_session(run_dir)
    return create_session(run_dir, case_id=case_id, run_id=run_id, mode=mode)


def inspect_session(run_dir: Path) -> AgentSession:
    return load_session(run_dir)
