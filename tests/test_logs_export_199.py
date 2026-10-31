"""审计日志服务端 CSV 导出（第 199 期）。"""
from __future__ import annotations

from novelforge.core import activity_log


def test_服务端导出_csv带筛选(client, auth_headers, isolated):
    activity_log.log("测试导出", "a.txt", "成功", detail="第一条")
    activity_log.log("测试导出", "b.txt", "失败", detail="第二条")
    r = client.get("/api/logs/export", params={"action": "测试导出", "status": "成功"},
                   headers=auth_headers)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    lines = [x for x in text.splitlines() if x.strip()]
    assert lines[0].startswith("ts,action,status,file")
    assert len(lines) == 2 and "a.txt" in lines[1] and "b.txt" not in text

    # 日期筛选透传（未来时间 → 空表，只有表头）
    r = client.get("/api/logs/export", params={"action": "测试导出", "since": 9999999999},
                   headers=auth_headers)
    assert len([x for x in r.content.decode("utf-8-sig").splitlines() if x.strip()]) == 1
