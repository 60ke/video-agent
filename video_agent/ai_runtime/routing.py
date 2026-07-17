from __future__ import annotations

import os
from pathlib import Path

from pydantic import SecretStr

from video_agent.io import load_json

from .contracts import CapabilityRoute, ModelProfile, ProviderProfile, RuntimeContract


class RuntimeConfiguration(RuntimeContract):
    providers: dict[str, ProviderProfile]
    models: dict[str, ModelProfile]
    routes: dict[str, CapabilityRoute]


def load_runtime_configuration(repo_root: Path) -> RuntimeConfiguration:
    local_path = repo_root / "config" / "ai.local.json"
    local = load_json(local_path) if local_path.is_file() else {}
    explicit_path = repo_root / "config" / "ai_runtime.v4.json"
    explicit = load_json(explicit_path) if explicit_path.is_file() else {}

    base_url = str(os.getenv("VIDEO_AGENT_AI_BASE_URL") or local.get("base_url") or "").rstrip("/")
    api_key = str(os.getenv("VIDEO_AGENT_AI_API_KEY") or local.get("api_key") or "")
    if not base_url or not api_key:
        raise ValueError("V4 AI runtime requires base_url and api_key in environment or config/ai.local.json")

    provider_values = explicit.get("providers", {}).get("deepseek_default", {})
    provider = ProviderProfile(
        profile_id="deepseek_default",
        base_url=base_url,
        api_key=SecretStr(api_key),
        max_concurrency=int(provider_values.get("max_concurrency", 3)),
        connect_timeout_seconds=float(provider_values.get("connect_timeout_seconds", 10)),
        read_timeout_seconds=float(provider_values.get("read_timeout_seconds", 240)),
    )
    max_tokens = int(local.get("max_tokens") or 8192)
    fast_model = str(local.get("coarse_model") or local.get("model") or "deepseek-chat")
    quality_model = str(local.get("model") or fast_model)
    models = {
        "semantic_fast": ModelProfile(
            profile_id="semantic_fast",
            provider_profile=provider.profile_id,
            model=fast_model,
            max_tokens=max_tokens,
        ),
        "semantic_quality": ModelProfile(
            profile_id="semantic_quality",
            provider_profile=provider.profile_id,
            model=quality_model,
            max_tokens=max_tokens,
        ),
    }
    route_values = explicit.get("routes", {})
    routes = {
        "scope_classifier": _route("scope_classifier", route_values.get("scope_classifier", {}), max_concurrency=2),
        "scene_semantics": _route("scene_semantics", route_values.get("scene_semantics", {}), max_concurrency=1),
        "field_repair": _route("field_repair", route_values.get("field_repair", {}), max_concurrency=1),
    }
    return RuntimeConfiguration(providers={provider.profile_id: provider}, models=models, routes=routes)


def _route(capability: str, values: dict, *, max_concurrency: int) -> CapabilityRoute:
    return CapabilityRoute(
        capability=capability,
        primary=str(values.get("primary") or "semantic_fast"),
        repair=str(values.get("repair") or "semantic_fast"),
        rebuild=str(values.get("rebuild") or "semantic_quality"),
        max_concurrency=int(values.get("max_concurrency", max_concurrency)),
        max_transport_retries=int(values.get("max_transport_retries", 2)),
        max_field_repairs=int(values.get("max_field_repairs", 2)),
        max_full_rebuilds=int(values.get("max_full_rebuilds", 1)),
    )
