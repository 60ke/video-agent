"""Anchor Compiler: SceneSemanticPlan + SpeechTimingLock → AnchoredTimingPlan."""

from __future__ import annotations

from video_agent.contracts.v4 import (
    AnchorBinding,
    AnchoredSceneSpan,
    AnchoredTimingPlan,
    PhraseAnchorV4,
    SceneSemanticPlan,
    SpeechTimingLock,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.io import sha256_json
from video_agent.timing.v4.speech_lock import normalize_text
from video_agent.timing.v4.text_alignment import project_char_span_to_token_ids
from video_agent.timing.v4.timebase import ms_to_hit_frame, ms_to_interval_end


def build_anchored_timing_plan(
    *,
    case_id: str,
    run_id: str,
    narration_sha256: str,
    speech: SpeechTimingLock,
    scene_plan: SceneSemanticPlan,
    effect_event_phrases: list[tuple[str, str, str]] | None = None,
    sfx_intent_phrases: list[tuple[str, str, str]] | None = None,
) -> AnchoredTimingPlan:
    """Compile scene spans and canonical PhraseAnchorV4 bindings.

    effect_event_phrases / sfx_intent_phrases: optional (scene_id, source_id, phrase).
    """
    token_norms = [(token.token_id, normalize_text(token.text)) for token in speech.tokens]
    full_norm = "".join(text for _, text in token_norms)
    ordered = sorted(scene_plan.scenes, key=lambda item: item.order)
    scene_norm = "".join(normalize_text(scene.text) for scene in ordered)
    if full_norm != scene_norm:
        raise Stage6Error("speech_text_mismatch", "speech tokens do not cover SceneSemanticPlan text")

    tokens_by_id = {token.token_id: token for token in speech.tokens}
    scene_spans: list[AnchoredSceneSpan] = []
    anchors: list[PhraseAnchorV4] = []
    bindings: list[AnchorBinding] = []
    anchor_by_key: dict[tuple[str, int, int], str] = {}

    cursor = 0
    for index, scene in enumerate(ordered):
        needle = normalize_text(scene.text)
        if not needle:
            raise Stage6Error("scene_span_gap", "empty scene text", scene_id=scene.scene_id)
        start = full_norm.find(needle, cursor)
        if start != cursor:
            raise Stage6Error(
                "scene_span_gap",
                f"scene text not contiguous at char {cursor}",
                scene_id=scene.scene_id,
            )
        end = start + len(needle)
        token_ids = project_char_span_to_token_ids(tokens=token_norms, start_char=start, end_char=end)
        if not token_ids:
            raise Stage6Error("scene_span_gap", "scene has no intersecting tokens", scene_id=scene.scene_id)
        start_frame = tokens_by_id[token_ids[0]].start_frame
        if index + 1 < len(ordered):
            next_needle = normalize_text(ordered[index + 1].text)
            next_start = end  # contiguous
            next_ids = project_char_span_to_token_ids(
                tokens=token_norms,
                start_char=next_start,
                end_char=next_start + len(next_needle),
            )
            if not next_ids:
                raise Stage6Error("scene_span_gap", "next scene missing tokens", scene_id=ordered[index + 1].scene_id)
            end_frame = tokens_by_id[next_ids[0]].start_frame
        else:
            end_frame = speech.duration_frames
        if end_frame <= start_frame:
            raise Stage6Error("scene_span_overlap", "non-positive scene span", scene_id=scene.scene_id)
        if scene_spans and start_frame < scene_spans[-1].end_frame:
            raise Stage6Error("scene_span_overlap", "overlapping scene spans", scene_id=scene.scene_id)
        scene_spans.append(
            AnchoredSceneSpan(
                scene_id=scene.scene_id,
                token_ids=token_ids,
                start_frame=start_frame,
                end_frame=end_frame,
            )
        )

        local_norm = full_norm[start:end]
        local_cursor = 0
        phrase_sources = _collect_phrase_sources(
            scene,
            effect_event_phrases=effect_event_phrases,
            sfx_intent_phrases=sfx_intent_phrases,
        )
        for kind, source_id, phrase in phrase_sources:
            if phrase not in scene.text:
                raise Stage6Error(
                    "anchor_unresolved",
                    f"phrase not verbatim in scene text: {phrase!r}",
                    scene_id=scene.scene_id,
                    slot_id=source_id if kind == "slot" else None,
                    event_id=source_id if kind in {"operation", "effect_event", "sfx_intent"} else None,
                )
            needle_p = normalize_text(phrase)
            if not needle_p:
                raise Stage6Error("anchor_unresolved", "empty phrase", scene_id=scene.scene_id)
            pos = _resolve_phrase_position(
                local_norm=local_norm,
                needle=needle_p,
                local_cursor=local_cursor,
                scene_id=scene.scene_id,
                phrase=phrase,
            )
            phrase_end = pos + len(needle_p)
            abs_start = start + pos
            abs_end = start + phrase_end
            hit_token_ids = project_char_span_to_token_ids(
                tokens=token_norms, start_char=abs_start, end_char=abs_end
            )
            if not hit_token_ids:
                raise Stage6Error("anchor_unresolved", "phrase has no tokens", scene_id=scene.scene_id)
            key = (scene.scene_id, abs_start, abs_end)
            if key in anchor_by_key:
                anchor_id = anchor_by_key[key]
            else:
                first = tokens_by_id[hit_token_ids[0]]
                last = tokens_by_id[hit_token_ids[-1]]
                onset = ms_to_hit_frame(first.start_ms, speech.fps)
                end_fr = max(onset + 1, ms_to_interval_end(last.end_ms, speech.fps))
                anchor_id = f"anchor://{scene.scene_id}/c{abs_start}_{abs_end}"
                anchors.append(
                    PhraseAnchorV4(
                        anchor_id=anchor_id,
                        scene_id=scene.scene_id,
                        text=phrase,
                        token_ids=hit_token_ids,
                        onset_ms=first.start_ms,
                        end_ms=last.end_ms,
                        onset_frame=onset,
                        end_frame=end_fr,
                        hit_frame=onset,
                    )
                )
                anchor_by_key[key] = anchor_id
            bindings.append(
                AnchorBinding(
                    binding_id=f"binding://{scene.scene_id}/{kind}/{source_id}",
                    scene_id=scene.scene_id,
                    anchor_id=anchor_id,
                    binding_kind=kind,  # type: ignore[arg-type]
                    source_id=source_id,
                )
            )
            local_cursor = max(local_cursor, phrase_end)
        cursor = end

    return AnchoredTimingPlan(
        schema_version=1,
        case_id=case_id,
        run_id=run_id,
        narration_sha256=narration_sha256,
        speech_timing_lock_sha256=sha256_json(speech),
        scene_plan_sha256=sha256_json(scene_plan),
        fps=speech.fps,
        duration_frames=speech.duration_frames,
        scene_spans=scene_spans,
        anchors=anchors,
        bindings=bindings,
    )


def _collect_phrase_sources(
    scene,
    *,
    effect_event_phrases: list[tuple[str, str, str]] | None,
    sfx_intent_phrases: list[tuple[str, str, str]] | None,
) -> list[tuple[str, str, str]]:
    sources: list[tuple[str, str, str]] = []
    for slot in scene.slots:
        sources.append(("slot", slot.slot_id, slot.anchor_phrase))
    for event in scene.events:
        sources.append(("operation", event.event_id, event.phrase))
    for claim in scene.claims:
        sources.append(("claim", claim.claim_id, claim.phrase))
    if effect_event_phrases:
        for scene_id, source_id, phrase in effect_event_phrases:
            if scene_id == scene.scene_id:
                sources.append(("effect_event", source_id, phrase))
    if sfx_intent_phrases:
        for scene_id, source_id, phrase in sfx_intent_phrases:
            if scene_id == scene.scene_id:
                sources.append(("sfx_intent", source_id, phrase))
    # no_asset scenes still need a scene-level PhraseAnchor for light_sweep / SFX.
    if not sources and (scene.no_asset or scene.visual_structure == "no_asset_transition"):
        sources.append(("operation", f"{scene.scene_id}.scene", scene.text))
    return sources


def _resolve_phrase_position(
    *,
    local_norm: str,
    needle: str,
    local_cursor: int,
    scene_id: str,
    phrase: str,
) -> int:
    """Locate phrase using declaration order + forward cursor; fail-loud on ambiguity."""
    forward = local_norm.find(needle, local_cursor)
    if forward >= 0:
        return forward

    matches: list[int] = []
    search = 0
    while True:
        found = local_norm.find(needle, search)
        if found < 0:
            break
        matches.append(found)
        search = found + 1
    if not matches:
        raise Stage6Error(
            "anchor_unresolved",
            f"phrase not found in scene tokens: {phrase!r}",
            scene_id=scene_id,
        )
    if len(matches) > 1:
        raise Stage6Error(
            "anchor_phrase_ambiguous",
            f"phrase occurs {len(matches)} times without unique forward match: {phrase!r}",
            scene_id=scene_id,
        )
    return matches[0]
