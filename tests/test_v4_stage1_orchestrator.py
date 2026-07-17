from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from video_agent.registries import load_bootstrap_registry
from video_agent.v4.orchestrator import run_fixed_voice_frontend


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_bootstrap_registry_is_strict_and_scope_filtered() -> None:
    registry = load_bootstrap_registry(REPO_ROOT)
    assert registry.category("文生图/文化墙") is not None
    assert registry.category("网站/主页").scope_eligible is False
    assert registry.item("visual_structures", "gallery") is not None
    assert registry.item("configured_assets", "default_outro") is not None


def test_fixed_voice_frontend_runs_speech_and_scope_concurrently(tmp_path: Path) -> None:
    speech_started = threading.Event()
    scope_started = threading.Event()

    def speech_job() -> Path:
        speech_started.set()
        assert scope_started.wait(timeout=1)
        output = tmp_path / "timing_lock.json"
        output.write_text("{}", encoding="utf-8")
        return output

    async def scope_job() -> str:
        scope_started.set()
        assert await asyncio.to_thread(speech_started.wait, 1)
        return "scope"

    timing, scope = asyncio.run(run_fixed_voice_frontend(speech_job=speech_job, scope_job=scope_job()))
    assert timing.name == "timing_lock.json"
    assert scope == "scope"
