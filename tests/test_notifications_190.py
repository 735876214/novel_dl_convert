"""通知中心：分页 / 隐藏 / 清空日志时清标记（第 190 期）。"""
from __future__ import annotations

from novelforge.core import activity_log, db


def _seed(n: int, prefix: str = "n190") -> None:
    for i in range(n):
        activity_log.log("测试", f"{prefix}-{i}.txt", "成功")


def test_通知分页与隐藏(client, auth_headers, isolated):
    _seed(5)
    r = client.get("/api/notifications", params={"limit": 2, "offset": 0},
                   headers=auth_headers).json()
    assert r["count"] == 2 and r["total"] >= 5
    assert r["has_more"] is True and r["next_offset"] == 2
    assert r["unread_total"] >= 5

    all_items = client.get("/api/notifications", params={"limit": 1000},
                           headers=auth_headers).json()["items"]
    ours = [x for x in all_items if str(x.get("file") or "").startswith("n190-")]
    assert len(ours) >= 5
    first = ours[0]["id"]

    # 隐藏一条：列表不再出现，活动日志本身还在（total 只少这一条）
    before_total = client.get("/api/notifications", headers=auth_headers).json()["total"]
    r = client.post("/api/notifications/dismiss", headers=auth_headers,
                    json={"ids": [first]})
    assert r.status_code == 200 and r.json()["dismissed"] == 1
    after = client.get("/api/notifications", params={"limit": 1000},
                       headers=auth_headers).json()
    assert first not in {x["id"] for x in after["items"]}
    assert after["total"] == before_total - 1

    # 全部隐藏：列表清空，未读数归零
    r = client.post("/api/notifications/dismiss", headers=auth_headers, json={"all": True})
    assert r.status_code == 200 and r.json()["dismissed"] >= 1
    assert client.get("/api/notifications", headers=auth_headers).json()["total"] == 0
    assert client.get("/api/notifications", headers=auth_headers).json()["unread_total"] == 0


def test_清空活动日志同时清已读与隐藏标记(client, auth_headers, isolated):
    _seed(3, prefix="n190clear")
    items = client.get("/api/notifications", params={"limit": 1000},
                       headers=auth_headers).json()["items"]
    ours = [x["id"] for x in items if str(x.get("file") or "").startswith("n190clear-")]
    client.post("/api/notifications/read", headers=auth_headers, json={"ids": ours})
    client.post("/api/notifications/dismiss", headers=auth_headers, json={"ids": ours})
    assert db.notification_read_ids() & set(ours)
    assert db.notification_dismissed_ids() & set(ours)

    r = client.delete("/api/logs", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["read_marks_cleared"] >= 0
    assert r.json()["dismiss_marks_cleared"] >= 0
    assert db.notification_read_ids() == set()
    assert db.notification_dismissed_ids() == set()
    assert client.get("/api/notifications", headers=auth_headers).json()["total"] == 0
