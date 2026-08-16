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
