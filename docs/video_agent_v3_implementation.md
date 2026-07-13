# Video Agent V3 实现说明

> 日期：2026-07-13  
> 状态：V3.1 主链已接入 Timing Lock 后主动补素材、固定画布和离线确定性网站标注

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
- 中文站点/结果素材解析、内容哈希 ID、三级语义路径和 CDP callout 锚点；
- E0-E3 证据分级、父素材 provenance、派生审核闸门；
- 规则式 Visual Demand Planner，按 Beat 时长、Claim anchor 和已审核素材计算视觉状态缺口；
- `result_detail_crop`、`result_vertical_layout` 等确定性 E1 主动派生；
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
- 自动派生请求及建议使用帧窗口。

默认视觉密度：

- `<1.2s`：1 个状态；
- `1.2–2.5s`：2 个状态；
- `2.5–4s`：3 个状态；
- `>4s`：按时长扩展，最多 4 个状态。

规则版自动请求只生成确定性 E1，不调用 GPT Image。Case 中已有的 `materialization_source` 会与自动请求合并，冲突 request ID 直接失败。

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

`asset_review` 检查输出文件、SHA256、尺寸、父素材、派生类型和证据级别。E1 通过后标记为 `machine_checked` 并继承父素材 Claims；E2 保持待视觉审核状态。

## 4. 网站截图与 CDP 坐标

统一规则：

1. CDP 只采集干净截图和结构化归一化坐标；
2. 坐标只进入离线确定性派生工具；
3. `VisualPlan` 和 `RenderPlan` 不保存网页元素坐标；
4. 运行时 Renderer 不根据网页坐标裁切、放大或绘制框线；
5. 网站 UI 不交给 GPT Image 重画。

`site-entry-batch` 使用 Pillow 根据 `click_target` / `panel_box` 生成 1080×1920 底图、透明圈选层和合成关键帧。`site-params-batch` 使用前端源码确认必填字段，再使用 CDP 字段框程序化生成花字、箭头和字段强调层。生成文件仍需清单审批后进入生产素材池。

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
python -m pytest
python -m compileall -q video_agent
python -m video_agent catalog --assets assets --json
```
