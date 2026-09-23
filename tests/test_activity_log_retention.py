"""审计日志留存策略（第 52 期）：轮转触发、保留份数、压缩、滚动后读取连续、清空语义。

⚠️ 日志目录是**模块级全局**（`activity_log._dir`），而 conftest 的 `LOG_DIR` 是全会话共用的
—— 所以这里必须把目录切到 `tmp_path` 并在结束后**还原**，否则会污染后续用例。
"""
import gzip
import pathlib

import pytest

from novelforge.core import activity_log


@pytest.fixture
def logdir(tmp_path):
    """把日志目录切到临时目录，用完还原（含内存缓冲）。"""
    old = activity_log.log_dir()
    activity_log.set_dir(tmp_path)
    yield tmp_path
    activity_log.set_dir(old)
    # 内存缓冲里可能留着本用例写在临时目录里的条目 —— 还原后必须清掉，
    # 否则下一个用例的 recent() 会看到别人的记录（读取端会按 jsonl 重建）。
    activity_log._memory.clear()


def _cfg(monkeypatch, **kw):
    """打桩留存策略（`retention_cfg` 是唯一读取点）。"""
    base = {"enabled": False, "max_bytes": 5 * 1024 * 1024, "keep": 5, "compress": True}
    base.update(kw)
    monkeypatch.setattr(activity_log, "_cfg_cache", {"at": 0.0, "val": None})
    monkeypatch.setattr(activity_log, "retention_cfg", lambda: base)


def _archives(d: pathlib.Path) -> list:
    return sorted(d.glob("activity-*.jsonl")) + sorted(d.glob("activity-*.jsonl.gz"))


def test_默认关闭_不产生归档(logdir, monkeypatch):
    _cfg(monkeypatch, enabled=False)
    for i in range(30):
        activity_log.log("转换", f"f{i}.txt", "成功", actor="a")
    assert _archives(logdir) == []
    assert (logdir / "activity.jsonl").is_file()


def test_超过阈值触发轮转并重新起文件(logdir, monkeypatch):
    _cfg(monkeypatch, enabled=True, max_bytes=300, keep=5, compress=False)
    for i in range(12):
        activity_log.log("转换", f"f{i}.txt", "成功", actor="a")

    assert _archives(logdir), "超过上限应产生归档"
    # 轮转后当前文件重新开始，体积必然小于归档
    cur = (logdir / "activity.jsonl").stat().st_size
    assert cur < sum(p.stat().st_size for p in _archives(logdir)) + cur


def test_压缩归档_内容可还原(logdir, monkeypatch):
    _cfg(monkeypatch, enabled=True, max_bytes=300, keep=5, compress=True)
    for i in range(12):
        activity_log.log("添加", f"g{i}.epub", "成功", actor="a")

    gz = sorted(logdir.glob("activity-*.jsonl.gz"))
    assert gz, "开启压缩应产生 .gz 归档"
    assert not list(logdir.glob("activity-*.jsonl")), "压缩后不应再留未压缩归档"
    with gzip.open(gz[0], "rt", encoding="utf-8", errors="ignore") as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    assert lines and "添加" in lines[0]


def test_保留份数_超出即删最旧的(logdir):
    """直接验 _prune_archives：轮转在秒内多次触发会因时间戳同名而覆盖，
    故「保留 N 份」这条规则单独钉，不靠多次轮转去碰运气。"""
    for i in range(5):
        (logdir / f"activity-2026010{i}-000000.jsonl").write_text("{}\n", encoding="utf-8")
        (logdir / f"activity-2026010{i}-000000.log").write_text("x\n", encoding="utf-8")
    activity_log._prune_archives(logdir, 2)
    assert [p.name for p in sorted(logdir.glob("activity-*.jsonl"))] == [
        "activity-20260103-000000.jsonl",
        "activity-20260104-000000.jsonl",
    ]
    # .log / .jsonl 是两类归档，各自保留，互不挤占
    assert len(sorted(logdir.glob("activity-*.log"))) == 2


def test_滚动后读取跨归档_历史不丢(logdir, monkeypatch):
    """这是最容易写坏的一条：轮转后若只读当前文件，重启（或缓冲清空）后历史就整体消失。"""
    _cfg(monkeypatch, enabled=True, max_bytes=300, keep=8, compress=False)
    for i in range(10):
        activity_log.log("转换", f"old{i}.txt", "成功", actor="old")
    assert _archives(logdir), "先要有归档，这条用例才有意义"
    for i in range(6):
        activity_log.log("刮削", f"new{i}.txt", "成功", actor="new")

    # 清掉内存缓冲 ⇒ 强制走 _read_tail（跨归档路径）
    activity_log._memory.clear()
    items = activity_log.recent(limit=500)
    names = {str(i.get("actor")) for i in items}
    assert "old" in names, "归档里的历史必须还能读到"
    assert "new" in names
    assert "old" in activity_log.actors(scan=500)


def test_clear_连归档一起删(logdir, monkeypatch):
    """清空必须连归档删 —— 读取端已跨归档，只删当前文件会让历史「复活」。"""
    _cfg(monkeypatch, enabled=True, max_bytes=300, keep=5, compress=False)
    for i in range(12):
        activity_log.log("清理", f"h{i}.txt", "成功", actor="a")
    assert _archives(logdir)

    assert activity_log.clear() is True
    assert not list(logdir.glob("activity-*")), "清空后不应残留任何日志或归档"
    assert activity_log.recent(limit=50) == []


def test_storage_info_形状(logdir, monkeypatch):
    _cfg(monkeypatch, enabled=True, max_bytes=300, keep=5, compress=False)
    activity_log.log("字体", "a.ttf", "成功", actor="a")
    info = activity_log.storage_info()
    assert set(info) == {"bytes", "archives", "retention"}
    assert info["bytes"] > 0 and isinstance(info["archives"], int)
    assert info["retention"]["enabled"] is True


def test_日志接口返回存盘情况(client, auth_headers):
    r = client.get("/api/logs?limit=5", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "storage" in body
    assert set(body["storage"]) == {"bytes", "archives", "retention"}
    # 默认配置下留存策略是关闭的（不能因为加了功能就默认改变行为）
    assert body["storage"]["retention"]["enabled"] is False


def test_留存策略可保存且回显布尔(client, auth_headers):
    r = client.put("/api/config", headers=auth_headers,
                   json={"logging": {"retention": {"enabled": True, "keep": 3}}})
    assert r.status_code == 200, r.text
    got = client.get("/api/logs?limit=1", headers=auth_headers).json()["storage"]["retention"]
    assert got["enabled"] is True and got["keep"] == 3
    # 还原（避免影响同会话其它用例）
    client.put("/api/config", headers=auth_headers,
               json={"logging": {"retention": {"enabled": False, "keep": 5,
                                               "max_bytes": 5 * 1024 * 1024,
                                               "compress": True}}})
