"""`/health` 的「监听没在跑」**只在监听本该开着时**才算问题（第 251 期）。

## 缺陷

`_health_checks()` 此前**一律**在 `watcher_running` 为假时追加
「收书监听没在跑（新文件不会被自动收进来）」。

但**用户主动关掉监听**（设置页关）时，他就是要它关 —— 那不是故障。可此前
`/health` 会长期返回 `status: "degraded"` ⇒ 用户自己的监控（Uptime 之类）
一直报警，而**他什么都没做错**。

⇒ 判据改成：**只在 `watcher.enabled` 为真（监听本该开着）却没跑时**才报。
`checks.watcher_running` 这个**事实**照旧给（前端与监控仍能看到「没在跑」）。

## 这里钉两条

1. 监听**关着** ⇒ `/health` 不把它算问题（`problems` 里没有那条、`status` 不是 degraded）；
2. 监听**开着**却没跑 ⇒ **照旧**要报（不能因为这次修改把真问题也藏了）。
"""
from __future__ import annotations


def _health(client, headers) -> dict:
    """**鉴权后**的完整快照（第 258 期：`problems` 挪到了 `GET /api/health`）。

    ⚠️ 免鉴权的 `/health` 现在**只给条数**（`problem_count`）——
    人话清单带**绝对路径** ⇒ 不能给任何人（第 258 期）。
    """
    r = client.get("/api/health", headers=headers)
    assert r.status_code in (200, 503), r.text
    return r.json()


def test_监听被关掉时不算问题(client, auth_headers, isolated):
    """`isolated` 把 `AUTO_WATCH` 设成 false ⇒ 监听是**用户主动关的**。"""
    body = _health(client, auth_headers)
    assert not any("监听" in p for p in body["problems"]), body["problems"]
    assert body["status"] != "degraded", body


def test_监听开着却没跑时照旧要报(client, auth_headers, isolated, monkeypatch):
    """⚠️ 不能因为这次修改把**真问题**也藏了。"""
    monkeypatch.setenv("AUTO_WATCH", "true")
    from novelforge import config
    config.load_config()
    body = _health(client, auth_headers)
    assert any("监听" in p for p in body["problems"]), body["problems"]
    assert body["status"] == "degraded", body
