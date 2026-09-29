"""跨库移动的**执行层**（`core/migrate.py` 的 `execute` / `rollback` / 台账）。

第 77 期前本文件测的是「按格式自动归库」（``preview`` / ``plan`` / 门禁 / 向导建议）——
那条路已整体移除（见 ``core/migrate.py`` 的模块 docstring），那些用例的**载体**没有了。
但 ``execute`` / ``rollback`` 那台机器还在，且仍在服务一个**会真移文件、真换 book_id**
的破坏性操作，所以沿用老文件同一套口径继续钉住，只是把载体从 ``plan()`` 换成
``move_plan()``：

- **会不会搬错**：与 ``test_book_move.py`` 同源（那里覆盖类型相容闸门 / 副本随迁 /
  预览==落盘）；
- **会不会重复搬**：见 :func:`test_重复执行不重复搬`；
- **一条失败会不会拖垮整批**：见 :func:`test_批量执行_单条失败不影响其余`；
- **台账是否如实**：见 :func:`test_批次台账计数如实` 与
  :func:`test_回滚后批次行标记为已回滚`；
- **错误口径**：见 :func:`test_不存在的批次要报错而不是静默`。

⚠️ 与 ``test_book_move.py`` 的分工：那个文件管「**搬到哪儿对不对**」（跨库移动特有的
口径），本文件管「**一次搬一批、中途出岔子会怎样**」（与 direction 无关的执行层纪律）。
两边的用例都不多，但都不重叠。
"""
import pathlib

import pytest

from novelforge import config
from novelforge.core import db, library, migrate


@pytest.fixture
def two_libs(isolated, default_root, make_book, make_library):  # noqa: ARG001
    """起手库（`default`，铺三本电子书）+ 一个电子书目标库（就地引用来源根下子目录）。"""
    for name in ("三体.epub", "流浪地球.epub", "球状闪电.epub"):
        make_book(default_root, name)
    library.invalidate()

    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    make_library("ebook", "电子书库", "ebook", src / "ebooks", source_subdir="ebooks")
    library.invalidate()
    return {"src": pathlib.Path(default_root), "dst": src / "ebooks"}


def _ids(names) -> list:
    """文件名 → **当前** book_id（搬库会换库前缀，所以每次都要重新取）。"""
    library.invalidate()
    by_name = {b["name"]: b["id"] for b in library.books()}
    return [by_name[n] for n in names]


# ---------------------------------------------------------------------------
# 执行：逐条独立 + 幂等
# ---------------------------------------------------------------------------

def test_批量执行_单条失败不影响其余(two_libs):
    """一条失败必须是「这一条失败」，不是「整批中止」。

    老文件同名用例（走 ``plan()``）保护的就是这条 —— 搬 300 本时因为一本坏书把
    剩下 299 本留在原地，用户看到的是「点了没反应」，比报错更难查。
    """
    batch = migrate.move_plan(_ids(["三体.epub", "流浪地球.epub", "球状闪电.epub"]), "ebook")
    assert batch["created"] == 3

    # 计划落定之后其中一本的源文件消失 —— 只有这一条该失败
    (two_libs["src"] / "流浪地球.epub").unlink()
    library.invalidate()

    res = migrate.execute(batch["batch_id"])
    assert res["ok"] is False
    assert res["moved"] == 2 and res["failed"] == 1, res
    assert any("源文件已不存在" in e["error"] for e in res["errors"])

    # 另两本**确实**到了目标库（不是「一条失败整批回退」）
    assert (two_libs["dst"] / "三体.epub").is_file()
    assert (two_libs["dst"] / "球状闪电.epub").is_file()


def test_重复执行不重复搬(two_libs):
    """manifest 先行的幂等依据：同一批次再点一次，搬过的条目必须 **skipped** 而不是再搬一遍。

    重复搬的后果不是「多一份文件」那么轻 —— 目标已有同名文件，第二条要么覆盖、
    要么冲突失败，两种都不是用户点第二次按钮时想要的结果。
    """
    batch = migrate.move_plan(_ids(["三体.epub", "流浪地球.epub"]), "ebook")
    first = migrate.execute(batch["batch_id"])
    assert first["ok"] is True and first["moved"] == 2

    again = migrate.execute(batch["batch_id"])
    assert again["moved"] == 0
    assert again["skipped"] == 2


# ---------------------------------------------------------------------------
# 台账
# ---------------------------------------------------------------------------

def test_批次台账计数如实(two_libs):
    """台账是回滚的**唯一依据**：计数错了，前端那条「撤销本次移动」就会指错批次或报错数。"""
    batch = migrate.move_plan(_ids(["三体.epub", "流浪地球.epub"]), "ebook")
    migrate.execute(batch["batch_id"])

    rows = [p for p in migrate.pending_batches() if p["batch_id"] == batch["batch_id"]]
    assert len(rows) == 1, "刚执行完的批次必须在台账里"
    assert rows[0]["direction"] == migrate.DIR_BOOKMOVE
    assert rows[0]["done"] == 2 and rows[0]["failed"] == 0 and rows[0]["pending"] == 0


def test_回滚后批次行标记为已回滚(two_libs):
    batch = migrate.move_plan(_ids(["三体.epub"]), "ebook")
    migrate.execute(batch["batch_id"])

    rb = migrate.rollback(batch["batch_id"])
    assert rb["ok"] is True and rb["restored"] == 1

    assert (two_libs["src"] / "三体.epub").is_file(), "正本要回到原处"
    assert not (two_libs["dst"] / "三体.epub").exists(), "目标库不该还留着"
    assert {r["status"] for r in db.migration_batch(batch["batch_id"])} == {"rolled_back"}


# ---------------------------------------------------------------------------
# 错误口径
# ---------------------------------------------------------------------------

def test_不存在的批次要报错而不是静默(two_libs):
    """静默返回「搬了 0 本」会让用户以为「这批已经处理过了」。"""
    with pytest.raises(ValueError):
        migrate.execute("不存在的批次")
    with pytest.raises(ValueError):
        migrate.rollback("不存在的批次")
