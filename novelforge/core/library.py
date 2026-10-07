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
from html import unescape as html_unescape
import json
import logging
import os
import pathlib
import posixpath
from urllib.parse import quote, unquote
import re
import stat
import threading
import time
import unicodedata
import uuid
import zipfile

from .. import config
from . import audio, audio_meta, comics, db, metadata, reading_list, units, zipkind

# 只把这些扩展名当成「书」；与 /api/files 的全量列表不同，这里是有意收窄的。
# .cbr（RAR 漫画）自第 9 期起在列 —— 由 core/comics.py 的 zip/rar 双后端解压。
# 单个音频文件也算一本书；「音频目录」（一章一文件）由 _iter_book_entries 单独识别。
# ⚠️ 第 87 期：`.zip` 也在列 —— 它是**通用容器**，真实形态由 `core/zipkind.py` 按内容分派
# （里面是图片就按漫画读、是一份 EPUB/PDF 就记成需要展开、判不出就如实报无法解析）。
# 第 111 期：`.rar` / `.7z` 同列 —— 同一种通用容器的另外两个壳（`.rar` 与 `.cbr`、
# `.7z` 与其并列）。不收进来的话，用户放进库里的 `.rar` 漫画**连书目都进不去**
# （表现为「文件在盘上、书架上看不见」，比打开失败更难排查）。
BOOK_EXTS = (".epub", ".mobi", ".azw3", ".azw", ".fb2", ".pdf", ".txt", ".cbz", ".cbr", ".zip",
             ".rar", ".7z", *audio.AUDIO_EXTS)

#: 扫描口径版本。**凡能改变「条目边界」或卡片字段口径的改动都要 +1**：
#: 第 73 期两处 —— ① 序号单元目录整棵树被合成一个条目（此前是每文件一本，更深的根本扫不到）；
#: ② 书名剥掉「范围 / 话数备注」（`《书名（1-43话）》` → `《书名》`）。
#: 第 79 期一处 —— ③ 一级子文件夹里的「前缀 + 尾部编号」散文件（`超人前传0904.pdf`）也被
#: 认成序号单元 ⇒ 该文件夹由 N 本合成 1 本（判据见 `units.is_unit_dir` 的「同前缀」闸）。
#: 它只影响**漫画库 / 有声书库**（`units.MERGE_LTYPES`），ebook / mixed 库的条目边界不变 ——
#: 但版本号是全局单值，所以那两类库的标志位也会跟着过期、多跑一次全量重探（一次性无害）。
#:
#: ⚠️ 它是**存量索引唯一的自愈通道**：增量刷新的闸门是每行的 ``(size, mtime)``，
#: 磁盘上的文件一个字节都没变，所以口径升级后那些旧行**永远不会被重探** ——
#: 用户在界面上看到的还是老样子（43 本各自独立），而且不报错、不重建。
#: `catalog` 拿这个数与 `app_state` 里的标记（**按库**）比对，不一致就把该库的下一轮
#: 刷新**当成 force**，全量重探一次后写回标记（见 `catalog` 里「扫描口径版本」那段）。
#: 第 72 期在派生件那边踩过同一个坑（`pipeline.ENCODING_RULE_VERSION`）。
#: 第 110 期一处 —— ④ `.azw` 进白名单（`BOOK_EXTS` / `_EBOOK_EXTS`）：此前它**不是书**
#: （扫描时被忽略），现在是一本可直读的 MOBI 家族书 ⇒ **条目边界变了**，存量库里那些
#: `.azw` 文件不 +1 就永远不会被重探（它们此前连索引行都没有）。
#: 第 111 期一处 —— ⑤ `.rar` / `.7z` 进白名单（三类库都收）：同理，「不是书」变成「一本书」。
#: 第 112 期一处 —— ⑥ `.fb2` 进白名单（`BOOK_EXTS` / `_EBOOK_EXTS`）：它此前不是书
#: （扫描时被忽略），现在是一本可直读的 FB2 ⇒ 存量库里那些 `.fb2` 文件不 +1 就永远不会被
#: 重探（它们此前连索引行都没有）。扫描期口径也扩了一格：`.fb2` 的 `has_cover` 改由
#: 内嵌封面探测（`fb2cache.has_embedded_cover`）决定。
SCAN_RULE_VERSION = 5

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


# ---------------- 冲突判定用的取名判据（第 87 期）----------------
# 与 `norm_key` 的分工：`norm_key` 服务**重复书籍 / 搜索 / 实体**（把《书名》与书名
# 当同一本），本组函数服务**同名冲突 / 副本识别**（判「这两条路径说的是不是同一本书」）。
# 两者口径不同，**不能合并**：合并会让搜索把不同卷的书也当成一本。

#: 副本后缀：`三体 (2).epub` / `三体（2）` / `三体[2]` —— 下载器与「另存为」的产物。
#: 它们**是同一本书**（用户第 87 期口径），判定前必须剥掉，否则会被当成两本。
_COPY_SUFFIX_RE = re.compile(r"\s*[（(\[【]\s*\d{1,3}\s*[)）\]】]\s*$")
#: 破折号家族统一（`‐` `‑` `‒` `–` `—` `―` `−` 与 `-` 视作同一个字符）—— 用户口径：
#: `Vol.01-Vol.13` 与 `Vol.01–Vol.13` 是同一本书，不该算两个名字。
_DASH_RE = re.compile(r"[‐‑‒–—―−]")
#: 卷号：`第3卷` / `Vol.01` / `v2`（解析不出就返回空 —— 不猜位置）
_VOLUME_RES = (
    re.compile(r"第\s*(\d{1,4})\s*[卷话册集部]"),
    re.compile(r"\bvol(?:ume)?\.?\s*(\d{1,4})"),
    re.compile(r"\bv\s*(\d{1,3})\b"),
)


def conflict_key(name: str) -> str:
    """冲突判定的**基底键**：去目录、剥副本后缀、统一破折号 / 全角 / 空白 / 大小写。

    用于回答「这两条路径说的是不是同一本书」。注意它**保留数字**：所以
    `X Vol.01` 与 `X Vol.02` 得到**不同**的键（它们是不同的书）——
    这正是用户口径里「主标题相同的不同卷不该算一组」的那一半。
    """
    base = pathlib.PurePosixPath(str(name or "")).name
    base = unicodedata.normalize("NFKC", base)          # 全角 → 半角
    base = _DASH_RE.sub("-", base)
    pure = pathlib.PurePosixPath(base)
    # ⚠️ 副本后缀在**主名**上（`X (2).zip` 的 `(2)` 不在字符串末尾），所以先摘扩展名
    # 再去后缀；扩展名本身**保留在键里**（`X.zip` 与 `X.cbz` 是两种形态的文件，
    # 把它们当「同一本的副本」会误导用户去删掉另一种格式）。
    stem = _COPY_SUFFIX_RE.sub("", pure.stem).strip()
    return f"{norm_key(stem)}{pure.suffix.lower()}"


def volume_of(name: str) -> str:
    """卷号签名（`Vol.01` / `第3卷` / `v2` → ``"1"`` / ``"3"`` / ``"2"``；无则空串）。

    只用于**说清结论**（「同为第 3 卷的副本」），判定本身靠 :func:`conflict_key`
    里保留的数字。解析不出返回空串 —— 不猜位置（既有纪律）。
    """
    base = unicodedata.normalize("NFKC", pathlib.PurePosixPath(str(name or "")).name)
    low = base.lower()
    for rx in _VOLUME_RES:
        m = rx.search(low)
        if m:
            return str(int(m.group(1)))
    return ""


def is_copy_name(a: str, b: str) -> bool:
    """两个名字是不是**同一本书的副本**（归一化后同名，含 `(2)` / 破折号 / 全角差异）。"""
    ka, kb = conflict_key(a), conflict_key(b)
    return bool(ka) and ka == kb


def conflict_kind(rels, paths, lib_ids) -> tuple:
    """一组同 id 条目 → ``(kind, reason)``（**纯函数**，便于单测）。

    · ``duplicate_scan``：条目指向**同一个物理文件**（同一份文件被多个来源文件夹重复
      扫到）⇒ 改名是**错的**（改的是同一个文件），该修的是库配置；
    · ``cross_library``：同一条相对路径出现在多个库 ⇒ 真冲突，留一个改一个；
    · ``same_name_different_dirs``：同库内**同名但不同目录** ⇒ 它们是**不同的书**
      （不同系列的同名卷之类），只是 basename 逐字相同才撞了 id。
    """
    rels = [str(x) for x in rels]
    paths = [str(x) for x in paths]
    if len(set(paths)) < len(paths):
        return "duplicate_scan", ("这几条指向**同一个文件**（同一份文件被多个来源文件夹重复扫到）："
                                  "改名会改到同一个文件，应当修的是库配置（来源文件夹重叠）")
    if len(set(lib_ids)) > 1 and len(set(rels)) == 1:
        return "cross_library", "同一条相对路径出现在多个库：进度 / 批注只有一份，必须留一个、改一个"
    return "same_name_different_dirs", ("同名但**不同目录**（不同系列 / 不同书）：basename 逐字相同才撞了 id，"
                                        "改名时用目录名区分才有意义")


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


def _dc_description(opf: str) -> str:
    """``dc:description``：**先解 HTML 实体，再原样保留标签**。

    为什么单独一个函数而不复用 :func:`_tag_text`：``dc:description`` 在真实 OPF 里
    常常是**双写转义**的 HTML 片段（实测 Standard Ebooks 30/30 本写作 ``&lt;p&gt;…``），
    所以它需要的处理和 ``dc:title`` 这类纯文本字段**刚好相反**：
    - 纯文本字段（title / creator / publisher / language）：要**剥标签**，实体不解也无害。
    - description：要**解一次实体**（否则用户界面上直接看到 ``&lt;p&gt;`` 字面量），
      但**不能剥标签**（解出来的 ``<p>`` / ``<i>`` 是描述本身的内容，
      而它在很多源里本就是 HTML 片段 —— 剥了就丢信息）。

    ⚠️ **顺序不能反**：先剥标签再解实体会把 ``&lt;p&gt;`` 当成文本留下；
      先解实体再剥标签会把刚解出来的真标签吃掉。所以这里只做 unescape，
      并且**刻意不再调** ``re.sub(r"<[^>]+>", "", …)``。
    ⚠️ 前端用 ``{{ }}`` 文本插值渲染 description（``BookPreviewDialog.vue`` /
      ``detail/OverviewTab.vue``），浏览器**不会**再解一次实体 ⇒ 坏的那份会直接露出。

    口径与在线源对齐到「同一步」：``core/metasources.py`` 抓来的描述也解了实体
    （它额外剥了标签，因为它拿到的是**网页**、标签是站点模板；OPF 的标签是**书自己的内容**）。

    ⚠️ **前缀不写死成 ``dc:``**：野生 EPUB 里有把 Dublin Core 声明成别的别名的
      （``xmlns:dc1="http://purl.org/dc/elements/1.1/"`` + ``<dc1:description>``），
      而旧实现走 :func:`_tag_text` 时按**调用点传进来的标签名**匹配、本来就认这种写法。
      写死 ``dc:`` 会让这类书的描述**静默变空**（正是本文件最忌讳的失败模式），
      所以这里用 ``\\w+:description`` 认任意前缀。``re.S | re.I`` 与 :func:`_tag_text` 保持一致。
    """
    m = re.search(r"<\w+:description[^>]*>(.*?)</\w+:description>", opf, re.S | re.I)
    if not m:
        return ""
    return html_unescape(m.group(1)).strip()


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


def remember_origin(dest, library_id, origin) -> None:
    """入库成功后登记「① 原件 → 这本书」的对应关系（第 75 期）。

    ``dest`` = ② 落好的成品绝对路径；``origin`` = ① 原件的绝对路径（收书目录里那份）。
    ``book_id`` 只由 basename 派生（见 :func:`_book_id`），所以这里取 ``dest`` 的文件名。

    两条**刻意的静默返回**（都不是错误）：
    - ``dest`` 与 ``origin`` 是同一个文件（就地库：来源目录本身就是库根）⇒ 不登记。
      否则删书会对同一条路径回收两次，第二次报缺 —— 而真相只是「① 就是 ②」。
    - 判不出库 id ⇒ 不登记。没有库前缀的 id 是第 17 期之前的旧形状，与书目里的
      ``库$哈希`` 对不上，登记了也是一条永远查不中的记录。

    登记失败**绝不外抛**：它只是「删书时顺带把 ① 也清理掉」的便利信息，
    不该让一次**已经落盘成功**的入库变成失败（抛出去只会让调用方误判成没入库）。
    """
    try:
        if not library_id:
            return
        d, o = pathlib.Path(str(dest)), pathlib.Path(str(origin))
        if d.resolve() == o.resolve():
            return
        base = pathlib.PurePosixPath(str(d).replace("\\", "/")).name
        db.origin_set(_book_id(base, str(library_id)), str(o))
    except Exception:                                      # noqa: BLE001 —— 见 docstring
        logging.getLogger("novelforge").exception("登记原始文件来源失败：%s", dest)


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


def _plain_text(raw: str) -> str:
    """把一小段 HTML 压成纯文本（去标签 + 折叠空白）。

    ⚠️ 名字**刻意不叫 `_tag_text`**：那个名字在本模块 :119 已经有一个「按标签名从 XML 里
    取值」的同名函数（``_tag_text(xml, tag)``，``probe_epub`` 抽 OPF 元数据用）。
    重名会把先定义的那个**覆盖掉** —— 而且在 import 期不报错，只在跑起来时让
    `probe_epub` 抛 `TypeError`（被它自己的 except 吞掉）⇒ 书目集体丢元数据、
    系列/出版社全空。第 85 期实测踩过一次，别再改回去。
    """
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", raw or "")).strip()


def _doc_titles(path: pathlib.Path, media: list) -> dict:
    """从「目录里没有列到的」XHTML 文档头部取标题 → ``{zip 内路径: 标题}``。

    为什么值得读正文：**楔子这类条目经常根本不在 nav/NCX 里**（有些电子书的目录只列卷与
    正文章，前言 / 楔子 / 版权页是「额外」的文档）。而目录面板里那一格标题此前一律回落成
    「第 N 章」，把书自己写着的「楔子」丢掉了 —— 这是**本地就有的信息**，不该丢。

    只读每个文档的**前 64 KB**（``_HEAD_SCAN_BYTES``，与 :func:`chapter_assets` 扫内联
    ``<style>`` 同一口径）：标题在文档开头。``<title>`` 优先，否则第一个 ``<h1>–<h6>``。
    **只对 nav 缺失的那些文档调用**（正常书一本都不会读）。
    """
    if not media:
        return {}
    out: dict = {}
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            for m in media:
                if m not in names:
                    continue
                try:
                    with z.open(m) as f:
                        head = f.read(_HEAD_SCAN_BYTES).decode("utf-8", "ignore")
                except Exception:                            # noqa: BLE001 —— 坏条目跳过
                    continue
                m_title = re.search(r"<title[^>]*>(.*?)</title>", head, re.S | re.I)
                t = _plain_text(m_title.group(1)) if m_title else ""
                if not t:
                    m_h = re.search(r"<h[1-6][^>]*>(.*?)</h[1-6]>", head, re.S | re.I)
                    if m_h:
                        t = _plain_text(m_h.group(1))
                if t:
                    out[m] = t
    except Exception:                                        # noqa: BLE001 —— 坏 zip 不抛
        return out
    return out


def _filename_title(media: str) -> str:
    """文件名的**中文**回退名（``楔子.xhtml`` → ``楔子``）；不可读时给空串。

    ⚠️ 只认**含汉字**的文件名：``c0003.xhtml`` / ``cover.xhtml`` / ``chapter1.xhtml`` 这类
    骨架名拿来做标题比「第 N 章」更难懂，所以宁可继续用兜底名（第 85 期口径）。
    """
    stem = pathlib.PurePosixPath(media).stem
    return stem if re.search(r"[\u4e00-\u9fff]", stem) else ""


def _reading_list(path: pathlib.Path) -> list:
    """阅读顺序（对齐 spine）的「卷 / 段 → 章」结构；标题优先取目录（按文件精确对齐）。

    spine 决定章节顺序与 index（阅读器据此加载正文），目录仅提供标题与卷层级，
    因此目录条目数与 spine 不一致时也能正确套用（封面、版权页等多出的条目不会错位）。

    **标题解析链**（第 85 期）：目录（nav / NCX）→ 文档自带的 ``<title>`` / 首个标题元素
    （**只对目录没列到的那些文档读**）→ 文件名（含汉字时）→ ``第 N 章``。
    此前缺了中间两环，于是「楔子」这种不在目录里的条目一律显示成「第 3 章」。

    ⚠️ **index 始终是 spine 下标**，一个字都不许动（阅读进度 / 批注 / 书签的坐标，
    且 TXT 两条路线的索引空间刻意对齐）。分组交给
    :func:`novelforge.core.reading_list.build_reading_list`（与 TXT 路径共用同一份规则）。
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

    missing = [spine[i] for i in range(n) if spine[i] not in depth_of]
    doc_titles = _doc_titles(path, missing)

    entries: list = []
    for i in range(n):
        media = spine[i]
        title = (titled.get(media) or doc_titles.get(media) or _filename_title(media)
                 or f"第 {i + 1} 章")
        entries.append({"title": title, "index": i, "depth": depth_of.get(media)})
    return reading_list.build_reading_list(entries)


def _body_of(doc: str) -> str:
    m = re.search(r"<body[^>]*>(.*)</body>", doc, re.S | re.I)
    return m.group(1) if m else doc


# ---------------- 书内资源 URL（第 76 期）----------------
# 正文（`_rewrite_assets`）与书内样式（`chapter_assets`）**共用**下面这套解析与 URL 构造。
# ⚠️ 令牌**不在这里拼** —— 这两个函数的产物都会被缓存，写进令牌会让它过期后整章正文
# 的插图全 401；令牌由端点在**读完缓存之后**统一追加（`server._with_asset_token`）。

def _asset_url(bid: str, resolved: str) -> str:
    """zip 内条目 → asset 接口 URL（**全仓唯一构造点**，别处不许再拼这个形状）。"""
    return f"/api/books/{bid}/asset?p={quote(resolved)}"


def _resolve_asset(val: str, base: "pathlib.PurePosixPath") -> str:
    """相对引用 → zip 内条目路径；**不该改写的一律回空串**。

    回空串的情形：空值、``#锚``、协议相对（``//``）、带 scheme 的值（``http:`` /
    ``data:`` / ``mailto:`` …），以及**折叠 ``..`` 之后仍逃出 zip 根**的路径。
    最后一种刻意**不重写**：与其造一个必然 404 的 URL，不如原样保留 —— 那本来就说明
    这本书自身的引用是坏的。

    ``..`` **必须折叠**：真实 EPUB 里 ``../Images/x.jpg`` 极常见，而 `/asset` 是拿
    ``z.namelist()`` **精确相等**匹配的（``server.api_book_asset``）—— 不折叠就永远
    命不中（404）。
    """
    val = str(val or "").strip()
    if not val or val.startswith("#") or val.startswith("//") or val.startswith("/"):
        # `//host/x` 是协议相对、`/x` 是站内绝对：都不是 zip 内条目。
        # ⚠️ 绝对路径这一条还兼着**幂等**：改写产出的 `/api/…` 也正是这个形状，
        # 于是「内联进来的 CSS 已经改写完」时外层再跑一遍不会把它套成第二层。
        return ""
    if re.match(r"^[a-z][a-z0-9+.-]*:", val, re.I):          # http: / data: / mailto: …
        return ""
    try:
        head = str(base or "")
        joined = f"{head}/{val}" if head and head != "." else val
        resolved = posixpath.normpath(joined)
    except Exception:                                        # noqa: BLE001 —— 坏值当「不改写」
        return ""
    if resolved in ("", ".", "..") or resolved.startswith(("../", "/")):
        return ""
    return resolved


#: 会被改写的属性。**一条正则吃四种**：`(attr)(引号)(值)\2` 用反向引用保证两边引号一致，
#: 于是单引号写法（真实 EPUB 里不少）也被覆盖，且不必猜值里有没有另一种引号。
#: `srcset` 的值是「逗号分隔的多个候选」、`style` 的值是 CSS，各自另有处理（见下）。
_ASSET_ATTR_RE = re.compile(r"""\b(src|href|poster|srcset|style)\s*=\s*(["'])(.*?)\2""", re.I)
#: 正文里内联的 `<style>` 块（`style="…"` 属性由上面那条正则覆盖）
_STYLE_TAG_RE = re.compile(r"(<style\b[^>]*>)(.*?)(</style\s*>)", re.S | re.I)
#: CSS 里的 `url(...)`（三种引号写法）
_CSS_URL_RE = re.compile(r"""url\(\s*(?:"([^"]*)"|'([^']*)'|([^)"']*))\s*\)""", re.I)
#: CSS 里的 `@import`（url() 形式与裸字符串形式；只取到分号）
_CSS_IMPORT_RE = re.compile(
    r"""@import\s+(?:url\(\s*(?:"([^"]+)"|'([^']+)'|([^)"']+))\s*\)|"([^"]+)"|'([^']+)')"""
    r"""[^;]*;""",
    re.I,
)
#: `<a href="…">` 指向的是**别的章节文档**，不是资源 —— 不能改写（改写后点开会把
#: XHTML 当文件下下来）。判据只看扩展名，够用且不必解析文档结构。
_DOC_EXTS = (".xhtml", ".html", ".htm")


def _attr_value(m: "re.Match", *groups) -> str:
    """「二选一引号」这类正则里实际命中的那个捕获组（另一支是 ``None``）。"""
    for g in groups:
        v = m.group(g)
        if v is not None:
            return v
    return ""


def _rewrite_css_urls(css: str, base: "pathlib.PurePosixPath", bid: str) -> str:
    """把 CSS 里的 ``url(...)`` 改写成 asset 接口（相对路径以**该 CSS 文件自身**为基准）。

    图片与 ``@font-face`` 的字体走同一条路 —— 它们都是 zip 内条目，`/asset` 一个入口
    就够（Content-Type 由 ``mimetypes`` 给出）。

    ⚠️ **刻意不加引号**（`url(/api/…)` 而不是 `url("…")`）：这段 CSS 可能被嵌在
    `style="…"` 属性里（正文的内联样式），加双引号会把属性**提前截断**。而路径已经过
    `quote()`，里面不会有 `)` / 引号 / 空白（这几个字符全被百分号编码），
    所以不带引号的 `url()` 没有歧义、在任何上下文里都成立。
    """
    def fix(m: "re.Match") -> str:
        resolved = _resolve_asset(_attr_value(m, 1, 2, 3), base)
        return f"url({_asset_url(bid, resolved)})" if resolved else m.group(0)

    return _CSS_URL_RE.sub(fix, css)


#: ``@import`` 跟随深度上限（`seen` 是主防循环，这里是第二道）
_CSS_MAX_DEPTH = 5


def _load_css(z: zipfile.ZipFile, name: str, bid: str, seen: set, depth: int = 0) -> str:
    """读一个 zip 内 CSS：**递归内联** `@import`，再把 `url()` 改写成 asset 接口。

    为什么要内联而不是把 `@import` 也指向 `/asset`：被导入的 CSS 里那些**相对**
    ``url()`` 是相对**它自己**的位置解析的，交给浏览器去取就会以 `/asset` 为基准 ⇒
    全错。内联掉之后每条 ``url()`` 都能用正确的 base 处理。

    ⚠️ 内联进来的文本**已经改写完**，外层再跑一遍 `_rewrite_css_urls` 时它不会被二次
    改写 —— 改写后的值是绝对路径（``/api/…``），`_resolve_asset` 对它回空串（见其说明）。
    """
    if depth > _CSS_MAX_DEPTH or not name or name in seen or name not in z.namelist():
        return ""
    seen.add(name)
    try:
        raw = z.read(name).decode("utf-8", "ignore")
    except Exception:                                        # noqa: BLE001 —— 坏条目跳过
        return ""
    base = pathlib.PurePosixPath(name).parent

    def imp(m: "re.Match") -> str:
        resolved = _resolve_asset(_attr_value(m, 1, 2, 3, 4, 5), base)
        return _load_css(z, resolved, bid, seen, depth + 1)

    return _rewrite_css_urls(_CSS_IMPORT_RE.sub(imp, raw), base, bid)


#: 扫 spine 文档的 head 找内联 `<style>` 时，每个文档最多读多少字节（head 在开头）
_HEAD_SCAN_BYTES = 64 * 1024


def chapter_assets(path: pathlib.Path, bid: str) -> dict:
    """一本书的**书内样式**：`<style>` 块 + `<link rel=stylesheet>` + `@import` 链。

    返回 ``{"css": str, "sheets": [zip 内路径…], "fixed_layout": bool}``。

    ⚠️ **必须以独立字段下发，绝不内嵌进 `chapter_html` 的 html** —— 见
    :mod:`core.epub_cfi` 的字符偏移不变量：正文容器的 ``textContent.length`` 是前后端
    共用的那把尺子，而 CSS 本身就是文本节点 —— 注入进去会把正文长度顶长，
    让进度 / 批注 / 高亮的偏移**全线错位**。

    粒度取**整本一次**而不是每章：滚动流同时挂着相邻章块，样式若随章切换会互相打架；
    真实 EPUB 也基本都是全书共用一套。

    坏书 / 坏 CSS 一律**静默降级为空样式** —— 宁可没有书内排版，也不许因此读不了书。
    """
    empty = {"css": "", "sheets": [], "fixed_layout": False}
    try:
        with zipfile.ZipFile(path) as z:
            opf_path = _opf_path(z)
            if not opf_path:
                return dict(empty)
            opf = z.read(opf_path).decode("utf-8", "ignore")
            opf_base = pathlib.PurePosixPath(opf_path).parent

            # ① manifest 里声明为 CSS 的条目（`<link rel=stylesheet>` 指向的就是它们）。
            #    走 manifest 而不是逐章扫 `<link>`：一份 OPF 就够，且不受「某些章没写
            #    link」影响（样式表按 OPF 声明，这正是 EPUB 的权威来源）。
            sheets: list = []
            for m in re.finditer(r"<item\b([^>]*?)/?>", opf, re.I):
                a = m.group(1)
                hm = re.search(r'href="([^"]+)"', a)
                if not hm:
                    continue
                tm = re.search(r'media-type="([^"]+)"', a, re.I)
                href = hm.group(1)
                media = (tm.group(1) if tm else "").lower()
                if "css" not in media and not href.lower().split("?")[0].endswith(".css"):
                    continue
                resolved = _resolve_asset(href, opf_base)
                # 只认**真的在 zip 里**的那些：OPF 声明了却缺文件的样式表不少见，
                # 报给前端一份「读了但读不到」的清单没有意义。
                if resolved and resolved in z.namelist() and resolved not in sheets:
                    sheets.append(resolved)

            seen: set = set()
            parts = [_load_css(z, n, bid, seen) for n in sheets]

            # ② 内联 `<style>`（只扫 head；正文里的那些由 `_rewrite_assets` 就地处理）。
            #    逐文档只读前 64 KB：head 在文件开头，读满会有明显的无用解压开销。
            for doc in _spine(path):
                if doc not in z.namelist():
                    continue
                try:
                    with z.open(doc) as f:
                        raw = f.read(_HEAD_SCAN_BYTES).decode("utf-8", "ignore")
                except Exception:                            # noqa: BLE001 —— 坏条目跳过
                    continue
                head = raw.split("</head>", 1)[0]
                doc_base = pathlib.PurePosixPath(doc).parent
                for sm in _STYLE_TAG_RE.finditer(head):
                    parts.append(_rewrite_css_urls(sm.group(2), doc_base, bid))

            return {"css": "\n".join(p for p in parts if p and p.strip()),
                    "sheets": sheets, "fixed_layout": _fixed_layout_of(opf)}
    except Exception:                                        # noqa: BLE001 —— 坏书当「没有样式」
        logging.getLogger("novelforge").debug("抽取书内样式失败：%s", path, exc_info=True)
        return dict(empty)


def _rewrite_assets(html: str, media: str, bid: str) -> str:
    """把正文里的相对资源改写成后端 asset 接口（第 76 期扩面）。

    覆盖真实 EPUB 出现过的写法：双引号与**单引号**属性、`srcset`（逗号分隔的多候选）、
    `<style>` 块与 `style="…"` 里的 `url(...)`。`..` 折叠、外链 / 锚 / `data:` 不动
    （判据集中在 :func:`_resolve_asset`）。

    ⚠️ 令牌**不在这里**拼（见本节开头的说明）；`<a href>` 指向章节文档时也不改写。
    """
    base = pathlib.PurePosixPath(media).parent

    def fix(m: "re.Match") -> str:
        attr, q, val = m.group(1).lower(), m.group(2), m.group(3)
        if attr == "style":
            return f"style={q}{_rewrite_css_urls(val, base, bid)}{q}"
        if attr == "srcset":
            items = []
            for piece in val.split(","):
                bits = piece.strip().split(None, 1)          # 「URL [描述符]」
                if not bits:
                    continue
                resolved = _resolve_asset(bits[0], base)
                if resolved:
                    bits[0] = _asset_url(bid, resolved)
                items.append(" ".join(bits))
            return f"srcset={q}{', '.join(items)}{q}" if items else m.group(0)
        resolved = _resolve_asset(val, base)
        if not resolved:
            return m.group(0)
        if attr == "href" and resolved.lower().endswith(_DOC_EXTS):
            return m.group(0)                                # 章节间链接，不是资源
        return f"{attr}={q}{_asset_url(bid, resolved)}{q}"

    out = _ASSET_ATTR_RE.sub(fix, html)
    return _STYLE_TAG_RE.sub(
        lambda m: f"{m.group(1)}{_rewrite_css_urls(m.group(2), base, bid)}{m.group(3)}", out)


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
        kind, reason = conflict_kind([b["name"] for b in items],
                                     [pathlib.Path(root_of(b)) / b["name"] for b in items],
                                     [b.get("library_id") for b in items])
        # 同名但不同目录 ⇒ 建议名**带上父目录名**（原来给的是没有信息量的 `X (2).cbz`）
        by_dir = kind == "same_name_different_dirs"
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
                "volume": volume_of(b["name"]),
                # 建议名只给**要改名**的那些（保留项不动）；文案与迁移侧同口径
                "suggest": "" if keep else suggest_name(b["name"], b.get("library_id"),
                                                        root_of(b), use_dir=by_dir),
            })
        out.append({
            "id": bid,
            "name": items[0]["name"],
            "title": items[0].get("title") or items[0]["name"],
            "cross_library": len(libs) > 1,
            "library_count": len(libs),
            "keep": items[0]["name"],
            # 组级结论（第 87 期）：说清「这是同一本书的两个副本 / 同名的不同书 /
            # 同一个文件被扫了两遍」——界面据此决定要不要勾选、提示怎么写。
            "kind": kind,
            "reason": reason,
            # 组级默认建议名 = 第一个待改名项的建议名（界面「一键」用它打底）
            "suggest": rows[1]["suggest"] if len(rows) > 1 else "",
            "items": rows,
        })
    # 跨库的排前面；组内书多的排前面；同档按名字稳定排序
    out.sort(key=lambda g: (not g["cross_library"], -len(g["items"]), g["name"]))
    return out


def copy_groups() -> list:
    """同一目录下的**副本**（归一化后同名）：`X Vol.01 (2).zip` 与 `X Vol.01.zip`。

    第 87 期用户口径：这类差异（`(2)` 副本后缀 / 破折号 / 全角半角 / 多余空格）
    **是同一本书**，不该被当成两本、也不该进「同名冲突」要求改名 —— 它们的 basename
    本来就不同，**没撞 id**。但它们往往意味着「同一本书下到了两遍」，
    用户真正想知道的是**多出来的那份要不要删**。所以这里把它们显式列出来，
    并给出「留哪一份」的依据（体积大者更完整），**只列不动**：
    删除不可逆，必须由用户确认。

    ⚠️ 与 `id_conflicts` 的分工（两张表**不重复报同一件事**）：
    同名冲突管「basename 逐字相同 ⇒ 撞了 id ⇒ 必须改名」；
    本表管「basename 不同但归一化相同 ⇒ 是同书副本 ⇒ 是否删多余」。
    """
    groups: dict = {}
    for b in books():
        key = (str(b.get("library_id") or ""),
               str(pathlib.PurePosixPath(str(b["name"])).parent),
               conflict_key(b["name"]))
        if key[2]:
            groups.setdefault(key, []).append(b)
    out = []
    for (lib_id, parent, ckey), items in groups.items():
        if len(items) < 2 or len({str(b["name"]) for b in items}) < 2:
            continue                      # 逐字同名的归「同名冲突」，这边不重复列
        ordered = sorted(items, key=lambda b: (-int(b.get("size") or 0), str(b["name"])))
        keep = str(ordered[0]["name"])
        out.append({
            "library_id": lib_id,
            "dir": parent,
            "key": ckey,
            "count": len(items),
            "keep": keep,
            "reason": "同一本书的副本（名字只差副本后缀 / 破折号 / 全角半角）："
                      "保留体积最大的那一份",
            "items": [{"name": b["name"], "size": b.get("size") or 0,
                       "mtime": b.get("mtime") or 0,
                       "keep": str(b["name"]) == keep} for b in items],
        })
    out.sort(key=lambda g: (-g["count"], g["dir"], g["items"][0]["name"]))
    return out


def container_books(limit: int = 200) -> list:
    """**按内容分派不出形态的容器**清单（`zipkind.CONTAINER_FORMATS`，第 87 期）：展开操作的入口。

    只列**通用容器**（`.zip` / `.rar` / `.7z`）且**没能分派出形态**的那些 —— 图片档已经
    归一成 `CBZ`（能直接读），不在此列。判据取 `zipkind.CONTAINER_FORMATS` 而不是写死
    `"ZIP"`：第 111 期加 `.rar` / `.7z` 时，写死的那一份会让它们**从待展开清单里消失**
    （文件在盘上、书架上打进不了，且界面上一个字都不提）。
    `reason` / `targets` **现算**（每次开一次归档；容器条目通常很少，
    而且这是用户主动打开的工具页，不是列表热路径）。`limit` 是防御：真遇到几百个
    容器时别让一次请求卡住界面（前端会显示实际条数）。
    """
    out = []
    for b in books():
        if str(b.get("format") or "").upper() not in zipkind.CONTAINER_FORMATS:
            continue
        plan = zipkind.unpack_plan(pathlib.Path(root_of(b)) / b["name"])
        out.append({
            "id": b.get("id") or "",
            "name": b["name"],
            "library_id": b.get("library_id"),
            "size": b.get("size") or 0,
            "unpackable": bool(plan.get("ok")),
            "reason": plan.get("reason") or "",
            "targets": [str(a.get("dest") or a.get("name") or "")
                        for a in (plan.get("actions") or [])],
        })
        if len(out) >= int(limit):
            break
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


def suggest_name(name: str, library_id=None, root=None, *, use_dir: bool = False) -> str:
    """给 ``name`` 找一个「不撞 id、目标目录里也不存在」的候选名。

    文案沿用 ``三体 (2).epub`` 那套（第 77 期前 ``core.migrate._suggest_name`` 也用它，
    那个函数随自动归库一起删了，**本函数是现在唯一的实现**）；
    这里**只建议、不自动改** —— 改名会换 ``book_id``，必须显式确认后走冲突修复
    流程（它会把关联数据一起搬，见 ``db.remap_book_id``）。

    ``use_dir=True``（第 87 期）先试**带父目录名**的候选：`科幻/Vol.01.cbz`
    → `科幻/科幻 - Vol.01.cbz`。同名但不同目录的两条本来就是**不同的书**，
    用 `(2)` 区分等于让用户以后完全看不出哪本是哪本（用户口径：`(2)` 是
    没有信息量的名字）。带目录名的候选撞了才回落到 `(N)` 那一套。
    """
    p = pathlib.PurePosixPath(str(name))
    stem, suffix, parent = p.stem, p.suffix, str(p.parent)
    cands = []
    if use_dir and parent not in ("", "."):
        cands.append(f"{pathlib.PurePosixPath(parent).name} - {stem}{suffix}")
    cands += [f"{stem} ({i}){suffix}" for i in range(2, 100)]
    for cand in cands:
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
            out["description"] = _dc_description(opf)
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

def _iter_book_entries(d: pathlib.Path, exts=None, exclude=None, ltype=None) -> list:
    """**一个书库根目录**下的书目条目（平铺 + 一层系列目录），按遍历顺序返回。

    条目有三种形态，都算「一本书」：
    - **文件**：``suffix in exts`` 的电子书 / 漫画 / **单个音频文件**；
    - **目录**：含音频文件的目录（有声书多轨，「一章一文件」）；
    - **序号单元目录**（第 73 期）：整棵子树里 ≥2 个能解析出序号的文件
      （`第1话` / `第二话` / `第03话` / `4 第4话` / `01`）⇒ **整棵树 = 一本书**，
      话清单见 :mod:`core.units`。此前这种树的文件各成一本书（更深的根本扫不到）。

    ``ltype`` 是库类型，**只用来决定要不要做序号单元合并**（`mixed` 与 `ebook` 都不做，
    见下面 ``allow_units`` 的注释）。它必须由调用方传进来：本函数拿不到库实体，
    而「哪些库要合并」是**库级**决定。两个调用点（``_scan_once`` / ``catalog``）
    都手上有库实体。

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
    # 「这个库收不收音频目录」——`collected_by` 与下面「下探一层」的那一支共用同一判据
    # （白名单含音频扩展名：漫画库不含 ⇒ 它既不把顶层音频目录当书，也不收子目录）。
    allow_audio_dir = units.audio_allowed(allowed)
    # 序号单元（第 73 期）：**只对漫画库与有声书库**合并。用户拍板的口径是「这类形态
    # 只在漫画库 / 有声书库出现」。判据（哪些文件算一话）与库类型无关，但「要不要把
    # 一棵树当成一本书」是**库的意图**：ebook 的语义就是「一个文件一本」，mixed 是
    # 「什么都收」的兜底类型 —— 在兜底类型上猜意图，猜错就是把用户几本独立的书粘成
    # 一本（那只能靠改名目录来救）。改类型即可启用，文档里写明。
    # 判据在 `units.merges_for`（搬家闸门 `migrate.compat_reason` 读同一份）。
    allow_units = units.merges_for(ltype)
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
        # 目录型条目：**整棵子树 = 一本书**。两种形态（平铺音频 / 序号单元树）与
        # 「这个库收不收」的判据全在 `units.collected_by` 一处 —— 本函数只负责加上
        # 本库的排除图案。以前这里有两份字面量判据，与 `_probe_entry` 各写各的：
        # 顺序一旦不一致（先单元还是先音频），平铺目录就会「卡片说 3 话、播放器 2 轨」。
        # ⚠️ 必须 `continue` —— 不 continue 就会继续往下探一层，把同一棵树的文件
        # 再登记成兄弟条目，于是「一本书」与「它的一话」同时出现在书架上。
        # 书边界取**最外层**通过判据的那个目录（本函数只扫库根这一层，天然满足）。
        if not _excluded(f.name, f.name, patterns) \
                and units.collected_by(f, allowed, allow_units):
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
# 第 87 期：`.zip` **三类库里都收** —— 它是通用容器，真实形态由内容分派
# （`core/zipkind.py`）。不收它就等于「某个库里看不见用户放进去的书」。
# ⚠️ 收进来 ≠ 当成漫画：里面是别的文档 / 嵌套 / 坏包时一律记「无法解析」，
# 于是它在「待修复」里看得见，而不会被静默忽略。
# 第 111 期：`.rar` / `.7z` 与 `.zip` 同一处理（漫画库收、电子书库也收 —— 里面可能是一份 EPUB）。
# 第 112 期：`.fb2` 进电子书白名单（可直读，见 `core/fb2cache.py`）。它**只归电子书**，
# 不进 `_COMIC_EXTS` —— FB2 是文字书，不是漫画。
_COMIC_EXTS = (".cbz", ".cbr", ".pdf", ".zip", ".rar", ".7z")
_EBOOK_EXTS = (".epub", ".mobi", ".azw3", ".azw", ".fb2", ".pdf", ".txt", ".zip", ".rar", ".7z")


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

    ⚠️ **没有扩展名的条目一律不拦**：「一章一文件」的**目录**形态（有声书目录 /
    第 73 期的序号单元树）在这里判不了，它扫不扫得到由 :func:`_iter_book_entries`
    的 ``allow_audio_dir`` / ``allow_units`` 按**内容与类型**决定。
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


def _dir_facts(f: pathlib.Path) -> tuple:
    """**目录型**条目的 ``(体积, mtime)`` —— 探测与闸门**共用这一处**。

    两条支路，判据都来自 `units`：

    - 序号单元树（第 73 期）⇒ ``units.dir_fingerprint``，**递归**整个子树；
    - 其余（平铺音频目录 / 空目录）⇒ ``audio.dir_size_and_mtime``，只看直接子文件
      —— 与改造前逐字一致。

    ⚠️ 递归这件事是**必须**的：改造前目录条目用的是只看直接子文件的音频口径，
    于是嵌套树里「新增了一话」在 ``(size, mtime)`` 上**完全看不见** —— 增量刷新
    不会重探，用户加了一话、书架上是 0 变化，而且不报错。它在
    `_cheap_facts` 与 `_probe_entry` 里同时生效，两边的值仍然同源。
    """
    fp = units.dir_fingerprint(f)
    if fp is not None:
        return fp[0], fp[1]
    return audio.dir_size_and_mtime(f)


def _cheap_facts(f: pathlib.Path) -> "tuple | None":
    """条目的**便宜事实** ``(size, mtime, is_dir)``：不打开文件就能拿到的全部信息。

    ⚠️ 这是增量刷新的**唯一闸门**：``catalog.refresh_library`` 拿它与索引现值比，
    相同就整段跳过、不调 :func:`_probe_entry`（那次调用要开 zip 读 OPF，
    NAS 上几十毫秒）。所以本函数与 :func:`_probe_entry` **必须同源** ——
    后者算出的 ``size``/``mtime`` 就是写进索引的那两个值。为此两边共用本函数，
    而不是各写一套公式；否则会出现「明明变了却永远不重探」这种查不出来的陈旧。

    目录条目的 ``(体积, mtime)`` 见 :func:`_dir_facts`（改造前是
    ``audio.dir_size_and_mtime`` —— 与 ``_scan_once`` 里生效的那两个值逐字节一致：
    改造前它先跑了一次 ``_entry_mtime`` 的递归 rglob，但那笔结果在本分支**必被覆盖**
    （``_iter_book_entries`` 只把「含音频文件的目录」当条目返回 ⇒ dm 恒非 0），
    所以删掉它纯粹是省下一次整子树的递归遍历，不改任何值。第 73 期把「序号单元树」
    这一支换成了真正的递归指纹 —— 只影响那一类条目）。

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
        size, dm = _dir_facts(f)
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

    目录型条目的形态由 ``units.shape_of`` 定（第 73 期）：**平铺音频目录**（含编号轨，
    改造前的全部行为逐字不变）或**序号单元树**（`一话一文件`，第 73 期新增）。
    单元树的话数记在 ``tracks`` 列（复用既有列，不新增），``format`` 按内容定 ——
    全音频仍是 ``AUDIO``（前端进播放器，嵌套有声书因此也修好了），混了 PDF / 漫画
    才是 ``UNITS``。``pages`` 对它恒为 0：本项目的 ``pages`` 是**估算页数**，
    一话一文件的树没有页的概念。

    条目不可读（``stat`` 失败）返回 ``None``，调用方跳过。
    """
    facts = _cheap_facts(f)
    if facts is None:
        return None
    size, mtime, is_dir = facts
    # 目录型条目的**形态**（第 73 期）：判据与顺序都在 `units.shape_of` 一处，
    # 枚举侧（`units.collected_by`）、`tracks_of`、增量闸门（`dir_fingerprint`）读的
    # 也是它 —— 两边各写一套判据，就会出现「卡片说 3 话、播放器只列 2 轨」。
    # 判据只读这棵树本身（`units` 不碰库级状态），与上面那条硬约束相容。
    shape = units.shape_of(f) if is_dir else ""
    unit_items = units.units(f) if shape == "units" else []
    # 音频统一成 format="AUDIO"，前端据此进播放器：单个音频文件，以及**不是**序号单元树
    # 的目录（平铺音频目录 / 空目录 / 树里的文件刚被删掉 —— 后两种走这一支才能保持与
    # 改造前逐字相同，否则空目录会掉进下面按扩展名分流的漫画分支）。
    # 全是音频话的单元树（嵌套有声书）在下面那一支里同样落到 AUDIO。
    is_audio_entry = audio.is_audio(f) or (is_dir and shape != "units")
    name_meta = metadata.from_filename(f.name)
    info = {
        "title": "", "author": "", "series": "", "has_cover": False, "unparsable": False,
        "year": "", "publisher": "", "isbn": "", "language": "", "description": "", "tags": [],
        "cover": "", "pages": 0, "pages_source": "", "series_index": "", "fixed_layout": False,
        # 演播者（第 53 期）：扫描期从音频标签解析，列表形态与 tags 同构
        "narrators": [],
    }
    tracks = 0
    fmt = f.suffix.lstrip(".").upper()
    # `.zip` 是**通用容器**（第 87 期）：真实形态由内容定（`core/zipkind.py`），不看后缀。
    # 只有「里面是图片」这一档能读，且把它**归一成 CBZ** —— 于是封面接口、逐页接口、
    # 前端阅读器的既有 CBZ 判据**全部自动生效（上层零分支）**。
    # 其余各档（内部是别的文档 / 嵌套 / 混装 / 坏包）**不假装能读**：记成无法解析，
    # 让它在「待修复」分面里看得见 —— 文件在盘上、书目里却找不到，比拒收更糟。
    zip_v = zipkind.analyze(f) if zipkind.is_container(f) else None
    if zip_v is not None:
        if zip_v["readable"]:
            fmt = zip_v["format"] or fmt
        else:
            info["unparsable"] = True
    if shape == "units":
        tracks = len(unit_items)
        # 全是音频 ⇒ 仍是 AUDIO：嵌套有声书（`《书名》/第1卷/第1话.mp3`）因此进播放器，
        # 话数就是轨数（`tracks_of` 读的也是同一份清单）；混进了 PDF / 漫画 ⇒ UNITS，
        # 前端进「按话聚合」的阅读器。
        fmt = "AUDIO" if all(it["kind"] == "audio" for it in unit_items) else "UNITS"
        # 演播者：取树内第一个**音频**话（嵌套树里首轨可能在子目录里）
        try:
            _probe = units.first_audio(f)
            if _probe is not None:
                info["narrators"] = audio_meta.extract(_probe).get("narrators") or []
        except Exception:
            info["narrators"] = []
        # 封面可能埋在子树里（`cover_in_tree` 在树根时与 `cover_in_dir` 同值）
        cover = units.cover_in_tree(f)
        info.update({"has_cover": bool(cover), "cover": cover})
    elif is_audio_entry:
        tracks = audio.tracks(f)["total"]
        fmt = "AUDIO"
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
    elif comics.is_comic(f) and (zip_v is None or zip_v["kind"] == "comic"):
        # 漫画（CBZ / CBR / ZIP 的图片档）：页数与封面都是**真实值**（不是估算），
        # pages_source = "archive"。
        # ⚠️ `.zip` 必须带上后面那条附加判据：它已经进了 `comics.COMIC_EXTS`，而
        # `is_comic` **只看后缀** —— 少了这一条，一个「内部其实是 EPUB」的 zip 也会
        # 被当成漫画去数页（数出来的是 EPUB 里的插图张数），用户看到一本假的漫画。
        info.update(comics.probe(f))
    elif f.suffix.lower() == ".fb2":
        # 第 112 期：FB2 直读 —— 扫描期只做**廉价头部扫描**判有没有内嵌封面（整本 XML 解析
        # 留给派生缓存 `fb2cache`，别把「丢一本书进库」变成一次 XML 解析）。
        from . import fb2cache
        info["has_cover"] = fb2cache.has_embedded_cover(f)

    return {
        "is_dir": is_dir,
        "size": size,
        "mtime": mtime,
        "tracks": tracks,
        "format": fmt,
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
        for f in _iter_book_entries(d, exts, patterns, lib.get("type")):
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
    # ⚠️ 第 88 期试过在这里「顺手派后台刷新」（`catalog.invalidate_and_refresh`），
    # 实测**退回**：本函数有 20+ 个调用点，点火后后台刷新会和调用方紧接着的读断言
    # 赛跑，`tests/test_catalog.py` 里连「顺序 / 序号单元目录」这两条**与契约无关**的
    # 用例都被打红（4 红）⇒ 那是 flaky 的来源，不是收益。
    # 现在的点火点只有三处、且都是**不与人抢**的位置：读路径（脏库才派，见 catalog._settle
    # 的 SETTLE_WAIT）、服务启动预热（prewarm_async）、监听线程每轮增量刷新。


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


def _toc_apply(b: dict, chapters: list) -> tuple:
    """书城目录覆盖（第 85 期批次 B）：``(结构, 每来源状态清单, 当前生效的来源)``。

    只挑**最后一次成功**的那份套用（`ok=1`）；其中**手动指定优先于自动匹配** ——
    用户亲手填的书页地址是他明确的意图，不该被一次自动匹配盖过去。

    返回的清单**不带目录负载**（只给条数）：详情页要的是「每个来源现在什么状态」，
    把整份书城目录再回传一遍纯属浪费带宽。
    """
    from ..sources import toc_sources        # 延迟导入：core 不在模块级反向依赖 sources
    book_id = b.get("id") or ""
    if not book_id:
        return chapters, [], ""
    items, best = [], None
    for raw in db.store_toc_get(book_id):
        entries = raw.get("entries") or []
        # ⚠️ 给界面用的那份**另建**一个 dict：`entries` 是覆盖层的输入，
        # 不能在「顺手瘦身清单」时把它 pop 掉 —— 那样映射照样落库、目录却一点不生效，
        # 而且两边看着都正常（本轮实测踩过）。
        item = {k: v for k, v in raw.items() if k != "entries"}
        item["label"] = (toc_sources.by_id(raw["source"]) or {}).get("label", raw["source"])
        item["state"] = toc_sources.state_note(toc_sources.by_id(raw["source"]) or {})
        item["mapped"] = len(db.toc_map_get(book_id, raw["source"]))
        item["entry_count"] = len(entries)
        items.append(item)
        if raw["ok"]:
            rank = (1 if raw["manual"] else 0, float(raw["fetched_at"] or 0))
            if best is None or rank > best[0]:
                best = (rank, raw)          # 留住**原行**（含 entries）给覆盖层用
    if best is None:
        return chapters, items, ""
    row = best[1]
    return reading_list.apply_toc_override(
        chapters, row.get("entries") or [], db.toc_map_get(book_id, row["source"])), items, row["source"]


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
        # 第 110 期：MOBI / AZW3 / AZW **直读**（解包，不转换，见 `core/mobicache.py`）。
        # KF8 路线的目录与真 EPUB 同源 —— `mobicache.chapters` 内部就是拿解包出的 EPUB
        # 喂 :func:`_reading_list`，所以目录 / 批注 / 进度的坐标系与 EPUB 完全一致。
        #
        # ⚠️ 延迟导入**必须在本分支的第一行**：写成 `elif suffix in mobicache.EXTS:` 的话，
        # 函数里那句 `from . import mobicache` 会把 `mobicache` 变成**局部名**，而条件表达式
        # 先求值 ⇒ `UnboundLocalError`（实测在详情接口上全线 500）。扩展名清单仍只认
        # `mobicache.EXTS` 这一处真值源，所以判据放在导入之后。
        from . import fb2cache, mobicache   # 延迟导入：本模块顶层 import 它们会与它们反向依赖
        if suffix in mobicache.EXTS:
            chapters = mobicache.chapters(b, path=path, root=root)
        elif suffix in fb2cache.EXTS:
            # 第 112 期：FB2 **直读**（解析后归一成派生 EPUB，见 `core/fb2cache.py`）——
            # 目录与真 EPUB 同源（`fb2cache.chapters` 内部就是拿派生 EPUB 喂 :func:`_reading_list`）。
            chapters = fb2cache.chapters(b, path=path, root=root)
        else:
            chapters = []
    # 第 85 期批次 B：本地目录「不清楚」时，套用正版书城取回的那份（只改标题与卷名）
    chapters, toc_items, toc_applied = _toc_apply(b, chapters)
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
    # 书城目录来源（第 85 期批次 B）：`toc_applied` 空串 = 当前用的是本地目录。
    # 清单随详情下发，详情页的「目录来源」区块不必再发一次请求。
    detail["toc_sources"] = toc_items
    detail["toc_applied"] = toc_applied
    fmt = (b.get("format") or "").upper()
    # 有声书：把轨道清单随详情一起下发，播放器首屏无需再发一次请求。
    # 第 73 期起走 `units.tracks_of` —— 嵌套有声书（`《书名》/第1卷/第1话.mp3`）的轨
    # 在子目录里，`audio.tracks` 只看直接子文件、会给 0 条。平铺目录两处同值。
    if fmt == "AUDIO":
        detail["audio_tracks"] = units.tracks_of(path)["items"]
    # 序号单元（第 73 期）：话清单随详情下发，与 `audio_tracks` 同一个道理
    elif fmt == "UNITS":
        detail["units"] = units.units(path)
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
