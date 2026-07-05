---
name: video-agent
description: Generate a vertical product/demo video from a target website using Kimi WebBridge for browser interaction, a vision model for screenshot understanding, TTS plus FunASR for voice/subtitle alignment, a multi-track video_project.json contract, HyperFrames for rendering, and ffmpeg for postprocess and QA.
---

# Video Agent

Use this skill when the user provides a target website or asks to create a short feature seeding, product demo, website showcase, or social media promo video from a real website.

## Required Reading

Read these files before running a full case:

1. `docs/agent-playbook.md`
2. `docs/minimal-command-sop.md`
3. `rules/setup.md`
4. `rules/browser-webbridge.md` when browser/website interaction is required
5. `rules/douyin-real-demo.md` when the target platform is Douyin/Kuaishou/Reels/Shorts or when the video must demonstrate a real website flow
6. `rules/hyperframes-render.md` before building or rendering HyperFrames
7. `references/SPEC.md`
8. `references/DEPENDENCIES.md`
9. `references/SCHEMA.md`
10. `references/QA.md`

Use `references/copywriting-rules.md` and `references/copywriting-options.md` as copywriting knowledge when the brand is 科幻熊猫.

## Inputs

Minimum:

```json
{
  "target_url": "https://example.com",
  "video_goal": "功能种草",
  "duration": 30
}
```

Optional:

```json
{
  "preferred_features": ["文化墙"],
  "brand_profile": "科幻熊猫",
  "target_platform": "douyin",
  "voice_config": {
    "prompt_audio_policy": "default"
  },
  "ending_track": {
    "policy": "default"
  }
}
```

## Outputs

Required:

- `website_knowledge.json`
- `feature_cards.json`
- `browser_materials.json`
- `video_script.json`
- `voice.wav`
- `funasr_alignment.json`
- `video_project.json`
- `hyperframes/index.html`
- `output/versions/final.mp4`
- `output/qa/contact_sheet.jpg`
- `output/reports/render_report.json`

## Execution

1. Verify dependencies.
   - Kimi WebBridge reachable
   - HyperFrames available
   - FunASR available
   - TTS available
   - ffmpeg/ffprobe available
   - vision model available

2. Research the website with Kimi WebBridge.
   - Capture pages, screenshots, DOM/page text, and safe interaction evidence.
   - Stop if required login or permissions are unavailable.
   - For Douyin/product-demo cases, classify every requested feature as `verified_result`, `verified_entry_only`, `blocked_login`, `blocked_quota`, `blocked_permission`, `unsafe_action`, or `unavailable` before script planning.
   - If the result state is not captured, do not invent or generate substitute result visuals.

3. Generate feature cards and operation recipes.
   - Every selected feature must have page evidence.
   - Dangerous browser actions are forbidden.

4. Capture browser materials.
   - Screenshots and recordings are frozen local assets.
   - Record action events and result-ready moments.
   - Prefer real screen recordings or sequential screenshots of input, action, loading, and result states.
   - If the user is logged in but has no credits/points, capture the blocker and build only an approved workflow preview, not a fake result video.

5. Generate structured video script.
   - Do not stop at plain copy.
   - Every segment needs text, stage, visual intent, and material task.

6. Generate voice and ASR alignment.
   - Use `assets/voice/default_voice_clone_prompt_5s.wav` when `voice_config.prompt_audio_policy` is `default`.
   - Copy the prompt audio into the case `audio/` directory before calling the voice clone API.
   - Run FunASR on generated audio.
   - Use ASR timing for subtitles.
   - Run brand-name and silence QA.

7. Build `video_project.json`.
   - Use the multi-track schema in `references/SCHEMA.md`.
   - Plan voice, subtitles, visuals, overlays, optional audio, optional ending, renderer plan, and QA rules.

8. Build and validate HyperFrames.
   - Use frozen local assets.
   - Preserve timing from `video_project.json`.
   - Do not add unsupported claims or undeclared text.

9. Render and postprocess.
   - Render main video with HyperFrames.
   - Append `assets/outro/default_panda_outro.mp4` after the generated main video when `ending_track.policy` is `default`.
   - Use ffmpeg for concat/mux/extract frames.

10. Run QA.
    - Voice QA
    - subtitle QA
    - visual/layout QA
    - browser material QA
    - render QA

11. Return final artifacts only when QA passes.

## Non-Negotiable Rules

- Use Kimi WebBridge for P0 browser interaction.
- Use HyperFrames as the P0 renderer.
- `video_project.json` is the source of truth.
- Do not rely on estimated timing after voice exists.
- Do not mutate bundled skill assets; copy default voice assets into the case before use.
- Do not include the fixed outro in script, subtitle, voice, or visual beat planning; append it only after the main video is complete.
- Do not generate video from imagination when real website material is available.
- Do not use generated product photos, generic mockups, emoji, or invented UI as product evidence.
- Do not claim or show a generated result unless the real result was captured or supplied.
- Do not spend credits/points, publish, pay, delete, or change account state unless the user explicitly approves that action.
- Do not show unrelated category labels as equal subjects when the user asked for a specific category such as `电商`; crop and narrate only the verified category state.
- Do not add arbitrary zoompan, jitter, breathing, or floating motion. Motion must be tied to voiceover or a real browser action.
- Do not skip contact-sheet or snapshot QA.
- Do not present a video as final if brand voice, subtitle timing, visual readability, or layout QA fails.
- Keep older output versions; never overwrite an accepted render.
