"""侧栏「浏览」三计数的缓存：失效竞态 + 清孤儿记录漏失效（第 288 期）。

第 287 期补上了「批注写入口要调 `library.invalidate_counts()`」，但这一层还剩两处：

① **计算与失效的竞态**：`counts()` 先在锁内读缓存（未命中）→ 出锁 `_compute()`
   → 再进锁写缓存。若 `_compute()` 期间发生了一次写入（它要遍历书目 / 查批注表，
   冷索引或 NAS 上可达数百毫秒），那次 `invalidate()` 丢的正是**还没写进去的键**，
   随后旧结果被写回 ⇒ 侧栏又错 60 秒。与第 88 期 `catalog` 的脏计数同一条教训：
   **「算之前」与「存之前」必须是同一代**。
② **清孤儿记录也会删批注行**（`ORPHAN_TABLES` 含 `annotations`），但
   `/api/maintenance/orphans/clear` 只删库、不失效侧栏计数 ⇒ 清完之后侧栏「批注」
   仍显示旧数字（最多 60 秒）。与第 287 期修的是同一条纪律，这是漏掉的第二个写入口。
"""
import threading
import time

from novelforge.core import browse_counts, epub_builder, library


def test_计算期间被失效时旧结果不得写回缓存(monkeypatch):
    browse_counts.invalidate("")
    started = threading.Event()
    release = threading.Event()
    calls = {"n": 0}

    def fake_compute(lid):
        calls["n"] += 1
        n = calls["n"]
        started.set()
        release.wait(10)
        return {"library_id": lid, "authors": n, "series": 0,
                "annotations": n, "books": 0, "computed_at": time.time()}

    monkeypatch.setattr(browse_counts, "_compute", fake_compute)

    out = {}
    t = threading.Thread(target=lambda: out.update(browse_counts.counts("")))
    t.start()
    try:
        assert started.wait(10), "计算没开始"
        browse_counts.invalidate("")   # 计算进行中发生写入 ⇒ 这份结果必须作废
        release.set()
        t.join(10)
        assert not t.is_alive()
    finally:
        release.set()

    second = browse_counts.counts("")
    assert second["cached"] is False, "计算期间被失效，旧结果却被写回缓存"
    assert second["annotations"] == 2
    browse_counts.invalidate("")


def _library_with_two_books(client, auth_headers, make_library, tmp_path):
    root = tmp_path / "L"
    root.mkdir(parents=True, exist_ok=True)
    for name, title in (("a.epub", "书A"), ("b.epub", "书B")):
        epub_builder.build_epub(
            {"title": title, "author": "作者", "language": "zh"},
            [{"title": "第一章", "body_html": "<p>x</p>"}], str(root / name))
    make_library("L", "库", "ebook", root)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    return root, {it["title"]: it["id"] for it in items}


def test_清孤儿记录后侧栏批注计数立刻刷新(client, auth_headers, make_library, tmp_path):
    browse_counts.invalidate("")
    root, ids = _library_with_two_books(client, auth_headers, make_library, tmp_path)
    bid_a = ids["书A"]

    r = client.post(f"/api/books/{bid_a}/annotations", headers=auth_headers,
                    json={"quote": "选中一句", "chapter": 1})
    assert r.status_code == 200, r.text
    first = client.get("/api/browse-counts", headers=auth_headers).json()
    assert first["cached"] is False
    assert first["annotations"] == 1, first

    # 书 A 的文件消失；同库的 B 还在 ⇒ A 的批注行成为「可清理的孤儿」
    (root / "a.epub").unlink()
    library.books(force=True)
    orphans = client.get("/api/maintenance/orphans", headers=auth_headers).json()
    ann_ids = (orphans.get("tables", {}).get("annotations") or {}).get("sample") or []
    assert bid_a in ann_ids, orphans

    cleared = client.post("/api/maintenance/orphans/clear", headers=auth_headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json().get("removed", {}).get("annotations") == 1, cleared.text

    after = client.get("/api/browse-counts", headers=auth_headers).json()
    assert after["cached"] is False, "清孤儿删掉了批注行，侧栏计数却还在吃缓存"
    assert after["annotations"] == 0, after
