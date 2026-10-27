"""实体管理扩到 6 类（第 159 期）：题材 / 出版社 / 语言 / 演播者的聚合与改名。

钉住四条：
- 聚合来自**生效值**（含 override），多值字段按标签分组；
- 改名只写服务端元数据，**多值字段只替换命中的那个标签**、其余原样；
- 合并同名标签时去重保序；
- 类型集合只有一处（`core.entities`），未知类型一律 400。
"""
from __future__ import annotations

import pathlib


def _setup(client, auth_headers, make_library, make_epub, tmp_path: pathlib.Path) -> list[str]:
    root = tmp_path / "ent-lib"
    make_library("ent-lib", "实体库", "ebook", root)
    make_epub(root, "甲.epub")
    make_epub(root, "乙.epub")
    assert client.post("/api/libraries/ent-lib/scan", headers=auth_headers).status_code == 200
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    ids = sorted(b["id"] for b in items if b["name"] in ("甲.epub", "乙.epub"))
    assert len(ids) == 2
    for bid in ids:
        r = client.post(f"/api/books/{bid}/metadata", headers=auth_headers, json={
            "fields": {"publisher": "旧社", "language": "zh",
                       "tags": ["科幻", "经典"], "narrators": ["张三"]},
        })
        assert r.status_code == 200, r.text
    return ids


def _meta(client, auth_headers, bid: str) -> dict:
    return client.get(f"/api/books/{bid}/metadata", headers=auth_headers).json()["fields"]


def test_六类聚合都来自生效值(client, auth_headers, make_library, make_epub, tmp_path):
    _setup(client, auth_headers, make_library, make_epub, tmp_path)
    for kind, name in (("tag", "科幻"), ("publisher", "旧社"),
                       ("language", "zh"), ("narrator", "张三")):
        body = client.get(f"/api/entities?type={kind}", headers=auth_headers).json()
        hit = next((i for i in body["items"] if i["name"] == name), None)
        assert hit and hit["count"] == 2, (kind, body)
    # 多值字段按标签分组：一本两个标签 ⇒ 两个分组
    tags = {i["name"] for i in client.get("/api/entities?type=tag", headers=auth_headers).json()["items"]}
    assert {"科幻", "经典"} <= tags


def test_多值改名只替换命中标签_合并去重(client, auth_headers, make_library, make_epub, tmp_path):
    ids = _setup(client, auth_headers, make_library, make_epub, tmp_path)

    pv = client.post("/api/entities/rename/preview", headers=auth_headers,
                     json={"type": "tag", "from": "科幻", "to": "科幻小说"}).json()
    assert pv["count"] == 2
    r = client.post("/api/entities/rename/apply", headers=auth_headers,
                    json={"type": "tag", "from": "科幻", "to": "科幻小说"})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 2
    for bid in ids:
        assert _meta(client, auth_headers, bid)["tags"] == ["科幻小说", "经典"] or \
               sorted(_meta(client, auth_headers, bid)["tags"]) == sorted(["科幻小说", "经典"])

    # 把「经典」并进「科幻小说」：命中的标签替换后与已存在的重名 ⇒ 去重、不重复两项
    client.post("/api/entities/rename/apply", headers=auth_headers,
                json={"type": "tag", "from": "经典", "to": "科幻小说"})
    for bid in ids:
        assert _meta(client, auth_headers, bid)["tags"] == ["科幻小说"]


def test_单值改名与未知类型(client, auth_headers, make_library, make_epub, tmp_path):
    ids = _setup(client, auth_headers, make_library, make_epub, tmp_path)
    r = client.post("/api/entities/rename/apply", headers=auth_headers,
                    json={"type": "publisher", "from": "旧社", "to": "新社"})
    assert r.status_code == 200 and r.json()["count"] == 2
    for bid in ids:
        assert _meta(client, auth_headers, bid)["publisher"] == "新社"

    assert client.get("/api/entities?type=not_a_type", headers=auth_headers).status_code == 400
    assert client.post("/api/entities/rename/preview", headers=auth_headers,
                       json={"type": "not_a_type", "from": "a", "to": "b"}).status_code == 400
