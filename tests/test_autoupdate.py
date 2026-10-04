"""追更的后台调度（第 86 期最后一项）。

这里只钉**调度口径**（零网络、零外呼）—— 追更本身的正确性在
`tests/test_update_report.py`（只追加 / 既有条目一字不动 / 起点不靠章名）。

⚠️ 真机验证仍缺（本机没有真实可跑的书源），与本期其它下载链路同口径如实标注。

第 93 期补：单本追更的**唯一入口** `update_book`（定时轮次 / 详情页「检查更新」/ 自动落地
之后的更新都走它）—— 读留档、过闸门、记日志三件事的收敛点。闸门在 `tick` 层面的
整体行为（拦得住 / 放得行 / 两种「0 章」分得开）在 `tests/test_autoupdate_gate.py`。
"""
import pathlib
import threading

import pytest

from novelforge import config
from novelforge.core import autoupdate, library


def _mk_book(root, stem: str, *, sidecar: bool = True) -> dict:
    """造一本**有留档**的书并返回它的书目条目（`library.books()` 里的那一条）。

    ⚠️ 成品（epub）落**书库根**、留档（`<名>.meta.json`）落**收书目录**（`config.INPUT_DIR`）
    —— 这正是下载链路的真实布局（`download_to(item, out_dir, input_dir, opts)`），
    也是第 93 期修掉的那个真 bug 的现场：两边放同一个目录时，「按书库根找留档」也会绿。
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{stem}.epub").write_bytes(b"PK")
    if sidecar:
        inp = pathlib.Path(config.INPUT_DIR)
        inp.mkdir(parents=True, exist_ok=True)
        (inp / f"{stem}.meta.json").write_text(
            '{"source": "stub", "chapters": 1}', encoding="utf-8")
    library.invalidate()
    return next(b for b in library.books() if b["name"] == f"{stem}.epub")


class _FakeMgr:
    """只会回答闸门的假下载器（本文件不外呼，`update_report` 也不该被调到）。"""

    cfg: dict = {}

    def __init__(self, reason: str = ""):
        self._reason = reason

    def gate_reason(self, source=None, feature="download"):  # noqa: ARG002
        return self._reason


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
    """候选 = **原件旁边**有同名 `.meta.json` 的那些（sidecar 是「下载来的」唯一持久痕迹）。

    ⚠️ 第 93 期之前这条用例把留档写在**书库根**（与成品同目录）—— 那是**错的现场**：
    真实下载链路把留档写在收书目录（原件旁边），所以照旧写法算出来的候选在正常部署下
    **一本都没有**，而用例照样绿。现在留档落在 `config.INPUT_DIR`（`_mk_book` 的口径），
    「手写书」那条不造留档 —— 两者都在**同一个**书库根里，唯一的差别就是留档在不在。
    """
    _mk_book(default_root, "有留档")
    _mk_book(default_root, "手写书", sidecar=False)

    got = {c["sidecar"].name for c in autoupdate.candidates()}
    assert "有留档.meta.json" in got
    assert "手写书.meta.json" not in got, "没有留档的书不是追更对象"


def test_留档要在收书目录里找(isolated, default_root):  # noqa: ARG001
    """**按书库根找留档 = 一本都找不到**（第 93 期修的真 bug，这里反向钉住）。

    这条用例的现场就是「正常部署」：成品在书库根、留档在收书目录，**两个不同的目录**。
    第 86 期按书库根算 ⇒ 追更永远零候选（与「`DownloadManager()` 少传 cfg」合起来，
    定时追更整条链从来没跑起来过，且两处都不报错）。
    """
    _mk_book(default_root, "三体")
    # 同一个文件名的留档**放在书库根**（旧口径的位置）：它不该被认作候选
    (default_root / "三体.meta.json").write_text('{"source":"旧位置"}', encoding="utf-8")

    c = autoupdate.candidates()[0]
    assert c["sidecar"].parent == pathlib.Path(config.INPUT_DIR)
    assert c["sidecar"].parent != default_root


def test_候选带得上书与留档名(isolated, default_root):  # noqa: ARG001
    """候选**不是一串路径**（第 93 期改成 `{"name", "sidecar", "book"}`）：逐本追更要按
    **书**走（`update_book(book)` —— 闸门入参「来自哪个源」与日志都要看留档，
    而「这本书是哪一条书目」只有书目本身知道），路径只是它的一个字段。"""
    _mk_book(default_root, "三体")

    c = autoupdate.candidates()[0]
    assert c["name"] == "三体" and c["sidecar"].name == "三体.meta.json"
    assert c["book"]["name"] == "三体.epub"
    assert autoupdate.sidecar_of(c["book"]) == c["sidecar"], "两处拼法必须是同一个"


def test_单轮上限生效(isolated, default_root):  # noqa: ARG001
    """`max_books` 是硬上限：一次外呼不许打爆（宁可下一轮再追剩下的）。"""
    for i in range(5):
        _mk_book(default_root, f"书{i}")

    assert len(autoupdate.candidates(limit=2)) == 2


def test_没有候选时返回空而不是报错(isolated):  # noqa: ARG001
    assert autoupdate.candidates() == []


# ---------------- 单本追更的唯一入口（第 93 期）----------------

def test_单本追更_没留档就如实报错(isolated, default_root):  # noqa: ARG001
    """没有留档的文件名要**点出来** —— 「更新失败」四个字帮不了任何人。"""
    default_root.mkdir(parents=True, exist_ok=True)
    (default_root / "手写书.epub").write_bytes(b"PK")
    library.invalidate()
    book = next(b for b in library.books() if b["name"] == "手写书.epub")

    with pytest.raises(ValueError) as err:
        autoupdate.update_book(book, _FakeMgr())

    assert "手写书.meta.json" in str(err.value), err.value


def test_单本追更_闸门不过就不外呼也不伪造报告(isolated, default_root, monkeypatch):  # noqa: ARG001
    """闸门未放行 ⇒ 抛 `Blocked`（原文照传），**绝不**返回一份「新增 0 章」。

    两种 0 章必须分得开：一个是「源上没有新章」（状态），一个是「你关着开关」（指令）。
    调用方（详情页的「检查更新」）要把后者原样显示成 400 的原因。
    """
    book = _mk_book(default_root, "三体")
    called: list = []
    monkeypatch.setattr(autoupdate, "_run_one", lambda m, t: called.append(t))

    with pytest.raises(autoupdate.Blocked) as err:
        autoupdate.update_book(book, _FakeMgr("下载功能未开启：到「设置 → 网络与下载」打开"))

    assert "下载功能未开启" in str(err.value)
    assert called == [], "闸门拦下了还去追更 —— 那就是假开关"


def test_单本追更_成功时记一笔带章数的账(isolated, default_root, monkeypatch):  # noqa: ARG001
    """活动日志的写点收敛到这里之后，措辞只有一份（定时轮次与手动检查更新共用）。"""
    book = _mk_book(default_root, "三体")
    logged: list = []
    monkeypatch.setattr(autoupdate.activity_log, "log",
                        lambda *a, **kw: logged.append((a, kw)))
    monkeypatch.setattr(autoupdate, "_run_one", lambda m, t: {"added": 2, "note": ""})

    res = autoupdate.update_book(book, _FakeMgr(), origin="check-update")

    assert res["added"] == 2
    assert len(logged) == 1, logged
    args, kw = logged[0]
    assert args[0] == autoupdate.activity_log.ACTION_UPDATE
    assert args[1] == "三体", "账上要点名是哪一本"
    assert args[2] == autoupdate.activity_log.STATUS_OK
    assert "新增 2 章" in kw["detail"]
    assert kw["source"] == "check-update", "来源要能区分定时轮次与手动检查"


def test_单本追更_失败记一笔再原样冒出(isolated, default_root, monkeypatch):  # noqa: ARG001
    """单本失败要**留下账**再冒出去：`tick` 靠异常计数，调用方靠异常给原因，两者都要。"""
    book = _mk_book(default_root, "三体")
    logged: list = []
    monkeypatch.setattr(autoupdate.activity_log, "log",
                        lambda *a, **kw: logged.append((a, kw)))

    def boom(m, t):
        raise RuntimeError("站点炸了")

    monkeypatch.setattr(autoupdate, "_run_one", boom)

    with pytest.raises(RuntimeError):
        autoupdate.update_book(book, _FakeMgr())

    assert len(logged) == 1 and logged[0][1]["detail"] == "追更失败：站点炸了", logged
    assert logged[0][0][2] == autoupdate.activity_log.STATUS_FAIL


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


def test_留档名与_sidecar_口径一致(monkeypatch):
    """`<stem>.meta.json` 的拼法与**所在目录**是**约定**（与 `manager.write_sidecar` 同口径）：
    改了这里就找不到留档，追更会静默「零候选」。

    第 93 期起这条约定只剩**一处实现**（`autoupdate.sidecar_of`），所以这里直接钉它，
    不再由用例自己算一遍 —— 用例里复刻一份「同一个约定」正是两处漂移的起点。
    """
    monkeypatch.setattr(config, "INPUT_DIR", pathlib.Path("/in"))
    assert autoupdate.sidecar_of(
        {"name": "三体.epub"}) == pathlib.Path("/in/三体.meta.json")

    # 算不出来时返回 None（调用方据此如实说「这本书没有留档」，而不是编一个路径出来）
    assert autoupdate.sidecar_of({"name": ""}) is None
    assert autoupdate.sidecar_of({}) is None


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
