"""M4B / M4A 的内嵌章节（第 171 期）—— 「章节从哪来」的唯一判据源。

只认 MP4 容器里**标准**的章节信息，读不到就返回空列表（不猜、不按文件大小切）：
  · Nero 的 `moov/udta/chpl`（M4B 最常见）；
  · 读不到 `chpl` 时**不**退回 QuickTime 章节轨（`tref/chap` + 文本轨）—— 它要拼
    两条轨的时间轴，坑远多于收益；需要时再单独立项。

性能：`moov` 通常只有几 MB，但整个 M4B 可能有几个 GB ⇒ **按 box 头 seek**，只把
`moov` 读进内存（上限 `MAX_MOOV_BYTES`），绝不整文件读。

时间单位：`chpl` 里的起始时间是 **100 纳秒**（1/10000 毫秒），这里统一换算成毫秒。
"""
from __future__ import annotations

import pathlib
import threading

#: 只把 `moov` 读进内存的上限（正常几百 KB；超过说明文件异常，放弃解析）。
MAX_MOOV_BYTES = 64 * 1024 * 1024

#: 支持的容器扩展名（章节只对「单文件有声书」有意义）。
CHAPTER_EXTS = (".m4b", ".m4a")

_cache: dict = {}
_cache_lock = threading.Lock()
_CACHE_MAX = 64


def _iter_boxes(fp, start: int, end: int):
    """遍历 `[start, end)` 的 MP4 box：`(type, payload_start, payload_end)`。

    坏 box（size 为 0/1 等边界）一律停下 —— 结构已经不可信，继续读只会得到垃圾。
    """
    off = start
    while off + 8 <= end:
        fp.seek(off)
        head = fp.read(16)
        if len(head) < 8:
            return
        size = int.from_bytes(head[0:4], "big")
        typ = head[4:8].decode("latin-1", "replace")
        hdr = 8
        if size == 1:
            if len(head) < 16:
                return
            size = int.from_bytes(head[8:16], "big")
            hdr = 16
        elif size == 0:
            size = end - off                       # 一直到容器末尾
        if size < hdr or off + size > end:
            return
        yield typ, off + hdr, off + size
        off += size


def _find_box(fp, start: int, end: int, path: tuple):
    """按路径找嵌套 box（只看第一层里同名的第一个）。"""
    for typ, s, e in _iter_boxes(fp, start, end):
        if typ != path[0]:
            continue
        if len(path) == 1:
            return s, e
        return _find_box(fp, s, e, path[1:])
    return None


def _parse_chpl(payload: bytes) -> list:
    """`chpl` → `[{title, start_ms}]`。坏数据尽量读出已读到的部分，绝不抛。"""
    if len(payload) < 5:
        return []
    version = payload[0]
    off = 4
    if version == 1:
        off += 4                                   # 保留 4 字节（Nero 的版本 1 才有）
    if off >= len(payload):
        return []
    count = payload[off]
    off += 1
    out = []
    for _ in range(count):
        if off + 9 > len(payload):
            break
        start_100ns = int.from_bytes(payload[off:off + 8], "big")
        off += 8
        ln = payload[off]
        off += 1
        if off + ln > len(payload):
            break
        title = payload[off:off + ln].decode("utf-8", "replace").strip()
        off += ln
        out.append({
            "title": title or f"第 {len(out) + 1} 章",
            "start_ms": start_100ns // 10000,
        })
    return out


def _read(path: pathlib.Path) -> list:
    try:
        total = path.stat().st_size
    except OSError:
        return []
    try:
        with path.open("rb") as fp:
            moov = _find_box(fp, 0, total, ("moov",))
            if not moov:
                return []
            s, e = moov
            if e - s > MAX_MOOV_BYTES:
                return []
            chpl = _find_box(fp, s, e, ("udta", "chpl"))
            if not chpl:
                return []
            cs, ce = chpl
            fp.seek(cs)
            payload = fp.read(ce - cs)
    except OSError:
        return []
    return _parse_chpl(payload)


def chapters(path) -> list:
    """单文件有声书的章节清单（毫秒起点）；目录 / 非 M4B / 无章节都返回 `[]`。

    结果按 `(路径, mtime_ns, size)` 缓存 —— 同一本书反复打开播放器不必重复解析。
    """
    p = pathlib.Path(str(path))
    if p.suffix.lower() not in CHAPTER_EXTS or not p.is_file():
        return []
    try:
        st = p.stat()
    except OSError:
        return []
    key = (str(p), st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(key)
    if hit is not None:
        return hit
    out = _read(p)
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            _cache.clear()                         # 简单封顶：这是纯派生结果，清了再算
        _cache[key] = out
    return out
