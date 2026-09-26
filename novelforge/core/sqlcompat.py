"""SQL 方言适配（第 62 期）：**一份 SQL 同时跑 SQLite 与 PostgreSQL**。

为什么后端是可选的，而不是直接换掉
----------------------------------
本项目积累了一个 3900 行 / 198 函数 / 35 表的持久层（``db.py``），全部按 SQLite
写就；同时仓库有一条硬纪律：**测试完全离线跑**（``.venv/bin/python -m pytest``，
基线 939 例全绿，见 ``.codebuddy/memory/MEMORY.md``「自动化测试」）。如果数据库
硬换成 PG，测试就必须先起一个 Postgres —— 那条纪律当场作废，且离线开发环境
（Windows 本机）直接跑不了全量。

所以后端由环境变量 ``NOVELFORGE_DB`` 选择，**默认仍是 sqlite**：

- ``sqlite``（默认）→ 老 ``db.py`` 原样跑，测试与离线开发零变化；
- ``pg``            → SQL 经本模块翻译后交给 psycopg，见 ``pg.py``。

翻译为什么是安全的（三道**实测**前提，不是估计）
------------------------------------------------
① 全仓 SQL 里**没有任何 ``?`` 出现在单引号字面量内** —— 否则占位符替换会改坏
   字面量。本模块仍然做了字面量感知扫描（见 :func:`_translate`），因为「今天
   没有」不等于「明天不会有」，而这类 bug 只会在开了 PG 的机器上炸；
② 全仓**没有一处 ``LIKE '%…%'``**，所有残留 ``%`` 都是 Python 侧的 ``%``-格式化
   或取模，在到达驱动前就已被消耗。但 psycopg 用 ``%s`` 做客户端插值，SQL 文本里
   的裸 ``%`` 仍须转义成 ``%%`` —— 本模块统一处理；
③ ``db.py`` 里**已经在用 ``%s`` 做 Python 侧的表名/列名格式化**（如
   ``"SELECT %s FROM bookmarks …" % _BOOKMARK_COLS``）。适配层收到的是**已被
   Python 格式化过的最终字符串**，此时那些 ``%s`` 早被消耗 —— 顺序天然正确。

⚠️ 本模块**只做字符串 → 字符串**：不碰连接、不碰参数、不碰事务。参数一律原样
交给驱动（SQLite 的 ``?`` 与 psycopg 的 ``%s`` 都吃「位置参数序列」）。
"""
from __future__ import annotations

import os
import re

#: 后端名 → 是否用 PostgreSQL。**默认 sqlite**：任何没显式配置的环境（测试、
#: 离线开发、老部署）行为与第 61 期完全一致。
BACKEND_SQLITE = "sqlite"
BACKEND_PG = "pg"

#: 选后端的唯一入口。**默认 sqlite** —— 不设它时全仓行为与第 61 期逐字节一致。
_ENV_KEY = "NOVELFORGE_DB"

#: 当前后端（进程内缓存；``reset()`` 供测试改动环境变量后重读）。
_backend: "str | None" = None


def backend() -> str:
    """当前后端名：``"sqlite"``（默认）或 ``"pg"``。

    取值为 ``pg`` 需要同时给出 ``NOVELFORGE_PG_DSN``（见 ``pg.py``），否则
    ``pg.py`` 会带着明确错误启动失败 —— 半配置状态比直接报错更难查。
    """
    global _backend
    if _backend is None:
        v = (os.getenv(_ENV_KEY) or "").strip().lower()
        _backend = BACKEND_PG if v in ("pg", "postgres", "postgresql") else BACKEND_SQLITE
    return _backend


def is_pg() -> bool:
    """是否走 PostgreSQL。热路径请用本函数而不是每次比较 ``backend()``。"""
    return backend() == BACKEND_PG


def reset() -> None:
    """丢掉缓存的后端判定（测试改完环境变量后调用）。"""
    global _backend
    _backend = None


# ---------------- 翻译 ----------------

#: 不能机械翻译、必须由调用点显式改写的构造 —— 撞上即**大声失败**。
#:
#: 这些是**故意的**：静默放过它们会得到「PG 上语法错误」或更糟的「语义悄悄变了」，
#: 而错误现场（某个后台线程）离配置动作（打开 PG）可能隔了好几天。
_UNSUPPORTED = (
    (re.compile(r"\bINSERT\s+OR\s+REPLACE\b", re.I),
     "INSERT OR REPLACE 需要显式冲突目标（PG 的 ON CONFLICT (…) DO UPDATE SET …）；"
     "SQLite 的 REPLACE 语义是「删旧插新」，与 DO UPDATE 不等价，不能机械翻译"),
    (re.compile(r"\bAUTOINCREMENT\b", re.I),
     "AUTOINCREMENT 在 PG 无对应拼写（IDENTITY 是列约束、且位置与 SQLite 不同），"
     "须在建表 SQL 里逐表改写"),
    (re.compile(r"\bPRAGMA\b", re.I),
     "PRAGMA 是 SQLite 专有：table_info 走 information_schema.columns，其余需逐条评估"),
    (re.compile(r"\bWITHOUT\s+ROWID\b", re.I),
     "WITHOUT ROWID 是 SQLite 专有"),
)


class DialectError(RuntimeError):
    """SQL 无法机械翻译成 PG —— 调用点必须显式改写。"""


def _translate(sql: str) -> str:
    """字面量感知的单遍扫描：``?`` → ``%s``，裸 ``%`` → ``%%``。

    **为什么要字面量感知**：``?`` 出现在 ``'...'`` 里就是普通字符，替换它会改坏
    数据；``%`` 出现在字面量里**同样要转义**（psycopg 对整条 SQL 文本做插值，
    不区分字面量内外），所以两个方向的处理并不对称 —— 见下面两个分支。
    """
    out: list = []
    i, n = 0, len(sql)
    in_str = False
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'":
                # SQL 里 '' 是转义的单引号：连同下一颗一起吃掉，别误判成收尾
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("''")
                    i += 2
                    continue
                in_str = False
                out.append(ch)
            else:
                out.append("%%" if ch == "%" else ch)
            i += 1
            continue
        if ch == "'":
            in_str = True
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def adapt(sql: str) -> str:
    """SQLite 方言的 SQL → 当前后端的 SQL。

    sqlite 后端**原样返回**（零开销、零风险）；pg 后端做翻译。
    """
    if not is_pg():
        return sql
    for pat, why in _UNSUPPORTED:
        if pat.search(sql):
            raise DialectError(f"{why}\n原 SQL：{sql.strip()[:200]}")
    out = _translate(sql)
    # INSERT OR IGNORE 无冲突目标即可翻译：PG 的 ON CONFLICT DO NOTHING 吃任意冲突。
    # 追加到语句末尾 —— 先剥掉可能存在的收尾分号与空白。
    if re.search(r"\bINSERT\s+OR\s+IGNORE\b", out, re.I):
        body = out.rstrip()
        semi = ""
        if body.endswith(";"):
            body, semi = body[:-1].rstrip(), ";"
        out = re.sub(r"\bINSERT\s+OR\s+IGNORE\b", "INSERT", body, count=1, flags=re.I)
        out = out + " ON CONFLICT DO NOTHING" + semi
    return out


def script(sql: str) -> "list[str]":
    """``executescript`` 用的整段 DDL → **单条语句列表**（PG 侧逐条执行）。

    两个必须做的处理，都不是理论问题而是踩过的：

    1. **先剥 ``--`` 行注释再按 ``;`` 切**：本仓 DDL 的注释里有**半角单引号**
      （例如 ``-- 原 mode('inplace'/'import')``），带着注释做字面量扫描会把
      那一行当成「进了字符串没出来」，从此整段 SQL 全被误判为字面量；
    2. 剥注释同样要字面量感知 —— ``'--'`` 是真数据，不能当注释起点。

    sqlite 后端不会走这条路（``executescript`` 原生可用），故直接返回整段。
    """
    if not is_pg():
        return [sql] if sql.strip() else []
    stripped = _strip_line_comments(sql)
    return [s.strip() for s in stripped.split(";") if s.strip()]


def _strip_line_comments(sql: str) -> str:
    """去掉 ``--`` 行注释（字面量内的 ``--`` 保留）。"""
    out: list = []
    i, n = 0, len(sql)
    in_str = False
    while i < n:
        ch = sql[i]
        if in_str:
            if ch == "'":
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("''")
                    i += 2
                    continue
                in_str = False
            out.append(ch)
            i += 1
            continue
        if ch == "'":
            in_str = True
            out.append(ch)
            i += 1
            continue
        if ch == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            out.append("\n")
            continue
        out.append(ch)
        i += 1
    return "".join(out)
