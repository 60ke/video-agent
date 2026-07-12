from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoadedPrompt:
    path: Path
    text: str
    sha256: str


def load_prompt(path: Path) -> LoadedPrompt:
    text = path.read_text(encoding="utf-8")
    return LoadedPrompt(path=path, text=text, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())
