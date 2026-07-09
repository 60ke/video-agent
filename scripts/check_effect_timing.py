from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils.effects.registry import normalize_effect_config


def run(_: argparse.Namespace) -> dict[str, Any]:
    cases = [
        ("short_drop", {"name": "drop_bounce", "duration": 2.4}, 0.40, None),
        ("zero_budget", {"name": "tile_drop", "duration": 1.1}, 0.55, None),
        ("below_min_after_crop", {"name": "tile_drop", "duration": 1.1}, 1.2, None),
        ("normal_clip", {"name": "tile_drop", "duration": 2.4}, 2.0, 1.1),
        ("short_but_valid_pop", {"name": "pop_in", "duration": 1.2}, 1.0, 0.45),
    ]
    results = []
    for name, effect, group_duration, expected_duration in cases:
        normalized = normalize_effect_config(effect, group_duration=group_duration)
        if expected_duration is None:
            if normalized is not None:
                raise AssertionError(f"{name}: expected disabled effect, got {normalized}")
        else:
            if not normalized:
                raise AssertionError(f"{name}: expected enabled effect")
            actual = float(normalized["duration"])
            if abs(actual - expected_duration) > 1e-6:
                raise AssertionError(f"{name}: expected duration {expected_duration}, got {actual}")
        results.append({"name": name, "normalized": normalized})
    return {"ok": True, "code": "ok", "reason": "", "data": {"cases": results}}


def build_parser() -> argparse.ArgumentParser:
    return argparse.ArgumentParser(description="Check programmatic effect timing normalization guardrails.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run(args)
    except Exception as exc:  # noqa: BLE001
        output = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc), "data": {}}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
