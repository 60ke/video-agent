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
| Generic website, brand platform, or AI-agent conclusion | `site_home` | Random category `result_image` |
| Registered tool list, editing-tool overview, or product capability page | The registered generic page role, normally `other` | A category `feature_entry` unless the words explicitly name its entry page |
| Edit or revise an earlier result | An `editor_sequence` relation bound to the earlier `result_image` | Unrelated result image or standalone editor page |
| Reference scene produces a result or exported plan | A causal relation bound to the same registered/derived family | Arbitrary reference/result pairing |

For a sentence that contains multiple workflow steps, use `sequence` and give
each step its own slot. Do not collapse feature entry, parameter setup, and
result payoff into one role. When the script says only a general product
capability and there is no registered page for it, use `other`; do not invent
a category or silently turn it into a result image.
