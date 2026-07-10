# Video Agent V3 设计方案（AI 编排增强版）

> 版本：V3.1  
> 目标：不考虑 V2 兼容性，以最终成片效果为唯一标准，重点保证：
>
> 1. **卡点准确**：所有视觉事件以 Minimax word timing 为时间权威，关键词到画面动作误差不超过 1 帧；
> 2. **AI 编排能力最大化**：AI 能理解现有截图、结果图、实景图及它们之间的关系，主动设计镜头和新素材；
> 3. **素材不足时自动补图**：支持基于现有素材作为参考，自动生成满足固定文案和镜头需要的新图；
> 4. **特效丰富且可动态插入**：特效根据语义、素材构图、镜头模板和时间窗口动态选择；
> 5. **结果可信**：真实产品结果、语义派生图和装饰图严格区分；
> 6. **可复现、可审查、可重跑**：同一 Render Plan 在固定环境中逐帧确定性一致。

---

# 1. 核心原则

V3 不再是“图片加转场”的脚本集合，而是一个真正的视频编译系统。

```text
固定文案或用户目标
  ↓
Minimax TTS + word timing
  ↓
不可变 timing_lock
  ↓
语义 Beat 解析
  ↓
多模态素材理解
  ↓
素材关系图
  ↓
AI 视觉机会发现
  ↓
素材缺口分析
  ↓
参考素材驱动的派生/造图
  ↓
候选方案生成与视觉 Critic
  ↓
锁定 Visual Plan
  ↓
镜头模板 + 动态特效编排
  ↓
唯一 render_plan.json
  ↓
Python 场景图渲染
  ↓
FFmpeg 多轨混音、字幕和编码
  ↓
最终成片 QA
  ↓
交付
```

V3 的控制边界必须明确：

> **AI 决定画什么、缺什么、如何补图、采用什么视觉叙事；确定性编译器决定什么时候发生。**

也就是说：

- AI 可以决定“这里应该做实景参考图到生成效果”；
- AI 可以决定“素材库缺一张编辑后结果，需要基于当前页面截图生成”；
- AI 可以决定“这里适合做前后对比，而不是普通轮播”；
- AI 可以决定“在‘一键生成’处加入点击和能量反馈”；

但 AI 不直接决定：

- 第 2.183 秒开始；
- 持续 0.437 秒；
- 平移 174 像素；
- 为了完整播放特效，把语义事件推迟 12 帧。

具体帧、时长和动画参数必须由：

```text
Minimax word timing
+ Cue Compiler
+ Shot Template
+ Effect Recipe
+ Timing Policy
```

共同编译。

---

# 2. V3 的最高优先级：卡点准确

卡点是 V3 的第一原则，其他所有能力都必须服从卡点。

## 2.1 Minimax word timing 是唯一时间权威

当前 Minimax 已经能够直接返回 word 级时间段，V3 不再重新估算词时间，也不依赖额外 ASR 才能完成卡点。

正确链路：

```text
Minimax 原始 word timing
→ 保留原始 token 和时间段
→ 将 narration 中的关键词短语映射到 word token
→ 量化为绝对帧
→ 锁定 timing_lock.json
```

## 2.2 `timing_lock.json`

一旦生成，后续模块只读，不允许被素材生成、镜头选择或特效时长修改。

```json
{
  "schema_version": 3,
  "fps": 30,
  "duration_frames": 536,
  "words": [
    {
      "index": 0,
      "text": "上传",
      "start_ms": 2133,
      "end_ms": 2333,
      "start_frame": 64,
      "end_frame": 70
    },
    {
      "index": 1,
      "text": "现场图",
      "start_ms": 2366,
      "end_ms": 2766,
      "start_frame": 71,
      "end_frame": 83
    },
    {
      "index": 2,
      "text": "生成",
      "start_ms": 3533,
      "end_ms": 3800,
      "start_frame": 106,
      "end_frame": 114
    },
    {
      "index": 3,
      "text": "效果",
      "start_ms": 3833,
      "end_ms": 4133,
      "start_frame": 115,
      "end_frame": 124
    }
  ],
  "semantic_cues": [
    {
      "phrase": "现场图",
      "word_range": [1, 1],
      "frame": 71,
      "action": "reference.show"
    },
    {
      "phrase": "生成效果",
      "word_range": [2, 3],
      "frame": 106,
      "action": "result.reveal"
    }
  ]
}
```

## 2.3 卡点优先级

冲突时固定采用以下优先级：

```text
P0：语义 Cue 帧
P1：语义与画面匹配
P2：素材可读性与稳定尾帧
P3：镜头模板完整性
P4：特效完整性
P5：音乐节拍
P6：装饰效果
```

发生冲突时允许：

```text
缩短特效
→ 使用轻量特效变体
→ 减少装饰层
→ 更换镜头模板
→ 放弃非必要镜头运动
```

绝不允许：

```text
移动关键词 Cue
拉伸或重排固定旁白
为了完整播放特效而推迟结果出现
为了踩音乐节拍而改变语义动作帧
```

## 2.4 特效必须服从时间窗口

每个 Effect Recipe 必须提供多个时长变体。

```text
result_reveal:
  micro:   6 帧
  short:  10 帧
  normal: 18 帧
  rich:   28 帧
```

如果某个语义 Cue 到下一个 Cue 之间只有 14 帧，编译器只能选择 `micro` 或 `short`，不能为了使用 `rich` 把动作推迟。

---

# 3. 支持三种生产模式

## 3.1 `script_locked`

固定文案，不允许改写。

这是 V3 必须优先支持的核心模式。

```text
固定文案
→ Minimax TTS + word timing
→ timing_lock
→ 文案语义 Beat 解析
→ AI 根据时间窗口寻找或制造素材
→ 锁定镜头
→ 渲染
```

## 3.2 `visual_first`

素材先行，AI 根据已有素材设计画面并生成口播。

```text
素材理解
→ 视觉机会
→ Visual Plan
→ Narration
→ TTS
→ Cue 编译
```

## 3.3 `hybrid`

开头、品牌话术、结尾固定，中间允许 AI 根据素材调整。

```text
固定 Hook
+ 固定 CTA
+ 可变产品演示段
```

---

# 4. 正式数据产物

V3 只保留九个正式契约。

## 4.1 `case.json`

描述用户目标和全局约束。

```json
{
  "schema_version": 3,
  "case_id": "vi_seed_001",
  "mode": "script_locked",
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

## 4.2 `asset_catalog.json`

唯一素材目录，替代所有并行的素材清单和理解文件。

```json
{
  "schema_version": 3,
  "assets": [
    {
      "id": "asset_scene_reference_001",
      "kind": "reference_image",
      "source": "assets/references/企业前台实景.jpg",
      "feature_path": ["文生图", "文化墙"],
      "identity_group_id": "scene_company_lobby_001",
      "facet": {
        "kind": "scene",
        "label": "企业前台"
      },
      "evidence": {
        "type": "real_reference",
        "allowed_claims": [
          "这是原始现场参考图"
        ],
        "forbidden_claims": [
          "这是产品生成结果"
        ]
      },
      "anchors": [
        {
          "id": "wall_area",
          "role": "editable_region",
          "space": "source_normalized",
          "box": {
            "x": 0.18,
            "y": 0.22,
            "w": 0.56,
            "h": 0.44
          }
        }
      ],
      "quality": {
        "state": "vision_verified"
      },
      "provenance": {
        "sha256": "...",
        "created_by": "user_upload"
      }
    }
  ]
}
```

## 4.3 `asset_relationship_graph.json`

描述素材之间可用于视觉叙事的关系。

```json
{
  "schema_version": 3,
  "nodes": [
    "asset_editor_before",
    "asset_editor_after",
    "asset_real_scene",
    "asset_generated_scene",
    "asset_logo",
    "asset_vi_board"
  ],
  "relationships": [
    {
      "id": "rel_001",
      "type": "before_after",
      "from": "asset_editor_before",
      "to": "asset_editor_after",
      "confidence": 0.94,
      "evidence": [
        "same_canvas_geometry",
        "same_subject",
        "localized_difference"
      ]
    },
    {
      "id": "rel_002",
      "type": "reference_to_result",
      "from": "asset_real_scene",
      "to": "asset_generated_scene",
      "confidence": 0.91,
      "evidence": [
        "same_camera_angle",
        "same_room_geometry"
      ]
    },
    {
      "id": "rel_003",
      "type": "same_identity",
      "assets": [
        "asset_logo",
        "asset_vi_board"
      ],
      "identity_group_id": "brand_001",
      "confidence": 0.97
    },
    {
      "id": "rel_004",
      "type": "workflow_transition",
      "from": "asset_params_page",
      "to": "asset_generated_scene",
      "action": "click_generate",
      "confidence": 0.89
    }
  ]
}
```

## 4.4 `visual_strategy_draft.json`

AI 基于固定文案、时间窗口和素材关系图生成的候选视觉策略。

```json
{
  "schema_version": 3,
  "beats": [
    {
      "id": "beat_003",
      "text": "上传一张现场图，马上看到完整设计效果。",
      "frame_window": {
        "start_frame": 64,
        "end_frame": 146
      },
      "semantic_cues": [
        {
          "phrase": "现场图",
          "frame": 71,
          "action": "reference.show"
        },
        {
          "phrase": "设计效果",
          "frame": 106,
          "action": "result.reveal"
        }
      ],
      "candidates": [
        {
          "id": "candidate_003_a",
          "visual_pattern": "reference_to_generated_result",
          "shot_template": "reference_to_result_reveal",
          "required_slots": [
            "reference",
            "result"
          ],
          "timing_fit": true
        },
        {
          "id": "candidate_003_b",
          "visual_pattern": "ui_action_to_result",
          "shot_template": "ui_one_click_generate",
          "required_slots": [
            "params_page",
            "result"
          ],
          "timing_fit": true
        }
      ]
    }
  ]
}
```

## 4.5 `materialization_plan.json`

描述素材缺口，以及需要如何基于参考素材制造新图。

```json
{
  "schema_version": 3,
  "tasks": [
    {
      "id": "materialize_result_001",
      "beat_id": "beat_003",
      "visual_pattern": "reference_to_generated_result",
      "output_slot": "result",
      "kind": "reference_grounded_result",
      "references": [
        {
          "asset_id": "asset_real_scene_001",
          "role": "geometry_reference"
        },
        {
          "asset_id": "asset_brand_logo_001",
          "role": "identity_reference"
        },
        {
          "asset_id": "asset_style_reference_003",
          "role": "style_reference"
        },
        {
          "asset_id": "asset_existing_result_002",
          "role": "quality_reference"
        }
      ],
      "constraints": {
        "preserve_scene_geometry": true,
        "preserve_camera_angle": true,
        "preserve_doors_windows": true,
        "change_only_design_region": true,
        "target_anchor_id": "wall_area",
        "target_style": "科技企业文化墙",
        "no_unrelated_objects": true
      },
      "evidence_class": "semantic_derivative"
    }
  ]
}
```

## 4.6 `visual_plan.json`

从多个候选中选择通过 Critic 的方案，并填充最终素材槽位。

```json
{
  "schema_version": 3,
  "status": "locked",
  "timing_lock_sha256": "...",
  "asset_catalog_sha256": "...",
  "beats": [
    {
      "id": "beat_003",
      "purpose": "展示现场图到完整设计效果",
      "shot_template": "reference_to_result_reveal",
      "asset_slots": {
        "reference": "asset_real_scene_001",
        "result": "asset_derived_scene_result_001"
      },
      "allowed_claims": [
        "基于现场参考图构建设计效果"
      ],
      "cue_bindings": [
        {
          "action": "reference.show",
          "frame": 71
        },
        {
          "action": "result.reveal",
          "frame": 106
        }
      ]
    }
  ]
}
```

## 4.7 `narration.json`

在 `script_locked` 模式下保存固定文案；在其他模式下保存 AI 生成口播。

```json
{
  "schema_version": 3,
  "mode": "script_locked",
  "segments": [
    {
      "id": "seg_003",
      "text": "上传一张现场图，马上看到完整设计效果。",
      "emphasis_cues": [
        {
          "phrase": "现场图",
          "action": "reference.show"
        },
        {
          "phrase": "设计效果",
          "action": "result.reveal"
        }
      ]
    }
  ]
}
```

## 4.8 `render_plan.json`

所有时间和动画都编译成绝对帧。

```json
{
  "schema_version": 3,
  "fps": 30,
  "duration_frames": 536,
  "shots": [
    {
      "id": "shot_003",
      "start_frame": 64,
      "end_frame": 146,
      "template": "reference_to_result_reveal",
      "asset_slots": {
        "reference": "asset_real_scene_001",
        "result": "asset_derived_scene_result_001"
      },
      "cues": [
        {
          "frame": 71,
          "action": "reference.show"
        },
        {
          "frame": 106,
          "action": "result.reveal"
        },
        {
          "frame": 106,
          "action": "sfx.whoosh"
        },
        {
          "frame": 132,
          "action": "camera.settle"
        }
      ],
      "effect_instances": [
        {
          "recipe": "region_morph_reveal",
          "start_frame": 106,
          "duration_frames": 14,
          "variant": "short"
        }
      ]
    }
  ]
}
```

## 4.9 `run_manifest.json` 与 `qa_report.json`

分别记录完整可追溯信息与最终 QA 结论。

---

# 5. 多模态素材理解

V3 的 AI 编排不能只依赖文件名和标签，必须直接理解图像内容。

## 5.1 每张素材需要提取的内容

- 画面主体；
- 页面或场景类型；
- 可见文字；
- 品牌与身份；
- 布局和构图；
- 可编辑区域；
- 结果区域；
- 输入与输出关系；
- 前后状态；
- 相同场景或相同品牌；
- 适合的镜头模式；
- 可支持的事实；
- 不允许支持的事实；
- 生成新图时必须保持的结构。

## 5.2 视觉锚点

建议统一使用：

```text
click_target
editable_region
result_region
brand_region
logo_region
subject_region
protected_region
comparison_region
```

示例：

```json
{
  "id": "result_panel",
  "role": "result_region",
  "space": "source_normalized",
  "box": {
    "x": 0.52,
    "y": 0.14,
    "w": 0.42,
    "h": 0.72
  }
}
```

---

# 6. Visual Opportunity Director

这是 V3 最大化发挥 AI 编排能力的核心模块。

它的任务不是简单选图，而是主动发现：

> 现有素材之间可以构建什么视觉叙事，以及为了文案可以补出什么新画面。

## 6.1 可发现的关系

### 编辑页面前后对比

```text
原始编辑页面
→ 局部修改/滑块/擦除
→ 编辑后页面
```

### 实景参考到生成效果

```text
实景图
→ 聚焦改造区域
→ 生成效果覆盖或展开
```

### 输入到输出

```text
LOGO、草图、照片或表单输入
→ 处理演绎
→ 完整结果
```

### 参数设置到结果

```text
参数页
→ 点击生成
→ 结果图
```

### 局部到整体

```text
LOGO、局部细节或单个模块
→ 拉远/拼接/展开
→ 完整设计
```

### 同一输入的多种风格

```text
相同输入
→ 风格 A
→ 风格 B
→ 风格 C
```

### 多参考合成

```text
空间参考
+ 品牌参考
+ 风格参考
→ 新结果
```

---

# 7. Visual Pattern Registry

AI 发现机会后，必须映射到受控的 Visual Pattern。

首批模式：

```text
editor_before_after
reference_to_generated_result
input_to_output
ui_action_to_result
detail_to_full
style_variant_compare
reference_composition
logo_to_vi
concept_gap_fill
result_gallery
```

每个 Visual Pattern 声明：

- 需要哪些素材槽位；
- 哪些槽位允许 AI 生成；
- 哪些槽位必须是真实素材；
- 允许使用哪些镜头模板；
- 适合哪些语义 Cue；
- 最小帧预算；
- 证据要求；
- QA 规则。

示例：

```json
{
  "name": "reference_to_generated_result",
  "required_slots": {
    "reference": {
      "allowed_kinds": ["reference_image"],
      "must_be_real": true
    },
    "result": {
      "allowed_kinds": [
        "real_generated_result",
        "semantic_derivative"
      ],
      "can_materialize": true
    }
  },
  "min_frames": 36,
  "preferred_templates": [
    "reference_to_result_reveal",
    "before_after_slider",
    "region_morph_reveal"
  ]
}
```

---

# 8. Asset Gap Analyzer

对每个 Beat，系统检查：

```text
文案需要什么
→ Visual Pattern 需要什么槽位
→ 素材关系图中已有何种素材
→ 哪些槽位缺失
```

输出：

```text
可直接满足
可通过确定性派生满足
需基于参考图生成
无法满足
```

## 8.1 缺口处理优先级

```text
1. 使用已有真实素材
2. 使用已有素材的确定性裁切/抠图/组合
3. 使用目标产品真实生成流程补结果
4. 使用参考素材约束的 AI 派生图
5. 调整镜头模板
6. 明确失败
```

禁止在缺图时静默使用语义不匹配的首页或入口页替代。

---

# 9. Reference-Grounded Visual Synthesizer

素材不足时自动造图，但生成必须由现有素材约束。

## 9.1 参考角色

每张参考图必须声明角色：

```text
geometry_reference
identity_reference
style_reference
composition_reference
quality_reference
content_reference
color_reference
```

## 9.2 生成约束

可控制：

- 保持场景结构；
- 保持镜头角度；
- 保持人物、建筑或产品身份；
- 保持品牌 LOGO；
- 只修改指定区域；
- 不新增无关物体；
- 不改变中文文字；
- 保持源图关键元素；
- 与已有结果风格一致。

## 9.3 生成任务类型

### `logo_isolate`

从结果板中抽离 LOGO。

### `subject_cutout`

从原图中抽离人物、产品或图形主体。

### `background_clean`

清理背景但保持主体。

### `background_extend`

扩展竖屏背景，主体原像素重新覆盖。

### `reference_grounded_result`

基于实景图、风格参考、品牌参考生成结果图。

### `editor_after_state`

基于编辑前页面或输入素材构建合理的编辑后状态。

### `style_variant`

基于同一输入生成不同风格结果。

### `concept_reconstruct`

构建非证据概念画面。

## 9.4 生成状态

```text
requested
generated
machine_checked
vision_verified
human_approved
rejected
```

未达到 `vision_verified` 不得进入正式 Visual Plan。

---

# 10. 证据与真实性

生成图可以丰富视频，但必须区分真实性。

## 10.1 Evidence Asset

真实截图、真实结果、确定性变换。

可以支持产品事实和结果声明。

## 10.2 Semantic Derivative

基于现有素材重构的新图。

可以用于：

- 概念演绎；
- 前后对比；
- 场景过渡；
- 视觉补足；
- 设计可能性展示。

不能自动证明：

- 产品确实生成了该结果；
- 该结果来自当前用户操作；
- 页面真实存在某个内容。

## 10.3 Decorative Asset

纯背景、粒子、光效、纹理，不支持任何事实。

---

# 11. 候选方案与 Visual Critic

AI 不应一次决定唯一方案。

每个 Beat 生成 2–4 个候选：

```text
候选 A：前后滑块对比
候选 B：实景图局部改造展开
候选 C：参数页点击到结果
候选 D：卡片堆叠式展示
```

## 11.1 Critic 评分

```text
timing_fit
semantic_match
asset_availability
identity_consistency
evidence_safety
readability
visual_novelty
style_consistency
motion_continuity
```

其中以下为硬门槛：

```text
timing_fit
semantic_match
evidence_safety
identity_consistency
```

卡点放不下的候选直接淘汰。

---

# 12. 镜头模板系统

Planner 选择镜头模板，而不是底层 effect。

## 12.1 UI 类

```text
ui_overview_focus
ui_menu_click
ui_params_walkthrough
ui_perspective_push_in
ui_one_click_generate
```

## 12.2 对比与生成类

```text
before_after_slider
editor_before_after_reveal
reference_to_result_reveal
region_morph_reveal
input_to_output_expand
concept_logo_to_vi_reveal
```

## 12.3 结果展示类

```text
result_full_bleed_push
result_carousel
result_card_stack
result_mosaic_reveal
style_variant_carousel
```

## 12.4 `concept_logo_to_vi_reveal`

注意：

```text
logo_isolate = 派生资产任务
concept_logo_to_vi_reveal = 镜头模板
```

流程：

```text
LOGO 单体进入
→ 移动到 VI 结果板对应位置
→ VI 模块逐层展开
→ 完整真实 VI 结果稳定展示
```

---

# 13. Primitive、Effect Recipe 与动态插入

## 13.1 Primitive

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

## 13.2 Effect Recipe

```text
soft_pop
camera_hit
neon_scan
tile_assemble
radial_reveal
perspective_push
card_stack
light_sweep
region_morph
module_expand
```

## 13.3 动态插入

AI 或规则输出受控指令：

```json
{
  "frame": 106,
  "action": "effect.insert",
  "recipe": "region_morph",
  "target": "result",
  "duration_budget_frames": 14,
  "intensity": 0.7
}
```

编译器选择适合帧预算的变体：

```json
{
  "recipe": "region_morph",
  "variant": "short",
  "start_frame": 106,
  "duration_frames": 12
}
```

---

# 14. Python 场景图渲染器

V3 继续采用纯 Python 渲染路线。

```text
Python
+ Pillow
+ NumPy
+ OpenCV
+ 可选 Skia
+ 可选 ModernGL
+ FFmpeg
```

## 14.1 场景图

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

## 14.2 节点属性

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

## 14.3 关键帧

```json
{
  "property": "opacity",
  "keyframes": [
    {
      "frame": 106,
      "value": 0.0,
      "ease": "linear"
    },
    {
      "frame": 118,
      "value": 1.0,
      "ease": "outCubic"
    }
  ]
}
```

## 14.4 现有透视拉近能力

当前 `perspective_push_in` 可迁移为：

```text
PerspectivePlane Primitive
+ perspective_push Effect Recipe
+ ui_perspective_push_in Shot Template
```

不再由素材类别自动硬套。

---

# 15. 特效能量预算

为了鲜活但不杂乱：

- 每 2 秒最多一个强 hit；
- 连续最多两个强动效镜头；
- 强动效后至少 10 帧稳定期；
- 同时活跃的高强度动态层不超过 3 个；
- UI 阅读期禁止持续晃动；
- 字幕出现时降低背景运动；
- 同一模板默认最多使用两次；
- 相邻镜头方向保持连续；
- 不允许每张图随机使用不同特效。

---

# 16. 多轨音频

V3 支持：

```text
voice
bgm
sfx_click
sfx_whoosh
sfx_hit
sfx_pop
outro
```

规则：

- 旁白为主轨；
- BGM 自动 duck；
- SFX 与视觉 Cue 同帧；
- SFX 不得比画面事件早超过 1 帧；
- 强 hit 避免覆盖口播重音；
- 音乐节拍只能在语义 Cue 附近 ±80ms 吸附；
- 不得为了踩鼓点改变语义 Cue。

---

# 17. 最终 QA

QA 只针对最终完整视频。

## 17.1 时间轴 QA

- Minimax word timing 完整；
- Phrase Matcher 无歧义；
- Cue 误差不超过 1 帧；
- 音画总时长误差不超过 1 帧；
- 正式模式无估算卡点；
- 特效未修改 timing_lock；
- 稳定尾帧满足要求。

## 17.2 素材 QA

- 资产来源可追溯；
- 参考角色完整；
- 生成任务约束执行；
- 品牌身份一致；
- 派生资产未越权继承 claims。

## 17.3 保真 QA

- UI 文字与源截图一致；
- 结果图主体一致；
- LOGO 字形和几何一致；
- 生成结果保持场景结构；
- 指定不可修改区域未变化；
- callout 与 anchor 对齐。

## 17.4 构图 QA

- 主体占比；
- 黑边比例；
- 字幕与主体重叠；
- 中央 3:4 安全区；
- UI 最小文字高度；
- 手机缩略图可读性。

## 17.5 动效 QA

抽取：

```text
首帧
转场中点
特效峰值帧
callout 激活帧
稳定尾帧
最长字幕帧
```

检查：

- 闪屏；
- 越界；
- 跳帧；
- 速度和加速度；
- 强特效连续性；
- 模板重复；
- 方向冲突；
- 稳定期。

## 17.6 Vision QA

输入：

```text
关键帧
+ 当前文案
+ 当前字幕
+ asset id
+ Visual Pattern
+ Shot Template
+ expected cue
+ allowed claims
+ forbidden claims
+ protected anchors
```

只有最终完整视频通过后才能标记：

```text
deliverable
```

---

# 18. Agent 结构

```text
Semantic Beat Analyzer
  固定文案 → Beat 与关键短语

Multimodal Asset Analyst
  理解截图、实景图、结果图、编辑页面

Asset Relationship Builder
  建立 before/after、reference/result、same_identity 等关系

Visual Opportunity Director
  主动发现可构建的新画面和叙事

Asset Gap Analyzer
  判断每个 Beat 缺少哪些素材槽位

Materialization Director
  规划裁切、抠图、组合或参考图生成

Reference-Grounded Generator
  基于一张或多张参考素材造图

Visual Critic
  比较候选图与候选镜头

Shot Director
  选择镜头模板

Effect Director
  在固定 Cue 周围选择特效变体

Cue Compiler
  以 Minimax word timing 为唯一时间权威

Deterministic Renderer
  执行唯一 render_plan

Final QA Director
  对最终视频执行交付门禁
```

---

# 19. 代码组织

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
    analyst.py
    relationships.py
    anchors.py
    identity.py
    provenance.py
    quality.py

  planning/
    semantic_beat_analyzer.py
    visual_opportunity_director.py
    asset_gap_analyzer.py
    materialization_director.py
    shot_director.py
    effect_director.py
    visual_critic.py
    narration_director.py

  derived/
    compiler.py
    task_router.py
    logo_isolate.py
    subject_cutout.py
    background_clean.py
    background_extend.py
    reference_grounded_result.py
    editor_after_state.py
    style_variant.py
    concept_reconstruct.py
    qa.py

  speech/
    minimax_client.py
    word_timing.py
    normalization.py
    phrase_matcher.py
    timing_lock.py
    prosody.py

  cues/
    models.py
    compiler.py
    conflict_solver.py
    frame_quantizer.py
    beat_snap.py
    timing_policy.py

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
      region_mask.py

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
      region_morph.py
      module_expand.py

    templates/
      registry.py
      ui_overview_focus.py
      ui_menu_click.py
      ui_params_walkthrough.py
      ui_perspective_push_in.py
      ui_one_click_generate.py
      before_after_slider.py
      editor_before_after_reveal.py
      reference_to_result_reveal.py
      region_morph_reveal.py
      input_to_output_expand.py
      concept_logo_to_vi_reveal.py
      result_full_bleed_push.py
      result_carousel.py
      result_card_stack.py
      result_mosaic_reveal.py
      style_variant_carousel.py

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

tests/
  unit/
  integration/
  golden/
  e2e/
```

---

# 20. 统一 CLI

```bash
video-agent init
video-agent assets sync
video-agent analyze
video-agent relationships
video-agent timing
video-agent opportunities
video-agent materialize
video-agent plan
video-agent compile
video-agent render
video-agent qa
video-agent preview
video-agent review
video-agent run
```

固定文案模式：

```bash
video-agent run \
  --case cases/vi_seed_001 \
  --mode strict \
  --script-locked
```

---

# 21. 实施顺序

## 阶段 1：Timing Lock

优先实现：

- Minimax word timing 标准化；
- Phrase Matcher；
- `timing_lock.json`；
- 帧量化；
- strict 模式禁止 fallback；
- timing QA。

这是最先实现的部分，因为后续一切都依赖它。

## 阶段 2：统一资产目录与多模态理解

- `asset_catalog.json`；
- anchors；
- identity group；
- provenance；
- evidence；
- 多模态素材分析。

## 阶段 3：素材关系图与视觉机会发现

- Asset Relationship Builder；
- Visual Pattern Registry；
- Visual Opportunity Director；
- 每个 Beat 生成 2–4 个候选。

## 阶段 4：素材缺口与参考图造图

- Asset Gap Analyzer；
- Materialization Plan；
- 多参考角色；
- Reference-Grounded Generator；
- 派生资产 QA。

## 阶段 5：锁定 Visual Plan

- Visual Critic；
- Timing Fit 硬门槛；
- 素材槽位绑定；
- 证据检查；
- 品牌连续性检查。

## 阶段 6：Python 场景图

- Scene/Node；
- AnimatedValue；
- Transform；
- ImageNode；
- MaskNode；
- CursorNode；
- CalloutNode；
- Pillow/OpenCV Backend；
- 单帧和低清预览。

## 阶段 7：核心镜头模板

优先实现：

```text
reference_to_result_reveal
editor_before_after_reveal
ui_one_click_generate
ui_perspective_push_in
concept_logo_to_vi_reveal
result_carousel
```

## 阶段 8：动态特效与音频

- Effect Director；
- 特效时长变体；
- 运动预算；
- SFX；
- BGM；
- ducking；
- beat snap。

## 阶段 9：最终 QA 与 Review UI

- cue-aware 抽帧；
- OCR/pHash/anchor QA；
- motion QA；
- audio QA；
- Vision QA；
- deliverable gate。

---

# 22. Golden Case

## 22.1 VI 种草

```text
一个简单 LOGO
→ 延展成整套 VI
→ 一键生成
→ 多品牌真实结果
```

必测：

```text
logo_isolate
concept_logo_to_vi_reveal
ui_one_click_generate
result_carousel
```

## 22.2 实景参考到效果图

```text
上传现场图
→ 指定改造区域
→ 生成设计效果
→ 前后对比
```

必测：

```text
reference_grounded_result
reference_to_result_reveal
region_morph_reveal
before_after_slider
```

## 22.3 编辑页面前后对比

```text
编辑前页面
→ 修改动作
→ 编辑后页面
```

必测：

```text
editor_after_state
editor_before_after_reveal
ui_menu_click
```

---

# 23. 最终验收指标

| 维度 | 验收目标 |
|---|---|
| 卡点 | 关键词 Cue 与视觉事件误差不超过 1 帧 |
| 时间权威 | Minimax word timing 为唯一权威，后续只读 |
| 固定文案 | 文案不因素材或特效变化而被移动或重写 |
| AI 编排 | 能主动发现前后对比、参考到结果、输入到输出等视觉机会 |
| 缺图补全 | 能基于一张或多张参考素材自动生成缺失画面 |
| 素材关系 | 每个镜头能追溯到明确素材关系和槽位 |
| 真实性 | 真实结果、语义派生和装饰素材严格区分 |
| 特效 | 可根据语义动态插入，并自动适配帧预算 |
| 鲜活感 | 画面动作、SFX 和语义重音同步 |
| 可读性 | UI、主体、callout、字幕无冲突 |
| 品牌一致 | 同一故事中的 LOGO、结果和场景属于同一 identity group |
| 可复现 | 同一 Render Plan 在固定环境下逐帧一致 |
| QA | 只针对最终完整视频执行 |
| 交付 | 未通过最终 QA 不得标记 deliverable |

---

# 24. 最终结论

V3 的目标不是限制 AI，而是给 AI 最大化的视觉编排空间，同时用确定性时间轴约束它。

最终架构应遵循：

```text
AI 自由决定：
  画什么
  缺什么
  怎么补
  使用什么视觉模式
  使用什么镜头和特效

系统严格决定：
  在哪一帧发生
  特效最多持续多久
  语义 Cue 是否准确
  素材是否可信
  最终视频是否允许交付
```

浓缩为一句话：

> **AI 尽可能自由地构建视觉内容，所有镜头和特效必须被编译进 Minimax word timing 锁定的帧窗口，任何视觉能力都无权牺牲卡点准确性。**
