from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from video_agent.assets import build_catalog
from video_agent.assets.site_entry_batch import approve_site_entry_manifest, generate_site_entry_keyframes
from video_agent.assets.site_params_sequence import approve_parameter_frame_sequences, generate_parameter_frame_sequences
from video_agent.assets.video_material_import import import_video_material_images
from video_agent.audio.register import register_sfx_library
from video_agent.contracts import AssetCatalog, CaseConfig
from video_agent.cover import postprocess_cover
from video_agent.io import load_json, load_model, write_json_atomic
from video_agent.orchestrator import Orchestrator
from video_agent.runtime import RunContext, STAGES


def _print(value: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        for key, item in value.items():
            print(f"{key}: {item}")


def command_catalog(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.assets).resolve()
    output = Path(args.output).resolve() if args.output else root / "catalog.json"
    catalog = build_catalog(root, output)
    return {"ok": True, "catalog": output.as_posix(), "assets": len(catalog.assets), "warnings": len(catalog.warnings)}


def command_run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    context = RunContext.open(case_dir, args.resume) if args.resume else RunContext.create(case_dir)
    final_video = Orchestrator(context).run(from_stage=args.from_stage, until_stage=args.until_stage)
    return {"ok": True, "run_id": context.run_id, "run_dir": context.run_dir.as_posix(), "final_video": final_video.as_posix() if final_video else None}


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
    config = CaseConfig(case_id=args.case_id, goal=args.goal, feature_path=args.feature_path or [])
    write_json_atomic(case_dir / "case.json", config)
    (case_dir / "input").mkdir()
    return {"ok": True, "case": case_dir.as_posix(), "case_json": (case_dir / "case.json").as_posix()}


def command_asset_review(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    run_id = args.run or load_json(case_dir / "latest_run.json")["run_id"]
    catalog_path = case_dir / "runs" / run_id / "asset_catalog.json"
    catalog = load_model(catalog_path, AssetCatalog)
    asset = next((item for item in catalog.assets if item.asset_id == args.asset_id), None)
    if asset is None:
        raise ValueError(f"asset not found in run catalog: {args.asset_id}")
    if args.reject:
        if not args.reason:
            raise ValueError("--reason is required when rejecting an asset")
        asset.quality.status = "rejected"
        asset.quality.rejection_reason = args.reason
    else:
        asset.quality.status = "human_approved"
        asset.quality.rejection_reason = None
        if "human_reviewed" not in asset.quality.checks:
            asset.quality.checks.append("human_reviewed")
    write_json_atomic(catalog_path, catalog)
    return {"ok": True, "run_id": run_id, "asset_id": asset.asset_id, "status": asset.quality.status}


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


def command_site_entry_approve(args: argparse.Namespace) -> dict[str, Any]:
    result = approve_site_entry_manifest(Path(args.manifest).resolve())
    return {"ok": True, **result, "manifest": Path(args.manifest).resolve().as_posix()}


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


def command_site_params_sequence_approve(args: argparse.Namespace) -> dict[str, Any]:
    manifest = Path(args.manifest).resolve()
    result = approve_parameter_frame_sequences(manifest)
    return {"ok": True, **result, "manifest": manifest.as_posix()}


def command_import_video_materials(args: argparse.Namespace) -> dict[str, Any]:
    result = import_video_material_images(Path(__file__).resolve().parents[1], Path(args.source).resolve())
    return {"ok": True, **result}


def command_cover_postprocess(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).resolve()
    run_id = args.run or load_json(case_dir / "latest_run.json")["run_id"]
    run_dir = case_dir / "runs" / run_id
    spec = Path(args.spec).resolve() if args.spec else case_dir / "input" / "cover.json"
    report = postprocess_cover(Path(__file__).resolve().parents[1], case_dir, run_dir, spec)
    return {
        "ok": True,
        "run_id": run_id,
        "video": (run_dir / "final" / "video.mp4").as_posix(),
        "cover": report["cover"],
        "crop_preview": report["crop_preview"],
        "cover_frames": report["cover_frames"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="video-agent", description="Video Agent V3 material-first video compiler")
    parser.add_argument("--json", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

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
    init.set_defaults(handler=command_init)

    run = sub.add_parser("run", help="Run the single V3 production DAG")
    run.add_argument("--json", dest="sub_json", action="store_true")
    run.add_argument("--case", required=True)
    run.add_argument("--resume")
    run.add_argument("--from-stage", choices=STAGES)
    run.add_argument("--until-stage", choices=STAGES)
    run.set_defaults(handler=command_run)

    inspect = sub.add_parser("inspect", help="Inspect a V3 run")
    inspect.add_argument("--json", dest="sub_json", action="store_true")
    inspect.add_argument("--case", required=True)
    inspect.add_argument("--run")
    inspect.set_defaults(handler=command_inspect)

    review = sub.add_parser("asset-review", help="Approve or reject a derived asset in one run")
    review.add_argument("--json", dest="sub_json", action="store_true")
    review.add_argument("--case", required=True)
    review.add_argument("--run")
    review.add_argument("--asset-id", required=True)
    decision = review.add_mutually_exclusive_group(required=True)
    decision.add_argument("--approve", action="store_true")
    decision.add_argument("--reject", action="store_true")
    review.add_argument("--reason")
    review.set_defaults(handler=command_asset_review)

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

    approve_entries = sub.add_parser("site-entry-approve", help="Mark every generated site-entry keyframe in a manifest as human approved")
    approve_entries.add_argument("--json", dest="sub_json", action="store_true")
    approve_entries.add_argument("--manifest", default="assets/derived/sites/柯幻熊猫/文生图/功能入口/manifest.json")
    approve_entries.set_defaults(handler=command_site_entry_approve)

    site_params = sub.add_parser("site-params-sequence", help="Generate complete base, stage, and final parameter-page flower-text frames")
    site_params.add_argument("--json", dest="sub_json", action="store_true")
    site_params.add_argument("--source", default="assets/sites")
    site_params.add_argument("--output", default="assets/derived/sites/柯幻熊猫/文生图/参数面板序列")
    site_params.add_argument("--include")
    site_params.add_argument("--exclude", action="append", default=[])
    site_params.add_argument("--workers", type=int, default=2)
    site_params.add_argument("--force", action="store_true")
    site_params.set_defaults(handler=command_site_params_sequence)

    approve_params = sub.add_parser("site-params-sequence-approve", help="Mark every generated parameter frame sequence as human approved")
    approve_params.add_argument("--json", dest="sub_json", action="store_true")
    approve_params.add_argument("--manifest", default="assets/derived/sites/柯幻熊猫/文生图/参数面板序列/manifest.json")
    approve_params.set_defaults(handler=command_site_params_sequence_approve)

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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    args.json = args.json or getattr(args, "sub_json", False)
    try:
        result = args.handler(args)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "error": exc.__class__.__name__, "message": str(exc)}
    _print(result, args.json)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
