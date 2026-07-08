from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


MODES = ("draft", "standard", "strict")


@dataclass(frozen=True)
class ModePolicy:
    gpt_image: bool
    voice_qa: bool
    contact_sheet: bool
    render_qa: bool
    hygiene: bool
    contact_frames: int


POLICIES = {
    "draft": ModePolicy(
        gpt_image=False,
        voice_qa=False,
        contact_sheet=False,
        render_qa=False,
        hygiene=False,
        contact_frames=8,
    ),
    "standard": ModePolicy(
        gpt_image=True,
        voice_qa=True,
        contact_sheet=True,
        render_qa=True,
        hygiene=False,
        contact_frames=12,
    ),
    "strict": ModePolicy(
        gpt_image=True,
        voice_qa=True,
        contact_sheet=True,
        render_qa=True,
        hygiene=True,
        contact_frames=24,
    ),
}


def rel(path: Path) -> str:
    return str(path)


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def newest_mtime(paths: list[Path]) -> float:
    values = [path.stat().st_mtime for path in paths if path.is_file()]
    return max(values) if values else 0.0


def oldest_mtime(paths: list[Path]) -> float:
    values = [path.stat().st_mtime for path in paths if path.is_file()]
    return min(values) if values and len(values) == len(paths) else 0.0


def outputs_current(outputs: list[Path], deps: list[Path]) -> bool:
    if not outputs or any(not path.is_file() for path in outputs):
        return False
    dep_time = newest_mtime(deps)
    if dep_time <= 0:
        return True
    return oldest_mtime(outputs) >= dep_time


def run_command(cmd: list[str], cwd: Path, dry_run: bool) -> dict[str, Any]:
    if dry_run:
        return {"status": "planned", "command": cmd}
    proc = subprocess.run(
        cmd,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "command failed: "
            + " ".join(cmd)
            + "\nSTDOUT:\n"
            + proc.stdout[-4000:]
            + "\nSTDERR:\n"
            + proc.stderr[-4000:]
        )
    return {"status": "ran", "command": cmd, "stdout": proc.stdout.strip()}


def step(
    *,
    name: str,
    cmd: list[str],
    cwd: Path,
    outputs: list[Path],
    deps: list[Path],
    force: bool,
    dry_run: bool,
    always: bool = False,
) -> dict[str, Any]:
    if not always and not force and outputs_current(outputs, deps):
        return {
            "name": name,
            "status": "skipped_current",
            "outputs": [rel(path) for path in outputs],
        }
    result = run_command(cmd, cwd, dry_run)
    return {"name": name, **result, "outputs": [rel(path) for path in outputs]}


def script_cmd(script: str, *args: str) -> list[str]:
    return [sys.executable, str(Path("scripts") / script), *args]


def should_use_gpt(args: argparse.Namespace, policy: ModePolicy) -> bool:
    if args.gpt_image == "always":
        return True
    if args.gpt_image == "never":
        return False
    return policy.gpt_image


RESULT_STEPS = {"result_crop", "result_export", "result_gallery"}


def is_website_case(input_data: dict[str, Any]) -> bool:
    request = input_data.get("request", {}) if isinstance(input_data.get("request"), dict) else {}
    return bool(str(request.get("target_url") or "").strip())


def asset_workflow_step(asset: dict[str, Any]) -> str:
    image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
    return str(image_resource.get("workflow_step") or "").strip().lower()


def event_claims_real_result(event: dict[str, Any], assets: dict[str, dict[str, Any]]) -> bool:
    evidence = str(event.get("evidence_binding") or "").strip().lower()
    if "real_result" in evidence or evidence in {"real_generated_result", "real_result_image"}:
        return True
    if str(event.get("operation_status") or "").strip().lower() == "verified_result":
        return True
    for asset_id in event.get("asset_ids", []):
        asset = assets.get(str(asset_id), {})
        if not isinstance(asset, dict):
            continue
        source = str(asset.get("source") or "").replace("\\", "/").lower()
        role = str(asset.get("role") or "").lower()
        if asset_workflow_step(asset) in RESULT_STEPS:
            return True
        if "assets/results/" in source:
            return True
    return False


def source_asset_ids(asset: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("source_asset_id",):
        value = str(asset.get(key) or "").strip()
        if value:
            values.append(value)
    image_resource = asset.get("image_resource", {}) if isinstance(asset.get("image_resource"), dict) else {}
    for key in ("source_asset_id", "origin_asset_id"):
        value = str(image_resource.get(key) or "").strip()
        if value:
            values.append(value)
    return values


def normalized_source(value: Any) -> str:
    return str(value or "").replace("\\", "/").strip().lower()


def asset_derives_from(
    asset_id: str,
    allowed_result_ids: set[str],
    allowed_result_sources: set[str],
    assets: dict[str, dict[str, Any]],
    seen: set[str] | None = None,
) -> bool:
    if asset_id in allowed_result_ids:
        return True
    if seen is None:
        seen = set()
    if asset_id in seen:
        return False
    seen.add(asset_id)
    asset = assets.get(asset_id, {})
    if not isinstance(asset, dict):
        return False
    if normalized_source(asset.get("source")) in allowed_result_sources:
        return True
    return any(
        asset_derives_from(source_id, allowed_result_ids, allowed_result_sources, assets, seen)
        for source_id in source_asset_ids(asset)
    )


def receipt_result_refs(case_dir: Path, receipt_ids: list[str]) -> tuple[set[str], set[str]]:
    receipts_payload = load_json(case_dir / "generation_receipts.json", {"receipts": []})
    receipts = receipts_payload.get("receipts", []) if isinstance(receipts_payload, dict) else []
    by_id = {
        str(receipt.get("id")): receipt
        for receipt in receipts
        if isinstance(receipt, dict) and receipt.get("id")
    }
    missing = [receipt_id for receipt_id in receipt_ids if receipt_id not in by_id]
    if missing:
        raise ValueError(f"required generation receipt not found: {', '.join(missing)}")
    result_ids: set[str] = set()
    result_sources: set[str] = set()
    for receipt_id in receipt_ids:
        receipt = by_id[receipt_id]
        if str(receipt.get("status") or "").lower() != "verified_result":
            raise ValueError(f"required generation receipt is not verified_result: {receipt_id}")
        for asset_id in receipt.get("result_asset_ids", []):
            value = str(asset_id).strip()
            if value:
                result_ids.add(value)
        for source in receipt.get("result_sources", []):
            value = normalized_source(source)
            if value:
                result_sources.add(value)
    if not result_ids:
        raise ValueError(f"required generation receipts have no result_asset_ids: {', '.join(receipt_ids)}")
    return result_ids, result_sources


def verify_result_receipt_binding(
    *,
    case_dir: Path,
    project_path: Path,
    receipt_ids: list[str],
    allow_existing_results: bool,
) -> dict[str, Any]:
    project = load_json(project_path, {})
    if not isinstance(project, dict):
        raise ValueError(f"project JSON is missing or invalid for result receipt check: {project_path}")
    input_data = project.get("inputs", {}) if isinstance(project.get("inputs"), dict) else load_json(case_dir / "input.json", {})
    assets_list = project.get("assets", [])
    assets = {
        str(asset.get("id")): asset
        for asset in assets_list
        if isinstance(asset, dict) and asset.get("id")
    }
    result_events = [
        event
        for event in project.get("visual_track", [])
        if isinstance(event, dict) and event_claims_real_result(event, assets)
    ]
    if not result_events:
        return {"name": "verify_result_receipt_binding", "status": "skipped_no_result_claims"}
    if is_website_case(input_data) and not receipt_ids and not allow_existing_results:
        raise ValueError(
            "website result video requires --receipt-id for the current CDP generation. "
            "Do not let agents reuse demo/case assets as results; register the fresh CDP output first, "
            "then pass its receipt id, e.g. --receipt-id receipt_activity_meichen_20260708."
        )
    if allow_existing_results and not receipt_ids:
        return {
            "name": "verify_result_receipt_binding",
            "status": "skipped_allow_existing_results",
            "result_event_count": len(result_events),
        }

    allowed_result_ids, allowed_result_sources = receipt_result_refs(case_dir, receipt_ids)
    violations: list[str] = []
    checked_asset_ids: set[str] = set()
    for idx, event in enumerate(result_events):
        for asset_id in event.get("asset_ids", []):
            asset_id = str(asset_id)
            if not asset_id:
                continue
            checked_asset_ids.add(asset_id)
            if not asset_derives_from(asset_id, allowed_result_ids, allowed_result_sources, assets):
                violations.append(f"visual_track[{idx}] asset {asset_id} is not from required receipt(s)")
    if violations:
        raise ValueError(
            "refusing to render with unapproved result assets: "
            + "; ".join(violations)
            + ". Use only result_asset_ids from the current generation_receipts.json receipt, "
            "or GPT derivatives whose source_asset_id points to those assets."
        )
    return {
        "name": "verify_result_receipt_binding",
        "status": "passed",
        "receipt_ids": receipt_ids,
        "allowed_result_asset_ids": sorted(allowed_result_ids),
        "allowed_result_sources": sorted(allowed_result_sources),
        "checked_asset_ids": sorted(checked_asset_ids),
        "result_event_count": len(result_events),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[1]
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")
    policy = POLICIES[args.mode]
    label = args.label or f"{args.mode}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    force_all = args.no_cache or args.force

    paths = {
        "input": case_dir / "input.json",
        "script": case_dir / "video_script.json",
        "voice_plan": case_dir / "voice_plan.json",
        "voice_audio": case_dir / "audio" / "voice.mp3",
        "minimax_alignment": case_dir / "output" / "minimax" / "minimax_alignment.json",
        "voice_report": case_dir / "output" / "minimax" / "voice_report.json",
        "voice_qa": case_dir / "output" / "reports" / "voice_qa_report.json",
        "subtitle_track": case_dir / "subtitle_track.json",
        "image_resources": case_dir / "image_resources.json",
        "asset_manifest": case_dir / "asset_manifest.json",
        "project": case_dir / "video_project.json",
        "gpt_project": case_dir / "video_project.gpt_image.json",
        "render": case_dir / "output" / "versions" / f"{label}.mp4",
        "render_report": case_dir / "output" / "reports" / f"{label}_render_report.json",
        "contact_sheet": case_dir / "output" / "qa" / f"{label}_contact_sheet.jpg",
        "render_qa": case_dir / "output" / "reports" / f"{label}_qa_report.json",
    }
    if not paths["script"].is_file():
        raise FileNotFoundError(f"reviewed video_script.json is required before pipeline run: {paths['script']}")

    gpt_enabled = should_use_gpt(args, policy)
    steps: list[dict[str, Any]] = []

    steps.append(
        step(
            name="create_voice_plan",
            cmd=script_cmd("create_voice_plan.py", "--case", rel(case_dir), "--json"),
            cwd=root,
            outputs=[paths["voice_plan"]],
            deps=[paths["script"]],
            force=force_all,
            dry_run=args.dry_run,
        )
    )
    steps.append(
        step(
            name="generate_voice_minimax",
            cmd=script_cmd("generate_voice_minimax.py", "--case", rel(case_dir), "--json"),
            cwd=root,
            outputs=[paths["voice_audio"], paths["minimax_alignment"], paths["voice_report"]],
            deps=[paths["voice_plan"]],
            force=force_all or args.force_voice,
            dry_run=args.dry_run,
        )
    )
    steps.append(
        step(
            name="build_subtitle_track",
            cmd=script_cmd("build_subtitle_track.py", "--case", rel(case_dir), "--json"),
            cwd=root,
            outputs=[paths["subtitle_track"]],
            deps=[paths["script"], paths["minimax_alignment"]],
            force=force_all,
            dry_run=args.dry_run,
        )
    )
    if policy.voice_qa or args.voice_qa:
        steps.append(
            step(
                name="check_voice_qa",
                cmd=script_cmd("check_voice_qa.py", "--case", rel(case_dir), "--json"),
                cwd=root,
                outputs=[paths["voice_qa"]],
                deps=[paths["voice_audio"], paths["minimax_alignment"], paths["voice_plan"]],
                force=force_all,
                dry_run=args.dry_run,
            )
        )
    else:
        steps.append({"name": "check_voice_qa", "status": "skipped_by_mode"})

    steps.append(
        step(
            name="build_video_project",
            cmd=script_cmd("build_video_project.py", "--case", rel(case_dir), "--json"),
            cwd=root,
            outputs=[paths["project"]],
            deps=[
                paths["input"],
                paths["script"],
                paths["subtitle_track"],
                paths["voice_report"],
                paths["image_resources"],
                paths["asset_manifest"],
            ],
            force=force_all,
            dry_run=args.dry_run,
        )
    )
    steps.append(
        step(
            name="validate_video_project_base",
            cmd=script_cmd("validate_video_project.py", "--case", rel(case_dir), "--project", rel(paths["project"]), "--strict", "--json"),
            cwd=root,
            outputs=[],
            deps=[],
            force=True,
            dry_run=args.dry_run,
            always=True,
        )
    )
    steps.append(
        verify_result_receipt_binding(
            case_dir=case_dir,
            project_path=paths["project"],
            receipt_ids=list(args.receipt_id or []),
            allow_existing_results=args.allow_existing_results,
        )
        if not args.dry_run or paths["project"].is_file()
        else {"name": "verify_result_receipt_binding_base", "status": "planned"}
    )

    render_project = paths["project"]
    if gpt_enabled:
        gpt_cmd = script_cmd("prepare_gpt_image_keyframes.py", "--case", rel(case_dir), "--project", rel(paths["project"]), "--json")
        if args.force_gpt or force_all:
            gpt_cmd.append("--force")
        if args.gpt_dry_run:
            gpt_cmd.append("--dry-run")
        steps.append(
            step(
                name="prepare_gpt_image_keyframes",
                cmd=gpt_cmd,
                cwd=root,
                outputs=[paths["gpt_project"]],
                deps=[paths["project"]],
                force=force_all or args.force_gpt,
                dry_run=args.dry_run,
            )
        )
        render_project = paths["gpt_project"]
    else:
        steps.append({"name": "prepare_gpt_image_keyframes", "status": "skipped_by_mode"})

    steps.append(
        step(
            name="validate_video_project_render",
            cmd=script_cmd("validate_video_project.py", "--case", rel(case_dir), "--project", rel(render_project), "--strict", "--json"),
            cwd=root,
            outputs=[],
            deps=[],
            force=True,
            dry_run=args.dry_run,
            always=True,
        )
    )
    steps.append(
        verify_result_receipt_binding(
            case_dir=case_dir,
            project_path=render_project,
            receipt_ids=list(args.receipt_id or []),
            allow_existing_results=args.allow_existing_results,
        )
        if not args.dry_run or render_project.is_file()
        else {"name": "verify_result_receipt_binding_render", "status": "planned"}
    )

    render_cmd = script_cmd("render_simple_ffmpeg.py", "--case", rel(case_dir), "--project", rel(render_project), "--label", label, "--json")
    if args.skip_outro:
        render_cmd.append("--skip-outro")
    steps.append(
        step(
            name="render_simple_ffmpeg",
            cmd=render_cmd,
            cwd=root,
            outputs=[paths["render"], paths["render_report"]],
            deps=[render_project, paths["voice_audio"], paths["subtitle_track"]],
            force=force_all or args.force_render,
            dry_run=args.dry_run,
        )
    )

    if policy.contact_sheet or args.contact_sheet:
        steps.append(
            step(
                name="make_contact_sheet",
                cmd=script_cmd(
                    "make_contact_sheet.py",
                    "--case",
                    rel(case_dir),
                    "--video",
                    rel(paths["render"]),
                    "--label",
                    label,
                    "--max-frames",
                    str(args.max_frames or policy.contact_frames),
                    "--json",
                ),
                cwd=root,
                outputs=[paths["contact_sheet"]],
                deps=[paths["render"], render_project],
                force=force_all,
                dry_run=args.dry_run,
            )
        )
    else:
        steps.append({"name": "make_contact_sheet", "status": "skipped_by_mode"})

    if policy.render_qa or args.render_qa:
        steps.append(
            step(
                name="render_qa",
                cmd=script_cmd("render_qa.py", "--case", rel(case_dir), "--project", rel(render_project), "--video", rel(paths["render"]), "--json"),
                cwd=root,
                outputs=[paths["render_qa"]],
                deps=[paths["render"], render_project, paths["contact_sheet"]],
                force=force_all,
                dry_run=args.dry_run,
            )
        )
    else:
        steps.append({"name": "render_qa", "status": "skipped_by_mode"})

    if policy.hygiene or args.hygiene:
        steps.append(
            step(
                name="check_case_hygiene",
                cmd=script_cmd("check_case_hygiene.py", "--case", rel(case_dir), "--json"),
                cwd=root,
                outputs=[],
                deps=[],
                force=True,
                dry_run=args.dry_run,
                always=True,
            )
        )
    else:
        steps.append({"name": "check_case_hygiene", "status": "skipped_by_mode"})

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "mode": args.mode,
            "label": label,
            "case_dir": rel(case_dir),
            "render_project": rel(render_project),
            "video": rel(paths["render"]),
            "policy": policy.__dict__,
            "gpt_image_enabled": gpt_enabled,
            "dry_run": bool(args.dry_run),
            "steps": steps,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Pipeline V2 with draft/standard/strict validation modes.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--mode", choices=MODES, default="standard")
    parser.add_argument("--label")
    parser.add_argument("--gpt-image", choices=("auto", "always", "never"), default="auto")
    parser.add_argument(
        "--receipt-id",
        action="append",
        default=[],
        help="Required current-generation receipt id for website real-result videos. Repeat for multiple receipts.",
    )
    parser.add_argument(
        "--allow-existing-results",
        action="store_true",
        help="Allow old/demo result assets without a receipt id. Use only for explicit packaging tests.",
    )
    parser.add_argument("--gpt-dry-run", action="store_true", help="Use GPT image rewrite path without calling the image API.")
    parser.add_argument("--voice-qa", action="store_true", help="Run voice QA even when the mode would skip it.")
    parser.add_argument("--contact-sheet", action="store_true", help="Build contact sheet even when the mode would skip it.")
    parser.add_argument("--render-qa", action="store_true", help="Run render QA even when the mode would skip it.")
    parser.add_argument("--hygiene", action="store_true", help="Run case hygiene even when the mode would skip it.")
    parser.add_argument("--max-frames", type=int, help="Override contact-sheet frame count.")
    parser.add_argument("--force", action="store_true", help="Re-run all cacheable stages.")
    parser.add_argument("--no-cache", action="store_true", help="Alias for forceful re-run of cacheable stages.")
    parser.add_argument("--force-voice", action="store_true")
    parser.add_argument("--force-gpt", action="store_true")
    parser.add_argument("--force-render", action="store_true")
    parser.add_argument("--skip-outro", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Print the planned steps without running commands.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        data = output["data"]
        print(f"Pipeline {data['mode']} complete: {data['video']}")
        for item in data["steps"]:
            print(f"- {item['name']}: {item['status']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
