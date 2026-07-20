from __future__ import annotations

from video_agent.contracts.v4 import (
    EffectEventIntent,
    SceneMotionIntent,
    SceneSemanticPlan,
    SfxEntry,
    SfxIntent,
    SfxProfileEntry,
)
from video_agent.io import sha256_json
from video_agent.registries import CapabilityRegistryHub

from .errors import Stage5Error


OPERATION_INTENT_LABELS: dict[str, tuple[str, ...]] = {
    "type": ("参数输入", "名称", "主题", "描述"),
    "click": ("菜单点击", "按钮点击", "字段点击"),
    "generate": ("生成完成", "任务完成", "成功"),
    "upload": ("上传",),
    "export": ("导出图片", "截图", "保存", "定格"),
    "select": ("菜单点击", "按钮点击"),
    "edit": ("菜单点击", "按钮点击"),
}

EFFECT_EVENT_LABELS: dict[str, tuple[str, ...]] = {
    "item_transition": ("slide_left", "slide_right", "短结果切换", "大镜头交接"),
    "enter": ("轻量淡变", "短结果切换"),
    "reveal": ("生成完成", "成功"),
    "push_in": ("轻量淡变",),
    "settle": ("轻量淡变",),
    "flip": ("slide_left", "大镜头交接"),
    "grid_enter": ("短结果切换",),
    "compare_reveal": ("短结果切换",),
    "sweep": ("大镜头交接", "轻量淡变"),
    "breath": (),
}


def freeze_sfx_profile(registry: CapabilityRegistryHub, profile_id: str = "normal"):
    from video_agent.contracts.v4.motion_audio import FrozenSfxProfileRef

    entry = registry.entry("sfx_profile", profile_id)
    if not isinstance(entry, SfxProfileEntry):
        raise Stage5Error("missing_sfx_profile", f"unknown sfx profile: {profile_id}")
    document = registry.registry("sfx_profile")
    return FrozenSfxProfileRef(
        profile_id=entry.id,
        profile_version=str(entry.schema_version),
        content_sha256=sha256_json(entry.model_dump(mode="json")),
    ), entry, document.version


def emit_sfx_intents(
    scene_plan: SceneSemanticPlan,
    scene_motions: list[SceneMotionIntent],
    *,
    registry: CapabilityRegistryHub,
    profile_id: str = "normal",
):
    from video_agent.contracts.v4.motion_audio import FrozenSfxProfileRef

    profile_ref, profile, _ = freeze_sfx_profile(registry, profile_id)
    assert isinstance(profile_ref, FrozenSfxProfileRef)
    motions = {item.scene_id: item for item in scene_motions}
    sfx_entries = [
        entry
        for entry in registry.registry("sfx").entries
        if isinstance(entry, SfxEntry) and entry.enabled
    ]

    raw: list[SfxIntent] = []
    for scene in sorted(scene_plan.scenes, key=lambda item: item.order):
        motion = motions.get(scene.scene_id)
        if motion is None:
            continue
        # Operation semantic first.
        for event in scene.events:
            labels = OPERATION_INTENT_LABELS.get(event.intent, ())
            sfx = _match_sfx(
                sfx_entries,
                labels=labels,
                source_kind="operation_semantic",
                direction=motion.effect.direction,
            )
            if sfx is None:
                continue
            raw.append(
                SfxIntent(
                    intent_id=f"sfx:{scene.scene_id}.{event.event_id}",
                    scene_id=scene.scene_id,
                    event_id=None,
                    source_kind="operation_semantic",
                    anchor_phrase=event.phrase if event.phrase in scene.text else scene.text,
                    sfx_id=sfx.id,
                    priority=sfx.capabilities.priority,
                )
            )
        for effect_event in motion.event_intents:
            labels = _effect_labels(effect_event, motion.effect.direction)
            sfx = _match_sfx(
                sfx_entries,
                labels=labels,
                source_kind="effect_event",
                direction=motion.effect.direction,
            )
            if sfx is None:
                continue
            raw.append(
                SfxIntent(
                    intent_id=f"sfx:{effect_event.event_id}",
                    scene_id=scene.scene_id,
                    event_id=effect_event.event_id,
                    source_kind="effect_event",
                    anchor_phrase=effect_event.anchor_phrase,
                    sfx_id=sfx.id,
                    priority=sfx.capabilities.priority,
                )
            )

    return _apply_profile_density(raw, profile), profile_ref


def _effect_labels(event: EffectEventIntent, direction: str) -> tuple[str, ...]:
    base = list(EFFECT_EVENT_LABELS.get(event.event_type, ()))
    if event.event_type == "item_transition":
        if direction == "left":
            base = ["slide_left", *base]
        elif direction == "right":
            base = ["slide_right", *base]
    # de-dupe preserve order
    seen: set[str] = set()
    ordered: list[str] = []
    for label in base:
        if label not in seen:
            seen.add(label)
            ordered.append(label)
    return tuple(ordered)


def _match_sfx(
    entries: list[SfxEntry],
    *,
    labels: tuple[str, ...],
    source_kind: str,
    direction: str,
) -> SfxEntry | None:
    if not labels:
        return None
    matched: list[SfxEntry] = []
    for entry in entries:
        caps = entry.capabilities
        if source_kind not in caps.source_kinds and caps.source_kinds:
            continue
        allowed = set(caps.allowed_event_intents)
        forbidden = set(caps.forbidden_event_intents)
        if any(label in forbidden for label in labels):
            continue
        if not any(label in allowed for label in labels):
            continue
        matched.append(entry)
    if not matched:
        return None
    # Prefer direction-specific whoosh when available.
    if direction in {"left", "right"}:
        for entry in matched:
            if entry.id == "transition_whoosh":
                return entry
    return sorted(matched, key=lambda item: (-item.capabilities.priority, item.id))[0]


def _apply_profile_density(intents: list[SfxIntent], profile: SfxProfileEntry) -> list[SfxIntent]:
    """Stage5 coarse filter only: fold exact duplicates; same-phrase prefer operation.

    Must NOT truncate different Anchors via window_event_budget — that is Stage6 work.
    """
    caps = profile.capabilities
    # Fold field-identical duplicates (keep first by stable intent_id order).
    seen_keys: set[tuple[str, str, str, str, str]] = set()
    deduped: list[SfxIntent] = []
    for intent in sorted(intents, key=lambda item: item.intent_id):
        key = (
            intent.scene_id,
            intent.source_kind,
            intent.anchor_phrase,
            intent.sfx_id,
            intent.event_id or "",
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(intent)

    by_scene: dict[str, list[SfxIntent]] = {}
    for intent in deduped:
        by_scene.setdefault(intent.scene_id, []).append(intent)

    kept: list[SfxIntent] = []
    for scene_id in sorted(by_scene):
        scene_intents = by_scene[scene_id]
        operations = [item for item in scene_intents if item.source_kind == "operation_semantic"]
        effects = [item for item in scene_intents if item.source_kind == "effect_event"]
        if caps.prefer_operation_semantic:
            op_anchors = {item.anchor_phrase for item in operations}
            effects = [item for item in effects if item.anchor_phrase not in op_anchors]
        combined = sorted(
            [*operations, *effects],
            key=lambda item: (
                0 if item.source_kind == "operation_semantic" else 1,
                -item.priority,
                item.intent_id,
            ),
        )
        # window_event_budget is a Stage6 time-window capacity, not a Stage5 list truncate.
        kept.extend(combined)
    return kept
