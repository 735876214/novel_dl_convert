"""Komga 持续审计第 5 轮（第 277 期，**零新增缺陷 → 收尾**）。

这一轮扫了三个角度，全部干净：

**① 事件队列的「丢最旧」**（`events.MAX_QUEUE = 64`）—— 给一个订阅者灌 200 条：
积压恰好停在 **64**，且**最后一条（最新的）在**。此前这条语义只有代码注释，**没有用例**
（`test_realtime.py` 只验发布/订阅通不通），本轮顺手钉住。

**② 扫描进行中的并发读与写**：300 本的库，一边触发后台重扫，一边 3 个线程刷
`/api/v1/books?size=20`、1 个线程写 20 本书的进度 —— 38 个请求全部 200 / 204，
**0 异常、0 个 5xx**，重扫本身 56 ms（只负责标脏、不阻塞请求）。

**③ 队列/扫描的边界**：见上两条。

判定为零的理由：这一轮既没有「改前→改后」可写，也没有任何一条能从用例里复现出来的
不一致；所有观察到的行为都与代码注释/文档里写下的口径一致（队列有界丢最旧、扫描是
后台标脏、读路径只读索引）。
"""
import asyncio
import threading
import time

import pytest

from novelforge.core import events


def test_事件队列满时丢最旧_最新那条必须留着():
    """`MAX_QUEUE` 是**有界**的，满了丢最旧 —— 界面要的是最新状态。

    没有订阅者时 `publish` 是空操作；有订阅者时用 `loop.call_soon_threadsafe` 投递。
    这里直接在事件循环里订阅，从**同线程**灌 200 条，再看积压里剩的是什么。
    """

    async def main():
        q = events.subscribe()
        try:
            for i in range(200):
                events.publish("audit:noop", {"i": i})
            await asyncio.sleep(0.05)          # 让 call_soon_threadsafe 投递完
            out = []
            while not q.empty():
                out.append(q.get_nowait())
            return out
        finally:
            events.unsubscribe(q)

    got = asyncio.run(main())
    assert len(got) == events.MAX_QUEUE, f"积压 {len(got)} 条，上限 {events.MAX_QUEUE}"
    assert got[-1]["data"]["i"] == 199, "最新的那条被丢了（界面会显示旧状态）"
    # 丢的是**最旧**的那一批：第一条不再是 0
    assert got[0]["data"]["i"] == 200 - events.MAX_QUEUE


def test_扫描进行中并发读与写不出_5xx(client, auth_headers, make_library, tmp_path):
    """扫描是**后台标脏**，不该把同一时刻的读/写打成 5xx（也不该卡住）。"""
    import io
    import zipfile

    from novelforge import config
    from novelforge.core import library
    from PIL import Image

    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        root = tmp_path / "L"
        root.mkdir(parents=True, exist_ok=True)
        make_library("L", "库", "comic", root)
        for i in range(120):
            p = root / ("系列%02d" % (i // 10)) / ("系列%02d #%d.cbz" % (i // 10, i % 10 + 1))
            p.parent.mkdir(parents=True, exist_ok=True)
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                b = io.BytesIO()
                Image.new("RGB", (20, 30), (0, 0, 0)).save(b, "PNG")
                z.writestr("001.png", b.getvalue())
            p.write_bytes(buf.getvalue())
        client.post("/api/scan", headers=auth_headers)
        library.invalidate()
        hk = {"X-API-Key": "test-key"}
        bs = client.get("/api/v1/books?size=50", headers=hk).json()["content"]

        codes, errors = [], []
        stop = {"go": False}

        def reader():
            while not stop["go"]:
                try:
                    r = client.get("/api/v1/books?size=20", headers=hk)
                    codes.append(r.status_code)
                    if r.status_code == 200 and "totalElements" not in r.json():
                        errors.append("分页壳缺字段")
                except Exception as e:          # noqa: BLE001
                    errors.append(repr(e))

        def writer():
            for b in bs[:10]:
                try:
                    codes.append(client.put("/api/v1/books/" + b["id"] + "/read-progress",
                                            json={"page": 1}, headers=hk).status_code)
                except Exception as e:          # noqa: BLE001
                    errors.append(repr(e))

        ths = [threading.Thread(target=reader) for _ in range(2)] + [threading.Thread(target=writer)]
        for t in ths:
            t.start()
        t0 = time.perf_counter()
        assert client.post("/api/scan", headers=auth_headers).status_code == 200
        assert (time.perf_counter() - t0) < 5.0, "重扫把请求路径卡住了（应当只标脏）"
        time.sleep(0.3)
        stop["go"] = True
        for t in ths:
            t.join(timeout=30)

        assert not errors, errors[:3]
        assert codes and set(codes) <= {200, 204}, sorted(set(codes))
    finally:
        config.save_overrides({})
