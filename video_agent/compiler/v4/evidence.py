"""Claim evidence visibility checks against frozen used-assets snapshot."""

from __future__ import annotations

from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    AssetRepositorySnapshot,
    CompiledVisualClip,
    EvidenceClass,
    ResolvedAssetPlan,
    SceneSemanticPlan,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error


_FACTUAL = {EvidenceClass.SOURCE, EvidenceClass.FAITHFUL}


def validate_claim_evidence(
    *,
    scene_plan: SceneSemanticPlan,
    resolved: ResolvedAssetPlan,
    anchored: AnchoredTimingPlan,
    snapshot: AssetRepositorySnapshot,
    base_clips: list[CompiledVisualClip],
) -> None:
    assets = {item.asset_ref: item for item in snapshot.assets}
    anchors = {item.anchor_id: item for item in anchored.anchors}
    bindings = anchored.bindings
    resolved_scenes = {scene.scene_id: scene for scene in resolved.scenes}

    for scene in scene_plan.scenes:
        if not scene.claims:
            continue
        resolved_scene = resolved_scenes.get(scene.scene_id)
        if resolved_scene is None:
            raise Stage6Error("claim_evidence_not_visible", "resolved scene missing", scene_id=scene.scene_id)
        slot_assets = {
            slot.slot_id: slot.asset_ref
            for slot in resolved_scene.slots
            if slot.asset_ref
        }
        for claim in scene.claims:
            claim_bindings = [
                binding
                for binding in bindings
                if binding.scene_id == scene.scene_id
                and binding.binding_kind == "claim"
                and binding.source_id == claim.claim_id
            ]
            if not claim_bindings:
                raise Stage6Error(
                    "claim_evidence_not_visible",
                    f"claim has no anchor binding: {claim.claim_id}",
                    scene_id=scene.scene_id,
                )
            claim_anchor = anchors[claim_bindings[0].anchor_id]
            if claim.evidence_window == "anchor":
                window_start = claim_anchor.hit_frame
                window_end = claim_anchor.hit_frame + 1
            else:
                span = next(s for s in anchored.scene_spans if s.scene_id == scene.scene_id)
                window_start = span.start_frame
                window_end = span.end_frame

            visible_refs: list[str] = []
            for slot_id in claim.supporting_slots:
                asset_ref = slot_assets.get(slot_id)
                if not asset_ref:
                    continue
                snap = assets.get(asset_ref)
                if snap is None:
                    raise Stage6Error(
                        "claim_evidence_not_visible",
                        f"supporting asset missing from snapshot: {asset_ref}",
                        scene_id=scene.scene_id,
                        slot_id=slot_id,
                    )
                if snap.evidence_class not in _FACTUAL:
                    continue
                if claim.claim_id not in snap.claims and claim.phrase not in snap.claims:
                    # Allow empty claims list on E0/E1 only when slot identity itself is evidence carrier
                    if snap.claims:
                        continue
                for clip in base_clips:
                    if clip.scene_id != scene.scene_id:
                        continue
                    if clip.slot_id not in {None, slot_id} and slot_id not in clip.asset_bindings:
                        if asset_ref not in clip.asset_bindings.values():
                            continue
                    if clip.start_frame < window_end and clip.end_frame > window_start:
                        if asset_ref in clip.asset_bindings.values() or clip.slot_id == slot_id:
                            visible_refs.append(asset_ref)
                            break

            if claim.quantifier == "all":
                needed = [slot_assets.get(slot_id) for slot_id in claim.supporting_slots]
                needed = [ref for ref in needed if ref]
                if not needed or any(ref not in visible_refs for ref in needed):
                    raise Stage6Error(
                        "claim_evidence_not_visible",
                        f"claim {claim.claim_id} missing visible supporting assets",
                        scene_id=scene.scene_id,
                        anchor_id=claim_anchor.anchor_id,
                    )
            elif not visible_refs:
                raise Stage6Error(
                    "claim_evidence_not_visible",
                    f"claim {claim.claim_id} has no visible factual evidence",
                    scene_id=scene.scene_id,
                    anchor_id=claim_anchor.anchor_id,
                )
