"""第 18 期：改名 / 合并**只改文件名 + 写服务端元数据**，绝不改写 EPUB 内容。

这条口径与「元数据只存服务端」是一套的：批量重命名的本质是改文件名（那必须真改），
但「实体改名 / 合并」顺带要变的**元数据**（作者名 / 系列名）不再回写 OPF，
而是写 ``meta_override`` —— 列表 / 详情 / 实体聚合照常按新名字走，原文件逐字节不变。

钉死四条：
1. 文件**被移动**（文件名真变），但**字节分毫未动**；
2. 覆盖落在**新 book_id** 上（book_id 由 basename 派生，落到旧 id 等于没改）；
3. ``old == new``（只改元数据、文件名不变）时**一个字节都不碰**；
4. 纯命名规则批改（不传 meta_field）行为不变：只改名、不写任何覆盖。
"""
import hashlib
import pathlib

import pytest

from novelforge.core import db, epub_builder, fileops, library


def _epub(root, name: str, *, title: str, author: str = "", series: str = "",
          index: str = "") -> pathlib.Path:
    """真 EPUB（系列 / 作者要能从 OPF 解析出来，假占位不行）。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": author or "原作者", "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    fields = {}
    if series:
        fields["series"] = series
    if index:
        fields["series_index"] = index
    if fields:
        assert fileops.patch_epub_meta(path, fields)
    return path


def _sha(path) -> str:
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


@pytest.fixture
def lib(isolated, default_root):  # noqa: ARG001 —— 依赖 isolated 切目录
    """默认库里放一本「银河帝国 #1」的真 EPUB。"""
    _epub(default_root, "基地.epub", title="基地", author="阿西莫夫",
          series="银河帝国", index="1")
    library.invalidate()
    return default_root


# ---------------------------------------------------------------------------
# 实体改名：文件名真改，内容不动
# ---------------------------------------------------------------------------

def test_实体改名只动文件名并写服务端覆盖(lib):
    src = pathlib.Path(lib) / "基地.epub"
    before_sha = _sha(src)
    new_name = "银河帝国 01.epub"

    res = fileops.apply_rename([{"old": "基地.epub", "new": new_name}],
                               meta_field="series", meta_value="基地系列")

    assert res["count"] == 1 and res["errors"] == []
    dst = pathlib.Path(lib) / new_name
    assert dst.is_file() and not src.exists()
    assert _sha(dst) == before_sha, "改名只动文件名，EPUB 字节不能被改写"

    # 生效值（列表读的就是它）必须已经是新系列名 —— 这是最终契约，先断它
    library.invalidate()
    b = next(x for x in library.books() if x["name"] == new_name)
    assert b["series"] == "基地系列"

    # 覆盖必须落在**扫描真正使用的那个 id** 上（库维度化：「库$哈希」）。
    # 落到旧 id / 纯哈希形态都不会报错，只会「改了没生效」——所以这里按扫描结果比对。
    assert res["overrides"] == [{"name": new_name, "book_id": b["id"],
                                "field": "series", "value": "基地系列"}]
    assert db.get_overrides(b["id"]) == {"series": "基地系列"}


def test_只改元数据时文件名不变且不碰文件字节(lib):
    """old == new（系列改名时文件名可能不变）→ 不移动、不改字节、只写覆盖。"""
    src = pathlib.Path(lib) / "基地.epub"
    before = _sha(src)

    res = fileops.apply_rename([{"old": "基地.epub", "new": "基地.epub"}],
                               meta_field="series", meta_value="银河帝国（新）")

    assert res["count"] == 1 and res["errors"] == []
    assert src.is_file() and _sha(src) == before
    library.invalidate()
    b = next(x for x in library.books() if x["name"] == "基地.epub")
    assert b["series"] == "银河帝国（新）"
    assert db.get_overrides(b["id"]) == {"series": "银河帝国（新）"}


def test_纯命名规则批改不写任何覆盖(lib):
    """批量重命名（pattern 路径）不传 meta_field → 只改名，不产生元数据覆盖。"""
    before_sha = _sha(pathlib.Path(lib) / "基地.epub")
    res = fileops.apply_rename([{"old": "基地.epub", "new": "阿西莫夫 - 基地.epub"}])
    assert res["count"] == 1 and res["overrides"] == []
    assert _sha(pathlib.Path(lib) / "阿西莫夫 - 基地.epub") == before_sha
    assert db.all_overrides() == {}


def test_跳过冲突条目不写覆盖(lib):
    res = fileops.apply_rename(
        [{"old": "基地.epub", "new": "撞名.epub", "conflict": True}],
        meta_field="series", meta_value="不该写入")
    assert res["count"] == 0 and res["errors"]
    assert db.all_overrides() == {}


# ---------------------------------------------------------------------------
# 接口层：两个端点都走同一套 core
# ---------------------------------------------------------------------------

def test_接口_实体改名端点不写文件(client, auth_headers, lib):  # noqa: ARG001
    src = pathlib.Path(lib) / "基地.epub"
    before = _sha(src)
    r = client.post("/api/entities/rename/apply", headers=auth_headers, json={
        "type": "author", "to": "艾萨克·阿西莫夫",
        "items": [{"old": "基地.epub", "new": "基地（精校）.epub"}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 1
    assert _sha(pathlib.Path(lib) / "基地（精校）.epub") == before
    # 生效值要真的换了作者（而不是只写了一条没人读的记录）
    b = next(x for x in client.get("/api/books", headers=auth_headers).json()["items"]
             if x["name"] == "基地（精校）.epub")
    assert b["author"] == "艾萨克·阿西莫夫"


def test_接口_重排册号端点不写文件(client, auth_headers, lib):  # noqa: ARG001
    before = _sha(pathlib.Path(lib) / "基地.epub")
    prev = client.get("/api/series/银河帝国/renumber/preview", headers=auth_headers)
    assert prev.status_code == 200, prev.text
    items = [{"name": i["name"], "new_index": i["new_index"]}
             for i in prev.json()["items"]]
    r = client.post("/api/series/银河帝国/renumber/apply", headers=auth_headers,
                    json={"items": items})
    assert r.status_code == 200, r.text
    assert r.json()["mismatched"] == []
    assert _sha(pathlib.Path(lib) / "基地.epub") == before
    # 序号进了服务端生效值：系列详情页读到的就是它
    detail = client.get("/api/series/银河帝国", headers=auth_headers)
    assert detail.status_code == 200, detail.text
    book = detail.json()["books"][0]
    assert str(book.get("series_index") or "") == items[0]["new_index"]
