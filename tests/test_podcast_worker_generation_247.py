"""播客下载 worker 的**世代号**（第 247 期）。

## 为什么需要

worker 是**跨用例常驻**的 daemon 线程（`while True` 阻塞在 `_q.get()`），而测试的 DB
是**用例级隔离**的（`db.close()` + `db.init()`）⇒ 一个跨用例活着的线程会拿着
**旧连接**去查**新库** ⇒ 「单独跑必过、全量跑随机挂」的假故障
（与 `core/scrape.py::stop` 的注释是同一件事；播客第 173 期漏了这套机制）。

实测（Linux 容器）：`test_podcast_download_175.py` 与 `test_podcast_auto_181.py`
一起跑时两条红，单独跑都绿。

## 修法

`stop_worker()` 作废**世代号**（+1）⇒ 残留线程醒来时发现世代变了 ⇒ 直接丢弃手上的
任务：**不查库、不写库、不落文件**。

## 这里钉三件事

1. `stop_worker()` 会让**排队中**的任务被丢弃（返回丢弃条数）；
2. 作废后的 worker **不写库**（世代不匹配的任务直接返回）；
3. 作废后**还能重新排队**（`_ensure_worker` 会再起一个 worker）—— 否则功能会瘫。
"""
from __future__ import annotations

import queue

from novelforge.core import db, podcasts


def test_stop_worker_丢弃排队中的任务():
    """排队里塞两个，stop 之后队列应当是空的。"""
    podcasts._q.put("ep-a")
    podcasts._q.put("ep-b")
    dropped = podcasts.stop_worker(0.0)
    assert dropped == 2, dropped
    assert podcasts._q.qsize() == 0, podcasts._q.qsize()
    assert podcasts._q.unfinished_tasks == 0, podcasts._q.unfinished_tasks


def test_世代不匹配的任务不写库(isolated, monkeypatch):
    """世代已变 ⇒ `_download_one` 直接返回，**一次库都不碰**。"""
    calls = []
    monkeypatch.setattr(podcasts, "db", type("D", (), {
        "get_podcast_episode": lambda eid: calls.append(eid) or None,
    })())

    old_gen = podcasts._gen
    try:
        # 用一个**过期**的世代号调用 ⇒ 应当立刻返回
        podcasts._download_one("ep-x", old_gen - 1)
        assert calls == [], f"世代不匹配还去查库了：{calls}"
    finally:
        podcasts._gen = old_gen


def test_stop_worker_之后还能重新排队(isolated, monkeypatch):
    """作废后 `_ensure_worker` 必须能再起一个 worker（否则功能瘫）。"""
    podcasts.stop_worker(0.0)
    # 起一个 worker（只验证「能起来」，不真的下载）
    podcasts._ensure_worker()
    assert podcasts._worker_started is True
    # 队列能再放进去
    podcasts._q.put("ep-z")
    assert podcasts._q.qsize() >= 1
    podcasts.stop_worker(0.0)


def test_收尾会作废播客_generation():
    """收尾夹具**必须**调用 `stop_worker`（否则跨用例污染会回来）。

    判据：夹具源码里出现 `stop_worker` —— 收尾那一处是**唯一**该调用它的地方。
    """
    import pathlib
    conf = pathlib.Path(__file__).resolve().parents[1] / "tests" / "conftest.py"
    text = conf.read_text(encoding="utf-8")
    assert "stop_worker" in text, "收尾没有作废播客 worker 的世代号 ⇒ 跨用例污染会回来"
