# Video Agent V3 设计方案

> 版本：V3  
> 目标：不考虑 V2 兼容性，以最终成片效果为唯一标准，重点解决卡点准确、素材与叙事匹配、特效丰富且可动态插入、画面鲜活、结果可复现、最终成片可验证。  
> 核心技术路线：**Python 控制平面 + Python 场景图渲染器 + Minimax word timing + FFmpeg 编码与多轨混音**。  
> 说明：本方案综合 `docs/video_pipeline_architecture_review_20260710.md`、`docs/gpt_image_derived_assets_todo.md` 以及当前仓库实现重新设计，不延续 `video_project.json -> video_project.gpt_image.json -> video_project.effects.json` 的 V2 派生链。

---

## 1. 设计结论

V3 不再是若干脚本串联的“图片视频生成流程”，而是一个真正的**视频编译系统**：

```text
真实素材与结果
  ↓
统一资产目录
  ↓
视觉策略规划
  ↓
派生资产任务编译与执行
  ↓
锁定视觉计划
  ↓
基于视觉计划生成口播
  ↓
Minimax 生成语音与 word timing
  ↓
语义 Cue 编译
  ↓
镜头模板与特效编排
  ↓
唯一 render_plan.json
  ↓
Python 场景图逐帧渲染
  ↓
FFmpeg 多轨混音、字幕、片尾与编码
  ↓
最终成片 QA
  ↓
交付
```

V3 的四个基础能力是：

```text
正确的素材
+ 精确的语义 Cue
+ 可组合的镜头模板
+ 最终成片级 QA
```

丰富特效必须建立在这四项能力之上。否则特效越多，越容易把素材错位、时间轴不准和证据不可信的问题放大。

---

## 2. V3 与当前系统的根本区别

### 2.1 删除多份派生项目文件

V3 删除：

```text
video_project.json
video_project.gpt_image.json
video_project.effects.json
```

不再让不同脚本反复修改同一个项目结构，也不再根据“哪个文件存在”决定下一步输入。

最终渲染只接受一份：

```text
render_plan.json
```

### 2.2 删除基础版与特效版双轨交付

当前基础流水线和特效流水线分离，可能出现基础版通过 QA、正式特效版没有重新 QA 的问题。

V3 只有一个生产入口：

```bash
video-agent run --case <case-dir> --mode strict
```

所有关键帧、派生素材、特效、字幕、BGM、SFX、片尾和封面都进入同一条 DAG，QA 只针对最终交付文件执行。

### 2.3 不再让 GPT Image 重绘网站 UI

网站 UI 采用：

```text
CDP 原始截图
+ DOM/视觉锚点
+ 确定性构图变换
+ 程序化高亮、光标、波纹、标签
+ 可选纯装饰背景
```

网站截图和结果图主体始终保留原始像素。GPT Image 只用于明确允许创造或重构的派生任务和装饰任务。

### 2.4 不再按素材类别硬套特效

V3 中 Planner 不选择 `drop_bounce`、`wipe_reveal` 这类底层 effect，而是选择镜头模板：

```text
ui_menu_click
ui_params_walkthrough
ui_perspective_push_in
concept_logo_to_vi_reveal
result_carousel
```

特效只是镜头模板内部的实现细节。

---

## 3. 核心架构

V3 分为六个领域层。

```text
┌─────────────────────────────────────┐
│ 1. Asset System                     │
│ 素材、证据、锚点、派生关系、质量状态 │
├─────────────────────────────────────┤
│ 2. Planning System                  │
│ 故事结构、素材策略、镜头模板、口播    │
├─────────────────────────────────────┤
│ 3. Speech & Cue System              │
│ Minimax word timing、短语映射、帧编译 │
├─────────────────────────────────────┤
│ 4. Render Plan Compiler             │
│ 镜头、节点、关键帧、特效、音频 Cue    │
├─────────────────────────────────────┤
│ 5. Python Scene Graph Renderer      │
│ 逐帧场景图、透视、遮罩、粒子、合成    │
├─────────────────────────────────────┤
│ 6. Final QA & Delivery              │
│ 时间、保真、构图、动效、视觉、交付门禁 │
└─────────────────────────────────────┘
```

---

## 4. 正式数据产物

V3 只保留七个正式契约。

### 4.1 `case.json`

描述用户目标和全局约束。

```json
{
  "schema_version": 3,
  "case_id": "vi_seed_001",
  "video_type": "single_feature_seed",
  "feature_path": ["文生图", "VI"],
  "platform": "douyin",
  "canvas": {
    "width": 1080,
    "height": 1920,
    "fps": 30
  },
  "duration": {
    "target_seconds": 18,
    "max_seconds": 24
  },
  "style_pack": "tech_product_demo",
  "voice_profile": "energetic_seed",
  "delivery": {
    "with_cover": true,
    "with_outro": true
  }
}
```

### 4.2 `asset_catalog.json`

唯一素材目录，替代：

```text
asset_manifest.json
image_resources.json
material_understanding.json
```

建议结构：

```json
{
  "schema_version": 3,
  "assets": [
    {
      "id": "asset_vi_bankexingqiu_result",
      "kind": "result_image",
      "source": "assets/results/半克星球_VI.png",
      "feature_path": ["文生图", "VI"],
      "identity_group_id": "brand_bankexingqiu",
      "facet": {
        "kind": "brand_case",
        "label": "半克星球"
      },
      "evidence": {
        "type": "real_generated_result",
        "allowed_claims": [
          "该品牌存在完整 VI 结果"
        ],
        "forbidden_claims": []
      },
      "anchors": [],
      "quality": {
        "state": "vision_verified",
        "checks": [
          "image_readable",
          "brand_visible",
          "no_private_info"
        ]
      },
      "provenance": {
        "sha256": "...",
        "receipt_id": "receipt_xxx",
        "created_by": "registered_result"
      }
    }
  ]
}
```

### 4.3 `visual_plan.json`

视觉计划只描述：

- 每个 beat 的叙事目标；
- 使用的镜头模板；
- 素材槽位；
- 可说与不可说事实；
- 派生资产需求；
- 语义动作意图。

```json
{
  "schema_version": 3,
  "status": "locked",
  "beats": [
    {
      "id": "beat_logo_to_vi",
      "purpose": "展示一个 LOGO 延展成整套 VI",
      "shot_template": "concept_logo_to_vi_reveal",
      "asset_slots": {
        "logo": "asset_derived_logo_bankexingqiu",
        "vi_board": "asset_vi_bankexingqiu_result"
      },
      "allowed_claims": [
        "从一个 LOGO 延展为完整 VI"
      ],
      "cue_intents": [
        {
          "role": "logo_intro",
          "action": "logo.enter"
        },
        {
          "role": "vi_expand",
          "action": "vi.reveal"
        }
      ]
    }
  ]
}
```

### 4.4 `narration.json`

口播只通过 `visual_beat_id` 引用视觉计划，不重复素材字段。

```json
{
  "schema_version": 3,
  "visual_plan_sha256": "...",
  "prosody_profile": "energetic_seed",
  "segments": [
    {
      "id": "seg_001",
      "visual_beat_id": "beat_logo_to_vi",
      "text": "一个简单 LOGO，直接延展成整套 VI。",
      "emphasis_cues": [
        {
          "phrase": "一个简单 LOGO",
          "action": "logo.enter",
          "lead_ms": 100
        },
        {
          "phrase": "延展成整套 VI",
          "action": "vi.reveal",
          "lead_ms": 80
        }
      ]
    }
  ]
}
```

### 4.5 `render_plan.json`

由程序编译生成，所有时间都量化为绝对帧。

```json
{
  "schema_version": 3,
  "fps": 30,
  "duration_frames": 540,
  "shots": [
    {
      "id": "shot_001",
      "start_frame": 0,
      "end_frame": 92,
      "template": "concept_logo_to_vi_reveal",
      "asset_slots": {
        "logo": "asset_derived_logo_bankexingqiu",
        "vi_board": "asset_vi_bankexingqiu_result"
      },
      "cues": [
        {
          "frame": 2,
          "action": "logo.enter"
        },
        {
          "frame": 39,
          "action": "vi.reveal"
        },
        {
          "frame": 48,
          "action": "sfx.whoosh"
        },
        {
          "frame": 76,
          "action": "camera.settle"
        }
      ]
    }
  ]
}
```

渲染器不再接受模糊自然语言，只执行确定的镜头、节点、关键帧与 Cue。

### 4.6 `run_manifest.json`

记录完整可追溯信息：

- 输入 hash；
- Git commit；
- Python、Pillow、OpenCV、FFmpeg 版本；
- 字体名称和 hash；
- Minimax 模型与参数；
- GPT Image 模型与 prompt hash；
- 所有素材 hash；
- Render Plan hash；
- 各阶段耗时和成本；
- 缓存命中；
- 重试记录；
- 最终输出文件。

### 4.7 `qa_report.json`

只针对最终交付文件，记录：

- 时间轴 QA；
- 素材保真 QA；
- 构图 QA；
- 动效 QA；
- 音频 QA；
- Vision QA；
- 最终交付状态。

---

## 5. 资产信任体系

素材统一分为三类。

### 5.1 Evidence Asset

真实证据素材：

- CDP 原始截图；
- 保存下来的真实结果图；
- 原图确定性裁切；
- 原图抠图；
- 原图蒙版组合；
- 原图透视、缩放和位移。

可以支持事实声明。

### 5.2 Semantic Derivative

语义派生素材：

- LOGO 抽离；
- 产品或人物主体抠图；
- 从结果板中拆出的组件；
- 背景清理；
- 基于原图重构的概念画面。

只继承明确允许的证据能力。

```json
{
  "evidence_inheritance": {
    "inherits": ["brand_identity"],
    "does_not_inherit": [
      "full_result",
      "generation_process",
      "exact_layout"
    ]
  }
}
```

### 5.3 Decorative Asset

纯装饰：

- 网格背景；
- 粒子；
- 渐变；
- 光效；
- 速度线；
- 封面背景；
- 特效纹理。

不支持任何事实声明。

---

## 6. 派生资产系统

派生资产不是 GPT Image 的附属功能，而是一个独立的 `Derived Asset Compiler`。

### 6.1 派生请求

Planner 只声明语义任务，不直接写模型 prompt。

```json
{
  "id": "derive_logo_001",
  "kind": "logo_isolate",
  "source_asset_ids": [
    "asset_vi_bankexingqiu_result"
  ],
  "purpose": {
    "visual_beat_id": "beat_logo_to_vi",
    "narrative_claim": "一个简单 LOGO"
  },
  "constraints": {
    "preserve_geometry": true,
    "preserve_text_exactly": true,
    "transparent_background": true,
    "no_new_elements": true
  }
}
```

### 6.2 首批派生类型

#### `logo_isolate`

输入：VI 结果板。  
输出：透明底或纯色底 LOGO 单体。

执行策略：

```text
显式 anchor 裁切
→ 分割/抠图
→ Alpha 清理
→ OCR/视觉相似度检查
→ 必要时 GPT Image 只修复边缘
```

GPT Image 是 fallback，不是默认 extractor。

#### `subject_cutout`

输入：人物、产品、图形主体。  
输出：透明底主体。

```text
SAM/抠图模型
→ 边缘优化
→ Alpha QA
```

#### `background_clean`

输入：带复杂背景的结果图。  
输出：主体保留、背景清理版本。

#### `background_extend`

输入：原图主体。  
输出：适配竖屏的扩展背景。

规则：

```text
原主体锁定
→ 仅生成外部背景
→ 主体原像素重新覆盖
```

#### `concept_reconstruct`

只允许用于非证据概念镜头。

必须标记为：

```text
semantic_derivative
```

并强制经过 Vision QA。

### 6.3 派生质量状态

禁止 API 成功后自动标记已验证。

```text
requested
generated
machine_checked
vision_verified
human_approved
rejected
```

只有 `vision_verified` 或 `human_approved` 才能进入正式 Visual Plan。

### 6.4 派生资产记录

```json
{
  "id": "asset_derived_logo_bankexingqiu",
  "kind": "semantic_derivative",
  "derive_kind": "logo_isolate",
  "derived_from": [
    "asset_vi_bankexingqiu_result"
  ],
  "identity_group_id": "brand_bankexingqiu",
  "provenance": {
    "recipe_id": "derive_logo_001",
    "tool": "segmentation_then_cleanup",
    "model": "...",
    "prompt_hash": "...",
    "source_sha256": "..."
  },
  "quality": {
    "state": "vision_verified",
    "checks": {
      "brand_match": true,
      "text_match": true,
      "alpha_valid": true
    }
  },
  "evidence_inheritance": {
    "inherits": ["brand_identity"],
    "does_not_inherit": ["full_vi_result"]
  }
}
```


---

## 7. 视觉规划系统

V3 的视觉规划分为四个角色。

### 7.1 Story Director

决定整体叙事结构。

VI 种草片应优先：

```text
LOGO 单体
→ LOGO 延展为 VI
→ 一键生成机制
→ 多品牌真实结果
→ 总结/CTA
```

而不是固定：

```text
首页
→ 功能入口
→ 参数页
→ 结果
```

### 7.2 Asset Director

负责：

- 从现有素材中选材；
- 判断是否需要派生素材；
- 检查品牌前后统一；
- 检查真实证据是否足够；
- 为镜头模板填充素材槽位；
- 判断多图是否需要逐图绑定。

### 7.3 Shot Director

选择镜头模板，不直接选择底层 effect。

### 7.4 Narration Director

只在 Visual Plan 锁定后写口播。

这样可以彻底避免：

```text
visual_intent = LOGO 延展
locked_asset_ids = 首页截图
```

### 7.5 规划两阶段

由于派生素材在第一次规划时可能尚不存在，视觉规划分为：

```text
visual_strategy_draft
→ derived_asset_requests
→ 派生资产生成与验证
→ visual_plan.locked
```

只有锁定后的 Visual Plan 才能进入口播生成。

---

## 8. Minimax word timing 与语义 Cue 编译

### 8.1 基本判断

当前 Minimax 已经能返回 word 级语音时间段。V3 不需要重新估算词时间，也不需要额外 ASR 才能完成卡点。

V3 的任务是：

```text
Minimax 原始 word timing
+ narration 中的 emphasis_cues
→ 短语到 word token 的映射
→ 帧级 Cue
```

### 8.2 编译流程

```text
Narration 文本
+ Minimax word timing
+ emphasis_cues
        ↓
文本规范化
        ↓
Token 级短语匹配
        ↓
置信度与歧义检查
        ↓
lead_ms / offset_ms
        ↓
最小可读时长约束
        ↓
镜头冲突求解
        ↓
30fps 帧量化
        ↓
Compiled Cue
```

### 8.3 为什么仍需要 Phrase Matcher

即使 Minimax 已提供 word timing，仍需处理：

- 中文标点差异；
- 英文大小写；
- `LOGO`、`VI` 等字母拆分；
- 数字与单位；
- 同一句中重复短语；
- TTS 返回 token 与原文分词差异；
- 强调短语跨多个 word token。

Phrase Matcher 不是重新做语音识别，而是把语义短语映射到已有 word timing。

### 8.4 Cue 类型

#### 场景

```text
scene.enter
scene.exit
scene.cut
scene.crossfade
```

#### 素材

```text
asset.show
asset.hide
asset.switch
asset.reveal
asset.expand
asset.stack
```

#### 镜头

```text
camera.push
camera.pull
camera.hit
camera.pan
camera.tilt
camera.settle
camera.shake
```

#### UI

```text
cursor.move
cursor.click
callout.show
callout.pulse
field.focus
panel.scan
```

#### 特效

```text
mask.wipe
glow.flash
particle.burst
tile.assemble
line.trace
scan.sweep
blur.focus
parallax.shift
```

#### 音频

```text
sfx.click
sfx.whoosh
sfx.hit
sfx.pop
bgm.duck
```

### 8.5 强制门槛

- 关键词短语到视觉 Cue 的时间误差不超过 1 帧；
- Cue 歧义不得继续渲染；
- 每个镜头必须有稳定尾帧；
- UI 镜头稳定可读时长至少 1.2 秒；
- 结果图普通可读时长至少 0.75 秒；
- 正式模式禁止任何按字符比例估算卡点；
- 原始 word timing 必须完整存档。

---

## 9. Python 场景图渲染器

### 9.1 技术路线

V3 不引入 Remotion，采用：

```text
Python
+ Pillow
+ NumPy
+ OpenCV
+ 可选 Skia
+ 可选 ModernGL
+ FFmpeg
```

原因：

- 当前 AI、素材、CV、QA 链路已经是 Python；
- 当前透视拉近已经证明 Python 可以完成高质量特效；
- 大量需求本质是图片处理、锚点变换、mask、透视和保真 QA；
- 引入 TypeScript/Chromium 会增加两套运行时和调试链；
- AI 已显著降低单个特效复刻成本；
- 真正需要建设的是场景图与模板系统，而不是更换语言。

### 9.2 场景图结构

```text
Scene
├── BackgroundNode
├── ImageNode
├── GroupNode
├── MaskNode
├── ShapeNode
├── TextNode
├── CursorNode
├── CalloutNode
├── ParticleNode
├── VideoNode
└── SubtitleProtectedRegion
```

### 9.3 节点属性

```text
position
scale
rotation
perspective_quad
opacity
blur
shadow
mask
crop
z_index
blend_mode
```

### 9.4 关键帧

```json
{
  "property": "scale",
  "keyframes": [
    {
      "frame": 0,
      "value": 0.72,
      "ease": "outCubic"
    },
    {
      "frame": 28,
      "value": 1.06,
      "ease": "outExpo"
    },
    {
      "frame": 42,
      "value": 1.0,
      "ease": "inOutSine"
    }
  ]
}
```

### 9.5 Scene API 草案

```python
class Scene:
    id: str
    duration_frames: int
    nodes: list["Node"]


class Node:
    id: str
    z_index: int
    visible_range: tuple[int, int]
    transform: "AnimatedTransform"
    opacity: "AnimatedValue"
    mask: "Mask | None"

    def render(self, context: "FrameContext") -> "FrameLayer":
        ...


class FrameContext:
    frame: int
    fps: int
    width: int
    height: int
    assets: "AssetResolver"
    cues: list["CompiledCue"]
    style: "StylePack"
```

### 9.6 渲染后端

第一阶段：

```text
Pillow + NumPy + OpenCV
```

后续根据性能增加：

```text
Skia Backend
ModernGL Backend
```

上层 Scene、Render Plan 和 Shot Template 不变。

---

## 10. Primitive、Effect Recipe 与 Shot Template

V3 必须区分三个层级。

### 10.1 Primitive

底层能力：

```text
translate
scale
rotate
perspective
opacity
mask
blur
shadow
glow
spring
bounce
motion_blur
particle
scanline
gradient
cursor
callout
text_reveal
```

### 10.2 Effect Recipe

特效配方：

```text
soft_pop
camera_hit
neon_scan
tile_assemble
radial_reveal
perspective_push
card_stack
light_sweep
module_expand_reveal
```

### 10.3 Shot Template

镜头语言，组合：

```text
素材槽位
+ Primitive
+ Effect Recipe
+ Cue
+ Style Pack
```

Planner 只选择 Shot Template 和语义动作，不直接拼底层参数。

---

## 11. 首批镜头模板

第一版建议实现 12 个模板。

### 11.1 UI 类

#### `ui_overview_focus`

适用：首页。

流程：

```text
全局建立
→ 目标入口聚光
→ 轻微推近
→ 稳定阅读
```

#### `ui_menu_click`

适用：功能入口、二级菜单。

流程：

```text
光标移动
→ 目标高亮
→ 点击波纹
→ 切入下一镜
```

#### `ui_params_walkthrough`

适用：参数页。

流程：

```text
面板稳定展示
→ 按 Cue 强调上传区
→ 强调参数项
→ 强调生成按钮
```

#### `ui_perspective_push_in`

适用：参数页、功能页。

流程：

```text
深色网格背景
→ UI 作为不可变平面
→ 四点透视倾斜
→ 拉近并减弱倾斜
→ 阴影与边缘光
→ 最后稳定
```

现有 `perspective_push_in` 的透视矩阵、网格、圆角、阴影和发光逻辑可迁移为该模板的 primitive。

#### `ui_one_click_generate`

适用：“不需要提示词，一键生成”。

流程：

```text
参数页稳定
→ 光标移动到生成按钮
→ 点击
→ 能量反馈/SFX
→ 结果转场
```

### 11.2 概念演绎类

#### `concept_logo_to_vi_reveal`

素材槽位：

```text
logo
vi_board
```

流程：

```text
LOGO 单体出现
→ LOGO 移动到结果板对应位置
→ VI 模块逐层展开
→ 完整真实 VI 板稳定展示
```

注意：`logo_to_vi_reveal` 是镜头模板，不是 GPT 派生图片类型。

#### `concept_subject_expand`

适用：一个主体扩展成多个场景或应用。

#### `concept_before_after`

适用：输入与最终结果对比。

起点和终点必须都来自真实素材，不生成虚构证据中间态。

### 11.3 结果展示类

#### `result_full_bleed_push`

单图完整展示，轻微推入和景深。

#### `result_carousel`

多张结果逐张绑定关键词切换。

#### `result_card_stack`

卡片堆叠、抽出、回收，适合品牌案例。

#### `result_mosaic_reveal`

先逐张展示，再组合为可读拼图，不把图片切碎到不可读。

---

## 12. 动态特效插入系统

### 12.1 原则

动态插入特效不是运行时让 AI 修改 Python 代码，而是让 AI 或规则系统输出受控的特效指令。

```json
{
  "frame": 42,
  "action": "effect.insert",
  "recipe": "neon_scan_hit",
  "target": "vi_board",
  "duration_frames": 18,
  "intensity": 0.7
}
```

编译器执行：

```python
effect = EFFECT_REGISTRY["neon_scan_hit"]

nodes = effect.compile(
    target="vi_board",
    start_frame=42,
    duration_frames=18,
    intensity=0.7,
)

scene.nodes.extend(nodes)
```

### 12.2 注册机制

```python
@register_effect("neon_scan_hit")
class NeonScanHitEffect(EffectRecipe):
    def compile(
        self,
        *,
        target: str,
        start_frame: int,
        duration_frames: int,
        intensity: float,
    ) -> list[Node]:
        ...
```

```python
@register_template("concept_logo_to_vi_reveal")
class LogoToVIRevealTemplate(ShotTemplate):
    def build(
        self,
        shot: CompiledShot,
        context: BuildContext,
    ) -> Scene:
        ...
```

### 12.3 Effect Director

输入：

```text
镜头模板
+ 当前语义 Cue
+ 素材构图
+ Style Pack
+ 已使用模板
+ 当前运动能量
```

输出：

```text
Effect Recipe
+ 起止帧
+ 强度
+ SFX
```

### 12.4 特效能量预算

为了鲜活但不杂乱：

- 每 2 秒最多一个强 hit；
- 连续最多两个强动效镜头；
- 强动效后至少保留 10 帧稳定期；
- 同时活跃的高强度动态层不超过 3 个；
- UI 阅读期禁止持续晃动；
- 字幕出现时降低背景运动强度；
- 同一模板一条视频默认最多使用两次；
- 相邻镜头运动方向需连续；
- 不允许每张图随机使用不同特效。

---

## 13. Style Pack

风格包统一控制整条视频的视觉语言。

首批建议：

```text
tech_product_demo
minimal_business
energetic_social
luxury_brand
playful_youth
cinematic_showcase
```

风格包控制：

- 主色与辅助色；
- 缓动曲线；
- 发光强度；
- 阴影；
- 粒子密度；
- 卡片圆角；
- 转场速度；
- 镜头运动幅度；
- SFX 类型；
- 字幕样式；
- 网格、背景和装饰元素。

---

## 14. 音频系统

V3 实现真正的多轨：

```text
voice
bgm
sfx_click
sfx_whoosh
sfx_hit
sfx_pop
outro
```

### 14.1 混音规则

- 旁白为主轨；
- BGM 在旁白期间自动 duck；
- SFX 与视觉 Cue 共享同一帧；
- SFX 不得比画面事件早超过 1 帧；
- 强 hit 避免覆盖口播重音；
- 输出统一做响度和峰值限制；
- 片尾音频独立处理。

### 14.2 节拍吸附

音乐只辅助语义卡点：

```text
先确定语义 Cue
→ 在 Cue 附近 ±80ms 搜索音乐节拍
→ 有合适节拍才吸附
→ 没有则保持语义时间
```

不得为了踩鼓点破坏口播与画面同步。


---

## 15. 字幕与安全区

字幕不是最后简单叠加。

每个镜头模板必须提前知道：

- 字幕保护区；
- 主体保护区；
- callout 可用区；
- 平台 UI 遮挡区；
- 中央 3:4 安全区。

场景图固定渲染顺序：

```text
背景
→ 原始证据图/结果图
→ 设计化 callout、光标和特效
→ 非证据装饰
→ 字幕
```

字幕与主体、按钮、LOGO、品牌文字不得冲突。

---

## 16. 最终 QA

QA 只对最终视频执行。

### 16.1 资产 QA

- 源文件存在；
- hash 一致；
- receipt 有效；
- 派生关系可追溯；
- 质量状态满足要求；
- 派生素材未越权继承 claims；
- 同一镜头的品牌素材属于同一 `identity_group_id`。

### 16.2 时间轴 QA

- narration 与 Minimax word timing 映射完整；
- 关键词 Cue 误差不超过 1 帧；
- 无歧义 Cue；
- 音画总时长误差不超过 1 帧；
- UI 稳定可读时长；
- 结果图最小可读时长；
- 动效后稳定尾帧；
- 正式模式无估算卡点。

### 16.3 保真 QA

- 网站关键文字 OCR 与源截图一致；
- UI 主体像素差异只来自确定性变换；
- 结果图主体 pHash/特征一致；
- LOGO 几何和文字一致；
- callout 与变换后 anchor 的 IoU 达标；
- GPT Image 未重画证据主体。

### 16.4 构图 QA

- 主体占画布比例；
- 黑边与空白比例；
- UI 最小文字高度；
- 字幕行数；
- 字幕与主体重叠率；
- protected anchor 是否被遮挡；
- 中央 3:4 安全区；
- 手机缩略图可读性。

### 16.5 动效 QA

抽取：

```text
每个镜头首帧
每个转场中点
每个特效峰值帧
每个 callout 激活帧
每个镜头稳定尾帧
字幕最长帧
```

检查：

- 是否闪屏；
- 是否越界；
- 是否跳帧；
- 运动速度；
- 运动加速度；
- 连续强特效数量；
- 模板重复次数；
- 镜头方向是否冲突；
- 稳定期是否足够。

### 16.6 Vision QA

Vision QA 输入：

```text
关键帧
+ 当前旁白
+ 当前字幕
+ asset id
+ shot template
+ expected cue
+ allowed claims
+ forbidden claims
+ protected anchors
```

只有 Vision QA 通过后，最终文件才能标记：

```text
deliverable
```

---

## 17. 运行目录与缓存

每次运行使用不可变目录：

```text
runs/<run_id>/
  case.snapshot.json
  asset_catalog.snapshot.json
  visual_strategy_draft.json
  derived_asset_requests.json
  derived_assets/
  visual_plan.locked.json
  narration.json
  voice/
  word_timing.json
  cue_timing_report.json
  render_plan.json
  frames/
  visual_intermediate.mp4
  audio_mix.wav
  final.mp4
  qa_report.json
  run_manifest.json
  review/
```

缓存依据：

```text
输入素材 hash
+ 配置 hash
+ prompt hash
+ 模型版本
+ 代码版本
```

禁止使用 mtime 作为主要缓存依据。

支持按阶段重跑：

```text
assets
derive
plan
narrate
voice
compile
render
qa
```

---

## 18. 预览与 Review

V3 必须提供三种预览：

```text
单帧预览
单镜头低清预览
整片低清预览
```

命令示例：

```bash
video-agent preview shot_003 --frame 45
video-agent preview shot_003 --scale 0.5
video-agent preview run --resolution 540x960
```

Preview 与 Final 必须使用同一个 Render Plan，只允许降低分辨率和编码质量，不允许改变：

- 帧数；
- Cue；
- 缓动；
- 模板；
- 动效时长；
- 音效时间。

Review UI 应展示：

- 视频播放器；
- frame timeline；
- word timing；
- Cue；
- 镜头模板；
- asset slots；
- QA 错误；
- 单镜重跑入口。

---

## 19. 性能策略

逐帧渲染必须避免重复计算。

缓存内容：

```text
原始图片解码
静态背景
圆角 mask
文字栅格
阴影层
模糊层
透视系数
不变装饰层
静态节点结果
```

节点分类：

```text
Static Node
Transform-only Node
Dynamic Raster Node
GPU Node
```

第一阶段优先保证正确性和效果，后续再引入：

```text
多进程分镜渲染
ModernGL GPU Backend
分镜级缓存
帧级增量重渲染
```

---

## 20. 色彩、字体与可复现性

必须锁定：

```text
Python 版本
Pillow/OpenCV/NumPy 版本
FFmpeg 版本
字体名称与字体 hash
插值算法
颜色空间
视频 range
随机种子
```

建议统一：

```text
图像处理：sRGB
视频输出：Rec.709
像素格式：yuv420p
range：明确固定
```

同一 Render Plan 在相同环境下应逐帧确定性一致。

---

## 21. 代码组织

```text
video_agent/
  cli.py

  domain/
    models.py
    enums.py
    policies.py
    errors.py

  assets/
    catalog.py
    importer.py
    filename_parser.py
    provenance.py
    quality.py
    anchors.py
    identity.py

  derived/
    compiler.py
    task_router.py
    logo_isolate.py
    subject_cutout.py
    background_clean.py
    background_extend.py
    concept_reconstruct.py
    qa.py

  planning/
    story_director.py
    asset_director.py
    shot_director.py
    narration_director.py
    context_builder.py

  speech/
    minimax_client.py
    word_timing.py
    normalization.py
    phrase_matcher.py
    prosody.py

  cues/
    models.py
    compiler.py
    conflict_solver.py
    frame_quantizer.py
    beat_snap.py

  render_plan/
    compiler.py
    validator.py
    serializer.py

  render/
    engine.py
    scene.py
    node.py
    frame_context.py
    cache.py
    easing.py
    transforms.py
    masks.py
    text.py

    backends/
      pillow_backend.py
      opencv_backend.py
      skia_backend.py
      moderngl_backend.py

    primitives/
      image_plane.py
      perspective_plane.py
      cursor.py
      callout.py
      particles.py
      glow.py
      scanline.py
      motion_blur.py

    effects/
      registry.py
      soft_pop.py
      camera_hit.py
      neon_scan.py
      tile_assemble.py
      radial_reveal.py
      perspective_push.py
      card_stack.py
      light_sweep.py

    templates/
      registry.py
      ui_overview_focus.py
      ui_menu_click.py
      ui_params_walkthrough.py
      ui_perspective_push_in.py
      ui_one_click_generate.py
      concept_logo_to_vi_reveal.py
      concept_subject_expand.py
      concept_before_after.py
      result_full_bleed_push.py
      result_carousel.py
      result_card_stack.py
      result_mosaic_reveal.py

    styles/
      tech_product_demo.py
      minimal_business.py
      energetic_social.py
      luxury_brand.py
      playful_youth.py
      cinematic_showcase.py

  audio/
    mixer.py
    loudness.py
    ducking.py
    beat_detector.py
    sfx_registry.py

  qa/
    assets.py
    timing.py
    fidelity.py
    composition.py
    motion.py
    audio.py
    vision.py
    delivery.py

  orchestration/
    pipeline.py
    stage.py
    cache.py
    run_manifest.py

tools/
  cdp_capture/

tests/
  unit/
  integration/
  golden/
  e2e/
```

---

## 22. 统一 CLI

```bash
video-agent init
video-agent assets sync
video-agent plan
video-agent derive
video-agent narrate
video-agent voice
video-agent compile
video-agent render
video-agent qa
video-agent preview
video-agent review
video-agent run
```

标准生产命令：

```bash
video-agent run \
  --case cases/vi_seed_001 \
  --mode strict
```

---

## 23. 开发实施顺序

### 阶段 1：领域模型与运行框架

- Pydantic V3 模型；
- `case.json`；
- `asset_catalog.json`；
- immutable run directory；
- content-hash cache；
- run manifest；
- 单一 CLI。

完成标准：

- 同一输入产生唯一 run；
- 所有字段都有唯一模型和校验器；
- 不再生成 V2 派生项目文件。

### 阶段 2：派生资产系统

优先实现：

```text
logo_isolate
subject_cutout
background_clean
background_extend
```

同时实现：

- provenance；
- evidence inheritance；
- quality states；
- identity group；
- machine QA；
- Vision QA。

完成标准：

- VI 结果图可稳定派生出同品牌 LOGO；
- 派生资产可追溯；
- 未验证资产不能进入正式计划。

### 阶段 3：Visual Plan 与 Narration

- Story Director；
- Asset Director；
- Shot Director；
- Visual Strategy Draft；
- 派生任务回填；
- Locked Visual Plan；
- Visual Plan 变更导致旧 Narration 自动失效。

完成标准：

- 不再出现视觉意图与锁定素材分裂；
- 每个 beat 都有明确模板和素材槽位。

### 阶段 4：Minimax word timing 与 Cue Compiler

- 原始 word timing 存档；
- phrase matcher；
- Cue 编译；
- 30fps 帧量化；
- 冲突求解；
- timing report。

完成标准：

- 每个视觉事件都能说明对应哪个词、哪一帧；
- 正式模式无估算卡点。

### 阶段 5：Python Scene Graph Renderer

先实现：

```text
Scene / Node
AnimatedValue
Transform
ImageNode
MaskNode
CursorNode
CalloutNode
ParticleNode
Pillow/OpenCV Backend
```

完成标准：

- 单镜头逐帧确定性渲染；
- 支持缓存；
- 支持单帧和低清预览。

### 阶段 6：核心模板

优先完成：

```text
concept_logo_to_vi_reveal
ui_one_click_generate
ui_perspective_push_in
result_full_bleed_push
result_carousel
```

完成标准：

- 可完整复跑 VI 种草案例；
- 前 1–2 镜为 LOGO 单体与 LOGO→VI；
- 第 3 镜准确对应“一键生成”；
- 后续结果与前段品牌形成闭环。

### 阶段 7：Effect Director 与多轨音频

- Effect Registry；
- Effect Director；
- Style Pack；
- 运动预算；
- BGM；
- SFX；
- ducking；
- beat snap。

完成标准：

- 特效可按语义动态插入；
- SFX 与视觉事件同帧；
- 效果丰富但不随机堆叠。

### 阶段 8：最终 QA 与 Review UI

- cue-aware frame extraction；
- OCR/pHash/anchor QA；
- motion QA；
- audio QA；
- Vision QA；
- deliverable gate；
- Review UI。

完成标准：

- 只有最终带特效、字幕、声音、封面、片尾的视频通过 QA 后才能交付。

### 阶段 9：删除 V2

删除：

```text
video_project.* 派生链
render_with_effects.py
render_with_cover.py
apply_effect_plan.py
旧 GPT UI 重绘路径
旧 schemas
旧 wrapper
旧 timeline 规则
```

可复用算法迁移进 V3 模块，不保留旧接口。

---

## 24. 首个 Golden Case：VI 种草片

### 24.1 目标叙事

```text
镜头 1：LOGO 单体
镜头 2：LOGO 延展成 VI
镜头 3：一键生成
镜头 4–N：真实品牌结果
镜头 N+1：总结/CTA
```

### 24.2 素材要求

- 同一品牌 LOGO 与 VI 板；
- 真实参数页；
- 真实生成按钮 anchor；
- 至少 3 个真实 VI 品牌结果；
- 每个结果有 identity/facet/receipt。

### 24.3 必测模板

```text
concept_logo_to_vi_reveal
ui_one_click_generate
ui_perspective_push_in
result_carousel
result_mosaic_reveal
```

### 24.4 验收

- “一个简单 LOGO”出现时，画面是 LOGO 单体；
- “延展成整套 VI”触发 VI 展开；
- “一键生成”触发真实按钮点击；
- 结果图按品牌词逐张切换；
- LOGO 与后续结果属于同一品牌；
- 所有 Cue 误差不超过 1 帧；
- UI 文字未被重绘；
- 最终视频通过全部 QA。

---

## 25. 其他必须纳入 V3 的问题

### 25.1 品牌连续性

所有属于同一品牌的：

```text
LOGO
VI 板
包装
名片
应用场景
```

必须使用同一 `identity_group_id`。

### 25.2 镜头方向连续性

Render Plan Compiler 应记录：

```text
entry_direction
exit_direction
camera_energy
visual_center
```

并求解相邻镜头连续性，避免左右乱跳。

### 25.3 失败必须显式

例如 LOGO 抽离失败时：

```text
任务失败
→ 输出原因
→ 重新派生或换品牌素材
```

禁止静默退回首页截图。

### 25.4 LLM 不直接控制逐帧参数

LLM 可以决定：

```text
这里需要扩展感
这里需要点击
这里需要重点命中
```

但不能自由输出任意动画数值。

最终参数由：

```text
Shot Template
+ Effect Recipe
+ Style Pack
+ Compiler Policy
```

共同生成。

### 25.5 网站内容视为不可信输入

网页文本、文件名、素材描述进入 Planner 前必须结构化和净化，防止提示注入。

### 25.6 成本与耗时

记录：

- GPT Image 调用次数；
- Vision QA 次数；
- TTS 成本；
- 渲染帧数；
- 每阶段耗时；
- 缓存命中率。

但不得为了省成本自动跳过严格 QA。

### 25.7 测试体系

必须建立：

- Pydantic 模型测试；
- word timing 短语映射测试；
- Cue 编译属性测试；
- 每个模板 golden frame；
- 同素材连续镜头不闪屏测试；
- 30fps 边界测试；
- 音画时长测试；
- 一个 8–12 秒离线 E2E fixture；
- VI Golden Case E2E。

---

## 26. 最终验收指标

| 维度 | 验收目标 |
|---|---|
| 图文匹配 | 每句口播绑定明确 visual beat 与素材槽位 |
| 卡点 | 关键词 Cue 与视觉事件误差不超过 1 帧 |
| Word Timing | 直接使用 Minimax word timing，无正式模式估算回退 |
| 素材保真 | 网站关键文字 100% 保留，结果主体不被生成模型改写 |
| 派生素材 | 品牌一致、可追溯、证据继承明确 |
| 时长 | 默认功能种草 15–20 秒，超过 24 秒失败 |
| 信息量 | 多品牌/多场景文案必须逐图绑定 |
| 特效 | 可按语义动态插入，强特效不过载 |
| 鲜活感 | 视觉动作、SFX 和语义重音同步 |
| 可读性 | UI、结果主体、callout、字幕无冲突 |
| 可复现性 | 同一 Render Plan 在固定环境下逐帧一致 |
| QA | 只对最终完整视频执行并放行 |
| 交付 | 未通过最终 QA 不得标记 deliverable |

---

## 27. 最终建议

V3 不应继续增加独立 effect 脚本，也不应继续在 V2 的多份项目 JSON 上叠加功能。

应直接围绕以下主线建设：

```text
统一资产目录
→ 派生资产编译
→ 锁定视觉计划
→ Minimax word timing
→ 语义 Cue 编译
→ Python 场景图
→ 镜头模板与动态特效
→ 多轨音频
→ 最终成片 QA
```

其中：

- `logo_isolate` 是派生资产任务；
- `concept_logo_to_vi_reveal` 是镜头模板；
- `ui_one_click_generate` 是 UI 操作模板；
- `perspective_push_in` 是可复用渲染 primitive；
- Minimax 已有的 word timing 是卡点基础；
- Python 完全可以承担 V3 渲染，不需要依赖 Remotion；
- AI 降低了单个特效复刻成本，但必须通过 Scene Graph、Effect Registry 和 Shot Template 将其工程化。

V3 的成功不以“新增多少特效”为标准，而以最终视频是否做到以下四点为标准：

```text
画面对
卡点准
特效活
结果可信
```
