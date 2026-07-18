# Video Agent V4 Stage 1：语义 Contract 与 AI Runtime 正式设计

日期：2026-07-17

状态：正式设计 v1

权威上游：

- `video_agent_v4_architecture_framework_rev3_20260717.md`
- `video_agent_v4_stage0_golden_scenario_rev3_20260718.md`

本文是 V4 八项正式设计中的第 1、2 项，并补齐二者实施所必需的 AI Runtime：

1. `VideoScope`、`SceneSemanticPlan` 和字段纠错 Contract；
2. Scope、Scene Semantics Prompt 和请求导出规范；
3. 两个 AI 节点的异步调度、模型路由、重试、追踪和产物冻结边界。

本文不设计素材数据库表、动效配置细节、GPT Image Prompt、时间编译器实现或 Remotion 组件。它只定义这些模块能够稳定消费的语义输入。

## 1. 已冻结的架构决定

### 1.1 只有两个固定 AI 节点

```text
Scope Classifier
Scene Semantics Agent
```

它们是无状态、单次、结构化模型调用，不是互相聊天的自治角色。

以下能力不是固定 Agent：

- 多候选素材语义排序；
- 缺失素材的派生决策和 GPT Image Prompt；
- Goal 模式文案生成；
- 自动音色排序；
- 封面语义规划。

这些是由后续阶段按条件调用的 AI Capability，不参与 Stage 1 主 Contract。

### 1.2 Python Orchestrator 拥有流程控制权

AI 不决定：

- 下一个节点执行什么；
- 是否并行；
- 素材 ID；
- 动效 ID；
- 音效 ID；
- 帧号；
- 重试次数；
- 模型升级；
- 是否写入素材库。

以上均由显式 DAG、注册表和程序校验决定。

### 1.3 不引入 OpenAI Agents SDK

V4 使用轻量内部 Runtime：

```text
httpx.AsyncClient
+ Pydantic Contract
+ asyncio.TaskGroup
+ Provider Adapter
+ 本地 Trace Export
```

原因：当前任务是确定性 DAG，不需要模型 handoff、会话记忆或自主工具循环。保留自己的 Runtime 可以精确控制 DeepSeek JSON Mode、请求快照、字段纠错、模型升级和断点恢复。

### 1.4 AI 输出原文语义，程序绑定时间

AI 输出 `text`、`anchor_phrase`、event phrase 和 claim phrase。它们必须是冻结文案的原文子串。

程序随后使用 `SpeechTimingLock` 定位词级 Anchor，并生成：

```text
画面切入
字幕 Cue
字幕高亮
操作事件
SFX 峰值
Claim 证据窗口
```

AI 永远不输出 token ID、毫秒或帧号。

## 2. Stage 1 主流程与并行边界

### 2.1 固定音色模式

```text
FrozenNarration
├── TTS Provider --------------------------> SpeechTimingLock
└── Scope Classifier -> VideoScope
                       └── Scene Semantics -> SceneSemanticPlan

SpeechTimingLock + SceneSemanticPlan -> 后续 AnchorCompiler
```

TTS 与 Scope Classifier 可并行。Scene Semantics 依赖已验证的 `VideoScope`。

### 2.2 自动音色模式

```text
FrozenNarration
└── Scope Classifier -> VideoScope
    ├── Scene Semantics -------------------> SceneSemanticPlan
    └── Voice Ranking -> VoiceSelection -> TTS -> SpeechTimingLock
```

Scene Semantics 与 Voice Ranking 可并行。Voice Ranking 是条件 Capability，不进入本文两个固定 Agent 的 Contract。

### 2.3 Stage 1 不允许的并行

- Scene Semantics 不得在 `VideoScope` 校验完成前启动；
- 同一 Agent 的字段纠错不得与完整重建同时运行；
- 同一阶段产物不得由多个任务竞争写入；
- Trace 可以并行采集，但最终 Manifest 由单写入器提交。

## 3. 公共 Contract 约定

### 3.1 版本、指纹与严格模式

`schema_version` 和输入指纹由程序写入不可变 Artifact Envelope，不要求模型照抄：

```python
class ArtifactEnvelope(BaseModel, Generic[T]):
    schema_version: str
    input_fingerprints: dict[str, str]
    payload: T
```

持久化的 `video_scope.json` 和 `scene_semantic_plan.json` 使用 Envelope；模型响应的 `response.validated.json` 只保存经过校验的业务 payload。这样模型不会因为抄错 SHA 或版本号产生无意义纠错。

Pydantic 配置：

```python
ConfigDict(extra="forbid", strict=True)
```

AI 输出出现未知字段、隐式类型转换或注册表外 ID 时直接进入校验失败，不静默丢弃。

### 3.2 动态注册表 ID

Category、Asset Role、Operation Intent、Claim、Visual Structure 等字段在 Python 类型上使用受校验的 `str`，不写成永久 `Literal`。

合法值来自当前 Run 冻结的 Registry Snapshot：

```python
category_id: str
asset_role: str
operation_intent: str
claim_id: str
visual_structure: str
```

Pydantic 完成结构校验，Domain Validator 完成注册表存在性与启用状态校验。

### 3.3 标识符所有权

AI 可以输出当前对象内部的临时语义 ID：

- `scene_id`
- `slot_id`
- `event_id`
- `input_name`
- `output_name`

程序必须校验唯一性和引用完整性。素材 ID、关系组 ID、派生素材 ID 和 Run ID 只能由程序生成。

### 3.4 不输出 error 对象冒充业务对象

模型业务响应只允许输出目标 Contract。错误由 Runtime Envelope 表达：

```json
{
  "status": "failed",
  "failure_type": "contract_validation",
  "validation_errors": [],
  "raw_response_ref": "run://agents/.../response.raw.json"
}
```

这样可以避免 `VideoScope | ErrorObject`、`SceneSemanticPlan | ErrorObject` 污染下游类型。

## 4. VideoScope Contract

### 4.1 职责

`VideoScope` 只回答：

1. 文案聚焦一个具体功能，还是涉及多个具体功能；
2. 涉及哪些启用的功能分类；
3. 哪个功能是叙事主线或举例重点；
4. 文案属于固定脚本还是 Goal 生成脚本不属于 Scope 的职责，来源由上游 Manifest 记录。

“通用素材”不是 Scope，“网站主页”也不是 Scope。它们是后续 Scene Slot 的素材角色。

### 4.2 Schema

```python
class ScopeCategory(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    category_id: str
    mention_phrases: list[str]
    is_primary: bool


class VideoScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scope_mode: Literal["single_category", "multi_category"]
    categories: list[ScopeCategory]
```

### 4.3 不保留 confidence 和自由解释

正式 Contract 不保存模型自报 `confidence`，也不保存大段 `reasoning`。这两个字段无法作为可靠校验依据，还会增加下游分支。

可审计信息使用受控代码：

```python
scope_mode
category_id
mention_phrases
is_primary
```

原始模型响应仍完整保存在 Trace 中。

### 4.4 Domain Validation

程序必须验证：

1. `categories` 非空且 `category_id` 唯一；
2. category 存在于冻结 Category Registry 且已启用；
3. 每个 `mention_phrase` 是 FrozenNarration 原文子串；
4. `single_category` 恰好一个 category 且为 primary；
5. `multi_category` 至少两个 category；
6. primary 最多一个；
7. 文案存在明确举例重点时必须有一个 primary；
8. 别名先由程序标准化，再进行 category 校验；
9. Artifact Envelope 中的 FrozenNarration 指纹由 Runtime 根据真实输入写入。

### 4.5 理想输出示例

```json
{
  "scope_mode": "multi_category",
  "categories": [
    {
      "category_id": "文生图/文化墙",
      "mention_phrases": ["文化墙"],
      "is_primary": true
    },
    {
      "category_id": "文生图/门头招牌",
      "mention_phrases": ["门头招牌"],
      "is_primary": false
    },
    {
      "category_id": "文生图/美陈",
      "mention_phrases": ["美陈"],
      "is_primary": false
    }
  ]
}
```

## 5. SceneSemanticPlan Contract

### 5.1 职责

Scene Semantics 将完整 FrozenNarration 划分为有顺序、可依赖的语义场景，并为每个场景声明：

- 原文跨度；
- 画面结构；
- 一个或多个素材槽；
- 每个槽的具体功能分类与素材角色；
- 素材来源方式；
- 操作事件；
- 场景输入和输出；
- 字幕关键词强调；
- 事实 Claim；
- 是否允许无素材的纯过渡场景。

它不查看完整素材目录，也不选择具体素材。素材是否存在由后续 Asset Resolver 判断。

### 5.2 顶层 Schema

```python
class SceneSemanticPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scenes: list[SemanticScene]
```

### 5.3 SemanticScene

```python
class SemanticScene(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    scene_id: str
    order: int
    text: str
    visual_structure: str
    slots: list[MaterialSlot]
    events: list[OperationEvent]
    inputs: list[SceneInput]
    outputs: list[SceneOutput]
    claims: list[SceneClaim]
    no_asset: bool
```

`order` 只表达文案顺序，不表达帧号。`scene_id` 推荐由模型输出 `s001`、`s002`，程序校验连续和唯一。

### 5.4 画面结构

`visual_structure` 来自 Visual Structure Registry，例如：

```text
single
gallery
comparison
sequence
no_asset_transition
```

这只是结构，不是 Remotion effect ID：

- `gallery` 表示多个槽按短语依次展示；
- `sequence` 表示同一过程关系组的有序状态；
- `comparison` 表示具有明确关系的两个或多个成员同时或前后对照；
- 具体使用 SlideGallery、CardStack 或其他动效由后续程序配置决定。

### 5.5 MaterialSlot

```python
class MaterialSlot(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    slot_id: str
    anchor_phrase: str
    entry_policy: Literal["scene_start", "phrase_start"]
    hold_policy: Literal["until_next_slot", "scene_end"]
    category_id: str | None
    asset_role: str
    source: SlotSource
    subtitle_emphasis: Literal["none", "keyword"]
```

规则：

- 具体功能素材必须有 `category_id`；
- 配置型通用素材允许 `category_id=null`；
- `anchor_phrase` 必须是 scene.text 原文子串；
- 枚举项逐图展示时，每个被说出的具体对象必须有独立 slot；
- slot 不携带 orientation、effect 或具体 asset ID。

### 5.6 SlotSource 判别联合

```python
class AssetQuerySource(BaseModel):
    kind: Literal["asset_query"]


class AssetGroupQuerySource(BaseModel):
    kind: Literal["asset_group_query"]
    group_alias: str
    group_type: str


class GroupMemberSource(BaseModel):
    kind: Literal["group_member"]
    group_alias: str
    group_type: str
    member_key: str


class SceneInputSource(BaseModel):
    kind: Literal["scene_input"]
    input_name: str


class RelationFromInputSource(BaseModel):
    kind: Literal["relation_from_input"]
    input_name: str
    group_alias: str
    group_type: str
    member_key: str


class ConfiguredAssetSource(BaseModel):
    kind: Literal["configured_asset"]
    config_key: str
```

```python
SlotSource = Annotated[
    AssetQuerySource
    | AssetGroupQuerySource
    | GroupMemberSource
    | SceneInputSource
    | RelationFromInputSource
    | ConfiguredAssetSource,
    Field(discriminator="kind"),
]
```

AI 不输出 `derive_required`。例如关系成员不存在时，后续 Asset Resolver 根据 `relation_from_input`、Derivation Registry 和素材缺口策略决定是否派生；Stage 1 只表达语义需求。

### 5.7 场景依赖

```python
class SceneInput(BaseModel):
    input_name: str
    from_scene: str
    from_output: str
    required: bool


class SceneOutput(BaseModel):
    output_name: str
    bound_slot: str
    asset_role: str
```

场景输出绑定的是 slot 的最终解析素材身份。后续场景通过 input 使用同一素材，保证：

```text
结果图
-> 用该结果进入编辑页面
-> 展示该结果对应的参考图
-> 导出该结果对应的平面图
```

依赖图必须无环。`from_scene` 必须位于当前 scene 之前。

### 5.8 OperationEvent

```python
class OperationEvent(BaseModel):
    event_id: str
    phrase: str
    intent: str
    target_slot: str | None
```

`intent` 来自 Operation Intent Registry。Event 只表达语义操作，不指定鼠标坐标、动画或音效。

### 5.9 SceneClaim

```python
class SceneClaim(BaseModel):
    claim_id: str
    phrase: str
    quantifier: Literal["any", "all"]
    supporting_slots: list[str]
    evidence_window: Literal["anchor", "scene_span"]
```

Claim 声明事实表达，不判断实际素材证据是否合格。后续解析素材后，由程序结合 Evidence Class 校验。

### 5.10 no_asset

`no_asset=true` 只用于 Scene Semantics 明确判断该短语适合无素材过渡的情况，例如缺乏具体视觉对象的承接句。

约束：

```text
no_asset=true
=> visual_structure=no_asset_transition
=> slots=[]
=> inputs=[]
=> outputs=[]
=> claims=[]
```

“素材暂时没找到”不是 `no_asset` 的理由。Scene Semantics 不知道素材是否存在，因此不能用 `no_asset` 掩盖素材缺口。

## 6. SceneSemanticPlan 全局校验

### 6.1 文案覆盖

将 scenes 按 `order` 连接后，必须与 FrozenNarration 规范化文本完全一致：

- 不丢字；
- 不改字；
- 不重复；
- 不重排；
- 标点规范化只能使用统一 Normalizer。

程序保存每个 scene 的字符区间，但不要求 AI 输出字符 offset。

### 6.2 短语定位

以下字段必须是所属 scene.text 的原文子串：

- slot.anchor_phrase；
- event.phrase；
- claim.phrase。

相同短语重复出现时，程序按 scene 字符区间和对象顺序定位。仍有歧义时进入字段纠错，不允许任意匹配第一次出现。

### 6.3 Gallery 枚举规则

文案连续列举具体功能时：

- 每个对象建立独立 slot；
- 每个 slot 的 `anchor_phrase` 是对应对象原文；
- 每个 slot 的 category 和 role 独立；
- 同一 gallery 的 hold 顺序连续；
- 最后一个 slot 才能 `scene_end`；
- 汇总短语可以形成 scene-span Claim，但不能替代枚举槽。

### 6.4 Sequence 与 Comparison

- `sequence` 必须使用 asset group 或 relation source，不能靠多个无关系 `asset_query` 假装过程；
- `comparison` 必须有明确关系组或上游输入关系；
- 参考图、结果图、平面图关系不能通过视觉相似度猜测；
- 编辑场景必须引用上游结果输出，不能随机找另一张结果图。

### 6.5 注册表校验

程序校验：

- category；
- asset role；
- visual structure；
- operation intent；
- claim；
- group type；
- configured asset key。

注册表快照未声明的值一律失败，不由程序创建近似 ID。

## 7. Prompt 正式设计

### 7.1 Prompt 文件结构

```text
video_agent/prompts/v4/
  scope_classifier/
    system.v1.md
    input.schema.json
    output.schema.json
    examples.v1.json
  scene_semantics/
    system.v1.md
    input.schema.json
    output.schema.json
    decision_table.v1.md
    examples.v1.json
  field_repair/
    system.v1.md
    input.schema.json
    output.schema.json
```

### 7.2 System Prompt 六段

每个 system prompt 必须包含：

```markdown
# Role
# Goal
# Inputs
# Allowed Decisions
# Forbidden Decisions
# Output Contract
```

Scene Semantics 追加：

```markdown
# Decision Table
# Positive Examples
# Negative Examples
```

禁止在 Prompt 中手写长期枚举。Category、Asset Role、Operation Intent、Claim 和结构能力由当前 Registry Snapshot 动态渲染。

### 7.3 Scope Input

```json
{
  "request_id": "scope_<run_id>",
  "frozen_narration": {
    "text": "完整固定文案",
    "source_fingerprint": "sha256:..."
  },
  "enabled_categories": [
    {
      "category_id": "文生图/文化墙",
      "display_name": "文化墙",
      "aliases": ["企业文化墙", "党建文化墙"]
    }
  ]
}
```

Scope 不接收素材目录、动效、音效或 TTS 时间戳。

### 7.4 Scene Semantics Input

```json
{
  "request_id": "scene_<run_id>",
  "frozen_narration": {
    "text": "完整固定文案",
    "source_fingerprint": "sha256:..."
  },
  "video_scope": {},
  "registry_snapshot": {
    "asset_roles": [],
    "visual_structures": [],
    "operation_intents": [],
    "claims": [],
    "group_patterns": [],
    "configured_assets": []
  }
}
```

Scene Semantics 不接收：

- 完整素材列表；
- 宿主机路径；
- 具体 asset ID；
- Effect Registry；
- SFX Registry；
- 帧率和安全区；
- TTS token 时间。

这样场景语义不会被“当前碰巧有什么图片”反向污染。

### 7.5 输出要求

模型只输出一个 JSON object：

- 不输出 Markdown code fence；
- 不输出解释；
- 不输出思维链；
- 不输出未知字段；
- 不使用绝对路径；
- 不伪造素材和关系组 ID。

DeepSeek 调用启用 `response_format={"type":"json_object"}`，但 JSON Mode 只保证语法倾向，不替代 Pydantic 和 Domain Validation。

## 8. 字段纠错与模型升级

### 8.1 错误分类

```text
transport_error          网络、超时、限流、服务错误
json_syntax_error        不是合法 JSON object
schema_error             Pydantic 结构不合法
domain_error             注册表、引用、文案覆盖或短语定位不合法
```

不同错误不得共用一个模糊重试 Prompt。

### 8.2 字段级纠错

只对可局部修复且不会改变场景整体语义的错误使用字段纠错，例如：

- 注册表 ID 拼写错误；
- 缺少 required 字段；
- source.kind 与字段组合不匹配；
- slot 引用拼写错误。

输入：

```json
{
  "contract": "SceneSemanticPlan/v4.1",
  "field_path": "scenes[4].slots[0].asset_role",
  "invalid_value": "editor",
  "validation_code": "UNKNOWN_ASSET_ROLE",
  "allowed_values": ["editor_page", "edited_result"],
  "local_context": {},
  "original_text": "继续进入编辑页面"
}
```

输出使用 RFC 6902 风格的受限 replace：

```json
{
  "op": "replace",
  "path": "/scenes/4/slots/0/asset_role",
  "value": "editor_page"
}
```

程序只允许 patch 原始 `field_path`，应用后重新执行完整校验。

### 8.3 不允许字段纠错的错误

以下错误直接进入完整重建：

- scenes 无法完整覆盖文案；
- 场景顺序错误；
- Gallery 枚举丢项；
- 场景依赖有环；
- 编辑或因果链引用了错误上游场景；
- `no_asset` 掩盖明确素材需求；
- 大量字段同时失败。

### 8.4 升级策略

由 Model Route Profile 配置：

```yaml
scene_semantics:
  primary: semantic_fast
  repair: semantic_fast
  rebuild: semantic_quality
  max_transport_retries: 2
  max_field_repairs: 2
  max_full_rebuilds: 1
```

高级模型完整重建也必须通过相同 Contract，不允许绕过校验。耗尽后 Stage 明确失败，不生成可编译的猜测结果。

## 9. 内部 AI Runtime

### 9.1 模块结构

```text
video_agent/ai_runtime/
  gateway.py
  contracts.py
  routing.py
  concurrency.py
  retry.py
  trace.py
  fingerprint.py
  providers/
    base.py
    openai_compatible.py
```

业务节点：

```text
video_agent/semantic/
  scope_classifier.py
  scene_semantics.py
  validators.py
  repair.py
```

### 9.2 ModelGateway

```python
class ModelGateway(Protocol):
    async def invoke_structured(
        self,
        *,
        capability: str,
        system_prompt: str,
        input_payload: dict[str, Any],
        output_type: type[T],
        trace_context: TraceContext,
    ) -> StructuredInvocation[T]: ...
```

业务代码不知道 base URL、API key、供应商 HTTP 字段或重试细节。

### 9.3 Provider Adapter

第一版只实现 `OpenAICompatibleProvider`：

```python
class OpenAICompatibleProvider:
    def __init__(self, client: httpx.AsyncClient, profile: ProviderProfile): ...

    async def complete_json(self, request: ProviderRequest) -> ProviderResponse: ...
```

Provider 负责：

- Chat Completions 请求；
- JSON Mode；
- HTTP 错误标准化；
- usage 提取；
- request ID 提取；
- 响应原文保留。

Provider 不负责：

- Pydantic Domain Contract；
- 业务字段纠错；
- Stage 重建；
- 素材查询；
- Prompt 拼装。

### 9.4 并发控制

```yaml
ai_runtime:
  providers:
    deepseek:
      max_concurrency: 3
      connect_timeout_seconds: 10
      read_timeout_seconds: 240
  capabilities:
    scope_classifier:
      max_concurrency: 2
    scene_semantics:
      max_concurrency: 1
```

数字是部署配置，不进入 Contract。Runtime 使用 Provider Semaphore 和 Capability Semaphore 的较小值。

### 9.5 请求去重

调用指纹：

```text
provider_profile
+ model
+ system_prompt_sha256
+ input_payload_sha256
+ output_schema_sha256
+ model_settings
```

相同指纹且已有 `validated` 产物时直接重放。失败响应不作为成功缓存。

## 10. 请求导出与本地追踪

### 10.1 目录

```text
cases/<case>/runs/<run>/agents/
  01_scope_classifier/
    request.system.md
    request.input.json
    response.raw.json
    response.validated.json
    manifest.json
    repairs/
  02_scene_semantics/
    request.system.md
    request.input.json
    response.raw.json
    response.validated.json
    manifest.json
    repairs/
```

### 10.2 manifest.json

```json
{
  "capability": "scene_semantics",
  "prompt_version": "scene_semantics.v1",
  "provider_profile": "deepseek_default",
  "model_profile": "semantic_quality",
  "model": "configured-at-runtime",
  "request_fingerprint": "sha256:...",
  "started_at": "ISO-8601",
  "elapsed_ms": 0,
  "usage": {},
  "validation_status": "validated",
  "repair_count": 0,
  "rebuild_count": 0
}
```

不得记录 API Key、Authorization Header 或宿主机绝对素材路径。

### 10.3 日志

```text
[AI][scope_classifier] 开始 model_profile=semantic_fast
[AI][scope_classifier] 完成 elapsed=... categories=...
[AI][scene_semantics] 开始 scope=multi_category
[AI][scene_semantics] Contract 失败 code=UNKNOWN_ASSET_ROLE path=...
[AI][scene_semantics] 字段纠错 1/2
[AI][scene_semantics] 完成 scenes=... slots=... elapsed=...
```

日志负责人类定位，JSON 产物负责机器重放，两者不可互相替代。

## 11. Stage 产物与断点恢复

### 11.1 冻结产物

```text
video_scope.json
scene_semantic_plan.json
```

一旦标记为 validated，下游只能读取，不得原地修改。纠错结果必须在 Stage 内完成后再原子替换临时文件。

### 11.2 Resume 指纹

Scope 输入指纹包含：

- FrozenNarration 内容；
- Category Registry Snapshot；
- Scope Prompt；
- output schema；
- model profile。

Scene Semantics 输入指纹包含：

- FrozenNarration；
- validated VideoScope；
- 相关 Registry Snapshots；
- Scene Prompt、Decision Table 和 examples；
- output schema；
- model profile。

任何一项变化都使 Stage 失效。

## 12. 目录与代码落点

```text
video_agent/
  ai_runtime/
  semantic/
  contracts/v4/
    scope.py
    scene.py
    common.py
  prompts/v4/
  registries/

cases/<case>/runs/<run>/
  frozen_narration.json
  video_scope.json
  scene_semantic_plan.json
  agents/
```

旧 `text_client.py` 在迁移期只能作为 Provider 行为参考，V4 节点不得直接调用它。完成切换后删除同步 AI 文本调用入口。

## 13. 实施顺序

1. 建立 `contracts/v4` 和纯程序 Domain Validator；
2. 从阶段 0 理想响应生成固定 fixture，先验证 Contract；
3. 建立 Prompt 文件和 Prompt Renderer；
4. 建立异步 `ModelGateway` 与 DeepSeek Provider；
5. 实现 Scope Stage、请求导出和 Resume；
6. 实现 Scene Semantics Stage、字段纠错和完整重建；
7. 将两个 Stage 接入新 V4 Orchestrator，但暂不替换后续素材与渲染链路；
8. 使用阶段 0 FrozenNarration 产出真实 `video_scope.json` 和 `scene_semantic_plan.json`；
9. Contract 稳定后进入 Stage 2：Capability Registry 与素材领域 Contract。

## 14. Stage 1 完成标准

Stage 1 完成不是“模型返回了一段 JSON”，而是满足：

1. 固定文案通过两个真实 AI 节点产生 validated 产物；
2. Scene 文本无丢失、重复或改写；
3. Gallery 每个明确对象都有独立 slot 和原文 Anchor；
4. 编辑、参考图、结果图和平面图的跨场景依赖正确；
5. 未找到素材不会提前变成 `no_asset`；
6. 所有动态 ID 均来自冻结注册表；
7. Prompt、输入、原始输出、验证输出、纠错和模型信息完整导出；
8. 固定音色模式下 TTS 与 Scope 确实并行；
9. 重放 validated 产物不再次调用模型；
10. 下游可以仅凭 `SceneSemanticPlan` 构造素材查询和时间 Anchor，不需要读取模型原始响应。

达到以上标准后，Stage 1 Contract 冻结为 `v4.1`，后续设计只能通过显式 schema version 升级，不得在实现中悄悄改变字段语义。
