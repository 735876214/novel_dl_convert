"""第 17 期 T2：watcher 多目标调度（逐库扫描）。

核心断言（取自方案拍板）：
- 全局 INPUT_DIR 行为不变（格式/关键词路由）；
- 每个库的每个来源文件夹（source_dirs，就地引用）是独立扫描目标，带该库 watch/interval/cron；
- 关掉的库（watch=0）不扫它的来源文件夹；开的库按间隔扫、设 cron 的只在定时窗口扫；
- 坏 cron 退化为 interval，不崩；每库目标扫完回写 last_scan_at（LAST SCAN）。

全部离线、不依赖真 EPUB（扫描只按扩展名收书）。
"""
import pathlib
import time

from novelforge import config, server
from novelforge.core import db, library
from novelforge.core.watcher import FolderWatcher


def _make_watcher(**kw):
    cfg = {"watcher": {"enabled": True, "copy_non_txt": True}}
    cfg["watcher"].update(kw)
    return FolderWatcher(cfg=cfg)


# ---------------------------------------------------------------------------
# 单元层：目标派生 + 调度判定
# ---------------------------------------------------------------------------

def test_derive_targets_honors_per_library_watch(isolated, make_library):
    """关库 (watch=0) 的目标 watch=False；开库与全局 INPUT_DIR 目标 watch=True。"""
    src = config.LIBRARY_SOURCE_DIR
    make_library("open1", "开库", "ebook", src / "open1")
    make_library("closed1", "关库", "ebook", src / "closed1")
    db.update_library("closed1", watch=0)

    w = _make_watcher()
    targets = {t["library_id"]: t for t in w._derive_targets()}

    assert targets["open1"]["watch"] is True
    assert targets["closed1"]["watch"] is False
    # 全局 INPUT_DIR 目标（library_id=None）始终 watch=True（沿用全局 enabled）
    assert targets[None]["watch"] is True
    # 默认库（mixed，来源=OUTPUT_DIR）也会成为一个逐库目标
    assert targets["default"]["watch"] is True


def test_derive_targets_per_library_interval_and_cron(isolated, make_library):
    """逐库目标的 interval / cron 取自该库列；scan_interval=0 时继承全局。"""
    src = config.LIBRARY_SOURCE_DIR
    make_library("lib1", "库1", "ebook", src / "lib1")
    db.update_library("lib1", scan_interval=120, scan_cron="0 3 * * *")

    w = _make_watcher()
    t = next(x for x in w._derive_targets() if x["library_id"] == "lib1")
    assert t["interval"] == 120
    assert t["cron"] == "0 3 * * *"


def test_should_scan_cron_window_and_bad_cron_fallback(isolated):
    """cron 在两次触发之间应判 True；坏 cron 退化为 interval 而不崩。"""
    w = _make_watcher()

    # 每分触发；从未扫过 → 应扫
    tc = {"tkey": "c", "cron": "* * * * *", "interval": 3600, "watch": True}
    w._target_last["c"] = 0.0
    assert w._should_scan(tc) is True
    # 刚扫过（上一分钟触发点还没到）→ 不应扫
    w._target_last["c"] = time.time()
    assert w._should_scan(tc) is False

    # 坏 cron → 退化 interval；interval 很大且刚扫过 → 不应扫，且不抛
    tb = {"tkey": "b", "cron": "不是合法的 cron @@@", "interval": 3600, "watch": True}
    w._target_last["b"] = time.time()
    assert w._should_scan(tb) is False


# ---------------------------------------------------------------------------
# 行为层：实际扫描 + 摄入 + LAST SCAN 回写
# ---------------------------------------------------------------------------

def test_open_library_source_is_scanned_and_writes_last_scan(isolated, make_library, tmp_path):
    """开库（就地引用）的来源文件夹被扫描，文件登记入库，并回写 last_scan_at。"""
    src = config.LIBRARY_SOURCE_DIR
    folder = src / "ebooks"
    make_library("eb1", "电子书", "ebook", folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "测试书.epub").write_bytes(b"EPUB")

    w = _make_watcher()
    w.scan_library_now("eb1")

    assert (folder / "测试书.epub").exists(), "就地引用库的文件应在原地被登记"
    assert db.get_library("eb1")["last_scan_at"] > 0, "应回写 LAST SCAN"


def test_closed_library_source_not_scanned_by_scheduler(isolated, make_library, tmp_path):
    """复刻 _loop 的调度判定：关库（watch=0）的来源文件夹不应被扫（文件留在原地）。"""
    src = config.LIBRARY_SOURCE_DIR
    folder = src / "clsrc"
    make_library("cl1", "关库", "ebook", folder)
    db.update_library("cl1", watch=0)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "不应被收.epub").write_bytes(b"EPUB")

    w = _make_watcher()
    # 与 FolderWatcher._loop 一致的判定：只扫 watch=True 的目标
    for t in w._derive_targets():
        if t["watch"]:
            w._scan_target(t)

    assert (folder / "不应被收.epub").exists(), "关库文件应留在来源目录"


def test_global_input_dir_still_routes_to_a_matching_library(isolated, tmp_path, make_library):
    """全局 INPUT_DIR 的文件仍按「格式」路由到**命中的那个库**。

    第 37 期前这里断的是「落默认库 = OUTPUT_DIR」；默认库没了，但路由本身不变 ——
    换成一个 `ebook` 库来收，验证命中后落的是**它的根**（不是 OUTPUT_DIR）。
    """
    inp = config.INPUT_DIR
    inp.mkdir(parents=True, exist_ok=True)
    (inp / "全局书.epub").write_bytes(b"EPUB")
    lib = make_library("ebook", "电子书库", "ebook", tmp_path / "ebooks")

    w = _make_watcher()
    w.scan_once()  # 只扫全局 INPUT_DIR

    assert (library.roots_of(lib)[0] / "全局书.epub").exists(), \
        "命中了 ebook 库就该落进它的根"


def test_global_input_dir_不收不命中任何库的文件(isolated, tmp_path, make_library):
    """规则不命中 ⇒ **拒收**：文件留在原地、记一次带原因的失败，绝不猜一个库塞进去。

    这是第 37 期新立的规矩（以前会兜底进默认库）。用户选的语义是「库的 rules 就是
    路由表，路由表不命中就不猜」——猜错的话书会进一个没人管的目录，还得手工找回来。
    """
    inp = config.INPUT_DIR
    inp.mkdir(parents=True, exist_ok=True)
    (inp / "没人要.xyz").write_bytes(b"EPUB")   # 扩展名不认识，也不命中任何库的关键词规则
    lib = make_library("ebook", "电子书库", "ebook", tmp_path / "ebooks")

    w = _make_watcher()
    res = w.scan_once()                 # 只扫全局 INPUT_DIR

    assert (inp / "没人要.xyz").exists(), "拒收时**不许**动原文件"
    assert not (library.roots_of(lib)[0] / "没人要.xyz").exists()
    assert res["failed"], "拒收要如实进失败清单，不能静默跳过"
    assert "没有可接收的书库" in res["failed"][0]["error"]


def test_建库后被拒收过的文件会自动重新收走(client, auth_headers, isolated,
                                            monkeypatch, tmp_path):
    """照着提示建完库，原先被拒收的文件应当**自己**就被收进去。

    这条钉的是 `server._libraries_changed()`（= `library.invalidate()` +
    `WATCHER.forget_failures()`）里的后半截。没有它的话，拒收与「重试到上限就
    永久跳过」叠加会变成：用户在提示的指导下建好了库，文件却**再也不被尝试**——
    他只能删了重投一遍。这与「库的 rules 就是路由表」这个语义毫无关系，
    纯属失败计数这个实现的副作用。

    刻意把 `max_retries` 设成 1：第一轮就到达上限，于是「再扫一轮」**不会**重试，
    成败只取决于建库时有没有清计数 —— 否则本用例就算掉了 `forget_failures`
    也会因为「还没到上限、本来就会重试」而误过。
    """
    # 清空书库表：本用例要的是「一个库都没有」这个起点（`isolated` 会建一条）
    for l in library.libraries():
        db.delete_library(l["id"])
    library.invalidate()
    assert library.libraries() == []

    inp = config.INPUT_DIR
    inp.mkdir(parents=True, exist_ok=True)
    (inp / "后来才有人要.epub").write_bytes(b"EPUB")

    w = _make_watcher(max_retries=1)
    # 让 API 侧的书库增删改作用在**这个**实例上（否则钩子清的是另一个 watcher 的账）
    monkeypatch.setattr(server, "WATCHER", w)

    assert w.scan_once()["failed"], "前置：没有库时应当拒收"
    assert not w.scan_once()["failed"], "前置：到上限后就不该再试 —— 否则本用例不成立"

    root = config.LIBRARY_SOURCE_DIR / "ebooks"
    r = client.post("/api/libraries", headers=auth_headers,
                    json={"name": "电子书库", "type": "ebook",
                          "source_dirs": [str(root)]})
    assert r.status_code == 200, r.text

    res = w.scan_once()
    assert res["added"] or res["converted"], f"建库后应被收走，实际 {res}"
    assert (root / "后来才有人要.epub").exists(), "应当落进新建那条库的根"
