"""全仓 Python 源码不许出现 `invalid escape sequence`（第 292 期 CI 清理）。

## 为什么要有这份测试

第 292 期的 CI 日志里有 4 条 `SyntaxWarning: invalid escape sequence`（都在测试里：
`test_audit_279.py` 的 docstring 与两条 Windows 路径字面量、`test_recycle_restore.py`
的一条 docstring）。它们不红 CI，但有两个实际代价：

1. 每次全量都在 warning summary 里占位置，真正该看的告警被淹掉；
2. Python 已把「无效转义序列」列为待移除语法 —— 未来版本会变成 `SyntaxError`，
   到那天是**整份测试文件收集失败**，而不是一行 warning。

修法只有一种：含反斜杠的 docstring / 字面量写成 **raw string**（在开头引号前加 `r`）。
这条用例把「修完又回来」堵死：逐文件 `compile()`，把 `SyntaxWarning` 当错误。
"""
from __future__ import annotations

import pathlib
import warnings

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 不扫的目录：第三方依赖 / 构建产物 / VCS。
_SKIP_PARTS = {".venv", "node_modules", "__pycache__", ".git", "static", ".deveco"}


def test_没有_invalid_escape_sequence() -> None:
    bad: list[str] = []
    for p in sorted(ROOT.rglob("*.py")):
        if _SKIP_PARTS & set(p.parts):
            continue
        try:
            src = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        rel = p.relative_to(ROOT)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                compile(src, str(p), "exec")
            except SyntaxError as e:
                bad.append(f"{rel}: 编译失败：{e}")
                continue
        for w in caught:
            if issubclass(w.category, SyntaxWarning):
                bad.append(f"{rel}:{w.lineno}: {w.message}")
    assert not bad, (
        "存在无效转义序列 / 编译告警（含反斜杠的 docstring / 字面量请写成 raw string）：\n  "
        + "\n  ".join(bad))
