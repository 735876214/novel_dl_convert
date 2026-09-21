"""自动归库 ↔ 用户发起移动：两条路的「账目完整度」契约（第 39 期）。

`core/migrate.py:301-303` 原文写着自动归库那条路「**行为一字不改**……这是本期**有意**
留下的边界……**要改它得单独一期**」。第 39 期就是那一期。

## 两条路差在哪（读码所得，不是猜）

`execute`（`:955`）原先按 `direction` 分两条：

- ``bookmove``（用户点选的跨库移动，第 36 期）走 `_after_bookmove`（`:795`），
  完整链：`remap` → **副本随书搬**（`copy_plan` / `_apply_copy`）→ **台账改挂**
  （`scrape_remap_item`）→ 通知 watcher。
- ``move``（自动归库）只做 `db.remap_book_id` + `watcher.mark_processed`。

**第 39 期把两者收成一条**：`execute`（`:955`）与 `rollback`（`:1035`）现在都不再看
`direction`，一律走 `_after_bookmove`（`:795`）/ `_after_bookmove_back`（`:886`）。
差别只剩「谁选源集合、谁定目标库」—— **不在账目完整度**。

## 后果：自动归库后台账行**完全脱钩**

`db.remap_book_id`（`db.py:1731`）的 docstring 明写：

    ``scrape_items``（见 :func:`scrape_remap_item`）**刻意不在这里**：它在 book_id
    之外还有 ``library_id`` / ``source_rel`` / ``link_rel`` 三个库相关列要一起改。

`REMAP_TABLES`（`db.py:1633-1637`）也确实不含它 ⇒ 自动归库后，那本书的 id 换了库前缀，
**台账行还挂在旧 id 上**，于是：

- 新库的 `scrape_list(library_id=新库)` 里看不到它（`library_id` 列还是旧的）；
- 而 `_after_bookmove` 的注释第 2 条指出，对账（`scrape.verify` / `_lost`）只在
  **同一库内**做 —— 旧库那边按旧库根找源文件自然找不到，会把一行好好的「已出版」
  判成 ``orphan`` / ``removed``，**把一次正常搬迁变成一次误报事故**。

## 本文件的来历（「语义确实变了」的证据）

按「先护栏、后统一」的顺序做的：先写了一条**为当时冻结行为拍的现状快照**
（断言副本原地不动、台账仍挂旧 id），它**是绿的**；统一之后它**转红**；
再把断言反写成新语义、回到绿。那处 diff 就是语义确实变了的证据 —— 比任何说明文字都硬。

## 变异验证（M5）

把 `rollback` 里的 `_after_bookmove_back(...)` 换成 `{"copied": False, "note": ""}`
（等价于「回程不统一」）⇒ 两条回滚用例**都红**，且分别是
「副本没跟着回来」与「关联数据没从新 id 搬回来」；另两条不碰回滚的用例保持绿。
"""
import pathlib
import shutil

import pytest

from novelforge import config
from novelforge.core import db, epub_builder, library, migrate, scrape

#: `isolated` 建的**起手库** id（`conftest.TEST_LIB_ID`）。里面那本书就是待迁源。
START_LIB = "default"


def _epub(root, name: str, title: str = "书") -> pathlib.Path:
    """真实可解析的 EPUB —— 刮削出版必须真文件（`test_scrape_publish` 同款）。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": "作者", "language": "zh"},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    return path


@pytest.fixture
def published(isolated, default_root, tmp_path):  # noqa: ARG001 —— 依赖 isolated 切目录
    """起手库配了成品目录，且里头有一本**真的刮削出版过**的书。

    必须先真跑一遍刮削：台账行的 ``link_rel`` 只有刮削才写得出来，手写一行等于
    自己编造被测状态，测出来的东西不能说明任何事。
    """
    pdir = tmp_path / "libraries" / "_sorted_start"
    pdir.mkdir(parents=True, exist_ok=True)
    db.update_library(START_LIB, publish_path=str(pdir))
    library.invalidate()

    src = _epub(default_root, "三体.epub", title="三体")
    library.invalidate()
    book = next(b for b in library.books() if b["name"] == "三体.epub")

    assert scrape.enqueue(book)["queued"] is True
    assert scrape.run_once()["processed"] == 1

    row = db.scrape_get(book["id"])
    assert row and row["status"] == "ok", f"刮削没出版成功，用例前提不成立：{row}"
    assert (pdir / row["link_rel"]).is_file(), "副本没落到成品目录，用例前提不成立"

    # 一条**关联数据**（按 book_id 存）：用来观察 ``remap_book_id`` 有没有跑。
    # 只看文件与台账是看不出「回程 remap 漏了」的 —— 那正是最难查的半拉子回滚。
    db.set_progress(book["id"], 42, 0.42)
    return {"pdir": pdir, "src": src, "book": book, "row": row}


@pytest.fixture
def ebook_target(make_library):
    """迁入目标：一个**配了成品目录**的电子书库。

    配成品目录是关键 —— 只有它存在，「副本该不该跟过来」才是一个**可观测**的差别。
    """
    src = pathlib.Path(config.LIBRARY_SOURCE_DIR)
    pdir = src / "_sorted_ebook"
    pdir.mkdir(parents=True, exist_ok=True)
    lib = make_library("ebook", "电子书库", "ebook", src / "ebooks", source_subdir="ebooks")
    # ⚠️ `make_library` 不接受 `publish_path`，必须补这一步 —— 少了它目标库就没有成品目录，
    # 「副本该不该跟过来」根本无从观察（`copy_plan` 会如实报 `left`）。
    db.update_library("ebook", publish_path=str(pdir))
    library.invalidate()
    return lib, pdir


def test_自动归库之后_副本与台账都跟着走(published, ebook_target):
    """自动归库（``direction="move"``）的账目**必须和 bookmove 一样齐**（第 39 期统一）。

    ⚠️ 这条用例的前身是「统一之前的现状快照」：那时它断言副本**原地不动**、台账
    **还挂在旧 id 上**，而且**是绿的**。第 39 期统一之后它转红、随即将断言改成下面这样
    —— 那处 diff 就是「语义确实变了」的证据（比任何说明文字都硬）。
    """
    _target_lib, target_pdir = ebook_target
    old_book, row_before, start_pdir = published["book"], published["row"], published["pdir"]
    copy_before = start_pdir / row_before["link_rel"]
    assert copy_before.is_file()

    res = migrate.execute(migrate.plan()["batch_id"])
    assert res["ok"] is True and res["moved"] == 1
    assert res["copies"] == 1, f"副本没随迁：{res}"
    assert res["copies_left"] == 0

    library.invalidate()
    new_book = next(b for b in library.books() if b["name"] == "三体.epub")
    assert new_book["id"] != old_book["id"], "搬了库 id 却没换前缀 —— 前提不成立"

    # ① 副本：随书搬到**目标库**成品目录，原处不留
    assert not copy_before.exists(), "旧副本应已离开原库"
    assert list(target_pdir.iterdir()), "目标库成品目录里应有副本"

    # ② 台账：改挂到新 id，且三个库相关列一起改对 —— 否则新库看不到它，
    #    而旧库的对账会把一行好好的「已出版」判成 orphan / removed
    row_after = db.scrape_get(new_book["id"])
    assert row_after is not None, "台账没改挂到新 id"
    assert row_after["library_id"] == _target_lib["id"], "台账的 library_id 没跟着换库"
    assert row_after["source_rel"] == "三体.epub"
    assert db.scrape_get(old_book["id"]) is None, "台账在旧 id 上不该还留着"


def test_用户发起的移动_副本与台账都跟着走(published, ebook_target):
    """``bookmove`` 那条路 —— 与上一条**结构完全平行**，这正是本期的契约。

    两条路的实现现在共用 ``_after_bookmove``；这两条用例把「共用」钉在**可观测结果**上：
    谁把两条路拆回两套，就会有一条红。
    """
    target_lib, target_pdir = ebook_target
    old_book, row_before, start_pdir = published["book"], published["row"], published["pdir"]

    batch = migrate.move_plan([str(old_book["id"])], target_lib["id"])
    res = migrate.execute(batch["batch_id"])
    assert res["ok"] is True and res["moved"] == 1
    assert res["copies"] == 1, f"副本没随迁：{res}"

    library.invalidate()
    new_book = next(b for b in library.books() if b["name"] == "三体.epub")

    # ① 副本：随书搬到**目标库**成品目录
    assert not (start_pdir / row_before["link_rel"]).exists(), "旧副本应已离开原库"
    assert list(target_pdir.iterdir()), "目标库成品目录里应有副本"

    # ② 台账：改挂到新 id，且库相关列一起改对
    row_after = db.scrape_get(new_book["id"])
    assert row_after is not None, "台账没改挂到新 id"
    assert row_after["library_id"] == target_lib["id"], "台账的 library_id 没跟着换库"
    assert row_after["source_rel"] == "三体.epub"
    assert db.scrape_get(old_book["id"]) is None, "台账在旧 id 上不该还留着"


def test_自动归库_执行后回滚能把副本与台账一起带回来(published, ebook_target):
    """跑一整圈：自动归库 → 回滚 —— 副本、正本、台账都必须回到出发时的样子。

    去程统一了、回程不统一，就会「搬过去齐了、滚回来又散了」，而那比两边都不齐更难查：
    用户看到的是书回到了原处、进度也在，只有成品目录里那份副本悄悄留在了新库。
    """
    _target_lib, target_pdir = ebook_target
    old_book, row_before, start_pdir = published["book"], published["row"], published["pdir"]
    copy_before = start_pdir / row_before["link_rel"]
    src_path = pathlib.Path(published["src"])

    batch_id = migrate.plan()["batch_id"]
    assert migrate.execute(batch_id)["ok"] is True
    library.invalidate()
    mid_id = next(b for b in library.books() if b["name"] == "三体.epub")["id"]
    assert db.get_progress(mid_id)["locator"] == 42, "前提不成立：去程没搬关联数据"

    res = migrate.rollback(batch_id)
    assert res["ok"] is True and res["restored"] == 1

    # 正本回到原处
    assert src_path.is_file(), "正本没回来"
    # 副本也回到原处，且目标库成品目录不再留着它
    assert copy_before.is_file(), "副本没跟着回来"
    assert list(target_pdir.iterdir()) == [], "副本在新库成品目录里留了一份"

    # 关联数据回到原 id —— 只看文件看不出这一步漏没漏，而漏了就是
    # 「书回到原处却干干净净、读点还都不报错」那个静默断链
    assert db.get_progress(mid_id) is None, "关联数据没从中间 id 搬走"
    assert (db.get_progress(old_book["id"]) or {}).get("locator") == 42, \
        "回滚没把关联数据搬回原 id"

    # 台账回到旧 id，库相关列也跟着回来
    library.invalidate()
    back_book = next(b for b in library.books() if b["name"] == "三体.epub")
    row_back = db.scrape_get(back_book["id"])
    assert row_back is not None, "台账没改挂回原 id"
    assert row_back["library_id"] == START_LIB
    assert row_back["link_rel"] == row_before["link_rel"]
    assert db.scrape_get(mid_id) is None, "台账在中间 id 上不该还留着"


def test_存量批次回滚不造假台账(published, ebook_target):
    """**第 39 期之前**写下的 ``status="done"`` 批次，回滚时不能凭空生出台账。

    存量批次长这样（旧 ``execute`` 留下的）：正本搬走了、关联数据 remap 了，但
    **台账仍挂在旧 id 上**（``remap_book_id`` 刻意不碰 ``scrape_items``）。这种行回滚时，
    ``_after_bookmove_back`` 会去 ``new_id`` 上取台账 —— 取不到。

    取不到时怎么办：``scrape_remap_item`` 的约定是「**没有台账行就什么都不做**」
    （``db.py:3028``），实现上由 ``db.py:3046`` 那道守卫 + 写语句只做 ``UPDATE``
    共同兜住 —— 它**本就不具备造行的能力**。所以这里断言的是**空操作**：
    绝不补出一行假台账（补出来会让一本没刮削过的书显示成「已出版」，或者把 ``link_rel``
    写成一个根本不存在的副本路径）。

    ⚠️ 也因此，这条用例的**牙口在另外三条断言上**（正本回来、关联数据跟着回来、
    旧行一字不改）—— 「不造假台账」那一条是防将来有人把 ``UPDATE`` 改写成
    ``INSERT ... ON CONFLICT`` 的，靠变异验证证明不了（要把造行能力写进去才验得了）。
    """
    target_lib, _target_pdir = ebook_target
    old_book, row_before, start_pdir = published["book"], published["row"], published["pdir"]
    src_path = pathlib.Path(published["src"])
    dst_path = pathlib.Path(target_lib["root_path"]) / "三体.epub"

    # —— 手工复刻旧版 execute 的终态（不调 execute，因为它现在已经是新语义）
    batch_id = "auto-legacy-fixture"
    db.migration_add(batch_id, "move", target_lib["id"], str(src_path), str(dst_path))
    library.invalidate()
    new_id = library.book_id("三体.epub", target_lib["id"])
    db.remap_book_id(old_book["id"], new_id)
    shutil.move(str(src_path), str(dst_path))
    row_id = db.migration_batch(batch_id)[0]["id"]
    db.migration_mark(row_id, "done")

    # 前提核对：旧语义留下的正是「台账还在旧 id 上」这个状态
    assert db.scrape_get(new_id) is None, "前提不成立：新 id 上不该有台账行"
    assert db.scrape_get(old_book["id"]) is not None

    res = migrate.rollback(batch_id)
    assert res["ok"] is True and res["restored"] == 1

    assert src_path.is_file(), "正本没搬回去"
    # ★ 空操作：新 id 上**没有**被补出一行假台账
    assert db.scrape_get(new_id) is None, \
        "回滚凭空造了一行台账 —— 这就是「写伪造数据」"
    # 旧行原样留着：它仍如实描述着原库那份副本，谁也没资格替用户删或改
    row_after = db.scrape_get(old_book["id"])
    assert row_after["library_id"] == START_LIB
    assert row_after["link_rel"] == row_before["link_rel"]
    assert (start_pdir / row_before["link_rel"]).is_file(), "副本本就没动过，应还在原处"

    # 台账是空操作，但**关联数据不是** —— ``remap_book_id`` 必须照样跑回程。
    # 存量批次最容易漏的就是这一半：台账没事（因为它从没动过），于是「回滚成功」的
    # 表象之下，读点 / 批注留在了废 id 上。
    assert db.get_progress(new_id) is None, "关联数据没从新 id 搬回来"
    assert (db.get_progress(old_book["id"]) or {}).get("locator") == 42, \
        "存量批次回滚把关联数据落下了"
