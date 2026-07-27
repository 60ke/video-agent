"""Small, structured tools exposed to the Video Agent Skill."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4
from datetime import datetime
import secrets

from video_agent.agent_runtime.contracts import AgentSession, ArtifactRef, NextAction, ToolError, ToolResult
from video_agent.agent_runtime.session import append_tool_event, create_session, load_session, save_session
from video_agent.io import load_json, sha256_file
from video_agent.runtime import RunContext
from video_agent.contracts import CaseConfig, VoiceConfig
from video_agent.speech.minimax import local_minimax_voice_id


_CHECKPOINT_ARTIFACTS: tuple[tuple[str, str, str], ...] = (
    ("narration", "frozen_narration.json", "freeze_narration"),
    ("speech", "speech_timing_lock.json", "build_speech"),
    ("scene", "scene_semantic_plan.json", "plan_scenes"),
    ("materials", "resolved_asset_plan.json", "resolve_materials"),
    ("anchors", "anchored_timing_plan.json", "compile_anchors"),
    ("edit", "motion_audio_plan.json", "plan_edit_intents"),
    ("blueprint", "compiled_video_timeline.json", "build_jianying_draft"),
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


def create_agent_case(
    *,
    cases_root: Path,
    goal: str | None = None,
    script_text: str | None = None,
    case_id: str | None = None,
    mode: str = "interactive",
) -> ToolResult:
    """Create a new Case/Run and initialize its Agent Session."""

    if bool(goal) == bool(script_text):
        raise ValueError("provide exactly one of goal or script_text")
    repo_root = Path(__file__).resolve().parents[2]
    cases_root = cases_root.resolve()
    cases_root.mkdir(parents=True, exist_ok=True)
    actual_case_id = case_id or f"video_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(2)}"
    case_dir = cases_root / actual_case_id
    if case_dir.exists():
        raise FileExistsError(f"case already exists: {case_dir}")
    voice_id = local_minimax_voice_id(repo_root)
    config = CaseConfig(
        case_id=actual_case_id,
        goal=goal or "固定文案视频制作",
        feature_path=["文生图"],
        voice=VoiceConfig(
            voice_id=voice_id or VoiceConfig().voice_id,
            voice_profile_id="minimax_adman_clear_01",
        ),
        mode="script_locked" if script_text else "material_first",
        narration_source="input/source_script.txt" if script_text else None,
        ai_enabled=not bool(script_text),
    )
    case_dir.mkdir()
    (case_dir / "input").mkdir()
    from video_agent.io import write_json_atomic

    write_json_atomic(case_dir / "case.json", config)
    if script_text:
        (case_dir / "input" / "source_script.txt").write_text(script_text.strip() + "\n", encoding="utf-8")
    context = RunContext.create(case_dir)
    session = create_session(context.run_dir, case_id=actual_case_id, run_id=context.run_id, mode=mode)
    artifacts = [ArtifactRef(kind="case", path="case.json", sha256=sha256_file(case_dir / "case.json"))]
    if script_text:
        source = case_dir / "input" / "source_script.txt"
        artifacts.append(ArtifactRef(kind="source_script", path="input/source_script.txt", sha256=sha256_file(source)))
    return ToolResult(
        ok=True,
        tool="create_case",
        case_id=actual_case_id,
        run_id=context.run_id,
        status="completed",
        artifacts=artifacts,
        next_actions=[NextAction(action="inspect_context", reason="new Agent Session is ready")],
        warnings=[f"session_id={session.session_id}"],
    )


def _result_artifacts(run_dir: Path, paths: dict[str, Path | None]) -> list[ArtifactRef]:
    artifacts: list[ArtifactRef] = []
    for kind, path in paths.items():
        if path is None or not path.is_file():
            continue
        try:
            relative = path.resolve().relative_to(run_dir.resolve()).as_posix()
        except ValueError:
            # Drafts may intentionally live outside the run directory.  Keep the
            # tool protocol repository-relative and expose only the basename.
            relative = path.name
        artifacts.append(ArtifactRef(kind=kind, path=relative, sha256=sha256_file(path)))
    return artifacts


def _tool_error(exc: Exception) -> ToolError:
    recoverable = isinstance(exc, (TimeoutError, ConnectionError))
    return ToolError(
        code=exc.__class__.__name__.lower(),
        message=str(exc),
        recoverable=recoverable,
    )


def _stage1_artifacts(run_dir: Path) -> dict[str, Path]:
    return {
        "frozen_narration": run_dir / "frozen_narration.json",
        "resolved_voice_profile": run_dir / "resolved_voice_profile.json",
        "speech_timing_lock": run_dir / "speech_timing_lock.json",
        "video_scope": run_dir / "video_scope.json",
        "scene_semantic_plan": run_dir / "scene_semantic_plan.json",
    }


def _complete_frontend(run_dir: Path) -> bool:
    return all(path.is_file() for path in _stage1_artifacts(run_dir).values())


def _run_tool_impl(
    *,
    case_dir: Path,
    run_id: str,
    tool: str,
    options: dict[str, Any] | None = None,
) -> ToolResult:
    """Execute one deterministic kernel operation behind the Skill contract.

    This is deliberately a facade, not a second orchestrator.  It delegates to
    the existing V4 runners and keeps external capture/derivation as explicit
    waiting states until their provider tool is available.
    """

    options = options or {}
    context = RunContext.open(case_dir, run_id)
    case_id = context.case.case_id
    if tool in {"capture_site", "derive_assets"}:
        action = "capture_site" if tool == "capture_site" else "derive_assets"
        capability = "cdp_site_capture" if tool == "capture_site" else "gpt_image_registered_derivation"
        return ToolResult(
            ok=True,
            tool=tool,
            case_id=case_id,
            run_id=run_id,
            status="waiting_for_tool",
            next_actions=[NextAction(action=action, capability_id=capability, reason="external provider tool is required")],
            warnings=["no external capture/derivation provider was invoked by this local command"],
        )

    from video_agent.v4 import V4Orchestrator

    runner = V4Orchestrator(context)
    if tool in {"freeze_narration", "build_speech", "plan_scenes"}:
        if not _complete_frontend(context.run_dir):
            result = runner.run_stage1()
        else:
            result = None
        artifacts = _result_artifacts(
            context.run_dir,
            {
                "frozen_narration": _stage1_artifacts(context.run_dir)["frozen_narration"],
                "resolved_voice_profile": _stage1_artifacts(context.run_dir)["resolved_voice_profile"],
                "speech_timing_lock": _stage1_artifacts(context.run_dir)["speech_timing_lock"],
                "video_scope": _stage1_artifacts(context.run_dir)["video_scope"],
                "scene_semantic_plan": _stage1_artifacts(context.run_dir)["scene_semantic_plan"],
            },
        )
        return ToolResult(
            ok=True,
            tool=tool,
            case_id=case_id,
            run_id=run_id,
            status="completed",
            artifacts=artifacts,
            next_actions=[NextAction(action="resolve_materials", reason="semantic frontend is frozen")],
            warnings=["freeze_narration, build_speech and plan_scenes share the atomic V4 semantic_frontend kernel"]
            if result is not None
            else [],
        )

    if tool == "resolve_materials":
        result = runner.run_stage4(
            run_seed=str(options.get("seed", "default")),
            allow_fake_derivation=False,
            db=Path(options["db"]).resolve() if options.get("db") else None,
            object_root=Path(options["object_root"]).resolve() if options.get("object_root") else None,
        )
        return ToolResult(
            ok=True,
            tool=tool,
            case_id=case_id,
            run_id=run_id,
            status="completed",
            artifacts=_result_artifacts(
                context.run_dir,
                {"resolved_asset_plan": result.resolved_asset_plan, "asset_repository_snapshot": result.asset_repository_snapshot},
            ),
            next_actions=[NextAction(action="compile_anchors", reason="materials are resolved")],
        )

    if tool == "compile_anchors":
        if not context.artifact("resolved_asset_plan.json").is_file():
            return ToolResult(
                ok=False,
                tool=tool,
                case_id=case_id,
                run_id=run_id,
                status="blocked",
                error=ToolError(code="missing_resolved_assets", message="resolve_materials must complete first", recoverable=True),
                next_actions=[NextAction(action="resolve_materials")],
            )
        result = runner.run_stage6(phase="anchor")
        return ToolResult(
            ok=True,
            tool=tool,
            case_id=case_id,
            run_id=run_id,
            status="completed",
            artifacts=_result_artifacts(context.run_dir, {"anchored_timing_plan": result.anchored_timing_plan}),
            next_actions=[NextAction(action="plan_edit_intents", reason="word anchors are compiled")],
        )

    if tool == "plan_edit_intents":
        if not context.artifact("anchored_timing_plan.json").is_file():
            return ToolResult(
                ok=False,
                tool=tool,
                case_id=case_id,
                run_id=run_id,
                status="blocked",
                error=ToolError(code="missing_anchored_timing", message="compile_anchors must complete first", recoverable=True),
                next_actions=[NextAction(action="compile_anchors")],
            )
        result = runner.run_stage5(
            run_seed=str(options.get("seed", "default")),
            sfx_profile_id=str(options.get("sfx_profile", "normal")),
        )
        return ToolResult(
            ok=True,
            tool=tool,
            case_id=case_id,
            run_id=run_id,
            status="completed",
            artifacts=_result_artifacts(
                context.run_dir,
                {"motion_audio_plan": result.motion_audio_plan, "anchored_timing_plan": result.anchored_timing_plan},
            ),
            next_actions=[NextAction(action="build_jianying_draft", reason="edit and SFX intents are planned")],
        )

    if tool == "build_jianying_draft":
        result = runner.run_stage6(
            phase="compile-render",
            render=True,
            skip_ffmpeg=True,
            editor_backend="jianying",
            jianying_skill_root=Path(options["jianying_skill_root"]).resolve()
            if options.get("jianying_skill_root")
            else None,
            jianying_drafts_root=Path(options["jianying_drafts_root"]).resolve()
            if options.get("jianying_drafts_root")
            else None,
        )
        return ToolResult(
            ok=True,
            tool=tool,
            case_id=case_id,
            run_id=run_id,
            status="completed",
            artifacts=_result_artifacts(
                context.run_dir,
                {
                    "compiled_timeline": result.compiled_timeline,
                    "editor_manifest": result.editor_manifest,
                    "editor_draft": result.editor_draft,
                },
            ),
            next_actions=[NextAction(action="inspect_delivery", reason="Jianying draft is ready")],
        )

    if tool == "inspect_delivery":
        paths = {
            "compiled_timeline": context.artifact("compiled_video_timeline.json"),
            "stage6_validation": context.artifact("stage6_validation.json"),
            "jianying_manifest": context.run_dir / "render" / "jianying" / "jianying_project_manifest.json",
            "final_video": context.run_dir / "final" / "video.mp4",
            "final_cover": context.run_dir / "final" / "cover.png",
        }
        artifacts = _result_artifacts(context.run_dir, paths)
        return ToolResult(
            ok=bool(artifacts),
            tool=tool,
            case_id=case_id,
            run_id=run_id,
            status="completed" if artifacts else "blocked",
            artifacts=artifacts,
            next_actions=[] if artifacts else [NextAction(action="build_jianying_draft")],
            error=None if artifacts else ToolError(code="delivery_not_found", message="no delivery artifacts found", recoverable=True),
        )

    raise ValueError(f"unknown agent tool: {tool}")


AGENT_TOOL_NAMES = (
    "freeze_narration",
    "build_speech",
    "plan_scenes",
    "resolve_materials",
    "capture_site",
    "derive_assets",
    "compile_anchors",
    "plan_edit_intents",
    "build_jianying_draft",
    "inspect_delivery",
)


def execute_agent_tool(
    case_dir: Path,
    *,
    run_id: str,
    tool: str,
    options: dict[str, Any] | None = None,
) -> ToolResult:
    """Run one Tool Facade operation and persist its session event."""

    if tool not in AGENT_TOOL_NAMES:
        raise ValueError(f"unknown agent tool: {tool}; expected one of {AGENT_TOOL_NAMES}")
    run_dir = case_dir.resolve() / "runs" / run_id
    if not (run_dir / "agent_session.json").is_file():
        raise FileNotFoundError(f"agent session not found: {run_dir / 'agent_session.json'}")
    session = load_session(run_dir)
    call_id = f"agent-call://{uuid4().hex}"
    session.status = "planning"
    session.current_checkpoint = tool
    session.last_tool_call_id = call_id
    save_session(run_dir, session)
    try:
        result = _run_tool_impl(case_dir=case_dir.resolve(), run_id=run_id, tool=tool, options=options)
    except Exception as exc:  # convert all kernel failures into the stable envelope
        result = ToolResult(
            ok=False,
            tool=tool,
            case_id=session.case_id,
            run_id=run_id,
            status="blocked",
            error=_tool_error(exc),
        )
    append_tool_event(run_dir, call_id=call_id, result=result)
    if result.ok:
        if tool not in session.completed_tools:
            session.completed_tools.append(tool)
        session.status = "draft_ready" if tool == "build_jianying_draft" else "waiting_for_tool"
        session.recoverable = True
    else:
        session.status = "recovering" if result.error and result.error.recoverable else "failed"
        session.recoverable = bool(result.error and result.error.recoverable)
    session.pending_gaps = list(result.gaps)
    save_session(run_dir, session)
    return result
