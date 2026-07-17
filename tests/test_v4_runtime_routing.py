from __future__ import annotations

import json
from pathlib import Path

from video_agent.ai_runtime.routing import load_runtime_configuration


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_semantic_models_disable_thinking_by_default(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIDEO_AGENT_AI_BASE_URL", raising=False)
    monkeypatch.delenv("VIDEO_AGENT_AI_API_KEY", raising=False)
    _write_json(
        tmp_path / "config" / "ai.local.json",
        {
            "base_url": "https://example.invalid",
            "api_key": "local-only",
            "model": "quality-model",
            "coarse_model": "fast-model",
            "max_tokens": 4096,
        },
    )

    configuration = load_runtime_configuration(tmp_path)

    assert configuration.models["semantic_fast"].thinking is False
    assert configuration.models["semantic_quality"].thinking is False


def test_semantic_model_settings_can_be_overridden(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("VIDEO_AGENT_AI_BASE_URL", raising=False)
    monkeypatch.delenv("VIDEO_AGENT_AI_API_KEY", raising=False)
    _write_json(
        tmp_path / "config" / "ai.local.json",
        {
            "base_url": "https://example.invalid",
            "api_key": "local-only",
            "model": "quality-model",
            "coarse_model": "fast-model",
        },
    )
    _write_json(
        tmp_path / "config" / "ai_runtime.v4.json",
        {
            "models": {
                "semantic_quality": {
                    "model": "quality-override",
                    "max_tokens": 12000,
                    "temperature": 0.2,
                    "thinking": True,
                }
            }
        },
    )

    configuration = load_runtime_configuration(tmp_path)
    quality = configuration.models["semantic_quality"]

    assert quality.model == "quality-override"
    assert quality.max_tokens == 12000
    assert quality.temperature == 0.2
    assert quality.thinking is True
