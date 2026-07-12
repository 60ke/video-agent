from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .base import Contract, VersionedContract


class CheckResult(Contract):
    check_id: str
    status: Literal["passed", "failed", "warning", "skipped"]
    message: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class QaReport(VersionedContract):
    case_id: str
    run_id: str
    status: Literal["passed", "failed"]
    final_video: str | None = None
    checks: list[CheckResult]
