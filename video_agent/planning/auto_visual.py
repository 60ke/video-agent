from __future__ import annotations

from collections import defaultdict

from video_agent.compiler.evidence import resolves_to_supporting_asset
from video_agent.contracts import Asset, AssetCatalog, CueBinding, Narration, ParameterFrameSequence, ShotPlan, TimeRef, TimingLock, TransitionIn, VisualPlan


BEAT_START_ANCHOR_PREFIX = "beat_start:"
TIMELINE_START_ANCHOR = "timeline_start"
TIMELINE_END_ANCHOR = "timeline_end"
APPROVED_STATUSES = {"machine_checked", "vision_verified", "human_approved"}
MAX_REPRESENTATIVE_VISUALS = 3
ENUMERATED_GENERIC_TERMS = {
    "真实结果",
    "多结果",
    "结果",
    "展示",
    "设计方案",
    "功能",
    "功能总览",
}
# Spoken copy naturally uses a few product-facing aliases that are different
# from the canonical feature names used by the material catalog.
FEATURE_TERM_ALIASES = {
    "门店招牌": ("门店招牌", "门头招牌"),
    "品牌logo": ("品牌logo", "logo"),
    "品牌标志": ("品牌标志", "logo"),
    "商业美陈": ("商业美陈", "美陈"),
}
MIN_VISUAL_SECONDS = {
    "feature_entry_marker": 1.2,
    "ui_feature_entry": 1.5,
    "ui_params_focus": 2.2,
    "result_showcase": 1.2,
    "reference_to_result": 1.5,
    "brand_ip_cutaway": 1.2,
}
REFERENCE_COMPARISON_TERMS = (
    "实景图",
    "实景参考",
    "参考图",
    "现场照片",
    "改造前",
    "改造后",
    "生成前",
    "生成后",
    "前后对比",
    "效果对比",
    "对比图",
)
OPENING_EXPLICIT_VISUAL_TERMS = (
    "首页",
    "主页",
    "网站首页",
    "参数",
    "输入",
    "上传",
    "点击",
    "进入",
    "选择",
    "功能入口",
    "真实结果",
    "生成效果",
    "案例",
    "参考图",
)


def _minimum_visual_frames(asset: Asset, template: str, fps: int) -> int:
    key = "feature_entry_marker" if template == "ui_feature_entry" and asset.role == "feature_entry" else template
    return max(1, round(fps * MIN_VISUAL_SECONDS.get(key, 1.2)))


def _representative_candidates(candidates: list[tuple[Asset, str]], count: int) -> list[tuple[Asset, str]]:
    if count >= len(candidates):
        return candidates
    if count <= 1:
        return [candidates[len(candidates) // 2]]
    indexes = [round(index * (len(candidates) - 1) / (count - 1)) for index in range(count)]
    return [candidates[index] for index in indexes]


def _fit_visual_candidates(
    candidates: list[tuple[Asset, str]],
    duration_frames: int,
    fps: int,
    *,
    all_required: bool,
    beat_id: str,
) -> list[tuple[Asset, str]]:
    if not candidates:
        raise ValueError(f"no visual candidates for {beat_id}")
    if all_required:
        required_frames = sum(_minimum_visual_frames(asset, template, fps) for asset, template in candidates)
        if required_frames > duration_frames:
            raise ValueError(
                f"claim visuals need {required_frames / fps:.2f}s but {beat_id} has {duration_frames / fps:.2f}s"
            )
        return candidates
    limit = min(len(candidates), MAX_REPRESENTATIVE_VISUALS)
    while limit > 1:
        selected = _representative_candidates(candidates, limit)
        if sum(_minimum_visual_frames(asset, template, fps) for asset, template in selected) <= duration_frames:
            return selected
        limit -= 1
    selected = _representative_candidates(candidates, 1)
    minimum = _minimum_visual_frames(*selected[0], fps)
    if minimum > duration_frames:
        raise ValueError(
            f"{selected[0][1]} needs at least {minimum / fps:.2f}s but {beat_id} has {duration_frames / fps:.2f}s"
        )
    return selected


def _normalized_term(value: str) -> str:
    return "".join(value.lower().split()).replace("_", "").replace("*", "")


def _feature_terms(term: str) -> tuple[str, ...]:
    normalized = _normalized_term(term)
    return FEATURE_TERM_ALIASES.get(normalized, (normalized,))


def _matching_phrase_anchor(asset: Asset, anchors: list[object]) -> object | None:
    # Timing anchors bind to structured catalog semantics (feature path and
    # curator tags), never a coincidental word in a filename.
    labels = [_normalized_term(label) for label in [*asset.semantic_path[1:], *asset.tags] if label]
    matches = [
        anchor
        for anchor in anchors
        if any(
            any(term in label or label in term for term in _feature_terms(anchor.text))
            for label in labels
        )
    ]
    return matches[0] if matches else None


def _role_assets(catalog: AssetCatalog) -> dict[str, list[Asset]]:
    roles: dict[str, list[Asset]] = defaultdict(list)
    for asset in catalog.assets:
        if not asset.production_eligible:
            continue
        usable_media = asset.media_type == "image" or asset.role in {"brand_ip_animation", "brand_ip_video"}
        if asset.quality.status in APPROVED_STATUSES and usable_media:
            if asset.role == "feature_form_params" and asset.metadata.get("sequence_role") != "base":
                continue
            roles[asset.role].append(asset)
    for assets in roles.values():
        assets.sort(key=lambda asset: (asset.provenance.origin != "gpt_image_site_keyframe", asset.filename, asset.asset_id))
    return roles


def _brand_cutaway(intent: str, roles: dict[str, list[Asset]]) -> Asset | None:
    is_cta = any(word in intent for word in ("评论", "关注", "点赞", "收藏", "告诉我", "想看", "下期", "再见", "挑战一天", "真的可以"))
    is_transition = any(word in intent for word in ("生成中", "等待", "稍等", "马上生成", "正在生成"))
    if not is_cta and not is_transition:
        return None
    candidates = roles["brand_ip_video"] + roles["brand_ip_animation"] + roles["brand_ip_static"]
    if not candidates:
        return None
    preferred_action = "挥手" if is_cta else "跑步"
    return next((asset for asset in candidates if preferred_action in " ".join(asset.tags + [asset.filename])), candidates[0])


def _opening_defaults_to_home(beat: object, roles: dict[str, list[Asset]]) -> bool:
    """Use the site home for an unqualified opening instead of a mascot cutaway."""

    if not roles.get("site_home") or beat.visual_strategy == "enumerated_results" or beat.claim_cues:
        return False
    intent = " ".join([beat.spoken_text, *beat.asset_slots]).lower()
    return not any(term in intent for term in OPENING_EXPLICIT_VISUAL_TERMS)


def _matching_results(intent: str, slots: list[str], roles: dict[str, list[Asset]], used: set[str]) -> list[Asset]:
    results = roles["result_image"]
    if not results:
        return []
    generic_terms = {"真实结果", "多结果", "结果", "展示", "收束", "文化墙展示", "vi成套展示", "vi系统"}
    terms = [item.lower().replace(" ", "") for item in slots if item.lower().replace(" ", "") not in generic_terms]

    def _haystack(asset: Asset) -> str:
        return " ".join(asset.semantic_path + asset.tags + asset.claims + [asset.filename]).lower().replace(" ", "")

    def _matched_term(asset: Asset) -> str | None:
        haystack = _haystack(asset)
        for term in terms:
            if term and term in haystack:
                return term
        return None

    matching = [asset for asset in results if _matched_term(asset) is not None] if terms else list(results)
    if not matching:
        return []
    fresh = [asset for asset in matching if asset.asset_id not in used]
    pool = fresh or matching
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


def _requires_reference_comparison(text: str, slots: list[str]) -> bool:
    intent = " ".join([text, *slots]).lower().replace(" ", "")
    return any(term in intent for term in REFERENCE_COMPARISON_TERMS)


def _reference_to_result_pair(text: str, slots: list[str], roles: dict[str, list[Asset]], used: set[str]) -> tuple[Asset, Asset] | None:
    """Return a same-feature reference/result pair only for explicit comparison copy."""

    if not _requires_reference_comparison(text, slots):
        return None
    results = _matching_results(text, slots, roles, used)
    references = roles.get("reference_image", [])
    if not results or not references:
        return None
    for result in results:
        same_feature = [reference for reference in references if reference.semantic_path == result.semantic_path]
        if same_feature:
            return same_feature[0], result
    return None


def _feature_result_matches(term: str, asset: Asset) -> bool:
    feature_labels = [_normalized_term(item) for item in [*asset.semantic_path[1:], *asset.tags] if item]
    return any(
        candidate in label or label in candidate
        for candidate in _feature_terms(term)
        for label in feature_labels
    )


def _enumerated_results(hit_phrases: list[str], roles: dict[str, list[Asset]], used: set[str]) -> list[Asset]:
    selected: list[Asset] = []
    missing: list[str] = []
    for phrase in hit_phrases:
        matches = [asset for asset in roles["result_image"] if _feature_result_matches(phrase, asset)]
        fresh = [asset for asset in matches if asset.asset_id not in used and asset not in selected]
        candidate = next(iter(fresh or [asset for asset in matches if asset not in selected]), None)
        if candidate is None:
            missing.append(phrase)
        else:
            selected.append(candidate)
    if missing:
        raise ValueError("enumerated result assets are missing for: " + ", ".join(missing))
    return selected


def _enumerated_result_pairs(anchors: list[object], roles: dict[str, list[Asset]], used: set[str]) -> list[tuple[Asset, object]]:
    """Resolve each spoken feature anchor to one distinct result image.

    The anchor travels with the chosen material until scheduling, so a broad
    feature such as ``美陈`` cannot later attach itself to a different phrase.
    """

    selected: list[tuple[Asset, object]] = []
    for anchor in anchors:
        phrase = _normalized_term(anchor.text)
        if not phrase or phrase in ENUMERATED_GENERIC_TERMS:
            continue
        matches = [asset for asset in roles["result_image"] if _feature_result_matches(anchor.text, asset)]
        fresh = [asset for asset in matches if asset.asset_id not in used and all(asset.asset_id != item[0].asset_id for item in selected)]
        candidate = next(iter(fresh or [asset for asset in matches if all(asset.asset_id != item[0].asset_id for item in selected)]), None)
        if candidate is not None:
            selected.append((candidate, anchor))
    return selected


def _matching_feature_entries(slots: list[str], roles: dict[str, list[Asset]]) -> list[Asset]:
    generic_terms = {"功能入口", "入口", "路径", "主流设计需求", "设计方案"}
    terms = [item.lower().replace(" ", "") for item in slots if item.lower().replace(" ", "") not in generic_terms]
    entries = roles.get("feature_entry", [])

    def _haystack(asset: Asset) -> str:
        return " ".join(asset.semantic_path + asset.tags + [asset.filename]).lower().replace(" ", "")

    selected: list[Asset] = []
    for term in terms:
        if not term:
            continue
        match = next((asset for asset in entries if term in _haystack(asset) and asset not in selected), None)
        if match:
            selected.append(match)
    return selected


def _assets_for_beat(
    beat_text: str,
    slots: list[str],
    roles: dict[str, list[Asset]],
    used_results: set[str],
    *,
    visual_strategy: str = "auto",
    hit_phrases: list[str] | None = None,
) -> list[tuple[Asset, str]]:
    if visual_strategy == "enumerated_results":
        results = _enumerated_results(hit_phrases or [], roles, used_results)
        return [(asset, "result_showcase") for asset in results]
    intent = " ".join(slots + [beat_text]).lower()
    brand_asset = _brand_cutaway(intent, roles)
    if brand_asset:
        return [(brand_asset, "brand_ip_cutaway")]
    if any(word in intent for word in ("首页", "主页", "网站首页", "home")) and roles["site_home"]:
        return [(roles["site_home"][0], "ui_feature_entry")]
    if any(word in intent for word in ("参数", "输入", "param", "field", "upload")):
        if roles["feature_form_params"]:
            return [(roles["feature_form_params"][0], "ui_params_focus")]
        raise ValueError("a human-approved complete parameter frame sequence is required for a parameter-page beat")
    if any(word in intent for word in ("功能列表", "小功能", "功能总览")) and roles.get("feature_list"):
        return [(roles["feature_list"][0], "ui_feature_entry")]
    navigation_intent = any(word in intent for word in ("点击", "进入", "选择", "展开", "导航路径", "操作路径", "功能入口", "entry", "menu"))
    if navigation_intent:
        matched_entries = _matching_feature_entries(slots, roles)
        if matched_entries:
            return [(asset, "ui_feature_entry") for asset in matched_entries]
        if roles["feature_entry"]:
            return [(roles["feature_entry"][0], "ui_feature_entry")]
        raise ValueError("approved production feature-entry keyframe is required; source website screenshots cannot be used")
    comparison = _reference_to_result_pair(beat_text, slots, roles, used_results)
    if comparison:
        return [(comparison[1], "reference_to_result")]
    results = _matching_results(intent, slots, roles, used_results)
    if results:
        return [(asset, "result_showcase") for asset in results[:3]]
    if any(word in intent for word in ("十几类", "全能覆盖")) and roles.get("feature_list"):
        return [(roles["feature_list"][0], "ui_feature_entry")]
    if roles.get("feature_list"):
        return [(roles["feature_list"][0], "ui_feature_entry")]
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
    if template in {"ui_feature_entry", "ui_params_focus"}:
        return "mouse_click"
    if template == "result_showcase":
        return "swish"
    return None


def _claim_ids_for_asset(narration: Narration, beat_id: str, asset_id: str, catalog: AssetCatalog) -> list[str]:
    beat = next(item for item in narration.beats if item.beat_id == beat_id)
    claims = {claim.claim_id: claim for claim in narration.claims}
    asset_by_id = {asset.asset_id: asset for asset in catalog.assets}
    return [
        cue.claim_id
        for cue in beat.claim_cues
        if resolves_to_supporting_asset(asset_id, set(claims[cue.claim_id].supporting_asset_ids), asset_by_id)
    ]


def _transition(template: str, first_shot: bool, *, enumerated_result: bool = False) -> TransitionIn:
    if first_shot:
        return TransitionIn()
    if enumerated_result:
        return TransitionIn(kind="slide_left", duration_frames=8)
    if template == "ui_feature_entry":
        return TransitionIn(kind="slide_left", duration_frames=8)
    if template == "result_showcase":
        return TransitionIn(kind="crossfade", duration_frames=8)
    return TransitionIn(kind="crossfade", duration_frames=6)


def _windowed_assets(catalog: AssetCatalog, beat_id: str, start_frame: int, end_frame: int) -> list[tuple[Asset, str, int, int]]:
    scheduled: list[tuple[Asset, str, int, int]] = []
    for asset in catalog.assets:
        metadata = asset.metadata
        if metadata.get("beat_id") != beat_id:
            continue
        preferred_start = metadata.get("preferred_start_frame")
        preferred_end = metadata.get("preferred_end_frame")
        if preferred_start is None and preferred_end is None:
            continue
        if preferred_start is None or preferred_end is None:
            raise ValueError(f"materialized asset has an incomplete preferred window: {asset.asset_id}")
        preferred_start = int(preferred_start)
        preferred_end = int(preferred_end)
        if not (start_frame <= preferred_start < preferred_end <= end_frame):
            raise ValueError(
                f"materialized asset window is outside {beat_id}: {asset.asset_id}/{preferred_start}-{preferred_end}"
            )
        if asset.quality.status not in APPROVED_STATUSES or not asset.production_eligible:
            raise ValueError(f"materialized asset for locked window is not approved: {asset.asset_id}/{asset.quality.status}")
        scheduled.append((asset, _template_for_asset(asset), preferred_start, preferred_end))
    scheduled.sort(key=lambda item: (item[2], item[3], item[0].asset_id))
    for previous, current in zip(scheduled, scheduled[1:], strict=False):
        if current[2] < previous[3]:
            raise ValueError(
                f"materialized preferred windows overlap in {beat_id}: {previous[0].asset_id} and {current[0].asset_id}"
            )
    return scheduled


def _schedule_with_locked_windows(
    candidates: list[tuple[Asset, str]],
    locked: list[tuple[Asset, str, int, int]],
    start_frame: int,
    end_frame: int,
    *,
    all_required: bool,
    beat_id: str,
) -> list[tuple[Asset, str, int, int]]:
    locked_ids = {asset.asset_id for asset, _, _, _ in locked}
    base_candidates = [candidate for candidate in candidates if candidate[0].asset_id not in locked_ids]
    gaps: list[tuple[int, int]] = []
    cursor = start_frame
    for _, _, locked_start, locked_end in locked:
        if cursor < locked_start:
            gaps.append((cursor, locked_start))
        cursor = locked_end
    if cursor < end_frame:
        gaps.append((cursor, end_frame))

    if gaps and not base_candidates:
        raise ValueError(f"locked materialized windows leave uncovered time with no base visual in {beat_id}")
    if all_required and len(base_candidates) > len(gaps):
        raise ValueError(f"locked materialized windows leave too few intervals for required claim visuals in {beat_id}")

    if not gaps:
        return locked
    if all_required:
        selected = base_candidates
    else:
        selected = _representative_candidates(base_candidates, min(len(gaps), len(base_candidates)))
    base_schedule = [
        (*selected[index % len(selected)], gap_start, gap_end)
        for index, (gap_start, gap_end) in enumerate(gaps)
    ]
    return sorted([*base_schedule, *locked], key=lambda item: (item[2], item[3], item[0].asset_id))


def build_auto_visual_plan(case_id: str, narration: Narration, timing: TimingLock, catalog: AssetCatalog) -> VisualPlan:
    roles = _role_assets(catalog)
    phrases_by_beat = defaultdict(list)
    for anchor in timing.phrase_anchors:
        phrases_by_beat[anchor.beat_id].append(anchor)
    spans = {span.beat_id: span for span in timing.beat_spans}
    shots: list[ShotPlan] = []
    used_results: set[str] = set()

    for beat_index, beat in enumerate(narration.beats):
        span = spans[beat.beat_id]
        next_span = spans[narration.beats[beat_index + 1].beat_id] if beat_index + 1 < len(narration.beats) else None
        claim_assets = _claim_assets_for_beat(beat.beat_id, narration, catalog)
        beat_anchors = sorted(phrases_by_beat[beat.beat_id], key=lambda anchor: anchor.hit_frame)
        requested_anchors = [anchor for anchor in beat_anchors if anchor.text in beat.hit_phrases]
        enumerated_pairs = _enumerated_result_pairs(
            requested_anchors if beat.visual_strategy == "enumerated_results" else beat_anchors,
            roles,
            used_results,
        )
        beat_intent = " ".join([beat.spoken_text, *beat.asset_slots]).lower()
        navigation_intent = any(word in beat_intent for word in ("点击", "进入", "选择", "展开", "导航路径", "操作路径", "功能入口", "entry", "menu"))
        # Only result-showcase copy may infer enumeration. A navigation phrase
        # can also name several features, but it must remain an entry flow.
        is_enumerated = beat.visual_strategy == "enumerated_results" or (not navigation_intent and len(enumerated_pairs) >= 2)
        if beat.visual_strategy == "enumerated_results" and len(enumerated_pairs) != len(beat.hit_phrases):
            resolved = {anchor.text for _, anchor in enumerated_pairs}
            missing = [phrase for phrase in beat.hit_phrases if phrase not in resolved]
            raise ValueError("enumerated result assets are missing for: " + ", ".join(missing))
        starts_with_home = beat_index == 0 and _opening_defaults_to_home(beat, roles)
        candidates = (
            [(asset, _template_for_asset(asset)) for asset, _, _ in claim_assets]
            if claim_assets
            else [(roles["site_home"][0], "ui_feature_entry")]
            if starts_with_home
            else [(asset, "result_showcase") for asset, _ in enumerated_pairs]
            if is_enumerated
            else _assets_for_beat(
                beat.spoken_text,
                beat.asset_slots,
                roles,
                used_results,
                visual_strategy=beat.visual_strategy,
                hit_phrases=beat.hit_phrases,
            )
        )
        comparison = _reference_to_result_pair(beat.spoken_text, beat.asset_slots, roles, used_results) if not claim_assets else None
        locked = _windowed_assets(catalog, beat.beat_id, span.start_frame, span.end_frame)
        if locked:
            schedule = _schedule_with_locked_windows(
                candidates,
                locked,
                span.start_frame,
                span.end_frame,
                all_required=bool(claim_assets) or is_enumerated,
                beat_id=beat.beat_id,
            )
        else:
            candidates = _fit_visual_candidates(
                candidates,
                span.end_frame - span.start_frame,
                timing.fps,
                all_required=bool(claim_assets) or is_enumerated,
                beat_id=beat.beat_id,
            )
            enumerated_anchors = [anchor for _, anchor in enumerated_pairs] if is_enumerated else []
            if enumerated_anchors and any(anchor is None for anchor in enumerated_anchors):
                raise ValueError(f"enumerated result phrase anchors are incomplete in {beat.beat_id}")
            count = len(candidates)
            schedule = []
            for index, (asset, template) in enumerate(candidates):
                if claim_assets:
                    claim_anchor_frames = sorted(
                        anchor.hit_frame
                        for anchor in phrases_by_beat[beat.beat_id]
                        if set(anchor.claim_ids).intersection(claim_assets[index][2])
                    )
                    hit = claim_anchor_frames[0]
                    previous_hit = (
                        max(
                            anchor.hit_frame
                            for anchor in phrases_by_beat[beat.beat_id]
                            if set(anchor.claim_ids).intersection(claim_assets[index - 1][2])
                        )
                        if index
                        else span.start_frame
                    )
                    next_hit = (
                        min(
                            anchor.hit_frame
                            for anchor in phrases_by_beat[beat.beat_id]
                            if set(anchor.claim_ids).intersection(claim_assets[index + 1][2])
                        )
                        if index + 1 < count
                        else span.end_frame
                    )
                    absolute_start = span.start_frame if index == 0 else round((previous_hit + hit) / 2)
                    absolute_end = span.end_frame if index == count - 1 else round((hit + next_hit) / 2)
                elif enumerated_anchors:
                    hit = enumerated_anchors[index].hit_frame
                    previous_hit = enumerated_anchors[index - 1].hit_frame if index else span.start_frame
                    next_hit = enumerated_anchors[index + 1].hit_frame if index + 1 < count else span.end_frame
                    absolute_start = span.start_frame if index == 0 else round((previous_hit + hit) / 2)
                    absolute_end = span.end_frame if index == count - 1 else round((hit + next_hit) / 2)
                else:
                    absolute_start = span.start_frame + round((span.end_frame - span.start_frame) * index / count)
                    absolute_end = span.start_frame + round((span.end_frame - span.start_frame) * (index + 1) / count)
                schedule.append((asset, template, absolute_start, absolute_end))

        for index, (asset, template, absolute_start, absolute_end) in enumerate(schedule):
            if template == "result_showcase":
                used_results.add(asset.asset_id)
            is_first = not shots
            is_last = beat_index == len(narration.beats) - 1 and index == len(schedule) - 1
            is_beat_tail = index == len(schedule) - 1
            content_start = absolute_start
            content_end = absolute_end
            shot_start = 0 if is_first and absolute_start > 0 else absolute_start
            shot_end = absolute_end
            pause_hold = False
            if is_last and timing.duration_frames > span.end_frame:
                shot_end = timing.duration_frames
                pause_hold = True
            elif is_beat_tail and next_span is not None and shot_end < next_span.start_frame:
                shot_end = next_span.start_frame
                pause_hold = True
            start = (
                TimeRef(anchor_id=TIMELINE_START_ANCHOR)
                if shot_start == 0
                else TimeRef(
                    anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}",
                    offset_frames=shot_start - span.start_frame,
                )
            )
            if shot_end == timing.duration_frames:
                end = TimeRef(anchor_id=TIMELINE_END_ANCHOR)
            elif pause_hold and next_span is not None and shot_end == next_span.start_frame:
                end = TimeRef(anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{narration.beats[beat_index + 1].beat_id}")
            else:
                end = TimeRef(
                    anchor_id=f"{BEAT_START_ANCHOR_PREFIX}{beat.beat_id}",
                    offset_frames=shot_end - span.start_frame,
                )
            cue_bindings: list[CueBinding] = []
            transition = _transition(template, is_first, enumerated_result=is_enumerated and template == "result_showcase")
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
                        offset_frames=content_start - span.start_frame,
                        sfx=entrance_sfx,
                    )
                )
            for phrase in phrases_by_beat[beat.beat_id]:
                if not (content_start <= phrase.hit_frame < content_end):
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
            duration = shot_end - shot_start
            motion = (
                "scale_in"
                if template == "ui_params_focus"
                else "page_turn_3d"
                if asset.role == "site_home"
                else "detail_push_in"
                if template == "ui_feature_entry"
                else "full_bleed_to_safe_card"
                if template == "result_showcase"
                else "brand_breath"
                if template == "brand_ip_cutaway"
                else "none"
            )
            long_hold = "reading" if duration > timing.fps * 2.2 and template == "ui_params_focus" else None
            if duration > timing.fps * 2.2 and template in {"result_showcase", "brand_ip_cutaway", "ui_feature_entry"}:
                long_hold = "appreciation"
            if pause_hold:
                long_hold = "pause"
            asset_bindings = {"primary": asset.asset_id}
            parameter_sequence = None
            if template == "ui_params_focus":
                sequence_ids = asset.metadata.get("sequence_asset_ids")
                if not isinstance(sequence_ids, dict) or set(sequence_ids) != {"base", "stage", "final"}:
                    raise ValueError(f"parameter-page asset has no complete approved frame sequence: {asset.asset_id}")
                parameter_sequence = ParameterFrameSequence(
                    sequence_id=str(asset.metadata.get("sequence_id") or ""),
                    base_asset_id=str(sequence_ids["base"]),
                    stage_asset_id=str(sequence_ids["stage"]),
                    final_asset_id=str(sequence_ids["final"]),
                    required_field_labels=[str(item) for item in asset.metadata.get("required_field_labels", [])],
                    callout_text=str(asset.metadata.get("callout_text") or ""),
                )
                asset_bindings = {
                    "base": parameter_sequence.base_asset_id,
                    "stage": parameter_sequence.stage_asset_id,
                    "final": parameter_sequence.final_asset_id,
                }
            if template == "reference_to_result":
                if comparison is None or comparison[1].asset_id != asset.asset_id:
                    raise ValueError(f"reference comparison pair is missing for {beat.beat_id}")
                reference, result = comparison
                asset_bindings = {"reference": reference.asset_id, "result": result.asset_id}
            shots.append(
                ShotPlan(
                    shot_id=f"shot_{len(shots) + 1:03d}",
                    track="base",
                    beat_ids=[beat.beat_id],
                    start=start,
                    end=end,
                    template=template,
                    asset_bindings=asset_bindings,
                    claim_ids=_claim_ids_for_asset(narration, beat.beat_id, asset.asset_id, catalog),
                    cue_bindings=cue_bindings,
                    energy="high" if not shots else "medium",
                    motion=motion,
                    transition_in=transition,
                    long_hold_reason=long_hold,
                    parameter_sequence=parameter_sequence,
                )
            )
    return VisualPlan(case_id=case_id, shots=shots)
