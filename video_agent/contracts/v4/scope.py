from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import V4Contract


class ScopeCategory(V4Contract):
    category_id: str = Field(min_length=1)
    mention_phrases: list[str] = Field(min_length=1)
    is_primary: bool


class VideoScope(V4Contract):
    scope_mode: Literal["single_category", "multi_category"]
    categories: list[ScopeCategory] = Field(min_length=1)
