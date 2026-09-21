"""第 34 期：刮削 worker 的**停机收尾** —— 被作废的那一轮一个字都不许落库。

**根因（不是「偶发」，是可构造的必然）**：

1. ``stop(timeout)`` 只等一段时间就走，而**单条处理是不可中断的整段调用**
   （外呼 / 重试 / 写副本都可能远超 timeout）；
2. 于是 worker 会带着 ``_stop`` 检查不到的进度把那条跑完，然后**照常落库**；
3. 而测试的库是**用例级隔离**的（``db.close()`` + ``db.init()`` 换一套空库）
   ⇒ 残留线程的写落到**下一个用例的库**上：删行让全局总数变 0、插行变 2。
   这正是「单跑必过、全量偶挂」的形状（受害断言是全局 ``total``）。

**修法** = worker 世代号（``scrape._epoch``）：``stop()`` / ``start()`` 推进世代，
旧世代在**每个落库点**被拒 ⇒「收尾必须干净」成为可强制的事实。
代价只是「那条留到下次重来」—— 那本来就是既有恢复路径
（``start()`` 会 ``scrape_reset_running()`` 把 running 打回 pending）。

这个用例**不靠运气**：把「一条处理要跑很久」用替身做成确定性事实，
再显式演一遍夹具的换库动作。**断言的是库内容，不是时序**。
"""
import pathlib
import threading
import time

import pytest

from novelforge import config
from novelforge.core import db, epub_builder, library, publish, scrape


@pytest.fixture
def env(isolated, tmp_path: pathlib.Path) -> dict:  # noqa: ARG001 —— 依赖 isolated 切目录
    """库根 + 独立成品目录（与 test_scrape_publish 同一套：成品目录不与库根相交）。"""
    root = tmp_path / "libraries" / "novels"
    pdir = tmp_path / "libraries" / "_sorted"
    root.mkdir(parents=True, exist_ok=True)
    db.create_library("novels", "小说库", "ebook", "inplace", str(root),
                      source_subdir="novels", publish_path=str(pdir))
    library.invalidate()
    return {"lid": "novels", "root": root, "pdir": pdir}


def _slow_publish(entered: threading.Event, release: threading.Event):
    """出版替身：先进 `entered` 报到，再等 `release` 放行（最多 3 秒，防用例挂死）。

    「跑很久的单条」在生产里是外呼 / 重试 / 写大副本 —— 这里把它变成确定性事实。
    """
    def fake(book, **_kw):
        entered.set()
        release.wait(timeout=3.0)
        return {"ok": True, "rel": "西游.epub", "mode": publish.LINK_COPY}
    return fake


def test_停机后残留worker写不进换过的那套库(env, monkeypatch, tmp_path: pathlib.Path):
    src = env["root"] / "西游.epub"
    epub_builder.build_epub({"title": "西游", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(src))
    library.invalidate()
    book = next(b for b in library.books(env["lid"]) if b["name"] == "西游.epub")
    assert scrape.enqueue(book)["queued"] is True

    entered, release = threading.Event(), threading.Event()
    monkeypatch.setattr(publish, "publish", _slow_publish(entered, release))

    scrape.start()
    try:
        assert entered.wait(5.0), "worker 没走到出版那一步（替身没被调用）"

        # ① 停不下来：timeout 内收不掉 —— 这就是原来漏掉的那个窗口
        scrape.stop(timeout=0.2)
        assert scrape.is_running() is True, "用例前提：这条处理收不掉（真实场景同理）"

        # ② 演一遍夹具的换库动作：`isolated` 的收尾是「改 DATA_DIR → db.close() 」，
        #    下一个用例再 init 出一套**全新的空库**。所以这里也必须换目录 ——
        #    只调 close()+init() 会重开同一个文件，断言就失去意义了。
        monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data-next")
        db.close()
        db.init()
        assert db.scrape_counts() == {}, "换库后应当是新空库"

        # ③ 放行那条「跑了很久」的处理，并等残留线程收干净
        release.set()
        scrape.stop(timeout=5.0)
        time.sleep(0.1)          # 给残留线程一点时间「作案」—— 作不了才说明守卫生效

        assert db.scrape_counts() == {}, "残留 worker 往换过的那套库里写了行（全局 total 会被它改掉）"
        assert db.scrape_get(book["id"]) is None
    finally:
        release.set()
        scrape.stop(timeout=5.0)


def test_正常一轮照旧落库(env, monkeypatch):
    """守卫只对「被作废的那一轮」生效 —— 正常运行不许被它挡住。"""
    src = env["root"] / "西游.epub"
    epub_builder.build_epub({"title": "西游", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(src))
    library.invalidate()
    book = next(b for b in library.books(env["lid"]) if b["name"] == "西游.epub")
    assert scrape.enqueue(book)["queued"] is True

    res = scrape.run_once()
    assert res["processed"] == 1
    assert res["items"][0]["ok"] is True, res["items"][0]
    assert db.scrape_get(book["id"])["status"] == "ok"


def test_作废世代会拒绝落库(env):
    """模块层直测不变量：世代被推进之后，旧世代的一切落库点都拒绝。"""
    src = env["root"] / "西游.epub"
    epub_builder.build_epub({"title": "西游", "author": "作者", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>正文</p>"}], str(src))
    library.invalidate()
    book = next(b for b in library.books(env["lid"]) if b["name"] == "西游.epub")
    scrape.enqueue(book)

    stale_gen = scrape.epoch()          # 记下「现在这一轮」
    scrape.stop(timeout=0.0)            # 作废它
    out = scrape.process(book["id"], fetch=False, gen=stale_gen)

    assert out.get("aborted") is True, out
    assert db.scrape_get(book["id"])["status"] != "ok", "作废的那一轮把状态写成 ok 了"

    # 不传世代（同步 / 接口触发的调用）不受影响 —— 守卫对常规路径透明
    fresh = scrape.process(book["id"], fetch=False)
    assert fresh.get("ok") is True, fresh
    assert db.scrape_get(book["id"])["status"] == "ok"
