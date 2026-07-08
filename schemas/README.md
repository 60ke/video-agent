# Video Agent Schemas

This directory contains the new contracts for the material-library driven video pipeline.

The new pipeline has no compatibility obligation to the old CDP recording based video path. Browser recordings, recording camera tracks, `crop-focus`, and local `zoom_to_area` repair are intentionally excluded from these schemas.

## Files

### `material_manifest.schema.json`

Long-lived asset inventory for a site material library.

Use it for:

- website screenshots
- callout screenshots
- real result images
- curated case images
- GPT image prepared 9:16 keyframes

Important constraints:

- Every asset has a strict `asset_kind`.
- `result_page_evidence` is evidence only and must not be used as a `result_showcase`.
- Standard video assets should be `gpt_9x16` or `prepared_9x16`.
- Real generation claims must be carried by `truth.can_claim_real_generation`.

### `material_groups.schema.json`

Reusable asset groups for planners.

Use it for:

- site flow steps
- result galleries
- industry galleries
- multi-feature galleries
- hook fast cuts

Important constraints:

- Planners should prefer groups over ad hoc single asset selection.
- Gallery-style groups require multiple assets.
- Each group declares its recommended `clip_type`.

### `video_project_v2.schema.json`

Render-ready multi-track project for vertical videos.

Use it for:

- script-to-visual timing
- image sequence clips
- grid clips
- site flow step clips
- result gallery clips
- overlays, subtitles, voice, BGM/SFX, and ending track

Important constraints:

- `assets` are image-only. Outro video belongs in `ending_track`; BGM/SFX belong in `audio_tracks`.
- `clip_type` is limited to image-driven clips.
- `display_rule` must be chosen before motion.
- Motion is whole-frame only. Local crop focus and recording camera moves are not part of V2.

## Rendering Order

Every visual clip must render in this order:

```text
source image
-> display_rule creates a 1080x1920 base frame
-> whole-frame motion
-> overlay motion
-> subtitles
```

This preserves motion without letting animation damage the image framing.

