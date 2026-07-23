"""Resolve semantic motion intents against Jianying's native effect catalog."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


def _normalized(value: str) -> str:
    return re.sub(r"[\s_\-]+", "", value).casefold()


@dataclass(frozen=True)
class NativeEffectQuery:
    enum_name: str
    keywords: tuple[str, ...]
    allow_vip: bool = True
    prefer_free: bool = False


@dataclass(frozen=True)
class NativeEffectCandidate:
    enum_name: str
    member_name: str
    display_name: str
    effect_id: str
    is_vip: bool
    default_duration_us: int
    enum_member: Any

    def manifest_record(
        self,
        *,
        target_id: str,
        intent: str,
        applied_duration_us: int,
    ) -> dict[str, Any]:
        return {
            "target_id": target_id,
            "intent": intent,
            "enum_name": self.enum_name,
            "member_name": self.member_name,
            "display_name": self.display_name,
            "effect_id": self.effect_id,
            "is_vip": self.is_vip,
            "default_duration_us": self.default_duration_us,
            "applied_duration_us": applied_duration_us,
        }


class NativeEffectCatalog:
    """Search enum metadata shipped with the installed Jianying skill."""

    def __init__(self, draft: Any) -> None:
        self.draft = draft

    def candidates(self, enum_name: str) -> list[NativeEffectCandidate]:
        enum_type = getattr(self.draft, enum_name, None)
        if enum_type is None:
            raise RuntimeError(f"Jianying effect enum unavailable: {enum_name}")

        candidates: list[NativeEffectCandidate] = []
        for member in enum_type:
            metadata = member.value
            display_name = str(
                getattr(metadata, "title", getattr(metadata, "name", member.name))
            )
            candidates.append(
                NativeEffectCandidate(
                    enum_name=enum_name,
                    member_name=member.name,
                    display_name=display_name,
                    effect_id=str(getattr(metadata, "effect_id", "")),
                    is_vip=bool(getattr(metadata, "is_vip", False)),
                    default_duration_us=int(
                        getattr(
                            metadata,
                            "duration",
                            getattr(metadata, "default_duration", 500_000),
                        )
                    ),
                    enum_member=member,
                )
            )
        return candidates

    def resolve(self, query: NativeEffectQuery) -> NativeEffectCandidate:
        ranked: list[tuple[int, NativeEffectCandidate]] = []
        for candidate in self.candidates(query.enum_name):
            if candidate.is_vip and not query.allow_vip:
                continue
            searchable = _normalized(
                f"{candidate.member_name} {candidate.display_name}"
            )
            score = 0
            for keyword_index, keyword in enumerate(query.keywords):
                normalized_keyword = _normalized(keyword)
                if searchable == normalized_keyword * 2:
                    match_score = 20_000
                elif _normalized(candidate.member_name) == normalized_keyword:
                    match_score = 20_000
                elif _normalized(candidate.display_name) == normalized_keyword:
                    match_score = 19_000
                elif normalized_keyword in searchable:
                    match_score = 10_000
                else:
                    continue
                score = max(score, match_score - keyword_index * 500)
            if not score:
                continue
            if query.prefer_free and candidate.is_vip:
                score -= 12_000
            ranked.append((score, candidate))

        if not ranked:
            raise RuntimeError(
                "No Jianying native effect matched "
                f"{query.enum_name}: {', '.join(query.keywords)}"
            )
        ranked.sort(
            key=lambda item: (
                -item[0],
                item[1].is_vip,
                item[1].member_name,
            )
        )
        return ranked[0][1]


def clip_motion_query(clip: Any, *, is_first_clip: bool) -> tuple[str, NativeEffectQuery] | None:
    """Translate scene semantics into catalog search intent."""
    if is_first_clip and clip.motion_context == "site_home":
        return (
            "website_book_open",
            NativeEffectQuery("IntroType", ("翻书", "翻页", "翻入")),
        )
    if clip.motion_context == "parameter":
        return (
            "parameter_reveal",
            NativeEffectQuery(
                "IntroType",
                ("展开", "渐显", "轻微放大"),
                prefer_free=True,
            ),
        )
    if clip.motion_context == "result":
        if clip.asset_orientation == "landscape":
            return (
                "landscape_result_focus",
                NativeEffectQuery(
                    "GroupAnimationType",
                    ("拉镜", "放大弹动", "放大"),
                    prefer_free=True,
                ),
            )
        return (
            "portrait_result_focus",
            NativeEffectQuery(
                "IntroType",
                ("轻微放大", "放大", "渐显"),
                prefer_free=True,
            ),
        )
    if clip.motion_context == "site_home":
        return (
            "website_settle",
            NativeEffectQuery(
                "IntroType",
                ("缩小", "渐显", "翻入"),
                prefer_free=True,
            ),
        )
    return None


def transition_motion_query(
    previous_clip: Any,
    current_clip: Any,
) -> tuple[str, str, NativeEffectQuery]:
    """Return intent, consistency group, and catalog query for a boundary."""
    if (
        previous_clip.scene_id == current_clip.scene_id
        and previous_clip.motion_context == "gallery"
    ):
        return (
            "gallery_page_turn",
            f"gallery:{previous_clip.scene_id}",
            NativeEffectQuery(
                "TransitionType",
                ("翻页", "上下翻页", "左移"),
                prefer_free=True,
            ),
        )
    if (
        previous_clip.scene_id == current_clip.scene_id
        and previous_clip.motion_context
        in {"reference_result", "result_flat_plan"}
    ):
        return (
            "causal_before_after",
            f"causal:{previous_clip.scene_id}",
            NativeEffectQuery(
                "TransitionType",
                ("前后对比_II", "前后对比", "叠化"),
                prefer_free=True,
            ),
        )
    if current_clip.motion_context == "site_home":
        return (
            "website_book_close",
            f"website:{current_clip.scene_id}",
            NativeEffectQuery(
                "TransitionType",
                ("翻书转场", "翻页", "叠化"),
            ),
        )
    return (
        "scene_soft_transition",
        f"boundary:{previous_clip.scene_id}:{current_clip.scene_id}",
        NativeEffectQuery(
            "TransitionType",
            ("叠化", "淡入淡出"),
            prefer_free=True,
        ),
    )
