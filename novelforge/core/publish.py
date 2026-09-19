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

**目录型条目**（有声书一章一文件）同样出版：副本是一个**真目录**，内部逐文件硬链接
（``os.link`` / ``shutil.copy2`` 都不能对目录用，故必须逐文件，见 :func:`link_tree_or_copy`）。
它的源指纹是**整树指纹**而非单文件 size/mtime —— 目录自身的 mtime 不随内部文件内容变化
（见 :func:`source_sig`）。名字**不带扩展名**（见 :func:`relpath_for`）。上面三条硬约束
对目录型条目逐字成立，其中第 2 条（副本禁止原地写）天然满足：音轨目录没有可写的 OPF。
"""
from __future__ import annotations

import hashlib
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


#: 整树枚举时跳过的噪声（与 ``pipeline._copy_tree`` 的入库侧过滤同口径）
_TREE_JUNK = ("__MACOSX", "Thumbs.db", ".DS_Store")


def _tree_files(root) -> list:
    """目录型条目的**内容清单**：相对路径（posix、排序后），跳过隐藏项与 macOS 垃圾。

    ⚠️ :func:`source_sig` 与 :func:`link_tree_or_copy` **必须共用这一份** —— 两处若各写
    一套「哪些文件算数」，「源目录里多了一个被跳过的文件」就会变成假变更，或者更糟：
    副本漏链了文件而指纹说「源没变」。排序是为了指纹稳定（遍历顺序由文件系统决定）。
    """
    root = pathlib.Path(str(root))
    out = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part.startswith(".") or part in _TREE_JUNK for part in rel.parts):
            continue
        out.append(rel.as_posix())
    return sorted(out)


def _is_dir_entry(book) -> bool:
    """目录型条目（有声书一章一文件）判定：**条目名不带书库认识的扩展名**。

    目录型条目的 ``name`` 是目录名（``书名`` / ``系列/书名``），没有扩展名；单文件条目
    —— 含**单文件音频** ``.m4b``——一定以 :data:`library.BOOK_EXTS` 里的扩展名结尾。
    刻意**不 stat 磁盘**：``relpath_for`` 在整库预览里每本调一次，不该有 O(n) 次系统调用；
    也刻意**不看** ``format``：单文件音频与目录型音频同为 ``AUDIO``，那个字段区分不开。

    已知边界：目录名自带扩展名（``书.epub`` 里装音轨）判不出来 —— :func:`publish` 会
    因此**跳过**而不是产出一个名字算错的书（见那里的对齐检查）。
    """
    suffix = pathlib.PurePosixPath(str(book.get("name") or "")).suffix.lower()
    return suffix not in library.BOOK_EXTS


# ---------------- 落点 ----------------

def publish_dir(library_id) -> "pathlib.Path | None":
    """该库的成品目录；未配置（空串）返回 ``None``。"""
    lib = library.get_library(library_id) or {}
    raw = str(lib.get("publish_path") or "").strip()
    return pathlib.Path(raw) if raw else None


def relpath_for(book: dict, cfg: dict = None) -> str:
    """副本在**成品目录**下的相对路径（``/`` 分隔）。

    ``cfg`` 传 ``lib_settings.config_for(该库)``：于是命名规则与落盘布局都是**该库的
    生效值**（每库覆写 ?? 全局），这正是「针对不同书库手动调整命名规则」的落点。

    **目录型条目**（有声书一章一文件）走 :func:`komga.relpath_for_dir`：副本是一个**目录**，
    名字**不带扩展名** —— 目录名本身就是装音轨的容器，硬加 ``.audio`` 这类伪扩展名只会
    让磁盘上的目录名变脏。口径与入库侧（``pipeline`` / ``watcher``）完全一致。
    """
    name = str(book.get("name") or "")
    is_dir = _is_dir_entry(book)
    if is_dir:
        # 目录名里的「点」不是扩展名（``书.名`` 是一本书，不是 ``.名`` 格式）——
        # 真去猜哪个点是扩展名只会更常猜错
        ext = ""
        stem = pathlib.PurePosixPath(name).name
    else:
        ext = pathlib.Path(name).suffix
        stem = pathlib.PurePosixPath(name).stem
    naming = (cfg or {}).get("naming") or {}
    pattern = str(naming.get("pattern") or "").strip()
    scope = str(naming.get("scope") or "all").strip().lower()
    # scope 限定「规则适用于哪些格式」：不在范围内就保留原文件名。
    # 目录型条目**没有扩展名可筛**，故只有 all 才算命中 —— 用户把 scope 设成「仅 EPUB」
    # 就是明确说了不要动别的格式，不该顺带把有声书目录也改了。
    in_scope = scope in ("", "all") if is_dir else scope in ("", "all", ext.lstrip(".").lower())
    if pattern and in_scope:
        if is_dir:
            # ``{ext}`` 对目录型条目**没有取值**：摘掉这个占位符再展开，而不是塞空串 ——
            # ``fill_pattern`` 的 ``ext`` 参数是「覆盖值」，传空串会回落去读书目名的后缀
            # （``书.名`` 于是填出「名」）。模式里剩下的分隔符残留由 ``sanitize_stem`` 的
            # ``_BAD_TAIL`` 收掉（``书名 - 作者.`` → ``书名 - 作者``）。
            pattern = pattern.replace("{ext}", "")
        # 展开走 fileops.fill_pattern —— **全项目唯一实现**（第 28 期合并，
        # 原先这里是只认 5 个占位符的第二套实现，与预览各说各话）
        stem = fileops.fill_pattern(pattern, book, ext) or stem
    series = str(book.get("series") or "")
    index = str(book.get("series_index") or "")
    layout = str(((cfg or {}).get("output") or {}).get("layout") or "flat")
    rel = (komga.relpath_for_dir(stem, series, index, layout) if is_dir
           else komga.relpath_for(stem, ext, series, index, layout))
    # 一层子目录（系列）是 Komga 的硬要求，但**不允许**规则里塞进多级路径
    parts = pathlib.PurePosixPath(rel).parts
    if len(parts) > 2 or any(p in ("..", "") for p in parts):
        return (komga.relpath_for_dir(stem, "", "", "flat") if is_dir
                else komga.relpath_for(stem, ext, "", "", "flat"))
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


def link_tree_or_copy(src, dst) -> str:
    """整树落地：逐文件硬链接 ``src`` → ``dst``，不支持时逐文件回退复制。返回 link_mode。

    **目录型有声书（一章一文件）走这条**：``os.link`` 与 ``shutil.copy2`` **都不能对目录用**，
    所以必须逐文件；回退语义与 :func:`link_or_copy` 逐字一致（``EXDEV`` / ``EPERM`` /
    CIFS 都是常态，只记 mode 不报错）。

    返回的 ``mode`` 取整棵树里**最弱**的一档：只要有一个文件退化成复制，整本书就不该被
    标成「硬链接」—— 页面那一栏是给用户看「这本占不占额外空间」的真话。
    """
    src, dst = pathlib.Path(str(src)), pathlib.Path(str(dst))
    dst.mkdir(parents=True, exist_ok=True)
    mode = LINK_HARD
    for rel in _tree_files(src):
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if link_or_copy(src / rel, target) == LINK_COPY:
            mode = LINK_COPY
    return mode


def tree_shared(src, dst) -> bool:
    """副本目录是否**逐文件**与源共享数据块（对应文件的 ``same_file``）。

    目录自身 inode 永远不同，所以「目录型条目的 :func:`same_file`」只能逐文件问。
    空树返回 ``False``：一个没有任何文件的副本不可能是「共享数据块的副本」。
    """
    src, dst = pathlib.Path(str(src)), pathlib.Path(str(dst))
    files = _tree_files(src)
    return bool(files) and all(same_file(src / rel, dst / rel) for rel in files)


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
    """源指纹 ``[size, mtime]``：变了就重刮，源没变就跳过（幂等）。

    - **文件**：``[size, mtime_ns]`` —— 原有口径，**不改**（存量台账行按它比对）。
    - **目录**（有声书一章一文件）：``[整树字节和, 整树指纹]``。单文件那一套对目录是**错的**：
      目录自身的 mtime 不随内部文件内容变化（改一轨音频的音频数据不会碰父目录的 mtime），
      于是「源改了却不重刮」。指纹取 :func:`_tree_files` 的 ``(相对路径, size, mtime_ns)``
      排序后做 sha1 —— 因此**音轨改名也算变更**（音轨顺序就是文件名顺序，改名等于换章序），
      而目录 mtime 那套完全看不出这一点。

    指纹截到 52 位：``scrape_items.src_mtime`` 是 REAL，超过 ``2**53`` 的整数存进去会被
    双精度截断（存回来的值稳定、比较也仍然相等，但没必要留这个坑）。
    """
    p = pathlib.Path(str(path))
    if p.is_dir():
        total = 0
        h = hashlib.sha1()
        for rel in _tree_files(p):
            try:
                st = (p / rel).stat()
            except OSError:
                continue
            total += int(st.st_size)
            h.update(f"{rel}\0{int(st.st_size)}\0{int(st.st_mtime_ns)}\0".encode("utf-8"))
        return [total, int(h.hexdigest()[:13], 16) & ((1 << 52) - 1)]
    try:
        st = os.stat(str(p))
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


#: 落点被占时的处置（见 :func:`rel_verdict`）
REL_REUSE = "reuse"          # 落点空着，或已是**本源**的硬链接 → 直接用
REL_REBUILD = "rebuild"      # 是**本书记台账的**旧副本 → 回收后重建
REL_DECLINE = "decline"      # **不属于这本书**的东西占着 → 退让改名，绝不覆盖


def rel_verdict(pdir: pathlib.Path, rel: str, src=None, prev_rel: str = "") -> str:
    """落点 ``rel`` 已存在时该怎么处置。**只读**：不建目录、不动文件。

    ``publish`` 与「重命名预览」共用这一份判据 —— 预览必须能预先说出「哪几本会退让
    改名（``书名 (2).ext``）」，否则预览名与实际落盘名就会各说各话（第 28 期）。
    """
    dst = pdir / rel
    if not dst.exists():
        return REL_REUSE
    if src is not None and same_file(src, dst):
        return REL_REUSE
    if prev_rel and str(prev_rel) == rel:
        return REL_REBUILD
    return REL_DECLINE


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
        # ⚠️ 判存在用 ``is_dir`` / ``is_file``，**不要**用 ``src.is_file()`` 一票否决 ——
        # 目录型条目（有声书）是目录，``is_file()`` 为假，会被误判成「源不存在」
        # （元数据 apply 那条链路踩过同一个坑）。
        is_dir = src.is_dir()
        if not is_dir and not src.is_file():
            out["skipped"] = True
            out["error"] = "源既不是普通文件也不是目录"
            return out
        if is_dir != _is_dir_entry(book):
            # 名字算得出扩展名、磁盘上却是目录（如 ``书.epub`` 里装音轨）：命名规则与
            # 落盘形态会各说各话。与其产出一个名字算错的书，不如**明确跳过**让人看见。
            out["skipped"] = True
            out["error"] = "条目的名字与磁盘形态不一致（目录名带扩展名或反之），命名会算错；请改名后重扫"
            return out

        rel = relpath_for(book, cfg)
        dst = pdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)

        # 目标已存在：是我们自己的就复用/重建，是别人的就退让改名（判据与预览共用）
        verdict = rel_verdict(pdir, rel, src, prev_rel)
        if verdict == REL_REBUILD:
            # 上次我们自己产的副本（复制模式，或源换过 inode）→ 移入回收后重建
            recycle(dst, why="重建副本")
        elif verdict == REL_DECLINE:
            rel = _free_rel(pdir, rel)
            dst = pdir / rel

        if not dst.exists():
            out["mode"] = link_tree_or_copy(src, dst) if is_dir else link_or_copy(src, dst)
        else:
            out["mode"] = LINK_HARD

        # 只有 EPUB 能内嵌元数据 / 封面；其它格式只产出副本（没内容要写也算成功 ——
        # 外部阅读器至少能看到这本书，页面另标「不可内嵌」）。目录型条目天然落在这里：
        # 音轨目录没有 OPF 可写，元数据照旧只存服务端 DB。
        embedded, has_cover = [], False
        if not is_dir and src.suffix.lower() in EMBED_EXTS:
            embedded = embed_meta(dst, dict(updates or {}), cover)
            has_cover = bool(cover)
        out.update({"ok": True, "rel": rel, "path": str(dst),
                    "embedded": embedded, "cover": has_cover, "error": "",
                    # 写入后复查：内嵌过元数据的副本已换成独立 inode，不再共享数据块。
                    # 目录型条目只能**逐文件**问（目录自身 inode 永远不同）。
                    "shared": tree_shared(src, dst) if is_dir else same_file(src, dst)})

        # 落点变了（如后来补了系列）→ 旧副本移入回收，不留双份
        if prev_rel and str(prev_rel) not in ("", rel):
            old = pdir / str(prev_rel)
            if old != dst:
                recycle(old, why="落点变化")
    except Exception as e:                            # noqa: BLE001 —— 单本失败不影响队列
        out["error"] = str(e)
    return out
