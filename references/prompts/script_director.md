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
  "high_risk_terms": ["柯幻熊猫", "AI"],
  "segments": [
    {
      "id": "seg_001",
      "stage": "hook",
      "text": "做一套品牌视觉，不用从零开始。",
      "camera_note": "从首页进入文生图，再点进 VI 功能页；此路径靠录屏/镜头体现，不要念出来。",
      "feature_id": "vi_design",
      "visual_intent": "show_result_quality",
      "material_task": "use_result_or_before_after",
      "evidence_binding": "real_result",
      "operation_status": "verified_result",
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

### Narration vs camera notes (critical)

`text` is the spoken voiceover, and it is also used verbatim as the on-screen subtitle. It must read as natural, benefit-first marketing copy for a viewer.

`text` must NOT contain operation instructions, UI step recitation, or production/meta commentary. These belong in `camera_note`, which is planning metadata only and is never voiced or captioned.

- Forbidden in `text` (put in `camera_note` instead, or drop): "点击/点开/点一下…", "选择/选…（某功能）", "上传…", "填写/输入…", "打开某菜单", and production meta such as "真实录屏", "一秒不剪", "没有剪辑", "这是录屏/演示".
- The entry path (首页 → 文生图 → 具体功能) is shown by the recording or callout screenshots and may be described in `camera_note`. Do not narrate the click steps.
- Describing the *content* the user provides (e.g. "用大白话写清风格：简约时尚、突出新鲜感") is allowed, because it is about the creative input, not about which button to press.
- Prefer outcome/benefit phrasing: say what the viewer gets ("一句话描述就能出整套效果图"), not what the automation did ("点开始生成马上出图").

### General

- Each segment must be short enough for subtitles.
- Prefer 8-18 Chinese characters per subtitle line, but segment text can be longer if semantically needed.
- Keep speech density at 6.0 or more Chinese characters/speech units per second.
- Include high-risk terms for ASR checks.
- Bind each segment to a visual intent and material task.
- Bind each segment to real evidence. Use one of: `real_recording`, `real_screenshot`, `real_result`, `error_state`, `evidence_cover`, or `packaging_only`.
- For website/product tasks, real evidence means CDP browser capture by default. Use static material assets as the primary evidence only when the user explicitly requested static resources/material folders/supplied assets.
- Use `preferred_asset_ids` only when the material is visually verified.
- When `site_asset_pool` is present, select website screenshots from that structured pool instead of guessing from filenames.
- If the same feature has `AI优化关键帧` or assets with `workflow_step=prepared_site_keyframe`, use those prepared 9:16 keyframes first. Fall back to raw `功能入口截图` / `参数面板截图` only when no prepared keyframe exists.
- For each feature video, prefer assets whose `feature_id` or `feature_key` exactly matches the segment feature. Do not mix screenshots from another 文生图 feature just because the UI looks similar.
- For 图文广告 children, the effective path is `文生图 -> 图文广告 -> 子功能`. A 车贴 video may use only the 车贴 entry/parameter screenshots, not 贴纸、灯箱、菜单 or the parent 图文广告 item as a substitute.
- Process/path beats should use the same feature's `功能入口截图` and `参数面板截图`. Result-showcase beats must use real result assets, not website screenshots.
- For `功能入口截图`, the visual target is the opened hover/dropdown child item for the feature, not a top-level card pill/chip with the same label. Put this distinction in `camera_note`.
- Result/gallery narration must be derived from the selected assets' `visible_text`, `supported_claims`, `feature_label`, and `prompt_inputs`. Do not name industries/scenes that are not visible or registered on the selected result images.
- Parameter-panel narration must match required fields visible in the screenshot. If exact filled values are unknown, use generic wording such as "按必填项填好行业、场景和描述", not specific upload/theme/style claims that the screenshot does not prove.
- Include `layout_intent` only for already prepared assets, such as `result-showcase`, `full-width`, `grid-rebuild`, `main-plus-reference`, or `browser-recording`.
- Website/app screenshots used in final video must already be AI-verified 9:16 screenshots. Generated result visuals must be saved result crops/exports under `assets/results/`, not website result-page screenshots.
- Do not select multiple images for one segment unless the layout can keep them readable in 9:16. Use sequential close-ups if equal-width comparison would be too narrow.
- When using tall detail pages, reserve enough time for readable movement or request `multi-section`.
- Do not add extra on-screen titles unless they are explicitly part of `overlay_track`.
- Fixed panda outro is not part of script.
- Do not claim or imply a generated result unless a captured/supplied result image exists. A website result page screenshot is evidence only; it is not a result image for final display.
- Do not use generated product photos, generic mockups, emoji, or invented UI as product evidence.
- If a feature is `blocked_login`, `blocked_permission`, or `verified_entry_only`, write a workflow/entry-point script only, or stop for user approval/materials.
- For category features such as `电商`, the script must name only the verified category state. Do not write copy that suggests unrelated categories or an opened result page unless captured evidence proves it.
- For 柯幻熊猫 generated-result demos, a preferred hook is `生成这样的一张效果图要多久？先看结果，再用真实截图证明它怎么来的。` The "result" must be a saved result image/crop/export, while website screenshots may only prove the operation path.
- For 柯幻熊猫 feature seeding, include at least one process segment that *shows* the entry path (首页 → `文生图` → target feature such as `VI` → feature page) via the recording or sequential callouts. Put the path description in that segment's `camera_note`; the spoken `text` stays benefit-focused and must not recite the clicks. Do not jump straight from result to form.
- If multiple generated result assets share a result group, add one short gallery segment instead of repeating the same screenshot.
- For single-feature seeding videos, follow the material sequence unless the case lacks assets: `网站主页截图` -> same-feature `功能入口截图` -> same-feature `参数面板截图` -> same-feature saved `结果图`. Prefer multiple result images when the copy says 多场景/多行业/多风格.
- Put feature path details in `feature_id`, `camera_note`, `visual_intent`, and `material_task` so the builder can map segments to site screenshots and result galleries. Do not rely on filename guessing.
