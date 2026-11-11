"""定时扫描 cron：写入口校验 + 退化时的留痕（第 282 期）。

审计实测（修前）：把某库的 `scan_cron` 写成「每天 4 点」——

```
目标 interval = 5.0   cron = '每天 4 点'
  上次扫描在 0s 前 -> should_scan = False
  上次扫描在 6s 前 -> should_scan = True     ← 按全局 5 秒间隔狂扫
last_scan_note = '扫描 1 项'                 ← 没有说明
watcher.last_error = ''                      ← 也没有
```

而设置页写的是「错误只记在扫描备注里」。两个问题：

1. **写入口不校验** ⇒ 用户以为设的是「每天 4 点」，实际是**每 5 秒扫一次**；
2. 退化**无声** ⇒ 界面承诺的「扫描备注」里什么都没有。

修法：
- `watcher.cron_problem()` 是唯一判据 —— 建库 / 改库用它拒绝坏表达式（400 + 人话）；
- 调度线程用它判退化：每个目标只写一条 warning（5 s 一轮，不能刷屏），原因留在
  `_cron_problems`，下次扫描拼进该库的 `last_scan_note`；表达式改好后自动清掉。
"""
import pathlib
import time

from novelforge import config
from novelforge.core import db
from novelforge.core.watcher import FolderWatcher, cron_problem


def _watcher() -> FolderWatcher:
    return FolderWatcher(cfg={"watcher": {"enabled": True, "copy_non_txt": True}})


def _src(name: str) -> pathlib.Path:
    return pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / name


def _target(w: FolderWatcher, lid: str) -> dict:
    return next(x for x in w._derive_targets() if x["library_id"] == lid)


def test_cron_problem_是唯一判据():
    assert cron_problem("") == ""
    assert cron_problem("   ") == ""
    for ok in ("0 4 * * *", "*/5 * * * *", "0 */6 * * *", "0 3 * * 0"):
        assert cron_problem(ok) == "", ok
    for bad in ("每天 4 点", "0 4 * * * *", "* * *", "61 * * * *", "@daily"):
        assert cron_problem(bad) != "", bad


def test_建库与改库都拒绝坏表达式(client, auth_headers):
    src = _src("cron-lib")
    src.mkdir(parents=True, exist_ok=True)

    r = client.post("/api/libraries", headers=auth_headers,
                    json={"name": "坏cron", "type": "ebook",
                          "source_dirs": [str(src)], "scan_cron": "每天 4 点"})
    assert r.status_code == 400, r.text
    assert "定时扫描表达式无效" in r.json()["detail"], r.text

    r = client.post("/api/libraries", headers=auth_headers,
                    json={"name": "好cron", "type": "ebook",
                          "source_dirs": [str(src)], "scan_cron": "0 4 * * *"})
    assert r.status_code == 200, r.text
    lid = r.json()["library"]["id"]

    r = client.patch(f"/api/libraries/{lid}", headers=auth_headers,
                     json={"scan_cron": "0 4 * * * *"})       # 6 段
    assert r.status_code == 400, r.text
    assert db.get_library(lid)["scan_cron"] == "0 4 * * *", "坏值不许写进库"


def test_坏表达式退化并按扫描备注说明(isolated, make_library):
    src = _src("badcron")
    make_library("bad", "坏 cron 库", "ebook", src)
    db.update_library("bad", scan_interval=0, scan_cron="每天 4 点")

    w = _watcher()
    t = _target(w, "bad")
    assert t["interval"] == 5.0, "scan_interval=0 应继承全局 5s"
    w._target_last[t["tkey"]] = time.time() - 6
    assert w._should_scan(t) is True, "坏表达式应退化为按间隔扫描"
    assert "5 段" in w._cron_problems[t["tkey"]]

    src.mkdir(parents=True, exist_ok=True)
    (src / "x.epub").write_bytes(b"EPUB")
    w.scan_library_now("bad")
    note = db.get_library("bad")["last_scan_note"]
    assert "定时表达式无效" in note and "5 段" in note, note


def test_表达式改好后备注不再带错误(isolated, make_library):
    src = _src("fixcron")
    make_library("fix", "修好的库", "ebook", src)
    db.update_library("fix", scan_cron="不是 cron")

    w = _watcher()
    t = _target(w, "fix")
    w._target_last[t["tkey"]] = 0.0
    assert w._should_scan(t) is True
    w.scan_library_now("fix")
    assert "定时表达式无效" in db.get_library("fix")["last_scan_note"]

    db.update_library("fix", scan_cron="0 4 * * *")
    t2 = _target(w, "fix")
    w._target_last[t2["tkey"]] = 0.0
    assert w._should_scan(t2) is True
    w.scan_library_now("fix")
    assert "定时表达式无效" not in db.get_library("fix")["last_scan_note"]
