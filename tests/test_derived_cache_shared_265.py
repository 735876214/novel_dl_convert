"""派生缓存的**共用骨架**只许有一份（第 265 期）。

## 缺陷

`.fb2` / `.mobi` / `.txt` 三个派生缓存模块此前各写了一遍「原子换入」与「查缓存 → 双检 →
构建」：

- `_swap_in` 在 `fb2cache` 与 `mobicache` 里**逐字相同**（23/24 行），`txtcache` 那里是一个
  略弱的变体（不先清残留、失败回滚少一个判据）；
- `read_target` 在 `fb2cache` 与 `mobicache` 里**逐字相同**（34/35 行）。

原子换入是 AGENTS 第 1 节的**硬约束**（源不可变 / 临时文件 + `Path.replace`）。
两份拷贝意味着改一处漏一处，而漏掉的那种失败只会在崩溃后留下半个缓存目录 —— 平时看不出来。

## 这里钉什么

1. `swap_in` / `read_target` 只在 `core/derivedcache.py` 定义一次；
2. 三个缓存模块都不再自带 `_swap_in`，且都调用共享的那份；
3. 原子换入的**行为**：换入成功后 `final` 是新内容、没有残留的 `.old-*`；
   换入失败时旧目录**被放回去**（绝不留下「什么都没有」）。
"""
from __future__ import annotations

import pathlib
import re

import pytest

from novelforge.core import derivedcache, fb2cache, mobicache, txtcache

ROOT = pathlib.Path(__file__).resolve().parents[1]
PKG = ROOT / "novelforge"


def test_swap_in_只定义一次():
    offenders = []
    for p in sorted(PKG.rglob("*.py")):
        if p.name == "derivedcache.py":
            continue
        if re.search(r"^def _?swap_in\(", p.read_text(encoding="utf-8", errors="ignore"), re.M):
            offenders.append(p.relative_to(ROOT).as_posix())
    assert not offenders, "这些文件又自己定义了一份原子换入：" + ", ".join(offenders)


def test_read_target_只有共享实现_其余只是转调():
    """缓存模块可以保留同名的 `read_target`，但**函数体只能是转调**（不许再写一遍流程）。"""
    import ast

    offenders = []
    for p in sorted(PKG.rglob("*.py")):
        if p.name == "derivedcache.py":
            continue
        tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        for n in tree.body:
            if isinstance(n, ast.FunctionDef) and n.name == "read_target":
                body = [x for x in n.body
                        if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant))]
                ok = (len(body) == 1 and isinstance(body[0], ast.Return)
                      and "derivedcache" in ast.unparse(body[0]))
                if not ok:
                    offenders.append(p.relative_to(ROOT).as_posix())
    assert not offenders, "这些文件的 read_target 不是转调，而是又写了一遍流程：" + ", ".join(offenders)


def test_三个缓存模块都走共享实现():
    for mod in (fb2cache, mobicache, txtcache):
        assert mod.derivedcache is derivedcache
    # 模块级钩子齐全（共享的 read_target 靠运行时属性查找，见 derivedcache 的说明）
    for mod in (fb2cache, mobicache):
        for hook in ("EXTS", "_src_path", "_fingerprint", "_cache_dir", "_lookup",
                     "_build", "_BUILD_LOCK"):
            assert hasattr(mod, hook), f"{mod.__name__} 缺 {hook}"


def test_原子换入成功(tmp_path):
    """stage 换进 final：内容是新的一份，盘上不留 `.old-*` 残留。"""
    final = tmp_path / "book"
    final.mkdir()
    (final / "旧.txt").write_text("old", encoding="utf-8")
    stage = tmp_path / ".stage-book"
    stage.mkdir()
    (stage / "新.txt").write_text("new", encoding="utf-8")

    derivedcache.swap_in(stage, final)

    assert (final / "新.txt").read_text(encoding="utf-8") == "new"
    assert not (final / "旧.txt").exists()
    assert not [p for p in tmp_path.iterdir() if ".old-" in p.name]


def test_换入失败要把旧目录放回去(tmp_path, monkeypatch):
    """回归点：换入中途失败时若直接放弃，这本书的缓存目录会**整个消失**（下次得重建）。"""
    final = tmp_path / "book"
    final.mkdir()
    (final / "旧.txt").write_text("old", encoding="utf-8")
    stage = tmp_path / ".stage-book"
    stage.mkdir()

    real_replace = pathlib.Path.replace

    def boom(self, target):                       # noqa: ANN001
        if pathlib.Path(str(self)) == stage:
            raise OSError("模拟换入失败")
        return real_replace(self, target)

    monkeypatch.setattr(pathlib.Path, "replace", boom)
    with pytest.raises(OSError):
        derivedcache.swap_in(stage, final)

    assert (final / "旧.txt").read_text(encoding="utf-8") == "old", "旧目录必须被放回去"
