from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from utils.skill_path import require_skill_root


PROMPTS = {
    "material": "references/prompts/material_understanding.md",
    "script": "references/prompts/script_director.md",
    "timeline": "references/prompts/timeline_director.md",
}


def load_json(path: Path, default: Any) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_text(path: Path, default: str = "") -> str:
    if not path.is_file():
        return default
    return path.read_text(encoding="utf-8")


def compact_asset(asset: dict[str, Any], insight: dict[str, Any] | None) -> dict[str, Any]:
    metadata = asset.get("metadata", {}) if isinstance(asset.get("metadata"), dict) else {}
    payload = {
        "id": asset.get("id"),
        "type": asset.get("type"),
        "filename": asset.get("filename"),
        "relative_source": asset.get("relative_source"),
        "source": asset.get("source"),
        "mime_type": asset.get("mime_type"),
        "width": metadata.get("width"),
        "height": metadata.get("height"),
        "aspect_ratio": metadata.get("aspect_ratio"),
        "duration": metadata.get("duration"),
        "probe_ok": metadata.get("probe_ok"),
        "role": asset.get("role"),
        "description": asset.get("description"),
        "visible_text": asset.get("visible_text", []),
        "supported_claims": asset.get("supported_claims", []),
        "quality": asset.get("quality", {}),
    }
    if insight:
        payload["existing_review"] = {
            "vision_summary": insight.get("vision_summary", ""),
            "page_or_scene_role": insight.get("page_or_scene_role", ""),
            "recommended_usage": insight.get("recommended_usage", ""),
            "display_risk": insight.get("display_risk", []),
            "layout_advice": insight.get("layout_advice", ""),
            "needs_review": insight.get("needs_review", True),
        }
    return payload


def material_insights(case_dir: Path) -> dict[str, dict[str, Any]]:
    understanding = load_json(case_dir / "material_understanding.json", {"materials": []})
    materials = understanding.get("materials", []) if isinstance(understanding, dict) else []
    return {
        str(item.get("asset_id")): item
        for item in materials
        if isinstance(item, dict) and item.get("asset_id")
    }


def copywriting_context(skill_root: Path, input_data: dict[str, Any]) -> dict[str, Any]:
    request = input_data.get("request", {}) if isinstance(input_data.get("request"), dict) else {}
    brand_profile = str(request.get("brand_profile") or "")
    if "科幻熊猫" not in brand_profile:
        return {}
    rules = read_text(skill_root / "references" / "copywriting-rules.md")
    options = read_text(skill_root / "references" / "copywriting-options.md")
    return {
        "brand_profile": brand_profile,
        "copywriting_rules_excerpt": rules[:6000],
        "copywriting_options_excerpt": options[:4000],
    }


def build_context(case_dir: Path, skill_root: Path, stage: str) -> dict[str, Any]:
    input_data = load_json(case_dir / "input.json", {})
    manifest = load_json(case_dir / "asset_manifest.json", {"assets": []})
    assets = manifest.get("assets", []) if isinstance(manifest, dict) else []
    insights = material_insights(case_dir)

    prompts = {}
    selected = PROMPTS if stage == "all" else {stage: PROMPTS[stage]}
    for name, rel in selected.items():
        prompts[name] = {
            "path": rel,
            "content": read_text(skill_root / rel),
        }

    context = {
        "schema_version": 1,
        "status": "ready_for_planner",
        "case_dir": str(case_dir),
        "stage": stage,
        "input": input_data,
        "prompts": prompts,
        "assets": [compact_asset(asset, insights.get(str(asset.get("id")))) for asset in assets if isinstance(asset, dict)],
        "website_knowledge": load_json(case_dir / "website_knowledge.json", {}),
        "feature_cards": load_json(case_dir / "feature_cards.json", {}),
        "browser_materials": load_json(case_dir / "browser_materials.json", {}),
        "operation_recipes": load_json(case_dir / "operation_recipes.json", {}),
        "material_understanding": load_json(case_dir / "material_understanding.json", {}),
        "video_script": load_json(case_dir / "video_script.json", {}),
        "copywriting_context": copywriting_context(skill_root, input_data),
        "output_contract": {
            "material_output": "material_understanding.json",
            "script_output": "video_script.json",
            "accept_command": "python scripts/accept_planner_output.py --case <CASE_DIR> --kind <material|script> --input <MODEL_OUTPUT_JSON> --json",
        },
        "non_negotiable_rules": [
            "Do not rely on filenames alone for visual decisions.",
            "Use asset IDs exactly as listed in asset_manifest.json.",
            "Do not include the fixed outro in script or visual planning.",
            "Do not invent product claims unsupported by material evidence.",
            "Return JSON only for planner outputs.",
        ],
    }
    return context


def write_brief(context: dict[str, Any], path: Path) -> None:
    request = context.get("input", {}).get("request", {}) if isinstance(context.get("input"), dict) else {}
    lines = [
        "# Planner Brief",
        "",
        f"Case: `{context.get('case_dir')}`",
        f"Stage: `{context.get('stage')}`",
        f"Goal: {request.get('video_goal', '')}",
        f"Target duration: {request.get('duration', '')}",
        f"Brand profile: {request.get('brand_profile', '')}",
        "",
        "## Assets",
    ]
    for asset in context.get("assets", []):
        lines.append(
            f"- `{asset.get('id')}` {asset.get('type')} {asset.get('filename')} "
            f"({asset.get('width')}x{asset.get('height')}, aspect={asset.get('aspect_ratio')})"
        )
    lines.extend(
        [
            "",
            "## Required Output",
            "",
            "Use the prompt contract embedded in `planner_context.json`. Return JSON only, then pass it through:",
            "",
            "```powershell",
            "python scripts\\accept_planner_output.py --case <CASE_DIR> --kind <material|script> --input <MODEL_OUTPUT_JSON> --json",
            "```",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    if not case_dir.is_dir():
        raise FileNotFoundError(f"case directory not found: {case_dir}")
    if args.stage != "all" and args.stage not in PROMPTS:
        raise ValueError(f"unsupported stage: {args.stage}")

    skill_root = require_skill_root(Path(__file__).resolve())
    context = build_context(case_dir, skill_root, args.stage)

    out_dir = case_dir / "output" / "planner"
    out_dir.mkdir(parents=True, exist_ok=True)
    context_path = out_dir / f"{args.stage}_planner_context.json"
    brief_path = out_dir / f"{args.stage}_planner_brief.md"
    context_path.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_brief(context, brief_path)

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "stage": args.stage,
            "planner_context": str(context_path),
            "planner_brief": str(brief_path),
            "asset_count": len(context.get("assets", [])),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare model-ready planner context for video-agent cases.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--stage", choices=("all", "material", "script", "timeline"), default="all")
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
        print(f"Planner context: {output['data']['planner_context']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
