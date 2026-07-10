from . import registry as _registry
from .perspective_push_in import EFFECT_NAME as PERSPECTIVE_PUSH_IN, install as _install_perspective_push_in

_install_perspective_push_in(_registry)

from .registry import (  # noqa: E402
    EFFECT_NAMES,
    EFFECTS_REQUIRE_AUX,
    EffectSuggestionInput,
    effect_aux_asset_ids,
    effect_requires_aux,
    normalize_effect_config,
    render_effect_frame,
    suggested_effect,
)

__all__ = [
    "EFFECT_NAMES",
    "EFFECTS_REQUIRE_AUX",
    "PERSPECTIVE_PUSH_IN",
    "EffectSuggestionInput",
    "effect_aux_asset_ids",
    "effect_requires_aux",
    "normalize_effect_config",
    "render_effect_frame",
    "suggested_effect",
]
