"""第 94 期 · 阶段 3：抓取加固 —— **响应体上限 / 全局并发 / 每源超时**（全程零网络）。

前两个是「源站不按常理出牌时别把容器拖垮」的护栏，第三个是「一个慢站别拖住整轮搜索」。
三条都由**实测过的现象**驱动过：坏源返回几百 MB 页面、20 个书源各开 8 并发、
规则里写歪的 `timeout` 被悄悄换成默认值（= 假配置）。

本文件钉住的东西：

* 超限是**边收边数、超限即断**（不是收完再看长度 —— 那时内存已经吃进去了）；
* 超限的响应**不重试**（重试只会把同样的几百 MB 再拉一遍）；
* 改走 `client.stream()` 之后 **Set-Cookie 照旧进 CookieJar**、
  `.text` 的编码判据与 `.content` 的字节**一字不差**（这是最容易悄悄改坏的地方）；
* 全局闸读的是 `config.network.max_concurrency`（**不另写一份默认值**）；
* 超时夹逼只有 `clamp_timeout` 一处，校验与执行问同一个它。
"""
import asyncio
import gzip

import httpx
import pytest

from novelforge import config
from novelforge.core import network
from novelforge.sources import manager, rules


# ---------------- 超时夹逼（唯一一处判据）----------------

@pytest.mark.parametrize("value, want", [
    (None, 30.0), ("", 30.0), ("abc", 30.0), (0, 30.0), (-5, 30.0),
    (1, 5.0),             # 太小 ⇒ 夹到下限（0.5 秒的「超时」等于随机失败）
    (9999, 120.0),        # 太大 ⇒ 夹到上限（一个源挂 3 小时会拖住整轮）
    (7, 7.0), (5, 5.0), (120, 120.0), ("45", 45.0),
])
def test_超时夹逼(value, want):
    assert network.clamp_timeout(value) == want


def test_夹逼是幂等的():
    """`manager._client` 会对已经夹过的值再夹一次 —— 必须还是同一个数。"""
    for v in (None, 1, 9999, 45):
        once = network.clamp_timeout(v)
        assert network.clamp_timeout(once) == once


# ---------------- 规则里的 timeout ----------------

def _rule(**extra) -> dict:
    r = {"name": "t", "domains": ["a.com"],
         "search": {"url": "https://a.com/s?q={title}", "mode": "css", "container": ".i",
                    "fields": {"url": "a::attr(href)"}},
         "book": {"mode": "single", "content": {"mode": "css", "container": "#c", "text": True}}}
    r.update(extra)
    return r


def test_规则里的timeout进到适配器():
    assert rules.make_rule_class(_rule()).timeout == 30.0
    assert rules.make_rule_class(_rule(timeout=7)).timeout == 7.0
    assert rules.make_rule_class(_rule(timeout=1)).timeout == 5.0
    assert rules.make_rule_class(_rule(timeout=9999)).timeout == 120.0
    # 实例与类**同一个数**（`RuleBasedSource.__init__` 与 `make_rule_class` 都用 clamp_timeout）
    assert rules.make_rule_class(_rule(timeout=7))().timeout == 7.0


@pytest.mark.parametrize("bad", ["abc", 0, -1, [], {}])
def test_校验拒绝写歪的timeout(bad):
    """写歪了会被夹逼悄悄换成默认值 —— 那正是假配置，导入时就要说清。"""
    errs = rules.validate_rule(_rule(timeout=bad))
    assert any("timeout" in e for e in errs), errs


def test_超范围的值不算错():
    """夹逼是**有意为之**（这一项是可选护栏）—— 越界不报错，只有类型/正负才报。"""
    assert not any("timeout" in e for e in rules.validate_rule(_rule(timeout=9999)))
    assert not any("timeout" in e for e in rules.validate_rule(_rule()))


def test_内置适配器的默认超时来自同一处常量():
    """`SourceAdapter.timeout` 不许另写一个字面量（改了常量就该跟着变）。"""
    from novelforge.sources.base import SourceAdapter
    assert SourceAdapter.timeout == network.TIMEOUT_DEFAULT


# ---------------- manager 建客户端时带上源的超时 ----------------

class _FakeSource:
    name = "假源"
    headers = {"X-A": "1"}
    timeout = 7.0


def test_manager按源建客户端带上超时():
    mgr = manager.DownloadManager({"network": {}, "download": {}})
    c = mgr._client(_FakeSource())
    assert c.client.timeout == httpx.Timeout(7.0)


# ---------------- 全局并发闸 ----------------

def _config_with(monkeypatch, **net):
    base = dict(config.DEFAULTS["network"])
    base.update(net)
    monkeypatch.setattr(config, "load_config", lambda: {"network": base})


@pytest.mark.parametrize("limit, want", [(1, 1), (4, 4)])
def test_全局闸按配置换挡(monkeypatch, limit, want):
    _config_with(monkeypatch, max_concurrency=limit)
    network._gate_cache.clear()
    gate = network.global_gate()
    assert isinstance(gate, type(asyncio.Semaphore()))
    assert gate._value == want


def test_0表示不限制(monkeypatch):
    _config_with(monkeypatch, max_concurrency=0)
    network._gate_cache.clear()
    assert isinstance(network.global_gate(), network._Unlimited)


def test_改了上限就换一个闸(monkeypatch):
    """按**值**缓存：设置页把上限从 1 改成 4，必须真的生效（不是继续用 1 的那把闸）。"""
    _config_with(monkeypatch, max_concurrency=1)
    network._gate_cache.clear()
    first = network.global_gate()
    _config_with(monkeypatch, max_concurrency=4)
    second = network.global_gate()
    assert first is not second and second._value == 4


def test_全局闸是模块级的_不是每个客户端一份(monkeypatch):
    _config_with(monkeypatch, max_concurrency=2)
    network._gate_cache.clear()
    assert network.global_gate() is network.global_gate()


# ---------------- 响应体上限（边收边数、超限即断）----------------

class _ChunkStream(httpx.AsyncByteStream):
    """按块吐字节并**记录吐了几块** —— 用来证明超限时真的提前收手。"""

    def __init__(self, chunks: list[bytes], log: list[int]):
        self._chunks = chunks
        self._log = log

    async def __aiter__(self):
        for c in self._chunks:
            self._log.append(len(c))
            yield c


def _capped_client(tmp_path, handler, cap: int, monkeypatch):
    _config_with(monkeypatch, max_response_bytes=cap)
    bc = network.BrowserClient("上限测试", cookie_dir=tmp_path, max_retries=3)
    old, bc.client = bc.client, httpx.AsyncClient(
        transport=httpx.MockTransport(handler), headers=bc.client.headers,
        cookies=bc.jar, follow_redirects=True, timeout=bc.client.timeout)
    return bc, old


def test_超限即断_不把整段拉进来(monkeypatch, tmp_path):
    log: list[int] = []
    seen = {"n": 0}

    def handler(req):
        seen["n"] += 1
        return httpx.Response(200, stream=_ChunkStream([b"x" * 100] * 10, log))

    bc, old = _capped_client(tmp_path, handler, 250, monkeypatch)

    async def go():
        try:
            with pytest.raises(network.ResponseTooLarge) as ei:
                await bc.get_text("https://a.com/big")
            return str(ei.value)
        finally:
            await bc.aclose()
            await old.aclose()

    msg = asyncio.run(go())
    assert log == [100, 100, 100], f"没有在第 3 块就收手：{log}"
    assert "max_response_bytes" in msg, "错误里要说清去哪儿调（否则用户只能猜）"
    assert seen["n"] == 1, "超限的响应不该重试（只会把同样的几百 MB 再拉一遍）"


def test_不超限时字节与文本一字不差(monkeypatch, tmp_path):
    body = "中文正文<br>第二段".encode("utf-8")

    def handler(req):
        return httpx.Response(200, content=body,
                              headers={"Content-Type": "text/html; charset=utf-8"})

    bc, old = _capped_client(tmp_path, handler, 4096, monkeypatch)

    async def go():
        try:
            return await bc.get_text("https://a.com/ok"), await bc.get_bytes("https://a.com/ok")
        finally:
            await bc.aclose()
            await old.aclose()

    text, raw = asyncio.run(go())
    assert text == "中文正文<br>第二段"
    assert raw == body, "get_bytes 拿到的必须是站上那一份字节（不能被文本编码解过一遍）"


def test_压缩响应不会被解两遍(monkeypatch, tmp_path):
    """**真网回归钉**（第 94 期实测踩到）：

    `_send_capped` 重建响应时若原样保留 `Content-Encoding`，httpx 会拿**已经解压**的字节
    再解一次 ⇒ gzip 数据当场抛
    `DecodingError: Error -3 while decompressing data: incorrect header check`。
    现象是「所有开了压缩的真实站点全抓不到」（单测里 mock 不压缩，只有真网暴露），
    所以这条用例用**真 gzip 字节 + `Content-Encoding: gzip`** 走一遍上限通道。
    """
    body = "中文正文<br>第二段".encode("utf-8")
    log: list[int] = []
    gz = gzip.compress(body)

    def handler(req):
        return httpx.Response(
            200, stream=_ChunkStream([gz], log),
            headers={"Content-Encoding": "gzip",
                     "Content-Type": "text/html; charset=utf-8"})

    bc, old = _capped_client(tmp_path, handler, 4096, monkeypatch)

    async def go():
        try:
            resp = await bc.get("https://a.com/gz")
            return resp, await bc.get_text("https://a.com/gz"), await bc.get_bytes(
                "https://a.com/gz")
        finally:
            await bc.aclose()
            await old.aclose()

    resp, text, raw = asyncio.run(go())
    assert raw == body, "压缩响应解出来的字节不对（多半是解了两遍）"
    assert text == "中文正文<br>第二段", "Content-Type 里的 charset 判据被弄丢了"
    assert "content-encoding" not in {k.lower() for k in resp.headers}, (
        "重建后的响应不该再自称有 Content-Encoding（字节已经是解压后的）")
    # Content-Length 由 httpx 按**解压后**的字节重算（不是原样抄过来的压缩后长度）
    assert resp.headers.get("content-length") == str(len(body)), (
        "Content-Length 应该是解压后的真实长度，而不是压缩时的那个数字")


def test_set_cookie在流式请求后仍然生效(monkeypatch, tmp_path):
    """改走 `client.stream()` 最容易悄悄弄坏的就是这一条：登录态不再保留。"""

    def handler(req):
        return httpx.Response(200, text="ok",
                              headers={"Set-Cookie": "sid=abc123; Path=/",
                                       "Content-Type": "text/html; charset=utf-8"})

    bc, old = _capped_client(tmp_path, handler, 4096, monkeypatch)

    async def go():
        try:
            await bc.get_text("https://a.com/login")
            names = {c.name: c.value for c in bc.jar}
            return names, bc.cookie_path.exists()
        finally:
            await bc.aclose()
            await old.aclose()

    names, _ = asyncio.run(go())
    assert names.get("sid") == "abc123", f"Set-Cookie 没进 CookieJar：{names}"


def test_0表示不限响应体(monkeypatch, tmp_path):
    big = b"y" * (200 * 1024)

    def handler(req):
        return httpx.Response(200, content=big)

    bc, old = _capped_client(tmp_path, handler, 0, monkeypatch)

    async def go():
        try:
            return await bc.get_bytes("https://a.com/huge")
        finally:
            await bc.aclose()
            await old.aclose()

    assert asyncio.run(go()) == big


def test_429仍然退避重试(monkeypatch, tmp_path):
    """改发送路径不许把既有的 429 退避弄丢（它就在同一条 `_request` 里）。"""
    seq = {"n": 0}

    def handler(req):
        seq["n"] += 1
        if seq["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, text="ok",
                              headers={"Content-Type": "text/html; charset=utf-8"})

    bc, old = _capped_client(tmp_path, handler, 4096, monkeypatch)

    async def go():
        try:
            return await bc.get_text("https://a.com/s")
        finally:
            await bc.aclose()
            await old.aclose()

    assert asyncio.run(go()) == "ok" and seq["n"] == 2


# ---------------- 配置三处同步 ----------------

def test_默认值里有这两个护栏():
    net = config.DEFAULTS["network"]
    assert net["max_response_bytes"] == 16 * 1024 * 1024
    assert net["max_concurrency"] == 16


def test_可写白名单与默认值同步():
    """`EDITABLE` 漏了子键 ⇒ 能写进 settings.json 但保存后被丢掉（假配置）。"""
    from novelforge import server

    assert {"max_response_bytes", "max_concurrency"} <= server.EDITABLE["network"]


def test_设置页有对应控件():
    """第 3 个同步点：白名单有了、界面没控件 ⇒ 用户改不到（与「假配置」是同一种病）。

    照 `tests/test_update_config_contract.py` 的做法直接读前端注册表 —— 靠人眼比对
    这两处，历史上漏过不止一次。
    """
    import pathlib
    import re

    ts = (pathlib.Path(__file__).resolve().parents[1]
          / "frontend" / "src" / "data" / "settingsFields.ts").read_text(encoding="utf-8")
    for key in ("max_response_bytes", "max_concurrency"):
        assert re.search(rf"path:\s*'network\.{key}'", ts), f"设置页缺 network.{key} 控件"


def test_每个键都有真实读点():
    """**假配置的直接判据**：在 `core/network.py` 里找不到 `.get("<键>")` 就等于改完没生效。"""
    import pathlib

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "novelforge" / "core" / "network.py").read_text(encoding="utf-8")
    for key in ("max_response_bytes", "max_concurrency"):
        assert f'.get("{key}")' in src, f"network.{key} 没有任何读点 —— 这是假配置"


def test_接口拒绝负数但放行0(client, auth_headers, monkeypatch, tmp_path):
    """0 在这里是**有意义**的取值（= 不限制），不能照抄上传上限那条「必须大于 0」。"""
    # 覆盖层写到本用例专属文件：不然这条用例会把 `max_concurrency` 留在会话级
    # settings.json 里，后面的用例读到的是它（污染别的用例最难查）。
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")

    bad = client.put("/api/config", json={"network": {"max_concurrency": -1}},
                     headers=auth_headers)
    assert bad.status_code == 400

    ok = client.put("/api/config", json={"network": {"max_concurrency": 0}}, headers=auth_headers)
    assert ok.status_code == 200
    assert config.load_config()["network"]["max_concurrency"] == 0

    broken = client.put("/api/config", json={"network": {"max_response_bytes": "很大"}},
                        headers=auth_headers)
    assert broken.status_code == 400
