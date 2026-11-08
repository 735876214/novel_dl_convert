"""覆盖写入的批量事务（第 171 期）：`db.set_overrides` + `pathmeta.apply`。

**为什么值得钉**：「工具 → 从文件名提取元数据」的典型用法是**整库**套一个规则。
逐行 `db.set_override` 时每行一次 `commit()`（实测 **2.26 ms/行**，fsync 主导；
PG 还要加网络），2,000 本 × 2 字段 ≈ **9.5 s**，已顶到前端 15 s 请求超时 ——
与第 170 期批量动作同一类缺陷。改成「算齐 → 一条事务」后，提交次数与书本数无关。

这里钉三件事：

1. **批量与单本的语义逐字一致**：空值 = 撤覆盖（删行）、`orig` 只在新建行时写；
2. `apply` 的返回形状不变（count / items / errors）；
3. **结构性判据**：N 本书只提交常数次 —— 退回逐行 `commit()` 时立刻红。
"""
from __future__ import annotations

import pathlib
import threading

from novelforge.core import db, pathmeta

RULE = r"^\[(?P<author>[^\]]+)\]\s*(?P<title>.+?)$"


def _counting(monkeypatch):
    """把 `db._connect` 换成数提交次数的代理 —— **只数本线程的提交**。

    ⚠️ 第 278 期：此前数的是**全局**提交数。`apply` 是**同步调用**（跑在测试线程里），
    而全量跑时别的线程（扫描 / 追更 / 监听 / 事件）可能同一时刻也在提交 ——
    于是这条「常数次提交」的断言被**无关写入**污染、**假红**（实测：全量跑数到 6 次，
    单独跑是 3 次，而产品代码一个字没改）。

    判据的本意是「**这一次调用**提交了几次」，所以按线程过滤：只有测试线程
    自己的 commit 计数。这样它仍然对「退回逐行 commit」（同一线程 20+ 次）足够灵敏。

    ⚠️ **同一条判据在 `test_batch_bulk_170.py::_counting_connect` 里第 246 期就修过**
    （那边写着同样的理由），这份是**漏掉的第二个副本** —— 两处现在一致。
    """
    real = db._connect
    owner = threading.get_ident()

    class Counting:
        def __init__(self, inner):
            self._inner = inner
            self.commits = 0

        def commit(self):
            if threading.get_ident() == owner:
                self.commits += 1
            return self._inner.commit()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    shared = Counting(real())
    monkeypatch.setattr(db, "_connect", lambda: shared)
    return shared


def test_批量覆盖与单本语义一致(isolated):  # noqa: ARG001
    db.set_override("b$1", "author", "甲", orig="旧甲")
    db.set_override("b$1", "title", "书名", orig="旧书名")
    # 批量的三行：新值 / 已存在行改值（orig 不该被覆盖）/ 空值删行
    assert db.set_overrides([
        ("b$2", "author", " 乙 ", "旧乙"),      # 空白要 strip
        ("b$1", "author", "丙", "再旧"),        # 已存在行：orig 保持「旧甲」
        ("b$1", "title", "  ", "x"),            # 空值 = 撤覆盖
    ]) == 3

    assert db.get_overrides("b$2") == {"author": "乙"}
    assert db.get_overrides("b$1") == {"author": "丙"}
    row = db.get_override_row("b$1", "author")
    assert row is not None and row["orig"] == "旧甲", "已有行的 orig 不许被批量覆盖改掉"


def test_apply_整库只提交常数次(client, auth_headers, make_library, make_epub,
                              tmp_path, monkeypatch):
    root = tmp_path / "bulk-lib"
    make_library("bulk-lib", "批量库", "ebook", root)
    for i in range(20):
        make_epub(root, f"[作者{i % 3}] 书{i}.epub")
    assert client.post("/api/libraries/bulk-lib/scan", headers=auth_headers).status_code == 200

    c = _counting(monkeypatch)
    try:
        out = pathmeta.apply(RULE, "stem", "bulk-lib")
    finally:
        monkeypatch.undo()

    assert out["count"] == 20, out
    assert out["errors"] == []
    # 常数级：覆盖写入 1 次 + 活动日志 / 目录失效等固定几次（实测 3）。
    # 逐行 commit 时这里是 20+，所以这条对「退回旧写法」足够灵敏。
    assert c.commits <= 4, f"20 本书提交了 {c.commits} 次 —— 又退回逐行 commit 了"

    # 值真的落库了（不是只数提交）
    bid = out["items"][0]["book_id"]
    assert db.get_overrides(bid).get("author", "").startswith("作者")


def test_apply_返回形状不变(client, auth_headers, make_library, make_epub, tmp_path):
    root = tmp_path / "shape-lib"
    make_library("shape-lib", "形状库", "ebook", root)
    make_epub(root, "[甲] 一本.epub")
    make_epub(root, "不匹配.epub")
    assert client.post("/api/libraries/shape-lib/scan", headers=auth_headers).status_code == 200

    out = pathmeta.apply(RULE, "stem", "shape-lib")
    assert set(out) >= {"count", "items", "errors"}
    assert out["count"] == 1 and out["items"][0]["fields"] == ["author", "title"]
