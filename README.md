# Video Agent

Agent-driven website-to-video skill for generating short product/demo videos from a target website.

This project is a skill specification first. The P0 implementation is intentionally narrow:

```text
Kimi WebBridge -> website/browser materials
Vision model -> screenshot understanding and layout review
TTS -> voice
FunASR -> subtitle timing and voice QA
video_project.json -> multi-track source of truth
HyperFrames -> main video render
ffmpeg -> audio/video postprocess, outro concat, QA frames
```

## Canonical Docs

Read these in order:

1. `SKILL.md` - agent-facing skill entry
2. `docs/agent-playbook.md` - execution routing and acceptance checks
3. `docs/minimal-command-sop.md` - command budget, retry rules, and anti-patterns
4. `references/SPEC.md` - product and execution specification
5. `references/DEPENDENCIES.md` - required local tools and skills
6. `references/SCHEMA.md` - multi-track `video_project.json` contract
7. `references/QA.md` - voice, visual, layout, and render quality gates
8. `DEVELOPMENT_PLAN.md` - implementation roadmap

## Reference Docs

These are retained as source material, not implementation contracts:

- `references/copywriting-rules.md` - brand/copywriting knowledge base
- `references/copywriting-options.md` - copywriting option matrix

## Current Scripts

- `scripts/init_case.py` - create a case scaffold and copy default assets
- `scripts/register_materials.py` - register static image/video/audio materials
- `scripts/prepare_planner_context.py` - build model-ready planning context and brief files
- `scripts/accept_planner_output.py` - validate AI planner JSON and write reviewed artifacts
- `scripts/create_voice_plan.py` - join reviewed script segments into voice text and risk terms
- `scripts/generate_voice.py` - call the voice clone API and write `audio/voice.wav`
- `scripts/run_funasr.py` - transcribe `audio/voice.wav` and write FunASR alignment
- `scripts/check_voice_qa.py` - check speech density, ASR terms, and silence
- `scripts/apply_asr_alignment.py` - allocate ASR timing to reviewed script subtitles
- `scripts/build_video_project.py` - merge case artifacts into render-ready `video_project.json`
- `scripts/build_hyperframes.py` - build a minimal HyperFrames composition from `video_project.json`
- `scripts/render_hyperframes.py` - render HyperFrames and append declared outro
- `scripts/make_contact_sheet.py` - extract QA frames and build contact sheet
- `scripts/render_qa.py` - run machine-checkable render QA
- `scripts/validate_video_project.py` - validate `input.json` and `video_project.json`
- `scripts/check_case_hygiene.py` - check case and skill output hygiene
- `scripts/utils/skill_path.py` - resolve skill root and bundled default assets

## Current Rules

- `rules/setup.md` - skill root and asset bootstrap
- `rules/browser-webbridge.md` - Kimi WebBridge evidence-gathering boundary
- `rules/hyperframes-render.md` - HyperFrames render boundary and QA expectations
