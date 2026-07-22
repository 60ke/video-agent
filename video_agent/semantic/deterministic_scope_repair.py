"""Mechanical normalization for ``VideoScope`` model output.

Scope classification remains an AI decision.  This module only resolves states
that cannot be semantically valid under the contract, such as returning one
category while declaring a multi-category video.
"""

from __future__ import annotations

from video_agent.contracts.v4 import VideoScope


def normalize_video_scope(scope: VideoScope) -> VideoScope:
    """Return a contract-consistent scope without inventing categories.

    A single returned category has an unambiguous scope and primary category.
    Normalizing that contradictory representation locally avoids a pointless
    second model request while preserving the model's only category decision.
    """

    if len(scope.categories) != 1:
        return scope

    category = scope.categories[0].model_copy(update={"is_primary": True})
    return scope.model_copy(update={"scope_mode": "single_category", "categories": [category]})
