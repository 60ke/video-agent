# Video Agent 架构审查与重构建议

> 审查日期：2026-07-10  
> 审查范围：当前仓库的素材注册、视觉规划、文案、Minimax 语音与时间戳、字幕、项目构建、GPT Image、特效、FFmpeg 渲染、封面、QA、CDP 素材采集及现有案例。  
> 目标：不考虑旧链路兼容性，以更准确的卡点、更可靠的图文匹配和更好的视觉效果为唯一判断标准。  
> 本文只给出审查和重构建议，不包含代码修改。

## 1. 结论摘要

当前方向已经比早期浏览器录屏方案正确很多，但还没有形成真正闭环的“视频编译系统”。它更像一组能串起来运行的脚本：数据字段很多、规则很多、文档很多，但最终渲染器真正执行的能力远少于 JSON 声明的能力，最终特效版又绕开了基础生产链的部分质量门禁。

建议不要继续在现有 `video_project.json -> video_project.gpt_image.json -> video_project.effects.json` 上叠功能。应直接进入一次 V3 重构：

```text
真实素材
-> 唯一素材目录与证据事实
-> 锁定视觉计划
-> 仅基于视觉计划生成口播
-> Minimax 真实语音与 word timing
-> 语义卡点编译器
-> 唯一 render_plan.json
-> 镜头模板/场景图渲染器
-> 最终成片级 QA
```

核心判断如下：

| 结论 | 建议 |
| --- | --- |
| 视觉先行、再写文案 | 保留，这是当前最正确的设计 |
| 结果图保存后注册，不用结果页截图冒充 | 保留并加强来源证明 |
| Minimax `subtitle_type=word` | 保留，但必须取消静默比例回退 |
| FFmpeg 最终编码、ASS 字幕 | 保留，稳定且可控 |
| CDP 只负责素材采集 | 保留，彻底删除历史录屏产物 |
| GPT Image 重绘网站 UI 并直接标记为已验证 | 重做，网站 UI 原像素必须保真 |
| 每个画面按规则硬套一个特效 | 重做为“镜头模板 + 语义 cue” |
| 三份派生 `video_project` | 删除，改成一次编译得到唯一渲染计划 |
| 29 个平铺脚本互相调用 | 重构成领域包和单一 CLI/DAG |
| 当前 JSON Schema | 删除后重建，现有 schema 与运行产物不一致 |
| 当前机器 QA | 只适合作为基础检查，不能代表视觉验收 |

## 2. 当前真实链路

仓库文档描述的主链路大体正确，但真实执行分成了四条相互改写数据的子链路：

```text
素材链：
assets/sites + assets/results
-> asset_manifest.json + image_resources.json

语义链：
planner context
-> visual_plan.json
-> video_script.json

基础生产链：
video_script.json
-> voice_plan.json
-> Minimax voice/alignment
-> subtitle_track.json
-> video_project.json
-> video_project.gpt_image.json
-> 基础视频 + contact sheet + QA

最终视觉链：
video_project.gpt_image.json
-> video_project.effects.json
-> 特效视频
-> 可选封面再次修改视频
```

这里最大的问题不是脚本数量，而是“最终交付物”没有一条唯一的、带完整质量门禁的生产路径。

## 3. 必须优先解决的问题

### P0-1：最终特效版绕开了完整 QA

`run_pipeline_mode.py` 负责语音、字幕、基础项目、GPT 关键帧、基础渲染、contact sheet 和 QA；文档随后要求再运行 `render_with_effects.py` 生成正式特效版。

但 `render_with_effects.py` 只执行：

```text
apply_effect_plan
-> prepare_effect_assets
-> render_simple_ffmpeg
```

它没有再次执行：

- 严格项目校验；
- 结果 receipt 绑定；
- 字幕密度检查；
- 最终 contact sheet；
- 最终 render QA；
- 特效峰值帧和字幕遮挡检查。

因此目前可能出现“基础版通过 QA，真正交付的特效版没有通过 QA”的情况。

建议：只保留一个生产入口。所有关键帧、特效、音频混合、封面和片尾都在同一个 run DAG 内完成，QA 必须针对最终字节文件执行。

### P0-2：字级对齐失败时静默退化为比例分配

`scripts/build_subtitle_track.py:214-215` 在 Minimax 文本无法精确匹配时，会按各段字符数比例分配整段音频时长，只写一条 warning。

这意味着：

```text
正常情况：画面边界来自真实语音时间
异常情况：画面边界来自估算
```

两种情况在后续项目里看起来几乎一样，最终用户无法知道卡点已经失真。

建议：

- `strict` 模式禁止比例回退；匹配置信度不足直接失败。
- 使用 token 级序列匹配，而不是整段字符串 `find`。
- 允许标点、空格、英文大小写和同音规范化，但必须输出匹配覆盖率。
- 每个 segment 记录 `alignment_confidence`、`matched_token_range`、`timing_source`。
- 只有草稿模式允许 fallback，并在画面上/报告中明确标记为估算时间轴。

### P0-3：当前“卡点”只卡到字幕段起点，没有卡到语义词

现在一个 script segment 对应一个 visual event，特效统一从 visual group 开头播放。比如一句话里先说“打开功能”，后说“看五个行业结果”，画面和特效不能在“行业结果”这个词出现时精确触发。

结果 gallery 也只是按总时长平均分图，`sequence.min_item_duration` 和 `max_item_duration` 没有真正驱动渲染；每张图没有绑定对应的词或短语。

建议新增语义卡点编译器：

```text
narration emphasis cue
-> 在 Minimax word timing 中定位短语
-> 生成绝对时间
-> 加入视觉预提前量
-> 可选吸附到最近音乐节拍
-> 输出 frame-aligned render cue
```

默认规则建议：

| 事件 | 时间策略 |
| --- | --- |
| 新镜头进入 | 对应短语前 100-220ms |
| 红框/光标/点击脉冲 | 动作词开始前 0-80ms |
| 结果图切换 | 行业/品牌/场景词前 80-160ms |
| 重点缩放 hit | 关键词起点，误差不超过 1 帧 |
| 镜头稳定尾帧 | 最后一个词结束后至少保留 250-450ms |
| 音乐吸附 | 只允许在语义点附近 ±80ms 内吸附，不能为了踩鼓点破坏语义同步 |

### P0-4：GPT Image 输出被自动标成 `ai_verified=true`

`scripts/prepare_gpt_image_keyframes.py:498-500` 在 GPT Image 请求成功后直接写入：

```json
{
  "ai_verified_for_video": true,
  "quality": {
    "readable": true,
    "needs_review": false,
    "ai_verified": true
  }
}
```

请求成功只代表生成了图片，不代表：

- UI 文字没有改错；
- 菜单项没有重绘错；
- 红框标在了正确的同名元素；
- 参数字段完整；
- 结果图内容没有变化；
- 9:16 画面真的可读。

建议把状态拆为：

```text
generated
-> machine_checked
-> vision_verified
-> human_approved（可选）
```

没有执行检查的输出只能是 `generated`，不能被 Planner 当作高优先级已验证素材。

### P0-5：网站 UI 不应继续交给 GPT 重绘

当前提示词要求 GPT Image 在保持 UI 的同时完成 9:16 排版和设计化高亮。这个目标本身互相冲突：生成模型擅长重构视觉，不擅长像素级保持中文 UI。

更合适的方案是：

```text
CDP 原始截图（不可变纹理）
+ DOM 目标框/面板框
+ 确定性 9:16 transform
+ 程序化矢量高亮/光标/点击反馈
+ 可选 GPT 生成的纯背景或装饰层
```

重点不是回到过去简单的程序红框，而是让 callout 也成为设计系统：圆角高亮框、聚光蒙版、角标、光标、点击波纹、细箭头、标签都可以程序化且更美观。只要高亮框与截图共享同一变换矩阵，坐标不会再错位。

GPT Image 可以继续用于：

- 不含网站 UI 的封面背景；
- 纯抽象包装帧；
- 原图之外的背景延展；
- 特效辅助纹理；
- 不承担证据的装饰层。

网站 UI 和结果图主体应始终以原始像素叠在最上层，不能被生成模型重画。

### P0-6：JSON 声明了渲染器没有实现的能力

当前 `video_project` 声明了 `layout`、`display_mode`、`display_rule`、`sequence`、`audio_tracks` 等字段，但执行器存在明显落差：

- `scripts/render_simple_ffmpeg.py:281-282` 的 `compose_single_image()` 完全忽略 `layout`，所有单图都调用同一个 `fit_width_on_canvas()`。
- `portrait-showcase`、`result-showcase`、`full-width` 对单图的最终构图没有区别。
- `sequence.min_item_duration`、`max_item_duration` 没有参与帧选择，序列只是平均切分。
- `audio_tracks` 被校验、被写入项目，但渲染器只映射旁白音频，没有混入 BGM/SFX。
- `display_rule` 只存在于数据层，渲染器不执行。

这会误导 Planner：它以为自己选择了不同构图，实际上视频没有变化。

建议：删除所有未实现字段。每一个保留字段必须有渲染实现、schema 校验、golden frame 测试和 QA 规则。

### P0-7：15-20 秒规则没有进入主流水线

仓库已经新增 `check_subtitle_density.py`，但 `run_pipeline_mode.py` 没有调用它。实际案例中：

- `cases/logo_showcase_new` 约 38.677 秒、237 字；
- `cases/logo_effects_fullregen_20260709_1742` 约 42.191 秒；
- 两者都明显超过文档的 15-20 秒目标。

`accept_planner_output.py` 只限制“最低语速”，没有限制总字数、总时长和每个镜头的信息负担，因此长文案仍会进入生产。

建议在生成语音前就执行文案预算：

```text
目标 18s
-> 预留 0.4s 开头/收口缓冲
-> 按 speed=1.2 的历史实测字速计算总字数预算
-> 按视觉 beat 分配字数
-> 超预算直接要求重写
```

字幕密度检查必须是 `standard` 和 `strict` 的硬门禁，而不是可选说明文档。

### P0-8：Minimax 默认速度与既定要求不一致，情感字段未接通

此前约定默认速度为 1.2，但 `scripts/generate_voice_minimax.py:15` 当前默认是 1.5，本地配置未显式覆盖 speed，因此实际会使用 1.5。

同时 `video_script.voice_style` 没有映射到 Minimax `emotion` 或其他 prosody 配置；本地配置也没有 emotion。当前“快节奏、清晰、种草”只是文本元数据，对声音没有作用。

建议：

- 默认 speed 明确固定为 1.2，并写进每次 run manifest。
- `narration.json` 增加受控的 `prosody_profile`，例如 `calm_demo`、`energetic_seed`、`professional_review`。
- profile 映射到允许的 voice、speed、emotion、pitch、pause policy。
- 第一阶段先整条视频统一 prosody，避免逐段生成导致声音接缝。
- 以后需要 hook/CTA 情绪变化时，再支持少量分段 TTS 和交叉淡化。

### P0-9：当前 voice QA 不是独立的发音校验

`check_voice_qa.py` 把 Minimax 返回的 subtitle/alignment 文本当作 `asr_text`，再检查高风险词是否存在。该文本来自同一次 TTS 请求，不是对生成音频重新识别，因此无法证明实际发音正确。

建议二选一：

1. 把这项检查准确命名为 `provider_alignment_text_check`，不要称为 ASR；
2. 对品牌名、英文缩写和高风险词运行独立 ASR/音素检查，才作为 pronunciation QA。

## 4. 重要但次一级的问题

### P1-1：特效按素材类别硬套，缺少镜头语法

当前默认映射基本是：

```text
首页/入口 -> drop_bounce
参数页 -> wipe_reveal
结果图 -> tile_drop 或 radial_unfurl
普通图 -> pop_in
```

这会导致所有视频快速同质化，而且特效与文案中的动作、关键词和图片构图没有关系。结果图被切成 4x4/5x5 小块时，首秒内容不可读；入口整屏下落也不一定符合真实操作语义。

建议从“effect 名称”升级为“shot template”。特效只是镜头模板内部的一部分，Planner 选择的是叙事镜头，而不是底层动画函数。

### P1-2：素材多，但 Builder 经常只取第一张

`choose_asset_ids()` 即使收到多个 `locked_asset_ids`，只有当 `material_task` 或 `visual_intent` 命中 gallery/grid 等词时才保留多图，否则只返回第一张。

这会让视觉计划锁了多张结果图，但最终项目只展示第一张。多图是否使用不应依赖自然语言 token，应由明确的 `shot_template` 和 `asset_slots` 决定。

### P1-3：素材语义把所有第三级标签都硬编码成 industry

当前结果图命名解析把功能后的标签统一写为 `industry_label/scene_label`。但最新 VI 素材里的 `半克星球`、`TATA木门`、`八马茶业` 实际是品牌案例，不是行业。

这也是新增 `_vi_brand_index.json` 的根本原因：通用模型无法表达 feature-specific taxonomy。

建议改为通用 facet：

```json
{
  "feature_path": ["文生图", "VI"],
  "facet": {
    "kind": "brand_case",
    "label": "TATA木门"
  }
}
```

`facet.kind` 可取：`industry`、`scene`、`brand_case`、`style`、`product_category`、`campaign_type`。文件名仍使用中文，不需要恢复复杂目录层级；类型由 feature profile 决定。

### P1-4：Planner 上下文重复且存在规则冲突

`prepare_planner_context.py` 同时放入：

- compact assets；
- 完整 `image_resources`；
- `site_asset_pool`；
- `material_understanding`；
- website/profile 信息；
- prompt 全文；
- copywriting rules/options 大段截取。

同一素材信息重复多次，既浪费上下文，也容易让模型抓错字段。

更严重的是规则冲突：

- `script_director.md:54-57` 禁止旁白念“点击、选择、上传、填写”；
- `copywriting-rules.md` 又强制“三句话演示：丢进去、选参数、点生成”。

当前程序没有最终文案规则裁决，`TODO.md` 也承认缺少程序化 guard。实际案例仍出现“打开、找到、输入、选行业、点开始生成”。

建议：上下文按阶段最小化，品牌话术先编译成当前视频可用的短规则，再交给模型；冲突规则必须由程序明确优先级。

### P1-5：Schema 和运行时校验是两套系统

`schemas/video_project_v2.schema.json` 要求 `schema_version=2`，实际 Builder 输出 `schema_version=1`；schema 未被任何 Python 代码加载。`material_manifest.schema.json` 和 `material_groups.schema.json` 也没有驱动当前 `asset_manifest.json`。

当前真实契约散落在：

- JSON Schema；
- `accept_planner_output.py`；
- `build_video_project.py`；
- `validate_video_project.py`；
- `render_simple_ffmpeg.py`；
- 各 Markdown prompt。

建议用一套代码模型作为唯一契约来源，例如 Pydantic v2：

```text
Python model
-> 运行时校验
-> 自动生成 JSON Schema
-> 自动生成 Planner 允许字段摘要
```

### P1-6：派生项目文件会造成隐式状态和选错版本

当前同一个 case 可能同时存在：

```text
video_project.json
video_project.gpt_image.json
video_project.effects.json
```

不同 wrapper 根据“哪个文件存在”选择输入，封面 wrapper 甚至默认挑最新 mp4。这会让一次运行受到上次残留文件影响，也可能给错误版本加封面。

建议每次运行使用不可变 run 目录：

```text
runs/<run_id>/
  input_snapshot.json
  render_plan.json
  artifacts.json
  final.mp4
  qa_report.json
```

case 根目录只保留 `current_run.json` 指向明确接受的版本。缓存按输入内容 hash 判断，不使用 mtime。

### P1-7：没有自动化测试和 Python 依赖清单

仓库当前没有标准 tests 目录，也没有 `pyproject.toml` 或 requirements 锁定。`check_effect_timing.py` 是手写自检脚本，无法覆盖核心风险。

建议至少建立：

- schema/model 单元测试；
- 字幕 fuzzy alignment 测试；
- cue compiler 属性测试；
- 每个 shot template 的 golden frame 测试；
- 同素材连续镜头不闪屏测试；
- 30fps 边界和音画时长测试；
- 一个 8-12 秒离线 E2E fixture；
- CDP 文件名和坐标变换测试。

### P1-8：历史产物仍占用大量空间

当前本地统计：

| 路径 | 文件数 | 大小 |
| --- | ---: | ---: |
| `cdp-capture/output` | 22523 | 约 4168.3 MB |
| `cdp-poc` | 5345 | 约 946.6 MB |
| `cases` | 2925 | 约 846.4 MB |
| 根 `output` | 397 | 约 70.6 MB |

`cdp-capture/output` 中仍是已放弃的录屏、CFR 帧和 timeline 产物。虽然被 gitignore 忽略，但会拖慢检索、备份和本地操作。

建议确认不再需要回看后直接清理；`cdp-poc` 只剩历史 output/profiles，也应整体移除。

## 5. 建议的目标架构

### 5.1 六个核心产物

V3 不再让每个脚本自由扩展 JSON，只保留六个正式产物：

| 产物 | 责任 | 是否人工/AI 审核 |
| --- | --- | --- |
| `case.json` | 用户目标、平台、功能、时长、声音和封面要求 | 输入确认 |
| `asset_catalog.json` | 唯一素材目录、证据、分类、锚点、来源和质量状态 | 素材 QA |
| `visual_plan.json` | 锁定 beat、素材、可说/不可说事实、镜头模板 | 必须审核 |
| `narration.json` | 只写口播、关键词 cue、prosody，不重复选材 | 必须审核 |
| `render_plan.json` | 音频生成后编译出的绝对时间轴和可执行场景图 | 程序生成 |
| `run_manifest.json` | 输入 hash、工具版本、模型参数、产物和 QA | 程序生成 |

`subtitle_track.json`、Minimax raw payload 等可以作为 run 中间产物，但不再与正式语义契约并列。

### 5.2 单一素材目录

合并 `asset_manifest.json` 和 `image_resources.json`，避免同一素材在两处复制并逐渐漂移。

建议素材记录：

```json
{
  "id": "asset_site_kx_vi_entry",
  "source": "assets/sites/柯幻熊猫_文生图_VI_功能入口截图.png",
  "kind": "site_screenshot",
  "feature_path": ["文生图", "VI"],
  "workflow_step": "feature_entry",
  "facet": null,
  "evidence": {
    "type": "real_screenshot",
    "allowed_claims": ["VI 功能入口存在"],
    "forbidden_claims": ["已生成 VI 结果"]
  },
  "anchors": [
    {
      "id": "target_feature",
      "role": "click_target",
      "label": "VI",
      "space": "source_normalized",
      "box": {"x": 0.05, "y": 0.41, "w": 0.08, "h": 0.05}
    }
  ],
  "quality": {
    "state": "machine_checked",
    "checks": ["route_match", "target_visible", "no_open_toast"]
  },
  "provenance": {
    "sha256": "...",
    "capture_tool": "cdp_material_capture",
    "captured_at": "..."
  }
}
```

### 5.3 Visual Plan 保留，但不复制字段

当前两阶段视觉先行是正确的。建议保留 `visual_plan.json`，但 `narration.json` 只通过 `visual_beat_id` 引用它，不再重复：

- asset ids；
- feature id；
- allowed/forbidden claims；
- layout intent；
- operation status。

`narration.json` 需要记录 `visual_plan_sha256`。视觉计划改变后，旧文案自动失效，避免图换了、文案还沿用。

### 5.4 语义卡点编译器

建议引入 `cue_compiler`，把自然语言 cue 编译成绝对帧时间。

规划输入示例：

```json
{
  "visual_beat_id": "beat_result_traffic",
  "text": "交通出行，风格稳重利落。",
  "emphasis_cues": [
    {
      "phrase": "交通出行",
      "action": "asset_switch",
      "lead_ms": 120
    },
    {
      "phrase": "稳重利落",
      "action": "camera_hit",
      "offset_ms": 0
    }
  ]
}
```

编译输出不再保留模糊短语，只保留确定时间：

```json
{
  "shot_id": "shot_004",
  "start_frame": 218,
  "end_frame": 274,
  "template": "result_full_bleed_push",
  "asset_slots": {"primary": "asset_result_logo_traffic_01"},
  "cues": [
    {"frame": 218, "action": "scene.enter"},
    {"frame": 241, "action": "camera.hit", "params": {"amount": 0.025}}
  ]
}
```

编译器必须执行：

1. phrase 到 word tokens 的 fuzzy match；
2. 匹配置信度和歧义检查；
3. lead/offset 处理；
4. 最小可读时长约束；
5. 30fps 帧量化；
6. 相邻镜头冲突求解；
7. 可选音乐 beat snap；
8. 输出 cue timing report。

### 5.5 镜头模板替代零散特效

建议第一版只实现 7 个高质量模板，不追求大量特效名：

| 模板 | 适用画面 | 核心运动 |
| --- | --- | --- |
| `ui_overview_focus` | 网站首页 | 全局建立后聚光目标入口 |
| `ui_menu_click` | 功能入口/二级菜单 | 光标移动、目标高亮、点击波纹 |
| `ui_params_walkthrough` | 参数面板 | 面板稳定展示，按 cue 依次强调字段组 |
| `ui_perspective_push_in` | 参数页/功能页 | 网格背景、UI 平面透视倾斜、拉近后稳定 |
| `result_full_bleed_push` | 单张结果图 | 左右铺满、完整保图、轻推入 |
| `result_carousel` | 多张结果图 | 每张绑定独立语义词，方向一致切换 |
| `result_mosaic_reveal` | 3-4 张结果总结 | 先单图，再组成可读拼图，不切碎文字 |

用户前面给出的“倾斜拉近”效果应落在 `ui_perspective_push_in`，不是普通 motion：

```text
深色网格背景
-> 截图作为不可变 UI 平面
-> 真实四点透视变换
-> 起始小比例、较大 yaw/roll
-> 0.8-1.2s 拉近并减小倾斜
-> 阴影、边缘光、轻微景深
-> 最后稳定 0.5s 供阅读
```

这个模板应使用 OpenCV/NumPy 的 perspective warp 或等价矩阵实现；不能只用旋转加缩放伪装透视。

### 5.6 场景图渲染器

建议保留 FFmpeg 编码，但把当前 700 行单文件渲染器拆成确定性场景图：

```text
Canvas
├── BackgroundNode
├── ImagePlaneNode
├── CalloutNode
├── CursorNode
├── DecorationNode
└── SubtitleSafeRegion
```

每个 node 只允许经过校验的关键帧属性：

```text
position
scale
rotation
perspective_quad
opacity
blur
shadow
mask
```

渲染顺序固定为：

```text
背景
-> 原始证据图/结果图
-> 设计化 callout 与光标
-> 非证据装饰
-> 字幕
```

推荐继续使用 rawvideo -> FFmpeg 或改用 PyAV；核心不是编码器，而是场景图和镜头模板要有明确契约。

### 5.7 音频成为真正的多轨

当前 `audio_tracks` 是假能力。V3 要么删除，要么完整实现：

```text
voice
bgm
sfx_click
sfx_whoosh
sfx_hit
outro_audio
```

混音规则建议：

- 旁白为主轨，峰值和响度标准固定；
- BGM 在有旁白时自动 duck；
- 点击/切换/重点 hit 使用短 SFX，并绑定同一 cue；
- SFX 不得比画面事件早超过 1 帧；
- 片尾音频单独拼接，不参与主体卡点。

## 6. 最终 QA 应如何设计

### 6.1 时间轴 QA

| 检查 | 建议门槛 |
| --- | --- |
| 文本与 Minimax token 匹配覆盖率 | strict >= 98% |
| 语义 cue 到目标词误差 | <= 1 帧 |
| 主视频音频与画面时长差 | <= 1 帧 |
| UI 单镜头稳定可读时长 | >= 1.2s |
| 普通结果图可读时长 | >= 0.75s |
| 特效结束后的稳定尾帧 | >= 0.35s |
| fallback timing | strict 禁止 |

### 6.2 素材保真 QA

- 网站关键文字 OCR 必须与源截图一致；
- UI 平面像素差异只能来自明确缩放/透视/压缩，不允许内容生成；
- 结果图主体必须与源图 perceptual hash 对应；
- callout 与变换后的 CDP 目标框 IoU 建议 >= 0.75；
- 高亮目标必须位于中央可读区；
- 字幕不得覆盖 protected anchors。

### 6.3 视觉 QA

均匀 contact sheet 不足以检查动效。应按渲染计划抽取：

```text
每个镜头首帧
每个 transition 中点
每个 effect 峰值帧
每个 callout 激活帧
每个镜头稳定尾帧
字幕最长的帧
```

Vision QA 输入应同时包含：

- 抽取帧；
- 当前旁白/字幕；
- 预期 asset id；
- target anchor；
- allowed/forbidden claims；
- shot template 预期。

Vision 模型通过后才写 `vision_verified`。机器检查不能伪装成 AI 检查。

### 6.4 美学 QA

建议增加可量化的基础指标：

- 主体占画布比例；
- 黑边/空白比例；
- UI 最小文字高度；
- 字幕行数和宽度；
- 字幕与主体重叠率；
- 连续镜头亮度跳变；
- 运动速度和加速度峰值；
- 同一视频重复模板次数；
- 连续强特效数量。

## 7. 建议删除和合并的内容

### 直接删除

- `cdp-poc/`：只剩已废弃录屏实验产物。
- `cdp-capture/output/` 中历史 MP4、CFR frames、recording camera/narration 等约 4.17GB 产物。
- `schemas/material_groups.schema.json`：当前没有生产代码消费。
- `references/prompts/timeline_director.md`：当前生产链没有调用，时间轴实际由 Builder 生成；V3 由 cue compiler 取代。
- `scripts/check_effect_timing.py`：迁移成正式测试后删除脚本入口。
- 根目录旧 `output/` 中已经确认无复用价值的历史产物。

### 重构完成后删除

- `video_project.gpt_image.json` 和 `video_project.effects.json` 的文件级接口。
- `scripts/render_with_effects.py` 和 `scripts/render_with_cover.py` 两个二次 wrapper，统一进单一生产 DAG。
- `scripts/register_materials.py`、`register_site_assets.py`、`register_result_assets.py` 的重复框架，合并成统一 catalog importer。
- `material_driven_video_refactor_plan.md`：内容合并到新架构文档后删除。
- `docs/pipeline_v2_refactor.md`：V3 落地后改为简短架构说明，不再保留历史叙事。
- 当前手写 schema 和 `validate_video_project.py` 的重复契约，改由领域 model 生成。

### 必须保留

- `cdp-capture` 的 profile 登录、登录态检查、页面稳定检测、截图、表单解析和 DOM 坐标提取。
- 中文文件命名与 `文生图 -> 图文广告 -> 子功能` 路径规则。
- visual-first / evidence-bound planning。
- result receipt 与真实结果来源约束。
- Minimax 原始 payload 和 word timing 存档。
- FFmpeg 编码、ASS 字幕风格、片尾独立追加。
- contact sheet 概念，但升级为 cue-aware QA frames。

## 8. 建议的代码组织

不要继续把业务代码平铺在 `scripts/`。建议结构：

```text
video_agent/
  cli.py
  domain/
    models.py
    policies.py
    errors.py
  assets/
    catalog.py
    filename_parser.py
    site_importer.py
    result_importer.py
    quality.py
  planning/
    visual_plan.py
    narration.py
    cue_compiler.py
  audio/
    minimax_client.py
    alignment.py
    prosody.py
    mixer.py
  render/
    engine.py
    scene_graph.py
    transforms.py
    subtitles.py
    templates/
      ui_overview_focus.py
      ui_menu_click.py
      ui_params_walkthrough.py
      ui_perspective_push_in.py
      result_full_bleed_push.py
      result_carousel.py
      result_mosaic_reveal.py
  qa/
    timing.py
    fidelity.py
    layout.py
    render.py
  orchestration/
    pipeline.py
    cache.py
    run_manifest.py

tools/
  cdp_capture/

tests/
  unit/
  golden/
  e2e/
```

对外只暴露少量命令：

```text
video-agent assets sync
video-agent plan
video-agent build
video-agent qa
video-agent run
```

## 9. 推荐实施顺序

### 阶段 1：先修正确性，不做新特效

1. 把 Minimax 默认 speed 恢复为 1.2，并显式记录 prosody。
2. 把 subtitle density 接入 standard/strict 硬门禁。
3. strict 禁止 proportional timing fallback。
4. 最终特效版进入同一条 QA 链。
5. 停止自动写 `ai_verified=true`。
6. 给现有文化墙、LOGO/VI 各选一个 10-15 秒 golden case。

完成标准：同一输入重复运行，时间轴和程序画面逐帧一致；失败不会被包装成 warning 继续交付。

### 阶段 2：建立唯一数据契约

1. 建立 Pydantic domain model。
2. 合并素材目录。
3. 清理 `video_project.*` 派生链。
4. 引入 immutable run directory 和 content-hash cache。
5. 删除未执行字段和死 schema。

完成标准：任一渲染字段都能追踪到唯一 model、唯一校验器和唯一执行代码。

### 阶段 3：实现语义卡点编译器

1. narration 增加 emphasis cues。
2. 实现 fuzzy token alignment。
3. 生成绝对 frame cues。
4. 多图逐张绑定 cue phrase。
5. 增加 speech-first、music-second 的吸附策略。

完成标准：每次图切、点击、缩放 hit 都能说明“对应哪一个词、哪一帧”。

### 阶段 4：重做视觉系统

1. 实现场景图与变换矩阵。
2. 先做 `ui_perspective_push_in`、`ui_menu_click`、`result_carousel` 三个模板。
3. 网站截图改为原图纹理 + 矢量 callout。
4. 实现真实多轨音频和 SFX cue。
5. 为每个模板建立 golden frames。

完成标准：网站 UI 零内容重绘，结果图主体零内容改写，镜头运动稳定且可复用。

### 阶段 5：视觉验收闭环

1. cue-aware frame extraction。
2. OCR/坐标/图像保真检查。
3. Vision QA。
4. 自动产出失败原因和可重跑阶段。
5. 只把最终效果版标记为 deliverable。

## 10. 最终验收指标

重构是否成功，不看新增了多少脚本或特效，而看以下指标：

| 维度 | 验收目标 |
| --- | --- |
| 图文匹配 | 每句旁白都能追溯到锁定素材和 allowed claim |
| 卡点 | 关键词 cue 与视觉事件误差 <= 1 帧 |
| 素材保真 | 网站关键文字 100% 保留，结果主体不被生成模型改写 |
| 时长 | 默认功能种草 15-20s，超过 24s 直接失败 |
| 信息量 | 多行业/多场景文案必须逐图绑定，不用一张图代替多个结论 |
| 视觉效果 | 每个镜头使用明确模板，强特效不连续堆叠 |
| 可读性 | UI 主体、callout、字幕无冲突，手机缩略观看仍可辨识 |
| 可复现性 | 同一 render plan 逐帧确定性一致 |
| 可追溯性 | 最终 MP4 能追溯到输入 hash、素材 hash、模型参数和 QA 报告 |
| 交付门禁 | 只有最终带特效/封面/片尾的文件通过 QA 后才能交付 |

## 11. 最终建议

不建议继续在当前 V2 上增加第八、第九个独立 effect。当前最缺的不是特效数量，而是三个基础能力：

1. 语音关键词到视觉事件的真正 cue 编译；
2. 不重绘证据图的高质量镜头模板；
3. 只针对最终成片执行的严格 QA。

把这三件事完成后，倾斜拉近、点击聚焦、参数巡览、多结果轮播等效果都会变成可复用、可控、可卡点的镜头语言。否则继续增加特效只会让不准确的时间轴和素材状态变得更花哨。
