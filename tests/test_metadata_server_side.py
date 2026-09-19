"""第 17 期 T3：元数据只存服务端、不重写 EPUB；列表 / 封面全以服务器为准。

钉死三条设计约束（这是「数据存服务器」的落地口径）：

1. 任何「写回元数据」落点（手动编辑 / revert / 在线 apply）**都不改 EPUB 文件字节**，
   只在 DB（``meta_online`` / ``meta_override`` / ``meta_cover``）留痕；
2. ``library.books()`` 批量合并 ``override > online > opf``，并把服务端封面纳入
   ``has_cover``（与文件自带封面取并集）—— 列表 / 卡片 / 搜索 / OPDS 一致；
3. 每库 ``metadata_fetch.auto_on_import`` 可独立于全局开关（能力矩阵联动）。

全部离线：封面下载与在线抓取一律 mock，禁外呼。真实 OPF 用 ``epub_builder`` 生成。
"""
import pathlib

import pytest

from novelforge import config
from novelforge.core import db, epub_builder, fileops, lib_settings, library, metafetch


def _real_epub(root, name: str, title: str = "书") -> pathlib.Path:
    """生成一个**真实可解析**的 EPUB（改元数据 / 解析封面都要读真 OPF）。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": "作者", "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    return path


def _books(client, headers) -> list:
    r = client.get("/api/books", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _find(client, headers, title: str) -> dict:
    hit = next((b for b in _books(client, headers) if b["title"] == title), None)
    assert hit is not None, f"找不到《{title}》：{[b['title'] for b in _books(client, headers)]}"
    return hit


# ---------------------------------------------------------------------------
# DB 层：批量生效元数据（override > online，date→year，tags→列表）
# ---------------------------------------------------------------------------

def test_effective_meta优先级与字段映射(isolated):  # noqa: ARG001
    db.set_online("bx", {"title": ("在线标题", "ol"), "date": ("2001", "ol"),
                         "tags": ("['科幻', '悬疑']", "ol")})
    db.set_override("bx", "title", "覆盖标题")

    m = db.get_effective_meta(["bx"])["bx"]
    assert m["title"] == "覆盖标题"          # override > online
    assert m["year"] == "2001"               # date 映射成书对象键 year
    assert m["tags"] == ["科幻", "悬疑"]      # tags 解析成列表


def test_effective_meta无值不返回键(isolated):  # noqa: ARG001
    assert db.get_effective_meta(["nope"]) == {}
    db.set_online("bx", {"title": ("", "ol")})       # 空值跳过
    assert db.get_effective_meta(["bx"]) == {}


def test_cover_ids批量返回命中集合(isolated):  # noqa: ARG001
    db.set_cover("c1", b"\x89PNG" + b"0" * 2000, "image/png")
    assert db.cover_ids(["c1", "c2"]) == {"c1"}
    assert db.get_cover("c1")[1] == "image/png"
    assert db.get_cover("c2") is None


# ---------------------------------------------------------------------------
# 列表合并：books() 以服务器为准
# ---------------------------------------------------------------------------

def test_列表合并服务端元数据与封面(isolated, default_root):  # noqa: ARG001
    _real_epub(default_root, "合并.epub", title="合并")
    library.invalidate()
    b = next(x for x in library.books() if x["title"] == "合并")
    assert b["has_cover"] is False

    db.set_online(b["id"], {"author": ("在线作者", "ol")})
    db.set_cover(b["id"], b"\x89PNG" + b"0" * 2000, "image/png")
    library.invalidate()

    b2 = next(x for x in library.books() if x["id"] == b["id"])
    assert b2["author"] == "在线作者"
    assert b2["has_cover"] is True
    assert "no-cover" not in b2["issues"]            # 服务端封面撤掉文件判定的缺失


# ---------------------------------------------------------------------------
# 手动链路：编辑 / 恢复都不写文件
# ---------------------------------------------------------------------------

def test_手动编辑只存服务端不改文件(client, auth_headers, default_root):
    p = _real_epub(default_root, "服务侧.epub", title="服务侧")
    library.invalidate()
    b = _find(client, auth_headers, "服务侧")
    before = p.read_bytes()

    r = client.post(f"/api/books/{b['id']}/metadata", headers=auth_headers,
                    json={"fields": {"publisher": "服务端社", "title": "服务端标题"}})
    assert r.status_code == 200, r.text
    assert r.json()["written"] == []                 # 不再写文件
    assert p.read_bytes() == before                  # EPUB 字节不变

    # 列表 / 卡片反映服务端值
    b2 = _find(client, auth_headers, "服务端标题")
    assert b2["id"] == b["id"]
    assert b2["publisher"] == "服务端社"
    # 详情生效值一致
    fields = client.get(f"/api/books/{b['id']}/metadata", headers=auth_headers).json()["fields"]
    assert fields["publisher"] == "服务端社" and fields["title"] == "服务端标题"


def test_恢复到在线值只撤覆盖不改文件(client, auth_headers, default_root):
    p = _real_epub(default_root, "回退.epub", title="回退")
    library.invalidate()
    b = _find(client, auth_headers, "回退")
    db.set_online(b["id"], {"publisher": ("在线社", "openlibrary")})
    client.post(f"/api/books/{b['id']}/metadata", headers=auth_headers,
                json={"fields": {"publisher": "用户社"}})
    before = p.read_bytes()

    r = client.post(f"/api/books/{b['id']}/metadata/revert", headers=auth_headers,
                    json={"fields": ["publisher"]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["recovered"] == ["publisher"]
    assert d["meta"]["publisher"]["overridden"] is False
    assert d["meta"]["publisher"]["online"] == "在线社"
    assert p.read_bytes() == before                  # 不写文件


def test_封面接口服务端优先并回退EPUB(client, auth_headers, default_root):
    _real_epub(default_root, "封面书.epub", title="封面书")
    library.invalidate()
    b = _find(client, auth_headers, "封面书")

    # 原文件没封面 → 404
    assert client.get(f"/api/books/{b['id']}/cover", headers=auth_headers).status_code == 404
    # 写入服务端封面 → 直接下发
    db.set_cover(b["id"], b"\x89PNG" + b"0" * 2000, "image/png")
    r = client.get(f"/api/books/{b['id']}/cover", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("image/png")


# ---------------------------------------------------------------------------
# 自动链路：apply 只写 DB（封面下载 mock，禁外呼）
# ---------------------------------------------------------------------------

def test_在线apply只写服务端DB(default_root, monkeypatch):  # noqa: ARG001
    p = _real_epub(default_root, "抓取.epub", title="抓取")
    library.invalidate()
    b = next(x for x in library.books() if x["title"] == "抓取")
    before = p.read_bytes()

    monkeypatch.setattr(metafetch, "_download_cover",
                        lambda url: (b"\x89PNG" + b"0" * 2000, "image/png"))
    res = metafetch.apply([{
        "name": b["name"], "library_id": b["library_id"], "book_id": b["id"],
        "fields": {"title": "在线标题"}, "cover": {"url": "http://example.invalid/c.png"},
    }])

    assert res["count"] == 1 and res["failed"] == []
    assert p.read_bytes() == before                  # 不改文件
    assert db.get_online(b["id"])["title"]["value"] == "在线标题"
    assert db.get_cover(b["id"]) is not None


# ---------------------------------------------------------------------------
# 每库 auto_on_import 开关（原 T3 小目标）
# ---------------------------------------------------------------------------

def test_每库auto_on_import独立于全局(isolated, make_library, tmp_path):  # noqa: ARG001
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    assert lib_settings.config_for(lid)["metadata_fetch"]["auto_on_import"] is False

    lib_settings.set_overrides(lid, {"metadata_fetch.auto_on_import": True})
    assert lib_settings.config_for(lid)["metadata_fetch"]["auto_on_import"] is True
    assert config.load_config()["metadata_fetch"]["auto_on_import"] is False   # 全局不动


def test_漫画库也能覆盖auto_on_import(isolated, make_library, tmp_path):  # noqa: ARG001
    """第 21 期：抓取不再按格式分流 → 漫画库也暴露并接受该覆盖项（此前断言「不暴露」）。"""
    lid = "comic-a"
    make_library(lid, "漫画库", "comic", tmp_path / "libraries" / lid)

    keys = [s["key"] for s in lib_settings.schema("comic")]
    assert "metadata_fetch.auto_on_import" in keys
    lib_settings.set_overrides(lid, {"metadata_fetch.auto_on_import": True})
    assert lib_settings.config_for(lid)["metadata_fetch"]["auto_on_import"] is True


# ---------------------------------------------------------------------------
# 第 22 期：编辑放开到所有格式 + 「显式清空」（哨兵）
# ---------------------------------------------------------------------------

def test_清空哨兵字段与可编辑字段同集合(isolated):  # noqa: ARG001
    """`db._CLEARABLE` 必须与 `fileops.METADATA_FIELDS` 同集合。

    db 不能 import fileops（后者 import 前者，会成环），那份字段清单是手抄的 ——
    这条断言就是防「加了字段却忘了能清空」。
    """
    assert set(db._CLEARABLE) == set(fileops.METADATA_FIELDS)
    assert db.clearable("publisher") is True
    assert db.clearable("不存在的字段") is False


def test_清空题材在批量热路径返回空列表(isolated):  # noqa: ARG001
    """题材清空后要进列表形态（``[]``），否则列表 / 卡片会拿到字符串。"""
    db.set_override("bx", "tags", db.META_CLEAR)
    assert db.get_effective_meta(["bx"])["bx"]["tags"] == []
    # 哨兵本身不该被当成值漏出去
    assert db.META_CLEAR not in str(db.get_effective_meta(["bx"]))


def test_非EPUB编辑并显式清空盖住在线值(client, auth_headers, default_root, make_book):
    """非 EPUB 也能编辑；「清空」（提交 ``null``）是**显式无值**，不会被在线值填回来。"""
    make_book(default_root, "漫画.cbz")
    library.invalidate()
    bid = next(b["id"] for b in library.books() if b["format"] == "CBZ")
    db.set_online(bid, {"publisher": ("在线社", "openlibrary")})
    library.invalidate()

    meta = client.get(f"/api/books/{bid}/metadata", headers=auth_headers).json()
    assert meta["editable"] is True
    assert meta["fields"]["publisher"] == "在线社"          # 在线值先露出来

    r = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                    json={"fields": {"publisher": "用户社"}})
    assert r.status_code == 200, r.text
    assert r.json()["fields"]["publisher"] == "用户社"

    # 清空 = 显式无值：详情为空、仍算「用户改过」、库里落的是哨兵
    r = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                    json={"fields": {"publisher": None}})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["changed"] == ["publisher"]
    assert d["fields"]["publisher"] == ""
    assert d["meta"]["publisher"]["overridden"] is True
    assert db.get_overrides(bid)["publisher"] == db.META_CLEAR

    # 批量热路径（列表 / 卡片 / OPDS / Komga 都走它）同样为空，不回落在线值
    library.invalidate()
    assert next(b for b in library.books() if b["id"] == bid)["publisher"] == ""

    # 抓取保护：哨兵同样在 overrides 里 → metafetch 不会再把它填回来
    assert db.all_overrides()[bid]["publisher"] == db.META_CLEAR

    # 撤销覆盖 → 回到在线值（这是「恢复」，不是「清空」）
    r = client.post(f"/api/books/{bid}/metadata/revert", headers=auth_headers,
                    json={"fields": ["publisher"]})
    assert r.status_code == 200, r.text
    assert r.json()["fields"]["publisher"] == "在线社"


def test_EPUB空串仍是撤销覆盖(client, auth_headers, default_root):
    """EPUB 的老行为不变：提交**空串** = 撤销覆盖（回落 OPF / 在线值），不写哨兵。"""
    _real_epub(default_root, "空串.epub", title="空串书")
    library.invalidate()
    b = _find(client, auth_headers, "空串书")

    client.post(f"/api/books/{b['id']}/metadata", headers=auth_headers,
                json={"fields": {"publisher": "用户社"}})
    assert db.get_overrides(b["id"])["publisher"] == "用户社"

    r = client.post(f"/api/books/{b['id']}/metadata", headers=auth_headers,
                    json={"fields": {"publisher": ""}})
    assert r.status_code == 200, r.text
    assert "publisher" not in db.get_overrides(b["id"])     # 覆盖被撤掉
    assert db.get_overrides(b["id"]).get("publisher") != db.META_CLEAR
