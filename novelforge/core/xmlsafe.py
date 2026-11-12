"""不可信 XML 的解析入口（第 292 期）：拒绝内部实体声明，防实体膨胀吃内存。

## 为什么要有这个模块

项目要解析大量**外部不可信** XML：EPUB 的 `container.xml` / OPF / SMIL、FB2、播客 RSS、
OPML、用户上传的 SVG 图标。`xml.etree.ElementTree` 对实体膨胀有两道保护，但**都不够**：

- 未定义实体 ⇒ `ParseError`（安全）；
- 内部实体展开有「输出 / 输入放大比」上限（实测 Python 3.12 在约 4 万倍时抛
  ``limit on input amplification factor (from DTD and entities) breached``）。

⚠️ **放大比可以被稀释**：实测同一份「10^5 实体 × 100 次引用」的炸弹，
743 B 输入被拦；在 DOCTYPE 后**垫 1 MB 注释**（比值降到 30 倍）就**放行**，
3 秒展开 30 MB。而本项目的单个 zip 条目上限是 128 MB（`comics.MAX_ENTRY_BYTES`）、
RSS 上限 8 MB ⇒ 一份精心构造的 OPF / RSS 就能在**自动扫描 / 订阅刷新**时把进程内存打爆。

## 判据

**含 `<!ENTITY` 声明的一律拒绝**（XML 关键字大小写敏感，DOCTYPE 内部子集里的声明
必然写成大写）。理由：

- 正常 EPUB（EPUB3；EPUB2 的 `<!DOCTYPE ... PUBLIC ...>` 没有内部实体）/ RSS / OPML /
  FB2 **不需要**自定义实体；
- 预定义实体（`&amp;` 等）与外部 DTD 引用（`<!DOCTYPE ... PUBLIC ...>`，本就不加载）
  不受影响；
- 失败是**可解释的**（`ParseError` ⇒ 现有的「这本书读不了」路径），而不是进程被 OOM 杀掉。

外部实体（`SYSTEM "file://…"`）在 stdlib ET 下本就不解析；lxml 5+ 的默认
`resolve_entities=False` 也不解析 —— 本模块只负责把**内部实体膨胀**这条堵死。
⚠️ **判据必须先于任何解析器动作**：调用方自己用正则剥 DOCTYPE 的（`fb2cache` /
`epub_cfi`）要在**剥之前**问这里，否则 `<!ENTITY` 已经被切碎、查不出来。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

#: 内部实体声明的字面量。XML 关键字大小写敏感；DOCTYPE 内部子集里的声明只写成大写。
_ENTITY_DECL = "<!ENTITY"
_ENTITY_DECL_B = b"<!ENTITY"


def ensure_no_entities(data) -> None:
    """文档里出现内部实体声明就抛 :class:`ET.ParseError`（与解析失败走同一条路径）。

    对 ``str`` / ``bytes`` 都生效；**只查子串**、不做 XML 解析 —— 判据必须先于任何
    可能展开实体的解析器动作。
    """
    unsafe = (_ENTITY_DECL in data if isinstance(data, str)
              else _ENTITY_DECL_B in bytes(data))
    if unsafe:
        raise ET.ParseError(
            "拒绝解析带内部实体声明（<!ENTITY）的 XML：实体膨胀防护（见 core/xmlsafe.py）")


def fromstring(data):
    """不可信 XML 的**唯一**解析入口：先查实体声明，再交给 ``ET.fromstring``。"""
    ensure_no_entities(data)
    return ET.fromstring(data)
