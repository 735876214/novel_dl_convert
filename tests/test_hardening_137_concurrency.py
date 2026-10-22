"""第 137 期：并发 / 后台任务加固的回归钉。

这些用例钉的不是「某个功能好不好用」，而是**竞态的边界**：同一条起停路径被并发调用
时只能起一条线程、同一本书不能被两个线程同时处理、单轮异常必须留痕且不能杀线程。

纪律（照 125 / 131 期的口径）：

- **全离线**：外呼、出版目录、源指纹一律换成桩，DB 用 ``isolated`` 夹具；
- **不许 sleep 竞猜**：线程之间的先后一律用 ``threading.Barrier`` / ``Event`` 同步 ——
  断言「B 在 A 放行之前进不来」，而不是「睡 200ms 应该够了」（后者在 CI 上必然是
  随机失败的那一个）。
"""
import json
import logging
import threading

from novelforge.core import autoupdate, bookdock, db, library, scrape, updater
from novelforge.core import watcher as watcher_mod
from novelforge.core.watcher import FolderWatcher


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def _watcher(tmp_path, **wcfg) -> FolderWatcher:
    """用例专属 watcher：输入目录与 state 文件都落在 ``tmp_path``。

    ⚠️ ``state_file`` 必须显式给（默认值是会话级共享文件，跨用例互相污染）。
    """
    return FolderWatcher(input_dir=tmp_path / "input",
                         state_file=tmp_path / "watcher-state.json",
                         cfg={"watcher": {"enabled": True, **wcfg}})


def _race(n, fn):
    """让 ``fn`` 被 n 条线程**尽可能同时**调用一次，返回各自的结果。

    用 Barrier 而不是「起完就算」：并发缺陷只在两个调用真的重叠时才复现，
    顺序调 20 次永远绿。
    """
    barrier = threading.Barrier(n)
    results = []
    lock = threading.Lock()

    def _call():
        barrier.wait(10)
        r = fn()
        with lock:
            results.append(r)

    ts = [threading.Thread(target=_call, name=f"race-{i}") for i in range(n)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(30)
    assert all(not t.is_alive() for t in ts), "有线程没在超时内退出（用例自身的问题）"
    return results


def _gated_get(guard, state, first_name, first_in, release_first, second_in):
    """造一个「进门报到 + 第一条线程挂住」的假 ``db.scrape_get``。

    它是 ``_process_locked`` / ``enqueue`` 里**取按书锁之后的第一句**，所以它的并发度
    就等于「按书锁」的并发度 —— 用它把锁的效果测出来，不必真的去出版一本 EPUB。
    """
    def _get(_bid):
        with guard:
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
            state["order"].append(threading.current_thread().name)
        try:
            if threading.current_thread().name == first_name:
                first_in.set()
                release_first.wait(20)
            else:
                second_in.set()
            return {}                       # 空行 ⇒ 走「书库已不在」这条最短出口
        finally:
            with guard:
                state["cur"] -= 1
    return _get


# ---------------------------------------------------------------------------
# 1. watcher.start()：并发调用只能起一条线程
# ---------------------------------------------------------------------------

def test_watcher_start并发只能起一条监听线程(tmp_path):
    """症状（第 137 期）：两个并发调用都看到 `is_alive()` 为假 ⇒ 各起一条
    `novelforge-watcher` 扫同一棵树；后建的那条把 `_stop` 清掉，先建的那条
    于是**永远停不下来**。修法是把「查 + clear + 建线程 + start」整段进一把锁。

    这里用「线程体报到后挂住」的假 `_loop` 计数：起几条线程就报到几次。
    """
    w = _watcher(tmp_path)
    entered = []
    gate = threading.Event()

    def _fake_loop():                      # 线程体：报到一次，然后等放行
        entered.append(threading.current_thread().name)
        gate.wait(20)

    w._loop = _fake_loop
    try:
        results = _race(20, w.start)
        assert len(entered) == 1, f"并发 start() 起了 {len(entered)} 条监听线程"
        assert results.count(True) == 1, f"只有一次能返回 True，实际 {results.count(True)}"
    finally:
        gate.set()
        w.stop()


# ---------------------------------------------------------------------------
# 2. 收书目录的单文件重扫：必须走 watcher 的官方入口（持 _scan_lock）
# ---------------------------------------------------------------------------

def test_收书目录rescan走watcher官方入口且不持注册锁(isolated, tmp_path):  # noqa: ARG001
    """`bookdock.rescan` 以前直接调 `watcher.handle_file`（不持 `_scan_lock`），
    于是请求线程与监听轮次同时处理同一个文件：重复拷贝 / 重复 book_id /
    `_state.fails` 互相覆盖。

    钉三件事：① 走 `rescan_one`；② 参数原样透传；③ 进来时**不持**
    `bookdock._reg_lock`（「持 `_reg_lock` 时绝不碰 watcher」那条不变量）。
    """
    db.create_library("lid-137", "甲库", "ebook",
                      source_dirs=[str(tmp_path / "libs" / "one")],
                      settings=json.dumps({"watcher": {"copy_non_txt": True}}))
    library.invalidate()

    calls = {}

    class _FakeWatcher:
        def __init__(self):
            self.input_dir = tmp_path / "input"
            self.input_dir.mkdir(parents=True, exist_ok=True)
            (self.input_dir / "Book-1.epub").write_bytes(b"EPUB")

        def rescan_one(self, src, owner_lib=None, owner_root=None):
            calls["cfg"] = (str(src), owner_lib, owner_root)
            # RLock._is_owned()：只有当前线程持有才为真 ⇒ 断言「调用方没持注册锁」
            calls["owner_held"] = bookdock._reg_lock._is_owned()
            return ("converted", str(src))

        def handle_file(self, *_a, **_k):
            raise AssertionError("bookdock 不许直接调 watcher.handle_file（要经 rescan_one 持锁）")

        def mark_processed(self, _p):
            raise AssertionError("mark_processed 应由 watcher.rescan_one 内部做")

    w = _FakeWatcher()
    db.dock_upsert("Book-1.epub", "Book-1.epub", ext=".epub", size=4, status="pending")

    item = bookdock.rescan(w, "Book-1.epub")

    assert "cfg" in calls, "没有走 watcher.rescan_one 这个官方入口"
    assert calls["cfg"][0].endswith("Book-1.epub")
    assert calls["owner_held"] is False, "bookdock 是持着 _reg_lock 调的 watcher（会 AB-BA）"
    assert item["status"] == "ready"


def test_watcher_rescan_one持扫描锁且并发串行(tmp_path):
    """`rescan_one` 是**唯一**的外部单文件入口，它自己持 `_scan_lock`。

    断言两点：① 调 `handle_file` 时锁确实「已持有」；② 两个线程同时调时峰值并发 == 1
    （B 在 A 放行之前**进不来** —— 用 Event 判定，不睡）。
    """
    w = _watcher(tmp_path)
    src = tmp_path / "Book-1.epub"
    src.write_bytes(b"EPUB")

    lock_held = []
    guard = threading.Lock()
    inside = [0, 0]                       # [当前并发, 历史最大]
    a_in, release_a, b_in = threading.Event(), threading.Event(), threading.Event()

    def _handle(p, owner_lib=None, owner_root=None):  # noqa: ARG001
        with guard:
            lock_held.append(w._scan_lock.locked())
            inside[0] += 1
            inside[1] = max(inside[1], inside[0])
        try:
            if threading.current_thread().name == "rescan-A":
                a_in.set()
                release_a.wait(20)
            else:
                b_in.set()
            return ("converted", str(p))
        finally:
            with guard:
                inside[0] -= 1

    w.handle_file = _handle
    ta = threading.Thread(target=w.rescan_one, args=(src,), name="rescan-A")
    tb = threading.Thread(target=w.rescan_one, args=(src,), name="rescan-B")
    try:
        ta.start()
        assert a_in.wait(20), "A 没进 handle_file"
        tb.start()
        assert not b_in.wait(0.3), "B 与 A 同时进了 handle_file —— _scan_lock 没起作用"
        release_a.set()
        ta.join(20)
        assert b_in.wait(20), "A 放行后 B 没能继续（锁没释放？）"
        tb.join(20)
    finally:
        release_a.set()
        ta.join(20)
        tb.join(20)

    assert lock_held and all(lock_held), "rescan_one 调 handle_file 时没有持 _scan_lock"
    assert inside[1] == 1, f"同一文件被并发处理，峰值 {inside[1]}"


# ---------------------------------------------------------------------------
# 3. 刮削：同一本书的 process 必须串行
# ---------------------------------------------------------------------------

def test_同一本书的process并发调用被串行化(isolated, monkeypatch):
    """`publish` 的 `dst.exists()` → `recycle` → `link_or_copy` 是无锁 check-then-act：
    两个线程同时处理一本书时，一方会把另一方刚落的副本移进回收站。修法是按 `bid`
    的互斥（`scrape._bid_guard`）。
    """
    bid = "bid-serial-137"
    guard = threading.Lock()
    state = {"cur": 0, "max": 0, "order": []}
    a_in, release_a, b_in = threading.Event(), threading.Event(), threading.Event()

    monkeypatch.setattr(db, "scrape_get",
                        _gated_get(guard, state, "proc-A", a_in, release_a, b_in))
    monkeypatch.setattr(scrape, "_stale", lambda gen: False)

    ta = threading.Thread(target=scrape.process, args=(bid,), name="proc-A")
    tb = threading.Thread(target=scrape.process, args=(bid,), name="proc-B")
    try:
        ta.start()
        assert a_in.wait(20), "A 没进 _process_locked"
        tb.start()
        assert not b_in.wait(0.3), "同一 bid 的两个 process 同时跑 —— 按书锁没起作用"
        release_a.set()
        ta.join(20)
        assert b_in.wait(20), "A 结束后 B 没能继续（锁没释放？）"
        tb.join(20)
    finally:
        release_a.set()
        ta.join(20)
        tb.join(20)

    assert state["max"] == 1, f"同一 bid 的 process 峰值并发 {state['max']}"
    assert state["order"] == ["proc-A", "proc-B"], "B 抢在 A 前面跑了（锁顺序不对）"


def test_刮削各入口共用同一把按书锁():
    """单一真值源：互斥只许有一处实现（`_bid_guard`）。谁绕过它谁就是缺陷。

    静态钉住四个入口都**亲自**取这把锁 —— 新增入口忘了加锁时这条用例会红。
    """
    import inspect

    for fn in (scrape.enqueue, scrape.process, scrape.verify, scrape.resolve):
        src = inspect.getsource(fn)
        assert "_bid_guard(" in src, f"{fn.__name__} 没走按书锁（_bid_guard）"


# ---------------------------------------------------------------------------
# 4. force_fetch：入队与收尾串行在同一把按书锁上
# ---------------------------------------------------------------------------

def test_入队与收尾串行在同一把按书锁上(isolated, monkeypatch, tmp_path):
    """老形状：入队写 `force_fetch=1`、worker 收尾**无条件**写 `0` ⇒ 用户在处理途中点
    「重新刮削」会被收尾的回写吞掉（或者被 `status='running'` 的「已在队列中」早退），
    用户的动作**静默无效**。

    修法不是再补一次 CAS 写库，而是让两者串行在同一把按书锁上：收尾读到的
    `force_fetch` 一定是它自己入队时写的那个，用户的新动作必然要么落在它之前
    （被读到 ⇒ 重跑）、要么落在它之后（不被覆盖）。这里断言「enqueue 进不来」。
    """
    bid = "bid-force-137"

    class _Pub:
        @staticmethod
        def publish_dir(_lib_id):
            return tmp_path

        @staticmethod
        def source_sig(_p):
            return (0, 0.0)

    class _Lib:
        @staticmethod
        def library_of(_book):
            return {}

        @staticmethod
        def abs_path(_book):
            return tmp_path / "x.txt"

        @staticmethod
        def get_library(_lid):
            return None

    monkeypatch.setattr(scrape, "publish", _Pub)
    monkeypatch.setattr(scrape, "library", _Lib)
    monkeypatch.setattr(scrape, "_stale", lambda gen: False)

    guard = threading.Lock()
    state = {"cur": 0, "max": 0, "order": []}
    a_in, release_a, b_in = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(db, "scrape_get",
                        _gated_get(guard, state, "proc-A", a_in, release_a, b_in))

    ta = threading.Thread(target=scrape.process, args=(bid,), name="proc-A")
    tb = threading.Thread(target=lambda: scrape.enqueue({"id": bid, "name": "x.txt"},
                                                        force=True, reason="rescan"),
                          name="enq-B")
    try:
        ta.start()
        assert a_in.wait(20), "A 没进 _process_locked"
        tb.start()
        assert not b_in.wait(0.3), "入队与收尾同时动这本书 —— 用户的「重新刮削」会被吞掉"
        release_a.set()
        ta.join(20)
        assert b_in.wait(20), "收尾结束后入队没能继续（锁没释放？）"
        tb.join(20)
    finally:
        release_a.set()
        ta.join(20)
        tb.join(20)

    assert state["max"] == 1, f"入队与收尾峰值并发 {state['max']}"
    assert state["order"] == ["proc-A", "enq-B"]


# ---------------------------------------------------------------------------
# 5. 监听主循环：单轮异常留痕、不杀线程
# ---------------------------------------------------------------------------

def test_监听轮次异常留痕且不杀线程(tmp_path, caplog):
    """老实现是整段 `except Exception: time.sleep(...)`：`_scan_target` /
    `_catalog_tick` / `_auto_unpack_tick` 任何失败都**零日志**（NAS 上「监听在线但
    文件永不入库」只能靠猜）。现在每个子系统各自 try：留痕 + 计数 + 下一段照跑。
    """
    w = _watcher(tmp_path)

    def _boom():
        raise OSError("磁盘满")

    w._phase("扫描目标", _boom)                     # 不抛
    w._phase("书目索引", _boom)
    w._phase("容器自动展开", lambda: None)           # 前两次失败不影响后续

    assert w.stats["errors"] == 2, f"失败没计入 stats：{w.stats}"
    # `last_error` 只记**最近一次**（状态里不堆历史 —— 历史在日志里，见下一条断言）
    assert w.last_error == "书目索引失败：磁盘满", f"last_error 应是最近一次失败：{w.last_error}"
    # 两次失败都要**留痕**（"扫描目标"那次被后来的覆盖掉了，但它必须进过日志）
    logged = caplog.text
    for what in ("扫描目标", "书目索引"):
        assert f"监听轮次「{what}」失败" in logged, f"「{what}」的失败没留痕：{logged[-400:]}"
    # 错误计数走 `stats`（`status()` 没有顶层 `errors` 键）——界面按 `stats.errors` 显示
    assert w.status()["stats"]["errors"] == 2, "status() 要把错误计数下发（界面才看得见）"

    # 并且线程本身还活着：一轮炸过之后还能继续跑
    gate = threading.Event()
    w._loop = lambda: gate.wait(20)
    try:
        assert w.start() is True
        assert w._thread.is_alive()
    finally:
        gate.set()
        w.stop()


# ---------------------------------------------------------------------------
# 6. 旁路任务：有界执行器（不再一本一条线程）
# ---------------------------------------------------------------------------

def test_旁路执行器有界且wait_pending等得到全部():
    """老实现每本入库起一条线程、`_BG_THREADS` 只增不减：批量导入 1000 本 =
    峰值 2000 条线程同时外呼公网。现在是有界池。

    `wait_pending()` 的语义必须保住（`tests/test_watcher_auto_fetch.py` 依赖它）：
    调用后**所有已派作业**都跑完，一条都不能静默丢。
    """
    assert 0 < watcher_mod._BG_WORKERS <= 8, "旁路执行器必须有上限（且别开得太大）"

    guard = threading.Lock()
    state = {"cur": 0, "max": 0, "done": 0}
    gate = threading.Event()
    n = watcher_mod._BG_WORKERS * 5

    def _job():
        with guard:
            state["cur"] += 1
            state["max"] = max(state["max"], state["cur"])
        gate.wait(20)
        with guard:
            state["cur"] -= 1
            state["done"] += 1

    for i in range(n):
        assert watcher_mod._spawn_bg(_job, f"job-{i}") is not None
    gate.set()

    assert watcher_mod.wait_pending(30) == 0, "wait_pending 没能把已派作业等干净"
    assert state["done"] == n, f"有作业被静默丢弃（{state['done']}/{n}）"
    assert state["max"] <= watcher_mod._BG_WORKERS, f"峰值并发 {state['max']} 超过上限"


# ---------------------------------------------------------------------------
# 7. updater / autoupdate：起线程也要有锁
# ---------------------------------------------------------------------------

def test_updater_start_background并发只起一条线程(monkeypatch):
    """症状：并发保存配置各起一条检查线程，且后者的新 `_stop` 覆盖前者 ⇒ 前一条
    **永远停不掉**（界面显示已关闭、其实还在每 6 小时查一次并可能自动更新）。"""
    monkeypatch.setattr(updater, "_load_persisted", lambda: None)
    monkeypatch.setattr(updater, "_thread", None)
    entered = []

    def _fake_loop(hours, stop):            # noqa: ARG001
        entered.append(1)
        stop.wait(20)

    monkeypatch.setattr(updater, "_loop", _fake_loop)
    try:
        _race(20, lambda: updater.start_background(6))
        assert len(entered) == 1, f"并发 start_background 起了 {len(entered)} 条线程"
    finally:
        updater.stop_background()           # 只 set 最新的那个 Event
        t = updater._thread
        if t is not None:
            t.join(10)
            assert not t.is_alive(), "叫停后线程没退出"


def test_autoupdate_start_background并发只起一条线程(monkeypatch):
    monkeypatch.setattr(autoupdate, "_thread", None)
    monkeypatch.setattr(autoupdate, "_stop", None)
    entered = []

    def _fake_loop(hours, stop):            # noqa: ARG001
        entered.append(1)
        stop.wait(20)

    monkeypatch.setattr(autoupdate, "_loop", _fake_loop)
    try:
        results = _race(20, lambda: autoupdate.start_background(12))
        assert len(entered) == 1, f"并发 start_background 起了 {len(entered)} 条追更线程"
        assert results.count(True) == 1, "只有一次能返回「新起了线程」"
    finally:
        stop = autoupdate._stop
        if stop is not None:
            stop.set()
        t = autoupdate._thread
        if t is not None:
            t.join(10)


# ---------------------------------------------------------------------------
# 8. 残留 running 的复位：从 start() 的门里抬出来
# ---------------------------------------------------------------------------

def test_复位残留running不再挂在start门上(isolated, monkeypatch):
    """`scrape.enabled=false` 的部署重启后**根本不调 `start()`**，而复位以前挂在它的
    门里 ⇒ 所有 `running` 行永久显示「进行中」、`scrape_pending`（只取 pending）
    永不消费 —— 队列整体停摆。

    现在：复位是独立入口 `reset_interrupted()`，由启动流程无条件调一次。
    """
    db.scrape_set("bid-run-137", library_id="", status="running")
    assert any(r["book_id"] == "bid-run-137"
               for r in db.scrape_list(status="running", limit=10))

    orig = scrape.reset_interrupted
    seen = []
    monkeypatch.setattr(scrape, "reset_interrupted", lambda: seen.append(1) or 0)
    try:
        assert scrape.start() is True
    finally:
        scrape.stop(timeout=5.0)
    assert seen == [], "start() 还在顺手复位 running 行（复位必须与「起不起 worker」解耦）"

    monkeypatch.setattr(scrape, "reset_interrupted", orig)
    assert scrape.reset_interrupted() >= 1
    assert db.scrape_get("bid-run-137")["status"] == "pending", "复位没把 running 打回 pending"
