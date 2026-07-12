# Video Agent V3 当前架构审查

> 审查日期：2026-07-12  
> 审查基线：`master` / `b71e3ce8ca8fb2255dee1ce18cf433dd7a57a0bc`  
> 结论：V3 的确定性生产主干方向正确，但视觉层仍停留在“一个口播 Beat 对应一张图和一个入场效果”的 MVP。后续最优先要解决的是 Beat、Shot 和单张 Asset 的强绑定，否则多图轮播、左右切换、前后对比和 AI 视觉编排都会继续演变为特殊分支。

---

## 1. 总体判断

当前值得保留的架构基础：

- 单一 Orchestrator 和唯一阶段链；
- Pydantic 权威契约；
- Minimax 词级时间锁；
- Visual Plan 编译成唯一 Render Plan；
- E0-E3 证据分级；
- 最终 MP4 统一 QA；
- 提示词外置并记录 SHA256；
- Python 场景图 + FFmpeg 确定性渲染。

当前代码更准确的定位是：

> 已完成 V3 的确定性生产骨架，但视觉时间模型、多素材镜头模型和 AI 视觉理解尚未完成。

---

# 2. 主要问题

## 2.1 口播 Beat 和镜头被强制绑定为 1:1

当前自动视觉规划器对每个 narration beat 只生成一个 `ShotPlan`：

- `video_agent/planning/auto_visual.py`
- `build_auto_visual_plan()`

编译器又直接把该镜头的起止时间设置为整个 Beat 的起止时间：

- `video_agent/compiler/render_plan.py`
- `start_frame=span.start_frame`
- `end_frame=span.end_frame`

这会限制：

- 一个 Beat 内依次展示入口、参数和结果；
- 一句话内快速切换多张结果图；
- 实景图到生成效果；
- 编辑前、操作、编辑后；
- 同一页面按多个关键词连续聚焦；
- 一句话中插入品牌 IP 过渡。

虽然 `ShotPlan.asset_ids` 是列表，但渲染器只使用第一张素材：

```python
asset_id = shot.asset_ids[0]
```

因此当前数据契约看似支持多素材镜头，运行时实际上不支持。

### 建议

改为：

```text
Narration Beat 1 : N Visual Shot
```

镜头拥有独立的视觉时间范围，例如：

```json
{
  "shot_id": "shot_003",
  "beat_id": "beat_002",
  "start_anchor": "anchor_现场图",
  "end_anchor": "anchor_生成效果",
  "template": "reference_to_result",
  "asset_slots": {
    "reference": "asset_x",
    "result": "asset_y"
  }
}
```

一个 Beat 可以编译出多个 Shot；一个 Shot 也可以覆盖多个很短的 Beat。

---

## 2.2 当前没有真正的 AI 视觉编排

目前 AI 只负责生成 Narration，输入主要是：

- `asset_id`
- `semantic_path`
- `role`
- `claims`
- `tags`
- anchor 名称

AI 没有直接看到素材图片。

后续 Visual Plan 由 `_asset_for_beat()` 的关键词规则生成，大致逻辑是：

```text
出现“参数” -> 参数页面
出现“入口” -> 功能入口
其他情况 -> 结果图
```

结果镜头效果则在：

```text
scale_in
crossfade
page_slide
```

之间循环。

因此当前系统不能主动判断：

- 哪两张图是编辑前后；
- 哪张是实景输入，哪张是结果；
- 哪几张图属于同一生成任务；
- 哪些图适合轮播；
- 哪些图适合擦拭或滑块对比；
- 哪些素材可以组成“输入到输出”；
- 哪个视觉方案对当前文案最有冲击力。

### 建议

保留当前规则规划器作为 fallback，正式路径增加一次联合多模态调用：

```text
素材图片 + 素材元数据
-> AI 识别素材角色和关系
-> AI 提出候选 Visual Plan
-> 确定性代码检查时间、证据和模板可执行性
```

不需要拆成十几个 Agent，一个联合的 `StoryVisualPlanner` 即可。

---

## 2.3 证据模型存在，但没有贯穿到文案和镜头

当前 E0-E3 分类合理：

- E0：原始证据；
- E1：保真派生；
- E2：语义派生；
- E3：装饰素材。

并且 E2/E3 禁止携带 factual claims。

但实际规划链仍存在断层：

1. Story Planner 的提示词要求不把 E2/E3 当作产品证据；
2. 传给模型的材料数据却没有 `evidence_class` 和 `quality.status`；
3. 只要素材不是 `rejected` 就会进入 AI 上下文，包括 `unreviewed`；
4. `NarrationBeat` 虽有 `claim_ids`，后续 Visual Plan、Compiler 和 QA 没有验证当前镜头是否真的使用了支持该 claim 的 E0/E1 素材。

### 建议增加最小闭环

```text
Claim
├── claim_id
├── text
├── supporting_asset_ids
└── required_evidence_class
```

每个 Shot 显式绑定：

```json
{
  "claim_ids": ["claim_003"],
  "asset_ids": ["asset_result_x"]
}
```

编译阶段强制检查：

```text
每个 factual claim
-> 至少绑定一个当前镜头实际使用的 E0/E1 素材
```

否则当前证据分级更多只是资产属性，还不是成片事实安全机制。

---

## 2.4 镜头模板和特效仍然是硬编码分支

当前 Effect 白名单定义在 Compiler 中，Planner 输出字符串，Renderer 通过 `if/elif` 执行。

增加一个效果通常要修改：

- Planner；
- Effect allowlist；
- Compiler；
- Renderer；
- QA；
- Tests。

并且当前部分命名与真实行为不一致：

- `crossfade` 实际只是当前图片从背景淡入；
- `page_slide` 实际只是当前图片从右侧入场；
- 没有同时渲染前一张和后一张；
- 因此并不是真正的图片交叉淡化或左右切换。

这意味着当前只有“单画面入场效果”，没有真正的“双画面转场”。

### 建议

引入注册表：

```python
TemplateRegistry.register("image_carousel", ImageCarouselTemplate)
EffectRegistry.register("swipe_left", SwipeLeftTransition)
```

转场接口至少应支持：

```python
render(
    previous_frame,
    current_frame,
    local_frame,
    duration_frames,
    parameters,
)
```

这样才能自然支持：

- 左右滑动；
- 前后画面同时移动；
- 擦拭对比；
- 多图轮播；
- 卡片堆叠；
- 真正的交叉淡化。

---

## 2.5 `--resume` 不是真正的断点恢复

当前 `--resume` 只是打开已有 run 目录，并重新创建一个新的 Orchestrator。

Orchestrator 初始化时又重新构造空的：

```json
{
  "status": "running",
  "stages": {},
  "prompts": []
}
```

因此恢复运行会：

- 丢失原来的 stage 记录；
- 丢失原来的 prompt trace；
- 不会自动定位上次失败阶段；
- 不检查上游产物是否仍与当前输入匹配；
- 不验证 `case.json` 是否已经变化。

### 建议

恢复时先加载现有 `run_manifest.json`，每个阶段记录：

```text
input_hash
output_hash
status
started_at
completed_at
```

然后自动从第一个：

```text
missing / failed / input_hash_changed
```

的阶段继续。

当前 `--resume` 更接近“在原目录中手动重跑”，命名会让使用者误解。

---

## 2.6 当前实现基本绑定 Windows

当前 Renderer 只检查 Windows 字体路径：

```text
C:/Windows/Fonts/msyhbd.ttc
C:/Windows/Fonts/NotoSansSC-VF.ttf
C:/Windows/Fonts/simhei.ttf
```

找不到就直接失败。

CI 也只运行 `windows-latest`，最终响度检测使用 Windows 的 `NUL`。

如果后续在 Linux 服务器运行，这会直接阻塞。

### 最低限度调整

- 字体路径进入配置；
- 支持 `fc-match` 查找系统字体；
- 默认尝试 Noto Sans CJK；
- 使用 `os.devnull` 替代 `NUL`；
- CI 增加 Ubuntu；
- Windows 和 Ubuntu 各跑一次 FrameRenderer 与 FFmpeg smoke test。

---

## 2.7 音效只对齐文件开始，没有对齐听觉峰值

当前 `SemanticSfx` 支持：

- `trim_start_ms`
- `max_duration_ms`
- fade
- gain

但没有：

```text
onset_ms
peak_ms
sync_point
```

Compiler 直接把视觉 `hit_frame` 设置为 SFX 的 `start_frame`。

这对 swish 勉强合理，因为通常应对齐声音起点；但对以下音效并不准确：

- 点击；
- Pop；
- Impact；
- 结果落定。

这些音效通常应让声音峰值对齐视觉落点，而不是让音频文件起点对齐落点。

### 建议

```json
{
  "path": "swish.wav",
  "sync_point": "onset",
  "sync_offset_ms": 34
}
```

或：

```json
{
  "onset_ms": 18,
  "peak_ms": 126,
  "tail_ms": 430
}
```

编译时：

```text
音频开始时间 = 视觉 hit 时间 - peak_ms
```

---

# 3. 次要问题

## 3.1 分辨率表面可配置，实际只能使用 1080x1920

`CaseConfig` 允许配置任意 width、height 和 fps，但当前只有一个固定的 `douyin_portrait_v1`，Renderer 发现尺寸不一致就会失败。

建议二选一：

1. 当前阶段直接把 Case Contract 限制为 1080x1920；
2. 或将 Platform Profile 改成归一化坐标并在运行时缩放。

现在属于“配置项表面可用，运行时不可用”。

---

## 3.2 最终 Vision QA 只能看到静态 Contact Sheet

当前最多抽取 16 个关键帧组成 4x4 联系表。

它可以检查：

- 构图；
- 字幕位置；
- 结果图完整性；
- UI 高亮是否大致正确。

但不能可靠检查：

- 左右滑动是否顺畅；
- 转场方向是否正确；
- 是否闪帧；
- 动画峰值是否过快；
- 音效是否卡点；
- 某个问题的准确 frame。

### 建议

对关键 Cue 额外输出：

```text
Cue 前 3 帧
Cue 命中帧
Cue 后 3/6/12 帧
```

或者生成若干 0.5-1 秒的小视频片段给视觉模型审查。

---

## 3.3 提示词外置只完成了一半

Story Planner 和 Visual Critic 已经使用外部 Markdown，并保存 SHA256，这个方向正确。

但派生图片提示词仍硬编码在：

- `video_agent/assets/materializer.py`

考虑到后续希望通过提示词持续优化视觉和审美，建议将 `_prompt()` 中的内容移到：

```text
video_agent/prompts/materialization/
```

当前不需要建设复杂 Prompt Registry，只需统一读取 Markdown 文件即可。

---

# 4. 建议保留的部分

以下主干不建议推翻：

```text
Orchestrator
-> Timing Lock
-> Visual Plan
-> Render Plan
-> Renderer
-> Final QA
```

尤其值得保留：

- `timing_lock.json` 只保存音频、token、phrase anchor 和 beat span；
- 视觉动作只存在于 Visual Plan；
- Render Plan 负责绝对帧编译；
- word timing 严格匹配，不做按时长比例 fallback；
- Pydantic 使用 `extra="forbid"` 和 `validate_assignment=True`；
- AI 提示词记录路径和 SHA256；
- 最终只对实际 MP4 做交付 QA。

---

# 5. 建议修改优先级

## P0：先修视觉时间模型

```text
Beat 与 Shot 解耦
多 Shot / Beat
多 Asset / Shot
真实 Transition Compositor
```

这是多图轮播、左右切换、前后对比和动态视觉编排的基础。

## P1：增加最小 AI 视觉层

```text
多模态素材理解
素材角色和关系
候选 Visual Plan
规则和时间预算校验
```

当前不需要拆成多个 Agent，一个联合 Planner 足够。

## P2：补齐可靠性

```text
Claim 证据绑定
真正的 resume
Linux 支持
SFX onset/peak 对齐
动态 QA
```

---

# 6. 最终结论

当前 V3 主干合理，已经比旧流水线清晰很多，不需要推翻重做。

但 Visual Plan 仍然过于接近：

```text
一段口播
-> 一张图片
-> 一个入场效果
```

下一步最先应该修改的不是继续增加更多特效，而是解除：

```text
Beat
Shot
单张 Asset
```

之间的强绑定。

否则未来增加：

- 多图轮播；
- 左右切换；
- 编辑前后；
- 实景到效果；
- 输入到输出；
- AI 多素材编排；

都会继续变成新的硬编码特殊分支。
