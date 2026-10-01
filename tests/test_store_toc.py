"""第 85 期：书城目录来源的落库与还原（`core/db.py` 的 `store_toc` / `toc_map`）。

这是批次 B（官方书城目录）的底座：**只存目录**（标题 + 顺序 + 映射），不存正文。
四处容易静默出错的地方各钉一条：

1. **负结果必须落库** —— 否则每打开一次详情页就重新外呼一次，白挨风控；
2. **同源只留一行** —— 不是追加：界面读的是「当前这份目录」，历史没有意义；
3. **映射整批替换** —— 半新半旧会让覆盖层按两份不同的对齐结果渲染同一本书；
4. **「还原为本地目录」两表一起清** —— 留下孤立映射，覆盖层会继续按一份已经不存在的
   书城目录去改标题。
"""
import pytest

from novelforge.core import db


@pytest.fixture
def store(isolated):        # noqa: ARG001 —— 依赖 isolated 切目录
    db.init()
    return db


def test_往返保留目录与层级(store):
    store.store_toc_save("b1", "qidian", ok=True, store_ref="12345",
                         matched_title="三体", matched_author="刘慈欣", confidence=0.93,
                         entries=[{"title": "楔子", "depth": None},
                                  {"title": "第一卷", "depth": 1},
                                  {"title": "第一章", "depth": 2}])
    row = store.store_toc_get("b1", "qidian")[0]
    assert row["ok"] is True and row["manual"] is False
    assert row["confidence"] == pytest.approx(0.93)
    assert row["matched_title"] == "三体"
    assert [e["title"] for e in row["entries"]] == ["楔子", "第一卷", "第一章"]
    assert row["entries"][2]["depth"] == 2          # 层级要留着：覆盖层靠它分卷


def test_负结果也要落库(store):
    store.store_toc_save("b1", "fanqie", ok=False, note="没匹配到这本（最高置信度 0.21）")
    row = store.store_toc_get("b1")[0]
    assert row["ok"] is False
    assert "置信度" in row["note"]
    assert row["entries"] == []


def test_同源重取只留一行(store):
    store.store_toc_save("b1", "qidian", ok=True, entries=[{"title": "第一章"}])
    store.store_toc_save("b1", "qidian", ok=True,
                         entries=[{"title": "楔子"}, {"title": "第一章"}])
    rows = store.store_toc_get("b1", "qidian")
    assert len(rows) == 1
    assert [e["title"] for e in rows[0]["entries"]] == ["楔子", "第一章"]


def test_手动指定视为确定(store):
    store.store_toc_save("b1", "qidian", ok=True, manual=True, store_ref="https://x/1")
    row = store.store_toc_get("b1", "qidian")[0]
    assert row["manual"] is True


def test_映射整批替换(store):
    store.toc_map_replace("b1", "qidian", [(0, 0), (1, 2), (2, 3)])
    assert store.toc_map_get("b1", "qidian") == {0: 0, 1: 2, 2: 3}
    store.toc_map_replace("b1", "qidian", [(0, 0)])
    assert store.toc_map_get("b1", "qidian") == {0: 0}, "旧映射不许留下"


def test_多来源互不干扰(store):
    store.store_toc_save("b1", "qidian", ok=True, entries=[{"title": "甲"}])
    store.store_toc_save("b1", "fanqie", ok=True, entries=[{"title": "乙"}])
    store.toc_map_replace("b1", "qidian", [(0, 7)])
    store.toc_map_replace("b1", "fanqie", [(0, 9)])
    assert [r["source"] for r in store.store_toc_get("b1")] == ["fanqie", "qidian"]
    assert store.toc_map_get("b1", "qidian") == {0: 7}
    assert store.toc_map_get("b1", "fanqie") == {0: 9}
    assert set(store.toc_map_get("b1")) == {"qidian", "fanqie"}


def test_还原为本地目录把两表一起清(store):
    store.store_toc_save("b1", "qidian", ok=True, entries=[{"title": "第一章"}])
    store.toc_map_replace("b1", "qidian", [(0, 0)])
    assert store.store_toc_clear("b1") == 1
    assert store.store_toc_get("b1") == []
    assert store.toc_map_get("b1") == {}


def test_两张表按纪律登记():
    """含 `book_id` 的表必须登记：可清理（删书）+ 搬迁清单。

    `tests/test_remap_tables.py` 只保证「出现在 REMAP_TABLES / EXPLICIT / DERIVED 三者之一」，
    这里补上「确实进了孤儿清理」这一半，并把「刻意不搬」的选择钉住
    （理由写在 `db.REMAP_DERIVED_TABLES` 上方：主键含来源与书城序号，整表 UPDATE 撞主键
    会被外层 except 吞成「搬 0 行」，而重建成本只是再取一次目录）。
    """
    assert {"store_toc", "toc_map"} <= set(db.ORPHAN_TABLES)
    assert {"store_toc", "toc_map"} <= set(db.REMAP_DERIVED_TABLES)
