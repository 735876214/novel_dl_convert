"""卡片载荷契约（第 68 期）：列表**不发简介正文**，只发 `has_description`。

动机是体积 —— 600 本的库实测简介占 `GET /api/books` 的 **68%**：
`1,363,248 B → 417,189 B`（去掉正文，改发一个布尔）。

而列表界面（书架 / 系列 / 作者 / 收藏夹）**都不需要正文**：要正文的地方走详情接口
（快速预览浮层就是这么取简介的）。这条**必须**有契约，因为它失效时不会报任何错 ——
只有传输体积悄悄翻三倍，没有任何用例会红。

⚠️ 改 `server.py` 的 `_card()` 时同步改这里。
"""
import pathlib

from novelforge.core import epub_builder, library


def _epub(root, name: str, title: str) -> pathlib.Path:
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": "无名", "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    return path


def _find(items, title: str) -> dict:
    return next(b for b in items if b["title"] == title)


def _books(client, headers) -> list:
    r = client.get("/api/books", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_列表只给有没有简介_详情才给正文(client, auth_headers, default_root):
    _epub(default_root, "有简介.epub", "有简介")
    _epub(default_root, "无简介.epub", "无简介")
    library.invalidate()

    bid = _find(_books(client, auth_headers), "有简介")["id"]
    r = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                    json={"fields": {"description": "一段简介"}})
    assert r.status_code == 200, r.text

    items = _books(client, auth_headers)
    with_desc, without = _find(items, "有简介"), _find(items, "无简介")
    assert "description" not in with_desc, "列表不该再下发简介正文（它曾占列表体积 68%）"
    assert with_desc["has_description"] is True
    assert without["has_description"] is False

    # 详情接口仍带正文 —— 详情页与快速预览浮层都从这里取
    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    assert detail["description"] == "一段简介"


def test_其它列表出口口径一致(client, auth_headers, default_root):
    """`_card()` 是**所有**书目列表的出口（`/api/books`、系列、作者、演播者、收藏夹）。

    几处口径必须一致 —— 否则「列表说没简介、详情说有」这种自相矛盾会挑用户看得见的地方出现。
    """
    _epub(default_root, "地球往事 1.epub", "三体")
    library.invalidate()
    bid = _find(_books(client, auth_headers), "三体")["id"]
    r = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                    json={"fields": {"series": "地球往事", "description": "x"}})
    assert r.status_code == 200, r.text

    books = client.get("/api/series/地球往事", headers=auth_headers).json()["books"]
    assert books, "系列里应有那本书"
    for b in books:
        assert "description" not in b and "has_description" in b
