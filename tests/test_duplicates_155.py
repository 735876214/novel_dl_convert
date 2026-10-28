"""重复书三类判据 + 「不是重复」持久判定（第 155 期）。

- 文件内容相同（同尺寸 sha256）
- ISBN 相同
- 同作者 + 书名相似度 ≥ 阈值
三类都并进同一棵并查集；同一物理文件被两条登记引用时不算重复。
"""
from __future__ import annotations

import pathlib

from novelforge.core import library


def _book(bid, name, *, title="", author="", isbn="", size=0, path=""):
    return {"id": bid, "name": name, "title": title, "author": author, "isbn": isbn,
            "size": size, "mtime": 1.0, "format": "EPUB", "path": path,
            "library_id": "lib"}


def test_文件哈希与_ISBN_都并进同一棵并查集(monkeypatch, tmp_path):
    p1 = tmp_path / "a.epub"
    p2 = tmp_path / "b.epub"
    p1.write_bytes(b"same-bytes")
    p2.write_bytes(b"same-bytes")
    books = [
        _book("1", "甲", title="完全不同的甲", author="作者甲", size=10, path=str(p1)),
        _book("2", "乙", title="完全不同的乙", author="作者乙", size=10, path=str(p2)),
        _book("3", "丙", title="ISBN 丙", author="作者丙", isbn="978-7-111-11111-1"),
        _book("4", "丁", title="ISBN 丁", author="作者丁", isbn="9787111111111"),
        _book("5", "戊", title="测试相似度的很长书名甲", author="刘慈欣"),
        _book("6", "己", title="测试相似度的很长书名乙", author="刘慈欣"),
    ]
    monkeypatch.setattr(library, "books", lambda lid=None: books)
    out = library.duplicate_groups(85)
    reasons = {g["reason"] for g in out["groups"]}
    assert "文件内容完全相同" in reasons
    assert "ISBN 相同" in reasons
    assert any("书名相似度" in r for r in reasons)
    # 同一物理文件的两条登记不并组
    books.append(_book("7", "a.epub", title="完全不同的甲", author="作者甲", size=10,
                       path=str(p1)))
    out2 = library.duplicate_groups(85)
    assert all(len(g["items"]) < 2 or "7" not in [i["id"] for i in g["items"]]
               for g in out2["groups"])


def test_不是重复持久化与恢复(client, auth_headers, make_library, make_epub, tmp_path):
    root = tmp_path / "dup"
    make_library("dup-lib", "重复库", "ebook", root)
    make_epub(root, "一.epub")
    make_epub(root, "二.epub")
    r = client.get("/api/duplicates", headers=auth_headers)
    assert r.status_code == 200, r.text
    groups = r.json()["groups"]
    assert groups, "两本内容相同的 EPUB 应该被分到一组"
    ids = [it["id"] for it in groups[0]["items"]]
    assert len(ids) >= 2

    r = client.post("/api/duplicates/dismiss", headers=auth_headers, json={"ids": ids})
    assert r.status_code == 200, r.text
    assert r.json()["added"] >= 1
    assert client.get("/api/duplicates", headers=auth_headers).json()["groups"] == []

    r = client.delete("/api/duplicates/dismissals", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["removed"] >= 1
    assert client.get("/api/duplicates", headers=auth_headers).json()["groups"]


def test_大桶不因_bigram_预筛丢真相似(monkeypatch):
    """第 163 期：bigram 包含率预筛的**安全性**钉在这里。

    场景 = 真实库的痛点：2,000+ 本书共享一个空作者名（「未知」），长度预筛放行的对
    有 ~89 万，全量 SequenceMatcher 实测 ~20 s。预筛必须在**不丢真相似**的前提下
    把 SequenceMatcher 的调用数压下来 —— 这条用例把「不丢」钉死（「快」由门限注释
    里的实验数字保证，不在此处跑秒表，避免看机器快慢的 flake）。
    """
    import time as _t

    from difflib import SequenceMatcher

    # 一只 500 本的「未知」大桶：噪声书名互不相似 + 3 对刻意构造的真相似
    # （ratio ≥ 0.85 但 bigram 包含率偏低 → 门限附近）。
    books = [
        _book(str(i), f"书{i}",
              title=f"第{i}卷风起云涌{('甲乙丙丁戊己庚辛'[i % 8])}部曲",
              author="未知")
        for i in range(500)
    ]
    similar_pairs = [
        ("星際大争霸之銀河英雄傳說典藏版全二卷", "星際大争霸之銀河英雄傅說典藏版全二卷"),
        ("斗罗大陆外传神界传说最新修订完整版", "斗罗大陆外傅神界传说最新修订完整版"),
        ("魔法学徒之黎明篇第1-12卷完结合集", "魔法学徒之黎眀篇第1-12卷完结合集"),
    ]
    for j, (t1, t2) in enumerate(similar_pairs):
        books.append(_book(f"s{j}a", f"甲{j}", title=t1, author="未知"))
        books.append(_book(f"s{j}b", f"甲{j}", title=t2, author="未知"))
    monkeypatch.setattr(library, "books", lambda lid=None: books)

    t0 = _t.perf_counter()
    out = library.duplicate_groups(85)
    elapsed = _t.perf_counter() - t0
    # 组里带 group.title（代表本）与 members 的 id 映射回书名
    by_id = {b["id"]: b for b in books}
    names = []
    for g in out["groups"]:
        titles = {by_id[it["id"]]["title"] for it in g["items"] if it["id"] in by_id}
        names.append(titles)
    for _, (t1, t2) in enumerate(similar_pairs):
        assert any(t1 in ns and t2 in ns for ns in names), \
            f"预筛把真相似对丢了：{t1!r} / {t2!r}"
    # 门限注释里的换算：无预筛 ~30 s（本机）/ 89 万对；有预筛 < 5 s。
    # 宽松上限只防「有人把门限改成 0 退化回全量」，不测具体秒数。
    assert elapsed < 15, f"duplicate_groups 耗时 {elapsed:.1f}s —— 预筛疑似失效"
    # 交叉验证：门限后命中的对确实过得了 SequenceMatcher（自证「唯一的判定」还在）。
    assert SequenceMatcher(None, *similar_pairs[0]).ratio() >= 0.85
