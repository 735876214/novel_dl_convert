"""第 86 期：删库要**把该库的全部残留状态清干净**（索引行 + 口径标记）。

背景（用户报的缺陷）：对同一个文件夹「先删库、再把同一文件夹加回来」，
重建后的库读不到内容。定位到的一处脏数据是：库 id 由**库名**派生
（`server._new_library_id`），所以「同名重建」会**复用同一个 id** —— 而 `catalog.forget`
过去只清 `book_index` 行与内存标记，**没清 `app_state['book_index_rule:{lid}']`**，
新库于是一上来就带着旧库的口径版本，被 `_rule_stale` 判为「已是最新」而不做全量重扫。
"""
from novelforge.core import catalog, db


def test_forget也清口径标记(isolated):                                   # noqa: ARG001
    """**这一条是本次修复的核心**：同名重建复用 id 时，旧口径标记不许留下来。"""
    db.state_set(catalog._rule_key("lib-x"), "旧口径")
    assert db.state_get(catalog._rule_key("lib-x"), "") == "旧口径"
    catalog.forget("lib-x")
    assert db.state_get(catalog._rule_key("lib-x"), "") == "", \
        "删库必须把口径标记一起清掉，否则同名重建的库会按旧口径跳过全量重扫"


def test_forget空id是安全的(isolated):                                   # noqa: ARG001
    catalog.forget("")          # 不该抛
    catalog.forget(None)
