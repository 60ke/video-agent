from __future__ import annotations

import pytest

from video_agent.contracts.v4 import (
    MaterialSlot,
    OperationEvent,
    SceneSemanticPlan,
    SemanticScene,
    SpeechTimingLock,
    SpeechTokenTimingV4,
    AssetQuerySource,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.timing.v4.anchor_compiler import build_anchored_timing_plan


def _speech(tokens: list[tuple[str, int, int]], *, fps: int = 30) -> SpeechTimingLock:
    items = []
    for index, (text, start_ms, end_ms) in enumerate(tokens):
        start_frame = int(round(start_ms * fps / 1000))
        end_frame = max(start_frame + 1, int(round(end_ms * fps / 1000)))
        items.append(
            SpeechTokenTimingV4(
                token_id=f"tok_{index:04d}",
                text=text,
                start_ms=start_ms,
                end_ms=end_ms,
                start_frame=start_frame,
                end_frame=end_frame,
                beat_id=None,
            )
        )
    duration_ms = tokens[-1][2]
    return SpeechTimingLock(
        schema_version=1,
        case_id="case",
        run_id="run",
        narration_sha256="a" * 64,
        audio_object_key="audio/speech.wav",
        audio_sha256="a" * 64,
        voice_profile_id="v",
        voice_profile_version="1",
        voice_profile_sha256="a" * 64,
        fps=fps,
        duration_ms=duration_ms,
        duration_frames=max(1, int(round(duration_ms * fps / 1000))),
        tokens=items,
        pause_events=[],
        beat_spans=[],
    )


def test_anchor_compiler_builds_scene_spans_and_shared_anchors() -> None:
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s001",
                order=1,
                text="打开文化墙功能",
                visual_structure="single",
                slots=[
                    MaterialSlot(
                        slot_id="main",
                        anchor_phrase="文化墙",
                        entry_policy="phrase_start",
                        hold_policy="scene_end",
                        category_id=None,
                        asset_role="feature_entry",
                        source=AssetQuerySource(kind="asset_query"),
                        subtitle_emphasis="keyword",
                    )
                ],
                events=[
                    OperationEvent(
                        event_id="e1",
                        phrase="文化墙",
                        intent="click",
                        target_slot="main",
                    )
                ],
                inputs=[],
                outputs=[],
                claims=[],
                no_asset=False,
            )
        ]
    )
    speech = _speech([("打开", 0, 200), ("文化墙", 200, 500), ("功能", 500, 800)])
    plan = build_anchored_timing_plan(
        case_id="case",
        run_id="run",
        narration_sha256="a" * 64,
        speech=speech,
        scene_plan=scene_plan,
    )
    assert len(plan.scene_spans) == 1
    assert plan.scene_spans[0].start_frame == speech.tokens[0].start_frame
    assert plan.scene_spans[0].end_frame == speech.duration_frames
    # slot + operation share one canonical anchor
    assert len(plan.anchors) == 1
    assert len(plan.bindings) == 2
    assert {b.binding_kind for b in plan.bindings} == {"slot", "operation"}


def test_anchor_compiler_fails_on_ambiguous_phrase() -> None:
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s001",
                order=1,
                text="文化墙和再看文化墙",
                visual_structure="single",
                slots=[
                    MaterialSlot(
                        slot_id="main",
                        anchor_phrase="文化墙",
                        entry_policy="phrase_start",
                        hold_policy="scene_end",
                        category_id=None,
                        asset_role="feature_entry",
                        source=AssetQuerySource(kind="asset_query"),
                        subtitle_emphasis="none",
                    )
                ],
                events=[
                    OperationEvent(
                        event_id="e1",
                        phrase="文化墙",
                        intent="click",
                        target_slot="main",
                    )
                ],
                inputs=[],
                outputs=[],
                claims=[],
                no_asset=False,
            )
        ]
    )
    speech = _speech([("文化墙", 0, 300), ("和再看", 300, 600), ("文化墙", 600, 900)])
    # First binding consumes first occurrence; second binding searching forward finds second — OK
    plan = build_anchored_timing_plan(
        case_id="case",
        run_id="run",
        narration_sha256="a" * 64,
        speech=speech,
        scene_plan=scene_plan,
    )
    assert len(plan.anchors) == 2

    # Ambiguous: same phrase twice but second source cannot uniquely resolve when cursor already past both
    scene_plan2 = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s001",
                order=1,
                text="文化墙和再看文化墙",
                visual_structure="single",
                slots=[],
                events=[
                    OperationEvent(event_id="e1", phrase="文化墙", intent="click", target_slot=None),
                    OperationEvent(event_id="e2", phrase="文化墙", intent="click", target_slot=None),
                    OperationEvent(event_id="e3", phrase="文化墙", intent="click", target_slot=None),
                ],
                inputs=[],
                outputs=[],
                claims=[],
                no_asset=False,
            )
        ]
    )
    with pytest.raises(Stage6Error) as exc:
        build_anchored_timing_plan(
            case_id="case",
            run_id="run",
            narration_sha256="a" * 64,
            speech=speech,
            scene_plan=scene_plan2,
        )
    assert exc.value.code == "anchor_phrase_ambiguous"


def test_anchor_unresolved_phrase() -> None:
    scene_plan = SceneSemanticPlan(
        scenes=[
            SemanticScene(
                scene_id="s001",
                order=1,
                text="打开功能",
                visual_structure="single",
                slots=[
                    MaterialSlot(
                        slot_id="main",
                        anchor_phrase="文化墙",
                        entry_policy="phrase_start",
                        hold_policy="scene_end",
                        category_id=None,
                        asset_role="feature_entry",
                        source=AssetQuerySource(kind="asset_query"),
                        subtitle_emphasis="none",
                    )
                ],
                events=[],
                inputs=[],
                outputs=[],
                claims=[],
                no_asset=False,
            )
        ]
    )
    speech = _speech([("打开", 0, 200), ("功能", 200, 400)])
    with pytest.raises(Stage6Error) as exc:
        build_anchored_timing_plan(
            case_id="case",
            run_id="run",
            narration_sha256="a" * 64,
            speech=speech,
            scene_plan=scene_plan,
        )
    assert exc.value.code == "anchor_unresolved"
