from __future__ import annotations

import html
import re
from datetime import UTC, datetime

from gal_radar.models.event import EventType


def classify_news(title: str, contents: str, tags: list[str]) -> EventType:
    haystack = " ".join([title, contents, *tags]).casefold()
    if _contains_any(haystack, ("延期", "delay", "delayed", "postpone", "postponed")):
        return EventType.DELAY
    if _contains_any(
        haystack,
        ("release date", "launch date", "発売日", "發售日", "发售日"),
    ):
        return EventType.RELEASE_DATE
    if _contains_any(
        haystack,
        ("demo", "体験版", "體驗版", "试玩版", "trial version"),
    ):
        return EventType.DEMO
    if _contains_any(haystack, ("devlog", "developer update", "開発日誌", "開發日誌")):
        return EventType.DEVLOG
    if _contains_any(
        haystack,
        ("patch", "hotfix", "update", "更新", "アップデート", "version ", "ver."),
    ):
        return EventType.PATCH
    if _contains_any(haystack, ("trailer", "movie", "pv", "プロモーションムービー")):
        return EventType.TRAILER
    if _contains_any(
        haystack,
        (
            "now available",
            "available now",
            "released today",
            "now on sale",
            "発売開始",
            "正式發售",
            "正式发售",
        ),
    ):
        return EventType.RELEASED
    return EventType.OTHER


def _contains_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle.casefold() in value for needle in needles)


def extract_release_date(value: str) -> str | None:
    iso_match = re.search(r"\b(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})\b", value)
    if iso_match:
        return _validated_date(*iso_match.groups())

    month_names = {
        name.casefold(): number
        for number, name in enumerate(
            (
                "January",
                "February",
                "March",
                "April",
                "May",
                "June",
                "July",
                "August",
                "September",
                "October",
                "November",
                "December",
            ),
            start=1,
        )
    }
    month_pattern = "|".join(month_names)
    mdy_match = re.search(
        rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(20\d{{2}})\b",
        value,
        flags=re.IGNORECASE,
    )
    if mdy_match:
        month, day, year = mdy_match.groups()
        return _validated_date(year, str(month_names[month.casefold()]), day)

    dmy_match = re.search(
        rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_pattern})\s+(20\d{{2}})\b",
        value,
        flags=re.IGNORECASE,
    )
    if dmy_match:
        day, month, year = dmy_match.groups()
        return _validated_date(year, str(month_names[month.casefold()]), day)
    return None


def _validated_date(year: str, month: str, day: str) -> str | None:
    try:
        parsed = datetime(int(year), int(month), int(day), tzinfo=UTC)
    except ValueError:
        return None
    return parsed.date().isoformat()


def summarize_text(title: str, contents: str) -> str:
    cleaned = plain_text(contents)
    if cleaned:
        return f"{title.strip()} — {cleaned}"[:500].rstrip()
    return title.strip()[:500]


def plain_text(value: str) -> str:
    without_bbcode = re.sub(r"\[/?[^\]]+\]", " ", value)
    without_html = re.sub(r"<[^>]+>", " ", without_bbcode)
    return re.sub(r"\s+", " ", html.unescape(without_html)).strip()
