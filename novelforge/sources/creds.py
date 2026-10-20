"""书源凭据：Cookie 的**唯一真值源**（第 86 期）。

## 为什么必须有这个模块

Cookie 读写原先散在 `core/network.py`（`BrowserClient._load/_save_cookies`）与
`store.sources_status()` 两处**各自拼一遍**文件路径。两处一旦不一致，表现是
「界面说已保存登录态、下载时却还是匿名」—— 这类静默失败本项目最忌讳，
所以文件名的规则收成一处（:func:`cookie_file`）。

## 三条硬口径

1. **格式与 `BrowserClient` 逐字一致**：`LWPCookieJar` + `ignore_discard=True` /
   `ignore_expires=True`。写别的格式等于没写（客户端读不到，且不报错）。
2. **必须补域名**：从浏览器复制的串里通常没有 `Domain=`，而 `http.cookiejar` 是**按域匹配**的
   —— 不带域的 cookie 永远匹配不上任何请求。所以按来源声明的 `domains` 补齐，
   并优先用**去掉 `www.` 的父域**（父域能覆盖子域，反之不行）。
3. **只回状态、绝不回值**：:func:`status` 的返回里没有 value 字段
   （与 `llm.api_key` / `koreader.key` / `amazon_cookie` 同口径）。界面显示「已设置」就够了。
"""
from __future__ import annotations

import os
import pathlib
import re
from http.cookiejar import Cookie, LWPCookieJar

from .. import config

#: 粘贴串里可能出现的属性名（除这些之外一律当 cookie 对，避免把 `token=domain=x` 误判成属性）
_ATTRS = ("domain", "path", "expires", "max-age", "secure", "httponly", "samesite",
          "version", "comment")

_SUFFIX = ".cookies.txt"

#: 「没有登录态」的固定返回值。**一个口径只有一份**：状态接口 / 登录面板 / 书源列表
#: 都靠 ``has`` 判断，各写一份字典迟早漂移。
_EMPTY = {"has": False, "mtime": None, "size": 0, "count": 0, "domains": [], "names": []}


def cookie_dir() -> pathlib.Path:
    """Cookie 目录 —— **与 `DownloadManager` 用的是同一个表达式**。

    ⚠️ 不能图省事直接写 `config.COOKIE_DIR`：`DownloadManager` 读的是
    `network.cookie_dir` 配置（没配才回落环境变量）。用户一改这个配置，两处就指向不同目录，
    于是「保存了登录态却还是匿名」—— 正是本模块开头说的那类静默失败。
    """
    net = config.load_config().get("network") or {}
    raw = net.get("cookie_dir") or os.environ.get("COOKIE_DIR") or config.COOKIE_DIR
    return pathlib.Path(str(raw))


def cookie_name(rule_name: str) -> str:
    """Cookie 文件名（含后缀）—— **这个名字的拼法只有这一处**。"""
    return f"{rule_name}{_SUFFIX}"


def cookie_file(rule_name: str) -> pathlib.Path:
    """某书源的 Cookie 文件路径（`COOKIE_DIR/<规则名>.cookies.txt`）。

    ⚠️ 名字的判据**不在这里**：书源名同时是**磁盘上的文件名**，那条判据的唯一真值源是
    :func:`novelforge.sources.rules.rule_name_error`（第 120 期定的：不许路径分隔符 /
    ``..`` / 前导点 / 超长）。第 129 期才在这里补上调用 —— 此前这处**只拼路径不判名字**，
    与规则文件那一侧不一致：名字里带 ``..`` 就能把 Cookie 读出 / 写进 ``COOKIE_DIR``
    之外（``status`` / ``clear`` / ``save`` 三个口子都吃这个名字），超长名字则让
    ``status()`` 里的 ``is_file()`` 抛 ``OSError(ENAMETOOLONG)``，把「查登录态」变成 500。

    延迟导入 ``rules``（函数内，不是模块级）：``rules`` 要 ``core.network``，而
    ``network`` 又要 ``creds``（加载 Cookie）—— 模块级导入会成环。
    """
    from . import rules                       # 延迟导入：依赖方向见上
    err = rules.rule_name_error(rule_name)
    if err:
        raise ValueError(err)
    return cookie_dir() / cookie_name(str(rule_name).strip())


def parse_cookie_text(text: str) -> list:
    """把粘贴的 Cookie 解析成条目（`:class:`dict` 列表）。

    支持两种形态：

    · ``a=1; b=2``               —— DevTools 里复制的那串（**没有域名**，靠 `domains` 补）；
    · ``a=1; Domain=.x.com; Path=/`` —— 带属性的整串（属性会并到**前一条** cookie 上）。

    判据是「这段是不是已知属性名」：否则一律当 cookie 对，绝不猜。
    """
    out: list = []
    for chunk in re.split(r"[;\n\r]+", str(text or "")):
        part = chunk.strip()
        if not part:
            continue
        if "=" not in part:
            # 裸标志（`Set-Cookie` 里就是这样写 `Secure; HttpOnly`）—— 并到前一条上
            if out and part.lower() in ("secure", "httponly"):
                out[-1][part.lower()] = True
            continue
        k, v = part.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        if out and k.lower() in _ATTRS:
            out[-1][k.lower()] = v
            continue
        out.append({"name": k, "value": v, "domain": "", "path": "/", "secure": False})
    return [it for it in out if it["name"]]


def _site_domain(raw: str) -> str:
    """把来源声明的域名归成「可用父域」：去空格、去前导点、去 `www.`、转小写。"""
    d = str(raw or "").strip().lstrip(".").lower()
    return d[4:] if d.startswith("www.") else d


def save(rule_name: str, text: str, domains: list) -> dict:
    """把粘贴的 Cookie 落盘（**格式与 `BrowserClient` 读的一致**），返回 :func:`status`。

    没解析出任何 cookie、或既没有 `Domain=` 又拿不到来源声明域名时**如实报错**：
    不补域名地写下去等于写了个永远不生效的文件，那比报错更糟（用户以为登录好了）。
    """
    items = parse_cookie_text(text)
    if not items:
        raise ValueError("没解析出任何 Cookie：请粘贴形如 `name=value; name2=value2` 的内容")
    doms = [_site_domain(d) for d in (domains or [])]
    doms = [d for d in doms if d]
    if not doms and any(not it.get("domain") for it in items):
        raise ValueError("这条书源没有声明 domains，无法确定 Cookie 属于哪个站点（不猜）")

    jar = LWPCookieJar(str(cookie_file(rule_name)))
    for it in items:
        # 一律走同一套归一（去点、去 `www.`、转小写）：**存进去的就是真正用来匹配域的那个**，
        # 于是 `status()` 报出来的域与「这条 cookie 会不会被带上」是同一件事，不会两样。
        dom = _site_domain(it.get("domain") or doms[0])
        jar.set_cookie(Cookie(
            version=0, name=it["name"], value=it["value"], port=None, port_specified=False,
            domain=dom, domain_specified=True, domain_initial_dot=str(dom).startswith("."),
            path=str(it.get("path") or "/"), path_specified=True,
            secure=bool(it.get("secure")),
            # expires=None + discard=False：落盘时不带过期时间；客户端加载时忽略过期，
            # 于是「手动粘的登录态」不会因为站点没给 Expires 就当会话 cookie 被丢掉。
            expires=None, discard=False,
            comment=None, comment_url=None, rest={}, rfc2109=False,
        ))
    jar.save(ignore_discard=True, ignore_expires=True)
    return status(rule_name)


def status(rule_name: str) -> dict:
    """Cookie 状态：**只有元数据，没有任何 value**。

    名字非法或路径取不到 ⇒ 回「没有登录态」而**不抛** —— 与 ``rules.rule_file_exists``
    同一个口径（**读**路径上非法名 = 不存在；**写 / 删**路径上必须抛，见 :func:`cookie_file`）。
    """
    try:
        p = cookie_file(rule_name)
        with_jar = p.is_file()
    except (ValueError, OSError):
        return _EMPTY
    if not with_jar:
        return _EMPTY
    jar = LWPCookieJar(str(p))
    try:
        jar.load(ignore_discard=True, ignore_expires=True)
    except Exception:                                        # noqa: BLE001 —— 坏文件当空
        pass
    st = p.stat()
    return {
        "has": True, "mtime": st.st_mtime, "size": st.st_size, "count": len(jar),
        "domains": sorted({str(c.domain) for c in jar}),
        "names": sorted({str(c.name) for c in jar}),
    }


def clear(rule_name: str) -> bool:
    """清除登录态（删文件）。返回是否真的删掉了 —— 界面如实说「本来就没有」。

    名字非法 ⇒ ``False``（它不是一条能存在登录态的书源，等价于「本来就没有」）：
    走 :func:`cookie_file` 的 ``ValueError`` 会让「清除」这个动作回 500，而它本来就
    没什么可清。
    """
    try:
        p = cookie_file(rule_name)
        with_file = p.is_file()
    except (ValueError, OSError):
        return False
    if not with_file:
        return False
    try:
        p.unlink()
    except Exception:                                        # noqa: BLE001
        return False
    return True
