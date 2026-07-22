---
name: agent-test-video-editor
description: Build a minimal agent-driven product demo video using word-timed TTS, CDP website recording, and Remotion.
---

# Agent Test Video Editor

1. Read the project JSON and available recipe IDs/result assets.
2. Generate or reuse one complete narration audio track with word-level timestamps.
3. Treat the word timing as immutable. Subtitles and visual scenes must share it.
4. Classify every subtitle cue as exactly one of: `website_operation`, `result_detail`, `result_gallery`, `before_after`, `title_card`.
5. A `website_operation` scene must reference an existing recipe. Never invent selectors or actions.
6. Result scenes may only use paths explicitly listed in `result_assets`.
7. Use `title_card` when no truthful visual evidence exists.
8. Render the generated `remotion_props.json` through the `AgentTest` Remotion composition.
9. Diagnose problems from `timing_lock.json`, `scene_plan.json`, CDP capture reports, and the final MP4. Do not patch rendered frames manually.
