"""容器的**内容分派**（第 87 期立，第 111 期扩到 `.rar` / `.7z`）：容器看内容，不看后缀。

`.zip` / `.rar` / `.7z` 是通用容器、**不是一种书籍格式** —— 里面可能是漫画图片序列，也可能
是一份被改了后缀的 EPUB，还可能是别的文档。它到底算什么书只能看内容（与 `core/comics.py`
顶部「靠魔数嗅探、不信任扩展名」是同一条纪律的延伸：`.cbz` 与 `.zip`、`.cbr` 与 `.rar` 在
字节层面本就等价，`.7z` 只是第三种打包算法）。

结论分档，**判不出就如实报「无法判定」** —— 本项目的一条硬纪律：静默猜测的下场是
用户看到一本打不开的书，而原因离现象十万八千里。

⚠️ **「缺解压能力」不是「这本书坏了」**（第 111 期）：`.rar` 缺 bsdtar/unrar、`.7z` 缺
`py7zr` 时，用户该看到的是「服务器读不了、缺什么」，而不是「容器里一个文件都没有」。
判据只有一处（`comics.backend_problem`），本模块把它原样翻成 ``broken`` 的 ``reason``。

===============  ==============  ==================================================
kind             format          含义
===============  ==============  ==================================================
``comic``        ``CBZ``         容器内是图片序列 ⇒ 与 .cbz **完全同等待遇**（可读）
``epub``/``pdf`` 同名大写       容器内**恰好一份**文档（典型是被改了后缀的 EPUB）
``nested``       容器自身        内层还是压缩包 ⇒ 需先展开
``multi``        容器自身        内有多份文档 ⇒ 需先展开
``mixed``        容器自身        图文混装 ⇒ 判不准，不猜
``empty``        容器自身        一个文件都没有
``broken``       容器自身        坏包 / 魔数不认识 / **缺解压能力**（reason 说清是哪种）
===============  ==============  ==================================================

⚠️ **目前只有 ``comic`` 一档能读**（页序、封面、逐页接口全部复用漫画那一套）。
其余各档一律**不假装能读**：调用方按「无法解析」登记，让它在「待修复」里看得见 ——
文件在磁盘上、书目里却找不到，比直接拒收更糟（见 `library.accepts_ext` 的说明）。

「**容器自身**」= 该容器的后缀大写（``ZIP`` / ``RAR`` / ``7Z``），由 :data:`CONTAINER_FORMATS`
一处派生 —— 「待展开清单」（`library.container_books`）就按它筛，**别再手写第二份**。
"""
import pathlib

from . import comics

#: 需要内容分派才能定形态的扩展名（`.cbz` / `.cbr` 是漫画专属后缀，不走这里）。
#: 第 111 期：`.rar` / `.7z` 与 `.zip` 同列 —— 三者都是**通用容器**。
CONTAINER_EXTS = (".zip", ".rar", ".7z")

#: 「没分派出形态」的容器在书目里的 format 标签。由 :data:`CONTAINER_EXTS` 派生 ——
#: 它是「这还是一个需要展开的容器吗」这个判据的**唯一**来源（后端 `container_books`
#: 与前端注释都认它），手写第二份必然漂移。
CONTAINER_FORMATS = tuple(e.lstrip(".").upper() for e in CONTAINER_EXTS)

#: 容器内出现任一 ⇔ 它其实是一份 EPUB
_EPUB_MARKERS = ("mimetype", "META-INF/container.xml")

#: 容器内**恰好一份**这些文档时，它就是这个格式
_DOC_FORMATS = {".epub": "EPUB", ".pdf": "PDF", ".txt": "TXT", ".mobi": "MOBI",
                ".azw3": "AZW3", ".fb2": "FB2"}

#: 内层还是压缩包 ⇒ 需先展开
_ARCHIVE_EXTS = (".zip", ".cbz", ".cbr", ".rar", ".7z")

#: 可作为展开结果的扩展名（文档 + 内层压缩包）
_UNPACK_EXTS = tuple(_DOC_FORMATS) + _ARCHIVE_EXTS

#: 「容器里恰好一份文档」时的 kind 值（小写 format）—— 供**自动归库**判
#: 「这其实是一本电子书」（`core/library_rules._type_of_name`）。
DOC_KINDS = tuple(f.lower() for f in _DOC_FORMATS.values())


def is_container(path) -> bool:
    """这个后缀要不要走内容分派。"""
    return pathlib.PurePath(str(path)).suffix.lower() in CONTAINER_EXTS


def _suffix(name: str) -> str:
    return pathlib.PurePath(str(name)).suffix.lower()


def _container_format(path) -> str:
    """容器**自身**的 format 标签（没分派出形态时书目里显示的那个）。

    = 后缀大写（``ZIP`` / ``RAR`` / ``7Z``），与 :data:`CONTAINER_FORMATS` 同源；
    后缀取不到时回 ``ZIP``（调用方都在「已知它是容器」的场合，取不到后缀只可能是怪路径）。
    """
    return pathlib.PurePath(str(path)).suffix.lstrip(".").upper() or "ZIP"


def _junk(name: str) -> bool:
    """垃圾条目（`__MACOSX/`、`.DS_Store`、隐藏文件）—— 与取页那份判据同源。"""
    if any(j in name for j in comics._JUNK_PARTS):      # noqa: SLF001 —— 同包同源，刻意复用
        return True
    return pathlib.PurePath(name).name.startswith(".")


def analyze(path) -> dict:
    """判定容器里到底是什么。**只读、不改盘、不抛异常**。

    返回 ``{kind, format, reason, readable, needs_unwrap, evidence}``：
    ``format`` 是该形态**对应**的书目 format（只有 ``comic`` 一档会被上层直接采用，
    其余各档上层一律记成 ``ZIP`` + 无法解析 —— 见模块文档）。
    坏包 / 缺 RAR 依赖折算成 ``broken``（与 `comics.probe` 同口径，绝不抛异常）。
    """
    p = pathlib.Path(str(path))
    out = {"kind": "unknown", "format": _container_format(p), "reason": "", "readable": False,
           "needs_unwrap": False,
           "evidence": {"files": 0, "images": 0, "docs": [], "archives": 0, "sample": []}}
    # 「缺解压能力」与本文件坏要分开说：前者是**服务器**的问题（`.rar` 缺 bsdtar、`.7z`
    # 缺 py7zr），把它塞进下面那个 except 里会变成「不是可读的压缩包（ModuleNotFoundError）」
    # —— 用户据此只会去怀疑自己的文件（第 111 期）。
    problem = comics.backend_problem(p)
    if problem:
        out.update(kind="broken", reason=problem)
        return out
    try:
        with comics._open(str(p)) as arc:               # noqa: SLF001 —— 归档句柄的唯一owner
            names = [n for n in arc.names() if not _junk(n)]
    except Exception as e:                              # noqa: BLE001 —— 坏包如实报，不抛
        out.update(kind="broken",
                   reason=f"不是可读的压缩包（{type(e).__name__}）")
        return out

    images = [n for n in names if comics._keep(n)]      # noqa: SLF001 —— 「算不算一页」的唯一判据
    docs = [n for n in names if _suffix(n) in _DOC_FORMATS]
    archives = [n for n in names if _suffix(n) in _ARCHIVE_EXTS]
    out["evidence"] = {"files": len(names), "images": len(images),
                       "docs": docs[:5], "archives": len(archives), "sample": names[:5]}

    if any(n in _EPUB_MARKERS for n in names):
        out.update(kind="epub", format="EPUB", needs_unwrap=True,
                   reason="容器内是一份 EPUB（有 mimetype / container.xml），只是改了后缀"
                          " —— 需要先展开才能读")
    elif archives:
        out.update(kind="nested", needs_unwrap=True,
                   reason=f"容器内还有 {len(archives)} 个压缩包，需要先展开")
    elif images and not docs:
        out.update(kind="comic", format="CBZ", readable=True,
                   reason=f"容器内是 {len(images)} 张图片，按漫画包读取")
    elif len(docs) == 1 and not images:
        fmt = _DOC_FORMATS[_suffix(docs[0])]
        out.update(kind=fmt.lower(), format=fmt, needs_unwrap=True,
                   reason=f"容器内是一份 {fmt}，需要先展开才能读")
    elif len(docs) > 1:
        out.update(kind="multi", needs_unwrap=True,
                   reason=f"容器内有 {len(docs)} 份文档，需要先展开")
    elif images and docs:
        out.update(kind="mixed",
                   reason=f"容器内既有 {len(images)} 张图片又有文档，判不准（不猜）")
    elif not names:
        out.update(kind="empty", reason="容器内没有任何文件")
    else:
        out.update(kind="unknown",
                   reason=f"容器内没有可识别的内容（{len(names)} 个文件）")
    return out


# ---------------- 展开（第 87 期）----------------
# 「按内容分派」的另一半：容器里装的是**别的书**时，让它变成一本真正的书。
# 图片档本来就能直接读（见 `analyze` 的 comic 档），所以这里只处理其余可读情形：
#   · 容器**本身就是**一份被改了后缀的 EPUB（有 mimetype / container.xml）
#     ⇒ **整份另存为 `.epub`**（EPUB 本来就是 zip，字节复制即可，不必解压再打包）；
#   · 容器内是若干文档（epub / pdf / txt / mobi / azw3 / fb2）⇒ **逐个提取**；
#   · 容器内是压缩包（嵌套）⇒ 提取内层压缩包（**一层一层来**，不递归展开）。
# 三条纪律：只在容器所在目录落新文件；**原子写**（`.part` → replace）；
# **绝不覆盖已有文件**（撞名如实报，不静默改名）；**默认不动源**，即使要求回收也只是
# **移入回收站**（第 96 期：可还原、有台账，从不 `unlink`）。


def _safe_entry(name: str) -> bool:
    """条目名能否安全落到磁盘（防 zip-slip：绝对路径 / `..` / 盘符一律拒绝）。"""
    n = str(name or "").replace("\\", "/")
    if not n or n.startswith("/"):
        return False
    parts = n.split("/")
    if ":" in parts[0]:                       # `C:` 之类盘符
        return False
    return all(part not in ("", ".", "..") for part in parts)


def _unpack_entries(path) -> list:
    """容器内**值得落到磁盘**的条目名（文档 + 内层压缩包；须通过 zip-slip 检查）。"""
    try:
        with comics._open(str(path)) as arc:          # noqa: SLF001
            names = [n for n in arc.names() if not _junk(n)]
    except Exception:                                 # noqa: BLE001 —— 坏包当「没有」
        return []
    return [n for n in names if _suffix(n) in _UNPACK_EXTS and _safe_entry(n)]


def unpack_plan(path) -> dict:
    """**只算不做**：这个容器展开后会变成什么。返回 ``{ok, actions, reason}``。

    `actions` 里每条 ``{kind, name, dest, note}``：`repackage` = 整份另存为新后缀、
    `extract` = 从容器里取一个条目。
    """
    v = analyze(path)
    p = pathlib.Path(str(path))
    if v["kind"] == "epub":
        # ⚠️ 手做的 zip 里 `mimetype` 可能是**压缩**存的（正规 EPUB 要求它不压缩）。
        # 本项目自己的阅读链路按名字取 OPF、不看压缩标志，所以照样能读；
        # 这里不做「重新打包成合规 EPUB」——那要重写整个归档，风险远大于收益。
        return {"ok": True, "reason": "", "actions": [
            {"kind": "repackage", "name": "", "dest": p.with_suffix(".epub").name,
             "note": "整份另存为 EPUB（容器内本来就是一份 EPUB）"}]}
    if v["kind"] == "comic":
        return {"ok": False, "actions": [],
                "reason": "容器内是图片：已经能直接按漫画阅读，不需要展开"}
    ents = _unpack_entries(p)
    if ents:
        return {"ok": True, "reason": "", "actions": [
            {"kind": "extract", "name": n, "dest": n, "note": ""} for n in ents]}
    return {"ok": False, "actions": [],
            "reason": _junk_reason(v) if not ents else ""}


def _junk_reason(v: dict) -> str:
    """判不出可展开内容时给用户的说法（不糊弄：把容器里的实情说出来）。"""
    if v["kind"] in ("nested", "multi", "mixed"):
        return f"{v['reason']}；但其中没有可直接落地的文档（试试先手工解压）"
    return v["reason"] or "这个容器里没有可展开的内容"


def unpack(path, *, remove_source: bool = False) -> dict:
    """**真展开**：把容器里可读的内容落到容器所在目录，逐条回报结果。

    撞名 ⇒ 该条**跳过并如实报**（不覆盖、也不自动改名：改名会换 `book_id`，
    必须由用户确认）。

    ``remove_source=True`` ⇒ 把源容器**移入回收站**（第 96 期）：走 :func:`publish.recycle`，
    台账记下原路径 ⇒ 可在「设置 → 维护 → 回收站还原」把它搬回来。**本模块从不 ``unlink``
    任何东西**（`AGENTS.md` §1「删除一律移入回收站」）。此前这里是全仓**唯一**能真删用户
    书文件的地方（第 95 期审计批次 8）。

    回收失败**不静默**：原因进 ``source_note``，且原容器原样保留（``source_removed=False``）。
    """
    p = pathlib.Path(str(path))
    plan = unpack_plan(p)
    if not plan["ok"]:
        return {"ok": False, "reason": plan["reason"], "actions": [], "source_removed": False}
    results: list = []
    try:
        arc = comics._open(str(p))                    # noqa: SLF001
    except Exception as e:                            # noqa: BLE001
        return {"ok": False, "reason": f"打不开容器：{type(e).__name__}",
                "actions": [], "source_removed": False}
    with arc:
        for act in plan["actions"]:
            dest = p.parent / act["dest"]
            if dest.exists():
                results.append({**act, "ok": False,
                                "note": f"{dest.name} 已存在（不覆盖，请先处理它）"})
                continue
            try:
                data = p.read_bytes() if act["kind"] == "repackage" else arc.read(act["name"])
            except Exception as e:                    # noqa: BLE001
                results.append({**act, "ok": False, "note": f"读取失败：{type(e).__name__}"})
                continue
            if data is None:
                results.append({**act, "ok": False, "note": "容器内读不到该条目"})
                continue
            try:
                tmp = dest.with_name(dest.name + ".part")
                tmp.write_bytes(data)
                tmp.replace(dest)
            except Exception as e:                    # noqa: BLE001
                results.append({**act, "ok": False, "note": f"写入失败：{e}"})
                continue
            results.append({**act, "ok": True, "note": ""})
    ok = any(r["ok"] for r in results)
    removed, source_note = False, ""
    if ok and remove_source:
        if not p.exists():
            source_note = "源容器已不在原处，没有可回收的东西"
        else:
            try:
                # ⚠️ 局部 import：`publish` 顶层 import `library`，而 `library` 顶层 import
                # 本模块（`core/library.py` 的 import 行）⇒ 顶层写会成 import 环。
                from . import publish
                dst = publish.recycle(p, why="展开容器后回收源容器")
                removed = dst is not None
                if not removed:
                    source_note = "源容器没能移入回收站，已保留原文件"
            except Exception as e:                    # noqa: BLE001 —— 绝不静默
                source_note = f"回收源容器失败（{type(e).__name__}: {e}），已保留原文件"
    return {"ok": ok, "reason": "", "actions": results,
            "source_removed": removed, "source_note": source_note}
