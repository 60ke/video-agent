"""Lazy importable Derivation Registry handlers (avoids Hub ↔ assets circular imports)."""

from __future__ import annotations

from typing import Any


def DeterministicDerivationExecutor(*args: Any, **kwargs: Any):
    from video_agent.derivation.v4.executors import DeterministicDerivationExecutor as Impl

    return Impl(*args, **kwargs)


def GptImageDerivationExecutor(*args: Any, **kwargs: Any):
    from video_agent.derivation.v4.executors import GptImageDerivationExecutor as Impl

    return Impl(*args, **kwargs)


def Stage5DerivationExecutor(*args: Any, **kwargs: Any):
    from video_agent.derivation.v4.executors import Stage5DerivationExecutor as Impl

    return Impl(*args, **kwargs)
