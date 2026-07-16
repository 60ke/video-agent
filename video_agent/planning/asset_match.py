from __future__ import annotations

from collections import defaultdict

from video_agent.contracts import Asset, AssetCatalog


ENUMERATED_GENERIC_TERMS = {"真实结果", "多结果", "结果", "展示", "设计方案", "功能", "功能总览"}
FEATURE_TERM_ALIASES = {
    "门店招牌": ("门店招牌", "门头招牌"),
    "品牌logo": ("品牌logo", "logo"),
    "品牌标志": ("品牌标志", "logo"),
    "商业美陈": ("商业美陈", "美陈"),
    "电商视觉": ("电商视觉", "电商"),
}


def _normalized_term(value: str) -> str:
    return "".join(value.lower().split()).replace("_", "").replace("*", "")


def _feature_terms(term: str) -> tuple[str, ...]:
    normalized = _normalized_term(term)
    return FEATURE_TERM_ALIASES.get(normalized, (normalized,))


def role_assets(catalog: AssetCatalog) -> dict[str, list[Asset]]:
    roles: dict[str, list[Asset]] = defaultdict(list)
    for asset in catalog.assets:
        usable = asset.media_type == "image" or asset.role in {"brand_ip_animation", "brand_ip_video"}
        if not asset.production_eligible or asset.quality.status == "rejected" or not usable:
            continue
        if (
            asset.provenance.origin == "gpt_image_semantic_derivative"
            and asset.metadata.get("purpose") in {"asset_preflight", "action_scene"}
        ):
            continue
        if asset.role == "feature_form_params" and asset.metadata.get("sequence_role") not in {None, "base"}:
            continue
        roles[asset.role].append(asset)
    for values in roles.values():
        values.sort(
            key=lambda asset: (
                asset.provenance.origin not in {"gpt_image_site_keyframe", "curated_workflow_scene"},
                asset.filename,
                asset.asset_id,
            )
        )
    return roles


def brand_cutaway(intent: str, roles: dict[str, list[Asset]]) -> Asset | None:
    is_cta = any(word in intent for word in ("评论", "关注", "点赞", "收藏", "告诉我", "想看", "下期", "再见", "零基础", "轻松上手", "功能齐全"))
    is_transition = any(word in intent for word in ("生成中", "等待", "稍等", "马上生成", "正在生成", "实景功能"))
    if not is_cta and not is_transition:
        return None
    candidates = roles.get("brand_ip_video", []) + roles.get("brand_ip_animation", []) + roles.get("brand_ip_static", [])
    if not candidates:
        return None
    preferred = "挥手" if is_cta else "跑步"
    return next((asset for asset in candidates if preferred in " ".join(asset.tags + [asset.filename])), candidates[0])


def feature_result_matches(term: str, asset: Asset) -> bool:
    labels = [_normalized_term(item) for item in [*asset.semantic_path[1:], *asset.tags] if item]
    return any(candidate in label or label in candidate for candidate in _feature_terms(term) for label in labels)


def feature_result_match_score(term: str, asset: Asset) -> tuple[int, int, str]:
    terms = _feature_terms(term)
    canonical = _normalized_term(asset.semantic_path[1]) if len(asset.semantic_path) > 1 else ""
    content_type = str(asset.metadata.get("content_type") or "")
    variant_kind = str(asset.metadata.get("variant_kind") or "")
    content_rank = 0 if content_type.startswith("installed_") or variant_kind == "industry_scene" else 2 if variant_kind == "external_video_material" else 1
    if any(canonical == candidate for candidate in terms):
        return (0, content_rank, asset.asset_id)
    if any(candidate in canonical or canonical in candidate for candidate in terms):
        return (1, content_rank, asset.asset_id)
    tags = [_normalized_term(item) for item in asset.tags]
    if any(candidate == tag for candidate in terms for tag in tags):
        return (2, content_rank, asset.asset_id)
    return (3, content_rank, asset.asset_id)


def enumerated_result_pairs(anchors: list[object], roles: dict[str, list[Asset]], used: set[str]) -> list[tuple[Asset, object]]:
    selected: list[tuple[Asset, object]] = []
    for anchor in anchors:
        phrase = _normalized_term(anchor.text)
        if not phrase or phrase in ENUMERATED_GENERIC_TERMS:
            continue
        matches = sorted(
            (asset for asset in roles.get("result_image", []) if feature_result_matches(anchor.text, asset)),
            key=lambda asset: feature_result_match_score(anchor.text, asset),
        )
        fresh = [asset for asset in matches if asset.asset_id not in used and all(asset.asset_id != item[0].asset_id for item in selected)]
        candidate = next(iter(fresh or [asset for asset in matches if all(asset.asset_id != item[0].asset_id for item in selected)]), None)
        if candidate is not None:
            selected.append((candidate, anchor))
    return selected


def asset_matches_feature(asset: Asset, feature: str) -> bool:
    labels = [_normalized_term(label) for label in [*asset.semantic_path[1:], *asset.tags] if label]
    return any(candidate == label or candidate in label or label in candidate for candidate in _feature_terms(feature) for label in labels)


def feature_scope(text: str, slots: list[str], roles: dict[str, list[Asset]]) -> str | None:
    source = _normalized_term(" ".join([text, *slots]))
    known = {
        _normalized_term(label)
        for assets in roles.values()
        for asset in assets
        for label in asset.semantic_path[1:2]
        if label
    }
    matches = [feature for feature in known if feature and any(alias in source for alias in _feature_terms(feature))]
    return max(matches, key=len) if matches else None


def motion_for(asset: Asset, template: str) -> str:
    preferred = asset.metadata.get("preferred_effect")
    if isinstance(preferred, str) and preferred in {
        "card_flip_3d", "paper_curl_flip", "spring_card_pop", "grid_reveal", "vertical_scroll",
        "full_bleed_to_safe_card", "image_pan_scan", "detail_push_in",
    }:
        return preferred
    if template == "ui_params_focus":
        return "scale_in"
    if template == "ui_feature_entry":
        return "detail_push_in"
    if template == "brand_ip_cutaway":
        return "brand_breath"
    ratio = (asset.width or 1) / (asset.height or 1)
    if ratio >= 1.35:
        return "full_bleed_to_safe_card"
    if ratio <= 0.74:
        return "vertical_scroll"
    return "grid_reveal"
