# Video Agent Architecture Notes

## Current operating model

`video-agent` generates short vertical product/demo videos from prepared evidence: website screenshots, result images, narration, subtitle timing, and deterministic FFmpeg rendering. The canonical output authority after planning is `video_project.json`; render-time code must not reinterpret the script, voice, subtitle, or visual timeline.

The project keeps the V2 principle: use controlled, deterministic image motion instead of browser-driven or free-form animation. Effects are frame-compositing treatments applied inside an existing `visual_track` time span. They never change the voice track, subtitle timing, visual event start/end, or case evidence binding.

## Effect integration

The registered programmatic image effects live in `utils/effects/registry.py`.

Registered effects:

- `drop_bounce`: source-only, image drops from above and settles.
- `pop_in`: source-only, center scale/opacity pop-in.
- `zoom_pulse`: source-only, gentle center push/pull.
- `tile_drop`: source-only, source is split into tiles and assembled from above.
- `radial_unfurl`: source-only, tiles start near center and rotate/spread into final layout.
- `wipe_reveal`: source-only, masked reveal with a subtle scan edge.
- `scan_overlay`: source + auxiliary highlight overlay, used for blueprint/structure scan effects.

Removed effect:

- `slider_compare`: deliberately omitted because it overlaps semantically with scan/reveal effects and does not fit the default product-demo video rhythm.

## Pipeline usage

A safe effect workflow is:

```powershell
python scripts\build_video_project.py --case cases\<case> --json
python scripts\apply_effect_plan.py --case cases\<case> --project cases\<case>\video_project.json --json
python scripts\prepare_effect_assets.py --case cases\<case> --project cases\<case>\video_project.effects.json --json
python scripts\render_simple_ffmpeg.py --case cases\<case> --project cases\<case>\video_project.effects.json --label demo_effects --json
```

Or use the wrapper:

```powershell
python scripts\render_with_effects.py --case cases\<case> --project cases\<case>\video_project.gpt_image.json --label effects_preview --json
```

`apply_effect_plan.py` injects an `effect` object into eligible `visual_track` entries without changing any start/end times. `prepare_effect_assets.py` only generates auxiliary assets for effects that require them. Today that means `scan_overlay` creates a `highlight_overlay` image using the existing OpenAI-compatible GPT Image edit pipeline.

## Time-safety rules

Effects must preserve the existing timing contract:

- Do not edit `voice_track.duration`.
- Do not edit `subtitle_track.segments[].start/end`.
- Do not edit `visual_track[].start/end`.
- Do not restart effects for consecutive subtitle slices that reuse the same `layout + asset_ids` visual.
- Leave at least about 0.55 seconds of stable readable image after an entrance effect.
- For image effects with entrance movement, set `motion.name=hold` to avoid double motion.

## GPT Image auxiliary prompt chain

`scan_overlay` requires a derived image, not a new semantic image. The prompt must preserve the source exactly and produce a structure-highlight/blueprint overlay aligned one-to-one with the original.

Prompt policy:

- Uploaded source image is the only source of truth.
- Preserve layout, text positions, UI state, brand marks, and result content.
- Do not invent UI, text, logos, products, people, or result details.
- Convert important edges, text blocks, icons, modules, buttons, panels, and contours into cyan-blue/blue-white luminous outlines.
- Reduce large fills and background noise so the result can be alpha-blended above the original.

The concrete prompt builder is `highlight_prompt()` in `scripts/prepare_effect_assets.py`.

## Render order

The renderer applies image treatments in this order:

1. Compose the visual group base frame from the registered image assets.
2. Apply sequence item selection if the clip is an image sequence.
3. Apply `effect` within the group's own time span.
4. Apply bounded whole-frame `motion`.
5. Apply `transition_in` at group boundaries.
6. Apply `overlay_track` callouts.
7. Pipe RGB frames to FFmpeg and burn ASS subtitles.

Subtitles remain FFmpeg/ASS-driven and are not baked into intermediate image effects.
