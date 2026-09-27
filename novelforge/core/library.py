"""书目库：扫描导出目录并聚合出工具页需要的真实数据。

后端没有「图书库」实体 —— 唯一的真实「书」就是 ``OUTPUT_DIR`` 里的成品文件。
所以这里以「扫目录 + 读元数据」的方式聚合出**书目 / 作者 / 系列**，并在此之上
做**重复分组**与**缺失检测**，供工具页的四个工具消费：

- 实体管理     → :func:`entities`
- 重复书籍     → :func:`duplicate_groups`
- 缺失资源     → :func:`missing_items`
- 命名规则     → 只读 :func:`books`；预览 / 重出版副本见 ``core/scrape.plan_naming``
                （第 28 期起改名只改硬链接副本，源文件名不再有任何入口可改）

EPUB 解析是 IO 密集（要解开 zip 读 OPF）。**第 62 期起书目落库**（``core/catalog``）：
进程内 TTL 5 秒 + 目录指纹那套缓存整个删掉了 —— 它的致命处在「先算指纹再查缓存」，
于是**缓存命中也要付一次全目录 stat**，而未命中时在锁外全量重扫、还没有单飞
（线上 266 本书 = 42 秒/请求，见 ``catalog`` 模块文档）。现在请求路径只读一张表，
扫盘交给后台增量刷新；写操作后仍调 :func:`invalidate`，但它的语义已从
「清空扫描缓存」变成「标脏，下次读时增量刷一次」。
"""
from __future__ import annotations

import fnmatch
import hashlib
import html.parser
import json
import os
import pathlib
from urllib.parse import quote, unquote
import re
import stat
import threading
import time
import uuid
import zipfile

from .. import config
from . import audio, audio_meta, comics, db, metadata

# 只把这些扩展名当成「书」；与 /api/files 的全量列表不同，这里是有意收窄的。
# .cbr（RAR 漫画）自第 9 期起在列 —— 由 core/comics.py 的 zip/rar 双后端解压。
# 单个音频文件也算一本书；「音频目录」（一章一文件）由 _iter_book_entries 单独识别。
BOOK_EXTS = (".epub", ".mobi", ".azw3", ".pdf", ".txt", ".cbz", ".cbr", *audio.AUDIO_EXTS)

# 可能作为封面出现的图片扩展名
_COVER_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg")

# 小于这个字节数的「封面」一律视为无效。
# 实测遇到过 14 字节的 stub JPEG（只有 SOI + APP0/JFIF + EOI，没有任何图像数据）——
# 扩展名和 magic bytes 都对，接口也照常返回 200，但浏览器解码必然失败。
# 这类书如果算作「有封面」，就会从「无封面」分组里消失，用户根本找不到它们。
_COVER_MIN_BYTES = 1024

_lock = threading.RLock()

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


def _fixed_layout_of(opf: str) -> bool:
    """EPUB 是不是**固定版式**（pre-paginated）。

    固定版式的书每一页是**已经排好版的整页**（常见实现是整页 SVG / 绝对定位），
    字号 / 行高 / 首行缩进这类重排设置对它没有意义，页宽也由书本身决定。
    阅读器据此**不套用重排偏好、不改页宽**，否则会把整页排版揉烂。

    **只认显式声明**：读不到就当可重排（reflowable），不靠「有没有 SVG」这类特征猜 ——
    猜错会让一本正常的书被夺走排版设置，比不做判定更糟。

    三种写法都认，因为它们在真实书里都出现过：
    - EPUB3 正式写法：``<meta property="rendition:layout">pre-paginated</meta>``
    - EPUB3 属性写法：``<meta property="rendition:layout" content="pre-paginated"/>``
    - 早期 Apple 固定版式约定：``<meta name="fixed-layout" content="true"/>``
    """
    for m in re.finditer(r"<meta\b[^>]*>", opf, re.I):
        tag = m.group(0)
        key = re.search(r'(?:property|name)="([^"]*)"', tag, re.I)
        if not key:
            continue
        if key.group(1).strip().lower() not in ("rendition:layout", "fixed-layout"):
            continue
        cm = re.search(r'content="([^"]*)"', tag, re.I)
        if cm:
            val = cm.group(1)
        else:
            # 值也可以写在标签体内（EPUB3 的 property 写法允许）
            body = re.match(r"\s*([^<]*)", opf[m.end():])
            val = body.group(1) if body else ""
        if val.strip().lower() in ("pre-paginated", "true"):
            return True
    return False


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
    """从 ``dc:identifier`` 里挑 ISBN，返回**原始文本**（保留连字符等写法）。

    ⚠️ 形状判定走 ``metadata.isbn_digits``（唯一真值源，与 ``fileops._set_isbn`` 同一处）。
    这里原先用的是 `[\\dxX-]{10,17}` 的**子串**匹配，会把 UUID 当 ISBN —— 见该函数的注释。
    """
    for t in _tag_all(opf, "dc:identifier"):
        if metadata.isbn_digits(t):
            return re.sub(r"<[^>]+>", "", t).strip()
    return ""


def _subjects_of(opf: str) -> list:
    return [re.sub(r"<[^>]+>", "", t).strip() for t in _tag_all(opf, "dc:subject") if t.strip()]


def _book_id(name: str, library_id: str = None) -> str:
    """文件名 → 稳定短 id（用于 URL 与前端主键，避免暴露中文文件名）。

    **只用 basename**（不含系列目录）：这样把书从平铺迁进 Komga 布局
    （``三体.epub`` → ``三体/三体 #1.epub``）时 id 不变，
    进度 / 批注 / 评分 / 收藏夹等关联数据不会因为「只是挪了个目录」而断链。
    平铺时 basename 就是 name，与改动前的行为完全一致。

    **库维度（第 17 期）**：给定 ``library_id`` 时，id 形如 ``库$哈希``，
    让「A 库有三体.epub、B 库也有」得到**两个不同 id**，进度 / 批注互不串；
    不传则退化成纯哈希（旧行为，仅供一次性迁移按旧 id 反查关联行）。
    分隔符用 ``$``（URL 安全、且非 ``/``，``server._MEDIA_TOKEN_PATHS``
    的 ``[^/]+`` 仍整段匹配）；新 id 不再是纯十六进制，故取色相请用哈希而非 ``bid[:8]``。
    """
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    h = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
    if library_id:
        return f"{library_id}${h}"
    return h


def book_id(name: str, library_id: str = None) -> str:
    """``_book_id`` 的公开别名。

    布局迁移（``fileops.apply_komga_layout`` / ``apply_conflict_rename``）、
    扫描、元数据写回都要传 ``library_id``，保证算出的 id 与「库维度」规则一致 ——
    否则跨库同名会串 id。
    """
    return _book_id(name, library_id)


def _gradient(bid: str) -> tuple:
    """由 id 派生确定性 oklch 渐变（封面占位用，色相稳定）。

    第 17 期起 book_id 不再是纯十六进制（形如 ``库$哈希``），故改用完整 id 的
    SHA1 取色相，避免 ``int(bid[:8], 16)`` 因非十六进制字符抛错。
    """
    h = int(hashlib.sha1(bid.encode("utf-8")).hexdigest()[:8], 16) % 360
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


class BookIdConflict(RuntimeError):
    """同一 ``book_id`` 命中多本（跨库 / 库内同名同扩展）。

    单独一个类型是为了让服务层能把它翻成**可读的 409 + 修复入口**，而不是让
    详情页 / 阅读进度接口整体 500（第 13 期「冲突可见而非整页报错」）。
    继承 ``RuntimeError``：既有把 ``RuntimeError`` 当兜底的调用方行为不变。
    """


def by_id(bid: str) -> "dict | None":
    """按 id 取书。

    多库下同一 id 可能命中多本（跨库 / 库内**同名同扩展**）—— 此时**显式报错**，不静默取第一条，
    否则进度 / 批注会写到错的书上。

    ⚠️ 入库侧的冲突拦截是**第 13 期才补上**的（此前只有迁移侧会拦），所以老库里完全可能
    已经躺着这种数据 —— 旧注释写的「入库与迁移都已拦掉」与实况不符。命中时抛
    :class:`BookIdConflict`（是 ``RuntimeError`` 的子类，原有 except 不受影响），
    提示语直接指向修复入口。

    ⚠️ 第 62 期起走 ``catalog.find_by_id``（**带索引的一条 SELECT**，不是全库扫描）。
    改造前这里是 `[b for b in books() if b["id"] == bid]` —— 而 `books()` 会扫全部库，
    于是**书架一屏 30 本 = 30 次全库扫描**，封面接口叠加起来就是线上那份 42 秒。
    两条语义（多命中抛冲突、只认在册的库）在 catalog 里原样保留，见其文档。
    """
    from . import catalog
    return catalog.find_by_id(bid)


def by_id_raw(bid: str) -> "dict | None":
    """按 id 取书，**不过服务端元数据覆盖层** —— 「文件里原本是什么」。

    只给需要「原值」的少数调用方用（目前是 ``metastore``）：卡片上的字段是
    **生效值**（override > online > opf），拿它当 OPF 原值会让「与文件原值不同才写」
    这类判据恒为假。详见 :func:`catalog.raw_book`。

    命中多本（``BookIdConflict`` 那种）时返回 None，与 :func:`by_id` 的抛异常不同：
    这个入口是**取值**不是取书，拿不到交给调用方退回卡片即可。
    """
    from . import catalog
    return catalog.raw_book(bid)


# ---------------- 同名冲突（book_id 撞车）----------------

def id_conflicts() -> list:
    """**同名冲突**清单：按 ``book_id`` 聚合，只留命中多本的组。

    ``book_id`` 由 basename 派生（见 :func:`book_id`），所以「A 库有三体.epub、
    B 库也有三体.epub」会撞上**同一个 id** —— 进度 / 批注 / 评分只有一份，
    打开哪一本都说不清（``by_id`` 会直接抛 :class:`BookIdConflict`）。这里按 id
    分组把它显式列出来，交给工具页一键改名修复。

    - ``cross_library`` 为真 = **跨库**冲突（多书库下最该被注意的情形，新产生的会被
      入库侧拦掉，见 ``core/library_rules.resolve_target``）；
    - 库内的同名（同一库里两个系列目录下同名）同样会撞 id，也一并列出；
    - ``items[0]`` 是**保留项**（扫描顺序 = 库序 + 目录序，确定性），其余是需要改名的；
    - 每个**待改名**项带 ``suggest``（界面据此直接给出「改名为此」的默认值，
      省掉前端自己算一套 —— 口径只有 ``suggest_name`` 一处）。

    O(n) 一次分组，不做两两比对。
    """
    bucket: dict = {}
    for b in books():
        bid = str(b.get("id") or "")
        if bid:
            bucket.setdefault(bid, []).append(b)
    name_of_lib = {str(l.get("id")): str(l.get("name") or "") for l in libraries()}
    out = []
    for bid, items in bucket.items():
        if len(items) < 2:
            continue
        libs = sorted({str(b.get("library_id") or "") for b in items})
        rows = []
        for i, b in enumerate(items):
            keep = i == 0
            rows.append({
                "name": b["name"],
                "library_id": b.get("library_id"),
                "library_name": name_of_lib.get(str(b.get("library_id") or ""), ""),
                "format": b.get("format") or "",
                "size": b.get("size") or 0,
                "mtime": b.get("mtime") or 0,
                "keep": keep,
                # 建议名只给**要改名**的那些（保留项不动）；文案与迁移侧同口径
                "suggest": "" if keep else suggest_name(b["name"], b.get("library_id"),
                                                        root_of(b)),
            })
        out.append({
            "id": bid,
            "name": items[0]["name"],
            "title": items[0].get("title") or items[0]["name"],
            "cross_library": len(libs) > 1,
            "library_count": len(libs),
            "keep": items[0]["name"],
            # 组级默认建议名 = 第一个待改名项的建议名（界面「一键」用它打底）
            "suggest": rows[1]["suggest"] if len(rows) > 1 else "",
            "items": rows,
        })
    # 跨库的排前面；组内书多的排前面；同档按名字稳定排序
    out.sort(key=lambda g: (not g["cross_library"], -len(g["items"]), g["name"]))
    return out


def id_conflict_with(name: str, library_id=None) -> "dict | None":
    """``name`` 即将入库时，是否已存在**同 id 且不同路径**的书（入库冲突判据）。

    第 17 期起 ``book_id`` 是「库$哈希」：跨库同名得到不同 id，天然不冲突；
    真正会撞的是**同库内不同路径的同名书**（``科幻/三体.epub`` 与 ``三体.epub``
    同 basename → 同 id），那才会让 ``by_id`` 抛 ``BookIdConflict``，必须拦。

    判定口径：存在一本书 ``b`` 满足 ``b.id == book_id(name, library_id)``
    且 ``b.name != name``。同路径（``b.name == name``）= 重新投递一版、覆盖即可，放行。
    """
    bid = book_id(name, library_id)
    if not bid:
        return None
    for b in books():
        if b.get("id") == bid and str(b.get("name") or "") != str(name):
            return b
    return None


def suggest_name(name: str, library_id=None, root=None) -> str:
    """给 ``name`` 找一个「不撞 id、目标目录里也不存在」的候选名。

    文案与迁移侧同一套（``三体 (2).epub``，见 ``core.migrate._suggest_name``）；
    这里**只建议、不自动改** —— 改名会换 ``book_id``，必须显式确认后走冲突修复
    流程（它会把关联数据一起搬，见 ``db.remap_book_id``）。
    """
    p = pathlib.PurePosixPath(str(name))
    stem, suffix, parent = p.stem, p.suffix, str(p.parent)
    for i in range(2, 100):
        cand = f"{stem} ({i}){suffix}"
        rel = cand if parent in ("", ".") else f"{parent}/{cand}"
        if root is not None and (pathlib.Path(root) / rel).exists():
            continue
        if id_conflict_with(rel, library_id) is not None:
            continue
        return rel
    return f"{stem} ({uuid.uuid4().hex[:6]}){suffix}"


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


def series_gaps(name: str) -> dict:
    """按 ``calibre:series_index`` 找出该系列**缺失的册号**（第 43 期）。

    判据（**唯一真值源**，前端不再自己算）：
      · 只对**数字序号**判定：把各册 ``series_index`` 解析成整数集合，取 ``[1..max]``
        上的补集 —— 中间空洞与尾部缺口都算（上游 series-gaps 的语义）；
      · **无序号**（空串）在 ``unnumbered`` 单独计数，**不**并入缺册：否则每本没序号的书
        都会凭空造出一个「缺 1」；
      · **非数字 / 非整数序号**（如 ``"特典"``、``"1.5"``）在 ``non_numeric`` 单独计数，
        同样不参与数字补集（不硬猜它在第几册）。

    返回 ``{missing, max_index, numbered, unnumbered, has_unnumbered,
    non_numeric, has_non_numeric, total}``。
    """
    bs = series_books(name)
    nums: set = set()
    unnumbered = 0
    non_numeric = 0
    for b in bs:
        raw = str(b.get("series_index") or "").strip()
        if not raw:
            unnumbered += 1
            continue
        try:
            f = float(raw)
        except ValueError:
            non_numeric += 1
            continue
        if f == int(f) and f >= 1:
            nums.add(int(f))
        else:
            non_numeric += 1
    mx = max(nums) if nums else 0
    missing = [i for i in range(1, mx + 1) if i not in nums]
    return {
        "missing": missing,
        "max_index": mx,
        "numbered": len(nums),
        "unnumbered": unnumbered,
        "has_unnumbered": unnumbered > 0,
        "non_numeric": non_numeric,
        "has_non_numeric": non_numeric > 0,
        "total": len(bs),
    }


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


def narrators_list() -> list:
    """按演播者聚合：[{name, count, books:[BookCard, ...]}]，按册数降序（第 53 期，镜像 authors_list）。"""
    bucket: dict = {}
    for b in books():
        for n in (b.get("narrators") or []):
            n = str(n or "").strip()
            if n:
                bucket.setdefault(n, []).append(b)
    return [
        {"name": name, "count": len(items), "books": items}
        for name, items in sorted(bucket.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]


def narrator_books(name: str) -> list:
    """某演播者名下的书目（保持扫描顺序，第 53 期，镜像 author_books）。"""
    name = (name or "").strip()
    return [b for b in books() if name in [str(x or "").strip() for x in (b.get("narrators") or [])]]


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
        "cover": "", "pages": 0, "pages_source": "", "series_index": "", "fixed_layout": False,
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
            out["fixed_layout"] = _fixed_layout_of(opf)
            out["pages"] = _pages_in(z, opf, opf_path)
            if out["pages"]:
                out["pages_source"] = "estimate"
    except Exception:
        out["unparsable"] = True
    return out


# ---------------- 扫描 ----------------
# Komga 布局是「一层系列目录 + 书文件」（core/komga.py），所以扫描要跟着下探一层。
# **只下一层**：Komga 自己也不递归系列目录的子目录，再深只会扫到它不认的文件。

def _iter_book_entries(d: pathlib.Path, exts=None, exclude=None) -> list:
    """**一个书库根目录**下的书目条目（平铺 + 一层系列目录），按遍历顺序返回。

    条目有两种形态，二者都算「一本书」：
    - **文件**：``suffix in exts`` 的电子书 / 漫画 / **单个音频文件**；
    - **目录**：含音频文件的目录（有声书多轨，「一章一文件」）。

    ``exts`` 按**库类型**收窄白名单（漫画库只收 `.cbz/.cbr`、有声书库只收音频…），
    不传则用全量 ``BOOK_EXTS``。音频目录的识别也随之收窄：白名单里没有音频扩展名时
    不再把目录当有声书。

    ``exclude`` 是该库的**排除图案**（第 40 期，语义见 :func:`_excluded`）：命中的条目
    直接跳过，连进都不进书目。它的判据与白名单**正交** —— 白名单管「哪些格式要」，
    排除图案管「这些名字不要」（如 `*.draft.*` / `sample/*`）。

    `_scan_once`（老的全量扫盘，仍在）与 `catalog.refresh_library`（第 62 期起的增量刷新）
    共用它，保证「扫到哪些」与「什么算变化」永远一致 —— 这两处若各写一套，
    很容易出现「新书已入库但列表还是旧的」。

    **顶层与系列目录层都用 `os.scandir` 而不是 `Path.iterdir`**（第 62 期）：
    `DirEntry.is_file()/.is_dir()` 读的是目录项自带的类型（Linux 的 `d_type`、Windows 内联在
    返回结构里），**不发 syscall**；`Path.is_file()` 每次都要单发一个 stat。线上书库在 NAS 上，
    42.4s ÷ 266 本 ≈ 158ms/本 反推每次 syscall 都在付毫秒级往返（本机 SSD 上是微秒级）
    —— 每文件省一次，266 本一次刷新就省 266 次往返。`d_type` 不可用的文件系统
    （部分 SMB 挂载报 `DT_UNKNOWN`）会自动回落到一次内部 stat，**只是不更快，不会更错**。
    排序仍按 ``Path`` 比（`pathlib` 在 Windows 上大小写不敏感），与改造前逐项同序。
    """
    allowed = tuple(exts) if exts else BOOK_EXTS
    patterns = tuple(exclude or ())
    allow_audio_dir = any(e in allowed for e in audio.AUDIO_EXTS)
    out: list = []
    try:
        with os.scandir(d) as it:
            entries = sorted(((pathlib.Path(e.path), e) for e in it), key=lambda t: t[0])
    except Exception:
        return out
    for f, ent in entries:
        try:
            is_file, is_dir = ent.is_file(), ent.is_dir()
        except OSError:                       # 目录项在遍历途中消失：跳过，下一轮再说
            continue
        if is_file:
            if f.suffix.lower() in allowed and not _excluded(f.name, f.name, patterns):
                out.append(f)
            continue
        if not is_dir or f.name.startswith("."):
            continue
        # 顶层目录本身就是一个音频目录 → 整目录算一本书
        if allow_audio_dir and audio.is_audio_dir(f) \
                and not _excluded(f.name, f.name, patterns):
            out.append(f)
            continue
        try:
            with os.scandir(f) as it2:        # 同上：系列目录里的书也要一次 stat 都不发
                children = sorted(((pathlib.Path(x.path), x) for x in it2),
                                  key=lambda t: t[0])
        except Exception:
            continue
        for x, xent in children:
            rel = f"{f.name}/{x.name}"
            try:
                x_is_file, x_is_dir = xent.is_file(), xent.is_dir()
            except OSError:
                continue
            if x_is_file and x.suffix.lower() in allowed \
                    and not _excluded(rel, x.name, patterns):
                out.append(x)
            elif allow_audio_dir and x_is_dir and not x.name.startswith(".") \
                    and audio.is_audio_dir(x) and not _excluded(rel, x.name, patterns):
                out.append(x)
    return out


# ---------------- 书库注册表（第 10 期 D8）----------------
# 库是**数据**（存 SQLite），不是配置常量，而且**没有「默认库」这种东西**：
# 全新部署的书库表就是空的，所有书库都由用户手动新建（启动不再播种）。
#
# ⚠️ 因此「库表为空」是**合法且常见**的初始状态，不再是需要兜底的异常：
#   · `libraries()` 老老实实返回空列表（不合成、不假装有一条库）；
#   · `books()` 随之返回空（没有根可扫），孤儿判定因此必须改用
#     `db.orphans()` 里的「库不存在 ⇒ 不算孤儿」规则，否则「清空书库 →
#     点清理孤儿」会把所有进度 / 批注当成孤儿真删（启动注释里警告过这条）；
#   · 摄入侧一律拒收（没有可接收的库，见 `core/library_rules.py`）。
# 归属解析（`library_of` / `root_of`）仍对**留在磁盘上的旧书**保留 OUTPUT_DIR 兜底：
# 只是不再把它伪装成一个库。

# ⚠️ 第 61 期：漫画库**也收 .pdf** —— 要求「漫画库支持 PDF」。
# 收进来后按漫画形态读（前端 pdf.js 逐页渲染），设置页里另有「用 PDF 阅读器读」的开关。
# .pdf 同时仍属于电子书类型（`_EBOOK_EXTS`）：**自动归库**按类型路由时它优先去电子书库，
# 要进漫画库就把它放在漫画库的来源文件夹里 —— 不猜用户意图。
_COMIC_EXTS = (".cbz", ".cbr", ".pdf")
_EBOOK_EXTS = (".epub", ".mobi", ".azw3", ".pdf", ".txt")


def _exts_for_type(ltype) -> tuple:
    """库类型 → 扫描白名单（``mixed`` 用全量）。"""
    t = str(ltype or "mixed").lower()
    if t == "comic":
        return _COMIC_EXTS
    if t == "audiobook":
        return tuple(audio.AUDIO_EXTS)
    if t == "ebook":
        return _EBOOK_EXTS
    return BOOK_EXTS


# ---------------- 新库向导：格式白名单 / 排除图案（第 40 期）----------------
# ⚠️ **两条读时回落规则**：库表里这两列的空串都表示「没设过」，不是空集合 ——
#   allowed_exts='' ⇒ 继承库类型默认（_exts_for_type），**不是**「一个格式都不收」；
#   exclude=''      ⇒ 不过滤。
# 空集合会让库变成**永远扫不出东西的死库**，而界面上完全看不出原因（用户只会觉得
# 「我明明把书放进去了」），故一律当「没设过」。坏 JSON 同理。

def norm_ext(s) -> str:
    """扩展名归一：无前导点就补上、统一小写（``EPUB`` / ``epub`` → ``.epub``）。

    **公开**是因为写入口（``server.api_create_library`` 等）也要用同一套归一 ——
    各写一份必然会漂移（``EPUB`` 与 ``.epub`` 在同一个库里被当成两个格式）。
    """
    s = str(s or "").strip().lower()
    if not s:
        return ""
    return s if s.startswith(".") else "." + s


def _parse_str_list(raw, norm) -> tuple:
    """解析库表里的「JSON 数组文本」列。坏值 / 空一律当**没设过**（返回 ``()``）。

    与 ``lib_settings.overrides`` / ``library_rules.rules_of`` 同口径：手改坏一个字符
    不该把扫描整条链路打崩，更不该留下一个死库。
    """
    s = str(raw or "").strip()
    if not s:
        return ()
    try:
        data = json.loads(s)
    except Exception:                       # noqa: BLE001 —— 坏数据降级为「没设过」
        return ()
    if not isinstance(data, list):
        return ()
    out: list = []
    for v in data:
        n = norm(v)
        if n and n not in out:              # 去重且保序（用户填的顺序要留着）
            out.append(n)
    return tuple(out)


def parse_exts(raw) -> tuple:
    """``libraries.allowed_exts`` → 扩展名元组；空 / 坏值 ⇒ ``()``（=没设过）。"""
    return _parse_str_list(raw, norm_ext)


def parse_excludes(raw) -> tuple:
    """``libraries.exclude`` → glob 图案元组；空 / 坏值 ⇒ ``()``（=不过滤）。"""
    return _parse_str_list(raw, lambda v: str(v or "").strip())


def exts_for_library(lib) -> tuple:
    """某库**生效**的扫描白名单：设过就用设过的，没设过回落库类型默认。

    这是「这个库扫得到哪些格式」的**唯一真值源** —— 扫描、目录指纹、
    跨库相容闸门、入库路由都调它。别在别处再判一次 :func:`_exts_for_type`，
    否则「设过了」的那一层会被绕过。
    """
    lib = lib or {}
    return parse_exts(lib.get("allowed_exts")) or _exts_for_type(lib.get("type"))


def accepts_ext(lib, filename) -> bool:
    """该库扫不扫得到这个条目（按**扩展名**判）。

    给**入库路由**用：把一个文件路由到「收了也看不见」的库 = **隐形文件**
    （文件落盘了、书目里却找不到），比直接拒收更糟 —— 用户看得见失败，看不见消失。

    ⚠️ **没有扩展名的条目一律不拦**：有声书「一章一文件」的**目录**形态在这里判不了，
    它扫不扫得到由 :func:`_iter_book_entries` 的 ``allow_audio_dir`` 按**类型**决定。
    本函数的用途是防隐形文件，判不了就放过 —— 误拒比漏判更烦人。
    """
    ext = pathlib.PurePosixPath(str(filename or "")).suffix.lower()
    if not ext:
        return True
    return ext in exts_for_library(lib)


def _excluded(rel, name, patterns) -> bool:
    """条目是否命中库级排除图案（第 40 期）。

    语义与 ``watcher.ignore`` **同族但有两处明写的差异**（见建库表的 ``exclude`` 列注释）：

    ① 用 :func:`fnmatch.fnmatchcase`（**平台无关**）—— ``watcher._ignored`` 用的
       :func:`fnmatch.fnmatch` 在 Windows 上大小写不敏感，而库级排除是用户显式写的
       可见规则，不能随平台变（``*.DRAFT.*`` 在 Windows 上默默吞掉 ``draft``）；
    ② 图案**含 ``/``** 时匹**相对库根**的路径，否则只匹 basename（watcher 那套是纯 basename）。
    """
    if not patterns:
        return False
    name = str(name or "")
    rel = str(rel or "")
    for pat in patterns:
        p = str(pat or "")
        if not p:
            continue
        if fnmatch.fnmatchcase(rel if "/" in p else name, p):
            return True
    return False


def libraries() -> list:
    """全部书库 —— **真实行**，没有默认库兜底：库表为空就是空列表。"""
    try:
        return db.list_libraries() or []
    except Exception:
        return []


def get_library(lid) -> "dict | None":
    """按 id 取库实体；空 id / 查不到一律 ``None``（不再有合成默认库）。"""
    if not lid:
        return None
    try:
        return db.get_library(lid)
    except Exception:
        return None


def library_of(book: dict) -> "dict | None":
    """书目所属的库；按 ``library_id`` 查，**查不到返回 None**。

    查不到只会发生在「这个库被移除登记、书还留在磁盘上」的情形 —— 调用方必须
    自己决定怎么办（刮削 / 出版两条链路都按「该库未配置成品目录」跳过），
    **不要**在这里合成一个假库，那会让「库管理页看不到它、别的页却当它存在」。
    """
    lid = (book or {}).get("library_id")
    return get_library(lid) if lid else None


def roots_of(lib) -> "list[pathlib.Path]":
    """库的所有文件夹绝对路径（已 resolve）。空库 / 无归属返回空列表。

    第 41 期：库持有多个文件夹（``source_dirs``，绝对路径数组）。这是「取库的所有根」
    的唯一入口，取代旧的单一 ``root_path``。
    """
    raw = (lib or {}).get("source_dirs") or ""
    try:
        arr = json.loads(raw) if raw else []
    except Exception:
        arr = []
    out = []
    for x in arr:
        try:
            out.append(pathlib.Path(str(x)).resolve())
        except Exception:
            pass
    return out


def root_of(book_or_id) -> pathlib.Path:
    """书目（或库 id）的**库根目录** —— 替代全仓 ``config.OUTPUT_DIR``。

    ⚠️ 多文件夹库下返回**第一个文件夹**作为代表根（best-effort）；需要精确根请用
    :func:`roots_of` 结合书的绝对路径判断。这是多库后「取文件路径」的主要入口之一。

    无库归属（该库已移除登记）时回退 ``OUTPUT_DIR``：这类书虽然不在列表里，
    但文件确实可能还躺在那里，改名 / 回收 / 删除都要能算对路径，不能炸在 None 上。
    """
    lib = library_of(book_or_id) if isinstance(book_or_id, dict) else get_library(book_or_id)
    rs = roots_of(lib)
    return rs[0] if rs else pathlib.Path(config.OUTPUT_DIR)


def _cheap_facts(f: pathlib.Path) -> "tuple | None":
    """条目的**便宜事实** ``(size, mtime, is_dir)``：不打开文件就能拿到的全部信息。

    ⚠️ 这是增量刷新的**唯一闸门**：``catalog.refresh_library`` 拿它与索引现值比，
    相同就整段跳过、不调 :func:`_probe_entry`（那次调用要开 zip 读 OPF，
    NAS 上几十毫秒）。所以本函数与 :func:`_probe_entry` **必须同源** ——
    后者算出的 ``size``/``mtime`` 就是写进索引的那两个值。为此两边共用本函数，
    而不是各写一套公式；否则会出现「明明变了却永远不重探」这种查不出来的陈旧。

    音频目录的 ``(体积, mtime)`` 取**音频文件**的合计与最新（``audio.dir_size_and_mtime``），
    与改造前 ``_scan_once`` 里生效的那两个值逐字节一致 —— 改造前它先跑了一次
    ``_entry_mtime`` 的递归 rglob，但那笔结果在本分支**必被覆盖**
    （``_iter_book_entries`` 只把「含音频文件的目录」当条目返回 ⇒ dm 恒非 0），
    所以删掉它纯粹是省下一次整子树的递归遍历，不改任何值。

    条目不可读（``stat`` 失败）返回 ``None``。

    判「是不是目录」用**已经拿到的那个 stat**（``S_ISDIR``），不调 ``f.is_dir()``
    —— 后者会再发一次同样的 stat（第 62 期实测：那是增量刷新里每文件 3 次 stat 中的
    第 3 次，而增量刷新每次写操作后都要跑一遍，线上一次往返就是几毫秒）。语义不变：
    ``Path.stat()`` 与 ``Path.is_dir()`` 都跟随符号链接。
    """
    try:
        st = f.stat()
    except OSError:
        return None
    if stat.S_ISDIR(st.st_mode):
        size, dm = audio.dir_size_and_mtime(f)
        return (size, dm or st.st_mtime, True)
    return (st.st_size, st.st_mtime, False)


def _issues_of(rel: str, size: int, is_dir: bool, unparsable: bool, has_cover: bool) -> list:
    """条目的**文件派生**缺失项（第 5 期「缺失资源」工具的判定依据）。

    ⚠️ 判据必须**只依赖文件自身**（体积 / 是否目录 / 能否解析 / 有没有封面），
    这样它才能在读取时从索引列现算，而不必入库 —— 一旦有服务端状态掺进来
    （如「服务端有没有封面」），索引里那份就会过期。

    「服务端封面存在 ⇒ 撤掉 ``no-cover``」是**另一层**的事，在
    :func:`_apply_overlay` 里做（那里才查得到 ``db.cover_ids``）。
    """
    issues = []
    if not is_dir and size == 0:
        issues.append("zero-bytes")
    if unparsable:
        issues.append("unparsable")
    elif not has_cover and pathlib.PurePosixPath(rel).suffix.lower() == ".epub":
        issues.append("no-cover")
    # 非 EPUB（mobi/pdf/txt/漫画/音频）本项目不去解析封面，不计为缺失
    return issues


def _probe_entry(f: pathlib.Path) -> "dict | None":
    """单个书目条目的**昂贵探测**：开 zip 读 OPF / 解归档数页 / 读音频标签。

    这是扫描链路上唯一的重 IO 环节 —— NAS 上开一次 ``probe_epub`` 要几十毫秒，
    而线上 266 本书的整轮扫描因此要 42 秒。所以它被单独摘出来给两条链路共用：

    - :func:`_scan_once`（**无索引**时的全量扫描，仍是 catalog 的兜底与对拍基准）；
    - ``catalog.refresh_library``（增量刷新）—— **只在条目的 ``(size, mtime)``
      与索引现值不同时才调它**，没变就整段跳过。

    ⚠️ 因此本函数**只能依赖文件自身**。任何库级 / 服务端状态（元数据覆盖层、
    服务端封面、库名、库类型…）都不许掺进来 —— 掺了结果就不能跨请求复用，
    「文件没变 ⇒ 探测结果没变」这条增量刷新的立足点当场失效。库级的东西
    （``name`` / ``path`` / ``library_id`` / 渐变占位色）一律由 :func:`_row_of`
    在**读取时**现拼。

    ``title`` / ``author`` 在这里就把文件名兜底（``metadata.from_filename``）算完，
    存储的是**最终值** —— 否则读回索引时得重新拿文件名解析一遍，等于把探测成本
    又搬回了读取路径。

    条目不可读（``stat`` 失败）返回 ``None``，调用方跳过。
    """
    facts = _cheap_facts(f)
    if facts is None:
        return None
    size, mtime, is_dir = facts
    # 音频（单文件或目录）统一成 format="AUDIO"，前端据此进播放器
    is_audio_entry = is_dir or audio.is_audio(f)
    name_meta = metadata.from_filename(f.name)
    info = {
        "title": "", "author": "", "series": "", "has_cover": False, "unparsable": False,
        "year": "", "publisher": "", "isbn": "", "language": "", "description": "", "tags": [],
        "cover": "", "pages": 0, "pages_source": "", "series_index": "", "fixed_layout": False,
        # 演播者（第 53 期）：扫描期从音频标签解析，列表形态与 tags 同构
        "narrators": [],
    }
    tracks = 0
    if is_audio_entry:
        tracks = audio.tracks(f)["total"]
        # 演播者：解析音频标签（第 53 期补的「前置缺失」）。目录形态取首轨文件；
        # 解析失败只降级为空，绝不让一本书因标签坏而入库失败。
        try:
            _probe = audio.first_audio_file(f)
            if _probe is not None:
                info["narrators"] = audio_meta.extract(_probe).get("narrators") or []
        except Exception:
            info["narrators"] = []
        if is_dir:
            cover = audio.cover_in_dir(f)
            info.update({"has_cover": bool(cover), "cover": cover})
        if tracks == 0:
            info["unparsable"] = True
    elif f.suffix.lower() == ".epub":
        info = probe_epub(f)
    elif comics.is_comic(f):
        # 漫画（CBZ / CBR）：页数与封面都是**真实值**（不是估算），pages_source = "archive"
        info.update(comics.probe(f))

    return {
        "is_dir": is_dir,
        "size": size,
        "mtime": mtime,
        "tracks": tracks,
        "format": "AUDIO" if is_audio_entry else f.suffix.lstrip(".").upper(),
        "title": info["title"] or name_meta["title"],
        "author": info["author"] or name_meta["author"],
        "series": info.get("series", ""),
        # 系列内序号（字符串，空串 = 无）。解析见 _series_index_of
        "series_index": info.get("series_index", ""),
        "has_cover": bool(info.get("has_cover")),
        # 封面来源（EPUB = zip 内路径；漫画 = 归档内条目名；音频 = 目录内文件名；空串 = 无）
        "cover": info.get("cover", ""),
        # 页数：**估算值**（见 _pages_in），pages_source 恒为 "estimate"；
        # 漫画为归档真实页数（"archive"）；非 EPUB / 漫画恒为 0，前端据此不显示页数
        "pages": info.get("pages", 0),
        "pages_source": info.get("pages_source", ""),
        "year": info.get("year", ""),
        "publisher": info.get("publisher", ""),
        "isbn": info.get("isbn", ""),
        "language": info.get("language", ""),
        "description": info.get("description", ""),
        "tags": info.get("tags", []),
        # 演播者（第 53 期）：扫描期自音频标签解析，列表形态与 tags 同构
        "narrators": info.get("narrators", []),
        # 固定版式（pre-paginated）：阅读器据此**不套用重排偏好、不改页宽**（见 _fixed_layout_of）；
        # 非 EPUB 恒 false（本项目不解析它们的内容）
        "fixed_layout": bool(info.get("fixed_layout")),
        "unparsable": bool(info.get("unparsable")),
    }


def _row_of(lib: dict, root: pathlib.Path, f: pathlib.Path, p: dict) -> dict:
    """探测结果 + 库级信息 → BookCard 契约的书目条目。

    ``c1``/``c2``（渐变占位色）由 ``book_id`` 派生、``path`` 由 ``root``/``rel``
    现拼、``library_type`` 取自库实体 —— 这三样（连同 ``name`` 与 ``id`` 本身）
    都**不入库**：入库就等于把「库改名 / 挪根 / 换类型」变成一次需要回填索引的
    数据迁移，而它们本来就是一次哈希或一次字符串拼接的成本。

    ``name`` 是**相对该库根**的 posix 路径 —— BookCard 契约不变，前端 / OPDS /
    Komga 都不必连锁改；跨库同名由入库侧（``core/library_rules.resolve_target``）
    与迁移侧（``core/migrate.py``）**两道**冲突检测拦住 —— 入库侧的拦截是第 13 期
    才补上的，此前只有迁移侧会拦（旧注释把两件事写成了一件）。已经产生的冲突用
    :func:`id_conflicts` 列出来，走工具页一键改名修复。
    """
    rel = f.relative_to(root).as_posix()
    # id 由 basename 派生（见 _book_id），所以挪进系列目录不会换 id
    bid = _book_id(rel, lib.get("id"))
    c1, c2 = _gradient(bid)
    return {
        "id": bid,
        "name": rel,
        "size": p["size"],
        "mtime": p["mtime"],
        "format": p["format"],
        "title": p["title"],
        "author": p["author"],
        "series": p["series"],
        "series_index": p["series_index"],
        "has_cover": p["has_cover"],
        "cover": p["cover"],
        "pages": p["pages"],
        "pages_source": p["pages_source"],
        # 音频轨数（单文件 1、目录 n）；非音频恒 0
        "tracks": p["tracks"],
        "year": p["year"],
        "publisher": p["publisher"],
        "isbn": p["isbn"],
        "language": p["language"],
        "description": p["description"],
        "tags": p["tags"],
        "narrators": p["narrators"],
        "fixed_layout": p["fixed_layout"],
        "c1": c1,
        "c2": c2,
        "issues": _issues_of(rel, p["size"], p["is_dir"], p["unparsable"], p["has_cover"]),
        # 多书库：归属信息。`name` 相对**所属库根**，故协议层与前端无需改
        "path": str(f),
        "library_id": lib.get("id") or "",
        "library_type": lib.get("type") or "mixed",
    }


def _apply_overlay(books: list) -> list:
    """合并服务端元数据（override > online > opf）与封面。

    第 17 期 T3：使列表 / 卡片 / 搜索 / OPDS 全部以服务器为准（详情页早已由
    metastore 合并，这里补齐批量热路径）。

    **一次批量查询**摊销到整批书上，严禁逐书查库（get_overrides/get_online）。
    无索引时它挂在扫描上（靠 TTL 摊销）；有索引后挂在**读取**上 —— 这是这笔
    查询成本必须留意的变化：一次 `/api/books` 两次查询，与书本数无关。

    第 62 期从 :func:`_scan_once` 摘出来给 ``catalog`` 共用 —— 索引化的书目
    也必须过这一层，否则「服务端改过的元数据在列表里看不见」。
    """
    if not books:
        return books
    bids = [b["id"] for b in books]
    eff = db.get_effective_meta(bids)
    cids = db.cover_ids(bids)
    if eff or cids:
        for b in books:
            m = eff.get(b["id"])
            if m:
                for k, v in m.items():
                    b[k] = v
            if b["id"] in cids:
                # 服务端封面并入：置 has_cover 并撤掉扫描时基于文件判定的 no-cover
                b["has_cover"] = True
                b["issues"] = [x for x in b["issues"] if x != "no-cover"]
    return books


def _scan_once(lib: dict = None) -> list:
    """**全量扫盘**一个书库，返回书目条目（第 62 期起不再挂在请求路径上）。

    ⚠️ 这是「没有索引」时的实现，第 62 期之后**唯一的常规调用方是
    ``catalog.refresh_library`` 的冷启动/强制刷新**；请求路径一律走
    ``catalog.books``（读索引）。保留它是因为对拍脚本（改造前后逐字段比对）
    与索引损坏时的兜底都要拿它当基准 —— 它是「正确结果」的定义。
    """
    if not lib:
        return []                      # 没有库就没有根可扫（不再合成默认库）
    # 第 41 期：库持有多个文件夹（roots_of），逐个扫描后合并。
    roots = roots_of(lib)
    # 第 40 期：白名单与排除图案都按**该库生效值**取（设过就用设过的，没设过回落类型默认）
    exts = exts_for_library(lib)
    patterns = parse_excludes(lib.get("exclude"))
    books = []
    for d in roots:
        for f in _iter_book_entries(d, exts, patterns):
            p = _probe_entry(f)
            if p is None:
                continue
            books.append(_row_of(lib, d, f, p))
    return _apply_overlay(books)


def _books_of(lib: dict, force: bool = False) -> list:
    """单个库的书目 —— 第 62 期起**读索引**，不再扫盘。

    改造前这里是「先算目录指纹（全目录 rglob）再查 TTL 5 秒的缓存」，
    所以**缓存命中也要付一次全量 stat**；未命中则 `_scan_once`，且那一步在锁外、
    没有单飞 —— 并发请求各自重扫。线上 266 本书 42 秒就是这么来的。

    现在：索引命中即返回（一条 SELECT），扫盘交给 ``catalog`` 的后台增量刷新。
    冷启动（索引空）由 ``catalog`` 内部同步扫一次，之后永不再等。
    """
    if not lib:
        return []
    from . import catalog            # 延迟导入：catalog 反过来要用本模块的探测函数
    if force:
        catalog.refresh_library(lib, force=True)
    return catalog.books_of(lib)


def books(library_id=None, force: bool = False) -> list:
    """书目列表（**多库合并**；可按库过滤）。

    - ``library_id`` 为空 → 合并全部库（保持既有「全库」语义，供统计 / 搜索 / 推荐用）；
    - ``force=True`` → 先强制重扫该库（忽略索引里的 ``(size, mtime)`` 判据）。

    第 62 期起实现整体搬进 ``catalog``：读索引，不扫盘。**逐字段口径不变** ——
    存的是「只依赖文件自身」的那部分，读取时再拼库级字段并过服务端元数据覆盖层
    （与改造前 ``_scan_once`` 的两段完全同构，见 ``catalog._book_of_row``）。
    """
    from . import catalog
    if force:
        # 只强制重扫**点名的那个库**：`_scan_once` 是「立即扫描」按钮的语义，
        # 而对全部库做一次强制全量正是本期要消掉的那笔开销。
        if library_id:
            lib = get_library(library_id)
            if lib:
                catalog.refresh_library(lib, force=True)
        else:
            catalog.refresh_all(force=True)
    return catalog.books(library_id)


def invalidate(library_id=None) -> None:
    """让书目缓存失效（任何改文件的操作之后都要调）。

    给 ``library_id`` 时只失效该库；不给则全部失效（调用方多数不关心库，
    但按库失效能在多库下避免「改一个库、全库重扫」）。

    ⚠️ 第 62 期起语义从「清空进程内扫描缓存」变成「**标脏**」：下一个读该库的
    请求（或监听线程的下一轮）会做一次**增量**刷新 —— 一次目录遍历 + 每文件一次
    stat，不开 zip。改造前这里是直接清缓存，于是 `_libraries_changed()` 一调
    （**新建书库**时会调），紧接着前端连打的 `/api/libraries`、`/api/books`、
    `migration/preview` 每次都是**冷缓存全量重扫** —— 那正是「新建书库很慢」的根因。
    """
    from . import catalog
    catalog.invalidate(library_id)


def export_rows() -> list:
    """书目元数据的平铺行（CSV 导出用）。

    字段来自 ``books()``（文件派生 + 服务端元数据合并）。阅读进度 / 状态 / 评分在
    另一批表里，由接口层合并 —— 本函数不查这些表。
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


def find(name: str, library_id=None) -> dict | None:
    """按**库内相对路径**取书；给 ``library_id`` 时限定在该库内查找。"""
    for b in books(library_id):
        if b["name"] == name:
            return b
    return None


def sibling_files(path: pathlib.Path) -> list:
    """``path`` 的**同 stem 成品文件**清单（第 63 期 5/6 从 :func:`book_detail` 抽出）。

    抽出来的理由：详情页的「文件」标签与「本机绝对路径」（``GET
    /api/books/{bid}/local-paths``）都要这份清单，而「哪些算兄弟」的判据
    （**同一个目录**里、**同 stem**、**是文件**）只能有一份 —— 两处各写一遍，
    迟早在其中一处走样。三条判据都是有来由的：

    - **同一个目录**：Komga 布局下同系列的书都躺在系列目录内，跨目录去找会串到别的系列；
    - **同 stem**：``三体.epub`` 与 ``三体.mobi`` 是同一本书的两个成品，``三体2.epub`` 不是；
    - **是文件**：目录不参与 —— 目录型的书是**有声书**，它自己就是一个目录，
      枚举下去会把别的**目录**当成成品文件列出来。

    ⚠️ 返回的项给的是 ``path``（**绝对路径对象**），**不给库内相对路径** ——
    「相对哪个根」是调用方的事：``book_detail`` 相对库根取名（那是详情页契约），
    ``local-paths`` 端点直接给绝对路径。本函数只管「在文件系统上找出兄弟文件」。

    返回项 ``{path, format, size, mtime}``，按文件名排序；读不了目录时返回空
    （**枚举**拿不到就是拿不到，不能因此让整个详情页打不开）。
    """
    if path.is_dir():
        return []
    stem = path.stem
    out = []
    try:
        for f in sorted(path.parent.iterdir()):
            if f.is_file() and f.stem == stem:
                out.append({
                    "path": f,
                    "format": f.suffix.lstrip(".").upper() or "?",
                    "size": f.stat().st_size,
                    "mtime": f.stat().st_mtime,
                })
    except Exception:                         # noqa: BLE001
        pass
    return out


def book_detail(name: str, library_id=None) -> dict | None:
    """单本详情：基础元数据 + 真实章节树 + 同 stem 的成品文件列表（音频另给轨道清单）。"""
    b = find(name, library_id)
    if not b:
        return None
    root = root_of(b)
    path = root / name
    suffix = path.suffix.lower()
    if suffix == ".epub":
        chapters = _reading_list(path)
    elif suffix == ".txt":
        # 第 55 期：TXT 优先用**派生 EPUB** 的目录（与阅读内容同一形态，索引空间也一致）；
        # 转不动（超大 / 编码坏 / 构建失败）回落原生分章目录。形态由缓存里的源指纹锁定。
        from . import txtcache  # 延迟导入：txtcache 反向依赖本模块的 root_of
        ep = txtcache.derived_epub(b, path=path, root=root)
        chapters = _reading_list(ep) if ep else txtcache.native_chapters(b, path=path, root=root)
    else:
        chapters = []
    files = []
    for f in sibling_files(path):
        try:
            name = f["path"].relative_to(root).as_posix()
        except ValueError:
            # 拼不出库内相对路径 ⇒ 这一条**不列**（与改造前 `except: pass` 的
            # 行为一致）。多文件夹库下 `root_of` 只给「代表根」，书在别的根上时
            # 就是这个情形 —— 漏列比列一个指向别处的假路径好。
            continue
        files.append({"name": name, "format": f["format"],
                      "size": f["size"], "mtime": f["mtime"]})
    detail = dict(b)
    detail["chapters"] = chapters
    detail["files"] = files
    # 有声书：把轨道清单随详情一起下发，播放器首屏无需再发一次请求
    if (b.get("format") or "").upper() == "AUDIO":
        detail["audio_tracks"] = audio.tracks(path)["items"]
    return detail


# ---------------- 聚合 ----------------

def entities(kind: str, library_id=None) -> dict:
    """按作者或系列聚合：``{type, items: [{name, count, books}]}``。

    ``library_id`` 给定时**只看该库**（工具页的「范围：当前库」）；缺省 = 全部书库。
    """
    field = "author" if kind == "author" else "series"
    bs = books(library_id)
    bucket: dict = {}
    for b in bs:
        key = (b.get(field) or "").strip()
        if not key:
            continue
        bucket.setdefault(key, []).append(b["name"])
    items = [
        {"name": k, "count": len(v), "books": v}
        for k, v in sorted(bucket.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    ]
    return {"type": kind, "items": items, "total": len(bs)}


def duplicate_groups(threshold: int = 85, library_id=None) -> dict:
    """重复书目分组：**归一化后同作者 + 书名相似度 ≥ threshold**。

    与上游 Calibre 的「Similar-title threshold」同口径（默认 85%）：
      · 作者必须一致（归一化后完全相同）—— 同名不同作者的书不是重复；
      · 书名用 difflib 相似度比较，阈值可调：调低抓更多近似（含「XX 第2版」这类），
        调高只留几乎全同的；
      · 没有作者的书只在同样缺作者的书之间互比，避免把一堆「佚名」混作一组。

    聚类用并查集单链法：A~B、B~C 达标会把 A、B、C 并成一组（传递闭包），
    这与「人工看重复」的直觉一致 —— 中间那本把两头的书连起来了。

    ``library_id`` 给定时只在该库内找重复（工具页默认只看当前库）；缺省 = 全部书库。
    每条 item 都带 ``library_id``，组上给 ``cross_library`` —— 「全部书库」范围下
    分属不同库的重复会被明确标成**跨库重复**（这正是最该被注意的情形）。
    """
    from difflib import SequenceMatcher

    try:
        threshold = max(50, min(int(threshold), 100))
    except (TypeError, ValueError):
        threshold = 85
    thr = threshold / 100.0

    bs = books(library_id)
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
            libs = {str(m[0].get("library_id") or "") for m in members}
            groups.append({
                "key": f"{akey}|{ms[0]['id']}",
                "reason": (f"书名与作者完全相同" if exact
                           else f"同作者 · 书名相似度 ≥ {threshold}%"),
                "similarity": round(min(sims) * 100) if sims else 100,
                "title": ms[0]["title"],
                "author": ms[0]["author"],
                "cross_library": len(libs) > 1,
                "items": [
                    {"name": i["name"], "size": i["size"], "mtime": i["mtime"],
                     "format": i["format"], "library_id": i.get("library_id")}
                    for i in ms
                ],
            })
    # 跨库重复排前面：分属不同库的同名书是最该先看的（它们还会撞 book_id）
    groups.sort(key=lambda g: (not g["cross_library"], -len(g["items"]), -g["similarity"]))
    return {"groups": groups, "total": len(bs), "threshold": threshold}


def missing_items(library_id=None) -> dict:
    """有问题的条目：零字节 / 无法解析 / 缺封面。

    ``library_id`` 给定时只看该库（工具页默认只看当前库）；缺省 = 全部书库。
    """
    bs = books(library_id)
    items = [
        {"name": b["name"], "size": b["size"], "mtime": b["mtime"],
         "issues": b["issues"], "library_id": b.get("library_id")}
        for b in bs if b["issues"]
    ]
    return {"items": items, "total": len(bs)}
