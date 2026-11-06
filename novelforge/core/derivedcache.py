"""派生缓存的**共用骨架**（第 265 期收敛）。

## 为什么有这个模块

`.fb2` / `.mobi|.azw|.azw3` / `.txt` 三种格式各有一个派生缓存模块（`fb2cache` /
`mobicache` / `txtcache`），它们**不是三套逻辑**，而是同一套逻辑配三个解析器。此前：

- `_swap_in` 在 `fb2cache` 与 `mobicache` 里**逐字相同**（23/24 行）、`txtcache` 那里是一个
  略弱的变体（不先清残留、失败回滚少一个判据）；
- `read_target` 在 `fb2cache` 与 `mobicache` 里**逐字相同**（34/35 行）——
  而它承载的是一条**硬约束**：「这本书的正文其实在哪个文件里，只允许有一处答案」。

换句话说，AGENTS 第 1 节的「源不可变：临时文件 + `Path.replace`」这条**硬约束**，
在这两个文件里各躺了一份。改一处漏一处不会报错 —— 只会在某次崩溃后留下半个缓存目录。

## 这里放什么

- :func:`swap_in` —— 目录级原子换入（自包含，无参数化）；
- :func:`read_target` —— 缓存模块提供七个钩子
  （扩展名 / 源路径 / 指纹 / 缓存目录 / 查缓存 / 构建 / 构建锁），**流程只有一份**。

⚠️ 刻意**不**把各模块的 `_build`（真解析）搬进来：那是格式知识，各不相同。
"""
from __future__ import annotations

import os
import pathlib
import shutil
import time


def swap_in(stage: pathlib.Path, final: pathlib.Path) -> None:
    """把 stage 换成 final —— **原子换入**：旧目录先挪走、再 replace、最后删旧的。

    直接往 final 里写是不行的：中途失败会留下半个目录，而 `state.json` 一旦写成 ok，
    读者拿到的就是缺文件的正文。一律先在同卷临时目录里建完再换入
    （源不可变 + 临时文件 + `Path.replace` 的既有纪律）。

    换入失败时把旧目录**放回去**：否则这本书的缓存整个消失（下次会重建，但没必要）。
    """
    old = None
    if final.exists():
        old = final.with_name(f"{final.name}.old-{os.getpid()}-{int(time.time() * 1000)}")
        shutil.rmtree(old, ignore_errors=True)
        final.replace(old)
    try:
        stage.replace(final)
    except OSError:
        if old is not None and old.exists() and not final.exists():
            try:
                old.replace(final)
            except OSError:                            # noqa: BLE001
                pass
        raise
    if old is not None:
        shutil.rmtree(old, ignore_errors=True)


def read_target(mod, book: dict, *, path=None, root=None):
    """这本书的**读目标**：``(派生件路径, kind)`` 或 ``(None, "")``。

    ``mod`` 是**缓存模块本身**（`fb2cache` / `mobicache`），它必须提供这六个钩子
    （都是模块级、同名的私有函数，**流程只在本函数里有一份**）：

    | 钩子 | 语义 |
    |---|---|
    | `mod.EXTS` | 归它管的源文件扩展名集合（小写，含点） |
    | `mod._src_path(book, path, root)` | 这本书的源文件在哪 |
    | `mod._fingerprint(p)` | 源文件指纹（size+mtime；变了就重建） |
    | `mod._cache_dir(bid)` | 该书的派生缓存目录 |
    | `mod._lookup(cdir, fp, src)` | 查缓存 → `(verdict, target, kind)` |
    | `mod._build(book, src, bid, cdir, fp)` | 真解析（**格式知识，各写各的**） |
    | `mod._BUILD_LOCK` | 构建锁（构建期间只许一个线程写） |

    ⚠️ 这里刻意用**模块对象 + 运行时属性查找**，而不是在导入期把函数对象抓进一个
    dataclass —— 抓进对象后 `monkeypatch.setattr(fb2cache, "_build", …)` 就不生效了
    （测试正是靠打桩 `_build` 数「解析了几次」的）。

    非本格式 / 文件不在 / 无 book_id ⇒ ``(None, "")``（调用方各自回落既有行为）。
    查缓存 → 命中即用 → 未命中在**构建锁**下**双检**（等锁期间别人可能已经建好了）。
    """
    p = mod._src_path(book, path, root)
    if p.suffix.lower() not in mod.EXTS or not p.is_file():
        return None, ""
    bid = str(book.get("id") or "")
    if not bid:
        return None, ""
    try:
        fp = mod._fingerprint(p)
    except OSError:
        return None, ""
    cdir = mod._cache_dir(bid)

    verdict, target, kind = mod._lookup(cdir, fp, p)
    if verdict == "hit":
        return target, kind
    if verdict == "locked":
        return None, ""

    with mod._BUILD_LOCK:
        # 双检：等锁期间别人可能已经解好了（解包是秒级操作，这里省掉重复的一遍）
        verdict, target, kind = mod._lookup(cdir, fp, p)
        if verdict == "hit":
            return target, kind
        if verdict == "locked":
            return None, ""
        return mod._build(book, p, bid, cdir, fp)
