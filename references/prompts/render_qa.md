# Render QA Prompt

Use this prompt with the contact sheet and render report.

## Goal

Decide whether the render can be called final or must be repaired.

## Required Output

Return JSON:

```json
{
  "status": "passed",
  "failures": [],
  "warnings": [],
  "repair_actions": [
    {
      "target": "vis_003",
      "problem": "UI screenshot is too narrow to read.",
      "action": "Switch to crop-focus and enlarge the main form region."
    }
  ]
}
```

## Checkpoints

- no black frames
- no missing media
- no sudden flash when the same image continues
- UI/result content is readable on mobile
- no large meaningless blank or blurred panels
- subtitles are visible and do not cover key content
- no undeclared text/title appears outside subtitle rail
- visual content matches current subtitle
- product-result claims are backed by captured/supplied product evidence
- requested category crops make that category dominant
- no generated photo, generic mockup, emoji, or invented UI is used as product evidence
- no arbitrary zoompan, breathing, jitter, or floating motion appears
- fixed panda outro starts only after the generated main video

## Rules

- If a scene is only decorative background with tiny content, fail it.
- If a tall image scrolls too fast to understand, fail it.
- If dual-panel media occupies only the top of tall empty panels, fail it.
- If website/app screenshots are available but the render uses unclear static material, request recapture or crop-focus.
- If a real generation/result was not captured but the render shows a generated-looking result, fail it.
- If the user asked for `电商` but the frame visually emphasizes the entire category row or unrelated category labels, fail it.
- If motion makes UI text harder to read, fail it.
- Do not mark final if the voice QA or render QA report already has failures.
