---
name: kehuanxiongmao-capture
description: Fixed Kimi WebBridge capture workflow for 柯幻熊猫 real generation demos.
---

# 柯幻熊猫截图与结果采集规则

Use this rule whenever the target site is `https://kehuanxiongmao.com` or the case is a 柯幻熊猫 feature demo.

The goal is to capture a complete, auditable product flow that can support future short-video generation and skill optimization. The browser evidence must show the real path from feature discovery to generated result, but the final video does not need to show every captured step.

## Hard Requirements

- Access the website only through Kimi WebBridge.
- Use the user's already logged-in browser session. Do not ask for passwords or handle credentials.
- Before generation, capture visible evidence that the account is logged in and the points/credits balance is greater than 100.
- If the balance is 100 or lower, or the balance cannot be read, do not press `开始生成`; capture the blocker and stop for approval or supplied result material.
- If the user explicitly asked for the full generation flow and the balance is greater than 100, pressing the generation button is allowed for this site.
- Every screenshot used in the video must be copied into the case directory. Do not leave final assets in temp folders.

## Case Directory Layout

Save browser and result materials under:

```text
assets/browser/raw/
assets/browser/annotated/
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

The profile is a shortcut, not proof. Kimi WebBridge must still verify live page state, login state, points balance, screenshots, and generated results.

1. Open `https://kehuanxiongmao.com` with Kimi WebBridge.
2. Capture the home page or dashboard state.
   - Save a clean screenshot.
   - Record page URL, page title, visible navigation labels, avatar/login indicator, and points balance.
3. Capture the feature entry path.
   - Show the left navigation or top feature card.
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
   - Capture loading/generation state when visible.
8. Capture the result.
   - Save the result page screenshot.
   - Export/download the generated image if the site provides an action.
   - If no export is available, crop the result area from the browser screenshot and save it under `assets/results/`.
   - If multiple results are produced, save at least 2 and preferably 4 result crops or exports.
9. Write metadata.
   - Update `browser_materials.json` for browser evidence.
   - Update `image_resources.json` for every clean, annotated, and result image.
   - Update `generation_receipts.json` with before/after points, feature id, generation cost when visible, input summary, result assets, and any errors.

## Red Callout Policy

Use red callouts to show the operation path, but preserve clean source screenshots.

Required:

- A clean raw screenshot for evidence.
- A separate annotated screenshot, or an `overlay_track` callout, for video presentation.
- Callout metadata in `image_resources.json` with target label and normalized box coordinates when available.

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

Do not make the capture workflow itself the default video topic. Use it to prove that the result is real, then choose the most persuasive subset for the final short video.

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
2. Use Kimi WebBridge to verify only the minimum live state: route/page title, expected labels, logged-in account, points balance, and generate button.
3. Continue with screenshot/result capture.

Manual refresh:

1. Re-read the frontend code for the target feature.
2. Use Kimi WebBridge to capture fresh snapshots of the home page, feature entry, form, cost display, and result list/history state.
3. Update `references/site_profiles/kehuanxiongmao.json`.
4. Run `scripts/apply_site_profile.py --refresh-needed --force` on an existing case to mark stale artifacts, then re-apply without `--refresh-needed` after the profile is reviewed.

Refresh when:

- `/textToImage/signboard` no longer opens 门头招牌.
- `src/router/index.js` maps the route to a different component.
- `src/views/textToSvg/components/LeftFormPanel.vue` changes required fields, option lists, quality values, or submit payload.
- `src/api/textToSvg.js` changes generation or task-list API names.
- WebBridge snapshots cannot find the expected page title, `开始生成`, or points display.
