from __future__ import annotations

from collections import defaultdict

from video_agent.contracts import Asset, AssetCatalog, CueBinding, Narration, ShotPlan, TimeRef, TimingLock, TransitionIn, VisualPlan


BEAT_START_ANCHOR_PREFIX = "beat_start:"
BEAT_END_ANCHOR_PREFIX = "beat_end:"
APPROVED_STATUSES = {"machine_checked", "vision_verified", "human_approved"}


def _role_assets(catalog: AssetCatalog) -> dict[str, list[Asset]]:
    roles: dict[str, list[Asset]] = defaultdict(list)
    for asset in catalog.assets:
        usable_media = asset.media_type == "image" or asset.role in {"brand_ip_animation", "brand_ip_video"}
        if asset.quality.status in APPROVED_STATUSES and usable_media:
            roles[asset.role].append(asset)
    return roles


def _brand_cutaway(intent: str, roles: dict[str, list[Asset]]) -> Asset | None:
    is_cta = any(word in intent for word in ("评论", "关注", "点赞", "收藏", "告诉我", "想看", "下期", "再见"))
    is_transition = any(word in intent for word in ("生成中", "等待", "稍等", "马上生成", "正在生成"))
    if not is_cta and not is_transition:
        return None
    candidates = roles["brand_ip_video"] + roles["brand_ip_animation"] + roles["brand_ip_static"]
    if not candidates:
        return None
    preferred_action = "挥手" if is_cta else "跑步"
    return next((asset for asset in candidates if preferred_action in " ".join(asset.tags + [asset.filename])), candidates[0])


def _matching_results(intent: str, slots: list[str], roles: dict[str, list[Asset]], used: set[str]) -> list[Asset]:
    results = roles["result_image"]
    if not results:
        return []
    generic_terms = {"真实结果", "多结果", "结果", "展示", "收束", "文化墙展示", "vi成套展示", "vi系统"}
    terms = [item.lower().replace(" ", "") for item in slots if item.lower().replace(" ", "") not in generic_terms]
    matching = []
    for candidate in results:
        haystack = " ".join(candidate.tags + candidate.claims + [candidate.filename]).lower().replace(" ", "")
        if any(term and term in haystack for term in terms):
            matching.append(candidate)
    pool = matching or results
    fresh = [candidate for candidate in pool if candidate.asset_id not in used]
    return fresh or pool


def _assets_for_beat(
    beat_text: str,
    slots: list[str],
    roles: dict[str, list[Asset]],
    used_results: set[str],
) -> list[tuple[Asset, str]]:
    intent = " ".join(slots + [beat_text]).lower()
    brand_asset = _brand_cutaway(intent, roles)
    if brand_asset:
        return [(brand_asset, "brand_ip_cutaway")]
    if any(word in intent for word in ("参数", "输入", "param", "field", "upload")) and roles["feature_form_params"]:
        return [(roles["feature_form_params"][0], "ui_params_focus")]
    if any(word in intent for word in ("入口", "路径", "entry", "menu")) and roles["feature_entry"]:
        return [(roles["feature_entry"][0], "ui_feature_entry")]
    results = _matching_results(intent, slots, roles, used_results)
    if results:
        return [(asset, "result_showcase") for asset in results[:3]]
    if roles["feature_entry"]:
        return [(roles["feature_entry"][0], "ui_feature_entry")]
    if roles["site_home"]:
        return [(roles["site_home"][0], "ui_feature_entry")]
    raise ValueError(f"no usable visual material for beat: {beat_text}")


def _anchor_for_phrase(asset: Asset, phrase: str) -> str | None:
    normalized = phrase.lower().replace(" ", "")
    for anchor in asset.visual_anchors:
        label = anchor.label.lower().replace(" ", "")
        if label and (label in normalized or normalized in label):
            return anchor.anchor_id
    return None


def _semantic_sfx(template: str, phrase: str) -> str | None:
    normalized = phrase.lower().replace(" ", "")
    if any(word in normalized for word in ("上传", "导入", "参考图", "实景图")):
        return "upload"
    if template == "ui_feature_entry":
        return "ui_click"
    if template == "ui_params_focus":
        return "field_focus"
    if template == "result_showcase":
        return "result_reveal"
    return None


def _claim_ids_for_asset(narration: Narration, beat_id: str, asset_id: str) -> list[str]:
    beat = next(beat for beat in narration.beats if beat.beat_id == beat_id)
    by_id = {claim.claim_id: claim for claim in narration.claims}
    return [claim_id for claim_id in beat.claim_ids if asset_id in by_id[claim_id].supporting_asset_ids]


def _transition(template: str, first_shot: bool) -> TransitionIn:
    if first_shot:
        return TransitionIn()
    if template == "ui_feature_entry":
        return TransitionIn(kind="slide_left", duration_frames=8)
    if template == "result_showcase":
        return TransitionIn(kind="crossfade", duration_frames=8)
    return TransitionIn(kind="crossfade", duration_frames=6)


def build_auto_visual_plan(case_id: str, narration: Narration, timing: TimingLock, catalog: AssetCatalog) -> VisualPlan:
    roles = _role_assets(catalog)
    phrases_by_beat = defaultdict(list)
    for anchor in timing.phrase_anchors:
        phrases_by_beat[anchor.beat_id].append(anchor)
    spans = {span.beat_id: span for span in timing.beat_spans}
    shots: list[ShotPlan] = []
    used_results: set[str] = set()

    for beat in narration.beats:
        span = spans[beat.beat_id]
        candidates = _assets_for_beat(beat.spoken_text, beat.asset_slots, roles, used_results)
        # Short spoken beats stay legible. Only split when each visual can remain on screen for at least 0.8 seconds.
        max_visuals = max(1, (span.end_frame - span.start_frame) // max(1, round(timing.fps * 0.8)))
        candidates = candidates[:max_visuals]
        count = len(candidates)
        for index, (asset, template) in enumerate(candidates):
            if template == "result_showcase":
                used_results.add(asset.asset_id)
            start_offset = round((span.end_frame - span.start_frame) * index / count)
            end_offset = round((span.end_frame - span.start_frame) * (index + 1) / count)
            start = TimeRef(anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}", offset_frames=start_offset)
            end = (
                TimeRef(anchor_id=f"{BEAT_END_ANCHOR_PREFIX}{beat.beat_id}")
                if index == count - 1
                else TimeRef(anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}", offset_frames=end_offset)
            )
            cue_bindings: list[CueBinding] = []
            entrance_sfx = "result_reveal" if template == "result_showcase" else _semantic_sfx(template, beat.spoken_text)
            if entrance_sfx:
                cue_bindings.append(
                    CueBinding(
                        action="visual.enter",
                        anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}",
                        offset_frames=start_offset,
                        sfx=entrance_sfx,
                    )
                )
            for phrase in phrases_by_beat[beat.beat_id]:
                if not (span.start_frame + start_offset <= phrase.hit_frame < span.start_frame + end_offset):
                    continue
                asset_anchor = _anchor_for_phrase(asset, phrase.text) if template.startswith("ui_") else None
                cue_bindings.append(
                    CueBinding(
                        action="focus.hit" if asset_anchor else "visual.hit",
                        anchor_id=phrase.anchor_id,
                        asset_anchor_id=asset_anchor,
                        sfx=None if entrance_sfx else _semantic_sfx(template, phrase.text),
                    )
                )
            motion = "scale_in" if template == "ui_params_focus" else "fade_in" if template == "brand_ip_cutaway" else "none"
            duration = end_offset - start_offset
            long_hold = "appreciation" if duration > timing.fps * 2.2 and template in {"result_showcase", "brand_ip_cutaway"} else None
            shots.append(
                ShotPlan(
                    shot_id=f"shot_{len(shots) + 1:03d}",
                    track="base",
                    beat_ids=[beat.beat_id],
                    start=start,
                    end=end,
                    template=template,
                    asset_bindings={"primary": asset.asset_id},
                    claim_ids=_claim_ids_for_asset(narration, beat.beat_id, asset.asset_id),
                    cue_bindings=cue_bindings,
                    energy="high" if not shots else "medium",
                    motion=motion,
                    transition_in=_transition(template, not shots),
                    long_hold_reason=long_hold,
                )
            )
    return VisualPlan(case_id=case_id, shots=shots)
