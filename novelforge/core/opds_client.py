"""OPDS **客户端**：订阅远程 OPDS 目录（Komga / Calibre-Web / 任何标准 OPDS 源）。

与 ``core/opds.py``（本应用**对外提供**的 OPDS 服务）方向相反，两者互不依赖 ——
本模块只负责「读别人的 feed、把书取回来」。

解析只看 Atom 的通用约定，不针对某个服务器写特例：

- 条目带 ``rel="subsection"``            → 目录项，可继续点进去
- 条目带 ``rel="http://opds-spec.org/acquisition"`` → 可下载
- 两者都没有的条目直接丢弃（导航 feed 里常混着 search 之类）

**只在可信网络里用**：地址由用户自己填（内网 Komga 是主场景），
所以这里不做 SSRF 白名单，只强制 http/https 并限制响应体大小。
"""
import pathlib
import xml.etree.ElementTree as ET

import httpx

from .opds import NS_ATOM, NS_DC, NS_OS

NS = {"a": NS_ATOM, "dc": NS_DC, "os": NS_OS}

#: 响应的 content-type（宽松匹配：不少源返回 application/atom+xml 或 text/xml）
FEED_TYPES = ("application/atom+xml", "application/xml", "text/xml", "application/opds+json")
#: feed 体积上限（有些源一页就几 MB，超过基本是异常或恶意）
MAX_FEED_BYTES = 8 * 1024 * 1024
#: 单本书下载上限：保护磁盘，也防「点错链接当下来一个几百 G 的镜像」
MAX_BOOK_BYTES = 4 * 1024 * 1024 * 1024
#: 超时：连接 10s、整体 120s（内网慢盘 + 大文件下载）
TIMEOUT = httpx.Timeout(120.0, connect=10.0)


def _text(el, path: str, default: str = "") -> str:
    if el is None:
        return default
    found = el.find(path, NS)
    return (found.text or "").strip() if found is not None and found.text else default


def _abs(href: str, base: str) -> str:
    """相对链接补全为绝对地址（feed 里两种都会出现）。"""
    href = (href or "").strip()
    if not href:
        return ""
    if href.startswith(("http://", "https://")):
        return href
    return httpx.URL(base).join(href).human_repr()


def parse_feed(xml_text: str, base_url: str) -> dict:
    """Atom feed → ``{title, entries, next, up}``。

    entries 每项：
      ``{title, author, updated, kind, href, type, length, cover, summary, size_hint}``
      kind = ``nav``（进目录）/ ``book``（可下载）。
    """
    root = ET.fromstring(xml_text)
    out = {
        "title": _text(root, "a:title") or "OPDS",
        "next": "",
        "up": "",
        "entries": [],
    }
    for lk in root.findall("a:link", NS):
        rel = (lk.get("rel") or "").strip()
        href = _abs(lk.get("href") or "", base_url)
        if rel == "next":
            out["next"] = href
        elif rel == "up":
            out["up"] = href

    for e in root.findall("a:entry", NS):
        title = _text(e, "a:title")
        acq = None
        sub = None
        cover = ""
        for lk in e.findall("a:link", NS):
            rel = (lk.get("rel") or "").strip()
            if rel == "http://opds-spec.org/acquisition" and acq is None:
                acq = lk
            elif rel == "subsection" and sub is None:
                sub = lk
            elif rel in ("http://opds-spec.org/image", "http://opds-spec.org/image/thumbnail") and not cover:
                cover = _abs(lk.get("href") or "", base_url)
        if sub is not None:
            out["entries"].append({
                "title": title or "(未命名目录)",
                "author": "",
                "updated": _text(e, "a:updated"),
                "kind": "nav",
                "href": _abs(sub.get("href") or "", base_url),
                "type": sub.get("type") or "",
                "length": 0,
                "cover": "",
                "summary": _text(e, "a:content") or _text(e, "a:summary"),
                "size_hint": "",
            })
        elif acq is not None:
            length = 0
            try:
                length = int(acq.get("length") or 0)
            except (TypeError, ValueError):
                length = 0
            out["entries"].append({
                "title": title or "(未命名)",
                "author": _text(e, "a:author/a:name"),
                "updated": _text(e, "a:updated"),
                "kind": "book",
                "href": _abs(acq.get("href") or "", base_url),
                "type": acq.get("type") or "",
                "length": length,
                "cover": cover,
                "summary": _text(e, "a:summary") or _text(e, "dc:description"),
                "series": _text(e, "dc:isPartOf"),
                "size_hint": f"{length / 1048576:.1f} MB" if length else "",
            })
    return out


class OpdsError(Exception):
    """抓取/解析失败（消息直接给用户看）。"""


def _client(source: dict) -> httpx.Client:
    """按源凭据建客户端。

    - URL 只允许 http/https —— ``file://`` 之类一律拒绝。
    - **``trust_env=False``：不走系统 / 环境变量代理。**
      OPDS 源（Komga、Calibre-Web）绝大多数在**内网**，而 macOS 与企业环境的
      系统代理会把内网请求也一起转发出去。httpx 默认读系统代理，实测踩到过：
      ``127.0.0.1:1`` 与一个不存在的域名都被代理回成 **502**，真实错误
      （连接被拒 / DNS 失败）完全被掩盖，排查起来毫无头绪。
      真要经代理访问公网源，再加显式开关（当前不做）。
    """
    url = str(source.get("url") or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise OpdsError("源地址必须以 http:// 或 https:// 开头")
    user = str(source.get("username") or "")
    auth = httpx.BasicAuth(user, str(source.get("password") or "")) if user else None
    return httpx.Client(
        timeout=TIMEOUT,
        follow_redirects=True,
        auth=auth,
        trust_env=False,
        headers={"User-Agent": "NovelForge/1.0 (+opds-client)", "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.8"},
    )


def fetch(source: dict, href: str = "") -> dict:
    """抓取并解析一个 feed。``href`` 为空时用源地址（即订阅入口）。"""
    url = (href or "").strip() or str(source.get("url") or "").strip()
    with _client(source) as c:
        try:
            r = c.get(url)
        except httpx.HTTPError as e:
            raise OpdsError(f"连接失败：{e}") from e
        if r.status_code == 401:
            raise OpdsError("需要认证：请检查用户名 / 密码")
        if r.status_code >= 400:
            raise OpdsError(f"源返回 {r.status_code}")
        body = r.text
    if len(body.encode("utf-8", "ignore")) > MAX_FEED_BYTES:
        raise OpdsError("feed 过大，已中止")
    try:
        parsed = parse_feed(body, url)
    except ET.ParseError as e:
        raise OpdsError(f"不是有效的 OPDS/Atom feed：{e}") from e
    parsed["url"] = url
    return parsed


#: MIME 关键字 → 扩展名（下载落盘要用，Komga 那边靠扩展名认格式）
_MIME_EXT = (
    ("epub", ".epub"),
    ("pdf", ".pdf"),
    ("comicbook+zip", ".cbz"),
    ("mobipocket", ".mobi"),
    ("plain", ".txt"),
)
_KNOWN_EXTS = (".cbz", ".epub", ".pdf", ".mobi", ".azw3", ".azw", ".txt")


def split_name(title: str, content_type: str = "") -> tuple:
    """把「标题 + MIME」拆成 ``(主干, 扩展名)``（扩展名含点、**永远非空**）。

    优先级：MIME 认得出就用它（服务端最权威）；否则用标题自带的扩展名；
    都没有则默认 ``.epub`` —— OPDS 源里绝大多数是电子书。

    返回的两部分可直接喂给 ``komga.relpath_for()``：它会自己拼 ``主干.扩展名``，
    所以这里必须**先把扩展名从标题里剥掉**，否则会出现 ``三体.epub.epub``。
    """
    ct = (content_type or "").lower()
    stem = (title or "").strip() or "未命名"
    ext = ""
    for key, e in _MIME_EXT:
        if key in ct:
            ext = e
            break
    low = stem.lower()
    for e in _KNOWN_EXTS:
        if low.endswith(e):
            stem = stem[:-len(e)]
            ext = ext or e
            break
    return stem, ext or ".epub"


def download(source: dict, href: str, dest_dir: pathlib.Path, filename: str) -> dict:
    """流式下载到 ``dest_dir/filename``（先写 ``.part`` 再改名，中断不留半成品）。

    返回 ``{path, bytes}``；失败抛 :class:`OpdsError`。
    """
    dest_dir = pathlib.Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / filename
    if target.exists():
        raise OpdsError("同名文件已存在")
    part = target.with_name(target.name + ".part")
    total = 0
    try:
        with _client(source) as c, c.stream("GET", href) as r:
            if r.status_code == 401:
                raise OpdsError("需要认证：请检查用户名 / 密码")
            if r.status_code >= 400:
                raise OpdsError(f"下载失败：源返回 {r.status_code}")
            with open(part, "wb") as f:
                for chunk in r.iter_bytes(65536):
                    total += len(chunk)
                    if total > MAX_BOOK_BYTES:
                        raise OpdsError("文件超过 4GB 上限，已中止")
                    f.write(chunk)
        part.replace(target)
    except OpdsError:
        part.unlink(missing_ok=True)
        raise
    except (httpx.HTTPError, OSError) as e:
        part.unlink(missing_ok=True)
        raise OpdsError(f"下载失败：{e}") from e
    return {"path": target, "bytes": total}
