"""更新前的数据快照（第 84 期）。

为什么要有这个模块：此前一键更新**只备份 config.yaml**（`server._backup_config`），
业务数据（书目索引、阅读进度、批注、书签、书库实体）**完全没有安全网**。而一键更新
要做的事是「删掉自己这个容器、用新镜像重建」—— 一旦新版本有 bug 或迁移写坏数据，
用户手上没有任何可回滚的东西。NAS 上的数据往往是几年的书 + 进度，重装代价极高。

快照策略（按当前后端二分，判据复用 `core/sqlcompat.is_pg()`，**不新增第二份判据**）：

* **PostgreSQL** → ``pg_dump -Fc`` 写单文件自定义格式归档。选 ``-Fc`` 而不是
  ``COPY ... TO STDOUT``：归档格式是**压缩 + 单文件 + 单进程单连接**，能直接落盘、
  不用把结果读进内存，``pg_restore`` 还原时也更快。
* **SQLite** → ``shutil.copy2`` 整文件拷贝。注意这是**热拷**（不停库），对 SQLite 而言
  有小概率拿到撕裂的页；备份**失败或结果可疑时调用方必须中止更新**，宁可这次不更新，
  也不能拿一份坏快照当「已备份」继续往下走。

⚠️ **失败即中止**是硬要求（本模块唯一的正确用法）：`snapshot()` 失败时抛
:class:`SnapshotError`，调用方（``updater.apply_update``）把它变成
``stage="backup_failed"`` 并**不进入拉镜像**。理由很直白：一份不可信的备份 + 一次
已经破坏数据的更新 = 用户连回滚的机会都没有。

备份落 ``config.BACKUP_DIR``（默认 ``/app/config/backups``）—— 在**持久卷**上，
容器被删掉重建之后备份还在。这点是选它而不是 ``/app/data`` 的唯一理由。

轮转保留最近 :data:`_BACKUP_KEEP` 份（同 ``reason`` 前缀的一组），删最旧的。
不新增配置键：保留份数是运维口味而非用户配置，弄成可配置就要付「新增配置分区 =
三处同步点」的代价（见 AGENTS.md），不值当。
"""
from __future__ import annotations

import logging
import os
import pathlib
import shutil
import subprocess
import time

_log = logging.getLogger("novelforge")

#: 同一 ``reason`` 保留几份。5 份足够覆盖「连续 5 次更新都失败」的场景，
#: 而每次自动更新才产生一份 ⇒ 目录不会无限增长。
_BACKUP_KEEP = 5

#: ``pg_dump`` 超时（秒）。大书库的 dump 在 NAS 上可能跑到几分钟，但**不能无限等**：
#: 卡死的子进程既不产出文件也不返回，最终拖住自动更新。
_PG_DUMP_TIMEOUT = 1800

#: stderr 截断长度（保留尾部 —— 报错信息通常在最后几行）。
_ERR_TAIL = 400


class SnapshotError(RuntimeError):
    """快照失败。**必须中止更新**，不得当作「跳过备份」继续。"""


def backup_dir() -> pathlib.Path:
    """备份落点（延迟读 ``config``，避免 import 期固化目录常量）。"""
    from .. import config

    d = pathlib.Path(config.BACKUP_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1e6) % 1000000:06d}"


def _rotate(d: pathlib.Path, reason: str) -> "list[str]":
    """同 ``reason`` 只留最近 :data:`_BACKUP_KEEP` 份，返回被删的路径。"""
    files = sorted(d.glob(f"pre-update-{reason}-*"), key=lambda p: p.stat().st_mtime)
    removed: "list[str]" = []
    for old in files[: max(0, len(files) - _BACKUP_KEEP)]:
        try:
            old.unlink()
            removed.append(str(old))
        except Exception:  # noqa: BLE001 —— 删不掉旧备份不该让这次备份算失败
            _log.warning("删不掉旧备份 %s", old)
    return removed


def _dump_pg(dest: pathlib.Path) -> str:
    """``pg_dump -Fc`` 到 dest。返回归档路径；失败抛 :class:`SnapshotError`。"""
    from . import pg

    dsn = pg._dsn()          # 读不到 DSN 时它自己抛 PgUnavailable（消息带正确口径）
    # -Fc 自定义格式：压缩、单文件、单进程单连接 ⇒ 直接落盘、还原更快。
    # --no-owner/--no-acl：还原进本项目自己的库时不依赖原库里的角色与权限。
    cmd = ["pg_dump", "-Fc", "--no-owner", "--no-acl", "-d", dsn, "-f", str(dest)]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=_PG_DUMP_TIMEOUT)
    except FileNotFoundError:
        raise SnapshotError(
            "容器里没有 pg_dump 可执行文件，无法给 PostgreSQL 做更新前备份。"
            "请手动备份数据库后重试，或临时关掉 update.auto_apply") from None
    except subprocess.TimeoutExpired:
        raise SnapshotError(f"pg_dump 超时（>{_PG_DUMP_TIMEOUT}s），已中止本次更新") from None
    if p.returncode != 0:
        raise SnapshotError(
            f"pg_dump 失败（退出码 {p.returncode}）：{(p.stderr or '').strip()[-_ERR_TAIL:]}")
    if not dest.is_file() or dest.stat().st_size == 0:
        raise SnapshotError("pg_dump 退出码为 0 但没留下备份文件（已中止本次更新）")
    return str(dest)


def _copy_sqlite(dest: pathlib.Path) -> str:
    """SQLite 整文件拷贝。失败抛 :class:`SnapshotError`。"""
    from . import db

    src = pathlib.Path(db.db_path())
    if not src.is_file():
        raise SnapshotError(f"找不到 SQLite 数据文件 {src}（已中止本次更新）")
    try:
        shutil.copy2(src, dest)
    except Exception as e:  # noqa: BLE001
        raise SnapshotError(f"拷贝 SQLite 数据文件失败：{e}（已中止本次更新）") from e
    if not dest.is_file() or dest.stat().st_size == 0:
        raise SnapshotError("SQLite 拷贝完成但文件为空（已中止本次更新）")
    return str(dest)


def snapshot(reason: str = "auto") -> "dict":
    """做一次数据快照。成功返回 ``{ok, path, kind, size, removed}``。

    :param reason: 归档文件名的中段（``pre-update-<reason>-<时间戳>.*``），用于分组轮转。
    :raises SnapshotError: **任何**环节失败 —— 调用方必须中止更新。

    刻意**不返回**「失败但继续」这档：备份不是可选步骤，「尽力而为地备份一下」
    在这里等于「有时候没有备份」。
    """
    reason = (reason or "auto").strip() or "auto"
    d = backup_dir()
    kind = "pg" if _is_pg() else "sqlite"
    dest = d / f"pre-update-{reason}-{_stamp()}.{'dump' if kind == 'pg' else 'db'}"
    if kind == "pg":
        path = _dump_pg(dest)
    else:
        path = _copy_sqlite(dest)
    removed = _rotate(d, reason)
    _log.info("更新前快照已写入 %s（%s，%.1f MB）", path, kind, os.path.getsize(path) / 1e6)
    return {"ok": True, "path": path, "kind": kind,
            "size": os.path.getsize(path), "removed": removed}


def _is_pg() -> bool:
    from . import sqlcompat

    return sqlcompat.is_pg()
