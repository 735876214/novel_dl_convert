"""第 63 期（6/6）：批注的**位置锚**与**幂等导入**。

钉住四件事，每一件都对应一种「不报错但结果不对」的失效：

1. **老库补列**：三列补上、存量行回落 `''/-1/-1`、照旧可读。回落值是「不知道」，
   界面要能据此如实说「按文本定位」—— 回填一个猜的偏移才是错的。
2. **偏移真能往返**：接口写进去、列表读回来一致。漏改某一处 SELECT 的列清单，
   表现就是「锚丢了」，而高亮**仍然画得出来**（退回文本搜索），没人会发现。
3. **导入幂等**：同一批数据反复上传必须收敛成同一份。设备每次都传全量，
   所以「第二次同步多出一份副本」是必然会发生的事，不是边界情况。
4. **导入不得让删掉的批注复活**：用户在本项目里删了、设备端并不知道，
   再导一次就回来了 —— 比第一次没导入更恼人。

另有一条**设计决定的回归锁**：`annotations` 上**没有**唯一索引（见文件最后一条用例）。
"""
import pathlib
import time

from novelforge.core import db, library


def _bid(root, name: str = "anchor-book.epub") -> str:
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"EPUB")
    library.invalidate()
    books = [b for b in library.books() if b["name"].endswith(name)]
    assert books, "扫描没找到 %s" % name
    return books[0]["id"]


def _item(anchor: str, quote: str = "quote", **kw) -> dict:
    return {"anchor": anchor, "quote": quote, **kw}


# ---------------------------------------------------------------------------
# 1. 迁移：老库补列，存量行回落「不知道」
# ---------------------------------------------------------------------------

def test_legacy_db_gets_anchor_columns_with_unknown_defaults(isolated):
    """造一张第 44 期形状的表，触发迁移，检查三个新列与它们的回落值。

    ⚠️ 回落必须是 `''/-1/-1` 而不是某个「看起来合理」的值：老批注当时**根本没记**
    偏移，补不回来。回填 0 会让它们全部指到章首 —— 高亮会画错地方，而且不报错。
    """
    c = db._connect()
    c.execute("DROP TABLE annotations")
    c.execute(
        """CREATE TABLE annotations (
            id         INTEGER PRIMARY KEY,
            book_id    TEXT NOT NULL,
            chapter    INTEGER NOT NULL,
            quote      TEXT NOT NULL,
            color      TEXT NOT NULL DEFAULT 'yellow',
            style      TEXT NOT NULL DEFAULT 'highlight',
            note       TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            origin     TEXT NOT NULL DEFAULT 'web',
            deleted_at REAL NOT NULL DEFAULT 0
        )"""
    )
    c.execute(
        "INSERT INTO annotations(book_id, chapter, quote, color, style, note, created_at, origin) "
        "VALUES('lib$legacy6', 0, '老批注', 'green', 'underline', '老笔记', ?, 'web')",
        (time.time(),),
    )
    c.commit()
    db.close()
    db.init()  # 触发轻量迁移

    cols = {r["name"] for r in db._connect().execute("PRAGMA table_info(annotations)")}
    assert {"anchor", "start_off", "end_off"} <= cols

    items = db.list_annotations("lib$legacy6")
    assert len(items) == 1, "存量行必须照旧可见"
    a = items[0]
    assert a["quote"] == "老批注" and a["note"] == "老笔记" and a["style"] == "underline"
    assert a["anchor"] == "" and a["start_off"] == -1 and a["end_off"] == -1, \
        "老批注的锚必须回落成「不知道」，不许回填一个猜的偏移"


# ---------------------------------------------------------------------------
# 2. 往返：写进去的偏移要能原样读回来
# ---------------------------------------------------------------------------

def test_offsets_roundtrip_through_the_api(client, auth_headers, default_root):
    bid = _bid(default_root)

    r = client.post(f"/api/books/{bid}/annotations", headers=auth_headers, json={
        "chapter": 2, "quote": "第二次出现的那句话", "color": "yellow",
        "start_off": 120, "end_off": 130,
    })
    assert r.status_code == 200, r.text

    # 不传锚的老客户端照旧可用：回落 -1，不是 0
    r2 = client.post(f"/api/books/{bid}/annotations", headers=auth_headers, json={
        "chapter": 0, "quote": "没带锚", "color": "yellow",
    })
    assert r2.status_code == 200, r2.text

    items = {a["quote"]: a for a in
             client.get(f"/api/books/{bid}/annotations", headers=auth_headers).json()["items"]}
    assert (items["第二次出现的那句话"]["start_off"],
            items["第二次出现的那句话"]["end_off"]) == (120, 130)
    assert items["没带锚"]["start_off"] == -1 and items["没带锚"]["end_off"] == -1

    # 总览端点（另一处 SELECT，列清单手抄过）也要带上锚 —— 漏一处就等于那条路径没锚
    all_items = client.get("/api/annotations", headers=auth_headers).json()["items"]
    hit = [a for a in all_items if a["quote"] == "第二次出现的那句话"]
    assert hit and hit[0]["start_off"] == 120, "总览端点的列清单漏了锚列"

    # 前端 `AllAnnotation extends Annotation`（那一份列清单也手抄过），所以总览这一路
    # 必须**每一列都在**。这里挑 `chapter_title`：值是空串，但**键必须在** ——
    # 少一列的话前端拿到的是 `undefined`，`chapterLabel()` 会当成「没有标题」静默返回空，
    # 界面上表现为「设备批注不显示章节」，不报错、也不空成括号，只是少一段。
    assert "chapter_title" in hit[0], "总览端点的列清单漏了 chapter_title"
    assert "anchor" in hit[0] and "end_off" in hit[0]


def test_find_by_anchor_treats_blank_anchor_as_no_identity(isolated):
    """空锚一律返回 None。

    拿空锚去重会把「两条都没有锚的批注」判成同一条 —— 于是第二条**永远导不进来**，
    且每次都报「已存在」，看起来像是去重生效了。
    """
    db.add_annotation("lib$a", 0, "第一条", "yellow", "")
    assert db.find_annotation_by_anchor("lib$a", "koreader", "") is None
    assert db.find_annotation_by_anchor("lib$a", "koreader", "   ") is None


def test_find_by_anchor_sees_tombstones(isolated):
    """墓碑也要查得到 —— 调用方靠它决定「跳过」，查不到就会复活那条批注。"""
    db.add_annotation("lib$a", 0, "会被删掉的", "yellow", "")
    aid = db.add_annotation("lib$a", 0, "会被删掉的", "yellow", "", anchor="/body/p[1]")
    db.delete_annotation("lib$a", aid)

    row = db.find_annotation_by_anchor("lib$a", "web", "/body/p[1]")
    assert row is not None, "墓碑没查到 ⇒ 导入会把用户删掉的批注复活"
    assert row["deleted_at"] > 0 and row["id"] == aid


# ---------------------------------------------------------------------------
# 3. 导入幂等（以及每个计数各自代表什么）
# ---------------------------------------------------------------------------

def test_reimporting_the_same_batch_converges(isolated):
    """设备每次同步都传全量，所以「第二次会怎样」是主路径，不是边界。"""
    bid = "lib$imp"
    batch = [_item("/body/p[1]", "第一段", note="笔记一", chapter=0),
             _item("/body/p[2]", "第二段", chapter=1)]

    first = db.import_annotations(bid, "koreader", batch)
    assert first["added"] == 2, first
    assert len(db.list_annotations(bid)) == 2

    # 原样再导两次 —— 行数**必须不变**，且计数如实说「一条都没动」
    for _ in range(2):
        again = db.import_annotations(bid, "koreader", batch)
        assert again == {"added": 0, "updated": 0, "unchanged": 2, "trashed": 0,
                         "no_anchor": 0, "no_quote": 0}, again
        assert len(db.list_annotations(bid)) == 2, "重复导入多出了副本"


def test_device_edit_updates_content_but_keeps_device_timestamp(isolated):
    """内容变了就更新，但 `created_at` 保留**设备**的时间。

    改成导入时刻会让「按月份」分组与历史时间线全部错位 —— 而时间戳本身
    （「这条高亮是什么时候划的」）是设备的事实，导入方无权改写。
    """
    bid = "lib$imp2"
    made_at = time.time() - 86400 * 30          # 一个月前划的
    db.import_annotations(bid, "koreader", [
        _item("/body/p[9]", "原引文", note="旧笔记", created_at=made_at)])

    out = db.import_annotations(bid, "koreader", [
        _item("/body/p[9]", "原引文", note="设备上改过的笔记", created_at=made_at)])
    assert out == {"added": 0, "updated": 1, "unchanged": 0, "trashed": 0,
                   "no_anchor": 0, "no_quote": 0}, out

    rows = db.list_annotations(bid)
    assert len(rows) == 1
    assert rows[0]["note"] == "设备上改过的笔记"
    assert rows[0]["created_at"] == made_at, "创建时间被导入时刻覆盖了"


def test_items_without_anchor_are_not_imported(isolated):
    """空锚条目**不收**：收进来等于每次同步都多一份副本，而且每次都不报错。"""
    bid = "lib$imp3"
    out = db.import_annotations(bid, "koreader", [
        {"quote": "没有锚", "chapter": 0},
        _item("", "锚是空串"),
        _item("/body/p[1]", quote=""),          # 有锚但没有引文
        _item("/body/p[2]", "这条是好的"),
    ])
    assert out["no_anchor"] == 2 and out["no_quote"] == 1 and out["added"] == 1, out
    assert [a["quote"] for a in db.list_annotations(bid)] == ["这条是好的"]


def test_counts_sum_to_the_number_of_items(isolated):
    """六个计数相加必须等于送进来的条数。

    这是「静默丢失」的通用哨兵：任何一条走了没被记数号的分支，这个等式就会破 ——
    而单看任何一个计数都发现不了。
    """
    bid = "lib$imp4"
    db.import_annotations(bid, "koreader", [_item("/body/p[1]", "先占位")])
    db.delete_annotation(bid, db.list_annotations(bid)[0]["id"])

    batch = [
        _item("/body/p[1]", "先占位"),          # 命中墓碑
        _item("/body/p[1]", "先占位"),          # 同锚：上面那条已判墓碑，这条也是
        _item("/body/p[2]", "新的"),
        {"quote": "没锚"},
    ]
    out = db.import_annotations(bid, "koreader", batch)
    assert out["trashed"] == 2, out             # 顺手钉住「同锚的第二条也走墓碑分支」
    assert sum(out.values()) == len(batch), out


# ---------------------------------------------------------------------------
# 4. 用户删掉的批注不得被导入复活
# ---------------------------------------------------------------------------

def test_import_does_not_resurrect_a_trashed_annotation(isolated):
    """用户在本项目里删了这条，设备端并不知道 —— 再导一次不许把它弄回来。

    这是「幂等」之外的另一条性质：**删是一条比同步更强的意图**。
    少了它，用户会发现「删了又回来」，而唯一的解释是我方偷偷把它复活了。
    """
    bid = "lib$imp5"
    db.import_annotations(bid, "koreader", [_item("/body/p[3]", "会被删的")])
    aid = db.list_annotations(bid)[0]["id"]
    db.delete_annotation(bid, aid)

    out = db.import_annotations(bid, "koreader", [_item("/body/p[3]", "会被删的")])
    assert out["trashed"] == 1 and out["added"] == 0, out
    assert db.list_annotations(bid) == [], "被删的批注被导入复活了"
    assert len(db.trashed_annotations(bid)) == 1, "不该多出一条副本"


def test_same_anchor_from_different_origins_coexist(isolated):
    """身份是 `(book_id, origin, anchor)` 三元组。

    只看 anchor 的话，KOReader 的 XPointer 与别的来源撞上同一个字符串就会互相顶掉。
    """
    bid = "lib$imp6"
    db.import_annotations(bid, "koreader", [_item("/body/p[1]", "来自 KOReader")])
    db.import_annotations(bid, "kobo", [_item("/body/p[1]", "来自 Kobo")])
    assert {a["quote"] for a in db.list_annotations(bid)} == {"来自 KOReader", "来自 Kobo"}


# ---------------------------------------------------------------------------
# 5. 设计决定的回归锁：annotations 上**没有**唯一索引
# ---------------------------------------------------------------------------

def test_anchored_annotations_survive_a_book_id_remap(isolated):
    """**这一条锁的是一个决定，不是一个行为**（见 `db` 里建表处那段注释）。

    看起来 `(book_id, origin, anchor)` 很该建唯一索引（导入去重要用）。真建了就会
    精确复刻 bookmarks 那个坑：`remap_book_id` 的「目标已有数据」探测**带着
    `deleted_at=0`**（`REMAP_PROBE_FILTER`）所以看不见墓碑 —— 整体 UPDATE 撞唯一约束
    → 异常被外层 `except` 吞成「搬了 0 行」→ **整本书的批注静默丢失**。

    所以这里造出那个会撞的场景：旧书有带锚的活跃批注，目标 id 上**有同锚的墓碑**，
    搬迁必须把旧书那几条**全部**搬过去（墓碑与活跃共存都行，就是不能丢活跃的）。
    """
    old, new = "lib$anchold", "lib$anchnew"
    db.import_annotations(old, "koreader", [
        _item("/body/p[1]", "旧书的活跃批注"),
        _item("/body/p[2]", "旧书的另一条"),
    ])
    # 目标书上：同锚的墓碑（用户在新 id 上删过同名位置的那条）
    db.import_annotations(new, "koreader", [_item("/body/p[1]", "新书上的旧副本")])
    db.delete_annotation(new, db.list_annotations(new)[0]["id"])

    moved = db.remap_book_id(old, new)

    live = {a["quote"] for a in db.list_annotations(new)}
    assert live == {"旧书的活跃批注", "旧书的另一条"}, \
        f"带锚的批注在搬迁中被静默丢弃了（moved={moved}）"
    assert db.list_annotations(old) == [], "旧 id 下还留着没搬走的批注"
