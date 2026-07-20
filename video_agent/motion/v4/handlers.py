"""Importable Effect Registry handlers.

Stage 5 Motion Assignment selects effect IDs from the registry. These callables
exist so Hub can validate `handler` references at load time without pulling V3
EFFECTS. Bodies are Stage 6 / Remotion adapter stubs (`runtime: noop`); they do
not render pixels in Stage 5.
"""

from __future__ import annotations


def none(*, effect_id: str = "none", **_kwargs) -> dict[str, str]:
    return {"effect_id": effect_id, "runtime": "noop"}


def fade_in(**kwargs) -> dict[str, str]:
    return none(effect_id="fade_in", **kwargs)


def result_reveal(**kwargs) -> dict[str, str]:
    return none(effect_id="result_reveal", **kwargs)


def detail_push_in(**kwargs) -> dict[str, str]:
    return none(effect_id="detail_push_in", **kwargs)


def full_bleed_to_safe_card(**kwargs) -> dict[str, str]:
    return none(effect_id="full_bleed_to_safe_card", **kwargs)


def spring_card_pop(**kwargs) -> dict[str, str]:
    return none(effect_id="spring_card_pop", **kwargs)


def card_flip_3d(**kwargs) -> dict[str, str]:
    return none(effect_id="card_flip_3d", **kwargs)


def paper_curl_flip(**kwargs) -> dict[str, str]:
    return none(effect_id="paper_curl_flip", **kwargs)


def slide_gallery(**kwargs) -> dict[str, str]:
    return none(effect_id="slide_gallery", **kwargs)


def card_stack(**kwargs) -> dict[str, str]:
    return none(effect_id="card_stack", **kwargs)


def grid_reveal(**kwargs) -> dict[str, str]:
    return none(effect_id="grid_reveal", **kwargs)


def before_after(**kwargs) -> dict[str, str]:
    return none(effect_id="before_after", **kwargs)


def light_sweep(**kwargs) -> dict[str, str]:
    return none(effect_id="light_sweep", **kwargs)


def brand_breath(**kwargs) -> dict[str, str]:
    return none(effect_id="brand_breath", **kwargs)
