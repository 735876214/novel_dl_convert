"""`AGENTS.md` 的索引契约（第 117 期）。

第 117 期把 `AGENTS.md` 从「什么都说一点」改成**入口索引**（一行判据 + 去哪看）。
索引化的前提是**跳转有效** —— 一个指向不存在文件的指针比没有指针更坏：
读者会以为自己已经查过了，于是连「没查」这个事实都丢了。

所以这里只钉一条：`AGENTS.md` 里用反引号括起、且**看起来是仓库内相对路径**的字符串必须真实存在。

判据的边界（为什么这样切）：

- 只认白名单**前缀**（`docs/` / `tests/` / `scripts/` / `.codebuddy/` / `frontend/` / `novelforge/`）
  **且**白名单**后缀**（`.md` / `.py` / `.sh` / `.mjs` / `.ts` / `.vue`）——
  否则 `server.EDITABLE`、`db._connect()`、`library.hasFeature(k)` 这类符号名会被误判成路径。
- 含 `*` / `{` / 空格的一律不查（那是模式或说明文字，不是路径）。
- 以 `/` 收尾的（目录）不查 —— 目录存在性对读者没有意义，且 `docs/review/` 这类随时可能空掉。
- 只查 `AGENTS.md` 一份。其余文档的路径由 `tests/check_doc_anchors.py` 那套工具管。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "AGENTS.md"

#: 只认这些前缀 —— 白名单，不是黑名单（宁可漏判，不可误判）
PREFIXES = ("docs/", "tests/", "scripts/", ".codebuddy/", "frontend/", "novelforge/")
#: 只认这些后缀（`.json` / `.txt` / `.yml` 等文件也在文里出现，但不属「指针」形态）
SUFFIXES = (".md", ".py", ".sh", ".mjs", ".ts", ".vue")

_CODE_SPAN = re.compile(r"`([^`\n]+)`")


def _candidate_paths(text: str) -> list[str]:
    out: list[str] = []
    for span in _CODE_SPAN.findall(text):
        span = span.strip()
        if not span.startswith(PREFIXES) or not span.endswith(SUFFIXES):
            continue
        if any(bad in span for bad in ("*", "{", " ", "/ ")):
            continue
        if span.endswith("/"):
            continue
        out.append(span)
    return out


def test_AGENTS_里的路径指针都真实存在() -> None:
    text = AGENTS.read_text(encoding="utf-8")
    paths = _candidate_paths(text)

    # 判据自身也要防失效：写法变了（比如全改成链接）⇒ 扫到 0 条，此用例必须红而不是空过
    assert paths, (
        "在 `AGENTS.md` 里一条路径都没扫到 —— 要么写法变了（判据失效），"
        "要么真的一个指针都不剩；两种情况都得先改本用例再改文档"
    )

    missing = sorted({p for p in paths if not (ROOT / p).exists()})
    assert not missing, (
        "`AGENTS.md` 指向了**不存在**的文件：\n  "
        + "\n  ".join(missing)
        + "\n入口索引的价值全在「跳过去有东西」—— 请改指针（或补文件）；"
        "若是有意保留的占位，请把它从反引号路径的写法里拿出来"
    )
