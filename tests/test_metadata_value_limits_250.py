"""元数据覆盖值的**长度上限**（第 250 期）。

## 缺陷

覆盖值（`meta_override`）会**进书目列表的响应**（`/api/books` 每本书都带
title / author / series…），而此前**没有任何长度限制** ⇒ 用户把书名粘成 1 MB 文本
也能保存 ⇒

- 一页 120 本的响应 = **120 MB**（每本 1 MB）⇒ 浏览器直接崩；
- 不分页时 = 2309 本 × 1 MB ≈ **2.3 GB** ⇒ 书架彻底打不开，**且没有自愈路径**
  （除非手改数据库）。

## 修法

长度上限放在**存储层**（`set_override` / `set_overrides` 共用的 `_ovr_norm`）⇒
任何调用方（单书编辑 / 正则导入 / 批量改名 / 实体改名）都受约束，**一处**。
上限**按字段**给：`description` / `tags` / `narrators` 不进列表（第 68 期只发
`has_description`）⇒ 可以宽；进列表的短字段 ⇒ 严。

⚠️ **超限是「拒绝」不是「截断」** —— 截断会静默丢数据（用户以为改了完整值）。
"""
from __future__ import annotations

import pytest

from novelforge.core import db


def test_超长的书名被拒绝():
    with pytest.raises(ValueError) as e:
        db.set_override("lib$x$b1", "title", "长" * 5000)
    assert "太长" in str(e.value)


def test_超长的简介也按自己的上限拒绝(isolated):
    """`description` 不进列表 ⇒ 上限宽（8000），但仍要有上限。"""
    db.set_override("lib$x$b1", "description", "简" * 4000)   # 不抛
    with pytest.raises(ValueError):
        db.set_override("lib$x$b2", "description", "简" * 9000)


def test_正常长度的值照旧写得进去(isolated):
    db.set_override("lib$x$b1", "title", "三体")
    assert db.get_override_row("lib$x$b1", "title")["value"] == "三体"


def test_撤销覆盖不受长度上限影响(isolated):
    """撤销 = 传空串 ⇒ 空值不校验长度（否则「撤销一个超长的旧值」会被拦）。"""
    db.set_override("lib$x$b1", "title", "")       # 撤销
    assert db.get_override_row("lib$x$b1", "title") is None


def test_批量写入里有一条超长则整批不写(isolated):
    """批量与单本**同一套判据**（`_ovr_norm` 共用）⇒ 超长的一条会让整批失败。"""
    with pytest.raises(ValueError):
        db.set_overrides([
            ("lib$x$b1", "title", "正常", ""),
            ("lib$x$b2", "title", "长" * 5000, ""),
        ])
    assert db.get_override_row("lib$x$b1", "title") is None, "超长那条不该把整批写进去"


def test_上限表覆盖了所有会进列表的短字段():
    """上限表不能漏掉「进列表」的字段 —— 漏一个就等于那个字段没上限。"""
    from novelforge.core import fileops

    listed = {"title", "author", "series", "series_index", "subtitle"}
    missing = sorted(f for f in listed if f not in db._FIELD_MAX_LEN)
    assert not missing, f"这些字段进列表却没有长度上限：{missing}"
    assert all(db._FIELD_MAX_LEN[f] <= 500 for f in listed), db._FIELD_MAX_LEN


def test_在线抓取值超长则跳过该字段而不是整次失败(isolated):
    """⚠️ 处置与用户写入**故意不同**。

    用户写入超长 ⇒ **拒绝**（抛错，告诉用户「太长了」）；
    在线抓取超长 ⇒ **跳过该字段**（不抛）—— 一家站点返回异常大的 title，
    不该毁掉**整次抓取**（其它字段照写）。
    """
    db.set_online("lib$x$b1", {
        "title": ("长" * 5000, "src"),        # 超长 ⇒ 跳过
        "author": ("刘慈欣", "src"),          # 正常 ⇒ 写入
    })
    got = db.get_online("lib$x$b1")
    assert "title" not in got, got
    assert got["author"]["value"] == "刘慈欣", got


def test_两个入口共用同一套上限判据():
    """上限表只有一份（`db._FIELD_MAX_LEN`），两个入口都查它。"""
    from novelforge.core import db as dbmod
    assert dbmod._too_long("title", "x" * 1000) > 0
    assert dbmod._too_long("title", "x" * 10) == 0
    # 未知字段按兜底上限算
    assert dbmod._too_long("没登记的字段", "x" * (dbmod._DEFAULT_FIELD_MAX_LEN + 1)) > 0


def test_服务端把长度超限翻成_400(client, auth_headers, isolated, make_library, make_book, tmp_path):
    """⚠️ 第 250 期：超限是**用户的输入问题** ⇒ 4xx + 人话，不是 500「服务器错误」。

    （上限的闸门在存储层 `core/db.py`，这里是**服务端**那一侧的翻译。）
    """
    root = tmp_path / "lib"
    make_library("lib$m", "限长库", "ebook", root)
    make_book(root, "三体.epub")
    from novelforge.core import library
    library.invalidate()
    bid = library.books("lib$m")[0]["id"]

    r = client.post(f"/api/books/{bid}/metadata", headers=auth_headers,
                    json={"fields": {"title": "长" * 5000}})
    assert r.status_code == 400, (r.status_code, r.text[:200])
    assert "太长" in str(r.json().get("detail", "")), r.text[:200]


def test_元数据详情会下发逐字段上限(client, auth_headers, isolated,
                                    make_library, make_book, tmp_path):
    """前端据此给输入框加 `maxlength`（前端**不抄**一份上限表）。"""
    root = tmp_path / "lib"
    make_library("lib$lim", "下发库", "ebook", root)
    make_book(root, "三体.epub")
    from novelforge.core import library
    library.invalidate()
    bid = library.books("lib$lim")[0]["id"]

    r = client.get(f"/api/books/{bid}/metadata", headers=auth_headers)
    assert r.status_code == 200, r.text
    limits = r.json()["limits"]
    assert limits["title"] == db._FIELD_MAX_LEN["title"], limits
    assert limits["author"] == db._FIELD_MAX_LEN["author"], limits
