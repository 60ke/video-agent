from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.skill_path import require_skill_root


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"JSON file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return data


def write_json(path: Path, payload: dict[str, Any], force: bool) -> str:
    if path.exists() and not force:
        return "skipped"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return "written"


def profile_path(skill_root: Path, profile: str) -> Path:
    rel = Path("references") / "site_profiles" / f"{profile}.json"
    return skill_root / rel


def select_feature(profile: dict[str, Any], feature_id: str | None) -> dict[str, Any]:
    features = profile.get("features", [])
    if not isinstance(features, list) or not features:
        raise ValueError("site profile has no features")
    if not feature_id:
        return features[0]
    for feature in features:
        if isinstance(feature, dict) and feature.get("id") == feature_id:
            return feature
    raise ValueError(f"feature not found in profile: {feature_id}")


def build_website_knowledge(profile: dict[str, Any], feature: dict[str, Any], refresh_needed: bool) -> dict[str, Any]:
    status = "profile_seeded_refresh_needed" if refresh_needed else "profile_seeded_needs_live_verification"
    expected_text = feature.get("expected_visible_text", [])
    nav = profile.get("stable_navigation", {})
    frontend = profile.get("frontend_code_evidence", {})
    return {
        "schema_version": 1,
        "status": status,
        "profile_id": profile.get("profile_id"),
        "profile_last_reviewed": profile.get("last_reviewed"),
        "generated_at": now_iso(),
        "refresh_needed": refresh_needed,
        "pages": [
            {
                "id": "page_home",
                "url": profile.get("canonical_url"),
                "title": profile.get("site_name"),
                "role": "homepage",
                "description": "Profile-seeded homepage/navigation structure. Verify live state with Kimi WebBridge before capture.",
                "visible_text": [item.get("label") for item in nav.get("left_nav", []) if isinstance(item, dict)],
                "account_indicators": nav.get("account_indicators", []),
                "verification": {
                    "source": "site_profile",
                    "requires_kimi_webbridge_snapshot": True
                }
            },
            {
                "id": f"page_{feature.get('id')}",
                "url": feature.get("url"),
                "route": feature.get("route"),
                "title": feature.get("name"),
                "role": "feature_page",
                "feature_name": feature.get("name"),
                "description": "Profile-seeded feature page from frontend route/component evidence.",
                "visible_text": expected_text,
                "form_fields": feature.get("form_fields", []),
                "cost": feature.get("known_cost", {}),
                "frontend_code_evidence": {
                    "router_file": frontend.get("router_file"),
                    "component": frontend.get("signboard_route", {}).get("component"),
                    "left_form_component": frontend.get("left_form_component"),
                    "api_file": frontend.get("api_file")
                },
                "verification": {
                    "source": "frontend_code_and_site_profile",
                    "requires_kimi_webbridge_snapshot": True
                }
            }
        ],
        "notes": [
            "This file is seeded from a stable site profile to reduce repeated exploration.",
            "Kimi WebBridge must still verify login state, points balance, visible page state, and real generated results.",
            "Run a manual refresh when profile refresh triggers are observed."
        ]
    }


def build_feature_cards(profile: dict[str, Any], feature: dict[str, Any], refresh_needed: bool) -> dict[str, Any]:
    status = "profile_seeded_refresh_needed" if refresh_needed else "profile_seeded_needs_live_verification"
    return {
        "schema_version": 1,
        "status": status,
        "profile_id": profile.get("profile_id"),
        "generated_at": now_iso(),
        "features": [
            {
                "id": f"feature_{feature.get('id')}",
                "name": feature.get("name"),
                "category": feature.get("category"),
                "summary": "根据前端代码和站点画像固化的功能卡；真实截图和生成结果仍需 Kimi WebBridge 验证。",
                "page_url": feature.get("url"),
                "page_evidence_id": f"page_{feature.get('id')}",
                "key_points": feature.get("supported_claims", []),
                "visual_moments": feature.get("required_capture_steps", []),
                "default_demo_inputs": feature.get("default_demo_inputs", {}),
                "video_hooks": feature.get("video_hooks", []),
                "operation_status": "profile_seeded",
                "allowed_claims_before_live_verification": [
                    "功能入口存在",
                    "表单字段来自前端代码",
                    "生成结果必须等真实结果资产保存后再声明"
                ]
            }
        ]
    }


def build_operation_recipes(profile: dict[str, Any], feature: dict[str, Any], refresh_needed: bool) -> dict[str, Any]:
    status = "profile_seeded_refresh_needed" if refresh_needed else "profile_seeded_needs_live_verification"
    frontend = profile.get("frontend_code_evidence", {})
    return {
        "schema_version": 1,
        "status": status,
        "profile_id": profile.get("profile_id"),
        "generated_at": now_iso(),
        "recipes": [
            {
                "id": f"recipe_{feature.get('id')}_webbridge_capture",
                "feature_id": feature.get("id"),
                "name": f"{feature.get('name')} Kimi WebBridge 素材采集",
                "mode": "site_profile_accelerated",
                "target_url": feature.get("url"),
                "frontend_code_evidence": frontend,
                "webbridge": profile.get("webbridge", {}),
                "entry_path": feature.get("entry_path", []),
                "minimum_live_verification": profile.get("refresh_policy", {}).get("minimum_live_verification", []),
                "refresh_triggers": profile.get("refresh_policy", {}).get("refresh_triggers", []),
                "default_demo_inputs": feature.get("default_demo_inputs", {}),
                "api_payload_template": feature.get("api_payload_template", {}),
                "capture_steps": [
                    {
                        "id": step,
                        "requires_live_browser": True,
                        "save_to_case": True
                    }
                    for step in feature.get("required_capture_steps", [])
                ],
                "safety": {
                    "generation_allowed_when": "logged-in state visible and points balance > 100",
                    "do_not_generate_when": "points <= 100, login missing, or page state differs from profile in a way that changes cost/required fields"
                }
            }
        ]
    }


def build_site_profile_snapshot(profile: dict[str, Any], feature: dict[str, Any], frontend_root: str | None, refresh_needed: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "refresh_needed" if refresh_needed else "active",
        "profile": profile,
        "selected_feature": feature,
        "frontend_root": frontend_root,
        "applied_at": now_iso(),
        "next_agent_instructions": [
            "Use this snapshot to avoid re-reading the full frontend unless refresh_needed is true.",
            "Use Kimi WebBridge for live login, points, screenshots, form filling, generation, and result capture.",
            "If route, field labels, required fields, or cost differ from this snapshot, refresh the profile manually."
        ]
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    skill_root = require_skill_root(Path(__file__).resolve())
    case_dir = Path(args.case).expanduser().resolve(strict=False)
    case_dir.mkdir(parents=True, exist_ok=True)

    profile = load_json(profile_path(skill_root, args.profile))
    feature = select_feature(profile, args.feature)
    outputs = {
        "website_knowledge.json": build_website_knowledge(profile, feature, args.refresh_needed),
        "feature_cards.json": build_feature_cards(profile, feature, args.refresh_needed),
        "operation_recipes.json": build_operation_recipes(profile, feature, args.refresh_needed),
        "site_profile_snapshot.json": build_site_profile_snapshot(profile, feature, args.frontend_root, args.refresh_needed),
    }

    touched: list[str] = []
    skipped: list[str] = []
    for filename, payload in outputs.items():
        result = write_json(case_dir / filename, payload, args.force)
        if result == "written":
            touched.append(str(case_dir / filename))
        else:
            skipped.append(str(case_dir / filename))

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "case_dir": str(case_dir),
            "profile": args.profile,
            "feature": feature.get("id"),
            "refresh_needed": args.refresh_needed,
            "touched": touched,
            "skipped": skipped,
        },
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed a case from a stable website profile.")
    parser.add_argument("--case", required=True)
    parser.add_argument("--profile", default="kehuanxiongmao")
    parser.add_argument("--feature", default="signboard")
    parser.add_argument("--frontend-root", help="Optional frontend project root used as profile evidence.")
    parser.add_argument("--refresh-needed", action="store_true", help="Mark seeded artifacts as requiring manual profile refresh.")
    parser.add_argument("--force", action="store_true", help="Overwrite existing seeded artifacts.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001 - CLI must return structured errors.
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
    elif output["ok"]:
        print(f"Applied site profile: {output['data']['profile']} / {output['data']['feature']}")
    else:
        print(f"ERROR: {output['reason']}", file=sys.stderr)
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
