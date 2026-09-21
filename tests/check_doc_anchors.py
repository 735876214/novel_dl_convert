#!/usr/bin/env python
"""文档锚点核验：把「文档里写的 `文件:行号` 还对不对」从人工变成可复跑。

第 32 / 33 期各做过一轮人工反向 grep（第 33 期核 312 条、修 28 处），第 34 期又改了
6 个高频被引用文件（净增 958 行）—— 靠人记偏移量必然再次走样，于是把方法固化成工具。

用法::

    .venv/bin/python tests/check_doc_anchors.py              # 全量报告（只读，不动文档）
    .venv/bin/python tests/check_doc_anchors.py --file server.py
    .venv/bin/python tests/check_doc_anchors.py --drift      # 只看「疑似漂移」清单
    .venv/bin/python tests/check_doc_anchors.py --todo --file db.py
                                                             # 待人工复核清单（并排打印真实原文）
    .venv/bin/python tests/check_doc_anchors.py --strict     # 有硬错时退出码 1

它能自动判的（硬判定）：
  · **文件不存在**：按多个根解析（仓库根 / docs / novelforge / novelforge/core / frontend/src / tests）；
  · **行号越界**：行号超过目标文件行数；
  · **区间倒置**：`a-b` 里 a > b。
它只能给**候选**的（软判定）：
  · **疑似漂移**：锚点那一句里点名的符号（函数 / 常量 / 字段名）在目标行 ±RANGE 行内找不到。
  · **需人工看**：该句没点名任何符号；或符号在该文件里出现太多次（太泛）；或**历史引用行**、
    **裸文件名 + 句里提到上游**（很可能指的是上游仓的同名文件）这两类不作判定。
它**判不了**的：
  · 「行号合法但内容换了」—— 那句话没点名任何符号时只能人工看。
    ⚠️ 所以本工具**不替代人工复核**，它只负责把「一眼能看出的错」和「该看哪几行」摆出来。

「疑似漂移」这一组被实测调过六轮，误报来源与对策都写在对应常量/函数注释里（第 35 期）：
  ① 整行取符号 → 按**相邻锚点**夹出小句；② 区间只按右端取窗口 → 取「区间 ±RANGE」；
  ③ `name()` / `NAME = (...)` 这种反引号内容取不到符号 → 取反引号内容的**首个标识符**；
  ④ 历史引用行（「原引 …」/「文档写 `x.py:1`，真值 `:2`」）与「上游裸文件名」被当成真锚点
     → 单独归类，不报漂移；
  ⑤ 小句被反引号**内部**的逗号切断（`` `A = ("x","y")` ``）→ 分隔符只在反引号外才算界；
  ⑥ `、` 不作分隔符 + 「`符号`（`文件:行`）」里的符号被前一条锚点抢走 → `、` 算界，
     且**紧跟另一条锚点**的反引号归那条锚点（第 35 期：`sources` 曾被算到 `ToolsLayout.vue:48-49` 头上）。
⚠️ 已实测的两类**漏报**（工具报不出来，只能靠人 + 反向 grep）：
  · 小句被切断时符号可能被整段吞掉（⑤ 修的就是这一种）；
  · 「行号合法但内容换了、且那句没点名任何符号」—— 无解，本工具天生测不出 ⇒ 用 `--todo` 出清单并排看。

纪律（与 roadmap §四一致）：**别记偏移量，只记当前真实行号**。发现漂移时把文档改成
实测行号，而不是在旧行号上加一个差值。另：**「修好了」的判据是工具报 0 条漂移 + 人工看过
`--todo` 清单**，不是「工具不报错」—— 它报不出内容型漂移，这一点第 35 期又被实测印证过一次
（`DOCK_TABS` 那条工具当年漏报，靠人逐条看才发现真值差了 568 行）。
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 目标文件解析根（按序尝试）。短名（如 `server.py`、`db.py`）在不同文档里指代不同位置，
#: 所以必须多根 —— 这也是这段历史里最容易出错的地方。
ROOTS = (
    ROOT,
    ROOT / "novelforge",
    ROOT / "novelforge" / "core",
    ROOT / "frontend" / "src",
    ROOT / "tests",
    ROOT / "docs",
)

#: 锚点：`路径:行号` 或 `路径:行号-行号`，引号可有可无
ANCHOR = re.compile(
    r"`?([A-Za-z0-9_./\\-]+\.(?:py|ts|vue|js|mjs|json|md|css|html|sh|toml|yml|yaml))"
    r":(\d+)(?:-(\d+))?`?"
)

#: **裸续锚**：只写 `:行号` 不带文件名（表格里为了不重复写路径，很常见）。
#: 它承接**同一行里最近出现过的那个文件名** —— 这是启发式，所以判定结果会标注来源，
#: 让人能一眼看出「这条是按谁解析的」并自行打折。
BARE_ANCHOR = re.compile(r"`?:(\d+)(?:-(\d+))?`?")

#: 外部（上游仓库）路径前缀：这些在本仓**本来就不存在**，不是断链
EXTERNAL_PREFIXES = ("packages/", "apps/", "modules/", "plugins/", "scripts/", "src/lib/")

#: 不扫的文档（相对仓库根的 glob）：`docs/review/**` 是当时对上游界面与**构建产物**的取证
#: （锚到 `static/v2/assets/index-XXXX.js`），产物不入库 ⇒ 这些锚点永远核不到，留着只会淹掉真问题。
SKIP_DOCS = ("docs/review/**",)

#: 「裸文件名 + 本行提到上游」⇒ 该锚点很可能指**上游仓**的同名文件。本仓偶然有个同名文件
#: 会把它解析到错的落点（实测：`library.ts:72` 指的其实是上游 `packages/types/src/library.ts`，
#: 却撞上本仓 `frontend/src/stores/library.ts`）⇒ 这类交人工，不报漂移。
#: ⚠️ 只对**上游栈的扩展名**生效（上游是 Next.js 仓，`.ts/.tsx/.js` 才可能撞名）；
#: 裸 `server.py` / `db.py` / `*.md` 之类必是本仓文件 —— 不加这条限制会把「行里恰好提到上游」
#: 的本仓 Python 锚点（实测 5 处 `server.py:*`）误归成上游。
UPSTREAM_HINT = "上游"
UPSTREAM_EXTS = (".ts", ".tsx", ".js", ".jsx", ".mjs")

#: 软判定时在目标行上下各看多少行
RANGE = 6

#: 太泛的符号不参与判定：它们到处都是，命中也不能说明锚点对不对
#: （`db.xxx` 取尾段后是 `xxx`，这里列的是那种「本身就是常见词」的名）
VAGUE = {
    "GET", "POST", "PUT", "PATCH", "DELETE", "api", "db", "id", "version", "items",
    "value", "data", "text", "line", "size", "name", "list", "items", "set", "get",
    "true", "false", "null", "str", "int", "dict", "list", "json", "self",
}

#: 同一符号在目标文件里出现超过这么多次就算「歧义」，交人工而不是报漂移
AMBIGUOUS = 20

#: 这些词出现在锚点那一小句里时**不做符号判定**：那是在引用**历史锚点**
#: （「原引 `server.py:494-504` 今天是 …」），行号本来就该是旧的 —— 判它漂移是误报。
#: 归到「需人工」而不是「通过」：历史引用也不是自动就对。
#: ⚠️ 「真值」句式也必须收进来（第 35 期实测）：文档里最常用的更正写法是
#: 「**文档写** `core/db.py:1546`，**真值** `:2114`」—— 前半截是**记录旧错**，
#: 不加这个词会被报成「`DOCK_TABS` 不在 `:1546` 附近」，反而误导人去改一条正确的叙述。
HISTORICAL = ("原引", "原判", "原写", "文档写", "真值", "作废", "已失效", "已过期", "已删",
              "已成过去", "原先")

#: 符号候选：反引号内容里的**首个标识符**（含点号访问）。取首个而不是「整个反引号必须就是
#: 一个标识符」，是因为文档里最常见的写法是符号后还跟着括号或赋值 ——
#: `` `counts()` ``、`` `DOCK_TABS = ("all", …)` ``、`` `_quiesce_background(fixture)` ``。
#: 按「整个内容就是一个标识符」取会全部漏掉（实测漏报：`DOCK_TABS`）
BACKTICK = re.compile(r"`([^`]+)`")
SPAN_LEAD = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*(?:[.:][A-Za-z_][A-Za-z0-9_]*)*)")
FILELIKE = re.compile(r"\.(?:py|ts|vue|js|json|md|css|html)$")


def resolve(target: str) -> "pathlib.Path | None":
    """把文档里的路径解析成仓内文件；解析不到返回 None。

    两级解析：
      1. **按根拼**（`server.py`、`core/db.py`、`frontend/src/x.vue` 这类）；
      2. **按 basename 反查**（文档里也常只写 `BookDetailView.vue` —— 它其实在
         `frontend/src/views/` 下）。同名多份时取**路径最短**的那个（确定性），
         这类歧义在本仓极少（同名 .vue 不会有两个）。
    """
    p = target.replace("\\", "/")
    for root in ROOTS:
        cand = root / p
        if cand.is_file():
            return cand
    if "/" not in p and p.endswith(".md"):
        # 4. **文档互相引用常写简称**：`capability-gap.md` 实为 `docs/bookorbit-capability-gap.md`、
        #    `settings-inventory.md` 实为 `docs/bookorbit-settings-inventory.md` ⇒ 按名字后缀反查一次。
        hits = sorted((x for x in ALL_FILES if x.suffix == ".md" and x.name.endswith(p)),
                      key=lambda x: (len(x.parts), str(x)))
        if hits:
            return hits[0]
    if "/" not in p:
        hits = sorted((x for x in INDEX.get(p, [])), key=lambda x: (len(x.parts), str(x)))
        if hits:
            return hits[0]
    else:
        # 3. **按后缀反查**：文档里还常写半截路径（`views/ReaderView.vue`、
        #    `settings/pages/WatcherPage.vue`），它们在仓内是 `frontend/src/views/...`。
        #    穷举根目录列不完这些前缀，直接按「路径以它结尾」匹配更省事。
        tail = "/" + p
        hits = sorted((x for x in ALL_FILES if str(x).replace("\\", "/").endswith(tail)),
                      key=lambda x: (len(x.parts), str(x)))
        if hits:
            return hits[0]
    return None


def is_external(target: str) -> bool:
    p = target.replace("\\", "/")
    if "/" not in p:
        return False                      # 裸文件名找不到 ⇒ 是本仓引用丢了，不是外部
    return p.startswith(EXTERNAL_PREFIXES)


def build_index() -> dict:
    """全仓 basename → 路径列表（文档里常只写裸文件名，得能反查到）。

    用 ``os.walk`` + 剪掉大目录：``rglob`` 会一头扎进 ``node_modules``，
    为了一份报告扫几万个文件不值得。
    """
    import os

    skip_dirs = {"node_modules", ".git", "__pycache__", "static", "dist", "build",
                 "output", "input", "cache", "cookies", "data-test", "beautifier",
                 ".venv", ".codebuddy", ".vite", "generated-images"}
    out: dict = {}
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            out.setdefault(name, []).append(pathlib.Path(dirpath) / name)
    return out


INDEX = build_index()

#: 全仓文件列表（后缀反查用）
ALL_FILES = sorted((p for ps in INDEX.values() for p in ps), key=lambda x: (len(x.parts), str(x)))


def line_count(path: pathlib.Path) -> int:
    try:
        return len(path.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError:
        return 0


#: 文件内容缓存（同一次运行里反复读同一个文件没必要）
_FILE_TEXT: dict = {}


def file_text(path: pathlib.Path) -> str:
    key = str(path)
    if key not in _FILE_TEXT:
        try:
            _FILE_TEXT[key] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            _FILE_TEXT[key] = ""
    return _FILE_TEXT[key]


def nearby(path: pathlib.Path, line: int, span: int = RANGE, end: int = None) -> str:
    """锚点前后 ``span`` 行的原文。

    ``end``（区间锚点的右端）必须传：只按右端取窗口的话，`函数:71-90` 这种锚点
    会把窗口落在 90 附近，而函数定义在 71 —— 那就会把一批**本来正确**的锚点
    误报成漂移（本工具第二次跑就是 73 条，其中一大半是这么来的）。
    所以区间锚点取「整个区间 ± span」。
    """
    lines = file_text(path).splitlines()
    lo = max(0, line - 1 - span)
    hi = min(len(lines), (end or line) + span)
    return "\n".join(lines[lo:hi])


def symbols_near(text: str, lo: int, hi: int, anchor_text: str) -> list:
    """锚点**那一小句**里点名的符号（排除锚点自身与文件名）。

    ⚠️ 小句边界 = **被相邻锚点夹住的区间**再按标点收窄，不能整行取：
      · 一行里经常并排写好几个 `文件:行号`（表格单元格尤其如此），整行取会把「别的锚点对应的」
        符号算到这一条头上（第一次跑 154 条，绝大多数是这么来的）；
      · 只按标点切仍不够 —— ``…（`CACHE_TTL` `:25`、`counts()` `:65`）+ `GET /api/x`（`server.py:3572`）``
        里 `CACHE_TTL` 距下一个逗号很远，会被算到后面的锚点上（实测误报）。
        `lo` / `hi` 由调用方按相邻锚点给出，这里只在此基础上再收窄。
    标点分隔符取中文分号 / 分号 / 句号 / 竖线 / 逗号（表格单元格里常用）。
    """
    pos = text.find(anchor_text)
    if pos < 0:
        return []
    # ⚠️ 分隔符只在**反引号之外**才算界：`` `DOCK_TABS = ("all","needs_review",…)` `` 里的逗号
    # 会把小句从中间切断 ⇒ 那个反引号没了闭合、符号被整段吞掉，本该报的漂移静默通过。
    # （第 35 期实测漏报：`capability-gap.md` 里 `core/db.py:1546` 那条点的是 `DOCK_TABS`，
    # 真值在 `:2114` —— 工具当时没报，是人复核出来的。）
    spans = [(m.start(), m.end()) for m in BACKTICK.finditer(text)]
    # ⚠️ `、` 也算界（第 35 期加）：文档里「`A`（`:1`）、`B`（`:2`）」是最常见的并排写法，
    # 少了它，前一条锚点的小句会一路吞到下一个逗号，把后面那条的符号算到自己头上。
    for m in re.finditer(r"[；;。|，,、]", text):
        if any(a <= m.start() < b for a, b in spans):
            continue
        s, e = m.start(), m.end()
        if lo <= s <= pos:
            lo = e
        elif pos < s < hi:
            hi = s
    seg = text[lo:hi]
    out = []
    seen = set()
    # 按**绝对位置**遍历（不再在 seg 切片上遍历），因为下面要回看原文判断
    # 「这个反引号是不是紧跟着**另一条**锚点」
    for m in BACKTICK.finditer(text):
        if m.start() < lo or m.end() > hi:
            continue
        content = m.group(1)
        lead = SPAN_LEAD.match(content)
        if not lead:
            continue
        # 反引号里是**路径**的（`` `docs/x.md` ``、`` `@/components/ui/Icon.vue` ``）不是符号：
        # 只看首段标识符会取出 `docs` / `components` 这种「文件名的第一段」，实测全是误报
        if "/" in content or FILELIKE.search(content) or "\\" in content:
            continue
        sym = lead.group(1)
        if sym in anchor_text:
            continue
        # 文档最常用的写法是「`符号`（`文件:行`）」—— 这种**紧跟另一条锚点**的反引号属于那条锚点，
        # 不该算进前一条的小句（实测误报：`…裁剪（书源管理挂了 `sources`（`:37`）` 把 `sources`
        # 算到了前一个锚点 `ToolsLayout.vue:48-49` 头上）。判据=跳过空白与开括号后能匹配到锚点，
        # 且那条锚点**不是正在核的这条**（否则等于把符号从自己的小句里剔掉，会丢真漂移）。
        _j = m.end()
        while _j < len(text) and text[_j] in " \t（(【[":
            _j += 1
        _nxt = ANCHOR.match(text, _j) or BARE_ANCHOR.match(text, _j)
        if _nxt and _nxt.group(0) != anchor_text:
            continue
        # `db.save_bookmark` / `library.export_rows` 这种带前缀的，真正有信息量的是**尾段**
        # （前缀是模块名，取它只会到处命中）
        tail = sym.split(".")[-1]
        if len(tail) < 3 or tail in VAGUE or tail in seen:
            continue
        seen.add(tail)
        out.append((sym, tail))
    return out


def iter_anchors(line: str) -> list:
    """一行的全部锚点：``(锚点文本, 目标文件, 起始行, 结束行, 是否裸续锚, 起点, 终点)``，按出现次序。

    裸续锚（`:123`）承接**同一行里最近出现过的文件名** —— 表格单元格里基本都这么写。
    尾部的起点/终点给 `symbols_near` 用：靠它把「符号归谁」夹在两个相邻锚点之间。
    """
    out = []
    last_file = ""
    fulls = list(ANCHOR.finditer(line))
    events = [(m.start(), "full", m) for m in fulls]
    events += [(m.start(), "bare", m) for m in BARE_ANCHOR.finditer(line)]
    for _pos, kind, m in sorted(events, key=lambda x: x[0]):
        if kind == "full":
            last_file = m.group(1)
            out.append((m.group(0), m.group(1), int(m.group(2)),
                        int(m.group(3)) if m.group(3) else None, False, m.start(), m.end()))
        elif last_file:
            # 裸锚若被 full 锚的匹配吞掉（`:123` 落在 `x.py:123` 里）就跳过
            if any(e.start() <= m.start() < e.end() for e in fulls):
                continue
            out.append((m.group(0), last_file, int(m.group(1)),
                        int(m.group(2)) if m.group(2) else None, True, m.start(), m.end()))
    return out


def scan(docs: list) -> dict:
    """扫全部文档，返回各判定分组的清单（``ok`` 只数「符号在目标行附近命中」的）。"""
    res: dict = {"missing": [], "range": [], "reversed": [], "drift": [], "unknown": [],
                 "stale": [], "upstream": [], "ok": 0, "total": 0}
    for doc in docs:
        for lineno, line in enumerate(doc.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            anchors = iter_anchors(line)
            for i, (anchor_text, target, a, b, bare, _astart, _aend) in enumerate(anchors):
                res["total"] += 1
                where = f"{doc.relative_to(ROOT)}:{lineno}"
                if bare:
                    where += "（裸续锚）"
                shown = f"{target}:{a}{'-' + str(b) if b else ''}"
                if any(w in line for w in HISTORICAL):
                    # 行内自称「原引 / 作废」⇒ 行号本来就该是旧的，连带硬错一起不判
                    res["stale"].append((where, shown, "本行标注为历史/作废引用，不做判定"))
                    continue
                if ("/" not in target and target.endswith(UPSTREAM_EXTS)
                        and UPSTREAM_HINT in line):
                    res["upstream"].append((where, shown, "裸文件名 + 行内含「上游」：疑指上游同名文件"))
                    continue
                path = resolve(target)
                if path is None:
                    # 外部引用（上游仓）不算断链，但要能看到它们的存在
                    res["missing"].append((where, target, "外部引用" if is_external(target) else "仓内无此文件"))
                    continue
                total_lines = line_count(path)
                if a > total_lines or (b and b > total_lines):
                    if bare:
                        # 裸续锚越界**大概率是继承错了文件名**（表格里最近的那个文件不是它的
                        # 目标），所以不报硬错，交人工 —— 报硬错会让人去改一个本来没错的锚点。
                        res["unknown"].append(
                            (where, shown,
                             f"裸续锚越界（{target} 只有 {total_lines} 行，继承的文件名可能不对）"))
                    else:
                        res["range"].append((where, shown, f"文件只有 {total_lines} 行"))
                    continue
                if b and a > b:
                    res["reversed"].append((where, shown, "区间首尾倒置"))
                    continue
                syms = symbols_near(line, anchors[i - 1][6] if i else 0,
                                    anchors[i + 1][5] if i + 1 < len(anchors) else len(line),
                                    anchor_text)
                names = [tail for _sym, tail in syms]
                if not names:
                    res["unknown"].append((where, shown, "该句没点名符号，需人工看"))
                    continue
                blob = nearby(path, a, end=b)
                if any(n in blob for n in names):
                    res["ok"] += 1
                    continue
                # 符号不在附近：再看它在整个文件里出现几次。取**最具体的那个**（出现最少）
                # 作判据：1~20 次 = 定位得到但跑偏了（漂移）；>20 次 = 到处都是，
                # 机器说了不算（交人工）；一次都没有 = 符号已不在这个文件（强信号）。
                whole = file_text(path)
                counts = {n: whole.count(n) for n in names}
                best = min(counts.values())
                note = "该句点名的 " + "、".join(names) + " "
                if best == 0:
                    res["drift"].append((where, shown, note + "在该文件里已不存在", path, names))
                elif best > AMBIGUOUS:
                    res["unknown"].append((where, shown, note + f"出现 {best} 次，太泛，需人工看"))
                else:
                    res["drift"].append((where, shown, note + "不在目标行附近", path, names))
    return res


def suggest(path: pathlib.Path, symbols: list, maxn: int = 4) -> list:
    """符号在当前文件里的**真实行号**（给漂移项一个可直接抄的候选）。

    只按符号名找（``def save_bookmark`` / ``export_rows`` / ``CACHE_TTL`` 都能命中），
    命中多处时全部列出让人挑 —— 工具不替人决定「哪一处才是文档想说的那一处」。
    """
    lines = file_text(path).splitlines()
    out = []
    for name in symbols[:2]:
        hits = [(i, ln.strip()[:80]) for i, ln in enumerate(lines, 1) if name in ln]
        out.append((name, hits[:maxn], len(hits)))
    return out


def print_group(title: str, rows: list, shown: int) -> None:
    print(f"\n== {title}：{len(rows)} 条 ==")
    for row in rows[:shown]:
        print("  " + "  |  ".join(str(x) for x in row))
    if len(rows) > shown:
        print(f"  …（还有 {len(rows) - shown} 条，用 --limit 调大或 --file 收窄）")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="文档锚点核验（只读，不改任何文件）")
    ap.add_argument("--file", default="", help="只看锚点指向这个文件的引用（如 server.py）")
    ap.add_argument("--drift", action="store_true", help="只输出「疑似漂移」清单")
    ap.add_argument("--limit", type=int, default=40, help="每组最多打印多少条（默认 40）")
    ap.add_argument("--strict", action="store_true", help="有硬错（缺文件 / 越界 / 倒置）时退出码 1")
    ap.add_argument("--suggest", action="store_true",
                    help="对每条漂移给出「符号的真实行号」候选（可直接抄进文档）")
    ap.add_argument("--todo", action="store_true",
                    help="输出「待人工复核清单」：没点符号的锚点 + 目标行原文，便于并排核对")
    args = ap.parse_args(argv)

    skips = tuple(g.rstrip("*") for g in SKIP_DOCS)
    docs = sorted(p for p in (ROOT / "docs").rglob("*.md")
                  if not str(p.relative_to(ROOT)).startswith(skips))
    if not docs:
        print("没找到 docs/*.md")
        return 2
    res = scan(docs)

    print(f"文档锚点核验：扫 {len(docs)} 份文档、{res['total']} 处 `文件:行号`"
          f"（跳过 {', '.join(SKIP_DOCS)}）")
    print(f"  符号命中（自动通过）{res['ok']} 条 / 疑似漂移 {len(res['drift'])} 条 / "
          f"需人工看 {len(res['unknown']) + len(res['stale']) + len(res['upstream'])} 条"
          f"（没点符号 {len(res['unknown'])} + 历史引用 {len(res['stale'])} + 疑上游裸名 {len(res['upstream'])}）"
          f" / 硬错 {len(res['range']) + len(res['reversed'])} 条 / "
          f"目标不在此仓 {len(res['missing'])} 条")

    def keep(row) -> bool:
        return (not args.file) or (args.file in row[1])

    missing = [r for r in res["missing"] if keep(r)]
    hard = [r for r in res["range"] + res["reversed"] if keep(r)]
    drift = [r for r in res["drift"] if keep(r)]

    if not args.drift:
        print_group("目标不在本仓（外部引用属正常，仓内缺失才是问题）", missing, args.limit)
        print_group("硬错（文件不存在 / 行号越界 / 区间倒置）", hard, args.limit)
        print_group("需人工判断（该句没点名符号 / 符号太泛）", [r for r in res["unknown"] if keep(r)], args.limit)
        print_group("历史/作废引用（行号本就该是旧的，不判）", [r for r in res["stale"] if keep(r)], args.limit)
        print_group("疑上游同名文件（裸文件名 + 行内含「上游」）", [r for r in res["upstream"] if keep(r)], args.limit)
    print_group("疑似漂移（该句点名的符号不在目标行附近）",
                [r[:3] for r in drift], args.limit)
    if args.todo:
        # 这一类是**工具天生测不出**的：文档那句没点名任何符号，机器无从判断
        # 「行号还在、但指的内容已经换了」。唯一有效的手法是**并排打印**
        # 「锚点声称的位置」与「该位置的真实原文」，靠人一眼认出对不对。
        # 先按目标文件分组（同一文件的引用一起看效率最高），再按行号升序。
        print("\n---- 待人工复核清单（没点符号的锚点：并排看「声称位置 vs 真实原文」）----")
        rows = []
        for where, shown, _note in res["unknown"]:
            if not keep((where, shown, _note)):
                continue
            tgt, _, rng = shown.rpartition(":")
            path = resolve(tgt)
            if path is None:
                continue
            try:
                first = int(rng.split("-")[0])
            except ValueError:
                continue
            lines = file_text(path).splitlines()
            src = lines[first - 1].strip()[:110] if 0 < first <= len(lines) else "<行号越界>"
            # 也要把**文档自己的那一行**打出来：不然只有「目标行原文」，没法判断
            # 「文档这句声称的东西」跟它对不对得上 —— 并排才是人唯一能判的形态。
            m = re.match(r"(docs/[^:]+):(\d+)", where)
            claim = "<读不到>"
            if m:
                dlines = (ROOT / m.group(1)).read_text(encoding="utf-8").splitlines()
                di = int(m.group(2))
                if 0 < di <= len(dlines):
                    dl = dlines[di - 1].strip()
                    # 表格行动辄几百字符 ⇒ 只截「锚点前后各 70 字」，否则关键上下文全被截掉
                    i = dl.find(shown)
                    claim = dl if i < 0 else (
                        ("…" if i > 70 else "") + dl[max(0, i - 70): i + len(shown) + 70]
                        + ("…" if i + len(shown) + 70 < len(dl) else "")
                    )
            rows.append((str(path.relative_to(ROOT)), first, where, shown, src, claim))
        rows.sort(key=lambda r: (r[0], r[1]))
        cur = None
        for f, _first, where, shown, src, claim in rows:
            if f != cur:
                cur = f
                print(f"\n  【{f}】")
            print(f"    {where}  →  {shown}\n        文档: {claim}\n        实况: {src}")
        print(f"\n  合计 {len(rows)} 条（其中「历史/作废引用」与「疑上游裸名」已单独归类，不在此列）")

    if args.suggest:
        print("\n---- 漂移项的「符号真实行号」候选（抄实测行号，别记偏移量）----")
        for row in drift:
            where, anchor, _note, path, syms = row
            print(f"  {where} → {anchor}")
            for base, hits, total in suggest(path, syms):
                shown = "；".join(f"{i}: {txt}" for i, txt in hits) or "（该文件里没有这个符号）"
                print(f"      {base}（{total} 处）{shown}")

    print("\n提示：硬错要修；疑似漂移要逐条打开看 —— 行号合法但内容换了的（工具测不出）"
          "只能靠人。修的时候写**实测行号**，不要记偏移量。")
    if args.strict and (hard or any("仓内无此文件" in r[2] for r in missing)):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
