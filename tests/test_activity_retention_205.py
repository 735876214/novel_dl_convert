"""审计归档按天保留（第 205 期）。"""
from __future__ import annotations

import os
import time

from novelforge.core import activity_log


def test_归档按天数清理(tmp_path):
    old = tmp_path / "activity-2020-01-01.log"
    new = tmp_path / "activity-2026-01-01.log"
    old.write_text("old")
    new.write_text("new")
    ten_days = 10 * 86400
    os.utime(old, (time.time() - ten_days, time.time() - ten_days))

    activity_log._prune_archives(tmp_path, keep=10, max_days=7)
    assert not old.exists() and new.exists()

    # max_days=0 = 不按时间清理
    old.write_text("old")
    os.utime(old, (time.time() - ten_days, time.time() - ten_days))
    activity_log._prune_archives(tmp_path, keep=10, max_days=0)
    assert old.exists() and new.exists()


def test_留存配置的边界(monkeypatch):
    monkeypatch.setattr("novelforge.config.load_config",
                        lambda: {"logging": {"retention": {"max_days": 9999}}})
    activity_log.invalidate_retention_cache()
    assert activity_log.retention_cfg()["max_days"] == 3650

    monkeypatch.setattr("novelforge.config.load_config",
                        lambda: {"logging": {"retention": {"max_days": -3}}})
    activity_log.invalidate_retention_cache()
    assert activity_log.retention_cfg()["max_days"] == 0
