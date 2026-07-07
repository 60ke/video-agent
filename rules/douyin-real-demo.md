---
name: douyin-real-demo
description: Douyin-quality real-demo rules for website-to-video cases.
---

# Douyin Real Demo Rules

Use these rules for Douyin, Kuaishou, Shorts, Reels, and any vertical product/demo video whose subject is a real website.

The video must be a short film assembled from real product evidence. It must not be a decorative interpretation of the website.

## Evidence Order

Use visual evidence in this priority order:

1. Real browser recording of the user flow.
2. Real screenshots of the input state, selected feature/category, generation/loading state, and result state.
3. Real exported result assets from the product.
4. Cropped website screenshots that support a specific claim.
5. Designed cover/title frames based on captured evidence.

Do not use generated product photos, generic ecommerce mockups, emoji, stock-like illustrations, or invented UI as a substitute for missing website output.

Generated or hand-designed imagery is allowed only for:

- cover/title packaging
- neutral backgrounds
- callout shapes
- transitions

It must be labeled as packaging in planning artifacts and must never be presented as a product-generated result.

## Operation Flow Gate

Before script planning, classify each requested feature:

```json
{
  "feature_id": "ecommerce_text_to_image",
  "requested_claim": "select ecommerce and generate product image",
  "operation_status": "verified_result | verified_entry_only | blocked_login | blocked_permission | unsafe_action | unavailable",
  "evidence_assets": [],
  "missing_evidence": [],
  "allowed_claims": [],
  "disallowed_claims": []
}
```

Rules:

- `verified_result`: input, generation, and result are captured. A full demo video may claim real generation.
- `verified_entry_only`: only the entry/category is visible. The video may claim the entry exists, but may not show or imply generated results.
- `blocked_login`: stop and ask for login or supplied materials.
- `unsafe_action`: stop before payment, publishing, deletion, or account changes unless the user explicitly allows that action.

If a result is not captured, do not write narration such as "生成高质量主图" unless it is clearly framed as a capability stated by the website and backed by page text. Prefer "进入电商分类" or "准备输入产品、风格、场景".

When real generated results are captured, favor a short result gallery beat over repeating the same UI screenshot. Save each result as a separate local asset and describe it in `image_resources.json` before using lines such as "连续看几张不同方向的结果".

## Category Selection Rules

When the requested feature is a category, such as `电商`, the visual must make that category the only focal point.

Reject:

- showing a whole category row where many unrelated labels compete with the requested category
- adding a box around `电商` while the title or subtitle discusses another category
- cropping so wide that `招牌门头`, `文化墙`, `IP形象`, or other categories read as equal subjects
- implying that clicking the category opened a separate page if URL/content did not change

Required:

- crop tightly enough that `电商` is legible and dominant
- include action evidence if selection changes state
- if selection has no visible state change, record that as `verified_entry_only`
- narration must match the actual evidence: "文生图里有电商分类入口" is allowed; "进入电商结果页" is not allowed unless a result page exists

## Login And Result Handling

If the user is not logged in, stop before generation and capture the blocker. If generation is requested and login is verified, proceed through the real interaction chain. Do not create fake generated results; if a real result cannot be captured, make a workflow-only video only with explicit approval.

## Douyin Layout Rules

Every frame must pass a mobile squint test:

- one dominant visual subject occupying at least 40% of the canvas
- no full-page website strips unless the strip is background only
- no tiny dense website text as the primary visual
- no more than one short headline and one subtitle rail per frame
- no repeated explanatory text blocks
- subtitles must not cover the active input, result, category, or CTA area
- cover frame must be designed from actual captured evidence or explicitly marked packaging

Use large focus crops, screen recordings, and result close-ups. Split dense UI into sequential close-ups instead of showing the whole page. For feature-entry demos, prefer a short recording of the click path; when recording is unavailable, use multiple red-callout screenshots so the viewer can follow each click.

## Motion Rules

Default motion is stable.

Reject:

- arbitrary zoompan on every scene
- jitter, breathing, or floating cards used only to make still frames look alive
- camera movement that makes UI text harder to read
- motion that is not tied to voiceover or a real user action

Allowed:

- click-to-focus
- crop push into a selected category/input/result
- screen-recording playback
- one deliberate transition between evidence states
- still holds when the user needs to read the UI

If there is no useful motion, hold still. Stillness is better than artificial movement.

## Script And Visual Binding

Each script segment must bind to one of:

- `real_recording`
- `real_screenshot`
- `real_result`
- `error_state`
- `evidence_cover`
- `packaging_only`

Segments with `packaging_only` cannot contain product-result claims.

Every segment must answer:

- What real page/action/result supports this line?
- Is this line visible in the captured evidence?
- If not visible, is it supported by page text?
- Does the visual show exactly what the voice says at that moment?

If the answer is no, rewrite the segment or recapture evidence.

## Final Gate

Do not call a render final unless the report states:

- `real_demo_status`: `verified_result` or an approved non-result workflow preview state
- no generated imagery is used as product evidence
- category crops focus only the requested category
- no arbitrary motion failures
- Douyin mobile layout QA passed
