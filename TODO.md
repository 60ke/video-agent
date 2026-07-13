# 主动视觉派生 TODO

## 目标

在声音、字幕和画面卡点准确的前提下，让系统根据口播、Claim、现有素材密度和画面用途，主动使用 GPT Image 衍生必要的视觉素材。

核心原则：声音决定时间，素材决定内容，动画负责在指定帧把内容送到视觉重点。GPT Image 只扩充素材，不拥有修改时间轴的权力。

## 目标链路

```text
原始素材注册
→ 文案与 Claim
→ MiniMax 语音生成
→ 词级 Timing Lock
→ Visual Demand Planner
→ GPT Image 派生素材
→ 自动视觉审核
→ Visual Planner 镜头编排
→ 帧级编译
→ 渲染后音画卡点 QA
```

主动派生必须位于 Timing Lock 之后、Visual Planner 之前。Timing Lock 完成后，音频、字幕、Claim anchor 和视频总帧数均不可因素材生成结果而改变。

## Visual Demand Planner

新增独立的视觉需求规划阶段。它分析每个 Beat 的时间范围、Claim anchor、现有素材和视觉密度，只描述需要补充的视觉状态，不直接编排最终镜头。

建议契约：

```json
{
  "beat_id": "beat_03",
  "start_frame": 182,
  "end_frame": 296,
  "claim_anchors": [
    {"claim_id": "claim_medical", "hit_frame": 228}
  ],
  "source_assets": ["asset_result_001"],
  "visual_density": 3,
  "requests": [
    {
      "derive_kind": "result_detail_focus",
      "source_asset_id": "asset_result_001",
      "purpose": "detail_cutaway",
      "preferred_window": [245, 286]
    }
  ]
}
```

视觉密度规则：

- 小于 1.2 秒：通常只使用一张图。
- 1.2 至 2.5 秒：安排 1 至 2 个视觉状态。
- 2.5 至 4 秒：安排 2 至 3 个视觉状态。
- 超过 4 秒：必须补充派生图、品牌 IP 或其他结果素材。
- 单个有效画面建议保持 0.8 至 2.2 秒。

## 首期派生类型

- `result_detail_focus`：从结果图生成主体更清楚的细节展示。
- `result_vertical_layout`：保持原内容，重排为抖音安全区内的 9:16 展示。
- `reference_to_result`：明确展示参考图与生成图的对应关系。
- `result_collection`：将同功能、同行业的多张结果图组成总览。
- `logo_system_transition`：生成 Logo 到完整 VI 系统的过渡展示。
- `brand_ip_break`：用柯幻熊猫 IP 填充等待、转折或 CTA 段落。
- `text_visual_break`：素材不足时生成简短文字与品牌元素间隔帧。

网站首页、功能入口和参数面板继续使用已经人工审核并缓存的固定派生素材，不在每个 Case 中重复生成。

## 证据边界

- GPT Image 派生图属于 E2 语义素材，不能单独支持事实 Claim。
- Claim 命中帧必须显示 E0 原图或 E1 可信裁切图。
- E2 派生图可以放在 Claim 前后丰富视觉。
- Claim 命中时若使用 E2，必须同时显示对应 E0/E1。
- 参考图和结果图必须有明确角色，不允许把参考图描述为生成结果。
- 所有派生图必须记录 `source_asset_id`、Prompt SHA256、模型、响应 ID 和输出 SHA256。

## 帧级编排

Visual Planner 在派生素材审核通过后再编排最终镜头。镜头必须绑定词级 Anchor：

```json
{
  "start": {"anchor_id": "phrase:填写必填项", "offset_frames": -6},
  "hit": {"anchor_id": "phrase:填写必填项"},
  "end": {"anchor_id": "phrase:开始生成", "offset_frames": -4},
  "asset_id": "asset_derived_xxx",
  "motion": "scale_in",
  "motion_hit_progress": 0.72
}
```

动画可提前进入，但重点状态、字幕关键词和音效峰值必须命中同一个词级 Anchor。

## 降级策略

GPT Image 生成或审核失败时，只允许视觉降级：

```text
审核通过的派生图
→ E1 确定性裁切
→ 原始素材安全区展示
→ 品牌 IP 间隔帧
```

失败不得触发语音重生成、字幕移动、Claim anchor 变化或总时长变化。

## QA

素材审核：

- 原图主体和事实内容保持正确。
- 不出现错误中文、虚构 UI、人物或 Logo。
- 参考图和结果图身份正确。
- 符合 9:16 和抖音安全区。
- 派生结果确实增加视觉价值。

成片审核：

- Claim 命中帧显示支持素材。
- 动画重点在关键词帧到位。
- 字幕与词级时间一致。
- SFX 峰值与视觉 hit 误差不超过 1 帧。
- 单画面没有停留过久。
- 不出现连续 3 秒以上没有有效视觉变化。
- 字幕、标题和重点内容没有进入抖音遮挡区。

## 实施顺序

1. 调整 DAG，使 Timing Lock 位于自动素材派生之前。
2. 新增 `VisualDemandPlan` 和 `DerivedVisualRequest` 契约。
3. 实现规则版 Visual Demand Planner，先保证行为稳定。
4. 实现结果图、对比图和品牌 IP 等首期派生类型。
5. 接入 Vision Critic，审核通过后注册进 Case Catalog。
6. 改造 Visual Planner，围绕词级 Anchor 分配派生素材。
7. 增加渲染后逐帧卡点 QA。
8. 使用文化墙和 VI Golden Case 完整验证。

---

# DeepSeek 全程序化编排 TODO

## 目标

将 DeepSeek 接入 V3 编排链路，让视频从 Case 目标和功能路径出发自动完成文案、Claim、视觉需求、派生素材规划和镜头编排，不再依赖 Codex 或其他 Agent 预先编写业务 JSON。

DeepSeek 负责创意和结构决策，确定性程序负责时间轴、证据、素材状态和渲染约束。任何 AI 输出都不能绕过契约校验直接进入渲染器。

## 当前 AI 边界

当前已经具备：

- `ai_enabled=true` 时通过 OpenAI-compatible 文本模型生成 Narration。
- `visual_planner_mode=multimodal` 时通过多模态模型查看候选素材并生成 Visual Plan。
- `vision_review_enabled=true` 时通过多模态模型审核成片关键帧。
- GPT Image 执行已有 `MaterializationPlan` 中的图片派生请求。
- MiniMax 生成语音和词级时间戳。

当前仍需要人工或外部 Agent 完成：

- 判断哪些 Beat 缺少视觉素材。
- 编写 `materialization.json`。
- 规划 GPT Image 派生类型和来源素材。
- 处理复杂的文案、Claim 与素材关系。
- 根据视觉 QA 结果决定重跑范围。

## Provider 路由

不要把全部 AI 能力绑定到单一 Provider。新增按阶段路由的 Provider 配置：

```json
{
  "providers": {
    "deepseek": {
      "type": "openai_compatible_text",
      "base_url": "https://api.deepseek.com",
      "api_key": "local-only",
      "model": "deepseek-v4-pro"
    },
    "vision": {
      "type": "openai_compatible_vision",
      "base_url": "local-only",
      "api_key": "local-only",
      "model": "vision-model"
    }
  },
  "stages": {
    "narration": "deepseek",
    "visual_demand": "deepseek",
    "materialization_plan": "deepseek",
    "visual_plan": "deepseek",
    "plan_repair": "deepseek",
    "asset_vision": "vision",
    "derived_asset_review": "vision",
    "final_video_review": "vision"
  }
}
```

API Key 继续只保存在本地忽略文件或环境变量中，不提交到 GitHub。Manifest 和 Resume 指纹只记录 Provider、Base URL、模型和配置摘要，不记录 Key。

## DeepSeek 职责

DeepSeek 用于：

- Story/Narration Planner。
- Claim Planner。
- Visual Demand Planner。
- Materialization Planner。
- 基于结构化素材描述的 Visual Planner。
- QA Repair Planner。

视觉模型继续用于：

- 素材图片首次理解。
- GPT Image 派生图审核。
- 成片关键帧与 Contact Sheet 审核。

GPT Image 继续用于图片编辑和派生，MiniMax 继续用于 TTS 和词级时间戳。

## 素材语义缓存

由于文本模型不直接依赖图片输入，素材注册时应由视觉模型生成并缓存结构化描述：

```json
{
  "asset_id": "asset_result_001",
  "role": "result_image",
  "semantic_path": ["文生图", "文化墙", "医疗"],
  "visual_summary": "医院楼梯转角文化墙，粉白色医疗主题",
  "subject": "医疗文化墙",
  "composition": "横屏广角，主体位于左侧墙面",
  "recommended_usage": ["result_showcase", "reference_to_result"],
  "quality": {
    "readable": true,
    "human_approved": true
  }
}
```

视觉描述需要记录生成模型、Prompt SHA256、源素材 SHA256 和审核状态。只有源素材或分析 Prompt 变化时才重新分析，正常 Case 运行直接使用缓存。

## 全程序化执行链路

Case 最小输入：

```json
{
  "goal": "制作文化墙功能种草视频",
  "feature_path": ["文生图", "文化墙"]
}
```

程序自动执行：

```text
1. 筛选同功能素材
2. DeepSeek 生成文案和 Claim
3. MiniMax 生成语音
4. 锁定词级时间轴
5. DeepSeek 分析视觉密度
6. DeepSeek 生成派生请求
7. GPT Image 执行派生
8. 视觉模型审核派生图
9. DeepSeek 根据完整素材池编排镜头
10. 编译器进行帧级校验
11. 渲染视频
12. 视觉模型审核关键帧
13. DeepSeek 根据失败项生成修复计划
14. 只重跑受影响阶段
```

## 卡点约束

DeepSeek 不得输出任意秒数或脱离 Timing Lock 的绝对时间，只能引用已经存在的词级 Anchor，并提供受限的帧偏移：

```json
{
  "start": {
    "anchor_id": "phrase:填写必填项",
    "offset_frames": -6
  },
  "hit": {
    "anchor_id": "phrase:填写必填项"
  },
  "end": {
    "anchor_id": "phrase:开始生成",
    "offset_frames": -4
  }
}
```

确定性编译器继续负责并严格验证：

- Anchor 解析和镜头边界。
- 动画重点命中帧。
- 字幕显示区间。
- SFX 峰值与视觉 hit 的帧级误差。
- Claim anchor 的证据素材覆盖。
- Base Track 从 `timeline_start` 到 `timeline_end` 的连续性。
- 最小镜头时长、抖音安全区和 Overlay 约束。

AI 输出验证失败时先执行有限次数的结构化修复；仍失败则终止当前阶段并保留诊断，不允许编译器猜测或静默修正关键时间。

## 结构化输出

每个 AI 阶段必须绑定独立 Pydantic 契约。优先使用严格 Tool/Function Schema；若 Provider 只支持 JSON Output，则必须执行：

1. JSON 解析。
2. Pydantic 校验。
3. 业务规则校验。
4. 将精确错误反馈给 Repair Planner。
5. 限定重试次数。

禁止直接信任自由文本或只依赖 Prompt 约束。

## Resume 与可追溯性

每个 AI 阶段的输入指纹至少包含：

- 上游产物 SHA256。
- Provider、Base URL 和模型。
- Thinking/Reasoning 配置。
- Prompt SHA256。
- 输出契约版本。
- 素材语义描述版本。
- QA 和修复策略版本。

模型、Prompt、素材描述或上游时间轴变化时，对应阶段及其下游 Resume 必须失效。

## 实施顺序

1. 将 `OpenAICompatibleTextClient` 拆为 Provider 接口和 Stage Router。
2. 新增 DeepSeek Provider、本地配置示例、超时和错误分类。
3. 使用 DeepSeek 接管 Narration，并完成契约校验与重试测试。
4. 建立素材视觉描述契约、缓存和视觉模型分析阶段。
5. 实现 DeepSeek Visual Demand Planner。
6. 实现 DeepSeek Materialization Planner，自动生成派生请求。
7. 将主动派生接入 Timing Lock 之后的新 DAG。
8. 实现基于结构化素材描述的 DeepSeek Visual Planner。
9. 实现视觉 QA 结果到 DeepSeek Repair Plan 的闭环。
10. 使用文化墙和 VI Golden Case 验证全程无需手写 narration、materialization 和 visual plan。
# MiniMax 情感控制

- 暂不在当前生成链路启用 Beat 级 `emotion`。
- 后续建立同一音色、同一文案的情感枚举试听样本，再确定钩子、讲解、枚举和 CTA 的情感策略。
- 情感参数必须通过人工听感验收，并验证分段拼接后不会出现音色、响度或语调突变。
