# Agent Notes

## Current Direction

- The previous Electron recorder and CDP video capture experiments are abandoned.
- CDP is used for login reuse, navigation, screenshot capture, form inspection, and coordinate metadata only.
- Video visuals are built from registered images, GPT image prepared 9:16 keyframes, optional registered programmatic image effects, and renderer-side `overlay_track` callouts.
- Do not add a new browser video recording path unless the user explicitly reopens that experiment.

## Effect Integration

Registered programmatic image effects are documented in `AGENT.md` and `docs/effects_pipeline.md`. The implementation is in `utils/effects/registry.py` and is executed by `scripts/render_simple_ffmpeg.py` from `visual_track[].effect`.

Current whitelist:

- `drop_bounce`
- `pop_in`
- `zoom_pulse`
- `tile_drop`
- `radial_unfurl`
- `wipe_reveal`
- `scan_overlay`

`slider_compare` is intentionally not part of the default set.

## Safe Effect Workflow

```powershell
python scripts\apply_effect_plan.py --case cases\<case> --project cases\<case>\video_project.gpt_image.json --json
python scripts\prepare_effect_assets.py --case cases\<case> --project cases\<case>\video_project.effects.json --json
python scripts\render_simple_ffmpeg.py --case cases\<case> --project cases\<case>\video_project.effects.json --label effects_preview --json
```

Or use:

```powershell
python scripts\render_with_effects.py --case cases\<case> --project cases\<case>\video_project.gpt_image.json --label effects_preview --json
```

Effects must not change voice/subtitle/visual start-end timing. They only change how an already selected image is composited during its own `visual_track` span.
