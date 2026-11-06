"""**共享格式化函数**必须是唯一实现（第 265 期）。

## 缺陷

`frontend/src/lib/format.ts` 早就导出了 `fmtBytes`，但**只有 9 个文件在用**，
另外 11 个 `.vue` 各自定义了一份本地副本，取整规则分成 5 种：

| 位置 | 1.5 MB 显示 |
|---|---|
| `lib/format.ts`（正主） | `1.5 MB` |
| 重复书籍 / 本地转换 / 缺失资源 / 输出目录 | `1.50 MB` |
| 审计日志 / Book Dock | `1.5 KB`→`1.5 MB`（KB 取 1 位） |
| 书籍概览 / 阅读字体 | KB 取 0 位 |
| 仪表盘「占用」小卡片 | **`2 MB`** |

⇒ 同一个体积在不同页面显示不同的数；更糟的是仪表盘那张卡片**只认 MB/GB**，
一个合计 500 KB 的书库显示 **`0 MB`**（而空库显示 `0 B`）—— 有内容却报 0。

日期同理：5 份 `fmtDate` + 7 份 `fmtTime`，播客页用 `toLocaleDateString()`
（`2026/11/6`）、书籍概览用斜杠格式、其余用 `localDate()`（`2026-11-06`）。

## 这里钉什么

1. **除了 `lib/format.ts`，不许再定义这些名字**（列表见 `SHARED`）；
2. **不许再用 `toLocaleDateString`**（浏览器默认格式随语言/地区变，本项目统一 `YYYY-MM-DD`）；
3. `toLocaleString` 只许出现在两处有明确理由的地方（千分位 / 时区问候语）。

⚠️ 这是**纯文本 + 轻量正则**断言，不拉 node 子进程（全量测试必须离线，见
`tests/test_frontend_unit_contract.py` 的开头说明）。它**不需要**知道函数实现对不对 ——
那是 `frontend/src/lib/format.spec.ts` 的事。这里只管「有没有第二份」。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
CANON = SRC / "lib" / "format.ts"

#: 只许在 `lib/format.ts` 里定义的名字（第 265 期收敛的那批）。
SHARED = (
    "fmtBytes",
    "fmtDay",
    "fmtDateTime",
    "fmtDateTimeSec",
    "fmtClock",
    "fmtClockHM",
    "fmtAgo",
    "fmtWhen",
)

#: 允许出现 `toLocaleString` 的地方（各有明确理由，不是漏网的）。
LOCALE_OK = {
    "lib/format.ts",              # thousands()：数字千分位，本就该按语言走
    "lib/dashboardGreeting.ts",   # 按**用户配置的时区**取钟点，toLocaleString 是唯一正路
}


def _sources():
    for p in sorted(SRC.rglob("*")):
        if p.suffix not in (".ts", ".vue") or p.name.endswith(".spec.ts"):
            continue
        yield p


def _rel(p: Path) -> str:
    return p.relative_to(SRC).as_posix()


def _defines(name: str) -> list:
    """`function name(` / `const name = ` / `const name = (` 三种写法都算定义。"""
    pat = re.compile(
        r"(?:^|\n)\s*(?:export\s+)?(?:function\s+" + re.escape(name) + r"\s*\(|"
        r"const\s+" + re.escape(name) + r"\s*=)"
    )
    return [p for p in _sources() if pat.search(p.read_text(encoding="utf-8", errors="ignore"))]


def test_共享格式化只在_format_ts_里定义():
    offenders = []
    for name in SHARED:
        for p in _defines(name):
            if p.resolve() == CANON.resolve():
                continue
            offenders.append(f"{_rel(p)}: {name}")
    assert not offenders, "这些文件自己定义了一份共享格式化（应 import from '@/lib/format'）：\n  " + "\n  ".join(offenders)


def test_format_ts_自己确实定义了它们():
    """反向：正主少了某个名字，上面的用例会因为「没人定义」而假绿。"""
    text = CANON.read_text(encoding="utf-8")
    missing = [n for n in SHARED if not re.search(r"export function " + re.escape(n) + r"\s*\(", text)]
    assert not missing, f"`lib/format.ts` 缺这些导出：{missing}"


def test_不用_toLocaleDateString():
    """浏览器默认日期格式随语言/地区变（`2026/11/6` vs `11/6/2026`）——
    本项目统一 `YYYY-MM-DD`（`localDate` / `fmtDay`），别再让某个页面自己走 locale。"""
    offenders = [_rel(p) for p in _sources()
                 if "toLocaleDateString" in p.read_text(encoding="utf-8", errors="ignore")]
    assert not offenders, "这些文件用了 toLocaleDateString（改用 fmtDay / fmtDateTime）：" + ", ".join(offenders)


def test_toLocaleString_只在白名单里():
    offenders = [_rel(p) for p in _sources()
                 if "toLocaleString(" in p.read_text(encoding="utf-8", errors="ignore")
                 and _rel(p) not in LOCALE_OK]
    assert not offenders, "这些文件用了 toLocaleString（日期请用 fmtDateTime；数字请用 thousands）：" + ", ".join(offenders)


def test_仪表盘占用不再显示_0_MB():
    """回归点：仪表盘曾只认 MB/GB 且 `toFixed(0)` ⇒ 合计 500 KB 的库显示 `0 MB`。"""
    widget = (SRC / "components" / "dashboard" / "widgets" / "LibraryOverviewWidget.vue").read_text(encoding="utf-8")
    assert "fmtBytes" in widget, "仪表盘不再走共享的 fmtBytes"
    assert "toFixed(0)} MB" not in widget, "仪表盘又回到了「只认 MB 档」的本地实现"
