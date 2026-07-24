# Video Agent V4

面向抖音 9:16 短视频的 V4 生产主线。系统以冻结口播、MiniMax
词级时间轴、Scene Semantics 和 Stage3 素材仓库生成确定性时间线，再由
Remotion 输出 MP4，或由剪映 Skill 输出可继续人工编辑的原生草稿。

## 核心原则

- 口播短语、字幕、视觉焦点和语义 SFX 共用同一个词级 Anchor。
- 画布固定 1080×1920 @ 30fps，布局使用抖音安全区 profile。
- AI 只负责 Scope / Scene / Goal 文案等语义决策；渲染器是 dumb executor。
- 生产选材只读 Stage3 Repository；进入仓库的素材视为项目外已人工确认，程序只做完整性检查。
- 官网 Logo 固定为 `assets/brand/kehuanxiongmao/logo/柯幻熊猫_LOGO.png`。
- BGM 默认关闭；启用前必须注册真实可探测 Profile（当前未启用）。

## 生产链路

```text
--script / --goal
  -> FrozenNarration
  -> MiniMax SpeechTimingLock
  -> VideoScope + SceneSemanticPlan
  -> Stage4 ResolvedAssetPlan (+ 允许的 Derivation)
  -> AnchoredTimingPlan
  -> MotionAudioPlan
  -> BGM (skipped while disabled)
  -> CompiledVideoTimeline
  -> Structured QA
  -> Editor Backend
       |- Remotion V4Timeline + FFmpeg mix
       `- Jianying Skill -> 原生剪映草稿
  -> Cover.png (独立交付，不改正文首帧)
  -> Delivery QA
  -> final/video.mp4 + final/cover.png
```

公共入口只走 `V4ProductionOrchestrator`。V3 Orchestrator / VerticalDemo / cover 首帧污染路径已删除。

## 安装

要求：Python 3.10–3.12、Node.js、FFmpeg。

```powershell
python -m pip install -e ".[dev]"
Set-Location remotion
npm install
Set-Location ..
```

密钥只放在已忽略的本地配置中：

- `config/minimax.local.json`
- `config/gpt_image.local.json`
- `config/ai.local.json`（或 AI Runtime 对应本地配置）

示例见同目录 `*.example.json`。

## 命令行生成视频

日常生产只需两种命令（`main.py` 会把以 `-` 开头的参数路由到 `generate_video`）：

```powershell
python main.py --script C:\copy\文案.txt
python main.py --goal "柯幻熊猫文生图功能种草"
```

等价显式写法：

```powershell
python main.py generate-video --script C:\copy\文案.txt
python main.py generate-video --goal "柯幻熊猫文生图功能种草" --json
```

- `--script`：锁定原文，不改写。
- `--goal`：先由 Goal Narration 生成口播，再冻结为同一条生产链。

成功后返回 `case_id`、`run_id`、`final_video`、`final_cover`。

可选：

```powershell
python main.py --script .\文案.txt --cases D:\video_cases --case-id ad_demo_v1 --json
```

### 剪映原生草稿后端

剪映后端复用同一份冻结口播、词级 Anchor、选材和编译时间线，只替换最后的编辑
执行层。先检查本机 Skill：

```powershell
python main.py jianying-probe --json `
  --jianying-skill-root "C:\Users\CNGG\Desktop\jianying-editor-skill"
```

从文案直接生成剪映草稿：

```powershell
python main.py --script .\文案.txt `
  --editor-backend jianying `
  --jianying-skill-root "C:\Users\CNGG\Desktop\jianying-editor-skill"
```

也可以把已有 Run 的 Stage6 时间线编译为草稿：

```powershell
python main.py v4-stage6 `
  --case cases\<case_id> `
  --resume <run_id> `
  --phase compile-render `
  --render `
  --editor-backend jianying `
  --jianying-skill-root "C:\Users\CNGG\Desktop\jianying-editor-skill"
```

Run 内会写入：

```text
render/jianying/edit_blueprint.json
render/jianying/jianying_project_manifest.json
```

CLI 同时返回剪映草稿的绝对路径。当前生产支持图片轨、剪映原生转场与动画、
字幕、MiniMax 配音及 SFX；草稿需在剪映中人工打开并导出。本机剪映 11.1
超出外部 Skill 自动导出控制器的兼容范围，因此不会伪装成已经输出 MP4。
录屏脚本、鼠标事件和点击动效仍属于后续 Capture 接入，不在当前生产能力内。

### 本地配置

```powershell
Copy-Item config\minimax.example.json config\minimax.local.json
Copy-Item config\gpt_image.example.json config\gpt_image.local.json
```

- `minimax.local.json`：整段口播 + word 时间戳（必需）。
- GPT Image：仅当 Stage4 需要生产 Derivation 时调用。

```powershell
Set-Location remotion
npm install
Set-Location ..
```

### 调试入口

`init` / `script-lock` / `run` / `inspect` 以及 `v4-stage1`…`v4-stage6`、`v4-assets` 用于调试与素材管理，不是日常成片入口。

```powershell
python main.py run --case cases\demo --json
python main.py inspect --case cases\demo --json
```

`script-lock` 写入 `input/source_script.txt`（V4 冻结文案源），不再写 V3 `narration.json`。

## Case 与运行产物

```text
cases/<case>/
  case.json
  input/
    source_script.txt          # script 模式
  runs/<run_id>/
    frozen_narration.json
    speech_timing_lock.json
    video_scope.json
    scene_semantic_plan.json
    resolved_asset_plan.json
    anchored_timing_plan.json
    motion_audio_plan.json
    bgm_plan.json              # 当前多为 disabled 记录
    compiled_video_timeline.json
    structured_qa_report.json
    run_manifest.json
    render/silent.mp4
    render/final.mp4
    final/cover.png
    final/video.mp4
```

封面是独立 `final/cover.png`，**不会**改写正文视频首帧。片尾由 Scene 中 `configured_asset` outro 进入时间线，不再做 V3 后处理追加。

## 素材与仓库

生产真相在 Stage3：

- DB：`var/v4/assets.sqlite3`
- Object root：`assets/`（见 `config/assets.v4.json`）

管理命令：

```powershell
python main.py v4-assets migrate-legacy --json
python main.py v4-assets audit --json
python scripts/run_production_asset_coverage_gate.py --repo-root .
```

Admin 批处理（不属于成片 DAG）：

```powershell
python main.py site-entry-batch --json
python main.py site-params-sequence --json
python main.py editor-flow --artwork ... --editor-template ... --modal-template ... --semantic-path 文生图 --json
python main.py import-video-materials --source C:\materials --json
```

## 音频

- MiniMax 单次合成完整口播，`subtitle_type=word`。
- 字幕 / 视觉 / SFX 绑定同一份 `SpeechTimingLock` + Anchor Compiler。
- SFX 来自 `assets/audio/sfx` 与 MotionAudioPlan。
- Remotion 输出静音视频；FFmpeg 混口播与 SFX。
- **BGM 默认关闭**；未注册真实 Profile 前不得启用。

## 模块架构

| 模块 | 职责 |
|---|---|
| `video_agent/v4/production.py` | 唯一生产 DAG |
| `video_agent/v4/` | Stage1/4/5/6 runners |
| `video_agent/contracts/v4/` | V4 Contract |
| `video_agent/semantic/` | Scope / Scene / Goal Narration |
| `video_agent/speech/v4/` + `speech/minimax.py` | 原生 TTS / 鉴权壳 |
| `video_agent/assets/v4/` | Stage3 Repository / ObjectStore / Resolver |
| `video_agent/compiler/v4/` | Timeline / subtitles / SFX compile |
| `video_agent/render/v4/` | Remotion export + FFmpeg mix |
| `video_agent/media/` | 共享 ffprobe / canvas |
| `remotion/src/v4/` | `V4Timeline` composition |

设计边界见 [架构说明](docs/architecture.md) 与 [V4 实施进度](docs/v4_implementation_progress.md)。

## 验证

```powershell
python -m compileall -q video_agent
python -m pytest tests -k v4 -q
Set-Location remotion
npx tsc --noEmit
```
