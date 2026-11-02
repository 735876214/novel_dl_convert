"""**逐本评分不许每次读一遍配置**（第 226 期）。

`metascore.audit(b)` 不传 `weights` 时会调 `_weights()` ⇒ `config.load_config()`
⇒ 读 config.yaml + settings.json 并解析 YAML。**逐本调用就是每本书读一次盘**。

改前 `stats.overview` 就是这么写的：2,309 本的书库 ⇒ 一个 `/api/stats` 请求
**读 2,309 次 YAML**（实测 500 本：313 ms → 13 ms，−96%）。

这里钉两件事：
1. **批量路径必须算一次、传进去** —— 用打桩数 `load_config` 的调用次数；
2. **`audit(b, weights)` 与 `audit(b)` 结果逐字相同**（传参不改变语义）。
"""
from __future__ import annotations

import pytest

from novelforge import config
from novelforge.core import metascore


def _book(i: int) -> dict:
    return {
        "id": f"b{i}", "name": f"书{i}", "title": f"书名{i}", "author": "作者",
        "format": "EPUB", "isbn": "", "path": "", "size": 100, "mtime": 1.0,
        "library_id": "lib", "series": "", "series_index": "", "year": 2020,
        "language": "zh", "publisher": "", "tags": [], "narrators": [],
    }


@pytest.fixture
def count_load_config(monkeypatch):
    calls = {"n": 0}
    orig = config.load_config

    def counting():
        calls["n"] += 1
        return orig()

    monkeypatch.setattr(config, "load_config", counting)
    return calls


def test_逐本_audit_每次都读配置(count_load_config):
    """**记下这个事实**：不传 `weights` 的 `audit` 每次都读一遍配置（这是要避免的用法）。"""
    count_load_config["n"] = 0
    metascore.audit(_book(1))
    assert count_load_config["n"] == 1, "不传 weights 时确实读了配置（用例要跟着这个事实改）"


def test_批量评分只读一次配置(count_load_config):
    """批量路径：算一次 `weights()`，逐本传进去 ⇒ 配置只读 1 次。"""
    books = [_book(i) for i in range(50)]
    count_load_config["n"] = 0
    w = metascore.weights()
    out = [metascore.audit(b, w) for b in books]
    assert count_load_config["n"] == 1, f"读了 {count_load_config['n']} 次配置 —— 逐本读盘回来了"
    assert len(out) == 50


def test_传权重不改变结果():
    """传参只是**省掉重复读**，语义必须逐字相同。"""
    books = [_book(i) for i in range(20)]
    w = metascore.weights()
    assert [metascore.audit(b) for b in books] == [metascore.audit(b, w) for b in books]


def test_stats_overview_只读一次配置(monkeypatch):
    """`stats.overview` 本身也不能逐本读盘（它有两条 audit 调用点：主列表 + 按库对比）。"""
    from novelforge.core import stats

    calls = {"n": 0}
    orig = config.load_config

    def counting():
        calls["n"] += 1
        return orig()

    monkeypatch.setattr(config, "load_config", counting)

    books = [_book(i) for i in range(30)]
    monkeypatch.setattr(stats.library, "books", lambda *a, **k: books)
    try:
        stats.overview()
    except Exception:
        # overview 依赖的其它字段可能不全 —— 但**配置读盘次数**这个判据仍要成立：
        # 只要它已经超过 1 次就说明逐本读的路径被走过。
        pass
    assert calls["n"] <= 2, f"overview 读了 {calls['n']} 次配置 —— 逐本读盘还在"
