"""删库与扫描的竞态：扫描结果不得写回已被移除的库（第 288 期）。

`DELETE /api/libraries/{lid}` 的顺序是「删登记 → `catalog.forget(lid)`」。若此刻
后台 / 读路径正在扫这个库（NAS 大目录可达分钟级），`forget()` 的 DELETE 跑在扫描
**中间**，扫描随后又把行写回来 ⇒ `book_index` 里留下一条谁都看不见、也再没人清的
行（`api_delete_library` 的注释专门怕这张表只增不减）。修法：`forget()` 先推进
「被移除」代际号，`refresh_library` 收尾时比对 —— 变了就把本轮写入作废。
"""
import threading

from novelforge.core import catalog, db, epub_builder


def _rows(lid: str) -> int:
    return int(catalog._exec(
        f"SELECT COUNT(*) AS n FROM {catalog.TABLE} WHERE library_id=?", (lid,)
    ).fetchone()["n"] or 0)


def test_删库期间完成的扫描不得把索引行写回来(isolated, make_library, tmp_path, monkeypatch):
    root = tmp_path / "L"
    root.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": "书A", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>x</p>"}],
                            str(root / "a.epub"))
    lib = make_library("L", "库", "ebook", root)

    entered = threading.Event()
    release = threading.Event()
    real = catalog._refresh_locked

    def slow_refresh(lib_, force):
        entered.set()
        assert release.wait(10), "测试没放行扫描"
        return real(lib_, force)          # 真正的扫描在「删库之后」才写行

    monkeypatch.setattr(catalog, "_refresh_locked", slow_refresh)

    out: dict = {}
    t = threading.Thread(target=lambda: out.update(catalog.refresh_library(lib, force=True)))
    t.start()
    try:
        assert entered.wait(10), "扫描没开始"
        # 与 `api_delete_library` 同序：删登记 → forget
        db.delete_library("L")
        catalog.forget("L")
        release.set()
    finally:
        release.set()
    t.join(15)
    assert not t.is_alive()

    assert _rows("L") == 0, f"扫描在删库之后仍写回了 {_rows('L')} 行索引"
    assert out.get("skipped") is True, out


def test_用删库前的旧实体扫描也不得写回索引(isolated, make_library, tmp_path):
    """第二条窗口：调用方拿着**删库之前**取得的旧 lib 实体（代际号早已推进过，
    比对不出来）⇒ 收尾必须再问一次库表。"""
    root = tmp_path / "L2"
    root.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": "书B", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>x</p>"}],
                            str(root / "b.epub"))
    stale = make_library("L2", "库", "ebook", root)     # 先拿到实体（快照）
    db.delete_library("L2")                             # 请求线程删库
    catalog.forget("L2")

    out = catalog.refresh_library(stale, force=True)
    assert out.get("skipped") is True, out
    assert _rows("L2") == 0, f"旧实体把已删库的 {_rows('L2')} 行写回了索引"

