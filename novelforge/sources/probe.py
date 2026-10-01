"""书源有效性探测（第 86 期第 4 步）。

## 为什么是「单字」

一个字的查询（默认「我」）是**最省流量、最不容易触发风控**的存活确认：返回 ≥1 条即有效。
比「搜书名」可靠 —— 书名可能真没有，单字几乎一定有。这也是 Legado 生态里的通行做法。

## 四种状态，**互斥且不许混**（第 86 期点名的两件事之一）

| 状态 | 含义 | 出网 | 台账 `verify_ok` | 界面配色 |
|---|---|---|---|---|
| `ok` | ≥1 条，这条源现在能用 | 是 | `True` | 成功色 |
| `zero` | 请求成功但 0 条（规则 / 选择器可能失效） | 是 | `False` | 警示色 |
| `error` | 网络 / 解析异常（原文照回） | 是 | `False` | 警示色 |
| `unsupported` | **不可执行**（判 no / 已停用 / 未知） | **否** | **`None`** | 中性灰 |

⚠️ 两个关键取舍：

1. **`unsupported` 根本不出网** —— 一条判了 `no` 的源（需要 Java 桥 / 地址不是 URL）
   去请求只是白挨风控；而它「不能用」的原因早在台账里写着，如实显示就够了。
2. **`unsupported` 的 `verify_ok` 记 `None`，不是 `False`** —— 那条源**根本没被测过**。
   记成 `False` 会让界面把一个中性事实（不支持）染成警告色（真失败），
   这正是「不支持 ≠ 验证失败」在数据层面的落点。

## 目录来源的探测**不落库**

`probe_toc()` 只读一次目录页，**绝不写 `store_toc`**：探测是「看看这条来源还活着吗」，
顺手落库就把一次随手探测变成「这本书的目录已被覆盖」——那是取目录动作才该干的事。
"""
from __future__ import annotations

import asyncio
import pathlib
import time

from .. import config
from ..core import db
from . import base, toc_sources
from .manager import SEARCH_TIMEOUT

#: 探测用查询词（单字：省流量、不易被风控，且几乎一定有结果）
DEFAULT_QUERY = "我"
#: 「全部验证」时两条之间的停顿（秒）—— 串行 + 间隔是对站点的基本礼貌
DEFAULT_INTERVAL = 1.5

OK, ZERO, UNSUPPORTED, ERROR = "ok", "zero", "unsupported", "error"


def _ms(t0: float) -> int:
    return max(0, int((time.perf_counter() - t0) * 1000))


def _out(name: str, state: str, count: int, t0: float, error: str = "",
         *, supported: str = "yes") -> dict:
    return {"name": name, "state": state, "count": int(count), "ms": _ms(t0),
            "error": str(error or ""), "supported": supported}


def _exists(name: str) -> bool:
    """这条源「真的存在」吗（注册过 / 有规则文件 / 台账里有行）。"""
    return (name in base.REGISTRY
            or pathlib.Path(config.SOURCES_DIR, f"{name}.json").is_file()
            or db.source_ledger_get(name) is not None)


def record(name: str, res: dict) -> dict:
    """把一次探测结果写回台账（**只有真测过的才写**）。"""
    if not res.get("recorded", True) or not _exists(name):
        return res
    db.source_ledger_upsert(
        name, verified_at=time.time(),
        # `unsupported` ⇒ None（没测过）；`ok` ⇒ True；`zero` / `error` ⇒ False
        verify_ok=None if res["state"] == UNSUPPORTED else res["state"] == OK,
        verify_count=res["count"], verify_ms=res["ms"], verify_error=res["error"])
    return res


async def probe(manager, name: str, *, query: str = DEFAULT_QUERY) -> dict:
    """探测一条源（**含回写台账**）：不出的情形绝不假装测过。"""
    t0 = time.perf_counter()
    name = str(name or "")
    row = db.source_ledger_get(name) or {}
    if row.get("supported") == "no":
        return record(name, {**_out(name, UNSUPPORTED, 0, t0,
                                    "这条源判为不可执行（需要 JS 通道或 Android 专有桥），"
                                    "不能直接跑；原因见台账里的逐条说明",
                                    supported="no")})
    cls = base.REGISTRY.get(name)
    if cls is None:
        # 停用的源仍在磁盘上，只是没注册（见 `store.set_enabled`）——
        # 这两种「不可用」的原因不同，措辞也要不同。
        why = ("书源已停用：在书源管理页重新启用后再验证"
               if pathlib.Path(config.SOURCES_DIR, f"{name}.json").is_file() else "未知书源（没有注册也没有规则文件）")
        return record(name, {**_out(name, UNSUPPORTED, 0, t0, why,
                                    supported=row.get("supported", "yes"))})
    q = str(query or "").strip() or DEFAULT_QUERY
    try:
        # ⚠️ `test_source` 自身**没有**单源超时（它是给「试搜」用的），这里必须自己包：
        # 一条卡住的源会让「全部验证」停在原地，用户看到的是界面一直转圈。
        items = await asyncio.wait_for(manager.test_source(cls, q), SEARCH_TIMEOUT)
    except asyncio.TimeoutError:
        res = _out(name, ERROR, 0, t0, f"探测超时（单源超过 {SEARCH_TIMEOUT:.0f} 秒）",
                   supported=row.get("supported", "yes"))
    except Exception as e:                                   # noqa: BLE001 —— 原文照回供排查
        res = _out(name, ERROR, 0, t0, str(e) or e.__class__.__name__,
                   supported=row.get("supported", "yes"))
    else:
        n = len(items or [])
        res = _out(name, OK if n else ZERO, n, t0,
                   "" if n else "请求成功但一条都没搜到：规则或站点结构可能变了",
                   supported=row.get("supported", "yes"))
    return record(name, res)


async def probe_many(manager, names, *, query: str = DEFAULT_QUERY,
                     interval: float = DEFAULT_INTERVAL, on_each=None) -> dict:
    """**串行**逐条探测，两条之间停 `interval` 秒（默认 1.5）。

    串行 + 间隔是刻意选的：一次「全部验证」可能跑几分钟，但比起被站点风控封掉、
    或把人家打挂，慢一点是对的（第 86 期取舍）。逐条回结果，界面能看到进度。

    ⚠️ 间隔**只在两条之间**睡：最后一条后面不睡，否则每次全验都白等一个间隔。
    """
    out: list = []
    names = [str(n) for n in (names or [])]
    for i, name in enumerate(names):
        res = await probe(manager, name, query=query)
        out.append(res)
        if callable(on_each):
            on_each(res)
        if interval and i < len(names) - 1:
            await asyncio.sleep(interval)
    counts: dict = {}
    for r in out:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return {"items": out, "counts": counts, "queried": len(out)}


async def probe_toc(manager, source_id: str, *, query: str = DEFAULT_QUERY) -> dict:
    """探测一条**目录来源**：只读目录页，**绝不落库**（不写 `store_toc` / `toc_map`）。"""
    t0 = time.perf_counter()
    ent = toc_sources.by_id(source_id)
    if not ent:
        return _out(str(source_id), UNSUPPORTED, 0, t0, "未知来源")
    if ent.get("status") == toc_sources.UNSUPPORTED or not ent.get("rule"):
        # 只登记没写规则的来源：**如实说不支持**，不去请求
        return _out(str(source_id), UNSUPPORTED, 0, t0, toc_sources.state_note(ent),
                    supported="no")
    q = str(query or "").strip() or DEFAULT_QUERY
    try:
        res = await asyncio.wait_for(
            toc_sources.fetch_toc(manager, source_id, book={"title": q}, query=q),
            SEARCH_TIMEOUT)
    except asyncio.TimeoutError:
        return _out(str(source_id), ERROR, 0, t0, f"探测超时（单源超过 {SEARCH_TIMEOUT:.0f} 秒）")
    except Exception as e:                                   # noqa: BLE001
        return _out(str(source_id), ERROR, 0, t0, str(e) or e.__class__.__name__)
    n = len(res.get("entries") or [])
    note = str(res.get("note") or "")
    return _out(str(source_id), OK if n else ZERO, n, t0,
                "" if n else (note or "请求成功但没取到目录：规则或站点结构可能变了"))
