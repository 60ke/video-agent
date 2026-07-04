# Timeline Director Prompt

Use this prompt after voice and FunASR alignment exist.

## Goal

Bind reviewed script segments, ASR subtitle timing, and verified assets into visual events for `video_project.json`.

## Required Output

Return JSON fields that can be merged into `video_project.json`:

```json
{
  "visual_track": [
    {
      "id": "vis_001",
      "script_segment_ids": ["seg_001"],
      "start": 0.0,
      "end": 3.2,
      "asset_ids": ["asset_003"],
      "layout": "crop-focus",
      "display_mode": "crop-focus",
      "framing": {
        "focus_region": "main_result_area",
        "subject_min_frame_ratio": 0.45,
        "subtitle_safe": true
      },
      "motion": {
        "name": "stable_focus",
        "avoid_flicker": true
      },
      "qa_expectations": {
        "no_black_frame": true,
        "no_flash_if_same_asset": true,
        "readable_ui": true,
        "no_meaningless_empty_panel": true
      },
      "layout_reason": "The subtitle talks about result quality, and this asset is a verified result preview."
    }
  ],
  "overlay_track": []
}
```

## Rules

- Use subtitle ASR timing as the default timing source.
- Visual start may lead subtitle start by up to 0.25s when it improves perceived sync.
- Do not switch away from the same asset if the next segment continues the same idea.
- Avoid flash transitions between identical assets.
- Dense UI screenshots require `crop-focus`.
- Tall pages require computed slow-scroll duration; if too fast, split into `multi-section`.
- Dual panels must not have large empty lower areas.
- Do not include the fixed panda outro in `visual_track`.
