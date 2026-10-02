"""书籍**追更**的后台调度（第 86 期最后一项）。

与 `core/updater.py`（**应用自身**的版本检查）是两件事，名字刻意分开，免得混淆。
骨架照抄 updater：daemon 线程 + **每次 start 换新 stop Event** + 每轮重读间隔
（改配置不必重启进程，热应用见 `server._apply_auto_update_config`）。

三条口径（都有测试钉住）：

1. **首轮不立刻跑** —— 延迟一个间隔才动。⚠️ 否则每次重启服务（含自动更新重建容器）
   都会对**全部**书外呼一轮。updater 那边「启动即检」是因为它只发**一次**请求，追更不是。
2. **礼貌节流且串行**：单轮最多 `max_books` 本、每本之间 `request_delay` 秒。
   并发外呼会被站点限流甚至封禁 —— 与 `core/watcher.py` 里那条既有注释同口径。
3. **不重复实现追更**：只调 `sources.manager.update_report` —— 它是**同路径互斥的唯一入口**，
   所以「只追加 / 原子写 / 并发保护 / 既有章 index 不漂移」这些保证仍然只在一处。

⚠️ 线程生命周期交给 `server.py` 的 lifespan（起：刮削之后；停：与 `scrape.stop()` 并列），
与 updater 同一范式 —— 这类**长期循环**线程不进 `watcher._BG_THREADS`
（那张表是给「短命旁路任务」收尾用的，长期循环会把收尾 join 卡死）。
"""
import logging
import pathlib
import threading
import time

from .. import config
from . import activity_log, library

_log = logging.getLogger("novelforge")

_thread = None
_stop = None


def _cfg() -> dict:
    """当前 `auto_update` 配置（读不到当空 —— 由调用方给默认值）。"""
    try:
        return dict(config.load_config().get("auto_update") or {})
    except Exception:                                    # noqa: BLE001
        return {}


def candidates(limit: int = 0) -> list:
    """本轮要追更的**留档清单**（`*.meta.json` 路径）。**只读枚举、不外呼**。

    判据：书库里每本书的同名 sidecar 是否存在 —— sidecar 是「这本书是下载来的」
    的唯一持久痕迹（`sources/manager.write_sidecar`）。**不查 DB**：sidecar 就在
    书旁边，比「遍历书目再反查来源」直接，也不受索引刷新时机影响。

    `limit > 0` 时最多收这么多本（单轮上限，防止一次外呼打爆）。
    """
    out: list = []
    try:
        books = library.books()
    except Exception as e:                               # noqa: BLE001
        _log.warning("追更：枚举书目失败（本轮跳过）：%s", e)
        return out
    for b in books:
        try:
            root = library.root_of(b)
            stem = pathlib.PurePosixPath(str(b.get("name") or "")).stem
            if not root or not stem:
                continue
            sidecar = pathlib.Path(root) / f"{stem}.meta.json"
            if sidecar.is_file():
                out.append(sidecar)
        except Exception:                                # noqa: BLE001 —— 单本失败不拖累整轮
            continue
        if limit and len(out) >= int(limit):
            break
    return out


def tick(conf: dict = None) -> dict:
    """跑**一轮**追更：串行、每本之间节流、逐本如实记账。**绝不外抛异常**。

    返回 ``{"total", "ok", "skipped", "errors", "added"}`` —— 供日志与
    `state()` 用；失败逐本记 `activity_log`，不让一本书拖垮整轮。
    """
    conf = dict(conf or _cfg())
    limit = int(conf.get("max_books") or 50)
    delay = max(0.0, float(conf.get("request_delay") or 0))
    rep = {"total": 0, "ok": 0, "skipped": 0, "errors": 0, "added": 0}
    try:
        from ..sources import manager as mgr_mod
    except Exception as e:                               # noqa: BLE001
        _log.warning("追更：加载下载器失败（本轮跳过）：%s", e)
        return rep
    files = candidates(limit=limit)
    rep["total"] = len(files)
    if not files:
        return rep
    try:
        mgr = mgr_mod.DownloadManager()
    except Exception as e:                               # noqa: BLE001
        _log.warning("追更：构造下载器失败（本轮跳过）：%s", e)
        return rep
    for i, sidecar in enumerate(files):
        name = sidecar.name[:-len(".meta.json")]
        try:
            txt = sidecar.with_suffix("").with_suffix(".txt")
            res = _run_one(mgr, txt)
            added = int(res.get("added") or 0)
            rep["ok"] += 1
            rep["added"] += added
            if res.get("note"):
                activity_log.log(activity_log.ACTION_UPDATE, name, activity_log.STATUS_OK,
                                 output=str(sidecar.parent), detail=str(res["note"]),
                                 source="auto-update")
            elif added:
                activity_log.log(activity_log.ACTION_UPDATE, name, activity_log.STATUS_OK,
                                 output=str(sidecar.parent), detail=f"新增 {added} 章",
                                 source="auto-update")
            else:
                rep["skipped"] += 1
        except Exception as e:                           # noqa: BLE001
            rep["errors"] += 1
            activity_log.log(activity_log.ACTION_UPDATE, name, activity_log.STATUS_FAIL,
                             detail=f"追更失败：{e}", source="auto-update")
            _log.warning("追更失败（%s）：%s", name, e)
        if delay and i < len(files) - 1:
            time.sleep(delay)                            # 礼貌节流：不在两本之间连打
    return rep


def _run_one(mgr, txt_path):
    """跑一本（`update_report` 是 async 的，这里同步等它 —— 每本一次 `asyncio.run`）。"""
    import asyncio
    return asyncio.run(mgr.update_report(txt_path, {"cfg": getattr(mgr, "cfg", None)}))


def start_background(interval_hours=None) -> bool:
    """起后台追更线程（已在跑且没被叫停 ⇒ 什么都不做）。返回是否新起了线程。"""
    global _thread, _stop
    conf = _cfg()
    hours = int(interval_hours if interval_hours is not None
                else (conf.get("interval_hours") or 12))
    if _thread is not None and _thread.is_alive() and _stop is not None and not _stop.is_set():
        return False
    _stop = threading.Event()                            # 旧线程攥着旧 Event，不受影响
    _thread = threading.Thread(target=_loop, args=(max(1, hours), _stop),
                               name="novelforge-auto-update", daemon=True)
    _thread.start()
    return True


def _loop(interval_hours: int, stop: threading.Event) -> None:
    """⏳ **先等一个间隔再跑首轮**（见模块文档第 1 条 —— 重启即全量外呼是最该避免的形态）。"""
    interval = max(1, int(interval_hours))
    while not stop.wait(interval * 3600):
        try:
            tick()
        except Exception:                                # noqa: BLE001 —— 旁路功能绝不冒泡
            _log.exception("追更轮次异常")
        try:                                             # 间隔每轮重读 ⇒ 改配置不必重启
            interval = max(1, int(_cfg().get("interval_hours") or interval))
        except Exception:                                # noqa: BLE001
            pass


def stop() -> None:
    """叫停后台线程（lifespan 收尾调用；重复调用安全）。"""
    global _thread
    if _stop is not None:
        _stop.set()
    th, _thread = _thread, None
    if th is not None and th.is_alive():
        th.join(timeout=5)                               # 只等 5 秒：绝不让收尾被网络卡住


def state() -> dict:
    """当前运行态（给接口 / 排查用）。"""
    return {"running": bool(_thread is not None and _thread.is_alive()),
            "interval_hours": int(_cfg().get("interval_hours") or 12),
            "enabled": bool(_cfg().get("enabled", True))}
