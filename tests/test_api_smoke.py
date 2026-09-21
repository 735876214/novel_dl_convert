"""接口冒烟：FastAPI TestClient（真实路由 + 真实中间件 + 真实 SQLite）。

只盯三类最该被护栏看住的行为，不追求把 145 条路由都点一遍：

1. **鉴权**：`/api/*` 无令牌必须 401；`/health` 与登录端点放行；
2. **库根白名单**：库根只允许落在「来源目录 / 导出目录 / 数据目录」之内 ——
   库根就是 `safe_path` 的边界，放任任意路径等于放任改名 / 回收作用到系统目录；
3. **破坏性操作的护栏**：默认库不可删、非空库需显式 `force`、删除**只移除登记不删文件**。

⚠️ 本文件**刻意不碰会外呼的接口**（`…/metadata/online`、作者抓取）：测试必须离线可跑。
   元数据编辑 / 恢复链路之所以离线安全，是因为测试环境用的是空配置目录，
   `metadata_fetch.enabled` 为默认 `False` → `metafetch.online_candidate` 直接返回 None
   而不发网络请求（见 `test_测试环境元数据抓取默认关闭`）。
"""
import json
import pathlib

import pytest

from novelforge import config
from novelforge.core import db, epub_builder, library


def _build_real_epub(root, name: str, title: str = "三体", author: str = "刘慈欣") -> pathlib.Path:
    """造一个**真 EPUB**。

    元数据写回与系列解析都要读真实 OPF，用 `b"EPUB"` 占位会让接口 500 ——
    所以这里用项目自己的 `epub_builder` 生成（顺带也覆盖了它的可用性）。
    """
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": author, "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    return path


def _books(client, headers) -> list:
    r = client.get("/api/books", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _find_book(client, headers, title: str) -> dict:
    hit = next((b for b in _books(client, headers) if b["title"] == title), None)
    assert hit is not None, f"书目里找不到《{title}》：{[b['title'] for b in _books(client, headers)]}"
    return hit


def _create_library(client, headers, name: str, ltype: str, root, **extra) -> dict:
    payload = {"name": name, "type": ltype, "mode": "inplace", "root_path": str(root)}
    payload.update(extra)
    r = client.post("/api/libraries", headers=headers, json=payload)
    assert r.status_code == 200, r.text
    return r.json()["library"]


# ---------------------------------------------------------------------------
# 鉴权
# ---------------------------------------------------------------------------

def test_健康检查无需鉴权(client):
    assert client.get("/health").status_code == 200


def test_未带令牌的接口返回401(client):
    assert client.get("/api/books").status_code == 401
    assert client.get("/api/libraries").status_code == 401


def test_错误口令被拒(client):
    r = client.post("/api/auth/login", json={"user": "admin", "pin": "wrong-pin"})
    assert r.status_code == 401
    assert "账号或密码错误" in r.json()["detail"]


def test_登录后可访问(auth_headers, client):
    assert client.get("/api/books", headers=auth_headers).status_code == 200


def test_测试环境元数据抓取默认关闭(isolated):  # noqa: ARG001
    """本套测试的**离线前提**：抓取关着，`online_candidate` 不会发网络请求。"""
    assert config.load_config()["metadata_fetch"]["enabled"] is False


def test_求书接口已随决策移除(client, auth_headers):
    """C1（求书）已决策不做（2026-09-18）：接口从「返回空态」变为**不存在**。

    钉住这条是为了防止「删了页面、接口又被人加回来」的半删状态。
    """
    assert client.get("/api/requests/config", headers=auth_headers).status_code == 404


# ---------------------------------------------------------------------------
# 书库：列表 / 新建 / 修改 / 扫描 / 来源目录
# ---------------------------------------------------------------------------

def test_书库列表不再有默认库(client, auth_headers, test_lib_id):
    """第 37 期：产品不再播种任何书库，列表里**只有用户建的**，「默认库」概念整个下线。

    `is_default` 字段被删掉了（不再有「不可删除的那一个」），所以这里直接断言它不存在 ——
    否则前端会顺手读一个恒为 undefined 的字段，把「谁都不能删」的旧假设留在代码里。
    """
    data = client.get("/api/libraries", headers=auth_headers).json()
    items = data["items"]
    assert [i["id"] for i in items] == [test_lib_id], "只有夹具建的那一条，没有自动播种的库"
    assert all("is_default" not in i for i in items)
    assert items[0]["type"] == "mixed" and items[0]["mode"] == "inplace"
    # 新建向导要靠它给默认路径
    assert data["source_dir"] == str(config.LIBRARY_SOURCE_DIR)
    assert {t["value"] for t in data["types"]} == {"ebook", "comic", "audiobook", "mixed"}


def test_一个书库都没有时列表真的为空(client, auth_headers, test_lib_id):
    """全新部署的真实形态：0 个书库。以前这里会自动合成一条「默认书库」，永远不为空。"""
    r = client.delete(f"/api/libraries/{test_lib_id}", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert client.get("/api/libraries", headers=auth_headers).json()["items"] == []


def test_新建书库并改属性与扫描(client, auth_headers):
    # 库根必须落在白名单内（来源目录 / 导出目录 / 数据目录），这里用来源目录下的子目录
    root = pathlib.Path(config.LIBRARY_SOURCE_DIR) / "ebooks"
    lib = _create_library(client, auth_headers, "电子书库", "ebook", root,
                          source_subdir="ebooks", rules="科幻, 太空")
    # 中文名派生不出 ASCII slug → 回退 `lib-<hash>`（URL 安全、单段，避免路径里出现中文）
    assert lib["id"].startswith("lib-")
    assert lib["type_label"] == "电子书库"
    assert lib["mode_label"] == "就地引用"
    assert lib["exists"] is True and lib["writable"] is True
    assert json.loads(lib["rules"])["keywords"] == ["科幻", "太空"]

    patched = client.patch(f"/api/libraries/{lib['id']}", headers=auth_headers,
                           json={"name": "改名后的库"}).json()
    assert patched["library"]["name"] == "改名后的库"

    scanned = client.post(f"/api/libraries/{lib['id']}/scan", headers=auth_headers).json()
    assert scanned["ok"] is True and scanned["count"] == 0


def test_来源目录列举(client, auth_headers):
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    (src / "comics").mkdir(parents=True, exist_ok=True)
    (src / "comics" / "某漫画.cbz").write_bytes(b"CBZ")

    data = client.get("/api/libraries/source-dirs", headers=auth_headers).json()
    assert data["exists"] is True
    assert {d["name"]: d["entries"] for d in data["dirs"]}.get("comics") == 1


# ---------------------------------------------------------------------------
# 库根白名单与破坏性操作护栏（安全负例）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_root", ["/etc", "/tmp", "relative/path", ""])
def test_库根越界被拒(client, auth_headers, bad_root):
    r = client.post("/api/libraries", headers=auth_headers, json={
        "name": "坏库", "type": "ebook", "mode": "inplace", "root_path": bad_root})
    assert r.status_code == 400
    assert "库根" in r.json()["detail"]


@pytest.mark.parametrize("bad", [
    ("name", "非法类型", {"type": "nope"}),
    ("mode", "非法模式", {"mode": "somewhere"}),
])
def test_非法类型与模式被拒(client, auth_headers, tmp_path, bad):
    _, _, extra = bad
    payload = {"name": "某库", "type": "ebook", "mode": "inplace",
               "root_path": str(tmp_path / "libs" / "x")}
    payload.update(extra)
    assert client.post("/api/libraries", headers=auth_headers, json=payload).status_code == 400


def test_空库名被拒(client, auth_headers, tmp_path):
    r = client.post("/api/libraries", headers=auth_headers, json={
        "name": "   ", "type": "ebook", "mode": "inplace",
        "root_path": str(tmp_path / "libs" / "x")})
    assert r.status_code == 400
    assert "库名" in r.json()["detail"]


def test_没有任何库是不可删除的(client, auth_headers, test_lib_id, make_library):
    """第 37 期：以前那条「默认书库不可删除」的护栏随默认库概念一起下线。

    现在**每一**条库都能删 —— 但「库里还有书」的拦截仍在（那才是真正的数据保护，
    见 test_非空库需force才移除登记且不删文件）。
    """
    empty = make_library("comic2", "空漫画库", "comic", pathlib.Path(config.LIBRARY_SOURCE_DIR) / "c2")
    for lid in (test_lib_id, empty["id"]):
        r = client.delete(f"/api/libraries/{lid}", headers=auth_headers)
        assert r.status_code == 200, f"{lid} 应当可以移除登记：{r.text}"


def test_非空库需force才移除登记且不删文件(client, auth_headers):
    root = pathlib.Path(config.LIBRARY_SOURCE_DIR) / "ebooks"
    root.mkdir(parents=True, exist_ok=True)
    (root / "三体.epub").write_bytes(b"EPUB")
    lib = _create_library(client, auth_headers, "电子书库", "ebook", root)

    denied = client.delete(f"/api/libraries/{lib['id']}", headers=auth_headers)
    assert denied.status_code == 400
    assert "还有 1 本书" in denied.json()["detail"]

    ok = client.delete(f"/api/libraries/{lib['id']}?force=true", headers=auth_headers)
    assert ok.status_code == 200
    assert ok.json()["books_left_on_disk"] == 1
    # 关键：**只移除登记，文件必须还在**
    assert (root / "三体.epub").is_file()
    ids = {i["id"] for i in client.get("/api/libraries", headers=auth_headers).json()["items"]}
    assert lib["id"] not in ids


def test_不存在的书库返回404(client, auth_headers):
    assert client.patch("/api/libraries/不存在", headers=auth_headers,
                        json={"name": "x"}).status_code == 404
    assert client.post("/api/libraries/不存在/scan", headers=auth_headers).status_code == 404


# ---------------------------------------------------------------------------
# 迁移全链路（预览 → 计划 → 执行 → 回滚）
# ---------------------------------------------------------------------------

@pytest.fixture
def three_media_in_default(isolated, default_root, make_book, make_audio_dir):  # noqa: ARG001
    make_book(default_root, "三体.epub")
    make_book(default_root, "测试漫画 01.cbz")
    make_audio_dir(default_root, "活着", tracks=2)
    library.invalidate()
    return default_root


def _register_three_libraries(client, headers) -> None:
    """建三个类型库（显式给 id：中文名会自动派生哈希 id，断言里不好引用）。"""
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    for lid, name, ltype in (("ebook", "电子书库", "ebook"),
                             ("comic", "漫画库", "comic"),
                             ("audiobook", "有声书库", "audiobook")):
        _create_library(client, headers, name, ltype, src / f"{lid}s",
                        id=lid, source_subdir=f"{lid}s")


def test_迁移全链路(client, auth_headers, three_media_in_default):
    _register_three_libraries(client, auth_headers)

    pv = client.get("/api/library-migrations/preview", headers=auth_headers).json()
    assert pv["total"] == 3 and pv["ready"] == 3
    assert pv["needs_confirm"] is True

    planned = client.post("/api/library-migrations/plan", headers=auth_headers, json={}).json()
    assert planned["batch_id"] and planned["created"] == 3

    applied = client.post("/api/library-migrations/apply", headers=auth_headers,
                          json={"batch_id": planned["batch_id"]}).json()
    assert applied["ok"] is True and applied["moved"] == 3 and applied["failed"] == 0

    counts: dict = {}
    for b in library.books():
        counts[b["library_id"]] = counts.get(b["library_id"], 0) + 1
    assert counts == {"ebook": 1, "comic": 1, "audiobook": 1}
    assert client.get("/api/library-migrations/preview", headers=auth_headers).json()["total"] == 0

    rolled = client.post("/api/library-migrations/rollback", headers=auth_headers,
                         json={"batch_id": planned["batch_id"]}).json()
    assert rolled["ok"] is True and rolled["restored"] == 3
    assert (pathlib.Path(three_media_in_default) / "三体.epub").is_file()


def test_迁移接口的参数校验(client, auth_headers):
    assert client.post("/api/library-migrations/apply", headers=auth_headers,
                       json={}).status_code == 400
    bad = client.post("/api/library-migrations/apply", headers=auth_headers,
                      json={"batch_id": "不存在的批次"})
    assert bad.status_code == 400
    assert client.get("/api/library-migrations/preview?targets=非法JSON",
                      headers=auth_headers).status_code == 400


def test_迁移门禁可暂不迁移与复位(client, auth_headers, three_media_in_default):
    _register_three_libraries(client, auth_headers)
    assert client.get("/api/library-migrations/preview",
                      headers=auth_headers).json()["needs_confirm"] is True

    client.post("/api/library-migrations/dismiss", headers=auth_headers, json={"note": "测试"})
    assert client.get("/api/library-migrations/preview",
                      headers=auth_headers).json()["needs_confirm"] is False

    client.post("/api/library-migrations/reset-gate", headers=auth_headers)
    assert client.get("/api/library-migrations/preview",
                      headers=auth_headers).json()["needs_confirm"] is True


# ---------------------------------------------------------------------------
# 书籍元数据：编辑 → 覆盖 → 恢复
# ---------------------------------------------------------------------------

def test_元数据编辑产生用户覆盖(client, auth_headers, default_root):
    _build_real_epub(default_root, "三体.epub", title="三体")
    library.invalidate()
    bid = _find_book(client, auth_headers, "三体")["id"]

    before = client.get(f"/api/books/{bid}/metadata", headers=auth_headers).json()
    assert before["editable"] is True
    assert before["meta"]["publisher"]["overridden"] is False
    assert before["fields"]["title"] == "三体"

    # 编辑 → 记为用户覆盖（受抓取保护），并记下编辑前的原值供回退
    edited = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                         json={"fields": {"publisher": "用户出版社"}}).json()
    assert "publisher" in edited["changed"]
    assert edited["meta"]["publisher"]["overridden"] is True
    assert edited["meta"]["publisher"]["value"] == "用户出版社"
    row = db.get_override_row(bid, "publisher")
    assert row["value"] == "用户出版社"
    assert row["orig"] == ""            # OPF 里本来没有出版社

    # 再改回 OPF 原值 → 撤销覆盖（回到「跟随在线 / OPF」）
    back = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                       json={"fields": {"publisher": ""}}).json()
    assert back["meta"]["publisher"]["overridden"] is False
    assert db.get_override_row(bid, "publisher") is None


def test_恢复到在线值(client, auth_headers, default_root):
    """有在线缓存值时，「恢复」撤销覆盖，展示回落到在线值（不写文件，见 T3）。"""
    _build_real_epub(default_root, "测试书.epub", title="测试书")
    library.invalidate()
    bid = _find_book(client, auth_headers, "测试书")["id"]
    db.set_online(bid, {"publisher": ("在线出版社", "openlibrary")})

    client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                json={"fields": {"publisher": "用户出版社"}})
    r = client.post(f"/api/books/{bid}/metadata/revert", headers=auth_headers,
                    json={"fields": ["publisher"]})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["recovered"] == ["publisher"]
    assert data["meta"]["publisher"]["overridden"] is False
    assert data["meta"]["publisher"]["online"] == "在线出版社"


def test_非EPUB也能编辑元数据(client, auth_headers, default_root, make_book):
    """第 22 期：手动编辑不再限 EPUB（此前断言「非 EPUB 一律 400」）。

    原先限 EPUB 的理由是「字段的兜底原值来自 OPF」；第 18/19 期把改动改成只落服务端 DB
    之后这条前提就不成立了 —— 非 EPUB 没有 OPF 层，「恢复原值」即撤销覆盖后回落在线的
    抓取值、没有在线值就是空，是清晰语义而不是缺口。
    """
    make_book(default_root, "测试漫画.cbz")
    library.invalidate()
    bid = next(b["id"] for b in _books(client, auth_headers) if b["format"] == "CBZ")

    assert client.get(f"/api/books/{bid}/metadata",
                      headers=auth_headers).json()["editable"] is True

    r = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                    json={"fields": {"publisher": "服务端社"}})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == ["publisher"]
    # 详情与列表（批量热路径）读到同一个值
    assert r.json()["fields"]["publisher"] == "服务端社"
    row = next(b for b in _books(client, auth_headers) if b["id"] == bid)
    assert row["publisher"] == "服务端社"


def test_提交不支持的字段被拒(client, auth_headers, default_root):
    _build_real_epub(default_root, "字段测试.epub", title="字段测试")
    library.invalidate()
    bid = _find_book(client, auth_headers, "字段测试")["id"]

    r = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                    json={"fields": {"不存在的字段": "x"}})
    assert r.status_code == 400
    assert "没有可改写的字段" in r.json()["detail"]


# ---------------------------------------------------------------------------
# 能力清单 / 系列按媒体分组（第 10 期收尾项）
# ---------------------------------------------------------------------------

def test_能力清单按库类型返回(client, auth_headers):
    everything = client.get("/api/features", headers=auth_headers).json()
    assert len(everything["features"]) == 18          # 「全部书库」= 不裁剪（含第 14 期的 opds；第 16 期删掉 opds_sources；第 34 期加 bookmarks）

    comic = _create_library(client, auth_headers, "漫画库", "comic",
                            pathlib.Path(config.LIBRARY_SOURCE_DIR) / "comics")
    per_lib = client.get(f"/api/features?library_id={comic['id']}", headers=auth_headers).json()
    assert per_lib["library_type"] == "comic"
    assert "comic" in per_lib["features"]
    # 第 21 期：元数据抓取不再按格式分流 → 漫画库也有该能力；本地转换仍只给电子书库
    assert "convert" not in per_lib["features"] and "metadata" in per_lib["features"]


def test_系列详情按媒体分组(client, auth_headers, default_root):
    _build_real_epub(default_root, "地球往事 1.epub", title="三体")
    _build_real_epub(default_root, "地球往事 2.epub", title="三体II")
    library.invalidate()

    for title, index in (("三体", "1"), ("三体II", "2")):
        bid = _find_book(client, auth_headers, title)["id"]
        r = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                        json={"fields": {"series": "地球往事", "series_index": index}})
        assert r.status_code == 200, r.text

    detail = client.get("/api/series/地球往事", headers=auth_headers).json()
    assert detail["count"] == 2
    assert len(detail["groups"]) == 1
    group = detail["groups"][0]
    assert group["media"] == "ebook"
    assert group["label"] == "电子书库"
    assert group["count"] == 2 and len(group["books"]) == 2


# ---------------------------------------------------------------------------
# 系列级元数据（第 12 期 C3）：编辑 / 覆盖 / 恢复 / 抓取优雅失败 / 重排 / 三处注入
# ---------------------------------------------------------------------------

def _series_setup(root, series: str = "银河帝国") -> str:
    """三册真 EPUB 同系列：出版社 2:1 多数派、年份 2012–2015、题材有交集与独有项。"""
    from novelforge.core import fileops

    for fn, title, idx, pub, year, tags in (
        ("基地.epub", "基地", "1", "江苏文艺出版社", "2012", ["科幻", "经典"]),
        ("基地与帝国.epub", "基地与帝国", "2", "江苏文艺出版社", "2013", ["科幻"]),
        ("第二基地.epub", "第二基地", "3", "读客文化", "2015", ["科幻", "太空"]),
    ):
        p = _build_real_epub(root, fn, title=title)
        assert fileops.patch_epub_meta(p, {"series": series, "series_index": idx,
                                           "publisher": pub, "date": year, "tags": tags})
    library.invalidate()
    return series


@pytest.fixture
def enable_services():
    """临时开启 OPDS / Komga 兼容服务 —— 注入点要启用后才能访问（未启用一律 404）。

    设置覆盖层写在**会话级** CONFIG_DIR 上，所以退出时必须还原，否则会渗到别的用例。
    """
    config.save_overrides({"opds": {"enabled": True},
                           "komga": {"enabled": True, "username": "admin", "api_key": "test-key"}})
    try:
        yield ("admin", "test1234")
    finally:
        config.save_overrides({})


def test_系列详情带元数据分层(client, auth_headers, default_root):
    name = _series_setup(default_root)
    detail = client.get(f"/api/series/{name}", headers=auth_headers).json()
    meta = detail["meta"]
    assert meta["owned_count"] == 3, "册数是实际拥有数"
    assert meta["publisher"] == "江苏文艺出版社" and meta["first_year"] == "2012"
    assert meta["tags"] == ["科幻", "经典", "太空"] and meta["declared_count"] == 0
    assert set(detail["meta_state"]) == {"description", "publisher", "first_year", "tags"}
    assert detail["meta_state"]["publisher"]["aggregated"] == "江苏文艺出版社"


def test_系列列表带简介字段(client, auth_headers, default_root):
    name = _series_setup(default_root)
    items = client.get("/api/series", headers=auth_headers).json()["items"]
    hit = next(i for i in items if i["name"] == name)
    assert hit["description"] == "" and hit["source"] == "", "没抓过就是空值，前端有值才渲染"
    assert hit["covers"] and hit["count"] == 3


def test_系列元数据编辑与恢复(client, auth_headers, default_root):
    name = _series_setup(default_root)
    r = client.get(f"/api/series/{name}/meta", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["fields"] == ["description", "publisher", "first_year", "tags"]

    r = client.post(f"/api/series/{name}/meta", headers=auth_headers,
                    json={"description": "银河帝国系列总简介"})
    assert r.status_code == 200, r.text
    assert r.json()["meta"]["description"] == "银河帝国系列总简介"
    assert r.json()["meta"]["overridden"]["description"] is True

    # 覆盖后不再随聚合/在线变化；清空即撤销覆盖
    r = client.post(f"/api/series/{name}/meta", headers=auth_headers, json={"description": ""})
    assert r.json()["meta"]["description"] == ""
    assert r.json()["meta"]["overridden"]["description"] is False
    # 未覆盖的字段始终取聚合值
    assert r.json()["meta"]["publisher"] == "江苏文艺出版社"


def test_系列元数据接口边界(client, auth_headers, default_root):
    name = _series_setup(default_root)
    assert client.get(f"/api/series/{name}/meta").status_code == 401, "无令牌必须拒绝"
    assert client.get("/api/series/不存在/meta", headers=auth_headers).status_code == 404
    # 字段白名单：不校验就等于放任任意列名流进库里
    assert client.post(f"/api/series/{name}/meta", headers=auth_headers,
                       json={"owned_count": "999"}).status_code == 400
    assert client.post(f"/api/series/{name}/meta", headers=auth_headers,
                       json={}).status_code == 400


def test_系列抓取离线优雅失败(client, auth_headers, default_root):
    """会外呼的接口只断言「不抛、结构正确」—— 测试环境抓取默认关闭。"""
    name = _series_setup(default_root)
    r = client.post(f"/api/series/{name}/fetch", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is False and r.json()["result"]["error"]
    assert client.post("/api/series/不存在/fetch", headers=auth_headers).status_code == 404
    assert client.post(f"/api/series/{name}/fetch").status_code == 401


def test_系列批量抓取结构与分批(client, auth_headers, default_root):
    _series_setup(default_root)
    r = client.post("/api/series/fetch-all", headers=auth_headers, json={"limit": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"total", "ok", "failed", "remaining", "items"}
    assert body["total"] == 1, "limit 应把一次处理的量卡住（前端循环显示进度）"
    assert body["failed"] == 1, "抓取未启用 → 如实计入失败，而不是抛错"
    assert client.post("/api/series/fetch-all", headers=auth_headers,
                       json={"names": "不是数组"}).status_code == 400


def test_重排册号预览与执行(client, auth_headers, default_root):
    name = _series_setup(default_root)
    before = {b["title"]: b["id"] for b in _books(client, auth_headers)}

    preview = client.get(f"/api/series/{name}/renumber/preview", headers=auth_headers)
    assert preview.status_code == 200, preview.text
    items = preview.json()["items"]
    assert [i["new_index"] for i in items] == ["1", "2", "3"]

    # 倒序重排：序号变了、文件名与 book_id 不能变
    payload = [{"name": i["name"], "new_index": str(len(items) - n)}
               for n, i in enumerate(items)]
    r = client.post(f"/api/series/{name}/renumber/apply", headers=auth_headers,
                    json={"items": payload})
    assert r.status_code == 200, r.text
    assert r.json()["renumbered"] == 3 and r.json()["mismatched"] == []
    assert {b["title"]: b["id"] for b in _books(client, auth_headers)} == before, \
        "只改 OPF 序号：book_id 不变 → 进度/批注不断链"
    assert client.get(f"/api/series/{name}",
                      headers=auth_headers).json()["meta"]["owned_count"] == 3


def test_重排册号接口边界(client, auth_headers, default_root):
    name = _series_setup(default_root)
    assert client.get("/api/series/不存在/renumber/preview", headers=auth_headers).status_code == 404
    assert client.post(f"/api/series/{name}/renumber/apply", headers=auth_headers,
                       json={"items": []}).status_code == 400
    assert client.get(f"/api/series/{name}/renumber/preview").status_code == 401


def test_Komga系列摘要注入(client, enable_services, auth_headers, default_root):
    """Komga 客户端的 SeriesDto.metadata.summary 必须带出系列简介（原先恒为空串）。"""
    from novelforge.core import komga_api

    name = _series_setup(default_root)
    client.post(f"/api/series/{name}/meta", headers=auth_headers, json={"description": "系列简介"})

    sid = komga_api.series_id(name)
    r = client.get(f"/api/v1/series/{sid}", auth=enable_services)
    assert r.status_code == 200, r.text
    dto = r.json()
    assert dto["metadata"]["summary"] == "系列简介"
    assert dto["booksMetadata"]["summary"] == "系列简介"
    assert dto["metadata"]["publisher"] == "江苏文艺出版社"


def test_OPDS系列入口带简介(client, enable_services, auth_headers, default_root):
    """订阅端在系列列表（<summary>）与系列内（<subtitle>）都能看到简介。"""
    import urllib.parse

    name = _series_setup(default_root)
    client.post(f"/api/series/{name}/meta", headers=auth_headers, json={"description": "系列简介"})

    nav = client.get("/opds/series", auth=enable_services)
    assert nav.status_code == 200, nav.text
    assert "系列简介" in nav.text and "<summary" in nav.text

    one = client.get(f"/opds/series/{urllib.parse.quote(name)}", auth=enable_services)
    assert one.status_code == 200, one.text
    assert "系列简介" in one.text and "<subtitle" in one.text
    # 作者 / 标签列表不该被顺带注入（那里没有系列简介的概念）
    auth_nav = client.get("/opds/authors", auth=enable_services)
    assert auth_nav.status_code == 200 and "<summary" not in auth_nav.text
