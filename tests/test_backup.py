"""第 84 期：`core/backup.py` 的离线契约测试。

更新前数据快照（PostgreSQL 走 pg_dump、SQLite 走整文件拷贝，保留最近 5 份轮转）。
硬要求：**失败即中止** —— `snapshot()` 抛 `SnapshotError` 时调用方必须停止更新，
绝不能「备份失败还继续更新」（否则一次写坏数据的更新 = 用户连回滚机会都没有）。

测试纪律：
* 绝不真连 PostgreSQL：`_is_pg` 与 `_dump_pg` 用替身，只验证「走到 pg 分支」与
  「快照落点的文件名 / kind 形状」。
* SQLite 真拷贝走 `isolated` 夹具提供的真实库文件（不造第二个判据）。
* 轮转用 `_rotate` 直接喂一组手建文件验证，不依赖真实 dump 时长。
"""
from __future__ import annotations

import pathlib

import pytest

from novelforge.core import backup as backup_mod
from novelforge import config as config_mod


@pytest.fixture
def bk(tmp_path, monkeypatch):
    """把备份落点指到临时目录；默认走 SQLite 分支（_is_pg 替身关掉）。"""
    monkeypatch.setattr(config_mod, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(backup_mod, "_is_pg", lambda: False)
    return tmp_path


def test_snapshot_sqlite_拷贝真实库文件(bk, isolated, monkeypatch):
    """SQLite 分支：把真实库文件整文件拷出来，返回 ok + 落点 + kind=sqlite。"""
    from novelforge.core import db

    src = pathlib.Path(db.db_path())
    assert src.is_file(), "isolated 夹具应已建立 SQLite 库文件"
    monkeypatch.setattr(backup_mod, "_is_pg", lambda: False)
    out = backup_mod.snapshot("auto")
    assert out["ok"] is True
    assert out["kind"] == "sqlite"
    assert out["path"].endswith(".db")
    p = pathlib.Path(out["path"])
    assert p.is_file() and p.stat().st_size > 0
    assert out["size"] == p.stat().st_size


def test_snapshot_pg_分支走_dump(bk, monkeypatch):
    """PG 分支：不走 SQLite 拷贝，调 pg_dump 并把归档落盘（dump 用替身）。"""
    captured = {}

    def fake_dump(dest: pathlib.Path) -> str:
        captured["dest"] = str(dest)
        dest.write_bytes(b"PGDUMP-FAKE")
        return str(dest)

    monkeypatch.setattr(backup_mod, "_is_pg", lambda: True)
    monkeypatch.setattr(backup_mod, "_dump_pg", fake_dump)
    out = backup_mod.snapshot("auto")
    assert out["ok"] is True
    assert out["kind"] == "pg"
    assert out["path"].endswith(".dump")
    assert pathlib.Path(out["path"]).is_file()
    assert pathlib.Path(out["path"]).read_bytes() == b"PGDUMP-FAKE"


def test_rotate_只留最近5份(bk):
    """同 reason 轮转保留 5 份，删最旧的。"""
    d = backup_mod.backup_dir()
    for i in range(7):
        f = d / f"pre-update-auto-{i:02d}.db"
        f.write_bytes(b"x")
        # 让 mtime 递增，排序才有意义
        pathlib.os.utime(f, (1_700_000_000 + i * 60, 1_700_000_000 + i * 60))
    removed = backup_mod._rotate(d, "auto")
    left = sorted(d.glob("pre-update-auto-*"))
    assert len(left) == 5, [p.name for p in left]
    assert len(removed) == 2
    # 留下的是较新的 5 份（i=02..06）
    names = {p.name for p in left}
    assert "pre-update-auto-00.db" not in names
    assert "pre-update-auto-01.db" not in names
    assert "pre-update-auto-06.db" in names


def test_rotate_按reason分组互不干扰(bk):
    """auto 与 manual 两组各自轮转，互不影响。"""
    d = backup_mod.backup_dir()
    for reason in ("auto", "manual"):
        for i in range(6):
            f = d / f"pre-update-{reason}-{i:02d}.db"
            f.write_bytes(b"x")
            pathlib.os.utime(f, (1_700_000_000 + i * 60, 1_700_000_000 + i * 60))
    backup_mod._rotate(d, "auto")
    auto_left = sorted(d.glob("pre-update-auto-*"))
    manual_left = sorted(d.glob("pre-update-manual-*"))
    assert len(auto_left) == 5
    assert len(manual_left) == 6, "manual 组没动过，应原样保留"


def test_snapshot_失败即抛SnapshotError(bk, monkeypatch):
    """拷贝抛错 ⇒ 整次 snapshot 抛 SnapshotError（调用方据此中止更新）。"""

    def boom(dest: pathlib.Path) -> str:
        raise backup_mod.SnapshotError("拷贝失败（测试预设）")

    monkeypatch.setattr(backup_mod, "_is_pg", lambda: False)
    monkeypatch.setattr(backup_mod, "_copy_sqlite", boom)
    with pytest.raises(backup_mod.SnapshotError):
        backup_mod.snapshot("auto")


def test_pg_dump失败即抛SnapshotError(bk, monkeypatch):
    """pg_dump 非零退出 ⇒ SnapshotError（带退出码与 stderr 尾段）。"""
    monkeypatch.setattr(backup_mod, "_is_pg", lambda: True)

    def boom(dest: pathlib.Path) -> str:
        raise backup_mod.SnapshotError("pg_dump 失败（退出码 1）：connection refused")

    monkeypatch.setattr(backup_mod, "_dump_pg", boom)
    with pytest.raises(backup_mod.SnapshotError) as ei:
        backup_mod.snapshot("auto")
    assert "pg_dump" in str(ei.value)
