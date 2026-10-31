"""元数据检索缓存统计 / 书源搜索健康（第 193 期）。"""
from __future__ import annotations

from novelforge.core import db, metasources


def test_检索缓存统计与清空(client, auth_headers, isolated):
    metasources.clear_cache()
    metasources._cache_put(("test-key",), [{"title": "a"}], 60)
    r = client.get("/api/metadata/cache", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["entries"] == 1 and r.json()["max"] > 0

    r = client.delete("/api/metadata/cache", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["cleared"] == 1 and r.json()["entries"] == 0


def test_书源搜索健康落账与清零(client, auth_headers, isolated):
    db.source_ledger_upsert("测试源", origin="test", supported="yes")
    db.record_source_search("测试源", False, "超时")
    db.record_source_search("测试源", False, "连接失败")
    row = db.source_ledger_get("测试源")
    assert row["search_fail_count"] == 2
    assert row["last_search_error"] == "连接失败"
    assert row["last_search_at"] > 0

    db.record_source_search("测试源", True)
    row = db.source_ledger_get("测试源")
    assert row["search_fail_count"] == 0 and row["last_search_error"] == ""

    # 台账接口也带这三列（前端据此显示「连续失败 N 次」）
    items = client.get("/api/sources/ledger", headers=auth_headers).json()["items"]
    mine = next(x for x in items if x["name"] == "测试源")
    assert mine["search_fail_count"] == 0 and "last_search_at" in mine

    # 台账里没有的源：静默跳过，不报错也不插行
    db.record_source_search("不存在", False, "x")
    assert db.source_ledger_get("不存在") is None
