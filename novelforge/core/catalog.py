"""书目索引（第 62 期）：把「每次请求现扫磁盘」换成「读一张表」。

问题（线上实测，http://192.168.0.95:8992，2026-09-27）
------------------------------------------------------
    GET /api/books         42.4s      GET /api/libraries  41.9s（响应体只有 1.8 KB）
    GET /api/books/export  43.1s      GET /api/stats      28.6s
    GET /api/authors       22.4s

3 个书库共 266 本，42 秒 ÷ 266 = **每本 158 毫秒**。本地磁盘开一次 zip 读 OPF 只要
几毫秒 —— 这个量级只有一个解释：书库挂在 NAS 网络存储上，``probe_epub`` 里几十次
syscall 每次都在付网络往返。而 254 KB 的 JSON 走局域网只要 0.1 秒。
**瓶颈 100% 在后端扫盘，不在传输、不在渲染。**

根因是书目**从不入库**：``library.py`` 里没有「图书库实体」，书目全靠实时扫盘聚合。
更糟的是 ``_books_of`` **先算目录指纹再查缓存** —— 缓存命中也要付一次全目录 stat，
而那个指纹还要对每个条目跑一遍递归 rglob；未命中就 ``_scan_once``，且那一步在锁外、
没有单飞，并发请求各自重扫。

本模块做的事
------------
一张 ``book_index`` 表 + 一次**增量**刷新：

- **请求路径不再扫盘**：``books_of()`` 是一条 SELECT（外加一次内存里的脏标记检查），
  ``by_id()`` 是一条带索引的 SELECT，``counts()`` 是一条 GROUP BY；
- **扫盘交给后台**：监听线程按每库的 ``scan_interval`` / ``scan_cron`` 调
  :func:`refresh_library`；写操作后的 ``library.invalidate()`` 只**标脏**，
  下一个请求发现脏了就同步刷一次（此时是增量的：一次目录遍历 + 每文件一次 stat，
  **不开 zip**）；
- **增量判据是 ``(size, mtime)``**：与索引现值相同就整段跳过，不调 ``probe_epub``。
  这是 42 秒与 1 秒的全部差别 —— 266 次 stat 与 266 次「开 zip + 读 container.xml +
  读 OPF + 找封面 + 遍历 manifest」是两件量级完全不同的事。

线程纪律（**重要**）
--------------------
本模块**不新起任何线程** —— 刷新只从两个地方发生：请求线程（同步，见
:func:`books_of`）与既有的监听线程（``watcher._loop``）。仓库有一条硬纪律：
「新增旁路线程必须进 ``tests/conftest.py::_quiesce_background`` 的收尾清单」
（第 39 期实测过残留线程攥着已关闭的连接去查下一个用例的库，全量跑后半程 segfault）。
不新起线程就没有这条尾巴。单飞靠**每库一把锁**，不靠后台队列。

入库的是「文件派生」的那部分
----------------------------
``issues`` 不入库（它要在读取时结合服务端封面重算）、``c1``/``c2``/``path`` /
``library_id`` / ``library_type`` / ``name`` 也不入库（由库实体与 id 现拼）。
判据见 ``library._probe_entry`` 的文档 —— 那条「探测结果只依赖文件自身」的约束
是增量刷新的立足点，掺进任何库级 / 服务端状态都会让它失效。
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
import time

from . import cache, db

#: pathlib 在 Windows 上比较路径时会把整串小写（``PurePath._str_normcase``），
#: 而 ``_iter_book_entries`` 用的是 ``sorted(d.iterdir())`` —— 排序口径必须跟着平台走，
#: 否则「Z.epub 与 a.epub 谁在前」在两条链路上给出不同答案。
_WIN = os.name == "nt"

#: 索引表名。**故意不叫 books** —— 它与 ``library.books()`` 的返回值不是一回事：
#: 这里缺 ``issues`` / ``c1`` / ``path`` 等读取时才拼的字段，也没有服务端元数据覆盖层。
TABLE = "book_index"

#: 列清单（DDL 与 upsert 共用一份，避免「加了列忘了写 upsert」）。
_COLS = (
    "library_id", "root", "rel", "book_id",
    "size", "mtime", "format", "title", "author", "series", "series_index",
    "has_cover", "cover", "pages", "pages_source", "tracks",
    "year", "publisher", "isbn", "language", "description",
    "tags", "narrators", "unparsable", "fixed_layout", "is_dir", "probed_at",
)

#: 主键 **必须是 (library_id, root, rel)**，不能是 (library_id, rel)：
#: 一个库可以持有多个来源文件夹（第 41 期 ``source_dirs``），两个根下出现同名文件
#: 是**合法且已经存在**的情形 —— 此时 ``by_id`` 要抛 ``BookIdConflict``。
#: 用 (library_id, rel) 当主键会把这两本**静默合并成一本**，冲突从此消失，
#: 而进度 / 批注会写到错的书上（那正是 ``BookIdConflict`` 要防的事）。
_SCHEMA = (
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
        library_id   TEXT NOT NULL,
        root         TEXT NOT NULL,
        rel          TEXT NOT NULL,
        book_id      TEXT NOT NULL,
        size         BIGINT NOT NULL DEFAULT 0,
        mtime        DOUBLE PRECISION NOT NULL DEFAULT 0,
        format       TEXT NOT NULL DEFAULT '',
        title        TEXT NOT NULL DEFAULT '',
        author       TEXT NOT NULL DEFAULT '',
        series       TEXT NOT NULL DEFAULT '',
        series_index TEXT NOT NULL DEFAULT '',
        has_cover    INTEGER NOT NULL DEFAULT 0,
        cover        TEXT NOT NULL DEFAULT '',
        pages        INTEGER NOT NULL DEFAULT 0,
        pages_source TEXT NOT NULL DEFAULT '',
        tracks       INTEGER NOT NULL DEFAULT 0,
        year         TEXT NOT NULL DEFAULT '',
        publisher    TEXT NOT NULL DEFAULT '',
        isbn         TEXT NOT NULL DEFAULT '',
        language     TEXT NOT NULL DEFAULT '',
        description  TEXT NOT NULL DEFAULT '',
        tags         TEXT NOT NULL DEFAULT '[]',
        narrators    TEXT NOT NULL DEFAULT '[]',
        unparsable   INTEGER NOT NULL DEFAULT 0,
        fixed_layout INTEGER NOT NULL DEFAULT 0,
        is_dir       INTEGER NOT NULL DEFAULT 0,
        probed_at    DOUBLE PRECISION NOT NULL DEFAULT 0,
        PRIMARY KEY (library_id, root, rel)
    )""",
    # by_id 是热路径里最热的一条（server.py 35 处调用，书架一屏 30 本 = 30 次）
    f"CREATE INDEX IF NOT EXISTS idx_bookindex_bid ON {TABLE}(book_id)",
)

_ready_done = False
_ready_lock = threading.Lock()

#: 每库一把刷新锁 —— **单飞**。同一库的并发刷新在此排队，第一个扫完后面的直接返回，
#: 不会出现「N 个请求各自全量扫一遍」（改造前正是如此）。
_locks: dict = {}
_locks_guard = threading.Lock()

#: 脏标记：库 id → 被标脏的时刻。``_dirty_all_seq`` 是「全库标脏」的**序号**。
#: 用**单调序号**而不是布尔，是因为全局失效必须对**每个**库生效 ——
#: 用一个全局布尔的话，第一个来刷新的库会把它清掉，后面的库全都看不到这次失效。
_dirty: dict = {}
#: 全局失效序号。**故意不用 `time.time()`**（第 63 期修正，见 `_is_stale`）。
_dirty_all_seq: int = 0
#: 库 id → 上次成功刷新时看到的 ``_dirty_all_seq``。比它大就是「之后又被全局标脏过」。
_refreshed_seq: dict = {}
_state_lock = threading.Lock()

#: 本进程内「已经至少完整刷过一次」的库。**冷启动的唯一判据** ——
#: 用它而不是每次查一次 ``COUNT(*)``，否则「读索引」这条热路径上又要多一条查询，
#: 那就等于把刚省下来的开销又还回去一截。
_ready: set = set()

#: 本进程往 Redis 写过「书目列表」键的库 id —— 「全库失效」时按它精确 DEL。
#: 用这个集合而不是 ``KEYS nf:book:list:*``：本层是挂在**共享 Redis** 上的，
#: 按图案扫全库键空间是给别人添堵的动作，而库的集合我们本来就知道。
#: 它是「可能写过」而不是「此刻确实有」—— 已被删掉的键再 DEL 一次是无害的空动作。
_cached_libs: set = set()


def _exec(sql: str, params=()):
    """走 ``db`` 的连接代理 —— 与全仓共用同一条连接、同一把锁。

    ⚠️ 用 ``db._connect()`` 这个下划线名是**故意的**：``auth.py`` 与全部测试
    都这么用，它是事实上的内部接口。绕开 ``db`` 自己开一条连接是不行的 ——
    那会多出一把锁、多一个事务域，``db.close()``（测试的用例级隔离靠它）
    也管不到它。

    ⚠️ SQL 一律**原样**交给代理，本模块不做任何方言处理（第 62 期修正）：
    适配发生在代理那一层（`db._Conn` / `pg.PgConn`），这里再 `adapt` 一次会
    变成**两遍**——第一遍把 `?` 换成 `%s`、把 `%` 转义成 `%%`，第二遍再把
    `%%` 转义成 `%%%%`，SQL 当场跑不通。SQLite 后端下 adapt 是恒等函数，
    所以这个错只在 PG 上现形。
    """
    return db._connect().execute(sql, params)


def _commit() -> None:
    db._connect().commit()


def ensure_schema() -> None:
    """建表（幂等）。``db.init()`` 之后调用；进程内只跑一次。"""
    global _ready_done
    with _ready_lock:
        if _ready_done:
            return
        for stmt in _SCHEMA:
            _exec(stmt)
        _commit()
        _ready_done = True


def reset_state() -> None:
    """清掉进程内状态（脏标记 / 就绪集 / 建表标记）。**供测试**切库或换 DATA_DIR 后调用。"""
    global _ready_done, _dirty_all_seq
    with _ready_lock:
        _ready_done = False
    with _state_lock:
        _dirty.clear()
        _refreshed_seq.clear()
        _ready.clear()
        _dirty_all_seq = 0
    # Redis 里的列表键也得丢：本函数是「换了一套库」的信号（`db.close()` 调它），
    # 而**库 id 会被重用**（测试里每个用例都叫 'novels'）—— 留着旧值，下一个用例
    # 会读到上一个用例的书。生产上这条不走，但代价是一次 DEL，不值得为它开分支。
    _drop_list()


# ---------------- 脏标记 ----------------

def _drop_list(library_id=None) -> None:
    """丢掉书目列表的缓存键。

    ``library_id`` 给定时只丢该库；不给则丢本进程写过键的**每个库**
    （``_cached_libs``）—— 见该集合上关于「不按图案扫键空间」的说明。

    ⚠️ 只丢「列表」这一种键：章节与封面**不在这里失效** —— 它们的键里带着源文件指纹
    （章节用被读的那个文件、封面用归档文件），文件一变键就变，不需要谁去清。
    列表没有这样的抓手（它掺了服务端元数据覆盖层），所以必须显式失效。
    """
    if library_id:
        cache.drop(cache.book_list_key(library_id))
        return
    with _state_lock:
        lids = sorted(_cached_libs)
    cache.drop(*[cache.book_list_key(l) for l in lids])


def invalidate(library_id=None) -> None:
    """标脏（**不**立刻扫盘）+ 丢 Redis 里的书目列表。

    这是 ``library.invalidate()`` 的实现 —— 全仓 20 多处写操作之后都会调它。
    改造前它是「清空进程内扫描缓存」，所以下一个请求必然冷扫一遍；现在它只是
    一个内存赋值，真正的开销被推迟到**下一次读**（且那时是增量的）。

    第 62 期 C：这是**失效的唯一汇聚点** —— 20 多个写调用点（改名 / 上传封面 /
    元数据编辑 / 刮削落库 / 搬迁 / 监听线程发现新文件 …）全都走这里到 Redis。
    在别处再挂一遍 DEL 是**冗余且危险**的：漏一处就变成「改了元数据但列表还是旧的」。
    """
    global _dirty_all_seq
    with _state_lock:
        if library_id:
            _dirty[str(library_id)] = time.time()
        else:
            _dirty_all_seq += 1
            _dirty.clear()
    _drop_list(library_id)


def _is_stale(lid: str) -> bool:
    """这个库自上次刷新之后又被标脏了吗？

    ⚠️ **这里的比较是两个计数，不是两个时刻**（第 63 期改正，原本是
    ``_dirty_all_at > _refreshed_at.get(lid, 0.0)``）。

    原写法在**同一时刻刻度内**判不出来：「全局标脏」与「刷新完成」两次
    ``time.time()`` 会返回**完全相同的浮点数**，于是 ``>`` 为假、库被判成不脏。
    这不是理论风险 —— Windows + Python 3.12 上实测 ``time.time()`` 的粒度约
    **15.6ms**，连续两次调用 2000 次**全部相同**。而「写文件 → ``invalidate()``
    → 立刻读一次书目」这一串（上传 / 刮削落库 / 批量导入 / 测试夹具）正好落在
    同一个刻度里：第一次读触发的 ``_mark_fresh`` 与紧接着的 ``invalidate()``
    时刻相等 ⇒ 下一次读不再刷新 ⇒ **刚写进去的文件在书目里看不见**，
    不报错、也不为空，只是少一本。

    序号不受时钟分辨率影响：每次全局标脏必然 +1，刷新时把「当时看到的号」记下来，
    两者相等就是「刷新之后没再脏过」。
    """
    with _state_lock:
        if lid in _dirty:
            return True
        return _dirty_all_seq > _refreshed_seq.get(lid, -1)


def _mark_fresh(lid: str) -> None:
    with _state_lock:
        _dirty.pop(lid, None)
        _refreshed_seq[lid] = _dirty_all_seq


def _lib_lock(lid: str) -> threading.Lock:
    with _locks_guard:
        lk = _locks.get(lid)
        if lk is None:
            lk = _locks[lid] = threading.Lock()
        return lk


# ---------------- 刷新 ----------------

# ---------------- 扫描口径版本（第 73 期）----------------
# 增量闸门是**每行的 (size, mtime)**：磁盘上的文件一个字节都没变时，那些旧行
# **永远不会被重探**。于是「扫描口径改了」（本期：序号单元合并 + 书名剥范围备注）
# 对存量索引完全不可见 —— 用户升级后看到的还是 43 本各自独立的书，而且不报错、
# 不重建。第 72 期在派生件那边踩过同一个坑（`pipeline.ENCODING_RULE_VERSION`）。
#
# 落点选 `app_state`（运行态 KV）而不是新表 / 新文件：它是**幂等标记**这一类东西
# 既有的地方（`migrate.GATE_KEY`、`pgmigrate.MARKER` 都在那儿），SQLite 与 PG 两种
# 后端自动都成立，不必新写一份「跑过一次」的持久化。丢了只是每库多扫一次全量，结果不变。
#
# ⚠️ 必须**按库**记（键里带库 id）：记成全局的话，第一个刷新完的库会把标记写成新版本，
# 后面的库再也不全量重探 ⇒ 只有一本书被修好，比不修更难查。按库分键同时也免掉了
# 「读—改—写」丢更新（两个库同时刷新各写各的键）。
_RULE_KEY = "book_index_rule"


def _rule_key(lid: str) -> str:
    return f"{_RULE_KEY}:{lid}"


def _rule_stale(lid: str) -> bool:
    """这个库上次全量重探时的口径版本与当前常量是否不一致（读不到一律当不一致）。"""
    from . import library as _lib        # 延迟导入：library 在模块级 import 本模块
    try:
        return int(db.state_get(_rule_key(lid)) or 0) != int(_lib.SCAN_RULE_VERSION)
    except Exception:
        return True


def _mark_rule(lid: str) -> None:
    """记下「这个库已按当前口径全量重探过」。写失败**不报错**（下次多扫一次而已）。"""
    from . import library as _lib
    try:
        db.state_set(_rule_key(lid), str(int(_lib.SCAN_RULE_VERSION)))
    except Exception:
        pass


def refresh_library(lib: dict, force: bool = False, blocking: bool = True) -> dict:
    """增量刷新一个库的索引。**幂等**，可在任意线程调。

    ``force=True`` 时无视 ``(size, mtime)`` 全部重探（「立即扫描」按钮 / 冷启动）。

    ⚠️ **扫描口径版本不一致时本函数也会按 ``force`` 处理**（见上面那段说明）：
    这是存量索引唯一的自愈通道，跑完只发生一次，之后回落增量。

    ``blocking=False`` 时若该库正有另一次刷新在跑就**直接跳过**（监听线程用这个 ——
    它没必要排在请求后面等，下一轮再来即可）。

    返回 ``{"scanned", "added", "removed", "unchanged", "seconds", "skipped"}``。
    """
    lid = str((lib or {}).get("id") or "")
    t0 = time.time()
    if not lid:
        return {"scanned": 0, "added": 0, "removed": 0, "unchanged": 0,
                "seconds": 0.0, "skipped": False}
    lk = _lib_lock(lid)
    if not lk.acquire(blocking=blocking):
        return {"scanned": 0, "added": 0, "removed": 0, "unchanged": 0,
                "seconds": 0.0, "skipped": True}
    # 判据放在锁内：同一库的并发刷新不该有两个线程各判一次
    if not force and _rule_stale(lid):
        force = True
    try:
        out = _refresh_locked(lib, force)
    finally:
        lk.release()
    # 跑完一整遍全量才记版本 —— 增量那一轮没资格代表「这库已按新口径重探过」
    if force and not out.get("skipped"):
        _mark_rule(lid)
    _mark_fresh(lid)
    with _state_lock:
        _ready.add(lid)
    # 索引**真的变了**才丢 Redis 的列表 —— 这条覆盖了「用户绕过 App 直接往目录里
    # 丢文件」：监听线程的定时刷新会走到这儿，added/removed 一非零，下一次请求
    # 就看不到旧列表了（那种变更**没有** invalidate() 可挂）。
    # unchanged 那种「扫了一遍但什么都没变」是稳态下的绝大多数，绝不能丢 ——
    # 丢了就等于每轮刷新都把列表缓存清一次，缓存等于不存在。
    if out.get("added") or out.get("removed"):
        with _state_lock:
            _cached_libs.discard(lid)      # 下一个写键的人会重新记上
        cache.drop(cache.book_list_key(lid))
    out["seconds"] = round(time.time() - t0, 3)
    return out


def _refresh_locked(lib: dict, force: bool) -> dict:
    from . import library as _lib          # 延迟导入：library 在模块级 import 本模块

    lid = str(lib["id"])
    roots = _lib.roots_of(lib)
    exts = _lib.exts_for_library(lib)
    pats = _lib.parse_excludes(lib.get("exclude"))

    # 现存索引：``(root, rel) -> row``。**只取判据需要的列** —— 把整表读进内存
    # 在万册书下会白占几十 MB，而增量判据只看 size/mtime。
    stored: dict = {}
    for r in _exec(
        f"SELECT root, rel, size, mtime FROM {TABLE} WHERE library_id=?", (lid,)
    ).fetchall():
        stored[(str(r["root"]), str(r["rel"]))] = (int(r["size"] or 0), float(r["mtime"] or 0))

    seen: set = set()
    added = unchanged = 0
    #: 待写行按批提交：一次 266 条 INSERT 放在一个事务里，SQLite 只付一次 fsync；
    #: 而 DATA_DIR 也可能在网络存储上，逐条 commit 会让刷新退化成几百次往返。
    pending: list = []
    BATCH = 200

    def _flush() -> None:
        nonlocal pending
        if pending:
            # execute 一次只能带一组参数；``executemany`` 正好（_Conn 也代理了它）。
            _conn = db._connect()
            sql = (f"INSERT INTO {TABLE} ({', '.join(_COLS)}) "
                   f"VALUES ({', '.join(['?'] * len(_COLS))}) "
                   f"ON CONFLICT (library_id, root, rel) DO UPDATE SET "
                   + ", ".join(f"{c}=excluded.{c}" for c in _COLS
                               if c not in ("library_id", "root", "rel")))
            _conn.executemany(sql, pending)
            _commit()
            pending = []

    for d in roots:
        droot = str(d)
        # ltype 传给枚举：库类型决定要不要做「序号单元」合并（第 73 期，见那里的注释）
        for f in _lib._iter_book_entries(d, exts, pats, lib.get("type")):
            try:
                rel = f.relative_to(d).as_posix()
            except ValueError:
                continue
            key = (droot, rel)
            if key in seen:
                continue
            seen.add(key)
            cur = stored.get(key)
            if cur is not None and not force:
                # 便宜闸门：条目自身没变就整段跳过 —— 一次 stat（音频目录是一次目录列举），
                # 而不是开 zip。**这是增量刷新的全部价值所在。**
                facts = _lib._cheap_facts(f)
                if facts is None:
                    continue
                if (facts[0], facts[1]) == cur:
                    unchanged += 1
                    continue
            p = _lib._probe_entry(f)
            if p is None:
                continue
            row = _lib._row_of(lib, d, f, p)
            pending.append((
                lid, droot, rel, row["id"],
                int(row["size"] or 0), float(row["mtime"] or 0),
                str(row["format"] or ""), str(row["title"] or ""), str(row["author"] or ""),
                str(row["series"] or ""), str(row["series_index"] or ""),
                1 if row["has_cover"] else 0, str(row["cover"] or ""),
                int(row["pages"] or 0), str(row["pages_source"] or ""),
                int(row["tracks"] or 0),
                str(row["year"] or ""), str(row["publisher"] or ""), str(row["isbn"] or ""),
                str(row["language"] or ""), str(row["description"] or ""),
                _dumps(row["tags"]), _dumps(row["narrators"]),
                1 if p["unparsable"] else 0,
                1 if row["fixed_layout"] else 0,
                1 if p["is_dir"] else 0,
                time.time(),
            ))
            added += 1
            if len(pending) >= BATCH:
                _flush()
    _flush()

    # 索引里有、磁盘上没了的行 → 删。按 (root, rel) 精确删，不整库重来
    # （整库重来在「只有一本书变了」时要重写全部 266 行，网络存储上纯属白付）。
    stale = [k for k in stored if k not in seen]
    for i in range(0, len(stale), 500):
        chunk = stale[i:i + 500]
        cond = " OR ".join(["(root=? AND rel=?)"] * len(chunk))
        params: list = [lid]
        for root, rel in chunk:
            params.extend([root, rel])
        _exec(f"DELETE FROM {TABLE} WHERE library_id=? AND ({cond})", params)
    if stale:
        _commit()

    return {"scanned": len(seen), "added": added, "removed": len(stale),
            "unchanged": unchanged, "skipped": False}


def refresh_all(force: bool = False, blocking: bool = True) -> dict:
    """刷新全部库（启动预热 / 「立即扫描」全量 / 监听线程每轮）。"""
    from . import library as _lib
    out = {}
    for lib in _lib.libraries():
        try:
            out[str(lib.get("id"))] = refresh_library(lib, force=force, blocking=blocking)
        except Exception:                     # noqa: BLE001 —— 一个库坏不该拖垮其余
            out[str(lib.get("id"))] = {"error": True, "skipped": False}
    return out


def refresh_stale(blocking: bool = False) -> dict:
    """只刷**脏了**的库 —— 监听线程每轮调它。

    监听线程额外负责「用户绕过 App 直接往 NAS 目录里丢文件」这种没有
    ``invalidate()`` 的变更：那些库永远不脏，靠 ``refresh_all`` 的定时全量兜底
    （见 ``watcher._loop``）。
    """
    from . import library as _lib
    out = {}
    for lib in _lib.libraries():
        lid = str(lib.get("id") or "")
        if not lid:
            continue
        if not _is_stale(lid) and lid in _ready:
            continue
        try:
            out[lid] = refresh_library(lib, blocking=blocking)
        except Exception:                     # noqa: BLE001
            out[lid] = {"error": True, "skipped": False}
    return out


def forget(library_id) -> None:
    """删掉某库的全部索引行（库被移除登记时调）。"""
    lid = str(library_id or "")
    if not lid:
        return
    _exec(f"DELETE FROM {TABLE} WHERE library_id=?", (lid,))
    _commit()
    with _state_lock:
        _dirty.pop(lid, None)
        _refreshed_seq.pop(lid, None)
        _ready.discard(lid)
        _cached_libs.discard(lid)
    # 库没了，它那本「列表」也得走 —— 这条**不经过 invalidate()**（库被删时不调它），
    # 所以必须自己删一次，否则 `/api/books` 会拿着一本已经不存在的库的书目。
    cache.drop(cache.book_list_key(lid))


# ---------------- 读取 ----------------

def _dumps(v) -> str:
    try:
        return json.dumps(v if v is not None else [], ensure_ascii=False)
    except Exception:                         # noqa: BLE001 —— 坏值降级成空列表，别让入库失败
        return "[]"


def _loads(s) -> list:
    try:
        v = json.loads(s) if s else []
    except Exception:                         # noqa: BLE001
        return []
    return v if isinstance(v, list) else []


def _book_of_row(lib: dict, row) -> dict:
    """索引行 + 库实体 → BookCard 契约的书目条目。

    字段与 ``library._row_of`` **逐项对应**（那份是权威定义，这里是它的逆）：
    存起来的直接取，读取时才拼的（``name``/``path``/``c1``/``c2``/``issues``/
    ``library_id``/``library_type``）现算。两边的口径靠 `test_catalog.py` 的
    对拍用例钉住 —— 一旦哪边加了字段而另一边没跟上，那条用例会红。
    """
    from . import library as _lib

    lid = str(lib.get("id") or "")
    rel = str(row["rel"] or "")
    root = str(row["root"] or "")
    bid = str(row["book_id"] or "")
    size = int(row["size"] or 0)
    is_dir = bool(row["is_dir"])
    has_cover = bool(row["has_cover"])
    c1, c2 = _lib._gradient(bid)
    try:
        # path 现拼：库里存的是根，不是绝对路径 —— 这样挪根 / 改库都不必回填索引
        path = str(pathlib.Path(root) / rel)
    except Exception:                         # noqa: BLE001
        path = root
    return {
        "id": bid,
        "name": rel,
        "size": size,
        "mtime": float(row["mtime"] or 0),
        "format": str(row["format"] or ""),
        "title": str(row["title"] or ""),
        "author": str(row["author"] or ""),
        "series": str(row["series"] or ""),
        "series_index": str(row["series_index"] or ""),
        "has_cover": has_cover,
        "cover": str(row["cover"] or ""),
        "pages": int(row["pages"] or 0),
        "pages_source": str(row["pages_source"] or ""),
        "tracks": int(row["tracks"] or 0),
        "year": str(row["year"] or ""),
        "publisher": str(row["publisher"] or ""),
        "isbn": str(row["isbn"] or ""),
        "language": str(row["language"] or ""),
        "description": str(row["description"] or ""),
        "tags": _loads(row["tags"]),
        "narrators": _loads(row["narrators"]),
        "fixed_layout": bool(row["fixed_layout"]),
        "c1": c1,
        "c2": c2,
        # ⚠️ 用**文件派生**的 has_cover（不是上面那个可能被元数据覆盖层改过的）——
        # 与 `_row_of` 完全一致：no-cover 是扫描期的判定，服务端封面在
        # `_apply_overlay` 里单独撤掉。
        "issues": _lib._issues_of(rel, size, is_dir, bool(row["unparsable"]), has_cover),
        "path": path,
        "library_id": lid,
        "library_type": str(lib.get("type") or "mixed"),
    }


def _order_key(rel: str):
    """书目顺序的排序键 —— 精确复刻 ``_iter_book_entries`` 的遍历顺序。

    遍历顺序是「库序 → 根序 → **先序遍历**（每层的名字排序）」：``sorted(d.iterdir())``
    排的是**整条绝对路径**，而子条目紧跟在它的父目录之后。整条路径比较等价于
    **按路径分段比较**（父目录是子条目的前缀，所以短的在前）——
    但**不等价于按 ``rel`` 整串比较**：拿 ``abc/`` 与 ``abc.epub`` 来说，
    分段比较给 ``abc/…`` 在前（``"abc"`` 是 ``"abc.epub"`` 的前缀），
    整串比较却是 ``abc.epub`` 在前（``.``=0x2E < ``/``=0x2F）。

    为什么要较真到这一层：**顺序是有语义的** —— ``id_conflicts`` 把每组里
    ``items[0]`` 当**保留项**（其余建议改名）。顺序一变，「保留哪一本」就变了，
    用户点一下「一键改名」改掉的会是另一本。所以这里按分段比较，不图省事。
    """
    parts = str(rel).split("/")
    return tuple([p.lower() for p in parts] if _WIN else parts)


def _rows_of(lib: dict) -> list:
    """一个库的全部索引行（**不做覆盖层**，调用方决定要不要合并元数据）。"""
    lid = str(lib.get("id") or "")
    if not lid:
        return []
    rows = _exec(f"SELECT * FROM {TABLE} WHERE library_id=?", (lid,)).fetchall()
    # 顺序 = 改造前 `_scan_once` 的顺序（库序 → 根序 → 目录序）。根序不能在 SQL 里
    # 排（root 是绝对路径，按字典序排不出用户在「来源文件夹」里设的顺序），
    # 所以在 Python 里按 roots_of 的位置补一层。
    from . import library as _lib
    pos = {str(p): i for i, p in enumerate(_lib.roots_of(lib))}
    rows.sort(key=lambda r: (pos.get(str(r["root"]), len(pos)), _order_key(r["rel"])))
    return rows


def _needs_refresh(lid: str) -> bool:
    """这个库现在需要扫一次吗？**一次内存判断**（不查库）。

    末一条判据与 ``_is_stale`` 是**同一个比较**（序号，不是时刻）——
    两处都手写过一遍时刻戳版本，改一处漏一处就等于这条路径没修。
    """
    with _state_lock:
        return (lid not in _ready
                or lid in _dirty
                or _dirty_all_seq > _refreshed_seq.get(lid, -1))


def _settle(lib: dict) -> None:
    """确保这个库的索引**本进程内至少刷过一次**，且此刻不脏。

    冷启动（刚升级上来、索引还是空的）与「写操作刚动过它」两条路都收敛到这里，
    其余情况只是一次内存判断、直接返回。

    「库是空的」与「索引是空的」在这里被显式分开：没有来源文件夹的库（空库 /
    已移除登记但书还留在磁盘上）会把 ``_ready`` 标上而不去扫 —— 不标的话
    每次读都会来试一遍全量刷新，而它永远扫不出东西。
    """
    from . import library as _lib
    lid = str((lib or {}).get("id") or "")
    if not lid or not _needs_refresh(lid):
        return
    if _lib.roots_of(lib):
        refresh_library(lib)
    else:
        _mark_fresh(lid)
        with _state_lock:
            _ready.add(lid)


def books_of(lib: dict) -> list:
    """一个库的书目（读索引 + 服务端元数据覆盖层）。**请求路径上的那个入口。**

    稳态下这是「一次 SELECT + 一次内存判断」，与书本数、与书库是不是挂在
    NAS 上都没有关系。

    第 62 期 C：外面再套一层 Redis。**收益如实说 —— 这一处有限**：省掉的是
    「一次 SELECT + 一次覆盖层批量查询 + 一遍 Python 拼装 + JSON 序列化」，
    在没有索引的时代这些相比扫盘可以忽略，现在它们就是这条路剩下的成本。
    254 KB 走局域网本身也要时间，所以它与「直读」是同一量级，**不必期待数量级的差别**
    （章节那一处的差别才是明显的：那边省掉的是开 zip + 解压 + 正则改写）。

    顺序要紧：``_settle()`` 必须在**读缓存之前** —— 它可能触发一次刷新、而刷新在
    「索引真的变了」时会丢缓存键。反过来的话就会「先读到旧值、再把旧值写回缓存」。
    """
    from . import library as _lib
    if not lib:
        return []
    _settle(lib)
    lid = str(lib.get("id") or "")
    key = cache.book_list_key(lid)
    hit = cache.get_json(key) if key else None
    if hit is not None:
        return hit
    rows = _rows_of(lib)
    out = _lib._apply_overlay([_book_of_row(lib, r) for r in rows])
    if key:
        cache.set_json(key, out, cache.TTL_LIST)
        with _state_lock:
            _cached_libs.add(lid)
    return out


def books(library_id=None) -> list:
    """全部库（或指定库）的书目 —— ``library.books()`` 的实现。"""
    from . import library as _lib
    libs = _lib.libraries()
    if library_id:
        libs = [l for l in libs if str(l.get("id")) == str(library_id)]
    out: list = []
    for lib in libs:
        out.extend(books_of(lib))
    return out


def find_by_id(bid: str) -> "dict | None":
    """按 id 取书（``library.by_id`` 的实现）。

    ⚠️ 两条语义必须保住，它们是**用进度 / 批注写错书**换来的：

    1. 命中多本 → 抛 ``BookIdConflict``（不静默取第一条）；
    2. 只认**仍登记在册**的库 —— 库被移除后索引行可能还在（索引是缓存不是真相源），
       不过滤就会让 ``by_id`` 返回一本界面上已经不存在的书。
    """
    from . import library as _lib
    hit = _hit_of(bid)
    if hit is None:
        return None
    row, lib = hit
    return _lib._apply_overlay([_book_of_row(lib, row)])[0]


def raw_book(bid: str) -> "dict | None":
    """按 id 取书，但**不过服务端覆盖层** —— 拿到的是「文件里原本是什么」。

    `book_index` 存的就是探测（EPUB 的 OPF / 文件名 / 归档）出来的原值，覆盖层
    （override > online > opf）是**读取时**才叠上去的，所以「原值」这一份在索引里
    一直躺着 —— 这个入口把它取出来。

    **为什么需要它**：`metastore.state()` 要给编辑器 / 刮削提供「OPF 原值」，用来
    判断「用户改过没有」与「要不要把这一版写进副本」。而卡片（``by_id`` / ``books()``）
    上的字段是**生效值** —— 拿它当 OPF 原值，只要用户改过书名，两边就永远相等，
    「与 OPF 原值不同才写」的判据于是恒为假：刮削**静默不再内嵌任何元数据**。
    （第 62 期之前这条路靠扫描缓存「碰巧」对：卡片是标脏之前扫出来的，身上还带着
    改之前的值。索引把覆盖层挪到读取时之后，这份巧合没有了 —— 该缺陷因此显形。）

    命中多本时**不抛异常**，返回 None：调用方是「取值」而不是「取书」，
    拿不到就退回传进来的卡片（= 第 62 期之前的行为），不该让编辑器接口 500。
    """
    from . import library as _lib
    hit = _hit_of(bid, unique_only=True)
    if hit is None:
        return None
    row, lib = hit
    return _book_of_row(lib, row)


def _hit_of(bid: str, unique_only: bool = False):
    """``book_id`` → ``(索引行, 库实体)``。取不到返回 None。

    ``unique_only=False``（`by_id` 用）时命中多本 → 抛 ``BookIdConflict``；
    ``unique_only=True``（`raw_book` 用）时命中多本 → 返回 None，交给调用方兜底。
    """
    from . import library as _lib
    bid = str(bid or "")
    if not bid:
        return None
    libs = _lib.libraries()
    by_lid = {str(l.get("id") or ""): l for l in libs}
    if not by_lid:
        return None
    # ⚠️ 每个库先 `_settle` 再查 —— 与 `books_of` / `counts` 同一个理由，但这里更
    # 要命：这里查的是**索引行**，而索引行由 `_settle` 保证新鲜。少了这一步，
    # ① 冷启动（索引还空着）时所有按 id 的接口一律 404，直到别的接口顺手扫了一次；
    # ② 更要命的是「改完立刻读」这条链路 —— `fileops` / 改名 / 上传封面都是
    #    `library.invalidate()` 紧接着 `library.by_id(bid)` 取新值（server.py 多处
    #    `fresh = library.by_id(bid) or {}`），不 settle 就会把**旧行**当成改完的结果。
    # 稳态下 `_settle` 只是一次内存字典判断，全库循环的代价可以忽略。
    for lib in libs:
        _settle(lib)
    keys = sorted(by_lid)
    hits: list = []
    # 分批 IN（与 db.get_effective_meta 同一范式）：SQLite 的变量上限是 999，
    # 库数量级远低于此，但写成分批就不必在加库时回头想这件事。
    for i in range(0, len(keys), 500):
        chunk = keys[i:i + 500]
        q = ",".join(["?"] * len(chunk))
        hits.extend(_exec(
            f"SELECT * FROM {TABLE} WHERE book_id=? AND library_id IN ({q})",
            [bid, *chunk],
        ).fetchall())
    if not hits:
        return None
    if len(hits) > 1:
        if unique_only:
            return None
        names = " / ".join(sorted({str(h["rel"]) for h in hits}))
        libs_txt = "、".join(sorted({str(h["library_id"]) for h in hits}))
        raise _lib.BookIdConflict(
            f"《{names}》在多个书库中同名（{libs_txt}），本服务无法确定是哪一本。"
            f"请到「设置 → 书库管理 → 跨库同名冲突」一键改名消除冲突后重试"
        )
    row = hits[0]
    lib = by_lid.get(str(row["library_id"]))
    if lib is None:                           # 库在查询与解析之间被删了
        return None
    return row, lib


def counts() -> dict:
    """``{library_id: 书目数}`` —— 一次 GROUP BY。

    改造前 `server._book_counts` 是「遍历 ``library.books()`` 数一遍」，
    也就是**为了列个书库清单要跑一次全量扫描**（线上 `/api/libraries` 返回
    1.8 KB 却要 41.9 秒，就是它）。

    ⚠️ 这里仍要对每个库跑一遍 :func:`_settle`：不跑的话冷启动时 `counts()` 会给
    每个库报 0（索引还空着），而 `/api/libraries` 恰恰是打开应用打的第一个接口 ——
    用户会先看到「所有库都是 0 本」，几百毫秒后才恢复正常。
    """
    from . import library as _lib
    for lib in _lib.libraries():
        _settle(lib)
    out: dict = {}
    for r in _exec(
        f"SELECT library_id, COUNT(*) AS n FROM {TABLE} GROUP BY library_id"
    ).fetchall():
        out[str(r["library_id"])] = int(r["n"] or 0)
    return out
