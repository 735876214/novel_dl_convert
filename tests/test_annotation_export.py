"""第 43 期：批注导出（markdown / json / csv）。

三条口径：
1. **只导活跃批注**（`deleted_at=0`）—— 垃圾桶里的是已丢弃的内容，不该出现在导出的书摘里；
2. 三种格式都要能出，并带 `Content-Disposition` 文件名（前端靠它命名）；
3. 可按单书 / 书库收窄；未知格式 400。
"""
from __future__ import annotations

from novelforge.core import library


def _bid(root, make_book, name: str) -> str:
    make_book(root, name)
    library.invalidate()
    # ⚠️ ``force=True`` 不是保险，是**必须**：读路径对「索引非空 + 标脏」只做
    # **有上限**的等待（``catalog.SETTLE_WAIT`` = 0.25 s，到点如实返回现有索引），
    # 全量跑起来机器负载高时那一拍等不到后台刷新跑完 ⇒ 第二次调本函数就扫不到
    # ``二.epub``。第 129 期全量里正是这么红的（单独跑必绿，只有满载才红）。
    # 写完要立刻读，就得明确要求同步重扫，别赌时序。
    books = [b for b in library.books(force=True) if b["name"].endswith(name)]
    assert books, f"扫描没找到 {name}"
    return books[0]["id"]


def _add(client, headers, bid: str, quote: str, note: str = "") -> int:
    r = client.post(
        f"/api/books/{bid}/annotations",
        headers=headers,
        json={"chapter": 1, "quote": quote, "note": note, "color": "yellow"},
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_导出markdown含书名与摘录(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book, "三体.epub")
    _add(client, auth_headers, bid, "凡是过去，皆为序章", note="笔记A")

    r = client.get("/api/annotations/export?format=markdown", headers=auth_headers)

    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/markdown")
    assert "attachment" in r.headers["content-disposition"]
    assert "凡是过去，皆为序章" in r.text
    assert "笔记A" in r.text


def test_导出json与csv(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book, "三体.epub")
    _add(client, auth_headers, bid, "摘录一")

    j = client.get("/api/annotations/export?format=json", headers=auth_headers)
    assert j.status_code == 200, j.text
    assert j.json()["total"] == 1
    assert j.json()["items"][0]["quote"] == "摘录一"

    c = client.get("/api/annotations/export?format=csv", headers=auth_headers)
    assert c.status_code == 200, c.text
    assert "quote" in c.text
    assert "摘录一" in c.text


def test_垃圾桶批注不导出(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book, "三体.epub")
    aid = _add(client, auth_headers, bid, "会被删掉的摘录")

    d = client.delete(f"/api/books/{bid}/annotations/{aid}", headers=auth_headers)
    assert d.status_code == 200, d.text

    out = client.get("/api/annotations/export?format=json", headers=auth_headers)
    assert out.json()["total"] == 0


def test_按单书收窄(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    a = _bid(default_root, make_book, "一.epub")
    b = _bid(default_root, make_book, "二.epub")
    _add(client, auth_headers, a, "A 的摘录")
    _add(client, auth_headers, b, "B 的摘录")

    out = client.get(
        f"/api/annotations/export?format=json&book_id={a}", headers=auth_headers
    ).json()

    assert out["total"] == 1
    assert out["items"][0]["quote"] == "A 的摘录"


def test_未知格式被拒(client, auth_headers):
    r = client.get("/api/annotations/export?format=docx", headers=auth_headers)
    assert r.status_code == 400
