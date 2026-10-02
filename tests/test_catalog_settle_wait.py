"""第 88 期收尾：把「脏库读只派后台刷新」与「写后立刻读仍看得见」这对**互相拉扯**的契约
用「有上限等待」同时钉住。**零外网**。

背景（为什么单独一个文件）：本期要把「脏库刷新」移出请求路径，但仓库里同时存在两组
方向相反的既有契约：

- ``test_catalog.py`` / ``test_scan_background.py`` 要求「脏库读**只派后台**、请求线程
  绝不扫盘」（否则 NAS 上「每次打开书库都慢」照旧）；
- 另有约五十条用例（``test_annotation_export`` / ``test_browse_counts`` / ``test_book_delete``
  …）依赖「写文件 → ``library.invalidate()`` → **立刻** ``library.books()`` → 必须看得见新书」。

纯「立即返回现有索引」满足前者、必然违反后者；纯「请求线程同步扫」反过来。
``catalog._settle`` 取的是**有上限等待**：把刷新派给后台，然后最多为它等
``catalog.SETTLE_WAIT`` 秒（到点如实返回现有索引，绝不无限等）。本文件钉住这条折中：
**等得到**（小库/局域网很快，满足写后立刻读）与**等得住上限**（慢刷新拖不住请求）。
"""
import pathlib
import threading
import time

from novelforge.core import catalog, library


def _put(root: pathlib.Path, name: str) -> pathlib.Path:
    """往库根放一本占位书（扫描只按扩展名收书，不需要真 EPUB）。"""
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    p.write_bytes(b"EPUB")
    return p


def _names(lid: str) -> set:
    return {b["name"] for b in library.books(lid)}


def test_写后立刻读仍能看到新书(default_root, test_lib_id):
    """**既有契约**：写文件 → ``invalidate`` → **立刻** ``books()``，本次就要看得见新书。

    这是全仓 20 多处写操作之后 ``library.invalidate()`` 的依据，也是约五十条既有用例
    的立足点。``SETTLE_WAIT`` 的那点等待就是为它留的 —— 把它调成 0 会让这些用例集体变红
    （那正是「立即返回现有索引」路线的代价，需要另择时机统一改那批用例的语义）。
    """
    lid = test_lib_id
    _put(default_root, "第一本.epub")
    assert _names(lid) == {"第一本.epub"}          # 冷启动：索引为空 ⇒ 同步扫

    _put(default_root, "第二本.epub")
    library.invalidate(lid)
    assert _names(lid) == {"第一本.epub", "第二本.epub"}, \
        "标脏后立刻读没看到新书（脏库的读没有把刷新等回来）"
    assert catalog.wait_pending(5.0) == 0, "后台刷新没收干净（收尾纪律）"


def test_脏库读走后台分支而不是请求线程扫盘(default_root, test_lib_id, monkeypatch):
    """反向钉住：脏库的读**派**后台刷新（``_trigger_background``），不是自己同步扫。

    没有这条，把 ``_settle`` 改回「请求线程里同步刷」也能让上一条通过 —— 而那正好是
    本期要消掉的行为。这里 Spy ``_trigger_background``：判据一退化，这里就收不到派活。
    """
    lid = test_lib_id
    _put(default_root, "第一本.epub")
    assert _names(lid) == {"第一本.epub"}

    triggered = []
    real = catalog._trigger_background
    monkeypatch.setattr(
        catalog, "_trigger_background",
        lambda lib_: (triggered.append(str(lib_.get("id"))), real(lib_))[1])

    _put(default_root, "第二本.epub")
    library.invalidate(lid)
    library.books(lid)                              # 脏库：应当只派后台
    assert triggered == [lid], "脏库没走后台分支（又回到请求线程里扫盘了）"
    assert catalog.wait_pending(5.0) == 0


def test_慢刷新不会无限拖住读请求(default_root, test_lib_id, monkeypatch):
    """**上限**：把刷新换成会长时间阻塞的桩，读请求仍必须在 ``SETTLE_WAIT`` 附近返回。

    这条钉的是「等得住上限」—— 没有它，「有上限等待」退化成「无限等」，
    NAS 上几十秒的全量重探又会挂到请求上（本期要根除的那个症状）。
    """
    lid = test_lib_id
    _put(default_root, "第一本.epub")
    assert _names(lid) == {"第一本.epub"}          # 冷启动先同步扫一次（不经过后台）

    # 把上限压到 50ms：读最多只能等这么久，之后必须如实返回现有索引
    monkeypatch.setattr(catalog, "SETTLE_WAIT", 0.05)
    release = threading.Event()

    def _blocked(lib_, force):                      # noqa: ARG001 —— 桩掉的正是「扫盘」那一步
        release.wait(10)
        return {"scanned": 0, "added": 0, "removed": 0, "unchanged": 0, "skipped": False}

    monkeypatch.setattr(catalog, "_refresh_locked", _blocked)
    _put(default_root, "第二本.epub")
    library.invalidate(lid)
    try:
        t0 = time.monotonic()
        library.books(lid)
        dt = time.monotonic() - t0
        # 宽松上限：真被那个 10s 的桩按住的话，这里会是 ~10s。50ms 的上限让它远小于 1s。
        assert dt < 1.0, f"读被慢刷新拖住了 {dt:.3f}s（SETTLE_WAIT 的上限没生效）"
    finally:
        release.set()                              # 一定放行：后台线程不许在测试里真等
        assert catalog.wait_pending(5.0) == 0
