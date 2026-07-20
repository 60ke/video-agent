from __future__ import annotations


class Stage5Error(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        scene_id: str | None = None,
        details: dict | None = None,
    ) -> None:
        self.code = code
        self.scene_id = scene_id
        self.details = details or {}
        parts = [code, message]
        if scene_id:
            parts.append(f"scene={scene_id}")
        super().__init__(" | ".join(parts))
