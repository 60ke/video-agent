from __future__ import annotations

import json
from pathlib import Path

from video_agent.ai.prompt_loader import load_prompt
from video_agent.ai.story_planner import PLANNER_APPROVED_STATUSES
from video_agent.ai.text_client import OpenAICompatibleTextClient
from video_agent.contracts import Asset, AssetCatalog, CaseConfig, Narration, TimingLock, VisualPlan
from video_agent.planning.auto_visual import _requires_reference_comparison


def _candidate_assets(case: CaseConfig, narration: Narration, catalog: AssetCatalog, limit: int = 12) -> list[Asset]:
    """Return a bounded, review-approved multimodal packet in stable order."""

    preferred_roles = {"site_home", "feature_entry", "feature_list", "feature_form_params", "result_image", "brand_logo", "brand_ip_static"}
    comparison_requested = any(_requires_reference_comparison(beat.spoken_text, beat.asset_slots) for beat in narration.beats)
    if comparison_requested:
        preferred_roles.add("reference_image")
    candidates = [
        asset
        for asset in catalog.assets
        if asset.media_type == "image"
        and asset.production_eligible
        and asset.quality.status in PLANNER_APPROVED_STATUSES
        and (asset.role in preferred_roles)
    ]
    by_id = {asset.asset_id: asset for asset in candidates}
    claims = {claim.claim_id: claim for claim in narration.claims}
    required_ids: list[str] = []
    for beat in narration.beats:
        for cue in beat.claim_cues:
            claim = claims[cue.claim_id]
            approved = [asset_id for asset_id in claim.supporting_asset_ids if asset_id in by_id]
            if not approved:
                raise ValueError(f"claim has no approved image for multimodal planning: {cue.claim_id}")
            for asset_id in approved:
                if asset_id not in required_ids:
                    required_ids.append(asset_id)
    if len(required_ids) > limit:
        raise ValueError(f"claim evidence exceeds multimodal image limit: {len(required_ids)}/{limit}")
    feature = [asset for asset in candidates if asset.semantic_path[: len(case.feature_path)] == case.feature_path]
    shared = [asset for asset in candidates if asset.role in {"site_home", "brand_logo"}]
    ordered: list[Asset] = []
    seen: set[str] = set()
    required = [by_id[asset_id] for asset_id in required_ids]
    for asset in required + sorted(feature + shared, key=lambda item: (item.role, item.filename, item.asset_id)):
        if asset.asset_id not in seen:
            ordered.append(asset)
            seen.add(asset.asset_id)
    return ordered[:limit]


def plan_visual(
    repo_root: Path,
    case: CaseConfig,
    narration: Narration,
    timing: TimingLock,
    catalog: AssetCatalog,
) -> tuple[VisualPlan, dict[str, object]]:
    prompt = load_prompt(repo_root / "video_agent" / "prompts" / "visual_story_planner.md")
    assets = _candidate_assets(case, narration, catalog)
    paths = [(repo_root / asset.path).resolve() for asset in assets]
    missing = [path.as_posix() for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"visual planner source assets missing: {missing}")
    timing_anchors = [
        {"anchor_id": "timeline_start", "frame": 0},
        {"anchor_id": "timeline_end", "frame": timing.duration_frames},
    ] + [
        {"anchor_id": f"beat_start:{span.beat_id}", "frame": span.start_frame}
        for span in timing.beat_spans
    ] + [
        {"anchor_id": f"beat_end:{span.beat_id}", "frame": span.end_frame}
        for span in timing.beat_spans
    ] + [
        {
            "anchor_id": anchor.anchor_id,
            "frame": anchor.hit_frame,
            "beat_id": anchor.beat_id,
            "text": anchor.text,
            "claim_ids": anchor.claim_ids,
        }
        for anchor in timing.phrase_anchors
    ]
    request = json.dumps(
        {
            "case_id": case.case_id,
            "feature_path": case.feature_path,
            "narration": narration.model_dump(mode="json"),
            "timing_anchors": timing_anchors,
            "assets": [
                {
                    "image_index": index + 1,
                    "asset_id": asset.asset_id,
                    "semantic_path": asset.semantic_path,
                    "role": asset.role,
                    "evidence_class": asset.evidence_class.value,
                    "claims": asset.claims,
                    "tags": asset.tags,
                    "anchors": [anchor.model_dump(mode="json") for anchor in asset.visual_anchors],
                }
                for index, asset in enumerate(assets)
            ],
        },
        ensure_ascii=False,
    )
    result = OpenAICompatibleTextClient(repo_root).complete_json_with_images(prompt.text, request, paths, "visual_story_plan")
    result.setdefault("case_id", case.case_id)
    visual = VisualPlan.model_validate(result)
    return visual, {"path": prompt.path.as_posix(), "sha256": prompt.sha256, "asset_ids": [asset.asset_id for asset in assets]}
