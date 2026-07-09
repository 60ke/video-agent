# Visual Plan Director Prompt

Use this prompt before script writing. The goal is to lock the material sequence first, then let `script_director.md` write narration only inside those visual constraints.

## Goal

Create `visual_plan.json`: a reviewed list of visual beats with fixed asset IDs, evidence type, feature binding, layout intent, and allowed narration claims.

Do not write spoken copy here. Do not invent assets. Do not select a result image unless it is registered as a real saved result.

## Required Output

Return JSON:

```json
{
  "schema_version": 1,
  "status": "reviewed",
  "feature_id": "activity_decoration",
  "feature_label": "活动美陈",
  "beats": [
    {
      "id": "beat_001",
      "stage": "site_home",
      "feature_id": "activity_decoration",
      "visual_intent": "show_site_entry",
      "material_task": "use_homepage_screenshot",
      "evidence_binding": "real_screenshot",
      "operation_status": "verified_entry_only",
      "locked_asset_ids": ["site_kehuanxiongmao_home_raw_desktop"],
      "layout_intent": "full-width",
      "focus_region": "text_to_image_entry",
      "duration_hint": 2.8,
      "camera_note": "展示首页到文生图入口，具体点击路径只体现在画面高亮里。",
      "allowed_claims": ["柯幻熊猫首页有文生图入口", "这是进入目标功能前的真实界面"],
      "forbidden_claims": ["不要说已经生成结果", "不要念点击步骤"]
    }
  ]
}
```

## Beat Order

For a single-feature 柯幻熊猫 seed video, prefer this order:

1. Homepage or product entry screenshot.
2. Same-feature `功能入口截图`.
3. Same-feature `参数面板截图`.
4. Same-feature saved `结果图` or result gallery.

If there are multiple saved result images for the same feature and different industries/scenes, create separate result beats or one result-gallery beat with multiple `locked_asset_ids`. The later script must describe only what those exact images prove.

## Asset Selection Rules

- Use `site_asset_pool` and `image_resources` for meaning; do not rely on filenames alone.
- Use assets whose `feature_id`, `feature_key`, or `feature_path` match the target feature.
- For `图文广告` children, keep the full path `文生图 -> 图文广告 -> 子功能`; do not substitute sibling child features.
- Website screenshots can prove workflow and UI only. They cannot be used as final generated-result proof.
- Result beats must use assets with workflow step `result_crop`, `result_export`, `result_gallery`, or `result_page`, or assets marked as generated result images.
- If a result beat names an industry/scene, that label must come from the selected result image metadata, visible text, or prompt inputs.
- If exact parameter values are not visible, the parameter beat's `allowed_claims` must stay generic, such as "按必填项补好行业、场景和描述".

## Narration Guardrails For Later Script

Each beat must include enough `allowed_claims` and `forbidden_claims` to constrain script writing.

- `allowed_claims`: facts the narration may say while this beat is on screen.
- `forbidden_claims`: words or claims the narration must avoid for this beat.
- `camera_note`: shot planning metadata only; it will not be voiced or captioned.

The script stage must reference `visual_beat_id` and reuse the beat's `locked_asset_ids`. Do not let script writing choose new images.
