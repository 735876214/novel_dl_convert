"""版本标识同源（第 30 期）：/health 下发的 version 必须等于后端唯一常量。

防止再分叉出第二个真值源（历史坑：后端写死 0.5.0、前端又手写 v0.6，两处各说各话）。
"""
from novelforge import server


def test_health_exposes_version_matching_single_source(client):
    # /health 在鉴权中间件白名单内（server.py 的 _auth_middleware），免鉴权
    r = client.get("/api/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "version" in body, "/health 必须下发 version"
    assert body["version"] == server.APP_VERSION
    assert body["version"], "版本号不应为空"
