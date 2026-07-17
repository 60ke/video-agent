from __future__ import annotations

from typing import Any


class AIRuntimeError(RuntimeError):
    failure_type = "runtime_error"

    def __init__(self, message: str, *, details: list[dict[str, Any]] | None = None) -> None:
        self.details = details or []
        super().__init__(message)


class AITransportError(AIRuntimeError):
    failure_type = "transport_error"


class AIJsonSyntaxError(AIRuntimeError):
    failure_type = "json_syntax_error"


class AISchemaError(AIRuntimeError):
    failure_type = "schema_error"


class AIDomainError(AIRuntimeError):
    failure_type = "domain_error"
