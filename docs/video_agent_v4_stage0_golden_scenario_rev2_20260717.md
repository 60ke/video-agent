# Video Agent V4 阶段 0：固定文案黄金执行链路（Rev2）

日期：2026-07-17

状态：阶段 0 设计稿 Rev2，待确认

上游文档：`video_agent_v4_architecture_framework_rev3_20260717.md`

本文修订 `video_agent_v4_stage0_golden_scenario_20260717.md`。旧稿保留作为审查记录，本文作为后续 Contract、Prompt 和迁移设计的唯一阶段 0 输入。

## 0. 阶段 0 的目标与边界

阶段 0 不实现 V4，也不建立完整测试体系。它使用一条固定文案，把 V4 的关键对象人工写成理想答案，并确认这些对象之间可以无歧义衔接。

阶段 0 必须回答：

1. AI 是否只负责范围与场景语义，不越权选择素材、动效、音效或帧号；
2. 每个画面槽能否明确说明素材来自查询、上游输入、关系组、派生或固定配置；
3. Gallery、流程序列、因果关系和跨场景连续性能否被统一表达；
4. 口播、字幕、画面、字幕高亮和音效能否绑定同一个词级 Anchor；
5. GPT Image 派生素材能否记录来源、加入关系组并持久化复用；
6. 最终链路是否同时覆盖封面、正文、BGM、固定片尾和交付视频。

阶段 0 不包含：

- 运行时 AI 图片审核；
- 运行时人工批准等待；
- 手工填写帧号；
- 为旧 V3 Contract 增加兼容字段；
- 用不存在的素材、音效或能力 ID 假装链路已打通。

进入项目素材库且状态为 `active` 的素材，视为已在项目外完成人工确认。运行时只检查文件、元数据、关系和 Contract 完整性。

## 1. 冻结文案与黄金覆盖范围

### 1.1 FrozenNarration

```text
想让门店设计不再等档期？打开柯幻熊猫，一个网站搞定全部设计。文化墙、门头招牌、美陈，都能一键出图。以文化墙为例，进入功能页，填上行业和风格，点击生成，一整面文化墙方案直接出来了。细节不满意？选中它继续编辑，改完直接用。还能上传实景参考图，按你的现场出效果，连施工平面图都能一并导出。设计这件事，从没这么省心。搜索柯幻熊猫，今天就试试。
```

文案在进入 TTS 前冻结。后续任何 AI 和程序模块都不得改写、删减或补充字符。

### 1.2 覆盖矩阵

| 能力 | 场景 |
|---|---|
| 网站主页开场 | s001 |
| 多分类结果 Gallery 与逐词切图 | s002 |
| Gallery 首项作为下游主素材 | s002 -> s005 |
| 文化墙功能入口 | s003 |
| 参数页花字流程序列 | s004 |
| 上游结果图重新展示 | s005 |
| 选中结果 -> 编辑页 -> 编辑后结果 | s006 |
| 参考图 -> 结果图因果展示 | s007 |
| 结果图 -> 平面图 | s008 |
| 无图片语义承接 | s009 |
| 固定片尾 | s010 |
| 完整文案驱动封面 | cover |
| TTS、BGM、SFX 与最终混音 | 全片 |

## 2. 阶段 0 冻结能力快照

以下是阶段 0 的逻辑快照。正式实现由 Capability Registry 生成同形 JSON；Prompt 不维护另一份手工枚举。

### 2.1 Category Registry

```json
[
  {"category_id": "文生图/文化墙", "name": "文化墙", "aliases": [], "scope_eligible": true},
  {"category_id": "文生图/门头招牌", "name": "门头招牌", "aliases": ["门店招牌"], "scope_eligible": true},
  {"category_id": "文生图/美陈", "name": "美陈", "aliases": [], "scope_eligible": true},
  {"category_id": "网站/主页", "name": "网站主页", "aliases": ["首页"], "scope_eligible": false}
]
```

`scope_eligible=false` 由程序在 Scope 请求前过滤，不依赖 Prompt 提醒模型排除网站主页。

### 2.2 Asset Role Registry

```json
[
  {"role_id": "site_home", "meaning": "柯幻熊猫真实网站主页", "allowed_sources": ["original", "faithful_derived"]},
  {"role_id": "feature_entry", "meaning": "具体功能入口截图或其忠实派生", "allowed_sources": ["original", "faithful_derived"]},
  {"role_id": "parameter_panel", "meaning": "具体功能参数面板", "allowed_sources": ["original", "faithful_derived", "semantic_derived"]},
  {"role_id": "result_image", "meaning": "功能结果图", "allowed_sources": ["original", "faithful_derived", "semantic_derived"]},
  {"role_id": "reference_image", "meaning": "上传到功能中的场景参考图", "allowed_sources": ["original", "semantic_derived"]},
  {"role_id": "flat_plan", "meaning": "由结果或场景导出的平面图", "allowed_sources": ["original", "semantic_derived"]},
  {"role_id": "editor_page", "meaning": "带上游结果图的编辑工作区", "allowed_sources": ["original", "semantic_derived"]},
  {"role_id": "edited_result", "meaning": "编辑后的结果状态", "allowed_sources": ["original", "semantic_derived"]},
  {"role_id": "outro", "meaning": "固定片尾素材", "allowed_sources": ["original", "faithful_derived"]}
]
```

### 2.3 Operation Intent Registry

```json
[
  {"intent_id": "select", "meaning": "选中已有对象"},
  {"intent_id": "type", "meaning": "输入文字或填写字段"},
  {"intent_id": "click", "meaning": "点击按钮或入口"},
  {"intent_id": "upload", "meaning": "上传图片"},
  {"intent_id": "generate", "meaning": "触发生成"},
  {"intent_id": "edit", "meaning": "进入或执行编辑"},
  {"intent_id": "export", "meaning": "导出结果"}
]
```

### 2.4 Claim Registry

```json
[
  {
    "claim_id": "real_website_screenshot",
    "meaning": "画面展示的是柯幻熊猫真实网站界面",
    "required_evidence": ["E0_source_evidence", "E1_faithful_derivative"]
  },
  {
    "claim_id": "feature_can_generate_result",
    "meaning": "所列功能能够生成对应结果图",
    "required_evidence": ["E0_source_evidence", "E1_faithful_derivative"]
  }
]
```

### 2.5 SFX Registry

只使用当前已注册语义 ID：

```text
typing
transition_whoosh
camera_shutter
task_complete
mouse_click
swish
```

本例使用 `douyin_common_v1` 音效素材库和 `normal` SFX Profile。Profile 只控制密度、冷却、优先级和冲突降级，不改变词级 Anchor。

### 2.6 Voice 与交付配置

```json
{
  "voice_mode": "fixed",
  "voice_profile_id": "minimax_ad_clear_01",
  "speech_rate": 1.2,
  "cover_enabled": true,
  "outro_enabled": true,
  "bgm_enabled": true,
  "canvas": {"width": 1080, "height": 1920, "fps": 30, "safe_area_profile": "douyin_v1"}
}
```

## 3. 完整执行轨迹

```text
FrozenNarration
├── [程序] fixed Voice Profile -> MiniMax TTS -> SpeechTimingLock
└── [AI] Scope Classifier -> VideoScope
      └── [AI] Scene Semantics Agent -> SceneSemanticPlan

SceneSemanticPlan
-> [程序] 文案完整覆盖、注册表、输入输出和 DAG 校验
-> [程序] 按 dependency_depth 解析素材，按 presentation_index 保持播放顺序
-> [程序] 关系组展开 / 合法派生 / 持久化注册
-> ResolvedAssetPlan
-> [程序] 动效分配 + SFX 分配 + BGM 选择

SpeechTimingLock + SceneSemanticPlan
-> [程序] AnchorCompiler
-> AnchoredTimingPlan

AnchoredTimingPlan + ResolvedAssetPlan + Motion/SFX/BGM
-> [程序] CompiledVideoTimeline
-> Remotion
-> FFmpeg
-> cover.png + body.mp4 + final/video.mp4
```

素材解析顺序和视频展示顺序是两个概念：

- `presentation_index`：由冻结文案决定，严格递增，决定播放顺序；
- `dependency_depth`：由场景依赖图计算，只决定素材解析先后。

## 4. AI 节点 1：Scope Classifier

### 4.1 System Prompt

```markdown
# Role
你是柯幻熊猫短视频的功能范围分类器。

# Goal
根据冻结文案判断视频围绕一个具体功能分类（single），还是多个具体功能分类（multiple），并确定叙事主分类。

# Inputs
- frozen_narration：不可修改的完整口播文案。
- enabled_scope_categories：本次 Run 允许选择的分类 ID、名称和别名。列表已经由程序排除不参与范围判断的展示载体。

# Allowed Decisions
- 只从 enabled_scope_categories 中选择文案明确提到或通过别名明确指代的分类。
- scope 只能是 single 或 multiple。
- primary_category_id 必须来自 category_ids。

# Forbidden Decisions
- 不得创造、改写或补全分类 ID。
- 不得把网站主页、编辑页等素材角色当成功能分类。
- 不得改写、解释或总结 frozen_narration。
- 无法可靠判断时不得猜测。

# Output Contract
只输出符合 VideoScope Schema 的 JSON 对象，不输出 Markdown、解释或额外字段。无法判断时输出 error 对象。
```

### 4.2 完整 User Input

```json
{
  "schema_version": "v4.video_scope.1",
  "frozen_narration": "想让门店设计不再等档期？打开柯幻熊猫，一个网站搞定全部设计。文化墙、门头招牌、美陈，都能一键出图。以文化墙为例，进入功能页，填上行业和风格，点击生成，一整面文化墙方案直接出来了。细节不满意？选中它继续编辑，改完直接用。还能上传实景参考图，按你的现场出效果，连施工平面图都能一并导出。设计这件事，从没这么省心。搜索柯幻熊猫，今天就试试。",
  "enabled_scope_categories": [
    {"category_id": "文生图/文化墙", "name": "文化墙", "aliases": []},
    {"category_id": "文生图/门头招牌", "name": "门头招牌", "aliases": ["门店招牌"]},
    {"category_id": "文生图/美陈", "name": "美陈", "aliases": []}
  ]
}
```

### 4.3 VideoScope Schema

成功：

```json
{
  "schema_version": "v4.video_scope.1",
  "scope": "single|multiple",
  "category_ids": ["注册表中的 category_id"],
  "primary_category_id": "category_ids 之一"
}
```

失败：

```json
{
  "schema_version": "v4.video_scope.1",
  "error": {"code": "scope_unresolved", "message": "简短原因"}
}
```

### 4.4 理想响应

```json
{
  "schema_version": "v4.video_scope.1",
  "scope": "multiple",
  "category_ids": ["文生图/文化墙", "文生图/门头招牌", "文生图/美陈"],
  "primary_category_id": "文生图/文化墙"
}
```

## 5. AI 节点 2：Scene Semantics Agent

### 5.1 职责边界

Scene Semantics Agent 只回答：

1. 文案应拆成哪些画面语义场景；
2. 每个场景需要什么分类和素材角色；
3. 素材是独立查询、复用上游输入、展开关系组还是使用固定配置；
4. 哪些原文短语是画面切入、字幕高亮或操作事件 Anchor；
5. 场景之间如何传递命名输入输出。

它不选择具体素材，不生成素材 ID，不选择动效或音效，不生成帧号，不判断素材是否存在。

### 5.2 System Prompt

```markdown
# Role
你是柯幻熊猫短视频的场景语义规划器。

# Goal
把冻结文案完整拆分为按原文顺序排列的 SceneSemanticPlan。每个场景必须声明画面结构、素材槽、素材来源方式、操作事件、场景输入输出、字幕强调和事实 Claim。

# Inputs
- frozen_narration：不可修改的完整口播文案。
- video_scope：已验证的 VideoScope。
- enabled_categories：分类 ID、名称、别名和语义说明。
- enabled_asset_roles：素材角色 ID 和语义边界。
- enabled_relation_patterns：允许使用的关系组类型、成员键和成员角色。
- enabled_operation_intents：可输出的操作事件 ID。
- enabled_claims：可声明的 Claim ID 和证据含义。
- configured_asset_keys：允许引用的固定素材配置键。

# Allowed Decisions
- 按独立画面语义切分 scenes。
- scenes 必须按原文顺序排列；所有 scene.text 顺序拼接后必须与 frozen_narration 完全一致，不得遗漏、重叠或改写字符。
- structure 只能是 single、parallel、causal、comparison、sequence。
- 每个素材槽必须从 asset_query、scene_input、relation_from_input、asset_group_query、group_member、configured_asset 中选择一种来源。
- 关系组类型和 member_key 必须命中 enabled_relation_patterns。
- 使用“它、这个、继续、基于上图”等指代时，必须通过命名 input 引用明确的上游 output。
- 识别 select、type、click、upload、generate、edit、export 操作事件，并绑定原文 phrase。
- Gallery 枚举项必须按原文顺序输出；不得为稳定末帧而重排。
- 需要字幕关键词高亮时设置 subtitle_emphasis=keyword。

# Forbidden Decisions
- 不得改写文案、输出帧号、素材文件、素材 ID、动效 ID、音效 ID或音色 ID。
- 不得输出注册表之外的分类、角色、操作事件或 Claim。
- 不得依赖“上一张图”或数组位置表达连续性。
- 不得为营销语气声明事实 Claim。
- 不得输出循环依赖。
- 不得用通用素材掩盖具体素材需求。

# Output Contract
只输出符合 SceneSemanticPlan Schema 的 JSON 对象，不输出 Markdown、解释或额外字段。无法确定的可选字段使用 null；必需字段无法确定时输出 error 对象，不得猜测。
```

### 5.3 完整 User Input

```json
{
  "schema_version": "v4.scene_semantics.request.1",
  "frozen_narration": "想让门店设计不再等档期？打开柯幻熊猫，一个网站搞定全部设计。文化墙、门头招牌、美陈，都能一键出图。以文化墙为例，进入功能页，填上行业和风格，点击生成，一整面文化墙方案直接出来了。细节不满意？选中它继续编辑，改完直接用。还能上传实景参考图，按你的现场出效果，连施工平面图都能一并导出。设计这件事，从没这么省心。搜索柯幻熊猫，今天就试试。",
  "video_scope": {
    "scope": "multiple",
    "category_ids": ["文生图/文化墙", "文生图/门头招牌", "文生图/美陈"],
    "primary_category_id": "文生图/文化墙"
  },
  "enabled_categories": [
    {"category_id": "文生图/文化墙", "name": "文化墙", "aliases": []},
    {"category_id": "文生图/门头招牌", "name": "门头招牌", "aliases": ["门店招牌"]},
    {"category_id": "文生图/美陈", "name": "美陈", "aliases": []},
    {"category_id": "网站/主页", "name": "网站主页", "aliases": ["首页"]}
  ],
  "enabled_asset_roles": [
    {"role_id": "site_home", "meaning": "柯幻熊猫真实网站主页"},
    {"role_id": "feature_entry", "meaning": "具体功能入口截图"},
    {"role_id": "parameter_panel", "meaning": "具体功能参数面板或其流程序列"},
    {"role_id": "result_image", "meaning": "功能生成结果图"},
    {"role_id": "reference_image", "meaning": "用于上传的场景参考图"},
    {"role_id": "flat_plan", "meaning": "由结果或场景导出的平面图"},
    {"role_id": "editor_page", "meaning": "带上游结果图的编辑工作区"},
    {"role_id": "edited_result", "meaning": "编辑后的结果状态"},
    {"role_id": "outro", "meaning": "固定片尾"}
  ],
  "enabled_relation_patterns": [
    {"pattern_id": "parameter_callout_sequence", "group_type": "process", "members": [{"member_key": "base", "asset_role": "parameter_panel"}, {"member_key": "stage", "asset_role": "parameter_panel"}, {"member_key": "final", "asset_role": "parameter_panel"}]},
    {"pattern_id": "editor_sequence", "group_type": "process", "members": [{"member_key": "source_result", "asset_role": "result_image"}, {"member_key": "editor_page", "asset_role": "editor_page"}, {"member_key": "edited_result", "asset_role": "edited_result"}]},
    {"pattern_id": "reference_result_plan", "group_type": "causal", "members": [{"member_key": "reference_image", "asset_role": "reference_image"}, {"member_key": "result_image", "asset_role": "result_image"}, {"member_key": "flat_plan", "asset_role": "flat_plan"}]}
  ],
  "enabled_operation_intents": ["select", "type", "click", "upload", "generate", "edit", "export"],
  "enabled_claims": [
    {"claim_id": "real_website_screenshot", "meaning": "画面是柯幻熊猫真实网站界面"},
    {"claim_id": "feature_can_generate_result", "meaning": "所列功能能够生成对应结果图"}
  ],
  "configured_asset_keys": ["default_outro"]
}
```

### 5.4 SceneSemanticPlan 核心 Contract

```json
{
  "schema_version": "v4.scene_semantics.1",
  "scenes": [
    {
      "scene_id": "s001",
      "presentation_index": 1,
      "text": "冻结文案的连续原文片段",
      "structure": "single|parallel|causal|comparison|sequence",
      "continuity_group": null,
      "slots": [
        {
          "slot_id": "场景内唯一",
          "anchor_phrase": "所属 scene.text 中的原文短语",
          "entry_policy": "scene_start|phrase_start",
          "hold_policy": "until_next_slot|scene_end",
          "category_id": "注册表 category_id 或 null",
          "asset_role": "注册表 role_id",
          "source": {
            "kind": "asset_query|scene_input|relation_from_input|asset_group_query|group_member|configured_asset",
            "input_name": null,
            "group_alias": null,
            "group_type": null,
            "member_key": null,
            "config_key": null
          },
          "subtitle_emphasis": "none|keyword"
        }
      ],
      "events": [
        {
          "event_id": "场景内唯一",
          "phrase": "所属 scene.text 中的原文短语",
          "intent": "注册表 operation intent",
          "target_slot": "slot_id 或 null"
        }
      ],
      "inputs": [
        {
          "input_name": "场景内唯一",
          "from_scene": "上游 scene_id",
          "from_output": "上游 output_name",
          "required": true
        }
      ],
      "outputs": [
        {
          "output_name": "场景内唯一",
          "bound_slot": "slot_id",
          "asset_role": "注册表 role_id"
        }
      ],
      "claims": [
        {
          "claim_id": "注册表 claim_id",
          "phrase": "承载 Claim 的原文短语",
          "quantifier": "any|all",
          "supporting_slots": ["slot_id"],
          "evidence_window": "anchor|scene_span"
        }
      ],
      "no_asset": false
    }
  ]
}
```

约束：

- `scene.text` 全量覆盖文案；
- `anchor_phrase`、event phrase、claim phrase 必须是所属 scene.text 的原文子串；
- `scene_input` 必须指定 input_name；
- `relation_from_input` 必须指定 input_name、group_type 和 member_key；关系或成员缺失时，由素材服务根据 Derivation Registry 选择合法派生器，Scene Agent 不选择技术派生类型；
- `asset_group_query` 建立 group_alias，后续 `group_member` 引用同一 alias；
- output 必须通过 bound_slot 绑定实际素材身份；
- `no_asset=true` 时 slots、inputs、outputs 和 claims 为空；
- AI 不输出字符位置。程序按 scenes 顺序和 phrase 出现顺序解析唯一字符区间。

## 6. Scene Semantics 理想响应

以下 JSON 是阶段 0 的核心理想答案。

```json
{
  "schema_version": "v4.scene_semantics.1",
  "scenes": [
    {
      "scene_id": "s001",
      "presentation_index": 1,
      "text": "想让门店设计不再等档期？打开柯幻熊猫，一个网站搞定全部设计。",
      "structure": "single",
      "continuity_group": null,
      "slots": [
        {
          "slot_id": "home",
          "anchor_phrase": "打开柯幻熊猫",
          "entry_policy": "scene_start",
          "hold_policy": "scene_end",
          "category_id": "网站/主页",
          "asset_role": "site_home",
          "source": {"kind": "asset_query", "input_name": null, "group_alias": null, "group_type": null, "member_key": null, "config_key": null},
          "subtitle_emphasis": "none"
        }
      ],
      "events": [],
      "inputs": [],
      "outputs": [],
      "claims": [{"claim_id": "real_website_screenshot", "phrase": "打开柯幻熊猫", "quantifier": "any", "supporting_slots": ["home"], "evidence_window": "anchor"}],
      "no_asset": false
    },
    {
      "scene_id": "s002",
      "presentation_index": 2,
      "text": "文化墙、门头招牌、美陈，都能一键出图。",
      "structure": "parallel",
      "continuity_group": "gallery_services",
      "slots": [
        {"slot_id": "g1", "anchor_phrase": "文化墙", "entry_policy": "phrase_start", "hold_policy": "until_next_slot", "category_id": "文生图/文化墙", "asset_role": "result_image", "source": {"kind": "asset_query", "input_name": null, "group_alias": null, "group_type": null, "member_key": null, "config_key": null}, "subtitle_emphasis": "keyword"},
        {"slot_id": "g2", "anchor_phrase": "门头招牌", "entry_policy": "phrase_start", "hold_policy": "until_next_slot", "category_id": "文生图/门头招牌", "asset_role": "result_image", "source": {"kind": "asset_query", "input_name": null, "group_alias": null, "group_type": null, "member_key": null, "config_key": null}, "subtitle_emphasis": "keyword"},
        {"slot_id": "g3", "anchor_phrase": "美陈", "entry_policy": "phrase_start", "hold_policy": "scene_end", "category_id": "文生图/美陈", "asset_role": "result_image", "source": {"kind": "asset_query", "input_name": null, "group_alias": null, "group_type": null, "member_key": null, "config_key": null}, "subtitle_emphasis": "keyword"}
      ],
      "events": [],
      "inputs": [],
      "outputs": [{"output_name": "primary_output", "bound_slot": "g1", "asset_role": "result_image"}],
      "claims": [{"claim_id": "feature_can_generate_result", "phrase": "都能一键出图", "quantifier": "all", "supporting_slots": ["g1", "g2", "g3"], "evidence_window": "scene_span"}],
      "no_asset": false
    },
    {
      "scene_id": "s003",
      "presentation_index": 3,
      "text": "以文化墙为例，进入功能页，",
      "structure": "single",
      "continuity_group": "workflow_文化墙",
      "slots": [
        {"slot_id": "entry", "anchor_phrase": "进入功能页", "entry_policy": "scene_start", "hold_policy": "scene_end", "category_id": "文生图/文化墙", "asset_role": "feature_entry", "source": {"kind": "asset_query", "input_name": null, "group_alias": null, "group_type": null, "member_key": null, "config_key": null}, "subtitle_emphasis": "none"}
      ],
      "events": [{"event_id": "open_feature", "phrase": "进入功能页", "intent": "click", "target_slot": "entry"}],
      "inputs": [], "outputs": [], "claims": [], "no_asset": false
    },
    {
      "scene_id": "s004",
      "presentation_index": 4,
      "text": "填上行业和风格，点击生成，",
      "structure": "sequence",
      "continuity_group": "workflow_文化墙",
      "slots": [
        {"slot_id": "p_base", "anchor_phrase": "填上", "entry_policy": "scene_start", "hold_policy": "until_next_slot", "category_id": "文生图/文化墙", "asset_role": "parameter_panel", "source": {"kind": "asset_group_query", "input_name": null, "group_alias": "params_sequence", "group_type": "process", "member_key": "base", "config_key": null}, "subtitle_emphasis": "none"},
        {"slot_id": "p_stage", "anchor_phrase": "行业和风格", "entry_policy": "phrase_start", "hold_policy": "until_next_slot", "category_id": "文生图/文化墙", "asset_role": "parameter_panel", "source": {"kind": "group_member", "input_name": null, "group_alias": "params_sequence", "group_type": "process", "member_key": "stage", "config_key": null}, "subtitle_emphasis": "none"},
        {"slot_id": "p_final", "anchor_phrase": "点击生成", "entry_policy": "phrase_start", "hold_policy": "scene_end", "category_id": "文生图/文化墙", "asset_role": "parameter_panel", "source": {"kind": "group_member", "input_name": null, "group_alias": "params_sequence", "group_type": "process", "member_key": "final", "config_key": null}, "subtitle_emphasis": "none"}
      ],
      "events": [
        {"event_id": "fill_fields", "phrase": "填上行业和风格", "intent": "type", "target_slot": "p_stage"},
        {"event_id": "generate", "phrase": "点击生成", "intent": "generate", "target_slot": "p_final"}
      ],
      "inputs": [], "outputs": [], "claims": [], "no_asset": false
    },
    {
      "scene_id": "s005",
      "presentation_index": 5,
      "text": "一整面文化墙方案直接出来了。",
      "structure": "single",
      "continuity_group": "workflow_文化墙",
      "slots": [
        {"slot_id": "result", "anchor_phrase": "一整面文化墙方案", "entry_policy": "scene_start", "hold_policy": "scene_end", "category_id": "文生图/文化墙", "asset_role": "result_image", "source": {"kind": "scene_input", "input_name": "featured_result", "group_alias": null, "group_type": null, "member_key": null, "config_key": null}, "subtitle_emphasis": "none"}
      ],
      "events": [],
      "inputs": [{"input_name": "featured_result", "from_scene": "s002", "from_output": "primary_output", "required": true}],
      "outputs": [{"output_name": "primary_result", "bound_slot": "result", "asset_role": "result_image"}],
      "claims": [{"claim_id": "feature_can_generate_result", "phrase": "一整面文化墙方案", "quantifier": "any", "supporting_slots": ["result"], "evidence_window": "anchor"}],
      "no_asset": false
    },
    {
      "scene_id": "s006",
      "presentation_index": 6,
      "text": "细节不满意？选中它继续编辑，改完直接用。",
      "structure": "sequence",
      "continuity_group": "workflow_文化墙",
      "slots": [
        {"slot_id": "selected", "anchor_phrase": "选中它", "entry_policy": "scene_start", "hold_policy": "until_next_slot", "category_id": "文生图/文化墙", "asset_role": "result_image", "source": {"kind": "scene_input", "input_name": "source_result", "group_alias": null, "group_type": null, "member_key": null, "config_key": null}, "subtitle_emphasis": "none"},
        {"slot_id": "editor", "anchor_phrase": "继续编辑", "entry_policy": "phrase_start", "hold_policy": "until_next_slot", "category_id": "文生图/文化墙", "asset_role": "editor_page", "source": {"kind": "relation_from_input", "input_name": "source_result", "group_alias": "editor_sequence", "group_type": "process", "member_key": "editor_page", "config_key": null}, "subtitle_emphasis": "none"},
        {"slot_id": "edited", "anchor_phrase": "改完直接用", "entry_policy": "phrase_start", "hold_policy": "scene_end", "category_id": "文生图/文化墙", "asset_role": "edited_result", "source": {"kind": "relation_from_input", "input_name": "source_result", "group_alias": "editor_sequence", "group_type": "process", "member_key": "edited_result", "config_key": null}, "subtitle_emphasis": "none"}
      ],
      "events": [
        {"event_id": "select_result", "phrase": "选中它", "intent": "select", "target_slot": "selected"},
        {"event_id": "open_editor", "phrase": "继续编辑", "intent": "edit", "target_slot": "editor"}
      ],
      "inputs": [{"input_name": "source_result", "from_scene": "s005", "from_output": "primary_result", "required": true}],
      "outputs": [{"output_name": "edited_result", "bound_slot": "edited", "asset_role": "edited_result"}],
      "claims": [], "no_asset": false
    },
    {
      "scene_id": "s007",
      "presentation_index": 7,
      "text": "还能上传实景参考图，按你的现场出效果，",
      "structure": "causal",
      "continuity_group": "workflow_文化墙",
      "slots": [
        {"slot_id": "reference", "anchor_phrase": "上传实景参考图", "entry_policy": "scene_start", "hold_policy": "until_next_slot", "category_id": "文生图/文化墙", "asset_role": "reference_image", "source": {"kind": "relation_from_input", "input_name": "shown_result", "group_alias": "reference_result_pair", "group_type": "causal", "member_key": "reference_image", "config_key": null}, "subtitle_emphasis": "none"},
        {"slot_id": "generated", "anchor_phrase": "按你的现场出效果", "entry_policy": "phrase_start", "hold_policy": "scene_end", "category_id": "文生图/文化墙", "asset_role": "result_image", "source": {"kind": "scene_input", "input_name": "shown_result", "group_alias": null, "group_type": null, "member_key": null, "config_key": null}, "subtitle_emphasis": "none"}
      ],
      "events": [{"event_id": "upload_reference", "phrase": "上传实景参考图", "intent": "upload", "target_slot": "reference"}],
      "inputs": [{"input_name": "shown_result", "from_scene": "s005", "from_output": "primary_result", "required": true}],
      "outputs": [], "claims": [], "no_asset": false
    },
    {
      "scene_id": "s008",
      "presentation_index": 8,
      "text": "连施工平面图都能一并导出。",
      "structure": "single",
      "continuity_group": "workflow_文化墙",
      "slots": [
        {"slot_id": "plan", "anchor_phrase": "施工平面图", "entry_policy": "scene_start", "hold_policy": "scene_end", "category_id": "文生图/文化墙", "asset_role": "flat_plan", "source": {"kind": "relation_from_input", "input_name": "source_result", "group_alias": "result_plan_pair", "group_type": "causal", "member_key": "flat_plan", "config_key": null}, "subtitle_emphasis": "none"}
      ],
      "events": [{"event_id": "export_plan", "phrase": "导出", "intent": "export", "target_slot": "plan"}],
      "inputs": [{"input_name": "source_result", "from_scene": "s005", "from_output": "primary_result", "required": true}],
      "outputs": [], "claims": [], "no_asset": false
    },
    {
      "scene_id": "s009",
      "presentation_index": 9,
      "text": "设计这件事，从没这么省心。",
      "structure": "single",
      "continuity_group": null,
      "slots": [], "events": [], "inputs": [], "outputs": [], "claims": [], "no_asset": true
    },
    {
      "scene_id": "s010",
      "presentation_index": 10,
      "text": "搜索柯幻熊猫，今天就试试。",
      "structure": "single",
      "continuity_group": null,
      "slots": [
        {"slot_id": "outro", "anchor_phrase": "搜索柯幻熊猫", "entry_policy": "scene_start", "hold_policy": "scene_end", "category_id": null, "asset_role": "outro", "source": {"kind": "configured_asset", "input_name": null, "group_alias": null, "group_type": null, "member_key": null, "config_key": "default_outro"}, "subtitle_emphasis": "none"}
      ],
      "events": [], "inputs": [], "outputs": [], "claims": [], "no_asset": false
    }
  ]
}
```

## 7. 程序校验与字段纠错

### 7.1 SceneSemanticPlan 校验

程序依次验证：

1. `presentation_index` 从 1 连续递增；
2. scenes 文本顺序拼接后逐字符等于 FrozenNarration；
3. 所有 phrase 可在所属 scene.text 内按顺序唯一解析；
4. category、role、intent 和 claim 命中冻结注册表；
5. source.kind 对应的必填字段完整；
6. input/output 引用存在，output.bound_slot 存在；
7. 依赖图无环；
8. Gallery 顺序与原文枚举顺序一致；
9. sequence 的 group_alias、group_type 和 member_key 自洽；
10. Claim supporting_slots 存在且证据窗口合法。

### 7.2 字段级纠错请求

```json
{
  "schema_version": "v4.field_repair.request.1",
  "original_response_sha256": "...",
  "field_path": "scenes[4].slots[0].asset_role",
  "invalid_value": "wall_result",
  "error_code": "unknown_asset_role",
  "allowed_values": ["result_image", "reference_image", "flat_plan"],
  "instruction": "只修正指定字段，不修改其他字段。"
}
```

模型必须返回：

```json
{
  "schema_version": "v4.field_repair.response.1",
  "field_path": "scenes[4].slots[0].asset_role",
  "corrected_value": "result_image"
}
```

程序确认 `field_path` 未变化后应用 JSON Patch，再执行完整校验。字段纠错耗尽后，高级模型基于原始请求和完整错误清单重建一次；仍失败则停止。

## 8. 黄金素材别名与关系组

阶段 0 使用可读的 Run 内别名，不把旧哈希 ID 暴露给 AI。正式 `asset_ref` 由迁移后的 Repository 分配。

| 别名 | 当前素材 | V4 角色 | 来源 |
|---|---|---|---|
| A0001 | 柯幻熊猫网站主页截图 | site_home | original |
| A0002 | 文化墙社区服务结果图 | result_image | original |
| A0003 | 门头招牌企业结果图 | result_image | original |
| A0004 | 美陈结果图 | result_image | original |
| A0005 | 文化墙功能入口截图 | feature_entry | original，正式执行前需解决现有重复 ID 数据问题 |
| A0006 | 文化墙参数面板截图 | parameter_panel | original |
| A0007 | 带 A0002 的编辑工作区 | editor_page | GPT Image derived |
| A0008 | A0002 编辑后结果 | edited_result | GPT Image derived |
| A0009 | A0002 对应的场景参考图 | reference_image | GPT Image derived |
| A0010 | A0002 对应平面图 | flat_plan | GPT Image derived |

关系组：

```json
[
  {
    "group_ref": "group://G0001",
    "group_type": "process",
    "category_id": "文生图/文化墙",
    "members": [
      {"member_key": "source_result", "asset_ref": "asset://A0002", "asset_role": "result_image"},
      {"member_key": "editor_page", "asset_ref": "asset://A0007", "asset_role": "editor_page"},
      {"member_key": "edited_result", "asset_ref": "asset://A0008", "asset_role": "edited_result"}
    ]
  },
  {
    "group_ref": "group://G0002",
    "group_type": "causal",
    "category_id": "文生图/文化墙",
    "members": [
      {"member_key": "reference_image", "asset_ref": "asset://A0009", "asset_role": "reference_image"},
      {"member_key": "result_image", "asset_ref": "asset://A0002", "asset_role": "result_image"},
      {"member_key": "flat_plan", "asset_ref": "asset://A0010", "asset_role": "flat_plan"}
    ]
  }
]
```

GPT Image 反推参考图可以用于“上传参考图 -> 生成结果”的功能演示。无需建立另一种场景结构，只需如实记录 `source_kind=derived`、`origin_type=gpt_image`、父素材和 prompt 血缘。

完整 causal 关系组的选择优先级：

1. 参考图与结果图均为人工导入原图；
2. 参考图为原图、结果图为合法派生；
3. 参考图由 GPT Image 从结果图反推并已注册；
4. 没有完整关系时，基于已选结果图派生缺失成员，持久化注册后重新查询。

不得从不同关系组分别猜一张参考图和结果图拼接。

## 9. ResolvedAssetPlan 理想结果

```text
s001.home      -> A0001
s002.g1        -> A0002
s002.g2        -> A0003
s002.g3        -> A0004
s003.entry     -> A0005
s004           -> 参数面板 process 组（A0006 派生并注册 base/stage/final）
s005.result    -> A0002（显式继承 s002.primary_output）
s006.selected  -> A0002
s006.editor    -> A0007（G0001）
s006.edited    -> A0008（G0001）
s007.reference -> A0009（G0002）
s007.generated -> A0002（显式继承 s005.primary_result）
s008.plan      -> A0010（G0002）
s009           -> no_asset
s010.outro     -> config.default_outro
```

显式依赖导致 A0002 多次出现，是叙事连续性，不参与独立随机选择的去重。

### 9.1 参数序列派生

页面登记信息与本次文案操作字段必须分开：

```json
{
  "derivation_type": "site_params_flower_text_frame_sequence",
  "source_asset_ref": "asset://A0006",
  "category_id": "文生图/文化墙",
  "registered_required_fields": ["由前端源码和 CDP 登记读取"],
  "spoken_operation_fields": ["行业", "风格"],
  "callout_fields": ["行业", "风格"],
  "output_members": ["base", "stage", "final"]
}
```

文案说到的字段不自动等于页面必填字段。花字内容由 `callout_fields` 决定，原页面红色星号保持不变。

base、stage、final 如果任一父素材是 E2，则整个序列不得提升为 E1。证据等级只能保持或降低，不能通过混合获得更高证据能力。

派生成功后立即通过统一 Repository 注册为 process 组，并进入当前 Run 解析上下文。无需运行时人工审核等待。

## 10. 动效与音效的程序化分配

AI 不参与本节决策。

### 10.1 动效分配

```text
s001  网站主页：从 Effect Registry 的 site_home 候选中按 seed 选择
s002  parallel Gallery：整组选择一次 SlideGallery 或同能力动效，组内方向与容器一致
s003  功能入口：入口聚焦类动效
s004  参数序列：花字渐显序列
s005  单结果图：结果细节展示
s006  编辑流程：选中 -> 编辑页 -> 编辑后结果的 process 动效
s007  causal：参考图 -> 结果图
s008  单平面图：可读性优先的单图动效
s009  no_asset：LightSweep
s010  configured outro：片尾配置决定
```

Effect Registry 中的时长是 `preferred_frames`，不是可以移动语音 Anchor 的硬限制。编译顺序：

```text
冻结词级 Anchor
-> 计算每个槽实际可用帧数
-> 选择 full / compact / instant 动效变体
-> 当前动效无法适配时改选同场景合法动效
```

不得为了满足动效最低时长延迟 Gallery 项、操作画面或字幕切入。

连续场景组共享的是视觉族、背景、主方向和节奏参数，不要求不同素材角色使用同一个 effect_id 或同一容器比例。

### 10.2 SFX 分配

```text
s002 Gallery 切换            -> swish
s003 进入功能页              -> mouse_click
s004 填写字段                -> typing
s004 点击生成                -> mouse_click
s005 结果完成                -> task_complete
s006 选中结果                -> mouse_click
s006 进入编辑                -> transition_whoosh
s007 上传参考图              -> mouse_click
s007 参考图切换到结果        -> swish
s008 导出平面图              -> camera_shutter（仅当语义被配置为导出定格）
```

操作语义音效优先于同 Anchor 的动效音效。Profile 超密度时抑制低优先级事件，不让编译失败。

## 11. SpeechTimingLock 与 AnchorCompiler

MiniMax 对完整 FrozenNarration 单次合成，输出不可变 `SpeechTimingLock`：

```text
TokenTiming
PauseEvent
BeatSpan
duration_frames
```

Scene Semantics 不输出帧号。AnchorCompiler 使用 `anchor_phrase`、event phrase 和 claim phrase，在 SpeechTimingLock 的 Token 中按场景顺序定位，产生 `AnchoredTimingPlan`。

每个 Anchor 可以同时绑定：

```text
画面槽切入
操作事件
字幕 Cue
字幕关键词高亮
SFX 峰值
Claim 证据窗口
```

例如：

```text
“文化墙”     -> A0002 切入 + 黄色字幕 + swish
“门头招牌”   -> A0003 切入 + 黄色字幕 + swish
“美陈”       -> A0004 切入 + 黄色字幕 + swish
“选中它”     -> A0002 选中态 + mouse_click
“继续编辑”   -> A0007 切入 + transition_whoosh
```

AnchorCompiler 自动生成全部帧号，阶段 0 和正式运行都不允许手工回填。

## 12. Claim 编译

单素材 Claim：在 Anchor 可见窗口中验证 supporting slot 的实际素材证据。

Gallery 集合 Claim：

```json
{
  "claim_id": "feature_can_generate_result",
  "quantifier": "all",
  "supporting_slots": ["g1", "g2", "g3"],
  "evidence_window": "scene_span"
}
```

表示三个 supporting slot 都必须在该场景跨度内展示过合格证据，不要求在“都能一键出图”发音瞬间同时出现在画面上。

E0 只说明素材是原始导入，不能自动证明任意 Claim。素材入库时必须登记可支撑 Claim，或由迁移规则把已确认的 `curated_result_image` 映射到 `feature_can_generate_result`。E2 参考图和编辑图不承担事实 Claim，但可以正常用于功能流程演示。

## 13. 封面、BGM、片尾与交付

### 13.1 封面

封面生成输入必须包含：

- 完整 FrozenNarration；
- VideoScope；
- 主分类；
- 柯幻熊猫品牌 IP 与 Logo 固定引用；
- 已选代表性结果图候选；
- 抖音安全区配置。

不得只使用文案首句推断标题，不得从客户案例结果图识别品牌 Logo。

### 13.2 BGM 与混音

BGM 由配置和视频语气选择，最终 FFmpeg 混音包含：

```text
TTS 主声道
BGM
SFX events
固定片尾音频（如有）
```

词级 Anchor 只约束 TTS、画面、字幕和 SFX；BGM 不参与语义卡点，但必须服从主声道 ducking 和最终响度配置。

### 13.3 最终产物

```text
cover.png
body.mp4
final/video.mp4（正文 + 固定片尾）
run_manifest.json
ai_requests/scope_request.json
ai_requests/scope_response.json
ai_requests/scene_semantics_request.json
ai_requests/scene_semantics_response.json
speech_timing_lock.json
anchored_timing_plan.json
resolved_asset_plan.json
compiled_video_timeline.json
```

所有路径在产物中使用 case 相对路径或对象引用，不写宿主机绝对路径。

## 14. 阶段 0 Pass B

Pass B 是一次真实黄金链路构造，不是手工补帧或运行 AI 图片审核：

1. 使用 FrozenNarration 调用真实 MiniMax，冻结 SpeechTimingLock；
2. 将本文两份完整 AI 请求和理想响应保存为 fixture；
3. 由 AnchorCompiler 自动生成 AnchoredTimingPlan；
4. 将当前素材通过迁移别名映射成 A0001-A0010；
5. 由程序生成 ResolvedAssetPlan 和 CompiledVideoTimeline；
6. 记录所有无法进入正式 Contract 的字段差异，修订 V4 Contract，不修改黄金语义去迁就旧实现。

阶段 0 完成条件：四个核心对象之间无隐式猜测。

```text
SceneSemanticPlan
-> ResolvedAssetPlan
-> AnchoredTimingPlan
-> CompiledVideoTimeline
```

## 15. 后续正式设计输入

阶段 0 确认后，正式设计按以下顺序展开：

1. VideoScope、SceneSemanticPlan、字段纠错 Contract；
2. Scope 与 Scene Semantics Prompt 模板和请求导出规范；
3. Capability Registry 与素材领域 Contract；
4. Repository、SQLite、ObjectStore 和迁移命令；
5. 素材选择、关系展开、GPT Image 派生和持久化；
6. Effect、SFX、SFX Profile、Voice、Operation Intent 和 Derivation Registry；
7. SpeechTimingLock、AnchorCompiler、AnchoredTimingPlan 与现有编译器接入；
8. V4 主线切换及旧单体 Planner 删除。
