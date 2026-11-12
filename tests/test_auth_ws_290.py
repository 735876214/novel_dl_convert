"""认证 / 实时通道的四个判据（第 290 期全项目审计第 10 轮）。

## 为什么要有这份测试

这一轮的三处缺陷都在「测试绿、真部署却不一样」的缝里：

1. **`/ws` 在所有部署里其实是死的**。`tests/test_realtime.py` 用 `TestClient`
   自带 WebSocket 实现，全绿；但裸 `uvicorn`（`requirements.txt` 里只有 `uvicorn>=0.29`）
   没有 WS 后端，真握手回 **404**，前端只是静默退回轮询。⇒ 钉「requirements 声明了
   WS 后端，且当前解释器里真的装得到」。
2. **WS 令牌进日志**。修好 (1) 之后，uvicorn 的握手日志走 `uvicorn.error`（INFO），
   URL 在 `args[1]`；而第 134 期的打码器只挂在 `uvicorn.access`、只认 `args[2]`。
   ⇒ 钉两条 logger、两种参数形状都打码。
3. **未鉴权入口的输入没有上限**。`/api/auth/login` 的账号名会进 `auth._fails` 的键
   （只增不减）和审计日志的 actor。一个 16 MB 的账号名能被持久写进审计日志。
   ⇒ 钉「超长输入 400，且不落任何持久结构」；退避表另有条目上限。

另外顺手钉住 `verify_token` 对**含点用户名**的处理：`AUTH_USER=john.doe` 时
`split(".")` 会把令牌切成 5 段 ⇒ 登录回 200、之后每个请求 401。
"""
from __future__ import annotations

import importlib.util
import logging
import pathlib
import re
import time

from novelforge.core import activity_log, auth
from novelforge import server as server_mod

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# 1. WS 后端：声明 + 实际可用
# ---------------------------------------------------------------------------

def test_websocket_后端已声明且真的可用() -> None:
    """`/ws` 要有 WS 实现才不是死通道 —— 声明与安装两侧都要钉。

    ⚠️ 只钉 requirements 文本不够：镜像装错了照样没用；只钉 `find_spec` 也不够：
    依赖可能被某个传递依赖临时带进来，下次升级就没了。两侧同一条用例里一起断言。
    """
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert re.search(r"^websockets>=13", req, re.M), \
        "requirements.txt 必须显式声明 WS 后端（否则 uvicorn 对 /ws 握手回 404）"
    spec = importlib.util.find_spec("websockets") or importlib.util.find_spec("wsproto")
    assert spec is not None, "声明了 WS 后端但当前解释器里没有：uvicorn 的 /ws 会 404"


# ---------------------------------------------------------------------------
# 2. 令牌打码：两条 logger、两种参数形状
# ---------------------------------------------------------------------------

def test_ws_握手日志里的令牌被打码(caplog) -> None:
    """uvicorn 的 WS 握手日志：URL 在 **args[1]**，logger 是 `uvicorn.error`。"""
    tok = "tok-ws-290-should-not-appear"
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        logging.getLogger("uvicorn.error").info(
            '%s - "WebSocket %s" [accepted]', "127.0.0.1:57416", f"/ws?token={tok}")
    assert tok not in caplog.text, "WS 令牌明文进了 uvicorn.error 日志"
    assert "token=***" in caplog.text


def test_http_access_日志里的令牌仍被打码(caplog) -> None:
    """第 134 期的原判据不能回退：HTTP access 日志 URL 在 args[2]。"""
    tok = "tok-http-290-should-not-appear"
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:1", "GET", f"/api/books/x/asset?p=a.png&token={tok}", "1.1", 200)
    assert tok not in caplog.text
    assert "token=***" in caplog.text


def test_打码器挂在两条_uvicorn_logger_上() -> None:
    """挂错 logger 就等于没挂 —— 这是上一版只覆盖一半的根因。"""
    for name in ("uvicorn.access", "uvicorn.error"):
        filters = logging.getLogger(name).filters
        assert any(isinstance(f, server_mod._RedactMediaToken) for f in filters), \
            f"{name} 上没挂令牌打码器"


# ---------------------------------------------------------------------------
# 3. 未鉴权入口的输入上限 + 退避表上限
# ---------------------------------------------------------------------------

def test_登录超长账号被拒且不落持久结构(client) -> None:
    """超长账号名：400 直接挡掉，不进取避表、不写审计日志。"""
    giant = "u" * 200_000
    before = set(auth._fails)
    r = client.post("/api/auth/login", json={"user": giant, "pin": "x"})
    assert r.status_code == 400, r.text
    assert set(auth._fails) == before, "超长账号名进了退避表"
    assert not any(k.startswith("uuuu") for k in auth._fails)
    items = activity_log.recent(limit=200)
    assert not any(len(str(i.get("actor") or "")) > 1000 for i in items), \
        "超长账号名被持久写进了审计日志"


def test_改密码超长口令被拒(client, auth_headers) -> None:
    # conftest 的 TEST_PIN
    r = client.post("/api/auth/pin", headers=auth_headers,
                    json={"old_pin": "test1234", "new_pin": "x" * 600})
    assert r.status_code == 400, r.text


def test_退避表超过上限会收缩且保留在退避中的键(monkeypatch) -> None:
    """`auth._fails` 必须封顶；但**正在退避**的键不能被清（那等于开一个绕过窗口）。"""
    monkeypatch.setattr(auth, "_FAILS_MAX", 8)
    auth._fails.clear()
    try:
        for _ in range(auth._FAIL_FREE + 1):       # 第 6 次进入退避窗口
            auth._note_failure("admin|10.0.0.1")
        assert auth._fails["admin|10.0.0.1"][1] > time.time()

        for i in range(50):
            auth._note_failure(f"u{i}|10.0.0.9")

        assert len(auth._fails) <= 8, "退避表没有封顶"
        assert "admin|10.0.0.1" in auth._fails, "正在退避的键被清掉了"
    finally:
        auth._fails.clear()


# ---------------------------------------------------------------------------
# 4. 含点用户名：令牌必须能往返
# ---------------------------------------------------------------------------

def test_用户名含点时令牌可往返(monkeypatch) -> None:
    """`AUTH_USER=john.doe`：登录回 200，但旧 `split(".")` 让此后每个请求 401。"""
    monkeypatch.setattr(auth, "_cred_version", lambda user: "deadbeefcafe")
    tok = auth.issue_token("john.doe@example.com")
    assert auth.verify_token(tok) == "john.doe@example.com"
    # 签名被改一位必须失败（别把「能切」误当成「不校验」）
    bad = tok[:-1] + ("0" if tok[-1] != "0" else "1")
    assert auth.verify_token(bad) is None


def test_普通用户名令牌仍可往返(monkeypatch) -> None:
    """rsplit 不能把原有形状改坏。"""
    monkeypatch.setattr(auth, "_cred_version", lambda user: "deadbeefcafe")
    tok = auth.issue_token("admin")
    assert auth.verify_token(tok) == "admin"
