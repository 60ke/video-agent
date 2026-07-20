from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from .common import DomainValidationError, ValidationIssue, V4Contract
from .scene import SceneSemanticPlan


MotionDirection = Literal["none", "left", "right", "up", "down"]
SfxSourceKind = Literal["operation_semantic", "effect_event"]

_SHA256 = r"^[a-f0-9]{64}$"
_FORBIDDEN_PARAM_KEYS = frozenset(
    {
        "start_frame",
        "end_frame",
        "hit_frame",
        "onset_frame",
        "start_ms",
        "end_ms",
        "timestamp",
        "track_start",
        "audio_start",
        "cue_id",
        "subtitle",
    }
)


class EffectBinding(V4Contract):
    effect_id: str = Field(min_length=1)
    effect_version: str = Field(min_length=1)
    layout_profile_id: str = Field(min_length=1)
    direction: MotionDirection = "none"
    parameters: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @field_validator("parameters")
    @classmethod
    def reject_timing_keys(cls, value: dict[str, str | int | float | bool]) -> dict[str, str | int | float | bool]:
        bad = sorted(key for key in value if key.lower() in _FORBIDDEN_PARAM_KEYS or "frame" in key.lower())
        if bad:
            raise ValueError(f"EffectBinding.parameters forbid timing/frame keys: {bad}")
        return value


class EffectEventIntent(V4Contract):
    event_id: str = Field(min_length=1)
    event_type: str = Field(min_length=1)
    slot_id: str | None = None
    member_key: str | None = None
    anchor_phrase: str = Field(min_length=1)


class SceneMotionIntent(V4Contract):
    scene_id: str = Field(min_length=1)
    continuity_group_id: str | None = None
    effect: EffectBinding
    event_intents: list[EffectEventIntent] = Field(default_factory=list)


class FrozenSfxProfileRef(V4Contract):
    profile_id: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    content_sha256: str = Field(pattern=_SHA256)


class SfxIntent(V4Contract):
    intent_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    event_id: str | None = None
    source_kind: SfxSourceKind
    anchor_phrase: str = Field(min_length=1)
    sfx_id: str = Field(min_length=1)
    priority: int = Field(ge=0)


class MotionAudioPlan(V4Contract):
    schema_version: int = Field(ge=1)
    run_seed: str = Field(min_length=1)
    scene_plan_sha256: str = Field(pattern=_SHA256)
    resolved_asset_plan_sha256: str = Field(pattern=_SHA256)
    speech_timing_lock_sha256: str = Field(pattern=_SHA256)
    anchored_timing_plan_sha256: str = Field(pattern=_SHA256)
    registry_snapshot_id: str = Field(min_length=1)
    scenes: list[SceneMotionIntent] = Field(min_length=1)
    sfx_profile: FrozenSfxProfileRef
    sfx_intents: list[SfxIntent] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> MotionAudioPlan:
        scene_ids = [scene.scene_id for scene in self.scenes]
        if len(scene_ids) != len(set(scene_ids)):
            raise ValueError("MotionAudioPlan.scenes scene_id must be unique")
        event_ids = [event.event_id for scene in self.scenes for event in scene.event_intents]
        if len(event_ids) != len(set(event_ids)):
            raise ValueError("EffectEventIntent.event_id must be unique within the plan")
        intent_ids = [intent.intent_id for intent in self.sfx_intents]
        if len(intent_ids) != len(set(intent_ids)):
            raise ValueError("SfxIntent.intent_id must be unique within the plan")
        return self


def validate_motion_audio_plan(plan: MotionAudioPlan, scene_plan: SceneSemanticPlan) -> None:
    issues: list[ValidationIssue] = []
    planned = [scene.scene_id for scene in sorted(scene_plan.scenes, key=lambda item: item.order)]
    actual = [scene.scene_id for scene in plan.scenes]
    if actual != planned:
        issues.append(
            ValidationIssue(
                code="scene_order_mismatch",
                path="scenes",
                message="MotionAudioPlan scenes must match SceneSemanticPlan order exactly",
            )
        )
    scenes_by_id = {scene.scene_id: scene for scene in scene_plan.scenes}
    continuity_bindings: dict[str, tuple[str, str, str]] = {}
    declared_events = {event.event_id for scene in plan.scenes for event in scene.event_intents}

    for index, motion in enumerate(plan.scenes):
        semantic = scenes_by_id.get(motion.scene_id)
        if semantic is None:
            issues.append(
                ValidationIssue(
                    code="unknown_scene",
                    path=f"scenes[{index}].scene_id",
                    message=f"unknown scene_id {motion.scene_id}",
                )
            )
            continue
        for event in motion.event_intents:
            if event.anchor_phrase not in semantic.text:
                issues.append(
                    ValidationIssue(
                        code="anchor_not_in_scene_text",
                        path=f"scenes[{index}].event_intents",
                        message=f"anchor_phrase not in scene text: {event.anchor_phrase}",
                    )
                )
            if event.slot_id is not None and event.slot_id not in {slot.slot_id for slot in semantic.slots}:
                issues.append(
                    ValidationIssue(
                        code="unknown_slot",
                        path=f"scenes[{index}].event_intents",
                        message=f"unknown slot_id {event.slot_id}",
                    )
                )
        if motion.continuity_group_id:
            key = (
                motion.effect.effect_id,
                motion.effect.direction,
                motion.effect.layout_profile_id,
            )
            previous = continuity_bindings.get(motion.continuity_group_id)
            if previous is None:
                continuity_bindings[motion.continuity_group_id] = key
            elif previous != key:
                issues.append(
                    ValidationIssue(
                        code="continuity_mismatch",
                        path=f"scenes[{index}].continuity_group_id",
                        message=(
                            f"continuity group {motion.continuity_group_id} must share "
                            "effect/direction/layout"
                        ),
                    )
                )

    for index, intent in enumerate(plan.sfx_intents):
        if intent.scene_id not in scenes_by_id:
            issues.append(
                ValidationIssue(
                    code="sfx_unknown_scene",
                    path=f"sfx_intents[{index}].scene_id",
                    message=f"unknown scene_id {intent.scene_id}",
                )
            )
            continue
        semantic = scenes_by_id[intent.scene_id]
        if intent.anchor_phrase not in semantic.text:
            issues.append(
                ValidationIssue(
                    code="sfx_anchor_not_in_scene_text",
                    path=f"sfx_intents[{index}].anchor_phrase",
                    message=f"anchor_phrase not in scene text: {intent.anchor_phrase}",
                )
            )
        if intent.source_kind == "effect_event":
            if not intent.event_id or intent.event_id not in declared_events:
                issues.append(
                    ValidationIssue(
                        code="sfx_missing_event",
                        path=f"sfx_intents[{index}].event_id",
                        message="effect_event SFX must reference a declared EffectEventIntent",
                    )
                )
        elif intent.event_id is not None and intent.event_id not in declared_events:
            # operation_semantic may omit event_id; if present it must exist.
            issues.append(
                ValidationIssue(
                    code="sfx_unknown_event",
                    path=f"sfx_intents[{index}].event_id",
                    message=f"unknown event_id {intent.event_id}",
                )
            )

    if issues:
        raise DomainValidationError("MotionAudioPlan", issues)
