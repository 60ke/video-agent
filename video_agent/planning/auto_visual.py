from __future__ import annotations

from collections import defaultdict

from video_agent.contracts import Asset, AssetCatalog, CalloutAnimation, CueBinding, Narration, ShotPlan, TimeRef, TimingLock, TransitionIn, VisualPlan


BEAT_START_ANCHOR_PREFIX = "beat_start:"
BEAT_END_ANCHOR_PREFIX = "beat_end:"
TIMELINE_START_ANCHOR = "timeline_start"
TIMELINE_END_ANCHOR = "timeline_end"
APPROVED_STATUSES = {"machine_checked", "vision_verified", "human_approved"}


def _role_assets(catalog: AssetCatalog) -> dict[str, list[Asset]]:
    roles: dict[str, list[Asset]] = defaultdict(list)
    for asset in catalog.assets:
        if not asset.production_eligible:
            continue
        usable_media = asset.media_type == "image" or asset.role in {"brand_ip_animation", "brand_ip_video"}
        if asset.quality.status in APPROVED_STATUSES and usable_media:
            roles[asset.role].append(asset)
    for assets in roles.values():
        assets.sort(key=lambda asset: (asset.provenance.origin != "gpt_image_site_keyframe", asset.filename, asset.asset_id))
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

    def _haystack(asset: Asset) -> str:
        return " ".join(asset.tags + asset.claims + [asset.filename]).lower().replace(" ", "")

    def _matched_term(asset: Asset) -> str | None:
        h = _haystack(asset)
        for term in terms:
            if term and term in h:
                return term
        return None

    if terms:
        matching = [a for a in results if _matched_term(a) is not None]
    else:
        matching = list(results)
    pool = matching or results
    fresh = [a for a in pool if a.asset_id not in used]
    pool = fresh or pool

    # Prioritise one result per matched term first, so that a beat mentioning
    # "宠物服务" + "科技办公" picks one from each industry instead of two
    # from the same industry.
    if not terms:
        return pool
    seen_terms: set[str] = set()
    prioritized: list[Asset] = []
    leftovers: list[Asset] = []
    for candidate in pool:
        term = _matched_term(candidate)
        if term and term not in seen_terms:
            seen_terms.add(term)
            prioritized.append(candidate)
        else:
            leftovers.append(candidate)
    return prioritized + leftovers


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
    if any(word in intent for word in ("首页", "主页", "网站首页", "home")) and roles["site_home"]:
        return [(roles["site_home"][0], "ui_feature_entry")]
    if any(word in intent for word in ("参数", "输入", "param", "field", "upload")) and roles["feature_form_params"]:
        return [(roles["feature_form_params"][0], "ui_params_focus")]
    if any(word in intent for word in ("入口", "路径", "entry", "menu")):
        if roles["feature_entry"]:
            return [(roles["feature_entry"][0], "ui_feature_entry")]
        raise ValueError("approved production feature-entry keyframe is required; source website screenshots cannot be used")
    results = _matching_results(intent, slots, roles, used_results)
    if results:
        return [(asset, "result_showcase") for asset in results[:3]]
    if roles["feature_entry"]:
        return [(roles["feature_entry"][0], "ui_feature_entry")]
    if roles["site_home"]:
        return [(roles["site_home"][0], "ui_feature_entry")]
    raise ValueError(f"no usable visual material for beat: {beat_text}")


def _template_for_asset(asset: Asset) -> str:
    if asset.role == "feature_form_params":
        return "ui_params_focus"
    if asset.role in {"feature_entry", "feature_list", "site_home"}:
        return "ui_feature_entry"
    if asset.role.startswith("brand_ip"):
        return "brand_ip_cutaway"
    return "result_showcase"


def _claim_assets_for_beat(beat_id: str, narration: Narration, catalog: AssetCatalog) -> list[tuple[Asset, str, list[str]]]:
    beat = next(item for item in narration.beats if item.beat_id == beat_id)
    claims = {claim.claim_id: claim for claim in narration.claims}
    assets = {asset.asset_id: asset for asset in catalog.assets}
    selected: dict[str, tuple[Asset, str, list[str]]] = {}
    for cue in beat.claim_cues:
        claim = claims[cue.claim_id]
        candidates = [
            assets[asset_id]
            for asset_id in claim.supporting_asset_ids
            if asset_id in assets
            and assets[asset_id].quality.status in APPROVED_STATUSES
            and (assets[asset_id].media_type == "image" or assets[asset_id].role in {"brand_ip_animation", "brand_ip_video"})
        ]
        if not candidates:
            raise ValueError(f"claim has no approved supporting asset: {beat_id}/{cue.claim_id}")
        asset = candidates[0]
        if asset.asset_id not in selected:
            selected[asset.asset_id] = (asset, cue.phrase, [cue.claim_id])
        else:
            selected[asset.asset_id][2].append(cue.claim_id)
    return list(selected.values())


def _semantic_sfx(template: str, phrase: str) -> str | None:
    normalized = phrase.lower().replace(" ", "")
    if any(word in normalized for word in ("截图", "保存", "定格", "导出图片")):
        return "camera_shutter"
    if any(word in normalized for word in ("生成完成", "任务完成", "成功", "生成好了")):
        return "task_complete"
    if template == "ui_params_focus" and any(word in normalized for word in ("输入", "填写", "名称", "主题", "描述", "必填项")):
        return "typing"
    if any(word in normalized for word in ("上传", "导入", "参考图", "实景图", "点击")):
        return "mouse_click"
    if template == "ui_feature_entry":
        return "mouse_click"
    if template == "ui_params_focus":
        return "mouse_click"
    if template == "result_showcase":
        return "swish"
    return None


def _claim_ids_for_asset(narration: Narration, beat_id: str, asset_id: str) -> list[str]:
    beat = next(beat for beat in narration.beats if beat.beat_id == beat_id)
    by_id = {claim.claim_id: claim for claim in narration.claims}
    return [cue.claim_id for cue in beat.claim_cues if asset_id in by_id[cue.claim_id].supporting_asset_ids]


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
    beat_index = {beat.beat_id: index for index, beat in enumerate(narration.beats)}
    shots: list[ShotPlan] = []
    used_results: set[str] = set()

    for beat in narration.beats:
        span = spans[beat.beat_id]
        claim_assets = _claim_assets_for_beat(beat.beat_id, narration, catalog)
        candidates = (
            [(asset, _template_for_asset(asset)) for asset, _, _ in claim_assets]
            if claim_assets
            else _assets_for_beat(beat.spoken_text, beat.asset_slots, roles, used_results)
        )
        # Short spoken beats stay legible. Only split when each visual can remain on screen for at least 0.8 seconds.
        max_visuals = max(1, (span.end_frame - span.start_frame) // max(1, round(timing.fps * 0.8)))
        if claim_assets and len(candidates) > max_visuals:
            raise ValueError(f"claim visuals cannot meet the 0.8s minimum in {beat.beat_id}")
        candidates = candidates[:max_visuals]
        count = len(candidates)
        for index, (asset, template) in enumerate(candidates):
            if template == "result_showcase":
                used_results.add(asset.asset_id)
            if claim_assets:
                claim_anchor_frames = sorted(
                    anchor.hit_frame
                    for anchor in phrases_by_beat[beat.beat_id]
                    if set(anchor.claim_ids).intersection(claim_assets[index][2])
                )
                hit = claim_anchor_frames[0]
                previous_hit = (
                    max(anchor.hit_frame for anchor in phrases_by_beat[beat.beat_id] if set(anchor.claim_ids).intersection(claim_assets[index - 1][2]))
                    if index
                    else span.start_frame
                )
                next_hit = (
                    min(anchor.hit_frame for anchor in phrases_by_beat[beat.beat_id] if set(anchor.claim_ids).intersection(claim_assets[index + 1][2]))
                    if index + 1 < count
                    else span.end_frame
                )
                start_offset = 0 if index == 0 else round(((previous_hit + hit) / 2) - span.start_frame)
                end_offset = span.end_frame - span.start_frame if index == count - 1 else round(((hit + next_hit) / 2) - span.start_frame)
            else:
                start_offset = round((span.end_frame - span.start_frame) * index / count)
                end_offset = round((span.end_frame - span.start_frame) * (index + 1) / count)
            is_first = not shots
            is_last = beat is narration.beats[-1] and index == count - 1
            start = (
                TimeRef(anchor_id=TIMELINE_START_ANCHOR)
                if is_first
                else TimeRef(anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}", offset_frames=start_offset)
            )
            end = (
                TimeRef(anchor_id=TIMELINE_END_ANCHOR)
                if is_last
                else TimeRef(anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{narration.beats[beat_index[beat.beat_id] + 1].beat_id}")
                if index == count - 1
                else TimeRef(anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}", offset_frames=end_offset)
            )
            cue_bindings: list[CueBinding] = []
            transition = _transition(template, is_first)
            entrance_sfx = (
                "transition_whoosh"
                if transition.kind in {"slide_left", "slide_right"}
                else None
                if template == "ui_feature_entry"
                else _semantic_sfx(template, beat.spoken_text)
            )
            if entrance_sfx:
                cue_bindings.append(
                    CueBinding(
                        action="visual.enter",
                        anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}",
                        offset_frames=start_offset,
                        sfx=entrance_sfx,
                    )
                )
            eligible_phrases = [
                phrase
                for phrase in phrases_by_beat[beat.beat_id]
                if span.start_frame + start_offset + 8 <= phrase.hit_frame < span.start_frame + end_offset
            ]
            callout_anchor_id: str | None = None
            callout_offset = 0
            has_prepared_callout = template == "ui_feature_entry" and asset.role == "feature_entry"
            if has_prepared_callout:
                if eligible_phrases:
                    callout_anchor_id = eligible_phrases[0].anchor_id
                else:
                    callout_anchor_id = f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}"
                    callout_offset = min(18, max(8, end_offset - start_offset - 1)) + start_offset
                cue_bindings.append(
                    CueBinding(
                        action="callout.complete",
                        anchor_id=callout_anchor_id,
                        offset_frames=callout_offset,
                        sfx="mouse_click",
                    )
                )
            for phrase in phrases_by_beat[beat.beat_id]:
                if not (span.start_frame + start_offset <= phrase.hit_frame < span.start_frame + end_offset):
                    continue
                cue_bindings.append(
                    CueBinding(
                        action="visual.hit",
                        anchor_id=phrase.anchor_id,
                        sfx=(
                            None
                            if template == "ui_feature_entry" or _semantic_sfx(template, phrase.text) == entrance_sfx
                            else _semantic_sfx(template, phrase.text)
                        ),
                    )
                )
            motion = "scale_in" if template in {"ui_params_focus", "ui_feature_entry"} else "fade_in" if template == "brand_ip_cutaway" else "none"
            absolute_start = 0 if is_first else span.start_frame + start_offset
            absolute_end = (
                timing.duration_frames
                if is_last
                else spans[narration.beats[beat_index[beat.beat_id] + 1].beat_id].start_frame
                if index == count - 1
                else span.start_frame + end_offset
            )
            duration = absolute_end - absolute_start
            long_hold = "reading" if duration > timing.fps * 2.2 and template == "ui_params_focus" else None
            if duration > timing.fps * 2.2 and template in {"result_showcase", "brand_ip_cutaway"}:
                long_hold = "appreciation"
            if is_last and timing.duration_frames > span.end_frame:
                long_hold = "pause"
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
                    transition_in=transition,
                    long_hold_reason=long_hold,
                    callout_animation=CalloutAnimation() if has_prepared_callout else None,
                )
            )
    return VisualPlan(case_id=case_id, shots=shots)
