"""**写入口**的统一前置：这本书必须现在还在书目里（第 272 期）。

沿用第 271 期（OPDS / KOReader）那条结论 ——「结构性缺陷不会只长在一个出口」。
这轮把它套到 `/api/*` 自己的写入口上，一数就露：

| 写入口 | 修前 |
|---|---|
| `POST /api/books/{bid}/annotations` | **200 并照写** |
| `POST /api/books/{bid}/bookmarks` | **200 并照写** |
| `PUT  /api/books/{bid}/progress` | **200 并照写** —— ⚠️ **这一条是故意的**（见下） |
| `PUT  /api/books/{bid}/review` | **200 并照写** |
| `PUT  /api/books/{bid}/status` | **200 并照写** |
| `POST /api/books/{bid}/session` · `POST .../metadata` · `PUT .../online/pos` | 404 ✓ |

后果两条：
· **说得过去的场景**：开着的页面在书被删之后继续保存 —— 前端显示「已保存」，
  用户的批注 / 评分 / 进度写进一条**谁都看不见也清不掉**的行；
· **说不那么过去的**：任何脚本手滑一个 id 就能往库里灌垃圾行。

判据收进 `server._require_book()` **一处**；这里钉「五个入口一律 404 且不落行」，
以及「存在的书照旧能写」（闸门不许把正常路径挡掉）。
"""
import pytest

BAD = "根本没有这本书$deadbeef"


@pytest.fixture
def one_book(client, auth_headers, make_library, tmp_path):
    root = tmp_path / "L"
    root.mkdir(parents=True, exist_ok=True)
    make_library("L", "库", "comic", root)
    (root / "书.cbz").write_bytes(bytes.fromhex("504b0304") + bytes(64))
    client.post("/api/scan", headers=auth_headers)
    from novelforge.core import library
    library.invalidate()
    return library.books()[0]["id"]


def _writes(bid: str) -> list:
    """(method, path, body) —— **四个**用户界面的写入口。

    ⚠️ `progress` **不在此列**：它刻意允许写给「暂时还扫不到的书」（同步先到、扫描后到，
    见 `test_进度可以写给还没扫到的书`）。
    """
    return [
        ("post", f"/api/books/{bid}/annotations",
         {"chapter": 0, "quote": "原文", "color": "yellow", "note": "想法"}),
        ("post", f"/api/books/{bid}/bookmarks",
         {"chapter": 0, "anchor": {"start": 0, "end": 0}, "title": "标记"}),
        ("put", f"/api/books/{bid}/review", {"stars": 5, "review": "很好"}),
        ("put", f"/api/books/{bid}/status", {"status": "reading"}),
    ]


def test_五个写入口对不存在的书一律_404(client, auth_headers, isolated):
    from novelforge.core import db

    for method, path, body in _writes(BAD):
        r = getattr(client, method)(path, headers=auth_headers, json=body)
        assert r.status_code == 404, f"{method.upper()} {path} -> {r.status_code} {r.text[:80]}"

    # 一个字都没落进库
    assert not db.list_annotations(BAD)
    assert not db.list_bookmarks(BAD)
    assert int((db.get_review(BAD) or {}).get("stars") or 0) == 0
    # `get_status` 对没有行的情况回一个**默认行**（status=unread）⇒ 只能问「表里有没有这一行」
    assert BAD not in db.all_statuses(), "给不存在的书写进了一条阅读状态"


def test_存在的书照旧能写(client, auth_headers, one_book):
    """闸门不许把正常路径一起挡掉。"""
    for method, path, body in _writes(one_book):
        r = getattr(client, method)(path, headers=auth_headers, json=body)
        assert r.status_code == 200, f"{method.upper()} {path} -> {r.status_code} {r.text[:80]}"


def test_软删除之后也写不进去(client, auth_headers, one_book):
    """最现实的那条路径：书被删了、前端页面还开着，继续保存。

    `library.by_id` 只认**在册**的书 ⇒ 软删除之后同一批写入口也一律 404 ——
    这正是「删书之后不再产生孤儿行」的保证。
    """
    from novelforge.core import library, db

    assert client.delete("/api/books/" + one_book, headers=auth_headers).status_code == 200
    library.invalidate()
    assert library.by_id(one_book) is None, "软删除后 by_id 仍返回，判据不成立"

    for method, path, body in _writes(one_book):
        r = getattr(client, method)(path, headers=auth_headers, json=body)
        assert r.status_code == 404, f"{method.upper()} {path} -> {r.status_code}"
    pass


def test_进度可以写给还没扫到的书(client, auth_headers, isolated):
    """**例外**：`PUT /api/books/{bid}/progress` 刻意**不**校验书在不在。

    「同步先到、扫描后到」是真实场景（KOReader / 第三方客户端先把进度推上来，
    书还没进索引）—— 这条口径写在他处用例的 docstring 里
    （`test_progress_per_file.py::test_奇怪的file_rel不会把进度保存弄失败`），
    本期审计把它**显式钉在这里**，免得下次有人「顺手统一」把它也挡掉。
    """
    from novelforge.core import db

    r = client.put(f"/api/books/{BAD}/progress", headers=auth_headers,
                   json={"locator": 2, "percent": 20})
    assert r.status_code == 200, r.text
    assert (db.get_progress(BAD) or {}).get("locator") == 2
