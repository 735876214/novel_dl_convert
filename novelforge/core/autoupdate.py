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
   第 93 期把「**单本**追更」也收敛成一处 :func:`update_book`（读留档 → 过闸门 → 追更 →
   记日志 → 返回报告）：定时轮次、详情页的「检查更新」、自动落地之后的更新都走它。
   三处各写一遍「读留档 + 记一笔账」时，最容易分叉的恰恰是**日志措辞与闸门**。
4. **追更也过闸门**（第 93 期补）—— 见下。

## 第 93 期补的两处（都是既有漏子，行为变化）

**① 追更原先完全不过闸门。** `download.enabled` 默认 **False**，而本模块照样逐本外呼抓正文 ——
正是第 71 / 80 期口径里点名的那种「假开关」：设置页写着「关闭时不搜索不下载」，定时线程照跑。
现在 `tick()` 在枚举完候选、动手之前先问 ``DownloadManager.gate_reason()``，被拦就**一本都不外呼**，
把闸门原文放进报告（``rep["blocked"]``）—— 手动按「立即追更」的人必须看到「为什么什么都没做」，
而不是一句「检查 N 本，新增 0 章」的假汇报（那句会被读成「源上没有新章节」）。

**② `DownloadManager()` 少传了 cfg。** 构造函数签名是 ``__init__(self, cfg: dict)``（**必填**），
而这里原先是无参调用 ⇒ 每轮都在 ``except`` 里静默退化成「构造下载器失败（本轮跳过）」，
**定时追更从来没真正跑过一本**。既有用例钉不到它：它们要么 monkeypatch 掉 `tick`，
要么只测候选枚举。改成与 `server._manager()` 同口径的 ``DownloadManager(config.load_config())``。
（这也是①的前提：闸门判据本身要从配置里读。）

⚠️ 线程生命周期交给 `server.py` 的 lifespan（起：刮削之后；停：与 `scrape.stop()` 并列），
与 updater 同一范式 —— 这类**长期循环**线程不进 `watcher._BG_THREADS`
（那张表是给「短命旁路任务」收尾用的，长期循环会把收尾 join 卡死）。
"""
import json
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


class Blocked(RuntimeError):
    """闸门未放行（``args[0]`` 是**可直接展示**的原因原文，与 `gate_reason()` 逐字一致）。

    为什么不返回一份「新增 0 章」的报告：调用方（含详情页的「检查更新」）必须能分出
    「源上没有新章」与「你自己关着下载开关」——后者是一句**指令**，前者只是一条状态。
    """


def sidecar_of(book: dict) -> pathlib.Path | None:
    """这本书的**留档**（`<stem>.meta.json`）路径；判不出来返回 ``None``。

    ⚠️ **在收书目录（`config.INPUT_DIR`）下，不在书库根下** —— 这是第 93 期修的一个
    真 bug：留档由 `manager.write_sidecar` 写在**原件旁边**，而下载链路把原件（txt）
    落在收书目录、把成品（epub）落在书库根（`download_to(item, out_dir, input_dir, opts)`）。
    第 86 期原先按「书库根 + 货名去后缀」算，于是**正常布局下一本都找不到**
    （只有「收书目录恰好就是书库根」的单目录部署才碰得上，测试正是那么造的现场，
    所以一直绿着）。`config.DEFAULTS["watch"]["ignore"]` 里那条 `*.meta.json` 也是
    为它留的：留档写在**被监听**的收书目录里，不排除就会被当成待转换的文件。

    ⚠️ 拼法**只有这一处**（书库扫描给的 `name` 是成品名，两者基名相同 —— 下载的 txt 与
    转出的 epub 同名）。**不查 DB**：留档就在原件旁边，比「遍历书目再反查来源」直接，
    也不受索引刷新时机影响。
    ⚠️ 本函数**只拼路径、不判存在**（`is_file()` 交给调用方）—— 这样它既能当
    「有没有留档」的判据，也能当「留档该写在哪」的判据（落地时要写它）。
    """
    stem = pathlib.PurePosixPath(str((book or {}).get("name") or "")).stem
    if not stem:
        return None
    return pathlib.Path(config.INPUT_DIR) / f"{stem}.meta.json"


def candidates(limit: int = 0) -> list:
    """本轮要追更的书目（``[{"name", "sidecar", "book"}...]``）。**只读枚举、不外呼**。

    判据：书库里每本书的同名 sidecar 是否存在 —— sidecar 是「这本书是下载来的」
    的唯一持久痕迹（`sources/manager.write_sidecar`）。

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
            sidecar = sidecar_of(b)
            if sidecar is not None and sidecar.is_file():
                out.append({"name": sidecar.name[:-len(".meta.json")],
                            "sidecar": sidecar, "book": b})
        except Exception:                                # noqa: BLE001 —— 单本失败不拖累整轮
            continue
        if limit and len(out) >= int(limit):
            break
    return out


def update_book(book: dict, mgr=None, *, origin: str = "auto-update") -> dict:
    """**单本追更的唯一入口**：读留档 → 过闸门 → `manager.update_report` → 记日志 → 返回报告。

    顺序是刻意的（第 93 期）：**先读留档再问闸门**，因为闸门的入参是「源」——
    而「这本书来自哪个源」只有留档知道。被拦下时抛 :class:`Blocked`（原文照传），
    **不返回假报告**；其余异常照常冒出（调用方逐本吞并计数，不让一本书拖垮整轮）。

    它同时是**活动日志的唯一写点**（原先这段在 `tick()` 里）：定时轮次、手动「检查更新」、
    自动落地后的更新都调这里，日志措辞就只有一份 —— 两处各写一份必然分叉。

    ⚠️ 真正的追更保证（只追加 / 原子写 / 并发互斥 / 既有章 index 不漂移）仍然**只在**
    `manager.update_report` 一处，本函数不复制它。
    """
    from ..sources import manager as mgr_mod
    sidecar = sidecar_of(book)
    if sidecar is None:
        raise ValueError(f"算不出这本书的留档路径（{book.get('name')}），无法追更")
    if not sidecar.is_file():
        raise ValueError(f"未找到 sidecar 元数据 {sidecar.name}，无法增量更新")
    name = sidecar.name[:-len(".meta.json")]
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    mgr = mgr if mgr is not None else mgr_mod.DownloadManager(config.load_config())
    reason = mgr.gate_reason(meta.get("source"))
    if reason:
        raise Blocked(reason)
    txt = sidecar.with_suffix("").with_suffix(".txt")
    try:
        res = _run_one(mgr, txt)
    except Exception as e:                               # noqa: BLE001 —— 记一笔再照原样冒出
        activity_log.log(activity_log.ACTION_UPDATE, name, activity_log.STATUS_FAIL,
                         detail=f"追更失败：{e}", source=origin)
        raise
    res = dict(res or {})
    added = int(res.get("added") or 0)
    if res.get("note"):
        activity_log.log(activity_log.ACTION_UPDATE, name, activity_log.STATUS_OK,
                         output=str(txt.parent), detail=str(res["note"]), source=origin)
    elif added:
        activity_log.log(activity_log.ACTION_UPDATE, name, activity_log.STATUS_OK,
                         output=str(txt.parent), detail=f"新增 {added} 章", source=origin)
    return res


def tick(conf: dict = None) -> dict:
    """跑**一轮**追更：串行、每本之间节流、逐本如实记账。**绝不外抛异常**。

    返回 ``{"total", "ok", "skipped", "errors", "added"}`` —— 供日志与
    `state()` 用；失败逐本记 `activity_log`，不让一本书拖垮整轮。
    ``total > 0`` 时可能另带 ``"blocked"``（闸门原文；此时**一本都没外呼**，全部计入
    ``skipped``）—— 见模块文档第 4 条：报告必须是「干了什么」的实录，
    「被拦下」与「源上没有新章」是两件事，不能都长成「新增 0 章」。

    ⚠️ ``conf`` 只管**调度**（`max_books` / `request_delay`）；闸门判据**只从配置读**
    （``DownloadManager.gate_reason()``，唯一一处），不接受参数覆盖 —— 否则调用方
    能顺手把开关绕过去，那就又变成了假开关。
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
        # ⚠️ cfg **必传**（见模块文档第 4 条②）：少了它构造就抛，整轮静默跳过。
        mgr = mgr_mod.DownloadManager(config.load_config())
    except Exception as e:                               # noqa: BLE001
        _log.warning("追更：构造下载器失败（本轮跳过）：%s", e)
        return rep
    blocked = mgr.gate_reason()
    if blocked:
        # 闸门管的是「真的去搜去下」。被拦就与 `/api/search`、`/api/download` 同款处理：
        # **一次外呼都不发**，并把同一句原文回给调用方（措辞只有一处）。
        rep["skipped"] = len(files)
        rep["blocked"] = blocked
        _log.info("追更：闸门未放行，本轮一本都没跑（%s）", blocked)
        return rep
    for i, cand in enumerate(files):
        name = cand["name"]
        try:
            # 逐本走**同一个**入口（第 93 期收敛）：闸门、报告、活动日志都在 `update_book` 里，
            # 这里只负责计数与节流 —— 定时轮次与手动「检查更新」的措辞因此不可能分叉。
            res = update_book(cand["book"], mgr)
            added = int(res.get("added") or 0)
            rep["ok"] += 1
            rep["added"] += added
            if not added and not res.get("note"):
                rep["skipped"] += 1
        except Blocked as e:
            # 理论上到不了（上面已整轮拦下），但闸门日后若按**源**分级就会走到这里：
            # 那时把它算成「失败」是错的（用户自己的开关，不是站点挂了），记「跳过」。
            rep["skipped"] += 1
            _log.info("追更：闸门未放行，跳过 %s（%s）", name, e)
        except Exception as e:                           # noqa: BLE001
            rep["errors"] += 1
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
