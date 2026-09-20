"""作者排序名（第 32 期）：本地覆盖 > 在线 的回退链、撤销覆盖、老库补列、接口三态。

排序名与显示名分开，解决的是「鲁迅」要排在 L 下、「The Lord of the Rings」要按 Lord
排这类问题 —— 都不是把显示名改掉能解决的。存储与 bio 同构：`sort_name`（在线值）与
`sort_name_local`（本地覆盖）**分列**，生效取本地覆盖 > 在线；两者都空则排序回退到
显示名（= 加此列之前的行为，一字不差）。

⚠️ 「在线值」列当前**没有抓取数据源**（上游 Provider 也没提供该字段），所以覆盖该分支
的用例一律直接写库 —— 这不是绕开抓取，而是如实反映现状：列先建好，将来接入 Provider 的
sort name 字段时直接写它即可，不必再迁移一次。

离线约定：本文件不发起任何外呼；造「有作者的书」用真 EPUB（`epub_builder`），
因为作者名来自 OPF，假 `b"EPUB"` 占位解析不出来。
"""
import pathlib
import urllib.parse

import pytest

from novelforge.core import authors as authors_mod, db, epub_builder, library


def _quote(name: str) -> str:
    return urllib.parse.quote(name)


@pytest.fixture
def author_fixture(isolated, default_root):  # noqa: ARG001 —— 依赖 isolated 切目录
    """一本带作者的真实 EPUB，让 `library.authors_list()` 认得这个作者。"""
    path = pathlib.Path(default_root) / "呐喊.epub"
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": "呐喊", "author": "鲁迅", "language": "zh"},
        [{"title": "狂人日记", "body_html": "<p>正文</p>"}],
        str(path),
    )
    library.invalidate()
    return "鲁迅"


# ---------------- 回退链（纯逻辑，直接操作表行）----------------

def test_排序名回退链_本地覆盖优先于在线(isolated):  # noqa: ARG001
    db.set_author_sort_name_local("某人", "Local Name")
    db._connect().execute(
        "UPDATE authors SET sort_name=? WHERE name=?", ("Online Name", "某人"))
    db._connect().commit()
    row = db.get_author("某人")
    assert authors_mod.sort_name_of(row) == "Local Name"
    assert authors_mod.effective("某人")["sort_name"] == "Local Name"
    assert authors_mod.effective("某人")["sort_name_overridden"] is True


def test_排序名回退链_无本地覆盖时用在线值(isolated):  # noqa: ARG001
    db._connect().execute(
        "INSERT INTO authors(name, sort_name) VALUES(?,?)", ("某人", "Online Name"))
    db._connect().commit()
    assert authors_mod.sort_name_of(db.get_author("某人")) == "Online Name"
    info = authors_mod.effective("某人")
    assert info["sort_name"] == "Online Name"
    # 生效值来自在线 ⇒ 不算「本地覆盖」，前端据此决定是否显示「恢复在线」
    assert info["sort_name_overridden"] is False


def test_排序名两列全空时为空串_不回退到显示名(isolated):  # noqa: ARG001
    """空串 = 「没设排序名」，回退到显示名是**排序时**的事，不在这一层做。

    否则「没设」与「设成和显示名一样」会被抹成同一状态，前端无法区分。
    """
    db.set_author_bio_local("鲁迅", "x")  # 造一行，只填 bio
    info = authors_mod.effective("鲁迅")
    assert info["sort_name"] == ""
    assert info["sort_name_overridden"] is False
    # 显示名始终原样返回，没被排序名污染
    assert info["name"] == "鲁迅"


def test_无行的作者也能写入排序名_upsert(isolated):  # noqa: ARG001
    """作者可能从没被抓取过（表里没有行），只设排序名时也要能落库。"""
    assert db.get_author("查无此人") is None
    authors_mod.set_sort_name("查无此人", "Nobody")
    assert db.get_author("查无此人") is not None
    assert authors_mod.effective("查无此人")["sort_name"] == "Nobody"


def test_撤销覆盖_空串回退到在线(isolated):  # noqa: ARG001
    db.set_author_bio_local("某人", "bio")  # 造行，同时确保撤销不误伤别的列
    authors_mod.set_sort_name("某人", "Local Name")
    authors_mod.set_sort_name("某人", "")
    info = authors_mod.effective("某人")
    assert info["sort_name"] == ""            # 无在线值 ⇒ 空
    assert info["sort_name_overridden"] is False
    assert info["bio"] == "bio"               # 撤销排序名不动 bio


def test_排序名首尾空白被裁掉(isolated):  # noqa: ARG001
    authors_mod.set_sort_name("某人", "  Lu Xun  ")
    assert authors_mod.effective("某人")["sort_name"] == "Lu Xun"


# ---------------- 老库补列 ----------------

def test_老库自动补排序名列(isolated):  # noqa: ARG001
    """老库（authors 表没有排序名两列）在初始化时自动补列，且存量行照旧可读。

    做法：先用当前 schema 建库并写一行，再把两列 DROP 掉模拟老库，
    关连接后重新 `init()` —— 若迁移段漏了，下面读 `sort_name_local` 会报 no such column。
    """
    db.set_author_bio_local("鲁迅", "存量传记")
    c = db._connect()
    c.execute("ALTER TABLE authors DROP COLUMN sort_name")
    c.execute("ALTER TABLE authors DROP COLUMN sort_name_local")
    c.commit()
    db.close()

    db.init()  # 迁移段应在此补回两列
    cols = {r["name"] for r in db._connect().execute("PRAGMA table_info(authors)")}
    assert {"sort_name", "sort_name_local"} <= cols
    # 存量行没丢，且新列取默认空串（= 排序回退到显示名，与加列前一致）
    row = db.get_author("鲁迅")
    assert row["bio_local"] == "存量传记"
    assert authors_mod.sort_name_of(row) == ""
    # 补列后立即可写
    authors_mod.set_sort_name("鲁迅", "Lu Xun")
    assert authors_mod.effective("鲁迅")["sort_name"] == "Lu Xun"


# ---------------- 接口 ----------------

def test_接口_列表与详情都下发排序名(client, auth_headers, author_fixture):
    name = author_fixture
    r = client.post(f"/api/authors/{_quote(name)}/sort-name",
                    json={"sort_name": "Lu Xun"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["sort_name"] == "Lu Xun"
    assert r.json()["sort_name_overridden"] is True

    detail = client.get(f"/api/authors/{_quote(name)}", headers=auth_headers).json()
    assert detail["sort_name"] == "Lu Xun"
    assert detail["sort_name_overridden"] is True

    # 列表接口也要给 —— 作者总览的「按姓名」排序就靠它
    items = {a["name"]: a for a in
             client.get("/api/authors", headers=auth_headers).json()["items"]}
    assert items[name]["sort_name"] == "Lu Xun"


def test_接口_撤销覆盖后列表回落到空(client, auth_headers, author_fixture):
    name = author_fixture
    client.post(f"/api/authors/{_quote(name)}/sort-name",
                json={"sort_name": "Lu Xun"}, headers=auth_headers)
    r = client.post(f"/api/authors/{_quote(name)}/sort-name",
                    json={"sort_name": ""}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["sort_name"] == ""
    assert r.json()["sort_name_overridden"] is False
    items = {a["name"]: a for a in
             client.get("/api/authors", headers=auth_headers).json()["items"]}
    assert items[name]["sort_name"] == ""


def test_接口_排序名_作者不存在404(client, auth_headers):
    r = client.post(f"/api/authors/{_quote('查无此人')}/sort-name",
                    json={"sort_name": "x"}, headers=auth_headers)
    assert r.status_code == 404


def test_接口_排序名_缺字段400(client, auth_headers, author_fixture):
    r = client.post(f"/api/authors/{_quote(author_fixture)}/sort-name",
                    json={}, headers=auth_headers)
    assert r.status_code == 400


def test_接口_排序名_未认证401(client, author_fixture):
    r = client.post(f"/api/authors/{_quote(author_fixture)}/sort-name",
                    json={"sort_name": "x"})
    assert r.status_code == 401
