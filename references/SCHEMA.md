# Multi-Track Video Project Schema

The project contract is `video_project.json`.

This schema is intentionally semantic. It constrains timing, asset intent, QA, and track relationships, while leaving HyperFrames free to choose high-quality HTML/CSS implementation details.

## Top-Level Shape

```json
{
  "schema_version": 1,
  "meta": {},
  "inputs": {},
  "website_knowledge": {},
  "assets": [],
  "script_segments": [],
  "voice_track": {},
  "subtitle_track": {},
  "visual_track": [],
  "overlay_track": [],
  "audio_tracks": [],
  "ending_track": null,
  "renderer_plan": {},
  "qa_rules": {},
  "reports": {}
}
```

## meta

```json
{
  "case_id": "culture_wall_001",
  "title": "文化墙功能种草",
  "width": 1080,
  "height": 1920,
  "fps": 30,
  "target_platform": "douyin",
  "target_duration": 30,
  "language": "zh-CN",
  "safe_area": {
    "top": 120,
    "bottom": 260,
    "left": 60,
    "right": 60
  }
}
```

The default canvas is vertical mobile video: `1080x1920`, `9:16`. Planner, material understanding, timeline, and renderer decisions must start from this constraint. Wide website screenshots and very tall static images cannot be treated as neutral images; they require a readable layout plan before rendering.

## inputs

```json
{
  "target_url": "https://example.com",
  "video_goal": "功能种草",
  "preferred_features": ["文化墙"],
  "brand_profile": "柯幻熊猫",
  "dependency_mode": {
    "browser": "kimi_webbridge",
    "renderer": "hyperframes",
    "asr": "funasr",
    "tts": "cosyvoice"
  }
}
```

Optional `voice_config`:

```json
{
  "voice_config": {
    "mode": "voice_clone",
    "engine": "voice_clone_api",
    "prompt_audio_policy": "default",
    "prompt_audio": "assets/voice/default_voice_clone_prompt_5s.wav",
    "case_prompt_audio": "audio/voice_prompt_5s.wav",
    "endpoint": "http://192.168.2.191:9890/api/v1/digital-human/voice-clones/generate"
  }
}
```

`prompt_audio_policy` values:

- `default`: use the bundled default voice clone prompt from the skill assets.
- `custom`: use a user-provided prompt audio file after validation and conversion.
- `none`: do not use voice clone; use a plain TTS voice.

Render code should copy the default skill asset into the case directory and reference the copied `case_prompt_audio` path for API calls. Do not mutate the skill asset.

## assets

Assets are frozen local files captured or supplied before render.

```json
{
  "id": "asset_ui_upload",
  "type": "image",
  "source": "outputs/screenshots/upload_page.png",
  "origin": "browser_capture",
  "role": "upload_form",
  "page_url": "/design/culture-wall",
  "description": "文化墙生成表单，包含实景图上传、行业、主题、场景和开始生成按钮。",
  "visible_text": ["上传实景图", "行业", "主题", "开始生成"],
  "supported_claims": ["无需提示词", "选择行业主题", "一键生成"],
  "operation_status": "verified_result",
  "evidence_role": "real_screenshot",
  "image_resource": {
    "id": "img_culture_wall_form_001",
    "feature_id": "culture_wall",
    "workflow_step": "form_filled",
    "variant": "clean",
    "capture_method": "kimi_webbridge_screenshot",
    "recommended_usage": ["operation_path"]
  },
  "aspect_ratio": 0.5625,
  "quality": {
    "readable": true,
    "contains_private_info": false,
    "needs_review": false
  },
  "layout_plan": {
    "primary_display_mode": "crop-focus",
    "focus_region": "left_form_and_generate_button",
    "fill_strategy": "crop_to_readable_functional_region",
    "min_subject_frame_ratio": 0.45,
    "center_safe_region": {"x": 0.18, "y": 0.12, "w": 0.64, "h": 0.68},
    "must_be_visible": ["上传实景图", "行业", "开始生成"],
    "safe_area_notes": "Keep primary UI above subtitles.",
    "forbidden_treatments": ["full_page_tiny_strip", "wide_full_preview_as_primary", "pan_subject_out_of_frame", "fast_scroll", "decorative_empty_panel"]
  }
}
```

Allowed `origin`:

- `browser_capture`
- `frontend_capture`
- `static_material_image`
- `product_export`
- `generated_asset`
- `user_supplied_video`

Allowed `operation_status`:

- `verified_result`: input/action/result evidence was captured.
- `verified_entry_only`: an entry point or category exists, but no changed state/result was captured.
- `blocked_login`: login is required.
- `blocked_quota`: logged-in operation is blocked by credits/points/quota.
- `blocked_permission`: account or browser permission blocks operation.
- `unsafe_action`: operation would pay, publish, delete, change account state, or spend quota without approval.
- `unavailable`: requested feature could not be found.

Allowed `evidence_role`:

- `real_recording`
- `real_screenshot`
- `real_result`
- `quota_or_error_state`
- `evidence_cover`
- `packaging_only`

Assets with `origin: "generated_asset"` are `packaging_only` by default. They must not support product-result claims unless explicitly supplied as real product output by the user.

## image_resources.json

`image_resources.json` is a case-level image catalog for later agents. It is separate from `video_project.json` because it can describe clean evidence screenshots, annotated derivatives, generated result exports, and result crops before the final render plan exists.

Filenames are hints only. The catalog is the semantic source of truth for image meaning.

```json
{
  "schema_version": 1,
  "status": "ready",
  "naming_policy": "kx_<feature>_<step>_<seq>_<variant>.png",
  "resources": [
    {
      "id": "img_logo_result_001",
      "asset_id": "asset_007",
      "filename": "kx_logo_result_crop_007_result.png",
      "source": "assets/results/kx_logo_result_crop_007_result.png",
      "type": "image",
      "feature_id": "logo",
      "workflow_step": "result_crop",
      "variant": "result",
      "origin": "browser_capture",
      "capture_method": "kimi_webbridge_screenshot_crop",
      "page_url": "https://kehuanxiongmao.com/...",
      "title": "LOGO生成结果裁切图",
      "description": "真实生成后的LOGO结果图，适合做视频里的主效果展示。",
      "visible_text": [],
      "prompt_inputs": {
        "brand_name": "星野咖啡实验室",
        "industry": "咖啡饮品",
        "description": "面向年轻办公人群，想要一个简洁、温暖、容易识别的品牌标志。"
      },
      "callouts": [],
      "relations": {
        "raw_source_id": "img_logo_result_page_001",
        "annotated_version_id": null,
        "result_group_id": "logo_generation_001"
      },
      "supported_claims": ["填写品牌信息后可生成LOGO效果图"],
      "recommended_usage": ["result_showcase", "hook_visual", "gallery"],
      "quality": {
        "readable": true,
        "contains_private_info": false,
        "needs_review": false
      },
      "layout_plan": {
        "primary_display_mode": "portrait-showcase",
        "focus_region": "generated_logo",
        "fill_strategy": "fill_mobile_width_without_cropping_logo",
        "min_subject_frame_ratio": 0.5,
        "center_safe_region": {"x": 0.12, "y": 0.08, "w": 0.76, "h": 0.72},
        "must_be_visible": ["完整LOGO结果"],
        "safe_area_notes": "Keep result above subtitle rail.",
        "forbidden_treatments": ["tiny_full_page_strip", "invented_result"]
      }
    }
  ]
}
```

Allowed `workflow_step` values:

- `home_entry`
- `feature_card`
- `navigation_callout`
- `menu_select`
- `feature_page_empty`
- `form_filled`
- `generate_callout`
- `generating`
- `result_page`
- `result_crop`
- `result_export`
- `result_gallery`
- `quota_or_error`
- `packaging`

`callouts` should use normalized coordinates when available:

```json
{
  "type": "red_box",
  "target_label": "LOGO",
  "purpose": "click_feature",
  "box": {"x": 0.28, "y": 0.45, "w": 0.18, "h": 0.07}
}
```

For 柯幻熊猫 result demos:

- `capture_method` must mention Kimi WebBridge.
- `origin` must be `browser_capture` for screenshots/crops or `product_export` for downloaded/generated result files.
- At least one `result_crop` or `result_export` resource is required before claiming `verified_result`.
- Multiple generated outputs should share a `result_group_id` so the renderer can build a gallery beat.
- Annotated images must relate back to a clean raw source through `relations.raw_source_id`.

For wide website/app screenshots:

- `primary_display_mode` must be `crop-focus`, `multi-section`, `main-plus-reference`, or `browser-recording`.
- `full-preview` is allowed only for non-narrated establishing context.
- `focus_region` must name the functional subject, not `whole_page` or `auto`.
- `center_safe_region` describes where the spoken subject must remain in the 9:16 frame.
- `must_be_visible` lists labels/buttons/results that must be readable in the rendered shot.
- `forbidden_treatments` must include `wide_full_preview_as_primary` and `pan_subject_out_of_frame`.

## generation_receipts.json

`generation_receipts.json` records quota/points state, generation inputs, and result assets for real website generation actions.

```json
{
  "schema_version": 1,
  "status": "ready",
  "receipts": [
    {
      "id": "receipt_logo_001",
      "feature_id": "logo",
      "operation_status": "verified_result",
      "page_url": "https://kehuanxiongmao.com/...",
      "browser_session": {
        "tool": "kimi_webbridge",
        "session_name": "kehuanxiongmao-logo-demo"
      },
      "account_state": {
        "logged_in": true,
        "points_before": 1000,
        "points_after": 994,
        "visible_generation_cost": 6,
        "balance_requirement": ">100"
      },
      "input_summary": {
        "brand_name": "星野咖啡实验室",
        "industry": "咖啡饮品",
        "description": "面向年轻办公人群，想要一个简洁、温暖、容易识别的品牌标志。"
      },
      "action_assets": [
        "img_logo_form_filled_001",
        "img_logo_generate_callout_001",
        "img_logo_generating_001"
      ],
      "result_assets": [
        "img_logo_result_001",
        "img_logo_result_002"
      ],
      "started_at": "2026-07-06T00:00:00Z",
      "finished_at": "2026-07-06T00:00:35Z",
      "errors": [],
      "notes": []
    }
  ]
}
```

If `operation_status` is not `verified_result`, `result_assets` must be empty and the receipt must explain the blocker in `errors` or `notes`.

## site_profile_snapshot.json

`site_profile_snapshot.json` is a case-local copy of stable website structure used to reduce repeated exploration. It must not replace Kimi WebBridge evidence for login, points, screenshots, generation, or results.

```json
{
  "schema_version": 1,
  "status": "active",
  "profile": {
    "profile_id": "kehuanxiongmao",
    "canonical_url": "https://kehuanxiongmao.com",
    "frontend_code_evidence": {},
    "features": []
  },
  "selected_feature": {
    "id": "signboard",
    "route": "/textToImage/signboard",
    "url": "https://kehuanxiongmao.com/textToImage/signboard",
    "form_fields": [],
    "default_demo_inputs": {},
    "api_payload_template": {}
  },
  "frontend_root": "C:/Users/CNGG/Documents/video_generate/wanxiang-frontend",
  "applied_at": "2026-07-06T00:00:00Z",
  "next_agent_instructions": []
}
```

Allowed `status`:

- `active`: profile can seed planning, but live WebBridge verification is still required.
- `refresh_needed`: do not trust seeded fields until the profile is manually updated from frontend code and fresh browser snapshots.

## script_segments

```json
{
  "id": "seg_003",
  "stage": "demo",
  "text": "把现场照片丢进来，选行业主题，点生成。",
  "feature_id": "culture_wall",
  "visual_intent": "show_operation_steps",
  "material_task": "use_browser_recording_or_ui_sequence",
  "evidence_binding": "real_recording",
  "operation_status": "verified_result",
  "keywords": ["现场照片", "行业主题", "点生成"],
  "duration_hint": 4.5,
  "allow_rewrite": true
}
```

`evidence_binding` must be one of the allowed `evidence_role` values. A segment with `evidence_binding: "packaging_only"` must not contain product-result claims.

If `operation_status` is `verified_entry_only`, `blocked_quota`, `blocked_login`, or `blocked_permission`, the segment text must be limited to the visible workflow state or blocker unless the user supplies result material.

## voice_track

```json
{
  "mode": "tts_or_voice_clone",
  "engine": "cosyvoice",
  "source_text": "完整口播文案",
  "audio_path": "outputs/audio/voice.wav",
  "duration": 27.4,
  "speed_policy": {
    "minimum_units_per_second": 6.0
  },
  "high_risk_terms": ["柯幻熊猫", "AI"],
  "qa": {
    "brand_terms_recognized": true,
    "internal_silence_ok": true,
    "needs_regeneration": false
  }
}
```

## subtitle_track

Subtitle text should use reviewed script text. Timing should come from ASR.

```json
{
  "source": "outputs/funasr/voice_raw.json",
  "format": "asr_aligned_segments",
  "segments": [
    {
      "id": "sub_003",
      "script_segment_id": "seg_003",
      "text": "把现场照片丢进来，选行业主题，点生成。",
      "start": 7.2,
      "end": 11.6
    }
  ]
}
```

## visual_track

Each visual event binds time, semantic intent, assets, layout, and framing.

```json
{
  "id": "vis_003",
  "script_segment_ids": ["seg_003"],
  "start": 7.0,
  "end": 11.8,
  "asset_ids": ["asset_ui_upload", "asset_recording_demo"],
  "layout": "ui_operation_focus",
  "display_mode": "crop-focus",
  "framing": {
    "focus_region": "left_form_and_generate_button",
    "subject_min_frame_ratio": 0.45,
    "subtitle_safe": true,
    "center_safe_region": {"x": 0.18, "y": 0.12, "w": 0.64, "h": 0.68},
    "must_be_visible": ["行业", "开始生成"],
    "viewport_transform": {
      "mode": "crop_to_region_before_motion",
      "lock_subject_in_center_safe_region": true,
      "allow_subject_drift": false
    }
  },
  "motion": {
    "name": "stable_focus_with_callout",
    "avoid_flicker": true,
    "motion_reason": "callout follows the generate button mentioned in voiceover",
    "forbidden_motion": ["arbitrary_zoompan", "breathing", "jitter", "pan_subject_out_of_frame"]
  },
  "qa_expectations": {
    "no_black_frame": true,
    "no_flash_if_same_asset": true,
    "readable_ui": true,
    "no_meaningless_empty_panel": true,
    "narrated_subject_inside_center_safe_region": true,
    "wide_ui_not_full_preview_primary": true
  }
}
```

Allowed `display_mode`:

- `full-preview`
- `portrait-showcase`
- `crop-focus`
- `slow-scroll`
- `multi-section`
- `dual-preview`
- `main-plus-reference`
- `grid-rebuild`
- `browser-recording`
- `outro-video`

Motion must be stable by default. `zoompan`, breathing, jitter, and floating-card motion are not valid unless the event declares a specific `motion_reason` tied to voiceover or a browser action.

## overlay_track

```json
{
  "id": "ov_003_button",
  "type": "highlight_ring",
  "start": 9.8,
  "end": 11.2,
  "target": "generate_button",
  "asset_id": "asset_ui_upload",
  "text": null
}
```

Overlay text is only allowed when explicitly declared. Prefer graphic highlights over extra words.

## audio_tracks

Optional for P0.

```json
{
  "id": "bgm_001",
  "type": "bgm",
  "source": "assets/bgm/tech_fast.mp3",
  "start": 0,
  "end": 30,
  "volume": 0.12,
  "ducking": true
}
```

## ending_track

Optional. If present, ffmpeg may append it after the HyperFrames main render.

```json
{
  "id": "default_panda_outro",
  "type": "video",
  "policy": "default",
  "source": "assets/outro/default_panda_outro.mp4",
  "start_policy": "after_voice",
  "participates_in_script": false,
  "participates_in_subtitles": false,
  "preserve_audio": true,
  "duration": 3.436009
}
```

Allowed `policy` values:

- `default`: append the bundled fixed panda outro after the generated main video.
- `custom`: append a user-provided ending video after validation.
- `none`: do not append an ending.

The ending track is postprocess-only. It must not influence script text, subtitle timing, visual-track matching, or voice duration. QA should check the final duration after concat.

## renderer_plan

```json
{
  "renderer": "hyperframes",
  "composition_dir": "hyperframes",
  "main_output": "output/versions/main.mp4",
  "final_output": "output/versions/final.mp4",
  "allow_creative_layout": true,
  "must_follow_tracks": true
}
```

## qa_rules

```json
{
  "voice": {
    "require_asr_alignment": true,
    "require_brand_term_check": true,
    "max_internal_silence_seconds": 0.12
  },
  "visual": {
    "no_black_frames": true,
    "no_unexplained_blanks": true,
    "min_subject_frame_ratio": 0.35,
    "ui_must_be_readable": true,
    "subtitle_must_not_cover_key_content": true,
    "real_result_claims_require_result_evidence": true,
    "generated_assets_are_packaging_only": true,
    "category_focus_required": true,
    "no_arbitrary_motion": true
  },
  "layout": {
    "dual_panel_height_must_match_media": true,
    "wide_ui_requires_crop_or_capture_if_unreadable": true,
    "tall_image_requires_scroll_or_sections": true,
    "portrait_result_should_fill_mobile_width": true,
    "no_overzoom_without_focus_reason": true,
    "same_asset_continuity_no_flash": true,
    "wide_ui_not_full_preview_primary": true,
    "narrated_subject_inside_center_safe_region": true
  }
}
```

## Renderer Freedom Boundary

HyperFrames may:

- choose visual hierarchy
- create motion details
- add masks, shadows, camera moves, and focus crops
- split one visual event into sub-clips for readability
- choose a richer layout than requested only when it preserves subtitle timing, asset meaning, and 9:16 readability

HyperFrames must not:

- invent unsupported claims
- add non-subtitle text unless declared in overlays
- change voice/subtitle timing without updating the project
- hide major layout decisions only in HTML
- render unreadable or meaningless scenes that fail QA
- render a tall page as a narrow strip
- over-zoom a website/app screenshot without a declared functional focus region
