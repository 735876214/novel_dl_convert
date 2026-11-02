"""**自定义字段的值**也要有长度上限（第 255 期）。

## 缺陷

自定义字段（`book_custom_values` 表）的值此前**一个上限都没有**：

- 用户在详情页把一个自定义字段粘成 1 MB ⇒ **存得进去**；
- `custom` 段是**详情响应**的一部分（`GET /api/books/{bid}/metadata`）
  ⇒ 打开一次详情页 = 传 1 MB；
- ⚠️ 更狠的是**默认值**：`default_value` 会被抓取写进**每一本缺这一项的书**
  （`metafetch._custom_changes`）⇒ 一个 1 MB 的默认值 ⇒ **放大到全库**。

⇒ 前端的自定义字段输入框也**没有 `maxlength`**（OPF 字段那条在第 250 期补上了）
⇒ 用户**输入时不知道有上限**，提交后才知道。

## 这里钉四件事

1. **超长的值被拒**（400 + 人话，不是 500）；
2. **超长的默认值被拒**（新建 / 改定义两条路都拒）；
3. **上限表只有一份**（`customfields.value_limits()`）且**与元数据字段同口径**
   （文本类取 `db.metadata_field_limits()["description"]` ⇒ 不另抄一个数）；
4. **上限下发到前端**（详情页 `custom_limits` + 设置页 `limits`）
   ⇒ 输入框有 `maxlength` ⇒ 用户**输入时**就知道。
"""
from __future__ import annotations

import pytest

from novelforge.core import customfields, db, library


@pytest.fixture
def book(isolated, make_library, make_book, tmp_path):
    """造一个书库 + 一本书，返回它的 book_id。"""
    root = tmp_path / "lib"
    make_library("lib$cf", "自定义字段库", "ebook", root)
    make_book(root, "三体.epub")
    library.invalidate()
    return library.books("lib$cf")[0]["id"]


@pytest.fixture
def text_field(client, auth_headers):
    """建一个文本类型的自定义字段，返回它的 key。"""
    r = client.post("/api/custom-fields", headers=auth_headers,
                    json={"label": "备注", "type": "text"})
    assert r.status_code == 200, r.text
    return r.json()["item"]["key"]


def _limits() -> dict:
    return customfields.value_limits()


# ---------------- ① 值：超长被拒 ----------------

def test_超长的值被拒(client, auth_headers, book, text_field):
    r = client.post(f"/api/books/{book}/metadata", headers=auth_headers,
                    json={"custom": {text_field: "x" * 100000}})
    assert r.status_code == 400, r.text
    assert "太长" in str(r.json().get("detail", "")), r.text


def test_超长的值_没落库(client, auth_headers, book, text_field):
    r = client.post(f"/api/books/{book}/metadata", headers=auth_headers,
                    json={"custom": {text_field: "x" * 100000}})
    assert r.status_code == 400, r.text
    assert text_field not in db.custom_field_values(book), db.custom_field_values(book)


def test_正常值照旧能存(client, auth_headers, book, text_field):
    r = client.post(f"/api/books/{book}/metadata", headers=auth_headers,
                    json={"custom": {text_field: "正常的备注"}})
    assert r.status_code == 200, r.text
    assert db.custom_field_values(book).get(text_field) == "正常的备注"


def test_列表类型的值也超长被拒(client, auth_headers, book):
    r = client.post("/api/custom-fields", headers=auth_headers,
                    json={"label": "题材", "type": "list"})
    assert r.status_code == 200, r.text
    key = r.json()["item"]["key"]
    r = client.post(f"/api/books/{book}/metadata", headers=auth_headers,
                    json={"custom": {key: "x" * 100000}})
    assert r.status_code == 400, r.text
    assert "太长" in str(r.json().get("detail", "")), r.text


# ---------------- ② 默认值：超长被拒 ----------------

def test_超长的默认值被拒(client, auth_headers):
    r = client.post("/api/custom-fields", headers=auth_headers,
                    json={"label": "备注", "type": "text", "default_value": "x" * 100000})
    assert r.status_code == 400, r.text
    assert "太长" in str(r.json().get("detail", "")), r.text


def test_改定义时超长的默认值也被拒(client, auth_headers, text_field):
    defs = client.get("/api/custom-fields", headers=auth_headers).json()["items"]
    cid = next(d["id"] for d in defs if d["key"] == text_field)
    r = client.patch(f"/api/custom-fields/{cid}", headers=auth_headers,
                     json={"default_value": "x" * 100000})
    assert r.status_code == 400, r.text
    assert "太长" in str(r.json().get("detail", "")), r.text


# ---------------- ③ 上限表只有一份，且与元数据字段同口径 ----------------

def test_上限表与元数据字段同口径():
    """⚠️ **不另抄一个数** —— 文本类取元数据字段那张表（第 250 期立的）
    ⇒ 两条路**永远同上限**（抄一份就会漂）。"""
    assert _limits()["text"] == db.metadata_field_limits()["description"]


def test_四种类型都有上限():
    lim = _limits()
    for t in ("text", "number", "date", "list"):
        assert t in lim and lim[t] > 0, lim


# ---------------- ④ 上限下发到前端 ----------------

def test_详情接口下发自定义字段的上限(client, auth_headers, book):
    r = client.get(f"/api/books/{book}/metadata", headers=auth_headers)
    assert r.status_code == 200, r.text
    cl = r.json().get("custom_limits") or {}
    assert cl, "详情接口必须下发自定义字段的上限（前端据此加 maxlength）"
    assert cl["text"] == _limits()["text"]


def test_自定义字段列表接口下发上限(client, auth_headers):
    r = client.get("/api/custom-fields", headers=auth_headers)
    assert r.status_code == 200, r.text
    lim = r.json().get("limits") or {}
    assert lim, "设置页必须拿到上限（默认值输入框据此加 maxlength）"
    assert lim["text"] == _limits()["text"]


# ---------------- 边界：刚好等于上限不算超 ----------------

def test_刚好等于上限不算超():
    lim = _limits()["text"]
    out = customfields.normalize("text", "x" * lim)
    assert len(out) == lim
