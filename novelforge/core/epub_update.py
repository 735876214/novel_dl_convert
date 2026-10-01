"""EPUB 增量写回：**逐条复制既有条目 + 追加新章**（第 86 期第 6 步）。

## 这个模块存在的唯一理由

追更必须做到「**既有条目一字不动**」：进度 / 批注 / 书签 / 阅读会话全都按
`(book_id, 条目 index)` 记录，只要既有条目的**编号、顺序、内容**都不变，新章节追加在后，
那些阅读数据就**不需要做任何迁移**。反过来，一旦实现成「重新生成整本 EPUB」，
条目顺序或内容有一丝漂移，用户的进度与批注就会整体错位 —— 而且**不会报错**。

所以本期**只做增量追加这一条路**，不做「重建 + 前 N 章一致」的退化路径：
后者看着更简单，但它把「字节一致」变成了「我们希望一致」。

## 三条不变量（测试逐条钉住）

1. **既有条目按原顺序原样复制**：内容字节、`compress_type`、`date_time` 全部保持；
2. **`mimetype` 仍然排在第一条且不压缩**（EPUB 规范要求，改了就有些阅读器直接拒收）；
3. **原子替换**：先写同目录 `.part` 再 `Path.replace` —— 与「源不可变、副本禁原地写」
   同一条纪律。中途失败只会留下 `.part`，既有文件一字不动。

⚠️ 「字节不变」的口径说清楚：我们保持的是**解压后的内容字节**与上述元数据。
重新压缩出的 deflate 流不保证与原来逐位相同（那由 zlib 版本决定，不是我们能承诺的），
但阅读器与阅读数据看到的**条目内容与顺序**完全一致。
"""
from __future__ import annotations

import pathlib
import zipfile

#: EPUB 规范：mimetype 必须是第一条且不压缩
MIMETYPE = "mimetype"
_STORED = zipfile.ZIP_STORED


def _write_entry(zf: zipfile.ZipFile, name: str, data: bytes, *, template=None,
                 compress_type: int = zipfile.ZIP_DEFLATED) -> None:
    """写一条：能沿用模板的元数据就沿用（`date_time` / `external_attr`），保证不变。"""
    info = zipfile.ZipInfo(str(name), date_time=getattr(template, "date_time", None)
                           or (1980, 1, 1, 0, 0, 0))
    info.compress_type = int(getattr(template, "compress_type", compress_type))
    info.external_attr = int(getattr(template, "external_attr", 0o600 << 16))
    info.internal_attr = int(getattr(template, "internal_attr", 0))
    info.create_system = int(getattr(template, "create_system", 0))
    zf.writestr(info, data)


def copy_with_extra(src, dst, *, extra=None, replace=None) -> pathlib.Path:
    """把 ``src`` 的条目**按原顺序原样**复制到 ``dst``，再追加 ``extra``。

    · ``extra``   = ``[(arcname, bytes), ...]``，**追加在末尾**（新章就在书的后面）；
    · ``replace`` = ``{arcname: bytes}``，**就地替换**某些条目的内容（重写 OPF / nav 用）；
      未在其中的条目一律从 ``src`` 原样复制。
    返回 ``dst``（原子替换完成后的正式路径）。
    """
    src, dst = pathlib.Path(src), pathlib.Path(dst)
    extra = list(extra or [])
    replace = dict(replace or {})
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".part")
    with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w") as zout:
        # 第一条必须先写（EPUB 规范），且保持 STORED
        names = zin.namelist()
        first = names[0] if names else ""
        if first == MIMETYPE:
            _write_entry(zout, MIMETYPE, zin.read(MIMETYPE), template=zin.getinfo(MIMETYPE),
                         compress_type=_STORED)
        for info in zin.infolist():
            if info.filename == MIMETYPE or info.is_dir():
                continue
            data = replace.get(info.filename)
            if data is None:
                data = zin.read(info.filename)
            _write_entry(zout, info.filename, data, template=info)
        for name, data in extra:
            _write_entry(zout, name, data)
    tmp.replace(dst)
    return dst


# ---------------- 新章要在三处 XML 里「登记」（纯函数，可单独验死）----------------
# 为什么先做这三个函数：追更的成败最终取决于**这三处字符串手术**是否做对 ——
# 少登记一处，表现是「新章抓下来了、文件也在包里，但阅读器翻不到它」（或目录里看不见），
# 从现象几乎无法反推是哪一处漏了。所以把它们拆成纯函数、单独测。
#
# 落点由真机 dump 决定（见 `.codebuddy/memory` 里「章节级 API 的结构基线」）：
# ebooklib 产物是 EPUB/content.opf + EPUB/c%04d.xhtml + EPUB/nav.xhtml + EPUB/toc.ncx。

def _insert_before(text: str, anchor: str, fragment: str, *, what: str, last: bool = False) -> str:
    """在锚点前插入片段；**找不到就响亮报错**（绝不静默无动作）。

    「静默无动作」在这里是最坏的失败形态：条目照样追加、包照样生成、一切看着都成功，
    只是读者翻不到新章。宁可当场炸。
    """
    i = text.rfind(anchor) if last else text.find(anchor)
    if i < 0:
        raise ValueError(f"EPUB 结构不符合预期：找不到{what}（锚点 {anchor!r}）")
    return text[:i] + fragment + text[i:]


def add_manifest_item(opf: str, *, href: str, item_id: str) -> str:
    """OPF 的 ``<manifest>`` 里登记新章（不登记 ⇒ 阅读器不认这个文件）。"""
    return _insert_before(
        opf, "</manifest>",
        f'<item href="{href}" id="{item_id}" media-type="application/xhtml+xml"/>',
        what="manifest 的 </manifest>")


def add_spine_itemref(opf: str, *, item_id: str) -> str:
    """OPF 的 ``<spine>`` 里**追加在末尾**（既有章节顺序不变 ⇒ 阅读数据的 index 不漂移）。"""
    return _insert_before(opf, "</spine>", f'<itemref idref="{item_id}"/>',
                          what="spine 的 </spine>")


def add_nav_link(nav: str, *, href: str, title: str) -> str:
    """`EPUB/nav.xhtml` 的**目录** ``<ol>`` 末尾追加一条链接（EPUB3 阅读器靠它显示目录）。

    ⚠️ 必须先**定位到目录那个 `<nav>`**（`epub:type="toc"`）再找它的 `</ol>`：
    一个 nav.xhtml 里可以有多个 `<ol>`（`landmarks` / `page-list` 若排在 toc 之前，
    直接找第一个 `</ol>` 会把章节链接插进「地标」列表 —— 阅读器目录里看不到，
    而「nav 里含这条链接」的断言照样会过，是典型的**静默插错位置**）。
    找不到 `epub:type="toc"` 时才退回「第一个 `</ol>`」的旧口径（那样至少有得用）。
    """
    frag = f'<li><a href="{href}">{title}</a></li>'
    pos = _toc_ol_close(nav)
    if pos is None:
        return _insert_before(nav, "</ol>", frag, what="nav.xhtml 的 </ol>")
    return nav[:pos] + frag + nav[pos:]


def _toc_ol_close(nav: str) -> "int | None":
    """目录 ``<ol>`` 的闭合位置（在 `<nav epub:type="toc">` 块内取**最后**一个 `</ol>`）。

    返回 ``None`` = 认不出目录块（调用方退回旧口径）。
    """
    idx = nav.find('epub:type="toc"')
    if idx == -1:
        idx = nav.find("epub:type='toc'")
    if idx == -1:
        return None
    end = nav.find("</nav>", idx)
    if end == -1:
        return None
    pos = nav.rfind("</ol>", idx, end)
    return pos if pos != -1 else None


def add_ncx_navpoint(ncx: str, *, href: str, title: str, play_order: int) -> str:
    """`EPUB/toc.ncx` 的 ``<navMap>`` 末尾追加 navPoint（EPUB2 阅读器仍读 NCX）。"""
    frag = (f'<navPoint id="navPoint-{int(play_order)}" playOrder="{int(play_order)}">'
            f"<navLabel><text>{title}</text></navLabel>"
            f'<content src="{href}"/></navPoint>')
    return _insert_before(ncx, "</navMap>", frag, what="toc.ncx 的 </navMap>")


_CHAPTER_RE_SRC = r"EPUB/c(\d{4})\.xhtml$"


def chapter_xhtml(title: str, body_html: str, *, lang: str = "zh") -> bytes:
    """按 ebooklib 既有章节的**同一模板**生成新章 XHTML（第 86 期）。

    ⚠️ 模板是从真产物的字节里取下来的（`EPUB/c0000.xhtml`），**不是自创的**：
    同一本书里混两种模板，会被某些阅读器区别对待（样式/目录识别不一致），
    而这种问题只在「追更之后」才出现，最难归因。
    """
    from xml.sax.saxutils import escape
    t = escape(str(title or ""))
    body = "\n".join(("    " + ln) if ln.strip() else "" for ln in str(body_html or "").splitlines())
    return (f"<?xml version='1.0' encoding='utf-8'?>\n<!DOCTYPE html>\n"
            f'<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"'
            f' epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/#"'
            f' lang="{lang}" xml:lang="{lang}">\n  <head>\n    <title>{t}</title>\n  </head>\n'
            f"  <body>\n    <h2>{t}</h2>\n{body}\n  </body>\n</html>\n").encode("utf-8")


def append_chapters(epub, chapters, *, lang: str = "zh") -> dict:
    """把新章**追加**进既有 EPUB（**既有条目一字不动**，本函数就是第 6 步的落点）。

    · `chapters` = ``[{"title": str, "body_html": str}, ...]``（按阅读顺序）；
    · 新章编号从**既有最大章号 + 1** 续（`EPUB/c%04d.xhtml` + manifest id `chapter_%d`，
      与 ebooklib 的既有命名一致；见 `.codebuddy/memory` 的结构基线）；
    · **原地原子替换**：先写 `.part` 再 `Path.replace` —— 中途失败既有文件一字不动；
    · 返回 ``{"path", "added", "start_index"}`` 供调用方如实报「新增 N 章」。

    ⚠️ 只登记**三处**（OPF manifest/spine + nav + NCX），其余条目由 :func:`copy_with_extra`
    原样搬运 —— 「既有章节的编号、顺序、内容一字不动」是阅读数据（进度/批注）不漂移的**根据**。
    """
    import re
    epub = pathlib.Path(epub)
    if not chapters:
        return {"path": epub, "added": [], "start_index": None}
    with zipfile.ZipFile(epub) as z:
        names = z.namelist()
        opf_path = next((n for n in names if n.endswith(".opf")), "")
        nav_path = next((n for n in names if n.endswith("nav.xhtml")), "")
        ncx_path = next((n for n in names if n.endswith(".ncx")), "")
        if not opf_path:
            raise ValueError("这个 EPUB 里找不到 OPF（不是标准结构，拒绝改）")
        nums = [int(m.group(1)) for m in (re.search(_CHAPTER_RE_SRC, n) for n in names) if m]
        start = (max(nums) + 1) if nums else 0
        opf = z.read(opf_path).decode("utf-8")
        nav = z.read(nav_path).decode("utf-8") if nav_path else ""
        ncx = z.read(ncx_path).decode("utf-8") if ncx_path else ""
    play = ncx.count("<navPoint") + 1
    extra: list = []
    added: list = []
    for i, ch in enumerate(chapters):
        n = start + i
        href = f"c{n:04d}.xhtml"
        item_id = f"chapter_{n}"
        extra.append((f"EPUB/{href}", chapter_xhtml(ch.get("title", ""), ch.get("body_html", ""),
                                                    lang=lang)))
        opf = add_spine_itemref(add_manifest_item(opf, href=href, item_id=item_id),
                                item_id=item_id)
        if nav:
            nav = add_nav_link(nav, href=href, title=str(ch.get("title", "")))
        if ncx:
            ncx = add_ncx_navpoint(ncx, href=href, title=str(ch.get("title", "")), play_order=play)
            play += 1
        added.append(f"EPUB/{href}")
    replace = {opf_path: opf.encode("utf-8")}
    if nav_path and nav:
        replace[nav_path] = nav.encode("utf-8")
    if ncx_path and ncx:
        replace[ncx_path] = ncx.encode("utf-8")
    copy_with_extra(epub, epub, extra=extra, replace=replace)
    return {"path": epub, "added": added, "start_index": start}


def verify_unchanged(src, dst, *, added=(), replaced=()) -> list:
    """校验 ``dst`` 相对 ``src`` **只多了 ``added`` / 只改了 ``replaced``**。

    返回**违规清单**（空 = 通过）。逐条核对：顺序、内容字节、`compress_type`、`date_time`。
    这是「既有条目一字不动」这条硬约束的**可执行判据** —— 有了它，
    「我做的是增量追加」就不是一句承诺，而是一次断言。
    """
    added, replaced = set(added), set(replaced)
    problems: list = []
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        old, new = a.namelist(), b.namelist()
        if new[:len(old)] != old:
            return [f"既有条目顺序/内容名变了：{old} → {new[:len(old)]}"]
        if set(new[len(old):]) != added:
            problems.append(f"追加的条目与预期不符：{new[len(old):]} ≠ {sorted(added)}")
        if old and old[0] != MIMETYPE:
            problems.append("源文件本身就不是 mimetype 打头")
        if MIMETYPE in new and new[0] != MIMETYPE:
            problems.append("mimetype 不在第一条（EPUB 规范要求）")
        if MIMETYPE in new and b.getinfo(MIMETYPE).compress_type != _STORED:
            problems.append("mimetype 被压缩了（EPUB 规范要求 STORED）")
        for name in old:
            if name in replaced:
                continue
            ia, ib = a.getinfo(name), b.getinfo(name)
            if ia.compress_type != ib.compress_type or ia.date_time != ib.date_time:
                problems.append(f"{name}: 元数据变了（compress/date）")
            if a.read(name) != b.read(name):
                problems.append(f"{name}: 内容字节变了")
    return problems
