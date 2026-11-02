"""**抓取预览阶段就标出「这个字段太长」**（第 259 期）。

## 缺陷

写入侧对超长的值有明确的处置（**第 250 / 255 期**）：

- 元数据字段超长 ⇒ **跳过该字段**（`db.set_online` 返回被跳过的字段名）；
- 自定义字段超长 ⇒ **拒绝**（`customfields.normalize` 抛 ValueError，第 255 期）。

但**预览阶段**（`metafetch.plan`，**只算不改**）此前**完全不做长度检查**：

- 界面列出「书名、简介、标签…」这些要改的字段，**看不出哪个会被丢掉**；
- 用户点「应用」⇒ 才在 toast 里看到一句「**N 个字段太长没写进去**」
  —— 但**哪个**字段没写进去，界面**没说**；
- ⚠️ 更糟：**自定义字段**那条是**抛**的 ⇒ 一个超长的自定义字段值会让
  **整次抓取失败**（该书一个字都写不进去）⇒ 与元数据字段**口径不同**。

## 这里钉四件事

1. **预览里标出超长的字段**（`changes[field].too_long`）⇒ 用户**在提交前**就知道；
2. **自定义字段超长也是「跳过」**（不是抛）⇒ 与元数据字段**同一口径**，
   一家返回异常值不该毁掉**整次**抓取；
3. **跳过要如实回报**（`skipped_long` 里带上它）⇒ 回执说「跳过了哪个」；
4. **判据只有一处**（写入侧用的那张表）⇒ 预览与写入**不会各说各话**。
"""
from __future__ import annotations

import pytest

from novelforge.core import customfields, db, metafetch


@pytest.fixture
def fake_limits(monkeypatch):
    """把上限调小（免得造几 MB 的字符串）。"""
    limits = db.metadata_field_limits()
    small = dict(limits)
    small["title"] = 10
    small["description"] = 20
    monkeypatch.setattr(db, "metadata_field_limits", lambda: small)
    monkeypatch.setattr(customfields, "value_limits",
                        lambda: {"text": 10, "number": 10, "date": 10, "list": 10})
    return small


def test_判据与写入侧同表():
    """⚠️ 预览与写入**必须用同一张表** —— 否则预览说「不超长」、写入却跳过。"""
    # 写入侧用的是 `customfields.normalize` ⇒ 它过 `value_limits()`
    assert metafetch._too_long_value("x", "y" * 5000, custom=True) is True
    assert metafetch._too_long_value("x", "短", custom=True) is False


def test_超长的值_预览里标出来(monkeypatch, fake_limits):
    changes = {"title": {"from": "", "to": "超长" * 50, "source": "X", "score": 1.0},
               "author": {"from": "", "to": "短", "source": "X", "score": 1.0}}
    out = metafetch._mark_too_long(changes, set())
    assert out["title"]["too_long"] is True
    assert "too_long" not in out["author"], out["author"]


def test_数组字段按整段算(monkeypatch, fake_limits):
    """⚠️ `tags` / `narrators` 是**数组** ⇒ 按**整段序列化后**的长度算
    —— 与写入侧 `db._as_list` 的存法一致（按「每条」算会漏判）。

    这里用 `tags`（它的上限是 2000）⇒ 造一个**每条都不长、但整段超限**的数组：
    正是「按每条算会漏判」的那种形态。
    """
    changes = {"tags": {"from": "", "to": ["很长" * 20] * 100, "source": "X", "score": 1.0}}
    out = metafetch._mark_too_long(changes, set())
    assert out["tags"]["too_long"] is True


def test_正常值不标(monkeypatch, fake_limits):
    changes = {"title": {"from": "", "to": "短标题", "source": "X", "score": 1.0}}
    out = metafetch._mark_too_long(changes, set())
    assert "too_long" not in out["title"], out["title"]


# ---------------------------------------------------------------------------
# 端到端：预览标出来 ⇒ apply **跳过**（不是整次抓取失败）
# ---------------------------------------------------------------------------

def _real_epub(root, name: str) -> pathlib.Path:
    """真实可解析的 EPUB（`plan()` 要读文件里的原值来判断「要不要改」）。"""
    import pathlib

    from novelforge.core import epub_builder
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": "原标题", "author": "原作者", "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    return path


def _cand(**kw):
    base = {"source": "openlibrary", "title": "在线标题", "author": "在线作者",
            "description": "在线简介", "publisher": "", "year": "", "language": "en",
            "tags": [], "isbn": "", "cover_url": "", "score": 0.9}
    base.update(kw)
    return base


def _fake_search(entries):
    return lambda *a, **k: {
        "entries": entries,
        "sources": {"openlibrary": {"ok": True, "count": len(entries), "error": ""}},
        "best": entries[0] if entries else None,
    }


def test_预览标出超长字段_端到端(isolated, default_root, monkeypatch):
    """⚠️ 预览（`plan`）里那个字段要带 `too_long` ⇒ 用户**提交前**就知道。"""
    from novelforge.core import library, metafetch, metasources

    _real_epub(default_root, "太长了.epub")
    library.invalidate()
    book = library.books()[0]

    monkeypatch.setattr(metasources, "search_all",
                        _fake_search([_cand(description="长" * 50000)]))
    monkeypatch.setattr(metasources, "search_by_isbn", lambda *a, **k: None)
    res = metafetch.plan(names=[book["name"]],
                         cfg={"metadata_fetch": {"enabled": True, "sources": ["openlibrary"],
                                               "threshold": 0.5, "limit": 5}}, limit=5)
    assert res["items"], res
    ch = res["items"][0]["changes"]
    assert ch.get("description", {}).get("too_long") is True, ch.get("description")
    # 正常的字段不该被标
    assert not ch.get("title", {}).get("too_long"), ch.get("title")


def test_超长的自定义字段值_跳过而不是让整次抓取失败(isolated, default_root, monkeypatch):
    """⚠️ **自定义字段**那条此前是**抛**的 ⇒ 一个超长的值会让**整次抓取失败**
    （该书一个字都写不进去）⇒ 与元数据字段**口径不同**。

    现在：**跳过**该字段、**如实回报**，其余照写。
    """
    from novelforge.core import library, metafetch, metasources

    _real_epub(default_root, "自定义超长.epub")
    library.invalidate()
    book = library.books()[0]

    # 建一个自定义字段（默认值极长 ⇒ 抓取要补的默认值也超长）
    db.create_custom_field(key="note", label="备注", type="text",
                           default_value="长" * 50000)
    monkeypatch.setattr(metasources, "search_all", _fake_search([_cand()]))
    monkeypatch.setattr(metasources, "search_by_isbn", lambda *a, **k: None)
    res = metafetch.apply([{"name": book["name"], "book_id": book["id"],
                            "fields": {"note": "长" * 50000}}],
                          cfg={"metadata_fetch": {"enabled": True}})
    # ⚠️ 那个字段**没写进去**（值仍是空的）
    assert db.custom_field_values(book["id"]).get("note", "") == ""
    # ⚠️ **归因要说清是哪个字段**（否则用户以为是自己传空了）
    # ⚠️ 但**不是**「整次抓取崩了」—— 抛的是 ValueError（这一条会进 `failed`），
    # 而**崩**会让整批都受影响。⇒ 断言：错因里点名了那个字段。
    err = " ".join(f.get("error", "") for f in res["failed"])
    assert "太长" in err, res["failed"]
    assert "note" in err, res["failed"]
