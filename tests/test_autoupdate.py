"""追更的后台调度（第 86 期最后一项）。

这里只钉**调度口径**（零网络、零外呼）—— 追更本身的正确性在
`tests/test_update_report.py`（只追加 / 既有条目一字不动 / 起点不靠章名）。

⚠️ 真机验证仍缺（本机没有真实可跑的书源），与本期其它下载链路同口径如实标注。
"""
import pathlib
import threading

from novelforge.core import autoupdate, library


# ---------------- 首轮不许立刻跑（最重要的一条）----------------

def test_首轮不立刻跑(monkeypatch):
    """叫停时 `_loop` 一次 `tick` 都不该发生 —— 重启服务不能等于「对全部书外呼一轮」。

    `stop.wait(interval)` 等待期间被叫停 ⇒ 立即返回 True ⇒ 循环体（含首轮 `tick`）
    一次也不执行。这正是我们想要的语义。
    """
    called: list = []
    monkeypatch.setattr(autoupdate, "tick", lambda cfg=None: called.append(1))
    stop = threading.Event()
    stop.set()                       # 起线程前就叫停
    autoupdate._loop(12, stop)       # noqa: SLF001 —— 直接跑循环体，不等 12 小时
    assert called == [], "首轮必须等一个间隔；否则重启即全量外呼"


def test_循环体异常不冒泡(monkeypatch):
    """`tick` 抛异常只记日志，不能让线程死掉（旁路功能绝不冒泡）。

    ⚠️ 不能让 `stop.wait` 真的等：`_loop` 的最小间隔是 1 小时，真等就把测试挂住
    （本轮实测踩过：整个 pytest 卡在 3600 秒的 wait 上）。这里把 `wait` 换成
    「前两次返回 False（= 等完该等了）、之后返回 True（= 被叫停）」的假实现。
    """
    seq = {"n": 0}
    waits = {"n": 0}
    stop = threading.Event()

    def fake_wait(timeout=None):     # noqa: ARG001
        waits["n"] += 1
        return waits["n"] > 2

    def boom(cfg=None):
        seq["n"] += 1
        raise RuntimeError("站点炸了")

    monkeypatch.setattr(stop, "wait", fake_wait)
    monkeypatch.setattr(autoupdate, "tick", boom)
    autoupdate._loop(1, stop)        # noqa: SLF001
    assert seq["n"] == 2, "异常必须被吞掉，且不阻止后续轮次"


# ---------------- 候选枚举 ----------------

def test_只认有留档的书(isolated, default_root):  # noqa: ARG001
    """候选 = 书旁边有同名 `.meta.json` 的那些（sidecar 是「下载来的」唯一持久痕迹）。"""
    default_root.mkdir(parents=True, exist_ok=True)
    (default_root / "有留档.epub").write_bytes(b"PK")
    (default_root / "有留档.meta.json").write_text('{"source":"x"}', encoding="utf-8")
    (default_root / "手写书.epub").write_bytes(b"PK")
    library.invalidate()

    got = {p.name for p in autoupdate.candidates()}
    assert "有留档.meta.json" in got
    assert "手写书.meta.json" not in got, "没有留档的书不是追更对象"


def test_单轮上限生效(isolated, default_root):  # noqa: ARG001
    """`max_books` 是硬上限：一次外呼不许打爆（宁可下一轮再追剩下的）。"""
    default_root.mkdir(parents=True, exist_ok=True)
    for i in range(5):
        (default_root / f"书{i}.epub").write_bytes(b"PK")
        (default_root / f"书{i}.meta.json").write_text('{"source":"x"}', encoding="utf-8")
    library.invalidate()

    assert len(autoupdate.candidates(limit=2)) == 2


def test_没有候选时返回空而不是报错(isolated):  # noqa: ARG001
    assert autoupdate.candidates() == []


# ---------------- 运行态与起停 ----------------

def test_禁用后不起线程(monkeypatch):
    """`enabled: false` ⇒ 线程不起（但 `start_background` 本身不负责判这个开关，
    判开关的是调用方 `server._apply_auto_update_config` —— 这里钉 `state()` 的口径）。"""
    monkeypatch.setattr(autoupdate, "_cfg", lambda: {"enabled": False})
    assert autoupdate.state()["enabled"] is False


def test_起停可反复调用(monkeypatch):
    """起 → 停 → 再起：不许因为「已有一个 stop Event」就起不来（updater 同款范式）。"""
    started: list = []

    class _FakeThread:
        def __init__(self, target=None, args=(), name="", daemon=False):
            started.append(name)
            self._alive = True

        def start(self):
            pass

        def is_alive(self):
            return self._alive

        def join(self, timeout=None):
            self._alive = False

    monkeypatch.setattr(autoupdate.threading, "Thread", _FakeThread)
    monkeypatch.setattr(autoupdate, "_cfg", lambda: {"enabled": True, "interval_hours": 1})
    assert autoupdate.start_background() is True
    assert autoupdate.start_background() is False, "已在跑就不该再起一个"
    autoupdate.stop()
    assert autoupdate.start_background() is True, "叫停之后必须能再起"
    autoupdate.stop()
    assert started == ["novelforge-auto-update"] * 2


def test_留档名与_sidecar_口径一致():
    """`<stem>.meta.json` 的拼法是**约定**（与 `manager.write_sidecar` 同口径）：
    改了这里就找不到留档，追更会静默「零候选」。"""
    sidecar = pathlib.PurePosixPath("科幻/三体.meta.json")
    assert sidecar.name[:-len(".meta.json")] == "三体"


# ---------------- 接口（第 86 期 sources-ui 的追更卡要用）----------------

def test_追更状态接口形状(client, auth_headers):  # noqa: ARG001
    """界面要显示「追更中 / 已暂停」⇒ 状态接口必须回 running / enabled / 间隔。"""
    r = client.get("/api/autoupdate", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"running", "enabled", "interval_hours"}
    assert isinstance(body["running"], bool) and isinstance(body["enabled"], bool)


def test_手动追更复用同一段代码(monkeypatch, client, auth_headers):  # noqa: ARG001
    """「立即追更一轮」必须调 `autoupdate.tick`（与定时轮次同一段代码）。

    两套实现必然分叉：定时那套改了「起点怎么算 / 怎么记台账」，手动那套不会跟着改 ——
    而手动是用户最常按的那个按钮（他刚发现少章时就会点）。
    """
    calls: list = []

    def fake_tick(conf=None):
        calls.append(conf)
        return {"total": 0, "ok": 0, "skipped": 0, "errors": 0, "added": 0}

    monkeypatch.setattr(autoupdate, "tick", fake_tick)
    r = client.post("/api/autoupdate/run", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert calls, "手动入口必须走 tick，不许另写一套"
    assert r.json()["total"] == 0


def test_手动追更的失败逐条回报(monkeypatch, client, auth_headers):  # noqa: ARG001
    """单本失败不该让整批失败：报告里 errors 计数，其余照常统计。"""
    monkeypatch.setattr(autoupdate, "tick",
                        lambda conf=None: {"total": 3, "ok": 2, "skipped": 0,
                                           "errors": 1, "added": 5})
    body = client.post("/api/autoupdate/run", headers=auth_headers).json()
    assert body == {"total": 3, "ok": 2, "skipped": 0, "errors": 1, "added": 5}
