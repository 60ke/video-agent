# Programmatic Image Effects Pipeline

## Goal

Add controlled short-video motion to Pipeline V2 without returning to browser-heavy or unstable animation stacks. Effects are deterministic Pillow compositions driven by `video_project.json` and rendered through the existing rawvideo-to-FFmpeg path.

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
- parameter/UI screenshots: `wipe_reveal`
- generated result images: `tile_drop` or `radial_unfurl`
- generic single-image beats: `pop_in`
- explicit analysis/highlight intent: `scan_overlay`

It writes `video_project.effects.json` and `output/reports/effect_plan_report.json`.

Motion handling defaults to `--freeze-motion auto`: only strong entrance/assembly effects (`drop_bounce`, `tile_drop`, `radial_unfurl`) replace existing push/pull motion with `hold`. Softer effects keep existing motion unless the caller explicitly passes `--freeze-motion always`. Use `--freeze-motion never` for experiments that should preserve all existing motion.

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

## Safety constraints

- Effects do not change audio, subtitles, or event timing.
- Same visual groups must keep the same effect across adjacent subtitle slices.
- Effects are bounded to the first part of a group, then the source image remains stable.
- Effect duration is clipped to the visual group safety budget; if the clipped duration is zero or below the effect's minimum duration, the effect is disabled instead of falling back to its default duration.
- Strong entrance/assembly effects set motion to `hold` by default to avoid compounded movement; soft effects preserve existing motion by default.
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
```
