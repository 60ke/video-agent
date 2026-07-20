"""Shared media helpers used by V4 and admin tooling (no V3 contracts)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def ffprobe(path: Path) -> dict[str, Any]:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {proc.stderr[-2000:]}")
    return json.loads(proc.stdout)
