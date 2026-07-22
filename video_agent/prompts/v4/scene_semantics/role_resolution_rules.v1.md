# Authoritative Role Resolution Rules

The rules in this section take precedence over generic role hints and examples.
Choose a role for what the audience must see at the spoken phrase, not for a
nearby product claim.

| Spoken semantic | Required visual structure and role | Forbidden substitute |
|---|---|---|
| Specific feature entry: "以文化墙为例", "进入文化墙", "选择文化墙功能" | `single` or `sequence` with `feature_entry` and that feature's category | `result_image` |
| Field selection: industry, theme, scene, required fields, prompt-free setup | `parameter_panel` and that feature's category | `result_image` |
| A generated design, effect image, finished plan, or concrete deliverable | `result_image` and the described feature's category | `feature_entry`, `parameter_panel` |
| Consecutive design-category list: "文化墙、门头招牌、LOGO" | `gallery`; one ordered `result_image` slot for each phrase and category | One generic image, `feature_entry` |
| Generic website, brand platform, AI-agent conclusion, or abstract efficiency payoff such as "统一操作简单好上手" | `site_home` | Random category `result_image` |
| Registered tool list, editing-tool overview, or product capability page | The registered generic page role, normally `other` | A category `feature_entry` unless the words explicitly name its entry page |
| Edit or revise an earlier result | Complete `editor_sequence`: `source_result`, `editor_page`, then `edited_result`, all bound to the earlier `result_image` | Unrelated result image, standalone editor page, or a sequence without the visible edited result |
| Reference scene produces a result or exported plan | A causal relation bound to the same registered/derived family | Arbitrary reference/result pairing |
| Real scene / reference photo is fused or generates an effect | Complete `reference_result_plan`: visually show `reference_image` then `result_image`; reuse its `flat_plan` only for a later export statement | A standalone result image that merely claims real-scene fusion |
| Exported plan shown on its own: "可导出平面图" | `single` with one relation-bound `flat_plan` | `comparison` with only a flat plan |
| Result is explicitly compared with its exported plan | `comparison` with exactly `result_image` and `flat_plan` from one causal family | A third comparison item or an unrelated plan |

For a sentence that contains multiple workflow steps, use `sequence` and give
each step its own slot. Do not collapse feature entry, parameter setup, and
result payoff into one role. When the script says only a general product
capability and there is no registered page for it, use `other`; do not invent
a category or silently turn it into a result image.

`comparison` is strictly a two-endpoint grammar. Its only supported causal
pairs are `reference_image → result_image` and `result_image → flat_plan`.
When a reference/result demonstration is followed by a plan export, split it
into a two-image comparison scene and a later single `flat_plan` scene.
