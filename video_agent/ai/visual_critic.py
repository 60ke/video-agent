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
    cue_contact_sheets: list[Path] | None = None,
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
    pages = [path for path in (cue_contact_sheets or []) if path.is_file()] or [contact_sheet]
    client = OpenAICompatibleTextClient(repo_root)
    results = [
        client.complete_json_with_images(prompt.text, request, [contact_sheet, page] if page != contact_sheet else [contact_sheet], f"visual_review_page_{index}")
        for index, page in enumerate(pages, start=1)
    ]
    verdict = "pass" if all(str(result.get("verdict") or "fail").lower() == "pass" for result in results) else "fail"
    issues = [issue for result in results for issue in (result.get("issues") if isinstance(result.get("issues"), list) else [])]
    check = CheckResult(
        check_id="vision_critic_contact_sheet",
        status="passed" if verdict == "pass" else "failed",
        message="; ".join(str(result.get("summary") or "") for result in results if result.get("summary")),
        details={"issues": issues, "pages_reviewed": len(results)},
    )
    trace = {"path": prompt.path.as_posix(), "sha256": prompt.sha256, "evidence_sheets": [contact_sheet.as_posix(), *[path.as_posix() for path in pages]], "result": {"verdict": verdict, "pages": results}}
    return check, trace
