"""Stage 5 derivation executors and capability resolution."""

from __future__ import annotations

__all__ = [
    "RegistryDerivationCapabilityResolver",
    "Stage5DerivationExecutor",
]


def __getattr__(name: str):
    if name == "RegistryDerivationCapabilityResolver":
        from .capability_resolver import RegistryDerivationCapabilityResolver

        return RegistryDerivationCapabilityResolver
    if name == "Stage5DerivationExecutor":
        from .executors import Stage5DerivationExecutor

        return Stage5DerivationExecutor
    raise AttributeError(name)
