# Video Agent V3

面向抖音 9:16 短视频的素材驱动视频编译器。系统把文案、MiniMax 词级时间轴、场景分类、素材关系、Remotion 动效、字幕和音效编译为一份确定性的 `render_plan.json`，再输出最终 MP4。

## 核心原则

- 声音、字幕、画面重点和语义音效共用同一个词级时间锚点。
- 画布固定为 1080x1920、30 fps，并统一使用抖音安全区。
- 场景先分类，再选素材和动效；具体可视化素材缺口由 AI 判断是否基于现有结果图调用 GPT Image 派生，抽象或不可可靠派生的缺口才使用 `light_sweep`，绝不拿无关图片猜测。
- `assets/` 是项目外人工整理后的可用素材边界。运行时只做文件完整性检查，不做 AI 视觉审核。
- 网站截图的标注使用缓存派生图或 Remotion 图层，不在渲染时读取原始网页坐标重画框选。
- GPT Image 派生发生在场景识别之后、视觉编排之前；派生只能补素材，不能改动语音和时间轴。

## 生产链路

```text
assets/
  -> catalog
  -> narration
  -> speech + word timing
  -> DeepSeek Flash full-catalog recall
  -> DeepSeek Pro ActionScene planning
  -> asset preflight / cached GPT Image derivation
  -> VisualPlan
  -> RenderPlan
  -> Remotion silent video
  -> FFmpeg audio mix
  -> final/video.mp4
```

唯一运行 DAG：

```text
catalog -> narration -> speech -> scene -> prepare_assets -> visual -> compile -> render
```

每个阶段的输入指纹、产物哈希和状态记录在 `run_manifest.json`。`--resume` 只复用指纹与产物都没有变化的阶段。

## 安装

要求：Python 3.10-3.12、Node.js、FFmpeg。

```powershell
python -m pip install -e ".[dev]"
Set-Location remotion
npm install
Set-Location ..
```

密钥只放在已忽略的本地配置中：

- `config/minimax.local.json`
- `config/gpt_image.local.json`
- `config/ai.local.json`

示例配置位于同目录的 `*.example.json`。运行时配置优先于契约默认值；不要在文档或代码中复制本地音色 ID 和 API Key。

## 命令行生成视频

### 1. 准备本地配置

复制示例文件并填写本机密钥。三个 `*.local.json` 均已被 Git 忽略：

```powershell
Copy-Item config\ai.example.json config\ai.local.json
Copy-Item config\minimax.example.json config\minimax.local.json
Copy-Item config\gpt_image.example.json config\gpt_image.local.json
```

- `ai.local.json`：固定文案和 AI 文案模式都需要。Flash 模型负责素材粗筛，Pro 模型负责 ActionScene 场景分类、素材绑定和派生决策。
- `minimax.local.json`：必需。负责整段口播和 word 级时间戳；本地 `voice_id`、`speed` 等配置会覆盖 Case 默认值。
- `gpt_image.local.json`：仅当场景需要补充因果素材、统一轮播比例或生成编辑状态等派生图时调用。已有缓存会直接复用。

Remotion 依赖也必须已安装：

```powershell
Set-Location remotion
npm install
Set-Location ..
```

### 2. 根据固定文案生成

推荐把文案保存为 UTF-8 文本文件，避免 PowerShell 对长中文和换行的转义问题。例如：

```powershell
@'
广告人必须收藏的全能网站！
文化墙、门店招牌、景观小品、商业美陈、品牌 LOGO、活动物料等各类设计，它都能一键生成。
拿文化墙设计举例，选定所属行业、主题还有场景，即刻出高级质感效果图。
'@ | Set-Content -Encoding utf8 C:\copy\ad_script.txt
```

在仓库根目录初始化一个全新的 Case。`--case-id` 只能使用英文、数字、下划线或连字符，且 `--case` 指向的目录不能已经存在：

```powershell
python -m video_agent init `
  --case cases\ad_demo_20260716 `
  --case-id ad_demo_20260716 `
  --goal "柯幻熊猫文生图功能种草" `
  --feature-path 文生图 `
  --script-file C:\copy\ad_script.txt `
  --json
```

执行完整生产链路：

```powershell
python -m video_agent run --case cases\ad_demo_20260716 --json
```

成功后命令会返回 `run_id`、`run_dir` 和 `final_video`。默认成片位于：

```text
cases/ad_demo_20260716/runs/<run_id>/final/video.mp4
```

查看最新运行的阶段记录和 QA 信息：

```powershell
python -m video_agent inspect --case cases\ad_demo_20260716 --json
```

固定文案模式只锁定口播原文。系统会确定性生成初始 `Narration`，MiniMax 提供词级时钟，AI 仍会结合完整素材目录完成场景分类、素材粗筛、精确卡点、素材派生决策和动效选择，但不会改写传入文案。

### 3. 更新已有 Case 的固定文案

```powershell
python -m video_agent script-lock `
  --case cases\ad_demo_20260716 `
  --script-file C:\copy\ad_script_v2.txt `
  --json

python -m video_agent run --case cases\ad_demo_20260716 --json
```

每次不带 `--resume` 执行 `run` 都会创建新的 Run，不会覆盖历史成片。

### 4. 直接传入短文案

短文案也可以使用 `--script-text`：

```powershell
python -m video_agent init `
  --case cases\culture_wall_demo `
  --case-id culture_wall_demo `
  --goal "文化墙功能介绍" `
  --feature-path 文生图 `
  --feature-path 文化墙 `
  --script-text "文化墙、门店招牌、景观小品都能一键生成。" `
  --json
```

### 5. 让 AI 生成文案

初始化不带 `--script-file` 或 `--script-text` 的 Case，然后把 `case.json` 的 `ai_enabled` 设为 `true`。Story Planner 会使用 `config/ai.local.json` 生成结构化 `Narration`。从 MiniMax 语音阶段开始，它与固定文案模式共用同一条 ActionScene、素材准备、视觉编排、编译和渲染链路。

## Case 与运行产物

```text
cases/<case>/
  case.json
  input/
    narration.json          # 锁定文案模式
    cover.json              # 可选；不存在时按 Case 和口播自动生成封面规格
  runs/<run_id>/
    asset_catalog.source.json
    narration.json
    timing_lock.json
    timing_qa.json
    scene_plan.json
    asset_preparation_plan.json
    asset_preparation_report.json
    asset_catalog.json
    resolved_scene_plan.json
    visual_plan.json
    render_plan.json
    run_manifest.json
    cover_report.json          # cover_enabled=true
    outro_report.json          # outro_enabled=true
    work/
    final/cover.png
    final/cover_3x4_preview.png
    final/video.mp4
```

封面和片尾是 Case 配置项，默认都开启：

```json
{
  "cover_enabled": true,
  "cover_source": "input/cover.json",
  "outro_enabled": true,
  "outro_source": "assets/outro/default_panda_outro.mp4"
}
```

`cover_source` 文件可以不存在，此时系统会根据 Case 目标、完整口播和实际使用素材生成默认封面规格。任一开关设为 `false` 即跳过对应后处理。

阶段重跑：

```powershell
python -m video_agent run --case cases\demo --resume <run_id> --from-stage scene --json
python -m video_agent run --case cases\demo --until-stage compile --json
```

## 素材目录

```text
assets/
  sites/                    # 网站主页、功能入口、参数页原始截图
  results/                  # 结果图，中文语义文件名
  references/               # 明确注册的参考图
  brand/                    # Logo、IP、GIF、视频等品牌素材
  workflow_templates/       # 编辑页、弹窗等固定 UI 模板
  derived/
    sites/                  # 固定网站截图派生图
    workflow_scenes/        # 编辑流程等缓存场景素材
    generated/              # Case 预检生成并复用的派生素材
  audio/sfx/                # douyin_common_v1 音效库
  relationships.json        # 参考图、结果图、平面图等严格关系
  catalog.json              # 全局素材索引
```

素材文件进入 `assets/` 前由人工在项目外确认。Catalog 会解析中文文件名、角色、语义路径、方向、尺寸和来源；`machine_checked` 只表示文件可解码等技术检查，不代表系统执行了视觉审核。

重新构建索引：

```powershell
python -m video_agent catalog --assets assets --json
```

## 场景与动效

当前场景契约：

| 场景 | 典型素材 | 默认动效 |
|---|---|---|
| `site_home` | 网站主页 | `paper_curl_flip` |
| `feature_entry` | 功能入口派生图 | `detail_push_in` |
| `parameter_input` | 参数页花字序列 | `scale_in` |
| `result_detail` | 单结果图 | 素材方向自适应展示 |
| `result_gallery` | 词级枚举结果图 | `slide_gallery` |
| `result_gallery_summary` | 多结果总结 | `card_stack` |
| `reference_to_result` | 参考图 -> 结果图 | `before_after` |
| `result_to_flat_plan` | 结果图 -> 平面图 | `before_after` |
| `editor_workspace` | 编辑工作区流程 | `fade_in` + 局部放大镜 |
| `editor_before_after` | 编辑前 -> 编辑后 | `before_after` |
| `light_sweep_fallback` | 最近的相关画面 | `light_sweep` |

场景默认值在 `config/scene_effects.json` 配置。动效自己的最短帧数和可读停留要求定义在 `video_agent/effects.py`，没有全局镜头时长或图片数量上限。

Scene 阶段始终先由 `deepseek-v4-flash` 对完整 Catalog 做无数量上限的语义粗筛，再由 `deepseek-v4-pro` 输出 ActionScene、精确原文起点和素材缺口决策。具体设计类别缺图时可输出 `contextual_result_fill`，从真实结果图派生缺失画面；抽象、误导风险高或没有可信母图的语义才输出 `light_sweep_fallback`。

严格因果场景优先读取 `assets/relationships.json`。关系或可视化素材缺失且 AI 判断可派生时，`prepare_assets` 才会根据当前场景和来源素材调用 GPT Image，并把输出按内容哈希持久化到 `assets/derived/generated/registry.json`，后续运行直接复用。

## 素材制作工具

这些命令生成可复用素材，不属于每次 Case 的生产 DAG：

```powershell
# 功能入口：生成拉近并突出目标入口的缓存关键帧
python -m video_agent site-entry-batch --source assets\sites --json

# 参数页：生成基础帧、花字阶段帧和最终帧
python -m video_agent site-params-sequence --source assets\sites --json

# 编辑流程：把业务结果图装入固定编辑页和局部编辑弹窗
python -m video_agent editor-flow `
  --artwork assets\results\example.png `
  --editor-template assets\workflow_templates\图片编辑\完整编辑页面模板.png `
  --modal-template assets\workflow_templates\图片编辑\局部编辑弹窗模板.png `
  --semantic-path 文生图 `
  --semantic-path 文化墙 `
  --json

# 导入外部人工整理素材
python -m video_agent import-video-materials --source C:\materials --json
```

CDP 截图命名、稳定等待与登录要求见 [CDP 网站截图素材规范](cdp_screenshot_material_spec.md)。

## 音频

- MiniMax 单次合成完整口播，并要求 `subtitle_type=word`。
- 本地 MiniMax 配置决定实际模型、音色和采样参数；Case 可覆盖语速和情感。
- 字幕、镜头 hit 和 SFX 从同一份 `timing_lock.json` 解析。
- `douyin_common_v1` 在 `assets/audio/sfx/catalog.json` 中保存音效哈希、裁切、增益和峰值偏移。
- 音效密度通过 `clean`、`normal`、`energetic` 或 `custom` Profile 配置。
- Remotion 输出静音视频，FFmpeg 负责口播、BGM、SFX 混音和最终编码。

## 其他命令

```powershell
# 注册抖音音效库
python -m video_agent sfx-register --source-dir C:\sfx --json

# 重新生成并前置发布封面；未提供 cover.json 时使用自动规格
python -m video_agent cover-postprocess --case cases\demo --run <run_id> --json

# 汇总全部 Case 的最终视频
python -m video_agent cases-export --cases cases --destination C:\Users\CNGG\Videos --json

# 仅在导出清单存在时清理 Case
python -m video_agent cases-clean --cases cases --export-manifest C:\Users\CNGG\Videos\video_agent_export_manifest.json --json
```

## 模块架构

| 模块 | 职责 |
|---|---|
| `video_agent/orchestrator.py` | 唯一生产 DAG、阶段指纹、Resume 和产物管理 |
| `video_agent/contracts/` | Case、Narration、Timing、ActionScene、VisualPlan、RenderPlan 契约 |
| `video_agent/ai/` | Story Planner、Flash 素材粗筛、Pro ActionScene 规划、GPT Image 客户端和提示词加载 |
| `video_agent/speech/` | MiniMax TTS、词级时间锁和停顿标签编译 |
| `video_agent/assets/` | Catalog、素材导入、网站派生、编辑流程、预检和持久化派生 |
| `video_agent/planning/` | 场景分类、严格素材匹配、参数序列和 VisualPlan 编排 |
| `video_agent/compiler/` | 锚点解析、字幕、证据边界、SFX 与 RenderPlan 编译 |
| `video_agent/render/` | Remotion Props 导出、视频渲染和 FFmpeg 混音 |
| `video_agent/cover.py` / `video_agent/outro.py` | 默认封面和固定片尾后处理 |
| `video_agent/qa/` | 时间锁与编译计划的确定性结构检查 |
| `remotion/src/` | 安全区布局、字幕、场景组件和动效实现 |
| `config/` | 本地 Provider 配置、场景动效和素材预检策略 |

完整设计边界与数据流见 [当前架构说明](docs/architecture.md)。待办项统一维护在 [TODO](TODO.md)，不再保留日期化设计稿。

## 验证

```powershell
python -m compileall -q video_agent
python -m pytest
Set-Location remotion
npx tsc --noEmit
```
