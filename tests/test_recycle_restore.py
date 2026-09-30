"""第 81 期：**回收站还原** 与 **长文件名加固**。

两件事一起测，因为它们是同一次线上事故的两半：

- **长名加固**：线上漫画库有 7 个 ≥240 字节的文件名（最长 277 字节），而 Linux 单文件名
  上限是 **255 字节（UTF-8）** ⇒ 旧落点名 ``f"{stamp}_{p.name}"`` 溢出，回收被记成 failed。
  修法在 :func:`fileops.recycled_name`（按字节边界截断 + 短哈希后缀），
  **回收落点名的唯一实现**（`publish.recycle` / `fileops.recycle_items` / `bookdock.remove`）。
- **台账 + 还原**：只有记下「哪条原路径被搬走了」才能把东西搬回去
  （`recycle_items` 表 + `core/recycle.py`）。本期要靠它把那批被误搬的漫画搬回原处。
- **刻意不含 ``book_id``**：台账认的是**磁盘路径**，不是某本书 ⇒ 不进 remap 四处清单。
"""
from __future__ import annotations

import pathlib
import time

from novelforge.core import db, fileops, publish, recycle

#: 本期要用到的两个 API 端点（字面量路径，不含 `{param}`）
API_LIST = "/api/recycle"
API_RESTORE = "/api/recycle/restore"


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
# 1. 落点名的字节长上限（纯函数）
# ---------------------------------------------------------------------------

def test_回收落点名按字节截断且不切坏多字节():
    stamp = "20260930-120000"
    # 短名：逐字保留原来的形状（`{stamp}_{原名}`）—— 存量口径不变
    assert fileops.recycled_name("三体.epub", stamp) == f"{stamp}_三体.epub"
    assert fileops.recycled_name("三体.epub", stamp, 2) == f"{stamp}_2_三体.epub"

    # 超长名：80 个汉字 + 扩展名 = 245 字节；加 17 字节前缀后必须被压回 ≤255
    name = "长" * 80 + ".epub"
    got = fileops.recycled_name(name, stamp)
    assert len(got.encode("utf-8")) <= fileops.RECYCLE_NAME_MAX, got
    got.encode("utf-8").decode("utf-8")          # 必须还是合法 UTF-8（没切坏多字节字符）
    assert got.startswith(stamp + "_")
    assert got.endswith(".epub"), "扩展名要尽量保住（否则在回收站里认不出是什么）"
    assert "~" in got, "超长名要有短哈希后缀（保唯一可辨）"

    # 目录型条目（没有扩展名）同样要压住
    got_dir = fileops.recycled_name("目" * 100, stamp)
    assert len(got_dir.encode("utf-8")) <= fileops.RECYCLE_NAME_MAX

    # 同名不同内容 ⇒ 哈希不同（截断后仍可辨）
    a = fileops.recycled_name("长" * 80 + "甲.epub", stamp)
    b = fileops.recycled_name("长" * 80 + "乙.epub", stamp)
    assert a != b


def test_超长文件名也能真的搬进回收站(isolated, tmp_path):
    """线上实测的那一形态：文件名本身 ≤255 字节（能创建），**加前缀后**才超。"""
    p = tmp_path / ("长" * 80 + ".epub")          # 245 字节，Windows / Linux 都能创建
    p.write_bytes(b"EPUB")
    dst = publish.recycle(p, why="测试超长名")
    assert dst is not None and dst.is_file(), "长名不该让回收整个失败"
    assert len(dst.name.encode("utf-8")) <= fileops.RECYCLE_NAME_MAX
    assert not p.exists(), "文件必须已从原处移走"
    # 台账照样记上（还原靠它）
    rows = db.recycle_list()
    assert len(rows) == 1 and rows[0]["recycled_name"] == dst.name
    assert rows[0]["orig_path"] == str(p)


# ---------------------------------------------------------------------------
# 2. 台账与列举
# ---------------------------------------------------------------------------

def test_回收台账表刻意不含book_id(isolated):
    """台账认的是**磁盘路径**，不是某本书 ⇒ 从设计上规避 remap 四处同步点。"""
    cols = {r["name"] for r in db._connect().execute("PRAGMA table_info(recycle_items)")}
    assert cols, "recycle_items 表应当存在"
    assert "book_id" not in cols, "刻意不含 book_id（见 core/db.py 建表注释）"
    for names in (db.ORPHAN_TABLES, db.REMAP_TABLES, db.REMAP_EXPLICIT_TABLES):
        assert "recycle_items" not in names


def test_回收后列表能给出原路径与磁盘实况(client, auth_headers, isolated, tmp_path):
    p = tmp_path / "三体.epub"
    p.write_bytes(b"EPUB")
    publish.recycle(p, why="测试")

    got = client.get(API_LIST, headers=auth_headers).json()
    assert got["total"] == 1, got
    it = got["items"][0]
    assert it["orig_path"] == str(p)
    assert it["why"] == "测试"
    assert it["exists"] is True and it["kind"] == "file"
    assert it["size"] == 4


# ---------------------------------------------------------------------------
# 3. 还原：按原路径搬回；已存在则退让不覆盖；幂等可续跑
# ---------------------------------------------------------------------------

def test_还原按原路径搬回(client, auth_headers, isolated, tmp_path):
    p = tmp_path / "三体.epub"
    p.write_bytes(b"EPUB-BYTES")
    publish.recycle(p, why="测试还原")
    assert not p.exists()

    r = client.post(API_RESTORE, headers=auth_headers, json={"all": True})
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 1
    t = _wait_task(client, auth_headers, r.json()["task_id"])
    assert t["status"] == "done", t
    assert t["type"] == "recycle" and t["progress"] == 100.0
    assert t["result"] == "", "还原没有产物可下"

    assert p.is_file() and p.read_bytes() == b"EPUB-BYTES", "字节必须原样回来"
    assert db.recycle_list() == [], "还原成功后台账行要删掉（幂等可续跑的前提）"

    # 幂等：再调一次 ⇒ 没有可还原的条目，不再排任务
    again = client.post(API_RESTORE, headers=auth_headers, json={"all": True})
    assert again.json()["task_id"] is None and again.json()["total"] == 0


def test_目标是已存在的文件时退让改名不覆盖(client, auth_headers, isolated, tmp_path):
    p = tmp_path / "退让.epub"
    p.write_bytes(b"OLD")
    publish.recycle(p, why="测试退让")
    p.write_bytes(b"NEW")                         # 原路径被别的东西占了

    r = client.post(API_RESTORE, headers=auth_headers, json={"all": True})
    t = _wait_task(client, auth_headers, r.json()["task_id"])
    assert t["status"] == "done", t
    assert "退让改名 1 份" in (t["notice"] or ""), t["notice"]

    assert p.read_bytes() == b"NEW", "**绝不覆盖**目标上已有的文件"
    assert (tmp_path / "退让 (2).epub").read_bytes() == b"OLD", "退让后的落点要如实说出来"


def test_恢复的条目不在台账时报错而不是静默(client, auth_headers, isolated, tmp_path):
    r = client.post(API_RESTORE, headers=auth_headers, json={"ids": [999]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["task_id"] is None and body["total"] == 0
    assert body["errors"] and "台账里没有这条记录" in body["errors"][0]["error"], body


# ---------------------------------------------------------------------------
# 4. 孤儿还原（历史无台账的文件：剥时间戳前缀 + 指定目录）
# ---------------------------------------------------------------------------

def test_孤儿还原必须指定目录_指定后按剥前缀的名字落进去(client, auth_headers, isolated, tmp_path):
    d = fileops.recycle_dir()
    orphan = d / "20260101-000000_历史孤儿.txt"
    orphan.write_bytes(b"LEGACY")

    listed = client.get(API_LIST, headers=auth_headers).json()
    assert any(o["name"] == orphan.name for o in listed["orphans"]), listed["orphans"]
    got = next(o for o in listed["orphans"] if o["name"] == orphan.name)
    assert got["stripped"] == "历史孤儿.txt" and got["stamp"] == "20260101-000000"

    # 不给 target_dir ⇒ 如实报错，不搬
    bad = client.post(API_RESTORE, headers=auth_headers, json={"names": [orphan.name]})
    assert bad.json()["task_id"] is None
    assert "必须指定还原目录" in bad.json()["errors"][0]["error"]
    assert orphan.is_file(), "报错时一个文件都不该动"

    target = tmp_path / "归位"
    ok = client.post(API_RESTORE, headers=auth_headers,
                     json={"names": [orphan.name], "target_dir": str(target)})
    t = _wait_task(client, auth_headers, ok.json()["task_id"])
    assert t["status"] == "done", t
    assert (target / "历史孤儿.txt").read_bytes() == b"LEGACY"
    assert not orphan.exists()


def test_孤儿条目名不许带路径分隔符(client, auth_headers, isolated):
    r = client.post(API_RESTORE, headers=auth_headers,
                    json={"names": ["../../etc/passwd"], "target_dir": "/tmp"})
    assert r.json()["errors"][0]["error"] == "条目名非法"


# ---------------------------------------------------------------------------
# 5. 清空回收站同批清台账
# ---------------------------------------------------------------------------

def test_清空回收站同时清掉台账(client, auth_headers, isolated, tmp_path):
    p = tmp_path / "要清的.epub"
    p.write_bytes(b"EPUB")
    publish.recycle(p, why="测试清空")
    assert db.recycle_list(), "前置：台账里应当有一条"

    r = client.post("/api/maintenance/recycle/clear", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ledger_cleared"] == 1
    assert db.recycle_list() == [], "文件都真删了，台账不该再宣称「可以还原」"


# ---------------------------------------------------------------------------
# 6. core/recycle 的纯函数
# ---------------------------------------------------------------------------

def test_剥时间戳前缀与退让命名():
    assert recycle.strip_stamp("20260930-120000_三体.epub") == ("三体.epub", "20260930-120000", 0)
    assert recycle.strip_stamp("20260930-120000_2_三体.epub") == ("三体.epub", "20260930-120000", 2)
    # 没有前缀（用户自己丢进回收目录的）⇒ 原名 / 空戳 / 0
    assert recycle.strip_stamp("用户自己的文件.epub") == ("用户自己的文件.epub", "", 0)

    assert not recycle._safe_name("a/b"), "含分隔符的名字一律不收"
    assert not recycle._safe_name("..") and not recycle._safe_name("")
    assert recycle._safe_name("三体.epub")
