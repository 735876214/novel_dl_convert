"""孤儿 `book_id` 的判据与清单（第 265 期从 `server.py` 挪下来）。

「这一行引用了一本**已经不存在的**书」—— 这是纯领域判断（库表 + 书目 + 引用表），
与 HTTP 无关。此前它长在 `server.py` 里，两个端点 + 一个清理动作各自 `from` 它。

⚠️ 判据只有 **:`orphan_refs`** 一份；`orphans()` 只是把结果整理成接口要的形状。
"""
from __future__ import annotations

from . import catalog, db, library


def orphan_refs() -> dict:
    """各表里**真正的**孤儿 book_id：``{表名: [book_id]}``。

    ⚠️ 第 37 期新增的第二道判据：「**书所属的库已经不存在**」的行不算孤儿。
    那之前书库表为空会自动播一条默认库，所以「书目为空」≈「书真没了」；现在没有
    默认库了，用户可以一个库都不建、也可以把库移除登记 —— 那时它的书只是**界面上
    看不见**，文件和进度 / 批注都还在原地。漏掉这道判据，「清空全部书库 → 点清理
    孤儿」就是一次不可恢复的数据大清洗。

    ``book_id`` 形如 ``库$哈希``（见 `library._book_id`）；没有 ``$`` 的是第 17 期
    库维度化之前的旧 id，无法归属到任何库，按老口径处理（不在书目里就算孤儿）。

    ⚠️ **第 119 期第二道护栏**：「**该库当前一本书都没被索引到**」时，它的行一律
    不判孤儿。判据与第一道同源（库还在），但防的是另一件事 —— 库根暂时不可用
    （NAS 未挂载 / 网盘掉线 / Docker 挂载缺失）时书目会暂时为空，此时若照第一道
    判据走，整库的进度 / 批注 / 书签 / 阅读会话**全部**会出现在「可清理」清单里，
    而清理是真 ``DELETE``（不进回收站）—— 用户看到「书架空了」再点一下清理，
    阅读历史就没了。代价：某库最后一本书被删后，它的残余行会留在清单外（清理不掉），
    只能连库一起删 —— 比起「一次点错删光全部历史」，这是刻意选的那一边。
    """
    books = library.books()
    valid = {b["id"] for b in books}
    try:
        lib_ids = {str(l.get("id") or "") for l in library.libraries()}
    except Exception:
        lib_ids = set()
    #: 当前**确实索引到了书**的库（前缀命中的才有资格判孤儿，见 docstring 第二道护栏）
    live_libs = {str(b.get("library_id") or "") for b in books}
    refs = db.book_id_refs()

    def _owner(i) -> str:
        return str(i).split("$", 1)[0]

    return {
        name: [i for i in ids
               if i not in valid and _owner(i) in lib_ids and _owner(i) in live_libs]
        for name, ids in refs.items()
    }

def orphans() -> dict:
    """算出各表中的孤儿 book_id（不改任何数据）。"""
    refs = db.book_id_refs()
    orphans = orphan_refs()
    tables: dict = {}
    total = 0
    for name, ids in refs.items():
        bad = orphans.get(name) or []
        total += len(bad)
        tables[name] = {"books": len(bad), "sample": bad[:10]}
    return {"tables": tables, "total": total,
            # 第 226 期：同「维护概览」—— 一次 COUNT 代替一次全库物化
            # （口径一致：只数当前登记的库）。
            "library_books": catalog.totals([l.get("id") for l in library.libraries()])["books"]}
