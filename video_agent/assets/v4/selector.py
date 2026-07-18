from __future__ import annotations

import hashlib
import math
import random

from video_agent.contracts.v4 import AssetRecord
from video_agent.contracts.v4.resolved_assets import CandidateSummary, RankMode, Stage4SelectionConfig


def candidate_summary_from_asset(asset: AssetRecord) -> CandidateSummary:
    return CandidateSummary(
        asset_ref=asset.asset_ref,
        display_name=asset.filename,
        module=asset.module,
        category_path=list(asset.category_path),
        asset_role=asset.asset_role,
        case_label=asset.case_label,
        industry=asset.industry,
        description=asset.description,
        orientation=asset.orientation.value,
        source_kind=asset.source_kind.value,
        evidence_class=asset.evidence_class.value,
        claims=list(asset.claims),
    )


def select_asset(
    candidates: list[AssetRecord],
    *,
    config: Stage4SelectionConfig,
    run_seed: str,
    seed_material: str,
    preferred_orientation: str | None = None,
    usage_counts: dict[str, int] | None = None,
) -> tuple[AssetRecord, RankMode, dict[str, float]]:
    if not candidates:
        raise ValueError("select_asset requires at least one candidate")
    if len(candidates) == 1:
        return candidates[0], "single", {"only_candidate": 1.0}

    weights = config.weights
    usage_counts = usage_counts or {}
    scored: list[tuple[float, str, AssetRecord, dict[str, float]]] = []
    for asset in candidates:
        breakdown = {
            "original_source": weights.get("original_source", 0.25) if asset.source_kind.value == "original" else 0.0,
            "orientation_continuity": (
                weights.get("orientation_continuity", 0.2)
                if preferred_orientation and asset.orientation.value == preferred_orientation
                else 0.0
            ),
            "recent_usage_penalty": -weights.get("recent_usage_penalty", 0.3) * float(usage_counts.get(asset.asset_ref, 0)),
        }
        score = sum(breakdown.values())
        scored.append((score, asset.asset_ref, asset, breakdown))

    max_score = max(item[0] for item in scored)
    ordered = sorted(scored, key=lambda item: item[1])
    probabilities = [math.exp(item[0] - max_score) for item in ordered]
    rng = random.Random(_seed_int(run_seed, seed_material))
    chosen = rng.choices(ordered, weights=probabilities, k=1)[0]
    return chosen[2], "deterministic_weighted", chosen[3]


def select_group(
    groups: list,
    *,
    run_seed: str,
    seed_material: str,
    assets_by_ref: dict[str, AssetRecord] | None = None,
):
    if not groups:
        raise ValueError("select_group requires at least one candidate")
    if len(groups) == 1:
        return groups[0], "single"
    assets_by_ref = assets_by_ref or {}
    scored = [(_group_priority(group, assets_by_ref), group.group_ref, group) for group in groups]
    best = max(item[0] for item in scored)
    top = sorted((item for item in scored if item[0] == best), key=lambda item: item[1])
    rng = random.Random(_seed_int(run_seed, seed_material))
    return rng.choice(top)[2], "deterministic_weighted"


def _group_priority(group, assets_by_ref: dict[str, AssetRecord]) -> tuple[int, int, int]:
    members = {member.member_key: assets_by_ref.get(member.asset_ref) for member in group.members}
    originals = sum(1 for asset in members.values() if asset and asset.source_kind.value == "original")
    source_evidence = sum(1 for asset in members.values() if asset and asset.evidence_class.value == "E0_source_evidence")
    causal_tier = 0
    if group.pattern_id == "reference_result_plan":
        reference = members.get("reference_image")
        result = members.get("result_image")
        if reference and result:
            if reference.source_kind.value == "original" and result.source_kind.value == "original":
                causal_tier = 4
            elif reference.source_kind.value == "original":
                causal_tier = 3
            elif result.source_kind.value == "original":
                causal_tier = 2
            else:
                causal_tier = 1
    return causal_tier, originals, source_evidence


def _seed_int(run_seed: str, seed_material: str) -> int:
    digest = hashlib.sha256(f"{run_seed}:{seed_material}".encode("utf-8")).hexdigest()
    return int(digest[:16], 16)
