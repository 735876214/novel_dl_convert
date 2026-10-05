"""跨库移动的「账目完整度」契约（第 39 期）+ 存量台账回滚（第 77 期收窄）。

第 77 期前本文件是「**自动归库 ↔ 用户发起移动**两条路」的对比契约。自动归库已整体
移除（`core/migrate.py` 的模块 docstring 有理由），那半边用例的**载体**没了
（`plan()` / `preview()` 不复存在），所以删掉，只留两件仍然成立、且**别处没覆盖**的事：

1. :func:`test_用户发起的移动_副本与台账都跟着走` —— 一次跨库移动必须把**副本**搬到
   目标库成品目录，并把 **`scrape_items` 台账**改挂到新 id（连同 `library_id` /
   `source_rel` 这些库相关列）。
2. :func:`test_存量批次回滚不造假台账` —— 第 77 期之前**自动归库**写下的
   ``direction="move"`` 批次行仍可能躺在真库的台账里（历史数据不清理）。那种行回滚时
   对台账必须**空操作**：不许凭空补一行假台账。

## 为什么「台账改挂」这一步不能漏（第 39 期的结论，仍然有效）

`db.remap_book_id`（`db.py:1731`）的 docstring 明写：

    ``scrape_items``（见 :func:`scrape_remap_item`）**刻意不在这里**：它在 book_id
    之外还有 ``library_id`` / ``source_rel`` / ``link_rel`` 三个库相关列要一起改。

`REMAP_TABLES`（`db.py:1633-1637`）也确实不含它 ⇒ 任何换库动作若只 remap 而不搬台账，
那本书的 id 换了库前缀而**台账行还挂在旧 id 上**，于是：

- 新库的 `scrape_list(library_id=新库)` 里看不到它（`library_id` 列还是旧的）；
- 对账（`scrape.verify` / `_lost`）只在**同一库内**做 —— 旧库那边按旧库根找源文件自然
  找不到，会把一行好好的「已出版」判成 ``orphan`` / ``removed``，**把一次正常搬迁变成
  一次误报事故**。

## 本文件的来历（「语义确实变了」的证据）

按「先护栏、后统一」的顺序做的：先写了一条**为当时冻结行为拍的现状快照**（断言副本
原地不动、台账仍挂旧 id），它**是绿的**；统一之后它**转红**；再把断言反写成新语义、
回到绿。那处 diff 就是语义确实变了的证据 —— 比任何说明文字都硬。

## 变异验证（M5）

把 `rollback` 里的 `_after_bookmove_back(...)` 换成 `{"copied": False, "note": ""}`
（等价于「回程不统一」）⇒ :func:`test_存量批次回滚不造假台账` 的牙口（「关联数据没从
新 id 搬回来」那条）转红。它那条「不造假台账」的断言**验不了这个变异** —— 要验它得
把造行能力写进去，见该用例自己的说明。
"""
import json
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
    src = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"])
    pdir = src / "_sorted_ebook"
    pdir.mkdir(parents=True, exist_ok=True)
    lib = make_library("ebook", "电子书库", "ebook", src / "ebooks", source_subdir="ebooks")
    # ⚠️ `make_library` 不接受 `publish_path`，必须补这一步 —— 少了它目标库就没有成品目录，
    # 「副本该不该跟过来」根本无从观察（`copy_plan` 会如实报 `left`）。
    db.update_library("ebook", publish_path=str(pdir))
    library.invalidate()
    return lib, pdir


def test_用户发起的移动_副本与台账都跟着走(published, ebook_target):
    """跨库移动的账目必须**齐**：副本随迁 + 台账改挂。

    第 77 期前这里还有一条结构平行的「自动归库之后……」，用来钉「两条路共用
    ``_after_bookmove``」。自动归库移除后那条路不存在了，但**本条的牙口没变**：
    它断言的是 `execute` 的收尾链（`remap` → `copy_plan`/`_apply_copy` → `scrape_remap_item`）
    确实跑完，而不是「两条路对齐」。谁把这条链拆掉一半，它就红。
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


def test_存量批次回滚不造假台账(published, ebook_target):
    """第 77 期之前**自动归库**写下的 ``status="done"`` 批次，回滚时不能凭空生出台账。

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
    dst_path = pathlib.Path(json.loads(target_lib["source_dirs"])[0]) / "三体.epub"

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
