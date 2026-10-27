"""实时事件总线 + `/ws`（第 153 期）。

覆盖三件事：
1. 没有订阅者时 `publish()` 是空操作（CLI / 单测不会因为「没人听」报错）；
2. `/ws` 必须带有效 token，否则以 4401 关闭（前端据此停止重连）；
3. 带 token 连上后能收到 `hello` 与后续 `publish()` 的事件。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from novelforge.core import events


def test_没有订阅者时_publish_是空操作() -> None:
    # 不抛异常即可；CLI / 后台线程在没人连时也会调用它。
    events.publish("test:noop", {"a": 1})
    assert events.subscriber_count() >= 0


def test_ws_无令牌以_4401_关闭(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect) as exc:
        with client.websocket_connect("/ws"):
            pass
    assert exc.value.code == 4401


def test_ws_带令牌能收到_hello_与事件(client: TestClient, auth_headers: dict) -> None:
    token = auth_headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect(f"/ws?token={token}") as ws:
        hello = ws.receive_json()
        assert hello["event"] == "hello"
        assert hello["data"]["version"]

        events.publish("book-dock:changed", {"item": "三体.epub"})
        msg = ws.receive_json()
        assert msg["event"] == "book-dock:changed"
        assert msg["data"]["item"] == "三体.epub"
