"""阅读状态 8 档（第 201 期）。"""
from __future__ import annotations

from novelforge.core import db


def test_八档状态与日期规则(isolated):
    assert db.READ_STATUSES == (
        "unread", "want_to_read", "reading", "rereading",
        "finished", "skimmed", "paused", "abandoned",
    )
    bid = "lib$status201"

    db.set_status(bid, "want_to_read")
    s = db.get_status(bid)
    assert s["status"] == "want_to_read" and s["started_at"] == 0 and s["finished_at"] == 0

    db.set_status(bid, "reading")
    s = db.get_status(bid)
    assert s["started_at"] > 0 and s["finished_at"] == 0

    db.set_status(bid, "rereading")
    s = db.get_status(bid)
    assert s["started_at"] > 0 and s["finished_at"] == 0

    db.set_status(bid, "skimmed")
    s = db.get_status(bid)
    assert s["started_at"] > 0 and s["finished_at"] > 0

    db.set_status(bid, "paused")
    s = db.get_status(bid)
    assert s["started_at"] > 0 and s["finished_at"] == 0

    db.set_status(bid, "want_to_read")
    s = db.get_status(bid)
    assert s["started_at"] == 0 and s["finished_at"] == 0
