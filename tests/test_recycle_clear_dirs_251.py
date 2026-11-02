"""**清空回收站**要连**目录**一起清掉（第 251 期）。

## 缺陷

回收站里**确实会有目录** —— `core/publish.py` 的 `recycle()` 用 `shutil.move`，
删库时回收的是**整个目录**。

而清空端点此前是：

```python
for p in list(d.rglob("*")):
    if not p.is_file():
        continue          # ← 目录被整个跳过
    p.unlink()
```

⇒ 目录里的文件被删（rglob 递归），**空目录壳留着**；而台账照常被清 ⇒
那些空目录成了「无台账孤儿」⇒ 界面说「已清空、释放 N B」，**实际有残留** ——
回收站是「删除即回收」承诺的**最后一道防线**（第 141 期刚修过同一类问题：
「删不掉的必须如实回报、台账不能一起清空」）。

## 这里钉三件事

1. **目录也要被清掉**（连同里面的文件）；
2. **计数是「条目」**（文件 + 目录各算一个）—— 不是「文件数」（否则目录里的文件会被数两遍）；
3. 清空后回收目录**真的空了**（`iterdir()` 为空）。
"""
from __future__ import annotations

import pathlib
import shutil

import pytest

from novelforge.core import fileops, publish

API_CLEAR = "/api/maintenance/recycle/clear"


@pytest.fixture(autouse=True)
def _clean_recycle():
    """每个用例前后把回收目录清空（含**目录**）。

    ⚠️ 回收目录是**整个测试会话共用**的（`isolated` 只隔离目录树）⇒ 留下的东西
    会被别的用例的「删掉 N 个、留 M 个」断言带跑。
    """
    d = fileops.recycle_dir()
    for p in sorted(d.rglob("*"), reverse=True):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink()
    yield
    for p in sorted(d.rglob("*"), reverse=True):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink()


def _put_back_dir(name: str = "一个目录") -> pathlib.Path:
    """在回收目录里造一个**目录**（带一个文件），并登记进台账。

    用 `publish.recycle` 走**真实**路径（它就是删库时回收整个目录的那条路）。
    """
    src = fileops.recycle_dir().parent / "待回收的目录"
    src.mkdir(parents=True, exist_ok=True)
    (src / "里面的.txt").write_text("x", encoding="utf-8")
    moved = publish.recycle(str(src), why="测试：回收一个目录")
    assert moved is not None, "回收失败"
    assert pathlib.Path(moved).is_dir(), f"回收落点应当是目录：{moved}"
    return pathlib.Path(moved)


def test_清空回收站_目录也要被清掉(client, auth_headers, isolated):
    d = fileops.recycle_dir()
    _put_back_dir()
    assert any(p.is_dir() for p in d.iterdir()), "前置不成立：回收目录里没有目录"

    r = client.post(API_CLEAR, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body
    leftovers = list(d.iterdir())
    assert not leftovers, f"回收目录没清空：{[p.name for p in leftovers]}"


def test_清空回收站_计数是条目数(client, auth_headers, isolated):
    """一个目录 = **一个**条目（不是「里面的文件数」）。"""
    d = fileops.recycle_dir()
    _put_back_dir()
    r = client.post(API_CLEAR, headers=auth_headers).json()
    assert r["removed"] == 1, r
    assert r["freed"] > 0, r


def test_清空回收站_文件也算一个条目(client, auth_headers, isolated):
    d = fileops.recycle_dir()
    (d / "单独一个文件.txt").write_text("x", encoding="utf-8")
    r = client.post(API_CLEAR, headers=auth_headers).json()
    assert r["removed"] == 1, r
    assert not list(d.iterdir())
