from __future__ import annotations

import hashlib
import math
import re

from video_agent.contracts import (
    Asset,
    AssetCatalog,
    BeatVisualDemand,
    DeriveKind,
    DerivedAssetRequest,
    Narration,
    TimingLock,
    VisualClaimAnchor,
    VisualDemandPlan,
)
from video_agent.io import sha256_json


APPROVED_STATUSES = {"machine_checked", "vision_verified", "human_approved"}
DERIVE_SEQUENCE = (DeriveKind.RESULT_DETAIL_CROP, DeriveKind.RESULT_VERTICAL_LAYOUT)
GENERIC_TERMS = {
    "结果",
    "展示",
    "真实结果",
    "效果",
    "画面",
    "功能",
    "入口",
    "参数",
    "网站",
    "首页",
    "生成",
}


def desired_visual_states(duration_frames: int, fps: int) -> int:
    seconds = duration_frames / fps
    if seconds < 1.2:
        return 1
    if seconds < 2.5:
        return 2
    if seconds < 4.0:
        return 3
    return min(4, max(3, math.ceil(seconds / 1.8)))


def _normalize(value: str) -> str:
    return re.sub(r"[\s，。！？、,.!?:：；;（）()\-_/]", "", value).lower()


def _asset_haystack(asset: Asset) -> str:
    return _normalize(" ".join(asset.semantic_path + asset.tags + asset.claims + [asset.filename, asset.role]))


def _usable_images(catalog: AssetCatalog) -> list[Asset]:
    return [
        asset
        for asset in catalog.assets
        if asset.media_type == "image"
        and asset.production_eligible
        and asset.quality.status in APPROVED_STATUSES
        and not (asset.role == "feature_form_params" and asset.metadata.get("sequence_role") != "base")
    ]


def _claim_support_ids(beat_id: str, narration: Narration) -> set[str]:
    claim_by_id = {claim.claim_id: claim for claim in narration.claims}
    beat = next(item for item in narration.beats if item.beat_id == beat_id)
    return {
        asset_id
        for cue in beat.claim_cues
        if cue.claim_id in claim_by_id
        for asset_id in claim_by_id[cue.claim_id].supporting_asset_ids
    }


def _candidate_score(asset: Asset, beat_text: str, terms: list[str], claim_support_ids: set[str]) -> tuple[int, int, str]:
    haystack = _asset_haystack(asset)
    normalized_text = _normalize(beat_text)
    score = 0
    if asset.asset_id in claim_support_ids:
        score += 100
    for term in terms:
        normalized = _normalize(term)
        if normalized and normalized not in GENERIC_TERMS and normalized in haystack:
            score += 20
    if any(_normalize(item) in normalized_text for item in asset.semantic_path if item):
        score += 8
    if asset.role == "result_image":
        score += 5
    elif asset.role in {"feature_entry", "feature_form_params", "site_home", "feature_list"}:
        score += 4
    if asset.provenance.origin == "deterministic_faithful_derivative":
        score += 2
    return score, 1 if asset.evidence_class.value.startswith("E0") else 0, asset.asset_id


def _candidates_for_beat(beat_id: str, narration: Narration, catalog: AssetCatalog) -> list[Asset]:
    beat = next(item for item in narration.beats if item.beat_id == beat_id)
    terms = [*beat.asset_slots, *beat.hit_phrases]
    claim_support = _claim_support_ids(beat_id, narration)
    candidates = _usable_images(catalog)
    ranked = sorted(
        candidates,
        key=lambda asset: _candidate_score(asset, beat.spoken_text, terms, claim_support),
        reverse=True,
    )
    positive = [asset for asset in ranked if _candidate_score(asset, beat.spoken_text, terms, claim_support)[0] > 0]
    if positive:
        return positive
    fallback_roles = {"result_image", "feature_entry", "feature_form_params", "site_home", "feature_list"}
    return [asset for asset in ranked if asset.role in fallback_roles][:1]


def _request_id(case_id: str, beat_id: str, index: int, source_asset_id: str, derive_kind: DeriveKind) -> str:
    digest = hashlib.sha256(f"{case_id}|{beat_id}|{index}|{source_asset_id}|{derive_kind.value}".encode("utf-8")).hexdigest()[:12]
    return f"auto_{digest}"


def build_visual_demand_plan(
    case_id: str,
    narration: Narration,
    timing: TimingLock,
    catalog: AssetCatalog,
) -> VisualDemandPlan:
    if narration.case_id != case_id or timing.case_id != case_id:
        raise ValueError("case ids differ across narration and timing contracts")

    span_by_id = {span.beat_id: span for span in timing.beat_spans}
    anchors_by_beat: dict[str, list[VisualClaimAnchor]] = {}
    for anchor in timing.phrase_anchors:
        if anchor.claim_ids:
            anchors_by_beat.setdefault(anchor.beat_id, []).extend(
                VisualClaimAnchor(claim_id=claim_id, hit_frame=anchor.hit_frame) for claim_id in anchor.claim_ids
            )

    requests: list[DerivedAssetRequest] = []
    demands: list[BeatVisualDemand] = []
    warnings: list[str] = []

    for beat in narration.beats:
        span = span_by_id.get(beat.beat_id)
        if span is None:
            raise ValueError(f"timing lock has no beat span for {beat.beat_id}")
        duration_frames = span.end_frame - span.start_frame
        required = desired_visual_states(duration_frames, timing.fps)
        candidates = _candidates_for_beat(beat.beat_id, narration, catalog)
        existing = candidates[:required]
        shortage = max(0, required - len(existing))
        request_ids: list[str] = []

        if shortage and candidates:
            source = candidates[0]
            window = max(1, duration_frames // required)
            for index in range(shortage):
                derive_kind = DERIVE_SEQUENCE[index % len(DERIVE_SEQUENCE)]
                request_id = _request_id(case_id, beat.beat_id, index, source.asset_id, derive_kind)
                preferred_start = min(span.end_frame - 1, span.start_frame + window * (len(existing) + index))
                preferred_end = min(span.end_frame, max(preferred_start + 1, preferred_start + window))
                requests.append(
                    DerivedAssetRequest(
                        request_id=request_id,
                        source_asset_id=source.asset_id,
                        derive_kind=derive_kind,
                        instruction=f"为 {beat.beat_id} 增加不改变事实内容的视觉状态",
                        output_role=source.role,
                        semantic_path=list(source.semantic_path),
                        tags=list(dict.fromkeys([*source.tags, "active_materialization", beat.beat_id])),
                        purpose="visual_density",
                        beat_id=beat.beat_id,
                        preferred_start_frame=preferred_start,
                        preferred_end_frame=preferred_end,
                    )
                )
                request_ids.append(request_id)
        elif shortage:
            warnings.append(f"{beat.beat_id} requires {required} visual states but has no eligible image source")

        demands.append(
            BeatVisualDemand(
                beat_id=beat.beat_id,
                start_frame=span.start_frame,
                end_frame=span.end_frame,
                required_visual_states=required,
                existing_asset_ids=[asset.asset_id for asset in existing],
                claim_anchors=anchors_by_beat.get(beat.beat_id, []),
                request_ids=request_ids,
                reason=(
                    f"{duration_frames / timing.fps:.2f}s beat requires {required} visual states; "
                    f"{len(existing)} approved matching assets available"
                ),
            )
        )

    return VisualDemandPlan(
        case_id=case_id,
        timing_lock_sha256=sha256_json(timing),
        catalog_sha256=sha256_json(catalog),
        demands=demands,
        requests=requests,
        warnings=warnings,
    )
