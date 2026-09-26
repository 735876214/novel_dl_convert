"""PostgreSQL 后端（第 62 期）：与 SQLite 那条路**同窄**的一条连接层。

本模块只做一件事：让 ``db.py`` 那 198 个函数、169 处调用点**一行不改**地跑在 PG 上。
它实现的是 ``db._Conn`` 那个窄接口（``execute`` / ``executemany`` / ``executescript``
/ ``commit`` / ``rollback``），返回同形的 ``_Result``；SQL 的方言差异全部由
:mod:`novelforge.core.sqlcompat` 在这一层抹平。

为什么是「单连接」而不是连接池
------------------------------
``db.py`` 的设计是**一个连接 + 一把全局 RLock**（第 39 期实测：SQLite 不保证
同连接多线程并发，读路径不持锁会抛 InterfaceError 甚至段错误）。那把锁把每条语句
都串行化了 —— 在它后面挂一个连接池，池里的连接永远只有一个在被用（其余在锁外排队），
只是多了一层簿记。PG 支持真并发没错，但**拆锁是另一件事**：那会改变语义
（`_lock` 现在也保护着「读-改-写」这类多语句序列），回归面远大于收益。
所以这里照旧单连接；要并发是将来单独一期的事。

三处必须与 SQLite 不同、且**不能静默**的地方
------------------------------------------
1. **RETURNING id**：``db.py`` 有 8 处 ``cur.lastrowid``（插完要拿自增主键）。
   PG 没有 lastrowid ⇒ 适配层在 INSERT 上自动追加 ``RETURNING id``，把取回的值
   填进 ``_Result.lastrowid``，**并把那行从结果里摘掉**（SQLite 的 INSERT 不产生
   结果集，调用点若 ``fetchone()`` 会拿到 None —— 保持这个口径才是等价的）。
   只对**确实有 id 列**的表追加（查一次 information_schema 并缓存）。
2. **语句失败会作废整个事务**：SQLite 里一条语句报错，后面的照跑；PG 里事务进入
   aborted 状态，后续每条都回 ``current transaction is aborted``。全仓有 3 处
   ``try/except`` 包着 SQL（都在「表可能不存在」的探测上），不处理的话那 3 处的
   异常会被吞掉、**紧接着的语句全部报另一个错**，现场与根因完全对不上。
   故 :meth:`PgConn.execute` 出错后先 ``rollback()`` 把连接恢复成可用状态再抛出，
   代价是那一笔未提交的改动一并丢弃 —— 对那 3 处只读探测无影响，而对写路径
   「全丢」好过「写一半」（改名 / 迁移这类多语句序列本就该是原子的）。
3. **自动预备语句必须关掉**：psycopg 默认在第 5 次执行后把语句转成 prepared
   statement，而本仓会在运行期建表 / 改表（``init`` 的补列迁移、测试的整库重建）。
   表结构一变，缓存计划就失效并抛 ``cached plan must not change result type`` ——
   一个只在「跑过几轮之后」才炸的错。``prepare_threshold=None`` 表示从不预备。
4. **事务的边界与 sqlite3 不同**（第 62 期实测，卡死过全量测试）：psycopg 在
   ``autocommit=False`` 下对**每条语句**都隐式 ``BEGIN`` —— 包括 SELECT；而
   python 的 ``sqlite3`` 只对 DML（INSERT/UPDATE/DELETE/REPLACE）开事务，
   非 DML 语句前还会把挂起的那笔**先提交掉**，语句本身在 autocommit 下跑。
   不补齐这个差异，PG 上「读一次」就会留下一个 ``idle in transaction`` 的连接攥着
   ``ACCESS SHARE`` 锁 —— 实测后果是测试夹具的 ``DROP SCHEMA … CASCADE``
   在 ``wait_event_type=Lock`` 上**无限期等待**，全量测试跑到 4% 再也不动。
   对齐逻辑在 :meth:`PgConn._settle`。

schema 与 ``NOVELFORGE_PG_RESET``
--------------------------------
表建在 ``NOVELFORGE_PG_SCHEMA``（默认 ``public``）里。测试的**用例级隔离**靠每个用例
把 schema 整个重建（``tests/conftest.py::isolated`` 显式调 :func:`drop_schema`）。

⚠️ 这个动作**不在** ``db.close()`` 里，尽管第一版那么写过：SQLite 侧的用例级隔离
靠的是**换 DATA_DIR**（每个用例一个全新临时目录），close() 只是关连接、从不删数据。
把它挂到 close() 上，「``close()`` + ``init()`` 模拟一次重启」的升级用例就变成
「把库删了重建」—— 三个这样的用例当场炸了。

``NOVELFORGE_PG_RESET=1`` 是「这个库是测试草稿纸」的开关，见 :func:`reset_enabled`。
"""
from __future__ import annotations

import os
import re
import sys
import threading

from . import sqlcompat

#: 连接串。选 pg 后端时必须给 —— 半配置状态（选了 pg 却没 DSN）在这里**直接报错**，
#: 比连上某个意外的库、或者在别处抛一个「连接串是空串」要容易查得多。
_DSN_ENV = "NOVELFORGE_PG_DSN"
_SCHEMA_ENV = "NOVELFORGE_PG_SCHEMA"
_RESET_ENV = "NOVELFORGE_PG_RESET"

#: ``INSERT`` 的表名（适配层要在它后面追加 RETURNING）。
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+([A-Za-z_][A-Za-z0-9_$]*)", re.I)
_RETURNING_RE = re.compile(r"\bRETURNING\b", re.I)

#: 会改数据的语句（DML）—— **只有它们在 sqlite3 的老事务模型里会隐式开一个事务**，
#: 也只有它们该把事务留给调用点的 ``commit()``。其余语句（SELECT / DDL / SHOW）
#: 既不进事务、还要把挂起的那笔先提交掉。见 :meth:`PgConn._settle`。
_DML_RE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)

#: 重建 schema 时等锁的上限（毫秒）。挡路的通常是**已经没人再用**的残留连接
#: （见 :func:`_clear_stuck`），但「没人再用」不等于「一定不在锁上」—— 不给上限
#: 就是安静地停住，实测表现是「全量测试跑到 4% 再也不动」，最难查的一类失败。
_LOCK_TIMEOUT_MS = 5000


class PgUnavailable(RuntimeError):
    """PG 后端不可用（没装驱动 / 没给 DSN / 连不上）—— **不降级**，直接失败。

    静默回落 SQLite 是这里最坏的一种「容错」：部署方以为数据进了 PG，
    实际写进了容器里一个随时会被丢掉的本地文件。
    """


_conn: "PgConn | None" = None
#: 只保护「连接的建立与替换」。语句的串行由 ``db._lock`` 负责（由 :func:`connect`
#: 传进来，见 :class:`PgConn`）—— 两把锁分工明确，不要在这里再实现一遍语句级串行
#: （那会和 db._lock 形成锁序问题）。
_guard = threading.Lock()


class _NoLock:
    """没传锁时的占位（``with`` 用）—— 只有单线程直连（诊断脚本 / 一次性工具）会走到。

    特意**不**在模块里兜底造一把锁：那样看起来「有串行了」，实际是两把互不相干的锁，
    比不加锁更难查 —— 见 :func:`connect` 的 ``lock`` 参数。
    """

    __slots__ = ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_no_lock = _NoLock()


def _dsn() -> str:
    dsn = (os.getenv(_DSN_ENV) or "").strip()
    if not dsn:
        raise PgUnavailable(
            f"后端选了 PostgreSQL（NOVELFORGE_DB=pg），但没有给 {_DSN_ENV}。"
            f"例：postgresql://novelforge:口令@127.0.0.1:5432/novelforge"
        )
    return dsn


def schema() -> str:
    """表所在的 schema（默认 ``public``）。"""
    s = (os.getenv(_SCHEMA_ENV) or "").strip() or "public"
    # 标识符要进 SQL 文本，且本模块不允许参数化标识符 —— 只放行安全字符，
    # 其余直接拒绝（宁可不给这个能力，也不要一个能拼 SQL 的口子）。
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", s):
        raise PgUnavailable(f"{_SCHEMA_ENV} 只能是字母数字下划线，收到：{s!r}")
    return s


def reset_enabled() -> bool:
    """本进程是不是在「测试模式」下跑（= 这个 PG 库的 schema 会被反复重建）。

    两个消费点，都不是「顺手删表」那种：

    - ``tests/conftest.py``：进 PG 后端却没开这个开关时**直接拒绝开跑** —— 用例级
      隔离靠每个用例重建 schema，不开就是一堆用例互相污染；
    - ``pgmigrate.auto_enabled()``：测试模式下不自动搬迁（见该函数）。

    ⚠️ ``db.close()`` **不**消费它（第一版消费了，被三个「关掉再重开」的升级用例
    当场抓住：close 一删，被测的那份数据在重启之前就没了）。删 schema 由夹具显式调
    :func:`drop_schema`。
    """
    return (os.getenv(_RESET_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


def _psycopg():
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as e:                       # pragma: no cover - 环境问题
        raise PgUnavailable(
            "后端选了 PostgreSQL，但没有装驱动。装：pip install 'psycopg[binary]'"
        ) from e
    return psycopg, dict_row


def _drop() -> None:
    """丢掉缓存的连接（坏掉 / 已关闭时调）—— 下一次 ``connect()`` 会重建。"""
    global _conn
    with _guard:
        _conn = None


def connect(result_cls, lock=None):
    """建（或复用）连接，返回与 ``db._Conn`` 同形的代理。

    ``result_cls`` 由 ``db`` 传入 —— 这样 ``_Result`` 只有一份定义，
    不会出现「PG 的结果对象少一个方法」这种只在某条路径上才炸的差异。

    ``lock`` 是 ``db._lock``（那把全局 RLock）。**必须传**：SQLite 那一侧由
    ``db._Conn`` 持锁，而这条路返回的是本模块的代理，不传就等于**一条语句都没串行**
    —— 两条跨线程的「读-改-写」序列会互相插队。第 62 期把「读也会提交事务」补进来
    之后这件事更要紧了：一次读带出的提交，可能把另一个线程写了一半的序列提交掉。
    """
    global _conn
    with _guard:
        if _conn is not None and not _conn.closed:
            return _conn
        psycopg, dict_row = _psycopg()
        try:
            raw = psycopg.connect(
                _dsn(),
                row_factory=dict_row,      # row["col"] 原样可用（与 sqlite3.Row 同形）
                autocommit=False,
                prepare_threshold=None,    # 见模块文档第 3 条
            )
        except PgUnavailable:
            raise
        except Exception as e:
            raise PgUnavailable(f"连不上 PostgreSQL：{e}") from e
        sch = schema()
        with raw.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{sch}"')
            cur.execute(f'SET search_path TO "{sch}"')
        raw.commit()
        _conn = PgConn(raw, result_cls, lock)
        return _conn


def _clear_stuck(psycopg) -> "list[tuple]":
    """终止本库里所有 ``idle in transaction`` 的连接，返回它们的信息。

    这是本动作**语义上就该有**的一步，不是「容错」：``NOVELFORGE_PG_RESET=1``
    已经声明了这个库是测试草稿纸（见 :func:`reset_enabled`）。而「开着事务却什么
    都不干」的连接在本套测试里只可能是**残留** —— 用例之间 ``db.close()`` 都关了
    自己的连接，能留下这种状态的只有「用例跑完了、又晚一步动手的后台线程」。

    ⚠️ 只动 ``idle in transaction``：**正在跑语句的连接一律不碰**（那可能是并排
    跑着的另一场测试，杀错了比慢一点糟得多）。
    """
    with psycopg.connect(_dsn(), autocommit=True) as con:
        rows = con.execute(
            "SELECT pid, client_port, now() - xact_start, "
            "       left(regexp_replace(coalesce(query, ''), E'[\\n\\r]+', ' ', 'g'), 60) "
            "FROM pg_stat_activity "
            "WHERE datname = current_database() AND pid <> pg_backend_pid() "
            "  AND state = 'idle in transaction'"
        ).fetchall()
        for pid, *_rest in rows:
            con.execute("SELECT pg_terminate_backend(%s)", (pid,))
    return [tuple(r) for r in rows]


def drop_schema() -> None:
    """删掉当前 schema 并重建（**测试专用**，由 ``tests/conftest.py`` 显式调）。

    ⚠️ ``DROP`` 与 ``CREATE`` **必须在同一个事务里**（第一版写成了 autocommit
    下两条独立提交的语句，实测会间歇性地把库留成一个**半死状态**：schema 明明
    建出来了，下一个连接的 ``CREATE TABLE`` 却报
    ``InvalidSchemaName: no schema has been selected to create in``、
    ``current_schema()`` 返回 NULL —— 也就是「按 search_path 找不到这个 schema」。
    偶尔还会在 ``CREATE SCHEMA`` 上直接撞
    ``duplicate key value violates unique constraint "pg_type_typname_nsp_index"``。

    根因是 PG 对**同名 schema 的删后重建**：DROP 删掉的目录行与 CREATE 插进去的
    新行会在 ``pg_type`` 等系统目录的唯一索引上碰面，而分处两个事务时彼此的
    可见性没有保证。合进一个事务，中间就没有「已经删了、还没建好」的窗口。

    ⚠️ 第二条教训（第 62 期实测）：**不要无条件等锁**。``DROP SCHEMA … CASCADE``
    要给 schema 里每张表上 ACCESS EXCLUSIVE，只要有另一条连接在那个库上还开着事务
    （哪怕它 ``idle in transaction``、只是读了一次），这句就会永久等待 ——
    实测 ``pg_stat_activity`` 里 ``wait_event_type=Lock``、事务龄 2 分 53 秒纹丝不动，
    而全量测试从 4% 起再也不动。现在：``lock_timeout`` 到点即失败 → 清掉残留连接 →
    重试一次；仍不行就把原样把错误抛出去（现场比「卡住」好查一百倍）。

    （这套动作只在 ``NOVELFORGE_PG_RESET=1`` 下发生，即测试的用例级隔离；
    生产路径永远不调它 —— 见本模块文档。）
    """
    psycopg, _ = _psycopg()
    sch = schema()
    err: "Exception | None" = None
    for attempt in (1, 2):
        try:
            # 不用 autocommit：`with` 出块时提交，DROP + CREATE 是一笔。
            with psycopg.connect(_dsn()) as con:
                con.execute(f"SET LOCAL lock_timeout = {_LOCK_TIMEOUT_MS}")
                con.execute(f'DROP SCHEMA IF EXISTS "{sch}" CASCADE')
                con.execute(f'CREATE SCHEMA "{sch}"')
            return
        except psycopg.Error as e:
            # 55P03 = lock_not_available（lock_timeout 到点）。**只有这一种**重试：
            # 别的错误（连接断了、语法错）重试只会把同一个错误犯第二遍。
            if getattr(e, "sqlstate", None) != "55P03" or attempt == 2:
                raise
            err = e
            stuck = _clear_stuck(psycopg)
            if not stuck:
                raise
            # 不静默：这件事本身是可诊断的信号（谁在什么时候留下了连接）
            print(f"[pg] 重建 schema 被锁挡住，已终止 {len(stuck)} 条残留连接：{stuck}",
                  file=sys.stderr)
    raise err                                        # pragma: no cover - 循环里已 return/raise


def server_version() -> str:
    """连一次报版本（健康检查 / 启动日志用）。连不上就抛 :class:`PgUnavailable`。"""
    psycopg, _ = _psycopg()
    with psycopg.connect(_dsn(), autocommit=True) as raw:
        with raw.cursor() as cur:
            cur.execute("SHOW server_version")
            row = cur.fetchone()
    return str((row or {}).get("server_version") or "")


class PgConn:
    """``db._Conn`` 的 PG 实现：每条语句走一遍方言适配，结果**在锁内取干净**。

    与 SQLite 版一样，取数的时机是「语句刚跑完」，不是「调用方来 fetch 时」——
    调用方拿到的是一段内存里的行（``_Result``），出锁后再读也安全。
    """

    __slots__ = ("_raw", "_cls", "_id_cols", "_open", "_lock")

    def __init__(self, raw, result_cls, lock=None):
        self._raw = raw
        self._cls = result_cls
        #: 表名 → 有没有 id 列。**只缓存肯定答案**，见 :meth:`_has_id`。
        self._id_cols: dict = {}
        #: 现在有没有一笔**由本适配层开着**的事务（见 :meth:`_settle`）。
        #: 不用 ``info.transaction_status``：那要过一次驱动，而这个标志在每条语句的
        #: 路径上都要读，本地布尔最省事也最直白。
        self._open = False
        #: ``db._lock``。**可以是 None**（单线程直连，例如诊断脚本）——
        #: 那时退化成不加锁，但生产路径永远传进来，见 :func:`connect`。
        self._lock = lock

    # ---- 内部 ----

    def _settle(self) -> None:
        """结束服务端那一笔事务 —— 把 psycopg 对齐到 python ``sqlite3`` 的老事务模型。

        两条规则，都是 sqlite3 的行为，缺一不可：

        1. **只有 DML 才把事务留给调用点**。psycopg 在 ``autocommit=False`` 下对
           **每条语句**（包括 SELECT）都隐式 ``BEGIN``；sqlite3 的 SELECT 压根不进
           事务、DDL 也在 autocommit 下跑完即生效。于是 PG 上「读一次」就留下一个
           ``idle in transaction`` 的连接攥着 ``ACCESS SHARE`` 锁 —— 实测把
           ``DROP SCHEMA … CASCADE`` 永久挡在 ``wait_event_type=Lock`` 上
           （全量测试跑到 4% 停住）。
        2. **非 DML 语句之前，挂起的那笔先提交掉**。这条是 sqlite3 的老规矩
           （"implicitly commits the pending transaction before non-DML statements"），
           所以本仓里「先写后读、最后才 commit」的序列在 SQLite 上一直是那样跑的，
           这里照搬 —— 包括它们「读到一半崩了也不会回滚前面那笔写」的既有行为。

        ⚠️ 判据是 ``_open``（**服务端有没有开着事务**），不是「有没有待提交的写」：
        读也会开事务，第一版拿「有没有写」当判据，等于每次读都不结算（实测过，
        探针里 ``SELECT 1`` 之后连接照样停在 ``idle in transaction``）。
        """
        if self._open:
            try:
                self._raw.commit()
            except Exception as e:                 # noqa: BLE001 —— 走 _fail 的统一清场
                self._fail(e)
                raise
            self._open = False

    @property
    def closed(self) -> bool:
        return bool(getattr(self._raw, "closed", True))

    def _has_id(self, table: str) -> bool:
        """这张表有没有 ``id`` 列（有才值得追加 RETURNING）。

        ⚠️ **否定的答案不缓存**：建表发生在 ``db.init()`` 里，而适配层可能在
        建表前就被问到（同一个进程、同一张表、先问后建）。缓存了否定答案，
        之后每一次 INSERT 都会永远拿不到 lastrowid。
        """
        if self._id_cols.get(table):
            return True
        try:
            with self._raw.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = current_schema() "
                    "AND table_name = %s AND column_name = 'id' "
                    # ⚠️ 判据是 **IDENTITY** 而不是「有 id 列」（第一版写错了，被
                    # `test_features` 当场抓住）：本仓有一半表的 `id` 是 **TEXT 主键**
                    # （libraries / users / tasks / book_dock_items / pref_devices），
                    # 它们的 id 由调用方给，SQLite 的 lastrowid 对它们返回的是**隐式
                    # rowid**（另一回事），没有任何调用点用。照「有 id 列」就去追加
                    # RETURNING，取回来的是 'comic' 这种字符串，`int()` 当场炸。
                    "AND is_identity = 'YES'",
                    (table,),
                )
                # 这句是 SELECT，但在 PG 上它同样开了一笔事务 —— 记上账，
                # 免得它绕过 :meth:`_settle` 变成没人收尾的那一笔。
                self._open = True
                row = cur.fetchone()
        except Exception:                          # noqa: BLE001 —— 问不到就当没有
            return False
        if row:
            self._id_cols[table] = True
            return True
        return False

    def _prepare(self, sql: str):
        """→ ``(可执行 SQL, 是否追加了 RETURNING)``。"""
        # 先 adapt 再 ddl：adapt 负责 `?`→`%s` 与元数据查询改写，ddl 负责把
        # `INTEGER PRIMARY KEY` / `REAL` / `BLOB` 换成 PG 拼写。
        # ⚠️ `ddl` 必须在这里也过一遍，不能只靠 `executescript` 里那次：
        # `db.init()` 的补列迁移（ALTER TABLE … ADD COLUMN）、以及**测试里手写的
        # 建表语句**都是走 `execute()` 的。少了这一遍，一条 `CREATE TABLE x
        # (id INTEGER PRIMARY KEY, …)` 在 PG 上不会变成 IDENTITY，于是插入时
        # `id` 为 NULL 撞非空约束 —— 而且只在「有人手写建表」时才现形。
        stmt = sqlcompat.ddl(sqlcompat.adapt(sql))
        m = _INSERT_RE.match(stmt)
        if m and not _RETURNING_RE.search(stmt) and self._has_id(m.group(1)):
            body = stmt.rstrip()
            semi = ""
            if body.endswith(";"):
                body, semi = body[:-1].rstrip(), ";"
            return f"{body} RETURNING id{semi}", True
        return stmt, False

    def _fail(self, exc: Exception):
        """语句失败后把连接恢复成**可用状态**（见模块文档第 2 条）。"""
        try:
            self._raw.rollback()
        except Exception:                          # noqa: BLE001
            pass
        self._open = False                         # 事务已经被 rollback 掉了
        # 连接本身没了（容器重启 / 网络断）→ 丢掉缓存，让下次 connect() 重建。
        # 其他错误不动连接：一条写错的 SQL 不该让整个服务开始重连。
        if self.closed:
            _drop()

    # ---- db._Conn 的接口 ----
    #
    # 六个方法一律先取 ``self._lock``（= ``db._lock``）。SQLite 那一侧的串行是
    # ``db._Conn`` 自带的，这条路必须自己补上 —— 见 :func:`connect` 的说明。
    # 锁是 RLock（``db.close()`` 持着它再调 :meth:`close` 不会自锁）。

    def execute(self, sql, parameters=()):
        with self._lock or _no_lock:
            stmt, injected = self._prepare(sql)
            is_dml = bool(_DML_RE.match(stmt))
            if not is_dml:
                self._settle()       # sqlite3：非 DML 语句之前先提交挂起的那笔
            try:
                cur = self._raw.cursor()
                cur.execute(stmt, parameters if parameters else None)
                # ⚠️ 无结果集的语句（ALTER / CREATE / UPDATE …）**不能** fetchall ——
                # psycopg 会抛 ProgrammingError（sqlite3 那边返回空列表，所以这个差异
                # 只有在 PG 上才现形）。判据用 description，它同时覆盖 RETURNING。
                rows = cur.fetchall() if cur.description is not None else []
                rowcount = cur.rowcount
                description = cur.description
                cur.close()
                # 语句跑过 = 服务端现在一定有一笔事务（psycopg 隐式 BEGIN），记上账
                self._open = True
            except Exception as e:
                self._fail(e)
                raise
            if is_dml:
                self._open = True    # 事务留给调用点的 commit()（与 sqlite3 一致）
            else:
                # 非 DML 在 SQLite 里跑在 autocommit 下（DDL 立即生效、SELECT 不进
                # 事务），这里等价地把事务就地结束 —— 不留锁、不留快照。
                self._settle()
            lastrowid = None
            if injected:
                if rows:
                    try:                           # 取到的必然是整数（判据是 IDENTITY），
                        lastrowid = int(rows[0].get("id"))   # 但**不拿类型赌**：转不了就给 None
                    except (TypeError, ValueError):
                        lastrowid = None
                rows = []      # INSERT 不产生结果集 —— 与 SQLite 口径一致（见模块文档）
            return self._cls(rows, rowcount, lastrowid, description)

    def executemany(self, sql, seq_of_parameters):
        with self._lock or _no_lock:
            stmt = sqlcompat.adapt(sql)            # 不追加 RETURNING：没有调用点用它
            try:
                cur = self._raw.cursor()
                cur.executemany(stmt, seq_of_parameters)
                rowcount = cur.rowcount
                cur.close()
            except Exception as e:
                self._fail(e)
                raise
            self._open = True                      # executemany 全是写（见 db.py 的调用点）
            return self._cls([], rowcount, None, None)

    def executescript(self, sql):
        """整段 DDL 逐条执行（PG 没有 executescript）。

        前后各 settle 一次，对齐 sqlite3 的 ``executescript``：它**先提交挂起的事务**，
        随后整段脚本不再有任何隐式事务控制（每条 DDL 各自 autocommit 生效）。
        """
        with self._lock or _no_lock:
            self._settle()
            try:
                cur = self._raw.cursor()
                for stmt in sqlcompat.script(sql):
                    cur.execute(stmt)
                cur.close()
                self._open = True
            except Exception as e:
                self._fail(e)
                raise
            self._settle()
            return self._cls([], -1, None, None)

    def commit(self):
        with self._lock or _no_lock:
            try:
                self._raw.commit()
            except Exception as e:
                self._fail(e)
                raise
            self._open = False

    def rollback(self):
        with self._lock or _no_lock:
            try:
                self._raw.rollback()
            except Exception as e:
                self._fail(e)
                raise
            self._open = False

    def close(self):
        with self._lock or _no_lock:
            try:
                self._raw.close()
            finally:
                self._open = False
                _drop()
