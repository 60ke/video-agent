---
name: browser-webbridge
description: Rules for using Kimi WebBridge as the browser evidence and interaction layer.
---

# Browser WebBridge Rules

Use Kimi WebBridge for real website or frontend interaction in P0.

The browser layer gathers evidence. It does not render the final video and does not invent claims.

## When To Use

Use WebBridge when:

- the user provides a website URL
- the user provides a frontend project that must be operated in a browser
- the video claims depend on real UI state, generated result pages, uploads, forms, dashboards, or browser interactions

This is the default for website/product videos. Do not downgrade to static materials unless the user's prompt explicitly asks to use static resources, an existing material folder, or already supplied assets as the evidence source.

On Windows, send WebBridge commands as JSON files posted with `curl.exe --data-binary`, especially when arguments contain Chinese text. Do not inline Chinese JSON in PowerShell command strings.

Do not use WebBridge when:

- the user explicitly asks to use only a static material folder or supplied assets and no live UI is needed
- the task is only validating an existing `video_project.json`
- the task is only appending the fixed outro or checking audio

## Required Captures

For each selected feature, save evidence under the case directory:

- page URL or route
- screenshot of the feature entry page
- visible page text or DOM summary when available
- interaction steps
- short browser recording of the entry path when available
- screenshot before operation
- screenshot or recording during operation when useful
- result screenshot or result area
- quota/points/login blocker screenshot when the operation cannot complete
- error screenshot if the operation fails

For `https://kehuanxiongmao.com`, also read `rules/kehuanxiongmao-capture.md` and follow its fixed sequence for logged-in/points verification, red callout screenshots, generation, result export/crop, and image resource metadata.

For navigation-heavy product demos, recording is preferred. If the browser bridge cannot record, capture a stepwise screenshot set with annotated click targets. Do not jump directly from result or form screenshots without showing how the viewer reaches the feature.

## Output Artifacts

Write or update:

```text
website_knowledge.json
feature_cards.json
operation_recipes.json
browser_materials.json
```

Each browser material should include:

```json
{
  "id": "browser_asset_001",
  "type": "image",
  "source": "assets/browser/upload_page.png",
  "origin": "browser_capture",
  "page_url": "/design/vi",
  "role": "feature_entry",
  "operation_status": "verified_result",
  "visible_text": ["上传", "开始生成"],
  "supported_claims": ["选择参数后一键生成"],
  "quality": {
    "readable": true,
    "contains_private_info": false,
    "needs_review": false
  }
}
```

Use ASCII ids. Keep Chinese text in `visible_text`, `description`, and `supported_claims`.

For image assets, also write `image_resources.json`. `browser_materials.json` records browser evidence; `image_resources.json` records reusable image-level meaning, filename conventions, callouts, result relationships, and layout guidance for later agents.

## Safety Boundaries

Do not perform:

- payment
- deletion
- publishing
- external messaging
- account changes
- irreversible generation that consumes paid quota unless the user explicitly allows it
- any action that exposes credentials or private user data

If sensitive data appears, mask it, crop it out, or recapture a safer state.

If the user is logged in but has no credits/points, capture the available setup/input UI and the quota blocker. Do not create or substitute a fake generated result.

## Material Quality Rules

- Prefer portrait/mobile captures when the target video is vertical.
- If the website is desktop-only, capture functional regions instead of full unreadable pages.
- Capture both input/control state and result state when the claim depends on before/after.
- For category features, crop around the requested category so it is the visual subject. Do not present unrelated categories as equal subjects.
- Do not use browser screenshots as tiny full-page strips.
- Do not use filenames as semantic truth; use visible content and vision review.

## Failure Rules

If WebBridge is not installed or reachable, stop and report the dependency failure.

If login is required and not available, stop and ask for access. Ask for static materials only as an explicit fallback option, and label the resulting workflow as static-materials based.

If the feature cannot be safely operated, document the limitation in `feature_cards.json` and choose another supported feature.

If captured materials cannot support the proposed narration, revise the narration or recapture evidence. Do not invent.

If the feature is only an entry point and clicking it does not change URL/content/state, record `operation_status: "verified_entry_only"` and limit claims to the visible entry point.
