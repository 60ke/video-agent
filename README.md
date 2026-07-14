# Video Agent V3

素材驱动、词级定时、确定性渲染的 9:16 短视频生产系统。

V3 只有一条正式成片链：

```text
assets catalog
-> claim-bound narration
-> MiniMax speech-2.8-hd (single request, word timing)
-> immutable timing lock
-> visual demand planning
-> controlled materialization + asset review
-> multi-track visual plan + shared semantic cues
-> single render plan
-> Pillow/OpenCV scene renderer
-> FFmpeg video and multi-track audio mix
-> final MP4 QA
```

主动补素材固定发生在 Timing Lock 之后、Visual Plan 之前。素材生成或审核结果只能改变画面选材，不能修改语音、字幕、Claim anchor 或总帧数。

## Quick Start

```powershell
python -m pip install -e ".[dev]"
python -m video_agent catalog --assets assets --json
python -m video_agent init --case cases\demo --case-id demo --goal "VI 功能种草" --feature-path 文生图 --feature-path VI --json
python -m video_agent run --case cases\demo --json
python -m video_agent inspect --case cases\demo --json
```

每次运行写入 `cases/<case>/runs/<run_id>/`。权威产物为：

- `asset_catalog.source.json`
- `narration.json`
- `timing_lock.json`
- `visual_demand.json`
- `asset_catalog.pending.json`
- `asset_review_report.json`
- `asset_catalog.json`
- `visual_plan.json`
- `render_plan.json`
- `run_manifest.json`
- `qa_report.json`
- `final/video.mp4`

`--from-stage`、`--until-stage` 和 `--resume <run_id>` 用于定位重跑，不会创建旁路成片格式。`--resume` 会校验已记录阶段的输入哈希与产物哈希；两者一致才复用，否则从第一个失效阶段重跑。

## Local Keys

密钥只保存在本地并由 `.gitignore` 排除：

- Minimax：`config/minimax.local.json` 或 `MINIMAX_API_KEY`
- GPT Image：`config/gpt_image.local.json` 或 `GPT_IMAGE_API_KEY`
- AI Planner/Critic：`config/ai.local.json` 或 `VIDEO_AGENT_AI_API_KEY`

MiniMax 默认速度为 `1.3`、`subtitle_type=word`。完整文案以换行连接 Beat 后只调用一次 TTS 接口，所有镜头和字幕使用该次请求返回的真实词级时间戳。显式停顿标签仍然关闭。

## Asset Policy

- `assets/sites/`：中文文件名的网站主页、功能入口、参数页干净截图；`_callouts.json` 保存 CDP 采集的结构化定位信息。
- `assets/results/`：按中文功能路径和行业/场景命名的真实结果图。
- `assets/brand/`：品牌 Logo、静态 IP、透明动画和动作视频；作为 CTA/过渡补镜头，不承担功能结果证据。
- `assets/outro/`：共享片尾或品牌素材。
- E0 原始证据和 E1 保真派生可支持事实；E2 语义派生和 E3 装饰素材不能支持事实。每条事实 Claim 必须绑定支持它的素材，并在实际可见镜头中再次验证。
- E1 派生只能来自 E0/E1，必须记录完整 parent provenance；Compiler 可沿经过审核的 E1 provenance 追溯 Claim 支持素材。
- GPT Image 派生默认 `unreviewed`，必须通过人工或 Vision Review 后才能进入正式 Render Plan。
- 网站功能入口和参数页的视觉标记由 GPT Image 生成最终 E2 关键帧；CDP 与前端结构只用于定位、校验和构造提示词，不进入 `VisualPlan`、`RenderPlan`，运行时 Renderer 不读取网页坐标，也不生成独立圈选层动画。
- 正式画布固定为 `douyin_portrait_v1`：1080×1920、30fps。

```powershell
python -m video_agent asset-review --case cases\demo --run <run_id> --asset-id <asset_id> --approve --json
```

## Active Materialization

规则版 `visual_demand` 会根据每个 Beat 的真实帧范围、Claim anchor、现有已审核素材和目标视觉密度生成补素材请求：

- 小于 1.2 秒：1 个视觉状态；
- 1.2–2.5 秒：2 个视觉状态；
- 2.5–4 秒：3 个视觉状态；
- 超过 4 秒：按时长扩展，最多 4 个状态。

首期自动密度补素材生成确定性 E1：`result_detail_crop` 和 `result_vertical_layout`。每个请求携带 `preferred_start_frame` / `preferred_end_frame`，Auto Visual Planner 将其视为硬时间窗：越界、重叠、未审核或无法覆盖 Beat 的素材直接失败，不再退化为平均分配。手工 `materialization.json` 仍可与自动请求合并。

网站入口和参数页通过独立批处理或显式 `SITE_*_KEYFRAME` 请求调用 GPT Image，产出最终 E2 标记素材；这些素材必须审核后才能进入视觉编排。

## Quality Gates

- 一个口播 Beat 可拆为多个镜头；base 轨连续覆盖全片，overlay 轨只承载局部标注或品牌补镜头。
- 普通概括段按可读时间选择最多 3 张代表素材；明确枚举功能时使用 `visual_strategy=enumerated_results`，每个 `hit_phrase` 必须匹配同功能结果图并命中词级 Cue，缺图或时长不足直接失败。
- 主动补出的派生图必须在请求声明的绝对帧窗口内出现；Planner 不得忽略或移动该窗口。
- 网站标记图是 GPT Image 生成并审核后的完整静态关键帧，不从红色像素中提取透明图层，也不在运行时播放手绘圈 reveal 动画。
- 字段操作的视觉、字幕强调和 SFX 共用词级 anchor；SFX 可按 onset 或 peak 提前起播，使听觉峰值落在视觉命中帧。
- 字幕始终单行，每 cue 不超过 10 个全角单位。
- 镜头连续覆盖全时间轴，默认 15–20 秒，超过 60 秒失败。
- 抖音右侧操作栏和底部信息区零碰撞。
- 参数页等文字密集 UI 禁止透视；普通功能片只允许简洁淡变、等比缩放、翻页和短暂后完全回正的透视入场。
- 唯一语义音效 profile 为 `douyin_common_v1`，由 `assets/audio/sfx/catalog.json` 校验哈希与 48kHz/16-bit/stereo 格式，并在运行时应用裁切、peak 对齐、增益和密度限流。
- 品牌 IP 只在评论引导、关注提示、等待生成等语义明确的 Beat 中自动出现；动态素材按镜头局部时间循环播放，忽略素材原音轨。
- 最终音频归一到约 `-16 LUFS / -1.5 dBTP` 并在 MP4 上复测。
- 最终 QA 检查真实 MP4，不以中间 JSON 成功代替交付成功；除总联系表外还会输出 Cue 前/命中/后的动态证据联系表。

将 case 的 `visual_planner_mode` 设为 `"multimodal"`，可让 AI 直接查看经审核的功能截图与结果图，提出多镜头视觉计划；本地编译器仍会严格校验锚点、轨道连续性、素材审核状态与 Claim 证据。

## Cover Postprocess

发布封面独立于口播、视觉编排和 RenderPlan。主体视频通过正常 QA 后，在 case 中创建 `input/cover.json`：

```json
{
  "title": "AI文化墙怎么做",
  "subtitle_hint": "上传描述，一键生成多套方案",
  "style_hint": "short_video_feature_seed",
  "reference_asset_ids": [],
  "max_references": 3
}
```

执行封面生成与单帧前置：

```powershell
python -m video_agent cover-postprocess --case cases\<case> --run <run_id>
```

产物包括 `final/cover.png`、`final/cover_3x4_preview.png` 和 `cover_report.json`。无封面主体保存在 `work/cover/video_without_cover.mp4`；重复执行会替换已有封面，不会累计增加帧数。

## Documentation

- [V3 终极设计](docs/video_agent_v3_final_design.md)
- [V3 实现说明](docs/video_agent_v3_implementation.md)
- [CDP 素材采集](cdp-capture/README.md)

## Tests

```powershell
python -m ruff check .
python -m pytest
python -m compileall -q video_agent
```

可复现案例位于 `golden_cases/vi_v3` 和 `golden_cases/culture_wall_v3`。运行产物被忽略，case、口播和素材均随仓库保存。
