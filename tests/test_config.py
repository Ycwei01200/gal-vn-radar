from __future__ import annotations

import pytest

from gal_radar.config import FollowConfig, SteamAppConfig, load_config


def test_invalid_notification_thresholds_fail_clearly(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "notification:\n  immediate_threshold: 40\n  digest_threshold: 70\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="digest_threshold"):
        load_config(path)


def test_resolved_developer_ids_are_runtime_only_and_rejected_in_yaml(tmp_path) -> None:
    invalid_path = tmp_path / "invalid-config.yaml"
    invalid_path.write_text(
        "follow:\n"
        "  developers:\n"
        "    - 枕\n"
        "  resolved_developer_ids:\n"
        "    - p30\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="resolved_developer_ids"):
        load_config(invalid_path)

    valid_path = tmp_path / "valid-config.yaml"
    valid_path.write_text(
        "follow:\n"
        "  developers:\n"
        "    - 枕\n",
        encoding="utf-8",
    )

    config = load_config(valid_path)
    config.follow.set_resolved_developer_ids(["p30"])

    assert config.follow.resolved_developer_ids == ["p30"]
    assert "resolved_developer_ids" not in config.model_dump()["follow"]


def test_steam_app_mapping_is_parsed_from_yaml(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "follow:\n"
        "  steam_apps:\n"
        "    - app_id: 123456\n"
        "      vn_id: v20431\n"
        "      title: サクラノ刻\n"
        "      developer: 枕\n",
        encoding="utf-8",
    )

    config = load_config(path)

    assert len(config.follow.steam_apps) == 1
    mapping = config.follow.steam_apps[0]
    assert mapping.app_id == 123456
    assert mapping.vn_id == "v20431"
    assert mapping.title == "サクラノ刻"
    assert mapping.developer == "枕"
    assert mapping.developer_ids == []


def test_discovered_steam_app_enriches_existing_mapping() -> None:
    follow = FollowConfig(
        steam_apps=[SteamAppConfig(app_id=123456, vn_id="v20431", title="サクラノ刻")]
    )

    follow.add_discovered_steam_app(
        SteamAppConfig(
            app_id=123456,
            vn_id="v20431",
            title="サクラノ刻",
            developer="Makura",
            developer_ids=["p30"],
        )
    )

    assert len(follow.steam_apps) == 1
    mapping = follow.steam_apps[0]
    assert mapping.developer == "Makura"
    assert mapping.developer_ids == ["p30"]


def test_invalid_steam_app_id_fails_configuration(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(
        "follow:\n"
        "  steam_apps:\n"
        "    - app_id: 0\n"
        "      vn_id: v20431\n"
        "      title: サクラノ刻\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="app_id"):
        load_config(path)
