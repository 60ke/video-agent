from __future__ import annotations

from video_agent.contracts import SemanticSfx


_PROFILES: dict[str, dict[str, SemanticSfx]] = {
    "short_video_ui_v1": {
        "menu_hover": SemanticSfx(
            path="assets/audio/sfx/menu_hover.wav",
            gain_db=-19.0,
            max_duration_ms=180,
            fade_out_ms=45,
            priority=25,
        ),
        "ui_click": SemanticSfx(
            path="assets/audio/sfx/ui_click.wav",
            gain_db=-16.0,
            max_duration_ms=160,
            fade_out_ms=40,
            priority=60,
        ),
        "field_focus": SemanticSfx(
            path="assets/audio/sfx/field_focus.wav",
            gain_db=-18.0,
            max_duration_ms=220,
            fade_out_ms=55,
            priority=45,
        ),
        "upload": SemanticSfx(
            path="assets/audio/sfx/upload.wav",
            gain_db=-17.0,
            max_duration_ms=380,
            fade_out_ms=80,
            priority=65,
        ),
        "result_reveal": SemanticSfx(
            path="assets/audio/sfx/result_reveal.wav",
            gain_db=-15.0,
            max_duration_ms=520,
            fade_out_ms=120,
            priority=80,
        ),
        "page_flip": SemanticSfx(
            path="assets/audio/sfx/page_flip.wav",
            gain_db=-19.0,
            max_duration_ms=300,
            fade_out_ms=90,
            priority=40,
        ),
        "success": SemanticSfx(
            path="assets/audio/sfx/success.wav",
            gain_db=-16.0,
            max_duration_ms=620,
            fade_out_ms=140,
            priority=85,
        ),
    }
}


def get_sfx_profile(name: str | None) -> dict[str, SemanticSfx]:
    if name is None:
        return {}
    if name not in _PROFILES:
        raise ValueError(f"unknown SFX profile: {name}")
    return {key: value.model_copy(deep=True) for key, value in _PROFILES[name].items()}


def merge_sfx_profile(name: str | None, overrides: dict[str, SemanticSfx]) -> dict[str, SemanticSfx]:
    profile = get_sfx_profile(name)
    profile.update({key: value.model_copy(deep=True) for key, value in overrides.items()})
    return profile
