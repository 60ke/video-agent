# Script Director Prompt

Use this prompt to convert user copy, product notes, website evidence, and material understanding into `video_script.json`.

## Goal

Create reviewed spoken script segments that can drive voice, subtitles, and visuals.

Do not output plain copy only.

The video is vertical mobile-first: `1080x1920`, `9:16`. Choose copy, assets, and visual intent with that canvas in mind.

## Required Output

Return JSON:

```json
{
  "schema_version": 1,
  "status": "reviewed",
  "voice_style": "快节奏、清晰、种草",
  "high_risk_terms": ["科幻熊猫", "AI"],
  "segments": [
    {
      "id": "seg_001",
      "stage": "hook",
      "text": "做一套品牌视觉，不用从零开始。",
      "feature_id": "vi_design",
      "visual_intent": "show_result_quality",
      "material_task": "use_result_or_before_after",
      "preferred_asset_ids": ["asset_003"],
      "layout_intent": "portrait-showcase",
      "focus_region": "final_result_center",
      "keywords": ["品牌视觉", "不用从零开始"],
      "duration_hint": 3.2,
      "allow_rewrite": true
    }
  ]
}
```

## Rules

- Each segment must be short enough for subtitles.
- Prefer 8-18 Chinese characters per subtitle line, but segment text can be longer if semantically needed.
- Keep speech density around 4.8-6.2 Chinese characters per second.
- Include high-risk terms for ASR checks.
- Bind each segment to a visual intent and material task.
- Use `preferred_asset_ids` only when the material is visually verified.
- Include `layout_intent` when the segment needs a specific layout such as `portrait-showcase`, `crop-focus`, `multi-section`, `grid-rebuild`, `main-plus-reference`, or `browser-recording`.
- Include `focus_region` for website/app screenshots. Use a real functional region, not `auto`, when the scene depends on UI readability.
- Do not select multiple images for one segment unless the layout can keep them readable in 9:16. Use sequential close-ups if equal-width comparison would be too narrow.
- When using tall detail pages, reserve enough time for readable movement or request `multi-section`.
- Do not add extra on-screen titles unless they are explicitly part of `overlay_track`.
- Fixed panda outro is not part of script.
