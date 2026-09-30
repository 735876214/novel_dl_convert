"""第 81 期：**「移除书库」不再在请求里搬文件** —— 两个口径 + 一条防回归。

线上故障复盘（库 ``lib-6a0b30d3``，约 2400 份 / 68 GB 漫画）：

- 旧实现 ``api_delete_library`` 把**跨文件系统的大搬迁**放在 HTTP 请求内同步跑
  （实测约 79 MB/s；``shutil.move`` 跨卷时退化为「复制 + 删源」）⇒ 请求数小时不返回，
  前端只能显示「失败」；期间 ``book_count`` 还在持续下降（说明动作其实在执行）。
- 那个库的 ``source_dirs`` 指向用户自己的漫画目录、``publish_path=""``，所以被当作
  「② 书库内成品」回收掉的**就是用户的本地原件** —— 与第 75 期「保留本地原件」的字面
  口径矛盾（名实不符）。

本期两条改动，逐条钉住：

1. **默认路径 = 只删登记、零文件触碰**（同步、立即返回 ``task_id=None``）；
2. ``purge_files=1`` 才连文件一起清，且改在**后台任务**里跑（逐份真进度、刻意不写 ``result``）；
3. ① 收书目录里的本地原件在**两条**路径下都不动。
"""
from __future__ import annotations

import pathlib
import time

from novelforge.core import db, epub_builder, fileops, library, scrape


def _epub(root, name: str = "三体.epub") -> pathlib.Path:
    """真 EPUB —— 出版链路要改写 OPF，占位字节过不去。"""
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": "三体", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(p))
    return p


def _lib(lid: str, root, pdir=None) -> dict:
    r = pathlib.Path(root)
    r.mkdir(parents=True, exist_ok=True)
    db.create_library(lid, lid, "ebook", source_dirs=str(r),
                      publish_path=str(pdir) if pdir else "")
    library.invalidate()
    return {"id": lid, "root": r, "pdir": pathlib.Path(pdir) if pdir else None}


def _book(lid: str, name: str) -> dict:
    library.invalidate()
    b = next((x for x in library.books(lid) if x["name"] == name), None)
    assert b is not None, f"扫描不到 {name}"
    return b


def _wait_task(client, headers, tid, timeout: float = 15.0) -> dict:
    end = time.time() + timeout
    row: dict = {}
    while time.time() < end:
        row = client.get(f"/api/tasks/{tid}", headers=headers).json()
        if row.get("status") in ("done", "failed"):
            return row
        time.sleep(0.02)
    raise AssertionError(f"任务 {tid} 超时未结束：{row}")


# ---------------------------------------------------------------------------
# 1. 默认路径：只删登记，**一个磁盘文件都不动**
# ---------------------------------------------------------------------------

def test_默认移除书库不动任何文件(client, auth_headers, tmp_path):
    """本期最容易写漏的一条：默认路径必须证明「磁盘零触碰」。

    断言不是「文件还在」（那太弱：一次跨卷复制也可能留下文件），而是
    **字节 + mtime_ns 逐项不变**，且回收目录里没有它的任何副本。
    """
    lib = _lib("p-default", tmp_path / "libs" / "d")
    src = _epub(lib["root"], "三体.epub")
    before = src.read_bytes()
    mtime = src.stat().st_mtime_ns
    # ⚠️ 回收目录是**会话级共享**的（CACHE_DIR 不随 `isolated` 切），所以断言只能看
    # 「本次有没有新增」，不能看「目录里本来有没有同名文件」——那会依赖用例执行顺序。
    recycle_before = {p.name for p in fileops.recycle_dir().iterdir()}

    r = client.delete(f"/api/libraries/{lib['id']}", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["books"] == 1
    assert body["purge_files"] is False
    assert body["targets"] == 0
    assert body["task_id"] is None, "默认路径不该产生任何后台任务"
    assert not any(t["type"] == "librarypurge" for t in db.task_list()), "默认路径不该排任务"

    assert src.is_file(), "默认移除书库**不许**动磁盘文件"
    assert src.read_bytes() == before, "文件内容必须逐字节不变"
    assert src.stat().st_mtime_ns == mtime, "连 mtime 都不该被碰（证明没走复制回退）"
    assert {p.name for p in fileops.recycle_dir().iterdir()} == recycle_before, \
        "默认路径不该产生任何回收件"

    assert db.get_library(lib["id"]) is None, "登记必须删掉"
    assert db.recycle_list() == [], "默认路径不写回收台账"


def test_默认路径连书库都不存在时404(client, auth_headers):
    assert client.delete("/api/libraries/没有这个库", headers=auth_headers).status_code == 404


# ---------------------------------------------------------------------------
# 2. purge_files=1：后台任务逐份回收（② + ③），台账留痕
# ---------------------------------------------------------------------------

def test_purge_files走后台任务_回收书库内文件与出版副本(client, auth_headers, tmp_path):
    lib = _lib("p-purge", tmp_path / "libs" / "p", pdir=tmp_path / "out" / "p")
    _epub(lib["root"], "三体.epub")
    b = _book(lib["id"], "三体.epub")
    # 真出版一次 ⇒ 台账里拿到 ③ 的真实路径（`link_rel`）
    assert scrape.enqueue(b)["queued"] is True
    assert scrape.run_once()["processed"] == 1
    row = db.scrape_get(b["id"])
    assert row["status"] == "ok", row
    copy_path = lib["pdir"] / row["link_rel"]
    assert copy_path.exists(), f"前置：副本应当已建出来：{copy_path}"
    recycle_before = {p.name for p in fileops.recycle_dir().iterdir()}

    r = client.delete(f"/api/libraries/{lib['id']}?purge_files=true", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["purge_files"] is True
    assert r.json()["targets"] == 2, "②（书库内文件）+ ③（出版副本）"
    tid = r.json()["task_id"]
    assert tid, "要清理文件就必须走后台任务"

    t = _wait_task(client, auth_headers, tid)
    assert t["status"] == "done", t
    assert t["type"] == "librarypurge"
    assert t["progress"] == 100.0
    assert t["result"] == "", "清理没有产物可下，result 留空（有它前端会渲染成下载按钮）"
    assert "回收 2 份" in (t["notice"] or ""), t["notice"]

    assert not (lib["root"] / "三体.epub").exists(), "② 书库内文件必须移走"
    assert not copy_path.exists(), "③ 出版副本必须移走"
    assert {p.name for p in fileops.recycle_dir().iterdir()} - recycle_before, \
        "回收目录里应当新增这批回收件"

    # 台账：两条，各自 orig_path 对得上（还原功能就靠它）
    rows = db.recycle_list()
    assert len(rows) == 2, rows
    origs = {str(x["orig_path"]) for x in rows}
    assert str(lib["root"] / "三体.epub") in origs
    assert str(copy_path) in origs
    # 登记与刮削台账都已清掉
    assert db.get_library(lib["id"]) is None
    assert db.scrape_get(b["id"]) is None, "库没了，刮削台账行不该留着"


def test_purge_files对空库不排任务(client, auth_headers, tmp_path):
    """空库 + purge_files：没有可回收的东西 ⇒ 不该白排一个任务。"""
    lib = _lib("p-empty", tmp_path / "libs" / "e")
    r = client.delete(f"/api/libraries/{lib['id']}?purge_files=true", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["targets"] == 0 and r.json()["task_id"] is None
    assert db.get_library(lib["id"]) is None


# ---------------------------------------------------------------------------
# 3. ① 收书目录里的本地原件：两条路径下都保留
# ---------------------------------------------------------------------------

def test_本地原件在两条路径下都保留(client, auth_headers, tmp_path):
    from novelforge import config
    lib = _lib("p-origin", tmp_path / "libs" / "o")
    _epub(lib["root"], "三体.epub")
    b = _book(lib["id"], "三体.epub")
    origin = pathlib.Path(config.DATA_DIR) / "收书目录" / "三体.epub"
    origin.parent.mkdir(parents=True, exist_ok=True)
    origin.write_bytes(b"ORIGINAL")
    db.origin_set(b["id"], str(origin))

    client.delete(f"/api/libraries/{lib['id']}", headers=auth_headers)
    assert origin.is_file(), "默认路径：① 必须保留"
    assert db.origin_get(b["id"]) == str(origin), "① 的登记也要留着（库再建回来认得出）"

    lib2 = _lib("p-origin2", tmp_path / "libs" / "o2")
    _epub(lib2["root"], "三体.epub")
    r = client.delete(f"/api/libraries/{lib2['id']}?purge_files=true", headers=auth_headers)
    _wait_task(client, auth_headers, r.json()["task_id"])
    assert origin.is_file(), "显式清理：① 依然保留（只清项目内的 ②③）"
