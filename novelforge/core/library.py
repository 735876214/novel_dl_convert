"""书目库：扫描导出目录并聚合出工具页需要的真实数据。

后端没有「图书库」实体 —— 唯一的真实「书」就是 ``OUTPUT_DIR`` 里的成品文件。
所以这里以「扫目录 + 读元数据」的方式聚合出**书目 / 作者 / 系列**，并在此之上
做**重复分组**与**缺失检测**，供工具页的四个工具消费：

- 实体管理     → :func:`entities`
- 重复书籍     → :func:`duplicate_groups`
- 缺失资源     → :func:`missing_items`
- 批量重命名   → 只读 :func:`books`，改名逻辑在 ``fileops``

EPUB 解析是 IO 密集（要解开 zip 读 OPF），因此扫描结果做进程内短期缓存：
TTL + 目录指纹（文件数 + 最新 mtime）双重判定；任何写操作后调用
:func:`invalidate` 立即失效，保证下一个请求读到新状态。
"""
from __future__ import annotations

import hashlib
import html.parser
import pathlib
from urllib.parse import quote, unquote
import re
import threading
import time
import zipfile

from .. import config
from . import comics, metadata

# 只把这些扩展名当成「书」；与 /api/files 的全量列表不同，这里是有意收窄的
# .cbz（漫画）在列；.cbr 刻意不在 —— RAR 需要额外解压依赖，见 core/comics.py
BOOK_EXTS = (".epub", ".mobi", ".azw3", ".pdf", ".txt", ".cbz")

# 可能作为封面出现的图片扩展名
_COVER_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")

# 小于这个字节数的「封面」一律视为无效。
# 实测遇到过 14 字节的 stub JPEG（只有 SOI + APP0/JFIF + EOI，没有任何图像数据）——
# 扩展名和 magic bytes 都对，接口也照常返回 200，但浏览器解码必然失败。
# 这类书如果算作「有封面」，就会从「无封面」分组里消失，用户根本找不到它们。
_COVER_MIN_BYTES = 1024

_CACHE_TTL = 5.0

_lock = threading.RLock()
_cache = {"at": 0.0, "sig": None, "books": []}

# 文件名噪声：括号里的版本说明 + 空白/连字符
_NOISE_RE = re.compile(r"[（(][^）)]*(?:校对|全本|完结|精校|未删减|典藏|合集)[^）)]*[）)]|[\s\-_·]+")
# 标点：归一化时全部去掉，避免《书名》与 书名 被判成两本
_PUNCT_RE = re.compile(r"[《》【】\[\]()（）:：·,，.。!！?？'\"“”‘’]")


# ---------------- 归一化 ----------------

def norm_key(text: str) -> str:
    """归一化书名 / 作者，用于重复判定（大小写、标点、版本后缀都不影响结果）。"""
    t = (text or "").lower()
    t = _NOISE_RE.sub("", t)
    t = _PUNCT_RE.sub("", t)
    return t.strip()


# ---------------- EPUB 探测 ----------------

def _series_index_of(opf: str) -> str:
    """系列内序号：``calibre:series_index``，EPUB3 用 ``group-position`` 兜底。

    返回**字符串**（与其它元数据字段类型一致），无序号返回空串。

    两种规整是必要的：
      · Calibre 写的是 "1.00" 这种两位小数 → 规整成 "1"，否则卡片上会显示 #1.00；
      · 但**非整数序号要保留**（1.5 常表示系列里的中篇），所以不能一律取整。
    """
    for pat in (
        r'<meta[^>]+name="calibre:series_index"[^>]+content="([^"]*)"',
        r'<meta[^>]+content="([^"]*)"[^>]+name="calibre:series_index"',
        r'<meta[^>]+property="group-position"[^>]*>(.*?)</meta>',
    ):
        m = re.search(pat, opf, re.S | re.I)
        if not m:
            continue
        raw = re.sub(r"<[^>]+>", "", m.group(1)).strip()
        if not raw:
            continue
        try:
            f = float(raw)
        except ValueError:
            return raw          # 不是数字就原样返回，不丢信息
        return str(int(f)) if f == int(f) else ("%g" % f)
    return ""


def _tag_text(xml: str, tag: str) -> str:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S | re.I)
    if not m:
        return ""
    return re.sub(r"<[^>]+>", "", m.group(1)).strip()


def _series_of(opf: str) -> str:
    """系列名：兼容 calibre 与 EPUB3 的两种写法。"""
    for pat in (
        r'<meta[^>]+name="calibre:series"[^>]+content="([^"]*)"',
        r'<meta[^>]+content="([^"]*)"[^>]+name="calibre:series"',
        r'<meta[^>]+property="belongs-to-collection"[^>]*>(.*?)</meta>',
    ):
        m = re.search(pat, opf, re.S | re.I)
        if m:
            v = re.sub(r"<[^>]+>", "", m.group(1)).strip()
            if v:
                return v
    return ""


# 估算页数时的「每页字节数」。
# EPUB 没有固定页数的概念，上游的 pages 也不可能是从 EPUB 里读出来的真值，
# 因此本项目给的是**估算值**，并在接口里以 pages_source='estimate' 明确标注，
# 不假装它是权威页数。
BYTES_PER_PAGE = 2048


def _pages_in(z: zipfile.ZipFile, opf: str, opf_path: str) -> int:
    """估算页数：阅读顺序文档的**解压后字节数** ÷ BYTES_PER_PAGE。

    为什么用「解压后字节数」而不是解压出来数汉字/单词：
    zip 的中央目录里本来就记着 file_size（解压后大小），**不需要真正解压** ——
    对一个几百本的书库，逐本解压全部章节再统计字数，开销要大一到两个数量级。

    代价是它把 XHTML 标签也算进去了（标签通常占两三成），所以这个数偏小；
    但成就判定只需要一个**稳定、单调**的度量（读得越多页数越大），
    绝对值是否精确并不影响「读过 500 页」这类判定是否成立。
    """
    try:
        base = pathlib.PurePosixPath(opf_path).parent
        manifest: dict = {}
        for m in re.finditer(r"<item\b([^>]*?)/?>", opf, re.I):
            a = m.group(1)
            hm = re.search(r'href="([^"]+)"', a)
            im = re.search(r'id="([^"]+)"', a)
            tm = re.search(r'media-type="([^"]+)"', a)
            if hm and im:
                manifest[im.group(1)] = (hm.group(1), (tm.group(1) if tm else "").lower())

        total = 0
        seen: set = set()
        for sid in re.findall(r'<itemref\b[^>]*idref="([^"]+)"', opf):
            item = manifest.get(sid)
            if not item:
                continue
            href, media = item
            if not ("html" in media or href.lower().endswith((".xhtml", ".html", ".htm"))):
                continue
            p = str(base / href.split("#")[0])
            if p not in seen and p in z.namelist():
                seen.add(p)
                total += z.getinfo(p).file_size
        if total <= 0:
            return 0
        return max(1, int(round(total / BYTES_PER_PAGE)))
    except Exception:
        return 0


def _cover_usable(z: zipfile.ZipFile, cover: str) -> bool:
    """封面路径是否指向一张**可用**的图片（存在，且不是 stub）。

    「有封面」这件事现在**只由一个来源派生**：解析出来的封面路径。
    不再另跑一套「属性/文件名里含 cover」的启发式 ——
    两套独立判断会造出「说有封面，却给不出路径」这种自相矛盾的状态。
    """
    if not cover:
        return False
    # SVG 是矢量**文本**，几百字节也可能是合法封面，故不套用光栅图的最小体积阈值
    if cover.lower().endswith(".svg"):
        return True
    try:
        return z.getinfo(cover).file_size >= _COVER_MIN_BYTES
    except KeyError:
        return False


def _cover_in(z: zipfile.ZipFile, opf: str, opf_path: str) -> str:
    """在**已打开**的 zip + OPF 文本上找封面在 zip 内的路径；找不到返回空串。

    返回的是具体路径（而不只是「有没有」）—— 前端要把它渲染成图片就必须要路径。
    路径是否**可用**由 :func:`_cover_usable` 判断（可能指向 stub 图片）。

    按可靠性依次尝试（OPF 是权威来源，后面的都是兜底）：
      1. manifest 里 ``properties="cover-image"``（EPUB3 标准做法）
      2. ``<meta name="cover" content="ID">`` 指向的 manifest 条目（EPUB2 常见做法）
      3. manifest 里 id / href 含 "cover" 的图片（不少制作工具不规范）
      4. manifest 里的第一个图片
      5. zip 内文件名含 "cover" 的图片（最后兜底）
    """
    base = pathlib.PurePosixPath(opf_path).parent

    def pick(href: str) -> str:
        """href → zip 内真实路径。href 可能是 URL 编码（%20 等），故做一次解码回退。"""
        if not href:
            return ""
        p = str(base / href.split("#")[0])
        if p in z.namelist():
            return p
        alt = unquote(p)
        return alt if alt in z.namelist() else ""

    items: list = []
    for m in re.finditer(r"<item\b([^>]*?)/?>", opf, re.I):
        a = m.group(1)
        hm = re.search(r'href="([^"]+)"', a)
        im = re.search(r'id="([^"]+)"', a)
        tm = re.search(r'media-type="([^"]+)"', a)
        if hm and im:
            items.append((im.group(1), hm.group(1), (tm.group(1) if tm else "").lower(), a))

    def is_img(href: str, mt: str) -> bool:
        return mt.startswith("image/") or href.lower().endswith(_COVER_EXTS)

    # 1) EPUB3：properties="cover-image"
    for _iid, href, mt, attrs in items:
        if is_img(href, mt) and re.search(r'properties="[^"]*cover-image', attrs, re.I):
            if (p := pick(href)):
                return p

    # 2) EPUB2：<meta name="cover" content="ID">
    for mm in re.finditer(r"<meta\b([^>]*?)/?>", opf, re.I):
        a = mm.group(1)
        if not re.search(r'name="cover"', a, re.I):
            continue
        cm = re.search(r'content="([^"]+)"', a)
        if not cm:
            continue
        target = cm.group(1).strip()
        for iid, href, mt, _attrs in items:
            if iid == target and is_img(href, mt):
                if (p := pick(href)):
                    return p

    # 3) id / href 里带 cover 的图片
    for iid, href, mt, _attrs in items:
        if is_img(href, mt) and ("cover" in iid.lower() or "cover" in href.lower()):
            if (p := pick(href)):
                return p

    # 4) manifest 里的第一个图片
    for _iid, href, mt, _attrs in items:
        if is_img(href, mt):
            if (p := pick(href)):
                return p

    # 5) 最后兜底：zip 内文件名含 cover 的图片
    for n in z.namelist():
        if n.lower().endswith(_COVER_EXTS) and "cover" in n.lower():
            return n
    return ""


def cover_path(path: pathlib.Path) -> str:
    """取 EPUB 封面的 zip 内路径（自行开包，供单本书的封面接口使用）。"""
    try:
        with zipfile.ZipFile(path) as z:
            opf_path = _opf_path(z)
            if not opf_path:
                return ""
            opf = z.read(opf_path).decode("utf-8", "ignore")
            return _cover_in(z, opf, opf_path)
    except Exception:
        return ""


def _tag_all(xml: str, tag: str) -> list:
    return re.findall(rf"<{tag}[^>]*>(.*?)</{tag}>", xml, re.S | re.I)


def _year_of(opf: str) -> str:
    m = re.search(r"(\d{4})", _tag_text(opf, "dc:date"))
    return m.group(1) if m else ""


def _isbn_of(opf: str) -> str:
    for t in _tag_all(opf, "dc:identifier"):
        if re.search(r"[\dxX-]{10,17}", t):
            return re.sub(r"<[^>]+>", "", t).strip()
    return ""


def _subjects_of(opf: str) -> list:
    return [re.sub(r"<[^>]+>", "", t).strip() for t in _tag_all(opf, "dc:subject") if t.strip()]


def _book_id(name: str) -> str:
    """文件名 → 稳定短 id（用于 URL 与前端主键，避免暴露中文文件名）。

    **只用 basename**（不含系列目录）：这样把书从平铺迁进 Komga 布局
    （``三体.epub`` → ``三体/三体 #1.epub``）时 id 不变，
    进度 / 批注 / 评分 / 收藏夹等关联数据不会因为「只是挪了个目录」而断链。
    平铺时 basename 就是 name，与改动前的行为完全一致。
    """
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]


def book_id(name: str) -> str:
    """``_book_id`` 的公开别名。

    布局迁移（``fileops.apply_komga_layout``）要在移动前后各算一次 id、
    判断是否需要搬关联数据，必须与扫描用的是同一个规则 —— 所以把它公开出来，
    而不是让外部去碰私有函数。
    """
    return _book_id(name)


def _gradient(bid: str) -> tuple:
    """由 id 派生确定性 oklch 渐变（封面占位用，色相稳定）。"""
    h = int(bid[:8], 16) % 360
    return (f"oklch(0.62 0.16 {h})", f"oklch(0.48 0.13 {(h + 38) % 360})")


def _toc_entries(path: pathlib.Path) -> list:
    """抽取 EPUB 目录为 [(depth, title, abs_file), ...]（按文档顺序，文件为 zip 内绝对路径）。

    仅用 EPUB3 nav / NCX 定位标题，真正的章节顺序以 spine 为准（见 _reading_list）。
    """
    try:
        with zipfile.ZipFile(path) as z:
            opf_path = _opf_path(z)
            if not opf_path:
                return []
            opf = z.read(opf_path).decode("utf-8", "ignore")
            base = pathlib.PurePosixPath(opf_path).parent

            doc_path = None
            for mm in re.finditer(r"<item\b([^>]*)>", opf):
                attrs = mm.group(1)
                pm = re.search(r'properties="([^"]*)"', attrs)
                if pm and "nav" in pm.group(1):
                    hm = re.search(r'href="([^"]+)"', attrs)
                    if hm:
                        doc_path = str(base / hm.group(1))
                    break
            if not doc_path:
                ncx = re.search(r'<item\b([^>]*)\bmedia-type="application/x-dtbncx\+xml"', opf)
                if ncx:
                    hm = re.search(r'href="([^"]+)"', ncx.group(1))
                    if hm:
                        doc_path = str(base / hm.group(1))
            if not doc_path:
                return []
            try:
                doc = z.read(doc_path).decode("utf-8", "ignore")
            except Exception:
                return []
            doc_dir = str(pathlib.PurePosixPath(doc_path).parent)
            if "navpoint" in doc.lower():
                return _ncx_entries(doc, doc_dir)
            return _nav_entries(doc, doc_dir)
    except Exception:
        return []


def _nav_entries(doc: str, doc_dir: str) -> list:
    """EPUB3 nav → [(depth, title, abs_file), ...]（depth 从 1 起，仅收带 href 的 <a>）。"""
    nav_match = re.search(r'<nav\b[^>]*epub:type="toc"[^>]*>(.*?)</nav>', doc, re.S | re.I)
    if not nav_match:
        nav_match = re.search(r"<nav\b[^>]*>(.*?)</nav>", doc, re.S | re.I)
    if not nav_match:
        return []
    nav = nav_match.group(1)
    base = pathlib.PurePosixPath(doc_dir)
    entries: list = []

    class _NavParser(html.parser.HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth = 0
            self.href = None
            self.text = ""
            self.in_a = False

        def handle_starttag(self, tag, attrs):
            if tag in ("ul", "ol"):
                self.depth += 1
            elif tag == "a":
                self.href = dict(attrs).get("href")
                self.text = ""
                self.in_a = True

        def handle_endtag(self, tag):
            if tag in ("ul", "ol"):
                self.depth = max(0, self.depth - 1)
            elif tag == "a" and self.in_a:
                title = self.text.strip()
                f = (self.href or "").split("#")[0]
                if title and f:
                    entries.append((max(1, self.depth), title, str(base / f)))
                self.in_a = False
                self.href = None

        def handle_data(self, data):
            if self.in_a:
                self.text += data

    _NavParser().feed(nav)
    return entries


def _ncx_entries(doc: str, doc_dir: str) -> list:
    """NCX（EPUB2）→ [(depth, title, abs_file), ...]，按 navPoint 文档顺序输出。"""
    base = pathlib.PurePosixPath(doc_dir)
    nodes: list = []  # (depth, node)
    stack: list = []
    for m in re.finditer(
        r'<navPoint\b[^>]*>|</navPoint>|<text>(.*?)</text>|<content\b[^>]*?src="([^"]+)"',
        doc, re.S | re.I,
    ):
        tok = m.group(0).lower()
        if tok.startswith("<navpoint"):
            node = {"title": "", "src": ""}
            nodes.append((len(stack) + 1, node))
            stack.append(node)
        elif tok.startswith("</navpoint"):
            if stack:
                stack.pop()
        elif m.group(1) is not None and stack:
            stack[-1]["title"] = m.group(1)
        elif m.group(2) is not None and stack:
            stack[-1]["src"] = m.group(2)

    entries: list = []
    for depth, node in nodes:
        title = re.sub(r"<[^>]+>", "", node["title"]).strip()
        f = (node["src"] or "").split("#")[0]
        if title and f:
            entries.append((depth, title, str(base / f)))
    return entries


def _opf_path(z: zipfile.ZipFile) -> str:
    """从 container.xml 解析 OPF 路径；找不到时退化为首个 .opf。"""
    try:
        container = z.read("META-INF/container.xml").decode("utf-8", "ignore")
        m = re.search(r'full-path="([^"]+)"', container)
        if m:
            return m.group(1)
    except Exception:
        pass
    names = [n for n in z.namelist() if n.lower().endswith(".opf")]
    return names[0] if names else ""


def _spine(path: pathlib.Path) -> list:
    """返回阅读顺序的 XHTML 文档在 zip 内的路径列表（已解析为 OPF 相对路径）。"""
    try:
        with zipfile.ZipFile(path) as z:
            opf_path = _opf_path(z)
            if not opf_path:
                return []
            opf = z.read(opf_path).decode("utf-8", "ignore")
            base = pathlib.PurePosixPath(opf_path).parent
            manifest = {}
            for m in re.finditer(r'<item\b([^>]*)/>', opf):
                a = m.group(1)
                hm = re.search(r'href="([^"]+)"', a)
                im = re.search(r'id="([^"]+)"', a)
                tm = re.search(r'media-type="([^"]+)"', a)
                if hm and im:
                    manifest[im.group(1)] = (hm.group(1), tm.group(1) if tm else "")
            out = []
            for sid in re.findall(r'<itemref\b[^>]*idref="([^"]+)"', opf):
                if sid in manifest:
                    href, mt = manifest[sid]
                    if "html" in mt or href.lower().endswith((".xhtml", ".html", ".htm")):
                        out.append(str(base / href))
            return out
    except Exception:
        return []


def _flat_volume(indexes, title_at) -> dict:
    return {
        "volume": "",
        "chapters": [
            {"num": j + 1, "title": title_at(i), "index": i} for j, i in enumerate(indexes)
        ],
    }


def _reading_list(path: pathlib.Path) -> list:
    """阅读顺序（对齐 spine）的卷-章结构；章标题优先取目录（按文件精确对齐）。

    spine 决定章节顺序与 index（阅读器据此加载正文），目录仅提供标题/卷层级，
    因此目录条目数与 spine 不一致时也能正确套用（封面、版权页等多出的条目不会错位）。
    """
    spine = _spine(path)
    n = len(spine)
    if not n:
        return []

    titled: dict = {}
    depth_of: dict = {}
    for d, t, f in _toc_entries(path):
        if f not in titled:
            titled[f] = t
            depth_of[f] = d

    def title_at(i: int) -> str:
        return titled.get(spine[i]) or f"第 {i + 1} 章"

    mapped = [i for i in range(n) if spine[i] in depth_of]
    if not mapped:
        return [_flat_volume(range(n), title_at)]

    min_depth = min(depth_of[spine[i]] for i in mapped)
    # 「卷容器」：某最浅层条目之后、下一个同级条目之前存在更深层条目
    containers = set()
    for k, i in enumerate(mapped):
        if depth_of[spine[i]] != min_depth:
            continue
        for j in mapped[k + 1:]:
            dj = depth_of[spine[j]]
            if dj > min_depth:
                containers.add(i)
                break
            if dj <= min_depth:
                break

    if not containers:
        return [_flat_volume(range(n), title_at)]

    volumes: list = []
    cur = None
    for i in range(n):
        if i in containers:
            cur = {"volume": titled.get(spine[i], ""), "chapters": []}
            volumes.append(cur)
        else:
            if cur is None:
                cur = {"volume": "", "chapters": []}
                volumes.append(cur)
            cur["chapters"].append(
                {"num": len(cur["chapters"]) + 1, "title": title_at(i), "index": i}
            )
    return volumes


def _body_of(doc: str) -> str:
    m = re.search(r"<body[^>]*>(.*)</body>", doc, re.S | re.I)
    return m.group(1) if m else doc


def _rewrite_assets(html: str, media: str, bid: str) -> str:
    """把章节内相对资源（图片 / 链接）改写为后端 asset 接口，跨 zip 取回。"""
    base = pathlib.PurePosixPath(media).parent

    def fix(m: "re.Match") -> str:
        attr, val = m.group(1), m.group(2)
        if re.match(r"^[a-z]+:", val, re.I) or val.startswith("#") or val.startswith("data:"):
            return m.group(0)
        try:
            resolved = str(base / val)
        except Exception:
            return m.group(0)
        return f'{attr}="/api/books/{bid}/asset?p={quote(resolved)}"'

    return re.sub(r'(src|href)="([^"]+)"', fix, html, flags=re.I)


def chapter_html(path: pathlib.Path, index: int, bid: str) -> dict:
    """抽取单章 XHTML 正文（body），资源 URL 已改写为后端接口。"""
    spine = _spine(path)
    if index < 0 or index >= len(spine):
        raise IndexError("章节不存在")
    media = spine[index]
    with zipfile.ZipFile(path) as z:
        raw = z.read(media).decode("utf-8", "ignore")
    html = _rewrite_assets(_body_of(raw), media, bid)
    title = pathlib.PurePosixPath(media).name
    return {"index": index, "total": len(spine), "title": title, "html": html}


def by_id(bid: str) -> "dict | None":
    for b in books():
        if b["id"] == bid:
            return b
    return None


def series_list() -> list:
    """按系列聚合：[{name, count, books:[BookCard, ...]}]，按册数降序。"""
    bucket: dict = {}
    for b in books():
        s = (b.get("series") or "").strip()
        if s:
            bucket.setdefault(s, []).append(b)
    return [
        {"name": name, "count": len(items), "books": items}
        for name, items in sorted(bucket.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]


def series_books(name: str) -> list:
    """某系列下的书目（保持扫描顺序）。"""
    return [b for b in books() if (b.get("series") or "").strip() == name]


def authors_list() -> list:
    """按作者聚合：[{name, count, books:[BookCard, ...]}]，按册数降序。"""
    bucket: dict = {}
    for b in books():
        a = (b.get("author") or "").strip()
        if a:
            bucket.setdefault(a, []).append(b)
    return [
        {"name": name, "count": len(items), "books": items}
        for name, items in sorted(bucket.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]


def author_books(name: str) -> list:
    """某作者名下的书目（保持扫描顺序）。"""
    return [b for b in books() if (b.get("author") or "").strip() == name]


def library_groups() -> list:
    """「库」的真实分组：按文件格式，外加元数据维度的「待修复 / 无封面」。

    本项目生成的 EPUB 不含 dc:subject，故不用内容标签分类；
    格式与 problem 标记始终可用，是最可靠的区分维度。
    key 形如 ``fmt:EPUB`` / ``issues:1`` / ``nocover:1``，前端据此筛选。
    """
    bs = books()
    fmt: dict = {}
    for b in bs:
        f = (b.get("format") or "?").upper()
        fmt[f] = fmt.get(f, 0) + 1
    groups = [
        {"key": f"fmt:{k}", "label": k, "count": v, "kind": "format"}
        for k, v in sorted(fmt.items(), key=lambda kv: (-kv[1], kv[0]))
    ]
    issues = [b for b in bs if b.get("issues")]
    if issues:
        groups.append({"key": "issues:1", "label": "待修复", "count": len(issues), "kind": "issues"})
    nocover = [b for b in bs if (b.get("format") or "").upper() == "EPUB" and not b.get("has_cover")]
    if nocover:
        groups.append({"key": "nocover:1", "label": "无封面", "count": len(nocover), "kind": "nocover"})
    return groups


def probe_epub(path: pathlib.Path) -> dict:
    """读 EPUB 容器内的 OPF，取书名 / 作者 / 系列，并判断有没有封面。

    任何失败都**不抛异常**，而是折算成 ``issues`` 里的 ``unparsable`` ——
    这个函数同时是「缺失资源」工具的判定依据，必须容错。
    """
    out = {
        "title": "", "author": "", "series": "", "has_cover": False, "unparsable": False,
        "year": "", "publisher": "", "isbn": "", "language": "", "description": "", "tags": [],
        "cover": "", "pages": 0, "pages_source": "", "series_index": "",
    }
    try:
        with zipfile.ZipFile(path) as z:
            opf_path = ""
            try:
                container = z.read("META-INF/container.xml").decode("utf-8", "ignore")
                m = re.search(r'full-path="([^"]+)"', container)
                if m:
                    opf_path = m.group(1)
            except Exception:
                opf_path = ""
            if not opf_path:
                names = [n for n in z.namelist() if n.lower().endswith(".opf")]
                if not names:
                    out["unparsable"] = True
                    return out
                opf_path = names[0]
            opf = z.read(opf_path).decode("utf-8", "ignore")
            out["title"] = _tag_text(opf, "dc:title")
            out["author"] = _tag_text(opf, "dc:creator")
            out["series"] = _series_of(opf)
            out["series_index"] = _series_index_of(opf)
            # 复用已打开的 zip，不再二次解包
            out["cover"] = _cover_in(z, opf, opf_path)
            out["has_cover"] = _cover_usable(z, out["cover"])
            if not out["has_cover"]:
                # 无效 / 缺失封面：连路径一起清掉，避免前端去请求一张注定解不开的图
                out["cover"] = ""
            out["year"] = _year_of(opf)
            out["publisher"] = _tag_text(opf, "dc:publisher")
            out["isbn"] = _isbn_of(opf)
            out["language"] = _tag_text(opf, "dc:language")
            out["description"] = _tag_text(opf, "dc:description")
            out["tags"] = _subjects_of(opf)
            out["pages"] = _pages_in(z, opf, opf_path)
            if out["pages"]:
                out["pages_source"] = "estimate"
    except Exception:
        out["unparsable"] = True
    return out


# ---------------- 扫描 ----------------
# Komga 布局是「一层系列目录 + 书文件」（core/komga.py），所以扫描要跟着下探一层。
# **只下一层**：Komga 自己也不递归系列目录的子目录，再深只会扫到它不认的文件。

def _iter_book_files(d: pathlib.Path) -> list:
    """OUTPUT_DIR 下的书文件（平铺 + 一层系列目录），按遍历顺序返回。

    `_scan_once` 与 `_dir_signature` 共用它，保证「扫到哪些」与「什么变化会让缓存失效」
    永远一致 —— 这两处若各写一套，很容易出现「新书已入库但列表还是旧的」。
    """
    out: list = []
    try:
        entries = sorted(d.iterdir())
    except Exception:
        return out
    for f in entries:
        if f.is_file():
            if f.suffix.lower() in BOOK_EXTS:
                out.append(f)
            continue
        if f.is_dir() and not f.name.startswith("."):
            try:
                out.extend(sorted(
                    x for x in f.iterdir()
                    if x.is_file() and x.suffix.lower() in BOOK_EXTS
                ))
            except Exception:
                continue
    return out


def _dir_signature(d: pathlib.Path) -> tuple:
    """目录指纹：书文件数 + 最新 mtime（含一层系列目录）。任一变化即让缓存失效。"""
    n, newest = 0, 0.0
    for f in _iter_book_files(d):
        n += 1
        try:
            m = f.stat().st_mtime
            if m > newest:
                newest = m
        except OSError:
            pass
    return (n, round(newest, 3))


def _scan_once() -> list:
    d = config.OUTPUT_DIR
    books = []
    for f in _iter_book_files(d):
        try:
            st = f.stat()
        except OSError:
            continue

        name_meta = metadata.from_filename(f.name)
        info = {
            "title": "", "author": "", "series": "", "has_cover": False, "unparsable": False,
            "year": "", "publisher": "", "isbn": "", "language": "", "description": "", "tags": [],
            "cover": "", "pages": 0, "pages_source": "", "series_index": "",
        }
        if f.suffix.lower() == ".epub":
            info = probe_epub(f)
        elif f.suffix.lower() == ".cbz":
            # 漫画：页数与封面都是**真实值**（不是估算），pages_source = "archive"
            info.update(comics.probe(f))

        issues = []
        if st.st_size == 0:
            issues.append("zero-bytes")
        if info["unparsable"]:
            issues.append("unparsable")
        elif not info["has_cover"] and f.suffix.lower() == ".epub":
            issues.append("no-cover")
        elif f.suffix.lower() != ".epub":
            # 非 EPUB（mobi/pdf/txt）本项目不会去解析封面，不计为缺失
            pass

        # 相对路径（Komga 布局下形如 "系列/书.epub"，平铺时就是文件名）；
        # id 由 basename 派生（见 _book_id），所以挪进系列目录不会换 id
        rel = f.relative_to(d).as_posix()
        bid = _book_id(rel)
        c1, c2 = _gradient(bid)
        books.append({
            "id": bid,
            "name": rel,
            "size": st.st_size,
            "mtime": st.st_mtime,
            "format": f.suffix.lstrip(".").upper(),
            "title": info["title"] or name_meta["title"],
            "author": info["author"] or name_meta["author"],
            "series": info["series"],
            # 系列内序号（字符串，空串 = 无）。解析见 _series_index_of
            "series_index": info.get("series_index", ""),
            "has_cover": info["has_cover"],
            # 封面在 zip 内的路径（空串 = 没有）。前端据此拼 /api/books/{id}/cover
            "cover": info.get("cover", ""),
            # 页数：**估算值**（见 _pages_in），pages_source 恒为 "estimate"；
            # 非 EPUB 恒为 0，前端据此不显示页数而不是显示 0 页
            "pages": info.get("pages", 0),
            "pages_source": info.get("pages_source", ""),
            "year": info.get("year", ""),
            "publisher": info.get("publisher", ""),
            "isbn": info.get("isbn", ""),
            "language": info.get("language", ""),
            "description": info.get("description", ""),
            "tags": info.get("tags", []),
            "c1": c1,
            "c2": c2,
            "issues": issues,
        })
    return books


def books(force: bool = False) -> list:
    """导出目录里的书目列表（带短期缓存）。"""
    d = config.OUTPUT_DIR
    sig = _dir_signature(d)
    with _lock:
        fresh = _cache["sig"] == sig and (time.time() - _cache["at"]) < _CACHE_TTL
        if fresh and not force:
            return _cache["books"]

    result = _scan_once()
    with _lock:
        _cache.update({"at": time.time(), "sig": sig, "books": result})
    return result


def invalidate() -> None:
    """让缓存立即失效（任何改文件的操作之后都要调）。"""
    with _lock:
        _cache.update({"at": 0.0, "sig": None, "books": []})


def export_rows() -> list:
    """书目元数据的平铺行（CSV 导出用）。

    只含**文件派生**的字段。阅读进度 / 状态 / 评分在 SQLite 里，
    由接口层合并 —— library 刻意不 import db，保持依赖单向（文件层 ↑ 数据层）。
    """
    rows = []
    for b in books():
        rows.append({
            "id": b.get("id") or "",
            "title": b.get("title") or "",
            "name": b.get("name") or "",
            "author": b.get("author") or "",
            "series": b.get("series") or "",
            "series_index": str(b.get("series_index") or ""),
            "format": b.get("format") or "",
            "size": int(b.get("size") or 0),
            "year": str(b.get("year") or ""),
            "publisher": b.get("publisher") or "",
            "language": b.get("language") or "",
            "isbn": b.get("isbn") or "",
            "tags": "、".join(b.get("tags") or []),
            "added": time.strftime("%Y-%m-%d", time.localtime(b.get("mtime") or 0)),
        })
    return rows


def find(name: str) -> dict | None:
    for b in books():
        if b["name"] == name:
            return b
    return None


def book_detail(name: str) -> dict | None:
    """单本详情：基础元数据 + 真实章节树 + 同 stem 的成品文件列表。"""
    b = find(name)
    if not b:
        return None
    path = config.OUTPUT_DIR / name
    chapters = _reading_list(path) if path.suffix.lower() == ".epub" else []
    stem = path.stem
    files = []
    try:
        # 同 stem 的其它格式（epub/mobi/azw3）只在**同一个目录**里找：
        # Komga 布局下同系列的书都躺在系列目录内，跨目录去找会串到别的系列
        for f in sorted(path.parent.iterdir()):
            if f.is_file() and f.stem == stem:
                files.append({
                    "name": f.relative_to(config.OUTPUT_DIR).as_posix(),
                    "format": f.suffix.lstrip(".").upper() or "?",
                    "size": f.stat().st_size,
                    "mtime": f.stat().st_mtime,
                })
    except Exception:
        pass
    detail = dict(b)
    detail["chapters"] = chapters
    detail["files"] = files
    return detail


# ---------------- 聚合 ----------------

def entities(kind: str) -> dict:
    """按作者或系列聚合：``{type, items: [{name, count, books}]}``。"""
    field = "author" if kind == "author" else "series"
    bucket: dict = {}
    for b in books():
        key = (b.get(field) or "").strip()
        if not key:
            continue
        bucket.setdefault(key, []).append(b["name"])
    items = [
        {"name": k, "count": len(v), "books": v}
        for k, v in sorted(bucket.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    return {"type": kind, "items": items, "total": len(books())}


def duplicate_groups(threshold: int = 85) -> dict:
    """重复书目分组：**归一化后同作者 + 书名相似度 ≥ threshold**。

    与上游 Calibre 的「Similar-title threshold」同口径（默认 85%）：
      · 作者必须一致（归一化后完全相同）—— 同名不同作者的书不是重复；
      · 书名用 difflib 相似度比较，阈值可调：调低抓更多近似（含「XX 第2版」这类），
        调高只留几乎全同的；
      · 没有作者的书只在同样缺作者的书之间互比，避免把一堆「佚名」混作一组。

    聚类用并查集单链法：A~B、B~C 达标会把 A、B、C 并成一组（传递闭包），
    这与「人工看重复」的直觉一致 —— 中间那本把两头的书连起来了。
    """
    from difflib import SequenceMatcher

    try:
        threshold = max(50, min(int(threshold), 100))
    except (TypeError, ValueError):
        threshold = 85
    thr = threshold / 100.0

    bs = books()
    by_author: dict = {}
    for b in bs:
        t = norm_key(b["title"])
        if not t:
            continue
        by_author.setdefault(norm_key(b["author"]), []).append((b, t))

    groups = []
    for akey, items in by_author.items():
        n = len(items)
        if n < 2:
            continue
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for i in range(n):
            for j in range(i + 1, n):
                ti, tj = items[i][1], items[j][1]
                # 便宜预筛：ratio = 2M/(lenA+lenB) 且 M ≤ min，故 ratio ≤ 2*min/(min+max)。
                # 由此得必要条件 max/min ≤ (2-thr)/thr —— 超过它相似度**数学上不可能**达标。
                # ⚠️ 不能用「长度差占比」(lenA-lenB)/max：那不是有效下界
                #    （"abc"/"abcd" 长度差 25%，相似度仍有 0.857，会被误杀）。
                lo, hi = (len(ti), len(tj)) if len(ti) <= len(tj) else (len(tj), len(ti))
                if not lo or hi / lo > (2 - thr) / thr:
                    continue
                if SequenceMatcher(None, ti, tj).ratio() >= thr:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[rj] = ri

        clusters: dict = {}
        for idx in range(n):
            clusters.setdefault(find(idx), []).append(items[idx])

        for members in clusters.values():
            if len(members) < 2:
                continue
            ms = [m[0] for m in members]
            # 组内最小相似度 = 这组「最不像的一对」，是判定强度最诚实的体现
            sims = [
                SequenceMatcher(None, members[i][1], members[j][1]).ratio()
                for i in range(len(members)) for j in range(i + 1, len(members))
            ]
            exact = len({m[1] for m in members}) == 1
            groups.append({
                "key": f"{akey}|{ms[0]['id']}",
                "reason": (f"书名与作者完全相同" if exact
                           else f"同作者 · 书名相似度 ≥ {threshold}%"),
                "similarity": round(min(sims) * 100) if sims else 100,
                "title": ms[0]["title"],
                "author": ms[0]["author"],
                "items": [
                    {"name": i["name"], "size": i["size"], "mtime": i["mtime"], "format": i["format"]}
                    for i in ms
                ],
            })
    groups.sort(key=lambda g: (-len(g["items"]), -g["similarity"]))
    return {"groups": groups, "total": len(bs), "threshold": threshold}


def missing_items() -> dict:
    """有问题的条目：零字节 / 无法解析 / 缺封面。"""
    items = [
        {"name": b["name"], "size": b["size"], "mtime": b["mtime"], "issues": b["issues"]}
        for b in books() if b["issues"]
    ]
    return {"items": items, "total": len(books())}
