from __future__ import annotations

from pathlib import Path

import httpx

from .gateway import AsyncModelGateway
from .providers import OpenAICompatibleProvider
from .routing import RuntimeConfiguration, load_runtime_configuration


class AIRuntimeSession:
    def __init__(self, repo_root: Path, configuration: RuntimeConfiguration | None = None) -> None:
        self.repo_root = repo_root
        self.configuration = configuration
        self._clients: list[httpx.AsyncClient] = []
        self.gateway: AsyncModelGateway | None = None

    async def __aenter__(self) -> AsyncModelGateway:
        configuration = self.configuration or load_runtime_configuration(self.repo_root)
        providers = {}
        for profile_id, profile in configuration.providers.items():
            timeout = httpx.Timeout(
                connect=profile.connect_timeout_seconds,
                read=profile.read_timeout_seconds,
                write=profile.read_timeout_seconds,
                pool=profile.connect_timeout_seconds,
            )
            client = httpx.AsyncClient(timeout=timeout)
            self._clients.append(client)
            providers[profile_id] = OpenAICompatibleProvider(client, profile)
        self.gateway = AsyncModelGateway(configuration, providers)
        return self.gateway

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        for client in reversed(self._clients):
            await client.aclose()
        self._clients.clear()
        self.gateway = None
