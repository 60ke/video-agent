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
- fixed panda outro starts only after the generated main video

## Rules

- If a scene is only decorative background with tiny content, fail it.
- If a tall image scrolls too fast to understand, fail it.
- If dual-panel media occupies only the top of tall empty panels, fail it.
- If website/app screenshots are available but the render uses unclear static material, request recapture or crop-focus.
- Do not mark final if the voice QA or render QA report already has failures.
