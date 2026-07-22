from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from agent_test.project import read_json

SCENE_KINDS = {"website_operation", "result_detail", "result_gallery", "before_after", "title_card"}
BEAT_ROLES = {"hook", "pain_point", "product_intro", "feature_showcase", "benefit_highlight", "social_proof", "branding", "cta"}
ARCS = {"pas", "future_pacing", "demo_loop", "bab", "feature_benefit_cascade"}


def normalize_spoken(value: str) -> str:
    return re.sub(r"[\s\W_]+", "", value, flags=re.UNICODE).lower()


def load_storyboard(path: Path) -> dict[str, Any]:
    data = read_json(path)
    beats = data.get("beats")
    if not isinstance(beats, list):
        raise ValueError("storyboard.beats must be a list")
    return data


def validate_storyboard(storyboard: dict[str, Any], *, script: str, recipes: dict[str, Any], result_assets: list[str]) -> list[str]:
    errors: list[str] = []
    arc = str(storyboard.get("arc") or "").lower()
    if arc not in ARCS:
        errors.append(f"unsupported arc: {arc or '<missing>'}")
    beats = storyboard.get("beats")
    if not isinstance(beats, list) or not beats:
        errors.append("storyboard requires at least one beat")
        return errors

    ids: set[str] = set()
    voiced: list[str] = []
    for index, raw in enumerate(beats, start=1):
        if not isinstance(raw, dict):
            errors.append(f"beat {index} must be an object")
            continue
        beat_id = str(raw.get("beat_id") or "")
        if not beat_id:
            errors.append(f"beat {index} missing beat_id")
        elif beat_id in ids:
            errors.append(f"duplicate beat_id: {beat_id}")
        ids.add(beat_id)
        role = str(raw.get("role") or "")
        if role not in BEAT_ROLES:
            errors.append(f"{beat_id or index}: unsupported role {role!r}")
        voiceover = str(raw.get("voiceover") or "").strip()
        if not voiceover:
            errors.append(f"{beat_id or index}: missing voiceover")
        voiced.append(voiceover)
        kind = str(raw.get("scene_kind") or "")
        if kind not in SCENE_KINDS:
            errors.append(f"{beat_id or index}: unsupported scene_kind {kind!r}")
        recipe_id = raw.get("recipe_id")
        if kind == "website_operation" and (not recipe_id or str(recipe_id) not in recipes):
            errors.append(f"{beat_id or index}: website_operation must use an existing recipe_id")
        assets = [str(value) for value in raw.get("asset_paths") or []]
        unknown = [value for value in assets if value not in result_assets]
        if unknown:
            errors.append(f"{beat_id or index}: unregistered assets: {unknown}")
        if kind in {"result_detail", "result_gallery", "before_after"} and not assets:
            errors.append(f"{beat_id or index}: {kind} requires asset_paths")
        windows = raw.get("visual_windows") or []
        if not isinstance(windows, list):
            errors.append(f"{beat_id or index}: visual_windows must be a list")

    if normalize_spoken("".join(voiced)) != normalize_spoken(script):
        errors.append("SCRIPT.md must equal the concatenated beat voiceover text")
    return errors


def _token_text(tokens: list[dict[str, Any]]) -> tuple[str, list[int]]:
    chars: list[str] = []
    owners: list[int] = []
    for index, token in enumerate(tokens):
        text = normalize_spoken(str(token.get("text") or ""))
        for char in text:
            chars.append(char)
            owners.append(index)
    return "".join(chars), owners


def _find_span(haystack: str, needle: str, start: int) -> tuple[int, int] | None:
    if not needle:
        return None
    found = haystack.find(needle, start)
    if found < 0:
        return None
    return found, found + len(needle)


def _frame(ms: int, fps: int) -> int:
    return max(0, round(ms / 1000 * fps))


def _ratio_window(start_ms: int, end_ms: int, window: dict[str, Any]) -> tuple[int, int]:
    duration = max(1, end_ms - start_ms)
    start_ratio = min(1.0, max(0.0, float(window.get("start_ratio", 0.0))))
    end_ratio = min(1.0, max(start_ratio, float(window.get("end_ratio", 1.0))))
    return start_ms + round(duration * start_ratio), start_ms + round(duration * end_ratio)


def align_storyboard(storyboard: dict[str, Any], tokens: list[dict[str, Any]], *, fps: int) -> list[dict[str, Any]]:
    if not tokens:
        raise ValueError("word timing tokens are required")
    global_text, owners = _token_text(tokens)
    if not global_text or not owners:
        raise ValueError("word timing tokens contain no spoken text")

    cursor = 0
    scenes: list[dict[str, Any]] = []
    for beat_index, beat in enumerate(storyboard["beats"], start=1):
        voiceover = str(beat["voiceover"])
        target = normalize_spoken(voiceover)
        span = _find_span(global_text, target, cursor)
        if span is None:
            raise ValueError(f"cannot align storyboard beat to TTS words: {beat.get('beat_id')}")
        char_start, char_end = span
        token_start = owners[char_start]
        token_end = owners[char_end - 1]
        start_ms = int(tokens[token_start]["start_ms"])
        end_ms = int(tokens[token_end]["end_ms"])
        cursor = char_end

        aligned_windows: list[dict[str, Any]] = []
        beat_text = global_text[char_start:char_end]
        beat_owner_slice = owners[char_start:char_end]
        window_cursor = 0
        raw_windows = beat.get("visual_windows") or []
        if not raw_windows:
            raw_windows = [{"label": voiceover, "start_ratio": 0.0, "end_ratio": 1.0, "motion": beat.get("motion") or "hold"}]
        for window_index, raw_window in enumerate(raw_windows, start=1):
            if not isinstance(raw_window, dict):
                raise ValueError(f"visual window must be an object: {beat.get('beat_id')}")
            cue = normalize_spoken(str(raw_window.get("cue") or ""))
            if cue:
                local_span = _find_span(beat_text, cue, window_cursor)
                if local_span is None:
                    raise ValueError(f"cannot align visual window cue {raw_window.get('cue')!r} in {beat.get('beat_id')}")
                local_start, local_end = local_span
                start_token = beat_owner_slice[local_start]
                end_token = beat_owner_slice[local_end - 1]
                window_start_ms = int(tokens[start_token]["start_ms"])
                window_end_ms = int(tokens[end_token]["end_ms"])
                window_cursor = local_end
            else:
                window_start_ms, window_end_ms = _ratio_window(start_ms, end_ms, raw_window)
            aligned_windows.append(
                {
                    "window_id": f"{beat.get('beat_id') or f'beat_{beat_index:02d}'}_window_{window_index:02d}",
                    "label": str(raw_window.get("label") or raw_window.get("cue") or "").strip(),
                    "layout": str(raw_window.get("layout") or "centered"),
                    "motion": str(raw_window.get("motion") or "hold"),
                    "start_ms": window_start_ms,
                    "end_ms": max(window_end_ms, window_start_ms + 1),
                    "start_frame": _frame(window_start_ms, fps),
                    "end_frame": max(_frame(window_end_ms, fps), _frame(window_start_ms, fps) + 1),
                }
            )

        scenes.append(
            {
                "scene_id": str(beat.get("beat_id") or f"beat_{beat_index:02d}"),
                "cue_id": str(beat.get("beat_id") or f"beat_{beat_index:02d}"),
                "role": str(beat.get("role") or "feature_showcase"),
                "text": voiceover,
                "start_ms": start_ms,
                "end_ms": end_ms,
                "start_frame": _frame(start_ms, fps),
                "end_frame": max(_frame(end_ms, fps), _frame(start_ms, fps) + 1),
                "kind": str(beat.get("scene_kind")),
                "recipe_id": beat.get("recipe_id"),
                "asset_paths": [str(value) for value in beat.get("asset_paths") or []],
                "blueprint": str(beat.get("blueprint") or "compose"),
                "transition_in": str(beat.get("transition_in") or "cut"),
                "motion": str(beat.get("motion") or "fade"),
                "windows": aligned_windows,
            }
        )
    return scenes
