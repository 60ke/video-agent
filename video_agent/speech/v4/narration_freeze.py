"""Native FrozenNarration builders for script and goal modes."""

from __future__ import annotations

from pathlib import Path

from video_agent.contracts.v4 import FrozenNarration
from video_agent.contracts.v4.common import normalize_frozen_text
from video_agent.io import sha256_bytes, sha256_json, write_json_atomic


def freeze_script_narration(*, text: str, source_bytes: bytes | None = None) -> FrozenNarration:
    # Script mode is verbatim: normalize line endings / edges only — no NFKC punctuation rewrite.
    frozen_text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not frozen_text:
        raise ValueError("script narration is empty after normalization")
    raw = source_bytes if source_bytes is not None else text.encode("utf-8")
    return FrozenNarration(
        text=frozen_text,
        source="script",
        source_fingerprint=f"sha256:{sha256_bytes(raw)}:{sha256_json({'text': frozen_text})}",
    )


def freeze_goal_narration(*, spoken_text: str, goal: str, response_fingerprint: str) -> FrozenNarration:
    frozen_text = normalize_frozen_text(spoken_text)
    if not frozen_text:
        raise ValueError("goal narration spoken_text is empty after normalization")
    return FrozenNarration(
        text=frozen_text,
        source="goal",
        source_fingerprint=(
            f"sha256:{sha256_json({'goal': goal.strip()})}:{response_fingerprint}:{sha256_json({'text': frozen_text})}"
        ),
    )


def resolve_script_text(case_dir: Path, *, narration_source: str | None = None) -> tuple[str, bytes]:
    """Load exact script text for freezing. Prefer source_script.txt over legacy narration.json."""
    source_script = case_dir / "input" / "source_script.txt"
    if source_script.is_file():
        raw = source_script.read_bytes()
        text = raw.decode("utf-8-sig")
        return text, raw

    if narration_source:
        path = case_dir / narration_source
        if path.is_file():
            payload = path.read_text(encoding="utf-8-sig")
            # Legacy V3 Narration JSON stores spoken_text; plain text files are also accepted.
            if path.suffix.lower() == ".json":
                from video_agent.io import load_json

                data = load_json(path)
                spoken = str(data.get("spoken_text") or "").strip()
                if not spoken and isinstance(data.get("beats"), list):
                    spoken = "".join(str(beat.get("spoken_text") or "") for beat in data["beats"])
                if not spoken:
                    raise ValueError(f"narration source has no spoken_text: {path}")
                return spoken, spoken.encode("utf-8")
            return payload, path.read_bytes()

    raise FileNotFoundError(
        "script mode requires input/source_script.txt or a readable narration_source"
    )


def write_frozen_narration(path: Path, frozen: FrozenNarration) -> Path:
    write_json_atomic(path, frozen)
    return path
