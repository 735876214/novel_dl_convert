"""第 18 / 28 期：实体改名 / 合并**只写服务端元数据**，源文件逐字节、逐文件名原样。

第 18 期定的口径是「只改文件名 + 写服务端元数据，绝不改写 EPUB 内容」；
第 28 期（批量重命名并入刮削）又收了一步：**连文件名也不改了** —— 源文件名在
任何入口下都不再被改动，改名只剩「按命名规则重出版**副本**」一条落盘路径
（见 tests/test_naming_publish.py）。实体改名与合并因此退化成一次纯元数据写入。

钉死四条：
1. 改名 / 合并前后源文件名与字节**分毫未动**（作者名没写在文件名里时，也不再按
   「《书名》作者：新名.epub」重建文件名 —— 那是本期删掉的行为）；
2. ``book_id`` 不变（它由 basename 派生）⇒ 进度 / 批注 / 评分无需搬迁、也不会断链；
3. 生效值真的换了（列表 / 详情 / 实体聚合按新名字走）：覆盖落在**扫描真正使用的
   那个 id** 上 —— 落到别的形态不会报错，只会「改了没生效」；
4. 要改哪些书由**服务端**按 ``from`` 自己算：接口不收 items，客户端指定不动任何文件。
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


def _book(name: str) -> dict:
    """按文件名取书目（读前先失效缓存 —— 覆盖刚写完时缓存里还是旧值）。"""
    library.invalidate()
    return next(x for x in library.books() if x["name"] == name)


@pytest.fixture
def lib(isolated, default_root):  # noqa: ARG001 —— 依赖 isolated 切目录
    """默认库里放一本「银河帝国 #1」的真 EPUB。"""
    _epub(default_root, "基地.epub", title="基地", author="阿西莫夫",
          series="银河帝国", index="1")
    library.invalidate()
    return default_root


# ---------------------------------------------------------------------------
# 实体改名：只写元数据，文件名与字节都不动
# ---------------------------------------------------------------------------

def test_系列改名只写服务端覆盖且不碰源文件(lib):
    src = pathlib.Path(lib) / "基地.epub"
    before_sha, before_id = _sha(src), _book("基地.epub")["id"]

    plan = fileops.plan_entity_rename("series", "银河帝国", "基地系列")
    assert plan["count"] == 1
    it = plan["items"][0]
    # 预览条目一律「同名」+ meta_only：改的不是文件名，而是元数据
    assert it["meta_only"] is True
    assert it["old"] == it["new"] == "基地.epub"
    assert it["conflict"] is False

    res = fileops.apply_entity_rename("series", "银河帝国", "基地系列")
    assert res["count"] == 1 and res["errors"] == []
    assert src.is_file() and _sha(src) == before_sha, "改名不再碰源文件"

    b = _book("基地.epub")
    assert b["id"] == before_id, "book_id 由 basename 派生：文件名不变则 id 不变"
    assert b["series"] == "基地系列"
    assert db.get_overrides(b["id"]) == {"series": "基地系列"}


def test_作者改名不再重建文件名(lib):
    """老行为：作者名没出现在文件名里时按约定重建成「《书名》作者：新名.epub」——已删。"""
    src = pathlib.Path(lib) / "基地.epub"
    before = _sha(src)

    res = fileops.apply_entity_rename("author", "阿西莫夫", "艾萨克·阿西莫夫")

    assert res["count"] == 1 and res["errors"] == []
    assert src.is_file() and _sha(src) == before
    assert not any(p.name != "基地.epub" for p in pathlib.Path(lib).iterdir())
    assert _book("基地.epub")["author"] == "艾萨克·阿西莫夫"


def test_改名不断关联数据(lib):
    """改名的书 `book_id` 不变 ⇒ 进度 / 批注原地不动（老 apply_rename 的病根）。"""
    bid = _book("基地.epub")["id"]
    db.set_progress(bid, 1234, 42.5)
    db.add_annotation(bid, 1, "引用一句", "yellow", "随手记")

    res = fileops.apply_entity_rename("series", "银河帝国", "基地系列")

    assert res["count"] == 1
    assert _book("基地.epub")["id"] == bid
    assert db.get_progress(bid)["percent"] == 42.5
    assert db.annotation_counts().get(bid) == 1


def test_只改该字段取值为原名的那本(lib):
    """要改哪些书由服务端按字段生效值筛：系列不同的书一根汗毛都不动。"""
    _epub(lib, "神们自己.epub", title="神们自己", author="阿西莫夫", series="其它系列")
    library.invalidate()

    res = fileops.apply_entity_rename("series", "银河帝国", "基地系列")

    assert res["count"] == 1 and [x["name"] for x in res["items"]] == ["基地.epub"]
    assert db.get_overrides(_book("神们自己.epub")["id"]) == {}
    assert _book("神们自己.epub")["series"] == "其它系列"


def test_没有书用这个名字时是空结果(lib):
    """空结果不是错误：前端据此提示「没有书的该字段等于这个名字」。"""
    res = fileops.apply_entity_rename("series", "查无此系列", "新名字")
    assert res["count"] == 0 and res["errors"] == []
    assert db.all_overrides() == {}


def test_空名称或纯非法字符的名称被拒绝(lib):
    """名称如今是**元数据**、不再当文件名用，所以 ``a/b`` 这类值是被允许的
    （真出版副本时由 ``fileops.sanitize_stem`` 兜底清掉）；被拒的只有「清洗后为空」。"""
    for frm, to in (("", "新"), ("旧", ""), ("银河帝国", "///")):
        with pytest.raises(ValueError):
            fileops.plan_entity_rename("series", frm, to)
    assert fileops.plan_entity_rename("series", "银河帝国", "a/b")["to"] == "a/b"


# ---------------------------------------------------------------------------
# 合并：与改名同构（源实体消失，文件不动）
# ---------------------------------------------------------------------------

def test_合并后源实体消失且不动文件(lib):
    src = pathlib.Path(lib) / "基地.epub"
    before = _sha(src)

    plan = fileops.plan_merge("series", "银河帝国", "基地系列")
    assert plan["count"] == 1 and plan["items"][0]["meta_only"] is True

    res = fileops.apply_entity_rename("series", "银河帝国", "基地系列")
    assert res["count"] == 1 and res["errors"] == []
    assert _sha(src) == before

    names = [i["name"] for i in library.entities("series")["items"]]
    assert "基地系列" in names and "银河帝国" not in names


# ---------------------------------------------------------------------------
# 接口层：契约只认 {type, from, to}，收不到「去动哪个文件」
# ---------------------------------------------------------------------------

def test_接口_实体改名端点只写元数据(client, auth_headers, lib):  # noqa: ARG001
    src = pathlib.Path(lib) / "基地.epub"
    before = _sha(src)

    r = client.post("/api/entities/rename/apply", headers=auth_headers, json={
        "type": "series", "from": "银河帝国", "to": "基地系列",
        # 老契约的 items 就算被塞进来也无效：改哪些书由服务端自己算
        "items": [{"old": "基地.epub", "new": "基地（精校）.epub"}],
    })
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    assert _sha(src) == before
    assert not (pathlib.Path(lib) / "基地（精校）.epub").exists()

    b = next(x for x in client.get("/api/books", headers=auth_headers).json()["items"]
             if x["name"] == "基地.epub")
    assert b["series"] == "基地系列"


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
