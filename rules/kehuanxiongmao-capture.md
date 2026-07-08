---
name: kehuanxiongmao-capture
description: Fixed CDP screenshot and result capture workflow for 柯幻熊猫 demos.
---

# 柯幻熊猫截图与结果采集规则

Use this rule whenever the target site is `https://kehuanxiongmao.com` or the case is a 柯幻熊猫 feature demo.

The goal is to capture auditable website evidence and result images that can later become prepared 9:16 video keyframes. CDP is responsible for screenshots, login verification, navigation, form inspection, and coordinate metadata. The final video uses prepared images plus `overlay_track` callouts, not browser recordings.

## Hard Requirements

- Access and operate the website only through CDP capture.
- Use the user's already logged-in browser session. Do not ask for passwords or handle credentials.
- Use the fixed local profile `kehuanxiongmao`; if the profile/auth state is unavailable or the page is not logged in, refuse generation workflows instead of running an anonymous flow.
- Before generation, capture visible evidence that the account is logged in.
- Pressing the generation button is allowed only when login is verified and the user requested the generation workflow.
- Every screenshot used in the video must be copied into the case directory or registered from `assets/sites`.
- Generated-result visuals used in the final video must be saved images/crops/exports under `assets/results/`. A website result page screenshot is evidence only and must not be used as the final result image.
- Function/process visuals used in the final video must be prepared as AI-verified 9:16 keyframes when available. The renderer width-fits images and does not perform local crop/zoom repair.
- For feature seeding videos, the entry path must be visible through sequential prepared screenshots: homepage or product entry, `文生图` menu expansion, target feature selection, and destination feature/parameter page.

## Site Screenshot Library

Reusable website screenshots live under:

```text
assets/sites/
```

Use Chinese filenames because the website labels are Chinese:

```text
柯幻熊猫_文生图_文化墙_功能入口截图.png
柯幻熊猫_文生图_文化墙_参数面板截图.png
柯幻熊猫_文生图_图文广告_车贴_参数面板截图.png
```

For `图文广告`, keep the extra child level in the filename path: `柯幻熊猫_文生图_图文广告_<子功能>_<截图类型>.png`.

CDP may also write `_callouts.json` beside screenshots. It should contain normalized target boxes, labels, and step semantics. Do not burn red boxes, cursor circles, or click pulses into the raw CDP screenshot; pass those as metadata for GPT image or `overlay_track`.

## Fixed Capture Scope

For each 文生图 feature, capture:

- `网站主页截图`: one logged-in homepage/dashboard screenshot.
- `功能入口截图`: the opened hover/dropdown state where the exact feature item is visible and targetable.
- `参数面板截图`: the destination feature page showing title, required fields, optional fields, upload areas, and `开始生成`.
- `结果图_*`: saved generated result images, crops, or exports when the workflow includes generation.

Parameter screenshots may fall back to full page if precise panel cropping is unstable. GPT image can convert the full page into a 9:16 parameter keyframe later.

## Source-First Navigation

Before sequence capture, use `references/site_profiles/kehuanxiongmao.json` and `references/site_profiles/kehuanxiongmao_text_to_image_modules.json`.

For any `文生图` module:

- Use the registry route, menu label, page title, component, `source_type`, and primary `task_type` as source of truth.
- Prefer direct module URL navigation for speed, then capture the visible menu path when video evidence needs it.
- Assert live state with CDP after navigation: `location.pathname` equals the registry route, `.label-active` equals `文生图-<模块名>`, and `开始生成` is visible.
- When capturing the menu path, hover/click the exact visible text in `.hover-submenu-item`. Never infer the module from historical images, OCR-like guesses, or broad visual similarity.

## Result Authenticity

If a live generation workflow is performed:

1. Fill demo content based on the feature's own visible fields.
2. Mark every mandatory input/select/click action as required in the capture logic. Missing selectors, failed input verification, or an unavailable generation button must abort the run.
3. Click the real `开始生成` button.
4. If the page shows historical generated results, record a baseline before clicking generate and accept only result cards whose visible timestamp is greater than or equal to this run's generation click time.
5. Ignore loading placeholders such as `/static/img/generate-loading`.
6. Save the generated image itself under `assets/results/`. Export/download when possible; otherwise crop the result image area.
7. Save at least 2 and preferably 4 results when multiple results are produced.
8. Mark result resources as `workflow_step: result_crop`, `result_export`, or `result_gallery`.

Do not reuse older case results, static webpage examples, or manually prepared stand-ins for a fresh generated-result claim.

## Metadata

Update case files after capture/registration:

- `browser_materials.json` for login proof and browser evidence.
- `asset_manifest.json` for copied/registered assets.
- `image_resources.json` for screenshot type, feature path, workflow step, prompt inputs, result status, and callouts.
- `generation_receipts.json` for feature id, input summary, result assets, and errors when a real generation workflow is executed.

Machine-checkable login proof:

```json
{
  "logged_in": true,
  "evidence_asset_id": "<screenshot asset id showing avatar/login state>"
}
```

## Red Callout Policy

Use red callouts to show the operation path, but preserve clean source screenshots.

Required:

- A clean raw screenshot for evidence.
- Callout metadata in `image_resources.json` or `_callouts.json` with target label and normalized box coordinates.
- `overlay_track` for dynamic markers such as pulse rings, click emphasis, arrows, and labels.
- Precise workflow steps: `home_entry`, `text_to_image_entry`, `feature_menu_select`, `feature_page_empty`, `feature_form_params`, `result_crop`, `result_export`, or `result_gallery`.

Allowed callouts:

- red rectangle around a clicked function entry
- red circle around a selected menu item
- red arrow pointing to the avatar/login state or `开始生成`
- short label such as `功能项`, `登录后的头像`

Do not burn private information into annotated assets. Crop, mask, or omit it.

## Video Narrative Binding

Separate evidence from storytelling:

- `evidence_only`: login proof, raw route proof, repeated intermediate screenshots, call-chain traces.
- `candidate_video_visual`: feature entry, parameter page, loading state, result page, red-callout keyframes.
- `final_video_visual`: visuals selected for the requested hook, claim, or user-approved demo narrative.

Do not make the capture workflow itself the whole video topic. Use it to prove that the result is real, then choose the most persuasive subset for the final short video. The selected subset must include a readable entry path through sequential prepared screenshots from `文生图` to the target feature.

Default hook pattern:

```text
生成这样的一张门头效果图要多久？先看结果，再用真实截图证明它怎么来的。
```

If result capture fails, remove result-quality claims and use a workflow-only script.

## Material Status Mapping

- `verified_result`: feature entry, input/generation action, and real result were captured.
- `verified_entry_only`: only the entry or form page was captured.
- `blocked_login`: logged-in state is unavailable.
- `blocked_permission`: account or browser permission blocks generation/export.
- `unsafe_action`: action would pay, publish, delete, change account settings, or otherwise alter state beyond generation.
- `unavailable`: the requested feature cannot be found.

Do not upgrade a feature to `verified_result` until at least one real generated result image is saved in the case directory and described in `image_resources.json`.

## Site Profile Update Chain

Default run:

1. Apply `references/site_profiles/kehuanxiongmao.json` into the case with `scripts/apply_site_profile.py`.
2. Use CDP to verify only the minimum live state: route/page title, expected labels, logged-in account, and generate button.
3. Continue with screenshot/result capture.

Manual refresh:

1. Re-read the frontend code for the target feature.
2. Use CDP to capture fresh snapshots of the home page, feature entry, form, login indicator, and result list/history state.
3. Update `references/site_profiles/kehuanxiongmao.json`.
4. Run `scripts/apply_site_profile.py --refresh-needed --force` on an existing case to mark stale artifacts, then re-apply without `--refresh-needed` after the profile is reviewed.
