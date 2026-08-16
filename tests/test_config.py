from __future__ import annotations

import pytest

from gal_radar.config import load_config


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
