"""后台作业的**编排**（第 265 期从 `server.py` 挪下来）。

两条作业都是纯领域流程 —— 「把源站内容落到这本书上」与「按产物类型下载一本书」：
状态机（`db.task_update` 的 0/50/100 三个真实里程碑）、活动日志、落点选择、产物分流。
它们此前长在 `server.py` 里，与 433 条路由挤在同一个 1.2 万行文件里 ——
改一处后台作业要在一个 1.2 万行的文件里定位。

**依赖由调用方注入**（管理器 / 收书目录 / `INPUT_DIR`）：这些是**运行时单例**，
属于 Web 层的装配，不属于领域逻辑。`core` 不认识 HTTP，也不持有全局单例。
"""
from __future__ import annotations

import asyncio
import pathlib

from . import activity_log, autoupdate, db, landing, library_rules, lib_settings

#: 产物类型 → 交给 `resolve_target` 判库用的**代表文件名**。
#: ⚠️ 音频产物最终是**目录**，但 `resolve_target` 是按**扩展名 + 关键词**判库的 ——
#: 用 `.mp3` 这个代表名才判得进「有声书」那类库。
KIND_PROBE_NAME = {"text": "{t}.epub", "comic": "{t}.cbz", "audio": "{t}.mp3"}


async def dispatch_product(mgr, kind: str, item: dict, root, opts: dict, *, input_dir):
    """按产物类型分流下载（第 86 期）：文本 → EPUB、漫画 → CBZ、有声书 → 目录树。"""
    if kind == "comic":
        return await mgr.download_comic(item, root, opts)
    if kind == "audio":
        return await mgr.download_audio(item, root, opts)
    return await mgr.download_to(item, root, input_dir, opts)


async def run_download(mgr, tid: str, item: dict, *, actor: str = "系统",
                       kind: str = "text", input_dir, watcher=None):
    """书源下载作业（`/api/download` 的后台那一半）。

    ``watcher`` 传**取值函数**（不是实例）：作业排队期间收书目录可能还没建起来。
    """
    # progress 只记**真实里程碑**：0 = 已入队、50 = 已开始、100 = 已结束。
    # 下载器不报细分进度，因此不伪造中间百分比。
    db.task_update(tid, status="running", progress=50.0)
    try:
        # 多书库：书源下载走产出 EPUB，按「来源子目录名 → 格式 → 关键词」归库。
        # 没有可接收的库（一个库都没有，或规则不命中）⇒ 拒收，如实报错，不猜落点。
        kind = kind or "text"
        dl_name = KIND_PROBE_NAME.get(kind, "{t}.epub").format(
            t=item.get("title") or "book")
        tgt = library_rules.resolve_target(
            name=dl_name,
            meta={"title": item.get("title"), "author": item.get("author")},
        )
        if tgt["root"] is None:
            raise RuntimeError(library_rules.no_library_reason(name=dl_name))
        # 第 13 期：产物格式 / 落盘布局按**目标库**取（库没覆写时等于全局值）
        opts = {"force": True, "merge": True,
                "cfg": lib_settings.config_for(tgt["library_id"] or None)}
        res = await dispatch_product(mgr, kind, item, tgt["root"], opts, input_dir=input_dir)
        notice = opts.get("_notice", "")
        path = pathlib.Path(res)
        name = path.name
        db.task_update(tid, status="done", progress=100.0,
                       result=f"/download/{name}", fname=name, notice=notice)
        activity_log.log_convert_ok(
            item.get("title") or name, name, source="download",
            # 音频产物是**目录**：对目录取 st_size 是个毫无意义的数字，如实留空
            size=(path.stat().st_size if path.is_file() else None),
            detail=notice, actor=actor,
        )
        # ⚠️ 只有「文本」这条链路会顺带落一个 txt，才需要把它登记为已处理；
        #    漫画 / 音频不产 txt，无条件 mark_recent 会把同一时间窗里**别人的** txt 一起盖掉。
        w = watcher() if callable(watcher) else watcher
        if kind == "text" and w is not None:
            await asyncio.to_thread(w.mark_recent, seconds=30, suffix=".txt")
    except Exception as e:
        db.task_update(tid, status="failed", progress=100.0, error=str(e))
        activity_log.log_convert_fail(
            item.get("title") or item.get("url") or "(未命名)",
            f"{type(e).__name__}: {e}", source="download", actor=actor,
        )


async def sync_worker(mgr, tid: str, b: dict, row: dict | None, *, actor: str = "系统",
                      overwrite: bool = False, allow_first: bool = True) -> None:
    """「把源站内容落到这本书上」的**唯一后台实现**（两条触发路都走它）。

    报告一律落进任务行（``notice`` 里是给人看的那句），**绝不吞掉原因**。三种结局分得开：

    · ``first`` —— 整本落地成功：活动日志记「添加」（与收书目录收进来的书同一口径）；
    · ``append`` —— 追加成功：**账已经由 `autoupdate.update_book_async` 记过了**，这里不再记
      第二笔（两处都记会让同一本书在活动日志里出现两行，用户以为发生了两件事）；
    · ``skip`` —— 什么都没做：如实记「失败」+ 原因。活动日志的状态词表只有成功 / 失败两档，
      而「未自动写入」是用户**必须**看到的一条（不是一句可忽略的提示）。
    """
    db.task_update(tid, status="running", progress=50.0)
    title = b.get("title") or b.get("name") or ""
    try:
        reason = mgr.gate_reason()
        if reason:
            raise RuntimeError(reason)
        if row:
            rep = await landing.sync(mgr, b, row, overwrite=overwrite, allow_first=allow_first)
        else:
            # 只有留档、没有绑定：就是既有追更（同一函数、同一账）。
            res = await autoupdate.update_book_async(b, mgr, origin="check-update")
            added = int(res.get("added") or 0)
            rep = {"mode": "append", "added": added, "note": str(res.get("note") or ""),
                   "epub": str(res.get("epub") or ""), "title": landing.book_stem(b),
                   "path": "", "detail": (f"新增 {added} 章" if added
                                          else (res.get("note") or "没有新章节"))}
        mode = str(rep.get("mode") or "")
        note = str(rep.get("detail") or rep.get("note") or "")
        name = str(rep.get("title") or landing.book_stem(b))
        db.task_update(tid, status="done", progress=100.0, notice=note, fname=name)
        if mode == "first":
            activity_log.log_add_ok(name, str(rep.get("path") or ""), detail=note,
                                    actor=actor, source="online")
        elif mode == "skip":
            activity_log.log(activity_log.ACTION_UPDATE, name, activity_log.STATUS_FAIL,
                             detail=f"未执行：{note}", actor=actor, source="online")
    except Exception as e:
        db.task_update(tid, status="failed", progress=100.0, error=str(e))
        activity_log.log(activity_log.ACTION_UPDATE, title, activity_log.STATUS_FAIL,
                         detail=f"检查更新失败：{e}", actor=actor, source="online")
