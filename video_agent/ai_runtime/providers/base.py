from __future__ import annotations

from typing import Protocol

from video_agent.ai_runtime.contracts import ProviderRequest, ProviderResponse


class JSONProvider(Protocol):
    async def complete_json(self, request: ProviderRequest) -> ProviderResponse: ...
