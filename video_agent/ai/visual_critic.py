from __future__ import annotations

import json
from pathlib import Path

from video_agent.ai.prompt_loader import load_prompt
from video_agent.ai.text_client import OpenAICompatibleTextClient
from video_agent.contracts import CheckResult, RenderPlan


def review_contact_sheet(
    repo_root: Path,
    plan: RenderPlan,
    contact_sheet: Path,
    cue_contact_sheet: Path | None = None,
) -> tuple[CheckResult, dict[str, object]]:
    prompt = load_prompt(repo_root / "video_agent" / "prompts" / "visual_critic.md")
    request = json.dumps(
        {
            "case_id": plan.case_id,
            "duration_sec": plan.frame_count / plan.fps,
            "platform_profile": plan.platform_profile,
            "shots": [
                {
                    "shot_id": shot.shot_id,
                    "track": shot.track,
                    "beat_ids": shot.beat_ids,
                    "template": shot.template,
                    "motion": shot.motion,
                    "transition_in": shot.transition_in,
                }
                for shot in plan.shots
            ],
            "subtitles": [cue.text for cue in plan.subtitles],
        },
        ensure_ascii=False,
    )
    evidence_sheets = [contact_sheet]
    if cue_contact_sheet and cue_contact_sheet.is_file():
        evidence_sheets.append(cue_contact_sheet)
    result = OpenAICompatibleTextClient(repo_root).complete_json_with_images(
        prompt.text,
        request,
        evidence_sheets,
        "visual_review",
    )
    verdict = str(result.get("verdict") or "fail").lower()
    issues = result.get("issues") if isinstance(result.get("issues"), list) else []
    check = CheckResult(
        check_id="vision_critic_contact_sheet",
        status="passed" if verdict == "pass" else "failed",
        message=str(result.get("summary") or ""),
        details={"issues": issues},
    )
    trace = {"path": prompt.path.as_posix(), "sha256": prompt.sha256, "evidence_sheets": [path.as_posix() for path in evidence_sheets], "result": result}
    return check, trace
