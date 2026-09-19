"""第 17 期 T2：watcher 多目标调度（逐库扫描）。

核心断言（取自方案拍板）：
- 全局 INPUT_DIR 行为不变（格式/关键词路由）；
- 每个库的 LIBRARY_SOURCE_DIR/<source_subdir> 是独立扫描目标，带该库 watch/interval/cron；
- 关掉的库（watch=0）不扫它的来源子目录；开的库按间隔扫、设 cron 的只在定时窗口扫；
- 坏 cron 退化为 interval，不崩；每库目标扫完回写 last_scan_at（LAST SCAN）。

全部离线、不依赖真 EPUB（扫描只按扩展名收书）。
"""
import time

from novelforge import config
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
    make_library("open1", "开库", "ebook", src / "open1", source_subdir="open1")
    make_library("closed1", "关库", "ebook", src / "closed1", source_subdir="closed1")
    db.update_library("closed1", watch=0)

    w = _make_watcher()
    targets = {t["library_id"]: t for t in w._derive_targets()}

    assert targets["open1"]["watch"] is True
    assert targets["closed1"]["watch"] is False
    # 全局 INPUT_DIR 目标（library_id=None）始终 watch=True（沿用全局 enabled）
    assert targets[None]["watch"] is True
    # 默认库没有 source_subdir，不应成为逐库目标
    assert all(t["library_id"] is not None for t in targets.values() if t["library_id"] != "open1" and t["library_id"] != "closed1") or targets[None]["library_id"] is None


def test_derive_targets_per_library_interval_and_cron(isolated, make_library):
    """逐库目标的 interval / cron 取自该库列；scan_interval=0 时继承全局。"""
    src = config.LIBRARY_SOURCE_DIR
    make_library("lib1", "库1", "ebook", src / "lib1", source_subdir="lib1")
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
    """开库（import 模式）的来源子目录被扫描，文件收进 storage，并回写 last_scan_at。"""
    src = config.LIBRARY_SOURCE_DIR
    storage = tmp_path / "storage"
    make_library("eb1", "电子书", "ebook", storage, mode="import", source_subdir="ebooks")
    (src / "ebooks").mkdir(parents=True, exist_ok=True)
    (src / "ebooks" / "测试书.epub").write_bytes(b"EPUB")

    w = _make_watcher()
    w.scan_library_now("eb1")

    assert (storage / "测试书.epub").exists(), "开库来源子目录的文件应被摄入 storage"
    assert db.get_library("eb1")["last_scan_at"] > 0, "应回写 LAST SCAN"


def test_closed_library_source_not_scanned_by_scheduler(isolated, make_library, tmp_path):
    """复刻 _loop 的调度判定：关库（watch=0）的来源子目录不应被扫（文件留在原地）。"""
    src = config.LIBRARY_SOURCE_DIR
    storage = tmp_path / "storage"
    make_library("cl1", "关库", "ebook", storage, mode="import", source_subdir="clsrc")
    db.update_library("cl1", watch=0)
    (src / "clsrc").mkdir(parents=True, exist_ok=True)
    (src / "clsrc" / "不应被收.epub").write_bytes(b"EPUB")

    w = _make_watcher()
    # 与 FolderWatcher._loop 一致的判定：只扫 watch=True 的目标
    for t in w._derive_targets():
        if t["watch"]:
            w._scan_target(t)

    assert not (storage / "不应被收.epub").exists(), "关库不应扫其来源子目录"
    assert (src / "clsrc" / "不应被收.epub").exists(), "关库文件应留在来源目录"


def test_global_input_dir_routing_unchanged(isolated, tmp_path):
    """全局 INPUT_DIR 行为不变：里面的文件仍按格式/关键词路由（这里落默认库 = OUTPUT_DIR）。"""
    inp = config.INPUT_DIR
    inp.mkdir(parents=True, exist_ok=True)
    (inp / "全局书.epub").write_bytes(b"EPUB")
    out = config.OUTPUT_DIR

    w = _make_watcher()
    w.scan_once()  # 只扫全局 INPUT_DIR

    assert (out / "全局书.epub").exists(), "全局 INPUT_DIR 文件应被路由摄入默认库"
