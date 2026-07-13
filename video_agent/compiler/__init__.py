from . import render_plan as _render_plan
from .evidence import resolves_to_supporting_asset, validate_claim_bindings
from .subtitles import compile_subtitles, fullwidth_units

# Keep the compiler entry point stable while installing the provenance-aware
# validator used by compile_render_plan. The renderer still has a single source
# of truth; only claim resolution is extended from direct IDs to verified E1 ancestry.
_render_plan._validate_claim_bindings = validate_claim_bindings
compile_render_plan = _render_plan.compile_render_plan

__all__ = [
    "compile_render_plan",
    "compile_subtitles",
    "fullwidth_units",
    "resolves_to_supporting_asset",
    "validate_claim_bindings",
]
