---
name: vertical-browser-framing
description: Rules for turning wide desktop browser evidence into readable 9:16 video scenes.
---

# Vertical Browser Framing Rules

Use these rules for website/app screenshots that will appear in a vertical `1080x1920` video. Generated effect/result images are different: save the actual result image/crop/export and preserve it whenever possible.

The browser captures evidence. The render uses prepared vertical shots. A wide desktop page is not a finished shot.

## Core Rule

Do not use a full wide desktop screenshot as the primary visual subject in a 9:16 scene.

Wide screenshots may be used only as:

- background evidence
- transition context
- a very brief establishing shot followed by a close-up

Every narration-bearing scene must use one of:

- an AI-verified 9:16 function screenshot
- a result export/crop
- a sequential close-up
- a split into readable sections

## Required Functional Regions

Each website/app visual must declare a `focus_region` that matches the line being spoken.

Examples:

- `feature_entry_card`
- `left_navigation_text_to_image`
- `signboard_menu_item`
- `left_form_required_fields`
- `industry_material_style_fields`
- `generate_button_area`
- `loading_or_generating_state`
- `result_gallery`
- `primary_result_image`
- `history_result_card`

Do not use vague values such as `center`, `auto`, or `whole_page` for a wide desktop screenshot. If the screenshot is still wide, prepare a 9:16 capture before it becomes a final video asset.

## Center Safe Region

For vertical video, the spoken subject must be visible inside the central safe region:

```json
{
  "center_safe_region": {
    "x": 0.18,
    "y": 0.12,
    "w": 0.64,
    "h": 0.68
  }
}
```

The active UI, button, selected menu item, or result image must remain inside this region for the whole scene. It cannot drift to the edge during animation.

## Motion Boundary

Allowed:

- stable hold
- small push-in after the crop is already correct
- click-tied callout
- one transition from overview to close-up

Forbidden for wide UI screenshots:

- arbitrary pan across the full page
- asking the renderer to repair framing with local crop/zoom
- moving the active UI out of the center safe region
- using blur/background duplicates as the main visual
- showing mostly empty website canvas while narration discusses a form, button, or result

## Material Understanding Output

For every wide website/app screenshot, write:

```json
{
  "display_risk": ["wide_desktop_ui"],
  "layout_plan": {
    "primary_display_mode": "portrait-showcase",
    "focus_region": "left_form_required_fields",
    "fill_strategy": "prepared_9x16_then_width_fit",
    "min_subject_frame_ratio": 0.45,
    "center_safe_region": {"x": 0.18, "y": 0.12, "w": 0.64, "h": 0.68},
    "must_be_visible": ["行业", "背景底板", "字体材质", "开始生成"],
    "forbidden_treatments": [
      "full_page_tiny_strip",
      "wide_full_preview_as_primary",
      "pan_subject_out_of_frame",
      "decorative_empty_panel"
    ]
  }
}
```

If the screenshot cannot be cropped into a readable region, request a new browser screenshot of the functional area.

## Result Display

Generated result images must be exported, downloaded, or cropped into `assets/results/` and shown with `portrait-showcase` or `result-showcase`.

The result page screenshot can prove that the product generated the result, but it is evidence only. It must not be used as the generated-result visual in the final video.

For generated effect images/result exports:

- Do not default to local detail crops just because the image is landscape.
- Use `result-showcase` or another contain layout that preserves the whole image.
- Fill the available video width when possible, with letterboxing or paired layouts preferred over cutting off meaningful edges.
- Crop only when the narration explicitly discusses a detail such as text, material, lighting, or a specific generated element.

## QA Failure Examples

Fail a scene when:

- the narrated UI is outside the central safe region
- a wide page is shown as a tiny full-page strip
- the frame is mostly blank website canvas
- the result claim is shown only as a tiny thumbnail inside a full page
- animation shifts the selected field/button/result off-screen
- subtitles cover the active form/button/result
