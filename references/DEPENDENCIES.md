# Dependencies

## Required P0 Dependencies

### Kimi WebBridge

Purpose:

- interact with the user's browser through Local Agent
- inspect real website pages
- click, type, upload, and capture screenshots/recordings when supported
- preserve logged-in browser state on the local machine

Install:

```powershell
irm https://cdn.kimi.com/webbridge/install.ps1 | iex
```

Reference:

```text
https://www.kimi.com/features/webbridge
```

Usage rule:

- Use WebBridge for browser interaction and website material capture.
- Do not treat WebBridge as a renderer.
- Save all captured artifacts to the case folder before HyperFrames consumes them.
- Use captured browser evidence as product truth. Do not replace missing product result states with generated images or invented UI.
- If a generation action requires credits/points, stop before spending quota unless the user explicitly approves. Capture the blocker and ask for next material/permission.

### HyperFrames

Purpose:

- render the main video from HTML/CSS/JS
- create deterministic UI animation, focus crops, callouts, and visual layouts

Install/reference:

```text
https://github.com/heygen-com/hyperframes
```

Usage rule:

- P0 renderer is HyperFrames only.
- Do not implement MoviePy or Remotion adapters in P0.
- Use ffmpeg for intro/outro concat if HyperFrames video extraction fails on Windows.

### FunASR

Purpose:

- transcribe generated voice
- provide subtitle timing
- detect script/voice mismatch through ASR text

Install:

```powershell
python -m pip install -U funasr modelscope soundfile
```

If the local environment already has FunASR installed, do not reinstall first. Run a smoke test instead.

Smoke test:

```powershell
@'
from funasr import AutoModel
model = AutoModel(model="iic/SenseVoiceSmall", vad_model="fsmn-vad", vad_kwargs={"max_single_segment_time": 30000})
print("funasr_ok")
'@ | python -
```

Recommended local recognition helper:

```python
from funasr import AutoModel

model = AutoModel(
    model="iic/SenseVoiceSmall",
    vad_model="fsmn-vad",
    vad_kwargs={"max_single_segment_time": 30000},
)

result = model.generate(
    input="outputs/audio/voice.wav",
    cache={},
    language="zh",
    use_itn=True,
    batch_size_s=60,
    merge_vad=True,
    merge_length_s=8,
)
```

Output contract:

```json
{
  "audio_path": "outputs/audio/voice.wav",
  "engine": "funasr",
  "raw_result": [],
  "segments": [
    {
      "text": "字幕文本",
      "start": 0.0,
      "end": 1.8
    }
  ]
}
```

Usage rule:

- Run FunASR after voice generation or speed fitting.
- Do not use estimated speech-rate timing for final subtitles.
- Use FunASR output for timing, not necessarily for subtitle text.
- Use reviewed script text for final subtitles when ASR text contains homophones or brand-name errors.
- Use ASR text to detect risk, especially brand names, product names, final slogans, and mixed Chinese/English tokens.
- Save raw ASR output and normalized alignment output separately.

### TTS

Supported engines:

- CosyVoice
- IndexTTS
- voice clone API if available in the environment

Required voice input format:

- Use WAV for voice-clone prompt audio.
- Convert M4A/MP3 prompt audio to a standard WAV before calling TTS.
- Use a short, clean prompt sample, normally about 5 seconds.
- Avoid samples with BGM, overlapping speech, heavy reverb, or long silence.

Default voice-clone prompt:

```text
assets/voice/default_voice_clone_prompt_5s.wav
```

Metadata:

```text
assets/voice/default_voice_clone_prompt.metadata.json
```

This default prompt is the approved project voice sample. For each new case, copy it into the case audio directory before generation:

```powershell
Copy-Item "$env:VIDEO_AGENT_SKILL_ROOT\assets\voice\default_voice_clone_prompt_5s.wav" "audio\voice_prompt_5s.wav"
```

If `VIDEO_AGENT_SKILL_ROOT` is not set, resolve the skill root with the bundled skill path helper once it exists, or use the absolute skill path during development.

Allow user override:

```json
{
  "voice_config": {
    "prompt_audio": "C:/path/to/custom_prompt.wav"
  }
}
```

When a custom prompt is supplied, still validate that it is WAV, about 5 seconds, mono, and suitable for cloning.

Prompt audio conversion:

```powershell
ffmpeg -y -i input.m4a -t 5 -ac 1 -ar 16000 outputs/audio/voice_prompt_5s.wav
```

Voice clone API example:

```powershell
curl.exe --location "http://192.168.2.191:9890/api/v1/digital-human/voice-clones/generate" `
  --form "prompt_audio=@C:/path/to/voice_prompt_5s.wav" `
  --form "text=你好，欢迎体验声音克隆。" `
  --output outputs/audio/voice.wav
```

If the API returns JSON with a file URL or base64 payload instead of raw audio, the caller must download/decode it into `outputs/audio/voice.wav` and record the response in `outputs/audio/voice_response.json`.

Generation contract:

```json
{
  "engine": "voice_clone_api",
  "endpoint": "http://192.168.2.191:9890/api/v1/digital-human/voice-clones/generate",
  "prompt_audio": "outputs/audio/voice_prompt_5s.wav",
  "text": "完整口播文案",
  "audio_path": "outputs/audio/voice.wav",
  "format": "wav",
  "duration": 21.4
}
```

Usage rule:

- Voice generation must be measured.
- Brand names, product names, and mixed Chinese/English text such as `AI` are high-risk and require ASR verification.
- If a slogan sounds choppy, regenerate that segment independently.
- Do not pass M4A prompt audio directly to a voice-clone API unless that API is explicitly verified to accept it.
- Do not use a long prompt sample by default; long samples increase request size and make failures harder to debug.
- After generation, run ffprobe to measure duration, then run FunASR before assigning final subtitle and visual timings.
- Use ffmpeg speed fitting only inside the project policy; if the required speed change is large, rewrite or split text instead.

Voice duration check:

```powershell
ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 outputs/audio/voice.wav
```

Speed policy:

```text
ideal Chinese speech density: 4.8-6.2 chars/sec
hard Chinese speech density: 4.2-7.0 chars/sec
```

The pipeline should calculate text density before TTS and measure actual generated duration after TTS.

### ffmpeg

Purpose:

- audio conversion
- audio speed fit
- silence detection
- muxing and concat
- frame extraction
- contact sheet generation

Default fixed outro:

```text
assets/outro/default_panda_outro.mp4
```

Metadata:

```text
assets/outro/default_panda_outro.metadata.json
```

Usage rule:

- The default outro is not part of copywriting, subtitle generation, or visual beat planning.
- Generate the main video first.
- After the main video passes timing checks, append this outro in postprocess.
- Preserve the outro audio.
- The final output duration is `main_video_duration + outro_duration`.
- If the user explicitly disables the outro, set `ending_track.policy` to `none`.

Recommended concat approach:

```powershell
ffmpeg -y -i main.mp4 -i assets/outro/default_panda_outro.mp4 `
  -filter_complex "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v0];[1:v]scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2,fps=30,setsar=1[v1];[0:a]aformat=sample_rates=44100:channel_layouts=stereo[a0];[1:a]aformat=sample_rates=44100:channel_layouts=stereo[a1];[v0][a0][v1][a1]concat=n=2:v=1:a=1[v][a]" `
  -map "[v]" -map "[a]" -c:v libx264 -pix_fmt yuv420p -c:a aac final.mp4
```

Required commands:

```powershell
ffmpeg -version
ffprobe -version
```

### Vision Model

Purpose:

- understand screenshots and supplied images
- identify page role, UI regions, visual quality, and result areas
- review layout reasonableness after render

Usage rule:

- Filenames are hints only.
- Visual understanding must describe actual visible content and supported claims.
- Render QA must inspect contact sheets or snapshots, not only JSON.

## Optional P1 Dependencies

- BGM/SFX library
- dedicated browser recording tool if WebBridge does not expose recording
- object/region detector for more precise UI crop regions
- storage backend for generated artifacts

## Dependency Health Check

Before the first run, an agent should verify:

```text
Kimi WebBridge installed and reachable
HyperFrames CLI available
FunASR import/model available
TTS engine reachable
5s WAV prompt sample available when voice clone is used
ffmpeg/ffprobe available
vision model available to the agent
```

If any P0 dependency is missing, stop and report the missing capability instead of producing a fake video from imagination.
