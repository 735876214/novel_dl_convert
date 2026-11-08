"""持续审计第 4 轮（第 276 期）：**开着的 WebSocket 不认「改口令」**。

这一轮扫了三个角度，两个零发现（**别重查**）：

- **WS 的订阅者生命周期**：连 3 次、每次收完 hello 就断 ⇒ `events.subscriber_count()`
  每次都回到基线 0（`finally: unsubscribe` 有效，没有订阅者泄漏）。
- **空形状**：`/api/v1/collections`、`/readlists`、`/collections/{cid}/series`、
  `/books/{id}/readlists` 在「什么都没有」时都是**空分页**（`totalElements=0` 且
  壳字段齐全），不编条目。

一条发现：**改口令之后，已经开着的 WebSocket 继续收事件**。

`/ws` 在**建立连接时**验一次票（`verify_token`），之后进入循环再也不验。于是：

```
连上（票合法） → 收到 hello ✓
改口令（`POST /api/auth/pin`，`_cred_version` 变） → 旧票走 HTTP **立刻 401**
publish 一条事件 → 旧连接**仍然收到**  ← 应该被断开
```

而「改口令 = 把此前签发的全部令牌作废、断开所有设备」正是这个动作的语义
（第 137 期给 OPDS/Komga 加的那套，第 240 期又补了重置）。前端标签页开着就一直在听
任务进度 / 书库变化 / 活动日志，直到它自己重连才会被 401 挡住。

**修法**：在 WS 循环里每 `_WS_RECHECK_SECONDS`（30 s）**或每收到一条事件**复核一次票；
失效就按 **4401** 关闭（前端见到 4401 会停止重连、等下次登录，见 `lib/realtime.ts`）。
"""
import pytest

from novelforge.core import events


def _tok(auth_headers: dict) -> str:
    return auth_headers["Authorization"].split(" ", 1)[1]


def test_改口令后旧连接被断开(client, auth_headers):
    tok = _tok(auth_headers)
    with client.websocket_connect("/ws?token=" + tok) as ws:
        assert ws.receive_json()["event"] == "hello"
        events.publish("book:progress-changed", {"book_id": "x", "percent": 10})
        assert ws.receive_json()["event"] == "book:progress-changed"

        r = client.post("/api/auth/pin", headers=auth_headers,
                        json={"old_pin": "test1234", "new_pin": "newpin99"})
        assert r.status_code == 200, r.text
        assert client.get("/api/books", headers=auth_headers).status_code == 401, \
            "用例前提：改口令后旧票在 HTTP 侧已经失效"

        events.publish("book:progress-changed", {"book_id": "y", "percent": 20})
        with pytest.raises(Exception) as exc:
            ws.receive_json()
        # Starlette 的测试会话把关闭码带在异常里；4401 = 「别重连」
        assert getattr(exc.value, "code", None) == 4401, \
            f"旧连接没有被断开（{exc.value!r}）—— 改口令之后它还在收事件流"


def test_正常连接照常收发(client, auth_headers):
    """复核不许把正常连接掐掉。"""
    tok = _tok(auth_headers)
    with client.websocket_connect("/ws?token=" + tok) as ws:
        assert ws.receive_json()["event"] == "hello"
        for i in range(3):
            events.publish("book-dock:changed", {"item": f"书{i}.epub"})
            assert ws.receive_json()["data"]["item"] == f"书{i}.epub"


def test_断开后订阅者清零(client, auth_headers):
    tok = _tok(auth_headers)
    base = events.subscriber_count()
    for _ in range(3):
        with client.websocket_connect("/ws?token=" + tok) as ws:
            ws.receive_json()
        assert events.subscriber_count() == base, "断开后订阅者没有清理（会越连越多）"
