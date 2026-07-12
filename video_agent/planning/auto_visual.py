from __future__ import annotations

from collections import defaultdict

from video_agent.contracts import Asset, AssetCatalog, CueBinding, Narration, ShotPlan, TimingLock, VisualPlan


BEAT_START_ANCHOR_PREFIX = "beat_start:"


def _role_assets(catalog: AssetCatalog) -> dict[str, list[Asset]]:
    roles: dict[str, list[Asset]] = defaultdict(list)
    for asset in catalog.assets:
        usable_media = asset.media_type == "image" or asset.role in {"brand_ip_animation", "brand_ip_video"}
        if asset.quality.status in {"machine_checked", "vision_verified", "human_approved"} and usable_media:
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
    return next(
        (asset for asset in candidates if preferred_action in " ".join(asset.tags + [asset.filename])),
        candidates[0],
    )


def _asset_for_beat(
    beat_index: int,
    beat_text: str,
    slots: list[str],
    roles: dict[str, list[Asset]],
    result_index: int,
    used_result_ids: set[str],
) -> tuple[Asset, str, int]:
    intent = " ".join(slots + [beat_text]).lower()
    brand_asset = _brand_cutaway(intent, roles)
    if brand_asset:
        return brand_asset, "brand_ip_cutaway", result_index
    if any(word in intent for word in ("参数", "输入", "param", "field", "upload")) and roles["feature_form_params"]:
        return roles["feature_form_params"][0], "ui_params_focus", result_index
    if any(word in intent for word in ("入口", "路径", "entry", "menu")) and roles["feature_entry"]:
        return roles["feature_entry"][0], "ui_feature_entry", result_index
    if roles["result_image"]:
        generic_terms = {"真实结果", "多结果", "结果", "展示", "收束", "文化墙展示", "vi成套展示", "vi系统"}
        terms = [item.lower().replace(" ", "") for item in slots if item.lower().replace(" ", "") not in generic_terms]
        matching = []
        for candidate in roles["result_image"]:
            haystack = " ".join(candidate.tags + candidate.claims + [candidate.filename]).lower().replace(" ", "")
            if any(term and term in haystack for term in terms):
                matching.append(candidate)
        pool = matching or roles["result_image"]
        asset = next((candidate for candidate in pool if candidate.asset_id not in used_result_ids), None)
        if asset is None:
            asset = pool[result_index % len(pool)]
        return asset, "result_safe_stage", result_index + 1
    if roles["feature_entry"]:
        return roles["feature_entry"][0], "ui_feature_entry", result_index
    if roles["site_home"]:
        return roles["site_home"][0], "ui_feature_entry", result_index
    raise ValueError(f"no usable image asset for beat {beat_index + 1}")


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
    if template == "result_safe_stage":
        return "result_reveal"
    return None


def build_auto_visual_plan(case_id: str, narration: Narration, timing: TimingLock, catalog: AssetCatalog) -> VisualPlan:
    roles = _role_assets(catalog)
    phrase_by_beat = defaultdict(list)
    for anchor in timing.phrase_anchors:
        phrase_by_beat[anchor.beat_id].append(anchor)
    shots: list[ShotPlan] = []
    result_index = 0
    used_result_ids: set[str] = set()
    result_effects = ("scale_in", "crossfade", "page_slide")
    for index, beat in enumerate(narration.beats):
        asset, template, result_index = _asset_for_beat(
            index,
            beat.spoken_text,
            beat.asset_slots,
            roles,
            result_index,
            used_result_ids,
        )
        if template == "result_safe_stage":
            used_result_ids.add(asset.asset_id)
        bindings: list[CueBinding] = []
        phrase_anchors = phrase_by_beat[beat.beat_id]
        entrance_sfx = "result_reveal" if template == "result_safe_stage" else None
        if entrance_sfx or not phrase_anchors:
            fallback_sfx = entrance_sfx or _semantic_sfx(template, beat.spoken_text)
            bindings.append(
                CueBinding(
                    action="visual.enter",
                    anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}",
                    sfx=fallback_sfx,
                )
            )
        for phrase_index, phrase_anchor in enumerate(phrase_anchors):
            asset_anchor = _anchor_for_phrase(asset, phrase_anchor.text) if template.startswith("ui_") else None
            bindings.append(
                CueBinding(
                    action="focus.hit" if asset_anchor else "visual.hit",
                    anchor_id=phrase_anchor.anchor_id,
                    asset_anchor_id=asset_anchor,
                    sfx=_semantic_sfx(template, phrase_anchor.text) if phrase_index == 0 and not entrance_sfx else None,
                )
            )
        if template == "ui_params_focus":
            effect = "scale_in"
        elif template == "ui_feature_entry":
            effect = "page_slide"
        elif template == "brand_ip_cutaway":
            effect = "fade_in" if asset.media_type == "video" else "scale_in"
        else:
            effect = result_effects[index % len(result_effects)]
        span = next(item for item in timing.beat_spans if item.beat_id == beat.beat_id)
        event_frames = [span.start_frame] + sorted(item.hit_frame for item in phrase_by_beat[beat.beat_id]) + [span.end_frame]
        max_gap = max((right - left for left, right in zip(event_frames, event_frames[1:])), default=0)
        long_hold = None
        if max_gap > timing.fps * 2.2:
            long_hold = "appreciation" if template in {"result_safe_stage", "brand_ip_cutaway"} else "reading"
        shots.append(
            ShotPlan(
                shot_id=f"shot_{index + 1:03d}",
                beat_id=beat.beat_id,
                template=template,
                asset_ids=[asset.asset_id],
                cue_bindings=bindings,
                energy="high" if index == 0 else "medium",
                effect=effect,
                long_hold_reason=long_hold,
            )
        )
    return VisualPlan(case_id=case_id, shots=shots)
