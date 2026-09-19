"""第 24 期：入库自动抓取放开到漫画 / 有声书。

核心断言（取自方案拍板）：
- `auto_fetch_async` 的 guard 从「只 .epub」放开为 allow-list（epub/mobi/azw3/pdf/fb2/cbz/cbr），
  目录型有声书靠 `kind="audiobook"` 显式放行；名字无后缀的散落文件（.jpg 等）不抓；
- 漫画库（source_subdir 摄入 .cbz）与有声书库（摄入音频目录）在开启 `auto_on_import` 时，
  入库会真正触发 `metafetch.auto_fetch`；
- 仍受 `metadata_fetch.enabled` + `auto_on_import` 双重门控，关掉则不触发（默认行为零变化）。

全部离线：用 monkeypatch 替换 `metafetch.auto_fetch`，只断言「名字抵达 metafetch」，不真联网。
后台线程纪律：派生线程由 `watcher.wait_pending` 在 `isolated` 夹具里收干净（见 conftest）。
"""
import novelforge.core.metafetch as metafetch_mod
from novelforge import config
from novelforge.core import db, lib_settings
from novelforge.core.watcher import FolderWatcher, auto_fetch_async


def _make_watcher(**kw):
    cfg = {"watcher": {"enabled": True, "copy_non_txt": True}}
    cfg["watcher"].update(kw)
    return FolderWatcher(cfg=cfg)


def _patch_auto_fetch(monkeypatch):
    calls = []
    def fake(name, cfg=None, limit=3):
        calls.append(name)
        return {"ok": True, "fields": [], "cover": False}
    monkeypatch.setattr(metafetch_mod, "auto_fetch", fake)
    return calls


# ---------------------------------------------------------------------------
# 单元层：guard 的 allow-list + kind 放行
# ---------------------------------------------------------------------------

def test_auto_fetch_async_allowlist_and_kind(monkeypatch):
    """可抓格式触发；散落文件（.jpg）/ 原始 .txt 不触发；有声书靠 kind 放行。"""
    calls = _patch_auto_fetch(monkeypatch)
    cfg = {"metadata_fetch": {"enabled": True, "auto_on_import": True}}

    for n in ["a.epub", "b.cbz", "c.cbr", "d.pdf", "e.fb2", "f.mobi", "g.azw3"]:
        auto_fetch_async(n, cfg)
    auto_fetch_async("Series/我的有声书", cfg, kind="audiobook")
    # 不应触发：散落文件 + 原始 txt（txt 转换后才是 .epub，原始 .txt 不会传进来）
    auto_fetch_async("stray.jpg", cfg)
    auto_fetch_async("note.txt", cfg)
    # 有声书若漏传 kind，名字无后缀也要被拦（不能靠后缀放行）
    auto_fetch_async("Series/我的有声书", cfg)

    from novelforge.core import watcher
    watcher.wait_pending(5.0)

    assert set(calls) == {
        "a.epub", "b.cbz", "c.cbr", "d.pdf", "e.fb2", "f.mobi", "g.azw3",
        "Series/我的有声书",
    }


def test_auto_fetch_async_respects_gate(monkeypatch):
    """未开 enabled 或 auto_on_import 时，即使可抓格式也不触发。"""
    calls = _patch_auto_fetch(monkeypatch)
    # 两者都关
    auto_fetch_async("x.cbz", {"metadata_fetch": {"enabled": False, "auto_on_import": False}})
    # 只开 enabled
    auto_fetch_async("x.cbz", {"metadata_fetch": {"enabled": True, "auto_on_import": False}})
    # 只开 auto_on_import
    auto_fetch_async("x.cbz", {"metadata_fetch": {"enabled": False, "auto_on_import": True}})
    # 有声书缺 kind 也不该绕过门控
    auto_fetch_async("Series/书", {"metadata_fetch": {"enabled": False, "auto_on_import": False}},
                     kind="audiobook")

    from novelforge.core import watcher
    watcher.wait_pending(5.0)
    assert calls == []


# ---------------------------------------------------------------------------
# 行为层：漫画库 / 有声书库扫描摄入确实触发 auto_fetch
# ---------------------------------------------------------------------------

def test_comic_library_scan_triggers_auto_fetch(isolated, make_library, monkeypatch):
    """漫画库 source_subdir 摄入 .cbz，开启 auto_on_import → 触发 metafetch.auto_fetch。"""
    calls = _patch_auto_fetch(monkeypatch)
    monkeypatch.setattr("novelforge.core.scrape.enabled", lambda lid: False)  # 隔离：本测试只验 auto_fetch
    src = config.LIBRARY_SOURCE_DIR
    storage = config.OUTPUT_DIR
    make_library("comic1", "漫画库", "comic", storage, mode="import", source_subdir="comics")
    lib_settings.set_overrides("comic1", {
        "metadata_fetch.enabled": True,
        "metadata_fetch.auto_on_import": True,
    })
    (src / "comics").mkdir(parents=True, exist_ok=True)
    (src / "comics" / "测试漫画.cbz").write_bytes(b"CBZ")

    w = _make_watcher()
    w.scan_library_now("comic1")
    from novelforge.core import watcher
    watcher.wait_pending(5.0)

    assert any("测试漫画.cbz" in c for c in calls), f"漫画入库应触发 auto_fetch，实际调用：{calls}"


def test_audiobook_library_scan_triggers_auto_fetch(isolated, make_library, make_audio_dir, monkeypatch):
    """有声书库摄入音频目录，开启 auto_on_import → 触发 metafetch.auto_fetch（kind=audiobook）。"""
    calls = _patch_auto_fetch(monkeypatch)
    monkeypatch.setattr("novelforge.core.scrape.enabled", lambda lid: False)  # 隔离：本测试只验 auto_fetch
    src = config.LIBRARY_SOURCE_DIR
    storage = config.OUTPUT_DIR
    make_library("audio1", "有声书库", "audiobook", storage, mode="import", source_subdir="audios")
    lib_settings.set_overrides("audio1", {
        "metadata_fetch.enabled": True,
        "metadata_fetch.auto_on_import": True,
    })
    make_audio_dir(src / "audios", "我的有声书", tracks=2)

    w = _make_watcher()
    w.scan_library_now("audio1")
    from novelforge.core import watcher
    watcher.wait_pending(5.0)

    assert any("我的有声书" in c for c in calls), f"有声书入库应触发 auto_fetch，实际调用：{calls}"


def test_auto_fetch_not_triggered_when_disabled(isolated, make_library, monkeypatch):
    """未开 auto_on_import 时，漫画入库不触发（默认行为零变化）。"""
    calls = _patch_auto_fetch(monkeypatch)
    src = config.LIBRARY_SOURCE_DIR
    storage = config.OUTPUT_DIR
    make_library("comic2", "漫画库2", "comic", storage, mode="import", source_subdir="comics2")
    (src / "comics2").mkdir(parents=True, exist_ok=True)
    (src / "comics2" / "不抓的漫画.cbz").write_bytes(b"CBZ")

    w = _make_watcher()
    w.scan_library_now("comic2")
    from novelforge.core import watcher
    watcher.wait_pending(5.0)

    assert calls == [], f"未开 auto_on_import 不应触发，实际：{calls}"
