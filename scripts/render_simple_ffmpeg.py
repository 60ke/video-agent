from __future__ import annotations

"""Compatibility entry point with merged-visual effect normalization.

The original FFmpeg renderer is preserved in ``render_simple_ffmpeg_legacy.py``.
This module patches only visual-group construction so adjacent caption slices that
reuse the same visual are merged before their effect duration is normalized.
"""

import importlib.util
import json
from pathlib import Path
from typing import Any

_LEGACY_PATH = Path(__file__).with_name("render_simple_ffmpeg_legacy.py")
_SPEC = importlib.util.spec_from_file_location("_video_agent_render_simple_ffmpeg_legacy", _LEGACY_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"unable to load legacy renderer: {_LEGACY_PATH}")
_legacy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_legacy)


def raw_effect_key(effect: Any) -> str:
    """Return a stable identity for an unnormalized effect declaration."""

    return json.dumps(effect or {}, ensure_ascii=False, sort_keys=True)


def build_visual_groups(track: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge equal consecutive visuals, then normalize one effect per group.

    Normalizing before grouping made the same raw effect resolve to different
    durations when caption slices had different lengths. The renderer would then
    reject the otherwise identical visual as a conflicting effect. This function
    compares raw declarations while merging and applies the timing budget only
    after the final group span is known.
    """

    events = sorted(
        (
            (idx, event)
            for idx, event in enumerate(track)
            if isinstance(event, dict)
            and isinstance(event.get("start"), (int, float))
            and isinstance(event.get("end"), (int, float))
            and float(event["end"]) > float(event["start"])
        ),
        key=lambda item: item[1]["start"],
    )
    groups: list[dict[str, Any]] = []
    for idx, event in events:
        label = _legacy.event_label(event, idx)
        key = _legacy.visual_group_key(event, label)
        start = float(event["start"])
        end = float(event["end"])
        motion = _legacy.normalize_motion(event, label)
        transition_in = _legacy.normalize_transition(event, label)
        raw_effect = event.get("effect")
        if raw_effect is not None and not isinstance(raw_effect, dict):
            raise ValueError(f"{label}.effect must be an object")

        if groups and groups[-1]["key"] == key:
            group = groups[-1]
            if transition_in["name"] != "cut":
                raise ValueError(
                    f"{label} reuses the same visual as the previous event but declares "
                    f"{transition_in['name']} transition; use transition_in.name=cut"
                )
            if motion != group["motion"]:
                raise ValueError(f"{label} reuses the same visual as the previous event but declares different motion")
            if raw_effect_key(raw_effect) != raw_effect_key(group.get("raw_effect")):
                raise ValueError(f"{label} reuses the same visual as the previous event but declares a different effect")
            group["end"] = max(group["end"], end)
            group["events"].append(event)
            continue

        groups.append(
            {
                "key": key,
                "start": start,
                "end": end,
                "events": [event],
                "asset_ids": [str(asset_id) for asset_id in event.get("asset_ids", [])],
                "layout": key[0],
                "clip_type": str(event.get("clip_type") or "image"),
                "sequence": event.get("sequence") if isinstance(event.get("sequence"), dict) else {},
                "motion": motion,
                "transition_in": transition_in,
                "raw_effect": raw_effect,
            }
        )

    for group in groups:
        group["effect"] = _legacy.normalize_effect_config(
            group.pop("raw_effect", None),
            group_duration=max(group["end"] - group["start"], 0.0),
        )
    if groups:
        groups[0]["transition_in"] = {"name": "cut", "duration": 0.0}
    return groups


# Patch the implementation module used by VisualGroupRenderer at runtime.
_legacy.build_visual_groups = build_visual_groups

# Preserve the historical import surface for callers that import functions or
# classes from scripts.render_simple_ffmpeg.
for _name in dir(_legacy):
    if not _name.startswith("__") and _name not in globals():
        globals()[_name] = getattr(_legacy, _name)


if __name__ == "__main__":
    raise SystemExit(_legacy.main())
