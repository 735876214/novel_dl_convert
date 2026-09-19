"""刮削出版：把刮削结果落到**硬链接副本**，源文件永不被改动。

为什么要「硬链接 + 写副本」而不是直接改源 EPUB：用户要求「不改变原有书籍的信息」，
同时又要让外部阅读器（Komga 等）读到整理完成的书。硬链接让副本与源**共享数据块**
（不额外占盘、内容即源文件的原始内容），刮削结果再写进副本 —— 源的 inode 与字节
始终与下载时一致。

⚠️ 三条硬约束（改这个模块前先读）：

1. **源文件只读**：只 ``open`` 读取；永不 ``unlink`` / ``move`` / 原地写源文件。
2. **副本禁止原地写**：硬链接副本与源**共享 inode**，``open(dst, "wb")`` 会经由同一
   inode 把源文件一起改坏。写元数据 / 封面一律走 :func:`fileops.rewrite_epub`
   （内部「临时文件 + ``Path.replace``」——替换的是**副本的目录项**，源 inode 不受影响）。
3. **删除即回收**：废弃 / 冲突 / 孤儿副本一律 ``shutil.move`` 进 ``CACHE_DIR/recycle``，
   **禁用 unlink**（与 :mod:`fileops` 同一条约定，唯一例外是 rewrite_epub 内部的
   ``.tmp-epub`` 失败清理）。

副本落点由**每库**的 ``libraries.publish_path`` 决定（新建书库时手动选择，空 = 不出版）。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import time

from . import fileops, komga, library

#: 副本的生成方式：硬链接（首选）/ 复制（文件系统不支持硬链接时的回退）
LINK_HARD = "hardlink"
LINK_COPY = "copy"

#: 能把元数据 / 封面**内嵌**进副本的格式；其它格式只产出副本（页面标注「不可内嵌」）
EMBED_EXTS = (".epub",)

#: 同名冲突时的编号上限（超过基本是配置炸了，早失败早发现）
_MAX_DUP = 100


# ---------------- 落点 ----------------

def publish_dir(library_id) -> "pathlib.Path | None":
    """该库的成品目录；未配置（空串）返回 ``None``。"""
    lib = library.get_library(library_id) or {}
    raw = str(lib.get("publish_path") or "").strip()
    return pathlib.Path(raw) if raw else None


def _index_text(book: dict) -> str:
    """``{index}`` 的取值：优先该书**自己的系列卷号**（``series_index``），
    其次调用方塞的 ``seq``（本库顺序），最后 ``01``。

    与批量改名的 ``{index}``（本次范围内的流水号）**语义不同** —— 出版要的是
    「这本书是第几卷」，不是「今天刮到第几本」；流水号会让文件名每刮一次就变。
    """
    for raw in (book.get("series_index"), book.get("seq")):
        s = str(raw or "").strip()
        if s.isdigit() and int(s) > 0:
            return f"{int(s):02d}"
    return "01"


def fill_pattern(pattern: str, book: dict, ext: str = "") -> str:
    """展开命名规则占位符 —— 缺省值与扩展名口径与 ``fileops.plan_pattern_rename``
    一致（{title} 退化到文件名、{author} → 未知、{series} → 无系列、扩展名不带点），
    避免两处解释不一致改错名字。
    """
    stem = pathlib.PurePosixPath(str(book.get("name") or "")).stem
    e = (ext or pathlib.Path(str(book.get("name") or "")).suffix).lstrip(".")
    filled = (
        str(pattern or "")
        .replace("{title}", str(book.get("title") or "") or stem)
        .replace("{author}", str(book.get("author") or "") or "未知")
        .replace("{series}", str(book.get("series") or "") or "无系列")
        .replace("{index}", _index_text(book))
        .replace("{ext}", e)
    )
    return fileops.sanitize_stem(filled)


def relpath_for(book: dict, cfg: dict = None) -> str:
    """副本在**成品目录**下的相对路径（``/`` 分隔）。

    ``cfg`` 传 ``lib_settings.config_for(该库)``：于是命名规则与落盘布局都是**该库的
    生效值**（每库覆写 ?? 全局），这正是「针对不同书库手动调整命名规则」的落点。
    """
    name = str(book.get("name") or "")
    ext = pathlib.Path(name).suffix
    stem = pathlib.PurePosixPath(name).stem
    naming = (cfg or {}).get("naming") or {}
    pattern = str(naming.get("pattern") or "").strip()
    scope = str(naming.get("scope") or "all").strip().lower()
    # scope 限定「规则适用于哪些格式」：不在范围内就保留原文件名
    in_scope = scope in ("", "all", ext.lstrip(".").lower())
    if pattern and in_scope:
        stem = fill_pattern(pattern, book, ext) or stem
    layout = str(((cfg or {}).get("output") or {}).get("layout") or "flat")
    rel = komga.relpath_for(stem, ext, str(book.get("series") or ""),
                            str(book.get("series_index") or ""), layout)
    # 一层子目录（系列）是 Komga 的硬要求，但**不允许**规则里塞进多级路径
    parts = pathlib.PurePosixPath(rel).parts
    if len(parts) > 2 or any(p in ("..", "") for p in parts):
        return komga.relpath_for(stem, ext, "", "", "flat")
    return rel


# ---------------- 链接 ----------------

def same_file(a, b) -> bool:
    """两路径是否指向同一 inode（判断副本是否**仍是我们建的硬链接**）。"""
    try:
        sa, sb = os.stat(a), os.stat(b)
    except OSError:
        return False
    return sa.st_dev == sb.st_dev and sa.st_ino == sb.st_ino


def link_or_copy(src, dst) -> str:
    """硬链接 ``src`` → ``dst``；文件系统不支持时回退复制。返回 link_mode。

    跨设备（``EXDEV``）、不支持硬链接的挂载（``EPERM`` / ``EOPNOTSUPP``）、
    以及某些 NAS 的 CIFS 挂载都会落到回退分支 —— **回退是常态而非异常**，
    故只记 mode 不报错（页面据实标注「硬链接 / 复制」）。
    """
    src, dst = str(src), str(dst)
    try:
        os.link(src, dst)
        return LINK_HARD
    except (OSError, NotImplementedError, AttributeError):
        pass
    shutil.copy2(src, dst)
    return LINK_COPY


def recycle(path, why: str = "") -> "pathlib.Path | None":
    """把文件/目录移入回收站（带时间戳前缀、重名加序号）。**不 unlink**。

    ``why`` 只用于返回给调用方记日志；不写进文件名，免得文件名长到看不清。
    """
    p = pathlib.Path(path)
    if not p.exists():
        return None
    dest_dir = fileops.recycle_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dst = dest_dir / f"{stamp}_{p.name}"
    n = 1
    while dst.exists():
        dst = dest_dir / f"{stamp}_{n}_{p.name}"
        n += 1
    shutil.move(str(p), str(dst))
    return dst


def source_sig(path) -> list:
    """源文件指纹 ``[size, mtime_ns]``：变了就重刮，源没变就跳过（幂等）。"""
    try:
        st = os.stat(str(path))
        return [int(st.st_size), int(st.st_mtime_ns)]
    except OSError:
        return [0, 0]


# ---------------- 写入副本 ----------------

def embed_meta(dst, updates: dict = None, cover=None) -> list:
    """把元数据 / 封面写进**副本**（原子替换，源文件不受影响）。返回写入的字段名。

    ``cover`` 传 ``(bytes, media_type)``；``None`` = 不动封面（源文件自带的封面
    会随硬链接一起被外部阅读器读到，无需重写）。
    """
    ups = {k: v for k, v in (updates or {}).items()
           if k in fileops.METADATA_FIELDS and v not in ("", None, [])}
    add_files = None
    href = mt = ""
    if cover:
        data, mt = cover
        opf_path, _, _ = fileops._read_epub(dst)
        if not opf_path:
            raise ValueError("副本没有可定位的 OPF")
        zip_rel, href = fileops.cover_paths(mt, opf_path)
        add_files = {zip_rel: data}
    if not ups and not add_files:
        return []

    def _transform(opf, _u=ups, _h=href, _m=mt):
        out = fileops.patch_opf_meta(opf, _u)
        if _h:
            out = fileops.set_epub_cover(out, _h, _m)
        return out

    if not fileops.rewrite_epub(dst, transform=_transform, add_files=add_files):
        raise ValueError("副本写入失败（只读或损坏）")
    return sorted(ups.keys())


def _free_rel(pdir: pathlib.Path, rel: str) -> str:
    """目标已被**非本系统生成**的文件占用时，找一个不冲突的新名字。

    绝不静默覆盖用户自己的文件 —— 成品目录是给人看的普通目录，用户完全可能往
    里面放东西。冲突时退让（``书名 (2).epub``）比覆盖安全。
    """
    p = pathlib.PurePosixPath(rel)
    for n in range(2, _MAX_DUP):
        # PurePosixPath 会把 '.' 段折叠掉，平铺（无系列目录）时父目录自然消失
        cand = str(p.parent / f"{p.stem} ({n}){p.suffix}")
        if not (pdir / cand).exists():
            return cand
    raise ValueError(f"同名副本过多，无法出版：{rel}")


def publish(book: dict, *, cfg: dict = None, updates: dict = None, cover=None,
            prev_rel: str = "") -> dict:
    """把一本书出版到该库的成品目录。**不抛异常**（调用方是队列，失败要落库）。

    返回 ``{ok, rel, path, mode, shared, embedded, cover, error, skipped}``：

    - ``ok=False`` + ``error``：失败原因（源不存在 / 成品目录不可用 / 写副本失败…）
    - ``skipped=True``：该库没配成品目录，或格式不支持（不是错误，页面单独归类）
    - ``mode``：``hardlink`` / ``copy``（回退复制时页面据实标注）
    - ``shared``：**写入后**是否仍与源共享数据块。写元数据必须替换目录项
      （见约束 2），所以「内嵌过元数据的副本」一定是独立文件、不再共享 ——
      这一项就是给用户看「这本占不占额外空间」的真话。
    - ``rel``：副本相对成品目录的路径（记进 DB，供删除检测与重建）
    """
    out = {"ok": False, "rel": "", "path": "", "mode": "", "shared": False,
           "embedded": [], "cover": False, "error": "", "skipped": False}
    try:
        lib = library.library_of(book)
        pdir = publish_dir(lib.get("id"))
        if pdir is None:
            out["skipped"] = True
            out["error"] = "该库未配置成品目录"
            return out
        src = library.root_of(book) / str(book.get("name") or "")
        if not src.is_file():
            out["skipped"] = True
            out["error"] = "源不是普通文件（目录型有声书暂不出版）"
            return out

        rel = relpath_for(book, cfg)
        dst = pdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        # 目标已存在：是我们自己的就复用/覆盖，是别人的就退让改名
        if dst.exists():
            if same_file(src, dst):
                pass                                  # 已是本源的硬链接，直接用
            elif prev_rel and str(prev_rel) == rel:
                # 上次我们自己产的副本（复制模式，或源换过 inode）→ 移入回收后重建
                recycle(dst, why="重建副本")
            else:
                rel = _free_rel(pdir, rel)
                dst = pdir / rel

        if not dst.exists():
            out["mode"] = link_or_copy(src, dst)
        else:
            out["mode"] = LINK_HARD

        # 只有 EPUB 能内嵌元数据 / 封面；其它格式只产出副本（没内容要写也算成功 ——
        # 外部阅读器至少能看到这本书，页面另标「不可内嵌」）
        embedded, has_cover = [], False
        if src.suffix.lower() in EMBED_EXTS:
            embedded = embed_meta(dst, dict(updates or {}), cover)
            has_cover = bool(cover)
        out.update({"ok": True, "rel": rel, "path": str(dst),
                    "embedded": embedded, "cover": has_cover, "error": "",
                    # 写入后复查：内嵌过元数据的副本已换成独立 inode，不再共享数据块
                    "shared": same_file(src, dst)})

        # 落点变了（如后来补了系列）→ 旧副本移入回收，不留双份
        if prev_rel and str(prev_rel) not in ("", rel):
            old = pdir / str(prev_rel)
            if old != dst:
                recycle(old, why="落点变化")
    except Exception as e:                            # noqa: BLE001 —— 单本失败不影响队列
        out["error"] = str(e)
    return out
