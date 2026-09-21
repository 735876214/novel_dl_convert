"""第 34 期：侧栏「浏览」组的三个计数（作者 / 系列 / 批注）。

这份计数最容易出的错不是算错，而是**算的跟目标页不是一回事** ——
侧栏写「作者 3」而 `/authors` 页列出 12 位，用户只会觉得界面在胡扯。
所以这里的核心断言是「与目标页同源」：计数必须等于对应接口返回的条数。
另外两条：按库可选收窄、60 秒节流（节流本身就是「数据变了但马上又读还是旧值」）。
"""
import pathlib

from novelforge.core import browse_counts, db, library


def _book(root, name: str) -> str:
    """造一本占位书并返回它的 book_id（扫描只按扩展名收，不需要真 EPUB）。"""
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"EPUB")
    library.invalidate()
    hits = [b for b in library.books() if b["name"].endswith(name)]
    assert hits, f"扫描没找到 {name}"
    return hits[0]["id"]


def _series(client, headers, bid: str, series: str) -> None:
    r = client.post(f"/api/books/{bid}/metadata",
                    json={"fields": {"series": series}}, headers=headers)
    assert r.status_code == 200, r.text


def _anno(client, headers, bid: str, quote: str) -> int:
    r = client.post(f"/api/books/{bid}/annotations",
                    json={"quote": quote, "chapter": 1, "color": "yellow", "note": ""},
                    headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_三数与目标页同源(client, auth_headers, default_root):
    """作者 / 系列 / 批注三个数，必须分别等于三个目标页的条数。"""
    a = _book(default_root, "银河帝国 1.epub")
    b = _book(default_root, "银河帝国 2.epub")
    # 第三本换个作者：作者数才有区分度
    c = _book(default_root, "沙丘.epub")
    for bid, name in ((a, "银河帝国"), (b, "银河帝国")):
        _series(client, auth_headers, bid, name)
    _anno(client, auth_headers, a, "摘录一")
    _anno(client, auth_headers, a, "摘录二")
    _anno(client, auth_headers, c, "摘录三")
    # 垃圾桶里的批注不该计入（与「批注」页的活跃档同一口径）
    trashed = _anno(client, auth_headers, b, "要丢掉的")
    assert client.delete(f"/api/books/{b}/annotations/{trashed}",
                         headers=auth_headers).status_code == 200

    browse_counts.invalidate()
    got = client.get("/api/browse-counts", headers=auth_headers).json()

    authors_total = client.get("/api/authors", headers=auth_headers).json()["total"]
    series_total = client.get("/api/series", headers=auth_headers).json()["total"]
    annos_total = client.get("/api/annotations", headers=auth_headers).json()["total"]
    assert got["authors"] == authors_total == 1   # 三本书都不带 OPF 作者 → 全归「未知」一格
    assert got["series"] == series_total == 1     # 只有「银河帝国」一个系列
    assert got["annotations"] == annos_total == 3, "垃圾桶里的批注不该计入"
    assert got["books"] == 3
    assert got["cached"] is False


def test_两个系列与两个作者(client, auth_headers, default_root):
    """上一例的「未知」是扫出来的真实结果；这里用元数据把作者也做成两档。"""
    a = _book(default_root, "甲.epub")
    b = _book(default_root, "乙.epub")
    for bid, author, series in ((a, "作者甲", "系列一"), (b, "作者乙", "系列二")):
        r = client.post(f"/api/books/{bid}/metadata",
                        json={"fields": {"author": author, "series": series}},
                        headers=auth_headers)
        assert r.status_code == 200, r.text

    browse_counts.invalidate()
    got = client.get("/api/browse-counts", headers=auth_headers).json()
    assert (got["authors"], got["series"]) == (2, 2)
    assert got["authors"] == client.get("/api/authors", headers=auth_headers).json()["total"]
    assert got["series"] == client.get("/api/series", headers=auth_headers).json()["total"]


def test_按库收窄_只算该库(client, auth_headers, default_root, make_library, tmp_path):
    a = _book(default_root, "默认库的书.epub")
    other_root = tmp_path / "libs" / "comics"
    make_library("comic", "漫画库", "comic", other_root)
    b = _book(other_root, "漫画一.cbz")
    c = _book(other_root, "漫画二.cbz")
    # 默认库 1 个系列、漫画库 2 个系列 —— 收窄才看得出来
    _series(client, auth_headers, a, "默认库系列")
    _series(client, auth_headers, b, "漫画系列甲")
    _series(client, auth_headers, c, "漫画系列乙")
    _anno(client, auth_headers, a, "默认库里的批注")
    _anno(client, auth_headers, b, "漫画里的批注")

    browse_counts.invalidate()
    all_ = client.get("/api/browse-counts", headers=auth_headers).json()
    mine = client.get("/api/browse-counts?library_id=comic", headers=auth_headers).json()

    assert (all_["books"], all_["series"], all_["annotations"]) == (3, 3, 2)
    assert (mine["books"], mine["series"], mine["annotations"]) == (2, 2, 1), \
        "按库收窄没生效（或批注没跟着书过滤）"
    assert mine["library_id"] == "comic"


def test_未知库返回全零不404(client, auth_headers, default_root):
    _book(default_root, "书.epub")
    browse_counts.invalidate()
    r = client.get("/api/browse-counts?library_id=不存在的库", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["books"], body["authors"], body["series"], body["annotations"]) == (0, 0, 0, 0)


def test_节流生效_数据变了TTL内仍给缓存值(client, auth_headers, default_root):
    """节流不是「省一次请求」这种模糊说法，它的可观测后果就是这条断言。"""
    _book(default_root, "第一本.epub")
    browse_counts.invalidate()

    first = client.get("/api/browse-counts", headers=auth_headers).json()
    again = client.get("/api/browse-counts", headers=auth_headers).json()
    assert (first["cached"], again["cached"]) == (False, True), "第二次必须命中缓存"

    # 数据真的变了（又多了一本书）—— TTL 内仍返回旧值，且如实标注 cached
    _book(default_root, "第二本.epub")
    stale = client.get("/api/browse-counts", headers=auth_headers).json()
    assert stale["cached"] is True and stale["books"] == 1, f"疑似没走缓存：{stale}"

    # 主动失效（扫描完想让数字立刻跟上时走这条）后立刻拿到新值
    browse_counts.invalidate()
    fresh = client.get("/api/browse-counts", headers=auth_headers).json()
    assert fresh["cached"] is False and fresh["books"] == 2


def test_节流按库分键(client, auth_headers, default_root, make_library, tmp_path):
    """切库要立刻拿到该库自己的数，所以缓存键必须是 library_id 而不是「一把全局键」。"""
    _book(default_root, "默认库的书.epub")
    other = tmp_path / "libs" / "comics"
    make_library("comic", "漫画库", "comic", other)
    _book(other, "漫画.cbz")

    browse_counts.invalidate()
    assert client.get("/api/browse-counts", headers=auth_headers).json()["cached"] is False
    scoped = client.get("/api/browse-counts?library_id=comic", headers=auth_headers).json()
    assert scoped["cached"] is False, "另一个库的键不该被上面那次调用预热"
    assert scoped["books"] == 1


def test_批注计数只算活跃(isolated):  # noqa: ARG001
    """模块层再钉一次：`annotation_counts()` 的 `deleted_at=0` 是这份计数的地基。"""
    bid = "lib$x"
    db.add_annotation(bid, 1, "留着的", "yellow", "")
    dropped = db.add_annotation(bid, 1, "丢掉的", "yellow", "")
    db.delete_annotation(bid, dropped)

    assert db.annotation_counts()[bid] == 1, "软删的批注被算进了侧栏计数"
