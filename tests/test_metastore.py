"""元数据分层：override（用户编辑）> online（在线抓取）> opf（文件原值）。

这是第 8 期「在线优先、本地兜底、可编辑」的落地口径。层级顺序错一格，
用户体验就是「我刚改的值被下一次抓取冲掉了」，而且很难复现 —— 所以逐层钉死。

本文件用**构造的书目字典**而不是真实 EPUB：分层逻辑只读书目字段 + DB，
不需要真文件；这样用例既快又不依赖 zip 解析。
"""
from novelforge.core import db, metastore

#: 一本「OPF 里什么都有」的书（`date` 在书目里叫 `year`，见 metastore._opf_value）
BOOK = {
    "id": "b1",
    "title": "本地标题",
    "author": "本地作者",
    "series": "本地系列",
    "series_index": "1",
    "year": "1999",
    "publisher": "本地出版社",
    "language": "zh",
    "description": "本地简介",
    "tags": ["本地标签"],
    "isbn": "9780000000000",
}


# ---------------------------------------------------------------------------
# 分层优先级
# ---------------------------------------------------------------------------

def test_无覆盖无在线时取文件原值(isolated):  # noqa: ARG001
    eff = metastore.effective(BOOK)
    assert eff["title"] == "本地标题"
    assert eff["publisher"] == "本地出版社"
    assert eff["date"] == "1999"          # date ↔ year 的映射
    assert eff["tags"] == ["本地标签"]


def test_在线值优先于文件原值(isolated):  # noqa: ARG001
    db.set_online("b1", {"title": ("在线标题", "openlibrary")})
    assert metastore.effective(BOOK)["title"] == "在线标题"


def test_用户覆盖优先于在线值(isolated):  # noqa: ARG001
    db.set_online("b1", {"title": ("在线标题", "openlibrary")})
    db.set_override("b1", "title", "用户标题", orig="本地标题")

    assert metastore.effective(BOOK)["title"] == "用户标题"
    assert metastore.state(BOOK)["title"] == {
        "value": "用户标题", "online": "在线标题", "opf": "本地标题", "overridden": True,
    }


def test_撤销覆盖后回落到在线值(isolated):  # noqa: ARG001
    db.set_online("b1", {"title": ("在线标题", "openlibrary")})
    db.set_override("b1", "title", "用户标题")
    db.set_override("b1", "title", "")          # 空值 = 撤销覆盖（删行）

    assert metastore.effective(BOOK)["title"] == "在线标题"
    assert metastore.state(BOOK)["title"]["overridden"] is False


def test_纯空白覆盖视同撤销(isolated):  # noqa: ARG001
    db.set_override("b1", "publisher", "   ")
    st = metastore.state(BOOK)["publisher"]
    assert st["overridden"] is False
    assert st["value"] == "本地出版社"


# ---------------------------------------------------------------------------
# 逐字段独立与明细
# ---------------------------------------------------------------------------

def test_逐字段覆盖互不影响(isolated):  # noqa: ARG001
    db.set_override("b1", "title", "只改标题")
    st = metastore.state(BOOK)
    assert st["title"]["overridden"] is True
    assert st["publisher"]["overridden"] is False
    assert st["publisher"]["value"] == "本地出版社"


def test_state同时给出在线建议值(isolated):  # noqa: ARG001
    """编辑器要同时显示「当前值」和「在线建议」，一次往返给全。"""
    db.set_online("b1", {"publisher": ("在线出版社", "googlebooks")})
    st = metastore.state(BOOK)["publisher"]
    assert st == {"value": "在线出版社", "online": "在线出版社",
                  "opf": "本地出版社", "overridden": False}


def test_没有在线值时online为空串(isolated):  # noqa: ARG001
    assert metastore.state(BOOK)["description"]["online"] == ""


# ---------------------------------------------------------------------------
# 边界：缺 id / 空库
# ---------------------------------------------------------------------------

def test_缺id的书不抛且取原值(isolated):  # noqa: ARG001
    # 边界：DB 里查不到就退回 OPF 原值，绝不因为缺 id 把详情页打崩
    assert metastore.effective({})["title"] == ""
    assert metastore.state({"id": "", "title": "有标题"})["title"]["value"] == "有标题"


def test_覆盖查询按书隔离(isolated):  # noqa: ARG001
    db.set_override("b1", "title", "只属于 b1")
    other = dict(BOOK, id="b2")
    assert metastore.state(other)["title"]["overridden"] is False
    assert metastore.effective(other)["title"] == "本地标题"


# ---------------------------------------------------------------------------
# orig（首次覆盖前的原值）：无在线值时靠它还原
# ---------------------------------------------------------------------------

def test_orig记录首次覆盖前的原值(isolated):  # noqa: ARG001
    assert db.get_override_row("b1", "title") is None
    db.set_override("b1", "title", "用户标题", orig="本地标题")
    assert db.get_override_row("b1", "title")["orig"] == "本地标题"


def test_二次覆盖不覆盖orig(isolated):  # noqa: ARG001
    """`orig` 代表「用户动手之前长什么样」，后续编辑不能把它改掉。"""
    db.set_override("b1", "title", "用户标题 v1", orig="本地标题")
    db.set_override("b1", "title", "用户标题 v2", orig="另一个值")
    row = db.get_override_row("b1", "title")
    assert row["value"] == "用户标题 v2"
    assert row["orig"] == "本地标题"
