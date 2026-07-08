# Timeline Director Prompt

Use this prompt after voice and Minimax alignment exist.

## Goal

Bind reviewed script segments, Minimax subtitle timing, and verified assets into visual events for `video_project.json`.

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
      "clip_type": "image",
      "asset_ids": ["asset_003"],
      "evidence_binding": "real_result",
      "operation_status": "verified_result",
      "layout": "result-showcase",
      "display_mode": "result-showcase",
      "display_rule": "prepared_9x16",
      "sequence": null,
      "semantic_binding": {
        "feature_id": "activity_decoration",
        "feature_key": "activity_decoration",
        "step_kind": "result",
        "visual_subject": "show_result_quality",
        "result_claim_allowed": true
      },
      "framing": {
        "focus_region": "main_result_area",
        "subject_min_frame_ratio": 0.45,
        "center_safe_region": {"x": 0.18, "y": 0.12, "w": 0.64, "h": 0.68},
        "must_be_visible": ["生成结果", "下载按钮"],
        "viewport_transform": {
          "mode": "fit_width_preserve_image",
          "requires_ai_verified_asset": true,
          "allow_detail_crop": false
        },
        "subtitle_safe": true
      },
      "motion": {
        "name": "push_in",
        "amount": 0.028,
        "anchor": "center",
        "avoid_flicker": true,
        "forbidden_motion": ["arbitrary_zoompan", "breathing", "jitter", "pan_subject_out_of_frame"]
      },
      "transition_in": {
        "name": "cut",
        "duration": 0.0
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
  "overlay_track": [
    {
      "id": "ov_001",
      "start": 3.35,
      "end": 4.85,
      "type": "pulse_ring",
      "target_visual_id": "vis_002",
      "box": {"x": 0.18, "y": 0.28, "w": 0.28, "h": 0.08},
      "text": "文生图入口"
    }
  ]
}
```

## Rules

- Use Minimax subtitle timing as the default timing source.
- Visual start may lead subtitle start by up to 0.25s when it improves perceived sync.
- Do not switch away from the same asset if the next segment continues the same idea.
- Avoid flash transitions between identical assets.
- Dense/wide UI screenshots must not be repaired by renderer crop. Use only AI-verified 9:16 function screenshots in final video.
- Generated result scenes must use saved result crops/exports under `assets/results/`; website result-page screenshots are evidence only.
- Final visual assets are placed by width-fit/preserve-image rules. Do not request arbitrary zoom, crop, pan, or local magnification.
- `layout` is the renderer authority. If `display_mode` is present, it must exactly equal `layout`.
- Use only controlled `motion.name` values: `hold`, `push_in`, `pull_out`. Use `hold` with `amount=0` for dense UI/multi-image scenes; use small `push_in`/`pull_out` values up to `0.06` for single-result scenes.
- Use only `transition_in.name` values: `cut`, `crossfade`. Use `crossfade` only when `layout + asset_ids` changes; identical consecutive visuals must use `cut`.
- Set `clip_type` explicitly. Use `image` for one prepared keyframe, `site_flow_steps` for homepage/entry/params sequences, `result_gallery` for multiple saved result images, and `image_sequence` for other fast cuts.
- Set `display_rule` explicitly. Use `prepared_9x16` for GPT image prepared frames, `portrait_full_width` for clean vertical result images, and `landscape_full_width_center` for clean landscape result images.
- For multi-image clips, include `sequence` with mode `step_cut` for site flow and `result_carousel` or `quick_cut` for result galleries. Each item must be readable for at least 0.75s.
- Use `overlay_track` only for dynamic cues such as pulse rings/click emphasis. Static red boxes/arrows may already be baked into GPT image prepared keyframes.
- Dual panels must not have large empty lower areas.
- Do not include the fixed panda outro in `visual_track`.
- Do not add arbitrary zoompan, breathing, jitter, local crop, or floating motion.
- Motion must not pan or zoom the active UI/result out of the center safe region.
- Motion must be tied to a real browser action, a voiceover cue, or a deliberate transition between evidence states.
- Category scenes must use a prepared 9:16 screenshot around the requested category. Do not use a whole wide category row as the primary visual.
- Result/demo scenes must use `real_result` saved image assets for result claims. Browser screenshots can support workflow claims only.
- If operation status is `blocked_permission`, use input/setup evidence only and mark the visual as workflow preview.
- For 柯幻熊猫, keep red-callout assets tied to click/navigation segments and real result assets tied to hook/result/gallery segments.
- For 柯幻熊猫 verified-result videos, the visual track must include sequential prepared screenshots/callouts for `home_entry` or `text_to_image_entry`, `menu_select` or `feature_menu_select`, and `feature_page_empty`. A single form screenshot is not enough to prove the route.
