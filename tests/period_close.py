#!/usr/bin/env python
"""收尾落位器 + 三方对账（第 107 期）。

为什么有这个东西：第 106 期把「收尾要写 5 处」砍成了「写两处」（roadmap 本期段 +
`MEMORY.md` 索引一行），但**落位仍然是手改**：`docs/TODO.md` 的头部 / §0 / §2 / §3、
`.codebuddy/memory/MEMORY.md` 的索引、以及 `AGENTS.md` §4 与 §0 的基线数字，全靠人记着改，
改漏了**不报错**。这个脚本把两件事分开：

  · **落位**（`new`）：一条命令把机械的几处改完 —— 它不做叙事，也不做提炼。
  · **对账**（`check`）：发现漂移并指出怎么修 —— 它绝不写文件。

工具**能**做的：把「写下的东西」在三处摆齐、把不可复算的数字（测试基线）同步两处。
工具**不能**做的：写出「本期发生了什么」以及「一句话铁律里的教训」—— 那是人的活。
所以第 107 期起收尾 = ① 手写 roadmap 本期段 → ② `new` 落位 → ③ 两道校验（本脚本 + `check_doc_anchors.py`）。

用法::

    python tests/period_close.py check                       # 对账（只读；有问题退 1）
    python tests/period_close.py check --history             # 同时列出历史豁免项（warning）
    python tests/period_close.py check --fix                 # 只修 §0/§4 的版本字面量
    python tests/period_close.py new --period 108 --title "…"                 # 落位
    python tests/period_close.py new --period 108 --title "…" --dry-run        # 只打印
    python tests/period_close.py new --period 108 --title "…" \
        --junit $TMP/junit.xml --seconds 274.56               # 同批刷新两处基线数字

口径常量都在下面：`STRICT_FROM` 之前的期号**不追改**（历史就那样：roadmap 有 52 个期段、
`docs/TODO.md` §2 只有 62 期起的 45 行、`MEMORY.md` 索引的 62–83 落在三条分组行里）——
给从未存在过的索引补内容是**编造**，不是整理。
"""

from __future__ import annotations

import argparse
import codecs
import datetime as _dt
import pathlib
import re
import sys
import xml.etree.ElementTree as ET

# ---------------------------------------------------------------- 口径常量

#: 这个期号起，三处记录必须齐全、`docs/TODO.md` §2 的行必须是一行（历史靠分组行覆盖）。
STRICT_FROM = 107
#: 当日日志在此日取消（第 106 期）；**日期大于它**的 `YYYY-MM-DD.md` = 旧仪式复活。
DAILY_LOG_STOP = "2026-10-06"
#: §2 索引行的长度上限（只在 `STRICT_FROM` 起生效）。
TODO_ROW_MAX = 300
#: 新期号在 §2 里长什么样。
TODO_ROW_TAIL = "—— 细节见 `docs/roadmap-gaps-remaining.md` 第 {n} 期段"

ROADMAP = "docs/roadmap-gaps-remaining.md"
TODO = "docs/TODO.md"
AGENTS = "AGENTS.md"
MEMORY = ".codebuddy/memory/MEMORY.md"
PERIODS = ".codebuddy/memory/MEMORY-PERIODS.md"
MEMORY_DIR = ".codebuddy/memory"
VERSION = "VERSION"

MEM_INDEX_HEAD = "## 逐期铁律索引"
SEC0 = "## 0."
SEC2 = "## 2."
SEC3 = "## 3."
SEC6 = "## 6."
SEC4 = "## 4."
HEAD_LINE = "- HEAD = "
BASELINE_COMMENT = "# 当前基线"
TWO_PLACES = "每期收尾只写两处"


# ---------------------------------------------------------------- 读写（保住行尾与 BOM）


class Doc:
    """一个文档：内部一律按 `\\n` 处理，保存时还原**原文件的行尾与 BOM**。

    少了这一步，一次收尾会在 git 里产出「整文件都改了」的假 diff（本机 core.autocrlf 是开的）。
    """

    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)
        raw = self.path.read_bytes()
        self.bom = raw.startswith(codecs.BOM_UTF8)
        text = raw.decode("utf-8-sig")
        crlf = text.count("\r\n")
        self.eol = "\r\n" if crlf else "\n"
        self.text = text.replace("\r\n", "\n")

    def save(self) -> None:
        out = self.text if self.eol == "\n" else self.text.replace("\n", self.eol)
        data = out.encode("utf-8")
        if self.bom:
            data = codecs.BOM_UTF8 + data
        self.path.write_bytes(data)


def _span(lines: list[str], head_prefix: str) -> tuple[int, int]:
    """取二级小节的 `[起, 止)` 行号；找不到返回 `(-1, -1)`。"""
    start = -1
    for i, ln in enumerate(lines):
        if not ln.startswith("## "):
            continue
        if start >= 0:
            return start, i
        if ln.startswith(head_prefix):
            start = i
    return (start, len(lines)) if start >= 0 else (-1, -1)


# ---------------------------------------------------------------- 解析


def parse_roadmap_periods(text: str) -> list[int]:
    return [int(n) for n in re.findall(r"(?m)^## 第 (\d+) 期", text)]


def parse_todo_rows(text: str) -> dict[int, str]:
    lines = text.split("\n")
    a, b = _span(lines, SEC2)
    out: dict[int, str] = {}
    if a < 0:
        return out
    for ln in lines[a:b]:
        m = re.match(r"^\| (\d+) \|(.*)$", ln)
        if m:
            out[int(m.group(1))] = ln
    return out


_INDEX_LINE_RE = re.compile(r"^- \*\*(?P<label>[^*]{1,24})\*\*")


def parse_memory_index(text: str) -> list[str]:
    """返回索引标签原文（`≤74` / `75–79` / `84` / `107` 这些）。"""
    lines = text.split("\n")
    a, b = _span(lines, MEM_INDEX_HEAD)
    if a < 0:
        return []
    return [m.group("label").strip() for ln in lines[a:b] if (m := _INDEX_LINE_RE.match(ln))]


def index_numbers(label: str) -> tuple[int, int] | None:
    """`≤74` / `75–79`（en dash 或半角）/ `107` → `(最小, 最大)`；认不出返回 None。"""
    s = label.replace(" ", "")
    if m := re.fullmatch(r"≤(\d+)", s):
        return 1, int(m.group(1))
    if m := re.fullmatch(r"(\d+)[–—\-](\d+)", s):
        return int(m.group(1)), int(m.group(2))
    if m := re.fullmatch(r"(\d+)", s):
        return int(m.group(1)), int(m.group(1))
    return None


def parse_baseline(text: str) -> tuple[int, int, int] | None:
    """从 `docs/TODO.md` §0 的基线句里取 `(总例数, passed, skipped)`。"""
    m = re.search(
        r"后端 \*\*(\d+) 例（(\d+) passed / (\d+) failed / (\d+) errors / (\d+) skipped）\*\*",
        text,
    )
    return (int(m.group(1)), int(m.group(2)), int(m.group(5))) if m else None


def parse_agents_baseline(text: str) -> tuple[int, int, int] | None:
    m = re.search(r"# 当前基线 (\d+) 例（(\d+) passed / (\d+) skipped", text)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


_VERSION_LIT_RE = re.compile(r"`VERSION`\s*(?:=|仍)\s*`?\*{0,2}(\d+\.\d+\.\d+)\*{0,2}`?")

#: 旧口径里手记的「连续 N 轮未升版」整块（第 107 期起换成 VERSION 派生句）。
_ROUND_BLOCK_RE = re.compile(r"^\s*（\*\*[^\n]{0,40}轮都刻意未升\*\*")


# ---------------------------------------------------------------- 对账


def check_records(root: pathlib.Path, *, history: bool = False) -> tuple[list[str], list[str]]:
    """返回 `(problems, warnings)`。problems 非空 ⇒ `check` 退 1。"""
    root = pathlib.Path(root)
    problems: list[str] = []
    warns: list[str] = []

    def read(rel: str) -> str:
        return (root / rel).read_text(encoding="utf-8-sig")

    roadmap = read(ROADMAP)
    todo = read(TODO)
    agents = read(AGENTS)
    memory = read(MEMORY)

    periods = parse_roadmap_periods(roadmap)
    rows = parse_todo_rows(todo)
    labels = parse_memory_index(memory)
    spans = [index_numbers(lb) for lb in labels]
    max_period = max(periods) if periods else 0

    # -- R1 新期号三处齐全
    for n in periods:
        if n < STRICT_FROM:
            continue
        if n not in rows:
            problems.append(f"[R1] 第 {n} 期：`{TODO}` §2 缺一行 `| {n} | … |`")
        if not any(s and s[0] <= n <= s[1] for s in spans):
            problems.append(f"[R1] 第 {n} 期：`{MEMORY}` 逐期索引缺一行 `- **{n}** …`")

    # -- R2 索引自身：标签可解析、不重复、不越界
    for lb, s in zip(labels, spans):
        if s is None:
            problems.append(f"[R2] `{MEMORY}` 索引标签认不出：`- **{lb}**`（只支持 `≤N` / `A–B` / `N`）")
            continue
        if s[1] > max_period:
            problems.append(f"[R2] `{MEMORY}` 索引 `{lb}` 超出 roadmap 最大期号（第 {max_period} 期）= 幽灵期号")
        if s[0] == s[1] and s[0] not in periods:
            msg = f"[R2] `{MEMORY}` 索引 `{lb}` 在 roadmap 里没有对应期段"
            (problems if s[0] >= STRICT_FROM else warns).append(msg)
    seen: set[str] = set()
    for lb in labels:
        if lb in seen:
            problems.append(f"[R2] `{MEMORY}` 索引标签重复：`- **{lb}**`")
        seen.add(lb)

    # -- R3 §0 提到最新期号；两处基线一致
    lines = todo.split("\n")
    a, b = _span(lines, SEC0)
    sec0 = "\n".join(lines[a:b]) if a >= 0 else ""
    if a < 0:
        problems.append(f"[R3] `{TODO}` 找不到 `{SEC0}` 小节")
    elif f"第 {max_period} 期" not in sec0:
        problems.append(f"[R3] `{TODO}` §0 的 HEAD 链没提到最新期号（第 {max_period} 期）")

    tb, ab = parse_baseline(todo), parse_agents_baseline(agents)
    if tb is None:
        problems.append(f"[R3] `{TODO}` §0 里找不到测试基线句（`后端 **N 例（P passed / …）**`）")
    if ab is None:
        problems.append(f"[R3] `{AGENTS}` §4 里找不到 `{BASELINE_COMMENT} N 例（P passed / S skipped…）`")
    if tb and ab and tb != ab:
        problems.append(f"[R3] 基线数字两处不一致：`{TODO}` §0 = {tb}，`{AGENTS}` §4 = {ab}")

    # -- R4 当日日志不许复活
    for p in sorted((root / MEMORY_DIR).glob("*.md")):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.md", p.name) and p.name[:10] > DAILY_LOG_STOP:
            problems.append(
                f"[R4] `{MEMORY_DIR}/{p.name}`：当日日志已于 {DAILY_LOG_STOP} 取消（第 106 期），不该再新建"
            )

    # -- R5 存档只读
    for n in parse_roadmap_periods(read(PERIODS)):
        if n >= STRICT_FROM:
            problems.append(f"[R5] `{PERIODS}` 是**只读存档**，却出现了 `## 第 {n} 期`")

    # -- R6 新期号的 §2 行是一行
    for n, ln in rows.items():
        if n >= STRICT_FROM and len(ln) > TODO_ROW_MAX:
            problems.append(
                f"[R6] 第 {n} 期的 §2 行有 {len(ln)} 字符（上限 {TODO_ROW_MAX}）："
                f"新期号只写一行 `| {n} | <标题> {TODO_ROW_TAIL.format(n=n)} |`，细节进 roadmap"
            )

    # -- R7 版本字面量 = 仓库根 VERSION
    want = (root / VERSION).read_text(encoding="utf-8-sig").strip()
    for rel in (TODO, AGENTS):
        for got in _VERSION_LIT_RE.findall(read(rel)):
            if got != want:
                problems.append(f"[R7] `{rel}` 里的版本字面量 `{got}` ≠ 仓库根 `{VERSION}` 的 `{want}`（`--fix` 可改）")

    # -- R8 口径还在
    la, lb_ = _span(agents.split("\n"), SEC6)
    if la < 0 or TWO_PLACES not in "\n".join(agents.split("\n")[la:lb_]):
        problems.append(f"[R8] `{AGENTS}` §6 找不到「{TWO_PLACES}」的口径 —— 旧仪式可能被写回来了")

    if history:
        for n in periods:
            if n < STRICT_FROM and n not in rows:
                warns.append(f"（历史豁免）第 {n} 期在 roadmap 有期段，但 §2 从来没有过这一行")
    return problems, warns


# ---------------------------------------------------------------- 落位


class ScaffoldError(RuntimeError):
    pass


def numbers_from_junit(path: pathlib.Path) -> tuple[int, int, int]:
    """pytest 的 junit xml → `(总例数, passed, skipped)`。"""
    root_el = ET.parse(str(path)).getroot()
    suites = [root_el] if root_el.tag == "testsuite" else list(root_el)
    total = passed = skipped = 0
    for s in suites:
        if s.tag != "testsuite":
            continue
        t = int(s.get("tests", 0))
        f = int(s.get("failures", 0)) + int(s.get("errors", 0))
        k = int(s.get("skipped", 0))
        total += t
        passed += t - f - k
        skipped += k
    if total == 0:
        raise ScaffoldError(f"{path} 里没读到用例数（tests=0）")
    return total, passed, skipped


def _replace_baselines(todo: Doc, agents: Doc, period: int, numbers, seconds, log: list[str]) -> None:
    total, passed, skipped = numbers
    sec = f"{seconds} s" if seconds else None
    m = re.search(
        r"(?m)^- 测试基线（[^\n]*?）：后端 \*\*\d+ 例（\d+ passed / \d+ failed / \d+ errors / \d+ skipped）\*\*，全量 ([0-9.]+) s；$",
        todo.text,
    )
    if not m:
        log.append(f"⚠️ `{TODO}` §0 的基线句没匹配上，**两处基线请手改**")
    else:
        sec = sec or f"{m.group(2)} s"
        todo.text = todo.text[: m.start()] + (
            f"- 测试基线（第 {period} 期实测）：后端 **{total} 例"
            f"（{passed} passed / 0 failed / 0 errors / {skipped} skipped）**，全量 {sec}；"
        ) + todo.text[m.end():]
        log.append(f"· `{TODO}` §0 基线 → {total} 例（{passed} passed / {skipped} skipped），{sec}")

    # 这行是**注释**（`.venv/bin/python -m pytest    # 当前基线 …`）⇒ 不能锚行首。
    m2 = re.search(r"(# 当前基线 )\d+ 例（\d+ passed / \d+ skipped；只增不减）", agents.text)
    if not m2:
        log.append(f"⚠️ `{AGENTS}` §4 的基线注释没匹配上，**两处基线请手改**")
    else:
        agents.text = agents.text[: m2.start()] + (
            f"# 当前基线 {total} 例（{passed} passed / {skipped} skipped；只增不减）"
        ) + agents.text[m2.end():]
        log.append(f"· `{AGENTS}` §4 基线 → {total} 例（{passed} passed / {skipped} skipped）")


def _drop_round_counter(todo: Doc, version: str, log: list[str]) -> None:
    """把旧口径里手记的「连续 N 轮未升版」换成 VERSION 派生的一句（没有就不动）。"""
    lines = todo.text.split("\n")
    start = next((i for i, ln in enumerate(lines) if _ROUND_BLOCK_RE.match(ln)), -1)
    if start < 0:
        return
    end = -1
    for i in range(start, min(start + 12, len(lines))):
        if "单一真值源" in lines[i] or "先不发版" in lines[i]:
            end = i
        if "单一真值源" in lines[i]:
            break
    if end < start:
        end = start
    lines[start : end + 1] = [
        f"  `VERSION` 仍 `{version}`（自 v{version} 起未再升版；最近一次升版见 `CHANGELOG.md`）——",
        "  单一真值源，`GET /health` 下发。",
    ]
    todo.text = "\n".join(lines)
    log.append("· 去掉手记的「连续 N 轮未升版」计数（换成 VERSION 派生句）")


def scaffold(
    root: pathlib.Path,
    period: int,
    title: str,
    *,
    numbers: tuple[int, int, int] | None = None,
    seconds: str | None = None,
    dry_run: bool = False,
    today: str | None = None,
) -> list[str]:
    """把一期收尾要改的几处一次落位；**任何一处冲突就整体不做**。"""
    root = pathlib.Path(root)
    log: list[str] = []
    today = today or _dt.date.today().isoformat()

    roadmap = Doc(root / ROADMAP)
    todo = Doc(root / TODO)
    agents = Doc(root / AGENTS)
    memory = Doc(root / MEMORY)

    # -- 前置：期号未被占用、锚点都在（缺一个就整体拒绝，绝不半途改一半）
    bad: list[str] = []
    if re.search(rf"(?m)^## 第 {period} 期", roadmap.text):
        bad.append(f"`{ROADMAP}` 已有 `## 第 {period} 期`")
    if period in parse_todo_rows(todo.text):
        bad.append(f"`{TODO}` §2 已有 `| {period} |` 行")
    if any(s and s[0] <= period <= s[1] for s in (index_numbers(x) for x in parse_memory_index(memory.text))):
        bad.append(f"`{MEMORY}` 索引已覆盖第 {period} 期")
    head_i = next((i for i, ln in enumerate(todo.text.split("\n")) if ln.startswith(HEAD_LINE)), -1)
    if head_i < 0:
        bad.append(f"`{TODO}` §0 找不到 `{HEAD_LINE}…` 那条 HEAD 链")
    elif "；`VERSION`" not in todo.text.split("\n")[head_i]:
        bad.append(f"`{TODO}` §0 的 HEAD 链里没有 `；`VERSION`` 锚点")
    if _span(todo.text.split("\n"), SEC2)[0] < 0:
        bad.append(f"`{TODO}` 找不到 `{SEC2}` 小节")
    if not re.search(r"(?m)^\|---\|", todo.text):
        bad.append(f"`{TODO}` §2 找不到表头分隔行 `|---|---|`")
    if not re.search(rf"(?m)^{re.escape(MEM_INDEX_HEAD)}", memory.text):
        bad.append(f"`{MEMORY}` 找不到 `{MEM_INDEX_HEAD}`")
    if bad:
        raise ScaffoldError("落位前检查不通过（未改任何文件）：\n  - " + "\n  - ".join(bad))

    # 1) roadmap：追加期段标题（只插标题，不套骨架 —— 各期小节数本来就不同）
    roadmap.text = roadmap.text.rstrip("\n") + f"\n\n## 第 {period} 期（{title}）\n"
    log.append(f"· `{ROADMAP}` 追加 `## 第 {period} 期（{title}）`（正文待手写）")

    # 2) TODO 头部：换成本期占位段落
    tlines = todo.text.split("\n")
    h_start = next((i for i, ln in enumerate(tlines) if ln.startswith("**最后更新**")), -1)
    if h_start < 0:
        bad.append(f"`{TODO}` 头部找不到 `**最后更新**：`（未改任何文件）")
        raise ScaffoldError("落位前检查不通过（未改任何文件）：\n  - " + "\n  - ".join(bad))
    h_end = h_start
    while h_end + 1 < len(tlines) and tlines[h_end + 1].strip():
        h_end += 1
    tlines[h_start : h_end + 1] = [
        f"**最后更新**：{today} —— 第 {period} 期**{title}**：",
        "<一句话说清本期为什么做、做到什么程度>",
        "历史：<上一期一句话>；`VERSION` 仍 `{v}`（无版本变更时保留这句）。".format(v=(root / VERSION).read_text(encoding="utf-8-sig").strip()),
    ]
    log.append(f"· `{TODO}` 头部 → 第 {period} 期占位段（**一句话与历史行待手写**）")

    # 3) TODO §2：一行索引（最新在最上）
    a, b = _span(tlines, SEC2)
    sep = next((i for i in range(a, b) if re.match(r"^\|---\|", tlines[i])), -1)
    tlines.insert(sep + 1, f"| {period} | {title} {TODO_ROW_TAIL.format(n=period)} |")
    log.append(f"· `{TODO}` §2 加一行 `| {period} | {title} … |`")

    # 4) TODO §0：HEAD 链追加本段
    head_i = next(i for i, ln in enumerate(tlines) if ln.startswith(HEAD_LINE))
    ln = tlines[head_i]
    cut = ln.rfind("；`VERSION`")
    tlines[head_i] = ln[:cut] + f" + 第 {period} 期{title}" + ln[cut:]
    log.append(f"· `{TODO}` §0 HEAD 链追加 `+ 第 {period} 期{title}`")

    todo.text = "\n".join(tlines)

    # 5) MEMORY.md 索引加一行
    mlines = memory.text.split("\n")
    a, b = _span(mlines, MEM_INDEX_HEAD)
    last = max((i for i in range(a, b) if _INDEX_LINE_RE.match(mlines[i])), default=-1)
    mlines.insert(last + 1, f"- **{period}** {title}")
    memory.text = "\n".join(mlines)
    log.append(f"· `{MEMORY}` 索引加一行 `- **{period}** {title}`")

    # 6) 基线两处（给了数字才动）
    if numbers:
        _replace_baselines(todo, agents, period, numbers, seconds, log)
    else:
        log.append(f"⚠️ 没给 `--numbers` / `--junit`：`{TODO}` §0 与 `{AGENTS}` §4 的基线数字**待手改**（两处必须一致）")

    # 7) 去掉旧口径的手记轮次数
    _drop_round_counter(todo, (root / VERSION).read_text(encoding="utf-8-sig").strip(), log)

    if dry_run:
        log.append("（--dry-run：没有写任何文件）")
        return log
    for d in (roadmap, todo, agents, memory):
        d.save()
    log.append("已写入：" + "、".join(f"`{p}`" for p in (ROADMAP, TODO, AGENTS, MEMORY)))
    log.append("还要手写：roadmap 本期段、TODO 头部那一句话、索引行里要补的 ⚠️ 教训")
    return log


# ---------------------------------------------------------------- CLI


def _fix_versions(root: pathlib.Path) -> list[str]:
    want = (root / VERSION).read_text(encoding="utf-8-sig").strip()
    out = []
    for rel in (TODO, AGENTS):
        doc = Doc(root / rel)
        fixed = 0

        def sub(m: re.Match) -> str:
            nonlocal fixed
            if m.group(1) != want:
                fixed += 1
                return m.group(0).replace(m.group(1), want)
            return m.group(0)

        doc.text = _VERSION_LIT_RE.sub(sub, doc.text)
        if fixed:
            doc.save()
            out.append(f"· `{rel}`：{fixed} 处版本字面量 → {want}")
    return out


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="收尾落位器 + 三方对账（第 107 期）")
    ap.add_argument("--root", default=".", help="仓库根（测试用临时副本）")
    # `--root` 放在子命令后面也要能用（`new --root X`）：子解析器上给一份 SUPPRESS 默认值的副本，
    # 没写就不覆盖顶层已经解析出来的值。
    child_root = argparse.ArgumentParser(add_help=False)
    child_root.add_argument("--root", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", parents=[child_root], help="对账（只读）")
    c.add_argument("--history", action="store_true", help="同时列出历史豁免项")
    c.add_argument("--fix", action="store_true", help="只修 §0/§4 的版本字面量")

    n = sub.add_parser("new", parents=[child_root], help="落位一期收尾")
    n.add_argument("--period", type=int, required=True)
    n.add_argument("--title", required=True, help="期标题（与 roadmap 期段标题一致）")
    n.add_argument("--numbers", help='三个数字："总例数 passed skipped"')
    n.add_argument("--junit", help="pytest 的 junit xml（与 --numbers 二选一）")
    n.add_argument("--seconds", help="全量耗时（秒，写进 §0 基线句）")
    n.add_argument("--dry-run", action="store_true")

    args = ap.parse_args(argv)
    root = pathlib.Path(args.root).resolve()

    if args.cmd == "new":
        numbers = None
        if args.numbers:
            nums = [int(x) for x in re.findall(r"\d+", args.numbers)]
            if len(nums) != 3:
                print('--numbers 需要三个数字："总例数 passed skipped"', file=sys.stderr)
                return 2
            numbers = (nums[0], nums[1], nums[2])
        elif args.junit:
            numbers = numbers_from_junit(pathlib.Path(args.junit))
        try:
            for ln in scaffold(
                root,
                args.period,
                args.title,
                numbers=numbers,
                seconds=args.seconds,
                dry_run=args.dry_run,
            ):
                print(ln)
        except ScaffoldError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    if args.fix:
        for ln in _fix_versions(root):
            print(ln)
    problems, warns = check_records(root, history=args.history)
    for w in warns:
        print("warning: " + w)
    if not problems:
        print("收尾记录对账通过（0 问题）")
        return 0
    for p in problems:
        print(p)
    print(f"\n共 {len(problems)} 处问题：roadmap 本期段是唯一叙事，其余几处用 `period_close.py new` 落位。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
