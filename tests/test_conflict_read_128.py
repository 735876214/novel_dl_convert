"""同名冲突的**降级路径**（第 128 期）。

``book_id`` 只由 basename 派生（``库id$sha1(basename)``）⇒ 同一个书库里两个不同
目录下的同名书会撞同一个 id。而**旧库里的冲突是按设计可以存在的**：入库拦截是
第 13 期才补的，那之前写进去的书、以及「先有书、后又在另一个目录放了同名文件」
都会留下冲突 —— 修复入口（改名）恰恰要求用户先能打开应用。

改前的实测表现（隔离实例复现）：只要那个 id 上有**一条旧批注**，
``GET /api/annotations`` 与 ``GET /api/annotations/export`` 就恒 500
（连「先导出备份再去改名」这条路都走不通），``GET /api/books/{bid}`` 也是 500
—— 响应体里没有任何可行动的线索。

本文件钉住四条：
1. 单书入口 ⇒ **409** + ``code="book_id_conflict"`` + 修复指引（不是 500）；
2. 批注总览 ⇒ **200**，冲突只是那一行的状态（``book_conflict``）；
3. 批注导出 ⇒ **200**（它就是「先备份」那一步）；
4. 无冲突 / 跨库同名 ⇒ ``book_conflict`` 为假（别把正常的书也标成冲突）。
"""
from novelforge.core import db, library


def _conflict_library(make_library, make_book, tmp_path, lid="lib-a"):
    """造一个「同库两个目录同名」的真冲突，返回 (库 id, 撞车的 book_id)。"""
    root = tmp_path / "libraries" / lid
    make_library(lid, "甲库", "ebook", root)
    make_book(root, "三体.epub")            # 平铺
    make_book(root, "科幻/三体.epub")        # 同库不同路径同名 ⇒ 同 id
    library.invalidate()
    return lid, library.book_id("三体.epub", lid)


def test_冲突时单书详情回409并带修复指引(client, auth_headers, make_library, make_book, tmp_path):
    _lid, bid = _conflict_library(make_library, make_book, tmp_path)

    r = client.get(f"/api/books/{bid}", headers=auth_headers)
    assert r.status_code == 409, f"冲突不该是 500：{r.status_code} {r.text}"
    body = r.json()
    assert body["code"] == "book_id_conflict"
    assert "同名冲突" in body["hint"], "响应体必须给出可行动的修复入口"
    # 文案按实际情形说 —— 这组是**同一个库**里的两个目录，不是跨库
    assert "在同一个书库里" in body["detail"]
    assert "跨库" not in body["detail"]


def test_冲突时批注总览照出且标出冲突(client, auth_headers, make_library, make_book, tmp_path):
    _lid, bid = _conflict_library(make_library, make_book, tmp_path)
    db.add_annotation(bid, 0, "正文", "yellow", "旧批注")

    r = client.get("/api/annotations", headers=auth_headers)
    assert r.status_code == 200, f"一条坏记录不该让整页打不开：{r.text}"
    rows = [i for i in r.json()["items"] if i["book_id"] == bid]
    assert len(rows) == 1
    assert rows[0]["book_conflict"] is True
    # 取不到书名时**回退成 id**，而不是编一个「未知」或空串
    assert rows[0]["book_title"] == bid
    assert rows[0]["book_author"] == ""


def test_冲突时批注导出仍可用(client, auth_headers, make_library, make_book, tmp_path):
    _lid, bid = _conflict_library(make_library, make_book, tmp_path)
    db.add_annotation(bid, 0, "正文", "yellow", "")

    r = client.get("/api/annotations/export?format=json", headers=auth_headers)
    assert r.status_code == 200, f"导出是「先备份再去修」那一步，不能挂：{r.text}"
    rows = [i for i in r.json()["items"] if i["book_id"] == bid]
    assert rows and rows[0]["book_conflict"] is True


def test_无冲突时book_conflict为假(client, auth_headers, make_library, make_book, tmp_path):
    root = tmp_path / "libraries" / "lib-ok"
    make_library("lib-ok", "乙库", "ebook", root)
    make_book(root, "独一本.epub")
    library.invalidate()
    bid = library.book_id("独一本.epub", "lib-ok")
    db.add_annotation(bid, 0, "正文", "yellow", "")

    r = client.get("/api/annotations", headers=auth_headers)
    assert r.status_code == 200
    row = [i for i in r.json()["items"] if i["book_id"] == bid][0]
    assert row["book_conflict"] is False
    assert row["book_title"] == "独一本", "正常书的书名照旧来自书目，不是 id"


def test_跨库同名不算冲突(client, auth_headers, make_library, make_book, tmp_path):
    """第 17 期语义的回归：跨库同名各自 id 不同，详情照常 200。"""
    for lid in ("lib-x", "lib-y"):
        make_library(lid, lid, "ebook", tmp_path / "libraries" / lid)
        make_book(tmp_path / "libraries" / lid, "同名.epub")
    library.invalidate()

    ids = {library.book_id("同名.epub", lid) for lid in ("lib-x", "lib-y")}
    assert len(ids) == 2, "跨库同名必须得到两个不同 id"
    for bid in ids:
        r = client.get(f"/api/books/{bid}", headers=auth_headers)
        assert r.status_code == 200, f"跨库同名不是冲突：{r.status_code} {r.text}"
