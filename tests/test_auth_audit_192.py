"""登录 / 登出审计与日期筛选（第 192 期）。"""
from __future__ import annotations

import time


def _auth_logs(client, headers, **params):
    return client.get("/api/logs", params={"action": "登录", "limit": 200, **params},
                      headers=headers).json()["items"]


def test_登录成功与失败都落审计(client, auth_headers, isolated):
    ok = client.post("/api/auth/login", json={"user": "admin", "pin": "test1234"})
    assert ok.status_code == 200
    items = _auth_logs(client, auth_headers)
    assert any(x["status"] == "成功" and x["actor"] == "admin" for x in items)

    bad = client.post("/api/auth/login", json={"user": "admin", "pin": "wrong-pin"})
    assert bad.status_code == 401
    items = _auth_logs(client, auth_headers)
    fail = [x for x in items if x["status"] == "失败" and x["actor"] == "admin"]
    assert fail and "密码错误" in fail[0]["detail"]

    r = client.post("/api/auth/logout", headers=auth_headers)
    assert r.status_code == 200
    out = client.get("/api/logs", params={"action": "登出", "limit": 20},
                     headers=auth_headers).json()["items"]
    assert out and out[0]["actor"] == "admin"


def test_审计日期范围筛选(client, auth_headers, isolated):
    now = time.time()
    client.post("/api/auth/login", json={"user": "admin", "pin": "test1234"})
    assert _auth_logs(client, auth_headers, since=now + 60) == []
    assert _auth_logs(client, auth_headers, until=now - 60) == []
    assert _auth_logs(client, auth_headers, since=now - 600, until=now + 600)
