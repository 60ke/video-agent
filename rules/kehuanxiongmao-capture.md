---
name: kehuanxiongmao-capture
description: Fixed CDP capture workflow for 柯幻熊猫 real generation demos.
---

# 柯幻熊猫截图与结果采集规则

Use this rule whenever the target site is `https://kehuanxiongmao.com` or the case is a 柯幻熊猫 feature demo.

The goal is to capture a complete, auditable product flow that can support future short-video generation and skill optimization. The browser evidence must show the real path from feature discovery to generated result, but the final video does not need to show every captured step.

## Hard Requirements

- Access and operate the website only through CDP capture.
- Use the user's already logged-in browser session. Do not ask for passwords or handle credentials.
- CDP automation and recording must use the fixed local profile `kehuanxiongmao`; if the profile/auth state is unavailable or the page is not logged in, refuse execution instead of recording an anonymous flow.
- Before generation, capture visible evidence that the account is logged in and the points/credits balance is greater than 100.
- If the balance is 100 or lower, or the balance cannot be read, do not press `开始生成`; capture the blocker and stop for approval or supplied result material.
- If the user explicitly asked for the full generation flow and the balance is greater than 100, pressing the generation button is allowed for this site.
- Every screenshot used in the video must be copied into the case directory. Do not leave final assets in temp folders.
- Generated-result visuals used in the final video must be saved images/crops/exports under `assets/results/`. A website result page screenshot is evidence only and must not be used as the result image in the final video.
- Function/process visuals used in the final video must be captured or prepared as AI-verified 9:16 screenshots. The renderer will place images by width-fit and will not perform local crop/zoom repair.
- For feature seeding videos, the entry path must be visible. Prefer a short browser recording from home/dashboard through `文生图` into the target feature. The recording should stop right after clicking `开始生成`; do not wait for the result in the recording. This is only the recording boundary, not the automation boundary: the same browser task must continue after recording stops and obtain the real generated result. If recording is not available, capture multiple red-callout screenshots that show the step-by-step path: home or feature entry, `文生图` menu expansion, target feature selection such as `VI`, and the destination feature page.

## Case Directory Layout

Save browser and result materials under:

```text
assets/browser/raw/
assets/browser/annotated/
assets/recordings/
assets/results/
```

Use stable ASCII filenames:

```text
kx_<feature>_<step>_<seq>_<variant>.png
```

Examples:

```text
kx_logo_home_entry_001_clean.png
kx_logo_menu_select_002_callout.png
kx_logo_form_empty_003_clean.png
kx_logo_form_filled_004_clean.png
kx_logo_generating_005_clean.png
kx_logo_result_page_006_clean.png
kx_logo_result_crop_007_result.png
```

Keep the filename short. Put Chinese details, prompt text, visible text, and usage notes in `image_resources.json`.

## Fixed Capture Sequence

Before sequence capture, use `references/site_profiles/kehuanxiongmao.json` when available. The profile stores stable frontend-derived facts such as routes, component names, form fields, charge config defaults, API names, and expected capture steps. This reduces repeated browser exploration.

The profile is a shortcut, not proof. CDP must still verify live page state, login state, points balance, screenshots, and generated results.

1. Open `https://kehuanxiongmao.com` with CDP using the fixed `kehuanxiongmao` profile.
2. Capture the home page or dashboard state.
   - Save a clean screenshot.
   - Record page URL, page title, visible navigation labels, avatar/login indicator, and points balance.
3. Capture the feature entry path.
   - Show the left navigation or top feature card.
   - Prefer a short CDP recording that starts before the first useful click and ends immediately after the `开始生成` trigger if generation is part of the demo.
   - The recording must include real required-field input and the real generation click. Do not use mock UI, skipped fields, pre-filled fake states, or a video that only pretends to click generation.
   - In the CDP task, put `stopRecordingAfter: true` on the real `开始生成` click action. Continue the remaining task actions after that point to wait for the real result and save/export/crop it.
   - Keep the recording landscape/normal browser size. In final video use `browser-recording-fit-width`, which fills the 1080px width and centers the recording vertically without crop.
   - Add concise `narration` text to key CDP actions, such as opening `文生图`, selecting `VI`, filling fields, and clicking `开始生成`; `recording_narration_track.json` will use actual action timestamps.
   - If recording is unavailable, save a sequential screenshot set with red callouts:
     - `home_entry`: dashboard/home with the first entry target visible.
     - `text_to_image_entry`: the `文生图` entry before or during click.
     - `menu_select` or `feature_menu_select`: the expanded menu with `VI`, `LOGO`, `门头招牌`, or the requested target marked.
     - `feature_page_empty`: the loaded feature page title and empty form.
   - Create a red callout version that marks the functional entry the viewer should click.
   - If a menu opens, capture the menu and mark the selected category, such as `LOGO`.
4. Click into the feature page.
   - Capture the page title, required fields, optional fields, upload area, and `开始生成` button.
   - Save a clean screenshot before filling.
5. Fill demo content based on the feature's own fields.
   - Use safe, fictional demo data, not private user or customer data.
   - For LOGO demos, a valid default is:
     - brand name: `星野咖啡实验室`
     - industry: `咖啡饮品`
     - style: choose a visible modern/simple option if available
     - structure type: choose a visible icon+text or graphic option if available
     - description: `面向年轻办公人群，想要一个简洁、温暖、容易识别的品牌标志。`
   - For other features, derive inputs from visible field labels and the feature description.
6. Capture the filled form before generation.
   - The screenshot must show enough of the form to prove the inputs and selected controls.
   - Include a callout overlay for `开始生成` in the video plan or annotated image.
7. Generate.
   - Re-check that points balance is greater than 100 if the page shows a cost near the button.
   - Click `开始生成`.
   - For CDP recording, stop the recording immediately after this real click, but keep the browser automation running.
   - Capture loading/generation state when visible as evidence after the recording boundary if useful.
8. Capture the result.
   - Continue in the same authenticated browser session until a real generated result is visible or a timeout/error is captured.
   - Save the result page screenshot.
   - Export/download the generated image if the site provides an action.
   - If no export is available, crop the result area from the browser screenshot and save it under `assets/results/`.
   - If multiple results are produced, save at least 2 and preferably 4 result crops or exports.
   - Mark the result image resources as `workflow_step: result_crop`, `result_export`, or `result_gallery`; do not mark the webpage screenshot as the final result visual.
9. Write metadata.
   - Update `browser_materials.json` for browser evidence.
   - Record machine-checkable login proof in `browser_materials.auth_state`:
     - `logged_in: true`
     - `points_balance: <number greater than 100>`
     - `evidence_asset_id: <screenshot asset id showing avatar/balance>`
   - Update `image_resources.json` for every clean, annotated, and result image.
   - Update `generation_receipts.json` with before/after points, feature id, generation cost when visible, input summary, result assets, and any errors.
   - For CDP tasks, include the recording boundary action index and the post-recording result capture action(s) so reviewers can verify that the video stopped waiting but the real generation chain continued.

## Red Callout Policy

Use red callouts to show the operation path, but preserve clean source screenshots.

Required:

- A clean raw screenshot for evidence.
- A separate annotated screenshot, or an `overlay_track` callout, for video presentation.
- Callout metadata in `image_resources.json` with target label and normalized box coordinates when available.
- For step-by-step entry paths, set `workflow_step` precisely: `home_entry`, `text_to_image_entry`, `menu_select` or `feature_menu_select`, then `feature_page_empty`.

Allowed callouts:

- red rectangle around a clicked function entry
- red circle around a selected menu item
- red arrow pointing to points balance, avatar, or `开始生成`
- short label such as `功能项`, `积分`, `登录后的头像`

Do not burn private information into annotated assets. Crop, mask, or omit it.

## Video Narrative Binding

Separate evidence from storytelling:

- `evidence_only`: login proof, points balance, raw route proof, repeated intermediate screenshots, call-chain traces.
- `candidate_video_visual`: feature entry, filled form, loading state, result page, red-callout images.
- `final_video_visual`: only the visuals selected for the requested hook, claim, or user-approved demo narrative.

Do not make the capture workflow itself the whole video topic. Use it to prove that the result is real, then choose the most persuasive subset for the final short video. The selected subset must still include a readable entry path: one short recording or sequential red-callout screenshots from `文生图` to the target feature.

The script should emphasize the requested selling point, real result quality, and only the minimum process evidence needed to make the claim credible. Default hook pattern:

```text
生成这样的一张门头效果图要多久？先看结果，再用真实截图证明它怎么来的。
```

Only use a full-flow hook such as `我从选功能开始，直接录完整流程` when the user explicitly asks for a step-by-step walkthrough.

Allowed result-showcase lines require captured result assets:

- `填完品牌信息，点开始生成。`
- `等待出图后，可以连续看几张不同方向的结果。`
- `这一张可以作为主展示，其他结果做快速掠过。`

If result capture fails, remove result-quality claims and use a workflow-only script.

## Material Status Mapping

Use these statuses consistently:

- `verified_result`: feature entry, filled input, generation action, and real result were captured.
- `verified_entry_only`: only the entry or form page was captured.
- `blocked_login`: logged-in state is unavailable.
- `blocked_quota`: account is logged in but points/credits are 100 or lower, or generation is blocked by quota.
- `blocked_permission`: account or browser permission blocks generation/export.
- `unsafe_action`: action would pay, publish, delete, change account settings, or otherwise alter state beyond generation.
- `unavailable`: the requested feature cannot be found.

Do not upgrade a feature to `verified_result` until at least one real generated result image is saved in the case directory and described in `image_resources.json`.

## Site Profile Update Chain

Default run:

1. Apply `references/site_profiles/kehuanxiongmao.json` into the case with `scripts/apply_site_profile.py`.
2. Use CDP to verify only the minimum live state: route/page title, expected labels, logged-in account, points balance, and generate button.
3. Continue with screenshot/result capture.

Manual refresh:

1. Re-read the frontend code for the target feature.
2. Use CDP to capture fresh snapshots of the home page, feature entry, form, cost display, and result list/history state.
3. Update `references/site_profiles/kehuanxiongmao.json`.
4. Run `scripts/apply_site_profile.py --refresh-needed --force` on an existing case to mark stale artifacts, then re-apply without `--refresh-needed` after the profile is reviewed.

Refresh when:

- `/textToImage/signboard` no longer opens 门头招牌.
- `src/router/index.js` maps the route to a different component.
- `src/views/textToSvg/components/LeftFormPanel.vue` changes required fields, option lists, quality values, or submit payload.
- `src/api/textToSvg.js` changes generation or task-list API names.
- CDP snapshots cannot find the expected page title, `开始生成`, or points display.
