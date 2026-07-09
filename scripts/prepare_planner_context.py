from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from utils.skill_path import require_skill_root


PROMPTS = {
    "material": "references/prompts/material_understanding.md",
    "visual_plan": "references/prompts/visual_plan_director.md",
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


def image_resource_map(case_dir: Path) -> dict[str, dict[str, Any]]:
    payload = load_json(case_dir / "image_resources.json", {"resources": []})
    resources = payload.get("resources", []) if isinstance(payload, dict) else []
    return {
        str(item.get("asset_id")): item
        for item in resources
        if isinstance(item, dict) and item.get("asset_id")
    }


def material_insights(case_dir: Path) -> dict[str, dict[str, Any]]:
    understanding = load_json(case_dir / "material_understanding.json", {"materials": []})
    materials = understanding.get("materials", []) if isinstance(understanding, dict) else []
    return {
        str(item.get("asset_id")): item
        for item in materials
        if isinstance(item, dict) and item.get("asset_id")
    }


def compact_pool_resource(item: dict[str, Any]) -> dict[str, Any]:
    layout_plan = item.get("layout_plan", {}) if isinstance(item.get("layout_plan"), dict) else {}
    quality = item.get("quality", {}) if isinstance(item.get("quality"), dict) else {}
    return {
        "resource_id": item.get("id"),
        "asset_id": item.get("asset_id"),
        "filename": item.get("filename"),
        "source": item.get("source"),
        "capture_type": item.get("capture_type"),
        "workflow_step": item.get("workflow_step"),
        "source_workflow_step": item.get("source_workflow_step"),
        "title": item.get("title"),
        "feature_id": item.get("feature_id"),
        "feature_label": item.get("feature_label"),
        "feature_path": item.get("feature_path", []),
        "parent_feature_id": item.get("parent_feature_id"),
        "parent_feature_label": item.get("parent_feature_label"),
        "industry_id": item.get("industry_id"),
        "industry_label": item.get("industry_label"),
        "scene_id": item.get("scene_id"),
        "scene_label": item.get("scene_label"),
        "prompt_inputs": item.get("prompt_inputs", {}),
        "recommended_usage": item.get("recommended_usage", []),
        "layout": layout_plan.get("primary_display_mode"),
        "must_be_visible": layout_plan.get("must_be_visible", []),
        "origin": item.get("origin"),
        "ai_verified": quality.get("ai_verified"),
        "needs_review": quality.get("needs_review"),
        "source_asset_id": item.get("relations", {}).get("source_asset_id") if isinstance(item.get("relations"), dict) else "",
    }


def sort_pool_resources(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            0 if item.get("workflow_step") == "prepared_site_keyframe" else 1,
            0 if item.get("ai_verified") is True else 1,
            str(item.get("filename") or ""),
        ),
    )


def site_asset_pool(case_dir: Path) -> dict[str, Any]:
    payload = load_json(case_dir / "image_resources.json", {"resources": []})
    resources = payload.get("resources", []) if isinstance(payload, dict) else []
    features: dict[str, dict[str, Any]] = {}
    site_home: list[dict[str, Any]] = []

    for item in resources:
        if not isinstance(item, dict):
            continue
        origin = str(item.get("origin") or "")
        workflow_step = str(item.get("workflow_step") or "")
        source = str(item.get("source") or "").replace("\\", "/")
        is_site_screenshot = origin in {"site_screenshot_library", "gpt_image_site_keyframe"} or "assets/sites/" in source
        is_result = workflow_step in {"result_crop", "result_export", "result_gallery", "result_page"}
        if not is_site_screenshot and not is_result:
            continue

        if workflow_step == "home_entry":
            site_home.append(compact_pool_resource(item))
            continue

        feature_id = str(item.get("feature_id") or "").strip()
        if not feature_id:
            continue
        parent_id = str(item.get("parent_feature_id") or "").strip()
        feature_key = f"{parent_id}/{feature_id}" if parent_id else feature_id
        bucket = features.setdefault(
            feature_key,
            {
                "feature_key": feature_key,
                "feature_id": feature_id,
                "feature_label": item.get("feature_label") or "",
                "feature_path": item.get("feature_path") or [],
                "source_module_id": item.get("source_module_id") or "",
                "source_module_label": item.get("source_module_label") or "",
                "parent_feature_id": item.get("parent_feature_id") or "",
                "parent_feature_label": item.get("parent_feature_label") or "",
                "assets_by_role": {
                    "功能入口截图": [],
                    "参数面板截图": [],
                    "AI优化关键帧": [],
                    "结果图": [],
                    "其他": [],
                },
            },
        )
        capture_type = str(item.get("capture_type") or "")
        if workflow_step == "prepared_site_keyframe":
            role = "AI优化关键帧"
        elif capture_type in {"功能入口截图", "参数面板截图"}:
            role = capture_type
        elif is_result:
            role = "结果图"
        else:
            role = "其他"
        bucket["assets_by_role"].setdefault(role, []).append(compact_pool_resource(item))

    for bucket in features.values():
        for role, items in list(bucket["assets_by_role"].items()):
            bucket["assets_by_role"][role] = sort_pool_resources(items)

    ordered_features = sorted(
        features.values(),
        key=lambda item: " / ".join(str(value) for value in item.get("feature_path", [])) or item["feature_key"],
    )
    return {
        "status": "ready" if site_home or ordered_features else "empty",
        "source": "image_resources.json",
        "site_home": site_home,
        "features": ordered_features,
        "storyboard_templates": {
            "single_feature_seed": {
                "required_beats": [
                    {
                        "beat": "platform_home",
                        "use_role": "网站主页截图 / AI优化关键帧",
                        "purpose": "建立平台真实入口，突出文生图入口。",
                        "evidence_binding": "real_screenshot",
                    },
                    {
                        "beat": "feature_entry_path",
                        "use_role": "同功能 功能入口截图 / AI优化关键帧",
                        "purpose": "展示从文生图入口进入目标功能的路径，设计化高亮只用于镜头，不写进旁白。",
                        "evidence_binding": "real_screenshot",
                    },
                    {
                        "beat": "feature_params",
                        "use_role": "同功能 参数面板截图 / AI优化关键帧",
                        "purpose": "展示输入项、上传区、开始生成入口，保持 UI 完整可读。",
                        "evidence_binding": "real_screenshot",
                    },
                    {
                        "beat": "result_showcase",
                        "use_role": "同功能 结果图 / AI优化关键帧",
                        "purpose": "展示真实保存的结果图；如果有多张，优先快切或 gallery，而不是反复展示一张。",
                        "evidence_binding": "real_result",
                    },
                ],
                "minimum_materials": {
                    "site_home": 1,
                    "feature_entry": 1,
                    "feature_form_params": 1,
                    "result_images_recommended": 3,
                },
                "timing_guidance": [
                    "路径和参数图每张至少 1.2s，便于看清 UI。",
                    "结果图快切每张 0.8s-1.6s，重点结果可 1.8s-3.0s。",
                    "字幕描述多场景、多行业、多风格时必须绑定多张结果图或降级文案。",
                ],
            }
        },
        "selection_policy": [
            "同一功能视频优先选择 feature_id 或 feature_key 完全一致的素材。",
            "如果同一功能存在 workflow_step=prepared_site_keyframe 或 quality.ai_verified=true 的 AI优化关键帧，优先选择该素材。",
            "普通文生图功能使用 文生图/<功能> 下的 功能入口截图 和 参数面板截图。",
            "图文广告子功能使用 文生图/图文广告/<子功能> 下的素材，不要把不同子功能互相混用。",
            "只有 workflow_step 为 result_crop/result_export/result_gallery/result_page 的素材可作为结果图。",
            "结果图必须优先匹配同 feature_key 和同 industry_label/scene_label；字幕提到具体行业/场景时不要使用不匹配的结果图。",
            "网站截图只证明流程和界面，不能当作真实生成结果展示。",
        ],
    }


def copywriting_context(skill_root: Path, input_data: dict[str, Any]) -> dict[str, Any]:
    request = input_data.get("request", {}) if isinstance(input_data.get("request"), dict) else {}
    brand_profile = str(request.get("brand_profile") or "")
    if "柯幻熊猫" not in brand_profile:
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
    image_resources_by_asset = image_resource_map(case_dir)

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
        "assets": [
            {
                **compact_asset(asset, insights.get(str(asset.get("id")))),
                "image_resource": image_resources_by_asset.get(str(asset.get("id")), {}),
            }
            for asset in assets
            if isinstance(asset, dict)
        ],
        "website_knowledge": load_json(case_dir / "website_knowledge.json", {}),
        "feature_cards": load_json(case_dir / "feature_cards.json", {}),
        "browser_materials": load_json(case_dir / "browser_materials.json", {}),
        "image_resources": load_json(case_dir / "image_resources.json", {}),
        "site_asset_pool": site_asset_pool(case_dir),
        "operation_recipes": load_json(case_dir / "operation_recipes.json", {}),
        "material_understanding": load_json(case_dir / "material_understanding.json", {}),
        "visual_plan": load_json(case_dir / "visual_plan.json", {}),
        "video_script": load_json(case_dir / "video_script.json", {}),
        "copywriting_context": copywriting_context(skill_root, input_data),
        "output_contract": {
            "material_output": "material_understanding.json",
            "visual_plan_output": "visual_plan.json",
            "script_output": "video_script.json",
            "accept_command": "python scripts/accept_planner_output.py --case <CASE_DIR> --kind <material|visual_plan|script> --input <MODEL_OUTPUT_JSON> --json",
        },
        "non_negotiable_rules": [
            "Do not rely on filenames alone for visual decisions.",
            "Use image_resources.json for screenshot/result meaning when available.",
            "Use site_asset_pool for website screenshot selection; prefer assets from the same feature_id or feature_key.",
            "For 图文广告 children, keep selection under 文生图/图文广告/<子功能>; do not mix child feature screenshots.",
            "Use asset IDs exactly as listed in asset_manifest.json.",
            "When visual_plan.status=reviewed, script segments must reference visual_beat_id and reuse locked_asset_ids; do not choose new assets in script writing.",
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
            "python scripts\\accept_planner_output.py --case <CASE_DIR> --kind <material|visual_plan|script> --input <MODEL_OUTPUT_JSON> --json",
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
    parser.add_argument("--stage", choices=("all", "material", "visual_plan", "script", "timeline"), default="all")
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
