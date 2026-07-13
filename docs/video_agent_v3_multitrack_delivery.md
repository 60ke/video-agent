# Video Agent V3 多轨视觉编排交付说明

## 已落地的生产约束

`Narration` 现在包含显式 `Claim`。每个 Claim 指向 E0/E1 的 `supporting_asset_ids`；每个带事实的 Shot 也必须携带同一个 `claim_id` 并实际显示至少一个支持素材。编译器拒绝“文案讲 A、画面放 B”。

`VisualPlan` 的 Shot 不再等同于 Beat。Shot 使用 `start/end TimeRef`（词级 phrase anchor 或 `beat_start/beat_end` 加帧偏移），因此单个 Beat 可以有多个短镜头，一个镜头也可跨多个 Beat。Shot 具备：

- `track`: `base` 或 `overlay`；
- `asset_bindings`: `primary`、`reference`、`result` 等具名素材槽位；
- `transition_in`: `cut`、`crossfade`、`slide_left`、`slide_right`；
- `motion`: 简洁的 fade / scale / 受限 perspective；
- `claim_ids` 和共享词级 Cue。

base 轨必须连续覆盖整个片长。Renderer 会同时绘制前后 base 镜头完成真实 crossfade 或左右滑动；overlay 轨只在自己的时间范围叠加并提供相对 `content_safe` 的布局。`reference_to_result` 可消费参考图与结果图两个具名素材槽位；多图轮播由多个连续 `result_showcase` Shot 表达。

素材坐标不得驱动最终画面。`asset_anchor_id`、RenderAsset 坐标字典以及运行时框选/局部裁切均不属于 V3 渲染契约；视觉重点必须固化在已审核的派生图片中。

## AI 与确定性边界

case 设置 `visual_planner_mode: "multimodal"` 后，Visual Planner 会取得最多 12 张与功能路径有关、状态为 `machine_checked` / `vision_verified` / `human_approved` 的图片及其锚点元数据。它只能提出 `VisualPlan`；不合格的素材、错误 Claim、时间锚点、base 轨间隙/重叠、文字密集页面形变都会在本地编译和 QA 阶段失败。

默认 `auto` 模式仍完全离线。它会根据素材角色拆分足够长的 Beat，并对结果图使用克制的真实转场。

## 音频与交付 QA

`SemanticSfx` 增加 `sync_point` 和 `sync_offset_ms`。默认 UI 音效按照已配置的 peak 偏移提前开始，`AudioTrack.sync_frame` 永远保持视觉命中帧，QA 可以同时验证听觉和视觉共享同一 Cue。

除了 `contact_sheet.jpg`，最终 QA 每 8 个 Cue 生成一页 `cue_contact_sheet_001.jpg`、`cue_contact_sheet_002.jpg` 等，包含每个 Cue 的前 3 帧、命中帧和后约 0.2 秒帧。启用 Vision Critic 时逐页审查并聚合结论。

`--resume` 保留原 run manifest 的 stage / prompt trace，并使用每个阶段的输入和输出 SHA256 决定是否复用。case、语音配置、上游产物、成片或 QA 输入发生变化都会使对应阶段失效。
