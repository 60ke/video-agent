"""Operator-approved category inventory fallbacks for Stage4 selection."""

from __future__ import annotations

# Semantic category_id -> stocked category_id when inventory is empty.
CATEGORY_INVENTORY_FALLBACKS: dict[str, str] = {
    "文生图/雕塑小品": "文生图/景观小品",
}

# Categories that already have active reference_result_plan groups in production.
# Other categories collapse comparison scenes to a stocked result_image query
# instead of requiring GPT derivation for missing causal groups.
REFERENCE_RESULT_STOCKED_CATEGORIES: frozenset[str] = frozenset(
    {
        "文生图/LOGO",
        "文生图/文化墙",
    }
)
