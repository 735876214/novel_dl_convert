"""刮削出版的编排：状态机 + 单线程队列 worker。

分工刻意如此：:mod:`novelforge.core.publish` 只管**文件**（硬链接 / 写副本 / 回收），
本模块只管**状态与调度**（谁该刮、刮到哪一步、失败怎么办、副本没了怎么标记），
台账落在 ``scrape_items``（状态取值见 :data:`novelforge.core.db.SCRAPE_STATUSES`）。

三条与用户约定绑定的规则：

1. **单 worker 串行**：``metasources`` 是顺序外呼、无重试；并发只会放大被限流 /
   封禁的风险，也与 watcher 的 ``_scan_lock`` 串行化一致。进度靠轮询而非流式。
2. **副本被删只标记、不处置**：校验发现副本缺失 → 状态降为 ``removed`` + 记一条
   「硬链接副本已删除，原文件待确认」日志，由用户空闲时在刮削页上点确认
   （删原文件 / 保留原文件 / 重新生成副本）。**绝不自动删源、绝不自动重建**（降级约定）。
3. **队列持久化**：待办就是 ``status='pending'`` 的行，重启接着跑，不靠内存。

「刮削」在这里＝「让副本具备正确的元数据」：先按既有链路抓在线元数据
（``metafetch``，落 ``meta_online`` / ``meta_cover``），再把**生效值里与 OPF 原值
不同**的字段写进副本 —— 与 OPF 一致的不写，副本因此能保持纯硬链接、不额外占盘。
"""
from __future__ import annotations

import logging
import pathlib
import threading
import time

from . import (activity_log, db, fileops, lib_settings, library, metafetch,
               metastore, publish)

_logger = logging.getLogger("novelforge.scrape")

#: worker 空闲时的等待时长（有活干就立刻继续，不必等满）
_IDLE_WAIT = 5.0
#: 一批取多少条待办
_BATCH = 5

#: 「只许降级」的状态：这些状态**不会**因扫描 / 自动入队而回到 pending，
#: 必须由用户在页面上显式处置（见 :func:`resolve`）。
_HELD = {
    "removed": "副本已被删除，待你确认是否删除原文件",
    "kept": "已确认保留，如需重新出版请点「重新生成副本」",
    "orphan": "原文件已不在，副本为唯一留存，待你处置",
    "source_removed": "原文件已按确认移入回收站",
}

_lock = threading.RLock()
_wake = threading.Event()
_stop = False
_thread: "threading.Thread | None" = None
_last_verify = 0.0
_current = ""

#: **worker 世代号**（第 34 期定位到的真根因的修法）。
#:
#: 为什么需要它：``stop(timeout)`` 只等一段时间就走，而**单条处理是不可中断的整段调用**
#: （外呼 / 重试 / 写副本都可能远超 timeout）—— 于是 worker 会带着 ``_stop`` 检查不到的
#: 进度把那条跑完，然后**照常写库**。
#: 而测试的库是**用例级隔离**的（``db.close()`` + ``db.init()`` 换一套空库），
#: 残留线程的写就落到**下一个用例的库**上：删行让全局总数变 0、插行变 2 ——
#: 这正是「单跑必过、全量偶挂」的形状（受害断言是全局 ``total``）。
#:
#: 有了世代号，「**已被作废的那一轮不得落库**」成为可强制的事实：
#: `stop()` / `start()` 推进世代 ⇒ 旧世代的一切写入被拒。
#: 代价只是「那条留到下次重来」—— 而它本来就是既有恢复路径
#: （``start()`` 会 ``scrape_reset_running()`` 把 running 打回 pending）。
_epoch = 0


# ---------------- 配置 / 状态查询 ----------------

def _section(library_id=None) -> dict:
    """该库（或全局）的 ``scrape`` 配置段（每库覆写 ?? 全局）。"""
    return (lib_settings.config_for(library_id).get("scrape") or {})


def enabled(library_id=None) -> bool:
    """该库是否开启自动刮削（扫描入库后自动排队）。关闭后仍可手动跑。"""
    return bool(_section(library_id).get("enabled", True))


def _max_attempts(library_id=None) -> int:
    """同一本的自动重试上限（配置坏了也不让它变成 0 —— 那样第一轮就判死）。"""
    try:
        return max(1, int(_section(library_id).get("max_attempts") or 2))
    except (TypeError, ValueError):
        return 2


def is_running() -> bool:
    with _lock:
        return bool(_thread and _thread.is_alive())


def epoch() -> int:
    """当前 worker 世代号（`stop()` / `start()` 都会推进它）。

    给「想确认自己那一轮是否已作废」的调用方用（worker 内部走 :func:`_stale`）。
    """
    with _lock:
        return _epoch


def _stale(gen) -> bool:
    """worker 的一轮是否**已作废**（停机过、或又起了一轮）。

    ``gen is None`` = 不受世代约束 —— 同步调用与接口触发的处理都属于这一类
    （它们由当前请求驱动，没有「停机」这回事），所以这个守卫对它们完全透明。
    """
    return gen is not None and (_stop or gen != _epoch)


def _aborted() -> dict:
    """本轮已作废：**一个字都不写库**，条目留给下一轮重来。"""
    return {"ok": False, "aborted": True, "error": "worker 已停机，本轮结果未落库"}


def worker_state() -> dict:
    """worker 运行态。

    - ``running``：线程活着（**几乎总是 true**，worker 起来后常驻）→ 只适合显示
      「自动刮削已就绪」，**不能**用它判断「正在刮削」；
    - ``current``：正拿在手里的书名（空 = 没在跑具体某本）；
    - ``busy``：真的在干活（手里有书，或队列里还有待办）→ 界面用它决定
      「正在刮削 / 空闲」与**是否开启轮询**。
    """
    with _lock:
        cur = _current
    try:
        pending = bool(db.scrape_pending(limit=1))
    except Exception:                                 # noqa: BLE001 —— 查询失败不该影响界面
        pending = False
    return {"running": is_running(), "current": cur,
            "busy": bool(cur) or pending}


def _set_current(name: str) -> None:
    global _current
    with _lock:
        _current = str(name or "")


# ---------------- 日志 ----------------

def _log(book_name: str, detail: str, ok: bool = True) -> None:
    activity_log.log(activity_log.ACTION_SCRAPE, str(book_name or ""),
                     activity_log.STATUS_OK if ok else activity_log.STATUS_FAIL,
                     detail=detail, source="scrape")


# ---------------- 入队 ----------------

def enqueue(book: dict, *, force: bool = False, reason: str = "scan",
            row: dict = None) -> dict:
    """把一本书排进刮削队列（幂等）。``force=True`` = 用户显式重刮。

    幂等判断（``force=False`` 时）：
    - 已出版且**源指纹未变**且副本仍在 → 不重排（省掉一次外呼）；
    - 已在队列里 → 不重排；
    - 处于「只许降级」的状态（removed / kept / orphan / source_removed）→ **不复活**。

    ``row`` 可由调用方**批量预取**后传入（见 :func:`enqueue_library`）——
    逐本查库在整库入队时是几千次查询，虽然不致命，但没必要。
    """
    book = book or {}
    bid = str(book.get("id") or "")
    if not bid:
        return {"ok": False, "reason": "这本书没有 book_id"}
    lib = library.library_of(book)
    lib_id = str(lib.get("id") or "")
    pdir = publish.publish_dir(lib_id)
    if pdir is None:
        # 该库没配成品目录：**不建台账行** —— 否则整个库的书都会冒出来变成噪声。
        # 页面空状态直接引导「去书库管理设置成品目录」。
        return {"ok": False, "skipped": True, "reason": "该库未配置成品目录"}

    name = str(book.get("name") or "")
    src_path = library.root_of(book) / name
    sig = publish.source_sig(src_path)
    row = row if row is not None else (db.scrape_get(bid) or {})
    st = str(row.get("status") or "")
    if row and not force:
        same_src = (int(row.get("src_size") or 0) == sig[0]
                    and float(row.get("src_mtime") or 0) == float(sig[1]))
        # 「原文件已按确认回收」是**持有**状态，但用户若把文件重新放回源目录，
        # 意图就很明确了（他要这本书回来）：此时放行，否则这一行永远没有出口 ——
        # 该状态下页面不给任何按钮，重新入队又被挡，等于把这本书锁死。
        if st == "source_removed" and src_path.exists():
            pass
        elif st == "ok":
            rel = str(row.get("link_rel") or "")
            if same_src and rel and (pdir / rel).exists():
                return {"ok": True, "skipped": True, "reason": "已是最新"}
        elif st in ("pending", "running"):
            return {"ok": True, "skipped": True, "reason": "已在队列中"}
        elif st in _HELD:
            return {"ok": False, "skipped": True, "reason": _HELD[st]}
        elif st == "failed" and not same_src:
            pass                                      # 源换了 → 值得再试一次
        elif st == "failed" and int(row.get("attempts") or 0) >= _max_attempts(lib_id):
            # 已用尽自动重试次数：**不要每次扫描都再触发一遍**，等人工在页面上处理
            return {"ok": False, "skipped": True,
                    "reason": "已连续失败，请人工重试（页面可「重新刮削」）"}
        attempts = int(row.get("attempts") or 0) if same_src else 0
    else:
        attempts = 0
    db.scrape_set(bid, library_id=lib_id, source_rel=name, status="pending",
                  src_size=sig[0], src_mtime=sig[1], attempts=attempts,
                  force_fetch=1 if force else 0, error="")
    return {"ok": True, "queued": True, "reason": reason}


def enqueue_library(library_id=None, *, force: bool = False) -> dict:
    """把一个库（不给则全部库）的书排进队列。返回 ``{libs, total, queued}``。

    **不看自动开关** —— 这是「开始刮削 / 重新刮削」按钮的落点，用户点了就该跑
    （``scrape.enabled`` 只管「扫描后要不要自动排队」）。
    """
    libs = [library.get_library(library_id)] if library_id else library.libraries()
    total = queued = 0
    lib_ids = []
    for lib in libs or []:
        if not lib:
            continue
        lid = str(lib.get("id"))
        if publish.publish_dir(lid) is None:
            continue                                  # 没成品目录 → 整库跳过，不建噪声行
        lib_ids.append(lid)
        books = library.books(lid)
        # 一次批量取全台账（几千本时逐本查库是几千次查询，没必要）
        rows = db.scrape_books_in(lid, [b.get("id") for b in books])
        for b in books:
            total += 1
            if enqueue(b, force=force, row=rows.get(str(b.get("id")))).get("queued"):
                queued += 1
    return {"libs": lib_ids, "total": total, "queued": queued}


# ---------------- 处理单本 ----------------

def _has_value(v) -> bool:
    return bool(v) and str(v).strip() not in ("", "[]", "None")


def _norm_field(field: str, value):
    """字段值归一化后再比较「是否与 OPF 原值一致」。

    ``tags`` 两侧形态不同（override / online 存的是字符串，OPF 侧是列表），
    直接 ``str()`` 比会把「同一组题材」判成不同 —— 于是每本带题材的书都要白写一遍
    副本（丢掉硬链接、白占一份空间）。故在这里统一成列表比。
    """
    if field == "tags":
        vals = value if isinstance(value, (list, tuple)) else db._parse_tags(value)
        return sorted(str(x).strip() for x in vals if str(x).strip())
    return str(value or "").strip()


def process(bid, *, fetch: bool = None, gen: int = None) -> dict:
    """处理一本书：可选在线刮削 → 出版副本 → 落状态。**不抛异常**。

    ``fetch``：``None`` = 按配置自动判断（启用且没抓过、或队列标了强制重抓）；
    ``False`` = 只做文件操作（重建副本走这条，不外呼、够快）。

    ``gen``：调用方的 worker 世代号（见 ``_epoch``）。**只有后台 worker 传**；
    同步调用与接口触发一律 ``None`` = 不受世代约束。传入时，一旦那一轮被作废，
    本函数在**每个落库点**停手并返回 ``{"aborted": True}`` —— 条目留待下轮重来。
    """
    bid = str(bid)

    def stale() -> bool:
        return _stale(gen)

    row = db.scrape_get(bid) or {}
    lib_id = str(row.get("library_id") or "")
    lib = library.get_library(lib_id) if lib_id else None
    if not lib:
        if stale():
            return _aborted()
        db.scrape_delete(bid)
        return {"ok": False, "error": "书库已不在（台账已清）"}
    pdir = publish.publish_dir(lib_id)
    if pdir is None:
        if stale():
            return _aborted()
        db.scrape_set(bid, status="skipped", error="该库未配置成品目录")
        return {"ok": False, "skipped": True, "error": "该库未配置成品目录"}

    try:
        book = library.by_id(bid)
    except Exception as e:                            # noqa: BLE001 —— book_id 冲突等
        if stale():
            return _aborted()
        db.scrape_set(bid, status="failed", error=f"书目冲突：{e}")
        return {"ok": False, "error": str(e)}
    if not book:
        return _lost(bid, row, lib, "源已不在书目里", gen=gen)

    name = str(book.get("name") or row.get("source_rel") or "")
    src = library.root_of(book) / name
    if not src.exists():
        return _lost(bid, row, lib, "源文件已不在", gen=gen)

    cfg = lib_settings.config_for(lib_id)
    sig = publish.source_sig(src)
    if stale():
        return _aborted()
    db.scrape_set(bid, status="running", library_id=lib_id, source_rel=name)
    _set_current(name)
    try:
        # ① 在线刮削（可选）：结果照旧只落服务端（meta_online / meta_cover），
        #    再由 ② 统一写进副本 —— 手动整理与自动刮削因此走**同一条出版路径**。
        do_fetch = enabled(lib_id) if fetch is None else bool(fetch)
        do_fetch = do_fetch and bool((cfg.get("metadata_fetch") or {}).get("enabled"))
        if do_fetch and (row.get("force_fetch") or not db.get_online(bid)):
            metafetch.auto_fetch(name, cfg=cfg)       # 内部吞异常、只应用达阈值字段

        # ② 只写「与 OPF 原值不同」的字段：一致的不写 —— 副本因此保持纯硬链接、不占额外空间
        updates = {}
        for f, info in (metastore.state(book) or {}).items():
            v, opf = info.get("value"), info.get("opf")
            if not _has_value(v) or _norm_field(f, v) == _norm_field(f, opf):
                continue
            updates[f] = v

        res = publish.publish(book, cfg=cfg, updates=updates,
                              cover=db.get_cover(bid) or None,
                              prev_rel=str(row.get("link_rel") or ""))
        # ⚠️ 这段可能跑很久（外呼 / 重试 / 写副本），期间 stop() 可能已经把本轮作废
        #    —— 落库前必须再校验一次，否则残留线程会把结果写进**换过的那套库**。
        if stale():
            return _aborted()
        if res.get("ok"):
            db.scrape_set(bid, status="ok", link_rel=res.get("rel") or "",
                          link_mode=res.get("mode") or "",
                          link_shared=1 if res.get("shared") else 0,
                          src_size=sig[0], src_mtime=sig[1],
                          embedded=",".join(res.get("embedded") or []),
                          has_cover=1 if res.get("cover") else 0,
                          error="", force_fetch=0, removed_at=0, removed_path="",
                          confirmed_at=0)
            mode = "硬链接" if res.get("mode") == publish.LINK_HARD else "复制"
            extra = "，已内嵌元数据" if res.get("embedded") or res.get("cover") else "（无元数据可写）"
            _log(name, f"刮削出版：{res.get('rel')}（{mode}{extra}）")
            return {"ok": True, **res}
        if res.get("skipped"):
            db.scrape_set(bid, status="skipped", error=res.get("error") or "",
                          force_fetch=0)
            _log(name, f"跳过刮削：{res.get('error')}", ok=True)
            return {"ok": False, "skipped": True, **res}
        return _failed(bid, row, lib_id, res.get("error") or "未知失败", name, gen=gen)
    finally:
        _set_current("")


def _failed(bid, row, lib_id, error: str, name: str, gen: int = None) -> dict:
    """失败：未到上限打回 pending（下轮再试），到上限标 failed 等人工。"""
    attempts = int(row.get("attempts") or 0) + 1
    over = attempts >= _max_attempts(lib_id)
    if _stale(gen):
        return _aborted()
    db.scrape_set(bid, status="failed" if over else "pending", attempts=attempts,
                  error=error)
    _log(name, f"刮削失败（第 {attempts} 次）：{error}", ok=False)
    return {"ok": False, "error": error, "attempts": attempts, "give_up": over}


def _lost(bid, row, lib, why: str, gen: int = None) -> dict:
    """源不见了：副本还在 → 孤本待处置；副本也没了 → 台账没有意义，清掉。"""
    pdir = publish.publish_dir(str(lib.get("id")))
    rel = str(row.get("link_rel") or "")
    copy = (pdir / rel) if (pdir and rel) else None
    name = str(row.get("source_rel") or bid)
    if copy is not None and copy.exists():
        if _stale(gen):
            return _aborted()
        db.scrape_set(bid, status="orphan", error=f"{why}，副本为唯一留存")
        _log(name, f"原文件已不在（{why}），副本为唯一留存：{copy}")
        return {"ok": False, "orphan": True, "error": why}
    if _stale(gen):
        return _aborted()
    db.scrape_delete(bid)
    return {"ok": False, "error": f"{why}，且副本也不在（台账已清）"}


# ---------------- 校验（只标记，不处置）----------------

def verify(library_id=None, gen: int = None) -> dict:
    """校验已出版副本与源文件是否还在。**只降级标记 + 记日志，绝不处置。**

    - 副本缺失 → ``removed``（待确认：是否连原文件一起删）
    - 源缺失而副本在 → ``orphan``（副本是唯一留存了）

    返回 ``{checked, removed: [...], orphan: [...]}``，供接口回显。
    ``gen`` 口径同 :func:`process`：worker 传世代号，作废后不再落库（见 ``_epoch``）。
    """
    rows = db.scrape_list(library_id=library_id, status="ok")
    removed, orphan = [], []
    for row in rows:
        if _stale(gen):
            break
        bid = str(row.get("book_id"))
        lib = library.get_library(row.get("library_id"))
        if not lib:
            continue
        pdir = publish.publish_dir(str(lib.get("id")))
        rel = str(row.get("link_rel") or "")
        name = str(row.get("source_rel") or bid)
        src = pathlib.Path(lib.get("root_path") or "") / name
        copy = (pdir / rel) if (pdir and rel) else None
        if copy is not None and not copy.exists():
            db.scrape_set(bid, status="removed", removed_at=time.time(),
                          removed_path=str(copy),
                          error="硬链接副本已删除，原文件待确认")
            _log(name, f"硬链接副本已删除，原文件待确认（原文件：{src}）")
            removed.append({"book_id": bid, "name": name,
                            "source": str(src), "removed_path": str(copy)})
        elif not src.exists():
            db.scrape_set(bid, status="orphan", error="原文件已不在，副本为唯一留存")
            _log(name, f"原文件已不在，副本为唯一留存：{copy}")
            orphan.append({"book_id": bid, "name": name, "copy": str(copy)})
    return {"checked": len(rows), "removed": removed, "orphan": orphan}


# ---------------- 用户处置（全部需要显式调用）----------------

#: 页面上的处置动作 → 语义说明（接口据此校验，防手滑传错）
ACTIONS = {
    "delete_source": "删除原文件（移入回收站），副本保留",
    "keep_source": "保留原文件，不再提醒",
    "rebuild": "重新生成副本（按当前元数据重写，不外呼）",
    "keep_copy": "保留副本（原文件已不在，以副本为准）",
    "recycle_copy": "把副本移入回收站并清掉台账",
}


def resolve(bid, action: str) -> dict:
    """执行用户在某本书上的显式处置。**任何状态流转都只能从这里回到 ok**。"""
    action = str(action or "").strip()
    if action not in ACTIONS:
        return {"ok": False, "error": f"未知动作：{action}"}
    row = db.scrape_get(bid)
    if not row:
        return {"ok": False, "error": "没有这本书的刮削台账"}
    if action == "rebuild":
        return process(bid, fetch=False)

    lib = library.get_library(row.get("library_id")) or {}
    root = pathlib.Path(lib.get("root_path") or "")
    name = str(row.get("source_rel") or bid)
    src = root / name
    pdir = publish.publish_dir(str(lib.get("id")))
    rel = str(row.get("link_rel") or "")
    copy = (pdir / rel) if (pdir and rel) else None

    if action == "delete_source":
        if not src.exists():
            return {"ok": False, "error": "原文件已不在"}
        # 删除前后各记一条：用户要能在日志里看到「谁在什么时候把什么移走了」
        _log(name, f"确认删除原文件，移入回收站：{src}")
        try:
            dst = publish.recycle(src, why="用户确认删除原文件")
        except Exception as e:                        # noqa: BLE001
            _log(name, f"原文件移入回收站失败：{e}", ok=False)
            return {"ok": False, "error": str(e)}
        library.invalidate(str(lib.get("id")))
        db.scrape_set(bid, status="source_removed", confirmed_at=time.time(),
                      error=f"原文件已移入回收站：{getattr(dst, 'name', '')}")
        _log(name, f"原文件已移入回收站：{dst}")
        return {"ok": True, "action": action, "recycled": str(dst)}

    if action == "keep_source":
        db.scrape_set(bid, status="kept", confirmed_at=time.time(), error="")
        _log(name, "确认保留原文件（副本未重建）")
        return {"ok": True, "action": action}

    if action == "keep_copy":
        db.scrape_set(bid, status="kept", confirmed_at=time.time(), error="")
        _log(name, "确认保留副本（原文件已不在，以副本为准）")
        return {"ok": True, "action": action}

    # recycle_copy
    if copy is not None and copy.exists():
        _log(name, f"确认清理副本，移入回收站：{copy}")
        try:
            dst = publish.recycle(copy, why="用户确认清理副本")
        except Exception as e:                        # noqa: BLE001
            _log(name, f"副本移入回收站失败：{e}", ok=False)
            return {"ok": False, "error": str(e)}
        db.scrape_delete(bid)
        _log(name, f"副本已移入回收站：{dst}")
        return {"ok": True, "action": action, "recycled": str(dst)}
    db.scrape_delete(bid)
    return {"ok": True, "action": action, "note": "副本本来就不在，已清台账"}


# ---------------- 命名规则预览 / 重出版（第 28 期）----------------
# 「批量重命名」与刮削合并后，改名只剩一个口径：**只改硬链接副本的文件名**，源文件
# 永远只读。预览与落盘共用 ``publish.relpath_for`` / ``publish.rel_verdict``，所以
# 预览给出的 ``new_rel`` 就是重出版后台账里的 ``link_rel``（所见即所得）。

def _rule_cfg(library_id, pattern: str, scope: str) -> dict:
    """该库的生效配置；给了草稿规则就覆盖 ``naming``（预览「所见即所得」用）。"""
    cfg = lib_settings.config_for(library_id)
    if not str(pattern or "").strip():
        return cfg
    return {**cfg, "naming": {**(cfg.get("naming") or {}),
                              "pattern": str(pattern).strip(),
                              "scope": str(scope or "all").strip() or "all"}}


def plan_naming(library_id=None, pattern: str = "", scope: str = "") -> dict:
    """预览「当前副本名 → 重出版后的副本名」。**只算不改**（源与本都不碰）。

    ``pattern`` 留空 = 用该库已保存的生效规则（每库覆写 ?? 全局）；给了就按草稿算
    —— 设置页与刮削面板的「预览」都是这个用法。

    只列**已出版**的书（台账 ``link_rel`` 非空）：未出版的书归「开始刮削」管，
    在这里列出来只是噪声。``conflict`` 两类，都不进批量重出版：

    - ``dup``：同批内两本及以上落点相同（谁留谁走没有正确答案）；
    - ``occupied``：落点已被**不属于这本书**的文件占着 —— ``publish`` 会退让成
      「书名 (2).ext」。与其让预览说 A、落盘成 B，不如摆出来让用户自己处理。
    """
    lid = str(library_id or "").strip()
    saved = (lib_settings.config_for(lid or None).get("naming") or {})
    pat = str(pattern or "").strip() or str(saved.get("pattern") or "").strip()
    sc = str(scope or "").strip() or str(saved.get("scope") or "all")
    items = []
    for r in db.scrape_list(library_id=lid or None):
        bid = str(r.get("book_id") or "")
        old_rel = str(r.get("link_rel") or "")
        lib_id = str(r.get("library_id") or "")
        if not bid or not old_rel:
            continue
        pdir = publish.publish_dir(lib_id)
        if pdir is None:
            continue
        try:
            book = library.by_id(bid)
        except Exception:                             # noqa: BLE001 —— book_id 撞车等
            continue
        if not book:
            continue                                  # 源已不在书目里（台账另行处置）
        new_rel = publish.relpath_for(book, _rule_cfg(lib_id, pattern, sc))
        name = str(book.get("name") or r.get("source_rel") or "")
        verdict = publish.rel_verdict(pdir, new_rel, library.root_of(book) / name, old_rel)
        declined = verdict == publish.REL_DECLINE
        items.append({
            "book_id": bid, "library_id": lib_id,
            "name": name, "title": str(book.get("title") or "") or name,
            "old_rel": old_rel, "new_rel": new_rel,
            "changed": new_rel != old_rel,
            "conflict": "occupied" if declined else "",
            "reason": "落点已被不属于这本书的文件占用，重出版会另起「(2)」名" if declined else "",
        })

    dup: dict = {}
    for it in items:
        if it["changed"]:
            dup.setdefault(it["new_rel"], []).append(it)
    for group in dup.values():
        if len(group) > 1:
            for it in group:
                it["conflict"], it["reason"] = "dup", "同批内有多本书的落点相同"

    ready = [it for it in items if it["changed"] and not it["conflict"]]
    return {
        "library_id": lid, "pattern": pat, "scope": sc or "all",
        "fields": list(fileops.PATTERN_FIELDS), "items": items,
        "stats": {"total": len(items),
                  "changed": sum(1 for it in items if it["changed"]),
                  "conflict": sum(1 for it in items if it["conflict"]),
                  "ready": len(ready)},
    }


def republish(subset=None, library_id=None) -> dict:
    """按当前命名规则重出版：**只动副本，源文件只读**。

    只处理 :func:`plan_naming` 判为「会变且不冲突」的书 —— 名字没变的跳过（白搬一次
    文件没有意义）。单本走 ``resolve(bid, "rebuild")`` 即 ``process(bid, fetch=False)``：
    **不外呼**，只按当前元数据重写副本；旧副本由 ``publish`` 按 ``prev_rel`` 移入回收
    （源文件与旧副本都不会被 ``unlink``）。

    ``subset`` 给了就只做其中的书，但**仍以 plan 的判定为准**：客户端说了不算，
    冲突项与无变化的书一律跳过（也就不会出现「客户端指定去动某个文件」这个面）。
    """
    plan = plan_naming(library_id)
    allow = {str(x) for x in (subset or []) if str(x or "").strip()}
    targets = [it for it in plan["items"]
               if it["changed"] and not it["conflict"]
               and (not allow or it["book_id"] in allow)]
    items = []
    for it in targets:
        res = resolve(it["book_id"], "rebuild")
        items.append({"book_id": it["book_id"], "name": it["name"],
                      "old_rel": it["old_rel"], "new_rel": it["new_rel"],
                      "rel": str(res.get("rel") or ""), "ok": bool(res.get("ok")),
                      "error": str(res.get("error") or "")})
    done = sum(1 for x in items if x["ok"])
    # 每本的成功/失败已由 publish/process 各自记日志，这里只补一条批次小结
    _log(str(library_id or "全部书库"),
         f"按命名规则重出版：成功 {done} / 共 {len(items)}"
         f"（跳过 {len(plan['items']) - len(targets)}：名字未变或落点冲突）")
    return {"ok": True, "total": len(items), "done": done, "failed": len(items) - done,
            "skipped": len(plan["items"]) - len(targets), "items": items}


# ---------------- worker ----------------

def run_once(limit: int = _BATCH) -> dict:
    """同步跑一批待办（「立即跑一次」与测试用；不在后台线程里）。"""
    rows = db.scrape_pending(limit=int(limit))
    items = []
    for r in rows:
        res = process(r.get("book_id"))
        items.append({"book_id": str(r.get("book_id")),
                      "source_rel": r.get("source_rel") or "", **res})
    return {"processed": len(items), "items": items}


def start() -> bool:
    """启动后台 worker（幂等）。返回是否**本次**真的启动了。

    启动时把残留的 ``running`` 打回 ``pending`` —— 上次进程被 kill 时进行中的
    条目不该永远卡住。
    """
    global _thread, _stop, _epoch
    with _lock:
        if _thread and _thread.is_alive():
            return False
        _stop = False
        _epoch += 1                     # 新一轮 = 新世代（上一轮的残留写入从此被拒）
        try:
            db.scrape_reset_running()
        except Exception:                             # noqa: BLE001
            pass
        _thread = threading.Thread(target=_loop, name="nf-scrape", daemon=True)
        _thread.start()
        return True


def stop(timeout: float = 0.0) -> None:
    """停止 worker。``timeout > 0`` 时等它真的退出（测试收尾 / 关服务时用）。

    ⚠️ 测试里**必须**带 timeout 收尾：worker 是 daemon 线程，而测试的 DB 是
    用例级隔离的（``db.close()`` + ``db.init()``）——一个跨用例活着的线程会拿着
    旧连接去查新库，制造「单独跑必过、全量跑随机挂」的假故障。

    ⚠️ 但 timeout **等不到它真的退出**（单条处理不可中断，见 ``_epoch``）。
    所以本函数一定会推进世代号：那之后残留线程即使跑完手上这条，也**写不进库**。
    """
    global _stop, _epoch
    _stop = True
    with _lock:
        _epoch += 1                     # 作废当前世代 —— 这一步才是「收尾干净」的保证
    _wake.set()
    t = _thread
    if timeout > 0 and t is not None and t.is_alive():
        t.join(timeout=timeout)


def _loop() -> None:
    """worker 主循环：有活就串行干，空闲按周期校验副本是否还在。

    ``gen`` 是本轮的世代号：**每次碰库前后都校验**，作废即停手且不落库。
    """
    global _last_verify
    gen = epoch()
    while not _stop and not _stale(gen):
        try:
            rows = db.scrape_pending(limit=_BATCH)
            if rows:
                for r in rows:
                    if _stale(gen):
                        break
                    process(r.get("book_id"), gen=gen)
                continue                              # 立刻看下一批，不等
            try:
                interval = float(_section().get("verify_interval") or 0)
            except (TypeError, ValueError):
                interval = 0.0
            if interval > 0 and time.time() - _last_verify >= interval:
                _last_verify = time.time()
                verify(gen=gen)
            _wake.wait(timeout=_IDLE_WAIT)
            _wake.clear()
        except Exception as e:                        # noqa: BLE001 —— worker 不能死
            _logger.exception("刮削 worker 异常：%s", e)
            time.sleep(1.0)


def wake() -> None:
    """立刻唤醒 worker（入队后调用，省一次等待）。"""
    _wake.set()
