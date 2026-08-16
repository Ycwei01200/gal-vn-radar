from __future__ import annotations

import asyncio
from pathlib import Path

from gal_radar.config import AppConfig
from gal_radar.main import run_doctor, run_test_telegram
from gal_radar.models.event import EventType, NotificationStatus, SourceEvent
from gal_radar.notifications.telegram import render_zh_tw_notification
from gal_radar.services.normalize import normalize_event
from gal_radar.services.pipeline import Pipeline
from gal_radar.services.ranking import ScoreResult


class _FailingNotifier:
    async def send(self, *args, **kwargs):
        raise AssertionError("disabled event type must not be delivered")


def test_disabled_event_type_is_stored_as_skipped(event_store) -> None:
    config = AppConfig.model_validate(
        {
            "follow": {"visual_novels": ["v1"]},
            "notification": {
                "immediate_threshold": 70,
                "digest_threshold": 40,
                "enabled_event_types": ["RELEASED"],
            },
        }
    )
    pipeline = Pipeline(
        config=config,
        store=event_store,
        adapters=[],
        notifier=_FailingNotifier(),
    )
    event = SourceEvent(
        source="steam",
        source_event_id="steam:1:patch-1",
        vn_id="v1",
        event_type=EventType.PATCH,
        title="Example VN",
        url="https://example.com/patch-1",
    )

    record = asyncio.run(pipeline._process_one(event))

    assert record is not None
    assert record.relevance_score >= config.notification.immediate_threshold
    assert record.notification_status == NotificationStatus.SKIPPED.value


def test_source_priority_changes_display_order(event_store) -> None:
    normalized = normalize_event(
        SourceEvent(
            source="vndb",
            source_event_id="v1:released",
            vn_id="v1",
            event_type=EventType.RELEASED,
            title="Example VN",
            url="https://vndb.org/v1",
        )
    )
    record = event_store.add(normalized, ScoreResult(score=100, reasons=()))
    event_store.add_corroborating_source(
        record.id,
        {
            "source": "steam",
            "source_event_id": "steam:1:released",
            "url": "https://store.steampowered.com/app/1",
        },
    )
    event_store.add_corroborating_source(
        record.id,
        {
            "source": "rss",
            "source_event_id": "rss:released",
            "url": "https://example.com/released",
        },
    )
    record = event_store.list_events()[0]

    message = render_zh_tw_notification(
        record,
        source_priority=["rss", "steam", "vndb"],
    )

    assert "來源：官方 RSS、Steam、VNDB" in message


def test_doctor_reports_warnings_without_external_calls(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}\n", encoding="utf-8")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    code = run_doctor(
        config_path=str(config_path),
        database_path=str(tmp_path / "doctor.db"),
    )

    output = capsys.readouterr().out
    assert code == 0
    assert "WARN no follow targets are configured" in output
    assert "WARN TELEGRAM_BOT_TOKEN is missing" in output
    assert "WARN TELEGRAM_CHAT_ID is missing" in output


def test_test_telegram_dry_run_does_not_require_credentials(capfd) -> None:
    code = asyncio.run(run_test_telegram(dry_run=True))

    output = capfd.readouterr().out
    assert code == 0
    assert "Gal/VN Radar Telegram 測試成功" in output


def test_default_phase4_preferences_are_backward_compatible() -> None:
    config = AppConfig()

    assert config.notification.enabled_event_types == list(EventType)
    assert config.preferences.source_priority == ["vndb", "steam", "itch.io", "rss"]
