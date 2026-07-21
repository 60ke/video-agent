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
| 功能列表/工具清单/能力总览页（列举网站内置功能的页面，不是生成结果） | `feature_entry` |
| 编辑页面 | `editor_page` |
| 编辑弹窗 | `editor_modal` |
| 参考图 | `reference_image` |
| 平面图/排布图 | `flat_plan` |
| 编辑结果 | `edited_result` |
| 片尾 | `outro` |
| 以上都不匹配 | `other` |

**核心规则**：`parameter_panel` 展示操作过程，`result_image` 展示操作结果。两者可以在同一个 `sequence` 中按时间顺序组合（先过程、后结果），各自用正确的 asset_role。
