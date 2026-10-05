"""来源声明包（第 102 期）：把「一家源是什么」与「一家源怎么解析」分开。

- `registry`：声明表（一家源的全部事实**只写一处**）
- `kinds`：领域轴（电子书 / 漫画 / 动画·轻小说 / 有声书）

⚠️ **本包不是第二份实现**：解析函数仍在 `core/metasources.py` 原地，
这里只有声明与领域常量。`metasources` 的 7 张扁平表由 `registry.DECLARED` 派生。
"""
from . import kinds, registry
from .registry import GROUPS, Provider

__all__ = ["kinds", "registry", "GROUPS", "Provider"]
