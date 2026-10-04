"""出站 URL 的**唯一**闸门：URL 导入书源是本站唯一由用户指定 URL 的出网点（第 94 期阶段 4a）。

## 为什么单开一层

本项目其余的出网目标**都由书源规则里的域名白名单决定**，客户端不传 URL：

* 章节抓取永不由客户端传 URL（`server.py` 的 `/api/chapters`、`/api/download` 两处注解）；
* 搜索 / 目录 / 正文的地址来自规则里的 `domains` 与模板。

**URL 订阅导入**（`POST /api/sources/import-url`）破了这个口径 —— 用户直接给地址，服务端
替他去取。单用户 NAS 上这就等于把「读取内网」的能力开给了任何能打到这个端口的人：
`http://127.0.0.1:8080/admin`、`http://169.254.169.254/latest/meta-data/`、
`http://192.168.1.1/` 之类会返回**内网服务的内容**，而书源文件是 JSON/文本 ——
内容会原样进入导出、诊断、错误信息里。所以这条路上单独设闸。

## 判据只有一处

`ip_scope()` 的「落不进全球可路由集合」与 `server._is_local_request`（入站：来源是不是
本机 / 局域网）**是同一个集合、相反的方向**，所以两边共用这一个函数。刻意不用
`ipaddress.is_private`：它把文档段 / 保留段判成「公网」，而以「能不能从公网到达」为准时
它们同样不该被访问（本仓第 63 期就是这个口径，这里沿用而不是另立一套）。

## 逐跳复查

`httpx` 的自动重定向**不会**经过这里，所以不能开 `follow_redirects=True` 就完事 ——
一个公网地址 302 到 `http://127.0.0.1/` 就绕过了首跳校验。做法是让
`BrowserClient` 把**每一个**请求（含每一跳重定向）先过一遍 `assert_public_url`，
见 :func:`guard_request` 与 `core/network.BrowserClient(request_guard=...)`。

## 残余风险（**如实记录，不假装没有**）

校验时解析域名拿到 IP，httpx 真正连接时会**再解析一次**（TOCTOU）。攻击者控制一个
TTL 极短的域名，理论上可以让「校验时是公网 IP、连接时是内网 IP」。
Node/httpx 层面没有「连已校验 IP + 保留 Host/SNI」的现成开关（改 URL 成 IP 会破坏
HTTPS 的证书校验），所以这里**不做**伪装的加固，而是：

* 每一跳都校验（覆盖重定向）；
* 拒绝**任一**解析结果为非公网（多 A 记录里混一个内网也拒）；
* 把这段残余风险写在这里与 `docs/roadmap-gaps-remaining.md`，交给部署者判断
  （单用户 NAS 场景下，能打到这个端口的人通常已经在内网了）。
"""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

#: 只放行这两种。`file:` / `gopher:` / `ftp:` / `data:` 一律拒 —— 它们要么读本地文件，
#: 要么是 SSRF 的经典跳板。
ALLOWED_SCHEMES = ("http", "https")


class UrlBlocked(ValueError):
    """目标 URL 不允许访问。消息是**可以直接显示给用户**的人话原因。"""


def ip_scope(host: str) -> str | None:
    """``host`` 的归属：``"public"`` / ``"local"`` / ``None``（不是 IP 字面量）。

    **判据的唯一实现** —— 入站判「来源是不是本机/局域网」与出站判「目标是不是公网」
    都调它（方向相反，集合同一个）。IPv4-mapped IPv6（``::ffff:192.168.0.9``，双栈
    监听下很常见）先还原成 IPv4 再判，否则它既非回环也非私网，会被白白放过。
    """
    try:
        ip = ipaddress.ip_address((host or "").strip())
    except ValueError:
        return None                       # 域名 / 空串 / 带端口的字符串
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return "public" if ip.is_global else "local"


def resolve(host: str) -> list:
    """解析出该主机的**全部** A / AAAA 地址（去重，保序）。解析不出返回空列表。"""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    out: list = []
    for info in infos:
        addr = info[4][0]
        if addr not in out:
            out.append(addr)
    return out


def assert_public_url(url: str) -> str:
    """校验一个 URL 可以被出站访问；返回原 URL。不允许则抛 :class:`UrlBlocked`。

    三种拒法各有各的话说：协议不对、主机名解析不出、**任一**解析结果是内网。
    """
    parts = urlsplit((url or "").strip())
    scheme = (parts.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        raise UrlBlocked(f"只允许 http / https 的地址（协议：{scheme or '空'}）")
    host = parts.hostname or ""
    if not host:
        raise UrlBlocked("地址里没有主机名")
    scope = ip_scope(host)               # 直接就是 IP 的那种（http://127.0.0.1/）
    if scope == "local":
        raise UrlBlocked(f"拒绝访问内网 / 本机地址：{host}")
    if scope == "public":
        return url                       # IP 字面量且是公网 —— 不必再解析
    addrs = resolve(host)
    if not addrs:
        raise UrlBlocked(f"域名解析不出地址：{host}")
    # ⚠️ 只要**有任何一个**解析结果落在内网就整条拒 —— 「多 A 记录里混一个内网」正是
    # 绕过单值校验的常见手法。
    local = [a for a in addrs if ip_scope(a) != "public"]
    if local:
        raise UrlBlocked(
            f"域名 {host} 解析到内网 / 保留地址（{'、'.join(local[:3])}）—— 已拒绝")
    return url


async def guard_request(request) -> None:
    """给 ``httpx`` 的请求钩子用（收到的是 `httpx.Request`）：校验不过就抛 :class:`UrlBlocked`。

    挂到 `BrowserClient(request_guard=...)` 后**每一跳**（含重定向）都会先过这里 ——
    httpx 的 request 事件钩子在 `_send_handling_redirects` 的循环里逐个 await，
    「公网地址 302 到内网」这一步因此挡得住（不是只校验首跳）。

    三处实现细节都是必须的，且都是**实测**踩出来的：

    * **必须是 `async def`** —— httpx 对钩子做 `await hook(request)`，
      同步函数的返回值是 `None`，`await None` 会直接 `TypeError`；
    * **取 `request.url`，不是 `str(request)`** —— 钩子拿到的是 `Request` 对象，
      `str()` 出来是 `"<Request [GET http://…]>"`，`urlsplit` 解不出协议 ⇒ **每一个**
      请求（含首跳）都会被判成「协议：空」而拒绝（URL 导入恒失败）；
    * **解析放进线程池** —— `socket.getaddrinfo` 是阻塞调用，直接在事件循环里解析
      会让一次 URL 导入把整个服务卡住（本仓对阻塞调用一律走 `run_in_executor`）。
    """
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, assert_public_url, str(getattr(request, "url", request)))
