from video_agent.speech.v4.voice_resolve import resolve_fixed_voice_profile
from video_agent.speech.v4.narration_freeze import freeze_script_narration, freeze_goal_narration
from video_agent.speech.v4.tts import ensure_native_speech_timing_lock

__all__ = [
    "ensure_native_speech_timing_lock",
    "freeze_goal_narration",
    "freeze_script_narration",
    "resolve_fixed_voice_profile",
]
