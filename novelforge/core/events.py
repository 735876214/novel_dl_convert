"""进程内实时事件总线（第 153 期）。

## 为什么

上游 BookOrbit 用 Socket.IO 把「后台发生了什么」推给前端（`book-dock:changed`、
`book:progress-changed`、`book-metadata-fetch:status`…）。本项目此前只有轮询：
任务中心在有活跃任务时每几秒拉一次，通知浮层更是只在打开时拉 —— 后台完成的事情
要等下一次轮询（或用户点开）才看得见。

本模块只做**一件事**：把「某件事发生了」从任意线程（含 watcher / 刮削线程）
送到所有已连接的 WebSocket。它**不**保存历史、**不**做重放、**不**保证送达 ——
前端连上后仍以 HTTP 为准（断线回退轮询），事件只是「提前知道该刷新了」。

## 线程模型

- 订阅者在 **事件循环线程** 里 `subscribe()`，得到 `(queue, loop)`。
- 任何线程都可以 `publish()`；它用 `loop.call_soon_threadsafe` 投递，
  所以 watcher / 刮削 / 任务线程无需自己持 loop。
- 队列满时**丢最旧的一条**：界面要的是最新状态，积压旧事件只会让刷新更慢。
- 没有订阅者时 `publish()` 是纯空操作（CLI / 单测里不会因此报错）。

## 事件名

与上游对齐的用冒号形式；新增事件必须先有**真实发布点**再让前端订阅
（AGENTS「不做假交互」）。当前：

- `notifications:new` —— 活动日志新增一条（前端刷新未读角标）
- `book:progress-changed` —— 任一写入口写了阅读进度
- `book-dock:changed` —— 收书目录出/入/改/删
- `book-metadata-fetch:status` —— 批量元数据抓取状态变化（运行/暂停/结束）
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

_logger = logging.getLogger(__name__)

#: 每个订阅者最多积压多少条；满了丢最旧。64 条≈一次扫描的批次量，够前端追平。
MAX_QUEUE = 64

_lock = threading.Lock()
_subscribers: dict[asyncio.Queue, asyncio.AbstractEventLoop] = {}


def subscribe() -> asyncio.Queue:
    """在**当前事件循环**里订阅，返回队列。必须由 `asyncio` 上下文调用。"""
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
    with _lock:
        _subscribers[queue] = loop
    return queue


def unsubscribe(queue: asyncio.Queue) -> None:
    with _lock:
        _subscribers.pop(queue, None)


def subscriber_count() -> int:
    with _lock:
        return len(_subscribers)


def publish(event: str, data: dict[str, Any] | None = None) -> None:
    """从任意线程发布一个事件；没有订阅者时是空操作。"""
    with _lock:
        targets = list(_subscribers.items())
    if not targets:
        return

    payload = {
        "event": event,
        "ts": round(time.time(), 3),
        "data": data or {},
    }

    for queue, loop in targets:
        def _put(q: asyncio.Queue = queue, p: dict = payload) -> None:
            try:
                if q.full():
                    q.get_nowait()          # 丢最旧
                q.put_nowait(p)
            except Exception:               # 队列关闭 / 循环已停：这一个订阅者作废
                pass

        try:
            loop.call_soon_threadsafe(_put)
        except RuntimeError:
            # 事件循环已关闭：静默丢弃（服务正在退出，重连时会以 HTTP 为准）
            pass
        except Exception as exc:            # pragma: no cover - 防御性
            _logger.debug("events.publish 失败（%s）：%s", event, exc)
