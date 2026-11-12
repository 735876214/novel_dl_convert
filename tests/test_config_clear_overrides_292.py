"""清除设置覆盖层：并发读句柄下不能偶发 500（第 292 期）。

`DELETE /api/config/overrides` 以前直接 `SETTINGS_FILE.unlink()` —— 既不拿
`config._OVERRIDES_LOCK`，也没有短退避重试。Windows 上任何并发读句柄
（`load_overrides` 在另一个线程 / 进程里刚打开文件）都会让删除失败：

    WinError 32 另一个程序正在使用此文件，进程无法访问。

全量测试中段实测偶发一次（`test_clear_overrides_热应用` 500）。修法是把它收敛到
`config.clear_overrides()`：持锁 + `_unlink_with_retry`（与 `save_overrides` 同一套口径）。

⚠️ Linux 允许 `unlink` 一个仍被打开的文件，所以「占用 ⇒ 失败」只在本机（Windows）可验；
「短暂占用 ⇒ 重试后成功」在两端都能验（Linux 上它本来就立即成功，不会假红）。
"""
from __future__ import annotations

import sys
import threading
import time

import pytest

from novelforge import config


@pytest.fixture()
def settings_file(tmp_path, monkeypatch):
    p = tmp_path / "settings.json"
    p.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_FILE", p)
    return p


def test_清除覆盖层_幂等(settings_file) -> None:
    config.clear_overrides()
    assert not settings_file.exists()
    # 再删一次不该抛（文件已不存在）
    config.clear_overrides()


def test_短暂读占用_重试后成功(settings_file) -> None:
    """另一个句柄先打开 0.1 s 再关 —— 重试窗口必须覆盖它。"""
    f = open(settings_file, "rb")
    timer = threading.Timer(0.1, f.close)
    timer.start()
    try:
        started = time.time()
        config.clear_overrides()
        elapsed = time.time() - started
    finally:
        timer.join()
        if not f.closed:
            f.close()
    assert not settings_file.exists()
    if sys.platform == "win32":
        # 证明真的等过（不是恰好没撞上）—— Linux 上 unlink 不阻塞，不做此断言
        assert elapsed >= 0.05, f"没有等待就直接删掉了？elapsed={elapsed:.3f}s"


@pytest.mark.skipif(sys.platform != "win32",
                    reason="Windows 的删除占用语义（Linux 允许 unlink 打开中的文件）")
def test_永久占用_如实失败不静默(settings_file) -> None:
    """删不掉必须抛（接口据此回 500），不能假装清空了。"""
    with open(settings_file, "rb"):
        with pytest.raises(OSError):
            config.clear_overrides()
    assert settings_file.exists()
