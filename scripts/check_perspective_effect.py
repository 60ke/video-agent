from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw

from utils.effects import EFFECT_NAMES, EffectSuggestionInput, normalize_effect_config, render_effect_frame, suggested_effect


def synthetic_ui(width: int = 540, height: int = 960) -> Image.Image:
    frame = Image.new("RGB", (width, height), (8, 10, 12))
    ui_height = int(height * 0.34)
    ui = Image.new("RGB", (width, ui_height), (13, 18, 24))
    draw = ImageDraw.Draw(ui)
    draw.rounded_rectangle((18, 18, width - 18, ui_height - 18), radius=18, outline=(80, 170, 230), width=3)
    for index in range(5):
        left = 42 + index * 94
        draw.rounded_rectangle((left, 64, left + 70, ui_height - 56), radius=10, outline=(72, 125, 190), width=3)
    frame.paste(ui, (0, (height - ui_height) // 2))
    return frame


def run(output_dir: Path | None) -> dict[str, object]:
    if "perspective_push_in" not in EFFECT_NAMES:
        raise AssertionError("perspective_push_in was not registered")

    suggestion = suggested_effect(
        EffectSuggestionInput(
            step_kind="params",
            layout="prepared-site-keyframe",
            clip_type="image",
            duration=2.4,
            is_wide_ui=True,
            visual_intent="website function page",
        )
    )
    if not suggestion or suggestion.get("name") != "perspective_push_in":
        raise AssertionError(f"wide UI suggestion did not select perspective_push_in: {suggestion!r}")

    effect = normalize_effect_config(suggestion, group_duration=2.4)
    if not effect:
        raise AssertionError("perspective_push_in normalization unexpectedly disabled the effect")

    base = synthetic_ui()
    frames = {
        "start": render_effect_frame(base, effect, group_progress=0.0, group_duration=2.4),
        "mid": render_effect_frame(base, effect, group_progress=0.35, group_duration=2.4),
        "settled": render_effect_frame(base, effect, group_progress=0.85, group_duration=2.4),
        "tail": render_effect_frame(base, effect, group_progress=1.0, group_duration=2.4),
    }
    for name, frame in frames.items():
        if frame.size != base.size or frame.mode != "RGB":
            raise AssertionError(f"{name} frame has invalid shape/mode: {frame.size} {frame.mode}")

    if frames["mid"].tobytes() == base.tobytes():
        raise AssertionError("mid frame did not apply the perspective effect")
    if frames["settled"].tobytes() != frames["tail"].tobytes():
        raise AssertionError("stable tail changed after the perspective camera settled")

    written: list[str] = []
    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, frame in frames.items():
            path = output_dir / f"perspective_push_in_{name}.png"
            frame.save(path)
            written.append(str(path))

    return {
        "ok": True,
        "effect": effect,
        "registered": sorted(EFFECT_NAMES),
        "written": written,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-check the registered perspective_push_in image effect.")
    parser.add_argument("--output-dir", type=Path, help="Optional directory for four preview PNG frames.")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run(args.output_dir)
    except Exception as exc:  # noqa: BLE001
        result = {"ok": False, "code": exc.__class__.__name__, "reason": str(exc)}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif result.get("ok"):
        print("perspective_push_in check passed")
    else:
        print(f"ERROR: {result.get('reason')}", file=sys.stderr)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
