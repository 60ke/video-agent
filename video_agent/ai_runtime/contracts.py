from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class RuntimeContract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ProviderProfile(RuntimeContract):
    profile_id: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    api_key: SecretStr
    max_concurrency: int = Field(default=3, ge=1)
    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=240.0, gt=0)


class ModelProfile(RuntimeContract):
    profile_id: str = Field(min_length=1)
    provider_profile: str = Field(min_length=1)
    model: str = Field(min_length=1)
    max_tokens: int = Field(default=8192, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    thinking: bool | None = None


class CapabilityRoute(RuntimeContract):
    capability: str = Field(min_length=1)
    primary: str = Field(min_length=1)
    repair: str | None = None
    rebuild: str | None = None
    max_concurrency: int = Field(default=1, ge=1)
    max_transport_retries: int = Field(default=2, ge=0)
    max_field_repairs: int = Field(default=2, ge=0)
    max_full_rebuilds: int = Field(default=1, ge=0)


class ProviderRequest(RuntimeContract):
    capability: str
    system_prompt: str
    input_payload: dict[str, Any]
    model_profile: ModelProfile


class ProviderResponse(RuntimeContract):
    content: str
    raw_body: dict[str, Any]
    request_id: str | None = None
    usage: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class TraceContext:
    output_dir: Path
    prompt_version: str
    prompt_fingerprint: str | None = None


T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class StructuredInvocation(Generic[T]):
    value: T
    request_fingerprint: str
    model_profile: str
    replayed: bool
    raw_content: str | None
