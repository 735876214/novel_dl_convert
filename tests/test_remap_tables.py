"""第 36 期：搬迁清单必须覆盖**所有**含 book_id 的表（否则换库 / 改名即静默断链）。

`library.book_id` 由 basename 派生（``库$哈希``），所以**换库**（库前缀变）与
**改名 / 加卷号**（basename 变）都会换 id。凡是按 book_id 存的行，不跟着搬就变成
「读点按新 id 查不到」—— 而读点全都**不报错**，只是回落成抓取值或文件原值：
用户的编辑、封面、出版物台账就这么无声消失（不抛异常、不回滚、日志也无痕）。

本期之前漏的是四张表：``meta_override`` / ``meta_online`` / ``meta_cover`` /
``scrape_items``。第一条用例就是钉死这件事的**契约测试** —— 将来再加含 book_id 的表时
忘了登记，它会直接红。
"""
import pytest

from novelforge.core import db

def _tables_with_book_id() -> set:
    """当前库里**真的**含 book_id 列的表（取自 sqlite_master，不写死清单）。

    ⚠️ 断言的是「代码声明的清单」与「库的实际形状」一致，所以必须问库本身，
    不能拿常量互相对 —— 那样只是把常量抄了两遍。
    """
    c = db._connect()
    names = [r["name"] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    out = set()
    for n in names:
        if n.startswith("sqlite_"):
            continue
        cols = {r["name"] for r in c.execute(f"PRAGMA table_info({n})").fetchall()}
        if "book_id" in cols:
            out.add(n)
    return out


# ---------------------------------------------------------------------------
# 契约：清单完整（漏一张就断一条链）
# ---------------------------------------------------------------------------

def test_搬迁清单覆盖所有含book_id的表(isolated):  # noqa: ARG001
    covered = set(db.REMAP_TABLES) | set(db.REMAP_EXPLICIT_TABLES)
    missing = _tables_with_book_id() - covered
    assert missing == set(), (
        "这些表按 book_id 存却不在搬迁清单里 ⇒ 换库 / 改名后静默断链，"
        "补进 REMAP_TABLES（或 REMAP_EXPLICIT_TABLES）：%s" % sorted(missing)
    )


def test_搬迁清单里没有幽灵表(isolated):  # noqa: ARG001
    """清单里的表名必须真实存在且真的有 book_id 列（改表名时别忘了同步）。"""
    ghosts = set(db.REMAP_TABLES) - _tables_with_book_id()
    assert ghosts == set(), "清单里这些表不存在 / 没有 book_id 列：%s" % sorted(ghosts)


# ---------------------------------------------------------------------------
# meta_override / meta_online：逐行搬，同字段冲突保留目标行
# ---------------------------------------------------------------------------

def test_改名把用户覆盖搬过去(isolated):  # noqa: ARG001
    old, new = "lib$oldbook", "lib$newbook"
    db.set_override(old, "title", "用户改过的书名")
    db.set_override(old, "author", "用户改过的作者")

    moved = db.remap_book_id(old, new)

    assert moved["meta_override"] == 2
    assert db.get_overrides(new) == {"title": "用户改过的书名", "author": "用户改过的作者"}
    assert db.get_overrides(old) == {}, "旧 id 不留残留（否则是走不到的孤儿行）"


def test_改名把在线值搬过去(isolated):  # noqa: ARG001
    old, new = "lib$oldbook", "lib$newbook"
    db.set_online(old, {"publisher": ("在线出版社", "douban")})

    moved = db.remap_book_id(old, new)

    assert moved["meta_online"] == 1
    assert db.get_online(new)["publisher"]["value"] == "在线出版社"
    assert db.get_online(old) == {}


def test_改名时同字段冲突保留目标值(isolated):  # noqa: ARG001
    """`PRIMARY KEY(book_id, field)`：整体 UPDATE 会撞主键、异常被 `except` 吞成
    「搬 0 行」⇒ 用户的编辑静默消失。逐行处理后，两边都有同一字段时留着目标行。"""
    old, new = "lib$oldbook", "lib$newbook"
    db.set_override(old, "title", "旧")
    db.set_override(new, "title", "目标已有")

    moved = db.remap_book_id(old, new)

    assert moved["meta_override"] == 0, "目标已有同字段 ⇒ 不搬"
    assert db.get_overrides(new) == {"title": "目标已有"}
    assert db.get_overrides(old) == {}, "旧行要清掉，不能留下同一字段的两行"


def test_改名时目标已有别的字段也不整表跳过(isolated):  # noqa: ARG001
    """合并型表**不做整表跳过探测**：目标上有一个**别的**字段的编辑，
    不该让这本书其余字段的编辑统统搁浅（整表跳过会一次丢全部）。"""
    old, new = "lib$oldbook", "lib$newbook"
    db.set_override(old, "title", "旧标题")
    db.set_override(new, "author", "目标已有作者")

    moved = db.remap_book_id(old, new)

    assert moved["meta_override"] == 1
    assert db.get_overrides(new) == {"title": "旧标题", "author": "目标已有作者"}


# ---------------------------------------------------------------------------
# meta_cover：一张书一行，目标已有封面就不覆盖（宁可少搬，不可错搬）
# ---------------------------------------------------------------------------

def test_改名把封面缓存搬过去(isolated):  # noqa: ARG001
    old, new = "lib$oldbook", "lib$newbook"
    db.set_cover(old, b"\xff\xd8old-cover-bytes")

    moved = db.remap_book_id(old, new)

    assert moved["meta_cover"] == 1
    assert db.get_cover(new)[0] == b"\xff\xd8old-cover-bytes"
    assert db.get_cover(old) is None


def test_改名时目标已有封面则不覆盖(isolated):  # noqa: ARG001
    old, new = "lib$oldbook", "lib$newbook"
    db.set_cover(old, b"old")
    db.set_cover(new, b"target")

    moved = db.remap_book_id(old, new)

    assert moved["meta_cover"] == 0
    assert db.get_cover(new)[0] == b"target", "目标封面不能被旧书的封面顶掉"


# ---------------------------------------------------------------------------
# scrape_items：不走通用 remap（它还有 library_id / source_rel / link_rel 要改）
# ---------------------------------------------------------------------------

def test_出版物台账随搬家(isolated):  # noqa: ARG001
    """换库时台账要改的不止 book_id：``library_id`` 换库、``source_rel`` 换相对路径、
    ``link_rel`` 换副本位置 —— 只改 id 会留下一行「id 对了但指向旧库旧路径」的假账。"""
    old, new = "lib$oldbook", "lib$newbook"
    db.scrape_set(old, library_id="lib-a", source_rel="三体.epub",
                  link_rel="科幻/三体.epub", status="ok", link_mode="hardlink")

    n = db.scrape_remap_item(old, new, library_id="lib-b",
                             source_rel="小说/三体.epub", link_rel="科幻/三体.epub")

    assert n == 1
    assert db.scrape_get(old) is None, "旧 id 的行要搬走，不能两边都有"
    row = db.scrape_get(new)
    assert row["library_id"] == "lib-b"
    assert row["source_rel"] == "小说/三体.epub"
    assert row["link_rel"] == "科幻/三体.epub"
    assert row["status"] == "ok", "状态不该被搬迁顺手改掉（状态机只由检测 / 用户动作降级）"


def test_台账目标已有行时不覆盖(isolated):  # noqa: ARG001
    """目标 id 上已有台账行时不覆盖：那行可能正挂着「副本被删、待用户确认」的待办，
    静默顶掉就等于把待办藏了（反而更难发现）。"""
    old, new = "lib$oldbook", "lib$newbook"
    db.scrape_set(old, library_id="lib-a", source_rel="三体.epub", status="ok")
    db.scrape_set(new, library_id="lib-b", source_rel="别的一本.epub", status="removed")

    n = db.scrape_remap_item(old, new, library_id="lib-b")

    assert n == 0
    assert db.scrape_get(new)["status"] == "removed", "目标行的待确认状态原样保留"
    assert db.scrape_get(old)["status"] == "ok", "旧行原地留着（孤儿可清理，别静默删）"


def test_台账搬迁只认白名单列(isolated):  # noqa: ARG001
    """与 :func:`db.scrape_set` 同一道白名单：拼 SQL 前过滤，不认任意键。"""
    old, new = "lib$oldbook", "lib$newbook"
    db.scrape_set(old, library_id="lib-a", source_rel="三体.epub")

    n = db.scrape_remap_item(old, new, **{"book_id=1, status='ok' --": "x"})

    assert n == 1
    assert db.scrape_get(new)["status"] == "pending", "注入串被过滤，没当成列名拼进 SQL"


# ---------------------------------------------------------------------------
# 孤儿清单：这三张表此前既不在搬迁清单、也不在孤儿清单 ⇒ 行是「搬不走也清不掉」
# ---------------------------------------------------------------------------

def test_元数据三表可被孤儿清理(isolated):  # noqa: ARG001
    """搬迁修好的是「跟着走」，这条修的是「走不了时至少清得掉」：书被删（文件没了）后，
    元数据行同样界面上走不到、却一直占着库（``meta_cover`` 是 BLOB，占的大头）。"""
    for t in ("meta_override", "meta_online", "meta_cover"):
        assert t in db.ORPHAN_TABLES, f"{t} 不在 ORPHAN_TABLES ⇒ 这类行永远清不掉"

    db.set_override("lib$gone", "title", "遗留")
    db.set_cover("lib$gone", b"stale-cover")
    refs = db.book_id_refs()
    assert refs["meta_override"] == ["lib$gone"]
    assert refs["meta_cover"] == ["lib$gone"]

    removed = db.delete_orphans({"meta_override": ["lib$gone"], "meta_cover": ["lib$gone"]})
    assert removed["meta_override"] == 1
    assert removed["meta_cover"] == 1
    assert db.get_overrides("lib$gone") == {}


def test_出版物台账不进孤儿清理(isolated):  # noqa: ARG001
    """台账行被孤儿清理删掉 = 把「磁盘上可能还留着一个副本」这件事静默遗忘。
    它的生死归刮削流程自己管（对账 + 待确认），所以**刻意不**进 ORPHAN_TABLES。"""
    assert "scrape_items" not in db.ORPHAN_TABLES


def test_台账没有行时不造假行(isolated):  # noqa: ARG001
    assert db.scrape_remap_item("lib$a", "lib$b", source_rel="三体.epub") == 0
    assert db.scrape_get("lib$b") is None, "没经过刮削的书不该凭空多出一条待办"


def test_只换目录也改写台账路径(isolated):  # noqa: ARG001
    """层级整理只挪目录 ⇒ ``book_id`` 不变（basename 没变），但 ``source_rel`` 变了：
    台账不能还指着一条已经不存在的路径（那种行下一次对账就会被判成源消失）。"""
    bid = "lib$samebook"
    db.scrape_set(bid, library_id="lib-a", source_rel="三体.epub", status="ok")

    n = db.scrape_remap_item(bid, bid, source_rel="科幻/三体.epub")

    assert n == 1
    assert db.scrape_get(bid)["source_rel"] == "科幻/三体.epub"
    assert db.scrape_get(bid)["status"] == "ok", "只改路径，状态不动"
