"""收书目录（Book Dock）条目与五态流水线。

对应界面 5 个标签：**All / Needs review / Pending / Ready / Error**。真实状态 4 个（+1 个隐藏终态）::

    pending       已进投递目录，等待监听处理（文件仍在写入 / 监听暂停）
    ready         已处理完成（.txt 转 EPUB，或电子书格式直接入库）
    needs_review  类型不在自动处理范围内，无法自动处理，需人工决定
    error         处理抛异常（见 retries，达上限后 watcher 不再重试）
    ignored       用户显式忽略（**不计入任何标签页**，也不再自动处理）

设计取舍
--------
- **状态落 SQLite**（``db.book_dock_items``），条目 id = 投递目录里的**文件名**。
  投递目录是平的（``watcher.recursive`` 默认关闭），用文件名做 id 与 watcher 扫描结果
  的 ``{"file": p.name}`` 同口径，天然对得上。开启递归且各子目录出现同名文件时会合并 ——
  这是刻意的简化（上游 Book Dock 也是扁平列表）。
- **监听器不依赖本模块**：``FolderWatcher`` 只暴露 ``on_scan`` 回调，由 ``server.py`` 注入
  :func:`note_scan`，避免 ``core`` 内部循环依赖（watcher 不 import bookdock）。
- **列表懒对账**：读列表时先 :func:`reconcile` —— 把投递目录里「尚未登记」的文件补成
  pending / needs_review，并清掉文件已消失的悬空条目。这样即使用户绕过界面直接往
  目录里丢文件，列表也不会漏。
- **删除 ≠ unlink**：动磁盘的只有两处 —— ``rename``（**同目录改名**，不删任何东西）
  与 ``delete``（走**回收目录** ``CACHE_DIR/recycle``，与工具页同一约定，
  **永不真正删除**）。``rescan`` / ``ignore`` 只改登记行。
- **入库目标是一次性的**（第 65 期）：``rescan`` 允许带上用户**当场选的**
  ``library_id`` / ``root``（界面上的「入库到…」），但**不落库、不记忆** ——
  这是刻意的：目标库 / 目标文件夹是做这个动作那一刻的输入，不是这个条目的属性
  （下一次扫描仍按各库自己的来源目录路由）。以前这里写着「本项目没有单点目标库 /
  文件夹设置」，那是因为当时**没有这个动作**；现在动作有了，设置仍然没有。
"""
from __future__ import annotations

import pathlib
import shutil
import threading
import time

from . import activity_log, db, fileops, library, pipeline

#: 登记写入的互斥锁（第 65 期）：``rename`` 的「磁盘改名 + 登记行改名」、
#: ``reconcile`` / ``note_scan`` 的对账写入都在它里面，避免改名与对账交错
#: （对账会把改名前后两个名字各登记一次，列表上就多出一条幽灵条目）。
#:
#: ⚠️ **不变量：绝不持本锁去调 ``watcher`` 的任何方法。** watcher 持 ``_scan_lock``
#: 时会回调 ``on_scan`` → :func:`note_scan`（要拿这把锁），反序叠加就是 AB-BA 死锁。
#: 所以本模块的规矩是「**先把 watcher 侧的交互做完，再进锁**」：``reconcile`` 先把
#: 目录现状快照成纯数据，``rename`` 把所有检查（含 ``is_ignored``）放在拿锁之前。
_reg_lock = threading.RLock()

#: 状态 → 中文标签（All 由 payload 补，ignored 不出现）
STATUS_LABELS = {
    "needs_review": "待复核",
    "pending": "待处理",
    "ready": "就绪",
    "error": "出错",
    "ignored": "已忽略",
}

#: 非自动处理类型条目的说明文案（复用同一句，避免措辞漂移）
_UNSUPPORTED_HINT = "类型不在自动处理范围（.txt / EPUB / PDF / CBZ·CBR / 音频等）"


class DockError(Exception):
    """收书目录的操作被**规则**拒绝（不是内部错误，也不是「条目不存在」）。

    ``status`` 让端点直接映射成 HTTP 状态码：400 = 参数不对（库不存在 / 文件夹不属于
    该库 / 该库收不了这个格式），409 = 与当前状态冲突（已就绪 / 重名 / 命中忽略清单）。
    端点只认它；「条目不存在 → ``ValueError`` → 404」那条既有路径**一个字不改**。
    """

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


def supported(name: str) -> bool:
    """该文件能否被自动处理（.txt 转换，或 EBOOK_EXT 直接入库）。"""
    ext = pathlib.Path(str(name or "")).suffix.lower()
    return ext == ".txt" or ext in pipeline.EBOOK_EXT


def _clean_name(name: str) -> str:
    """条目 id 只允许**单个文件名**；分隔符 / ``..`` / 绝对路径一律拒绝。"""
    raw = str(name or "").strip().replace("\\", "/")
    rel = pathlib.PurePosixPath(raw)
    if not raw or rel.is_absolute() or len(rel.parts) != 1 or rel.parts[0] in ("", ".", ".."):
        raise ValueError("非法文件名：%s" % (name,))
    return rel.parts[0]


def _row(item_id) -> dict:
    row = db.dock_get(_clean_name(item_id))
    if not row:
        raise ValueError("条目不存在：%s" % (item_id,))
    return row


# ---------------- 对账 / 记录 ----------------

def reconcile(watcher) -> None:
    """把投递目录的现状对账进 dock 表（新增补登记、文件消失则清理悬空条目）。

    ⚠️ **watcher 的调用全在拿锁之前**：先在锁外把目录现状快照成纯数据
    （名字 / 扩展名 / 大小），再进锁写库 —— 见 :data:`_reg_lock` 的说明。
    """
    if watcher is None:
        return
    snap: "list[tuple[str, str, int]]" = []
    for p in watcher.iter_files():
        if watcher.is_ignored(p):
            continue
        try:
            size = int(p.stat().st_size)
        except OSError:
            size = 0
        snap.append((p.name, p.suffix.lower(), size))

    with _reg_lock:
        for name, ext, size in snap:
            row = db.dock_get(name)
            if row is None:
                st = "pending" if supported(name) else "needs_review"
                db.dock_upsert(
                    name, name, ext=ext, size=size, status=st,
                    detail="" if st == "pending" else _UNSUPPORTED_HINT,
                )
                continue
            # 文件被覆盖 / 续写（大小变化）→ 重新排队；ignored 保持忽略（用户已表态）
            if int(row.get("size") or 0) != size:
                db.dock_update(name, size=size)
                if row.get("status") != "ignored":
                    st = "pending" if supported(name) else "needs_review"
                    db.dock_update(
                        name, status=st,
                        detail="" if st == "pending" else _UNSUPPORTED_HINT,
                    )
        db.dock_prune_missing([n for n, _ext, _size in snap])


def note_scan(result: dict) -> None:
    """监听器每轮扫描的结果回调：把 converted / added / failed 写进 dock 状态。

    整段进 :data:`_reg_lock`（本函数不碰 watcher，只在锁里写库 ⇒ 不会与
    ``_scan_lock`` 反序叠加）。
    """
    res = result or {}
    with _reg_lock:
        for kind in ("converted", "added"):
            for it in res.get(kind) or []:
                name = str((it or {}).get("file") or "")
                try:
                    name = _clean_name(name)
                except ValueError:
                    continue
                db.dock_upsert(name, name)
                db.dock_update(
                    name, status="ready",
                    output=str((it or {}).get("output") or ""), detail="", retries=0,
                )
        for it in res.get("failed") or []:
            name = str((it or {}).get("file") or "")
            try:
                name = _clean_name(name)
            except ValueError:
                continue
            prev = db.dock_get(name) or {}
            db.dock_upsert(name, name)
            db.dock_update(
                name, status="error",
                detail=str((it or {}).get("error") or "处理失败"),
                retries=int(prev.get("retries") or 0) + 1,
            )


def payload(watcher, status=None) -> dict:
    """列表接口的响应体：条目 + 各标签计数。"""
    reconcile(watcher)
    db.dock_prune()
    counts = db.dock_counts()
    tabs = [
        {"key": t,
         "label": "全部" if t == "all" else STATUS_LABELS.get(t, t),
         "count": counts.get(t, 0)}
        for t in db.DOCK_TABS
    ]
    return {
        "items": db.dock_list(status=status),
        "counts": counts,
        "tabs": tabs,
        "statuses": list(db.DOCK_TABS),
    }


# ---------------- 单项操作 ----------------

def _ingest_target(name: str, library_id, root) -> tuple:
    """解析「入库到…」的目标，返回 ``(库实体 | None, 根目录 | None)``。

    都为空 ⇒ ``(None, None)`` = 走既有路由（第 65 期之前的行为**逐字不变**）。

    三条校验，都是「少给不错给」：
    - 库必须**已登记**；
    - 目标文件夹必须是**该库自己的**文件夹之一（空则取第一个 = 口径 7）——
      否则这个接口就成了「往任意目录写文件」的洞；
    - 该库的生效扫描白名单必须**收得了**这个格式（``library.accepts_ext``，
      入库路由共用的唯一真值源）：收进去也扫不到 = **隐形文件**（文件落盘了、
      书目里没有），比直接拒收更糟 —— 用户看得见失败，看不见消失。
    """
    if not library_id:
        return None, None
    lib = library.get_library(library_id)
    if not lib:
        raise DockError(f"书库不存在：{library_id}", status=400)
    roots = library.roots_of(lib)
    if not roots:
        raise DockError(
            f"「{lib.get('name') or library_id}」还没有文件夹：先到书库管理给它加一个",
            status=400)
    if root:
        try:
            want = pathlib.Path(str(root)).resolve()
        except Exception:                       # noqa: BLE001 —— 判不了就是不属于
            want = None
        if want not in roots:
            raise DockError("目标文件夹不属于该书库", status=400)
    else:
        want = roots[0]
    if not library.accepts_ext(lib, name):
        ext = pathlib.PurePosixPath(str(name)).suffix.lower()
        raise DockError(
            f"「{lib.get('name') or library_id}」的「允许的格式」里没有 "
            f"{ext or '（无扩展名）'}：收进去也扫不到，会变成看不见的隐形文件。"
            "先到书库管理把格式加进去，或换一个库", status=400)
    return lib, want


def rescan(watcher, item_id, library_id=None, root=None) -> dict:
    """重新处理单个条目（复用 watcher.handle_file，含日志与降级提示）。

    ``library_id`` / ``root`` 非空 = 用户在界面上**当场指定**了入库目标
    （「入库到…」，第 65 期）：库必须是已登记的，文件夹必须是该库自己的
    （空则取第一个）。两者都空时走既有路由 —— 老调用点的行为一字不改。
    """
    row = _row(item_id)
    item_id = row["id"]
    name = row["name"]

    src = watcher.input_dir / name
    if not src.is_file():
        db.dock_delete(item_id)
        raise ValueError("文件已不在投递目录")

    lib, root_path = _ingest_target(name, library_id, root)

    if lib is None and not supported(name):
        # 没指定目标库时沿用既有判据（**自动**流水线只处理 supported 的格式）。
        # ⚠️ 指定了目标库时**不能**这么早退：待复核条目恰恰大多是这些格式，早退会让
        # 「入库到…」变成**假交互**。显式意图的判据是**那个库收不收它**（accepts_ext，
        # 见 _ingest_target）—— 显式意图能让系统「不猜」，但同样不能让系统「装作收下了」。
        db.dock_update(item_id, status="needs_review", detail=_UNSUPPORTED_HINT)
        return db.dock_get(item_id)

    db.dock_update(item_id, status="pending", detail="")
    # 内部已写活动日志；owner_lib / owner_root 都为 None 时走既有 _target 路由
    kind, detail = watcher.handle_file(src, owner_lib=lib, owner_root=root_path)
    if kind in ("converted", "added"):
        db.dock_update(item_id, status="ready",
                       output=pathlib.Path(str(detail)).name, detail="", retries=0)
    elif kind == "failed":
        db.dock_update(item_id, status="error", detail=str(detail),
                       retries=int(row.get("retries") or 0) + 1)
    else:
        db.dock_update(item_id, status="needs_review", detail=str(detail))
    watcher.mark_processed(src)
    return db.dock_get(item_id)


def rename(watcher, item_id, new_name) -> dict:
    """把投递目录里的条目**改个文件名**（第 65 期）。

    改的是磁盘上的文件名 + 登记行的主键（条目 id 就是文件名）；``status`` /
    ``created_at`` / ``output`` 一概不动 —— 用户改的是名字，不是状态。

    为什么 ``ready`` 要拒（用户口径）：就绪条目的成品已经在书库里了（``output``
    指着它），改投递目录里的源文件既改不到那本书、又让两者对不上。「改已入库的
    书名」是元数据编辑与布局整理的地盘，不是这里。

    失败一律**什么都不改**：任一条校验不过就直接抛，磁盘与登记行一个字段都不动。
    """
    row = _row(item_id)                       # 条目不存在 → ValueError（端点 404）
    old_id, old_name = row["id"], row["name"]

    if str(row.get("status") or "") == "ready":
        raise DockError("已就绪的条目不能改名：它已经入库了，"
                        "要改书名请到书架用「编辑元数据」", status=409)

    # —— 以下检查**全部在拿锁之前**做完（含 `watcher.is_ignored`）——
    try:
        new_name = _clean_name(new_name)      # 分隔符 / ``..`` / 绝对路径一律拒
    except ValueError as e:
        raise DockError(str(e), status=400) from None

    old_ext = pathlib.PurePosixPath(old_name).suffix.lower()
    new_ext = pathlib.PurePosixPath(new_name).suffix.lower()
    if new_ext != old_ext:
        # **不静默替换**：扩展名决定这个文件怎么被处理（.txt 走管线、.epub 直接入库），
        # 悄悄改掉等于替用户换了一种处理方式。
        raise DockError(
            f"不能改扩展名：「{old_ext or '（无扩展名）'}」→ "
            f"「{new_ext or '（无扩展名）'}」——要换格式请重新投递", status=400)

    stem = fileops.sanitize_stem(pathlib.PurePosixPath(new_name).stem)
    if not stem:
        # sanitize_stem 是**静默删字符**的，能删成空串（比如名字全是 "???"）
        raise DockError("新文件名里没有可用字符（非法字符会被清掉）", status=400)
    new_name = stem + new_ext

    if new_name == old_name:
        return db.dock_get(old_id)            # 幂等：同名不动磁盘、不动库

    src = pathlib.Path(watcher.input_dir) / old_name
    if not src.is_file():
        db.dock_delete(old_id)
        raise ValueError("文件已不在投递目录")   # 与 rescan 同一处置（端点 404）

    dst = pathlib.Path(watcher.input_dir) / new_name
    # ⚠️ **不能只靠 `rename()` 判重名**：同名已存在时 Windows 抛 FileExistsError、
    # POSIX **静默覆盖** —— 跨平台不一致，而在收书目录里覆盖 = 悄悄少掉一个条目
    # （收书目录是平的，文件名唯一）。
    if dst.exists():
        raise DockError(f"投递目录里已经有「{new_name}」了", status=409)

    # 忽略清单按**文件名**记：改成清单里的名字，这一条从此刻起再也不会被自动处理，
    # 而清单在别处（界面上看不出来）—— 用户会以为改名之后「处理不了了」。
    if watcher.is_ignored(new_name):
        raise DockError(f"「{new_name}」在忽略清单里：改成它会让它再也不被自动处理",
                        status=409)

    with _reg_lock:                           # 锁内只做「改磁盘 + 一条 SQL」，不碰 watcher
        src.rename(dst)                       # 同目录改名，原子
        db.dock_rename(old_id, new_name, new_name, new_ext,
                       f"原文件名：{old_name}")
    activity_log.log(activity_log.ACTION_RENAME, new_name, activity_log.STATUS_OK,
                     detail=f"收书目录改名：{old_name} → {new_name}", source="api")
    return db.dock_get(new_name)


def ignore(watcher, item_id) -> dict:
    """忽略条目：登记进监听器运行时忽略集，之后不再自动处理（文件保留）。"""
    row = _row(item_id)
    item_id, name = row["id"], row["name"]
    watcher.add_ignore(name)
    db.dock_update(item_id, status="ignored", detail="已忽略，不再自动处理")
    activity_log.log(activity_log.ACTION_SKIP, name, activity_log.STATUS_OK,
                     detail="收书目录：忽略该条目", source="api")
    return db.dock_get(item_id)


def remove(watcher, item_id) -> dict:
    """移出收书目录：文件移入**回收目录**（不是删除），并清掉条目。"""
    row = _row(item_id)
    item_id, name = row["id"], row["name"]
    recycled = ""
    src = watcher.input_dir / name
    if src.is_file():
        dest_dir = fileops.recycle_dir()
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dst = dest_dir / f"{stamp}_{name}"
        n = 1
        while dst.exists():
            dst = dest_dir / f"{stamp}_{n}_{name}"
            n += 1
        shutil.move(str(src), str(dst))
        recycled = dst.name
        activity_log.log(activity_log.ACTION_RECYCLE, name, activity_log.STATUS_OK,
                         output=recycled, detail="从收书目录移入回收目录", source="api")
    db.dock_delete(item_id)
    return {"ok": True, "name": name, "recycled": recycled}
