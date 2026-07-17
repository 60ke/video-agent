from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import V4Contract


class FieldRepairPatch(V4Contract):
    op: Literal["replace"]
    path: str = Field(pattern=r"^/")
    value: Any
