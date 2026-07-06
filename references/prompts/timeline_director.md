# Timeline Director Prompt

Use this prompt after voice and FunASR alignment exist.

## Goal

Bind reviewed script segments, ASR subtitle timing, and verified assets into visual events for `video_project.json`.

When `image_resources.json` exists, use it to choose result crops, red-callout screenshots, and gallery groups. Filenames are not enough.

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
      "evidence_binding": "real_result",
      "operation_status": "verified_result",
      "layout": "crop-focus",
      "display_mode": "crop-focus",
      "framing": {
        "focus_region": "main_result_area",
        "subject_min_frame_ratio": 0.45,
        "center_safe_region": {"x": 0.18, "y": 0.12, "w": 0.64, "h": 0.68},
        "must_be_visible": ["生成结果", "下载按钮"],
        "viewport_transform": {
          "mode": "crop_to_region_before_motion",
          "lock_subject_in_center_safe_region": true,
          "allow_subject_drift": false
        },
        "subtitle_safe": true
      },
      "motion": {
        "name": "stable_focus",
        "avoid_flicker": true,
        "forbidden_motion": ["arbitrary_zoompan", "breathing", "jitter", "pan_subject_out_of_frame"]
      },
      "qa_expectations": {
        "no_black_frame": true,
        "no_flash_if_same_asset": true,
        "readable_ui": true,
        "narrated_subject_inside_center_safe_region": true,
        "wide_ui_not_full_preview_primary": true,
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
- Wide desktop UI screenshots must not use `full-preview` as the primary narrated visual.
- Wide website/app scenes must keep the spoken functional region inside `center_safe_region`.
- Wide UI framing must list `must_be_visible` labels, buttons, fields, or result areas.
- Tall pages require computed slow-scroll duration; if too fast, split into `multi-section`.
- Dual panels must not have large empty lower areas.
- Do not include the fixed panda outro in `visual_track`.
- Default to stable holds for UI/result readability. Do not add arbitrary zoompan, breathing, jitter, or floating motion.
- Motion must not pan or zoom the active UI/result out of the center safe region.
- Motion must be tied to a real browser action, a voiceover cue, or a deliberate transition between evidence states.
- Category scenes must use `crop-focus` around the requested category. Do not use a whole category row as the primary visual when only one category is discussed.
- Result/demo scenes must use `real_recording`, `real_screenshot`, or `real_result` assets. Packaging-only assets cannot support result claims.
- If operation status is `blocked_quota`, use quota/input/setup evidence only and mark the visual as workflow preview.
- For 柯幻熊猫, keep red-callout assets tied to click/navigation segments and real result assets tied to hook/result/gallery segments.
