from __future__ import annotations

import re
import unicodedata
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class V4Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


T = TypeVar("T", bound=BaseModel)


class ArtifactEnvelope(V4Contract, Generic[T]):
    schema_version: str = Field(min_length=1)
    input_fingerprints: dict[str, str]
    payload: T


class ValidationIssue(V4Contract):
    code: str
    path: str
    message: str


class DomainValidationError(ValueError):
    def __init__(self, contract_name: str, issues: list[ValidationIssue]) -> None:
        self.contract_name = contract_name
        self.issues = issues
        summary = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        super().__init__(f"{contract_name} domain validation failed: {summary}")


_SPACE_RE = re.compile(r"\s+")


def normalize_frozen_text(value: str) -> str:
    """Normalize representation only; never paraphrase or remove punctuation."""

    normalized = unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n")
    return _SPACE_RE.sub(" ", normalized).strip()
