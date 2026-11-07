"""Komga 兼容面**第四轮**审计的契约（第 269 期）。

这一轮的角度：**默认排序 / 排序字段的覆盖**、**聚合字段**、**ondeck 的语义**。

1. **系列内的默认顺序是文件名字典序**：12 卷的系列排成 `1,10,11,12,2,…`；
   而且 `sort=metadata.numberSort`（Komga 客户端真的会传）**不在排序表里** ⇒
   回落成 `name`，还是同一个错序。`grouped()` 本来已按卷号排好，默认再按字符串
   排一次反而把它打乱。**用户看到**：12 卷以上的系列「下一卷」跳到第 10 卷。
2. **`ondeck` 读完一卷就空**：判据要求「系列里有一本**在途**」，而读完第 1 卷之后
   系列里没有在途的书 ⇒ 整个系列从「继续阅读」消失（Komga 的语义是「已开始的系列 →
   下一本未读完的书」）。
3. **`SeriesDto.booksMetadata.authors` 恒空**：系列列表里每个系列都没有作者
   （书上有作者）。Komga 的系列作者就放在这里。
4. **系列 `tags` 与 `genres` 口径不一致**：同一份数据只进了 `genres`、`tags` 留空 ⇒
   客户端「按标签筛系列」永远筛不到。
"""
import io
import zipfile

import pytest

from novelforge import config
from novelforge.core import epub_builder, fileops, library


@pytest.fixture
def komga_on():
    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        yield {"X-API-Key": "test-key"}
    finally:
        config.save_overrides({})


def _vol(root, series: str, i: int, author: str = "某作者") -> None:
    p = root / series / f"{series} #{i}.epub"
    p.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": f"第{i}卷", "author": author, "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(p))
    assert fileops.patch_epub_meta(p, {"series": series, "series_index": str(i)})


def _scan(client, auth_headers):
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()


def _numbers(bs) -> list:
    return [b["metadata"]["number"] for b in bs]


# ---------------------------------------------------------------- 1. 默认顺序

def test_系列内默认顺序按卷号(client, auth_headers, make_library, tmp_path, komga_on):
    """12 卷的系列不许排成 1,10,11,12,2,…（文件名字典序）。"""
    root = tmp_path / "N"
    root.mkdir(parents=True, exist_ok=True)
    for i in range(1, 13):
        _vol(root, "长篇", i)
    make_library("N", "书库", "ebook", root)
    _scan(client, auth_headers)

    s = client.get("/api/v1/series?size=5", headers=komga_on).json()["content"][0]
    got = _numbers(client.get(f"/api/v1/series/{s['id']}/books?size=50",
                              headers=komga_on).json()["content"])
    assert got == [str(i) for i in range(1, 13)], f"默认顺序是字典序：{got}"

    asc = _numbers(client.get(
        f"/api/v1/series/{s['id']}/books?size=50&sort=metadata.numberSort,asc",
        headers=komga_on).json()["content"])
    assert asc == [str(i) for i in range(1, 13)], f"metadata.numberSort 没生效：{asc}"

    desc = _numbers(client.get(
        f"/api/v1/series/{s['id']}/books?size=50&sort=metadata.numberSort,desc",
        headers=komga_on).json()["content"])
    assert desc == [str(i) for i in range(12, 0, -1)], f"倒序不对：{desc}"


def test_全库列表也认卷号排序(client, auth_headers, make_library, tmp_path, komga_on):
    root = tmp_path / "A"
    root.mkdir(parents=True, exist_ok=True)
    for i in (1, 2, 10):
        _vol(root, "另一系列", i)
    make_library("A", "书库", "ebook", root)
    _scan(client, auth_headers)
    got = _numbers(client.get("/api/v1/books?size=50&sort=metadata.numberSort,asc",
                              headers=komga_on).json()["content"])
    assert got == ["1", "2", "10"], got


# ---------------------------------------------------------------- 2. ondeck

def test_ondeck_读完一卷之后给下一卷(client, auth_headers, make_library, tmp_path, komga_on):
    root = tmp_path / "O"
    root.mkdir(parents=True, exist_ok=True)
    for i in (1, 2, 3):
        _vol(root, "追更系列", i)
    make_library("O", "书库", "ebook", root)
    _scan(client, auth_headers)

    bs = client.get("/api/v1/books?size=10&sort=metadata.numberSort,asc",
                    headers=komga_on).json()["content"]
    ids = [b["id"] for b in bs]

    def ondeck() -> list:
        r = client.get("/api/v1/books/ondeck?size=10", headers=komga_on)
        return [b["name"] for b in r.json()["content"]]

    assert ondeck() == [], "一本没读就不该有待读"
    client.put("/api/v1/books/" + ids[0] + "/read-progress",
               json={"completed": True}, headers=komga_on)
    assert ondeck() == ["追更系列 #2.epub"], "读完第 1 卷，On Deck 应给第 2 卷"

    # 三本全读完 ⇒ 该系列退出 On Deck（不编造「下一本」）
    for bid in ids:
        client.put("/api/v1/books/" + bid + "/read-progress",
                   json={"completed": True}, headers=komga_on)
    assert ondeck() == [], "全读完还留着 On Deck 条目"


# ---------------------------------------------------------------- 3/4. 聚合字段

def test_系列聚合作者与首版年(client, auth_headers, make_library, tmp_path, komga_on):
    root = tmp_path / "S"
    root.mkdir(parents=True, exist_ok=True)
    for i in (1, 2):
        _vol(root, "有作者", i, author="刘慈欣")
    make_library("S", "书库", "ebook", root)
    _scan(client, auth_headers)

    bs = client.get("/api/v1/books?size=10", headers=komga_on).json()["content"]
    # 出版年 = OPF 的 `dc:date`（`date` 字段），不是独立的 year 键
    assert client.post("/api/books/" + bs[0]["id"] + "/metadata", headers=auth_headers,
                       json={"fields": {"date": "2010-03-01"}}).status_code == 200
    assert client.post("/api/books/" + bs[1]["id"] + "/metadata", headers=auth_headers,
                       json={"fields": {"date": "2008-05-01"}}).status_code == 200
    library.invalidate()

    s = client.get("/api/v1/series?size=5", headers=komga_on).json()["content"][0]
    meta = s["booksMetadata"]
    names = [a["name"] for a in meta["authors"]]
    assert names == ["刘慈欣"], f"系列没有作者：{meta['authors']}"
    # 取**最早**的那本（2008-05-01），不是 2010 那本；日期形态保留 `dc:date` 原文
    assert str(meta["releaseDate"]).startswith("2008"), f"首版日期没取最早的：{meta['releaseDate']}"


def test_系列的标签与_genres_是同一份(client, auth_headers, make_library, tmp_path, komga_on):
    root = tmp_path / "T"
    root.mkdir(parents=True, exist_ok=True)
    for i in (1, 2):
        _vol(root, "有标签", i)
    make_library("T", "书库", "ebook", root)
    _scan(client, auth_headers)

    bs = client.get("/api/v1/books?size=10", headers=komga_on).json()["content"]
    for b in bs:
        assert client.post("/api/books/" + b["id"] + "/metadata", headers=auth_headers,
                           json={"fields": {"tags": ["科幻", "太空"]}}).status_code == 200
    library.invalidate()

    s = client.get("/api/v1/series?size=5", headers=komga_on).json()["content"][0]
    assert s["metadata"]["tags"] == ["科幻", "太空"], s["metadata"]["tags"]
    assert s["metadata"]["genres"] == s["metadata"]["tags"], "两处口径不一致"
    assert s["booksMetadata"]["tags"] == s["metadata"]["tags"]
