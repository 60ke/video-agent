# Agent Notes

## Current Direction

- The previous Electron recorder and CDP video capture experiments are abandoned.
- CDP is used for login reuse, navigation, screenshot capture, form inspection, and coordinate metadata only.
- Video visuals are built from registered images, GPT image prepared 9:16 keyframes, and renderer-side `overlay_track` callouts.
- Do not add a new browser video recording path unless the user explicitly reopens that experiment.
