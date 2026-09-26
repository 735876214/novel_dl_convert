"""Redis 缓存层（第 62 期）：**可以缺席的一层**。

先说清楚它解决什么、不解决什么
------------------------------
本项目是**单进程 uvicorn + 单用户**，Redis 的跨进程 / 跨实例优势在这里用不上 ——
它**不是**「书架 42 秒」的解药，解药是书目索引落库（见 ``core/catalog.py``）。

本层真正明显的一处是**章节 HTML**：一次章节切换原本要开 zip、读条目、解压、
解码、正则改写正文里的资源 URL，而书库挂在 NAS 上时每一步都在付网络往返；
缓存命中后这些全免。另外两处（书目列表、封面）**收益有限**，各自调用点上
写了实测口径，不夸大。

缺席时怎么办（两条，都不许把异常抛给调用方）
-------------------------------------------
1. ``NOVELFORGE_REDIS_URL`` 不设 → 整个模块是**空操作**：``enabled()`` 为假，
   每个读都是「未命中」，行为与第 61 期逐字节一致（默认如此）；
2. 设了但连不上 / 中途挂掉 → **静默降级为「每次都未命中」**，业务照常直读
   PG/SQLite。缓存挂掉不该让服务挂掉。

⚠️ 降级不只是「吞掉异常」——还要**熔断**：Redis 挂掉时如果每个请求都去连一次、
每次都等满超时，那这层缓存就从「省时间」变成「每个请求多等 0.5 秒」。所以连续
失败 :data:`_FAILS_TO_TRIP` 次就进入 :data:`_COOLDOWN` 秒的静默期，期间一次网络
都不发。冷却结束自动重试一次（Redis 回来了就自己恢复，不需要重启服务）。

键空间约定
----------
所有键以 ``nf:`` 开头（共享 Redis 里便于识别与清理）。键里**不出现**绝对路径：
书库根在 NAS 上会变，路径进键等于换机器就全量失效，而 :func:`fingerprint` 用的
(大小, mtime) 已经足够区分「同一个文件变没变」。
"""
from __future__ import annotations

import json
import os
import threading
import time

#: 连接串。**不设 = 不启用**（默认，离线开发与老部署行为不变）。
_ENV_URL = "NOVELFORGE_REDIS_URL"

#: 键前缀。
_PREFIX = "nf:"

#: 「书目列表」这类派生数据的兜底 TTL（秒）。正常靠写操作显式 DEL，
#: TTL 只兜「有没有哪条写路径漏了 DEL」——所以短，宁可多查几次库。
TTL_LIST = 120

#: 章节 HTML 的 TTL（秒）。键里带了源文件指纹，文件一变键就变，
#: 所以这里可以长：它只负责把没人再读的旧键收走。
TTL_CHAPTER = 86400

#: 封面字节的 TTL（秒）。PG 仍是真相源（``meta_cover``），这里只是读缓存。
TTL_COVER = 86400

#: 连不上 / 操作失败连续多少次就熔断。
_FAILS_TO_TRIP = 3
#: 熔断后的静默期（秒）。到点自动放行一次去探活。
_COOLDOWN = 30.0
#: 单次操作的 socket 超时（秒）。**必须小**：缓存是可选路径，不能在它身上等。
_SOCKET_TIMEOUT = 0.5

_client = None
_guard = threading.Lock()

#: 连续失败计数 / 静默期截止时刻。
_fails = 0
_dead_until = 0.0

#: 命中统计（``stats()`` 用；不落盘、不暴露给未认证的接口）。
_stat = {"hit": 0, "miss": 0, "set": 0, "error": 0, "trip": 0, "del": 0}
_stat_lock = threading.Lock()


def url() -> str:
    """配置的连接串（空 = 不启用）。"""
    return (os.getenv(_ENV_URL) or "").strip()


def enabled() -> bool:
    """这层缓存现在**理论上**可用吗（配了连接串）。

    注意它与「此刻是否熔断」是两件事：熔断期间 :func:`enabled` 仍为真，
    只是每次读都直接判未命中 —— 调用点不需要关心这个区别。
    """
    return bool(url())


def reset() -> None:
    """丢掉缓存的客户端与熔断状态（测试改完环境变量后调用）。"""
    global _client, _fails, _dead_until
    with _guard:
        c, _client = _client, None
        _fails = 0
        _dead_until = 0.0
    if c is not None:
        try:
            c.close()
        except Exception:                          # noqa: BLE001 —— 关不掉也不该抛
            pass


def _bump(field: str, n: int = 1) -> None:
    with _stat_lock:
        _stat[field] = _stat.get(field, 0) + n


def _conn():
    """取（或建）客户端；不可用返回 None。**不抛异常。**"""
    global _client, _fails, _dead_until
    if not enabled():
        return None
    if time.time() < _dead_until:
        return None                                # 熔断中：一次网络都不发
    with _guard:
        if _client is not None:
            return _client
        try:
            import redis
        except ImportError:                        # pragma: no cover - 环境问题
            _bump("error")
            _dead_until = time.time() + _COOLDOWN
            return None
        try:
            c = redis.from_url(
                url(),
                socket_timeout=_SOCKET_TIMEOUT,
                socket_connect_timeout=_SOCKET_TIMEOUT,
                decode_responses=False,            # 字节进字节出：封面是二进制
                health_check_interval=30,
            )
            c.ping()                               # 真连一次，别把错误留到第一次读
        except Exception:                          # noqa: BLE001 —— 连不上就降级
            _bump("error")
            _trip()
            return None
        _client = c
        _fails = 0
        return c


def _trip() -> None:
    """记一次失败；连续够了就进静默期。"""
    global _fails, _dead_until
    _fails += 1
    if _fails >= _FAILS_TO_TRIP:
        _fails = 0
        _dead_until = time.time() + _COOLDOWN
        _bump("trip")


def _on_error() -> None:
    """一次操作失败：丢掉客户端（下次重建），并计数。"""
    global _client
    with _guard:
        c, _client = _client, None
    if c is not None:
        try:
            c.close()
        except Exception:                          # noqa: BLE001
            pass
    _bump("error")
    _trip()


def _get(key: str):
    """→ 字节 或 None。失败一律当未命中。"""
    c = _conn()
    if c is None:
        _bump("miss")
        return None
    try:
        out = c.get(key)
    except Exception:                              # noqa: BLE001
        _on_error()
        _bump("miss")
        return None
    if out is None:
        _bump("miss")
    else:
        _bump("hit")
    return out


def _set(key: str, data, ttl: int) -> None:
    c = _conn()
    if c is None:
        return
    try:
        c.set(key, data, ex=ttl)
        _bump("set")
    except Exception:                              # noqa: BLE001
        _on_error()


def _del(*keys) -> None:
    """删键。**失败不重试也不抛** —— 删不掉最坏的后果是「多读一会儿旧值」，
    而它自己会在 TTL 到点时消失；为此把写操作搞失败才是真的糟。"""
    keys = [k for k in keys if k]
    if not keys:
        return
    c = _conn()
    if c is None:
        return
    try:
        c.delete(*keys)
        _bump("del", len(keys))
    except Exception:                              # noqa: BLE001
        _on_error()


# ---------------- 键 ----------------

def book_list_key(library_id) -> str:
    """书目列表的键 —— **按库**，没有「全库合并」那种键。

    ``library.books()`` 本来就是「逐库取再拼」（``catalog.books``），所以库级键
    既够用、又能被库级失效（``catalog.invalidate(lid)``）精确命中 —— 而一个合并键
    会让任何单库的写操作都得清它一次，等于没有缓存。

    空 id → 返回 ``""``，而 :func:`drop` 会跳过空键（调用方不必先判空）。
    """
    lid = str(library_id or "")
    return f"{_PREFIX}book:list:{lid}" if lid else ""


def chapter_key(bid: str, index: int, fp: str, kind: str = "epub") -> str:
    """章节 HTML 的键：``(书, 章节序号, 源指纹)``。

    ``kind`` 区分 TXT 的两条路线（派生 EPUB / 原生分章）—— 它们的 index 语义
    各自内聚、**不许跨路线命中**（第 55 期定下的规矩，见 server 的章节接口）。
    """
    return f"{_PREFIX}chapter:{kind}:{bid}:{index}:{fp}"


def cover_key(bid: str, fp: str) -> str:
    """封面字节的键：``(书, 源文件指纹)``。

    ⚠️ 键里带指纹而不是只有 book_id，是**故意的**：封面没有「按书失效」那条路
    （写封面的在线抓取只调 ``library.invalidate()``，那是不带书号的），指纹是唯一
    能自证「换了没换」的东西。因此这条缓存只覆盖「从文件里读封面」的分支；
    服务端封面（``meta_cover``）那一支不进这里 —— 见 ``server._cover_cached``。
    """
    return f"{_PREFIX}cover:{bid}:{fp}"


def fingerprint(path) -> str:
    """文件的 ``(大小, mtime)`` 指纹；取不到就返回 ``""``（= 不缓存）。

    ``st_mtime_ns`` 而不是 ``st_mtime``：浮点秒在有些文件系统上精度只有 1 秒，
    同一秒内改两次文件就会拿到同一个指纹（"改了但没变"）。
    """
    try:
        st = os.stat(path)
    except OSError:
        return ""
    return f"{st.st_size}:{st.st_mtime_ns}"


# ---------------- 读写 ----------------

def get_json(key: str):
    """→ 反序列化后的对象，或 None（未命中 / 解析失败）。"""
    raw = _get(key)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:                              # noqa: BLE001 —— 脏数据当未命中
        _bump("error")
        return None


def set_json(key: str, obj, ttl: int) -> None:
    try:
        data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except Exception:                              # noqa: BLE001 —— 序列化不了就不缓存
        return
    _set(key, data, ttl)


def get_bytes(key: str):
    return _get(key)


def set_bytes(key: str, data: bytes, ttl: int) -> None:
    _set(key, data, ttl)


def drop(*keys) -> None:
    """显式失效。调用点集中在 ``catalog.invalidate`` / ``forget``（书目列表）
    与各写路径（封面 / 章节由指纹自失效，不需要手动删）。"""
    _del(*keys)


def stats() -> dict:
    """命中统计（服务端自检 / 部署核对用）。``hit_rate`` 是「读命中 ÷ 总读」。"""
    with _stat_lock:
        s = dict(_stat)
    reads = s["hit"] + s["miss"]
    s["reads"] = reads
    s["hit_rate"] = round(s["hit"] / reads, 4) if reads else None
    s["enabled"] = enabled()
    s["tripped"] = time.time() < _dead_until
    s["client"] = _client is not None
    return s
