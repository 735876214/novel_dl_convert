"""**书籍本体读 zip 条目一律走统一入口**（第 242 期立；第 292 期改成 AST 判据）。

`core/zipkind.py::read_entry` 是「读归档里一个条目」的**唯一入口** —— 它带解压后大小上限
（`comics.MAX_ENTRY_BYTES`），而裸 `z.read()` **绕过**这个上限：一份几百 KB 的 zip 炸弹
就能让内存吃光。

第 242 期审计在三处找到裸读（`server.py` 的书内资源 / 内嵌封面、`core/epub_cfi.py`）；
**第 292 期又找到三处**，都是同一条规则漏掉的：

| 位置 | 读的是什么 | 后果 |
|---|---|---|
| `core/publish.py` 去音频副本 | container.xml / OPF / 每个被复制的条目 | 出版一份恶意 EPUB ⇒ 内存暴涨 |
| `core/epub_update.py` 追加章节 | 每个未替换的条目 | 追更时读一本炸弹书 ⇒ 内存暴涨 |
| `core/kepub.py` 导出 KEPUB | 每个条目 | 导出炸弹书 ⇒ 内存暴涨 |

⚠️ **上一版的守卫是假绿**：它按**变量名白名单**（`z` / `zf` / `zip` / `archive` / `ar`）
认裸读，而这三处用的是 **`zin`** —— 白名单之外的变量名一概看不见。第 292 期改成
**AST 判据**：先找作用域里绑定到 `zipfile.ZipFile` 的变量（`with … as x` / `x = …`），
再找这些变量上的 `.read(...)` 调用 —— 变量名怎么起都跑不掉。

注释里提到「裸 `z.read()`」的**说明文字**不算（AST 只看真实调用）。
"""
from __future__ import annotations

import ast
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOVELFORGE = ROOT / "novelforge"


def _is_zip_ctor(node: ast.AST) -> bool:
    """`zipfile.ZipFile(...)` / `from zipfile import ZipFile` 后的 `ZipFile(...)`。"""
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    if isinstance(f, ast.Attribute):
        return f.attr == "ZipFile"
    if isinstance(f, ast.Name):
        return f.id == "ZipFile"
    return False


class _ZipVarScope(ast.NodeVisitor):
    """收集**当前函数作用域**绑定到 ZipFile 的变量名。

    刻意不下钻嵌套函数：A 函数里的 `z` 与 B 函数里的 `z` 是两回事 —— 跨作用域合并会
    把「普通文件读」误判成 zip 裸读。
    """

    def __init__(self) -> None:
        self.names: set[str] = set()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:      # noqa: N802
        return

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_With(self, node: ast.With) -> None:                   # noqa: N802
        for item in node.items:
            if _is_zip_ctor(item.context_expr) and isinstance(item.optional_vars, ast.Name):
                self.names.add(item.optional_vars.id)
        self.generic_visit(node)

    visit_AsyncWith = visit_With

    def visit_Assign(self, node: ast.Assign) -> None:               # noqa: N802
        if _is_zip_ctor(node.value):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    self.names.add(t.id)
        self.generic_visit(node)


def _zip_vars(fn: ast.AST) -> set[str]:
    """这个函数作用域里绑定到 ZipFile 的变量名（`with … as x` 与 `x = …` 两种）。"""
    v = _ZipVarScope()
    for child in getattr(fn, "body", []):
        v.visit(child)
    return v.names


def _bare_reads(path: pathlib.Path) -> list[tuple[int, str]]:
    """该文件里所有「ZipFile 变量上的 `.read(...)`」调用。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    out: list[tuple[int, str]] = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        zv = _zip_vars(fn)
        if not zv:
            continue
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "read"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in zv):
                out.append((node.lineno, f"{node.func.value.id}.read(...)"))
    return out


def test_没有裸读_zip_条目():
    hits = []
    for f in sorted(NOVELFORGE.rglob("*.py")):
        for line, what in _bare_reads(f):
            hits.append(f"{f.relative_to(ROOT)}:{line}  {what}")
    assert not hits, (
        "这些地方**裸读**了 zip 条目（绕过 `zipkind.read_entry` 的解压后大小上限）：\n  "
        + "\n  ".join(hits)
    )


def test_守卫本身认得出_zin_这种变量名():
    """自证这条用例不是空转：同一份代码，`zin.read` 必须被认出来。

    ⚠️ 上一版按变量名白名单认，`zin` 恰好不在表里 ⇒ 三处真裸读一直绿。这里用一段
    临时源码把「变量名不在白名单」这个失效模式钉死。
    """
    src = (
        "import zipfile\n"
        "def f(path):\n"
        "    with zipfile.ZipFile(path) as zin:\n"
        "        return zin.read('x')\n"
    )
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    zv = _zip_vars(fn)
    assert "zin" in zv
    found = [n for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "read" and isinstance(n.func.value, ast.Name)
             and n.func.value.id in zv]
    assert found, "AST 判据没认出 zin.read —— 守卫又变回假绿了"


def test_统一入口本身带上限():
    """`zipkind.read_entry` 必须真的带上限（否则「都走它」也没用）。"""
    from novelforge.core import comics, zipkind

    assert comics.MAX_ENTRY_BYTES > 0
    src = zipkind.read_entry.__doc__ or ""
    assert "上限" in src or "limit" in src, "read_entry 的 docstring 应说明它带上限"
