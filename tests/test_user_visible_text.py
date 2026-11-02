"""**用户可见文本里不许出现开发措辞**（第 223 期）。

第 222 期修了 `frontend/src/data/settingsNav.ts` 的 `note`（25 条里 19 条混着「已实现 /
第 N 期」），但只修了那一个文件 —— 第 223 期用同一判据扫全前端，又找出 **8 处**漏在
`PlaceholderView.vue` / `SettingsUnsupportedCard.vue` / `MaintenancePage.vue` / `OpdsPage.vue` /
`settingsFields.ts` / `whatsNew.ts` 里。

所以这里把判据**固化成用例**，覆盖整个前端：
- 扫描 `.vue` 模板里的**可见文本节点**与**用户可见属性**（title / label / placeholder /
  description / desc / message / aria-label），以及 `.ts` 里会显示给用户的**字面量**；
- **跳过注释**（`//` / `/* */` / `<!-- -->`）—— 注释里带期号是对的（那是给开发者看的）；
- 命中「第 N 期」「已实现」「本项目实现」「上游该页/上游本项目」即失败。

⚠️ 判据会误伤**合法的**开发语境吗？本仓里没有那种用法（用户可见文本不该讲期号），
若将来有（例如给管理员看的「v2 协议」），在 `EXEMPT` 里加一行并注明理由即可。
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend" / "src"

SKIP_DIRS = {"node_modules", "dist", "static", ".venv", "__pycache__"}

#: 开发措辞（任一命中即视为泄漏）
DEV_PATTERNS = (
    r"第\s*\d+\s*期",
    r"已实现",
    r"本项目实现",
    r"上游(?:该|本项目)",
)

#: 用户可见的属性
_ATTR = re.compile(
    r"""\b(title|label|placeholder|description|desc|message|aria-label|helperText|emptyText)\s*=\s*"([^"]*)""",
    re.I,
)
#: 模板文本节点
_TEXT = re.compile(r">([^<>{}]{3,160})<")
#: JS 字面量（排除路径与 URL）
_LITERAL = re.compile(r"['\"`]([^'\"`]{3,180})['\"`]")
#: 注释
_COMMENT_LINE = ("//", "*", "/*", "#")
#: 可豁免的例外（文件内子串 → 理由）
EXEMPT: dict[str, str] = {}


def _files() -> list[pathlib.Path]:
    out = []
    for pat in ("*.vue", "*.ts"):
        for f in FRONTEND.rglob(pat):
            if any(x in f.parts for x in SKIP_DIRS) or ".spec." in f.name:
                continue
            out.append(f)
    return out


def _hits_in_file(path: pathlib.Path) -> list[str]:
    hits: list[str] = []
    in_comment = False
    for i, line in enumerate(path.read_bytes().decode("utf-8", errors="replace").splitlines(), 1):
        s = line.strip()
        if s.startswith("<!--"):
            in_comment = "<!--" not in s[4:] or "-->" not in s
            continue
        if in_comment:
            if "-->" in s:
                in_comment = False
            continue
        if s.startswith(_COMMENT_LINE):
            continue
        candidates: list[tuple[str, str]] = []
        for m in _ATTR.finditer(line):
            candidates.append((m.group(1), m.group(2)))
        for m in _TEXT.finditer(line):
            candidates.append(("text", m.group(1).strip()))
        for m in _LITERAL.finditer(line):
            val = m.group(1)
            if val.startswith(("http", "@/", "./", "../")):
                continue
            candidates.append(("literal", val))
        for kind, val in candidates:
            if any(re.search(p, val) for p in DEV_PATTERNS):
                rel = str(path.relative_to(ROOT))
                if any(ex in val for ex in EXEMPT):
                    continue
                hits.append(f"{rel}:{i}  [{kind}] {val[:90]}")
    return hits


def test_用户可见文本里没有开发措辞():
    all_hits: list[str] = []
    for f in _files():
        all_hits.extend(_hits_in_file(f))
    assert not all_hits, (
        "这些**会显示给用户**的文本里混进了开发措辞（期号 / 已实现 / 上游…）：\n  "
        + "\n  ".join(all_hits)
    )


def test_判据本身有效_能抓到已知的一处():
    """判据要是坏的，上面那条用例会「永远绿」。这里用一个**内存里的样本**验它。"""
    sample = (
        '<template>\n'
        '  <p>第 51 期补齐</p>\n'
        '  <span title="已实现" />\n'
        '  <!-- 第 40 期：这行是注释，不该被抓 -->\n'
        '  <code>const x = "第 7 期"</code>\n'
        '</template>\n'
    )
    hits = [m.group(1) for m in _TEXT.finditer(sample)]
    assert any("第 51 期" in h for h in hits), "文本节点判据失效"
    assert any("已实现" in m.group(2) for m in _ATTR.finditer(sample)), "属性判据失效"
    # 注释块里的行不该进 hits
    assert not any("第 40 期" in h for h in hits), "注释被误当可见文本"
