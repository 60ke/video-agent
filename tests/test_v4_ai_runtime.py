from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from video_agent.ai_runtime import (
    AIJsonSyntaxError,
    AsyncModelGateway,
    CapabilityRoute,
    ModelProfile,
    ProviderProfile,
    RuntimeConfiguration,
    TraceContext,
)
from video_agent.ai_runtime.contracts import ProviderRequest, ProviderResponse


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    value: str


class FakeProvider:
    def __init__(self, contents: list[str]) -> None:
        self.contents = contents
        self.calls = 0
        self.requests: list[ProviderRequest] = []

    async def complete_json(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        content = self.contents[min(self.calls, len(self.contents) - 1)]
        self.calls += 1
        return ProviderResponse(content=content, raw_body={"choices": []}, request_id="req_1", usage={"tokens": 3})


def _configuration() -> RuntimeConfiguration:
    provider = ProviderProfile(profile_id="test", base_url="https://example.invalid", api_key="secret", max_concurrency=2)
    model = ModelProfile(profile_id="semantic_fast", provider_profile="test", model="fake-model", max_tokens=100)
    route = CapabilityRoute(capability="scope_classifier", primary="semantic_fast", max_transport_retries=0)
    return RuntimeConfiguration(providers={"test": provider}, models={"semantic_fast": model}, routes={"scope_classifier": route})


def test_gateway_traces_validated_response_without_secret(tmp_path: Path) -> None:
    provider = FakeProvider(['{"value":"ok"}'])
    gateway = AsyncModelGateway(_configuration(), {"test": provider})
    trace = TraceContext(output_dir=tmp_path / "agent", prompt_version="test.v1")

    result = asyncio.run(
        gateway.invoke_structured(
            capability="scope_classifier",
            system_prompt="Return JSON.",
            input_payload={"text": "hello"},
            output_type=Output,
            trace_context=trace,
        )
    )

    assert result.value.value == "ok"
    assert result.replayed is False
    assert provider.calls == 1
    assert "# Exact JSON Output Schema (Authoritative)" in provider.requests[0].system_prompt
    assert '"value"' in provider.requests[0].system_prompt
    manifest = json.loads((trace.output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["validation_status"] == "validated"
    assert "secret" not in "".join(path.read_text(encoding="utf-8") for path in trace.output_dir.iterdir())
    traced_system = (trace.output_dir / "request.system.md").read_text(encoding="utf-8")
    assert traced_system == provider.requests[0].system_prompt


def test_gateway_contract_forbids_undeclared_output_fields(tmp_path: Path) -> None:
    provider = FakeProvider(['{"value":"ok"}'])
    gateway = AsyncModelGateway(_configuration(), {"test": provider})

    asyncio.run(
        gateway.invoke_structured(
            capability="scope_classifier",
            system_prompt="Return JSON.",
            input_payload={"text": "hello"},
            output_type=Output,
            trace_context=TraceContext(output_dir=tmp_path / "agent", prompt_version="test.v1"),
        )
    )

    system_prompt = provider.requests[0].system_prompt
    assert '"additionalProperties": false' in system_prompt
    assert "Do not add envelope fields" in system_prompt


def test_gateway_replays_validated_fingerprint(tmp_path: Path) -> None:
    provider = FakeProvider(['{"value":"ok"}'])
    gateway = AsyncModelGateway(_configuration(), {"test": provider})
    kwargs = {
        "capability": "scope_classifier",
        "system_prompt": "Return JSON.",
        "input_payload": {"text": "hello"},
        "output_type": Output,
        "trace_context": TraceContext(
            output_dir=tmp_path / "agent",
            prompt_version="test.v1",
            prompt_fingerprint="prompt-sha",
        ),
    }

    asyncio.run(gateway.invoke_structured(**kwargs))
    replay = asyncio.run(gateway.invoke_structured(**kwargs))

    assert replay.replayed is True
    assert provider.calls == 1


def test_gateway_classifies_invalid_json(tmp_path: Path) -> None:
    gateway = AsyncModelGateway(_configuration(), {"test": FakeProvider(["not-json"])})
    with pytest.raises(AIJsonSyntaxError):
        asyncio.run(
            gateway.invoke_structured(
                capability="scope_classifier",
                system_prompt="Return JSON.",
                input_payload={"text": "hello"},
                output_type=Output,
                trace_context=TraceContext(output_dir=tmp_path / "agent", prompt_version="test.v1"),
            )
        )
    manifest = json.loads((tmp_path / "agent" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["failure_type"] == "json_syntax_error"
