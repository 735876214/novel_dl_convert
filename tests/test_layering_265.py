"""**分层边界**要有判据钉住（第 265 期）。

## 为什么要有这个用例

`docs/architecture.md` §1 明写两条边界：

1. `novelforge/server.py` 只做**编排与形状**（参数校验 → 调 core → 组装响应）；
2. `core/*` 是**领域逻辑**，**不认识 HTTP**。

第 265 期实测：这两条**当时确实成立**（`core/` 与 `sources/` 里 0 处 fastapi/starlette
导入）。但**没有任何用例盯着** —— 下次有人在 `core/` 里写
`from fastapi import HTTPException`（最省事的写法：直接把「404 该怎么说」塞进领域层），
CI 全绿，边界就此破一个口子，而且**破得无声无息**：直到某天想复用 `core/` 做 CLI
或后台任务，才发现它已经绑死在 Web 框架上。

## 钉的是什么

- `core/**` 与 `sources/**`：**不许** import `fastapi` / `starlette`；
- `core/**` 与 `sources/**`：**不许** import `novelforge.server`（反向依赖）；
- 除了 `server.py`，别的模块**不许** import 这两个框架（`cli.py` / `core/*` 都不该）。

⚠️ **注释里提到 fastapi 不算违规** —— 用例只解析 `ast` 里的 import 节点，
不扫文本（本仓的粗筛陷阱之一就是「注释里的文字被当成代码」）。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "novelforge"

#: 领域层目录（承接 `architecture.md` §1 的「core 不认识 HTTP」）。
DOMAIN_DIRS = ("core", "sources")

#: 领域层不许出现的第三方包（Web 框架本人）。
HTTP_FRAMEWORKS = ("fastapi", "starlette")


def _imports(path: Path) -> set:
    """该文件**所有** import 的顶层模块名（含函数内延迟导入 —— 那同样是依赖）。"""
    tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
    out: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                out.add(a.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # 相对导入：还原成 `novelforge.x.y`
                base = list(path.relative_to(ROOT).with_suffix("").parts[:-1])
                up = node.level - 1
                base = base[: len(base) - up] if up else base
                mod = ".".join(base + ([node.module] if node.module else []))
                out.add(mod)
            elif node.module:
                out.add(node.module)
    return out


def _domain_files():
    for d in DOMAIN_DIRS:
        yield from sorted((PKG / d).rglob("*.py"))


def _top(mod: str) -> str:
    return mod.split(".")[0]


def test_领域层不导入_web_框架():
    bad = []
    for p in _domain_files():
        for mod in _imports(p):
            if _top(mod) in HTTP_FRAMEWORKS:
                bad.append(f"{p.relative_to(ROOT).as_posix()} → {mod}")
    assert not bad, "领域层（core / sources）**不认识 HTTP**（architecture.md §1）：\n  " + "\n  ".join(bad)


def test_领域层不反向导入_server():
    bad = []
    for p in _domain_files():
        for mod in _imports(p):
            if mod == "novelforge.server" or mod.startswith("novelforge.server."):
                bad.append(f"{p.relative_to(ROOT).as_posix()} → {mod}")
    assert not bad, "领域层反向依赖了 server.py（分层倒置）：\n  " + "\n  ".join(bad)


def test_只有_server_导入_web_框架():
    bad = []
    for p in sorted(PKG.rglob("*.py")):
        if p.name == "server.py":
            continue
        for mod in _imports(p):
            if _top(mod) in HTTP_FRAMEWORKS:
                bad.append(f"{p.relative_to(ROOT).as_posix()} → {mod}")
    assert not bad, "除了 server.py，别的模块不该直接依赖 Web 框架：\n  " + "\n  ".join(bad)


def test_用例自己不是空转():
    """反向自检：`_imports` 必须真的看得见导入 —— 否则上面三条会**永远绿**。"""
    assert "fastapi" in {_top(m) for m in _imports(PKG / "server.py")}
    got = {_top(m) for p in _domain_files() for m in _imports(p)}
    assert "pathlib" in got or "json" in got, "领域层的 import 解析似乎什么都没看到"
