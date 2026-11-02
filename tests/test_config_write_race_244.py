"""设置覆盖层的**读写撞车**（第 244 期，Windows 特有）。

## 现象

全量里偶发两条红（`test_komga_credentials_163` / `test_opds_library`），报的是

```
PermissionError: [WinError 5] 拒绝访问:
  .../config/settings.json.tmp -> .../config/settings.json
```

即 `config.save_overrides` 的**原子替换**失败。

## 根因

Windows 上 `os.replace` 的**目标**文件若正被另一个句柄打开（哪怕只是另一个线程
在读），会直接报 `WinError 5`。而 `load_overrides()` **不持锁** ⇒
`load_config()`（每个读配置的地方都走它）与 `save_overrides()` 的替换撞车时，
保存直接失败（用户看到「设置写入失败」）。

## 修法（两处，缺一不可）

1. `_OVERRIDES_LOCK` 改成 **`RLock`**，并让**读**也持锁 ⇒ 同进程内读写互斥。
   （普通 `Lock` 会让 `mutate_overrides` 持锁后再调 `load_overrides` 自锁死。）
2. `os.replace` 加**短退避重试**（`_replace_with_retry`）⇒ 外部进程
   （另一个容器 / 另一个 uvicorn worker / 备份脚本）瞬时占用时也能成。
"""
from __future__ import annotations

import json
import os
import pathlib

import pytest

from novelforge import config


def test_读的时候不撞上替换(isolated, tmp_path):
    """读（`load_overrides`）与写（`save_overrides`）必须互斥。"""
    config.save_overrides({"watcher": {"interval": 7.0}})
    assert config.load_overrides()["watcher"]["interval"] == 7.0


def test_替换撞上瞬时占用要重试(isolated, monkeypatch):
    """`os.replace` 前两次被占（WinError 5）⇒ 应当重试后成功，而不是直接失败。"""
    real_replace = os.replace
    calls = {"n": 0}

    def flaky(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise OSError(5, "拒绝访问")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(config.os, "replace", flaky)
    config.save_overrides({"a": 1})
    assert calls["n"] == 3, calls
    assert config.load_overrides()["a"] == 1


def test_替换一直失败要抛出来(isolated, monkeypatch):
    """一直失败 ⇒ 原样抛（不静默 —— 「设置写不进」是本项目最忌讳的事）。"""
    def always_fail(src, dst, *a, **k):
        raise OSError(5, "拒绝访问")

    monkeypatch.setattr(config.os, "replace", always_fail)
    with pytest.raises(OSError):
        config.save_overrides({"a": 1})


def test_锁是可重入的(isolated):
    """`mutate_overrides` 持锁时调 `load_overrides` 不能自锁死。"""
    # 这条若锁不是 RLock，会直接死锁（用例超时）。
    out = config.mutate_overrides(lambda ov: {**ov, "x": 1})
    assert out["x"] == 1
    assert config.load_overrides()["x"] == 1
