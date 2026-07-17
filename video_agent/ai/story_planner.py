from __future__ import annotations

import json
from pathlib import Path

from video_agent.ai.prompt_loader import load_prompt
from video_agent.ai.text_client import OpenAICompatibleTextClient
from video_agent.contracts import AssetCatalog, CaseConfig, Narration


def plan_narration(repo_root: Path, case: CaseConfig, catalog: AssetCatalog) -> tuple[Narration, dict[str, str]]:
    prompt = load_prompt(repo_root / "video_agent" / "prompts" / "story_and_shot_proposal.md")
    materials = [
        {
            "asset_id": asset.asset_id,
            "semantic_path": asset.semantic_path,
            "role": asset.role,
            "evidence_class": asset.evidence_class.value,
            "claims": asset.claims,
            "tags": asset.tags,
            "anchors": [anchor.label for anchor in asset.visual_anchors],
        }
        for asset in catalog.assets
        if asset.quality.readable is not False
    ]
    user = json.dumps(
        {
            "case_id": case.case_id,
            "goal": case.goal,
            "feature_path": case.feature_path,
            "duration_policy": case.duration_policy.model_dump(),
            "materials": materials,
        },
        ensure_ascii=False,
    )
    result = OpenAICompatibleTextClient(repo_root).complete_json(prompt.text, user, "narration")
    result.setdefault("case_id", case.case_id)
    return Narration.model_validate(result), {"path": prompt.path.as_posix(), "sha256": prompt.sha256}
