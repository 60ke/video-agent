from __future__ import annotations

from pathlib import Path

from video_agent.io import write_json_atomic
from video_agent.runtime import RunContext
from video_agent.speech.minimax import apply_minimax_local_voice_defaults


def test_apply_minimax_local_voice_defaults_fills_omitted_voice_id(tmp_path: Path) -> None:
    write_json_atomic(tmp_path / "config" / "minimax.local.json", {"voice_id": "adman_ai_clone_20260715"})
    patched = apply_minimax_local_voice_defaults({"case_id": "demo", "goal": "测试"}, tmp_path)
    assert patched["voice"]["voice_id"] == "adman_ai_clone_20260715"


def test_apply_minimax_local_voice_defaults_overrides_stale_case_voice(tmp_path: Path) -> None:
    write_json_atomic(
        tmp_path / "config" / "minimax.local.json",
        {"model": "speech-2.8-turbo", "voice_id": "adman_ai_clone_20260715"},
    )
    patched = apply_minimax_local_voice_defaults(
        {"case_id": "demo", "goal": "测试", "voice": {"voice_id": "male-qn-qingse"}},
        tmp_path,
    )
    assert patched["voice"]["voice_id"] == "adman_ai_clone_20260715"
    assert patched["voice"]["model"] == "speech-2.8-turbo"


def test_run_context_loads_local_voice_id_when_case_omits_it(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    write_json_atomic(repo_root / "config" / "minimax.local.json", {"voice_id": "adman_ai_clone_20260715"})
    case_dir = tmp_path / "case"
    case_dir.mkdir()
    write_json_atomic(
        case_dir / "case.json",
        {"case_id": "demo_case", "goal": "测试目标", "feature_path": ["文生图"]},
    )
    case = RunContext._load_case(case_dir, repo_root)
    assert case.voice.voice_id == "adman_ai_clone_20260715"
