"""书库计数契约（第 39 期）。

``book_count`` 是侧边栏胶囊与书库页唯一的「这个库有多少书」来源。而在第 39 期之前，
它**全仓一个测试都没有** —— ``_book_counts()`` / ``library.books()`` 这条链被改坏，
没有任何用例会红。

本文件钉的是**不变量**（计数立刻反映真实书目），不是某个实现：

- 新建库之后再查，计数是**扫描出来的真值**，不是 0、也不是别的库的数；
- 一次响应里多个库各算各的，不串味；
- 改库根之后计数立刻跟着走，不回退成旧根的数；
- 库根不存在时 ``exists`` 为假、计数为 0，而不是炸掉或报有书。

## 与观察项 1（第 34 期「侧边栏首次加载显示 0 本」）的关系

第 39 期为此做过一次溯源，结论**推翻了当时的假设**，如实记在案：

- 计划里写的「侧边栏 ``onMounted`` 不带 ``force`` ⇒ 永远不刷新」**站不住** ——
  权威记录（``.codebuddy/memory/2026-09-21.md``）说的是「刷新即恢复」，方向正好相反；
  且 ``ShelfView`` / ``LibrariesView`` / ``BookDetailView`` 等多处本就调
  ``loadLibraries(true)``，侧边栏读的是同一个 store。
- 「第 37 期的 ``_libraries_changed()`` 顺带修掉了它」**也是错的** ——
  查 ``git show 49b348a^:novelforge/server.py``，建 / 改 / 删库三处**在那之前就已经**
  各自调 ``library.invalidate()``（旧文件 2734 / 2803 / 2825 行）。第 37 期做的是把它们
  收敛进 ``_libraries_changed()`` 并**新增** ``forget_failures()``。缓存失效从来没缺过。
- 所以那条观察**至今未被复现、机制仍不明**。本文件不假装能复现它 ——
  它补的是「这条链此前完全没有覆盖」这个**独立的、真实存在**的缺口。
"""
import shutil

#: 起手那条库（`isolated` 建的）。多数用例拿它当「已有的库」。
START_LIB = "default"


def _counts(c, h) -> dict:
    """``GET /api/libraries`` → ``{库id: book_count}``（侧边栏胶囊读的就是这个数）。"""
    r = c.get("/api/libraries", headers=h)
    assert r.status_code == 200, r.text
    return {x["id"]: x["book_count"] for x in r.json()["items"]}


def _lib(c, h, lid: str) -> dict:
    r = c.get("/api/libraries", headers=h)
    assert r.status_code == 200, r.text
    for x in r.json()["items"]:
        if x["id"] == lid:
            return x
    raise AssertionError(f"响应里没有库 {lid}：{[x['id'] for x in r.json()['items']]}")


def test_新建库之后立刻查计数就是真实值(client, auth_headers, make_book, tmp_path):
    """新库的书**先落在盘上、后登记库** —— 正是用户「先把漫画拷进去再建漫画库」的顺序。

    这条钉住的是「新建库之后再查，计数不能是 0」。第 34 期那条观察说的就是这个画面
    （新库显示 0 本、而库里明明有书），只是它至今没能复现；这里是它的**常驻回归位**。
    """
    manga = tmp_path / "libraries" / "manga"
    make_book(manga, "第一卷.epub")
    make_book(manga, "第二卷.epub")

    r = client.post("/api/libraries", headers=auth_headers,
                    json={"name": "漫画库", "type": "mixed", "root_path": str(manga)})
    assert r.status_code == 200, r.text
    lid = r.json()["library"]["id"]

    counts = _counts(client, auth_headers)
    assert counts.get(lid) == 2, (
        f"新建的库立刻查应是 2 本，实际 {counts.get(lid)!r}（全量：{counts}）—— "
        "计数没跟着建库走"
    )
    # 反向确认：新库的书没有把**起手那条库**的计数顶掉
    assert counts[START_LIB] == 0


def test_空库真的是_0_而不是别的库的数(client, auth_headers, default_root, make_book, tmp_path):
    """``0`` 是**真值**：库根存在、里头就是一本书都没有。

    跟一个**确实有书**的库并排查，才叫「不串味」；只查一个空库，
    「返回 0」与「整条链根本没跑」是分不开的。

    与前端 ``hasNoLibraries`` 那条「不知道 ≠ 0 个」是**两件事** —— 那条管的是
    「有没有拉到」，这里管的是「拉到了、值对不对」。别把两者混成一个口径。
    """
    make_book(default_root, "起手库.epub")                     # 对照：这个库有 1 本

    empty = tmp_path / "libraries" / "empty"
    empty.mkdir(parents=True, exist_ok=True)
    r = client.post("/api/libraries", headers=auth_headers,
                    json={"name": "空库", "type": "mixed", "root_path": str(empty)})
    assert r.status_code == 200, r.text

    counts = _counts(client, auth_headers)
    assert counts[r.json()["library"]["id"]] == 0, f"空库该是 0：{counts}"
    assert counts[START_LIB] == 1, f"起手库该是 1 —— 否则「空库是 0」说明不了什么：{counts}"


def test_多库计数各归各的不串味(client, auth_headers, default_root, make_book,
                                 make_library, tmp_path):
    """一次响应里每库各算各的。

    ``_book_counts()`` 是**一次扫描全库再按 ``library_id`` 分组**（不是逐库各扫一次），
    分组键写错就会让所有库显示同一个数 —— 而那个数看上去永远「不像 0」，很难察觉。
    """
    make_book(default_root, "起手库.epub")                 # 起手那条库：1 本

    other = tmp_path / "libraries" / "other"
    for n in ("甲", "乙", "丙"):
        make_book(other, f"{n}.epub")                      # 乙库：3 本
    make_library("lib-other", "乙库", "mixed", other)

    counts = _counts(client, auth_headers)
    assert counts[START_LIB] == 1, f"起手库应是 1 本，实际 {counts[START_LIB]}（{counts}）"
    assert counts["lib-other"] == 3, f"乙库应是 3 本，实际 {counts['lib-other']}（{counts}）"


def test_改库根之后计数立刻跟着走(client, auth_headers, default_root, make_book, tmp_path):
    """``PATCH root_path`` 只改登记、不搬文件；计数必须**当场**改口径。

    ⚠️ 先查一次把扫描缓存捂热（``_books_of`` 有 5s TTL），否则这条用例可能压根
    没走到缓存那条分支上 —— 那就成了「测了个寂寞」。
    """
    make_book(default_root, "旧根.epub")
    assert _counts(client, auth_headers)[START_LIB] == 1     # 捂热缓存

    fresh = tmp_path / "libraries" / "fresh"
    for n in ("甲", "乙", "丙"):
        make_book(fresh, f"{n}.epub")

    r = client.patch(f"/api/libraries/{START_LIB}", headers=auth_headers,
                     json={"root_path": str(fresh)})
    assert r.status_code == 200, r.text

    assert _counts(client, auth_headers)[START_LIB] == 3, \
        "换了库根，计数还是旧根的数 —— 扫描缓存没失效"


def test_库根不存在时_exists_为假且计数为_0(client, auth_headers, make_library, tmp_path):
    """库根被删掉（NAS 掉线 / 手工删目录）**不能炸**，也不能报「有书」。

    ``exists`` 与 ``book_count`` 在这里必须**一致地**说「这里没有书」——
    界面据此显示「目录不存在」，而不是一个凭空的数字。
    """
    gone = tmp_path / "libraries" / "gone"
    make_library("lib-gone", "已失效", "mixed", gone)     # make_library 会把这个目录建出来
    shutil.rmtree(gone)

    dto = _lib(client, auth_headers, "lib-gone")
    assert dto["exists"] is False, "库根都没了，exists 还是真"
    assert dto["book_count"] == 0, f"库根都没了，计数却是 {dto['book_count']}"


def test_删库护栏靠的就是这个计数(client, auth_headers, make_book, make_library, tmp_path):
    """「库里还有书就拒绝删库」这道数据保护**直接读 ``_book_counts()``**。

    所以计数一旦失真，失败方向是**朝开门**的：库里有书却报 0 ⇒ 拦住的那一下没了，
    用户以为删的是空库。这条把「计数准确」与「数据保护」焊在一起 ——
    比单看一个数字值钱得多。
    """
    lib_root = tmp_path / "libraries" / "full"
    make_book(lib_root, "唯一一本.epub")
    make_library("lib-full", "有书的库", "mixed", lib_root)

    r = client.delete("/api/libraries/lib-full", headers=auth_headers)
    assert r.status_code == 400, (
        f"库里有书却允许直接删（{r.status_code}）—— 数据保护失效了：{r.text}"
    )

    # force=1 才放行，且**只移除登记**：文件必须还在原地
    r = client.delete("/api/libraries/lib-full", headers=auth_headers, params={"force": 1})
    assert r.status_code == 200, r.text
    assert r.json()["books_left_on_disk"] == 1
    assert (lib_root / "唯一一本.epub").exists(), "「只移除登记，绝不删文件」被破坏了"
    assert "lib-full" not in _counts(client, auth_headers)
