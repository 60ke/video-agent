from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def is_kehuanxiongmao_case(input_data: dict[str, Any]) -> bool:
    request = input_data.get("request", {}) if isinstance(input_data.get("request"), dict) else {}
    target_url = str(request.get("target_url") or "").lower()
    brand = str(request.get("brand_profile") or "").lower()
    return "kehuanxiongmao.com" in target_url or "柯幻熊猫" in brand


def _walk(value: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        found.append(value)
        for child in value.values():
            found.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_walk(child))
    return found


def _truthy_login(value: Any) -> bool:
    if value is True:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"true", "yes", "logged_in", "login_ok", "authenticated", "已登录"}
    return False


def _numeric(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        digits = "".join(ch for ch in value if ch.isdigit() or ch == ".")
        if digits:
            try:
                return float(digits)
            except ValueError:
                return None
    return None


def find_kehuanxiongmao_auth_proof(case_dir: Path) -> dict[str, Any]:
    candidates: list[dict[str, Any]] = []
    for rel in ("browser_materials.json", "generation_receipts.json", "website_knowledge.json"):
        data = load_json(case_dir / rel, {})
        for item in _walk(data):
            item["_source_file"] = rel
            candidates.append(item)

    logged_in = False
    login_source: str | None = None
    points: float | None = None
    points_source: str | None = None

    login_keys = ("logged_in", "is_logged_in", "authenticated", "login_state", "auth_state", "account_logged_in")
    point_keys = ("points_balance", "credit_balance", "credits_balance", "balance", "points", "credits")

    for item in candidates:
        for key in login_keys:
            if key in item and _truthy_login(item.get(key)):
                logged_in = True
                login_source = item.get("_source_file")
        for key in point_keys:
            if key in item:
                value = _numeric(item.get(key))
                if value is not None and (points is None or value > points):
                    points = value
                    points_source = item.get("_source_file")

    return {
        "logged_in": logged_in,
        "login_source": login_source,
        "points_balance": points,
        "points_source": points_source,
    }


def kehuanxiongmao_auth_errors(case_dir: Path, input_data: dict[str, Any]) -> list[str]:
    if not is_kehuanxiongmao_case(input_data):
        return []
    proof = find_kehuanxiongmao_auth_proof(case_dir)
    errors: list[str] = []
    if proof["logged_in"] is not True:
        errors.append("kehuanxiongmao.com requires captured logged-in evidence before execution")
    if proof["points_balance"] is None:
        errors.append("kehuanxiongmao.com requires captured points/credits balance before generation")
    elif float(proof["points_balance"]) <= 100:
        errors.append(f"kehuanxiongmao.com points/credits balance must be > 100, got {proof['points_balance']}")
    return errors
