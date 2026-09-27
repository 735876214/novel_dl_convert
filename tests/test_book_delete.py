"""删除书籍（第 64 期 1/3）：`DELETE /api/books/{bid}` + `/download` 的库维度修复。

「删除」是本项目**第一个**把单本书从书目里拿掉的入口（此前只有「重复项清理」与
「删除整个书库」两条路），也是**第一个**由用户直接点、会移动源文件的接口。它有两处
写错了**看不出来**的地方，本文件的用例就是这两处的常驻哨兵：

1. **静默 unlink**：全仓约定是「删除即回收」（`publish.recycle`），真 unlink 掉文件
   不会有任何报错，只是这本书再也回不来 —— 而且要过很久才会有人发现。所以「文件没了」
   与「回收目录里多出一份**字节数相同**的原文件」两条必须**同时**断言，缺一不可。
2. **有声书是目录**：`fileops` 里那套按文件的回收**拒收目录**，而目录型的书整本就是一个
   目录 —— 只按文件删 = 点了没反应，而且不报错。用例专门盯目录型条目。

另外钉住一条**决策**（不是实现细节）：删书**不清**关联数据（进度 / 批注 / 评分 / 状态）。
依据是既有的更重那条路径 —— `DELETE /api/libraries/{lid}` 也只移除登记、不清数据
（见 `api_delete_library` 的 docstring 与 `_orphan_refs`）；而 `book_id` 由「库 id + 文件名」
派生，**文件从回收目录放回原路径数据就接回来了**，清掉反而让删书变成不可逆操作。
后人若「顺手」补一个 purge，第 5 条用例会红。

末尾三条是**已发现的真 bug 的回归**：`/download/{name}` 原来写死 `OUTPUT_DIR` 拼路径、
且只匹配单段，多库 + Komga 布局下详情页的下载按钮必 404（`fileops.output_dir` 的
docstring 专门禁止那样拼）。修法是加可选 `library_id` + 放宽到 `{name:path}`，
安全性仍一手交给 `fileops.safe_path`（第三条盯的就是「放宽匹配**不等于**放宽校验」）。
"""
from novelforge.core import activity_log, db, fileops, publish

# 与 `conftest.TEST_USER` 同值。这里不 import conftest：本文件自建账号无关的断言，
# 只为确认「日志里记了操作者」而不必把夹具的常量搬进来（先例见 test_local_paths.py）。
ACTOR = "admin"


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------

def _cards(c, h) -> list:
    r = c.get("/api/books", headers=h)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def _card(c, h, name: str) -> dict:
    """按显示名取卡片。

    目录型有声书的 `name` 末尾可能带 `/`，两边都 `rstrip("/")` 归一化 ——
    否则用例会以「书目里找不到这本书」的面目失败，看起来像扫描没收录。
    """
    for b in _cards(c, h):
        if str(b.get("name") or "").rstrip("/") == name.rstrip("/"):
            return b
    got = [b.get("name") for b in _cards(c, h)]
    raise AssertionError(f"书目里没有 {name}；现有：{got}")


def _ids(c, h) -> list:
    return [b["id"] for b in _cards(c, h)]


def _delete(c, h, bid):
    return c.delete(f"/api/books/{bid}", headers=h)


# ---------------------------------------------------------------------------
# 判据 ①：回收，不是真删
# ---------------------------------------------------------------------------

def test_删一本书_文件移进回收目录而不是真删(client, auth_headers, make_book, default_root):
    """最核心的一条：既不能还在原地，也不能凭空消失。"""
    src = make_book(default_root, "三体.epub", b"EPUB" * 500)
    size = src.stat().st_size
    bid = _card(client, auth_headers, "三体.epub")["id"]

    r = _delete(client, auth_headers, bid)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["ok"] is True and body["id"] == bid
    assert not src.exists(), "原路径必须已经不在了（否则等于没删）"

    recycled = body["recycled"]
    assert recycled and recycled.endswith("三体.epub"), f"回收文件名不对：{recycled}"
    dst = fileops.recycle_dir() / recycled
    assert dst.is_file(), f"回收目录里没有它：{dst}"
    # 字节数一致：证明搬走的是**原文件本身**，不是重建了个同名的空壳
    assert dst.stat().st_size == size, "回收的必须是原文件（字节数变了就是重建出来的）"


def test_删有声书_整个目录被移走(client, auth_headers, make_audio_dir, default_root):
    """有声书整本是一个目录：`recycle_items` 那条路会拒收目录（= 点了没反应）。"""
    d = make_audio_dir(default_root, "三体广播剧", tracks=3)
    card = _card(client, auth_headers, "三体广播剧")
    assert card["format"] == "AUDIO", f"前置条件不成立：{card['format']}"

    r = _delete(client, auth_headers, card["id"])
    assert r.status_code == 200, r.text
    assert not d.exists(), "目录必须整个搬走（只搬里面的文件 = 点了没反应）"

    dst = fileops.recycle_dir() / r.json()["recycled"]
    assert dst.is_dir() and len(sorted(dst.glob("*.mp3"))) == 3, f"整树要一起进回收站：{dst}"

    assert card["id"] not in _ids(client, auth_headers), "书必须从书目里消失"


def test_删后书目立刻少一本且计数不为零(client, auth_headers, make_book, default_root):
    for n in ("甲.epub", "乙.epub", "丙.epub"):
        make_book(default_root, n)
    before = client.get("/api/books", headers=auth_headers).json()
    assert before["total"] == 3, f"前置条件：三本都要被扫到，实际 {before['total']}"

    bid = _card(client, auth_headers, "乙.epub")["id"]
    assert _delete(client, auth_headers, bid).status_code == 200

    after = client.get("/api/books", headers=auth_headers).json()
    assert after["total"] == before["total"] - 1
    # ⚠️ 这一条防的是**静默归零**：`total` 从 3 变成 0 同样满足上面那句差值断言，
    # 而「删一本把全库清了」是比不删严重得多的错。
    assert after["total"] > 0, "删一本不能把整个书目清空"
    assert bid not in [b["id"] for b in after["items"]]
    assert "乙.epub" not in [b["name"] for b in after["items"]]


# ---------------------------------------------------------------------------
# 判据 ②：不许误伤（别人的数据 / 兄弟文件）
# ---------------------------------------------------------------------------

def test_删一本不动别人的进度与评分(client, auth_headers, make_book, default_root):
    """防「DELETE 漏 WHERE」这类误伤 —— 它只会在别人身上显形。"""
    make_book(default_root, "甲.epub")
    make_book(default_root, "乙.epub")
    a = _card(client, auth_headers, "甲.epub")["id"]
    b = _card(client, auth_headers, "乙.epub")["id"]
    db.set_progress(a, 3, 30.0)
    db.set_progress(b, 7, 70.0)
    db.set_rating(a, 2)
    db.set_rating(b, 5)
    db.set_status(a, "finished")
    db.set_status(b, "reading")

    assert _delete(client, auth_headers, a).status_code == 200

    cards = {x["id"]: x for x in _cards(client, auth_headers)}
    assert b in cards, "另一本不该从书目里消失"
    assert cards[b]["percent"] == 70.0
    assert cards[b]["stars"] == 5
    assert cards[b]["status"] == "reading"
    assert db.get_progress(b)["locator"] == 7
    # A 自己的数据同样是**保留**的（见下一条），这里只确认两者互不干扰
    assert db.get_progress(a)["locator"] == 3


def test_删书保留关联数据_文件放回去就能接上(client, auth_headers, make_book, default_root):
    """钉住「不清关联数据」这条决策 —— 后人顺手加 purge 时这里会红。

    依据见文件头与 `api_delete_book` 的 docstring：删整个库都不清，删一本书更不该清；
    而 `book_id` 由「库 id + 文件名」派生，文件放回原路径数据自然接回 ——
    保留数据才让「删书」成为真正可撤销的动作。
    """
    make_book(default_root, "三体.epub")
    bid = _card(client, auth_headers, "三体.epub")["id"]
    db.set_progress(bid, 12, 45.0)
    db.set_rating(bid, 4)
    db.set_status(bid, "reading")
    db.add_annotation(bid, 3, "给岁月以文明", "yellow", "笔记")

    assert _delete(client, auth_headers, bid).status_code == 200

    p = db.get_progress(bid)
    assert p is not None and p["locator"] == 12, "进度不该被删（删库都不清，删书更不该）"
    assert db.all_ratings().get(bid) == 4
    assert (db.all_statuses().get(bid) or {}).get("status") == "reading"
    annos = db.list_annotations(bid)
    assert [x["quote"] for x in annos] == ["给岁月以文明"], "用户手写的批注不可逆，绝不能删"


def test_删书把刮削台账降级而不是删行(client, auth_headers, make_book, default_root):
    """台账行要**留着**、状态降成 `source_removed`。

    静默失效方式：删行之后界面显示「没刮过」，用户以为还有源可刮；而留一行「已完成」
    更糟 —— 源文件已经不在了，下一轮刮削会照着它去动一个不存在的路径。降级是唯一
    两者都说得通的写法（`source_removed` 属「只许降级」，源放回来还能复活）。
    """
    make_book(default_root, "三体.epub")
    bid = _card(client, auth_headers, "三体.epub")["id"]
    db.scrape_set(bid, status="ok", source_rel="三体.epub")

    assert _delete(client, auth_headers, bid).status_code == 200

    row = db.scrape_get(bid)
    assert row is not None, "台账行不能被删掉（删了就查不出这本书曾经刮过）"
    assert row["status"] == "source_removed", row
    assert row["source_rel"] == "三体.epub", "别的列要原样留着"


def test_删一本不动同名的其它格式(client, auth_headers, make_book, default_root):
    """`三体.epub` 与 `三体.mobi` 是**两张卡片、两个 id**，不替用户一起删。"""
    epub = make_book(default_root, "三体.epub")
    mobi = make_book(default_root, "三体.mobi")
    card = _card(client, auth_headers, "三体.epub")

    r = _delete(client, auth_headers, card["id"])
    assert r.status_code == 200, r.text
    assert not epub.exists()
    assert mobi.is_file(), "兄弟文件是另一张卡，不能被顺手删掉"

    names = [b["name"] for b in _cards(client, auth_headers)]
    assert "三体.mobi" in names and "三体.epub" not in names
    # 确认文案要能点名兄弟文件，否则用户会以为两个格式一起没了
    assert r.json()["siblings"] == ["三体.mobi"], r.json()


def test_文件已不在磁盘_删除仍然成功(client, auth_headers, make_book, default_root):
    """磁盘被人先动过（手动删 / NAS 上改名）时不能变成死路：书得能删掉。"""
    src = make_book(default_root, "三体.epub")
    bid = _card(client, auth_headers, "三体.epub")["id"]
    # 用回收原语搬走，不是 unlink（本仓禁止真删）
    assert publish.recycle(src, why="用例先把它搬走") is not None

    r = _delete(client, auth_headers, bid)
    assert r.status_code == 200, f"文件已经不在了，删除不该失败：{r.text}"
    assert r.json()["recycled"] is None, "没有东西可回收时必须是 None，不能编一个名字"
    assert bid not in _ids(client, auth_headers), "台账里的这一行仍要清掉"


def test_删不存在的书_404(client, auth_headers, default_root):
    r = client.delete("/api/books/不存在的id", headers=auth_headers)
    assert r.status_code == 404, r.text


def test_id冲突时_409且两本都还在(client, auth_headers, make_book, default_root):
    """冲突时**绝不能**删掉其中一本 —— 宁可删不成。"""
    flat = make_book(default_root, "三体.epub")
    nested = make_book(default_root, "科幻/三体.epub")
    cards = _cards(client, auth_headers)
    ids = {b["id"]: b["name"] for b in cards}
    assert len(ids) == 1, f"前置条件：同库不同路径同名 → 同一个 id，实际 {ids}"

    r = _delete(client, auth_headers, next(iter(ids)))
    assert r.status_code == 409, f"冲突必须显式报错，不能挑一本删：{r.text}"
    assert flat.is_file() and nested.is_file(), "409 之后两个文件都必须原封不动"


# ---------------------------------------------------------------------------
# 台账与路由
# ---------------------------------------------------------------------------

def test_删书写审计日志(client, auth_headers, make_book, default_root):
    """移了文件却没有日志 = 事后没人查得出这本书去哪了。"""
    make_book(default_root, "审计专用.epub")
    bid = _card(client, auth_headers, "审计专用.epub")["id"]
    r = _delete(client, auth_headers, bid)
    recycled = r.json()["recycled"]

    hits = [e for e in activity_log.recent(limit=200, action=activity_log.ACTION_RECYCLE)
            if e.get("file") == "审计专用.epub"]
    assert hits, "删除没有留下审计记录"
    e = hits[0]
    assert e["status"] == activity_log.STATUS_OK
    # 日志里的回收文件名必须与响应一致：不一致的话照着日志找不回文件
    assert e["output"] == recycled, e
    assert e["actor"] == ACTOR, f"没记下操作者就查不出是谁删的：{e}"


def test_删书端点不吞别的路由(client, auth_headers, make_book, default_root):
    """参数化路由吞字面量路径在本仓踩过两次（见 `/api/books/batch` 上面的注释）。"""
    make_book(default_root, "三体.epub")
    bid = _card(client, auth_headers, "三体.epub")["id"]
    db.set_rating(bid, 4)

    r = client.delete(f"/api/books/{bid}/rating", headers=auth_headers)
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert db.all_ratings().get(bid) is None, "取消评分要真的生效"
    assert bid in _ids(client, auth_headers), "取消评分不能把书删掉"
    assert (default_root / "三体.epub").is_file(), "更不能把文件搬走"


def test_未登录不能删书(client, auth_headers, make_book, default_root):
    src = make_book(default_root, "三体.epub")
    bid = _card(client, auth_headers, "三体.epub")["id"]

    r = client.delete(f"/api/books/{bid}")          # 不带 Bearer
    assert r.status_code == 401, r.text
    assert src.is_file(), "401 之后文件必须原封不动"
    assert bid in _ids(client, auth_headers)


# ---------------------------------------------------------------------------
# `/download` 的库维度修复（既有 bug 的回归）
# ---------------------------------------------------------------------------

def test_下载接口按库解析根(client, auth_headers, make_book, make_library,
                            default_root, tmp_path):
    """库根 ≠ `OUTPUT_DIR` 时必须带 `library_id` 才下得到。

    这是多书库下详情页「下载」按钮点了 404 的真因：原写法 `OUTPUT_DIR / name`
    对其它库的书一律解析到错位置（`fileops.output_dir` 的 docstring 明令禁止）。
    """
    other = tmp_path / "libraries" / "lib-b"
    make_library("lib-b", "乙库", "ebook", other)
    make_book(other, "乙.epub", b"B" * 10)
    make_book(default_root, "甲.epub", b"A" * 10)

    # 不带 library_id：基根仍是 OUTPUT_DIR，别的库的书解析不到（= 改造前的老行为）
    assert client.get("/download/乙.epub").status_code == 404

    r = client.get("/download/乙.epub", params={"library_id": "lib-b"})
    assert r.status_code == 200 and r.content == b"B" * 10, r.text
    assert client.get("/download/甲.epub", params={"library_id": "lib-b"}).status_code == 404


def test_下载接口接受库内相对路径(client, auth_headers, make_book, default_root):
    """`{name}` → `{name:path}`：Komga 布局下 `files[].name` 是 `系列/文件`（单段路由接不住）。"""
    make_book(default_root, "三体/三体-1.epub", b"C" * 10)
    r = client.get("/download/三体/三体-1.epub", params={"library_id": "default"})
    assert r.status_code == 200 and r.content == b"C" * 10, r.text


def test_下载接口不放宽穿越(client, auth_headers, default_root):
    """放宽到 `:path` 只影响**匹配**，校验仍一手交给 `safe_path`。"""
    # 用 %2F 而非字面 `/`：避免客户端把 `..` 段规范化掉，测到的才是服务端的行为
    for bad in ("%2e%2e%2fsecret.epub", "..%2f..%2fsecret.epub", "a%2fb%2fc.epub"):
        r = client.get(f"/download/{bad}")
        assert r.status_code in (400, 404), f"{bad} 不该被放行：{r.status_code}"
