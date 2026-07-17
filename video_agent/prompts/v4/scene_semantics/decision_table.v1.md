| 文案语义 | visual_structure | 槽来源要求 |
|---|---|---|
| 单一页面或单图 | `single` | 独立查询、上游输入或配置素材 |
| 连续列举多个明确对象 | `gallery` | 每个对象独立槽，按原文短语进入 |
| 同一流程的多个状态 | `sequence` | 同一过程关系组，或上游输入加关系成员 |
| 参考与结果、编辑前后等明确关系 | `comparison` | 上游输入和关系成员，不得按相似度猜测 |
| 只有承接语义且没有明确视觉对象 | `no_asset_transition` | `no_asset=true` 且素材、输入、输出、Claim 均为空 |

补充规则：Gallery 最后一槽保持到场景结束；其他槽保持到下一槽。Scene Input 只能引用更早场景的命名 Output。
