from __future__ import annotations

from video_agent.assets.review import FAITHFUL_DERIVE_KINDS
from video_agent.contracts import Asset, EvidenceClass, Narration, VisualPlan


def resolves_to_supporting_asset(
    asset_id: str,
    supporting_asset_ids: set[str],
    asset_by_id: dict[str, Asset],
    seen: set[str] | None = None,
) -> bool:
    if asset_id in supporting_asset_ids:
        return True
    asset = asset_by_id.get(asset_id)
    if asset is None or asset.evidence_class != EvidenceClass.FAITHFUL:
        return False
    derive_kind = str(asset.metadata.get("derive_kind") or "")
    if derive_kind not in FAITHFUL_DERIVE_KINDS:
        return False
    visited = set() if seen is None else set(seen)
    if asset_id in visited:
        return False
    visited.add(asset_id)
    return any(
        resolves_to_supporting_asset(parent_id, supporting_asset_ids, asset_by_id, visited)
        for parent_id in asset.provenance.parent_asset_ids
    )


def validate_claim_bindings(narration: Narration, visual: VisualPlan, asset_by_id: dict[str, Asset]) -> None:
    claims = {claim.claim_id: claim for claim in narration.claims}
    for shot in visual.shots:
        for claim_id in shot.claim_ids:
            claim = claims.get(claim_id)
            if claim is None:
                raise ValueError(f"shot references unknown claim: {claim_id}")
            supporting = [
                asset_id
                for asset_id in shot.asset_ids
                if resolves_to_supporting_asset(asset_id, set(claim.supporting_asset_ids), asset_by_id)
            ]
            if not supporting:
                raise ValueError(f"claim {claim_id} is not supported by an asset visible in {shot.shot_id}")
            invalid = [
                asset_id
                for asset_id in supporting
                if asset_by_id[asset_id].evidence_class not in claim.required_evidence_classes
            ]
            if invalid:
                raise ValueError(f"claim {claim_id} uses insufficient evidence in {shot.shot_id}: {invalid}")
