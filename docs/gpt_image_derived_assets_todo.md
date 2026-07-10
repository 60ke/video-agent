# TODO: GPT Image 派生图重构能力（基于原图构造新画面）

> 状态：**未实现**  
> 来源：2026-07-10 `cases/vi_seed_effects_20260710` 成片复盘讨论  
> 关联案例：`cases/vi_seed_effects_20260710`（成片 `output/versions/vi_fx_v3.mp4`）

## 1. 问题背景

VI 功能种草片的口播前三句是：

1. `一个简单LOGO，直接延展成整套VI。这就是柯幻熊猫的设计玩法。`
2. `不需要写提示词，一键生成。`

但当前前三个分镜实际画面是：

| 分镜 | 当前画面 | 口播语义 |
|---|---|---|
| `vis_001` | 网站首页 | LOGO → 整套 VI |
| `vis_002` | VI 功能入口页 | （同上，仍在讲玩法） |
| `vis_003` | VI 参数面板 | 不需要提示词、一键生成 |

这是典型的 **叙事-画面错位**：

- 文案讲的是 **概念演绎**：从一个简单 LOGO 出发，延展成完整 VI。
- 画面展示的是 **操作路径**：首页 → 入口 → 参数页。

观众先听到“LOGO 变 VI”，眼睛却看到“网站怎么点进去”，中间会有一拍理解成本。问题不在特效，而在 **分镜素材类型与文案意象不匹配**。

## 2. 更合理的画面方向（讨论结论）

前段应优先服务“LOGO → VI”概念，后段再用真实结果页做证据背书。建议叙事结构：

```text
LOGO 单体（从结果页抽离）
  → LOGO 延展成 VI（同一品牌的完整 VI 画面）
    → 一键生成玩法（产品界面或生成过程）
      → 真实 VI 结果案例 × N
```

相比当前结构：

```text
首页 → 入口页 → 参数页 → 结果案例 × N
```

前者更贴近种草文案；后者更像功能教程。

**关键判断**：从后续结果页中抽离 LOGO，再动画展示 LOGO → 完整 VI，比继续堆网站截图更匹配这条片子的口播。且若 LOGO 与后面案例来自同一品牌（如半克星球），前后可形成闭环故事线。

## 3. 案例：`vi_seed_effects_20260710`

### 3.1 文案与分镜绑定

见 `cases/vi_seed_effects_20260710/output/planner/video_script_draft.json`：

- `seg_001` / `beat_001`：`visual_intent` 写的是「主页开场，LOGO延展成VI」，但 `locked_asset_ids` 锁的是 `site_kehuanxiongmao_home_raw_desktop`（首页截图）。
- `seg_002` / `beat_002`：口播「不需要写提示词，一键生成」，画面却是功能入口截图。
- `seg_003` / `beat_003`：参数面板截图。

编排层 **意图** 与 **素材选择** 已出现分裂；即便 `visual_intent` 写了 LOGO 延展，现有链路也没有产出这类画面的能力。

### 3.2 当前 GPT Image 实际做了什么

`scripts/prepare_gpt_image_keyframes.py` 对本案 8 个镜头只做两类处理（见 `output/reports/gpt_image_keyframes_report.json`）：

1. **网站截图 → 9:16 prepared keyframe**  
   保留原 UI，仅做竖屏构图、安全区、可选标注高亮。  
   Prompt 明确要求 *"Do not create different content"* / *"Preserve the website UI"*。

2. **结果图 → 9:16 layout optimization**  
   对 VI 结果板做竖屏裁切与排版优化，**不拆出 LOGO、不生成中间态**。

另有 `render_with_cover.py` 可基于参考图生成封面，但封面是独立步骤，**不参与分镜时间轴内的派生图构造**。

### 3.3 成片表现

`output/versions/vi_fx_v3.mp4` 前 3 镜特效分配（`drop_bounce` / `wipe_reveal`）已按首页/入口/参数路由修正，但 **素材语义问题仍在**：特效无法把首页截图变成 LOGO 单体或 LOGO→VI 演绎。

## 4. 能力缺口（当前链路不支持什么）

需要、但 **尚未实现** 的能力：

| 能力 | 说明 | 当前状态 |
|---|---|---|
| **派生图重构** | 以某张原图（通常是结果页）为唯一真源，让 GPT Image **构造一张语义不同的新图**，而非仅裁切/竖屏化 | ❌ 无 |
| **LOGO 抽离** | 从 VI 结果板中提取干净 LOGO 单体（透明底或纯色底） | ❌ 无 |
| **LOGO → VI 中间态** | 基于同一品牌 LOGO，生成“正在延展”或“已延展完成”的 VI 画面（可与原结果图对齐） | ❌ 无 |
| **分镜级派生任务** | 在 `visual_track` / planner 中声明 `material_task: extract_logo` / `derive_from: <asset_id>` 等，并由专用步骤产出新 asset | ❌ 无 |
| **叙事型前段模板** | 功能种草类文案自动选“概念演绎”前段，而非默认网站三连截图 | ❌ 无 |

现有 `prepare_gpt_image_keyframes.py` 的 prompt 策略是 **保真转格式**（`preserve` / `do not invent`），与 **创造性重构**（`extract` / `isolate` / `reconstruct`）方向相反。需要新的任务类型、prompt 模板、资产注册与 QA 规则，不能复用现有 site/result keyframe 逻辑硬套。

## 5. 建议实现方向（待做）

### 5.1 新步骤（命名待定）

在 `prepare_gpt_image_keyframes.py` 之外增加派生图步骤，例如：

```text
video_project.json
  -> prepare_gpt_image_derived_assets.py   # 新脚本
  -> video_project.gpt_image.json          # 含派生 asset + 原 asset 溯源
  -> apply_effect_plan.py
  -> render_simple_ffmpeg.py
```

### 5.2 派生任务类型（初版）

| `derive_kind` | 输入 | 期望输出 | 典型用途 |
|---|---|---|---|
| `logo_isolate` | VI 结果图 | 单 LOGO，干净背景 | 口播「一个简单 LOGO」 |
| `logo_to_vi_reveal` | 结果图 + 可选 logo_isolate 输出 | 完整 VI 板或“延展中”态 | 口播「延展成整套 VI」 |
| `product_one_click` | 参数页或生成页截图 | 强调“零提示词/一键”的竖屏产品画面 | 口播「不需要写提示词」 |

每个派生 asset 应记录：

- `source_asset_id` / `source_workflow_step`
- `derive_kind`
- `prompt` + `provider` receipt
- `semantic_binding.step_kind`（如 `logo` / `vi_reveal` / `product_demo`）
- QA：`logo_matches_result_brand`、`no_invented_text` 等

### 5.3 编排层

- Planner / `build_video_project` 需能根据 **文案意象**（非仅 feature 路径）选择前段素材策略。
- 对 `single_feature_seed` + VI 种草文案，默认前段走 **结果页派生**，网站截图降为可选证据镜或后置。
- `visual_intent` 与 `locked_asset_ids` 需一致；避免 intent 写 LOGO 延展却锁首页截图。

### 5.4 与特效的关系

派生图解决 **画什么**；`apply_effect_plan.py` 解决 **怎么动**。  
例如：`logo_isolate` 可用 `drop_bounce`，`logo_to_vi_reveal` 可用 `wipe_reveal` 或后续专用转场——但前提是先有正确的派生素材。

## 6. 验收标准（针对本案复跑）

用 `cases/vi_seed_effects_20260710` 或同文案新 case 验收：

1. 前 1–2 镜画面为 **LOGO 单体 / LOGO→VI**，与 `seg_001` 口播一致。
2. 第 3 镜承接「一键生成」，而非重复网站导航。
3. 派生 LOGO 与后面 `vis_004+` 结果案例 **同一品牌**，形成闭环。
4. 派生图可追溯：每个新 asset 能指回 `assets/results/` 中的源结果图。
5. 不破坏现有 site keyframe / result keyframe 流程（新能力为增量路径）。

## 7. 非目标（本 TODO 不做）

- 不在本阶段改 `vi_fx_v3` 成片（讨论记录 only）。
- 不替代 CDP 网站截图采集；网站证据仍可后置使用。
- 不要求一次性支持所有 derive_kind；优先 `logo_isolate` + `logo_to_vi_reveal`。

## 8. 行动项 checklist

- [ ] 定义 `derive_kind` 枚举与 asset schema 扩展（`image_resource.derive_kind` / `derived_from`）
- [ ] 新增 `prepare_gpt_image_derived_assets.py`（或扩展 keyframes 脚本的任务路由）
- [ ] 为 `logo_isolate` / `logo_to_vi_reveal` 编写专用 prompt 模板（允许重构，但仍约束品牌一致性）
- [ ] Planner 规则：VI 种草前段优先派生图策略，避免首页/入口/参数三连默认绑定
- [ ] 注册派生 asset 到 `image_resources.json` / `video_project.gpt_image.json`
- [ ] 用 `vi_seed_effects_20260710` 文案做 A/B：现有网站三连 vs 派生图前段
- [ ] 更新 `SKILL.md` / `AGENT.md` 生产流程（派生图步骤插入点）
