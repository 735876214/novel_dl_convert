"""Komga 库布局：**系列推断** + **目标相对路径**。

Komga（漫画/电子书服务器）扫描库根目录，结构约定决定了本模块的全部规则：

- **一层系列目录**：``库根/系列名/书文件``。Komga **不会递归** Series 文件夹的子目录
  （放两层，文件会被当成不存在或被打散）——所以本模块产出的路径**最多一层**目录。
- **一个目录 = 一个系列**，目录内的多个文件 = 该系列的多个「书（卷）」。
- **卷号从文件名解析**：``系列 #1.cbz`` / ``系列 v01.cbz`` / ``系列 第01卷.cbz`` /
  ``系列 (01).cbz`` 都能识别；解析不到就按文件名自然序当卷序。
- 无系列的书**保持平铺**：Komga 会把单个文件当成一个独立系列，这是合理结果 ——
  比硬塞进一个猜错的系列目录要好。

系列信息有两个来源，优先级从高到低：

1. **文件内元数据**（EPUB 的 ``calibre:series`` / ``calibre:series_index``）—— 权威，
   扫描时由 ``library.probe_epub`` 读出。
2. **文件名推断** —— 本项目转换产出的 EPUB **没有**系列元数据（``epub_builder`` 不写
   ``series``），外部来的 CBZ 漫画也多半只有文件名可依，所以这条路径是主力。

推断刻意**保守**：宁可判不出（保持平铺）也不要把不相干的书凑成一个系列 ——
分错组会让用户去 Komga 里手工收拾，比平铺更麻烦。
"""
import pathlib
import re

#: 能识别的「系列 + 卷号」文件名形态（按优先级）。全部要求卷号在**结尾**，
#: 避免把「三体 2 体」这类中间带数字的书名误切。
_SERIES_PATTERNS = (
    # 系列 第01卷 / 第3册 / 第2集 / 第4部 / 第5话 / 第6回
    re.compile(r"^(?P<s>.+?)[\s_\-—]*第\s*(?P<i>\d{1,3})\s*[卷册集部话回]$"),
    # 系列 #1 / 系列 vol.1 / 系列 v01
    re.compile(r"^(?P<s>.+?)[\s_\-—]*(?:#|vol\.?|v)\s*(?P<i>\d{1,3})$", re.I),
    # 系列 (01) / 系列 [01]
    re.compile(r"^(?P<s>.+?)[\s_\-—]*[\(\[]\s*(?P<i>\d{1,3})\s*[\)\]]$"),
    # 系列 - 01 / 系列_01（纯数字结尾）
    re.compile(r"^(?P<s>.+?)[\s_\-—]+(?P<i>\d{1,3})$"),
)

#: 跨平台不安全的文件名字符（与 fileops._BAD_CHARS 同规则）
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_BAD_TAIL = re.compile(r"[. ]+$")
#: 系列名最短长度：1 个字符多半是误切（如「A 01」）
_MIN_SERIES_LEN = 2
#: 卷号上限：超过基本是年份/编号而非卷号（如「系列 2024」）
_MAX_INDEX = 300


def clean_segment(text: str) -> str:
    """清洗成安全的**路径段 / 文件名主干**。

    与 ``fileops.sanitize_stem`` 同规则，但**故意不共用**：
    ``fileops`` 依赖 ``library``，而布局计算要能被 ``pipeline`` 直接调用，
    共用会引入 fileops↔pipeline 的耦合。
    """
    s = _BAD_CHARS.sub("", (text or "").strip())
    s = _BAD_TAIL.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def infer(stem: str, meta_series: str = "", meta_index: str = "") -> tuple:
    """推断 ``(系列名, 卷号)``；判不出系列时返回 ``("", "")``。

    卷号统一成「无前导零」的字符串（``01`` → ``1``），因为 Komga 对 ``#1`` 的解析最稳。
    """
    s = (meta_series or "").strip()
    if s:
        return clean_segment(s), normalize_index(meta_index)

    text = (stem or "").strip()
    if not text:
        return "", ""
    for rx in _SERIES_PATTERNS:
        m = rx.match(text)
        if not m:
            continue
        base = clean_segment(m.group("s"))
        idx = normalize_index(m.group("i"))
        if len(base) < _MIN_SERIES_LEN or not idx or int(idx) > _MAX_INDEX:
            continue
        return base, idx
    return "", ""


def normalize_index(value) -> str:
    """卷号归一化：``"01"`` → ``"1"``、``"0"`` → ``""``（0 卷无意义，当作没有）。"""
    v = str(value or "").strip()
    if not v.isdigit():
        return ""
    n = int(v)
    return "" if n <= 0 else str(n)


def relpath_for(stem: str, ext: str, series: str, index: str, layout: str = "flat") -> str:
    """书的**相对路径**（相对 ``OUTPUT_DIR``，用 ``/`` 分隔）。

    - ``layout='flat'`` 或无系列 → 平铺（``书名.epub``），与原行为一致。
    - ``layout='komga'`` 且有系列 → ``系列名/系列名 #N.ext``。
      有卷号时**用系列名重命名**（Komga 靠它解析卷号）；无卷号时保留原书名，
      免得把「三体全集」这类单本硬改成系列名。
    """
    ext = (ext or "").lstrip(".")
    stem = clean_segment(stem) or "untitled"
    if layout != "komga":
        return f"{stem}.{ext}"
    seg = clean_segment(series)
    if not seg:
        return f"{stem}.{ext}"
    idx = normalize_index(index)
    name = f"{seg} #{idx}.{ext}" if idx else f"{stem}.{ext}"
    return f"{seg}/{name}"


def relpath_for_dir(name: str, series: str, index: str, layout: str = "flat") -> str:
    """**目录型书目**（有声书目录）的相对路径：与 :func:`relpath_for` 同规则，但不带扩展名。

    目录名本身就是装音轨的容器，硬加 ``.audio`` 这类伪扩展名只会让磁盘上的目录名变脏。
    """
    seg = clean_segment(series)
    stem = clean_segment(name) or "untitled"
    if layout != "komga" or not seg:
        return stem
    idx = normalize_index(index)
    return f"{seg}/{seg} #{idx}" if idx else f"{seg}/{stem}"


def series_dir(relpath: str) -> str:
    """相对路径所属的系列目录名（平铺时为空串）。"""
    p = pathlib.PurePosixPath(str(relpath))
    return p.parent.name if len(p.parts) > 1 else ""
