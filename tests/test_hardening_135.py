"""第 135 期：第二轮审计（后端 7 条 + 前端 7 条）收口的**后端**契约用例。

口径：一条发现至少一条用例。这里只钉「修完之后的判据」，不测实现细节 ——
唯一例外是 B3（原子复制），它没有可观测行为，只能钉「入库存根不许再原地写」。

| 编号 | 发现 | 本文件的用例 |
|---|---|---|
| B1 | `upgrade_book_ids` 的 `rglob` 缩进跑出根循环 ⇒ 只有最后一个根被迁移、无来源目录的库 `UnboundLocalError` | `test_迁移要走到每一个库根` / `test_没有来源目录的库不再炸迁移` |
| B2 | `watcher.stop()` join 超时后置空线程引用 ⇒ 旧线程复活 + 双线程并扫 | `test_停止超时后保留线程引用` |
| B3 | 入库存根用 `shutil.copy2` 原地写 ⇒ 半截副本被索引 | `test_入库复制必须走原子写` |
| B4 | `_safe_name` 不挡 `..` ⇒ 音频缓存写到父目录、回滚删父目录 | `test_书名清洗不会逃到父目录` |
| B5 | 刮削异常只记日志不记台账 ⇒ 状态永远卡在 `running` | `test_刮削异常不会把台账卡在running` |
| B6 | 命令行闸门拒绝时 `return` ⇒ 退出码 0 | `test_下载闸门拒绝时退出码是2` |
| B7 | 自动展开失败只记指纹不记日志 ⇒ 坏包永久静默跳过 | `test_自动展开失败要留痕` |
"""

import json

import pytest

from novelforge import cli, config
from novelforge.core import (activity_log, db, library, publish, scrape, watcher)

# ---------------------------------------------------------------------------
# B1 —— 迁移要遍历**每一个**库根
# ---------------------------------------------------------------------------

def test_迁移要走到每一个库根(isolated, make_library, tmp_path):  # noqa: ARG001
    """`upgrade_book_ids` 的 `rglob` 曾与 `for _dp in _dir_list:` 同缩进（跑在循环外）。

    后果不是「慢一点」：只有**最后一个根**参与迁移，其余根里的书永远拿不到新 id。
    """
    root_a, root_b = tmp_path / "迁移A", tmp_path / "迁移B"
    root_a.mkdir(parents=True, exist_ok=True)
    root_b.mkdir(parents=True, exist_ok=True)
    (root_a / "a1.txt").write_text("甲", encoding="utf-8")
    (root_a / "a2.txt").write_text("乙", encoding="utf-8")
    (root_b / "b1.txt").write_text("丙", encoding="utf-8")

    lib = make_library("lib-migrate-135", "迁移库", "ebook", root_a)
    db.update_library(lib["id"], source_dirs=json.dumps([str(root_a), str(root_b)]))
    db.state_set("bookid_v2", "0")          # 让迁移真的跑一轮（否则开机会跳过）

    res = db.upgrade_book_ids()
    assert res["skipped"] is False, res
    assert res["indexed"] >= 3, f"两个根里的文件都要进索引（只跑一个根会少）：{res}"
    assert db.state_get("bookid_v2") == "1"


def test_没有来源目录的库不再炸迁移(isolated, make_library, tmp_path):  # noqa: ARG001
    """`source_dirs` 为空时 `d` 从未绑定 —— 以前是 `UnboundLocalError`（被开机流程吞掉）。"""
    lib = make_library("lib-emptyroot-135", "空根库", "ebook", tmp_path / "空根")
    db.update_library(lib["id"], source_dirs="[]")
    db.state_set("bookid_v2", "0")

    res = db.upgrade_book_ids()
    assert res["skipped"] is False, res
    assert db.state_get("bookid_v2") == "1", "迁移没跑完就退出的话每次启动都会重试"


# ---------------------------------------------------------------------------
# B2 —— stop() 超时不许丢掉线程引用
# ---------------------------------------------------------------------------

def test_停止超时后保留线程引用(isolated):  # noqa: ARG001
    """`join` 超时后置空引用 ⇒ `start()` 立刻起新线程并 `_stop.clear()`，两个线程并扫。"""
    w = watcher.FolderWatcher(input_dir=config.INPUT_DIR, output_dir=config.OUTPUT_DIR,
                              cfg={"watcher": {"interval": 0.0}})
    joined = []

    class _SlowThread:                       # 冒充「一条收不掉的扫描线程」
        def is_alive(self):
            return True

        def join(self, timeout=None):
            joined.append(timeout)           # 超时返回，线程其实还活着

    fake = _SlowThread()
    w._thread = fake
    w.stop()

    assert joined, "stop() 必须给它一次 join 的机会"
    assert w._thread is fake, "join 超时后仍要保留引用（否则 start() 会再起一条）"
    assert w.is_running() is True, "还在跑就得如实说在跑"


# ---------------------------------------------------------------------------
# B3 —— 入库复制必须原子（半截副本不许进索引）
# ---------------------------------------------------------------------------

def test_入库复制必须走原子写():
    """`shutil.copy2` 直接写目标文件 ⇒ 扫描可能把「写了一半」的副本当成品书。

    全仓纪律是「临时文件 + `Path.replace`」（`landing._copy_atomic` 就是唯一实现）。
    """
    import pathlib
    src = pathlib.Path(__file__).resolve().parents[1] / "novelforge" / "core" / "watcher.py"
    text = src.read_text(encoding="utf-8")
    assert "shutil.copy2" not in text, "入库存根又用回原地写了：应走 landing._copy_atomic"
    assert "_copy_atomic(p, dst)" in text


# ---------------------------------------------------------------------------
# B4 —— 书名清洗不许逃出父目录
# ---------------------------------------------------------------------------

def test_书名清洗不会逃到父目录():
    from novelforge.sources.manager import _safe_name

    for raw in ("..", ".", " ../etc/passwd ", ".git", "a. ", "...."):
        name = _safe_name(raw)
        assert "/" not in name and "\\" not in name, f"{raw!r} → {name!r} 还带路径分隔符"
        assert name not in ("", ".", ".."), f"{raw!r} → {name!r} 仍指向目录自身/父目录"
        assert not name.startswith("."), f"{raw!r} → {name!r} 是隐藏名/上跳名"


# ---------------------------------------------------------------------------
# B5 —— 刮削异常必须记台账（不许永远 running）
# ---------------------------------------------------------------------------

def test_刮削异常不会把台账卡在running(isolated, make_library, make_epub, monkeypatch, tmp_path):  # noqa: ARG001
    root = tmp_path / "刮削源"
    lib = make_library("lib-scrape-135", "刮削库", "ebook", root)
    db.update_library(lib["id"], publish_path=str(tmp_path / "成品"))
    make_epub(root, "异常.epub")
    library.invalidate()
    book = next(b for b in library.books(lib["id"]) if b["name"] == "异常.epub")
    assert scrape.enqueue(book)["queued"] is True

    def _boom(*_a, **_k):
        raise RuntimeError("出版炸了")

    monkeypatch.setattr(publish, "publish", _boom)
    out = scrape.process(book["id"], fetch=False)

    assert out["ok"] is False, out
    assert "RuntimeError" in out["error"], out
    row = db.scrape_get(book["id"]) or {}
    assert row.get("status") != "running", f"异常上抛后台账永久卡在「进行中」：{row}"
    assert "出版炸了" in str(row.get("error") or ""), row
    assert row.get("status") in ("pending", "failed"), row


# ---------------------------------------------------------------------------
# B6 —— 命令行闸门拒绝要给非 0 退出码
# ---------------------------------------------------------------------------

def test_下载闸门拒绝时退出码是2(monkeypatch):
    """返回 0 会让脚本把「下载没开」当成「网上没这本书」。"""
    import asyncio
    from types import SimpleNamespace

    monkeypatch.setattr(cli.DownloadManager, "gate_reason",
                        lambda self: "下载未开启（设置里打开它）")

    for fn, args in (
        (cli.cmd_search, SimpleNamespace(title="任意书名")),
        (cli.cmd_download, SimpleNamespace(item=None, source="", url="",
                                           title="任意书名", author="", out=None)),
    ):
        with pytest.raises(SystemExit) as ei:
            asyncio.run(fn(args))
        assert ei.value.code == 2, f"{fn.__name__} 被拒时的退出码应当是 2"


# ---------------------------------------------------------------------------
# B7 —— 自动展开失败要留痕
# ---------------------------------------------------------------------------

def test_自动展开失败要留痕(isolated, default_root, monkeypatch):  # noqa: ARG001
    """只记指纹不记日志 ⇒ 坏包永久跳过、用户零感知（后台任务诚实性）。"""
    import pathlib

    bad = pathlib.Path(default_root) / "坏包.zip"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"this is not a zip file at all")
    library.invalidate()

    logs = []
    monkeypatch.setattr(activity_log, "log",
                        lambda *a, **k: logs.append((a, k)) or {})

    w = watcher.FolderWatcher(input_dir=config.INPUT_DIR, output_dir=config.OUTPUT_DIR,
                              cfg={"libraries": {"auto_unpack": True},
                                   "watcher": {"interval": 5.0}})
    w.index_interval = 0.0                   # 关掉节流：用例里要立刻跑一轮
    w._auto_unpack_tick()

    # `log(action, file, status, …, detail=…)` —— 前三个是位置参数
    fails = [(a, k) for a, k in logs
             if len(a) >= 3 and a[2] == activity_log.STATUS_FAIL
             and "自动展开" in str(k.get("detail") or "")]
    assert fails, f"展开失败没留痕（活动日志里没有这条）：{logs}"
    assert fails[0][0][1] == bad.name, fails[0]
    assert bad.is_file(), "源容器必须原样保留"
