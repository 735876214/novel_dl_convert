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

from . import (activity_log, db, lib_settings, library, metafetch, metastore,
               publish)

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


def process(bid, *, fetch: bool = None) -> dict:
    """处理一本书：可选在线刮削 → 出版副本 → 落状态。**不抛异常**。

    ``fetch``：``None`` = 按配置自动判断（启用且没抓过、或队列标了强制重抓）；
    ``False`` = 只做文件操作（重建副本走这条，不外呼、够快）。
    """
    bid = str(bid)
    row = db.scrape_get(bid) or {}
    lib_id = str(row.get("library_id") or "")
    lib = library.get_library(lib_id) if lib_id else None
    if not lib:
        db.scrape_delete(bid)
        return {"ok": False, "error": "书库已不在（台账已清）"}
    pdir = publish.publish_dir(lib_id)
    if pdir is None:
        db.scrape_set(bid, status="skipped", error="该库未配置成品目录")
        return {"ok": False, "skipped": True, "error": "该库未配置成品目录"}

    try:
        book = library.by_id(bid)
    except Exception as e:                            # noqa: BLE001 —— book_id 冲突等
        db.scrape_set(bid, status="failed", error=f"书目冲突：{e}")
        return {"ok": False, "error": str(e)}
    if not book:
        return _lost(bid, row, lib, "源已不在书目里")

    name = str(book.get("name") or row.get("source_rel") or "")
    src = library.root_of(book) / name
    if not src.exists():
        return _lost(bid, row, lib, "源文件已不在")

    cfg = lib_settings.config_for(lib_id)
    sig = publish.source_sig(src)
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
        return _failed(bid, row, lib_id, res.get("error") or "未知失败", name)
    finally:
        _set_current("")


def _failed(bid, row, lib_id, error: str, name: str) -> dict:
    """失败：未到上限打回 pending（下轮再试），到上限标 failed 等人工。"""
    attempts = int(row.get("attempts") or 0) + 1
    over = attempts >= _max_attempts(lib_id)
    db.scrape_set(bid, status="failed" if over else "pending", attempts=attempts,
                  error=error)
    _log(name, f"刮削失败（第 {attempts} 次）：{error}", ok=False)
    return {"ok": False, "error": error, "attempts": attempts, "give_up": over}


def _lost(bid, row, lib, why: str) -> dict:
    """源不见了：副本还在 → 孤本待处置；副本也没了 → 台账没有意义，清掉。"""
    pdir = publish.publish_dir(str(lib.get("id")))
    rel = str(row.get("link_rel") or "")
    copy = (pdir / rel) if (pdir and rel) else None
    name = str(row.get("source_rel") or bid)
    if copy is not None and copy.exists():
        db.scrape_set(bid, status="orphan", error=f"{why}，副本为唯一留存")
        _log(name, f"原文件已不在（{why}），副本为唯一留存：{copy}")
        return {"ok": False, "orphan": True, "error": why}
    db.scrape_delete(bid)
    return {"ok": False, "error": f"{why}，且副本也不在（台账已清）"}


# ---------------- 校验（只标记，不处置）----------------

def verify(library_id=None) -> dict:
    """校验已出版副本与源文件是否还在。**只降级标记 + 记日志，绝不处置。**

    - 副本缺失 → ``removed``（待确认：是否连原文件一起删）
    - 源缺失而副本在 → ``orphan``（副本是唯一留存了）

    返回 ``{checked, removed: [...], orphan: [...]}``，供接口回显。
    """
    rows = db.scrape_list(library_id=library_id, status="ok")
    removed, orphan = [], []
    for row in rows:
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
    global _thread, _stop
    with _lock:
        if _thread and _thread.is_alive():
            return False
        _stop = False
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
    """
    global _stop
    _stop = True
    _wake.set()
    t = _thread
    if timeout > 0 and t is not None and t.is_alive():
        t.join(timeout=timeout)


def _loop() -> None:
    """worker 主循环：有活就串行干，空闲按周期校验副本是否还在。"""
    global _last_verify
    while not _stop:
        try:
            rows = db.scrape_pending(limit=_BATCH)
            if rows:
                for r in rows:
                    if _stop:
                        break
                    process(r.get("book_id"))
                continue                              # 立刻看下一批，不等
            try:
                interval = float(_section().get("verify_interval") or 0)
            except (TypeError, ValueError):
                interval = 0.0
            if interval > 0 and time.time() - _last_verify >= interval:
                _last_verify = time.time()
                verify()
            _wake.wait(timeout=_IDLE_WAIT)
            _wake.clear()
        except Exception as e:                        # noqa: BLE001 —— worker 不能死
            _logger.exception("刮削 worker 异常：%s", e)
            time.sleep(1.0)


def wake() -> None:
    """立刻唤醒 worker（入队后调用，省一次等待）。"""
    _wake.set()
