"""写批注后侧栏「浏览」三计数必须立刻失效（第 287 期）。

`browse_counts` 的缓存键是 `library_id`（60s TTL），而 `library.invalidate()` 的注释
声称「新增 / 删书 / **写批注**」之后都已失效 —— 实际批注端点**一次都没调它**。实测：

```
GET /api/browse-counts            → annotations=0, cached=false
POST /api/books/{bid}/annotations → 200
GET /api/browse-counts            → annotations=0, cached=true    ← 页面列出 1 条
```

于是侧栏在最多 60s 内说「批注 0」、点进去却有 1 条 —— 正是这个模块文档里最忌讳的
「侧栏显示 3、页面列出 12」。修法：批注写入口（新增 / 删除 / 恢复 / 彻底删除 /
KOReader 导入）调 `library.invalidate_counts()`；**不走** `library.invalidate()`
（批注不改书目，不该顺带把目录标脏、让下一个请求跑一次增量扫描）。
"""
import pathlib

from novelforge.core import epub_builder, library


def _book(client, auth_headers, make_library, tmp_path) -> str:
    root = tmp_path / "L"
    p = root / "a.epub"
    p.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": "书A", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>x</p>"}], str(p))
    make_library("L", "库", "ebook", root)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    return client.get("/api/books", headers=auth_headers).json()["items"][0]["id"]


def test_写批注与删批注都立刻反映到侧栏计数(client, auth_headers, make_library, tmp_path):
    bid = _book(client, auth_headers, make_library, tmp_path)

    assert client.get("/api/browse-counts", headers=auth_headers).json()["annotations"] == 0

    r = client.post(f"/api/books/{bid}/annotations", headers=auth_headers,
                    json={"quote": "选中一句", "chapter": 1})
    assert r.status_code == 200, r.text
    aid = r.json()["id"]

    after = client.get("/api/browse-counts", headers=auth_headers).json()
    assert after["cached"] is False, "写批注后计数还在吃 60s 缓存"
    assert after["annotations"] == 1, after

    assert client.delete(f"/api/books/{bid}/annotations/{aid}",
                         headers=auth_headers).status_code == 200
    again = client.get("/api/browse-counts", headers=auth_headers).json()
    assert again["cached"] is False
    assert again["annotations"] == 0, "软删除后活跃批注数应立刻掉回去"
