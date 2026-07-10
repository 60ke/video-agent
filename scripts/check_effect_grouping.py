from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.apply_effect_plan import apply_effects
from scripts.render_simple_ffmpeg import build_visual_groups


def base_event(event_id: str, start: float, end: float) -> dict[str, Any]:
    return {
        "id": event_id,
        "start": start,
        "end": end,
        "layout": "prepared-site-keyframe",
        "clip_type": "image",
        "asset_ids": ["asset_ui"],
        "motion": {"name": "push_in", "amount": 0.03, "anchor": "center"},
        "transition_in": {"name": "cut", "duration": 0.0},
        "semantic_binding": {"step_kind": "params"},
        "visual_intent": "show the website parameter page",
    }


def run(_: argparse.Namespace) -> dict[str, Any]:
    project = {
        "assets": [
            {
                "id": "asset_ui",
                "source": "assets/sites/ui.png",
                "role": "website_ui",
                "origin": "cdp_capture",
                "metadata": {"width": 1600, "height": 900, "aspect_ratio": 1600 / 900},
            }
        ],
        "visual_track": [
            base_event("slice_a", 0.0, 0.8),
            base_event("slice_b", 0.8, 1.6),
        ],
        "renderer_plan": {},
    }

    planned, changed = apply_effects(copy.deepcopy(project), preset="balanced", force=False, freeze_motion="auto")
    track = planned["visual_track"]
    if len(changed) != 2:
        raise AssertionError(f"expected both caption slices to receive the group effect, got {len(changed)}")
    effects = [event.get("effect") for event in track]
    if not all(isinstance(effect, dict) for effect in effects):
        raise AssertionError(f"missing planned group effect: {effects!r}")
    if effects[0] != effects[1]:
        raise AssertionError(f"same visual group received different effects: {effects!r}")
    if effects[0].get("name") != "perspective_push_in":
        raise AssertionError(f"wide parameter UI did not select perspective_push_in: {effects[0]!r}")
    if track[0].get("motion") != track[1].get("motion"):
        raise AssertionError("same visual group did not receive identical motion")

    groups = build_visual_groups(track)
    if len(groups) != 1:
        raise AssertionError(f"planned caption slices did not merge into one render group: {groups!r}")
    if not groups[0].get("effect"):
        raise AssertionError("merged group effect was unexpectedly disabled")

    raw_pop = {"name": "pop_in"}
    manual = [
        base_event("manual_a", 0.0, 1.0) | {"effect": copy.deepcopy(raw_pop)},
        base_event("manual_b", 1.0, 2.5) | {"effect": copy.deepcopy(raw_pop)},
    ]
    manual_groups = build_visual_groups(manual)
    if len(manual_groups) != 1:
        raise AssertionError("identical raw effects were not merged")
    if abs(float(manual_groups[0]["effect"]["duration"]) - 0.7) > 1e-6:
        raise AssertionError(f"effect was not normalized against merged duration: {manual_groups[0]['effect']!r}")

    short = [base_event("short", 0.0, 0.4) | {"effect": {"name": "drop_bounce", "duration": 2.4}}]
    short_groups = build_visual_groups(short)
    if short_groups[0].get("effect") is not None:
        raise AssertionError(f"short group should disable the effect: {short_groups[0]['effect']!r}")

    return {
        "ok": True,
        "code": "ok",
        "reason": "",
        "data": {
            "planned_effect": effects[0],
            "planned_changed_count": len(changed),
            "merged_group_count": len(groups),
            "manual_pop_effect": manual_groups[0]["effect"],
            "short_effect": short_groups[0].get("effect"),
        },
    }


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Check that effects are planned and normalized per merged visual group.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
