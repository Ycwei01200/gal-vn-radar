from __future__ import annotations

from dataclasses import dataclass

from gal_radar.config import AppConfig
from gal_radar.models.event import NormalizedEvent


@dataclass(frozen=True, slots=True)
class ScoreResult:
    score: int
    reasons: tuple[str, ...]


def score_event(event: NormalizedEvent, config: AppConfig) -> ScoreResult:
    score = 0
    reasons: list[str] = []
    followed_vns = {_normalized(item) for item in config.follow.visual_novels}
    if event.vn_id and _normalized(event.vn_id) in followed_vns:
        score += config.scoring.followed_vn
        reasons.append("followed visual novel")
    elif _normalized(event.title) in followed_vns:
        score += config.scoring.followed_vn
        reasons.append("followed visual novel")

    followed_developers = {_normalized(item) for item in config.follow.developers}
    for developer in event.developer_names:
        if _normalized(developer) in followed_developers:
            score += config.scoring.followed_developer
            reasons.append(f"followed developer: {developer}")
            break

    preferred_tags = {_normalized(item) for item in config.follow.tags}
    for tag in event.tags:
        if _normalized(tag) in preferred_tags:
            score += config.scoring.preferred_tag
            reasons.append(f"matched tag: {tag}")

    event_weight = config.scoring.event_type.get(event.event_type, 0)
    if event_weight:
        score += event_weight
        reasons.append(f"event type: {event.event_type.value}")

    return ScoreResult(score=score, reasons=tuple(reasons))


def _normalized(value: str) -> str:
    return value.strip().casefold()
