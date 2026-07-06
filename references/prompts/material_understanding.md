# Material Understanding Prompt

Use this prompt when the case has `asset_manifest.json` and the agent has vision capability.

## Goal

Inspect each image/video asset and produce `material_understanding.json`.

Do not rely on filenames alone. Filenames are hints only.

If the case also has `image_resources.json`, use it as the image-level semantic catalog and keep your `material_understanding.json` consistent with its feature id, workflow step, callouts, supported claims, and layout advice.

All planning is for a vertical mobile video: `1080x1920`, `9:16`, with subtitles in the lower safe area. Judge every image by how it will actually read on this canvas.

## Required Output

Return JSON:

```json
{
  "schema_version": 1,
  "status": "vision_reviewed",
  "materials": [
    {
      "asset_id": "asset_001",
      "filename": "VI界面.png",
      "type": "image",
      "vision_summary": "The screenshot shows a VI generation form with upload areas and a generate button.",
      "page_or_scene_role": "feature_entry",
      "visible_text": ["上传", "开始生成"],
      "supported_claims": ["上传素材后一键生成"],
      "recommended_usage": "show_operation_entry",
      "display_risk": ["wide_desktop_ui", "dense_desktop_ui"],
      "layout_advice": "Use crop-focus on the form area, not full-page tiny display.",
      "layout_plan": {
        "primary_display_mode": "crop-focus",
        "focus_region": "left_form_and_generate_button",
        "fill_strategy": "crop_to_readable_functional_region",
        "min_subject_frame_ratio": 0.45,
        "center_safe_region": {"x": 0.18, "y": 0.12, "w": 0.64, "h": 0.68},
        "must_be_visible": ["上传", "开始生成"],
        "safe_area_notes": "Keep the form and generate button above subtitles.",
        "forbidden_treatments": ["full_page_tiny_strip", "wide_full_preview_as_primary", "pan_subject_out_of_frame", "fast_scroll", "decorative_empty_panel"]
      },
      "needs_review": false
    }
  ]
}
```

## Rules

- Use ASCII `asset_id` exactly from `asset_manifest.json`.
- Preserve Chinese visible text in `visible_text`.
- Mark website/app screenshots by their functional role.
- A wide desktop website/app screenshot must be classified as `wide_desktop_ui` and must not recommend `full-preview` as the primary display mode.
- For tall screenshots, say whether they need `slow-scroll` or `multi-section`.
- For dense desktop UI, prefer `crop-focus`.
- For ordinary 9:16 or near-portrait result images, prefer `portrait-showcase`: fill most of the canvas width while preserving the key content.
- Never recommend showing a long page as a narrow full-height strip.
- Only recommend `slow-scroll` when the segment is long enough to read the content; otherwise recommend `multi-section`.
- For website/app screens, identify the functional region: upload area, form fields, result gallery, editor canvas, generate button, checkout/payment area, etc.
- For every wide UI crop, list `must_be_visible` labels/buttons/results that must remain inside the center safe region throughout the scene.
- If the narrated subject would sit on the far left/right edge after cropping, mark `needs_review: true` and request a recrop or a more specific browser screenshot.
- If a two-column or gallery layout would make both images unreadable, recommend sequential close-ups or `main-plus-reference`, not equal-width tiny panels.
- Mark over-zoom risk when cropping would hide the page purpose, important labels, or result area.
- For result images, identify whether the image is an input/reference/result/final effect.
- Do not invent claims that are not visually supported.
- For annotated screenshots, explain the underlying clean screenshot and the callout purpose. Do not treat red boxes/arrows as product UI.
- For generated result crops/exports, state whether they can support a result-quality claim or only a workflow claim.
