# Visual Coverage Review — 问题与方案备忘（暂缓实施）

Status: **记录中 / 不开工**
Date: 2026-07-20
Purpose: 汇总本地文案验收中暴露的画面问题，以及拟议的通用补救方向。待更多文案测完后，再收敛成正式设计与实施。

相关权威：

- 生产 DAG：`docs/architecture.md`
- Stage7 切主线：`docs/video_agent_v4_stage7_production_cutover_and_acceptance_design_20260720.md`
- 本地四文案 ledger：`tests/fixtures/v4/stage7/local_scripts_acceptance_ledger.json`

---

## 1. 工作约定

1. **不开工** Visual Coverage Review Agent / 新 DAG 节点，直到更多文案问题被收集并分类。
2. 禁止针对具体口播句子写死规则（例如「两三步」「换行业」）。
3. 已落地的通用 P0（末镜 `default_outro`、收束禁空）可保留；`feature_list` 角色已禁用，卖点口播改由 Prompt 引导 `site_home`。大方案仍以本文后续修订为准。
4. 每测完一条文案，把「字幕 / 当前配图 / 期望配图 / 问题类」追加到 §3、§4。

---

## 2. 根因判断（当前共识）

多数成片问题不是「库存为空」或 Resolver 坏了，而是：

> Scene Agent 一次承担了「语义规划 + 画面义务完整 + 成片密度合理」三件事；
> 其中密度、空镜是否合理、结果是否落地，往往要在 **时长确定 + 素材已选** 之后才能暴露。

因此方向上更合理的是：

- Scene：第一次语义规划；
- 确定性硬合同：片尾 / 明确角色义务 / 禁区；
- （拟议）画面覆盖审核层：看真实选材与时长，做最小化补充。

不要用「按某句文案加规则」当长期方案。

---

## 3. 已观察问题清单

问题用 **通用类** 归类，具体文案只作证据。

### 3.1 画面义务 / 语义覆盖（test1 = `test.txt`，run `20260720_165554_08529b`）

| 类 ID | 通用问题 | test1 证据（字幕 → 当前 → 期望） |
|---|---|---|
| V-EMPTY | 实质口播被做成空镜 / `no_asset` | 「二十多项…编辑小工具」→ 空；收束「这就是…智能体」→ 空 → 应品牌主页等。注：`feature_list` 已禁用，卖点/能力主张优先 `site_home` |
| V-PAYOFF | 过程有了，结果承诺未落地 | 「…轻松出效果图」→ 停在参数终态 → 「出效果图」应对准美陈 `result_image` |
| V-BREADTH | 语义广度 > 画面广度 | 「换行业、换主题、换风格」→ 单张结果 → 应多结果 Gallery |
| V-OUTRO | 固定片尾缺失 | 计划无 `default_outro` → 必须确定性强制（非 Agent 自由造） |
| V-OK | 已对齐（对照用） | 开场 `site_home`；品类 Gallery；「举个例子美陈」`feature_entry` |
| V-HOLD | `no_asset_transition` 成空镜 | test2t s002「不靠工具纯手工要多久」无槽 → 画面空白；**应至少 hold 上一画面**（待修，已同意） |
| V-MATCH | 口播品类/主题与所选结果图语义不对齐 | logo1a gallery：餐饮→口腔、交通→宠物服务、娱乐→手机 |
| V-PROMPT | 「无需/不需要提示词」未落到参数面板 | logo1a s002 做成 `no_asset` 空镜；应 `parameter_panel`（同 test2 规则） |
| V-SUB | 字幕被拆成单字残片 | logo1a「LOGO设 / 计」；aiday1b「融 / 合」 |

### 3.2 Claim / 证据错挂

| 类 ID | 通用问题 | 证据 |
|---|---|---|
| C-SLOT | Claim 挂在不能证明该事实的槽上 | test2：`feature_can_generate_result` → Stage6 `claim_evidence_not_visible`（现为 **warning**，不阻断出片） |

提示词侧已对 Claim `supporting_slots` 做过通用约束；证据不可见只告警，后续由 Visual Coverage Review 再收紧。

### 3.3 执行 / 环境（非语义决策表）

| 类 ID | 通用问题 | 证据 |
|---|---|---|
| E-DERIVE | 派生/生图链路失败 | test3：VI 需 RRP 派生；GPT Image uuapi 524 / casdao 429 |
| E-COVER | 封面代表素材偶发为空 | test1 分析：brief `representative_asset_refs` 曾为空（独立于 Coverage Agent） |

### 3.4 本地四文案流水状态（快照）

| 文案 | 流水 | 备注 |
|---|---|---|
| test1 `test.txt` | passed（可出片） | 视觉缺口见 §3.1；流水绿 ≠ 画面合格 |
| test2 `test2.txt` | passed（claim warning 不阻断） | `stage7_accept_local_test2t`；C-SLOT 仅告警 |
| test3 `test3.txt` | failed Stage4 | E-DERIVE |
| test4 `test4.txt` | passed | 待人工过目是否有同类 V-\* 问题 |

> 测 test2–test4 成片或半成品时，把新发现追加到下方「待补录」。

#### 待补录（继续测试时填写）

```text
文案: test2t
run_id: 20260720_201147_5faad5
字幕片段: 不靠工具纯手工要多久
当前配图: 空镜（no_asset_transition）
期望配图: hold 上一画面（s001 电商结果图）
归入类 ID（已有或新建）: V-HOLD
是否可用通用义务描述（不要写死原句）: no_asset_transition 至少 hold 上一有效 base 画面，禁止空镜
```

```text
文案: logo1a 一分钟搞定LOGO设计
run_id: 20260720_202134_5a72b0
字幕片段: 餐饮美食 / 交通出行 / 娱乐潮玩；无需提示词
当前配图: 口腔/宠物服务/手机 LOGO；s002 空镜
期望配图: 行业语义对齐的 LOGO 结果；免提示词→参数面板（或 hold）
归入类 ID（已有或新建）: V-MATCH / V-PROMPT / V-HOLD / V-SUB
是否可用通用义务描述（不要写死原句）: gallery 枚举项必须选与口播主题同语义的结果图；免提示词主张→parameter_panel
```

```text
文案: aiday1b 挑战一天一个AI生图功能
run_id: 20260720_202215_5da956
字幕片段: 都不在话下；企业办公和真实场景融合
当前配图: 空镜；时捷电商 VI 结果（场景融合语义弱）
期望配图: hold 上一画面；办公/实景融合类 VI
归入类 ID（已有或新建）: V-HOLD / V-MATCH / V-SUB
是否可用通用义务描述（不要写死原句）: 同上 hold；结果图需覆盖口播场景语义
```

```text
文案:
run_id:
字幕片段:
当前配图:
期望配图:
归入类 ID（已有或新建）:
是否可用通用义务描述（不要写死原句）:
```

---

## 4. 拟议方案（草案，待更多样本后修订）

名称：**Visual Coverage Review**（画面覆盖审核与补充）

### 4.1 核心分工

| 层 | 职责 |
|---|---|
| Scene Prompt + 决策表 | 通用义务（少空镜、过程+结果、多样性→gallery）；不写文案特判 |
| 确定性修复 | 硬合同：末镜 `default_outro`、收束禁空（不强制 `feature_list`） |
| Coverage Metrics | 程序算时长/密度/空镜/重复/无结果/广度信号；只触发审核 |
| Coverage Agent（拟） | 仅审风险 Scene；输出 issue + supplement 请求；不写 `asset_ref`/帧号/旁白 |
| Resolver 二过 | 执行补充 → `augmented_visual_plan` |
| 封面 / 片尾 | 确定性兜底；Agent 只报告缺失 |

### 4.2 建议挂载点（相对现 DAG）

```text
scene → assets → coverage_metrics → visual_coverage
      → visual_augment → augmented_visual_plan → motion_audio → …
```

- 不覆盖 Stage4 原 `resolved_asset_plan.json`
- Motion/Compile 改吃 augmented（无补充时等价原计划）

### 4.3 关键边界（必须保留）

1. **固定片尾**：语义末镜 `configured_asset(default_outro)`，不是渲染后 ffmpeg 再拼一段。
2. **不改冻结旁白 / SpeechTimingLock**；补充画面不得破坏词级 Anchor 铁律。
3. **指标只触发审核**，不强制「每 N 秒必须 M 张图」。
4. **程序先筛、Agent 后判、程序再校验**；Agent 关闭时确定性层仍应可独立工作。
5. Supplement 最小化；高严重度失败 fail-loud，低严重度可 warning。

### 4.4 建议实施顺序（开工前再确认）

1. Policy + Contracts
2. 确定性 metrics pre-audit
3. 规则可映射的 supplement 执行器 + augmented plan
4. （可选）Coverage Agent 灰区
5. Scene Prompt 通用增强（可并行）
6. DAG / QA / 多文案验收

**当前决策：全部暂缓，先积累 §3 样本。**

### 4.5 已部分落地（避免重复开工时遗忘）

截至 2026-07-20 对话内已做、且偏「硬合同」的改动：

- 确定性：末镜强制 `default_outro`；片尾前空收束补 `site_home`
- 注册表：`feature_list` 已禁用；Scene Prompt 引导品牌/卖点优先 `site_home`
- Prompt/决策表：上述通用条文 + 负例
- Validator / structured QA：`missing_terminal_outro` / `terminal_default_outro`

这些 **不替代** Coverage 层；大方案仍以 §4 为准，样本够了再统一设计文档。

---

## 5. 修订日志

| 日期 | 变更 |
|---|---|
| 2026-07-20 | 首版：记录 test1 视觉对照、四文案流水、拟议 Coverage 方案；明确暂缓实施 |
| 2026-07-20 | `feature_list` 角色禁用；卖点口播改 Prompt 引导 `site_home`，去掉强制改写为 `feature_list` 的规划修复 |
| 2026-07-20 | 免提示词主张 → `parameter_panel`（分类跟上下文，如电商→文生图/电商）；相邻卖点允许复用同图（Prompt + Stage4 稀缺角色复用） |
| 2026-07-20 | Claim 证据可见性改为 Stage6 **warning**（不阻断出片）；回退清空全部 claims 的修复改动 |
| 2026-07-20 | 记入 **V-HOLD**：`no_asset_transition` 不得空镜，应 hold 上一画面（待修，已同意） |
| 2026-07-20 | logo1a / aiday1b 成片复核：补 **V-MATCH / V-PROMPT / V-SUB** 样本 |
