"""TTS（自托管 / 局域网的 OpenAI-compatible 引擎，第 235 期）。

## 三条纪律（各有用例）

1. **默认关**：没打开就**不请求**、如实说「未启用」（不做「点了没反应」的假开关）。
2. **失败即失败**：合成不通 / 响应里没音频 ⇒ `ok=False` + 中文原因 ——
   **不返回空音频假装成功**（前端会拿它去播，播不出来时用户不知道是失败还是没声音）。
3. **不落书文件**：音频只进 `CACHE_DIR`。

另外钉住**分块**：长文本要切开合成（一次合成整章会超时），切在句末 ⇒
合成出来的音频不会在句中截断。
"""
from __future__ import annotations

import json

import pytest

from novelforge.core import tts


class _Resp:
    def __init__(self, status_code=200, content=b"", payload=None, ctype="audio/mpeg"):
        self.status_code = status_code
        self.content = content
        self._payload = payload
        # `httpx.Response.headers` 是 Headers 对象；这里给 dict（替身允许简化）
        self.headers = {"content-type": ctype}

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


def _enable(monkeypatch, **over):
    base = {
        "enabled": True,
        "base_url": "http://127.0.0.1:9",
        "api_key": "",
        "model": "tts-1",
        "voice": "alloy",
        "speed": 1.0,
        "timeout": 5.0,
    }
    base.update(over)
    monkeypatch.setattr(tts, "cfg", lambda: dict(base))
    return base


# ---------------------------------------------------------------------------
# 配置与状态
# ---------------------------------------------------------------------------

def test_默认关闭(monkeypatch):
    """默认**关** —— 不打开就不请求。"""
    monkeypatch.setattr(tts, "cfg", lambda: {
        "enabled": False, "base_url": "http://127.0.0.1:8000", "api_key": "",
        "model": "tts-1", "voice": "alloy", "speed": 1.0, "timeout": 60.0})
    res = tts.synthesize("你好")
    assert res["ok"] is False
    assert "未启用" in res["message"]


def test_状态不含_api_key(monkeypatch):
    """状态里**没有** api_key（那是凭据，不能进界面）。"""
    _enable(monkeypatch, api_key="secret-token")
    st = tts.status()
    assert "api_key" not in st
    assert st["has_key"] is True


# ---------------------------------------------------------------------------
# 分块
# ---------------------------------------------------------------------------

def test_长文本按句末切块():
    text = "第一句话。第二句话。第三句话。"
    blocks = tts._chunks(text, limit=10)
    assert len(blocks) > 1
    # 切在句末 ⇒ 每块都以句号结尾（不切在句中）
    for b in blocks:
        assert b.endswith("。")


def test_单句超限会硬切():
    """单句超限 ⇒ 硬切，且**每块都不超过上限**。

    ⚠️ 这一档**必须真的触发** —— 零宽断言用 `|` 连起来在 Python 的 `re` 里
    **不会切**，那样整块长句会被一次送出去（自托管引擎必超时）。
    """
    text = "啊" * 300
    blocks = tts._chunks(text, limit=50)
    assert len(blocks) >= 6
    assert all(len(b) <= 50 for b in blocks)


def test_空文本没有块():
    assert tts._chunks("") == []
    assert tts._chunks("   \n ") == []


# ---------------------------------------------------------------------------
# 合成
# ---------------------------------------------------------------------------

def test_合成成功_返回缓存路径与字节数(monkeypatch, tmp_path):
    _enable(monkeypatch)
    monkeypatch.setattr(tts, "_cache_path", lambda blob: tmp_path / "a.mp3")
    calls = []

    def _post(url, json=None, headers=None, timeout=None):
        calls.append((url, json))
        return _Resp(content=b"MP3DATA")

    monkeypatch.setattr(tts.httpx, "post", _post)
    res = tts.synthesize("你好")
    assert res["ok"] is True, res
    assert res["bytes"] == len(b"MP3DATA")
    assert (tmp_path / "a.mp3").read_bytes() == b"MP3DATA"
    # 请求打到了 OpenAI-compatible 的语音端点
    assert calls[0][0].endswith("/v1/audio/speech")


def test_合成失败_HTTP_错误如实说(monkeypatch, tmp_path):
    _enable(monkeypatch)
    monkeypatch.setattr(tts, "_cache_path", lambda blob: tmp_path / "a.mp3")
    monkeypatch.setattr(tts.httpx, "post",
                        lambda *a, **k: _Resp(status_code=500, content=b"boom"))
    res = tts.synthesize("你好")
    assert res["ok"] is False
    assert "500" in res["message"]
    assert res["path"] == ""


def test_合成失败_响应里没有音频(monkeypatch, tmp_path):
    """⚠️ **不返回空音频假装成功** —— 前端会拿它去播。"""
    _enable(monkeypatch)
    monkeypatch.setattr(tts, "_cache_path", lambda blob: tmp_path / "a.mp3")
    monkeypatch.setattr(tts.httpx, "post",
                        lambda *a, **k: _Resp(content=b"", payload={"nothing": 1},
                                             ctype="application/json"))
    res = tts.synthesize("你好")
    assert res["ok"] is False
    assert "没有音频" in res["message"]


def test_兼容实现回_base64_json(monkeypatch, tmp_path):
    """不少自托管实现回 ``{"audio": "<base64>"}`` 而不是二进制 —— 两种都认。"""
    import base64
    _enable(monkeypatch)
    monkeypatch.setattr(tts, "_cache_path", lambda blob: tmp_path / "a.mp3")
    payload = {"audio": base64.b64encode(b"MP3").decode()}
    _json_resp = _Resp(content=json.dumps(payload).encode(), ctype="application/json")
    _json_resp._payload = payload
    monkeypatch.setattr(tts.httpx, "post", lambda *a, **k: _json_resp)
    res = tts.synthesize("你好")
    assert res["ok"] is True, res
    assert res["bytes"] == len(b"MP3")


def test_探针_不通如实说(monkeypatch):
    _enable(monkeypatch)

    def _boom(*a, **k):
        raise tts.httpx.HTTPError("连不上")
    monkeypatch.setattr(tts.httpx, "post", _boom)
    res = tts.probe()
    assert res["ok"] is False
    assert "连不上" in res["message"]


# ---------------------------------------------------------------------------
# 音频出口
# ---------------------------------------------------------------------------

def test_音频出口不许穿越到缓存目录之外(tmp_path, monkeypatch):
    """⚠️ 只服务**缓存目录里**的文件。"""
    import novelforge.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "CACHE_DIR", tmp_path)
    assert tts.speak_url(str(tmp_path / "x.mp3")).endswith("/api/tts/audio/x.mp3")
    assert tts.speak_url(str(tmp_path.parent / "outside.mp3")) == ""
    assert tts.speak_url("") == ""
