# Programmatic Image Effects Pipeline

## Goal

Add controlled short-video motion to Pipeline V2 without returning to browser-heavy or unstable animation stacks. Effects are deterministic Pillow compositions driven by `video_project.json` and rendered through the existing rawvideo-to-FFmpeg path.

For the effect planning policy and future LLM planner design, see `docs/effect_planning_strategy.md`.

## Effect field

Each `visual_track` event may include:

```json
{
  "effect": {
    "name": "tile_drop",
    "duration": 1.1,
    "params": {
      "rows": 4,
      "cols": 4
    }
  }
}
```

For website UI screenshots, `perspective_push_in` produces the tilted camera push shown in product-demo videos:

```json
{
  "effect": {
    "name": "perspective_push_in",
    "duration": 1.45,
    "params": {
      "start_width": 0.72,
      "end_width": 1.08,
      "start_x": 0.08,
      "end_x": -0.02,
      "start_y": 0.22,
      "end_y": 0.05,
      "start_perspective": 0.14,
      "end_perspective": 0.075,
      "start_rotation": 1.8,
      "end_rotation": 0.35,
      "grid_spacing": 72,
      "corner_radius": 28,
      "border_width": 3,
      "shadow": true
    }
  }
}
```

The effect automatically detects a wide screenshot band inside a prepared 9:16 frame. Use `card_crop: [x, y, width, height]` with normalized coordinates when the automatic crop should be overridden. It renders a dark grid background, rounded screenshot card, perspective compression, border glow, shadow, and ease-out push-in. The camera reaches its final state by `effect.duration` and then holds that transformed state for the stable tail.

For effects that need an auxiliary image:

```json
{
  "effect": {
    "name": "scan_overlay",
    "duration": 1.3,
    "needs_aux_asset": true,
    "aux_asset_kind": "highlight_overlay",
    "params": {
      "band_width": 0.14,
      "overlay_opacity": 0.72,
      "residual_opacity": 0.1
    }
  }
}
```

After `prepare_effect_assets.py` runs, it becomes:

```json
{
  "effect": {
    "name": "scan_overlay",
    "duration": 1.3,
    "needs_aux_asset": false,
    "aux_asset_kind": "highlight_overlay",
    "aux_asset_id": "asset_effect_highlight_xxxxxxxx",
    "params": {
      "band_width": 0.14,
      "overlay_opacity": 0.72,
      "residual_opacity": 0.1
    }
  }
}
```

## Scripts

### `scripts/apply_effect_plan.py`

Adds default effect choices to `visual_track` based on existing project evidence:

- homepage/entry screenshots: `drop_bounce`
- parameter pages and wide website UI screenshots: `perspective_push_in`
- remaining parameter/UI screenshots that are not eligible for perspective treatment: `wipe_reveal`
- generated result images: `tile_drop` or `radial_unfurl`
- generic single-image beats: `pop_in`
- explicit analysis/highlight intent: `scan_overlay`

It writes `video_project.effects.json` and `output/reports/effect_plan_report.json`.

Motion handling defaults to `--freeze-motion auto`: strong entrance/assembly effects and the perspective camera effect (`drop_bounce`, `tile_drop`, `radial_unfurl`, `perspective_push_in`) replace existing push/pull motion with `hold`. Softer effects keep existing motion unless the caller explicitly passes `--freeze-motion always`. Use `--freeze-motion never` for experiments that should preserve all existing motion.

### `scripts/prepare_effect_assets.py`

Finds `scan_overlay` events that still need `highlight_overlay`, calls the existing GPT Image edit API, writes generated overlays into `assets/effects/`, appends them to `project.assets`, and writes `effect_asset_manifest.json` plus `output/reports/effect_assets_report.json`.

It supports `--dry-run`, which creates a local procedural edge-highlight fallback without calling GPT Image.

### `scripts/render_simple_ffmpeg.py`

Reads `visual_track[].effect`, applies registered effects during group rendering, and includes the resolved effect config in the render report.

### `scripts/render_with_effects.py`

Convenience wrapper for preview/review runs. It executes:

1. `apply_effect_plan.py`
2. `prepare_effect_assets.py`
3. `render_simple_ffmpeg.py`

Example:

```powershell
python scripts\render_with_effects.py `
  --case cases\<case> `
  --project cases\<case>\video_project.gpt_image.json `
  --label effects_preview `
  --preset balanced `
  --json
```

For local validation without GPT Image calls:

```powershell
python scripts\render_with_effects.py `
  --case cases\<case> `
  --project cases\<case>\video_project.json `
  --label effects_dry `
  --effect-assets-dry-run `
  --skip-outro `
  --json
```

### `scripts/check_perspective_effect.py`

Runs a dependency-free smoke check against a synthetic website UI frame. It verifies registration, rule-based selection for wide UI, normalization, output shape, visible mid-animation transformation, and a stable final tail.

```powershell
python scripts\check_perspective_effect.py --json
python scripts\check_perspective_effect.py --output-dir output\perspective_preview --json
```

## Planning model

Current first-pass planning is programmatic and conservative:

```text
LLM produces script, visual plan, semantic fields, and optional hint text.
apply_effect_plan.py maps those fields to the effect whitelist.
normalize_effect_config() validates and clips duration.
prepare_effect_assets.py generates required auxiliary overlays.
render_simple_ffmpeg.py renders only normalized effects.
```

Future LLM planning should stay bounded by the same whitelist and validation path. A recommended upgrade is to add `scripts/plan_effects_llm.py`, output `visual_track[].effect_candidate`, and let `apply_effect_plan.py` run in `hybrid` mode to accept valid candidates or fall back to rule-based `suggested_effect()`.

## Safety constraints

- Effects do not change audio, subtitles, or event timing.
- Same visual groups must keep the same effect across adjacent subtitle slices.
- Entrance effects are bounded to the first part of a group, then the source image remains stable.
- `perspective_push_in` settles during the bounded effect interval and holds the final transformed card through the stable tail instead of snapping back to the flat source.
- Effect duration is clipped to the visual group safety budget; if the clipped duration is zero or below the effect's minimum duration, the effect is disabled instead of falling back to its default duration.
- Strong entrance/assembly/perspective effects set motion to `hold` by default to avoid compounded movement; soft effects preserve existing motion by default.
- `scan_overlay` is the only first-pass effect that depends on GPT Image.

## Current whitelist

```text
drop_bounce
pop_in
zoom_pulse
tile_drop
radial_unfurl
wipe_reveal
scan_overlay
perspective_push_in
```
