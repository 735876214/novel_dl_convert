"""追更的并发保护（第 87 期收尾）。

`update_report` 是「读 sidecar → 抓章节 → **读全文** → 写 `.part` → replace」。
两个并发调用各自读到同一份旧内容 ⇒ 后写覆盖前写 = **丢章**，而且两边都返回
「已追加 N 章」—— 用户只会发现「少了几章」，没有任何报错。所以入口必须按**路径**串行。

零网络：这里只测锁的机制（真跑两路追更需要桩源，属 `test_update_report.py` 的范畴）。
"""
import asyncio

from novelforge.sources import manager


def test_同一路径永远拿到同一把锁():
    a1 = manager.update_lock("书.txt")
    a2 = manager.update_lock("书.txt")
    b = manager.update_lock("另一本.txt")
    assert a1 is a2, "同一个文件必须共用一把锁，否则等于没锁"
    assert a1 is not b, "不同文件必须是不同的锁（否则批量追更被全局串行化）"


def test_同一把锁下两路不会交错():
    """真正的机制验证：先拿到的跑完，另一路才开始（`in/out` 不会交织）。"""
    order: list = []

    async def job(tag: str, delay: float):
        async with manager.update_lock("同一本.txt"):
            order.append(f"{tag}-in")
            await asyncio.sleep(delay)
            order.append(f"{tag}-out")

    async def main():
        await asyncio.gather(job("a", 0.03), job("b", 0.0))

    asyncio.run(main())
    assert order == ["a-in", "a-out", "b-in", "b-out"], f"不能交错：{order}"


def test_不同文件可以并行():
    """按路径加锁的意义：两本不同的书互不阻塞（批量追更不该被拖成串行）。"""
    order: list = []

    async def job(tag: str, path: str):
        async with manager.update_lock(path):
            order.append(f"{tag}-in")
            await asyncio.sleep(0.03)
            order.append(f"{tag}-out")

    async def main():
        await asyncio.gather(job("a", "甲.txt"), job("b", "乙.txt"))

    asyncio.run(main())
    assert order == ["a-in", "b-in", "a-out", "b-out"], f"应当并行：{order}"
