from __future__ import annotations

import argparse
import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from video_agent.assets import build_catalog, generate_editor_flow_assets
from video_agent.assets.site_entry_batch import generate_site_entry_keyframes
from video_agent.assets.site_params_sequence import generate_parameter_frame_sequences
from video_agent.assets.video_material_import import import_video_material_images
from video_agent.assets.v4 import (
    AssetImportError,
    AssetQuery,
    LocalObjectStore,
    SQLiteAssetRepository,
    audit_repository,
    import_manifest,
    migrate_legacy,
)
from video_agent.audio.register import register_sfx_library
from video_agent.case_admin import clean_cases, export_case_videos
from video_agent.contracts import CaseConfig, VoiceConfig
from video_agent.cover import postprocess_cover
from video_agent.outro import postprocess_outro
from video_agent.io import load_json, load_model, write_json_atomic
from video_agent.orchestrator import Orchestrator
from video_agent.progress import configure_logging, get_logger
from video_agent.runtime import RunContext, STAGES
from video_agent.script_lock import locked_narration_from_text
from video_agent.speech.minimax import local_minimax_voice_id
from video_agent.v4 import V4Orchestrator
from video_agent.registries import CapabilityRegistryHub


logger = get_logger()


def _print(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        for key, item in value.items():
            print(f"{key}: {item}")


def _exception_result(exc: Exception) -> dict[str, Any]:
    result: dict[str, Any] = {
        "ok": False,
        "error": exc.__class__.__name__,
        "message": str(exc),
    }
    if isinstance(exc, AssetImportError):
        result["orphans"] = list(exc.orphans)
    return result


def command_catalog(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.assets).resolve()
    output = Path(args.output).resolve() if args.output else root / "catalog.json"
    catalog = build_catalog(root, output)
    return {"ok": True, "catalog": output.as_posix(), "assets": len(catalog.assets), "warnings": len(catalog.warnings)}


def command_run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    context = RunContext.open(case_dir, args.resume) if args.resume else RunContext.create(case_dir)
    final_video = Orchestrator(context).run(from_stage=args.from_stage, until_stage=args.until_stage)
    return {
        "ok": True,
        "run_id": context.run_id,
        "run_dir": context.run_dir.as_posix(),
        "final_video": final_video.as_posix() if final_video else None,
    }


def command_v4_stage1(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    context = RunContext.open(case_dir, args.resume) if args.resume else RunContext.create(case_dir)
    result = V4Orchestrator(context).run_stage1()
    return {
        "ok": True,
        "run_id": context.run_id,
        "run_dir": context.run_dir.as_posix(),
        "video_scope": result.video_scope.as_posix(),
        "scene_semantic_plan": result.scene_semantic_plan.as_posix(),
    }


def command_v4_stage4(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    context = RunContext.open(case_dir, args.resume) if args.resume else RunContext.create(case_dir)
    result = V4Orchestrator(context).run_stage4(
        run_seed=args.seed,
        allow_fake_derivation=args.allow_fake_derivation,
        db=Path(args.db).resolve() if args.db else None,
        object_root=Path(args.object_root).resolve() if args.object_root else None,
    )
    return {
        "ok": True,
        "run_id": context.run_id,
        "run_dir": context.run_dir.as_posix(),
        "resolved_asset_plan": result.resolved_asset_plan.as_posix(),
        "manifest": result.manifest.as_posix(),
    }


def command_v4_stage5(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    context = RunContext.open(case_dir, args.resume) if args.resume else RunContext.create(case_dir)
    result = V4Orchestrator(context).run_stage5(
        run_seed=args.seed,
        sfx_profile_id=args.sfx_profile,
    )
    return {
        "ok": True,
        "run_id": context.run_id,
        "run_dir": context.run_dir.as_posix(),
        "motion_audio_plan": result.motion_audio_plan.as_posix(),
        "anchored_timing_plan": result.anchored_timing_plan.as_posix(),
        "manifest": result.manifest.as_posix(),
    }


def command_v4_stage6(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    if not args.resume:
        raise ValueError("v4-stage6 requires --resume <run_id>")
    context = RunContext.open(case_dir, args.resume)
    result = V4Orchestrator(context).run_stage6(
        phase=args.phase,
        postroll_frames=args.postroll_frames,
        object_root=Path(args.object_root).resolve() if args.object_root else None,
        render=bool(args.render),
        skip_ffmpeg=bool(args.skip_ffmpeg),
    )
    payload: dict[str, Any] = {
        "ok": True,
        "run_id": context.run_id,
        "run_dir": context.run_dir.as_posix(),
        "phase": result.phase,
        "manifest": result.manifest.as_posix(),
    }
    if result.anchored_timing_plan is not None:
        payload["anchored_timing_plan"] = result.anchored_timing_plan.as_posix()
    if result.compiled_timeline is not None:
        payload["compiled_video_timeline"] = result.compiled_timeline.as_posix()
    if result.remotion_timeline is not None:
        payload["remotion_timeline"] = result.remotion_timeline.as_posix()
    if result.final_video is not None:
        payload["final_video"] = result.final_video.as_posix()
    return payload


def command_generate_video(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    cases_root = Path(args.cases).resolve()
    cases_root.mkdir(parents=True, exist_ok=True)
    case_id = args.case_id or f"video_{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(2)}"
    case_dir = cases_root / case_id
    if case_dir.exists():
        raise FileExistsError(f"case already exists: {case_dir}")

    script_path = Path(args.script).resolve() if args.script else None
    script_text = script_path.read_text(encoding="utf-8-sig").strip() if script_path else None
    if script_path and not script_text:
        raise ValueError(f"script file must not be empty: {script_path}")
    script_narration = locked_narration_from_text(case_id, script_text) if script_text else None
    default_goal = "柯幻熊猫文生图功能种草"

    voice_id = local_minimax_voice_id(repo_root)
    voice = VoiceConfig(voice_id=voice_id) if voice_id else VoiceConfig()
    config = CaseConfig(
        case_id=case_id,
        goal=args.goal or default_goal,
        feature_path=["文生图"],
        voice=voice,
        mode="script_locked" if script_text else "material_first",
        narration_source="input/narration.json" if script_text else None,
        ai_enabled=not bool(script_text),
    )
    case_dir.mkdir()
    input_dir = case_dir / "input"
    input_dir.mkdir()
    write_json_atomic(case_dir / "case.json", config)
    if script_narration:
        write_json_atomic(input_dir / "narration.json", script_narration)

    context = RunContext.create(case_dir)
    logger.info("[任务] 已创建 case=%s run=%s source=%s", case_id, context.run_id, "script" if script_text else "goal")
    final_video = Orchestrator(context).run()
    return {
        "ok": True,
        "case_id": case_id,
        "case": case_dir.as_posix(),
        "run_id": context.run_id,
        "run_dir": context.run_dir.as_posix(),
        "final_video": final_video.as_posix() if final_video else None,
    }


def command_inspect(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    run_id = args.run
    if not run_id:
        latest = load_json(case_dir / "latest_run.json")
        run_id = latest["run_id"]
    run_dir = case_dir / "runs" / run_id
    manifest = load_json(run_dir / "run_manifest.json")
    qa_path = run_dir / "qa_report.json"
    return {"ok": True, "run_id": run_id, "manifest": manifest, "qa": load_json(qa_path) if qa_path.is_file() else None}


def command_init(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    case_dir.mkdir(parents=True, exist_ok=False)
    repo_root = Path(__file__).resolve().parents[1]
    voice_id = local_minimax_voice_id(repo_root)
    voice = VoiceConfig(voice_id=voice_id) if voice_id else VoiceConfig()
    script_text = _script_text(args)
    config = CaseConfig(
        case_id=args.case_id,
        goal=args.goal,
        feature_path=args.feature_path or [],
        voice=voice,
        mode="script_locked" if script_text else "material_first",
        narration_source="input/narration.json" if script_text else None,
        ai_enabled=False,
    )
    write_json_atomic(case_dir / "case.json", config)
    (case_dir / "input").mkdir()
    result = {"ok": True, "case": case_dir.as_posix(), "case_json": (case_dir / "case.json").as_posix()}
    if script_text:
        narration_path = case_dir / "input" / "narration.json"
        narration = locked_narration_from_text(config.case_id, script_text)
        write_json_atomic(narration_path, narration)
        result.update({"narration": narration_path.as_posix(), "beats": len(narration.beats), "locked": True})
    return result


def _script_text(args: argparse.Namespace) -> str | None:
    direct = getattr(args, "script_text", None)
    source = getattr(args, "script_file", None)
    if direct is not None:
        value = str(direct).strip()
        if not value:
            raise ValueError("--script-text must not be empty")
        return value
    if source is not None:
        return Path(source).read_text(encoding="utf-8-sig").strip()
    return None


def command_script_lock(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    config_path = case_dir / "case.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"case.json not found: {config_path}")
    text = _script_text(args)
    if text is None:
        raise ValueError("provide --script-text or --script-file")
    config = CaseConfig.model_validate(load_json(config_path)).model_copy(
        update={"mode": "script_locked", "narration_source": "input/narration.json", "ai_enabled": False}
    )
    narration = locked_narration_from_text(config.case_id, text)
    narration_path = case_dir / "input" / "narration.json"
    write_json_atomic(narration_path, narration)
    write_json_atomic(config_path, config)
    return {
        "ok": True,
        "case": case_dir.as_posix(),
        "narration": narration_path.as_posix(),
        "beats": len(narration.beats),
        "locked": True,
    }


def command_sfx_register(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source_dir).resolve()
    output = Path(args.output).resolve()
    catalog = register_sfx_library(source, output)
    return {"ok": True, "profile_id": catalog.profile_id, "assets": len(catalog.assets), "catalog": (output / "catalog.json").as_posix()}


def command_site_entry_batch(args: argparse.Namespace) -> dict[str, Any]:
    result = generate_site_entry_keyframes(
        Path(__file__).resolve().parents[1],
        Path(args.source).resolve(),
        Path(args.output).resolve(),
        workers=args.workers,
        force=args.force,
    )
    return {"ok": True, **result}


def command_site_params_sequence(args: argparse.Namespace) -> dict[str, Any]:
    result = generate_parameter_frame_sequences(
        Path(__file__).resolve().parents[1],
        Path(args.source).resolve(),
        Path(args.output).resolve(),
        include=args.include,
        exclude=args.exclude,
        workers=args.workers,
        force=args.force,
    )
    return {"ok": True, **result}


def command_editor_flow(args: argparse.Namespace) -> dict[str, Any]:
    repo_root = Path(__file__).resolve().parents[1]
    focus_rect = {"x": args.focus_x, "y": args.focus_y, "w": args.focus_w, "h": args.focus_h}
    result = generate_editor_flow_assets(
        repo_root,
        Path(args.artwork).resolve(),
        Path(args.editor_template).resolve(),
        Path(args.modal_template).resolve(),
        Path(args.output).resolve(),
        semantic_path=args.semantic_path,
        focus_rect=focus_rect,
        force=args.force,
    )
    catalog_path = repo_root / "assets" / "catalog.json"
    catalog = build_catalog(repo_root / "assets", catalog_path)
    return {"ok": True, **result, "catalog": catalog_path.as_posix(), "catalog_assets": len(catalog.assets)}


def command_import_video_materials(args: argparse.Namespace) -> dict[str, Any]:
    result = import_video_material_images(Path(__file__).resolve().parents[1], Path(args.source).resolve())
    return {"ok": True, **result}


def _v4_repository(args: argparse.Namespace) -> SQLiteAssetRepository:
    root = Path(__file__).resolve().parents[1]
    config = load_json(root / "config" / "assets.v4.json")
    db = Path(args.db).resolve() if args.db else (root / config["database"]).resolve()
    object_root = (
        Path(args.object_root).resolve()
        if getattr(args, "object_root", None)
        else (root / config["object_root"]).resolve()
    )
    hub = CapabilityRegistryHub.load(root / "config" / "registries" / "v4")
    return SQLiteAssetRepository(db, LocalObjectStore(object_root), hub)


def command_v4_assets_migrate(args: argparse.Namespace) -> dict[str, Any]:
    repository = _v4_repository(args)
    try:
        return {"ok": True, **migrate_legacy(repository, repository.object_store.root, dry_run=args.dry_run)}
    finally:
        repository.close()


def command_v4_assets_import(args: argparse.Namespace) -> dict[str, Any]:
    repository = _v4_repository(args)
    try:
        return {"ok": True, **import_manifest(repository, Path(args.manifest).resolve())}
    finally:
        repository.close()


def command_v4_assets_inspect(args: argparse.Namespace) -> dict[str, Any]:
    repository = _v4_repository(args)
    try:
        if args.asset_ref:
            asset = repository.get_asset(args.asset_ref)
            return {"ok": True, "asset": asset.model_dump(mode="json") if asset else None}
        return {
            "ok": True,
            "assets": [item.model_dump(mode="json") for item in repository.query_assets(AssetQuery(active_only=False))],
        }
    finally:
        repository.close()


def command_v4_assets_audit(args: argparse.Namespace) -> dict[str, Any]:
    repository = _v4_repository(args)
    try:
        return audit_repository(repository)
    finally:
        repository.close()


def command_cover_postprocess(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    run_id = args.run or load_json(case_dir / "latest_run.json")["run_id"]
    run_dir = case_dir / "runs" / run_id
    spec = Path(args.spec).resolve() if args.spec else case_dir / "input" / "cover.json"
    report = postprocess_cover(Path(__file__).resolve().parents[1], case_dir, run_dir, spec)
    case = load_model(case_dir / "case.json", CaseConfig)
    if case.outro_enabled:
        postprocess_outro(Path(__file__).resolve().parents[1], run_dir, case.outro_source)
    return {
        "ok": True,
        "run_id": run_id,
        "video": (run_dir / "final" / "video.mp4").as_posix(),
        "cover": report["cover"],
        "crop_preview": report["crop_preview"],
        "cover_frames": report["cover_frames"],
    }


def command_cases_export(args: argparse.Namespace) -> dict[str, Any]:
    return {"ok": True, **export_case_videos(Path(args.cases), Path(args.destination))}


def command_cases_clean(args: argparse.Namespace) -> dict[str, Any]:
    cases = Path(args.cases).resolve()
    manifest = Path(args.export_manifest).resolve() if args.export_manifest else None
    return {"ok": True, **clean_cases(cases, require_export_manifest=manifest)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="video-agent", description="Video Agent V3 material-first video compiler")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    generate = sub.add_parser(
        "generate_video",
        aliases=["generate-video"],
        help="Create a new 文生图 case and run the complete production pipeline",
    )
    generate.add_argument("--json", dest="sub_json", action="store_true")
    source = generate.add_mutually_exclusive_group(required=True)
    source.add_argument("--script", help="UTF-8 fixed narration text file")
    source.add_argument("--goal", help="Goal used by AI to generate the narration")
    generate.add_argument("--cases", default="cases", help="Parent directory for automatically created cases")
    generate.add_argument("--case-id", help="Optional explicit case ID; defaults to a unique timestamp ID")
    generate.set_defaults(handler=command_generate_video)

    catalog = sub.add_parser("catalog", help="Build the global V3 asset catalog")
    catalog.add_argument("--json", dest="sub_json", action="store_true")
    catalog.add_argument("--assets", default="assets")
    catalog.add_argument("--output")
    catalog.set_defaults(handler=command_catalog)

    init = sub.add_parser("init", help="Initialize a V3 case")
    init.add_argument("--json", dest="sub_json", action="store_true")
    init.add_argument("--case", required=True)
    init.add_argument("--case-id", required=True)
    init.add_argument("--goal", required=True)
    init.add_argument("--feature-path", action="append")
    init_script = init.add_mutually_exclusive_group()
    init_script.add_argument("--script-text", help="Lock this exact text as the narration")
    init_script.add_argument("--script-file", help="UTF-8 text file to lock as the narration")
    init.set_defaults(handler=command_init)

    script_lock = sub.add_parser("script-lock", help="Turn exact text into locked narration for an existing case")
    script_lock.add_argument("--json", dest="sub_json", action="store_true")
    script_lock.add_argument("--case", required=True)
    script_source = script_lock.add_mutually_exclusive_group(required=True)
    script_source.add_argument("--script-text", help="Exact narration text")
    script_source.add_argument("--script-file", help="UTF-8 text file containing exact narration")
    script_lock.set_defaults(handler=command_script_lock)

    run = sub.add_parser("run", help="Run the single V3 production DAG")
    run.add_argument("--json", dest="sub_json", action="store_true")
    run.add_argument("--case", required=True)
    run.add_argument("--resume")
    run.add_argument("--from-stage", choices=STAGES)
    run.add_argument("--until-stage", choices=STAGES)
    run.set_defaults(handler=command_run)

    v4_stage1 = sub.add_parser("v4-stage1", help="Run the V4 semantic frontend with parallel speech and scope")
    v4_stage1.add_argument("--json", dest="sub_json", action="store_true")
    v4_stage1.add_argument("--case", required=True)
    v4_stage1.add_argument("--resume")
    v4_stage1.set_defaults(handler=command_v4_stage1)

    v4_stage4 = sub.add_parser("v4-stage4", help="Resolve Stage4 assets into ResolvedAssetPlan")
    v4_stage4.add_argument("--json", dest="sub_json", action="store_true")
    v4_stage4.add_argument("--case", required=True)
    v4_stage4.add_argument("--resume")
    v4_stage4.add_argument("--seed", default="default")
    v4_stage4.add_argument("--allow-fake-derivation", action="store_true")
    v4_stage4.add_argument("--db")
    v4_stage4.add_argument("--object-root")
    v4_stage4.set_defaults(handler=command_v4_stage4)

    v4_stage5 = sub.add_parser("v4-stage5", help="Assign motion/SFX into MotionAudioPlan")
    v4_stage5.add_argument("--json", dest="sub_json", action="store_true")
    v4_stage5.add_argument("--case", required=True)
    v4_stage5.add_argument("--resume")
    v4_stage5.add_argument("--seed", default="default")
    v4_stage5.add_argument("--sfx-profile", default="normal")
    v4_stage5.set_defaults(handler=command_v4_stage5)

    v4_stage6 = sub.add_parser("v4-stage6", help="Anchor timing and compile Remotion timeline")
    v4_stage6.add_argument("--json", dest="sub_json", action="store_true")
    v4_stage6.add_argument("--case", required=True)
    v4_stage6.add_argument("--resume", required=True)
    v4_stage6.add_argument("--phase", choices=["anchor", "compile-render"])
    v4_stage6.add_argument("--postroll-frames", type=int, default=0)
    v4_stage6.add_argument("--object-root")
    v4_stage6.add_argument("--render", action="store_true", help="Run Remotion V4Timeline + FFmpeg mix")
    v4_stage6.add_argument(
        "--skip-ffmpeg",
        action="store_true",
        help="With --render, keep silent Remotion MP4 and skip audio mix",
    )
    v4_stage6.set_defaults(handler=command_v4_stage6)

    v4_assets = sub.add_parser("v4-assets", help="Manage the V4 asset repository")
    v4_assets.add_argument("--json", dest="sub_json", action="store_true")
    v4_assets_sub = v4_assets.add_subparsers(dest="v4_assets_command", required=True)
    v4_migrate = v4_assets_sub.add_parser("migrate-legacy")
    v4_migrate.add_argument("--dry-run", action="store_true")
    v4_migrate.add_argument("--db")
    v4_migrate.add_argument("--object-root")
    v4_migrate.set_defaults(handler=command_v4_assets_migrate)
    v4_import = v4_assets_sub.add_parser("import")
    v4_import.add_argument("--manifest", required=True)
    v4_import.add_argument("--db")
    v4_import.add_argument("--object-root")
    v4_import.set_defaults(handler=command_v4_assets_import)
    v4_inspect = v4_assets_sub.add_parser("inspect")
    v4_inspect.add_argument("--asset-ref")
    v4_inspect.add_argument("--db")
    v4_inspect.set_defaults(handler=command_v4_assets_inspect)
    v4_audit = v4_assets_sub.add_parser("audit")
    v4_audit.add_argument("--db")
    v4_audit.add_argument("--object-root")
    v4_audit.set_defaults(handler=command_v4_assets_audit)

    inspect = sub.add_parser("inspect", help="Inspect a V3 run")
    inspect.add_argument("--json", dest="sub_json", action="store_true")
    inspect.add_argument("--case", required=True)
    inspect.add_argument("--run")
    inspect.set_defaults(handler=command_inspect)

    sfx = sub.add_parser("sfx-register", help="Register the canonical Douyin SFX library")
    sfx.add_argument("--json", dest="sub_json", action="store_true")
    sfx.add_argument("--source-dir", required=True)
    sfx.add_argument("--output", default="assets/audio/sfx")
    sfx.set_defaults(handler=command_sfx_register)

    site_entries = sub.add_parser("site-entry-batch", help="Generate cached GPT Image keyframes for all website feature-entry screenshots")
    site_entries.add_argument("--json", dest="sub_json", action="store_true")
    site_entries.add_argument("--source", default="assets/sites")
    site_entries.add_argument("--output", default="assets/derived/sites/柯幻熊猫/文生图/功能入口")
    site_entries.add_argument("--workers", type=int, default=3)
    site_entries.add_argument("--force", action="store_true")
    site_entries.set_defaults(handler=command_site_entry_batch)

    site_params = sub.add_parser("site-params-sequence", help="Generate complete base, stage, and final parameter-page flower-text frames")
    site_params.add_argument("--json", dest="sub_json", action="store_true")
    site_params.add_argument("--source", default="assets/sites")
    site_params.add_argument("--output", default="assets/derived/sites/柯幻熊猫/文生图/参数面板序列")
    site_params.add_argument("--include")
    site_params.add_argument("--exclude", action="append", default=[])
    site_params.add_argument("--workers", type=int, default=2)
    site_params.add_argument("--force", action="store_true")
    site_params.set_defaults(handler=command_site_params_sequence)

    editor_flow = sub.add_parser("editor-flow", help="Generate and register a fixed local-edit interaction sequence")
    editor_flow.add_argument("--json", dest="sub_json", action="store_true")
    editor_flow.add_argument("--artwork", required=True, help="Result/reference artwork loaded into both editor states")
    editor_flow.add_argument("--editor-template", required=True)
    editor_flow.add_argument("--modal-template", required=True)
    editor_flow.add_argument("--semantic-path", action="append", required=True)
    editor_flow.add_argument("--output", default="assets/derived/workflow_scenes")
    editor_flow.add_argument("--focus-x", type=float, default=0.80)
    editor_flow.add_argument("--focus-y", type=float, default=0.70)
    editor_flow.add_argument("--focus-w", type=float, default=0.13)
    editor_flow.add_argument("--focus-h", type=float, default=0.17)
    editor_flow.add_argument("--force", action="store_true")
    editor_flow.set_defaults(handler=command_editor_flow)

    import_materials = sub.add_parser("import-video-materials", help="Import and register curated external image materials")
    import_materials.add_argument("--json", dest="sub_json", action="store_true")
    import_materials.add_argument("--source", required=True)
    import_materials.set_defaults(handler=command_import_video_materials)

    cover = sub.add_parser("cover-postprocess", help="Generate a V2-style GPT Image cover and prepend exactly one frame after rendering")
    cover.add_argument("--json", dest="sub_json", action="store_true")
    cover.add_argument("--case", required=True)
    cover.add_argument("--run")
    cover.add_argument("--spec", help="Defaults to <case>/input/cover.json")
    cover.set_defaults(handler=command_cover_postprocess)

    cases_export = sub.add_parser("cases-export", help="Copy every final case video into one destination folder")
    cases_export.add_argument("--json", dest="sub_json", action="store_true")
    cases_export.add_argument("--cases", default="cases")
    cases_export.add_argument("--destination", required=True)
    cases_export.set_defaults(handler=command_cases_export)

    cases_clean = sub.add_parser("cases-clean", help="Remove every direct child case directory after export")
    cases_clean.add_argument("--json", dest="sub_json", action="store_true")
    cases_clean.add_argument("--cases", default="cases")
    cases_clean.add_argument("--export-manifest", help="Require the export manifest before deleting cases")
    cases_clean.set_defaults(handler=command_cases_clean)
    return parser


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    args.json = args.json or getattr(args, "sub_json", False)
    try:
        result = args.handler(args)
    except Exception as exc:  # noqa: BLE001
        result = _exception_result(exc)
    _print(result, args.json)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
