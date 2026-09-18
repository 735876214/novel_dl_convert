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
- **删除 ≠ unlink**：三项单项操作里只有 ``delete`` 动磁盘，且走**回收目录**
  （``CACHE_DIR/recycle``，与工具页同一约定），永不真正删除。
"""
from __future__ import annotations

import pathlib
import shutil
import time

from . import activity_log, db, fileops, pipeline

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
    """把投递目录的现状对账进 dock 表（新增补登记、文件消失则清理悬空条目）。"""
    if watcher is None:
        return
    seen: list[str] = []
    for p in watcher.iter_files():
        if watcher.is_ignored(p):
            continue
        name = p.name
        seen.append(name)
        try:
            size = int(p.stat().st_size)
        except OSError:
            size = 0

        row = db.dock_get(name)
        if row is None:
            st = "pending" if supported(name) else "needs_review"
            db.dock_upsert(
                name, name, ext=p.suffix.lower(), size=size, status=st,
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
    db.dock_prune_missing(seen)


def note_scan(result: dict) -> None:
    """监听器每轮扫描的结果回调：把 converted / added / failed 写进 dock 状态。"""
    res = result or {}
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

def rescan(watcher, item_id) -> dict:
    """重新处理单个条目（复用 watcher.handle_file，含日志与降级提示）。"""
    row = _row(item_id)
    item_id = row["id"]
    name = row["name"]

    src = watcher.input_dir / name
    if not src.is_file():
        db.dock_delete(item_id)
        raise ValueError("文件已不在投递目录")

    if not supported(name):
        db.dock_update(item_id, status="needs_review", detail=_UNSUPPORTED_HINT)
        return db.dock_get(item_id)

    db.dock_update(item_id, status="pending", detail="")
    kind, detail = watcher.handle_file(src)          # 内部已写活动日志
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
