"""落盘必须走**原子写**（第 244 期）。

## 为什么

`tts.synthesize` 原先直接 `path.write_bytes(blob)`、`koreader_export.apply_export`
原先直接 `write_text(...)` —— **非原子**。写盘途中：

- 另一个请求命中同名路径（TTS 按内容哈希命名 ⇒ 同文本必同路径）⇒
  `GET /api/tts/audio/{name}` 读到**半截 mp3**（`<audio>` 截断 / 播不出声）；
- KOReader 读到**半截**导出位点 ⇒ 它那边的导出记录坏掉（用户得手动修）。

全仓统一的写法是 `core/atomicio.py`（同目录临时文件 + `Path.replace`），与
`authors` / `fonts` / `landing` / `zipkind` 同一口径。

## 这里钉的是「写法」而不是「行为」

行为很难稳定复现（要真的撞上写盘中途的读）。所以这里断言**调用点确实走了
`atomicio`** —— 一旦有人改回 `write_bytes`，这条立刻红。
"""
from __future__ import annotations

import ast
import pathlib

CORE = pathlib.Path(__file__).resolve().parents[1] / "novelforge" / "core"


def _calls_in(module: str, func: str) -> set[str]:
    """某个模块里某个函数体内调用到的「名字」（含属性访问 `a.b`）。"""
    tree = ast.parse((CORE / module).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == func:
            out: set[str] = set()
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call):
                    f = sub.func
                    if isinstance(f, ast.Attribute):
                        parts = []
                        cur = f
                        while isinstance(cur, ast.Attribute):
                            parts.append(cur.attr)
                            cur = cur.value
                        if isinstance(cur, ast.Name):
                            parts.append(cur.id)
                        out.add(".".join(reversed(parts)))
                    elif isinstance(f, ast.Name):
                        out.add(f.id)
            return out
    raise AssertionError(f"{module} 里没有 {func}")


def test_tts_合成走原子写():
    """TTS 音频落盘必须走 `atomicio.write_bytes`。"""
    calls = _calls_in("tts.py", "synthesize")
    assert "atomicio.write_bytes" in calls, calls
    assert "path.write_bytes" not in calls, calls


def test_koreader_导出位点走原子写():
    """KOReader 导出位点必须走 `atomicio.write_text`。"""
    calls = _calls_in("koreader_export.py", "apply_export")
    assert "atomicio.write_text" in calls, calls
    assert "target.write_text" not in calls, calls
