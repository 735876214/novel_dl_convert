"""第 94 期 · 阶段 4a：URL 订阅导入 + SSRF 闸。

**要钉住的病**：URL 导入是本站**唯一**由用户指定 URL 的出网点（其余出网目标都由书源规则里的
`domains` 决定，客户端从不传地址）。单用户 NAS 上，这条路上不加闸就等于把「读取内网」的能力
开给任何能打到这个端口的人 —— `http://127.0.0.1:8080/admin`、`http://169.254.169.254/…`
返回的内容会进入导出 / 诊断 / 报错里。

本文件分四截：

① **判据**（`urlguard.ip_scope` / `assert_public_url`）—— 与 `server._is_local_request`
   共用同一个「非全球可路由」集合，所以两边一起钉；
② **逐跳** —— 「公网地址 302 到内网」必须在**第二跳**被挡下。这条依赖 httpx 的
   request 事件钩子在重定向循环里逐跳调用（写死成用例，httpx 改了行为这里就红）；
③ **接口**（`POST /api/sources/import-url`）—— 开关关着不出网、地址被拒不出网、
   取回来的内容走 `intake` 的同一条解析路；
④ **配置契约** —— `source_import` 的四个键与 `network.verify_tls` 在三处同步点一致，
   且**每个键都有真实读点**（假配置是本期点名要防的形态）。
"""
from __future__ import annotations

import asyncio
import inspect
import json
import pathlib
import re

import httpx
import pytest
from fastapi import HTTPException

from novelforge import config, server
from novelforge.core import network, urlguard
from novelforge.server import app  # noqa: F401  —— client fixture 依赖的 app

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------- ① 判据：与入站那份共用同一个集合 ----------------

@pytest.mark.parametrize("host, expected", [
    # 内网 / 本机 / 保留段 —— 一律不许出站去取
    ("127.0.0.1", "local"),
    ("::1", "local"),
    ("10.1.2.3", "local"),
    ("172.20.0.4", "local"),
    ("192.168.0.9", "local"),
    ("169.254.169.254", "local"),          # 云元数据端点，SSRF 的经典目标
    ("0.0.0.0", "local"),
    ("192.0.2.1", "local"),                # 文档段：看着像公网，实际非全球可路由
    # IPv4-mapped IPv6 的还原在**这一处**（不还原会被当成公网放过）
    ("::ffff:127.0.0.1", "local"),
    ("::ffff:8.8.8.8", "public"),
    # 真的全球可路由的地址
    ("8.8.8.8", "public"),
    ("1.1.1.1", "public"),
    ("2001:4860:4860::8888", "public"),
    # 不是 IP 字面量
    ("example.com", None),
    ("", None),
    ("127.0.0.1:8080", None),
])
def test_ip_判据(host, expected):
    assert urlguard.ip_scope(host) == expected


def test_入站判据与出站判据是同一份():
    """`server._is_local_request` 不许自己再写一遍 IP 判断（写两遍必然漂）。"""
    src = (ROOT / "novelforge" / "server.py").read_text(encoding="utf-8")
    assert "urlguard.ip_scope(host)" in src, "入站判据必须调 urlguard（唯一实现）"
    assert "ipaddress" not in src, "server.py 里不该再直接 import ipaddress"


@pytest.mark.parametrize("url, why", [
    ("file:///etc/passwd", "协议"),
    ("ftp://example.com/x.json", "协议"),
    ("gopher://127.0.0.1:6379/_INFO", "协议"),
    ("data:application/json,[]", "协议"),
    ("https://", "主机名"),
    ("http://127.0.0.1:8080/admin", "内网"),
    ("http://169.254.169.254/latest/meta-data/", "内网"),
    ("http://[::1]/", "内网"),
])
def test_直接拒掉的地址(url, why):
    with pytest.raises(urlguard.UrlBlocked) as e:
        urlguard.assert_public_url(url)
    assert why in str(e.value), str(e.value)


def test_公网地址直接放行(monkeypatch):
    monkeypatch.setattr(urlguard, "resolve", lambda host: ["93.184.216.34"])
    assert urlguard.assert_public_url("https://example.com/shuyuan.json")


def test_域名解析到内网要拒(monkeypatch):
    """DNS 指向内网（`evil.example.com → 127.0.0.1`）是同一族的手法。"""
    monkeypatch.setattr(urlguard, "resolve", lambda host: ["127.0.0.1"])
    with pytest.raises(urlguard.UrlBlocked) as e:
        urlguard.assert_public_url("http://evil.example.com/a.json")
    assert "解析到内网" in str(e.value)


def test_多地址里混一个内网也拒(monkeypatch):
    """只校验首个解析结果是最常见的绕过手法。"""
    monkeypatch.setattr(urlguard, "resolve", lambda host: ["93.184.216.34", "10.0.0.5"])
    with pytest.raises(urlguard.UrlBlocked) as e:
        urlguard.assert_public_url("http://mixed.example.com/a.json")
    assert "10.0.0.5" in str(e.value)


def test_解析不出就拒(monkeypatch):
    monkeypatch.setattr(urlguard, "resolve", lambda host: [])
    with pytest.raises(urlguard.UrlBlocked) as e:
        urlguard.assert_public_url("http://nx.example.com/a.json")
    assert "解析不出" in str(e.value)


# ---------------- ② 逐跳复查（含重定向）----------------

def _hop_transport(*, from_url: str, to_url: str):
    """第一跳 302 到 `to_url`，第二跳返回内容 —— 用来验「第二跳也过闸」。"""
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(from_url):
            return httpx.Response(302, headers={"location": to_url})
        return httpx.Response(200, content=b'{"ok": 1}')
    return httpx.MockTransport(handler)


def test_重定向到内网在第二跳被挡下(monkeypatch):
    """**最关键的一条**：`follow_redirects=True` 时，redirect 的每一跳都要过闸。

    这个判据完全依赖 httpx 的 request 事件钩子在 `_send_handling_redirects` 的循环里
    逐跳调用（0.28 实测如此）。哪天 httpx 改成只调一次，这条会红 —— 那时必须换实现，
    而不是让「公网地址 302 到内网」悄悄通过。
    """
    public = "http://public.example.com/list.json"
    monkeypatch.setattr(urlguard, "resolve", lambda host: ["93.184.216.34"])

    async def go():
        async with httpx.AsyncClient(
            follow_redirects=True,
            transport=_hop_transport(from_url=public, to_url="http://127.0.0.1/secret"),
            event_hooks={"request": [urlguard.guard_request]},
        ) as c:
            return await c.get(public)

    with pytest.raises(urlguard.UrlBlocked) as e:
        asyncio.run(go())
    assert "内网" in str(e.value)


def test_钩子必须是_async函数():
    """同步钩子会被 `await None` 打成 `TypeError`，而不是给出一句人话 —— 实测踩过。"""
    assert inspect.iscoroutinefunction(urlguard.guard_request)


def test_浏览器客户端默认不挂任何钩子():
    """⚠️ 不改变既有抓取行为：只有 URL 导入那条路才逐跳复查。"""
    c = network.BrowserClient("钩子测试", cookie_dir=".", max_retries=1)
    try:
        assert c.client.event_hooks["request"] == []
    finally:
        asyncio.run(c.aclose())


def test_浏览器客户端能挂上钩子与证书开关(monkeypatch):
    c = network.BrowserClient("钩子测试", cookie_dir=".", max_retries=1,
                              verify_tls=True, request_guard=urlguard.guard_request,
                              max_bytes=1234)
    try:
        assert c.client.event_hooks["request"] == [urlguard.guard_request]
        assert c.max_bytes == 1234
    finally:
        asyncio.run(c.aclose())


def test_证书校验默认关着不改既有行为():
    """`network.verify_tls` 默认 False —— 改默认值会静默让一批证书不规范的源失效。"""
    assert network.verify_tls_enabled({}) is False
    assert network.verify_tls_enabled({"network": {"verify_tls": True}}) is True
    assert config.DEFAULTS["network"]["verify_tls"] is False


def test_上限默认仍走_network_max_response_bytes(monkeypatch):
    """给了 `max_bytes` 才覆盖；没给就还是那个唯一读点（不新造第二份默认值）。"""
    c = network.BrowserClient("上限测试", cookie_dir=".", max_retries=1)
    try:
        assert c.max_bytes is None
    finally:
        asyncio.run(c.aclose())


# ---------------- ③ 接口层 ----------------

_LEGADO_ONE = json.dumps([{
    "bookSourceName": "订阅来的源", "bookSourceUrl": "https://sub.example.com",
    "bookSourceGroup": "订阅", "bookSourceType": 0,
    "searchUrl": "https://sub.example.com/search?key={{key}}",
    "ruleSearch": {"bookList": ".list li", "name": ".name@text",
                   "bookUrl": "a@href", "author": ".author@text"},
    "ruleToc": {"chapterList": "#toc a", "chapterName": "text", "chapterUrl": "href"},
    "ruleContent": {"content": "#content@html"},
}], ensure_ascii=False)


@pytest.fixture()
def url_import_on(monkeypatch):
    """打开 URL 导入开关：只在读取到的配置上翻这一个开关，别的一律照真实默认值。"""
    cfg = config.load_config()
    cfg.setdefault("source_import", {})["url_enabled"] = True
    monkeypatch.setattr(config, "load_config", lambda: cfg)
    return cfg


def test_开关关着时拒绝且不出网(client, auth_headers, monkeypatch):
    """**不出网**是这一条的重点：不能先访问再去判断能不能访问。"""
    monkeypatch.setattr(config, "load_config",
                        lambda: {"source_import": {"url_enabled": False}})
    called: list = []

    async def boom(url, cfg):                                    # noqa: ARG001
        called.append(url)
        return b""

    monkeypatch.setattr(server, "_fetch_source_url", boom)
    r = client.post("/api/sources/import-url", headers=auth_headers,
                    json={"url": "https://sub.example.com/shuyuan.json"})
    assert r.status_code == 400, r.text
    # 提示里给的是**设置页上的中文标签**，不是键名 —— 这话是给用户看的（toast 渲染纯文本，
    # 写 `url_enabled` 只会让他去搜一个界面上根本不存在的字符串）。
    assert "未启用" in r.json()["detail"]
    assert "允许从 URL 订阅导入书源" in r.json()["detail"]
    assert "`" not in r.json()["detail"], "toast 是纯文本，反引号会原样露出来"
    assert called == [], "开关关着时不许有任何出网动作"


def test_缺_url_报人话(client, auth_headers, url_import_on):
    r = client.post("/api/sources/import-url", headers=auth_headers, json={})
    assert r.status_code == 400
    assert "缺少 url" in r.json()["detail"]


def test_内网地址被拒且不出网(client, auth_headers, url_import_on, monkeypatch):
    """**走真的是取回函数**（不打桩）—— 打桩就把「先校验再连接」这个顺序也一起打掉了。

    「不出网」的判据是**连 HTTP 客户端都没建**：`_fetch_source_url` 里首跳校验在
    `BrowserClient(...)` 之前。
    """
    built: list = []

    def spy(*a, **kw):
        built.append(a)
        raise AssertionError("内网地址不该走到建客户端这一步")

    monkeypatch.setattr(network, "BrowserClient", spy)
    r = client.post("/api/sources/import-url", headers=auth_headers,
                    json={"url": "http://169.254.169.254/latest/meta-data/"})
    assert r.status_code == 400, r.text
    assert "不允许访问" in r.json()["detail"] and "内网" in r.json()["detail"]
    assert built == []


def test_取回的书源走同一条解析路并默认_dry_run(client, auth_headers, url_import_on,
                                                monkeypatch):
    async def fake(url, cfg):                                    # noqa: ARG001
        return _LEGADO_ONE.encode("utf-8")

    monkeypatch.setattr(server, "_fetch_source_url", fake)
    r = client.post("/api/sources/import-url", headers=auth_headers,
                    json={"url": "https://sub.example.com/shuyuan.json"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["dry_run"] is True, "默认必须 dry-run：一个字节都不写"
    assert [row["display_name"] for row in body["rows"]] == ["订阅来的源"]
    assert [row["supported"] for row in body["rows"]] == ["yes"]
    assert body["origin"] == "https://sub.example.com/shuyuan.json"
    # 解析结论与 `/import` 完全相同（同一条 `intake` 路 —— 不是第二套实现）
    same = client.post("/api/sources/import", headers=auth_headers,
                       json={"payload": _LEGADO_ONE})
    assert [row["supported"] for row in same.json()["rows"]] == \
           [row["supported"] for row in body["rows"]]


def test_取回的不是书源文件时回_400(client, auth_headers, url_import_on, monkeypatch):
    async def fake(url, cfg):                                    # noqa: ARG001
        return b"<html>404 not found</html>"

    monkeypatch.setattr(server, "_fetch_source_url", fake)
    r = client.post("/api/sources/import-url", headers=auth_headers,
                    json={"url": "https://sub.example.com/nope.html"})
    assert r.status_code == 400 and "无法识别格式" in r.json()["detail"]


def test_目标站报错时原文回给用户(client, auth_headers, url_import_on, monkeypatch):
    async def fake(url, cfg):                                    # noqa: ARG001
        raise HTTPException(400, "目标站返回 403（不是书源文件？）")

    monkeypatch.setattr(server, "_fetch_source_url", fake)
    r = client.post("/api/sources/import-url", headers=auth_headers,
                    json={"url": "https://sub.example.com/shuyuan.json"})
    assert r.status_code == 400 and "403" in r.json()["detail"]


def test_网络层异常也给原文(client, auth_headers, url_import_on, monkeypatch):
    async def fake(url, cfg):                                    # noqa: ARG001
        raise RuntimeError("连接被重置")

    monkeypatch.setattr(server, "_fetch_source_url", fake)
    r = client.post("/api/sources/import-url", headers=auth_headers,
                    json={"url": "https://sub.example.com/shuyuan.json"})
    assert r.status_code == 400
    assert "取回失败" in r.json()["detail"] and "连接被重置" in r.json()["detail"]


def test_真取回走_uruguard_与上限(monkeypatch):
    """`_fetch_source_url` 自己：先验首跳、给钩子、带上限与证书开关。"""
    seen: dict = {}

    async def fake_get(self, url, **kw):                          # noqa: ARG001
        seen["guard"] = bool(self.client.event_hooks["request"])
        seen["max_bytes"] = self.max_bytes
        return httpx.Response(200, content=b"[]", request=httpx.Request("GET", url))

    monkeypatch.setattr(network.BrowserClient, "get", fake_get)
    monkeypatch.setattr(urlguard, "assert_public_url", lambda u: u)
    raw = asyncio.run(server._fetch_source_url(
        "https://sub.example.com/x.json",
        {"max_bytes": 4096, "timeout": 5, "verify_tls": True}))
    assert raw == b"[]"
    assert seen == {"guard": True, "max_bytes": 4096}


def test_真取回时内网地址连客户端都不建(monkeypatch):
    built: list = []
    monkeypatch.setattr(network, "BrowserClient",
                        lambda *a, **kw: built.append(a) or pytest.fail("不该建客户端"))
    with pytest.raises(urlguard.UrlBlocked):
        asyncio.run(server._fetch_source_url("http://127.0.0.1/x.json",
                                             {"max_bytes": 4096, "timeout": 5}))
    assert built == []


# ---------------- ④ 配置契约（三处同步点 + 真实读点）----------------

TS = ROOT / "frontend" / "src" / "data" / "settingsFields.ts"

#: 键 → 必须存在的读点（文件, 源码片段）。没有读点的键 = 假配置（本仓点名的红线）。
READ_POINTS: dict[str, list[tuple[str, str]]] = {
    "url_enabled": [("novelforge/server.py", 'cfg.get("url_enabled"')],
    "max_bytes": [("novelforge/server.py", 'cfg.get("max_bytes")')],
    "timeout": [("novelforge/server.py", 'cfg.get("timeout")')],
    "verify_tls": [("novelforge/server.py", 'cfg.get("verify_tls"')],
}


def _ts() -> str:
    return TS.read_text(encoding="utf-8")


def _frontend_keys(prefix: str) -> set:
    text = _ts()
    return set(re.findall(rf"path:\s*'({prefix}\.[A-Za-z_][A-Za-z0-9_]*)'", text))


def test_白名单_回显_设置页三处一致():
    keys = set(server.EDITABLE["source_import"])
    assert keys == set(config.DEFAULTS["source_import"]), \
        "白名单与默认值必须同名同集合（缺默认值 ⇒ 恢复默认后控件消失）"
    assert keys == {k.split(".", 1)[1] for k in _frontend_keys("source_import")}, \
        "`server.EDITABLE['source_import']` 与设置页控件不一致"
    body = server.api_get_config()["config"]
    assert keys <= set(body["source_import"]), "GET /api/config 少回显了键"


def test_network_verify_tls_三处一致():
    assert "verify_tls" in server.EDITABLE["network"]
    assert "verify_tls" in config.DEFAULTS["network"]
    assert "network.verify_tls" in _frontend_keys("network")
    assert "verify_tls" in server.api_get_config()["config"]["network"]


def test_分区键指向这两段():
    """`SECTION_KEYS.network` 漏了 `source_import` ⇒ 界面上改了存不进去（隐蔽的假开关）。"""
    m = re.search(r"network:\s*\[([^\]]*)\]", _ts())
    assert m, "settingsFields.ts 里找不到 SECTION_KEYS 的 network 条目"
    keys = re.findall(r"'([A-Za-z_]+)'", m.group(1))
    assert keys == ["network", "download", "logging", "auto_update", "source_import"]


def test_每个键都有真实读点():
    for key, points in READ_POINTS.items():
        assert key in server.EDITABLE["source_import"], f"{key} 已不在白名单里，契约表要同步"
        for rel, needle in points:
            src = (ROOT / rel).read_text(encoding="utf-8")
            assert needle in src, f"`{key}` 在 {rel} 里找不到读法 `{needle}` —— 假配置"


def test_读点契约表覆盖白名单():
    assert set(READ_POINTS) == set(server.EDITABLE["source_import"])


def test_写入口值域校验(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    bad = [
        ({"source_import": {"max_bytes": 0}}, "大于 0"),
        ({"source_import": {"max_bytes": -1}}, "大于 0"),
        ({"source_import": {"max_bytes": "abc"}}, "必须是整数"),
        ({"source_import": {"timeout": 0}}, "0–300"),
        ({"source_import": {"timeout": 999}}, "0–300"),
    ]
    for patch, why in bad:
        r = client.put("/api/config", headers=auth_headers, json=patch)
        assert r.status_code == 400, (patch, r.text)
        assert why in r.json()["detail"], (patch, r.json()["detail"])
    ok = client.put("/api/config", headers=auth_headers,
                    json={"source_import": {"url_enabled": True, "max_bytes": 4096,
                                            "timeout": 12.5, "verify_tls": False}})
    assert ok.status_code == 200, ok.text
    got = client.get("/api/config", headers=auth_headers).json()["config"]["source_import"]
    assert got["max_bytes"] == 4096 and got["timeout"] == 12.5
    assert got["url_enabled"] is True and got["verify_tls"] is False
