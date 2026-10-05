"""SQLite 持久层：单用户场景下的阅读进度与批注存储。

设计要点：
- 数据库文件落在 ``config.DATA_DIR/novelforge.db``（NAS 持久卷，零额外服务）。
- 全进程共享一个连接（check_same_thread=False），**读写一律经 ``_lock`` 串行**
  （见 :class:`_Conn`）—— 只有写路径持锁是不够的，见该类文档。
- 表：users（轻登录账号）、progress（每本书当前阅读位置）、annotations（高亮/笔记）、
  bookmarks（书签，与批注同构的软删除 + 位置去重）、meta_locks（元数据字段级锁定）、
  custom_field_defs（自定义字段定义）+ book_custom_values（按书的值）。
"""
import ast
import hashlib
import logging
import pathlib
import re
import threading
import json
import time
import uuid
from datetime import datetime, timedelta

try:  # 时区归一（Python 3.9+ 标准库；极老环境或缺 tzdata 时回落本地时）
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from .. import config


_db_path: "pathlib.Path | None" = None
#: 第 39 期改 ``RLock``：`_Conn` 的每条语句都要拿它，而既有的 ``with _lock:``
#: 块里还会再调 ``c.execute(...)`` —— 非重入锁会自己把自己锁死。
_lock = threading.RLock()
_conn = None          # 裸 sqlite3 连接（只有 `_connect` / `close` 碰它）
_conn_proxy = None    # 对上暴露的持锁代理


def db_path() -> pathlib.Path:
    global _db_path
    if _db_path is None:
        d = pathlib.Path(config.DATA_DIR)
        d.mkdir(parents=True, exist_ok=True)
        _db_path = d / "novelforge.db"
    return _db_path


class _Result:
    """一条语句的结果 —— **在锁内就已完全物化**，出锁后再读也安全。

    代理绝不能把「还没取完的语句」留到锁外：同一连接上另一个线程的
    ``execute`` 会让它抛 ``InterfaceError``（SQLITE_MISUSE）。所以这里
    只是内存里的一段行，接口照着 ``sqlite3.Cursor`` 的常用面做窄。
    """

    __slots__ = ("_rows", "_i", "rowcount", "lastrowid", "description")

    def __init__(self, rows, rowcount, lastrowid, description=None):
        self._rows = rows
        self._i = 0
        self.rowcount = rowcount
        self.lastrowid = lastrowid
        self.description = description

    def fetchone(self):
        if self._i >= len(self._rows):
            return None
        row = self._rows[self._i]
        self._i += 1
        return row

    def fetchall(self):
        rows = self._rows[self._i:]
        self._i = len(self._rows)
        return rows

    def fetchmany(self, size=1):
        rows = self._rows[self._i:self._i + int(size)]
        self._i += len(rows)
        return rows

    def __iter__(self):
        while self._i < len(self._rows):
            row = self._rows[self._i]
            self._i += 1
            yield row


class _Conn:
    """连接代理：**每条语句都在 ``_lock`` 内跑完，并把结果取干净**。

    为什么要有这层（第 39 期，实测）：

    CPython 的 ``sqlite3`` 模块**不保证同一个连接可被多线程并发使用**。本模块
    全进程共享一个连接（``check_same_thread=False``），原先只有**写路径**持锁，
    读路径裸调 ``_connect().execute(...)`` —— 于是两个线程同时进这个连接时抛
    ``InterfaceError: bad parameter or other API misuse``（底层是 SQLITE_MISUSE），
    急起来还能把解释器**打成段错误**。

    后果不是「报个错」那么轻：``library.get_library`` 把这个异常吞成 ``None``，
    于是 `lib_settings.overrides()` 得空 dict ⇒ **每库覆写静默回落全局值**
    （实测：用户关掉某库的「自动刮削」，读回来又是开的；放大探针下 5 秒复现
    两千余次）。这正是 `test_scrape_publish.py` 那例「扫描后按开关自动入队」
    偶发失败的根因。

    169 处调用点一行不改就同时纳入锁，靠的就是这层代理 —— 比逐处手改更不容易漏。
    语句抛错时异常照常向外传（锁由 ``with`` 释放）。
    """

    __slots__ = ("_raw",)

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, parameters=()):
        with _lock:
            cur = self._raw.execute(sql, parameters)
            return _Result(cur.fetchall(), cur.rowcount, cur.lastrowid,
                           cur.description)

    def executemany(self, sql, seq_of_parameters):
        with _lock:
            cur = self._raw.executemany(sql, seq_of_parameters)
            return _Result([], cur.rowcount, cur.lastrowid, cur.description)

    def executescript(self, sql):
        with _lock:
            self._raw.executescript(sql)
            return _Result([], -1, None, None)

    def commit(self):
        with _lock:
            self._raw.commit()

    def rollback(self):
        with _lock:
            self._raw.rollback()


def _connect():
    """取连接代理。后端由 ``NOVELFORGE_DB`` 选（默认 sqlite，见 core/sqlcompat）。

    两条路返回的代理**同形**（``execute`` / ``executemany`` / ``executescript`` /
    ``commit`` / ``rollback`` → ``_Result``），所以上层 169 处调用点一行不改。
    语句串行靠上面那把 ``_lock``：SQLite 侧由 ``_Conn`` 自己持锁，**PG 侧由
    ``pg.connect(_Result, _lock)`` 把同一把锁交给它**（第 62 期）——同一把锁，不是
    两把，所以不存在锁序问题。

    ⚠️ **建连接这一段也要持锁**（第 62 期实测到过的真实泄漏）：原先这里裸判
    ``_conn is None``，两个线程可以同时判空、各自建一条连接，后一个把前一个**覆盖掉**
    —— 那条被覆盖的连接再也没人拿得到句柄，于是它上面挂着的事务（psycopg 对每条语句
    都隐式 BEGIN）永远没人提交，攥着锁直到进程退出。测试侧的现场是
    ``DROP SCHEMA … CASCADE`` 在 ``wait_event_type=Lock`` 上无限等待。
    """
    global _conn, _conn_proxy
    if _conn is None:
        from . import sqlcompat, pg

        # RLock：本函数常在本模块其它持锁路径里被调（169 处调用点里有一批在
        # ``with _lock:`` 内），所以这里必须是可重入的。
        with _lock:
            if _conn is None:                      # 双检：锁外那次判空只是快路径
                if sqlcompat.is_pg():
                    _conn = _conn_proxy = pg.connect(_Result, _lock)
                else:
                    import sqlite3

                    c = sqlite3.connect(str(db_path()), check_same_thread=False)
                    c.row_factory = sqlite3.Row
                    _conn = c
                    _conn_proxy = _Conn(c)
    return _conn_proxy


def close() -> None:
    """关闭并清空缓存的连接与数据库路径。

    供**测试**（每个用例一套独立空库）与「运行时切换 DATA_DIR」使用。
    正常请求流程不会调用它 —— 生产路径下连接始终复用，行为与之前完全一致。

    ⚠️ 第 39 期：本函数持 ``_lock``，因此**不会**再撞上在飞语句（原先会段错误）；
    但 ``close()`` 之后仍攥着旧代理的线程会拿到 ``ProgrammingError`` —— 那是
    真错误，别吞（测试侧的根因见 ``tests/conftest.py::_quiesce_background``）。
    """
    global _conn, _conn_proxy, _db_path
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
        _conn_proxy = None
        _db_path = None
    # 第 62 期：**PG 后端下 close() 不删表**（`pg.drop_schema()` 由测试夹具显式调，
    # 见 tests/conftest.py::isolated）。第一版把「换一套空库」挂在 close() 上，被
    # 三个「关掉再重开」的升级用例当场抓住：SQLite 那边换空库靠的是**换 DATA_DIR**
    # （`isolated` 每个用例指向一个新的 tmp 目录，close 只是关连接），而 close() 本身
    # 从不删数据。把这个动作挪到 close() 里，等于让「`close()` + `init()` 模拟一次重启」
    # 变成「把库删了重建」—— 被测的那份数据在重启之前就已经没了，用例测的是空气。
    # 结论：close 就是 close。删 schema 是**夹具的**动作，不是连接的。
    #
    # 第 62 期：书目索引（catalog）的进程内状态必须跟着一起重置 ——
    # 它的「建过表了」标记与「这个库已刷过」集都是**进程级**的，而本函数换的是
    # **库级**的隔离（测试每个用例一套空库）。不重置的话下一个用例会跳过建表，
    # 然后在一条 `SELECT * FROM book_index` 上撞 no such table。
    try:
        from . import catalog
        catalog.reset_state()
    except Exception:                         # noqa: BLE001 —— 收尾动作不该让 close 失败
        pass


#: ``progress`` 表的完整定义 —— **只有这一份**。
#:
#: 为什么抽成常量而不是直接写在 ``init()`` 的 executescript 里：第 63 期 4/6 把唯一
#: 约束从 ``UNIQUE(book_id)`` 改成 ``UNIQUE(book_id, file_rel)``，老库只能**重建表**
#: （SQLite 没有 ``ALTER … DROP CONSTRAINT``），而重建要用同一份定义。两处各写一遍
#: 的话，改了建表忘了改重建，新库老库的结构就此静默分叉 —— 那种分叉只会在很久以后
#: 以「同一条查询在新库上对、在老库上错」的面目出现。
#:
#: ⚠️ 重建复制行时**不要带上 ``id``**：见 :func:`_rebuild_progress`。
_PROGRESS_SQL = """CREATE TABLE IF NOT EXISTS progress (
                id         INTEGER PRIMARY KEY,
                book_id    TEXT NOT NULL,
                -- 读的是**这本书里的哪个文件**（第 63 期 4/6）。一本书可以有多个成品
                -- 文件（EPUB + PDF + MOBI），加这一列之前它们**共用同一行进度**、
                -- 互相覆盖。空串 = 「这本书自己」：写入方不知道文件时用它
                --（KOReader 同步 / Komga / 标记已读完），与 reading_sessions.file_rel
                -- 是同一套约定。
                file_rel   TEXT NOT NULL DEFAULT '',
                locator    INTEGER NOT NULL,
                percent    REAL NOT NULL DEFAULT 0,
                -- 精确阅读位置（第 54 期）：EPUB CFI，由服务端按 (locator, 章内字符偏移)
                -- 经 core/epub_cfi.py 生成；空串 = 没有精确坐标（非 EPUB / 生成失败 /
                -- 非 NF 阅读器来源的写入），恢复侧回落「章 + 全书百分比」。
                cfi        TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                UNIQUE(book_id, file_rel)
            )"""


def init():
    """建表并写入默认账号（环境变量 AUTH_USER / AUTH_PIN 控制，缺省 admin/changeme）。"""
    with _lock:
        c = _connect()
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY,
                username   TEXT UNIQUE NOT NULL,
                pin_hash   TEXT NOT NULL,
                created_at REAL NOT NULL
            );
            -- 语义向量（第 54 期）：每本书一行，vec = core/embed.py 按「当前语料 + 模型」
            -- 派生的 float32 小端定长向量。它是**纯派生缓存**（删了随时可由 recompute
            -- 重建），但行丢了 ⇒ 相似书的余弦一路静默回落词袋，所以仍按含 book_id 表的
            -- 纪律进 REMAP_TABLES / ORPHAN_TABLES —— 搬走比重算省事，清掉比留着诚实。
            -- model_tag 标「这行向量是哪套模型算的」：读点只认当前 tag（embed.load_vectors），
            -- 换模型 / 换语料口径后旧行自然失效，recompute 全量覆写，不必清表。
            CREATE TABLE IF NOT EXISTS book_embeddings (
                book_id    TEXT PRIMARY KEY,
                vec        BLOB NOT NULL,
                model_tag  TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            );
            -- 原始文件来源（第 75 期）：**书被删时要一起回收的那三份文件里的 ①**。
            -- ① = 用户放进收书目录的那份投递件；② = 书库根里的成品（书目 path）；
            -- ③ = 项目按命名规则产出的出版副本（publish_path）。②③ 都能从书目 / 台账算出来，
            -- **① 不能** —— 书目是磁盘扫描的投影，没有「它当初从哪来」这一列。
            -- 所以入库成功的那一刻把 ① 的绝对路径记在这里，删书时查它。
            -- ⚠️ 为什么不是 `book_index` 上加一列：那是**派生表**（重扫即重建，
            -- `REMAP_DERIVED_TABLES` 明说不搬），加了也留不住。本表是持久的。
            CREATE TABLE IF NOT EXISTS book_origins (
                book_id     TEXT PRIMARY KEY,
                source_path TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS annotations (
                id         INTEGER PRIMARY KEY,
                book_id    TEXT NOT NULL,
                chapter    INTEGER NOT NULL,
                quote      TEXT NOT NULL,
                color      TEXT NOT NULL DEFAULT 'yellow',
                style      TEXT NOT NULL DEFAULT 'highlight',
                note       TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                -- 位置锚（第 63 期 6/6）。**两列是两回事，别合并**：
                --   `anchor` 是**来源原生**的位置标识（KOReader 的 XPointer、Kobo 的 locator），
                --     本项目**解析不了它** —— 我们没有 KOReader 那套排版，同一个
                --     `/body/DocFragment[3]/body/div/p[5]` 在我们的 DOM 上落不到同一段文字上。
                --     它只用于两件事：导入去重、给用户看这条是哪来的。
                --   `start_off`/`end_off` 是**本应用章内字符偏移**（半开区间 `[起, 止)`），
                --     由阅读器自己算，所以**真能定位**：同章重复的一句话靠它才不会高亮错那一处。
                -- -1 = 无锚 / '' = 无原生标识。**不用 0 当哨兵** —— 0 是「章首」这个合法偏移。
                anchor     TEXT NOT NULL DEFAULT '',
                start_off  INTEGER NOT NULL DEFAULT -1,
                end_off    INTEGER NOT NULL DEFAULT -1,
                -- 来源给的是章节**标题**时存这里（设备批注），本项目自己写的批注留空。
                -- 为什么要有它：`chapter` 是本项目的**章节序号**，而设备只知道标题
                -- （KOReader 的 `chapter` 字段是 `getTocTitleByPage` 的结果）。拿标题
                -- 去填序号只能是猜 —— 界面照 `chapter+1` 渲染出「第 1 章」就是**编造**。
                -- 所以：`chapter = -1` 表示「序号未知」（与锚的 -1 同一套约定），
                -- 此时界面显示这个标题、也不给「跳转到该章」的链接。
                chapter_title TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_anno_book ON annotations(book_id);
            -- 书签（第 34 期）：软删除语义与批注**同构**（删除 = 移入垃圾桶写 deleted_at，
            -- 真删走独立的 purge 出口）。两处只属于书签的口径：
            --   · UNIQUE(book_id, anchor) ⇒ **同一位置不会产生第二条**（位置去重）；
            --   · 墓碑行（deleted_at != 0）留在原地，同位置再加书签时**复活那一行**
            --     而不是插新行（上游 bookmark.service.ts 的 tombstone 语义）。
            -- updated_at 是**并发合并**的比较基准（客户端回传它看到的版本，服务端据此判谁新）。
            CREATE TABLE IF NOT EXISTS bookmarks (
                id         INTEGER PRIMARY KEY,
                book_id    TEXT NOT NULL,
                anchor     TEXT NOT NULL,
                chapter    INTEGER NOT NULL DEFAULT 0,
                percent    REAL NOT NULL DEFAULT 0,
                label      TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                deleted_at REAL NOT NULL DEFAULT 0,
                UNIQUE(book_id, anchor)
            );
            CREATE INDEX IF NOT EXISTS idx_bookmark_book ON bookmarks(book_id);
            CREATE TABLE IF NOT EXISTS collections (
                id         INTEGER PRIMARY KEY,
                name       TEXT UNIQUE NOT NULL,
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS collection_items (
                id            INTEGER PRIMARY KEY,
                collection_id INTEGER NOT NULL,
                book_id       TEXT NOT NULL,
                added_at      REAL NOT NULL,
                UNIQUE(collection_id, book_id)
            );
            CREATE INDEX IF NOT EXISTS idx_citem_coll ON collection_items(collection_id);
            CREATE INDEX IF NOT EXISTS idx_citem_book ON collection_items(book_id);
            CREATE TABLE IF NOT EXISTS reading_sessions (
                id         INTEGER PRIMARY KEY,
                book_id    TEXT NOT NULL,
                seconds    REAL NOT NULL,
                started_at REAL NOT NULL,
                ended_at   REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_session_book ON reading_sessions(book_id);
            CREATE INDEX IF NOT EXISTS idx_session_end ON reading_sessions(ended_at);
            CREATE TABLE IF NOT EXISTS tasks (
                id         TEXT PRIMARY KEY,
                type       TEXT NOT NULL DEFAULT 'download',
                title      TEXT NOT NULL DEFAULT '',
                detail     TEXT NOT NULL DEFAULT '',
                status     TEXT NOT NULL DEFAULT 'queued',
                progress   REAL NOT NULL DEFAULT 0,
                error      TEXT NOT NULL DEFAULT '',
                result     TEXT NOT NULL DEFAULT '',
                fname      TEXT NOT NULL DEFAULT '',
                notice     TEXT NOT NULL DEFAULT '',
                actor      TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_task_created ON tasks(created_at DESC);
            CREATE TABLE IF NOT EXISTS notifications_read (
                notif_id  TEXT PRIMARY KEY,
                read_at   REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS achievements (
                key        TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                -- ⚠️ 列名加双引号（第 62 期）：``desc`` 是**保留字**（ORDER BY … DESC）。
                -- 双引号里的标识符在 SQLite 与 PG 上都是「这是列名」，两边都认；
                -- 不加的话 SQLite 侥幸能过，PG 直接语法错误。同一个理由见 smart_scopes.match。
                "desc"     TEXT NOT NULL DEFAULT '',
                group_name TEXT NOT NULL DEFAULT '',
                metric     TEXT NOT NULL DEFAULT '',
                target     REAL NOT NULL DEFAULT 1,
                sort       INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS user_achievements (
                key         TEXT PRIMARY KEY,
                unlocked_at REAL NOT NULL
            );
            -- 书籍评分（1–5 星，每书一条）。
            -- 上游成就体系里有 4 条依赖它（Rate your first book / Rate 10 books /
            -- Give a book a 5-star rating / Use all five star ratings），
            -- 而本项目此前**完全没有评分概念**，故先补这张表。
            CREATE TABLE IF NOT EXISTS ratings (
                book_id    TEXT PRIMARY KEY,
                stars      INTEGER NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS reading_status (
                book_id     TEXT PRIMARY KEY,
                status      TEXT NOT NULL DEFAULT 'unread',
                started_at  REAL NOT NULL DEFAULT 0,
                finished_at REAL NOT NULL DEFAULT 0,
                updated_at  REAL NOT NULL
            );
            -- 阅读尝试 / 重读（第 43 期）：把「一轮阅读」记成一行。
            -- 语义：一轮 = 「开始读 → 读完」；读完后重新开始就是**新一轮**（round 递增）
            -- ⇒ 它比 reading_status 的单一状态行更能表达「这本书读过几遍」。
            -- 与既有三处的关系：reading_status = 当前状态、reading_sessions = 会话碎片、
            -- progress = 停在哪儿；本表是**轮次**的上位记录（reset_reading_state 一并清）。
            -- finished_at=0 表示该轮尚未读完；status ∈ {reading, finished}。
            CREATE TABLE IF NOT EXISTS reading_attempts (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id     TEXT NOT NULL,
                round       INTEGER NOT NULL DEFAULT 1,
                started_at  REAL NOT NULL DEFAULT 0,
                finished_at REAL NOT NULL DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'reading',
                created_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_attempt_book ON reading_attempts(book_id);
            CREATE TABLE IF NOT EXISTS smart_scopes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                rules      TEXT NOT NULL,                      -- JSON: [{field, op, value}]
                "match"    TEXT NOT NULL DEFAULT 'all',        -- all = 且 / any = 或（保留字，见上）
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS opds_sources (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                url        TEXT NOT NULL,
                username   TEXT NOT NULL DEFAULT '',           -- Basic Auth（多数 OPDS 源用）
                password   TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS koreader_docs (
                book_id     TEXT PRIMARY KEY,
                doc_md5     TEXT NOT NULL,                     -- partialMD5（KOReader 默认算法）
                alt_md5     TEXT NOT NULL DEFAULT '',          -- md5(basename)（checksum_method=FILENAME）
                size        INTEGER NOT NULL DEFAULT 0,        -- 用于判断缓存是否过期
                mtime       REAL NOT NULL DEFAULT 0,
                computed_at REAL NOT NULL
            );
            -- 偏好「模式」：具名的整套偏好快照。payload 是 JSON（块名 reader/pdf/comic/
            -- appearance/cover 由前端定义），后端只做**浅校验**（见 server._check_payload）——
            -- 偏好字段随功能演进，深校验会把两端耦死。
            CREATE TABLE IF NOT EXISTS pref_profiles (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                payload    TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            -- 偏好「设备」：每台设备持有**自己的一份配置**（payload）。active_profile_id 只是
            -- 「当前套用了哪个模式」的来源标记 —— 应用模式 = 拷贝内容，之后各改各的，
            -- 所以删模式时只需把这个标记置空，绝不动设备 payload。
            CREATE TABLE IF NOT EXISTS pref_devices (
                id                TEXT PRIMARY KEY,
                name              TEXT NOT NULL DEFAULT '',
                payload           TEXT NOT NULL,
                active_profile_id INTEGER,
                created_at        REAL NOT NULL,
                last_seen         REAL NOT NULL
            );
            -- 收书目录条目（Book Dock 五态流水线，第 7 期）。
            -- 一条 = 投递目录里的一个文件：id 取文件名（投递目录是平的，见 core/bookdock.py），
            -- 状态在 core/bookdock.py 的常量里定义，这里只存字符串。
            CREATE TABLE IF NOT EXISTS book_dock_items (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                ext         TEXT NOT NULL DEFAULT '',
                size        INTEGER NOT NULL DEFAULT 0,
                status      TEXT NOT NULL DEFAULT 'pending',
                output      TEXT NOT NULL DEFAULT '',
                detail      TEXT NOT NULL DEFAULT '',
                retries     INTEGER NOT NULL DEFAULT 0,
                created_at  REAL NOT NULL,
                updated_at  REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dock_status ON book_dock_items(status);
            CREATE INDEX IF NOT EXISTS idx_dock_updated ON book_dock_items(updated_at DESC);
            -- 元数据在线/本地分层（第 8 期：在线优先 + 用户编辑兜底）。
            -- meta_override：用户显式改过的字段（受保护，再抓取不冲掉）；value 空 = 撤销覆盖。
            -- meta_online：最近一次在线抓取的值（仅供「恢复在线」回退，不参与展示优先）。
            CREATE TABLE IF NOT EXISTS meta_override (
                book_id    TEXT NOT NULL,
                field      TEXT NOT NULL,
                value      TEXT NOT NULL DEFAULT '',
                -- 首次覆盖前的 OPF 原值：无在线值时「恢复在线」用它还原，避免丢失编辑前的值
                orig       TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                PRIMARY KEY(book_id, field)
            );
            CREATE TABLE IF NOT EXISTS meta_online (
                book_id    TEXT NOT NULL,
                field      TEXT NOT NULL,
                value      TEXT NOT NULL DEFAULT '',
                source     TEXT NOT NULL DEFAULT '',
                fetched_at REAL NOT NULL,
                PRIMARY KEY(book_id, field)
            );
            CREATE INDEX IF NOT EXISTS idx_override_book ON meta_override(book_id);
            CREATE INDEX IF NOT EXISTS idx_online_book ON meta_online(book_id);
            -- 字段级锁定（第 35 期）：用户显式说「这个字段别让抓取动」。
            -- ⚠️ **刻意与 meta_override 分表**：override 行只在**有值**时存在，
            --    所以它无法表达「我没改过、但也不想让抓取动它」；而锁必须能落在
            --    一个从没被编辑过的字段上（也能在编辑过之后解锁、让抓取重新接管）。
            -- field 取值 = ``fileops.METADATA_FIELDS`` 的 10 个 + 独立的 ``cover``。
            CREATE TABLE IF NOT EXISTS meta_locks (
                book_id    TEXT NOT NULL,
                field      TEXT NOT NULL,
                locked_at  REAL NOT NULL,
                PRIMARY KEY(book_id, field)
            );
            CREATE INDEX IF NOT EXISTS idx_meta_lock_book ON meta_locks(book_id);
            -- 书籍封面（第 17 期 T3）：元数据写回改为只存服务端，封面同样不写进 EPUB，
            -- 而是按 book_id 缓存到本表（BLOB 直接落库，零外链、零独立目录）。
            -- 展示 / OPDS 封面接口优先取服务端缓存，无则回退 EPUB 内嵌图。
            CREATE TABLE IF NOT EXISTS meta_cover (
                book_id    TEXT PRIMARY KEY,
                data       BLOB NOT NULL,
                media_type TEXT NOT NULL DEFAULT 'image/jpeg'
            );
            -- 书城目录来源（第 85 期）：从**正版官方书城**取回的章节目录 —— 只取标题与顺序，
            -- **绝不取正文**（见 `sources/toc_sources.py` 的模块注释）。一行 = 一本书在一个来源上
            -- 的一次抓取结果。
            -- ⚠️ **负结果也要落库**（ok=0 的行）：否则每次打开详情页都会重新外呼一遍，
            --    白白挨风控；界面据 note 如实显示上次为什么没取到。
            CREATE TABLE IF NOT EXISTS store_toc (
                book_id        TEXT NOT NULL,
                source         TEXT NOT NULL,
                -- 书城侧的书号 / 书页 URL（用户手动指定时就是用户填的那个）
                store_ref      TEXT NOT NULL DEFAULT '',
                matched_title  TEXT NOT NULL DEFAULT '',
                matched_author TEXT NOT NULL DEFAULT '',
                confidence     REAL NOT NULL DEFAULT 0,
                -- 用户手动指定 ⇒ 视为确定（自动匹配的置信度不再参与判断）
                manual         INTEGER NOT NULL DEFAULT 0,
                ok             INTEGER NOT NULL DEFAULT 0,
                note           TEXT NOT NULL DEFAULT '',
                -- 目录负载：``[[标题, 层级], ...]`` 的 JSON（层级可缺省 = 平铺）
                payload        TEXT NOT NULL DEFAULT '[]',
                fetched_at     REAL NOT NULL,
                PRIMARY KEY(book_id, source)
            );
            CREATE INDEX IF NOT EXISTS idx_store_toc_book ON store_toc(book_id);
            -- 书城章节 ↔ 本地章节的映射（第 85 期）。覆盖层据此把书城那份的**标题与卷名**
            -- 套到本地章节上（`reading_list.apply_toc_override`）。
            -- ⚠️ **未映射的本地章节不出现在本表里** —— 于是覆盖层永远造不出「点不开的假条目」。
            -- ⚠️ 两张表都含 book_id，已按纪律登记进 ORPHAN_TABLES / REMAP_DERIVED_TABLES
            --    （不搬的理由写在 `REMAP_DERIVED_TABLES` 上方，契约测试 `test_remap_tables` 钉住）。
            CREATE TABLE IF NOT EXISTS toc_map (
                book_id     TEXT NOT NULL,
                source      TEXT NOT NULL,
                store_index INTEGER NOT NULL,
                local_index INTEGER NOT NULL,
                method      TEXT NOT NULL DEFAULT '',
                score       REAL NOT NULL DEFAULT 0,
                PRIMARY KEY(book_id, source, store_index)
            );
            CREATE INDEX IF NOT EXISTS idx_toc_map_local ON toc_map(book_id, local_index);
            -- 在线阅读的源绑定（第 93 期）：**一本书 ↔ 一个书源上的一页**。
            -- 存的是「去哪个源的哪个书页读这本」这件用户**显式声明**的事 ——
            -- 本表的每一行都是用户按下的一个动作（选源 / 粘 URL），磁盘上推不出来。
            --
            -- ⚠️ `url` 只在服务端：客户端永远按 `index` 取章，不许传 URL（无 SSRF 面）。
            -- ⚠️ `pos` 是**在线位置**，与 `progress` 表那条本地位置**并存且不互相覆盖** ——
            --    本地读到第 3 章、线上读到第 40 章是两件都真实的事（见 core/reading_list.align_online
            --    的注释）。跨客户端续读靠它：任何客户端打开这本书都从同一个 `pos` 开始。
            -- ⚠️ `seen` = 已读过的**在线**章下标（JSON 数组，上限 64）——「在线读超过 5 章
            --    就自动把本地补齐」的计数器，封顶是为了不让行无限长大（跨过门槛后它就不再有用）。
            -- ⚠️ `auto_task` = 自动落地任务 id，非空即「这次绑定已经触发过自动下载」⇒
            --    **只触发一次**（失败也不重复轰炸，用户可以在详情页显式重试）。
            -- ⚠️ 含 book_id ⇒ 与 store_toc / toc_map **不同**：那两张是「外部数据的缓存」，
            --    丢了下次再取一次就有；这张是**用户的声明**，换库 / 改名丢了就只能靠用户重新绑
            --    ⇒ 进 REMAP_TABLES 跟着搬、进 ORPHAN_TABLES 可清理（理由写在两处常量旁边）。
            CREATE TABLE IF NOT EXISTS online_bind (
                book_id    TEXT PRIMARY KEY,
                library_id TEXT NOT NULL DEFAULT '',
                source     TEXT NOT NULL DEFAULT '',
                url        TEXT NOT NULL DEFAULT '',
                title      TEXT NOT NULL DEFAULT '',
                pos        INTEGER NOT NULL DEFAULT 0,
                seen       TEXT NOT NULL DEFAULT '[]',
                auto_task  TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL DEFAULT 0
            );
            -- 书源台账（第 86 期）：**关于书源的元数据**，不是书源本体。
            -- ⚠️ 规则本体仍旧只存 `SOURCES_DIR/<name>.json`（`sources/store.py` 是唯一写入路径）——
            --    台账以 `name` 关联它，权限仅限「导入来源 / 去重键 / 档位 / 原始 JSON / 启停 /
            --    最近验证 / 最近追更」。长出第二份规则定义是本项目明令禁止的形态。
            -- ⚠️ **不含 book_id** ⇒ 不进 remap 四处（与第 81 期 `recycle_items` 同口径）。
            CREATE TABLE IF NOT EXISTS source_ledger (
                name             TEXT PRIMARY KEY,
                origin           TEXT NOT NULL DEFAULT '',   -- 哪份文件 / 哪个入口导入
                dedup_key        TEXT NOT NULL DEFAULT '',   -- 归一化站点（空 = 无法判定，不参与去重）
                rule_hash        TEXT NOT NULL DEFAULT '',   -- 整条源的规范化哈希
                supported        TEXT NOT NULL DEFAULT 'yes',-- yes / partial / no
                source_type      TEXT NOT NULL DEFAULT 'text',
                group_name       TEXT NOT NULL DEFAULT '',   -- Legado 的 bookSourceGroup
                raw_json         TEXT NOT NULL DEFAULT '',   -- 原始书源原文（导出的凭据，也是重新分析的输入）
                unsupported      TEXT NOT NULL DEFAULT '[]', -- 逐条 {field,why,instead} 的 JSON
                notes            TEXT NOT NULL DEFAULT '[]',
                enabled          INTEGER NOT NULL DEFAULT 1, -- 启停（文件仍在 SOURCES_DIR）
                imported         INTEGER NOT NULL DEFAULT 0, -- 1 = 由导入产生；0 = 手写 / 内置
                imported_at      REAL NOT NULL,
                updated_at       REAL NOT NULL,
                verified_at      REAL,
                verify_ok        INTEGER,
                verify_count     INTEGER NOT NULL DEFAULT 0,
                verify_ms        INTEGER NOT NULL DEFAULT 0,
                verify_error     TEXT NOT NULL DEFAULT '',
                last_update_at   REAL,
                last_update_note TEXT NOT NULL DEFAULT ''
            );
            CREATE INDEX IF NOT EXISTS idx_source_ledger_site ON source_ledger(dedup_key);
            -- 覆盖前备份（第 86 期）：`overwrite` / `update` 一律先把旧规则原文存这里，可回滚。
            -- ⚠️ 主键用 uuid 而**不用 AUTOINCREMENT**：本项目的 PG 后端经 `sqlcompat` 跑同一批
            --    DDL，自增语法不通用（自增只会让「备份回滚」这个功能在 PG 上整块失效）。
            CREATE TABLE IF NOT EXISTS source_ledger_history (
                id         TEXT PRIMARY KEY,
                name       TEXT NOT NULL,
                kind       TEXT NOT NULL DEFAULT '',   -- rule = 被覆盖的旧规则原文
                payload    TEXT NOT NULL DEFAULT '',
                rule_hash  TEXT NOT NULL DEFAULT '',
                note       TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_sl_hist_name ON source_ledger_history(name, created_at);
            -- 导入历史（第 86 期）：每次导入留一条（时间、来源、各档计数、逐条结论）。
            CREATE TABLE IF NOT EXISTS source_imports (
                id         TEXT PRIMARY KEY,
                origin     TEXT NOT NULL DEFAULT '',
                actor      TEXT NOT NULL DEFAULT '',
                counts     TEXT NOT NULL DEFAULT '{}',
                detail     TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL
            );
            -- 书源变量（第 86 期）：Legado 的 `loginUi` 表单值 / 密钥（番茄那源的「密钥」、
            -- 聚合源的「模式 / 音色」）。规则里以 `{var:<key>}` 引用。
            -- ⚠️ 值等同凭据：接口只回 `has_<key>`，**绝不回显明文**（与 llm.api_key 同口径）。
            CREATE TABLE IF NOT EXISTS source_vars (
                name       TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                PRIMARY KEY(name, key)
            );
            -- 作者级元数据（第 8 期 D1/D2/D5）：在线抓取的 bio/photo 与用户本地覆盖分列。
            -- 展示取 本地覆盖 > 在线；用户改过的不会被再次抓取冲掉。
            -- 照片一律缓存到 CACHE_DIR/authors/（零外链），这里只存文件名。
            CREATE TABLE IF NOT EXISTS authors (
                name             TEXT PRIMARY KEY,
                bio              TEXT NOT NULL DEFAULT '',
                bio_local        TEXT NOT NULL DEFAULT '',
                -- 排序名（第 32 期）：排序用的键，与显示名分开 —— 「鲁迅」要排在 L 下、
                -- 「The Lord of the Rings」要按 Lord 排，都不是把显示名改掉能解决的。
                -- 与 bio 同构：在线值与本地覆盖**分列**，生效取 本地覆盖 > 在线，
                -- 两者都空则排序回退到 name（即加此列之前的行为，一字不差）。
                sort_name        TEXT NOT NULL DEFAULT '',
                sort_name_local  TEXT NOT NULL DEFAULT '',
                photo_path       TEXT NOT NULL DEFAULT '',
                photo_source     TEXT NOT NULL DEFAULT '',
                photo_local_path TEXT NOT NULL DEFAULT '',
                fetched_at       REAL NOT NULL DEFAULT 0
            );
            -- 演播者级元数据（第 53 期）：与 authors 表同源同构，但**刻意精简** ——
            -- 能力矩阵 hasPhoto=—，故无 bio/photo；本项目作者侧亦未实现真·软删，故不引入
            -- deleted_at（与 authors 保持一致，杜绝双标）。只保留排序名两列：
            -- 在线派生值与本地覆盖**分列**，生效取 本地覆盖 > 在线（派生），两者皆空回退 name。
            CREATE TABLE IF NOT EXISTS narrators (
                name             TEXT PRIMARY KEY,
                sort_name        TEXT NOT NULL DEFAULT '',
                sort_name_local  TEXT NOT NULL DEFAULT ''
            );
            -- 系列级元数据（第 12 期 C3 SYNOPSIS）：与 authors 表同构 —— 在线抓取值与
            -- 用户本地覆盖**分列**，展示取 本地覆盖 > 在线，用户改过的不会被再次抓取冲掉。
            --
            -- ⚠️ **本表是系列级字段的唯一存储**：刻意**不写回 EPUB**。
            --    OPF 没有「系列简介」这个字段（唯一近似 dc:description 属于**单册**，
            --    写进去就是覆盖掉某一册自己的简介），而「系列首发年」写进各册 dc:date
            --    会让某本 2019 年出版的第 7 册变成 2015 年 —— 属信息损毁。
            --    代价（已确认接受）：其他软件**直读文件**时看不到这些字段；连服务读则可见。
            CREATE TABLE IF NOT EXISTS series_meta (
                name              TEXT PRIMARY KEY,
                description       TEXT NOT NULL DEFAULT '',
                description_local TEXT NOT NULL DEFAULT '',
                publisher         TEXT NOT NULL DEFAULT '',
                publisher_local   TEXT NOT NULL DEFAULT '',
                first_year        TEXT NOT NULL DEFAULT '',
                first_year_local  TEXT NOT NULL DEFAULT '',
                tags              TEXT NOT NULL DEFAULT '',
                tags_local        TEXT NOT NULL DEFAULT '',
                -- 外部**声明**的系列总册数；与「库里实际拥有数」语义不同，勿混用
                declared_count    INTEGER NOT NULL DEFAULT 0,
                source            TEXT NOT NULL DEFAULT '',
                -- 一致性打分（无系列实体，靠成员书打分挑候选）→ 界面据此展示置信度
                score             REAL NOT NULL DEFAULT 0.0,
                fetched_at        REAL NOT NULL DEFAULT 0
            );
            -- 自定义元数据（第 35 期）：把原先「抓取配置里写死的一串键值对」升级为
            -- **可管理的字段定义**（上游 custom-metadata 的建字段 / 排序 / 改标签 /
            -- 切适用书库 / 归档 / 软删恢复六项）。
            -- 定义与值分两张表：定义是全局的，值是**按书**的。
            -- ⚠️ `key` 与 `label` 分离是「改显示名不动值」的前提：值表按 **key** 引用，
            --    改 label 不会动任何一本书的值（改 key 则等于换了一个字段，故不提供）。
            -- 旧配置项 `metadata_fetch.custom_fields` 由 ``core.customfields.migrate_from_config``
            -- 一次性迁成定义（幂等），之后该配置项下线、不再有人读它。
            CREATE TABLE IF NOT EXISTS custom_field_defs (
                id            INTEGER PRIMARY KEY,
                key           TEXT NOT NULL UNIQUE,
                label         TEXT NOT NULL,
                -- text / number / date / list（校验在 core/customfields.py，DB 只存字符串）
                type          TEXT NOT NULL DEFAULT 'text',
                position      INTEGER NOT NULL DEFAULT 0,
                -- 适用书库（字面量列表，空 = 全部书库）；不是所有字段都对每个库有意义
                library_ids   TEXT NOT NULL DEFAULT '',
                -- 抓取时给「还没有这一项」的书补的值（空 = 不参与抓取，只做手工字段）
                default_value TEXT NOT NULL DEFAULT '',
                -- 归档：不进编辑界面（值不丢），但定义本身仍可管理
                archived      INTEGER NOT NULL DEFAULT 0,
                created_at    REAL NOT NULL,
                updated_at    REAL NOT NULL,
                -- 垃圾桶（软删，与批注 / 书签同构：删除 = 移入垃圾桶，真删走 purge）
                deleted_at    REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_custom_field_pos ON custom_field_defs(position, id);
            -- 按书的自定义字段值。
            -- ⚠️ **「行存在」本身就是语义**：抓到默认值只在**没有行**时写入 ——
            --    行存在即「这本书的这一项被管过了」（哪怕值是空串，也不该被默认值填回来）。
            --    这与批注/书签那套软删除无关：值表不做软删，清空 = 写空串而不是删行。
            CREATE TABLE IF NOT EXISTS book_custom_values (
                book_id    TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL,
                PRIMARY KEY(book_id, key)
            );
            CREATE INDEX IF NOT EXISTS idx_custom_value_book ON book_custom_values(book_id);
            -- 多书库（第 10 期 D8）：库实体。type 决定功能显隐矩阵。
            -- 第 41 期重构：库不再有单一 root_path，**持有多个文件夹的绝对路径**
            -- （source_dirs，JSON 数组）。每个文件夹必须落在某个已配置来源根之内
            -- （就地引用语义，跨根合法）。扫描 / 落盘 / 路径解析均遍历这些绝对路径。
            -- 原 mode('inplace'/'import') / root_path / storage_path / source_subdir
            -- 概念已移除——本项目只保留「就地引用」，相对子目录信息由前端展示层持有，不落库。
            CREATE TABLE IF NOT EXISTS libraries (
                id             TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                type           TEXT NOT NULL DEFAULT 'mixed',
                -- 第 41 期：该库所有文件夹的绝对路径（JSON 数组文本）。空 = 尚未配置内容来源。
                -- 每个路径必须落在某个来源根之内（server 建/改库时校验）。
                source_dirs    TEXT NOT NULL DEFAULT '',
                rules          TEXT NOT NULL DEFAULT '',
                -- 每库覆盖（第 13 期）：JSON 文本，键 = 全局配置的**点分路径**（如 "output.layout"）。
                -- 只存**被本库覆写**的键；未出现的键一律继承全局 ——
                -- 于是全局改了策略，没覆写过的库会自动跟着变（若存全量副本就做不到这点）。
                settings       TEXT NOT NULL DEFAULT '',
                sort_order     INTEGER NOT NULL DEFAULT 0,
                created_at     REAL NOT NULL,
                last_scan_at   REAL NOT NULL DEFAULT 0,
                last_scan_note TEXT NOT NULL DEFAULT '',
                -- 逐库扫描调度（第 17 期 T2）：watch=是否监听该库文件夹；
                -- scan_interval=轮询间隔秒（0=继承全局）；scan_cron=定时表达式（空=不启用）。
                watch           INTEGER NOT NULL DEFAULT 1,
                scan_interval   INTEGER NOT NULL DEFAULT 0,
                scan_cron       TEXT NOT NULL DEFAULT '',
                -- 刮削出版成品目录（第 18 期）：刮削后**硬链接副本**的落点，供外部阅读器
                -- （Komga 等）直接挂载读取。空 = 该库不产出副本。
                -- ⚠️ 副本只读源、只写自己：源文件永不改写。该目录不得位于任何库根 /
                -- 扫描源目录内部（否则会被扫回来，书列表出现重复），由 server 侧校验。
                publish_path    TEXT NOT NULL DEFAULT '',
                -- 新库向导（第 40 期）三列：
                -- icon=库图标名（前端 lib/icons.ts 的 ICONS 键；空 = 不显示图标）。
                -- allowed_exts=该库扫描白名单，JSON 数组文本（如 [".epub",".pdf"]）。
                --   ⚠️ ''=**没设过**（读时回落库类型默认，见 library.exts_for_library），
                --   不是「一个格式都不收」——空集合会让库变成永远扫不出东西的死库。
                --   ⚠️ 也不能把「按类型推导的扩展名」写成列默认值：SQLite 的
                --   ALTER TABLE ADD COLUMN 只接受常量默认值。
                -- exclude=库级排除图案，JSON 数组文本。glob 语义与 watcher.ignore **同族**
                --   但有两处明写的差异：用 fnmatchcase（平台无关；watcher 那套用的 fnmatch
                --   在 Windows 上大小写不敏感），且含 '/' 的模式匹相对库根的路径。
                --   ⚠️ 两者是**两条不同的轴**：watcher.ignore 只管 INPUT_DIR 投递。
                icon            TEXT NOT NULL DEFAULT '',
                allowed_exts    TEXT NOT NULL DEFAULT '',
                exclude         TEXT NOT NULL DEFAULT ''
            );
            -- 迁移台账：既做**幂等**依据（重复启动不重复搬），也做**回滚**依据。
            -- 迁移是破坏性操作，故逐条落库：src/dst 都要记全，供反向移动。
            CREATE TABLE IF NOT EXISTS library_migrations (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id   TEXT NOT NULL,
                direction  TEXT NOT NULL DEFAULT 'move',
                library_id TEXT NOT NULL DEFAULT '',
                src        TEXT NOT NULL,
                dst        TEXT NOT NULL,
                status     TEXT NOT NULL DEFAULT 'pending',
                error      TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_mig_batch ON library_migrations(batch_id);
            -- 轻量 KV：持久化**运行态**（如「用户已答过迁移门禁」）。
            -- 刻意不放 config.yaml —— 那是用户配置，会被设置页覆盖；门禁状态属于运行痕迹。
            CREATE TABLE IF NOT EXISTS app_state (
                key        TEXT PRIMARY KEY,
                value      TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            );
            -- 刮削出版台账（第 18 期）。**一张表身兼三职**：
            --   ① 队列（status='pending' 即待办，天然持久化、重启可续）；
            --   ② 结果视图（副本路径 / 模式 / 已写字段 / 失败原因）；
            --   ③ 待确认待办（status='removed' 等，用户「空闲时确认」的依据 ——
            --      若只写 activity_log 文件，重启后待办就丢了）。
            -- ⚠️ status 状态机**只许降级**：检测逻辑只能把 ok 降成 removed/orphan；
            --    回到 ok 必须由用户显式动作（重新生成副本 / 手动整理）触发。
            CREATE TABLE IF NOT EXISTS scrape_items (
                -- 库维度化的 book_id（库$哈希），与 meta_override 等同一套 id
                book_id      TEXT PRIMARY KEY,
                library_id   TEXT NOT NULL DEFAULT '',
                source_rel   TEXT NOT NULL DEFAULT '',   -- 源相对库根的路径
                status       TEXT NOT NULL DEFAULT 'pending',
                link_rel     TEXT NOT NULL DEFAULT '',   -- 副本相对成品目录的路径
                link_mode    TEXT NOT NULL DEFAULT '',   -- hardlink / copy
                -- 写入后是否仍与源共享数据块（内嵌过元数据 = 0，占额外空间）
                link_shared  INTEGER NOT NULL DEFAULT 0,
                src_size     INTEGER NOT NULL DEFAULT 0,
                src_mtime    REAL NOT NULL DEFAULT 0,
                embedded     TEXT NOT NULL DEFAULT '',   -- 已写进副本的字段（逗号分隔）
                has_cover    INTEGER NOT NULL DEFAULT 0,
                error        TEXT NOT NULL DEFAULT '',   -- 失败原因（供人工整理）
                attempts     INTEGER NOT NULL DEFAULT 0,
                -- 队列里这条待办是否要求**强制重新外呼抓取**（「重新刮削」按钮置 1，
                -- process 跑完清 0）。没有它就无法区分「入库自动刮」与「用户要重刮」，
                -- 只能靠「meta_online 为空」推断 —— 那会让重刮永远不生效。
                force_fetch  INTEGER NOT NULL DEFAULT 0,
                removed_at   REAL NOT NULL DEFAULT 0,    -- 副本被删（待确认）的时刻
                removed_path TEXT NOT NULL DEFAULT '',   -- 被删副本的路径（提示里给出）
                confirmed_at REAL NOT NULL DEFAULT 0,    -- 用户确认处置的时刻
                updated_at   REAL NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_scrape_status ON scrape_items(status);
            CREATE INDEX IF NOT EXISTS idx_scrape_library ON scrape_items(library_id);
            -- 回收站台账（第 81 期）：每次把文件/目录移入 CACHE_DIR/recycle 都记一行，
            -- 「回收站还原」据此把东西搬回**原路径**（历史无台账的行走「剥时间戳前缀 +
            -- 指定目录」的孤儿还原，见 core/recycle.py）。
            --
            -- ⚠️ **刻意不含 book_id**：它不是「某本书的数据」，而是「磁盘上某个被移走的
            -- 路径」的台账 —— 因此**不需要**进 remap 的四处清单（ORPHAN_TABLES /
            -- REMAP_TABLES / REMAP_PROBE_FILTER / REMAP_EXPLICIT_TABLES），
            -- 改名 / 换库都不会让它失效（它压根不认 book_id）。契约测试钉住这条。
            CREATE TABLE IF NOT EXISTS recycle_items (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                orig_path     TEXT NOT NULL DEFAULT '',   -- 被移走前的绝对路径（还原目标）
                recycled_name TEXT NOT NULL DEFAULT '',   -- 回收目录里的文件名（含时间戳前缀）
                why           TEXT NOT NULL DEFAULT '',   -- 移入原因（用户可见）
                size          INTEGER NOT NULL DEFAULT 0, -- 字节数（目录为整树和）
                created_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_recycle_name ON recycle_items(recycled_name);
            """
        )
        # progress 单独建，**不写进上面那段 executescript**：它的定义只有一份
        # （:data:`_PROGRESS_SQL`），重建表（第 63 期 4/6）要用同一份。也特意不用
        # f-string 插进去 —— 那个脚本里有 `{reading, finished}` 这样的注释，
        # f-string 会把大括号当成格式字段，报的是个与建表八竿子打不着的 NameError。
        c.execute(_PROGRESS_SQL)
        # 轻量迁移：ratings 表后来加了 review 列。CREATE TABLE IF NOT EXISTS
        # 不会改已有库的表结构，所以老库必须在这里补列，否则写入会报 no such column。
        cols = {r["name"] for r in c.execute("PRAGMA table_info(ratings)")}
        if "review" not in cols:
            c.execute("ALTER TABLE ratings ADD COLUMN review TEXT NOT NULL DEFAULT ''")
        # 第 54 期：progress 补「精确位置」列（EPUB CFI）。存量行回落 ''＝没有精确
        # 坐标，恢复侧回落「章 + 全书百分比」，与加列前行为一致；该列不含 book_id
        # 语义变化，progress 本就在 REMAP/ORPHAN 清单里，契约不受影响。
        pcols = {r["name"] for r in c.execute("PRAGMA table_info(progress)")}
        if pcols and "cfi" not in pcols:
            c.execute("ALTER TABLE progress ADD COLUMN cfi TEXT NOT NULL DEFAULT ''")
        # 第 63 期 4/6：唯一约束从 UNIQUE(book_id) 变成 UNIQUE(book_id, file_rel)。
        # ⚠️ 这一处**不能靠补列**：补出 file_rel 之后 UNIQUE(book_id) 还在原地，
        # 多文件的书写第二条进度就撞约束 —— 那正是本期要打破的那一条。补列会得到
        # 一个「看起来成功了、其实没生效」的假修复，所以只能重建表。
        # cfi 那一步必须排在它前面：重建要复制 cfi 列，老库可能还没有它。
        #
        # ⚠️ 第二个条件（progress_old 还在）**必须显式写**，不能指望第一个条件把它兜住：
        # 上一次重建死在中间时，`progress` 可能是「压根不存在」或「已经被建成新形状」，
        # 两种情况下 `"file_rel" not in pcols` 都是假 —— 自愈逻辑永远进不去，
        # 半成品原地不动。实测三种中间态（只剩 progress_old / 空壳新表 / 复制到一半）
        # 全都因为这个漏判而没被自愈。
        if (pcols and "file_rel" not in pcols) or _progress_cols(c, "progress_old"):
            _rebuild_progress(c)
        # 第 8 期：meta_override 后来加了 orig 列（编辑前原值），老库同样要补
        ocols = {r["name"] for r in c.execute("PRAGMA table_info(meta_override)")}
        if ocols and "orig" not in ocols:
            c.execute("ALTER TABLE meta_override ADD COLUMN orig TEXT NOT NULL DEFAULT ''")
        # 第 13 期：libraries 后来加了 settings 列（每库覆盖）。
        # CREATE TABLE IF NOT EXISTS 不会改已有表结构，老库不补列则读写会报 no such column。
        lcols = {r["name"] for r in c.execute("PRAGMA table_info(libraries)")}
        if lcols and "settings" not in lcols:
            c.execute("ALTER TABLE libraries ADD COLUMN settings TEXT NOT NULL DEFAULT ''")
        # 第 17 期 T2：libraries 又加了逐库扫描调度三列（watch / scan_interval / scan_cron）。
        # 老库不补列则 watcher 派生目标 / update_library 会报 no such column。
        if lcols and "watch" not in lcols:
            c.execute("ALTER TABLE libraries ADD COLUMN watch INTEGER NOT NULL DEFAULT 1")
        if lcols and "scan_interval" not in lcols:
            c.execute("ALTER TABLE libraries ADD COLUMN scan_interval INTEGER NOT NULL DEFAULT 0")
        if lcols and "scan_cron" not in lcols:
            c.execute("ALTER TABLE libraries ADD COLUMN scan_cron TEXT NOT NULL DEFAULT ''")
        # 第 18 期：libraries 加成品目录列（刮削出版落点）。
        # 与上面同理：老库不补列则 update_library / 刮削读取会报 no such column。
        if lcols and "publish_path" not in lcols:
            c.execute("ALTER TABLE libraries ADD COLUMN publish_path TEXT NOT NULL DEFAULT ''")
        # 第 40 期：libraries 加新库向导三列（图标 / 允许格式 / 排除图案）。
        # 与上面同理：老库不补列则 update_library / 建库向导读取会报 no such column。
        if lcols and "icon" not in lcols:
            c.execute("ALTER TABLE libraries ADD COLUMN icon TEXT NOT NULL DEFAULT ''")
        if lcols and "allowed_exts" not in lcols:
            c.execute("ALTER TABLE libraries ADD COLUMN allowed_exts TEXT NOT NULL DEFAULT ''")
        if lcols and "exclude" not in lcols:
            c.execute("ALTER TABLE libraries ADD COLUMN exclude TEXT NOT NULL DEFAULT ''")
        # 第 41 期：libraries 重构为「多文件夹就地引用」，取代单一 root_path。
        #   - 新增 source_dirs（JSON 数组，存每个文件夹的绝对路径）；
        #   - 删除 mode / root_path / storage_path / source_subdir。
        # 老库迁移：先把 inplace/import 库的 root_path（import 回退 storage_path）
        # 回填进 source_dirs（不丢库），再删旧列。幂等可重跑。
        lcols41 = {r["name"] for r in c.execute("PRAGMA table_info(libraries)")}
        if "source_dirs" not in lcols41:
            c.execute("ALTER TABLE libraries ADD COLUMN source_dirs TEXT NOT NULL DEFAULT ''")
        # 回填（与旧列是否存在无关，幂等：source_dirs 已填过的不动）
        if "root_path" in lcols41:
            rows = c.execute(
                "SELECT id, root_path, storage_path FROM libraries "
                "WHERE (source_dirs IS NULL OR source_dirs = '') "
                "AND (root_path IS NOT NULL AND root_path <> '')"
            ).fetchall()
            for r in rows:
                rp = r["root_path"] or r["storage_path"] or ""
                if rp:
                    c.execute("UPDATE libraries SET source_dirs=? WHERE id=?",
                              (json.dumps([str(rp)], ensure_ascii=False), r["id"]))
        # 删旧列（SQLite 3.35+ 支持 DROP COLUMN；老版本静默跳过，不影响运行）。
        for _col in ("mode", "root_path", "storage_path", "source_subdir"):
            if _col in lcols41:
                try:
                    c.execute(f"ALTER TABLE libraries DROP COLUMN {_col}")
                except Exception:
                    pass
        # 第 25 期：users 表补账号资料列（展示名 / 时区 / 头像相对文件名）。
        # 老库不补列则读写会报 no such column（与上方同理）。
        ucols = {r["name"] for r in c.execute("PRAGMA table_info(users)")}
        if "display_name" not in ucols:
            c.execute("ALTER TABLE users ADD COLUMN display_name TEXT NOT NULL DEFAULT ''")
        if "timezone" not in ucols:
            c.execute("ALTER TABLE users ADD COLUMN timezone TEXT NOT NULL DEFAULT ''")
        if "avatar_path" not in ucols:
            c.execute("ALTER TABLE users ADD COLUMN avatar_path TEXT NOT NULL DEFAULT ''")
        # 第 27 期：annotations 补「来源 / 软删除」两列，删除由硬删改为移入垃圾桶。
        # 老库不补列则读写会报 no such column；两列都有 NOT NULL DEFAULT，
        # 存量行照旧可读（来源回填 web —— 批注此前只可能由 Web 阅读器创建；
        # deleted_at=0 即「活跃」，语义与本次改动前完全一致）。
        acols = {r["name"] for r in c.execute("PRAGMA table_info(annotations)")}
        if acols and "origin" not in acols:
            c.execute("ALTER TABLE annotations ADD COLUMN origin TEXT NOT NULL DEFAULT 'web'")
        if acols and "deleted_at" not in acols:
            c.execute("ALTER TABLE annotations ADD COLUMN deleted_at REAL NOT NULL DEFAULT 0")
        # 第 44 期：annotations 补「样式类型」一列（高亮/下划线/删除线/纯笔记）。存量行回落
        # 'highlight'，读时无需额外补偿；该列不加 book_id，不影响 remap 契约。
        if acols and "style" not in acols:
            c.execute("ALTER TABLE annotations ADD COLUMN style TEXT NOT NULL DEFAULT 'highlight'")
        # 第 63 期（6/6）：annotations 补位置锚三列。存量行全部回落 ''/-1/-1 ——
        # 它们的**离线锚补不回来**（当时根本没有记），界面如实显示「按文本定位」，
        # 高亮继续走既有的「搜索首个匹配」回落。不假装知道、也不回填一个猜的偏移。
        #
        # ⚠️ **刻意不加唯一索引**。看起来 `(book_id, origin, anchor)` 很该唯一（导入去重要用），
        # 但那会精确复刻 bookmarks 那个坑（见 :func:`_remap_bookmarks`）：
        # remap 的「目标已有数据」探测**带着 `deleted_at=0`**（:data:`REMAP_PROBE_FILTER`），
        # 所以目标书上的**墓碑对它不可见** —— 整体 UPDATE 撞上唯一约束 → 异常被外层
        # `except` 吞成「搬了 0 行」→ **整本书的批注静默丢失**。批注比书签更糟：
        # 书签有墓碑可恢复，批注丢了就是丢了。
        # 去重改在 :func:`import_annotations` 里用 SELECT 做（应用层 upsert），
        # 代价是要自己保证幂等，收益是 remap 这条路径**不会**多出一个静默失效点。
        if acols and "anchor" not in acols:
            c.execute("ALTER TABLE annotations ADD COLUMN anchor TEXT NOT NULL DEFAULT ''")
        if acols and "start_off" not in acols:
            c.execute("ALTER TABLE annotations ADD COLUMN start_off INTEGER NOT NULL DEFAULT -1")
        if acols and "end_off" not in acols:
            c.execute("ALTER TABLE annotations ADD COLUMN end_off INTEGER NOT NULL DEFAULT -1")
        # 章节标题列（同上）。存量行回落 '' —— 「没有标题」正是它们的真实状态：
        # 本项目自己写的批注只知道序号，界面照旧显示「第 N 章」。
        if acols and "chapter_title" not in acols:
            c.execute("ALTER TABLE annotations ADD COLUMN chapter_title TEXT NOT NULL DEFAULT ''")
        # 第 47 期：collections 补 updated_at（最后修改时间），供收藏夹总览展示。
        # 存量行回填为 created_at（首次创建即最后一次改动），与加列前语义一致。
        ccols = {r["name"] for r in c.execute("PRAGMA table_info(collections)")}
        if "updated_at" not in ccols:
            c.execute("ALTER TABLE collections ADD COLUMN updated_at REAL NOT NULL DEFAULT 0")
            c.execute("UPDATE collections SET updated_at = created_at WHERE updated_at = 0")
        # 第 32 期：authors 补「排序名」两列（在线值 / 本地覆盖分列，与 bio 同构）。
        # 老库不补列则作者排序与覆盖读写会报 no such column。两列都有 NOT NULL DEFAULT ''，
        # 存量行照旧可读 —— 空串即「没有排序名」，排序回退到 name，与加列前完全一致。
        aucols = {r["name"] for r in c.execute("PRAGMA table_info(authors)")}
        if aucols and "sort_name" not in aucols:
            c.execute("ALTER TABLE authors ADD COLUMN sort_name TEXT NOT NULL DEFAULT ''")
        if aucols and "sort_name_local" not in aucols:
            c.execute("ALTER TABLE authors ADD COLUMN sort_name_local TEXT NOT NULL DEFAULT ''")
        # 第 63 期：reading_sessions 补「会话身份 + 进度锚点 + 来源」七列。
        #
        # 起因：阅读器每 30 秒上报一次心跳，**每次都是插新行** —— 读两小时就是 240 行，
        # 报表里的「会话数」于是变成「心跳数」。改成「一段连续阅读 = 一行」得先给心跳
        # 一个身份：前端开段时生成一个 uid，之后每次心跳带着它 upsert
        #（见 :func:`upsert_session`）。30 秒这个间隔**不动** —— 它是「浏览器崩了最多
        # 丢多少」的上界；改成「离开时写一行」会把上界变成「整段」。
        #
        # 数值列一律用 **-1 作「未知」哨兵**，不用 0：0% 是「读了但没动」这个**不同**的
        # 结论，混用会让「本次读了多久」那一列把历史会话显示成「原地踏步」。
        # 存量行全部回落 -1 / ''，界面如实显示「—」—— 历史会话的进度锚点补不回来，
        # 不假装知道（与「没有数据源就返回恒 0 是假数据」同一条纪律）。
        scols = {r["name"] for r in c.execute("PRAGMA table_info(reading_sessions)")}
        if scols and "session_uid" not in scols:
            c.execute("ALTER TABLE reading_sessions ADD COLUMN session_uid TEXT NOT NULL DEFAULT ''")
            # 一次性回填：老行的 uid 取 'legacy-'||id，**必须唯一**（下面要建唯一索引）。
            # ⚠️ PG 里 id 是 BIGINT，`text || bigint` 直接报错，非加 CAST 不可 ——
            # sqlcompat 只做 `?`→`%s` 与类型名替换，不会替你补这个转换。
            # 只在本列**刚被加上**时跑，这一行就是幂等的全部保证
            #（与第 47 期 collections.updated_at 的回填同一种写法）。
            c.execute("UPDATE reading_sessions SET session_uid = 'legacy-' || CAST(id AS TEXT) "
                      "WHERE session_uid = ''")
            # 唯一索引让「同一段会话的心跳」能 upsert 到同一行而不是插 240 行。
            # ⚠️ 必须建在回填**之后**：PG 上对全为 '' 的列建唯一索引会直接失败，
            # 而这段跑在启动路径上 —— 失败＝起不来。
            # 外层 try 兜住「老库上次中断留下半成品」：宁可少一条索引也不能让 init() 抛
            #（与上面 DROP COLUMN 同一种「尽力而为」处理）。
            try:
                c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_session_uid "
                          "ON reading_sessions(book_id, session_uid)")
            except Exception:
                pass
        if scols and "start_locator" not in scols:
            c.execute("ALTER TABLE reading_sessions ADD COLUMN start_locator INTEGER NOT NULL DEFAULT -1")
        if scols and "end_locator" not in scols:
            c.execute("ALTER TABLE reading_sessions ADD COLUMN end_locator INTEGER NOT NULL DEFAULT -1")
        if scols and "start_percent" not in scols:
            c.execute("ALTER TABLE reading_sessions ADD COLUMN start_percent REAL NOT NULL DEFAULT -1")
        if scols and "end_percent" not in scols:
            c.execute("ALTER TABLE reading_sessions ADD COLUMN end_percent REAL NOT NULL DEFAULT -1")
        if scols and "file_rel" not in scols:
            c.execute("ALTER TABLE reading_sessions ADD COLUMN file_rel TEXT NOT NULL DEFAULT ''")
        if scols and "source" not in scols:
            # 来源（web / audio / koreader …）。存量行回落**空串 = 未知**，不猜 'web'：
            # 改造前有声书播放器与网页阅读器走的是同一个上报接口，事后分不出来是哪一边。
            # 给历史数据贴一个可能不准的标签，比承认不知道更糟。
            c.execute("ALTER TABLE reading_sessions ADD COLUMN source TEXT NOT NULL DEFAULT ''")
        # 第 62 期：**一次性数据搬迁必须排在建账号之前**（这一行位置是有讲究的）。
        # 老库里的 `users` 行带着用户真正在用的口令散列；`_seed_user` 只在
        # 「用户名不存在」时才按 AUTH_USER/AUTH_PIN 建号。顺序反过来的话，
        # 空 PG 上会先冒出 `admin/changeme` 这个壳，随后搬迁的 `users` 行撞上
        # UNIQUE(username) 被 DO NOTHING 丢掉 —— 用户升级完发现口令被**静默重置成
        # changeme**，且没有任何报错。搬在前面，`_seed_user` 自然认账、什么都不做。
        #
        # 只在 PG 后端且没搬过时生效；非 PG / 测试（NOVELFORGE_PG_RESET）/ 老库
        # 不存在这三条路径都直接返回 None，SQLite 部署的行为与第 61 期逐字节一致。
        from . import pgmigrate
        pgmigrate.auto_migrate()
        _seed_user(c)
        c.commit()
    # 第 62 期：书目索引表（``core/catalog``）随建库一起建。
    # ⚠️ 挂在这里而不是 server 启动处，是因为**测试也走 db.init()**（用例级隔离：
    # `db.close()` + `db.init()` 换一套空库），挂在启动处会让全部用例的索引表缺失。
    # 延迟导入避免 `db ↔ catalog` 的模块级循环（catalog 模块级要用本模块的连接）。
    # 建表失败**不吞**：索引读不出来等于整个书架不可用，静默降级只会让问题
    # 在几千行之后以一个「no such table」的面目出现。
    from . import catalog
    catalog.ensure_schema()


def _progress_cols(c, table: str) -> set:
    """某张表的列名集合；表不存在就是空集（``PRAGMA table_info`` 的语义）。"""
    return {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}


def _rebuild_progress(c) -> None:
    """把 ``progress`` 重建成 ``UNIQUE(book_id, file_rel)``（第 63 期 4/6）。

    唯一约束写在 ``CREATE TABLE`` 里，而 SQLite 没有 ``ALTER … DROP CONSTRAINT``，
    所以改约束只能重建：改名 → 按 :data:`_PROGRESS_SQL` 建新表 → 复制 → 删旧表。

    ⚠️ **复制时不带 ``id``**，这是刻意的：让两个后端各自重新分配主键。带上 id 就会
    在 PG 上撞上「``GENERATED BY DEFAULT`` 对显式插入不推序列」那个坑
    （第 62 期补，见 ``pgmigrate._reset_sequences``）—— 新表刚建、序列还是 1，
    复制完 N 行之后第一次写入必撞主键。不复制就没有这个问题；而 ``progress.id``
    是个纯代理键，没有任何外键指向它，重编号不会破坏任何引用。

    半成品自愈不是防御性编程而是**必需**：SQLite 的 DDL 是**逐句自动提交**
    的（Python ``sqlite3`` 的老事务模型：非 DML 语句前先把挂起的那笔提交掉；
    ``pg._settle`` 第 2 条刻意在 PG 上照搬了同一行为），所以重建**不在一笔事务里**，
    进程随时可能死在中间。而死在中间的样子是最坏的一种：``progress`` 不在，
    下一次 ``init()`` 的补列块看到空列集就整段跳过 —— 数据还在 ``progress_old`` 里，
    但**没有任何东西知道**，用户的阅读进度就此永久隐身、且不报任何错。

    下面的分支按「看到什么就怎么办」排开，判据只有两个：**源表还在不在**、
    **源表的每一行在新表里有没有着落**。判决一律是「留数据」：缺的行补过去，
    绝不为了重来一次而丢掉任何一张表里已有的行；只有确认源表每一行都已在新表里
    时，才允许删掉源表；判断不了的组合（两张表并存且当前表还是旧形状）
    **一行不动、直接抛**，把决定权交给操作者。
    """
    cur = _progress_cols(c, "progress")
    old = _progress_cols(c, "progress_old")
    if not cur and not old:
        return                       # 全新库：建表那一步已经给了新形状
    if old and cur and "file_rel" not in cur:
        # 「旧形状的 progress」与「progress_old」并存 —— 本函数**造不出**这个状态
        #（顺序是先改名，所以中间态必然没有 progress）。两张表都可能装着数据，
        # 此时**一行都不动**：宁可少搬，不可错搬。
        #
        # 但这里**必须抛**，不能安静返回。安静返回的样子是：表没被重建，服务照常起来，
        # 然后**每一次读写进度都 500**（``column "file_rel" does not exist``）——
        # 现场离根因隔着好几层，而日志里没有任何一行说「迁移没跑」。这跟书签那条
        # 血泪教训是同一个形状的坑（见 docs/bookorbit/bookorbit-capability-gap.md 的 bookmarks 段）：
        # 坏在**静默**上。抛出去则 ``db.init()`` 直接把服务挡在启动之前，
        # 消息里点名两张表，操作者照着决定留哪张即可 —— 数据一行没动，仍可完整恢复。
        raise RuntimeError(
            "progress 表重建遇到无法判断的状态：progress 是旧形状（无 file_rel），"
            "且 progress_old 同时存在。两张表都可能装着数据，无法判断哪张才是权威，"
            "因此一行未动。请分别查看两张表的行数，保留其中一张（改名回 progress，"
            "另一张改名留作备份）后重启。"
        )
    if old and cur and "file_rel" in cur:
        # 上一轮已经建过新表。判据必须是**内容**而不是「新表在不在」：只看在不在的话，
        # 「建了新表、还没复制」会被当成「已经跑完」，然后把源表删掉 —— 恰好把唯一
        # 一份数据删没，而且一声不吭。
        #
        # 判据也**不是比行数**（``COUNT(新) >= COUNT(旧)``）：行数追平证明不了「源表每一行
        # 都复制过来了」—— 复制到一半时程序又往新表里写了两本书，行数就追平了，源表里
        # 那两行没搬过来的进度会被当成「已经搬完」删掉。问的既然是「源表的每一行在新表里
        # 有没有着落」，就直接这么问。老形状没有 file_rel 列，复制时一律填 ''，
        # 所以对应关系按 ``(book_id, '')`` 找；两列都是 NOT NULL，没有 NULL 比较的歧义。
        missing = int(c.execute(
            "SELECT COUNT(*) AS n FROM progress_old o WHERE NOT EXISTS ("
            "  SELECT 1 FROM progress p WHERE p.book_id = o.book_id AND p.file_rel = '')"
        ).fetchone()["n"])
        if missing:
            # 半途（或压根没开始复制）：把源表里缺的那些行**补进新表**，而不是把新表
            # 丢掉重来。重来会连带丢掉这期间写进新表的行 —— 那些是别人的进度，
            # 跟这次重建毫无关系，没理由陪葬。补齐之后新表就是两张表的并集。
            #
            # 只在源表那一行在新表里**没有着落**时才插，所以不会撞唯一约束；
            # 同理，新表里已有的那行一定更新（是后写的），保留它、不被源表盖回去。
            # 老形状没有 file_rel 列，补进来的行一律填 ''（= 书级那一行）。
            c.execute(
                "INSERT INTO progress(book_id, file_rel, locator, percent, cfi, updated_at) "
                "SELECT o.book_id, '', o.locator, o.percent, o.cfi, o.updated_at "
                "FROM progress_old o WHERE NOT EXISTS ("
                "  SELECT 1 FROM progress p WHERE p.book_id = o.book_id AND p.file_rel = '')"
            )
        c.execute("DROP TABLE progress_old")
        return
    if old:
        # 只剩源表（新表压根没建成）——改名回来，交给下面那条正常路径
        c.execute("ALTER TABLE progress_old RENAME TO progress")
    # 正常路径：progress 是待重建的旧表
    c.execute("ALTER TABLE progress RENAME TO progress_old")
    c.execute(_PROGRESS_SQL.replace("IF NOT EXISTS ", "", 1))
    c.execute(
        "INSERT INTO progress(book_id, file_rel, locator, percent, cfi, updated_at) "
        "SELECT book_id, '', locator, percent, cfi, updated_at FROM progress_old"
    )
    c.execute("DROP TABLE progress_old")


def _seed_user(c):
    """仅在账号**不存在**时按环境变量创建（AUTH_USER / AUTH_PIN）。

    已存在的账号不覆盖 —— 密码改由「设置 → 账户」在应用内修改，
    否则每次重启都会被 AUTH_PIN 还原。
    """
    import os

    user = os.getenv("AUTH_USER", "admin")
    row = c.execute("SELECT id FROM users WHERE username=?", (user,)).fetchone()
    if row:
        return
    pin = os.getenv("AUTH_PIN", "changeme")
    h = hashlib.sha256(f"{user}:{pin}".encode("utf-8")).hexdigest()
    c.execute(
        "INSERT INTO users(username, pin_hash, created_at) VALUES(?,?,?)",
        (user, h, time.time()),
    )


def set_pin(username: str, pin: str) -> None:
    """修改密码（哈希落库）。"""
    h = hashlib.sha256(f"{username}:{pin}".encode("utf-8")).hexdigest()
    c = _connect()
    with _lock:
        c.execute("UPDATE users SET pin_hash=? WHERE username=?", (h, username))
        c.commit()


# ---------------- 账号资料（第 25 期）----------------
# 单用户场景只有一行 users，以下读写一律命中该行，不做多用户区分。

def get_user_profile() -> dict:
    """返回唯一账号的资料（展示名 / 时区 / 头像相对文件名）。"""
    row = _connect().execute(
        "SELECT username, display_name, timezone, avatar_path FROM users LIMIT 1"
    ).fetchone()
    if not row:
        return {"username": "", "display_name": "", "timezone": "", "avatar_path": ""}
    return {
        "username": row["username"],
        "display_name": row["display_name"] or "",
        "timezone": row["timezone"] or "",
        "avatar_path": row["avatar_path"] or "",
    }


def update_user_profile(display_name: str, timezone: str) -> dict:
    """更新展示名与时区（均 strip；空串表示回退默认）。"""
    c = _connect()
    with _lock:
        c.execute(
            "UPDATE users SET display_name=?, timezone=? WHERE id=(SELECT id FROM users LIMIT 1)",
            (str(display_name or "").strip(), str(timezone or "").strip()),
        )
        c.commit()
    return get_user_profile()


def set_user_avatar(fn: str) -> None:
    """记录头像相对文件名（落在 CACHE_DIR/user/ 下）。空串 = 移除。"""
    c = _connect()
    with _lock:
        c.execute(
            "UPDATE users SET avatar_path=? WHERE id=(SELECT id FROM users LIMIT 1)",
            (str(fn or "").strip(),),
        )
        c.commit()


def clear_user_avatar() -> None:
    c = _connect()
    with _lock:
        c.execute(
            "UPDATE users SET avatar_path='' WHERE id=(SELECT id FROM users LIMIT 1)"
        )
        c.commit()


# ---------------- progress ----------------

def get_progress(book_id: str, file_rel: "str | None" = None):
    """读阅读进度；没有这一行时返回 ``None``。

    两个口径，由 ``file_rel`` 选（第 63 期 4/6）：

    - ``file_rel=None``（默认）= **这本书整体读到哪了**：取 ``updated_at`` 最新的
      那一行 —— 多文件的书里就是用户最后在看的那个文件。书架、统计、Komga、
      KOReader 互通都只认书级，走的都是这一条；
    - 给了 ``file_rel`` = **那个文件读到哪了**：阅读器恢复位置时用。
    """
    c = _connect()
    if file_rel is None:
        # `id DESC` 那个兜底不是多余的：同一毫秒写两行会打平（批量标记 / 整表搬迁
        # 就会那样），只按 updated_at 排序时「哪一行赢」取决于存储顺序 ——
        # 一个每次跑都可能不一样的答案。
        row = c.execute(
            "SELECT file_rel, locator, percent, cfi, updated_at FROM progress "
            "WHERE book_id=? ORDER BY updated_at DESC, id DESC LIMIT 1", (book_id,)
        ).fetchone()
    else:
        row = c.execute(
            "SELECT file_rel, locator, percent, cfi, updated_at FROM progress "
            "WHERE book_id=? AND file_rel=?", (book_id, str(file_rel))
        ).fetchone()
    # updated_at 是为 KOReader 互通加的：它用时间戳判断「服务端进度是否比本机新」
    # （见 server.ko_get_progress → core/koreader.from_nf）。前端只读 locator/percent，
    # 多一个字段没有任何影响。cfi 是第 54 期的精确位置（EPUB），空串 = 没有。
    # file_rel = 这一行读的是哪个文件（第 63 期 4/6），空串 =「这本书自己 / 不知道文件」。
    return ({"file_rel": row["file_rel"] or "", "locator": row["locator"],
             "percent": row["percent"], "cfi": row["cfi"] or "",
             "updated_at": row["updated_at"]} if row else None)


def set_progress(book_id: str, locator: int, percent: float, cfi: str = "",
                 file_rel: str = "") -> float:
    """写阅读进度；**返回写入的 ``updated_at``**（秒级 float）。

    ``file_rel`` 是这份进度属于**哪个文件**（第 63 期 4/6）：默认空串 =「这本书自己」，
    写入方不知道文件时就用它（KOReader 同步 / Komga / 标记已读完）—— 那些调用方
    **一个字都不用改**，行为与加这一列之前逐字节相同。知道文件的阅读器传自己的 rel，
    于是同一本书的 EPUB 与 PDF 各存各的读点，不再互相覆盖。

    ⚠️ 默认空串即「**清掉精确坐标**」：进度有多个写入来源（NF 阅读器 / KOReader
    同步 / Komga / 完成标记），只有 NF 阅读器算得出与 locator 配套的 CFI ——
    其它来源不传 cfi 时旧行必须清空，否则「章序号已变、CFI 还挂在旧章」的
    矛盾行会让恢复跳回错误位置。

    第 56 期起把时间戳返回给调用方：阅读器要拿它当「本机上次写入」的基准，
    轮询到比它更新的写入才提示「其他设备更新了进度」（见 ReaderView 的进度提示）。
    """
    now = time.time()
    c = _connect()
    with _lock:
        c.execute(
            """INSERT INTO progress(book_id, file_rel, locator, percent, cfi, updated_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(book_id, file_rel) DO UPDATE SET
                 locator=excluded.locator,
                 percent=excluded.percent,
                 cfi=excluded.cfi,
                 updated_at=excluded.updated_at""",
            (book_id, str(file_rel or ""), locator, percent, str(cfi or ""), now),
        )
        c.commit()
    return now


# ---------------- annotations ----------------

#: 批注的列清单（第 63 期 6/6 起含位置锚三列）。新增列请只改**这一处** ——
#: 三个 SELECT 原先各手抄了一遍清单，漏改一处的表现是**静默**的：列读不出来、
#: 前端回落成「按文本定位」，看起来只是「这条锚丢了」，没人会想到是查询少了一列。
_ANNO_BASE = ("quote, color, note, created_at, origin, style, "
              "anchor, start_off, end_off, chapter_title")
#: 单书用（与改动前一致的形状：不含 book_id / deleted_at）
_ANNO_COLS = "id, chapter, " + _ANNO_BASE
#: 总览 / 垃圾桶 / 按锚查找用：多要 ``book_id``（跨书）与 ``deleted_at``（分档视图与墓碑判定）
_ANNO_COLS_FULL = "id, book_id, chapter, " + _ANNO_BASE + ", deleted_at"


def list_annotations(book_id: str) -> list:
    c = _connect()
    rows = c.execute(
        "SELECT %s FROM annotations WHERE book_id=? AND deleted_at=0 "
        "ORDER BY chapter, created_at" % _ANNO_COLS,
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_annotation(book_id: str, chapter: int, quote: str, color: str, note: str,
                   origin: str = "web", style: str = "highlight",
                   anchor: str = "", start_off: int = -1, end_off: int = -1,
                   chapter_title: str = "") -> int:
    """新增一条批注。

    ``anchor`` / ``start_off`` / ``end_off`` / ``chapter_title`` 是第 63 期（6/6）的位置锚，
    四个都有默认值 ⇒ 既有调用点不必改。含义见建表处的注释：``anchor`` 是来源原生标识
    （**定位不了**，只用于去重与溯源），``start_off``/``end_off`` 是本应用章内字符偏移
    （**真能定位**），``chapter_title`` 只在 ``chapter < 0``（序号未知）时有意义。
    """
    c = _connect()
    with _lock:
        cur = c.execute(
            "INSERT INTO annotations(book_id, chapter, quote, color, note, created_at, origin, "
            "style, anchor, start_off, end_off, chapter_title) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (book_id, chapter, quote, color, note, time.time(), origin,
             style, anchor, int(start_off), int(end_off), str(chapter_title or "")),
        )
        c.commit()
        return cur.lastrowid or 0


def find_annotation_by_anchor(book_id: str, origin: str, anchor: str):
    """按 ``(book_id, origin, anchor)`` 找一条批注，**含垃圾桶里的**；没有返回 ``None``。

    **含墓碑是刻意的**：设备反复上传同一批批注，其中一条用户在本项目里删过 ——
    导入时若只看活跃行，会把它**复活**成一条新批注，用户删了又回来。
    调用方拿到墓碑应当**跳过**（不导入、不复活），返回完整行让调用方自己决定。

    ``anchor`` 为空串时一律返回 ``None``：空锚不构成身份，拿它去重会把
    「两条都没有锚的批注」判成同一条。
    """
    if not str(anchor or "").strip():
        return None
    c = _connect()
    row = c.execute(
        "SELECT %s FROM annotations WHERE book_id=? AND origin=? AND anchor=? LIMIT 1"
        % _ANNO_COLS_FULL,
        (book_id, origin, str(anchor)),
    ).fetchone()
    return dict(row) if row else None


def import_annotations(book_id: str, origin: str, items: list) -> dict:
    """**幂等**导入设备回传的一批批注。

    返回 ``{added, updated, unchanged, trashed, no_anchor, no_quote}`` —— 五个计数
    **分开记不合并**：各自对应一种「这次同步为什么没多出一条」，合并了出问题就看不出来。
    ``added + updated + unchanged + trashed + no_anchor + no_quote == len(items)``
    （有测试按这条式子钉住，它同时也是「没有哪一类被静默吞掉」的证明）。

    协议无关：调用方把设备报文解析成下面这几个键再进来，这里只管
    「同一批数据反复上传要收敛成同一份」。``items`` 里每一项认的键：
    ``anchor``（**必填**，无锚不收）、``quote``（必填）、``note`` / ``color`` / ``style``
    / ``created_at``（可选，各有默认）、``start_off`` / ``end_off``（可选，默认 -1）、
    ``chapter``（默认 **-1 = 序号未知**，不是 0）、``chapter_title``（序号未知时的落点）。

    ## 幂等靠什么

    靠 ``(book_id, origin, anchor)`` 这个**应用层**身份（不是唯一索引 —— 为什么不建索引
    见 :func:`_remap_bookmarks` 与建表处那条注释：会复刻书签那个「搬了 0 行」的静默丢失）。
    于是每一条进来先查一次 :func:`find_annotation_by_anchor`，查得到就按下面分派。

    ## 四种不需要写库/写库的情形，都是刻意的

    - **没有锚 → 不收**（``no_anchor``）。空锚不构成身份，收进来就等于「每次同步都多一份
      副本」，且**每一次都成功**，没有任何报错。宁可少收（用户可以手抄一条），
      不可重复堆积。
    - **命中墓碑 → 不收**（``trashed``）。用户在本项目里把这条删了，设备端并不知道；
      再导一次它就回来了 —— 那是「删了又回来」，比第一次就没导入更让人恼火。
    - **命中活跃且内容一字不差 → 不写**（``unchanged``）。这是最常见的一种（设备每次
      传全量），走 UPDATE 会白写一遍并刷新行版本，还会让「最近修改」这类展示失真。
    - **命中活跃但内容变了 → 更新**（``updated``）。用户在设备上改过笔记。
      ⚠️ **只更新内容，不动 ``created_at``** —— 那是「这条高亮是什么时候划的」，
      是设备的事实；改成导入时刻会让「按月份」分组和历史时间线全部错位。
    """
    # 五个计数分开记，**不合并**：它们各自对应一种「这次同步为什么没多出一条」，
    # 合起来就只剩一个数字，出问题时看不出是没锚、是被删过、还是本来就一样。
    out = {"added": 0, "updated": 0, "unchanged": 0, "trashed": 0,
           "no_anchor": 0, "no_quote": 0}
    c = _connect()
    with _lock:
        for raw in items or []:
            it = raw if isinstance(raw, dict) else {}
            anchor = str(it.get("anchor") or "").strip()
            if not anchor:
                out["no_anchor"] += 1
                continue
            quote = str(it.get("quote") or "").strip()
            if not quote:
                # 没有引文的「批注」没有可显示的内容（纯笔记也带引文 —— 本项目
                # 把纯笔记建成 style='note'，不是 quote 为空）。跳过，不建空壳。
                out["no_quote"] += 1
                continue
            note = str(it.get("note") or "")
            color = str(it.get("color") or "yellow")
            style = str(it.get("style") or "highlight")
            # `chapter` 缺省 **-1**（序号未知），不是 0 —— 0 是「第一章」这个合法序号，
            # 兜成 0 会让界面把每条设备批注都渲染成「第 1 章」，而设备根本没这么说。
            # 设备只给得出标题，那个走 `chapter_title`（见建表处）。
            chapter = int(it.get("chapter", -1))
            title = str(it.get("chapter_title") or "")
            row = find_annotation_by_anchor(book_id, origin, anchor)
            if row is not None:
                if float(row.get("deleted_at") or 0) != 0:
                    out["trashed"] += 1
                    continue
                if (row.get("quote") == quote and row.get("note") == note
                        and row.get("color") == color and row.get("style") == style):
                    out["unchanged"] += 1
                    continue
                c.execute(
                    "UPDATE annotations SET quote=?, note=?, color=?, style=? WHERE id=?",
                    (quote, note, color, style, row["id"]),
                )
                out["updated"] += 1
                continue
            created = it.get("created_at")
            c.execute(
                "INSERT INTO annotations(book_id, chapter, quote, color, note, created_at, "
                "origin, style, anchor, start_off, end_off, chapter_title) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (book_id, chapter, quote, color, note,
                 float(created) if created else time.time(), origin, style,
                 anchor, int(it.get("start_off", -1)), int(it.get("end_off", -1)), title),
            )
            out["added"] += 1
        c.commit()
    return out


def delete_annotation(book_id: str, anno_id: int) -> int:
    """**软删除**：移入垃圾桶（写 ``deleted_at``），行仍留在表内可恢复。

    返回受影响行数；0 表示该条目不存在或本来就在垃圾桶里。
    彻底删除走 :func:`purge_annotation`。
    """
    c = _connect()
    with _lock:
        cur = c.execute(
            "UPDATE annotations SET deleted_at=? "
            "WHERE id=? AND book_id=? AND deleted_at=0",
            (time.time(), anno_id, book_id),
        )
        c.commit()
        return int(cur.rowcount or 0)


def restore_annotation(book_id: str, anno_id: int) -> int:
    """从垃圾桶恢复。返回受影响行数；0 表示条目不存在或本就不在垃圾桶里。"""
    c = _connect()
    with _lock:
        cur = c.execute(
            "UPDATE annotations SET deleted_at=0 "
            "WHERE id=? AND book_id=? AND deleted_at!=0",
            (anno_id, book_id),
        )
        c.commit()
        return int(cur.rowcount or 0)


def purge_annotation(book_id: str, anno_id: int) -> int:
    """**彻底删除**（真 DELETE），且**只允许删垃圾桶里的条目**。

    ``deleted_at != 0`` 这个条件是刻意的：活跃条目必须先进垃圾桶，
    避免误点一次就不可恢复。返回受影响行数。
    """
    c = _connect()
    with _lock:
        cur = c.execute(
            "DELETE FROM annotations WHERE id=? AND book_id=? AND deleted_at!=0",
            (anno_id, book_id),
        )
        c.commit()
        return int(cur.rowcount or 0)


def trashed_annotations(book_id: str | None = None) -> list:
    """垃圾桶里的批注（``deleted_at`` 倒序 = 最近丢弃的在前）。

    传 ``book_id`` 则只看某本书。``include_trashed`` 的总览查询也走这里。
    """
    c = _connect()
    sql = ("SELECT %s FROM annotations WHERE deleted_at!=0" % _ANNO_COLS_FULL)
    args: tuple = ()
    if book_id is not None:
        sql += " AND book_id=?"
        args = (book_id,)
    rows = c.execute(sql + " ORDER BY deleted_at DESC", args).fetchall()
    return [dict(r) for r in rows]


# ---------------- 书签（第 34 期）----------------
# 软删除语义照抄批注那一套（第 27 期）：删除 = 移入垃圾桶（写 deleted_at），
# 真删是独立出口 ``purge_bookmark``，且**只肯删垃圾桶里的条目**。
#
# 与批注的两处差异都是**书签本身的性质**，不是新机制：
#   1. **位置去重**：``UNIQUE(book_id, anchor)`` —— 同一个位置反复加书签只会有一条；
#   2. **tombstone 复活**：位置被删过（墓碑行还在），再加同位置是「复活那一行」，
#      于是它的 created_at 得以保留（用户看到的是「还是原来那个书签」）。
#
# **并发冲突合并**用一个版本戳做乐观并发：客户端回传它看到的那一版 ``updated_at``，
# 服务端拿它跟库里现值比 —— 库里更新 ⇒ 服务端胜（``applied=False``，把服务端版本回给
# 客户端让它自己合并），否则落库。**比较只用服务端时钟**（客户端给的是「我基于哪一版」，
# 不是它自己的当前时间），否则两端时钟一歪就会误判。

_BOOKMARK_COLS = ("id, book_id, anchor, chapter, percent, label, "
                  "created_at, updated_at, deleted_at")


def _bookmark_out(row) -> dict:
    return {
        "id": int(row["id"]),
        "book_id": row["book_id"],
        "anchor": row["anchor"],
        "chapter": int(row["chapter"]),
        "percent": float(row["percent"]),
        "label": row["label"] or "",
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "deleted_at": float(row["deleted_at"]),
    }


def list_bookmarks(book_id: str) -> list:
    """某本书的**活跃**书签（按章序 / 位置升序；垃圾桶条目不在内）。"""
    rows = _connect().execute(
        "SELECT %s FROM bookmarks WHERE book_id=? AND deleted_at=0 "
        "ORDER BY chapter, percent, id" % _BOOKMARK_COLS,
        (str(book_id),),
    ).fetchall()
    return [_bookmark_out(r) for r in rows]


def trashed_bookmarks(book_id: str | None = None) -> list:
    """垃圾桶里的书签（``deleted_at`` 倒序 = 最近丢弃的在前）。"""
    c = _connect()
    sql = "SELECT %s FROM bookmarks WHERE deleted_at!=0" % _BOOKMARK_COLS
    args: tuple = ()
    if book_id is not None:
        sql += " AND book_id=?"
        args = (str(book_id),)
    rows = c.execute(sql + " ORDER BY deleted_at DESC", args).fetchall()
    return [_bookmark_out(r) for r in rows]


def bookmark_counts() -> dict:
    """每本书的**活跃**书签数（垃圾桶不计入）。"""
    rows = _connect().execute(
        "SELECT book_id, COUNT(*) AS n FROM bookmarks WHERE deleted_at=0 GROUP BY book_id"
    ).fetchall()
    return {r["book_id"]: r["n"] for r in rows}


def _bookmark_apply(c, row, percent, chapter, label) -> dict:
    """把一次写入落到既有行上（活跃行更新 / 墓碑行复活），返回出参。"""
    now = time.time()
    c.execute(
        "UPDATE bookmarks SET deleted_at=0, percent=?, chapter=?, label=?, updated_at=? WHERE id=?",
        (float(percent), int(chapter), str(label or ""), now, int(row["id"])),
    )
    c.commit()
    out = _bookmark_out(row)
    out.update({"percent": float(percent), "chapter": int(chapter),
                "label": str(label or ""), "updated_at": now, "deleted_at": 0.0})
    return out


def save_bookmark(book_id: str, anchor: str, percent: float = 0.0, chapter: int = 0,
                  label: str = "", base_updated_at: float = 0.0) -> dict:
    """加书签 / 复活墓碑 / 合并冲突 —— 一个入口对应一条 ``UNIQUE(book_id, anchor)`` 行。

    返回 ``{ok, id, created, revived, applied, server}``：

    - ``created`` 新插入了一行；``revived`` 复活了同位置的墓碑行；
      两者皆 False ⇒ 同位置本来就有活跃书签（**不产生第二条**）；
    - ``applied=False`` ⇒ 并发冲突且**服务端更新**，库里未被改写，
      ``server`` 是服务端现值（客户端据此合并本地状态）。
      注意：此时若 ``server.deleted_at != 0``，说明那条书签在客户端快照之后被删了。
    """
    bid, pos = str(book_id), str(anchor or "").strip()
    if not pos:
        raise ValueError("anchor 不能为空")
    c = _connect()
    with _lock:
        row = c.execute(
            "SELECT %s FROM bookmarks WHERE book_id=? AND anchor=?" % _BOOKMARK_COLS, (bid, pos)
        ).fetchone()
        base = float(base_updated_at or 0.0)
        if row is None:
            now = time.time()
            cur = c.execute(
                "INSERT INTO bookmarks(book_id, anchor, chapter, percent, label, "
                "created_at, updated_at) VALUES(?,?,?,?,?,?,?)",
                (bid, pos, int(chapter), float(percent), str(label or ""), now, now),
            )
            c.commit()
            return {
                "ok": True, "id": int(cur.lastrowid or 0), "created": True,
                "revived": False, "applied": True,
                "server": {"id": int(cur.lastrowid or 0), "book_id": bid, "anchor": pos,
                           "chapter": int(chapter), "percent": float(percent),
                           "label": str(label or ""), "created_at": now,
                           "updated_at": now, "deleted_at": 0.0},
            }
        # 库里已有同位置的行：客户端带着旧版本回来 ⇒ 服务端胜，不覆盖
        if base and base < float(row["updated_at"]):
            return {"ok": True, "id": int(row["id"]), "created": False,
                    "revived": False, "applied": False, "server": _bookmark_out(row)}
        revived = float(row["deleted_at"]) != 0
        server = _bookmark_apply(c, row, percent, chapter, label)
        return {"ok": True, "id": int(row["id"]), "created": False,
                "revived": revived, "applied": True, "server": server}


def update_bookmark(book_id: str, bookmark_id: int, label=None, percent=None, chapter=None,
                    base_updated_at: float = 0.0) -> dict:
    """改书签的备注 / 位置（**只对活跃条目**）。并发口径同 :func:`save_bookmark`。"""
    bid = str(book_id)
    c = _connect()
    with _lock:
        row = c.execute(
            "SELECT %s FROM bookmarks WHERE id=? AND book_id=? AND deleted_at=0" % _BOOKMARK_COLS,
            (int(bookmark_id), bid),
        ).fetchone()
        if row is None:
            return {"ok": False, "found": False}
        base = float(base_updated_at or 0.0)
        if base and base < float(row["updated_at"]):
            return {"ok": True, "found": True, "applied": False, "server": _bookmark_out(row)}
        server = _bookmark_apply(
            c, row,
            row["percent"] if percent is None else percent,
            row["chapter"] if chapter is None else chapter,
            row["label"] if label is None else label,
        )
        return {"ok": True, "found": True, "applied": True, "server": server}


def delete_bookmark(book_id: str, bookmark_id: int) -> int:
    """**软删除**：移入垃圾桶。返回受影响行数；0 = 不存在或本就在垃圾桶里。"""
    c = _connect()
    with _lock:
        cur = c.execute(
            "UPDATE bookmarks SET deleted_at=?, updated_at=? "
            "WHERE id=? AND book_id=? AND deleted_at=0",
            (time.time(), time.time(), int(bookmark_id), str(book_id)),
        )
        c.commit()
        return int(cur.rowcount or 0)


def restore_bookmark(book_id: str, bookmark_id: int) -> int:
    """从垃圾桶恢复。返回受影响行数；0 = 不存在或本就不在垃圾桶里。"""
    c = _connect()
    with _lock:
        cur = c.execute(
            "UPDATE bookmarks SET deleted_at=0, updated_at=? "
            "WHERE id=? AND book_id=? AND deleted_at!=0",
            (time.time(), int(bookmark_id), str(book_id)),
        )
        c.commit()
        return int(cur.rowcount or 0)


def purge_bookmark(book_id: str, bookmark_id: int) -> int:
    """**彻底删除**（真 DELETE），且**只允许删垃圾桶里的条目**（与批注同一条纪律）。"""
    c = _connect()
    with _lock:
        cur = c.execute(
            "DELETE FROM bookmarks WHERE id=? AND book_id=? AND deleted_at!=0",
            (int(bookmark_id), str(book_id)),
        )
        c.commit()
        return int(cur.rowcount or 0)


# ---------------- 收藏夹 ----------------

def list_collections() -> list:
    c = _connect()
    rows = c.execute(
        """SELECT c.id, c.name, c.created_at, c.updated_at,
                  (SELECT COUNT(*) FROM collection_items i WHERE i.collection_id = c.id) AS count,
                  -- 第 62 期：原为 `ORDER BY i.rowid`（SQLite 的隐式插入序）。
                  -- 本表的 id 就是 `INTEGER PRIMARY KEY`，在 SQLite 里**与 rowid
                  -- 同值**，所以改成 i.id 两边语义完全一致；而 PG 根本没有 rowid，
                  -- 照搬会在整段 SQL 上抛 `column i.rowid does not exist`。
                  (SELECT book_id FROM collection_items i
                    WHERE i.collection_id = c.id ORDER BY i.id LIMIT 1) AS first_book_id
           FROM collections c ORDER BY c.created_at"""
    ).fetchall()
    return [dict(r) for r in rows]


def get_collection(cid: int):
    c = _connect()
    row = c.execute("SELECT id, name, created_at FROM collections WHERE id=?", (cid,)).fetchone()
    return dict(row) if row else None


def create_collection(name: str) -> int:
    c = _connect()
    with _lock:
        now = time.time()
        cur = c.execute(
            "INSERT INTO collections(name, created_at, updated_at) VALUES(?,?,?)",
            (name, now, now),
        )
        c.commit()
        return cur.lastrowid or 0


def update_collection(cid: int, name: str) -> bool:
    """重命名（第 16 期 Komga Collections 用）。重名由 ``collections.name`` 的 UNIQUE
    约束拦下并向上抛（调用方翻成 409），不做「先查后改」以免竞态。

    返回是否真的改到行（不存在的夹返回 ``False``）。
    """
    c = _connect()
    with _lock:
        cur = c.execute(
            "UPDATE collections SET name=?, updated_at=? WHERE id=?",
            (str(name).strip(), time.time(), int(cid)),
        )
        c.commit()
        return int(cur.rowcount or 0) > 0


def _touch_collection(cid: int) -> None:
    """成员变动后刷新收藏夹的 updated_at（最后修改时间）。"""
    c = _connect()
    with _lock:
        c.execute(
            "UPDATE collections SET updated_at=? WHERE id=?", (time.time(), int(cid))
        )
        c.commit()


def clear_collection(cid: int) -> int:
    """清空成员（保留夹本身；Komga 的 ``PUT /collections/{id}/series`` 是**整体替换**）。"""
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM collection_items WHERE collection_id=?", (int(cid),))
        c.commit()
        return int(cur.rowcount or 0)


def delete_collection(cid: int):
    c = _connect()
    with _lock:
        c.execute("DELETE FROM collection_items WHERE collection_id=?", (cid,))
        c.execute("DELETE FROM collections WHERE id=?", (cid,))
        c.commit()


def collection_map() -> dict:
    """一次取回「书 → 所属收藏夹 id 列表」：``{book_id: [cid, ...]}``。

    给书目列表批量附带归属用（第 34 期的实体浏览页要按「收藏」维度分组）。
    ⚠️ **必须批量**：逐本调 :func:`collections_of_book` 会在书目列表热路径上
    产生 N 次查询，而这份数据一条 SQL 就能拿全。
    """
    rows = _connect().execute(
        "SELECT book_id, collection_id FROM collection_items"
    ).fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(r["book_id"], []).append(int(r["collection_id"]))
    return out


def collection_book_ids(cid: int) -> list:
    c = _connect()
    rows = c.execute(
        "SELECT book_id FROM collection_items WHERE collection_id=? ORDER BY added_at DESC",
        (cid,),
    ).fetchall()
    return [r["book_id"] for r in rows]


def add_book_to_collection(cid: int, book_id: str):
    c = _connect()
    with _lock:
        cur = c.execute(
            "INSERT OR IGNORE INTO collection_items(collection_id, book_id, added_at) VALUES(?,?,?)",
            (cid, book_id, time.time()),
        )
        c.commit()
        # 只有真插入了新成员才刷新「最后修改」（已存在则 INSERT OR IGNORE 不动行）
        if cur.rowcount:
            _touch_collection(cid)


def remove_book_from_collection(cid: int, book_id: str):
    c = _connect()
    with _lock:
        c.execute(
            "DELETE FROM collection_items WHERE collection_id=? AND book_id=?", (cid, book_id)
        )
        _touch_collection(cid)


def collections_of_book(book_id: str) -> list:
    c = _connect()
    rows = c.execute(
        "SELECT collection_id FROM collection_items WHERE book_id=?", (book_id,)
    ).fetchall()
    return [r["collection_id"] for r in rows]


# ---------------- 统计辅助（供 core/stats.py 聚合）----------------

def all_progress() -> dict:
    c = _connect()
    rows = c.execute(
        "SELECT id, book_id, file_rel, locator, percent, cfi, updated_at FROM progress"
    ).fetchall()
    # 第 63 期 4/6：多文件的书在表里有多行，这里**必须按 updated_at 取最新的那一行**。
    # 原先写的是 `{r["book_id"]: dict(r) for r in rows}` —— 字典推导在同一个 key 上
    # **静默保留最后一行**，于是「哪一行赢」取决于 SQL 的返回顺序（没有 ORDER BY，
    # 即取决于物理存储顺序）。那不是「书级进度」，是「碰巧排在最后的那一行」：
    # 同一份数据在不同机器上能给出不同的书架百分比。三个下游（core/stats.py 的
    # 进度漏斗、/api/books 附带的 percent、CSV 导出）都只认书级，口径在这里定死。
    best: dict = {}
    for r in rows:
        prev = best.get(r["book_id"])
        # 打平时的次键用 **id**（= 后写的那行赢），和 get_progress 的
        # `ORDER BY updated_at DESC, id DESC` 是**同一条规则**。两处口径必须一致：
        # 书架上的百分比（走这里）与详情页「正在读哪个文件」（走那里）说的是同一件事，
        # 次键不同就会在打平时各说各话。次键本身是什么无所谓，**一致**才要紧。
        if prev is None or (r["updated_at"], r["id"]) > (prev["updated_at"], prev["id"]):
            best[r["book_id"]] = dict(r)
    # id 只是排序用的次键，不进返回值 —— 返回形状与加这一列之前一致，
    # 下游（stats / /api/books / CSV）拿到的还是原来那几个字段。
    for row in best.values():
        row.pop("id", None)
    return best


# ---------------- 语义向量（第 54 期，core/embed.py 的落库层）----------------
# 存的只是 float32 BLOB + model_tag；解码 / 过滤旧 tag / 余弦一律在 embed.py 做，
# db 层不懂向量语义（与封面 BLOB 存 bytes、解析归调用方同一个分界）。

def get_embeddings() -> dict:
    """全部语义向量：``{book_id: (bytes, model_tag)}``。空库 / 无行 ⇒ ``{}``。"""
    rows = _connect().execute(
        "SELECT book_id, vec, model_tag FROM book_embeddings"
    ).fetchall()
    return {r["book_id"]: (bytes(r["vec"]), r["model_tag"]) for r in rows}


def set_embeddings(items: dict) -> None:
    """批量写向量：``{book_id: (bytes, model_tag)}``。重算任务一次提交一批。

    upsert（``ON CONFLICT``）：同一本书重算 = 覆写，不靠先删后插 —— 少一次事务，
    也避免 recompute 中途失败把库留在「删了旧的、没写新的」的空档。
    """
    if not items:
        return
    now = time.time()
    c = _connect()
    with _lock:
        c.executemany(
            "INSERT INTO book_embeddings(book_id, vec, model_tag, updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(book_id) DO UPDATE SET "
            "vec=excluded.vec, model_tag=excluded.model_tag, updated_at=excluded.updated_at",
            [(str(bid), bytes(vec), str(tag), now) for bid, (vec, tag) in items.items()],
        )
        c.commit()


def annotation_counts() -> dict:
    """每本书的**活跃**批注数（垃圾桶不计入）。

    ⚠️ 这个数字有三处下游，删批注改软删除后它们必须一起正确：
    统计页的 ``reading.annotations``（core/stats.py）、书目列表的
    ``annotation_count``（server.py ``GET /api/books``，驱动「有批注」智能书架）、
    以及 CSV 导出的「批注数」列（server.py ``GET /api/books/export``）。
    所以这里的 ``deleted_at=0`` 不是可选项。
    """
    c = _connect()
    rows = c.execute(
        "SELECT book_id, COUNT(*) AS n FROM annotations WHERE deleted_at=0 GROUP BY book_id"
    ).fetchall()
    return {r["book_id"]: r["n"] for r in rows}


def all_annotations(include_trashed: bool = False) -> list:
    """全部批注（跨书），按创建时间倒序；供「批注总览」页使用。

    ``include_trashed=True`` 时把垃圾桶里的条目一并返回，由调用方按 ``deleted_at``
    自行区分（总览页的垃圾桶视图靠它）。**默认只返回活跃批注** —— 这是既有行为，
    无参调用的几处（图书详情「批注」tab、每日划线 widget）不该看到已丢弃的条目。
    """
    c = _connect()
    sql = "SELECT %s FROM annotations" % _ANNO_COLS_FULL
    if not include_trashed:
        sql += " WHERE deleted_at=0"
    rows = c.execute(sql + " ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def _week_index(ts: float) -> int:
    """时间戳 → **单调递增的周序号**（按 ISO 周的周一归桶）。

    用「周一那天的 ordinal // 7」而不是 ``year*53 + week``：后者在 52/53 周的
    年份交界处算出的差值是错的，而下面正是要按周序号做差求「连续无批注周数」。
    """
    dt = datetime.fromtimestamp(ts)
    monday = dt.date() - timedelta(days=dt.weekday())
    return monday.toordinal() // 7


def annotation_overview() -> dict:
    """批注总览的统计口径（计数只看**活跃**批注，垃圾桶单列）。

    - ``weeks``：有过批注的周数（同一周内多条只算一周）。
    - ``longest_quiet_weeks``：最长的一段「连续无批注」周数 —— 既看历史周之间的
      空档，也看最后一次批注到**本周**的空档（所以停笔越久这个数越大）。
    """
    c = _connect()
    active = int(c.execute(
        "SELECT COUNT(*) AS n FROM annotations WHERE deleted_at=0"
    ).fetchone()["n"])
    trashed = int(c.execute(
        "SELECT COUNT(*) AS n FROM annotations WHERE deleted_at!=0"
    ).fetchone()["n"])
    ts = [r["created_at"] for r in c.execute(
        "SELECT created_at FROM annotations WHERE deleted_at=0"
    ).fetchall()]
    if not ts:
        return {"active": active, "trashed": trashed, "weeks": 0, "longest_quiet_weeks": 0}
    idx = sorted({_week_index(t) for t in ts})
    gaps = [b - a - 1 for a, b in zip(idx, idx[1:])]
    # 最后一段空档算到「本周」为止：长期没批注应该如实反映出来
    gaps.append(_week_index(time.time()) - idx[-1])
    return {
        "active": active,
        "trashed": trashed,
        "weeks": len(idx),
        "longest_quiet_weeks": max(max(gaps), 0),
    }


# ---------------- 阅读时长（会话）----------------

#: 「未知」哨兵（第 63 期）。start/end 的 locator 与 percent 用它，**不用 0** ——
#: 0% 是「读了但没动」这个不同的结论。出到 JSON 时由 read 侧转成 ``None``。
SESSION_UNKNOWN = -1

#: 会话来源（第 63 期）。**空串 = 未知**，不是「其他」—— 改造前的存量行分不出
#: 阅读器与播放器（两者走同一个上报接口），事后猜一个值就是造假。接口层按这张表校验，
#: 新增来源要同时加进这里。
SESSION_SOURCES = ("web", "audio", "manual")


def add_session(
    book_id: str,
    seconds: float,
    started_at=None,
    ended_at=None,
    *,
    session_uid: str = "",
    start_locator: int = SESSION_UNKNOWN,
    end_locator: int = SESSION_UNKNOWN,
    start_percent: float = SESSION_UNKNOWN,
    end_percent: float = SESSION_UNKNOWN,
    file_rel: str = "",
    source: str = "",
) -> None:
    """记录一次阅读会话（阅读器前台计时后上报）。

    **前四个位置参数一字不改**（既有调用点全部零改动），新参数一律关键字传入。

    ``session_uid`` 缺省时自动生成 ⇒ 每次调用都是一行新行，与加这些列之前**逐字节
    一致**。要「同一段会话的心跳更新同一行」请用 :func:`upsert_session` —— 两者分开
    而不是合成一个带开关的函数：调用方要表达的是「这是一次独立上报」还是「这是某一段
    的又一次心跳」，那是两件事。
    """
    now = time.time()
    started = float(started_at) if started_at else now - float(seconds)
    ended = float(ended_at) if ended_at else now
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO reading_sessions"
            "(book_id, seconds, started_at, ended_at, session_uid, "
            " start_locator, end_locator, start_percent, end_percent, file_rel, source) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                book_id, float(seconds), started, ended,
                session_uid or uuid.uuid4().hex,
                int(start_locator), int(end_locator),
                float(start_percent), float(end_percent),
                file_rel, source,
            ),
        )
        c.commit()


def upsert_session(
    book_id: str,
    session_uid: str,
    seconds: float,
    started_at=None,
    ended_at=None,
    *,
    start_locator: int = SESSION_UNKNOWN,
    end_locator: int = SESSION_UNKNOWN,
    start_percent: float = SESSION_UNKNOWN,
    end_percent: float = SESSION_UNKNOWN,
    file_rel: str = "",
    source: str = "",
) -> None:
    """**在线会话**：同一段会话的每次心跳更新同一行，而不是插新行。

    这是「一段连续阅读 = 一行」的实现。30 秒心跳照旧（浏览器崩了最多丢 30 秒），
    但不再每 30 秒留一行 —— 读两小时从 240 行变成 1 行。

    ``started_at`` 缺省按 ``now - seconds`` 反推（与 :func:`add_session` 同一算法）：
    心跳报上来的 ``seconds`` 是**这一段累计**，故反推出来就是会话起点，且只在首次心跳
    （真正 INSERT 的那一次，``seconds`` 还很小）被写进去 —— 后续心跳走 UPDATE，
    ``started_at`` 根本不在 SET 子句里，反推值再偏也落不了库。

    ``ON CONFLICT(book_id, session_uid)`` 是**具名冲突目标**（不是 INSERT OR REPLACE）：
    sqlcompat 明确拒绝机械翻译后者，而前者在 set_progress / set_embedding 里已经用了
    七处、PG 路径实测可用。冲突目标依赖 :func:`init` 补列区建的那个唯一索引。

    ⚠️ **``start_*`` 不进 SET 子句**（``file_rel`` / ``source`` 同理）：它们只在开段那
    一次被写进去，之后每次心跳只有终点信息。放进 SET 会让心跳把起点一遍遍覆盖成当前
    位置 —— 而 ``start_percent`` 正是「本次读了多少」的被减数，丢了它整列就没意义了。
    """
    now = time.time()
    started = float(started_at) if started_at else now - float(seconds)
    ended = float(ended_at) if ended_at else now
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO reading_sessions"
            "(book_id, seconds, started_at, ended_at, session_uid, "
            " start_locator, end_locator, start_percent, end_percent, file_rel, source) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(book_id, session_uid) DO UPDATE SET "
            "seconds=excluded.seconds, ended_at=excluded.ended_at, "
            "end_locator=excluded.end_locator, end_percent=excluded.end_percent",
            (
                book_id, float(seconds), started, ended, session_uid,
                int(start_locator), int(end_locator),
                float(start_percent), float(end_percent),
                file_rel, source,
            ),
        )
        c.commit()


def reading_totals(book_ids: set | None = None) -> dict:
    """阅读总时长与会话数。

    ``book_ids`` 为 **None = 不按书过滤**（与加库维度之前逐字节一致）；给了集合
    就只算这些书的会话 —— 阅读会话本身**没有库维度**，「某库的阅读时长」只能靠
    「这本书属于哪个库」判定，故由调用方（``core/stats.py``）传入该书库的书 id 集合。
    """
    c = _connect()
    rows = c.execute("SELECT book_id, seconds FROM reading_sessions").fetchall()
    picked = rows if book_ids is None else [r for r in rows if r["book_id"] in book_ids]
    return {
        "seconds": float(sum(float(r["seconds"]) for r in picked)),
        "sessions": len(picked),
    }


def daily_seconds(days: int = 28, book_ids: set | None = None) -> list:
    """近 days 天每日阅读秒数（索引 0 = days-1 天前，末尾 = 今天）。

    ``book_ids`` 语义同 ``reading_totals``（None = 全部）。
    """
    c = _connect()
    now = time.time()
    buckets = [0.0] * days
    for r in c.execute("SELECT book_id, seconds, ended_at FROM reading_sessions").fetchall():
        if book_ids is not None and r["book_id"] not in book_ids:
            continue
        d = int((now - r["ended_at"]) // 86400)
        if 0 <= d < days:
            buckets[days - 1 - d] += float(r["seconds"])
    return buckets


def _reading_zone():
    """阅读**时段图**的账号时区；``None`` = 回落服务器本地时。

    第 25 期起按账号时区归一：设置过 timezone 才转换，否则回落本地（保持历史口径，
    避免老库无时区时分布突变）；解析失败同样回落本地。

    ``hour_histogram``（几点读）与 ``weekday_histogram``（周几读）同属时段分布图，
    口径必须一致 —— 两处共用这一个判定，别再各写一份。
    """
    tz = (get_user_profile().get("timezone") or "").strip()
    if tz and ZoneInfo is not None:
        try:
            return ZoneInfo(tz)
        except Exception:
            return None
    return None


def hour_histogram(book_ids: set | None = None) -> list:
    """会话开始时段的 24 小时分布。

    时区口径见 ``_reading_zone``。

    ``book_ids`` 语义同 ``reading_totals``（None = 全部）。
    """
    c = _connect()
    zone = _reading_zone()
    buckets = [0] * 24
    for r in c.execute("SELECT book_id, started_at FROM reading_sessions").fetchall():
        if book_ids is not None and r["book_id"] not in book_ids:
            continue
        ts = r["started_at"]
        if zone is not None:
            hr = datetime.fromtimestamp(ts, tz=zone).hour
        else:
            hr = time.localtime(ts).tm_hour
        buckets[hr] += 1
    return buckets


def active_days(book_ids: set | None = None) -> list:
    """有阅读会话的日期（本地时区 YYYY-MM-DD，已排序）。

    ``book_ids`` 语义同 ``reading_totals``（None = 全部）。
    """
    c = _connect()
    rows = c.execute("SELECT book_id, ended_at FROM reading_sessions").fetchall()
    return sorted({
        time.strftime("%Y-%m-%d", time.localtime(r["ended_at"]))
        for r in rows
        if book_ids is None or r["book_id"] in book_ids
    })


def weekday_histogram(book_ids: set | None = None, days: int = 365) -> list:
    """最近 ``days`` 天按星期几聚合的阅读时长 + 各星期几在窗口内的出现天数。

    索引 **0 = 周日**（与前端 ``Date.getDay()`` 一致）。Python 的 ``weekday()`` 是
    周一 0、``tm_wday`` 是周一 0，故统一按 ``(weekday + 1) % 7`` 归一。

    时区口径同 ``hour_histogram``：两者都是时段分布图，见 ``_reading_zone``。

    每项带 ``days``（该星期几在这个窗口里出现过几天）—— 界面据此算**平均每日时长**
    （上游 Favorite Reading Days 的口径）。只给总时长会误导：窗口未必整除 7 天，
    直接比大小会造出「某个星期几总是最多」的假信号。

    ``book_ids`` 语义同 ``reading_totals``（None = 全部）。
    """
    c = _connect()
    zone = _reading_zone()
    now = time.time()
    floor = now - days * 86400
    seconds = [0.0] * 7
    events = [0] * 7
    for r in c.execute("SELECT book_id, seconds, started_at FROM reading_sessions").fetchall():
        if book_ids is not None and r["book_id"] not in book_ids:
            continue
        ts = r["started_at"]
        if ts < floor:
            continue
        if zone is not None:
            wd = (datetime.fromtimestamp(ts, tz=zone).weekday() + 1) % 7
        else:
            wd = (time.localtime(ts).tm_wday + 1) % 7
        seconds[wd] += float(r["seconds"])
        events[wd] += 1

    # 窗口内各星期几各有几天：按日期逐日走（窗口不整除 7 天时不能拿 days/7 糊弄）
    end = datetime.fromtimestamp(now, tz=zone) if zone is not None else datetime.fromtimestamp(now)
    cursor = end - timedelta(days=days - 1)
    occurrences = [0] * 7
    last = end.date()
    while cursor.date() <= last:
        occurrences[(cursor.weekday() + 1) % 7] += 1
        cursor += timedelta(days=1)

    return [
        {
            "weekday": i,
            "seconds": round(seconds[i], 1),
            "days": occurrences[i],
            # 会话次数：只给「数据够不够画」用 —— 图上画的是平均每日时长，
            # 但样本只有两三次会话时那个平均数没有意义，界面据此走「数据不足」。
            "events": events[i],
        }
        for i in range(7)
    ]


def completion_months(book_ids: set | None = None) -> list:
    """按月统计「读完」的本数：``[{"year": y, "month": m, "count": n}]``（年月升序）。

    数据源 = ``reading_status.finished_at`` —— ``set_status`` 进入 finished 时记时间、
    离开 finished 时清零（「读完」的日期只对「已读完」有意义），故只取 ``> 0`` 的行。

    **按本地日**折算年月（与阅读活动页的热力图口径一致）：这是「哪天读完的」，
    不是「哪个时段读的」，故不参与账号时区归一。

    ``book_ids`` 语义同 ``reading_totals``（None = 全部）。
    """
    c = _connect()
    months: dict = {}
    for r in c.execute(
        "SELECT book_id, finished_at FROM reading_status WHERE finished_at > 0"
    ).fetchall():
        if book_ids is not None and r["book_id"] not in book_ids:
            continue
        lt = time.localtime(r["finished_at"])
        key = (lt.tm_year, lt.tm_mon)
        months[key] = months.get(key, 0) + 1
    return [{"year": y, "month": m, "count": n} for (y, m), n in sorted(months.items())]


def recent_sessions(limit: int = 50) -> list:
    """最近的阅读会话（新 → 旧），Reading Log 的明细行。"""
    rows = _connect().execute(
        "SELECT book_id, seconds, started_at, ended_at FROM reading_sessions "
        "ORDER BY ended_at DESC LIMIT ?",
        (max(1, int(limit)),),
    ).fetchall()
    return [dict(r) for r in rows]


def session_by_book() -> dict:
    """按书聚合的阅读会话：``{book_id: {seconds, sessions, last_ended, avg_seconds}}``。

    ``avg_seconds`` 在同一句 SQL 里用 ``AVG(seconds)`` 算出（= seconds/sessions），
    不新增查询。
    """
    rows = _connect().execute(
        "SELECT book_id, SUM(seconds) AS seconds, COUNT(*) AS sessions, "
        "MAX(ended_at) AS last_ended, AVG(seconds) AS avg_seconds "
        "FROM reading_sessions GROUP BY book_id"
    ).fetchall()
    return {
        r["book_id"]: {
            "seconds": float(r["seconds"]),
            "sessions": int(r["sessions"]),
            "last_ended": float(r["last_ended"]),
            "avg_seconds": round(float(r["avg_seconds"]), 1),
        }
        for r in rows
    }


def longest_streak(days) -> dict | None:
    """有序日列表里**最长连续段**（纯函数，不碰库）：``{days, start, end}``；空输入 → ``None``。

    ``days`` 是 ``['YYYY-MM-DD', ...]``，即 :func:`active_days` 的输出（已排序去重）。

    ⚠️ 与 ``core/stats`` 里那段 streak 计数**不是一回事**，刻意不合并：那段算的是
    **当前**连续天数（成就用，断一天就归零）；这里要的是**历史最长**的那一段（阅读记录用，
    断了也不算丢）。同一本书上这两个数通常不相等 —— 所以调用方要拿同一份 ``days`` 喂进来，
    两个数才在同一套日集合上比较（见 :func:`book_reading_summary`）。

    平局取**更早**的那一段（先到先得）：与用户翻历史时的顺序一致，且结果稳定可测。
    """
    best = None
    cur_n = 0
    cur_start = ""
    prev = None
    for d in days:
        try:
            cur_day = datetime.strptime(str(d), "%Y-%m-%d").date()
        except ValueError:
            continue  # 脏数据跳过，不打断计数
        if prev is not None and (cur_day - prev).days == 1:
            cur_n += 1
        else:
            cur_n, cur_start = 1, str(d)
        # 严格 ``>``（不是 ``>=``）：平局保留**先到**的那一段更有意义，
        # 且遍历是升序的，先到的恒更早 ⇒ 结果与「取最早的那段最长连续」等价且稳定
        if best is None or cur_n > best["days"]:
            best = {"days": cur_n, "start": cur_start, "end": str(d)}
        prev = cur_day
    return best


def _session_row(r) -> dict:
    """会话行 → JSON 就绪的 dict（-1 哨兵在**这里**转 ``None``，出库即对外语义）。

    ``start_percent`` / ``end_percent`` / ``change`` 在第 63 期之前的行上是 ``None``：
    那些会话没记过进度锚点，补不回来。用 None 而不是 0 —— **0% 是「翻回开头了」，
    与「没记过」是两个结论**；前端据此显示「—」而不是「0%」。

    ``change`` 由服务端算：两端任一为 ``None`` 就整体 ``None``（「不知道」不是「0」）。
    """
    def num(v):
        return None if v is None or float(v) == SESSION_UNKNOWN else float(v)

    sp, ep = num(r["start_percent"]), num(r["end_percent"])
    return {
        "id": int(r["id"]),
        "seconds": float(r["seconds"]),
        "started_at": float(r["started_at"]),
        "ended_at": float(r["ended_at"]),
        "start_percent": sp,
        "end_percent": ep,
        "change": None if sp is None or ep is None else round(ep - sp, 2),
        "start_locator": num(r["start_locator"]),
        "end_locator": num(r["end_locator"]),
        "file_rel": r["file_rel"] or "",
        "source": r["source"] or "",
    }


def _book_day_rows(rows) -> list:
    """会话行按本地日归并（纯函数，可直接喂 dict 做单测）。

    返回 ``[{date, seconds, sessions, end_percent}]``，**按日期升序** —— 折线图 x 轴
    从左到右；而会话列表是降序（新 → 旧）。两者刻意不同：一个是时间轴，一个是流水。

    归日用 ``started_at``，与 :func:`reading_day_minutes`（热力图 / 全站日聚合）同一口径。
    入参须按 ``ended_at`` 升序：``end_percent`` 取当天**最后一次**已知的进度位置。

    ⚠️ :func:`active_days` 用的是 ``ended_at``，两者只在**跨零点的会话**上差一天。
    本函数不跟随那个口径，是为了让「图上这一天」与「热力图这一天」指的是同一天。
    """
    agg: dict = {}
    for r in rows:
        day = time.strftime("%Y-%m-%d", time.localtime(r["started_at"]))
        a = agg.setdefault(day, {"date": day, "seconds": 0.0, "sessions": 0, "end_percent": None})
        a["seconds"] += float(r["seconds"])
        a["sessions"] += 1
        if r["end_percent"] is not None:
            a["end_percent"] = r["end_percent"]
    return [agg[d] for d in sorted(agg)]


def book_reading_summary(book_id: str, limit: int = 200) -> dict | None:
    """单书的阅读汇总 + 会话列表（**一次扫描算完**）；一条会话都没有时返回 ``None``。

    ⚠️ 返回 None 而不是一个全 0 的对象。全 0 会让界面把「没记录」渲染成「读了 00:00」，
    那是假数据 —— 与 :func:`reading_totals` 不同：那个是**全站**口径，0 是真实的求和；
    单书场景下「0」与「没读过」必须分得开。

    与 :func:`session_log` 的分工：那个是**全站的时间窗**（days），这里的 ``sessions``
    是**单书的条数窗**（``limit``，新 → 旧）—— 一本书的会话数天然有限（几十到几百条），
    按时间窗切反而会让「半年前读完的一本书」显示成完全没读过。上限只防「一天几百条
    心跳」那种脏数据把响应撑爆，正常使用远到不了。

    出参（**与接口响应同形**，路由层直接展开，不再拆一遍）::

        {
          "reading":  {seconds, sessions, avg_seconds, active_days,
                       first_started, last_ended},
          "records":  {longest_session, best_day, busiest_day, longest_streak},
          "days":     [{date, seconds, sessions, end_percent}],   # 升序，见 _book_day_rows
          "sessions": [ ... ≤limit 条，新 → 旧，见 _session_row ],
        }

    ⚠️ 累计值收进 ``reading`` 子字典而不是摊在顶层，是**故意的**：「累计会话数」与
    「会话行列表」都叫 ``sessions``，摊平会撞成同一个键、后写的那个静默覆盖前面那个
    （本函数第一版就这么错过，被 ``test_历史会话没有进度快照时如实给_null`` 逮住）。

    ``records`` 里的每一个都可能是 ``None``（没有那个结论），界面按「不渲染」处理。
    ``longest_streak`` 用的是 :func:`active_days` 的日集合，**与全站连续天数同一口径** ——
    不然同一个用户会在两个页面上看到两套「连续」。
    """
    raw = _connect().execute(
        "SELECT id, seconds, started_at, ended_at, start_locator, end_locator, "
        "start_percent, end_percent, file_rel, source "
        "FROM reading_sessions WHERE book_id=? ORDER BY ended_at",
        (book_id,),
    ).fetchall()
    if not raw:
        return None

    rows = [_session_row(r) for r in raw]
    days = _book_day_rows(rows)
    total = sum(r["seconds"] for r in rows)
    longest = max(rows, key=lambda r: r["seconds"])
    return {
        "reading": {
            "seconds": total,
            "sessions": len(rows),
            "avg_seconds": round(total / len(rows), 1),
            "active_days": len(days),
            "first_started": rows[0]["started_at"],
            "last_ended": rows[-1]["ended_at"],
        },
        "records": {
            # 最长的一次：连日期一起给 —— 「3 小时」不带日期等于没说什么
            "longest_session": {
                "seconds": longest["seconds"],
                "ended_at": longest["ended_at"],
                "date": time.strftime("%Y-%m-%d", time.localtime(longest["ended_at"])),
            },
            "best_day": max(days, key=lambda d: d["seconds"]),
            "busiest_day": max(days, key=lambda d: d["sessions"]),
            "longest_streak": longest_streak(active_days({book_id})),
        },
        "days": days,
        # 升序取出、降序切片：尾部即最近 limit 条，反转就是「新 → 旧」，不再查一次库
        "sessions": list(reversed(rows[-max(1, int(limit)):])),
    }


def reading_day_minutes(book_ids: set | None = None) -> list:
    """按本地日聚合阅读分钟数（贡献热力图源）。

    返回 ``[(day 'YYYY-MM-DD', minutes, sessions), ...]``（已排序）。
    对齐上游 ``reading-session.ts`` 的 ``dailySummary{day,totalMinutes}[]``。
    ``book_ids`` 语义同 ``reading_totals``（None = 全部）。
    """
    c = _connect()
    rows = c.execute(
        "SELECT book_id, seconds, started_at FROM reading_sessions"
    ).fetchall()
    agg: dict = {}
    for r in rows:
        if book_ids is not None and r["book_id"] not in book_ids:
            continue
        day = time.strftime("%Y-%m-%d", time.localtime(r["started_at"]))
        a = agg.setdefault(day, [0.0, 0])
        a[0] += float(r["seconds"]) / 60.0
        a[1] += 1
    return [(d, round(m, 1), s) for d, (m, s) in sorted(agg.items())]


def session_feed(book_ids: set | None = None, limit: int = 500) -> list:
    """最近的阅读会话（新 → 旧），时间轴用。``book_ids`` 语义同 ``reading_totals``。"""
    c = _connect()
    rows = c.execute(
        "SELECT book_id, seconds, ended_at FROM reading_sessions ORDER BY ended_at DESC"
    ).fetchall()
    out = []
    for r in rows:
        if book_ids is not None and r["book_id"] not in book_ids:
            continue
        out.append({
            "book_id": r["book_id"],
            "seconds": float(r["seconds"]),
            "ended_at": float(r["ended_at"]),
        })
    return out[: max(1, int(limit))]


def session_log(days: int = 1825, book_ids: set | None = None) -> list:
    """按时间窗取会话**明细**（新 → 旧）：``{book_id, seconds, started_at, ended_at}``。

    与 ``session_feed`` 的差别有二，都是统计页第二批图表要的：

    - **带时间窗**（最近 ``days`` 天，按 ``started_at`` 起算）：题材阅读时长与会话形态
      各自只看 365 天，没有窗就得把全部历史读进内存再扔掉绝大部分。
    - **多给 ``started_at``**：会话形态要按**开始时刻**算小时与星期，只看 ``ended_at``
      会把跨零点的会话算到第二天（23:50 读的那一段会被记成 00:10）。

    ``book_ids`` 语义同 ``reading_totals``（None = 全部）：过滤在 Python 里做，
    与 ``reading_totals`` / ``session_feed`` 一致（``IN (?,?..)`` 的占位符拼接收在
    ``annotation_feed`` 一处，不在这里复用）。**先排序再过滤**不会错位 ——
    降序序列里滤掉若干条后，前 N 条仍是「这些书里最近的 N 条」。
    """
    since = time.time() - max(1, int(days)) * 86400
    rows = _connect().execute(
        "SELECT book_id, seconds, started_at, ended_at FROM reading_sessions "
        "WHERE started_at >= ? ORDER BY ended_at DESC",
        (since,),
    ).fetchall()
    return [
        {
            "book_id": r["book_id"],
            "seconds": float(r["seconds"]),
            "started_at": float(r["started_at"]),
            "ended_at": float(r["ended_at"]),
        }
        for r in rows
        if book_ids is None or r["book_id"] in book_ids
    ]


def annotation_feed(book_ids: set | None = None, limit: int = 500) -> list:
    """最近的批注（软删除除外），新 → 旧，时间轴用。

    ``book_ids`` 非空集合才过滤（空集合 = 该库无书，直接返回空，避免 ``IN ()`` 语法错）。
    """
    c = _connect()
    sql = "SELECT book_id, note, quote, created_at FROM annotations WHERE deleted_at=0 "
    if book_ids is not None:
        if not book_ids:
            return []
        sql += "AND book_id IN ({}) ".format(",".join("?" * len(book_ids)))
        args: tuple = tuple(book_ids)
    else:
        args = ()
    sql += "ORDER BY created_at DESC LIMIT ?"
    rows = c.execute(sql, args + (max(1, int(limit)),)).fetchall()
    return [dict(r) for r in rows]


# ---------------- 任务（下载 / 转换）----------------
# 任务原先只存在 server.py 的**进程内字典**里（重启即清空），前端还混了 6 条演示种子数据
# 并按固定步进「假推进」进度条。现在落 SQLite：
#   · 重启后仍可查历史任务
#   · progress 只记**真实里程碑**（0 = 已入队 / 50 = 已开始 / 100 = 已结束），
#     不再伪造中间百分比 —— 下载器不报细分进度，我们就不假装知道。
# ⚠️ 认领任务（claim）刻意不做：本后端是单进程 uvicorn，没有多 worker 竞争；
#    若将来上多 worker，需先加 SELECT ... WHERE status='queued' 的原子认领。

TASK_STATUSES = ("queued", "running", "done", "failed")


def task_create(task_id, type_, title, detail="", actor="", status="queued", progress=0.0) -> None:
    now = time.time()
    c = _connect()
    with _lock:
        c.execute(
            # 第 62 期：`INSERT OR REPLACE` → 显式 upsert（PG 没有 OR REPLACE 这种拼写，
            # 而 SQLite 3.24+ 就支持 ON CONFLICT … DO UPDATE，同一份 SQL 两边都跑）。
            # ⚠️ DO UPDATE 里**必须把表上所有列都写上**（含没进 INSERT 列表的
            # error/result/fname/notice）：SQLite 的 REPLACE 语义是「删旧插新」，
            # 没提到的列会回到默认值；只更新提到的那几列会**留着上一轮的 error/result**,
            # 那不是等价改写。PG 的 `excluded.<未列出的列>` 正好等于该列的默认值。
            "INSERT INTO tasks"
            "(id, type, title, detail, status, progress, actor, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "type=excluded.type, title=excluded.title, detail=excluded.detail, "
            "status=excluded.status, progress=excluded.progress, error=excluded.error, "
            "result=excluded.result, fname=excluded.fname, notice=excluded.notice, "
            "actor=excluded.actor, created_at=excluded.created_at, "
            "updated_at=excluded.updated_at",
            (str(task_id), str(type_), str(title), str(detail or ""), str(status),
             float(progress), str(actor or ""), now, now),
        )
        c.commit()


def task_update(task_id, **fields) -> None:
    """按字段更新任务。只接受白名单列名，避免把任意键拼进 SQL。"""
    allowed = {"status", "progress", "detail", "error", "result", "fname", "notice"}
    cols = {k: v for k, v in fields.items() if k in allowed}
    if not cols:
        return
    sets = ", ".join("%s=?" % k for k in cols)
    c = _connect()
    with _lock:
        c.execute(
            "UPDATE tasks SET %s, updated_at=? WHERE id=?" % sets,
            (*cols.values(), time.time(), str(task_id)),
        )
        c.commit()


def task_get(task_id) -> dict | None:
    r = _connect().execute("SELECT * FROM tasks WHERE id=?", (str(task_id),)).fetchone()
    return dict(r) if r else None


def task_list(limit: int = 100) -> list:
    """最近的任务（新 → 旧）。"""
    rows = _connect().execute(
        "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (max(1, int(limit)),)
    ).fetchall()
    return [dict(r) for r in rows]


def task_prune(keep: int = 200) -> int:
    """只保留最近 keep 条任务，返回删除条数（防止无限增长）。"""
    keep = max(10, int(keep))
    c = _connect()
    with _lock:
        cur = c.execute(
            "DELETE FROM tasks WHERE id NOT IN "
            "(SELECT id FROM tasks ORDER BY created_at DESC LIMIT ?)",
            (keep,),
        )
        c.commit()
        return int(cur.rowcount or 0)


# ---------------- 通知已读态 ----------------
# 通知条目本身来自活动日志（追加写的 jsonl，**条目没有自增主键**），
# 因此已读标记以「条目内容指纹」为主键，指纹算法见 server._notif_id。
# ⚠️ 刻意不做「自动剔除过期标记」：列表接口一次只取 N 条，
#    若按当前页去裁剪标记，会把「标了 1000 条、列表只显示前 100 条」时的另外 900 条误删。
#    日志被清空时才整体清掉标记（见 server.api_logs_clear）。

def mark_notifications_read(ids) -> int:
    """把若干通知标记为已读（重复标记不报错）。返回**新增**条数。"""
    now = time.time()
    added = 0
    c = _connect()
    with _lock:
        for raw in ids or []:
            key = str(raw or "").strip()
            if not key:
                continue
            cur = c.execute(
                "INSERT OR IGNORE INTO notifications_read(notif_id, read_at) VALUES(?,?)",
                (key, now),
            )
            added += int(cur.rowcount or 0)
        c.commit()
    return added


def notification_read_ids() -> set:
    """全部已读标记的 id 集合。"""
    rows = _connect().execute("SELECT notif_id FROM notifications_read").fetchall()
    return {r["notif_id"] for r in rows}


def clear_notifications_read() -> int:
    """清空全部已读标记（日志被清空后调用）。返回删除条数。"""
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM notifications_read")
        c.commit()
        return int(cur.rowcount or 0)


# ---------------- 成就 ----------------
# 两张表的分工：
#   achievements      目录的**物化副本**（条目定义在 core/achievements.ACHIEVEMENTS）。
#                     存一份是为了让已有解锁记录在目录条目改名 / 移除后仍有可解释的上下文，
#                     另外「回填」也需要一个可枚举的落点。
#   user_achievements 只记「解锁」这一件事（解锁时间）。
#                     进度**不落库**、永远由 metrics 实时算 —— 否则删掉几本书之后，
#                     库里的进度就变成了过期缓存，还会和界面显示对不上。

def upsert_achievement(key, name, desc, group_name, metric, target, sort) -> None:
    c = _connect()
    with _lock:
        c.execute(
            'INSERT INTO achievements(key, name, "desc", group_name, metric, target, sort) '
            "VALUES(?,?,?,?,?,?,?) "
            'ON CONFLICT(key) DO UPDATE SET name=excluded.name, "desc"=excluded."desc", '
            "group_name=excluded.group_name, metric=excluded.metric, "
            "target=excluded.target, sort=excluded.sort",
            (str(key), str(name), str(desc or ""), str(group_name or ""),
             str(metric or ""), float(target), int(sort)),
        )
        c.commit()


def list_achievements() -> list:
    rows = _connect().execute("SELECT * FROM achievements ORDER BY sort, key").fetchall()
    return [dict(r) for r in rows]


def unlocked_map() -> dict:
    """已解锁成就：``{key: unlocked_at}``。"""
    rows = _connect().execute("SELECT key, unlocked_at FROM user_achievements").fetchall()
    return {r["key"]: r["unlocked_at"] for r in rows}


def unlock_achievement(key) -> bool:
    """首次解锁时写入解锁时间。返回是否为**新解锁**（已解锁则为 False）。"""
    c = _connect()
    with _lock:
        cur = c.execute(
            "INSERT OR IGNORE INTO user_achievements(key, unlocked_at) VALUES(?,?)",
            (str(key), time.time()),
        )
        c.commit()
        return bool(cur.rowcount)


# ---------------- 孤儿记录（引用了已不存在的书的行）----------------
# 上游 Maintenance 页把这类东西叫 orphans。本项目的对应物不是「孤儿封面目录」
# （封面在 EPUB 内部，没有独立目录），而是**引用了已消失书籍的数据库行**：
# 书从 OUTPUT_DIR 移走后，progress / annotations / bookmarks / meta_locks /
# reading_sessions / collection_items 里仍留着它的行 —— 界面上再也走不到，却一直占着库。
#
# ⚠️ 清理是**不可恢复**的，但这些行的 key 是文件名派生的 book_id，
#    所以如果把同一个文件放回 OUTPUT_DIR，进度与批注会**重新关联上**。
#    也就是说：清理掉的是「可能还有用」的数据，因此必须由用户显式确认。

# ⚠️ **第 36 期补齐**：``meta_override`` / ``meta_online`` / ``meta_cover`` 也一直不在这里。
#    书被删（文件没了）之后，这三张表的行同样「界面上再也走不到却一直占着库」——
#    ``meta_cover`` 存的是封面 BLOB，占的正是大头。判据与上面一致：**凡含 book_id 的表
#    都该可清理、可被告知**（``tests/test_remap_tables.py`` 的契约测试钉住搬迁那一半）。
#    刻意**不含** ``scrape_items``：它是出版物台账，行被删等于把「磁盘上可能还留着一个
#    副本」这件事静默遗忘（刮削流程自己的对账/待确认负责它的生死），不归孤儿清理管。
ORPHAN_TABLES = ("progress", "annotations", "bookmarks", "meta_locks",
                 "book_custom_values", "collection_items", "reading_sessions",
                 "reading_attempts", "meta_override", "meta_online", "meta_cover",
                 "book_embeddings", "book_origins", "store_toc", "toc_map",
                 # 第 93 期：源绑定同样是「书走不到就再也看不见、却一直占着库」的行。
                 # 与 store_toc / toc_map 的区别只在于「重建成本」——它们重取一次就有，
                 # 绑定得用户重新选一次源 —— 但**可清理**这件事与成本无关。
                 "online_bind")


def book_id_refs() -> dict:
    """各表引用的 book_id 集合。表名取自固定常量，不拼接外部输入。

    ⚠️ 这里**刻意不看** ``annotations.deleted_at``：孤儿的判据是「book_id 已不在书库」，
    与批注是否进了垃圾桶无关 —— 书都没了，它的批注（活跃的、垃圾桶的）本就都该可清理。
    反过来，书**仍然存在**时它的垃圾桶批注不会被清（因为书在，book_id 不算孤儿）。
    所以别顺手给这条 SQL 加 ``deleted_at=0``：那会让「只剩垃圾桶批注的已删书」
    永远清不掉，垃圾桶里堆着看不见的垃圾。
    """
    out: dict = {}
    c = _connect()
    for t in ORPHAN_TABLES:
        try:
            rows = c.execute("SELECT DISTINCT book_id FROM %s" % t).fetchall()
        except Exception:
            rows = []
        out[t] = sorted({str(r["book_id"]) for r in rows})
    return out


def delete_orphans(orphans: dict) -> dict:
    """按表删除指定的 book_id 记录，返回 ``{表名: 删除行数}``。"""
    removed: dict = {}
    c = _connect()
    with _lock:
        for t, ids in (orphans or {}).items():
            if t not in ORPHAN_TABLES or not ids:
                continue
            n = 0
            for bid in ids:
                cur = c.execute("DELETE FROM %s WHERE book_id=?" % t, (str(bid),))
                n += int(cur.rowcount or 0)
            removed[t] = n
        c.commit()
    return removed


# ---------------- book_id 迁移（挪目录 / 改名时保住关联数据）----------------
# `library._book_id` 由 **basename** 派生，所以「只挪目录、不改文件名」时 id 不变；
# 但「改名」与「加卷号」（``三体.epub`` → ``三体 #1.epub``）会换 id，
# 而 progress / annotations / ratings / … 全是按 book_id 存的 ——
# 不搬就变成一堆走不到的孤儿行（见上方 ORPHAN_TABLES）。
# 所以**凡是会改变 basename 的移动，都要把关联数据搬过去**。

#: 需要跟着 book_id 迁移的表（与 ORPHAN_TABLES 相比多出 ratings / reading_status /
#: koreader_docs：ratings / reading_status 在删书时会主动清理，但改名时同样必须跟着走；
#: koreader_docs 是 KOReader 进度映射，id 换了必须一起搬，否则 KOReader 关联全断）。
#:
#: ⚠️ **第 36 期补齐**：``meta_override`` / ``meta_online`` / ``meta_cover`` 一直漏在这里。
#: 它们同样按 book_id 存，而换库（库前缀变）与改名 / 加卷号（basename 变）都会换 id ⇒
#: 移动或改名之后，用户的元数据编辑、在线抓取值、封面缓存**静默失联** —— 读点全按新 id
#: 查，查不到不抛异常、不回滚，只是无声回落成抓取值或文件原值（无痕的数据丢失）。
#: 判据由契约测试钉住（``tests/test_remap_tables.py``）：**凡含 book_id 列的表，必须
#: 出现在本清单或 :data:`REMAP_EXPLICIT_TABLES` 里**。
REMAP_TABLES = (
    "progress", "annotations", "bookmarks", "meta_locks", "book_custom_values",
    "collection_items", "reading_sessions", "reading_attempts", "ratings", "reading_status",
    "koreader_docs", "meta_override", "meta_online", "meta_cover", "book_embeddings",
    "book_origins", "online_bind",
)
# ⚠️ 第 93 期的 ``online_bind`` 加在这里，**不加进** :data:`REMAP_DERIVED_TABLES` ——
#    它与 store_toc / toc_map 长得很像（都是「从某个源取回来的东西」），但性质相反：
#    那两张是**外部数据的缓存**，丢了下次打开详情页再取一次就有；这一张记的是
#    **用户显式说过的「这本书在这个源这一页读」** —— 改名 / 换库后不搬，
#    用户就得自己重新想起来「我当初是在哪个站读的这本」。
#    PK 只有 ``book_id`` 一列（不像 store_toc 那样带来源 / 序号）⇒ 通用搬迁那种
#    「整表 UPDATE」不会撞主键，直接走通用路径即可，不需要 REMAP_EXPLICIT_TABLES 那套。

#: **不走通用搬迁**、改用自己那套函数的含 book_id 表（契约测试同样要认它们）。
#: 目前只有 ``scrape_items``：它除了 ``book_id`` 还有 ``library_id`` / ``source_rel`` /
#: ``link_rel`` 三个**库相关**列要一起改（换库改全部，改名只改 ``source_rel``），
#: 而通用搬迁不该知道出版物语义 ⇒ 走 :func:`scrape_remap_item`，由移动与改名两条路径共用。
REMAP_EXPLICIT_TABLES = ("scrape_items",)

#: **衍生表**：同样含 ``book_id``，但**刻意不搬** —— 它们是磁盘的投影，随重扫自然重算。
#:
#: ``book_index``（第 62 期）的每一行都是「某个根下、某个相对路径」的探测结果，判据
#: （``root`` / ``rel`` / ``size`` / ``mtime``）就写在行里。改名 / 换库之后旧行因为
#: **那条路径已经不存在**，被下一次增量刷新直接删掉，新行按新路径重新探测出来 ——
#: 这才是「索引跟着磁盘走」，比搬准得多。
#:
#: ⚠️ 反过来把它加进 :data:`REMAP_TABLES` 会**搬坏**：搬迁只改 ``book_id``、不改 ``rel``，
#: 于是行变成「book_id 已经是新名字了，rel 还是旧路径」，正好破坏
#: ``book_id == _book_id(rel, library_id)`` 这条派生不变式 —— ``by_id`` 会拿着一行
#: 自称指向某本书、路径却指向不存在文件的记录去开文件。契约测试认这份清单。
REMAP_DERIVED_TABLES = ("book_index", "store_toc", "toc_map")
# ⚠️ 后两张是**第 85 期的外部数据缓存**（书城目录 + 章节映射），与 `book_index` 同属「不搬」
#    那一类，但**理由不同**：它们的主键含来源与书城序号，通用搬迁那种「整表 UPDATE」一旦
#    撞上主键就会被外层 `except` 吞成「搬 0 行」（正是 :func:`_remap_bookmarks` 那个坑）；
#    而它们的重建成本只是「下次打开详情页再取一次目录」。改名 / 换库后旧行成为孤儿，
#    由 :data:`ORPHAN_TABLES` 清掉 —— 不搬不会损坏任何东西，搬错才会。

#: 目标 id 上**已有数据**时也**不整表跳过**的表：逐行搬，只对**同一字段**取舍。
#: 这几张表的 PK 都是 ``(book_id, field)`` ⇒ 搬迁的粒度本就是**字段**，目标上某个字段
#: 已有行，不该让这本书**其余字段**统统搁浅（整表跳过一次丢全部）。冲突一律
#: **保留目标行**（从不覆盖新 id 上已有的值 —— 「宁可少搬，不可错搬」）：
#:
#: - ``meta_locks``：两行语义相同（都是「这个字段别让抓取动」），留着目标行即可；
#:   反过来漏搬会让用户显式设过的锁无声消失。
#: - ``meta_override`` / ``meta_online``：行是**值**，但 ``new`` 上的行只可能来自一本
#:   已消失的书（``remap_book_id`` 的调用方都在「该 id 的槽位空着」时才搬），覆盖它没有
#:   收益却可能顶掉别人；代价是同字段冲突时牺牲旧 id 那一行（见 :func:`_remap_merge_fields`）。
REMAP_MERGE_TABLES = ("meta_locks", "meta_override", "meta_online")

# ⚠️ `book_custom_values` 的 `PRIMARY KEY(book_id, key)` 与书签同形，但**不需要**逐行搬：
#    书签要逐行是因为它的探测过滤了 `deleted_at=0`（墓碑行不算「已有数据」），
#    于是整体 UPDATE 会撞上墓碑；而值表**没有软删除** ⇒ 探测即精确判据 ——
#    探测说「目标没有数据」，就真的没有行可撞。多写一段逐行逻辑只会是死代码。
#    ⚠️ 但「不逐行」并非没有代价：目标上只要有一个**别的** key，整张表就被跳过，
#    旧书的**其余** key 会一起搁浅。meta_override / meta_online 与它同为
#    `(book_id, 字段)` 形，本期**选择付那份代码代价**（见 REMAP_MERGE_TABLES）——
#    理由是元数据编辑是用户显式改过的痕迹，丢一条比留一条陈旧值更糟。
#    两处口径不一致是**已知的**（第 35 期定的是这里注释的这条），
#    要统一就把本表也加进 REMAP_MERGE_TABLES，并把 `_remap_merge_fields` 的列名
#    从写死的 `field` 参数化（本表列名是 `key`）—— 本期不动它（不在移动的关键路径上）。

#: 「新 id 是否已有数据」这个探测要**按表**加过滤：annotations 第 27 期起有软删除、
#: bookmarks 第 34 期起同样有（两者都是「删除=移入垃圾桶」），
#: 新 id 上只躺着**垃圾桶**条目时不该算作「已有数据」—— 否则整张表被跳过搬迁，
#: 旧 id 的**活跃**条目会被搁浅成孤儿（静默丢失，不报错）。
#: ⚠️ 搬迁本身（UPDATE）**不加**这个谓词：活跃与垃圾桶条目都属于同一本书，都该跟着走。
REMAP_PROBE_FILTER = {"annotations": " AND deleted_at=0", "bookmarks": " AND deleted_at=0"}


def _remap_bookmarks(c, old: str, new: str) -> int:
    """书签的搬迁**必须逐行做**：``UNIQUE(book_id, anchor)`` 让整体 UPDATE 会撞唯一约束。

    撞上时整条 UPDATE 抛异常、被外层 ``except`` 吞成「搬了 0 行」—— 旧书签静默丢失。
    所以这里逐行搬：同位置已经有行就**先扔掉那一条再搬**。

    走到这里时目标 id 上**没有活跃书签**（有的话整张表已被探测跳过），
    故冲突方只可能是**墓碑**：它记录的是「这个位置曾被删过」，
    而旧 id 上那条（活跃或墓碑）是更完整的历史，让位即可。
    """
    moved = 0
    rows = c.execute("SELECT id, anchor FROM bookmarks WHERE book_id=?", (old,)).fetchall()
    for row in rows:
        clash = c.execute(
            "SELECT id FROM bookmarks WHERE book_id=? AND anchor=?", (new, row["anchor"])
        ).fetchone()
        if clash:
            c.execute("DELETE FROM bookmarks WHERE id=?", (int(clash["id"]),))
        cur = c.execute("UPDATE bookmarks SET book_id=? WHERE id=?", (new, int(row["id"])))
        moved += int(cur.rowcount or 0)
    return moved


def _remap_merge_fields(c, t: str, old: str, new: str) -> int:
    """``PRIMARY KEY(book_id, field)`` 的表逐行搬，**同 field 冲突时保留目标行**。

    为什么必须逐行：整体 ``UPDATE`` 撞主键会抛异常、被 :func:`remap_book_id` 的
    ``except`` 吞成「搬 0 行」—— 用户显式设过的东西**无声消失**（第 34 期书签同一个坑）。

    为什么连整表跳过也一并豁免（见 :data:`REMAP_MERGE_TABLES`）：这些表的搬迁粒度本就
    是**字段**，目标上某个字段已有行不该让这本书**其余字段**统统搁浅。

    冲突取舍与 :func:`_remap_bookmarks` 相反：书签那一行是**内容**（旧 id 的更完整，
    让目标让位），这几张表的目标行则**原样留存**、把旧 id 那一行删掉。

    ⚠️ 表名一律取自 :data:`REMAP_TABLES` 常量，**不拼接外部输入**。
    """
    moved = 0
    rows = c.execute("SELECT field FROM %s WHERE book_id=?" % t, (old,)).fetchall()
    for row in rows:
        f = row["field"]
        clash = c.execute(
            "SELECT 1 FROM %s WHERE book_id=? AND field=?" % t, (new, f)
        ).fetchone()
        if clash:
            c.execute("DELETE FROM %s WHERE book_id=? AND field=?" % t, (old, f))
            continue
        cur = c.execute(
            "UPDATE %s SET book_id=? WHERE book_id=? AND field=?" % t, (new, old, f)
        )
        moved += int(cur.rowcount or 0)
    return moved


def remap_book_id(old_id, new_id) -> dict:
    """把关联数据从 ``old_id`` 搬到 ``new_id``，返回 ``{表名: 搬迁行数}``。

    某张表在 ``new_id`` 上**已有数据**时该表跳过：那通常意味着目标文件名上已经有
    一本书的历史（用户先删旧文件、又放了同名新文件），覆盖会张冠李戴 ——
    宁可少搬，不可错搬。两处例外：
    **bookmarks**（见 :func:`_remap_bookmarks`）有唯一索引，整体 UPDATE 会直接抛异常
    被吞掉，只能逐行搬；**合并型表**（见 :data:`REMAP_MERGE_TABLES` 与
    :func:`_remap_merge_fields`：meta_locks / meta_override / meta_online）逐行搬、
    只对**同一字段**取舍，连跳过探测也一并豁免（目标上某个字段有行不该让其余字段搁浅）。

    ``scrape_items``（见 :func:`scrape_remap_item`）**刻意不在这里**：它在 book_id 之外
    还有 ``library_id`` / ``source_rel`` / ``link_rel`` 三个库相关列要一起改，
    而通用搬迁不该知道出版物语义。
    """
    old, new = str(old_id), str(new_id)
    if not old or not new or old == new:
        return {}
    moved: dict = {}
    c = _connect()
    with _lock:
        for t in REMAP_TABLES:
            try:
                # 「合并型」表**不做整表跳过探测**：目标上已有别的字段，
                # 不该让旧书其余字段的编辑丢掉
                if t in REMAP_MERGE_TABLES:
                    moved[t] = _remap_merge_fields(c, t, old, new)
                    continue
                exists = c.execute(
                    "SELECT 1 FROM %s WHERE book_id=?%s LIMIT 1"
                    % (t, REMAP_PROBE_FILTER.get(t, "")), (new,)
                ).fetchone()
                if exists:
                    moved[t] = 0
                    continue
                if t == "bookmarks":
                    moved[t] = _remap_bookmarks(c, old, new)
                    continue
                cur = c.execute(
                    "UPDATE %s SET book_id=? WHERE book_id=?" % t, (new, old)
                )
                moved[t] = int(cur.rowcount or 0)
            except Exception:
                moved[t] = 0
        c.commit()
    return moved


def upgrade_book_ids() -> dict:
    """一次性把 book_id 从「全局 basename 哈希」升级为「库维度 id（库$哈希）」。

    书本身不落库（扫描实时生成），需要迁移的只有按 book_id 存的关联表
    （见 ``REMAP_TABLES``，含 koreader_docs）。做法：

    1. 遍历每个库的根目录，按文件名 basename 反算**旧** id（纯 12 位哈希），
       建立 ``旧id → 库id`` 索引；
    2. 取所有关联表里出现过的旧 id，凡能在索引里查到库，就重算新 id 并
       ``remap_book_id`` 搬到新 id（复用既有搬迁逻辑，含「目标已有数据则跳过」保护）；
    3. 用 ``app_state.bookid_v2`` 记幂等标记，跑过即跳过。

    无法反查到库的行（文件已删、只剩孤儿关联）保持不动 —— 它们本就是孤儿，
    由「工具 → 维护」的孤儿清理负责，不必在此强搬。
    """
    if state_get("bookid_v2") == "1":
        return {"skipped": True}
    from . import library as _lib  # 延迟导入，避开与 library 的循环依赖
    index: dict = {}
    for lib in _lib.libraries():
        lid = str(lib.get("id") or "")
        _dirs = lib.get("source_dirs") or ""
        try:
            _dir_list = json.loads(_dirs) if _dirs else []
        except Exception:
            _dir_list = []
        for _dp in _dir_list:
            d = pathlib.Path(str(_dp))
            if not d.is_dir():
                continue
        for f in d.rglob("*"):
            if not f.is_file():
                continue
            base = f.name
            old = hashlib.sha1(base.encode("utf-8")).hexdigest()[:12]
            index.setdefault(old, lid)
    old_ids: set = set()
    c = _connect()
    for t in REMAP_TABLES:
        try:
            rows = c.execute("SELECT DISTINCT book_id FROM %s" % t).fetchall()
        except Exception:
            rows = []
        for r in rows:
            old_ids.add(str(r["book_id"]))
    moved_total = 0
    for old in sorted(old_ids):
        lid = index.get(old)
        if not lid:
            continue
        new = f"{lid}${old}"
        if new == old:
            continue
        moved = remap_book_id(old, new)
        moved_total += sum(moved.values())
    state_set("bookid_v2", "1")
    return {"skipped": False, "indexed": len(index),
            "old_ids": len(old_ids), "moved": moved_total}


def clear_unlocked() -> int:
    """清空全部解锁记录（「回填」时先清再算）。返回删除条数。"""
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM user_achievements")
        c.commit()
        return int(cur.rowcount or 0)


# ---------------- 书籍评分（1–5 星）----------------
# 上游成就体系有 4 条依赖它；本项目此前完全没有评分概念。
# 星级只存 1–5 的整数，**不做 0 星**：0 表示「未评分」，用「没有这一行」表达，
# 这样「未评分」与「评了 1 星」不会混淆 —— 后者在「Use all five star ratings」里是有效值。

def set_rating(book_id, stars) -> dict:
    """写入评分（1–5）。越界或非整数抛 ValueError。"""
    try:
        s = int(stars)
    except (TypeError, ValueError):
        raise ValueError("评分必须是 1–5 的整数")
    if not 1 <= s <= 5:
        raise ValueError("评分必须是 1–5 的整数")
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO ratings(book_id, stars, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(book_id) DO UPDATE SET stars=excluded.stars, updated_at=excluded.updated_at",
            (str(book_id), s, time.time()),
        )
        c.commit()
    return {"book_id": str(book_id), "stars": s}


def get_rating(book_id) -> int:
    """取某书评分；未评分为 0。"""
    r = _connect().execute(
        "SELECT stars FROM ratings WHERE book_id=?", (str(book_id),)
    ).fetchone()
    return int(r["stars"]) if r else 0


def all_ratings() -> dict:
    """全部评分：``{book_id: stars}``（供书单附带评分与成就判定）。"""
    rows = _connect().execute("SELECT book_id, stars FROM ratings").fetchall()
    return {r["book_id"]: int(r["stars"]) for r in rows}


def clear_rating(book_id) -> int:
    """取消评分。返回删除行数（0 = 本来就没评）。"""
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM ratings WHERE book_id=?", (str(book_id),))
        c.commit()
        return int(cur.rowcount or 0)


def set_review(book_id, review) -> dict:
    """写/清书评（空串 = 清除）。不动评分 —— 两者同表但独立编辑。"""
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO ratings(book_id, stars, review, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(book_id) DO UPDATE SET review=excluded.review, updated_at=excluded.updated_at",
            (str(book_id), get_rating(book_id) or 0, str(review or ""), time.time()),
        )
        c.commit()
    return {"book_id": str(book_id), "review": str(review or "")}


def all_reviews() -> dict:
    rows = _connect().execute(
        "SELECT book_id, review FROM ratings WHERE review != ''"
    ).fetchall()
    return {r["book_id"]: r["review"] for r in rows}


def get_review(book_id) -> dict:
    """评分 + 书评一起读（stars 0 = 未评分，review '' = 无书评）。"""
    r = _connect().execute(
        "SELECT stars, review FROM ratings WHERE book_id=?", (str(book_id),)
    ).fetchone()
    return {"book_id": str(book_id), "stars": int(r["stars"]) if r else 0,
            "review": (r["review"] if r else "") or ""}


# ---------------- 书城目录来源（第 85 期） ----------------
# 只存**目录**（标题 + 顺序 + 映射），不存正文；`payload` 存 JSON 字符串。
# 「取目录」的编排与规则在 `sources/toc_sources.py`，覆盖层在 `core/reading_list.py`。

def store_toc_get(book_id, source: str = "") -> list:
    """读某本书的书城目录行（`source` 留空 = 全部来源），按来源排序。

    ⚠️ **含 `ok=0` 的负结果行** —— 那不是错误数据，而是「上次没取到」的事实：
    界面据此如实显示原因，而不是把详情页变成每打开一次就外呼一次。
    """
    c = _connect()
    if source:
        rows = c.execute("SELECT * FROM store_toc WHERE book_id=? AND source=?",
                         (str(book_id), str(source))).fetchall()
    else:
        rows = c.execute("SELECT * FROM store_toc WHERE book_id=? ORDER BY source",
                         (str(book_id),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["entries"] = json.loads(d.pop("payload") or "[]")
        except Exception:                                    # noqa: BLE001 —— 坏 JSON 当空目录
            d["entries"] = []
        d["ok"] = bool(d.get("ok"))
        d["manual"] = bool(d.get("manual"))
        out.append(d)
    return out


def store_toc_save(book_id, source, *, ok, note="", store_ref="", matched_title="",
                   matched_author="", confidence=0.0, manual=False, entries=None) -> dict:
    """写一次抓取结果（**负结果也写**：`ok=False` 留着它才不会再反复外呼）。

    `entries` = 书城目录 ``[{"title": str, "depth": int | None}, ...]``（按书城顺序）。
    """
    payload = json.dumps(list(entries or []), ensure_ascii=False)
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO store_toc(book_id, source, store_ref, matched_title, matched_author,"
            " confidence, manual, ok, note, payload, fetched_at)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(book_id, source) DO UPDATE SET"
            " store_ref=excluded.store_ref, matched_title=excluded.matched_title,"
            " matched_author=excluded.matched_author, confidence=excluded.confidence,"
            " manual=excluded.manual, ok=excluded.ok, note=excluded.note,"
            " payload=excluded.payload, fetched_at=excluded.fetched_at",
            (str(book_id), str(source), str(store_ref or ""), str(matched_title or ""),
             str(matched_author or ""), float(confidence or 0), 1 if manual else 0,
             1 if ok else 0, str(note or ""), payload, time.time()),
        )
        c.commit()
    return {"book_id": str(book_id), "source": str(source), "ok": bool(ok)}


def toc_map_get(book_id, source: str = "") -> dict:
    """读映射 ``{书城序号: 本地 index}``；`source` 留空时按来源分组返回。"""
    c = _connect()
    if source:
        rows = c.execute("SELECT store_index, local_index FROM toc_map"
                         " WHERE book_id=? AND source=?", (str(book_id), str(source))).fetchall()
        return {int(r["store_index"]): int(r["local_index"]) for r in rows}
    out: dict = {}
    rows = c.execute("SELECT source, store_index, local_index FROM toc_map WHERE book_id=?",
                     (str(book_id),)).fetchall()
    for r in rows:
        out.setdefault(r["source"], {})[int(r["store_index"])] = int(r["local_index"])
    return out


def toc_map_replace(book_id, source, pairs) -> int:
    """整批替换某本书在某来源上的映射（`pairs` = ``[(书城序号, 本地 index), ...]``）。

    **先删后插**：映射是派生数据，逐条 diff 没有收益；而「半新半旧」会让覆盖层按两次
    不同的对齐结果渲染同一本书（昨天对齐到第 3 章、今天对到第 5 章，读者会以为书变了）。
    """
    c = _connect()
    rows = [(str(book_id), str(source), int(s), int(l)) for s, l in (pairs or [])]
    with _lock:
        c.execute("DELETE FROM toc_map WHERE book_id=? AND source=?", (str(book_id), str(source)))
        if rows:
            c.executemany("INSERT INTO toc_map(book_id, source, store_index, local_index)"
                          " VALUES(?,?,?,?)", rows)
        c.commit()
    return len(rows)


def store_toc_clear(book_id, source: str = "") -> int:
    """删掉某本书的书城目录与映射 —— **「还原为本地目录」就是这一个动作**，零副作用。

    两张表**一起**清：留下孤立的映射只会让下一次覆盖按一份已经不存在的书城目录去改标题。
    """
    c = _connect()
    with _lock:
        if source:
            n = c.execute("DELETE FROM store_toc WHERE book_id=? AND source=?",
                          (str(book_id), str(source))).rowcount
            c.execute("DELETE FROM toc_map WHERE book_id=? AND source=?",
                      (str(book_id), str(source)))
        else:
            n = c.execute("DELETE FROM store_toc WHERE book_id=?", (str(book_id),)).rowcount
            c.execute("DELETE FROM toc_map WHERE book_id=?", (str(book_id),))
        c.commit()
    return int(n or 0)


# ---------------- 在线阅读的源绑定（第 93 期）----------------
# 一本书 ↔ 一个书源上的一页（建表语句在 `init()` 的那段 executescript 里，注释写在那儿）。
#
# 为什么这张表必须落库、不能只放前端本地存储：用户的原话是「切换客户端，阅读进度同步」。
# 绑定与在线位置（`pos`）都是**跨客户端共享的一次事实**，本地存储做不到这件事。

#: `seen` 的长度上限。跨过自动落地的门槛（在线读完 5 章）之后它就不再参与判定，
#: 封顶只是不让一行随阅读无限长大。超过 64 章时**丢掉最早的** —— 留下最近读过的痕迹。
ONLINE_SEEN_MAX = 64

#: 绑定行的可写列（白名单：拼 SQL 前过滤，不认任意键 —— 与 `LEDGER_FIELDS` 同口径）。
ONLINE_BIND_FIELDS = ("library_id", "source", "url", "title", "pos", "seen",
                      "auto_task", "updated_at")


def _online_bind_row(d: dict) -> dict:
    """把库里的行整理成对外形状（`seen` 解码成 int 列表、`pos` 转 int）。"""
    row = dict(d)
    try:
        seen = json.loads(row.get("seen") or "[]")
    except Exception:                                       # noqa: BLE001 —— 坏 JSON 当没读过
        seen = []
    row["seen"] = [int(x) for x in seen
                   if isinstance(x, int) or str(x).lstrip("-").isdigit()]
    row["pos"] = int(row.get("pos") or 0)
    row["updated_at"] = float(row.get("updated_at") or 0)
    return row


def online_bind_get(book_id) -> dict | None:
    """读某本书的源绑定（没有绑定 ⇒ ``None``，调用方据此如实说「没绑定」）。"""
    c = _connect()
    r = c.execute("SELECT * FROM online_bind WHERE book_id=?", (str(book_id),)).fetchone()
    return _online_bind_row(dict(r)) if r else None


def online_bind_list() -> list[dict]:
    """**全部**绑定（自动追更要按它把「只有绑定、没有 sidecar」的书也算进候选）。

    ⚠️ 不与 `library.by_id()` 对账：那要扫库，而这一步在后台定时线程里跑；
    库里的书是否还在，由调用方按需判（不在就当孤儿，见 `ORPHAN_TABLES`）。
    """
    c = _connect()
    rows = c.execute("SELECT * FROM online_bind ORDER BY book_id").fetchall()
    return [_online_bind_row(dict(r)) for r in rows]


def online_bind_put(book_id, *, library_id="", source="", url="", title="") -> dict:
    """写入 / 覆盖一本书的源绑定（用户显式动作 = 选源 + 匹配书页）。

    ⚠️ **换了 (source, url) 就清零 `pos` / `seen` / `auto_task`**：那三样都是「在**那个**书页上
    读到哪儿」的记录，换了书页还留着它，读者一打开就会被空降到别的书的某个位置 ——
    而且旧 `auto_task` 会让「自动落地」再也触发不了（明明是新绑的源）。
    指向同一页的重复绑定（用户再点一次「绑定」）**不清零**：那是同一个事实。
    """
    bid = str(book_id or "")
    if not bid:
        raise ValueError("online_bind_put 需要 book_id")
    new = {"library_id": str(library_id or ""), "source": str(source or ""),
           "url": str(url or ""), "title": str(title or "")}
    old = online_bind_get(bid)
    same_page = bool(old) and old.get("source") == new["source"] and old.get("url") == new["url"]
    pos = int(old.get("pos") or 0) if same_page else 0
    seen = json.dumps(old.get("seen") or [], ensure_ascii=False) if same_page else "[]"
    auto_task = str(old.get("auto_task") or "") if same_page else ""
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO online_bind(book_id, library_id, source, url, title, pos, seen,"
            " auto_task, updated_at) VALUES(?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(book_id) DO UPDATE SET"
            " library_id=excluded.library_id, source=excluded.source, url=excluded.url,"
            " title=excluded.title, pos=excluded.pos, seen=excluded.seen,"
            " auto_task=excluded.auto_task, updated_at=excluded.updated_at",
            (bid, new["library_id"], new["source"], new["url"], new["title"],
             pos, seen, auto_task, time.time()),
        )
        c.commit()
    return online_bind_get(bid) or {}


def online_bind_set_pos(book_id, pos) -> int:
    """推进**在线位置**（在线阅读器每次翻章都会调）。

    ⚠️ 这张表只存在线位置；**本地**位置仍旧只有 `progress` 一处（第 93 期口径：
    两份位置并存、不互相覆盖 —— 见 `core/reading_list.align_online` 的注释）。
    """
    try:
        p = max(0, int(pos))
    except (TypeError, ValueError):
        return 0
    c = _connect()
    with _lock:
        n = c.execute("UPDATE online_bind SET pos=?, updated_at=? WHERE book_id=?",
                      (p, time.time(), str(book_id))).rowcount
        c.commit()
    return int(n or 0)


def online_bind_mark_seen(book_id, index) -> list:
    """把「在线读过的第 index 章」并进 `seen`，返回**去重后**的新列表。

    去重是必须的：反复翻回第 2 章若每次都算一章，门槛（> 5 章）就成了「翻 6 次」。
    """
    try:
        idx = int(index)
    except (TypeError, ValueError):
        return []
    row = online_bind_get(book_id)
    if not row:
        return []
    seen = [int(x) for x in (row.get("seen") or []) if int(x) != idx]
    seen.append(idx)
    seen = seen[-ONLINE_SEEN_MAX:]
    c = _connect()
    with _lock:
        c.execute("UPDATE online_bind SET seen=?, updated_at=? WHERE book_id=?",
                  (json.dumps(seen), time.time(), str(book_id)))
        c.commit()
    return seen


def online_bind_set_auto_task(book_id, task_id) -> int:
    """记下自动落地任务 id（**只触发一次**的凭据：非空即表示这本书已经落地过一次）。"""
    c = _connect()
    with _lock:
        n = c.execute("UPDATE online_bind SET auto_task=?, updated_at=? WHERE book_id=?",
                      (str(task_id or ""), time.time(), str(book_id))).rowcount
        c.commit()
    return int(n or 0)


def online_bind_clear(book_id) -> int:
    """解绑（只删这一行，**不动任何文件**）。书上的在线缓存由缓存模块自己按容量回收。"""
    c = _connect()
    with _lock:
        n = c.execute("DELETE FROM online_bind WHERE book_id=?", (str(book_id),)).rowcount
        c.commit()
    return int(n or 0)


# ---------------- 书源台账 / 导入历史 / 书源变量（第 86 期）----------------
# 台账只存**元数据**（规则本体在 `SOURCES_DIR/*.json`）；两张表都不含 book_id。

#: 台账列（`source_ledger_upsert` 只认这些键，多余键忽略 —— 免得打错字静默写不进去）
LEDGER_FIELDS = (
    "origin", "dedup_key", "rule_hash", "supported", "source_type", "group_name",
    "raw_json", "unsupported", "notes", "enabled", "imported", "imported_at", "updated_at",
    "verified_at", "verify_ok", "verify_count", "verify_ms", "verify_error",
    "last_update_at", "last_update_note",
)
#: JSON 字段（读时解码、写时编码）
_LEDGER_JSON = ("unsupported", "notes")


def _ledger_row(row) -> dict:
    d = dict(row)
    for k in _LEDGER_JSON:
        try:
            d[k] = json.loads(d.get(k) or "[]")
        except Exception:                                    # noqa: BLE001 —— 坏 JSON 当空
            d[k] = []
    d["enabled"] = bool(d.get("enabled", 1))
    d["imported"] = bool(d.get("imported", 0))
    d["verify_ok"] = None if d.get("verify_ok") is None else bool(d["verify_ok"])
    return d


def source_ledger_get(name: str) -> "dict | None":
    """读一条台账（没有返回 None）。"""
    c = _connect()
    r = c.execute("SELECT * FROM source_ledger WHERE name=?", (str(name),)).fetchone()
    return _ledger_row(r) if r else None


def source_ledger_all() -> list:
    """**一次查询**取全台账，供列表内存 join（逐源查会变成 N+1，第 86 期纪律）。"""
    c = _connect()
    return [_ledger_row(r) for r in c.execute("SELECT * FROM source_ledger").fetchall()]


def source_ledger_upsert(name: str, **fields) -> dict:
    """插入或部分更新一条台账（只认 :data:`LEDGER_FIELDS` 里的键）。"""
    name = str(name)
    row = source_ledger_get(name) or {}
    row.update({k: v for k, v in fields.items() if k in LEDGER_FIELDS})
    now = time.time()
    row["name"] = name
    row.setdefault("origin", "")
    row.setdefault("dedup_key", "")
    row.setdefault("rule_hash", "")
    row.setdefault("supported", "yes")
    row.setdefault("source_type", "text")
    row.setdefault("group_name", "")
    row.setdefault("raw_json", "")
    row["imported_at"] = float(row.get("imported_at") or now)
    row["updated_at"] = now
    row["enabled"] = 1 if row.get("enabled", True) else 0
    row["imported"] = 1 if row.get("imported", False) else 0
    row["verify_count"] = int(row.get("verify_count") or 0)
    row["verify_ms"] = int(row.get("verify_ms") or 0)
    row["verify_error"] = str(row.get("verify_error") or "")
    row["last_update_note"] = str(row.get("last_update_note") or "")
    row["verify_ok"] = None if row.get("verify_ok") is None else (1 if row["verify_ok"] else 0)
    for k in _LEDGER_JSON:
        v = row.get(k) or []
        row[k] = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    cols = [f for f in LEDGER_FIELDS if f != "name"]
    c = _connect()
    with _lock:
        c.execute(
            f"INSERT INTO source_ledger(name, {', '.join(cols)})"
            f" VALUES(?{', ?' * len(cols)})"
            f" ON CONFLICT(name) DO UPDATE SET "
            + ", ".join(f"{col}=excluded.{col}" for col in cols),
            [name] + [row.get(col) for col in cols],
        )
        c.commit()
    return source_ledger_get(name)


def source_ledger_set_enabled(name: str, enabled: bool) -> "dict | None":
    """改启停（台账是唯一真值源；文件不动）。"""
    if not source_ledger_get(name):
        return None
    return source_ledger_upsert(name, enabled=bool(enabled))


def source_ledger_delete(name: str) -> bool:
    """删台账（连同它的历史）。返回是否删掉了行。"""
    c = _connect()
    with _lock:
        n = c.execute("DELETE FROM source_ledger WHERE name=?", (str(name),)).rowcount
        c.execute("DELETE FROM source_ledger_history WHERE name=?", (str(name),))
        c.commit()
    return bool(n)


def source_ledger_rename(old: str, new: str) -> bool:
    """改名（保留旧名台账会与新的冲突；历史一并带过去）。"""
    c = _connect()
    with _lock:
        n = c.execute("UPDATE source_ledger SET name=? WHERE name=?", (str(new), str(old))).rowcount
        c.execute("UPDATE source_ledger_history SET name=? WHERE name=?", (str(new), str(old)))
        c.commit()
    return bool(n)


# ---- 覆盖前备份（可回滚）----

def ledger_history_add(name: str, payload: str, *, kind: str = "rule",
                       rule_hash: str = "", note: str = "") -> str:
    """把**旧规则原文**存一条历史（覆盖前调用）。返回历史 id。"""
    hid = uuid.uuid4().hex
    c = _connect()
    with _lock:
        c.execute("INSERT INTO source_ledger_history(id, name, kind, payload, rule_hash,"
                  " note, created_at) VALUES(?,?,?,?,?,?,?)",
                  (hid, str(name), str(kind), str(payload or ""), str(rule_hash or ""),
                   str(note or ""), time.time()))
        c.commit()
    return hid


def ledger_history_list(name: str, limit: int = 20) -> list:
    """某源的覆盖历史（新的在前）——「可回滚」的入口就在这儿。"""
    c = _connect()
    rows = c.execute("SELECT id, name, kind, rule_hash, note, created_at"
                     " FROM source_ledger_history WHERE name=? ORDER BY created_at DESC LIMIT ?",
                     (str(name), int(limit))).fetchall()
    return [dict(r) for r in rows]


def ledger_history_one(hid: str) -> "dict | None":
    c = _connect()
    r = c.execute("SELECT * FROM source_ledger_history WHERE id=?", (str(hid),)).fetchone()
    return dict(r) if r else None


def ledger_history_prune(name: str, keep: int = 10) -> int:
    """只留最近 `keep` 条历史（免得备份把库撑大；保留份数与回收站同一口径）。"""
    c = _connect()
    with _lock:
        n = c.execute(
            "DELETE FROM source_ledger_history WHERE name=? AND id NOT IN"
            " (SELECT id FROM source_ledger_history WHERE name=? ORDER BY created_at DESC LIMIT ?)",
            (str(name), str(name), int(keep))).rowcount
        c.commit()
    return int(n or 0)


# ---- 导入历史 ----

def source_import_add(origin: str, counts: dict, detail: list, *, actor: str = "") -> str:
    iid = uuid.uuid4().hex
    c = _connect()
    with _lock:
        c.execute("INSERT INTO source_imports(id, origin, actor, counts, detail, created_at)"
                  " VALUES(?,?,?,?,?,?)",
                  (iid, str(origin or ""), str(actor or ""),
                   json.dumps(counts or {}, ensure_ascii=False),
                   json.dumps(detail or [], ensure_ascii=False), time.time()))
        c.commit()
    return iid


def source_imports_clear() -> int:
    """清空导入历史（给测试隔离用；顺带也是将来「清理历史」的落点）。"""
    c = _connect()
    with _lock:
        n = c.execute("DELETE FROM source_imports").rowcount
        c.commit()
    return int(n or 0)


def source_imports(limit: int = 20) -> list:
    c = _connect()
    rows = c.execute("SELECT * FROM source_imports ORDER BY created_at DESC LIMIT ?",
                     (int(limit),)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("counts", "detail"):
            try:
                d[k] = json.loads(d.get(k) or "{}")
            except Exception:                                # noqa: BLE001
                d[k] = {} if k == "counts" else []
        out.append(d)
    return out


# ---- 书源变量（凭据：**只回是否存在，绝不回值**）----

def source_vars_get(name: str) -> dict:
    """读某源的变量**键 → 值**（供规则渲染用；接口层绝不把它直接回给前端）。"""
    c = _connect()
    rows = c.execute("SELECT key, value FROM source_vars WHERE name=?", (str(name),)).fetchall()
    return {str(r["key"]): str(r["value"] or "") for r in rows}


def source_vars_keys(name: str) -> dict:
    """给界面用的形状：``{键: 是否已设置}``（**值一律不回**）。"""
    c = _connect()
    rows = c.execute("SELECT key, value FROM source_vars WHERE name=?", (str(name),)).fetchall()
    return {str(r["key"]): bool(str(r["value"] or "")) for r in rows}


def source_vars_set(name: str, key: str, value: str) -> dict:
    """写一个变量（空值视为清除该键：界面上「填了又清空」要能真的清掉）。"""
    name, key, value = str(name), str(key), str(value or "")
    c = _connect()
    with _lock:
        if value == "":
            c.execute("DELETE FROM source_vars WHERE name=? AND key=?", (name, key))
        else:
            c.execute("INSERT INTO source_vars(name, key, value, updated_at) VALUES(?,?,?,?)"
                      " ON CONFLICT(name, key) DO UPDATE SET value=excluded.value,"
                      " updated_at=excluded.updated_at", (name, key, value, time.time()))
        c.commit()
    return source_vars_keys(name)


def source_vars_clear(name: str, key: str = "") -> int:
    c = _connect()
    with _lock:
        if key:
            n = c.execute("DELETE FROM source_vars WHERE name=? AND key=?",
                          (str(name), str(key))).rowcount
        else:
            n = c.execute("DELETE FROM source_vars WHERE name=?", (str(name),)).rowcount
        c.commit()
    return int(n or 0)


# ---------------- 自定义智能书架 ----------------
# 规则以 JSON 字符串落库；结构校验与解析在 server.py（口径与前端 lib/smartScope.ts 一致）。

def list_scopes() -> list:
    rows = _connect().execute(
        "SELECT * FROM smart_scopes ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_scope(scope_id):
    """单个书架；不存在返回 None。"""
    r = _connect().execute(
        "SELECT * FROM smart_scopes WHERE id=?", (int(scope_id),)
    ).fetchone()
    return dict(r) if r else None


def create_scope(name, rules_json, match="all") -> dict:
    c = _connect()
    with _lock:
        cur = c.execute(
            'INSERT INTO smart_scopes(name, rules, "match", created_at) VALUES(?,?,?,?)',
            (str(name), str(rules_json), str(match), time.time()),
        )
        c.commit()
        return get_scope(cur.lastrowid)


def update_scope(scope_id, name, rules_json, match="all") -> dict:
    c = _connect()
    with _lock:
        c.execute(
            'UPDATE smart_scopes SET name=?, rules=?, "match"=? WHERE id=?',
            (str(name), str(rules_json), str(match), int(scope_id)),
        )
        c.commit()
    return get_scope(scope_id)


def delete_scope(scope_id) -> bool:
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM smart_scopes WHERE id=?", (int(scope_id),))
        c.commit()
        return bool(cur.rowcount)



# ---------------- KOReader 文档索引（document md5 → 书）----------------
# KOReader 用 partialMD5 标识文档（见 core/koreader.py），本项目用 book_id。
# 两边对不上就同步不了，所以需要一张映射表；扫描是幂等的，故用整表重建。

def list_koreader_docs() -> list:
    rows = _connect().execute(
        "SELECT * FROM koreader_docs ORDER BY computed_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_koreader_doc(book_id):
    r = _connect().execute(
        "SELECT * FROM koreader_docs WHERE book_id=?", (str(book_id),)
    ).fetchone()
    return dict(r) if r else None


def find_koreader_doc(doc: str):
    """按 document 标识找书：partialMD5 与 ``md5(basename)`` 两种口径都认。"""
    d = str(doc or "").strip().lower()
    if not d:
        return None
    r = _connect().execute(
        "SELECT * FROM koreader_docs WHERE doc_md5=? OR alt_md5=? LIMIT 1", (d, d)
    ).fetchone()
    return dict(r) if r else None


def replace_koreader_docs(rows: list) -> int:
    """整表重建索引，返回写入行数。

    重建而非逐条 diff：扫描本身幂等，而且这样**不会留下陈旧行**——
    书被删/改名后若只做增量更新，旧映射会一直指向不存在的书。
    """
    c = _connect()
    with _lock:
        c.execute("DELETE FROM koreader_docs")
        now = time.time()
        n = 0
        for r in rows or []:
            c.execute(
                # upsert 写法同 task_create；上一条 DELETE 已经清过表，这里的冲突
                # 分支实际走不到，写全列只是为了让「改回不带 DELETE 的写法」也安全。
                "INSERT INTO koreader_docs"
                "(book_id, doc_md5, alt_md5, size, mtime, computed_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(book_id) DO UPDATE SET doc_md5=excluded.doc_md5, "
                "alt_md5=excluded.alt_md5, size=excluded.size, mtime=excluded.mtime, "
                "computed_at=excluded.computed_at",
                (str(r["book_id"]), str(r["doc_md5"]), str(r.get("alt_md5") or ""),
                 int(r.get("size") or 0), float(r.get("mtime") or 0), now),
            )
            n += 1
        c.commit()
        return n


# ---------------- 偏好模式 / 设备（第 3 期：按设备的模式同步）----------------
# payload 是不透明 JSON 字符串；结构校验（块名/大小）在 server._check_payload。
# 「模式是快照、设备各自持有配置」这条语义决定了下面几个函数的形状：
#   · apply 是**拷贝**，不是引用 → 改模式本体不影响已拷贝的设备；
#   · 删模式只置空设备的 active_profile_id（来源标记），设备 payload 绝不动。

# 哨兵：区分「不传该参数（保留原值）」与「显式传 None（清空）」
_KEEP = object()


def list_profiles() -> list:
    rows = _connect().execute(
        "SELECT * FROM pref_profiles ORDER BY updated_at DESC, id DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_profile(pid):
    r = _connect().execute("SELECT * FROM pref_profiles WHERE id=?", (int(pid),)).fetchone()
    return dict(r) if r else None


def create_profile(name, payload_json) -> dict:
    c = _connect()
    now = time.time()
    with _lock:
        cur = c.execute(
            "INSERT INTO pref_profiles(name, payload, created_at, updated_at) VALUES(?,?,?,?)",
            (str(name), str(payload_json), now, now),
        )
        c.commit()
        return get_profile(cur.lastrowid)


def update_profile(pid, name, payload_json) -> dict:
    """更新模式**本体**。已拷贝出去的设备不受影响（快照语义）。"""
    c = _connect()
    with _lock:
        c.execute(
            "UPDATE pref_profiles SET name=?, payload=?, updated_at=? WHERE id=?",
            (str(name), str(payload_json), time.time(), int(pid)),
        )
        c.commit()
    return get_profile(pid)


def delete_profile(pid) -> dict:
    """删模式：把引用它的设备解除引用（置空来源标记），返回受影响设备数。"""
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM pref_profiles WHERE id=?", (int(pid),))
        detached = c.execute(
            "UPDATE pref_devices SET active_profile_id=NULL WHERE active_profile_id=?",
            (int(pid),),
        ).rowcount
        c.commit()
    return {"deleted": bool(cur.rowcount), "detached_devices": int(detached or 0)}


def list_devices() -> list:
    return [dict(r) for r in _connect().execute(
        "SELECT * FROM pref_devices ORDER BY last_seen DESC"
    ).fetchall()]


def get_device(did):
    r = _connect().execute("SELECT * FROM pref_devices WHERE id=?", (str(did),)).fetchone()
    return dict(r) if r else None


def upsert_device(did, name, payload_json, active_profile_id=_KEEP) -> dict:
    """设备上报配置：不存在则插入，存在则更新配置与 last_seen。

    `active_profile_id` 省略 = **保留原值**（前端推送配置时不该顺手清掉来源标记）；
    显式传 None 才清空，传整数则切换来源标记。
    """
    c = _connect()
    now = time.time()
    with _lock:
        prev = c.execute("SELECT id FROM pref_devices WHERE id=?", (str(did),)).fetchone()
        if prev is None:
            c.execute(
                "INSERT INTO pref_devices(id, name, payload, active_profile_id, created_at, last_seen) "
                "VALUES(?,?,?,?,?,?)",
                (str(did), str(name), str(payload_json),
                 None if active_profile_id is _KEEP else active_profile_id, now, now),
            )
        elif active_profile_id is _KEEP:
            c.execute(
                "UPDATE pref_devices SET name=?, payload=?, last_seen=? WHERE id=?",
                (str(name), str(payload_json), now, str(did)),
            )
        else:
            c.execute(
                "UPDATE pref_devices SET name=?, payload=?, active_profile_id=?, last_seen=? WHERE id=?",
                (str(name), str(payload_json), active_profile_id, now, str(did)),
            )
        c.commit()
    return get_device(did)


def delete_device(did) -> bool:
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM pref_devices WHERE id=?", (str(did),))
        c.commit()
        return bool(cur.rowcount)


# ---------------- 阅读状态 ----------------
# ⚠️ 之前**没有真实状态字段**：前端用 percent 推导（p>0 = 在读、≥99.5% = 读完；
#    第 40 期起这两个数字可配，见 core/lib_settings.reading_thresholds）。
#     那是「进度」不是「状态」—— 想读、搁置、弃读根本表达不出来；
#     起止日期也没有任何落点。现在落表，进度推导只作为**无状态行时的兜底**。
#
# 状态集合刻意保持 5 个（与上游对齐）：unread / reading / finished / paused / abandoned。
# 「想读」由收藏夹承担，不在这里重复。
READ_STATUSES = ("unread", "reading", "finished", "paused", "abandoned")


def get_status(book_id) -> dict:
    r = _connect().execute(
        "SELECT * FROM reading_status WHERE book_id=?", (str(book_id),)
    ).fetchone()
    return dict(r) if r else {"book_id": str(book_id), "status": "unread",
                              "started_at": 0, "finished_at": 0, "updated_at": 0}


def all_statuses() -> dict:
    """全部状态行：``{book_id: {status, started_at, finished_at}}``（供书单批量附带）。"""
    rows = _connect().execute("SELECT * FROM reading_status").fetchall()
    return {r["book_id"]: dict(r) for r in rows}


# ---------------- 收书目录条目（Book Dock 五态流水线）----------------
# 状态集合（与 core/bookdock.STATUSES 一致）：
#   pending 待处理 / ready 就绪 / needs_review 待复核 / error 出错 / ignored 已忽略
# `ignored` 是「用户显式忽略」的终态：**不计入任何标签页**，也不算可见条目 ——
# 故 dock_list / dock_counts 默认把它排除在外。

DOCK_STATUSES = ("pending", "ready", "needs_review", "error", "ignored")
#: 界面标签页（All + 4 个可见状态）；ignored 刻意不出现在这里
DOCK_TABS = ("all", "needs_review", "pending", "ready", "error")

_DOCK_FIELDS = {"name", "ext", "size", "status", "output", "detail", "retries"}


def dock_upsert(item_id, name, ext="", size=0, status="pending",
                output="", detail="", retries=0) -> None:
    """新建条目；已存在则**只补空缺、不改状态**（状态流转交给 dock_update）。"""
    now = time.time()
    c = _connect()
    with _lock:
        c.execute(
            "INSERT OR IGNORE INTO book_dock_items"
            "(id, name, ext, size, status, output, detail, retries, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (str(item_id), str(name), str(ext or ""), int(size or 0), str(status),
             str(output or ""), str(detail or ""), int(retries or 0), now, now),
        )
        c.commit()


def dock_update(item_id, **fields) -> None:
    """按白名单列更新条目，并刷新 updated_at。"""
    cols = {k: v for k, v in fields.items() if k in _DOCK_FIELDS}
    if not cols:
        return
    sets = ", ".join("%s=?" % k for k in cols)
    c = _connect()
    with _lock:
        c.execute(
            "UPDATE book_dock_items SET %s, updated_at=? WHERE id=?" % sets,
            (*cols.values(), time.time(), str(item_id)),
        )
        c.commit()


def dock_rename(old_id, new_id, name, ext, detail="") -> bool:
    """改名：**换主键**（条目 id 就是文件名）并顺带把失败计数清零。

    为什么必须单开一个函数：``id`` **不在** :data:`_DOCK_FIELDS` 里 —— 那是给
    :func:`dock_update` 的白名单，放它进去会做出「按 id 改 id」这种怪接口，而
    改名的本体恰恰就是换主键。

    ``retries`` 归零：新名字是**没试过**的条目，旧名字试到上限这件事不该继续拦它
    （历史留在活动日志里）。``status`` / ``created_at`` / ``output`` 一概不动 ——
    用户改的是名字，不是状态。
    """
    c = _connect()
    with _lock:
        cur = c.execute(
            "UPDATE book_dock_items SET id=?, name=?, ext=?, detail=?, retries=0, "
            "updated_at=? WHERE id=?",
            (str(new_id), str(name), str(ext or ""), str(detail or ""),
             time.time(), str(old_id)),
        )
        c.commit()
        return bool(cur.rowcount)


def dock_get(item_id):
    r = _connect().execute(
        "SELECT * FROM book_dock_items WHERE id=?", (str(item_id),)
    ).fetchone()
    return dict(r) if r else None


def dock_list(status=None, limit=500) -> list:
    """可见条目（不含 ignored），可按状态过滤；新 → 旧。"""
    limit = max(1, int(limit))
    if status and status in DOCK_STATUSES and status != "ignored":
        rows = _connect().execute(
            "SELECT * FROM book_dock_items WHERE status=? ORDER BY updated_at DESC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = _connect().execute(
            "SELECT * FROM book_dock_items WHERE status!='ignored' "
            "ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def dock_counts() -> dict:
    """各可见状态计数 + total（不含 ignored）。"""
    rows = _connect().execute(
        "SELECT status, COUNT(*) AS n FROM book_dock_items WHERE status!='ignored' "
        "GROUP BY status"
    ).fetchall()
    counts = {s: 0 for s in DOCK_TABS if s != "all"}
    for r in rows:
        if r["status"] in counts:
            counts[r["status"]] = int(r["n"])
    counts["all"] = sum(counts.values())
    return counts


def dock_delete(item_id) -> bool:
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM book_dock_items WHERE id=?", (str(item_id),))
        c.commit()
        return bool(cur.rowcount)


def dock_prune_missing(existing_ids) -> int:
    """删掉「文件已不在投递目录」的条目，但**保留 ready 历史**（已入库的成品记录）。

    只清理 pending / needs_review / error 这类「悬空」条目 —— 文件都没了，
    再显示也不能重扫，留着只会误导。
    """
    keep = {str(x) for x in (existing_ids or [])}
    rows = _connect().execute(
        "SELECT id FROM book_dock_items WHERE status IN ('pending','needs_review','error')"
    ).fetchall()
    gone = [r["id"] for r in rows if r["id"] not in keep]
    if not gone:
        return 0
    c = _connect()
    with _lock:
        n = 0
        for i in gone:
            n += int(c.execute("DELETE FROM book_dock_items WHERE id=?", (i,)).rowcount or 0)
        c.commit()
        return n


def dock_prune(keep=500) -> int:
    """只保留最近 keep 条（含 ready 历史），返回删除条数，防止无限增长。"""
    keep = max(50, int(keep))
    c = _connect()
    with _lock:
        cur = c.execute(
            "DELETE FROM book_dock_items WHERE id NOT IN "
            "(SELECT id FROM book_dock_items ORDER BY updated_at DESC LIMIT ?)",
            (keep,),
        )
        c.commit()
        return int(cur.rowcount or 0)


# ---------------- 原始文件来源（第 75 期）----------------
# 只在**真的复制了一份**时登记（就地库「源即存储」不登记：那种情况 ① 与 ② 是同一个
# 文件，登记了会让删书对同一路径回收两次）。登记的调用点是摄入口（watcher / 上传），
# 删除入口（`server.api_delete_book`）读它决定 ① 要不要一起回收。
# ⚠️ 按 book_id 存 = 与全仓所有「书维度的数据」同一把钥匙；改名 / 换库时随
# `REMAP_TABLES` 一起搬（否则记录会指向一本已经不存在的书）。

def origin_set(book_id, source_path) -> None:
    """登记「这本书的 ① 原件在哪」（绝对路径）。入库成功时调用，幂等。"""
    bid, src = str(book_id or ""), str(source_path or "")
    if not bid or not src:
        return
    now = time.time()
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO book_origins(book_id, source_path, created_at, updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(book_id) DO UPDATE SET "
            "source_path=excluded.source_path, updated_at=excluded.updated_at",
            (bid, src, now, now),
        )
        c.commit()


def origin_get(book_id) -> str:
    """这本书的 ① 原件绝对路径；**没登记过返回空串**（不是错误）。

    空串的含义是「这本书没有独立的 ①」：或它是就地库（源即成品），或它是 75 期之前
    入库的（那时还不记这个），或记录被孤儿清理清掉了 —— 删书时按「missing」如实回执。
    """
    r = _connect().execute(
        "SELECT source_path FROM book_origins WHERE book_id=?", (str(book_id),)
    ).fetchone()
    return str(r["source_path"] or "") if r else ""


def origin_delete(book_id) -> bool:
    """忘掉这本书的 ①（删书时用完即弃：那个路径此刻已经被移进回收站了）。

    不删的话留着的是一条**指向已经不在原处的路径**的记录 —— 下次删书会照它去回收，
    找不到 → 报 missing，虽然无害，但让「① 到底存不存在」这件事变得不可信。
    """
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM book_origins WHERE book_id=?", (str(book_id),))
        c.commit()
        return bool(cur.rowcount)


# ---------------- 元数据 override / online（第 8 期）----------------
# 分层优先级：override（用户编辑）> online（在线抓取）> opf（文件本体）。
# override 同时是「受保护标记」：metafetch 抓取时跳过这些字段，避免冲掉用户修正。

#: 「显式无值」哨兵（第 18 期；第 22 期扩到全部可编辑字段）。
#: 覆盖值是**列**，存不了空串 —— 空串在 :func:`set_override` 里表示「撤销覆盖」（删行）。
#: 但「用户就是要这个字段没有值」需要单独表达：最早只有**重排册号清空序号**，
#: 第 22 期起非 EPUB 也能手动编辑元数据 —— 它们没有 OPF 兜底层，若只用「撤销覆盖」
#: 来表达清空，字段会立刻**回落到在线的抓取值**（看起来就是「清空后又被填回来」）。
#: 所以写哨兵、读取端翻译成「无值」；哨兵同时让该字段进入 metafetch 的保护名单
#: （见其 ``field in overrides.get(book_id)``），之后的抓取不会再把它填回来。
#: ⚠️ 字面量是 ``-``：字段进了 :data:`_CLEARABLE` 之后，**恰好填一个短横线**会被读成
#: 空值（可接受的极端情况）。接口层另有正规写法 ``null`` = 显式清空（前端「清空」按钮用它）。
META_CLEAR = "-"

#: 允许使用 :data:`META_CLEAR` 的字段（= 可手动编辑的全部字段）。
#: 与 ``fileops.METADATA_FIELDS`` 以及下方的 :data:`_META_FIELDS` **必须同集合**
#: （db 不能 import fileops —— 后者 import 前者会成环，故此处显式列一遍），
#: 三者一致性有测试钉住（``tests/test_metadata_server_side.py``）。
_CLEARABLE = ("title", "author", "series", "series_index", "date",
              "publisher", "language", "description", "tags", "isbn", "narrators",
              "subtitle", "google_books_id", "goodreads_id", "amazon_id", "hardcover_id",
              "openlibrary_id", "itunes_id", "kobo_id", "aladin_id", "audible_id")


def clearable(field: str) -> bool:
    """该字段是否支持「显式清空」（覆盖值写 :data:`META_CLEAR` 哨兵）。"""
    return str(field) in _CLEARABLE


def is_cleared(field: str, value) -> bool:
    """这个覆盖值是不是「显式无值」哨兵（只对 :data:`_CLEARABLE` 里的字段成立）。"""
    return str(value) == META_CLEAR and clearable(field)


def _meta_out(field: str, value):
    """把覆盖值翻译成对外形态：哨兵 → 「无值」（``tags`` / ``narrators`` 给空列表，其余给空串）。"""
    if is_cleared(field, value):
        return [] if str(field) in ("tags", "narrators") else ""
    return value


def set_override(book_id, field, value, orig=None) -> None:
    """记录/撤销单字段的用户覆盖。value 为空（含只有空白）=> 撤销覆盖（删行）。

    ``orig`` 是**首次覆盖前的 OPF 原值**，仅在新建行时写入；已存在的行**不更新**它
    （它代表「用户动手之前长什么样」，供无在线值时回退）。撤销即删行。
    """
    bid = str(book_id)
    f = str(field)
    v = str(value or "").strip()
    o = str(orig if orig is not None else "").strip()
    c = _connect()
    with _lock:
        if not v:
            c.execute("DELETE FROM meta_override WHERE book_id=? AND field=?", (bid, f))
        else:
            c.execute(
                "INSERT INTO meta_override(book_id, field, value, orig, updated_at) "
                "VALUES(?,?,?,?,?) "
                "ON CONFLICT(book_id, field) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (bid, f, v, o, time.time()),
            )
        c.commit()


def get_overrides(book_id) -> dict:
    rows = _connect().execute(
        "SELECT field, value FROM meta_override WHERE book_id=?", (str(book_id),)
    ).fetchall()
    return {r["field"]: r["value"] for r in rows}


def get_override_row(book_id, field) -> "dict | None":
    row = _connect().execute(
        "SELECT field, value, orig FROM meta_override WHERE book_id=? AND field=?",
        (str(book_id), str(field)),
    ).fetchone()
    return dict(row) if row else None


def all_overrides() -> dict:
    """全量覆盖：``{book_id: {field: value}}``（metafetch.plan 一次取全，避免逐书查询）。"""
    rows = _connect().execute("SELECT book_id, field, value FROM meta_override").fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(r["book_id"], {})[r["field"]] = r["value"]
    return out


def set_online(book_id, fields) -> None:
    """批量写入在线抓取值：``fields`` 为 ``{field: (value, source)}``。空值跳过。"""
    bid = str(book_id)
    now = time.time()
    c = _connect()
    with _lock:
        for f, (val, src) in (fields or {}).items():
            v = str(val or "").strip()
            if not v:
                continue
            c.execute(
                "INSERT INTO meta_online(book_id, field, value, source, fetched_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(book_id, field) DO UPDATE SET value=excluded.value, "
                "source=excluded.source, fetched_at=excluded.fetched_at",
                (bid, str(f), v, str(src or ""), now),
            )
        c.commit()


def get_online(book_id) -> dict:
    rows = _connect().execute(
        "SELECT field, value, source FROM meta_online WHERE book_id=?", (str(book_id),)
    ).fetchall()
    return {r["field"]: {"value": r["value"], "source": r["source"]} for r in rows}


def all_online() -> dict:
    rows = _connect().execute(
        "SELECT book_id, field, value, source FROM meta_online"
    ).fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(r["book_id"], {})[r["field"]] = {"value": r["value"], "source": r["source"]}
    return out


# ---------------- 元数据字段级锁定（第 35 期）----------------
# 与「用户改过就受保护」（:func:`all_overrides` 那道闸）**互相独立、可以并存**：
#   · override 那道是**隐式**的 —— 改过就保护，没改过不保护；
#   · 锁是**显式开关** —— 能锁住一个从没改过的字段，也能在改过之后解锁、
#     让抓取重新接管该字段。
# 作用面刻意只到**抓取**（用户口径）：锁定不挡手动编辑 —— 手动编辑是用户当下
# 的直接意志，本就走在最顶层（override），没有理由被一个更早的标记拦住。

#: 可锁的字段 = 全部可编辑字段 + 封面。
#: ⚠️ 封面用的是**独立键** ``cover``（抓取侧的策略键名就是它，见
#: ``metafetch.plan`` 的 ``cover_pol``），它不属于 ``METADATA_FIELDS``。
LOCK_COVER = "cover"


def set_lock(book_id, field, locked: bool = True) -> bool:
    """给某本书的某个字段上锁 / 解锁，返回**写入后的状态**。

    ``locked=True`` 用 upsert（重复上锁只刷新时间戳），``False`` 直接删行
    —— 与 :func:`set_override` 的「空值即撤销」是同一套「不留空行」的做法。
    """
    bid, f = str(book_id), str(field)
    c = _connect()
    with _lock:
        if locked:
            c.execute(
                "INSERT INTO meta_locks(book_id, field, locked_at) VALUES(?,?,?) "
                "ON CONFLICT(book_id, field) DO UPDATE SET locked_at=excluded.locked_at",
                (bid, f, time.time()),
            )
        else:
            c.execute("DELETE FROM meta_locks WHERE book_id=? AND field=?", (bid, f))
        c.commit()
    return bool(locked)


def get_locks(book_id) -> set:
    """某本书被锁的字段集合（无锁 = 空集）。"""
    rows = _connect().execute(
        "SELECT field FROM meta_locks WHERE book_id=?", (str(book_id),)
    ).fetchall()
    return {r["field"] for r in rows}


def all_locks() -> dict:
    """全量锁：``{book_id: {field, …}}``（``metafetch.plan`` 一次取全，避免逐书查询）。"""
    rows = _connect().execute("SELECT book_id, field FROM meta_locks").fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(r["book_id"], set()).add(r["field"])
    return out


# ---------------- 自定义字段定义与值（第 35 期）----------------
# 定义表（全局）与值表（按书）分开：
#   · 定义：建字段 / 排序 / 改标签 / 切适用书库 / 归档 / 软删恢复（上游 custom-metadata 六项）；
#   · 值：按书存，**「行存在」即「这本书的这一项被管过了」**（见建表注释的说明）。
# 读定义一律 `deleted_at=0`（垃圾桶条目只在垃圾桶视图里出），与批注 / 书签同一套纪律。
_CUSTOM_FIELD_COLS = ("id, key, label, type, position, library_ids, default_value, "
                      "archived, created_at, updated_at, deleted_at")

#: 允许的字段类型。校验落在 ``core/customfields.py``（domain 层），这里留一份供上层引用。
CUSTOM_TYPES = ("text", "number", "date", "list")


def _as_list(text) -> list:
    """把「字面量列表」列解析成 list（与 tags 等列同一套存法）。

    空值 / 坏值一律给**空列表**：单条脏数据不该让整页报错。
    """
    if isinstance(text, (list, tuple)):
        return [str(x) for x in text]
    s = str(text or "").strip()
    if not s:
        return []
    try:
        val = ast.literal_eval(s)
    except (ValueError, SyntaxError):
        return []
    return [str(x) for x in val] if isinstance(val, (list, tuple)) else []


def _custom_field_out(row) -> dict:
    return {
        "id": int(row["id"]),
        "key": row["key"],
        "label": row["label"],
        "type": row["type"],
        "position": int(row["position"]),
        "library_ids": _as_list(row["library_ids"]),
        "default_value": row["default_value"] or "",
        "archived": bool(row["archived"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
        "deleted_at": float(row["deleted_at"]),
    }


def list_custom_fields() -> list:
    """全部**活跃**定义（含归档项 —— 归档只是不进编辑界面，定义本身仍要可管理）。

    排序：position 升序、再按 id（position 相同时保持创建次序）。
    """
    rows = _connect().execute(
        "SELECT %s FROM custom_field_defs WHERE deleted_at=0 ORDER BY position, id"
        % _CUSTOM_FIELD_COLS
    ).fetchall()
    return [_custom_field_out(r) for r in rows]


def trashed_custom_fields() -> list:
    """垃圾桶里的定义（``deleted_at`` 倒序 = 最近丢弃的在前）。"""
    rows = _connect().execute(
        "SELECT %s FROM custom_field_defs WHERE deleted_at!=0 ORDER BY deleted_at DESC"
        % _CUSTOM_FIELD_COLS
    ).fetchall()
    return [_custom_field_out(r) for r in rows]


def get_custom_field(cid) -> "dict | None":
    row = _connect().execute(
        "SELECT %s FROM custom_field_defs WHERE id=?" % _CUSTOM_FIELD_COLS, (int(cid),)
    ).fetchone()
    return _custom_field_out(row) if row else None


def custom_field_by_key(key) -> "dict | None":
    """按 key 查定义，**含垃圾桶条目**（key 全局唯一，迁移判重就是查它）。"""
    row = _connect().execute(
        "SELECT %s FROM custom_field_defs WHERE key=?" % _CUSTOM_FIELD_COLS, (str(key),)
    ).fetchone()
    return _custom_field_out(row) if row else None


def create_custom_field(key, label, type="text", library_ids=None,
                        default_value="", position=None) -> dict:
    """新建字段定义（同 key 已存在 ⇒ 抛 ``ValueError``，由接口层转 400）。"""
    k = str(key or "").strip()
    if not k:
        raise ValueError("key 不能为空")
    now = time.time()
    c = _connect()
    with _lock:
        if c.execute("SELECT 1 FROM custom_field_defs WHERE key=?", (k,)).fetchone():
            raise ValueError(f"字段键已存在：{k}")
        if position is None:
            row = c.execute("SELECT MAX(position) AS m FROM custom_field_defs").fetchone()
            position = int((row["m"] if row and row["m"] is not None else -1)) + 1
        cur = c.execute(
            "INSERT INTO custom_field_defs(key, label, type, position, library_ids, "
            "default_value, archived, created_at, updated_at) VALUES(?,?,?,?,?,?,0,?,?)",
            (k, str(label or k), str(type or "text"), int(position),
             repr([str(x) for x in (library_ids or [])]), str(default_value or ""), now, now),
        )
        c.commit()
        cid = int(cur.lastrowid or 0)
    return get_custom_field(cid) or {}


def update_custom_field(cid, **patch) -> "dict | None":
    """改定义：``label / type / position / library_ids / default_value / archived``。

    **不含 key**：改 key 等于换了一个字段（值表按 key 引用，改了会让所有值失去归属）。
    """
    allowed = {"label", "type", "position", "library_ids", "default_value", "archived"}
    sets, args = [], []
    for k, v in (patch or {}).items():
        if k not in allowed:
            continue
        if k == "library_ids":
            v = repr([str(x) for x in (v or [])])
        elif k == "archived":
            v = 1 if v else 0
        elif k == "position":
            v = int(v)
        else:
            v = str(v or "")
        sets.append("%s=?" % k)
        args.append(v)
    if not sets:
        return get_custom_field(cid)
    sets.append("updated_at=?")
    args.extend([time.time(), int(cid)])
    c = _connect()
    with _lock:
        c.execute("UPDATE custom_field_defs SET %s WHERE id=?" % ", ".join(sets), tuple(args))
        c.commit()
    return get_custom_field(cid)


def reorder_custom_fields(ids: list) -> int:
    """按给定 id 次序重排（position = 下标），返回改动的行数。

    只认**活跃**定义：列表里给出的垃圾桶条目会被忽略（不给已删除的项留位置）。
    """
    moved = 0
    c = _connect()
    with _lock:
        for pos, cid in enumerate(ids or []):
            cur = c.execute(
                "UPDATE custom_field_defs SET position=?, updated_at=? "
                "WHERE id=? AND deleted_at=0",
                (int(pos), time.time(), int(cid)),
            )
            moved += int(cur.rowcount or 0)
        c.commit()
    return moved


def delete_custom_field(cid) -> int:
    """**软删除**：移入垃圾桶（值保留 —— 恢复后值还在）。返回受影响行数。"""
    c = _connect()
    with _lock:
        cur = c.execute(
            "UPDATE custom_field_defs SET deleted_at=?, updated_at=? WHERE id=? AND deleted_at=0",
            (time.time(), time.time(), int(cid)),
        )
        c.commit()
        return int(cur.rowcount or 0)


def restore_custom_field(cid) -> int:
    """从垃圾桶恢复（值一直都在，故恢复即完整还原）。"""
    c = _connect()
    with _lock:
        cur = c.execute(
            "UPDATE custom_field_defs SET deleted_at=0, updated_at=? WHERE id=? AND deleted_at!=0",
            (time.time(), int(cid)),
        )
        c.commit()
        return int(cur.rowcount or 0)


def purge_custom_field(cid) -> int:
    """**彻底删除**（真 DELETE，且只肯删垃圾桶里的），并**连带清掉所有书上的值**。

    值必须一起删：定义没了之后，值表的那些行既没人读、也不可能再被恢复，
    留着只是看不见的垃圾（且会跟着 book_id 在改名时被搬来搬去）。
    """
    row = _connect().execute(
        "SELECT key FROM custom_field_defs WHERE id=? AND deleted_at!=0", (int(cid),)
    ).fetchone()
    if not row:
        return 0
    c = _connect()
    with _lock:
        c.execute("DELETE FROM book_custom_values WHERE key=?", (row["key"],))
        cur = c.execute("DELETE FROM custom_field_defs WHERE id=? AND deleted_at!=0", (int(cid),))
        c.commit()
        return int(cur.rowcount or 0)


def custom_field_values(book_id) -> dict:
    """某本书的自定义字段值：``{key: 原始字符串}``（类型转换在 domain 层做）。"""
    rows = _connect().execute(
        "SELECT key, value FROM book_custom_values WHERE book_id=?", (str(book_id),)
    ).fetchall()
    return {r["key"]: r["value"] for r in rows}


def all_custom_field_values() -> dict:
    """全量值：``{book_id: {key: value}}``（``metafetch.plan`` 一次取全，避免逐书查询）。"""
    rows = _connect().execute("SELECT book_id, key, value FROM book_custom_values").fetchall()
    out: dict = {}
    for r in rows:
        out.setdefault(r["book_id"], {})[r["key"]] = r["value"]
    return out


def set_custom_field_values(book_id, values: dict) -> int:
    """写入某本书的自定义字段值（**写空串也算「管过了」**，见值表建注释）。

    只 upsert 传进来的键；不传的键保持不动（调用方负责按适用范围裁剪）。
    """
    bid = str(book_id)
    now = time.time()
    n = 0
    c = _connect()
    with _lock:
        for k, v in (values or {}).items():
            c.execute(
                "INSERT INTO book_custom_values(book_id, key, value, updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(book_id, key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (bid, str(k), str(v if v is not None else ""), now),
            )
            n += 1
        c.commit()
    return n


# ---------------- 书籍封面（第 17 期 T3）----------------
# 元数据写回改为只存服务端后，封面同样**不写进 EPUB**，而是按 book_id 缓存到
# ``meta_cover``（BLOB 直接落库，零外链、零独立目录）。展示 / OPDS 封面接口
# 优先取服务端缓存，无则回退 EPUB 内嵌图（兼容原文件自带的封面）。

def set_cover(book_id, data: bytes, media_type: str = "image/jpeg") -> None:
    """写入 / 覆盖某书的服务端封面。``data`` 为空视为**删除**该封面。"""
    bid = str(book_id)
    c = _connect()
    with _lock:
        if not data:
            c.execute("DELETE FROM meta_cover WHERE book_id=?", (bid,))
        else:
            c.execute(
                "INSERT INTO meta_cover(book_id, data, media_type) VALUES(?,?,?) "
                "ON CONFLICT(book_id) DO UPDATE SET data=excluded.data, "
                "media_type=excluded.media_type",
                (bid, bytes(data), str(media_type or "image/jpeg")),
            )
        c.commit()


def get_cover(book_id) -> "tuple | None":
    """``(data_bytes, media_type)``；无服务端封面返回 ``None``。"""
    row = _connect().execute(
        "SELECT data, media_type FROM meta_cover WHERE book_id=?", (str(book_id),)
    ).fetchone()
    if not row or not row["data"]:
        return None
    return (bytes(row["data"]), row["media_type"] or "image/jpeg")


def cover_ids(bids) -> set:
    """给定 book_id 集合，返回其中**有服务端封面**的 id 集合（一次批量查询）。"""
    ids = [str(x) for x in (bids or [])]
    return _ids_in("meta_cover", ids)


# ---------------- 批量生效元数据（列表 / 卡片合并用）----------------
# 列表 / 卡片 / 搜索 / OPDS 都要按 override > online > opf 展示服务端元数据，
# 但 ``library.books()`` 是热路径，必须**一次批量取全**（靠扫描缓存 TTL 摊销），
# 严禁逐书两次查库（get_overrides + get_online）。
#
#: 服务端可参与合并的字段（对齐 ``fileops.METADATA_FIELDS``，无封面）
_META_FIELDS = ("title", "author", "series", "series_index", "date",
                "publisher", "language", "description", "tags", "isbn", "narrators",
                "subtitle", "google_books_id", "goodreads_id", "amazon_id", "hardcover_id",
                "openlibrary_id", "itunes_id", "kobo_id", "aladin_id", "audible_id")
#: DB 字段名 → 书对象键（``date`` 在书目里叫 ``year``）
_META_BOOK_KEY = {"date": "year"}


def _ids_in(table: str, ids: list) -> set:
    """分片执行 ``SELECT book_id FROM <table> WHERE book_id IN (...)``，返回命中集合。

    SQLite 对 IN 参数数量有上限（默认 ~999），书库单次扫描可能上千，故按 500 分片。
    """
    if not ids:
        return set()
    c = _connect()
    out: set = set()
    with _lock:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = ",".join("?" * len(chunk))
            rows = c.execute(
                f"SELECT book_id FROM {table} WHERE book_id IN ({q})", chunk
            ).fetchall()
            out.update(r["book_id"] for r in rows)
    return out


def _parse_tags(value) -> list:
    """把 DB 里存的 tags 解析成列表：兼容 ``str(list)``（抓取/编辑写入）与分隔符串。"""
    s = str(value or "").strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        try:
            val = ast.literal_eval(s)
            if isinstance(val, (list, tuple, set)):
                return [str(t).strip() for t in val if str(t).strip()]
        except (ValueError, SyntaxError):
            pass
    return [t.strip() for t in re.split(r"[、,，;/|]", s) if t.strip()]


def get_effective_meta(bids) -> dict:
    """批量返回 ``{book_id: {book_key: value}}``：合并 override > online。

    只返回 override / online 里**确有值**的字段（opf 原值由 ``library`` 自己兜底）。
    ``tags`` 解析成列表（与书对象一致）；``date`` 映射成 ``year``；其余字符串。
    """
    ids = [str(x) for x in (bids or [])]
    if not ids:
        return {}
    ov: dict = {}
    on: dict = {}
    c = _connect()
    with _lock:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = ",".join("?" * len(chunk))
            for r in c.execute(
                f"SELECT book_id, field, value FROM meta_override WHERE book_id IN ({q})", chunk
            ).fetchall():
                ov.setdefault(r["book_id"], {})[r["field"]] = r["value"]
            for r in c.execute(
                f"SELECT book_id, field, value FROM meta_online WHERE book_id IN ({q})", chunk
            ).fetchall():
                on.setdefault(r["book_id"], {})[r["field"]] = r["value"]
    out: dict = {}
    for bid in ids:
        o = ov.get(bid, {})
        n = on.get(bid, {})
        merged: dict = {}
        for f in _META_FIELDS:
            # 哨兵：用户显式要求「这个字段没有值」（清空系列序号 / 清空某个抓来的字段）。
            # 必须**带着无值**并进结果 —— 否则 library 那边只会保留文件里的旧值，
            # 而在线值也会被重新填上（清空就等于没做）。
            if is_cleared(f, o.get(f)):
                merged[_META_BOOK_KEY.get(f, f)] = _meta_out(f, META_CLEAR)
                continue
            if o.get(f) and str(o[f]).strip():
                v = o[f]
            elif n.get(f) and str(n[f]).strip():
                v = n[f]
            else:
                continue
            if f in ("tags", "narrators"):
                merged[_META_BOOK_KEY.get(f, f)] = _parse_tags(v)
            else:
                merged[_META_BOOK_KEY.get(f, f)] = str(v)
        if merged:
            out[bid] = merged
    return out


# ---------------- 作者元数据（第 8 期 D1/D2/D5）----------------
# 在线抓取的 bio/photo 与用户本地覆盖（bio_local / photo_local_path）分开存：
# 展示取 本地覆盖 > 在线；用户改过的不会被再次抓取冲掉。

def upsert_author(name, bio="", photo_path="", photo_source="") -> None:
    """写入在线抓取的作者信息（bio / 照片缓存名 / 来源）。**不动**用户本地覆盖列。"""
    now = time.time()
    c = _connect()
    with _lock:
        c.execute(
            """INSERT INTO authors(name, bio, photo_path, photo_source, fetched_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 bio=excluded.bio, photo_path=excluded.photo_path,
                 photo_source=excluded.photo_source, fetched_at=excluded.fetched_at""",
            (str(name), str(bio or ""), str(photo_path or ""), str(photo_source or ""), now),
        )
        c.commit()


def get_author(name) -> "dict | None":
    row = _connect().execute("SELECT * FROM authors WHERE name=?", (str(name),)).fetchone()
    return dict(row) if row else None


def all_authors() -> dict:
    """``{name: row}``，供批量操作一次取全。"""
    rows = _connect().execute("SELECT * FROM authors").fetchall()
    return {r["name"]: dict(r) for r in rows}


def all_narrators() -> dict:
    """``{name: row}``，供批量操作一次取全（第 53 期，镜像 all_authors）。"""
    rows = _connect().execute("SELECT * FROM narrators").fetchall()
    return {r["name"]: dict(r) for r in rows}


def get_narrator(name) -> "dict | None":
    """取单个演播者行（第 53 期，镜像 get_author）。"""
    row = _connect().execute("SELECT * FROM narrators WHERE name=?", (str(name),)).fetchone()
    return dict(row) if row else None


def set_narrator_sort_name_local(name, value) -> None:
    """设置/清除演播者排序名的本地覆盖（空串 = 撤销覆盖，回退到派生排序名/显示名）。用 upsert。"""
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO narrators(name, sort_name_local) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET sort_name_local=excluded.sort_name_local",
            (str(name), str(value or "").strip()),
        )
        c.commit()


def set_narrator_sort_name(name, value) -> None:
    """写入派生/在线排序名（``sort_name`` 列，第 53 期回填用）。与本地覆盖列**分列**，回填只碰这一列。"""
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO narrators(name, sort_name) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET sort_name=excluded.sort_name",
            (str(name), str(value or "").strip()),
        )
        c.commit()


def set_author_bio_local(name, bio) -> None:
    """设置/清除用户本地传记覆盖（空串 = 撤销覆盖，回退到在线传记）。

    用 upsert 而非 UPDATE：作者可能从没抓取过（表里没有行），只编辑传记时也要能落库。
    """
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO authors(name, bio_local) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET bio_local=excluded.bio_local",
            (str(name), str(bio or "").strip()),
        )
        c.commit()


def set_author_photo_local(name, path) -> None:
    """设置/清除用户本地头像覆盖（空串 = 撤销覆盖，回退到在线照片）。用 upsert，理由同上。"""
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO authors(name, photo_local_path) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET photo_local_path=excluded.photo_local_path",
            (str(name), str(path or "").strip()),
        )
        c.commit()


def set_author_sort_name_local(name, value) -> None:
    """设置/清除作者排序名的本地覆盖（空串 = 撤销覆盖，回退到在线排序名/显示名）。用 upsert，理由同上。"""
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO authors(name, sort_name_local) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET sort_name_local=excluded.sort_name_local",
            (str(name), str(value or "").strip()),
        )
        c.commit()


def set_author_sort_name(name, value) -> None:
    """写入**派生/在线**排序名（``sort_name`` 列，第 43 期回填用）。

    与 :func:`set_author_sort_name_local` **分列**：后者是用户覆盖、前者是系统派生值；
    展示取 本地覆盖 > 派生（见 ``core/authors.sort_name_of``）。回填只碰这一列，
    绝不把派生死值写进用户覆盖列（否则界面会误显示成「用户改过」）。
    """
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO authors(name, sort_name) VALUES(?,?) "
            "ON CONFLICT(name) DO UPDATE SET sort_name=excluded.sort_name",
            (str(name), str(value or "").strip()),
        )
        c.commit()


# ---------------- 系列元数据（第 12 期 C3）----------------
# 与作者侧同构：在线值与本地覆盖分列。系列**没有独立实体表**（系列名来自各册
# calibre:series），故本表以系列名为键、按需创建行 —— 一律 upsert。

#: 允许被本地覆盖的列白名单（动态拼 SQL 前的校验，避免任意列名注入）
SERIES_LOCAL_COLS = ("description_local", "publisher_local", "first_year_local", "tags_local")


def upsert_series_meta(name, description="", publisher="", first_year="", tags="",
                       declared_count=0, source="", score=0.0) -> None:
    """写入在线抓取的系列字段。**不动**用户本地覆盖列（与 ``upsert_author`` 同规矩）。"""
    now = time.time()
    try:
        dc = int(declared_count or 0)
    except (TypeError, ValueError):
        dc = 0
    c = _connect()
    with _lock:
        c.execute(
            """INSERT INTO series_meta(name, description, publisher, first_year, tags,
                                       declared_count, source, score, fetched_at)
               VALUES(?,?,?,?,?,?,?,?,?)
               ON CONFLICT(name) DO UPDATE SET
                 description=excluded.description, publisher=excluded.publisher,
                 first_year=excluded.first_year, tags=excluded.tags,
                 declared_count=excluded.declared_count, source=excluded.source,
                 score=excluded.score, fetched_at=excluded.fetched_at""",
            (str(name), str(description or ""), str(publisher or ""), str(first_year or ""),
             str(tags or ""), dc, str(source or ""), float(score or 0.0), now),
        )
        c.commit()


def get_series_meta(name) -> "dict | None":
    row = _connect().execute("SELECT * FROM series_meta WHERE name=?", (str(name),)).fetchone()
    return dict(row) if row else None


def all_series_meta() -> dict:
    """``{name: row}``，供列表页一次取全（避免逐系列查库）。"""
    rows = _connect().execute("SELECT * FROM series_meta").fetchall()
    return {r["name"]: dict(r) for r in rows}


def set_series_local(name, **fields) -> None:
    """设置/清除系列的本地覆盖列（空串 = 撤销该字段的覆盖，回退到在线值）。

    用 upsert 而非 UPDATE：系列可能从没抓取过（表里没有行），只编辑简介时也要能落库。
    列名走 :data:`SERIES_LOCAL_COLS` 白名单 —— 这里是动态拼 SQL，不校验就等于开了注入口子。
    """
    cols = [k for k in fields if k in SERIES_LOCAL_COLS]
    if not cols:
        return
    vals = [str(fields[k] or "").strip() for k in cols]
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO series_meta(name, {cs}) VALUES(?,{qs}) "
            "ON CONFLICT(name) DO UPDATE SET {sets}".format(
                cs=", ".join(cols),
                qs=", ".join("?" for _ in cols),
                sets=", ".join(f"{k}=excluded.{k}" for k in cols),
            ),
            (str(name), *vals),
        )
        c.commit()


# ---------------- 刮削出版台账（第 18 期）----------------

#: 状态机取值（与前端徽标一一对应）：
#:   pending 待刮削 / running 进行中 / ok 已出版 / failed 失败 / skipped 跳过
#:   （库未配成品目录、条目的名字与磁盘形态不一致等「不是错误、但没出版」）
#:   removed 副本已被删除，**待用户确认**（是否连原文件一起删）
#:   kept    用户确认「保留」/ orphan 源已不在、副本成孤本
#:   source_removed 用户确认删除原文件（已移入回收站，副本保留）
#:
#: ⚠️ **只许降级**：检测逻辑只能把 ok 降为 removed / orphan；回到 ok 的唯一路径
#: 是用户显式动作（重新生成副本 / 手动整理后重建）。
SCRAPE_STATUSES = ("pending", "running", "ok", "failed", "skipped",
                   "removed", "kept", "orphan", "source_removed")

#: 可写列白名单（与 update_library 同一思路：过滤后拼 SQL，不认任意键）
_SCRAPE_COLS = {"library_id", "source_rel", "status", "link_rel", "link_mode",
                "link_shared", "src_size", "src_mtime", "embedded", "has_cover",
                "error", "attempts", "force_fetch", "removed_at", "removed_path",
                "confirmed_at", "updated_at"}


def scrape_set(book_id, **fields) -> None:
    """Upsert 一本书的刮削台账（只认 :data:`_SCRAPE_COLS`）。

    ``status`` 的流转合法性由**调用方**保证（见 :data:`SCRAPE_STATUSES` 的降级约定）——
    这里只做存储，不猜语义。
    """
    bid = str(book_id)
    cols = {k: v for k, v in fields.items() if k in _SCRAPE_COLS}
    cols.setdefault("updated_at", time.time())
    c = _connect()
    with _lock:
        names = ", ".join(cols)
        marks = ", ".join("?" * len(cols))
        c.execute(
            f"INSERT INTO scrape_items(book_id, {names}) VALUES(?,{marks}) "
            f"ON CONFLICT(book_id) DO UPDATE SET "
            + ", ".join(f"{k}=excluded.{k}" for k in cols),
            [bid, *cols.values()],
        )
        c.commit()


def scrape_get(book_id) -> "dict | None":
    row = _connect().execute(
        "SELECT * FROM scrape_items WHERE book_id=?", (str(book_id),)
    ).fetchone()
    return dict(row) if row else None


def scrape_remap_item(old_id, new_id, **fields) -> int:
    """把出版物台账从 ``old_id`` 改挂到 ``new_id``，并顺带改写库相关列。返回搬动行数。

    为什么不进 :func:`remap_book_id`：台账在 ``book_id`` 之外还有 ``library_id`` /
    ``source_rel`` / ``link_rel`` 三个**库相关**列 —— 换库时「在哪个库、源相对哪个库根、
    副本在哪个成品目录」全变，改名时至少 ``source_rel`` 变。通用搬迁只改 book_id，
    让它顺手改这三列等于把出版物语义塞进一个只认 id 的函数。所以走这里，
    由**移动**与**改名**两条路径共用（见 :data:`REMAP_EXPLICIT_TABLES`）。

    行为约定：

    - **没有台账行就什么都不做**（返回 0）：不造假行 —— 书可能压根没经过刮削。
    - ``old_id == new_id`` 时是「**只改列**」：只换了目录（层级整理）时 id 并不变，
      但 ``source_rel`` 变了，台账不能还指着一条已经不在的路径。
    - 目标 id 上**已有台账行则不搬**（返回 0），且**两边都不动**：那行可能正挂着
      「副本被删、待用户确认」（``status='removed'``），静默顶掉等于把待办藏起来；
      旧行也原样留着 —— 它仍如实描述着原库那份副本，而目标库下一轮入库/刮削
      会按书重建台账（自愈），不需要在这里替用户删。
    - 列过滤沿用 :data:`_SCRAPE_COLS` 同一道白名单（拼 SQL 前过滤，不认任意键）。
    - ``status`` **不由本函数转运**：状态机只由检测逻辑降级、或用户显式动作回升
      （见 :data:`SCRAPE_STATUSES`）。这里只负责把「这行属于哪本书、在哪」改对。
    """
    old, new = str(old_id), str(new_id)
    if not old or not new:
        return 0
    cols = {k: v for k, v in (fields or {}).items() if k in _SCRAPE_COLS}
    cols["updated_at"] = time.time()
    c = _connect()
    with _lock:
        if not c.execute("SELECT 1 FROM scrape_items WHERE book_id=?", (old,)).fetchone():
            return 0
        if new != old and c.execute(
                "SELECT 1 FROM scrape_items WHERE book_id=?", (new,)).fetchone():
            return 0
        cur = c.execute(
            "UPDATE scrape_items SET book_id=?, %s WHERE book_id=?"
            % ", ".join(f"{k}=?" for k in cols),
            [new, *cols.values(), old],
        )
        c.commit()
        return int(cur.rowcount or 0)


def scrape_list(library_id=None, status=None, limit=0) -> list:
    """台账列表（最近更新的在前）。``status`` 支持逗号分隔的多值（页面的分段筛选）。"""
    q = "SELECT * FROM scrape_items"
    where, args = [], []
    if library_id:
        where.append("library_id=?")
        args.append(str(library_id))
    statuses = [s.strip() for s in str(status or "").split(",") if s.strip()]
    if len(statuses) == 1:
        where.append("status=?")
        args.append(statuses[0])
    elif statuses:
        where.append("status IN (" + ",".join("?" * len(statuses)) + ")")
        args.extend(statuses)
    if where:
        q += " WHERE " + " AND ".join(where)
    q += " ORDER BY updated_at DESC"
    if limit:
        q += " LIMIT ?"
        args.append(int(limit))
    return [dict(r) for r in _connect().execute(q, args).fetchall()]


def scrape_counts(library_id=None) -> dict:
    """``{状态: 条数}`` 汇总（页面概览条用；一次 GROUP BY，不逐条查）。"""
    q = "SELECT status, COUNT(*) AS n FROM scrape_items"
    args = []
    if library_id:
        q += " WHERE library_id=?"
        args.append(str(library_id))
    q += " GROUP BY status"
    return {r["status"]: int(r["n"]) for r in _connect().execute(q, args).fetchall()}


def scrape_pending(limit=20) -> list:
    """取待办条目（队列 worker 用）。

    **不在这里改状态**：状态流转由调用方显式做 —— 否则「取出来了但进程被 kill」
    会让条目永远卡在 running 上。启动时另用 :func:`scrape_reset_running` 兜底。
    """
    rows = _connect().execute(
        "SELECT * FROM scrape_items WHERE status='pending' "
        "ORDER BY updated_at LIMIT ?", (int(limit),)
    ).fetchall()
    return [dict(r) for r in rows]


def scrape_reset_running() -> int:
    """把残留的 ``running`` 打回 ``pending``（上次进程被 kill / 重启时调用）。"""
    c = _connect()
    with _lock:
        cur = c.execute(
            "UPDATE scrape_items SET status='pending', updated_at=? "
            "WHERE status='running'", (time.time(),)
        )
        c.commit()
        return int(cur.rowcount or 0)


def scrape_delete(book_id) -> None:
    c = _connect()
    with _lock:
        c.execute("DELETE FROM scrape_items WHERE book_id=?", (str(book_id),))
        c.commit()


def scrape_delete_by_library(library_id) -> int:
    """移除某库的全部台账行（**只删登记，不动任何文件**）。

    库被移除登记后，这些行没有意义（UI 会显示一堆属于不存在书库的条目）；
    副本文件仍留在成品目录里，由用户自行处置 —— 与「移除库不删文件」一致。
    """
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM scrape_items WHERE library_id=?", (str(library_id),))
        c.commit()
        return int(cur.rowcount or 0)


def scrape_books_in(library_id, book_ids) -> dict:
    """``{book_id: 台账行}`` —— 扫描时一次取全，**避免逐书查库**（热路径）。"""
    ids = [str(x) for x in (book_ids or [])]
    if not ids:
        return {}
    out: dict = {}
    c = _connect()
    with _lock:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            q = ",".join("?" * len(chunk))
            rows = c.execute(
                f"SELECT * FROM scrape_items WHERE library_id=? AND book_id IN ({q})",
                [str(library_id), *chunk],
            ).fetchall()
            for r in rows:
                out[str(r["book_id"])] = dict(r)
    return out


# ---------------- 书库与迁移台账（第 10 期 D8）----------------

#: 库类型：电子书 / 漫画 / 有声书 / 混合通用（决定功能显隐矩阵）
LIBRARY_TYPES = ("ebook", "comic", "audiobook", "mixed")


def list_libraries() -> list:
    rows = _connect().execute(
        "SELECT * FROM libraries ORDER BY sort_order, created_at"
    ).fetchall()
    return [dict(r) for r in rows]


def get_library(lid) -> "dict | None":
    row = _connect().execute("SELECT * FROM libraries WHERE id=?", (str(lid),)).fetchone()
    return dict(row) if row else None


def _norm_source_dirs(value) -> str:
    """把 source_dirs 入参规整为 JSON 数组文本（入库统一形态）。

    接受：list / tuple / JSON 文本；空或非法则回落为空数组文本。
    """
    if isinstance(value, (list, tuple)):
        arr = [str(x) for x in value]
    elif isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            arr = [str(x) for x in parsed] if isinstance(parsed, (list, tuple)) else [value]
        except Exception:
            arr = [value]
    else:
        arr = []
    return json.dumps(arr, ensure_ascii=False)


def create_library(lid, name, type_, source_dirs="", rules="", sort_order=0,
                   settings="", watch=1, scan_interval=0, scan_cron="",
                   publish_path="", icon="", allowed_exts="", exclude="") -> dict:
    """建库。``settings`` 是每库覆盖的 JSON 文本（第 13 期）。

    ``watch`` / ``scan_interval`` / ``scan_cron`` 是逐库扫描调度（第 17 期 T2）：
    默认 watch=1（开）、scan_interval=0（继承全局）、scan_cron=""（不启用定时）。

    ``publish_path`` 是刮削出版的成品目录（第 18 期）：空 = 该库不产出硬链接副本。

    ``icon`` / ``allowed_exts`` / ``exclude`` 是新库向导三列（第 40 期）：分别是图标名、
    该库扫描白名单（JSON 数组文本）、库级排除图案（JSON 数组文本）。后两者空串 =
    **没设过**（读时回落库类型默认 / 不过滤），不是空集合 —— 见建表处的列注释。
    """
    try:
        w = int(watch or 0)
    except (TypeError, ValueError):
        w = 1
    try:
        si = int(scan_interval or 0)
    except (TypeError, ValueError):
        si = 0
    c = _connect()
    with _lock:
        c.execute(
            # upsert 写法同 task_create；libraries 的 17 列在 INSERT 列表里全给了，
            # 所以逐列 DO UPDATE 与 SQLite 的「删旧插新」**逐字段等价**
            # （last_scan_at / last_scan_note 在 VALUES 里就是字面量 0 与 ''）。
            "INSERT INTO libraries"
            "(id, name, type, source_dirs, rules,"
            " settings, sort_order, created_at, last_scan_at, last_scan_note,"
            " watch, scan_interval, scan_cron, publish_path,"
            " icon, allowed_exts, exclude) "
            "VALUES(?,?,?,?,?,?,?,?,0,'',?,?,?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "name=excluded.name, type=excluded.type, source_dirs=excluded.source_dirs, "
            "rules=excluded.rules, settings=excluded.settings, "
            "sort_order=excluded.sort_order, created_at=excluded.created_at, "
            "last_scan_at=excluded.last_scan_at, last_scan_note=excluded.last_scan_note, "
            "watch=excluded.watch, scan_interval=excluded.scan_interval, "
            "scan_cron=excluded.scan_cron, publish_path=excluded.publish_path, "
            "icon=excluded.icon, allowed_exts=excluded.allowed_exts, "
            "exclude=excluded.exclude",
            (str(lid), str(name), str(type_), _norm_source_dirs(source_dirs),
             str(rules or ""), str(settings or ""), int(sort_order or 0), time.time(),
             w, si, str(scan_cron or ""), str(publish_path or ""),
             str(icon or ""), str(allowed_exts or ""), str(exclude or "")),
        )
        c.commit()
    return get_library(lid) or {}


#: update_library 允许改的列（白名单，避免把任意键拼进 SQL）。
#: ⚠️ 新增列**必须**同时加进来，否则 update_library 会**静默写不进**
#: （它是「过滤后为空就原样返回」，不报错）。
_LIBRARY_COLS = {"name", "type", "source_dirs", "rules", "settings", "sort_order",
                 "watch", "scan_interval", "scan_cron", "publish_path",
                 "last_scan_at", "last_scan_note",
                 # 第 40 期新库向导三列
                 "icon", "allowed_exts", "exclude"}


def update_library(lid, **fields) -> "dict | None":
    cols = {k: v for k, v in fields.items() if k in _LIBRARY_COLS}
    if not cols:
        return get_library(lid)
    c = _connect()
    with _lock:
        c.execute(
            "UPDATE libraries SET " + ", ".join(f"{k}=?" for k in cols) + " WHERE id=?",
            (*cols.values(), str(lid)),
        )
        c.commit()
    return get_library(lid)


def delete_library(lid) -> bool:
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM libraries WHERE id=?", (str(lid),))
        c.commit()
    return bool(cur.rowcount)


def set_library_scan(lid, note="") -> None:
    c = _connect()
    with _lock:
        c.execute("UPDATE libraries SET last_scan_at=?, last_scan_note=? WHERE id=?",
                  (time.time(), str(note or ""), str(lid)))
        c.commit()


# ---- 迁移台账（幂等 + 回滚依据）----

def migration_add(batch_id, direction, library_id, src, dst, status="pending", error="") -> int:
    c = _connect()
    with _lock:
        cur = c.execute(
            "INSERT INTO library_migrations"
            "(batch_id, direction, library_id, src, dst, status, error, created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (str(batch_id), str(direction), str(library_id), str(src), str(dst),
             str(status), str(error or ""), time.time()),
        )
        c.commit()
        return int(cur.lastrowid or 0)


def migration_mark(row_id, status, error="") -> None:
    c = _connect()
    with _lock:
        c.execute("UPDATE library_migrations SET status=?, error=? WHERE id=?",
                  (str(status), str(error or ""), int(row_id)))
        c.commit()


def migration_batch(batch_id) -> list:
    rows = _connect().execute(
        "SELECT * FROM library_migrations WHERE batch_id=? ORDER BY id", (str(batch_id),)
    ).fetchall()
    return [dict(r) for r in rows]


def migration_batches(limit=20) -> list:
    rows = _connect().execute(
        "SELECT batch_id, direction, COUNT(*) n, MIN(created_at) at "
        "FROM library_migrations GROUP BY batch_id, direction ORDER BY at DESC LIMIT ?",
        (int(limit),),
    ).fetchall()
    return [dict(r) for r in rows]


def migration_last_batch(direction="move") -> str:
    """最近一次某方向的批次（回滚默认取最近一次 move 批次）。"""
    row = _connect().execute(
        "SELECT batch_id FROM library_migrations WHERE direction=? ORDER BY id DESC LIMIT 1",
        (str(direction),),
    ).fetchone()
    return row["batch_id"] if row else ""


# ---- 运行态 KV（app_state）----

def state_get(key, default="") -> str:
    row = _connect().execute("SELECT value FROM app_state WHERE key=?", (str(key),)).fetchone()
    return row["value"] if row else str(default)


def state_set(key, value) -> None:
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO app_state(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (str(key), str(value or ""), time.time()),
        )
        c.commit()


def state_delete(key) -> None:
    c = _connect()
    with _lock:
        c.execute("DELETE FROM app_state WHERE key=?", (str(key),))
        c.commit()


# ---------------- 回收站台账（第 81 期）----------------
# ⚠️ 这张表**刻意不含 book_id**（见建表处的注释）：它记的是「磁盘上某个被移走的路径」，
# 不是「某本书的数据」—— 改名 / 换库 / 删库都不会让它失效，因此**不进 remap 四处清单**。
# 写台账**永不外抛**（`recycle_add` 的调用方是回收动作本身，记账失败不该让回收失败）。

def recycle_add(orig_path, recycled_name, why="", size=0) -> int:
    """记一条回收台账，返回行 id。**只记账，不动文件**。"""
    c = _connect()
    with _lock:
        cur = c.execute(
            "INSERT INTO recycle_items"
            "(orig_path, recycled_name, why, size, created_at) VALUES(?,?,?,?,?)",
            (str(orig_path or ""), str(recycled_name or ""), str(why or ""),
             int(size or 0), time.time()),
        )
        c.commit()
        return int(cur.lastrowid or 0)


def recycle_note(orig_path, recycled_name, why="", size=0) -> None:
    """:func:`recycle_add` 的**永不外抛**版本。

    调用方是回收动作本身（把文件移进回收站）—— 记账失败**绝不能**让回收失败，
    否则「文件已移走、台账没写上」会变成「报错了但文件其实已经不在原地」的更糟形态。
    """
    try:
        recycle_add(orig_path, recycled_name, why=why, size=size)
    except Exception:                                  # noqa: BLE001
        logging.getLogger("novelforge").exception("写回收台账失败：%s", orig_path)


def recycle_list(limit: int = 0) -> list:
    """回收台账（新 → 旧）。``limit`` 为 0 表示不截断。"""
    sql = "SELECT * FROM recycle_items ORDER BY id DESC"
    params: tuple = ()
    if limit and int(limit) > 0:
        sql += " LIMIT ?"
        params = (int(limit),)
    rows = _connect().execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def recycle_get(rid) -> "dict | None":
    row = _connect().execute(
        "SELECT * FROM recycle_items WHERE id=?", (int(rid),)
    ).fetchone()
    return dict(row) if row else None


def recycle_delete(rid) -> None:
    c = _connect()
    with _lock:
        c.execute("DELETE FROM recycle_items WHERE id=?", (int(rid),))
        c.commit()


def recycle_clear() -> int:
    """清空台账（「清空回收站」的真删路径同批调它），返回删除行数。"""
    c = _connect()
    with _lock:
        cur = c.execute("DELETE FROM recycle_items")
        c.commit()
        return int(cur.rowcount or 0)


def _sync_attempt(c, bid, status, st, fin, now) -> None:
    """阅读状态变化时同步「阅读尝试（轮次）」（第 43 期）。**复用调用方的游标与锁**。

    · 进入 reading  → 没有进行中的那一轮就开一轮（有则不动，避免重复开）；
    · 进入 finished → 有进行中的那一轮就收尾；一轮都没有就补一条「已完成」的单轮；
    · paused / abandoned / unread → 不动（搁置不是「读完」，历史轮次也不该被状态回退抹掉）。
    """
    if status not in ("reading", "finished"):
        return
    cur = c.execute(
        "SELECT id FROM reading_attempts WHERE book_id=? AND finished_at=0 "
        "ORDER BY round DESC, id DESC LIMIT 1", (bid,)
    ).fetchone()
    if status == "reading":
        if cur:
            return
        mx = c.execute(
            "SELECT COALESCE(MAX(round), 0) AS m FROM reading_attempts WHERE book_id=?", (bid,)
        ).fetchone()
        c.execute(
            "INSERT INTO reading_attempts(book_id, round, started_at, finished_at, status, created_at) "
            "VALUES(?,?,?,?,?,?)", (bid, int(mx["m"] or 0) + 1, st, 0.0, "reading", now),
        )
        return
    # finished
    if cur:
        c.execute(
            "UPDATE reading_attempts SET finished_at=?, status='finished' WHERE id=?",
            (fin, cur["id"]),
        )
        return
    mx = c.execute(
        "SELECT COALESCE(MAX(round), 0) AS m FROM reading_attempts WHERE book_id=?", (bid,)
    ).fetchone()
    c.execute(
        "INSERT INTO reading_attempts(book_id, round, started_at, finished_at, status, created_at) "
        "VALUES(?,?,?,?,?,?)", (bid, int(mx["m"] or 0) + 1, st, fin, "finished", now),
    )


def set_status(book_id, status, started_at=None, finished_at=None) -> dict:
    """设置阅读状态并维护起止日期。

    日期规则（保证状态与日期不自相矛盾）：
      · 进入 reading/finished 且 started_at 为空 → 记为现在（开始读过才谈得上读）；
      · 进入 finished 且 finished_at 为空 → 记为现在；
      · 离开 finished → finished_at 清零（「读完」的日期只对「已读完」有意义）；
      · 回到 unread → 两个日期都清零（重来一遍）。
    显式传入的日期优先 —— 详情页允许手工修正历史日期。
    """
    if status not in READ_STATUSES:
        raise ValueError("未知阅读状态: %r" % (status,))
    cur_row = get_status(book_id)
    now = time.time()
    st = float(started_at) if started_at else cur_row.get("started_at") or 0
    fin = float(finished_at) if finished_at else cur_row.get("finished_at") or 0

    if status in ("reading", "finished") and not st:
        st = now
    if status == "finished" and not fin:
        fin = now
    if status != "finished":
        fin = 0.0
    if status == "unread":
        st = 0.0
    if status in ("paused", "abandoned"):
        pass  # 搁置/弃读保留已开始的日期，它记录的是「什么时候开始翻的」

    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO reading_status(book_id, status, started_at, finished_at, updated_at) "
            "VALUES(?,?,?,?,?) ON CONFLICT(book_id) DO UPDATE SET status=excluded.status, "
            "started_at=excluded.started_at, finished_at=excluded.finished_at, "
            "updated_at=excluded.updated_at",
            (str(book_id), status, st, fin, now),
        )
        _sync_attempt(c, str(book_id), status, st, fin, now)
        c.commit()
    return {"book_id": str(book_id), "status": status,
            "started_at": st, "finished_at": fin, "updated_at": now}


# ---------------- 阅读尝试 / 重读（第 43 期）----------------
# 一轮 = 「开始读 → 读完」；读完后重新开始＝新一轮。轮次由 db.set_status 自动维护
# （见 _sync_attempt），也可由用户显式「再来一遍」（start_attempt）或从历史补录（backfill_attempts）。

def list_attempts(book_id) -> list:
    """按轮次升序返回这本书的阅读尝试。"""
    rows = _connect().execute(
        "SELECT * FROM reading_attempts WHERE book_id=? ORDER BY round ASC, id ASC",
        (str(book_id),),
    ).fetchall()
    return [dict(r) for r in rows]


def current_attempt(book_id) -> "dict | None":
    """当前**进行中**（未读完）的那一轮，没有则 None。"""
    r = _connect().execute(
        "SELECT * FROM reading_attempts WHERE book_id=? AND finished_at=0 "
        "ORDER BY round DESC, id DESC LIMIT 1", (str(book_id),)
    ).fetchone()
    return dict(r) if r else None


def start_attempt(book_id, started_at=None) -> dict:
    """开新一轮阅读（「再来一遍」）。**幂等**：已有进行中的那一轮就原样返回，不重复开。"""
    bid = str(book_id)
    now = time.time()
    st = float(started_at) if started_at else now
    c = _connect()
    with _lock:
        cur = c.execute(
            "SELECT * FROM reading_attempts WHERE book_id=? AND finished_at=0 "
            "ORDER BY round DESC, id DESC LIMIT 1", (bid,)
        ).fetchone()
        if cur:
            return dict(cur)
        mx = c.execute(
            "SELECT COALESCE(MAX(round), 0) AS m FROM reading_attempts WHERE book_id=?", (bid,)
        ).fetchone()
        rnd = int(mx["m"] or 0) + 1
        c.execute(
            "INSERT INTO reading_attempts(book_id, round, started_at, finished_at, status, created_at) "
            "VALUES(?,?,?,?,?,?)", (bid, rnd, st, 0.0, "reading", now),
        )
        c.commit()
        r = c.execute(
            "SELECT * FROM reading_attempts WHERE book_id=? AND round=?", (bid, rnd)
        ).fetchone()
    return dict(r)


def finish_attempt(book_id, finished_at=None) -> "dict | None":
    """收尾进行中的那一轮。**没有进行中的轮次就返回 None**（不凭空造行）。"""
    bid = str(book_id)
    fin = float(finished_at) if finished_at else time.time()
    c = _connect()
    with _lock:
        cur = c.execute(
            "SELECT id FROM reading_attempts WHERE book_id=? AND finished_at=0 "
            "ORDER BY round DESC, id DESC LIMIT 1", (bid,)
        ).fetchone()
        if not cur:
            return None
        c.execute(
            "UPDATE reading_attempts SET finished_at=?, status='finished' WHERE id=?",
            (fin, cur["id"]),
        )
        c.commit()
        r = c.execute("SELECT * FROM reading_attempts WHERE id=?", (cur["id"],)).fetchone()
    return dict(r)


def delete_attempts(book_id) -> int:
    c = _connect()
    with _lock:
        n = int(c.execute(
            "DELETE FROM reading_attempts WHERE book_id=?", (str(book_id),)
        ).rowcount or 0)
        c.commit()
    return n


def backfill_attempts() -> dict:
    """从既有 ``reading_status`` 的起止日期补录**一轮**尝试（第 43 期一次性历史补录）。

    只补「一轮都没有」的书；不动 ``reading_status``，也不覆盖已有轮次。
    ``finished_at > 0`` 的补成已完成轮，否则补成进行中轮。返回 ``{created: n}``。
    """
    c = _connect()
    now = time.time()
    created = 0
    with _lock:
        rows = c.execute(
            "SELECT book_id, started_at, finished_at FROM reading_status "
            "WHERE started_at > 0 OR finished_at > 0"
        ).fetchall()
        for r in rows:
            bid = str(r["book_id"])
            if c.execute(
                "SELECT 1 FROM reading_attempts WHERE book_id=? LIMIT 1", (bid,)
            ).fetchone():
                continue
            fin = float(r["finished_at"] or 0)
            st = float(r["started_at"] or 0) or fin or now
            c.execute(
                "INSERT INTO reading_attempts(book_id, round, started_at, finished_at, status, created_at) "
                "VALUES(?,?,?,?,?,?)",
                (bid, 1, st, fin, "finished" if fin else "reading", now),
            )
            created += 1
        c.commit()
    return {"created": created}


def reset_reading_state(book_id) -> dict:
    """**从头开始**：删掉这本书的阅读会话、阅读进度、阅读状态与阅读尝试（第 34 期，第 43 期加尝试）。

    只清这些「读出来的痕迹」，因为它们的语义都是「这一次阅读」：
      · ``reading_sessions`` —— 时长与会话数（阅读记录 / 统计 / 成就都读它）；
      · ``progress`` —— 停在哪儿；
      · ``reading_status`` —— 读到什么程度（连行一起删，回到「没有状态行」的初态）；
      · ``reading_attempts`` —— 轮次历史（「读过几遍」的计数，第 43 期）。

    **刻意不动**的东西：批注 / 书签 / 评分 / 收藏 / 元数据覆盖 ——
    它们是**关于这本书的内容**，不是「读过」的痕迹；顺手删掉就是把用户的笔记一起清了。
    也不动已解锁的成就：成就的既定机制是「只解锁不回退」（见 core/achievements.py）。

    ⚠️ 只删 DB 行，**绝不碰磁盘上的文件**（源不可变是全局硬约定）。
    返回 ``{sessions, progress, status, attempts}`` 四处的删除行数。
    """
    bid = str(book_id)
    c = _connect()
    with _lock:
        n_sessions = int(c.execute(
            "DELETE FROM reading_sessions WHERE book_id=?", (bid,)
        ).rowcount or 0)
        n_progress = int(c.execute(
            "DELETE FROM progress WHERE book_id=?", (bid,)
        ).rowcount or 0)
        n_status = int(c.execute(
            "DELETE FROM reading_status WHERE book_id=?", (bid,)
        ).rowcount or 0)
        n_attempts = int(c.execute(
            "DELETE FROM reading_attempts WHERE book_id=?", (bid,)
        ).rowcount or 0)
        c.commit()
    return {"sessions": n_sessions, "progress": n_progress, "status": n_status,
            "attempts": n_attempts}
