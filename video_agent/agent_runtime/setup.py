"""First-run local configuration for the Video Agent Skill."""

from __future__ import annotations

import getpass
import os
from pathlib import Path
from typing import Any

from video_agent.editors.jianying import JianyingSkillRuntime
from video_agent.io import load_json, write_json_atomic


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = load_json(path)
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(path, value)


def _write_if_configured(path: Path, value: dict[str, Any], *, interactive: bool) -> None:
    """Keep non-interactive inspection read-only and preserve unknown fields."""
    if path.is_file() and not interactive:
        return
    _write_json(path, value)


def _ask(label: str, *, default: str = "", secret: bool = False, interactive: bool = True) -> str:
    if not interactive:
        return default
    suffix = "" if secret else (f" [{default}]" if default else "")
    prompt = f"{label}{suffix}: "
    value = getpass.getpass(prompt) if secret else input(prompt)
    value = value.strip()
    return value or default


def _configure_ai(repo_root: Path, *, interactive: bool) -> dict[str, Any]:
    path = repo_root / "config" / "ai.local.json"
    current = _read_object(path)
    value = {
        **current,
        "base_url": _ask("AI base URL", default=str(current.get("base_url") or "https://api.deepseek.com"), interactive=interactive),
        "api_key": _ask("AI API key", default=str(current.get("api_key") or os.getenv("VIDEO_AGENT_AI_API_KEY") or ""), secret=True, interactive=interactive),
        "model": _ask("AI primary model", default=str(current.get("model") or "deepseek-v4-pro"), interactive=interactive),
        "coarse_model": _ask("AI coarse model", default=str(current.get("coarse_model") or "deepseek-v4-flash"), interactive=interactive),
        "max_tokens": int(current.get("max_tokens") or 8192),
    }
    if value["api_key"]:
        _write_if_configured(path, value, interactive=interactive)
    return {"path": "config/ai.local.json", "configured": bool(value["api_key"]), "model": value["model"]}


def _configure_minimax(repo_root: Path, *, interactive: bool) -> dict[str, Any]:
    path = repo_root / "config" / "minimax.local.json"
    current = _read_object(path)
    value = {
        **current,
        "endpoint": _ask("MiniMax endpoint", default=str(current.get("endpoint") or "https://api.minimaxi.com/v1/t2a_v2"), interactive=interactive),
        "api_key": _ask("MiniMax API key", default=str(current.get("api_key") or os.getenv("MINIMAX_API_KEY") or ""), secret=True, interactive=interactive),
        "voice_id": _ask("MiniMax voice ID", default=str(current.get("voice_id") or "male-qn-qingse"), interactive=interactive),
        "sample_rate": int(current.get("sample_rate") or 32000),
        "bitrate": int(current.get("bitrate") or 128000),
        "vol": float(current.get("vol") or 1.0),
        "pitch": int(current.get("pitch") or 0),
    }
    if value["api_key"]:
        _write_if_configured(path, value, interactive=interactive)
    return {"path": "config/minimax.local.json", "configured": bool(value["api_key"]), "voice_id": value["voice_id"]}


def _configure_gpt_image(repo_root: Path, *, interactive: bool) -> dict[str, Any]:
    path = repo_root / "config" / "gpt_image.local.json"
    current = _read_object(path)
    current_providers = current.get("providers") if isinstance(current.get("providers"), list) else []
    old = current_providers[0] if current_providers and isinstance(current_providers[0], dict) else {}
    provider = {
        **old,
        "name": str(old.get("name") or "local-gpt-image"),
        "base_url": _ask("GPT Image base URL", default=str(old.get("base_url") or ""), interactive=interactive),
        "api_key": _ask("GPT Image API key", default=str(old.get("api_key") or os.getenv("GPT_IMAGE_API_KEY") or ""), secret=True, interactive=interactive),
        "weight": int(old.get("weight") or 1),
    }
    value = {
        **current,
        "strategy": str(current.get("strategy") or "weighted_failover"),
        "edit_path": str(current.get("edit_path") or "/v1/images/edits"),
        "model": str(current.get("model") or "gpt-image-2"),
        "quality": str(current.get("quality") or "low"),
        "size": str(current.get("size") or "1024x1792"),
        "timeout_seconds": int(current.get("timeout_seconds") or 600),
        "providers": [provider] if provider["api_key"] else current_providers,
    }
    if value["providers"]:
        _write_if_configured(path, value, interactive=interactive)
    return {"path": "config/gpt_image.local.json", "configured": bool(value["providers"]), "model": value["model"]}


def _configure_paths(repo_root: Path, *, interactive: bool) -> dict[str, Any]:
    existing = _read_object(repo_root / "config" / "agent.local.json")
    default_profile = str(existing.get("cdp_profile_dir") or (repo_root / "cdp-capture" / "profiles" / "kehuanxiongmao"))
    default_jy = str(existing.get("jianying_skill_root") or (Path.home() / "Desktop" / "jianying-editor-skill"))
    default_drafts = str(existing.get("jianying_drafts_root") or (repo_root / "cases" / "jianying_drafts"))
    profile_dir = Path(_ask("CDP profile directory", default=default_profile, interactive=interactive)).expanduser().resolve()
    skill_root = Path(_ask("Jianying Skill root", default=default_jy, interactive=interactive)).expanduser().resolve()
    drafts_root = Path(_ask("Jianying drafts directory", default=default_drafts, interactive=interactive)).expanduser().resolve()
    value = {
        "cdp_profile_dir": profile_dir.as_posix(),
        "cdp_auth_state": (profile_dir / "auth_state.json").as_posix(),
        "jianying_skill_root": skill_root.as_posix(),
        "jianying_drafts_root": drafts_root.as_posix(),
    }
    _write_if_configured(repo_root / "config" / "agent.local.json", value, interactive=interactive)
    cdp_ready = (profile_dir / "auth_state.json").is_file()
    try:
        runtime = JianyingSkillRuntime.discover(explicit_root=skill_root, repo_root=repo_root)
        capabilities = runtime.probe(import_modules=False).as_dict()
        jianying_ready = True
    except Exception as exc:
        capabilities = {"error": str(exc)}
        jianying_ready = False
    return {
        "path": "config/agent.local.json",
        "cdp_auth_state_present": cdp_ready,
        "jianying_ready": jianying_ready,
        "jianying_capabilities": capabilities,
    }


def setup_installation(repo_root: Path, *, interactive: bool = True) -> dict[str, Any]:
    """Configure local providers and return a redacted readiness report."""

    report = {
        "ok": True,
        "provider_configs": [
            _configure_ai(repo_root, interactive=interactive),
            _configure_minimax(repo_root, interactive=interactive),
            _configure_gpt_image(repo_root, interactive=interactive),
        ],
        "paths": _configure_paths(repo_root, interactive=interactive),
        "next_steps": [
            "If CDP auth is absent, run: node cdp-capture/bin/cdp-capture.js profile login kehuanxiongmao --url https://www.kehuanxiongmao.com",
            "Use `python main.py jianying-probe` to inspect native Jianying capabilities.",
            "Never commit config/*.local.json, CDP profiles, cookies, or generated runs.",
        ],
    }
    return report
