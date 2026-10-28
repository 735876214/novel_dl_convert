"""按正则从文件名提取元数据（第 165 期）。

钉住五条：

- 命名分组 = 元数据字段；预览**不写库**，应用才写（与单书编辑同一条覆盖路径）；
- 只改**匹配上且值有变化**的字段；空分组不写（不把「没提取到」当清空）；
- 未知字段名 / 坏正则 / 坏范围一律 400，消息直接可读；
- 多值字段（题材）按既有解析规则落成列表；
- 应用**重新算**，`book_ids` 只作收窄（预览过期也不会改错书）。
"""
from __future__ import annotations

import pathlib

RULE = r"^\[(?P<author>[^\]]+)\]\s*(?P<title>.+?)\s*\((?P<date>\d{4})\)$"


def _setup(client, auth_headers, make_library, make_epub, tmp_path: pathlib.Path) -> tuple:
    root = tmp_path / "pm-lib"
    make_library("pm-lib", "正则库", "ebook", root)
    make_epub(root, "[张三] 星际旅行 (2021).epub")
    make_epub(root, "无关的书.epub")
    assert client.post("/api/libraries/pm-lib/scan", headers=auth_headers).status_code == 200
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    hit = next(b["id"] for b in items if b["name"].startswith("[张三]"))
    other = next(b["id"] for b in items if b["name"] == "无关的书.epub")
    return hit, other


def _meta(client, auth_headers, bid: str) -> dict:
    return client.get(f"/api/books/{bid}/metadata", headers=auth_headers).json()["fields"]


def test_预览不写库_应用才写(client, auth_headers, make_library, make_epub, tmp_path):
    hit, _other = _setup(client, auth_headers, make_library, make_epub, tmp_path)
    before = _meta(client, auth_headers, hit)

    r = client.post("/api/books/path-import/preview", headers=auth_headers,
                    json={"pattern": RULE, "target": "stem", "library_id": "pm-lib"})
    assert r.status_code == 200, r.text
    pv = r.json()
    assert pv["matched"] == 1 and pv["unmatched"] == 1
    assert set(pv["fields"]) == {"author", "title", "date"}
    item = pv["items"][0]
    assert item["values"] == {"author": "张三", "title": "星际旅行", "date": "2021"}
    changed = {c["field"]: c for c in item["changes"]}
    assert changed["author"]["from"] == "未知" and changed["author"]["to"] == "张三"
    # 预览不写库
    assert _meta(client, auth_headers, hit) == before

    a = client.post("/api/books/path-import/apply", headers=auth_headers,
                    json={"pattern": RULE, "target": "stem", "library_id": "pm-lib"})
    assert a.status_code == 200, a.text
    assert a.json()["count"] == 1
    after = _meta(client, auth_headers, hit)
    assert after["author"] == "张三"
    assert after["title"] == "星际旅行"
    assert after["date"] == "2021"

    # 再应用一次：已经是这些值 ⇒ 没有变化、不重复写
    a2 = client.post("/api/books/path-import/apply", headers=auth_headers,
                     json={"pattern": RULE, "target": "stem", "library_id": "pm-lib"})
    assert a2.status_code == 200 and a2.json()["count"] == 0


def test_多值字段_收窄_与坏入参(client, auth_headers, make_library, make_epub, tmp_path):
    hit, other = _setup(client, auth_headers, make_library, make_epub, tmp_path)

    # 多值字段：一个分组里顿号分隔 ⇒ 落成列表（与单书编辑同一份解析）
    r = client.post("/api/books/path-import/apply", headers=auth_headers,
                    json={"pattern": r"^\[(?P<tags>[^\]]+)\]", "target": "stem",
                          "book_ids": [hit, other]})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    assert _meta(client, auth_headers, hit)["tags"] == ["张三"]
    # 另一本不匹配 ⇒ 没被写
    assert _meta(client, auth_headers, other)["tags"] == []

    # book_ids 收窄：给一个不相关的 id ⇒ 一本都不写
    r3 = client.post("/api/books/path-import/apply", headers=auth_headers,
                     json={"pattern": RULE, "target": "stem", "book_ids": ["nope"]})
    assert r3.status_code == 200 and r3.json()["count"] == 0

    bad = [
        {"pattern": "(?P<no_such_field>.+)", "target": "stem"},
        {"pattern": "([", "target": "stem"},
        {"pattern": "", "target": "stem"},
        {"pattern": "(?P<author>.+)", "target": "nope"},
        {"pattern": "(?P<author>.+)", "target": "stem", "library_id": "no-lib"},
    ]
    for payload in bad:
        assert client.post("/api/books/path-import/preview", headers=auth_headers,
                           json=payload).status_code in (400, 404), payload
    # 没有任何命名分组 ⇒ 400（否则「预览了但什么都没提取」很难查）
    assert client.post("/api/books/path-import/preview", headers=auth_headers,
                       json={"pattern": "^.+$", "target": "stem"}).status_code == 400
