# Video Agent V3 实现说明

> 日期：2026-07-14  
> 状态：V3.1 主链已接入 Timing Lock 后主动补素材、固定画布、GPT Image 网站标记关键帧和目标时间窗硬约束

## 1. 唯一运行链

`video_agent.runtime.STAGES` 定义唯一 DAG：

```text
catalog
-> narration
-> speech
-> visual_demand
-> materialize
-> asset_review
-> visual
-> compile
-> render
-> qa
```

`catalog` 只输出当前 Case 的原始/已审核素材快照。`speech` 生成不可变 `TimingLock` 后，`visual_demand` 才根据 Beat 帧范围和素材密度提出补素材请求。后续素材生成或审核失败不得触发 TTS、字幕、Claim anchor 或总帧数变化。

对外入口只有 `python -m video_agent`。每一阶段的输入输出位于同一 `runs/<run_id>/`，可用 `--resume` 和 `--from-stage` 定位重跑。

## 2. 已实现能力

- Pydantic 权威契约和原子 JSON 写入；
- 固定 `douyin_portrait_v1` 画布：1080×1920、30fps；
- 中文站点/结果素材解析、内容哈希 ID、三级语义路径和 CDP 定位信息；
- E0-E3 证据分级、父素材 provenance、派生审核闸门；
- 规则式 Visual Demand Planner，按 Beat 时长、Claim anchor 和已审核素材计算视觉状态缺口；
- `result_detail_crop`、`result_vertical_layout` 等确定性 E1 主动派生；
- 每个主动派生请求携带绝对目标帧窗口，Auto Visual Planner 将窗口作为硬约束；
- 网站功能入口、参数页通过 GPT Image 生成最终 E2 标记关键帧；
- E1 provenance 证据继承：Compiler 可追溯到 Claim 的 E0/E1 支持素材，E2/E3 不可继承；
- MiniMax `speech-2.8-hd`、默认速度 1.3、单次请求真实 `word` 时间戳；
- 仅允许标点差异的严格字序对齐，不存在比例 timing fallback；
- Beat 边界字幕切分、单行 10 单位限制、关键词强调；
- Claim -> supporting asset/E1 descendant -> visible shot 的事实证据闭环；
- 一个 Beat 多 Shot、连续 base 轨和可重叠 overlay 轨，支持真实 crossfade / 左右滑动；
- 视觉/SFX 共用 phrase anchor 或镜头起始 anchor，SFX onset/peak 可提前起播，绝对帧编译；
- 抖音安全区、低对比网格舞台、结果图完整展示；
- 参数表单等文字密集 UI 仅允许等比缩放或淡变，禁止透视和滑页形变；
- 语义 SFX profile、Voice/BGM/SFX 多轨混音和最终 MP4 QA；
- 可选多模态 Visual Planner 与 Contact Sheet Vision Critic；
- `--resume` 记录并校验阶段 input/output SHA256，从首个失效阶段继续。

## 3. 主动补素材

`visual_demand.json` 是 Timing Lock 后的视觉需求计划，包含：

- 每个 Beat 的绝对起止帧；
- Claim 命中帧；
- 所需视觉状态数量；
- 当前可用素材；
- 自动派生请求；
- `preferred_start_frame` / `preferred_end_frame` 目标使用窗口。

默认视觉密度：

- `<1.2s`：1 个状态；
- `1.2–2.5s`：2 个状态；
- `2.5–4s`：3 个状态；
- `>4s`：按时长扩展，最多 4 个状态。

规则版自动密度请求默认生成确定性 E1。Case 中已有的 `materialization_source` 会与自动请求合并，冲突 request ID 直接失败。网站入口和参数页可通过显式 `SITE_HOME_KEYFRAME`、`SITE_FEATURE_ENTRY_KEYFRAME`、`SITE_PARAMS_KEYFRAME` 请求或独立批处理调用 GPT Image。

Materializer 将目标窗口写入派生 Asset metadata。Auto Visual Planner 必须：

1. 在声明的 Beat 内使用该派生素材；
2. 保持声明的绝对起止帧，不得平均重排；
3. 拒绝越界、重叠、未审核或 production-ineligible 的窗口素材；
4. 用普通候选素材填满剩余空档，保证 base 轨连续覆盖；
5. 对 E1 后代沿 provenance 计算 Claim 绑定，使窗口覆盖 Claim anchor 时仍可完成事实验证。

阶段产物：

```text
asset_catalog.source.json
narration.json
timing_lock.json
visual_demand.json
asset_catalog.pending.json
asset_review_report.json
asset_catalog.json
```

`asset_review` 检查输出文件、SHA256、尺寸、父素材、派生类型和证据级别。E1 通过后标记为 `machine_checked` 并继承父素材 Claims；GPT Image E2 保持 `unreviewed`，必须经过人工或 Vision Review 才能进入正式视觉计划。

## 4. 网站截图与 GPT Image 标记

统一规则：

1. CDP 只采集干净截图、目标标签和结构化定位信息；
2. 功能入口和参数页标记通过 GPT Image 生成完整最终关键帧；
3. CDP 坐标与前端源码只用于定位、校验和构造提示词，不用于 Pillow/OpenCV 绘制框线；
4. `VisualPlan` 和 `RenderPlan` 不保存网页元素坐标；
5. 运行时 Renderer 不读取网页坐标，不提取红色像素，不生成透明圈选层，不播放 reveal 动画；
6. 网站标记关键帧属于 E2，不能承担事实 Claim，必须审核后使用。

`site-entry-batch` 将文件名中的功能路径转为 GPT Image 编辑指令，要求镜头拉近并突出唯一目标。`site-params-batch` 使用前端源码和 CDP 采集结果确认必填字段，再让 GPT Image 在完整参数面板上生成花字和箭头。两类生成文件均写入 manifest，人工审批后进入生产素材池。

## 5. 证据继承

事实 Claim 的可见支持素材满足以下任一条件：

- 镜头直接显示 `supporting_asset_ids` 中的素材；
- 镜头显示经过审核的 E1 后代，且 provenance 能追溯到支持素材；
- provenance 的每一层均为白名单保真派生。

E2/E3、未知派生类型、断裂或循环 provenance 均不能支持 Claim。

## 6. Golden Cases

既有案例仍位于：

- `golden_cases/vi_v3`
- `golden_cases/culture_wall_v3`

V3.1 改动不修改 Timing Lock、VisualPlan 绝对锚点语义、RenderPlan 单一渲染事实或最终 MP4 QA。正式回归应重新运行两个 Golden Case，确认新增阶段产物、最终视频和全部硬检查通过。

## 7. 本地配置

`config/minimax.local.json`、`config/gpt_image.local.json`、`config/ai.local.json` 均由 `.gitignore` 排除。仓库只提交 `*.example.json`。

共享音效位于 `assets/audio/sfx/`，唯一 profile 为 `douyin_common_v1`。设为 `"sfx_profile": null` 可关闭共享音效；`sfx_overrides` 可按语义 ID 覆盖路径、增益、最长时长、淡入淡出和优先级。

## 8. 验证

```powershell
python -m ruff check .
python -m pytest
python -m compileall -q video_agent
python -m video_agent catalog --assets assets --json
```
