"""出网失败的**归因**：把「连不上」拆成 DNS / TLS / 代理 / 连接超时 / 超时 / 网络六档。

为什么需要这个（第 104 期真机事故）：

- 本机的 `openlibrary.org` 解析到 **31.13.112.4**（Facebook 网段），`www.goodreads.com`
  解析到 **128.242.240.253**，而公共解析器 8.8.8.8 给的是 **199.59.149.201** /
  **199.59.148.6**；`hosts` 文件没有任何自定义行 ⇒ **上游 DNS 被污染**。
- 在那之前，体检把这件事报成「超时」，用户照着自己去修一个**根本没坏**的源；
  仓规反复写「误报比不测更糟：用户会去修一个根本没坏的东西」。

**边界（不做的事，写清楚免得被误用）**：

1. 只做**解析结果比对**，不做端到端连通性探测（真正的连通性由体检自己那一次外呼回答）；
2. 公共解析器答不上来就说「无法交叉核对」—— **未知 ≠ 污染**（宁可不说，也不能乱指）；
3. 本模块**只在诊断路径**（`probe` / `health_one`）被调用。数据路径（`search` / `detail`）
   只用 :func:`classify_exc` 这个**纯函数**（按异常链分类、零 I/O）—— 抓取不该为了写一句
   错误说明去发 DNS 查询。

`_local_ips` / `_dns_exchange` 是**两个 I/O 缝**，测试里替换掉即可做到「全进程零真实 DNS」。
"""
import random
import socket
import ssl
import struct
import time

import httpx

#: 交叉核对用的公共解析器。⚠️ 顺序有意义：本机实测 `8.8.8.8` 的 UDP/53 通、`1.1.1.1` 无应答，
#: 所以前者在前。**故意不加配置键** —— 这是诊断用的常量，不是用户可调的功能（§7.2 禁投机）。
DNS_CHECK_SERVERS = ("8.8.8.8", "1.1.1.1")

#: 哪些结论值得再花一次往返去交叉核对解析结果。
#: `timeout`（连上了但没回完）不在其中：那是站点慢，和 DNS 无关。
CROSS_CHECK_KINDS = ("dns", "connect_timeout", "network")

#: `compare()` 的结果缓存（本机解析在污染场景下**每次都可能给出不同错地址**，
#: 但一次体检里十几家源共用几个主机名，缓存能把往返从「每家一次」压到「每主机一次」）。
_CROSS_CACHE: dict = {}
#: 缓存条目上限（超出按写入时间淘汰最旧，与元数据缓存一个口径）。
_CROSS_CACHE_MAX = 64


def _clean_host(host) -> str:
    """归一化主机名；**IP 字面量返回空串**（它没有解析结果可比对）。"""
    h = str(host or "").strip().strip(".").lower()
    if not h:
        return ""
    if h.replace(".", "").isdigit() or ":" in h:      # 1.2.3.4 / IPv6
        return ""
    return h


def _chain(exc, limit: int = 8):
    """异常链（`__cause__` → `__context__`）。httpx 会把底层错误包一层，

    真正有用的类型（`socket.gaierror` / `ssl.SSLError`）往往在内层，必须沿着链找。
    """
    seen, cur = set(), exc
    while cur is not None and len(seen) < limit and id(cur) not in seen:
        seen.add(id(cur))
        yield cur
        cur = getattr(cur, "__cause__", None) or getattr(cur, "__context__", None)


def classify_exc(exc) -> str:
    """按**异常链**分类，回下面之一（空串 = 认不出来）：

    - ``dns``：解析不出域名（`socket.gaierror`，含 Windows 的 `[Errno 11001]`）
    - ``tls``：TLS 握手失败（证书 / 中间人 / 站点中途断开）
    - ``proxy``：代理不可用（本仓已记录的环境变量陷阱）
    - ``connect_timeout``：TCP 都建不起来（被阻断 / 地址错）
    - ``timeout``：连上了但没回完（站点慢 / 被限流）
    - ``network``：其它连接层失败（拒绝 / 重置 / 端到端不可达）

    **纯函数、零 I/O** —— 数据路径可以直接调它。
    """
    try:
        for e in _chain(exc):
            if isinstance(e, socket.gaierror):
                return "dns"
            if isinstance(e, ssl.SSLError):
                return "tls"
            if isinstance(e, httpx.ProxyError):
                return "proxy"
        for e in _chain(exc):
            if isinstance(e, httpx.ConnectTimeout):
                return "connect_timeout"
            if isinstance(e, httpx.TimeoutException):
                return "timeout"
        for e in _chain(exc):
            if isinstance(e, (httpx.ConnectError, ConnectionRefusedError,
                              ConnectionResetError, BrokenPipeError, OSError)):
                return "network"
    except Exception:                                    # noqa: BLE001 —— 归因本身绝不能抛
        return ""
    return ""


def host_of(exc, url: str = "") -> str:
    """这次失败打的是**哪个主机**（用于交叉核对）；拿不到就回空串。"""
    try:
        for e in _chain(exc):
            req = getattr(e, "request", None)
            h = _clean_host(getattr(getattr(req, "url", None), "host", ""))
            if h:
                return h
        if url:
            return _clean_host(httpx.URL(url).host)
    except Exception:                                    # noqa: BLE001
        return ""
    return ""


def describe_exc(exc, url: str = "") -> dict:
    """``{kind, host}`` —— **纯函数、零 I/O**，供 `search()` 附在失败返回值里。

    诊断路径拿到它之后再调 :func:`refine`（那一步才会真的去问公共解析器）。
    """
    try:
        return {"kind": classify_exc(exc), "host": host_of(exc, url)}
    except Exception:                                    # noqa: BLE001
        return {"kind": "", "host": ""}


# ---------------------------------------------------------------- DNS 查询（极简）

def _build_query(name: str, qid: int) -> bytes:
    """拼一个 A 记录的 DNS 查询包（标准查询、递归请求、单问题）。"""
    q = b""
    for part in [p for p in str(name).split(".") if p]:
        raw = part.encode("ascii", "ignore")[:63]
        q += bytes([len(raw)]) + raw
    q += b"\x00"
    head = struct.pack(">HHHHHH", qid & 0xFFFF, 0x0100, 1, 0, 0, 0)
    return head + q + struct.pack(">HH", 1, 1)


def _skip_name(data: bytes, off: int) -> int:
    """跳过一段域名（遇 `0x00` 结束，遇压缩指针 `0b11` 也结束）。"""
    while off < len(data):
        ln = data[off]
        if ln == 0:
            return off + 1
        if ln & 0xC0:
            return off + 2
        off += 1 + ln
    return off


def _parse_a_records(data: bytes, qid: int) -> list:
    """从响应里取 A 记录。**只认我们发的那个 qid、rcode 不为 0 就回空**；截断不抛。"""
    if not data or len(data) < 12:
        return []
    rid, flags, qd, an, _ns, _ar = struct.unpack(">HHHHHH", data[:12])
    if rid != (qid & 0xFFFF) or (flags & 0x000F):
        return []
    off = 12
    for _ in range(qd):
        off = _skip_name(data, off) + 4
    out = []
    for _ in range(an):
        off = _skip_name(data, off)
        if off + 10 > len(data):
            break
        rtype, rclass, _ttl, rdlen = struct.unpack(">HHIH", data[off:off + 10])
        off += 10
        if rtype == 1 and rclass == 1 and rdlen == 4 and off + 4 <= len(data):
            ip = ".".join(str(b) for b in data[off:off + 4])
            if ip not in out:
                out.append(ip)
        off += rdlen
    return out


def _dns_exchange(packet: bytes, server: str, timeout: float) -> bytes:
    """**I/O 缝**：把查询包发给 `server:53`（UDP）并取回响应。"""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(timeout)
        s.sendto(packet, (server, 53))
        data, _addr = s.recvfrom(2048)
    return data


def _local_ips(host: str, port: int = 443) -> list:
    """**I/O 缝**：本机解析结果（去重保序）。"""
    out = []
    for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP):
        ip = info[4][0]
        if ip and ip not in out:
            out.append(ip)
    return out


def resolve_via(server: str, host: str, timeout: float = 2.0) -> list:
    """问某个解析器要 `host` 的 A 记录（`[]` = 答不上来）。"""
    qid = random.randrange(0, 0x10000)
    return _parse_a_records(_dns_exchange(_build_query(host, qid), server, timeout), qid)


# ---------------------------------------------------------------- 交叉核对

def compare(host: str, *, timeout: float = 2.0, servers=DNS_CHECK_SERVERS,
            cache_ttl: float = 60.0) -> dict:
    """本机解析 vs 公共解析：``{host, local, public, server, agrees, polluted, error}``。

    - ``agrees``：两边**有交集**（CDN 多地址是常态，只要求有交集）；
    - ``polluted``：两边都答出来了但**完全没有交集** ⇒ 本机拿到的是错地址；
    - 公共解析器全答不上来 ⇒ ``agrees=None`` + ``error`` 说明「无法交叉核对」——
      **未知不等于污染**，宁可说不出来，也不能乱指。

    结果按主机缓存 `cache_ttl` 秒（一次体检里十几个源常常只涉及几个主机名）。
    """
    h = _clean_host(host)
    if not h:
        return {"host": "", "local": [], "public": [], "server": "", "agrees": None,
                "polluted": False, "error": "没有可核对的主机名"}
    now = time.monotonic()
    hit = _CROSS_CACHE.get(h)
    if hit and cache_ttl > 0 and now - hit[0] < cache_ttl:
        return dict(hit[1])
    try:
        local = _local_ips(h)
    except Exception:                                    # noqa: BLE001 —— 诊断不能抛
        local = []
    public, server, err = [], "", ""
    for srv in tuple(servers or ()):
        try:
            got = resolve_via(srv, h, timeout)
        except Exception as e:                           # noqa: BLE001
            err = f"{srv}：{e}"
            continue
        if got:
            public, server, err = got, srv, ""
            break
    if local and public:
        agrees = bool(set(local) & set(public))
        polluted = not agrees
    else:
        agrees, polluted = None, False
    if not public:
        err = f"公共解析器不可用，无法交叉核对（{err or '没有返回地址'}）"
    out = {"host": h, "local": local, "public": public, "server": server,
           "agrees": agrees, "polluted": polluted, "error": "" if public else err}
    if len(_CROSS_CACHE) >= _CROSS_CACHE_MAX and h not in _CROSS_CACHE:
        oldest = min(_CROSS_CACHE, key=lambda k: _CROSS_CACHE[k][0])
        _CROSS_CACHE.pop(oldest, None)
    _CROSS_CACHE[h] = (now, dict(out))
    return out


def _show(ips: list) -> str:
    return "、".join(ips[:2]) if ips else "—"


def pollution_note(cmp: dict) -> str:
    """本机解析到错地址（与公共解析器完全不一致）。"""
    return (f"域名 {cmp.get('host')} 在本机解析到 {_show(cmp.get('local'))}，"
            f"而公共解析器（{cmp.get('server')}）给的是 {_show(cmp.get('public'))} —— "
            "两者完全不一致 ⇒ 多半是**本机 DNS 被污染**，不是站点故障"
            "（先检查本机 DNS 设置，或换一个 DNS 再试）")


def unresolved_note(cmp: dict) -> str:
    """本机解析不出来，但公共解析器能。"""
    return (f"本机解析不出 {cmp.get('host')}，而公共解析器（{cmp.get('server')}）"
            f"能解析到 {_show(cmp.get('public'))} ⇒ 问题在本机 DNS，不是站点故障")


def blocked_note(cmp: dict) -> str:
    """解析一致但连不上 ⇒ 本机网络 / 防火墙拦了。"""
    return (f"{cmp.get('host')} 解析一致（{_show(cmp.get('local'))}）但还是连不上 ⇒ "
            "多半是本机网络或防火墙屏蔽了该站点，不是站点故障")


def refine(fail: dict, *, timeout: float = 2.0) -> dict:
    """把 ``{kind, host}`` 再往下钉一层，回 ``{kind, note}``。

    只在 :data:`CROSS_CHECK_KINDS` 里、且主机名已知时才真的去问公共解析器 ——
    这是本模块**唯一**会做 I/O 的公开入口，**调用方只能是诊断路径**。

    污染时 kind 升级成 ``dns_polluted``（结论分类里单列一档：它要用户做的事与「连不上」
    完全不同 —— 去改本机 DNS，而不是去等站点修复）。
    """
    kind = str((fail or {}).get("kind") or "")
    host = str((fail or {}).get("host") or "")
    if kind not in CROSS_CHECK_KINDS or not host:
        return {"kind": kind, "note": ""}
    try:
        cmp = compare(host, timeout=timeout)
    except Exception:                                    # noqa: BLE001
        return {"kind": kind, "note": ""}
    if cmp.get("polluted"):
        return {"kind": "dns_polluted", "note": pollution_note(cmp)}
    if cmp.get("agrees"):
        return {"kind": kind, "note": blocked_note(cmp)}
    if cmp.get("public") and not cmp.get("local"):
        return {"kind": kind, "note": unresolved_note(cmp)}
    return {"kind": kind, "note": str(cmp.get("error") or "")}


def clear_cache() -> int:
    """清空交叉核对缓存（测试用；返回清掉的条数）。"""
    n = len(_CROSS_CACHE)
    _CROSS_CACHE.clear()
    return n
