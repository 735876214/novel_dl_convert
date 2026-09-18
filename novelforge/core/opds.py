"""OPDS 目录订阅源（只读）。

供第三方阅读器（KyBook、静读天下、Moon+ Reader、Panels 等）订阅与下载。

**为什么不用 `/api/` 前缀**：本项目的鉴权中间件对 `/api/` 一律要求 Bearer Token，
而 OPDS 客户端只会发 **HTTP Basic Auth**，且多数不支持自定义请求头。
所以 `/opds` 用独立前缀 + 独立的 Basic 校验（复用 `auth.verify_pin`——账号就是应用账号，
不另建一套凭据，避免出现「第二份密码」这种迟早对不上的东西）。

协议：OPDS 1.2（Atom + Dublin Core + OpenSearch），acquisition feed 用
`http://opds-spec.org/acquisition`，封面用 `.../image` 与 `.../image/thumbnail`。

⚠️ **Atom 元素必须带命名空间**（`_q()` 包一层）。这是踩过的坑：
`ET.register_namespace("", NS_ATOM)` 只影响**序列化时的前缀**，不会给元素加命名空间；
用 `ET.Element("feed")` 建出来的仍是**无命名空间**的元素，客户端会解析不到条目。
"""
import datetime
import xml.etree.ElementTree as ET

NS_ATOM = "http://www.w3.org/2005/Atom"
NS_OPDS = "http://opds-spec.org/2010/catalog"
NS_DC = "http://purl.org/dc/terms/"
NS_OS = "http://a9.com/-/spec/opensearch/1.1/"

for _prefix, _uri in (("", NS_ATOM), ("opds", NS_OPDS), ("dc", NS_DC), ("os", NS_OS)):
    ET.register_namespace(_prefix, _uri)

# 每页条目数：OPDS 客户端小屏按需翻页，30 条一次下发不拖慢首屏
PAGE_SIZE = 30

# 格式 → MIME（acquisition link 的 type 必须是客户端认识的类型，否则不出现下载按钮）
_MIME = {
    "EPUB": "application/epub+zip",
    "PDF": "application/pdf",
    "MOBI": "application/x-mobipocket-ebook",
    "AZW3": "application/x-mobipocket-ebook",
    "CBZ": "application/vnd.comicbook+zip",
    "CBR": "application/vnd.comicbook-rar",
    "TXT": "text/plain",
    # 有声书：OPDS 客户端据此识别为音频（目录型书目的 size 为音频总体积）
    "AUDIO": "audio/mpeg",
}
_ACQ_REL = "http://opds-spec.org/acquisition"
_IMG_REL = "http://opds-spec.org/image"
_THUMB_REL = "http://opds-spec.org/image/thumbnail"
_NAV_TYPE = "application/atom+xml;profile=opds-catalog;kind=navigation"
_ACQ_TYPE = "application/atom+xml;profile=opds-catalog;kind=acquisition"


def _q(tag: str) -> str:
    """Atom 命名空间下的标签名。"""
    return f"{{{NS_ATOM}}}{tag}"


def mime_of(fmt: str) -> str:
    return _MIME.get((fmt or "").upper(), "application/octet-stream")


def _iso(ts: float) -> str:
    """Unix 时间 → Atom 的 updated（UTC、秒级、带 Z）。"""
    try:
        return datetime.datetime.fromtimestamp(float(ts), datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (TypeError, ValueError, OSError):
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _e(parent, tag: str, text=None, **attrs) -> ET.Element:
    el = ET.SubElement(parent, tag)
    for k, v in attrs.items():
        el.set(k, str(v))
    if text is not None:
        el.text = str(text)
    return el


def _atom(parent, tag: str, text=None, **attrs) -> ET.Element:
    return _e(parent, _q(tag), text, **attrs)


def _author(parent, name: str) -> None:
    """<author><name>…</name></author>。Atom 要求 entry 必须有 author。"""
    a = _atom(parent, "author")
    _atom(a, "name", name or "未知")


def _series_key(b: dict) -> float:
    """系列内序号：非数字（或空）排到最后，避免「第 1 册」被排到「第 10 册」后面。"""
    try:
        return float(str(b.get("series_index") or "").strip() or 1e9)
    except ValueError:
        return 1e9


def sort_books(bs: list, sort: str = "recent", order: str = "desc") -> list:
    """排序。sort = recent / title / author / series；order = asc / desc。"""
    keys = {
        "recent": lambda b: b.get("mtime") or 0,
        "title": lambda b: (b.get("title") or b.get("name") or "").lower(),
        "author": lambda b: ((b.get("author") or "").lower(), (b.get("title") or "").lower()),
        "series": lambda b: ((b.get("series") or "~").lower(), _series_key(b)),
    }
    key = keys.get(sort if sort in keys else "recent")
    return sorted(bs, key=key, reverse=(order != "asc"))


def _link(parent, rel: str, href: str, type_: str = None, **extra) -> None:
    attrs = {"rel": rel, "href": href}
    if type_:
        attrs["type"] = type_
    attrs.update(extra)
    _atom(parent, "link", None, **attrs)


def book_entry(parent, b: dict, base: str, *, with_alternate: bool = True,
               prefix: str = "/opds") -> None:
    """一本书 → OPDS acquisition entry。"""
    bid = b["id"]
    e = _atom(parent, "entry")
    _atom(e, "title", b.get("title") or b.get("name") or bid)
    _atom(e, "id", f"urn:novelforge:{bid}")
    _atom(e, "updated", _iso(b.get("mtime") or 0))
    _author(e, b.get("author") or "")

    if b.get("language"):
        _e(e, f"{{{NS_DC}}}language", b["language"])
    if b.get("publisher"):
        _e(e, f"{{{NS_DC}}}publisher", b["publisher"])
    if b.get("year"):
        _e(e, f"{{{NS_DC}}}issued", b["year"])
    if b.get("series"):
        idx = str(b.get("series_index") or "").strip()
        _e(e, f"{{{NS_DC}}}isPartOf", f"{b['series']}{f' #{idx}' if idx else ''}")
    for t in (b.get("tags") or [])[:12]:
        _atom(e, "category", None, term=str(t), label=str(t))

    # 封面：OPDS 用 image + image/thumbnail 两个 rel（客户端按屏幕密度各取所需）
    if b.get("has_cover"):
        _link(e, _IMG_REL, f"{base}{prefix}/cover/{bid}", "image/jpeg")
        _link(e, _THUMB_REL, f"{base}{prefix}/cover/{bid}", "image/jpeg")

    _link(e, _ACQ_REL, f"{base}{prefix}/download/{bid}",
          mime_of(b.get("format")), length=int(b.get("size") or 0))

    if with_alternate:
        # 详情 feed：客户端「书籍信息」页可据此展示完整元数据
        _link(e, "alternate", f"{base}{prefix}/book/{bid}", _ACQ_TYPE)


def _feed(title: str, feed_id: str, updated: float, links: list, *,
          subtitle: str = "") -> ET.Element:
    """Atom feed 底座（全站 4 个 feed 共用：导航 / 分组导航 / acquisition / 单本详情）。

    ``subtitle`` 是**keyword-only 且默认空**：既有调用点都传恰好 4 个位置参数，
    keyword-only 参数语法上不可能被位置参数顶掉；空值时**输出逐字节不变**。
    位置紧跟 ``<title>`` —— Atom 规范要求这个顺序，不图省事追加到末尾。
    """
    feed = ET.Element(_q("feed"))
    _atom(feed, "title", title)
    if subtitle:
        _atom(feed, "subtitle", subtitle, type="text")
    _atom(feed, "id", feed_id)
    _atom(feed, "updated", _iso(updated))
    _author(feed, "NovelForge")
    for lk in links:
        _link(feed, **lk)
    return feed


def tostring(feed: ET.Element) -> str:
    return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(feed, encoding="unicode")


def navigation_feed(base: str, counts: dict, *, prefix: str = "/opds",
                    title: str = "NovelForge 书库", feed_id: str = "urn:novelforge:opds:root",
                    libraries: list = None) -> str:
    """根导航：全部 / 最近添加 / 作者 / 系列 / 标签 / 搜索。

    客户端惯例是从根 feed 逐级点进来，所以这里必须是 navigation feed
    （`kind=navigation`），条目只带 subsection link、不带下载 link。

    ``prefix`` 让单库路由复用同一个导航：传 ``/opds/lib/<id>`` 时条目全部落到库内，
    默认 ``/opds`` → 输出与加这个参数之前**逐字节一致**。
    ``libraries`` = ``[(库 id, 名称, 册数)]``，**多于一个**才插入「按书库」入口
    （沿用 C2「仅多于一组才加组标题」的取法，单库时不给噪音）。
    """
    items = [
        ("全部书籍", f"{base}{prefix}/all", f"共 {counts.get('all', 0)} 本"),
        ("最近添加", f"{base}{prefix}/recent", "按入库时间倒序"),
        ("按作者", f"{base}{prefix}/authors", f"共 {counts.get('authors', 0)} 位"),
        ("按系列", f"{base}{prefix}/series", f"共 {counts.get('series', 0)} 个"),
        ("按标签", f"{base}{prefix}/tags", f"共 {counts.get('tags', 0)} 个"),
        ("搜索", f"{base}{prefix}/search", "OpenSearch"),
    ]
    libs = list(libraries or ())
    if len(libs) > 1:
        items.insert(2, ("按书库", f"{base}/opds/libraries", f"共 {len(libs)} 个"))
    updated = counts.get("updated") or 0
    feed = _feed(
        title,
        feed_id,
        updated,
        [
            {"rel": "start", "href": f"{base}{prefix}", "type_": _NAV_TYPE},
            {"rel": "search", "href": f"{base}{prefix}/search", "type_": "application/atom+xml"},
        ],
    )
    for label, href, desc in items:
        e = _atom(feed, "entry")
        _atom(e, "title", label)
        _atom(e, "id", href)
        _atom(e, "updated", _iso(updated))
        _atom(e, "content", desc, type="text")
        _link(e, "subsection", href, _NAV_TYPE)
    return tostring(feed)


def group_navigation(base: str, title: str, section: str, groups: list, updated: float,
                     *, descriptions: dict = None, prefix: str = "/opds",
                     feed_id: str = None) -> str:
    """作者 / 系列 / 标签的分组导航（每组一个 subsection）。

    ``descriptions``（可选）是 ``{组名: 简介}``：**传了才**给条目加 ``<summary>``。
    刻意做成外部显式传入、而不是函数内部自己去查系列元数据 —— 这个函数被
    作者 / 系列 / 标签三个路由共用，内部查库会让另外两页多跑无意义的查询、
    并顺带改变它们的输出。

    ``prefix`` 同 :func:`navigation_feed`：单库路由传 ``/opds/lib/<id>``，条目落进库内。
    """
    from urllib.parse import quote

    feed = _feed(
        title,
        feed_id or f"urn:novelforge:opds:{section}",
        updated,
        [
            {"rel": "start", "href": f"{base}{prefix}", "type_": _NAV_TYPE},
            {"rel": "up", "href": f"{base}{prefix}", "type_": _NAV_TYPE},
        ],
    )
    for name, count in groups:
        href = f"{base}{prefix}/{section}/{quote(str(name), safe='')}"
        e = _atom(feed, "entry")
        _atom(e, "title", name)
        _atom(e, "id", href)
        _atom(e, "updated", _iso(updated))
        _atom(e, "content", f"{count} 本", type="text")
        desc = str((descriptions or {}).get(name) or "").strip()
        if desc:
            _atom(e, "summary", desc, type="text")
        _link(e, "subsection", href, _ACQ_TYPE)
    return tostring(feed)


def acquisition_feed(
    base: str,
    title: str,
    section: str,
    books: list,
    *,
    page: int = 1,
    page_size: int = PAGE_SIZE,
    sort: str = "recent",
    order: str = "desc",
    subtitle: str = "",
    prefix: str = "/opds",
    feed_id: str = None,
) -> str:
    """书籍列表 feed（acquisition），带分页。

    ``subtitle``（可选）用于「系列：X」这类页面带出系列简介；默认空 → 输出不变。
    ``prefix`` 同 :func:`navigation_feed`；⚠️ self / next / previous / up 四组 href
    都要跟着它走，漏一处就会在单库翻页时跳回全局。
    """
    total = len(books)
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), pages)  # 越界回落到最后一页：客户端手滑翻过头不该看到报错
    chunk = books[(page - 1) * page_size: page * page_size]
    updated = max([b.get("mtime") or 0 for b in books] or [0])

    qs = f"&sort={sort}&order={order}" if section == "all" else ""
    up = base + (prefix if section in ("all", "recent", "search") else f"{prefix}/{section}")
    links = [
        {"rel": "start", "href": f"{base}{prefix}", "type_": _NAV_TYPE},
        {"rel": "up", "href": up, "type_": _NAV_TYPE},
        {"rel": "self", "href": f"{base}{prefix}/{section}?page={page}{qs}", "type_": _ACQ_TYPE},
    ]
    if page < pages:
        links.append({"rel": "next",
                      "href": f"{base}{prefix}/{section}?page={page + 1}{qs}", "type_": _ACQ_TYPE})
    if page > 1:
        links.append({"rel": "previous",
                      "href": f"{base}{prefix}/{section}?page={page - 1}{qs}", "type_": _ACQ_TYPE})

    feed = _feed(title, feed_id or f"urn:novelforge:opds:{section}:{page}", updated, links,
                 subtitle=str(subtitle or "").strip())
    # OpenSearch：客户端据此显示「第 N 页 / 共 M 条」
    _e(feed, f"{{{NS_OS}}}totalResults", total)
    _e(feed, f"{{{NS_OS}}}startIndex", (page - 1) * page_size + 1)
    _e(feed, f"{{{NS_OS}}}itemsPerPage", page_size)
    for b in chunk:
        book_entry(feed, b, base, prefix=prefix)
    return tostring(feed)


def library_navigation(base: str, libs: list, updated: float) -> str:
    """书库导航：``libs`` = ``[(库 id, 名称, 册数)]``，每条 subsection 指向该库的一整套 feed。

    传进来的**只应是对 OPDS 可见的库** —— 可见性判定留在 server 侧，那里才有请求与
    配置上下文；这个函数只管把给定的库列出来，不做第二处判断（免得两处口径走样）。
    """
    from urllib.parse import quote

    feed = _feed(
        "按书库",
        "urn:novelforge:opds:libraries",
        updated,
        [
            {"rel": "start", "href": f"{base}/opds", "type_": _NAV_TYPE},
            {"rel": "up", "href": f"{base}/opds", "type_": _NAV_TYPE},
        ],
    )
    for lid, name, count in libs:
        href = f"{base}/opds/lib/{quote(str(lid), safe='')}"
        e = _atom(feed, "entry")
        _atom(e, "title", name)
        _atom(e, "id", href)
        _atom(e, "updated", _iso(updated))
        _atom(e, "content", f"{count} 本", type="text")
        _link(e, "subsection", href, _NAV_TYPE)
    return tostring(feed)


def book_feed(base: str, b: dict, *, prefix: str = "/opds") -> str:
    """单本书的详情 feed：客户端「书籍信息」页用它，也提供下载入口。"""
    feed = _feed(
        b.get("title") or b.get("name") or b["id"],
        f"urn:novelforge:opds:book:{b['id']}",
        b.get("mtime") or 0,
        [
            {"rel": "start", "href": f"{base}{prefix}", "type_": _NAV_TYPE},
            {"rel": "up", "href": f"{base}{prefix}/all", "type_": _ACQ_TYPE},
        ],
    )
    book_entry(feed, b, base, with_alternate=False, prefix=prefix)
    return tostring(feed)
