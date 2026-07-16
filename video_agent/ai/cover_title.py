from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import Field, field_validator

from video_agent.ai.prompt_loader import load_prompt
from video_agent.ai.text_client import OpenAICompatibleTextClient
from video_agent.contracts import CaseConfig, Narration
from video_agent.contracts.base import Contract


class CoverTitlePlan(Contract):
    title: str = Field(min_length=4, max_length=24)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> str:
        title = re.sub(r"[，。！？；：,.!?:;、‘’“”《》]+", " ", str(value))
        return " ".join(title.split()).strip()


def plan_cover_title(
    repo_root: Path,
    case: CaseConfig,
    narration: Narration,
) -> tuple[CoverTitlePlan, dict[str, str]]:
    prompt = load_prompt(repo_root / "video_agent" / "prompts" / "cover_title_planner.md")
    user = json.dumps(
        {
            "goal": case.goal,
            "feature_path": case.feature_path,
            "full_narration": [
                {"beat_id": beat.beat_id, "spoken_text": beat.spoken_text}
                for beat in narration.beats
            ],
        },
        ensure_ascii=False,
    )
    raw = OpenAICompatibleTextClient(repo_root).complete_json(
        prompt.text,
        user,
        "cover_title",
        max_tokens=256,
        thinking=False,
    )
    plan = CoverTitlePlan.model_validate(raw)
    return plan, {"path": prompt.path.as_posix(), "sha256": prompt.sha256}
