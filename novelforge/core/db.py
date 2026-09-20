"""SQLite 持久层：单用户场景下的阅读进度与批注存储。

设计要点：
- 数据库文件落在 ``config.DATA_DIR/novelforge.db``（NAS 持久卷，零额外服务）。
- 全进程共享一个连接（check_same_thread=False + 写锁），单机单用户足够。
- 表：users（轻登录账号）、progress（每本书当前阅读位置）、annotations（高亮/笔记）。
"""
import ast
import hashlib
import pathlib
import re
import threading
import time
from datetime import datetime, timedelta

try:  # 时区归一（Python 3.9+ 标准库；极老环境或缺 tzdata 时回落本地时）
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from .. import config


_db_path: "pathlib.Path | None" = None
_lock = threading.Lock()
_conn = None


def db_path() -> pathlib.Path:
    global _db_path
    if _db_path is None:
        d = pathlib.Path(config.DATA_DIR)
        d.mkdir(parents=True, exist_ok=True)
        _db_path = d / "novelforge.db"
    return _db_path


def _connect():
    global _conn
    if _conn is None:
        import sqlite3

        c = sqlite3.connect(str(db_path()), check_same_thread=False)
        c.row_factory = sqlite3.Row
        _conn = c
    return _conn


def close() -> None:
    """关闭并清空缓存的连接与数据库路径。

    供**测试**（每个用例一套独立空库）与「运行时切换 DATA_DIR」使用。
    正常请求流程不会调用它 —— 生产路径下连接始终复用，行为与之前完全一致。
    """
    global _conn, _db_path
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
        _db_path = None


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
            CREATE TABLE IF NOT EXISTS progress (
                id         INTEGER PRIMARY KEY,
                book_id    TEXT NOT NULL,
                locator    INTEGER NOT NULL,
                percent    REAL NOT NULL DEFAULT 0,
                updated_at REAL NOT NULL,
                UNIQUE(book_id)
            );
            CREATE TABLE IF NOT EXISTS annotations (
                id         INTEGER PRIMARY KEY,
                book_id    TEXT NOT NULL,
                chapter    INTEGER NOT NULL,
                quote      TEXT NOT NULL,
                color      TEXT NOT NULL DEFAULT 'yellow',
                note       TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_anno_book ON annotations(book_id);
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
                desc       TEXT NOT NULL DEFAULT '',
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
            CREATE TABLE IF NOT EXISTS smart_scopes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT NOT NULL,
                rules      TEXT NOT NULL,                      -- JSON: [{field, op, value}]
                match      TEXT NOT NULL DEFAULT 'all',        -- all = 且 / any = 或
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
            -- 书籍封面（第 17 期 T3）：元数据写回改为只存服务端，封面同样不写进 EPUB，
            -- 而是按 book_id 缓存到本表（BLOB 直接落库，零外链、零独立目录）。
            -- 展示 / OPDS 封面接口优先取服务端缓存，无则回退 EPUB 内嵌图。
            CREATE TABLE IF NOT EXISTS meta_cover (
                book_id    TEXT PRIMARY KEY,
                data       BLOB NOT NULL,
                media_type TEXT NOT NULL DEFAULT 'image/jpeg'
            );
            -- 作者级元数据（第 8 期 D1/D2/D5）：在线抓取的 bio/photo 与用户本地覆盖分列。
            -- 展示取 本地覆盖 > 在线；用户改过的不会被再次抓取冲掉。
            -- 照片一律缓存到 CACHE_DIR/authors/（零外链），这里只存文件名。
            CREATE TABLE IF NOT EXISTS authors (
                name             TEXT PRIMARY KEY,
                bio              TEXT NOT NULL DEFAULT '',
                bio_local        TEXT NOT NULL DEFAULT '',
                photo_path       TEXT NOT NULL DEFAULT '',
                photo_source     TEXT NOT NULL DEFAULT '',
                photo_local_path TEXT NOT NULL DEFAULT '',
                fetched_at       REAL NOT NULL DEFAULT 0
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
            -- 多书库（第 10 期 D8）：库实体。type 决定功能显隐矩阵。
            -- root_path **永远是实际库根**（扫描 / 落盘 / 路径解析的唯一根），两种模式一致。
            -- mode='inplace' 就地引用来源子目录（不搬文件）；'import' 库另有独立存储（root_path 就是它）。
            -- source_subdir 来源子目录名（相对 LIBRARY_SOURCE_DIR）—— **只存相对名**：
            --   挂载点换了之后存绝对路径会失效，存相对子目录不会。
            -- storage_path 预留（当前为空）：将来「来源与存储在物理上分开记」时才用。
            CREATE TABLE IF NOT EXISTS libraries (
                id             TEXT PRIMARY KEY,
                name           TEXT NOT NULL,
                type           TEXT NOT NULL DEFAULT 'mixed',
                mode           TEXT NOT NULL DEFAULT 'inplace',
                root_path      TEXT NOT NULL,
                storage_path   TEXT NOT NULL DEFAULT '',
                source_subdir  TEXT NOT NULL DEFAULT '',
                rules          TEXT NOT NULL DEFAULT '',
                -- 每库覆盖（第 13 期）：JSON 文本，键 = 全局配置的**点分路径**（如 "output.layout"）。
                -- 只存**被本库覆写**的键；未出现的键一律继承全局 ——
                -- 于是全局改了策略，没覆写过的库会自动跟着变（若存全量副本就做不到这点）。
                settings       TEXT NOT NULL DEFAULT '',
                sort_order     INTEGER NOT NULL DEFAULT 0,
                created_at     REAL NOT NULL,
                last_scan_at   REAL NOT NULL DEFAULT 0,
                last_scan_note TEXT NOT NULL DEFAULT '',
                -- 逐库扫描调度（第 17 期 T2）：watch=是否监听该库来源子目录；
                -- scan_interval=轮询间隔秒（0=继承全局）；scan_cron=定时表达式（空=不启用）。
                watch           INTEGER NOT NULL DEFAULT 1,
                scan_interval   INTEGER NOT NULL DEFAULT 0,
                scan_cron       TEXT NOT NULL DEFAULT '',
                -- 刮削出版成品目录（第 18 期）：刮削后**硬链接副本**的落点，供外部阅读器
                -- （Komga 等）直接挂载读取。空 = 该库不产出副本。
                -- ⚠️ 副本只读源、只写自己：源文件永不改写。该目录不得位于任何库根 /
                -- 扫描源目录内部（否则会被扫回来，书列表出现重复），由 server 侧校验。
                publish_path    TEXT NOT NULL DEFAULT ''
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
            """
        )
        # 轻量迁移：ratings 表后来加了 review 列。CREATE TABLE IF NOT EXISTS
        # 不会改已有库的表结构，所以老库必须在这里补列，否则写入会报 no such column。
        cols = {r["name"] for r in c.execute("PRAGMA table_info(ratings)")}
        if "review" not in cols:
            c.execute("ALTER TABLE ratings ADD COLUMN review TEXT NOT NULL DEFAULT ''")
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
        _seed_user(c)
        c.commit()


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

def get_progress(book_id: str):
    c = _connect()
    row = c.execute(
        "SELECT locator, percent, updated_at FROM progress WHERE book_id=?", (book_id,)
    ).fetchone()
    # updated_at 是为 KOReader 互通加的：它用时间戳判断「服务端进度是否比本机新」
    # （见 server.ko_get_progress → core/koreader.from_nf）。前端只读 locator/percent，
    # 多一个字段没有任何影响。
    return ({"locator": row["locator"], "percent": row["percent"],
             "updated_at": row["updated_at"]} if row else None)


def set_progress(book_id: str, locator: int, percent: float):
    c = _connect()
    with _lock:
        c.execute(
            """INSERT INTO progress(book_id, locator, percent, updated_at)
               VALUES(?,?,?,?)
               ON CONFLICT(book_id) DO UPDATE SET
                 locator=excluded.locator,
                 percent=excluded.percent,
                 updated_at=excluded.updated_at""",
            (book_id, locator, percent, time.time()),
        )
        c.commit()


# ---------------- annotations ----------------

def list_annotations(book_id: str) -> list:
    c = _connect()
    rows = c.execute(
        "SELECT id, chapter, quote, color, note, created_at, origin "
        "FROM annotations WHERE book_id=? AND deleted_at=0 ORDER BY chapter, created_at",
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_annotation(book_id: str, chapter: int, quote: str, color: str, note: str,
                   origin: str = "web") -> int:
    c = _connect()
    with _lock:
        cur = c.execute(
            "INSERT INTO annotations(book_id, chapter, quote, color, note, created_at, origin) "
            "VALUES(?,?,?,?,?,?,?)",
            (book_id, chapter, quote, color, note, time.time(), origin),
        )
        c.commit()
        return cur.lastrowid or 0


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
    sql = ("SELECT id, book_id, chapter, quote, color, note, created_at, origin, deleted_at "
           "FROM annotations WHERE deleted_at!=0")
    args: tuple = ()
    if book_id is not None:
        sql += " AND book_id=?"
        args = (book_id,)
    rows = c.execute(sql + " ORDER BY deleted_at DESC", args).fetchall()
    return [dict(r) for r in rows]


# ---------------- 收藏夹 ----------------

def list_collections() -> list:
    c = _connect()
    rows = c.execute(
        """SELECT c.id, c.name, c.created_at,
                  (SELECT COUNT(*) FROM collection_items i WHERE i.collection_id = c.id) AS count
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
        cur = c.execute(
            "INSERT INTO collections(name, created_at) VALUES(?,?)", (name, time.time())
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
            "UPDATE collections SET name=? WHERE id=?", (str(name).strip(), int(cid))
        )
        c.commit()
        return int(cur.rowcount or 0) > 0


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
        c.execute(
            "INSERT OR IGNORE INTO collection_items(collection_id, book_id, added_at) VALUES(?,?,?)",
            (cid, book_id, time.time()),
        )
        c.commit()


def remove_book_from_collection(cid: int, book_id: str):
    c = _connect()
    with _lock:
        c.execute(
            "DELETE FROM collection_items WHERE collection_id=? AND book_id=?", (cid, book_id)
        )
        c.commit()


def collections_of_book(book_id: str) -> list:
    c = _connect()
    rows = c.execute(
        "SELECT collection_id FROM collection_items WHERE book_id=?", (book_id,)
    ).fetchall()
    return [r["collection_id"] for r in rows]


# ---------------- 统计辅助（供 core/stats.py 聚合）----------------

def all_progress() -> dict:
    c = _connect()
    rows = c.execute("SELECT book_id, locator, percent, updated_at FROM progress").fetchall()
    return {r["book_id"]: dict(r) for r in rows}


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
    sql = ("SELECT id, book_id, chapter, quote, color, note, created_at, origin, deleted_at "
           "FROM annotations")
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

def add_session(book_id: str, seconds: float, started_at=None, ended_at=None) -> None:
    """记录一次阅读会话（阅读器前台计时后上报）。"""
    now = time.time()
    started = float(started_at) if started_at else now - float(seconds)
    ended = float(ended_at) if ended_at else now
    c = _connect()
    with _lock:
        c.execute(
            "INSERT INTO reading_sessions(book_id, seconds, started_at, ended_at) VALUES(?,?,?,?)",
            (book_id, float(seconds), started, ended),
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


def hour_histogram(book_ids: set | None = None) -> list:
    """会话开始时段的 24 小时分布。

    第 25 期起按账号时区归一：设置过 timezone 才转换，否则回落服务器本地时
    （保持历史口径，避免老库无时区时分布突变）。时区解析失败同样回落本地时。

    ``book_ids`` 语义同 ``reading_totals``（None = 全部）。
    """
    c = _connect()
    tz = (get_user_profile().get("timezone") or "").strip()
    zone = None
    if tz and ZoneInfo is not None:
        try:
            zone = ZoneInfo(tz)
        except Exception:
            zone = None
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
            "INSERT OR REPLACE INTO tasks"
            "(id, type, title, detail, status, progress, actor, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
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
            "INSERT INTO achievements(key, name, desc, group_name, metric, target, sort) "
            "VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET name=excluded.name, desc=excluded.desc, "
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
# 书从 OUTPUT_DIR 移走后，progress / annotations / reading_sessions / collection_items
# 里仍留着它的行 —— 界面上再也走不到，却一直占着库。
#
# ⚠️ 清理是**不可恢复**的，但这些行的 key 是文件名派生的 book_id，
#    所以如果把同一个文件放回 OUTPUT_DIR，进度与批注会**重新关联上**。
#    也就是说：清理掉的是「可能还有用」的数据，因此必须由用户显式确认。

ORPHAN_TABLES = ("progress", "annotations", "collection_items", "reading_sessions")


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
REMAP_TABLES = (
    "progress", "annotations", "collection_items", "reading_sessions",
    "ratings", "reading_status", "koreader_docs",
)

#: 「新 id 是否已有数据」这个探测要**按表**加过滤：annotations 第 27 期起有软删除，
#: 新 id 上只躺着**垃圾桶**条目时不该算作「已有数据」—— 否则整张表被跳过搬迁，
#: 旧 id 的**活跃**批注会被搁浅成孤儿（静默丢失，不报错）。
#: ⚠️ 搬迁本身（UPDATE）**不加**这个谓词：活跃与垃圾桶条目都属于同一本书，都该跟着走。
REMAP_PROBE_FILTER = {"annotations": " AND deleted_at=0"}


def remap_book_id(old_id, new_id) -> dict:
    """把关联数据从 ``old_id`` 搬到 ``new_id``，返回 ``{表名: 搬迁行数}``。

    某张表在 ``new_id`` 上**已有数据**时该表跳过：那通常意味着目标文件名上已经有
    一本书的历史（用户先删旧文件、又放了同名新文件），覆盖会张冠李戴 ——
    宁可少搬，不可错搬。
    """
    old, new = str(old_id), str(new_id)
    if not old or not new or old == new:
        return {}
    moved: dict = {}
    c = _connect()
    with _lock:
        for t in REMAP_TABLES:
            try:
                exists = c.execute(
                    "SELECT 1 FROM %s WHERE book_id=?%s LIMIT 1"
                    % (t, REMAP_PROBE_FILTER.get(t, "")), (new,)
                ).fetchone()
                if exists:
                    moved[t] = 0
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
        lid = str(lib.get("id") or _lib.DEFAULT_LIBRARY_ID)
        d = pathlib.Path(lib.get("root_path") or config.OUTPUT_DIR)
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
            "INSERT INTO smart_scopes(name, rules, match, created_at) VALUES(?,?,?,?)",
            (str(name), str(rules_json), str(match), time.time()),
        )
        c.commit()
        return get_scope(cur.lastrowid)


def update_scope(scope_id, name, rules_json, match="all") -> dict:
    c = _connect()
    with _lock:
        c.execute(
            "UPDATE smart_scopes SET name=?, rules=?, match=? WHERE id=?",
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
                "INSERT OR REPLACE INTO koreader_docs"
                "(book_id, doc_md5, alt_md5, size, mtime, computed_at) VALUES(?,?,?,?,?,?)",
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
# ⚠️ 之前**没有真实状态字段**：前端用 percent 推导（p>0 = 在读、≥99.5% = 读完）。
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
              "publisher", "language", "description", "tags", "isbn")


def clearable(field: str) -> bool:
    """该字段是否支持「显式清空」（覆盖值写 :data:`META_CLEAR` 哨兵）。"""
    return str(field) in _CLEARABLE


def is_cleared(field: str, value) -> bool:
    """这个覆盖值是不是「显式无值」哨兵（只对 :data:`_CLEARABLE` 里的字段成立）。"""
    return str(value) == META_CLEAR and clearable(field)


def _meta_out(field: str, value):
    """把覆盖值翻译成对外形态：哨兵 → 「无值」（``tags`` 给空列表，其余给空串）。"""
    if is_cleared(field, value):
        return [] if str(field) == "tags" else ""
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
                "publisher", "language", "description", "tags", "isbn")
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
            if f == "tags":
                merged["tags"] = _parse_tags(v)
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
#: 归属模式：inplace = 就地引用来源子目录（不搬文件）；import = 另有存储目录（复制/移入）
LIBRARY_MODES = ("inplace", "import")


def list_libraries() -> list:
    rows = _connect().execute(
        "SELECT * FROM libraries ORDER BY sort_order, created_at"
    ).fetchall()
    return [dict(r) for r in rows]


def get_library(lid) -> "dict | None":
    row = _connect().execute("SELECT * FROM libraries WHERE id=?", (str(lid),)).fetchone()
    return dict(row) if row else None


def create_library(lid, name, type_, mode="inplace", root_path="",
                   storage_path="", source_subdir="", rules="", sort_order=0,
                   settings="", watch=1, scan_interval=0, scan_cron="",
                   publish_path="") -> dict:
    """建库。``settings`` 是每库覆盖的 JSON 文本（第 13 期）。

    ``watch`` / ``scan_interval`` / ``scan_cron`` 是逐库扫描调度（第 17 期 T2）：
    默认 watch=1（开）、scan_interval=0（继承全局）、scan_cron=""（不启用定时）。

    ``publish_path`` 是刮削出版的成品目录（第 18 期）：空 = 该库不产出硬链接副本。
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
            "INSERT OR REPLACE INTO libraries"
            "(id, name, type, mode, root_path, storage_path, source_subdir, rules,"
            " settings, sort_order, created_at, last_scan_at, last_scan_note,"
            " watch, scan_interval, scan_cron, publish_path) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,0,'',?,?,?,?)",
            (str(lid), str(name), str(type_), str(mode), str(root_path),
             str(storage_path or ""), str(source_subdir or ""), str(rules or ""),
             str(settings or ""), int(sort_order or 0), time.time(),
             w, si, str(scan_cron or ""), str(publish_path or "")),
        )
        c.commit()
    return get_library(lid) or {}


#: update_library 允许改的列（白名单，避免把任意键拼进 SQL）。
#: ⚠️ 新增列**必须**同时加进来，否则 update_library 会**静默写不进**
#: （它是「过滤后为空就原样返回」，不报错）。
_LIBRARY_COLS = {"name", "type", "mode", "root_path", "storage_path",
                 "source_subdir", "rules", "settings", "sort_order",
                 "watch", "scan_interval", "scan_cron", "publish_path",
                 "last_scan_at", "last_scan_note"}


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
        c.commit()
    return {"book_id": str(book_id), "status": status,
            "started_at": st, "finished_at": fin, "updated_at": now}
