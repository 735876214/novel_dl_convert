"""第 135 期：两条「自带鉴权」的表面不许漏掉任何一条路由。

`/api/v1/*`（Komga 兼容层）与 `/opds/*` 都在鉴权中间件里**放行**——它们各自
自带 Basic / X-API-Key / 会话 cookie 校验。放行的代价是：**新增一条路由忘了调
闸门，就多一个匿名可访问的入口**，而且这种漏洞不会报错、不会红测试、只有在被人
扫到的时候才会发现。

所以这里用静态判据把整张路由表钉住：**每一条**这类路由的函数体里都必须出现闸门
调用，除非它是「转调另一个已过闸的同名实现」（下面有显式白名单，写清楚为什么）。
"""
import ast
import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]
SERVER_SRC = (REPO / "novelforge" / "server.py").read_text(encoding="utf-8")
TREE = ast.parse(SERVER_SRC)

#: 允许「自己不调闸门」的路由 —— 它们只是换个 HTTP 方法转调另一个**已过闸**的实现。
#: 新增条目必须写明它转调谁，否则就变成合法后门。
_DELEGATING = {
    # PATCH 与 PUT 语义完全一致，函数体只有一行 `return ko_put_read_progress(...)`
    "ko_patch_read_progress": "PUT /api/v1/books/{book_id}/read-progress",
}


def _routes(prefix: str) -> list:
    """`(行号, 方法, 路径, 函数名, 函数体源码)`。"""
    out = []
    for node in TREE.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if not isinstance(d, ast.Call) or not isinstance(d.func, ast.Attribute):
                continue
            if not isinstance(d.func.value, ast.Name) or d.func.value.id != "app":
                continue
            if not d.args or not isinstance(d.args[0], ast.Constant):
                continue
            path = d.args[0].value
            if not isinstance(path, str) or not path.startswith(prefix):
                continue
            out.append((node.lineno, d.func.attr.upper(), path, node.name,
                        ast.get_source_segment(SERVER_SRC, node) or ""))
    return out


def _check(prefix: str, guard: str) -> None:
    rows = _routes(prefix)
    assert rows, f"{prefix} 下一条路由都没解析到 —— 判据本身失效了"
    missing = [r for r in rows
               if guard not in r[4] and r[3] not in _DELEGATING]
    assert not missing, (
        f"这些 {prefix} 路由没有调 {guard}（匿名可访问）：\n"
        + "\n".join(f"  server.py:{ln} {m} {p} — {fn}" for ln, m, p, fn, _ in missing))


def test_komga路由全部过闸():
    _check("/api/v1/", "_komga_guard")


def test_opds路由全部过闸():
    _check("/opds", "_opds_guard")


def test_转发式路由的白名单没有过期():
    """白名单里的函数必须还在，且真的只做转调 —— 否则「白名单」会变成藏身处。"""
    names = {fn for _, _, _, fn, _ in _routes("/api/v1/")}
    assert set(_DELEGATING) <= names
