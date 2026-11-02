"""**外部服务端点不许抄多份**（第 230 期收敛）。

第 230 期审计发现：Hardcover 的 GraphQL 端点
`https://api.hardcover.app/v1/graphql` 在**三个模块**各写了一份字面量 ——
`integrations.HARDCOVER_GRAPHQL` / `metasources.HARDCOVER` / `sync.HARDCOVER_GRAPHQL`，
**三处完全相同**。换域名 / 改版本要改三处，漏一处就静默打到旧端点（不报错，只是打不通）。

收敛：`integrations` 是真值源（它只依赖 httpx，是最底层），另两处引用它。

这里钉：**这些端点 URL 在代码里只许出现一次**（docstring 里的说明文字不算），
且引用方确实指向真值源。
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / "novelforge" / "core"

#: 已收敛到单一真值源的外部端点 → (真值源文件, 常量名, 引用方[(文件, 常量名)])
ENDPOINTS = {
    "https://api.hardcover.app/v1/graphql": (
        "integrations.py", "HARDCOVER_GRAPHQL",
        [("sync.py", "HARDCOVER_GRAPHQL"), ("metasources.py", "HARDCOVER")],
    ),
}


def _code_without_docstrings(text: str) -> str:
    """去掉 docstring（``\"\"\"...\"\"\"``）—— 说明文字里提到 URL 不算「抄了一份」。"""
    return re.sub(r'"""(?:.|\n)*?"""', "", text)


def test_端点字面量只出现一次():
    for url, (owner, _const, _users) in ENDPOINTS.items():
        hits = []
        for f in sorted(CORE.glob("*.py")):
            code = _code_without_docstrings(f.read_bytes().decode("utf-8", errors="replace"))
            if url in code:
                hits.append(f.name)
        assert hits == [owner], (
            f"{url} 在 {hits} 里出现 —— 应当只有真值源 {owner} 一处"
            f"（其余地方引用常量，别再写字面量）"
        )


def test_引用方确实指向真值源():
    """不只是「只出现一次」，还要**引用方引的是那个常量**（不是自己又定义了一个同值的）。"""
    for url, (owner, const, users) in ENDPOINTS.items():
        owner_src = (CORE / owner).read_bytes().decode("utf-8", errors="replace")
        assert re.search(rf'^{const}\s*=\s*"{re.escape(url)}"', owner_src, re.M), \
            f"{owner} 里没有定义 {const} = {url}"
        for fname, uco in users:
            src = (CORE / fname).read_bytes().decode("utf-8", errors="replace")
            assert re.search(rf"^from \.integrations import {const}(?: as {uco})?\r?$", src, re.M), \
                f"{fname} 没有从 integrations 引用 {const}"
            assert url not in _code_without_docstrings(src), \
                f"{fname} 里还有 {url} 的字面量"


def test_没有循环导入():
    """`integrations` 必须是**叶子**（不 import 任何 core 内模块）—— 否则被引用方 import 它会成环。"""
    src = (CORE / "integrations.py").read_bytes().decode("utf-8", errors="replace")
    inner = re.findall(r"(?m)^from \.(\w+)", src)
    assert not inner, f"integrations.py 现在 import 了 {inner} —— 它应当保持叶子模块"
