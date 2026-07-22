from __future__ import annotations

from pathlib import Path

from video_agent.v4.probe import CHECKPOINT_IDS, format_summary_text, probe_map, summarize_run


def test_probe_map_has_expected_checkpoints() -> None:
    mapping = probe_map()
    assert [item["id"] for item in mapping["checkpoints"]] == list(CHECKPOINT_IDS)


def test_summarize_existing_logo_run() -> None:
    root = Path(__file__).resolve().parents[1]
    case = root / "cases" / "stage7_accept_local_logo1a"
    if not case.is_dir():
        return
    summary = summarize_run(case, "20260720_202134_5a72b0")
    assert summary["ok"] is True
    assert summary["scenes"]
    text = format_summary_text(summary)
    assert "s001" in text
    assert "scope:" in text
