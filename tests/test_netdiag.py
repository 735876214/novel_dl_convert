"""第 104 期：出网失败**归因**（`novelforge/core/netdiag.py`）的契约。

要钉住的两件事：

1. **分类不能靠猜**：`socket.gaierror`（解析不出来）、`ssl.SSLError`（握手）、
   `httpx.ProxyError`、`ConnectTimeout`（TCP 没建起来）与 `ReadTimeout`（连上了没回完）
   在用户那里是**五件不同的事**，混成「连接失败」就只能瞎猜；而且真正有用的类型常在内层
   （httpx 会包一层），必须沿异常链找。
2. **未知不等于污染**：查了公共解析器、两边不一致才叫「被污染」；公共解析器答不上来
   一律如实说「无法交叉核对」—— 宁可说不出结论，也不能乱指一个方向（本仓口径：
   误报比不测更糟，用户会去修一个根本没坏的东西）。

⚠️ 本文件的**所有**用例都不出网：`tests/conftest.py` 的 `_no_live_dns_in_tests` 已把两个
I/O 缝换成「问不到」，要模拟解析结果就自己再 monkeypatch 那两个缝（后打的补丁生效）。
"""
import socket
import ssl
import struct

import httpx
import pytest

from novelforge.core import netdiag as nd


def _req(url: str = "https://openlibrary.org/search.json") -> httpx.Request:
    return httpx.Request("GET", url)


def _resp(ips, qid: int, name: str = "openlibrary.org", rcode: int = 0,
          truncate: int = 0) -> bytes:
    """合成一个 A 记录的 DNS 响应（用来钉编解码，不出网）。"""
    head = struct.pack(">HHHHHH", qid & 0xFFFF, 0x8180 | rcode, 1, len(ips), 0, 0)
    q = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    q += struct.pack(">HH", 1, 1)
    body = b""
    for ip in ips:
        body += b"\xc0\x0c" + struct.pack(">HHIH", 1, 1, 60, 4)
        body += bytes(int(x) for x in ip.split("."))
    data = head + q + body
    return data[:truncate] if truncate else data


# ---------------------------------------------------------------- 异常链分类

@pytest.mark.parametrize("exc,kind", [
    (socket.gaierror(-2, "Name or service not known"), "dns"),
    (ssl.SSLError("UNEXPECTED_EOF_WHILE_READING"), "tls"),
    (ssl.SSLCertVerificationError("certificate verify failed"), "tls"),
    (httpx.ProxyError("proxy connect failed"), "proxy"),
    (httpx.ConnectTimeout("timed out"), "connect_timeout"),
    (httpx.ReadTimeout("timed out"), "timeout"),
    (httpx.ConnectError("boom"), "network"),
    (ConnectionResetError("reset"), "network"),
    (ValueError("不是网络问题"), ""),
])
def test_异常分类分得开(exc, kind):
    assert nd.classify_exc(exc) == kind


def test_异常链要看内层():
    """httpx 会把底层错误包一层：`[SSL: UNEXPECTED_EOF…]` 本体是 `ssl.SSLError`。"""
    inner = socket.gaierror(-2, "Name or service not known")
    outer = httpx.ConnectError("getaddrinfo failed")
    outer.__cause__ = inner

    assert nd.classify_exc(outer) == "dns", "外层是 ConnectError，但根因是解析失败"


def test_取主机名用于交叉核对():
    assert nd.host_of(httpx.ConnectError("x", request=_req())) == "openlibrary.org"
    # IP 字面量没有「解析结果」可比对 ⇒ 回空串（免得拿 IP 去问 DNS）
    assert nd.host_of(httpx.ConnectError("x", request=_req("https://31.13.112.4/a"))) == ""
    # 裸异常（无 request）也不能抛
    assert nd.host_of(httpx.ConnectError("x")) == ""
    assert nd.host_of(RuntimeError("随便什么"), "https://OpenLibrary.org.") == "openlibrary.org"


def test_描述失败是纯函数():
    """`describe_exc` 会被数据路径（`search`）调用 ⇒ **不能有任何 I/O**。

    这里连 conftest 的两个缝都换成「一调就炸」，它照样要能返回。
    """
    def _boom(*a, **k):
        raise AssertionError("describe_exc 不该发起任何查询")

    orig_dns, orig_local = nd._dns_exchange, nd._local_ips
    nd._dns_exchange, nd._local_ips = _boom, _boom
    try:
        got = nd.describe_exc(httpx.ConnectError("x", request=_req()))
    finally:
        nd._dns_exchange, nd._local_ips = orig_dns, orig_local

    assert got == {"kind": "network", "host": "openlibrary.org"}


# ---------------------------------------------------------------- DNS 包编解码

def test_查询包编码():
    pkt = nd._build_query("openlibrary.org", 0x1234)

    assert pkt[:2] == b"\x12\x34", "事务 id 要在头部"
    assert pkt[2:4] == b"\x01\x00", "标准查询 + 递归请求"
    assert pkt[4:6] == b"\x00\x01", "一个问题"
    assert len("openlibrary") == pkt[12], "第一个标签是长度 + 字节"
    assert pkt[12 + 1:12 + 12] == b"openlibrary"
    assert pkt[-5:] == b"\x00\x00\x01\x00\x01", "QNAME 结束符 + QTYPE=A + QCLASS=IN"


def test_解析响应取A记录():
    qid = 0x4321
    data = _resp(["199.59.149.201", "199.59.148.6"], qid)

    assert nd._parse_a_records(data, qid) == ["199.59.149.201", "199.59.148.6"]


def test_解析响应认得出答非所问():
    data = _resp(["1.2.3.4"], 0x1111)

    assert nd._parse_a_records(data, 0x2222) == [], "id 不匹配必须丢"
    assert nd._parse_a_records(_resp(["1.2.3.4"], 0x1111, rcode=3), 0x1111) == [], "rcode≠0 是失败"
    assert nd._parse_a_records(b"", 0x1111) == []
    assert nd._parse_a_records(_resp(["1.2.3.4"], 0x1111, truncate=20), 0x1111) == [], \
        "截断的包只能回空，不能抛"


# ---------------------------------------------------------------- 交叉核对

@pytest.fixture
def seams(monkeypatch):
    """把两个 I/O 缝换成可编程的假实现。"""
    state = {"local": [], "public": {}, "local_calls": 0}

    def _local(host, port=443):
        state["local_calls"] += 1
        return list(state["local"])

    def _dns(packet, server, timeout):
        ip = state["public"].get(server)
        if not ip:
            raise OSError(f"{server} 无应答")
        qid = struct.unpack(">H", packet[:2])[0]
        return _resp(ip, qid)

    monkeypatch.setattr(nd, "_local_ips", _local)
    monkeypatch.setattr(nd, "_dns_exchange", _dns)
    return state


def test_两边一致就不算污染(seams):
    seams["local"] = ["199.59.149.201"]
    seams["public"] = {"8.8.8.8": ["199.59.149.201"]}

    cmp = nd.compare("openlibrary.org")

    assert cmp["agrees"] is True and cmp["polluted"] is False
    assert cmp["server"] == "8.8.8.8" and cmp["error"] == ""


def test_两边不一致就是污染(seams):
    """第 104 期真机现象：本机给的是 Facebook 网段，公共解析器给的是正确地址。"""
    seams["local"] = ["31.13.112.4"]
    seams["public"] = {"8.8.8.8": ["199.59.149.201"]}

    cmp = nd.compare("openlibrary.org")

    assert cmp["agrees"] is False and cmp["polluted"] is True
    note = nd.pollution_note(cmp)
    assert "31.13.112.4" in note and "199.59.149.201" in note and "8.8.8.8" in note
    assert "本机 DNS 被污染" in note


def test_公共解析器答不上来就说无法核对(seams):
    """**未知不等于污染** —— 说不出来就得如实说不知道。"""
    seams["local"] = ["31.13.112.4"]

    cmp = nd.compare("openlibrary.org")

    assert cmp["agrees"] is None and cmp["polluted"] is False
    assert "无法交叉核对" in cmp["error"]


def test_主机名不合法就直接说没得核对(seams):
    cmp = nd.compare("31.13.112.4")

    assert cmp["host"] == "" and cmp["polluted"] is False
    assert seams["local_calls"] == 0, "IP 字面量不该去问 DNS"


def test_交叉核对按主机缓存(seams):
    seams["local"] = ["1.2.3.4"]
    seams["public"] = {"8.8.8.8": ["1.2.3.4"]}

    nd.compare("openlibrary.org")
    nd.compare("openlibrary.org")
    assert seams["local_calls"] == 1, "同一主机的重复核对要走缓存（一次体检十几个源共用几个主机）"

    nd.clear_cache()
    nd.compare("openlibrary.org")
    assert seams["local_calls"] == 2


def test_污染时升级分类(seams):
    seams["local"] = ["31.13.112.4"]
    seams["public"] = {"8.8.8.8": ["199.59.149.201"]}

    ref = nd.refine({"kind": "connect_timeout", "host": "openlibrary.org"})

    assert ref["kind"] == "dns_polluted"
    assert "本机 DNS 被污染" in ref["note"]


def test_解析一致但连不上是本机网络问题(seams):
    seams["local"] = ["199.59.149.201"]
    seams["public"] = {"8.8.8.8": ["199.59.149.201"]}

    ref = nd.refine({"kind": "network", "host": "openlibrary.org"})

    assert ref["kind"] == "network", "解析没问题就不该改分类"
    assert "防火墙" in ref["note"] and "不是站点故障" in ref["note"]


def test_本机解析不出而公共能解析(seams):
    seams["public"] = {"8.8.8.8": ["199.59.149.201"]}

    ref = nd.refine({"kind": "dns", "host": "api.audnexus.com"})

    assert ref["kind"] == "dns", "分类仍是解析失败"
    assert "问题在本机 DNS" in ref["note"]


def test_与解析无关的失败不去核对(seams):
    """读超时（站点慢）与被限流都不该为写一句说明去发 DNS 查询。"""
    ref = nd.refine({"kind": "timeout", "host": "openlibrary.org"})

    assert ref == {"kind": "timeout", "note": ""}
    assert seams["local_calls"] == 0

    assert nd.refine({"kind": "network", "host": ""}) == {"kind": "network", "note": ""}
    assert nd.refine({}) == {"kind": "", "note": ""}
    assert nd.refine(None) == {"kind": "", "note": ""}
