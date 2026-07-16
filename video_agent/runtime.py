from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .contracts import CaseConfig
from .io import load_json, write_json_atomic
from .speech.minimax import apply_minimax_local_voice_defaults


STAGES = (
    "catalog",
    "narration",
    "speech",
    "scene",
    "prepare_assets",
    "visual",
    "compile",
    "render",
)


@dataclass(frozen=True)
class RunContext:
    repo_root: Path
    case_dir: Path
    case: CaseConfig
    run_id: str
    run_dir: Path

    @classmethod
    def _load_case(cls, case_dir: Path, repo_root: Path) -> CaseConfig:
        raw = load_json(case_dir / "case.json")
        if not isinstance(raw, dict):
            raise ValueError(f"case.json must be an object: {case_dir / 'case.json'}")
        return CaseConfig.model_validate(apply_minimax_local_voice_defaults(raw, repo_root))

    @classmethod
    def create(cls, case_dir: Path, run_id: str | None = None) -> "RunContext":
        case_dir = case_dir.resolve()
        repo_root = Path(__file__).resolve().parents[1]
        case = cls._load_case(case_dir, repo_root)
        actual_run_id = run_id or f"{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}"
        run_dir = case_dir / "runs" / actual_run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "work").mkdir()
        (run_dir / "final").mkdir()
        return cls(repo_root=repo_root, case_dir=case_dir, case=case, run_id=actual_run_id, run_dir=run_dir)

    @classmethod
    def open(cls, case_dir: Path, run_id: str) -> "RunContext":
        case_dir = case_dir.resolve()
        repo_root = Path(__file__).resolve().parents[1]
        case = cls._load_case(case_dir, repo_root)
        run_dir = case_dir / "runs" / run_id
        if not run_dir.is_dir():
            raise FileNotFoundError(f"run directory not found: {run_dir}")
        return cls(repo_root=repo_root, case_dir=case_dir, case=case, run_id=run_id, run_dir=run_dir)

    def artifact(self, name: str) -> Path:
        return self.run_dir / name

    def mark_latest(self, status: str, final_video: str | None = None) -> None:
        payload = {"run_id": self.run_id, "status": status}
        if final_video:
            payload["final_video"] = final_video
        write_json_atomic(self.case_dir / "latest_run.json", payload)
