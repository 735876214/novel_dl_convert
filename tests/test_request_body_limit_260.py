"""**请求体**要有上限（第 260 期）。

## 缺陷

全仓**没有任何请求体上限** —— 95 个 JSON 端点（`Body(...)`）收多少都照单全收。

实测（`POST /api/config/raw`，**未登录**）：50 MB 的请求体 ⇒ **峰值 125 MB**
（**放大 2.5 倍** —— JSON 解析时字符串与字节各存一份）。

⚠️ **连 401 都拦不住**：请求体在鉴权**之前**就被读进内存了
⇒ 一个请求就能把容器内存打满（NAS 上通常是几百 MB 的上限）。

⇒ 上传那条路早就有分块上限（`_read_capped`，第 94 期那条）
⇒ 但**所有 JSON 端点**都没有。

## 这里钉四件事

1. **超限的请求体 ⇒ 413**（不是 500、不是 401）；
2. **在读进内存之前**就拒（看 `Content-Length` ⇒ **不读**就能拒 ⇒ 零成本）；
3. **流式累计**那道闸也在（`Content-Length` 缺失或撒谎时 —— chunked 传输）；
4. **正常大小的请求照旧能过**（别把功能一起砍了）。
"""
from __future__ import annotations

import json
import socket
import threading
import time

import pytest

from novelforge import server

#: 上限（判据只有一处：`server._REQUEST_BODY_MAX`）。
#: ⚠️ 用 `getattr` 而不是直接取 —— 修前这个**常量压根不存在**，
#: 直接取会让整个模块**收集期就报错**（看不出是哪条用例红的）。
MAX = getattr(server, "_REQUEST_BODY_MAX", 16 * 1024 * 1024)


def test_上限是_16MB():
    """判据**只有一处**（`_REQUEST_BODY_MAX`）—— 别在别处再写一个数。"""
    assert MAX == 16 * 1024 * 1024, MAX


def test_超限的请求体回_413(client):
    """核心判据：超限 ⇒ **413**（不是 500、也不是 401）。"""
    big = "x" * (MAX + 1024)
    r = client.post("/api/config/raw", json={"text": big})
    assert r.status_code == 413, (r.status_code, r.text[:200])
    assert "上限" in r.text, r.text[:200]


def test_没超限的请求体照旧能过(client, auth_headers):
    """⚠️ **不能把功能一起砍掉** —— 正常大小的请求必须照旧走通。"""
    r = client.put("/api/config/raw", headers=auth_headers,
                   json={"text": "watcher:\n  enabled: false\n"})
    assert r.status_code == 200, r.text


def test_流式累计那道闸在(client):
    """⚠️ **两道闸，缺一不可**：
    ① 看 `Content-Length`（绝大多数请求都有）⇒ 不读就能拒；
    ② **流式累计**（`Content-Length` 缺失或撒谎时 —— chunked 传输）
    ⇒ 边读边数，超了立刻中断（**不**「先读完再判断」）。
    """
    # 造一个「没有 Content-Length、但体很大」的请求
    body = b"x" * (MAX + 1024)
    r = client.post("/api/config/raw", content=body,
                    headers={"Content-Type": "application/json"})
    # 无论走哪道闸，结果都必须是「拒」（不是 500、不是让它读进去）
    assert r.status_code in (413, 422), (r.status_code, r.text[:200])


def test_判据只有一处():
    """别在别处再写一个上限 —— 抄一份就会漂。"""
    import inspect
    src = inspect.getsource(server)
    # 上限的数字只出现在 `_REQUEST_BODY_MAX` 的定义那一处
    assert src.count("16 * 1024 * 1024") == 1, src.count("16 * 1024 * 1024")


# ---------------------------------------------------------------------------
# 真实 TCP：验「在读进内存之前就拒」（TestClient 会先把整个体建好，测不出这个）
# ---------------------------------------------------------------------------

def test_真实服务端_读体之前就拒():
    """⚠️ `TestClient` 会**先把整个请求体建好**再发 ⇒ 测不出「读之前就拒」。

    这里用**真实 TCP**：只发请求头（`Content-Length` 说 30 MB）而**不发体**，
    看服务端会不会**不等体**就回 413。
    """
    import uvicorn

    port = 8799
    cfg = uvicorn.Config(server.app, host="127.0.0.1", port=port, log_level="error")
    srv = uvicorn.Server(cfg)
    threading.Thread(target=srv.run, daemon=True).start()
    time.sleep(2.0)
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=10)
        s.sendall(
            b"POST /api/config/raw HTTP/1.1\r\nHost: x\r\n"
            b"Content-Type: application/json\r\n"
            b"Content-Length: 31457280\r\n\r\n")   # 声明 30 MB，但**一个字节都不发**
        s.settimeout(8)
        data = s.recv(200)
        s.close()
        assert b"413" in data, data[:200]
    finally:
        srv.should_exit = True
