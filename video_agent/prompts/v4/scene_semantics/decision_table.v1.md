# visual_structure 选择指南

根据口播的**视觉内容**选择 `visual_structure`，不使用文案表面模式匹配：

| 口播在说什么 | visual_structure |
|---|---|
| 一个画面/一个结果/一个页面/一句收束/一个入口 | `single` |
| 连续列举多个独立对象（文化墙、门头、LOGO…） | `gallery` |
| 同一流程的多个连续步骤（填参→点击→生成） | `sequence` |
| 因果/对比关系（参考图→结果图、编辑前→编辑后） | `comparison` |

**关键规则**：
- `sequence` 仅表示时间顺序，槽位角色可自由组合——parameter_panel → result_image 或纯 asset_query 拼流程都允许。
- **禁止空镜**：每镜都必须有画面。修辞反问、纯承接句也要根据上下文配最合适的画面。
- **画面丰富**：可拆分的视觉概念尽量拆成多张独立画面，不要压成单图。视频不是 PPT。

# asset_role 选择指南

根据口播描述的**画面内容类型**选择 `asset_role`：

| 口播描述的画面 | asset_role |
|---|---|
| 设计生成的结果图/效果图/方案图 | `result_image` |
| 操作界面/参数面板/免提示词入口 | `parameter_panel` |
| 网站首页/品牌主页 | `site_home` |
| 具体功能入口页面 | `feature_entry` |
| 某具体功能入口页（例如“进入文化墙”） | `feature_entry` |
| 功能列表/工具清单/能力总览页 | 素材库中实际存在的总览页角色；无匹配总览页时 `site_home` |
| 编辑页面 | `editor_page` |
| 编辑弹窗 | `editor_modal` |
| 参考图 | `reference_image` |
| 平面图/排布图 | `flat_plan` |
| 编辑结果 | `edited_result` |
| 以上都不匹配 | `other` |

**核心规则**：`parameter_panel` 展示操作过程，`result_image` 展示操作结果。两者可以在同一个 `sequence` 中按时间顺序组合。`flat_plan`、`editor_page` 和 `edited_result` 必须在新场景通过 `relation_from_input` 继承前一场新输出的 `result_image`，不能作为独立查询。

## 禁止替代

| 口播语义 | 必须使用 | 不得替代为 |
|---|---|---|
| “进入/选择/以 X 为例”的具体功能入口 | `feature_entry` + `文生图/X` | `result_image` |
| “选择行业、主题、场景 / 填写必填项” | `parameter_panel` + 对应品类 | `result_image` |
| “生成效果图/方案/成品” | `result_image` + 对应品类 | `feature_entry`、`parameter_panel` |
| “编辑/修改/局部编辑/指哪改哪” | 以前序 `result_image` 为父的完整 `editor_sequence`：`source_result → editor_page → edited_result` | 无关 `result_image`，或只展示编辑页 |
| 网站/平台/智能体的品牌收束、效率总结、易上手结论 | `site_home` | 随机品类 `result_image` |

连续列举多个**设计品类**（例如“文化墙、门头招牌、LOGO”）时，每个短语应在 `gallery` 中独立使用其品类 `result_image`。连续列举多个**网站工具/页面**时，只有明确进入某个具体功能才使用 `feature_entry`；工具总览必须使用库存中存在的总览页或 `site_home`。
