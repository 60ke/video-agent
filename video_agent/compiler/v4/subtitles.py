"""V4 subtitle compilation — single-line cues bound to PhraseAnchors."""

from __future__ import annotations

from video_agent.compiler.v4.font_measure import (
    DEFAULT_SUBTITLE_FONT_PX,
    measure_text_width_px,
)
from video_agent.contracts.v4 import (
    AnchoredTimingPlan,
    CompiledSubtitleCueV4,
    SceneSemanticPlan,
    SpeechTimingLock,
)
from video_agent.contracts.v4.stage6_errors import Stage6Error
from video_agent.platform.profiles import PlatformProfile, get_profile


BREAK_PUNCTUATION = set("，。！？；：、")
ORPHAN_CONNECTORS = {"从", "到", "和", "及", "与", "以及"}


def compile_subtitles_v4(
    *,
    speech: SpeechTimingLock,
    scene_plan: SceneSemanticPlan,
    anchored: AnchoredTimingPlan,
    platform_profile_id: str = "douyin_portrait_v1",
    font_px: int = DEFAULT_SUBTITLE_FONT_PX,
    profile: PlatformProfile | None = None,
) -> list[CompiledSubtitleCueV4]:
    platform = profile or get_profile(platform_profile_id)
    tokens_by_id = {token.token_id: token for token in speech.tokens}
    spans = {span.scene_id: span for span in anchored.scene_spans}
    gallery_phrases: dict[str, set[str]] = {}
    keyword_by_scene: dict[str, list[tuple[str, str]]] = {}
    for scene in scene_plan.scenes:
        if scene.visual_structure == "gallery":
            gallery_phrases[scene.scene_id] = {slot.anchor_phrase for slot in scene.slots}
        keyword_by_scene[scene.scene_id] = [
            (slot.slot_id, slot.anchor_phrase)
            for slot in scene.slots
            if slot.subtitle_emphasis == "keyword"
        ]

    cues: list[CompiledSubtitleCueV4] = []
    # Gallery yellow cues: one per gallery slot at hit frame
    for binding in anchored.bindings:
        if binding.binding_kind != "slot":
            continue
        phrases = gallery_phrases.get(binding.scene_id)
        if not phrases:
            continue
        anchor = next(a for a in anchored.anchors if a.anchor_id == binding.anchor_id)
        if anchor.text not in phrases:
            continue
        span = spans[binding.scene_id]
        # end at next gallery cue or scene end
        end = span.end_frame
        for other in anchored.anchors:
            if other.scene_id == binding.scene_id and other.hit_frame > anchor.hit_frame:
                end = min(end, other.hit_frame)
                break
        text = anchor.text.strip(" ，、。！？；：")
        max_width = platform.subtitle_lower.w
        if measure_text_width_px(text, font_px=font_px) > max_width + 1e-6:
            raise Stage6Error(
                "subtitle_single_line_overflow",
                f"gallery cue too wide: {text}",
                scene_id=binding.scene_id,
                slot_id=binding.source_id,
                anchor_id=anchor.anchor_id,
            )
        cues.append(
            CompiledSubtitleCueV4(
                cue_id=f"sub://gallery/{binding.scene_id}/{binding.source_id}",
                scene_id=binding.scene_id,
                anchor_id=anchor.anchor_id,
                text=text,
                start_frame=anchor.hit_frame,
                end_frame=max(anchor.hit_frame + 1, end),
                slot_id="subtitle_lower",
                style_id="gallery_yellow",
                emphasize_text=text,
                emphasize_start_frame=anchor.hit_frame,
                single_line=True,
            )
        )

    # Default scene narration cues from scene token spans, skipping gallery-covered scenes' full text
    for scene in sorted(scene_plan.scenes, key=lambda item: item.order):
        if scene.scene_id in gallery_phrases:
            continue
        span = spans[scene.scene_id]
        scene_tokens = [tokens_by_id[tid] for tid in span.token_ids if tid in tokens_by_id]
        if not scene_tokens:
            continue
        max_width = platform.subtitle_top.w
        segments = _split_scene_tokens(scene_tokens, max_width_px=max_width, font_px=font_px)
        keywords = keyword_by_scene.get(scene.scene_id, [])
        for index, segment in enumerate(segments):
            text = "".join(token.text for token in segment).strip(" ，、。！？；：")
            if not text or text in ORPHAN_CONNECTORS:
                continue
            if measure_text_width_px(text, font_px=font_px) > max_width + 1e-6:
                raise Stage6Error(
                    "subtitle_single_line_overflow",
                    f"cue too wide: {text}",
                    scene_id=scene.scene_id,
                )
            emphasize = None
            emphasize_frame = None
            for _slot_id, phrase in keywords:
                if phrase in text:
                    emphasize = phrase
                    match = next(
                        (
                            a
                            for a in anchored.anchors
                            if a.scene_id == scene.scene_id and a.text == phrase
                        ),
                        None,
                    )
                    emphasize_frame = match.hit_frame if match else segment[0].start_frame
                    break
            cues.append(
                CompiledSubtitleCueV4(
                    cue_id=f"sub://{scene.scene_id}/{index}",
                    scene_id=scene.scene_id,
                    anchor_id=None,
                    text=text,
                    start_frame=segment[0].start_frame,
                    end_frame=max(segment[0].start_frame + 1, segment[-1].end_frame),
                    slot_id="subtitle_top",
                    style_id="default",
                    emphasize_text=emphasize,
                    emphasize_start_frame=emphasize_frame,
                    single_line=True,
                )
            )

    cues.sort(key=lambda item: (item.start_frame, item.cue_id))
    if any("\n" in cue.text or "\r" in cue.text for cue in cues):
        raise Stage6Error("subtitle_single_line_overflow", "multiline subtitle produced")
    return cues


def _split_scene_tokens(tokens: list, *, max_width_px: int, font_px: int) -> list[list]:
    segments: list[list] = []
    current: list = []
    for token in tokens:
        candidate = "".join(item.text for item in current) + token.text
        if current and measure_text_width_px(candidate, font_px=font_px) > max_width_px:
            segments.append(current)
            current = []
        current.append(token)
        text = "".join(item.text for item in current)
        if (
            token.text
            and token.text[-1] in BREAK_PUNCTUATION
            and measure_text_width_px(text, font_px=font_px) >= font_px * 4
        ):
            segments.append(current)
            current = []
    if current:
        segments.append(current)
    return segments
