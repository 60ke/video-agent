from __future__ import annotations

from pathlib import Path

from video_agent.contracts.v4.resolved_assets import GapAction, Stage4SelectionConfig
from video_agent.contracts.v4.scene import SemanticScene
from video_agent.io import load_json

from .stage4_errors import Stage4Error


def load_selection_config(path: Path) -> Stage4SelectionConfig:
    return Stage4SelectionConfig.model_validate(load_json(path))


def resolve_gap_action(
    config: Stage4SelectionConfig,
    *,
    source_kind: str,
    asset_role: str,
    pattern_id: str | None,
    scene: SemanticScene,
) -> GapAction:
    matched: GapAction | None = None
    for rule in config.gap_policies:
        if rule.source_kind != source_kind or rule.asset_role != asset_role:
            continue
        if rule.pattern_id is not None and rule.pattern_id != pattern_id:
            continue
        matched = rule.action
        if rule.pattern_id == pattern_id:
            break
    if matched is None:
        raise Stage4Error(
            "no_candidate_asset",
            f"no gap policy for source={source_kind} role={asset_role} pattern={pattern_id}",
            scene_id=scene.scene_id,
        )
    if matched == "resolve_no_asset" and not _allows_no_asset(scene):
        raise Stage4Error(
            "no_candidate_asset",
            "resolve_no_asset only allowed for no_asset_transition scenes without claims/required slots",
            scene_id=scene.scene_id,
        )
    return matched


def _allows_no_asset(scene: SemanticScene) -> bool:
    if scene.visual_structure != "no_asset_transition" and not scene.no_asset:
        return False
    if scene.claims:
        return False
    required_slots = [slot for slot in scene.slots if slot.asset_role != "none"]
    return not required_slots or scene.no_asset
