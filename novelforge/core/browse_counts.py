"""侧栏「浏览」组的三计数（第 34 期，对齐上游 ``browse-counts.service.ts``）。

三条口径，每条都对应一个具体的坑：

1. **与目标页完全同源** —— 作者 / 系列数由 ``library.books()`` 聚合（与 ``authors_list`` /
   ``series_list`` 同一份数据），批注数取 ``db.annotation_counts()``（**只算活跃批注**，
   与「批注」页同一口径）。数字与点进去看到的列表条数必须一致：
   对不上就是在说假话，而这类「侧栏显示 3、页面列出 12」的偏差极难被发现。
2. **按库可选收窄**（``library_id`` 给了就只算该库）：
   · 侧栏**不传** —— 「作者 / 系列 / 批注」三页目前都是**跨库**的，计数也得跨库才对得上；
   · 浏览页传当前库 —— 那一页本身按库取数，数字自然同源。
3. **60 秒节流**（上游同款 TTL）：计数要过一遍书目，而侧栏每次渲染都会读它；
   不缓存等于每次进页面都重扫。TTL 内直接回缓存值，并在响应里如实给 ``cached`` ——
   界面若想说明「这是缓存的数」，不必再猜。

计数只读，不改任何数据；缓存键就是 ``library_id``，所以切库立刻拿到该库自己的数。
"""
import threading
import time

from . import db, library

#: 缓存有效期（秒）。照抄上游 browse-counts 的 60 s —— 侧栏计数是「粗略徽标」，
#: 早一分钟晚一分钟更新没有意义，而每次渲染重扫书目是有意义的开销。
CACHE_TTL = 60.0

_lock = threading.Lock()
_cache: dict = {}       # {library_id: (computed_at, payload)}


def invalidate(library_id: str = "") -> None:
    """丢掉缓存（``library_id`` 空串 = 全部丢掉）。

    给「刚改完文件就要看到新数字」的调用方用（如扫描完成后的前端刷新）。
    TTL 到期本身也会自然失效，所以不调也不会错，只是多等一会儿。
    """
    with _lock:
        if not library_id:
            _cache.clear()
        else:
            _cache.pop(str(library_id), None)


def _compute(lid: str) -> dict:
    bs = library.books(lid or None)
    authors = {(b.get("author") or "").strip() for b in bs}
    series = {(b.get("series") or "").strip() for b in bs}
    counts = db.annotation_counts()
    if lid:
        # 批注表没有库维度 ⇒ 只能按「这本书属于哪个库」过滤（与 core/stats.py 同一范式）
        ids = {b["id"] for b in bs}
        annotations = sum(n for bid, n in counts.items() if bid in ids)
    else:
        annotations = sum(counts.values())
    return {
        "library_id": lid,
        "authors": len(authors - {""}),
        "series": len(series - {""}),
        "annotations": annotations,
        "books": len(bs),
        "computed_at": time.time(),
    }


def counts(library_id: str = "") -> dict:
    """三计数 + ``books``（总数，便于界面说明口径）。``library_id`` 空串 = 全部书库。"""
    lid = str(library_id or "")
    now = time.time()
    with _lock:
        hit = _cache.get(lid)
        if hit and now - hit[0] < CACHE_TTL:
            return {**hit[1], "cached": True}
    data = _compute(lid)
    with _lock:
        _cache[lid] = (now, data)
    return {**data, "cached": False}
