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

Do not use WebBridge when:

- the user only provides a static material folder and no live UI is needed
- the task is only validating an existing `video_project.json`
- the task is only appending the fixed outro or checking audio

## Required Captures

For each selected feature, save evidence under the case directory:

- page URL or route
- screenshot of the feature entry page
- visible page text or DOM summary when available
- interaction steps
- screenshot before operation
- screenshot or recording during operation when useful
- result screenshot or result area
- quota/points/login blocker screenshot when the operation cannot complete
- error screenshot if the operation fails

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

If login is required and not available, stop and ask for access or static materials.

If the feature cannot be safely operated, document the limitation in `feature_cards.json` and choose another supported feature.

If captured materials cannot support the proposed narration, revise the narration or recapture evidence. Do not invent.

If the feature is only an entry point and clicking it does not change URL/content/state, record `operation_status: "verified_entry_only"` and limit claims to the visible entry point.
