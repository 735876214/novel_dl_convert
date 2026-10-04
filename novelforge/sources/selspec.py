"""取值 spec 的**唯一**解析与执行（第 94 期 · 阶段 2a）。

「取值 spec」= `search.container` / `search.fields.*` / `book.toc.*` / `book.content.container`
这些位置上的那个字符串。本项目自己的写法（标准 CSS + `::attr(href)`）与「阅读」的写法
（`class.x@tag.a.0@href##正则##替换`）**写在同一个位置**上，所以只许有**一个**解析器 ——
就是这个模块。阅读转换器（`legado.py`）只负责把整条规则拼起来，选择器**只有这里会解析**；
`rules.py` 的每个取值点都从这里拿节点/值，**自己不再碰选择器字符串**。

## 语法（每条都标了实测出处：`202003.txt` 1537 条 + XIU2 `shuyuan` 22 条）

| 写法 | 含义 | 实测次数 |
|---|---|---|
| `.a.b` / `a[href]` / `h2` / `.wrap a` | 标准 CSS，原样（空格 = 后代） | 既有 native 规则 |
| `class.a` / `id.a` / `tag.a` | 阅读前缀 → `.a` / `#a` / `a` | 3.x `class.section-list.-1@tag.a` |
| `class.a b c` | **同一个元素**的多个类 → `.a.b.c` | `class.fl color7@tag.span.0@tag.a.0@text`（含空格的 412 处） |
| `@tag.a` / `@css:a,.b` | 同上（`@` 开头）/ 后面整段就是 CSS | `@css:a.btn-mulu,.page_num>.y@href` |
| `a@text` / 裸 `text` | 取文本（默认方式） | `@text` 6038 · 裸 `text` 476 |
| `@textNodes` | 取文本（与 `text` 同义） | 753 |
| `@ownText` | 只取本节点的直接文本（不含子节点） | 5 |
| `@html` | 保留标签 | 318 |
| `@all` | 取**全部**匹配并逐行拼接 | 阅读通用 |
| `@href` / 裸 `href` / `@attr(x)` / `::attr(x)` | 取属性 | `@href` 2444 · 裸 `href` 531 |
| `@children` | 取当前节点的**子元素**（容器常用） | `class.cover@children` 35 |
| `!n` / `!-n` / `!a:b:c` | 取匹配列表里第 n 个（可负、可多段） | `#author tbody tr!0`、`.mySearch ul!-1` |
| `.n` | 同上（2.x 写法） | `.odd.0`、`a.0`、`class.book-part-list.-1@a` |
| `A\\|B` / `A\\|\\|B` | 候选：取**第一个非空**的 | 3.x `\\|\\|`；2.x 单 `\\|`（`class.author@text\\|class.author ellipsis@text`） |
| `A&&B` | 拼接（两边的值接起来） | `class.book-author.2@text&&class.book-zt@text` |
| `选择器##正则##替换` | 取到值后再替换（可多段，`$1` 自动转 `\\g<1>`）；只写 `##正则` 表示**删掉**命中段 | `.author text##作者：`、`href##$##,`（实测 663 处能编译 / 667） |

### 三个容易写错的顺序问题（都按实测口径定死）

1. **先摘 `##`，再切候选**，不能反过来。实测
   `data.content##.*(恋上你看书|630bookla|…).*|看深夜福利.+` —— 那个 `|` 在**替换正则里面**，
   先切候选会把这条替换切成两半，静默改坏取值。
2. **候选是单竖线**。阅读 2.x 用**一个** `|`（`class.author@text|class.author ellipsis@text`），
   3.x 才用 `||`；两种都认。`[]` / `()` / 引号**里面**的 `|` 不切（`[lang|en]`、`a[href*="&&"]`）。
3. **`@` 后面是标签还是属性**：先查已知属性名（`@href` / `@title` / `@content` / `data-*`），
   再查标签词表（`@a` 178 次、`@li` 81、`@dl` 12 是**后代标签**），都不是就当属性（`@txt`）。
   裸词只在**第一段**且确实是标签时当元素（`a`）、在属性表里时当属性（`href`）—— 于是
   `name` / `author` / `cover` 这类（只在 json 通道里当键名出现）行为**与今天一字不差**。

### 索引的语义（不做近似翻译）

`!n` / `.n` 的语义是「**取匹配列表里的第 n 个**」，不是 CSS 的 `:nth-of-type(n+1)`。
`#author tbody tr!0` 恰好等价（tr 互为兄弟），但 `.odd.0` 跨多个父节点时两者结果不同 ——
所以这里真的按结果列表取（`nodes[n]`），不做「差不多等价」的翻译。

### 绝不抛异常（本期红线）

`#author tbody tr!0` / `.odd.0` / `a.0` 直接交给 `soup.select_one` 会抛
`SelectorSyntaxError`（`tests/test_convert_honesty.py::test_索引语法真的会抛异常` 钉着这条），
而搜索与目录的调用点**没有 try 保护** ⇒ 从前一条「判可用」的规则一搜就让整次搜索 500。
本模块把所有选择器错误落成 ``plan.error`` + **空值**，调用点不需要 try；错误原文（人话）
由诚实闸与「查看原因」界面直接展示。

⚠️ 有几处是**故意**解析成 ``error`` 而不是硬塞进 CSS 的：`@js:` / `<js>`（要执行脚本）、
`$…` / `JSon:`（JSON 路径）、`//xpath`（XPath 通道）、单个 `#`（把 `##` 写错了）。
它们各自有负责的通道/语法，报「通道对不上」比报「不是合法 CSS」可照做得多。
"""
from __future__ import annotations

import re
from functools import lru_cache

__all__ = ["Plan", "Step", "parse_spec", "select", "one", "value", "render",
           "check_css", "spec_error", "replace_text", "apply_replace"]


# ---------------- 词表（**唯一**定义处）----------------

#: 取值方式关键字：整段就是它时表示「怎么取值」，不是选择器。
_MODES = {"text": "text", "textnodes": "text", "all": "all",
          "html": "html", "owntext": "own"}
#: 取子元素（容器常用）：`class.cover@children`。
_CHILDREN = "children"

#: **已知属性名**（阅读语法里 `@` 后面的属性）。实测：`@href` 2444、`@src` 1445、
#: `@content` 474、`@title` 22、`@data-original` 27。`data-*` 另按前缀认。
#: ⚠️ 这张表要**先于**标签词表查：`title` 既是标签名也是属性名，而 `tag.a@title` 取的是
#: a 的 title **属性**（实测 22 处），按标签处理会静默取到空值。
_ATTRS = frozenset({"href", "src", "_src", "poster", "alt", "value",
                    "content", "title", "txt"})

#: HTML 标签名：`@` 后面既可能是标签（`@a` 178 次、`@li` 81、`@dl` 12）
#: 也可能是属性 —— 用**标签词表**区分，不猜。标准标签集，一份。
_TAGS = frozenset({
    "a", "abbr", "address", "area", "article", "aside", "audio", "b", "base", "bdi",
    "bdo", "blockquote", "body", "br", "button", "canvas", "caption", "cite", "code",
    "col", "colgroup", "data", "datalist", "dd", "del", "details", "dfn", "dialog",
    "div", "dl", "dt", "em", "embed", "fieldset", "figcaption", "figure", "footer",
    "form", "h1", "h2", "h3", "h4", "h5", "h6", "head", "header", "hgroup", "hr",
    "html", "i", "iframe", "img", "input", "ins", "kbd", "label", "legend", "li",
    "link", "main", "map", "mark", "menu", "meter", "nav", "noscript", "object",
    "ol", "optgroup", "option", "output", "p", "param", "picture", "pre", "progress",
    "q", "rp", "rt", "ruby", "s", "samp", "script", "section", "select", "slot",
    "small", "source", "span", "strong", "style", "sub", "summary", "sup", "table",
    "tbody", "td", "template", "textarea", "tfoot", "th", "thead", "time", "title",
    "tr", "track", "u", "ul", "var", "video", "wbr",
})

#: 阅读的「前缀.名」写法（`class.a` → `.a`）。
_PREFIX = {"class": ".", "id": "#", "tag": ""}

#: 索引后缀：`!0` / `!-1` / `!0:1:-1` / `!`；`.0` / `.-1`。
_INDEX_BANG = re.compile(r"!(?P<spec>-?\d*(?::-?\d*)*)\s*$")
_INDEX_DOT = re.compile(r"\.(?P<spec>-?\d+)\s*$")
#: 单竖线的**误用**：`text#某个东西`（实测有作者把 `##` 写成 `#`）。
_MALFORMED_HASH = re.compile(r"^(?:text|textnodes|owntext|html|all)#", re.I)
#: 一段是不是「一个词」（用来判标签 / 属性名）。
_WORD = re.compile(r"[A-Za-z_][\w-]*")
#: 索引写在了**一段的中间**（`tr!0 li`）：`!` 后面是数字，但数字后面还有东西。
#: 留一个可照做的错（「用 `@` 分段」），不给的话用户只能看到「不是合法 CSS 选择器」。
_INDEX_MID = re.compile(r"!-?\d+(?::-?\d+)*(?=\s|$)")

_OPENERS = {"[": "]", "(": ")"}
_CLOSERS = {"]": "[", ")": "("}
_QUOTES = "\"'"


class Step:
    """一步选择：``css`` 选择器 + 索引 + 种类（``desc`` 后代 / ``children`` 子元素）。"""

    __slots__ = ("css", "index", "kind")

    def __init__(self, css: str = "", index: str = "", kind: str = "desc"):
        self.css = css
        self.index = index
        self.kind = kind

    def render(self) -> str:
        """还原成 spec 文本（索引写成 `!n`，`children` 写成 `@children`）。"""
        if self.kind == "children":
            return f"{self.css}@{_CHILDREN}" if self.css else f"@{_CHILDREN}"
        return f"{self.css}{'!' + self.index if self.index else ''}"

    def __repr__(self) -> str:                              # pragma: no cover —— 调试用
        return f"Step({self.render()!r})"


class Plan:
    """一个 spec 的解析结果。**只读**（解析结果按原文缓存并共享，改它会影响所有人）。"""

    __slots__ = ("raw", "steps", "sub", "combine", "attr", "mode", "replace", "error", "note")

    def __init__(self, raw: str = "", steps: tuple = (), sub: tuple = (), combine: str = "",
                 attr: str = "", mode: str = "text", replace: tuple = (),
                 error: str = "", note: str = ""):
        self.raw = raw
        self.steps = steps                # ((Step, …),)
        self.sub = sub                    # 候选（or）/ 拼接（and）的子计划
        self.combine = combine            # "" | "or" | "and"
        self.attr = attr                  # 取这个属性（空 = 按 mode 取文本/HTML）
        self.mode = mode                  # text | own | html | all
        self.replace = replace            # ((已编译的正则, 替换), …)
        self.error = error
        self.note = note

    # ---- 便捷判定 ----
    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def is_self(self) -> bool:
        """空 spec / `"."` = **节点自身**（字段取值相对条目容器时的默认）。"""
        return not self.error and not self.steps and not self.sub

    @property
    def has_index(self) -> bool:
        return any(st.index for st in self.steps)

    def render(self, *, drop_first_index: bool = False) -> str:
        """还原成 spec 文本（**选择部分**：步骤 + 属性 + `@html`/`@all` + `##替换`）。

        ``drop_first_index=True`` 用在**字段取值**上：取一个值时「第一个匹配」本来就是默认
        （`value()` 只取 ``nodes[0]``），`!0` 留着只会让界面上多一段噪音；**容器**不许丢
        （容器的默认是「全部匹配」，丢了 `!0` 就从「取第一项」变成「取所有项」）。
        """
        if self.sub:
            sep = " && " if self.combine == "and" else "||"
            text = sep.join(s.render(drop_first_index=drop_first_index) for s in self.sub)
        else:
            steps, juicy = [], False
            for st in self.steps:
                if drop_first_index and st.kind == "desc" and st.index == "0":
                    steps.append(st.css)          # 第一个匹配本来就是默认 ⇒ 索引是噪音
                    continue
                steps.append(st.render())
                juicy = juicy or bool(st.index) or st.kind == "children"
            # ⚠️ 步与步之间用空格还是 `@` **不是样式问题**：带索引的步（`#list!0`）或
            #    `@children` 步**后面接空格就再也解析不回来** —— `_strip_index` 只认段尾的索引，
            #    `#list!0 dl` 会被当成一整段 CSS（`!0` 摘不掉 ⇒ 编译器报错 / 去找 `<children>` 标签）。
            #    出现这两种步时改用 `@` 连接（阅读本来就这么写），保证 render → parse 往返一致。
            text = ("@" if juicy else " ").join(s for s in steps if s)
        if self.attr:
            text = f"{text}::attr({self.attr})" if text else f"::attr({self.attr})"
        else:
            if self.mode == "html":
                text = f"{text}@html" if text else ""
            elif self.mode == "all":
                text = f"{text}@all" if text else ""
        for pat, repl in self.replace:
            text += f"##{pat.pattern}##{_to_legacy_repl(repl)}" if repl else f"##{pat.pattern}"
        return text

    def __repr__(self) -> str:                              # pragma: no cover —— 调试用
        return f"Plan({self.render()!r}{' error=' + self.error if self.error else ''})"


# ---------------- 切分（括号/引号内的分隔符不算）----------------

def _split_outside(text: str, seps: tuple) -> list:
    """按 ``seps`` 切分，**跳过** `[...]` / `(...)` / 引号里的内容。

    `[lang|en]`、`a[href*="&&"]`、`a[href*="##"]` 里的分隔符是选择器的一部分，
    切开就是把一条能跑的规则改坏 —— 这类静默改坏最难查。
    """
    out, buf, depth, quote, i = [], [], 0, "", 0
    while i < len(text):
        ch = text[i]
        if quote:
            buf.append(ch)
            quote = "" if ch == quote else quote
            i += 1
            continue
        if ch in _QUOTES:
            quote = ch
            buf.append(ch)
            i += 1
            continue
        if ch in _OPENERS:
            depth += 1
        elif ch in _CLOSERS:
            depth = max(0, depth - 1)
        if depth == 0:
            hit = next((s for s in seps if text.startswith(s, i)), "")
            if hit:
                out.append("".join(buf))
                buf = []
                i += len(hit)
                continue
        buf.append(ch)
        i += 1
    out.append("".join(buf))
    return out


# ---------------- 一段（`@` 分隔的单元）的解析 ----------------

def _strip_index(part: str) -> "tuple[str, str]":
    """摘掉段尾的索引 → ``(剩下的选择器, 索引原文)``。`!0` / `!-1` / `!0:1` / `.0` 都认。"""
    m = _INDEX_BANG.search(part)
    if m:
        # ⚠️ 索引前面那个点要一起摘掉：实测真源写 `tag.p.!-1`（点 + `!`），留下的 `p.`
        # 会被当成「类选择器 p.」⇒ 编译报错（或更糟：静默取到别的元素）。`!` 前面的
        # 结尾点号在 CSS 里本来也不合法，摘掉是安全的。
        return part[:m.start()].rstrip(".").strip(), m.group("spec").strip()
    m = _INDEX_DOT.search(part)
    if m:
        # ⚠️ 只在**点是数字的点**时才算索引：`.item2` 的 `2`、`a[href*="x.2"]` 都不是索引。
        head = part[:m.start()]
        if head and not head.endswith(".") and not head.endswith("]"):
            return head.strip(), m.group("spec")
    return part.strip(), ""


def _prefixed_css(kind: str, rest: str) -> str:
    """`class.read-content j_readContent` → ``.read-content.j_readContent``。

    ⚠️ 空格在 `class.` 段里表示**同一个元素上的多个类**（实测 412 处含空格：
    `class.fl color7@tag.span.0@…`、`class.read-content j_readContent@tag.p@text`），
    不是后代选择器 —— 阅读用 `@` 分隔后代。纯 CSS 段里的空格才按后代处理（`.wrap img`）。
    """
    words = [w for w in rest.split() if w]
    if not words:
        return ""
    if kind == "tag":
        css, extra = words[0], words[1:]
    else:
        head = words[0].lstrip(".#")
        css = f"{_PREFIX[kind]}{head}"
        extra = words[1:]
    for w in extra:
        css += f".{w.lstrip('.#')}"
    return css


def _classify(part: str, *, first: bool) -> "tuple[str, str, str, str]":
    """一段 → ``(种类, css 或值, 索引, 错误)``；种类 ∈ desc / children / mode / attr。"""
    text, idx = _strip_index(part)
    if not text:
        return "desc", "", idx, ""
    m_mid = _INDEX_MID.search(text)
    if m_mid:
        # 索引只写在**它取的那一段**末尾（实测真样本全是 `tr!0` / `.odd.0` / `p.!-1`）。
        # `tr!0 li` 里那个 `!0` 没人认，整段会被当成 CSS ⇒ 编译报错，用户看不出该怎么改。
        return "desc", "", "", (
            f"「{text}」里的索引 `{m_mid.group(0)}` 后面还接着选择器 —— 索引要写在"
            "**它取的那一段**末尾；后面还要往下选就用 `@` 分段（`tr!0@a`），不要用空格")
    low = text.lower()
    if _MALFORMED_HASH.match(text):
        return "desc", "", "", (f"「{text}」里的 `#` 只写了一个 —— 阅读的替换分隔符是**两个** `#`"
                                "（`选择器##正则##替换`），单个 `#` 会被当成 CSS 的 id 选择器")
    if low.startswith("css:"):
        rest = text[4:].strip()
        return ("desc", rest, idx, "") if rest else ("desc", "", "", f"「{text}」后面没写选择器")
    if low.startswith(("js:", "@js", "json:", "jsonpath:", "json@")):
        return "desc", "", "", f"「{text}」要在选择器通道里执行脚本 / JSON 路径（通道对不上）"
    if text.lstrip("(").startswith("/"):
        return "desc", "", "", (f"「{text}」是 XPath —— 本项目的选择器通道是 CSS"
                                "（XPath 见 mode=\"xpath\"）")
    if text.startswith("$"):
        return "desc", "", "", f"「{text}」是 JSON 路径，不是 CSS 选择器"
    if low in _MODES:
        return "mode", _MODES[low], "", ""
    if low == _CHILDREN:
        return "children", "", idx, ""
    m = re.fullmatch(r"attr\(\s*([^)]*?)\s*\)", text, re.I)
    if m:
        name = m.group(1)
        return ("attr", name, "", "") if name else ("desc", "", "", f"「{text}」里没写属性名")
    head, _, rest = text.partition(".")
    if rest and head.lower() in _PREFIX:
        css = _prefixed_css(head.lower(), rest)
        return ("desc", css, idx, "") if css else ("desc", "", "", f"「{text}」里没写选择器名")
    if _WORD.fullmatch(text):
        # ① 已知属性名（`@href` / `@title` / `@data-src` / 裸 `href`）—— 必须**先于**标签查
        if low in _ATTRS or low.startswith("data-"):
            return "attr", text, "", ""
        # ② 标签名（`@a` / `@li` / 裸 `a`）
        if low in _TAGS:
            return "desc", text, idx, ""
        # ③ `@` 后面既不是标签也不是已知属性 ⇒ 属性名（阅读就这个口径，实测 `@txt` / `@_src`）
        if not first:
            return "attr", text, "", ""
    return "desc", text, idx, ""                  # 已是 CSS（`.intro` / `a[data-bid]` / `h2`）


def _steps_of(chain: str) -> "tuple[tuple, str, str, str]":
    """一条链 → ``(steps, attr, mode, error)``。

    ⚠️ 空的**首段**是合法的（`@css:.x` / `@text` 这种以 `@` 开头的阅读写法）；
    中间出现空段（`@@bad` / 结尾多一个 `@`）是**语法错**，必须报出来 —— 静默忽略会变成
    「这条选择器看着没写错，却永远取不到值」。
    """
    # 本项目自己的取值后缀 `::attr(href)`（native 规则从第 86 期起就这么写）：先摘下来，
    # 剩下的当纯选择器。**与阅读的 `@href` 是同一种东西**，只是两个写法 —— 都得认。
    m = re.search(r"::attr\(\s*([^)]*)\)", chain)
    tail_attr = ""
    if m:
        tail_attr = m.group(1).strip()
        chain = (chain[:m.start()] + chain[m.end():]).strip()
        if not tail_attr:
            return (), "", "", f"「{m.group(0)}」里没写属性名"
    steps: list = []
    attr, mode = "", "text"
    for i, raw in enumerate(_split_outside(chain, ("@",))):
        if raw.strip() == "":
            if i == 0:
                continue
            return (), "", "", f"选择器「{chain}」里有一个空的 `@` 段（`@@` 或结尾多一个 `@`）"
        kind, val, idx, bad = _classify(raw, first=not steps)
        if bad:
            return (), "", "", bad
        if kind == "mode":
            mode = val
        elif kind == "attr":
            attr = val
        elif kind == "children":
            steps.append(Step(index=idx, kind="children"))
        elif val:
            steps.append(Step(css=val, index=idx))
        elif idx and steps:
            # 纯索引段（`class.a@!0`）：索引归**上一步**，别把用户写的索引吃掉。
            steps[-1] = Step(css=steps[-1].css, index=idx, kind=steps[-1].kind)
    if tail_attr:
        # `::attr(x)` 是链的尾部取值方式：与 `@x` 撞车时以**它**为准（写在后面的赢）。
        attr = tail_attr
    return tuple(steps), attr, mode, ""


def _to_legacy_repl(repl: str) -> str:
    """Python 的替换串 → 阅读的替换串（``\\g<1>`` → ``$1``）—— `render()` 还原用。"""
    return re.sub(r"\\g<(\d+)>", r"$\1", str(repl or ""))


def _to_pyrepl(repl: str) -> str:
    """阅读的替换串 → Python 的替换串：``$1`` → ``\\g<1>``（``$0`` → ``\\g<0>``）。"""
    return re.sub(r"\$(\d+)", r"\\g<\1>", str(repl or ""))


def _replace_of(pieces: list) -> "tuple[tuple, str]":
    """`##` 之后的各段 → ``((已编译正则, 替换), …)``（成对；落单的那段表示**删掉**命中）。"""
    out, note = [], ""
    for i in range(0, len(pieces), 2):
        pat = pieces[i]
        repl = pieces[i + 1] if i + 1 < len(pieces) else ""
        if not pat and not repl:
            continue
        try:
            out.append((re.compile(pat, re.S), _to_pyrepl(repl)))
        except Exception as e:                     # noqa: BLE001 —— 如实记 note，不抛异常
            note = (f"替换用的正则编译不过（这一段当成没写）：{pat}"
                    f"（{type(e).__name__}: {e}）")
    return tuple(out), note


def _chain_plan(body: str, raw: str) -> Plan:
    """一条链（已切好候选/拼接、已摘掉 `##`）→ Plan。"""
    steps, attr, mode, err = _steps_of(body)
    if err:
        return Plan(raw=raw, error=err)
    return Plan(raw=raw, steps=steps, attr=attr, mode=mode)


def _plan(text: str) -> Plan:
    """**核心解析**（不含缓存）：`##` → 候选 → 拼接 → 步骤。"""
    pieces = _split_outside(text, ("##",))
    body = pieces[0]
    replace, note = _replace_of(pieces[1:])
    cands = _split_outside(body, ("||", "|"))
    if len(cands) > 1:
        subs, bad = [], ""
        for c in cands:
            sub = _chain_plan(c, text)
            bad = bad or sub.error
            subs.append(sub)
        if bad:
            return Plan(raw=text, error=bad, note=note)
        return Plan(raw=text, sub=tuple(subs), combine="or", replace=replace, note=note)
    parts = _split_outside(body, ("&&",))
    if len(parts) > 1:
        subs, bad = [], ""
        for p in parts:
            sub = _chain_plan(p, text)
            bad = bad or sub.error
            subs.append(sub)
        if bad:
            return Plan(raw=text, error=bad, note=note)
        return Plan(raw=text, sub=tuple(subs), combine="and", replace=replace, note=note)
    plan = _chain_plan(body, text)
    plan.replace = replace
    plan.note = note
    return plan


@lru_cache(maxsize=4096)
def parse_spec(raw) -> Plan:
    """spec 文本 → :class:`Plan`（**只读**，按原文缓存）。

    * 空 / `"."` / `"./"` ⇒ 节点自身（字段取值相对条目容器时的默认）。
    * 解析失败 ⇒ ``plan.error`` 是一句人话（选择器语法错、空的 `@` 段、通道对不上…），
      ``select`` / ``value`` 一律返回空 —— **调用点不需要 try**。
    """
    text = str(raw or "").strip()
    if text in ("", ".", "./"):
        return Plan(raw=text)
    return _plan(text)


# ---------------- 执行 ----------------

def _take(nodes: list, index: str) -> list:
    """按索引原文取子集：`""` 全取；`0` / `-1` 单个；`0:1:-1` 多段（越界的那段**跳过**）。"""
    spec = str(index or "").strip()
    if not spec:
        return nodes
    out = []
    for piece in spec.split(":"):
        piece = piece.strip()
        if not piece:
            continue
        try:
            want = int(piece)
        except ValueError:
            return nodes                       # 坏索引当没写（解析期已给过 error/note）
        try:
            out.append(nodes[want])
        except IndexError:
            continue
    return out


def select(root, plan) -> list:
    """按计划取**节点列表**。永不抛异常：选择器语法错 ⇒ 空列表（原因在 ``plan.error``）。"""
    if root is None or not isinstance(plan, Plan) or plan.error:
        return []
    if plan.sub:
        if plan.combine == "and":
            out = []
            for sub in plan.sub:
                out += select(root, sub)
            return out
        for sub in plan.sub:                       # or：取第一个非空的
            got = select(root, sub)
            if got:
                return got
        return []
    nodes = [root]
    for st in plan.steps:
        nxt = []
        for n in nodes:
            try:
                if st.kind == "children":
                    nxt += n.find_all(recursive=False)
                elif st.css:
                    # `n.select(css)` 就是「在 n 里面找」的语义（与 `soup.select` 同口径）。
                    nxt += n.select(st.css)
                else:
                    nxt.append(n)              # 纯索引步 / `"."` = 自身
            except Exception:                  # noqa: BLE001 —— soupsieve 的语法错落在这里
                return []
        nodes = _take(nxt, st.index)
        if not nodes:
            return []
    return nodes


def one(root, plan):
    """取**第一个**节点（没有就 ``None``）。容器用第一个、字段用第一个都走它。"""
    nodes = select(root, plan)
    return nodes[0] if nodes else None


def _value_raw(root, plan) -> str:
    """取值（**不含** `##` 替换）—— 替换只在整个计划的最外层做一次。"""
    if plan.sub:
        if plan.combine == "and":
            return "".join(_value_raw(root, sub) for sub in plan.sub)
        for sub in plan.sub:
            got = _value_raw(root, sub)
            if got:
                return got
        return ""
    nodes = select(root, plan)
    if not nodes:
        return ""
    if plan.mode == "all":
        return "\n".join(v for v in (_text_of(n, plan) for n in nodes) if v)
    return _text_of(nodes[0], plan)


def _text_of(node, plan: Plan) -> str:
    """从一个节点按计划取值（属性 / HTML / 自身直接文本 / 文本）。"""
    if plan.attr:
        try:
            v = node.get(plan.attr, "")
        except Exception:                          # noqa: BLE001 —— 坏节点当空
            return ""
        return str(v if v is not None else "")
    if plan.mode == "html":
        return str(node)
    if plan.mode == "own":
        parts = []
        for t in node.find_all(string=True, recursive=False):
            s = str(t).strip()
            if s:
                parts.append(s)
        return " ".join(parts)
    try:
        return node.get_text(" ", strip=True)
    except Exception:                              # noqa: BLE001
        return str(node)


def apply_replace(text: str, plan) -> str:
    """把计划里带的 `##正则##替换` 依次作用到值上（没有替换时原样返回）。"""
    out = str(text or "")
    for pat, repl in getattr(plan, "replace", ()) or ():
        try:
            out = pat.sub(repl, out)
        except Exception:                          # noqa: BLE001 —— 替换坏当没写
            continue
    return out


def value(root, plan) -> str:
    """按计划取**一个值**。永不抛异常：失败返回空串（原因在 ``plan.error``）。"""
    if root is None or not isinstance(plan, Plan) or plan.error:
        return ""
    return apply_replace(_value_raw(root, plan), plan)


def render(plan, *, drop_first_index: bool = False) -> str:
    """计划 → spec 文本（`Plan.render` 的函数式入口，供 `legado.convert` 用）。"""
    return plan.render(drop_first_index=drop_first_index) if isinstance(plan, Plan) else ""


def replace_text(text: str, pattern: str, repl: str) -> "tuple[str, str]":
    """单条替换（`ruleContent.replaceRegex` 那类**独立**替换段用）。

    与 `##正则##替换` 是**同一份**语义（`$1` → ``\\g<1>``，正则只编译一次）——
    「替换」这件事只许有这一处实现。返回 ``(结果, 错误原文)``；错误**不抛异常**，
    调用方按「这次没替换」如实处理。
    """
    if not pattern:
        return str(text or ""), ""
    try:
        pat = re.compile(pattern, re.S)
    except Exception as e:                         # noqa: BLE001 —— 原文给人看
        return str(text or ""), f"{type(e).__name__}: {e}"
    try:
        return pat.sub(_to_pyrepl(repl), str(text or "")), ""
    except Exception as e:                         # noqa: BLE001
        return str(text or ""), f"{type(e).__name__}: {e}"


def check_css(css: str) -> str:
    """这个 CSS 选择器能被编译器编译吗？返回错误原文（空串 = 没问题 / 查不了）。

    ⚠️ 用 `soupsieve`（bs4 的依赖，`requirements.txt` 已声明）**真的编译一次** ——
    「这条选择器到底能不能跑」只有编译器说了算，正则猜不出来。
    装不上 soupsieve 就**如实不查**（返回空串），不假装查过。
    """
    core = str(css or "").strip()
    if not core:
        return ""
    try:
        import soupsieve
    except Exception:                              # noqa: BLE001 —— 装不上就不查
        return ""
    try:
        soupsieve.compile(core)
    except Exception as e:                         # noqa: BLE001 —— 原文要给人看
        return f"{type(e).__name__}: {e}"
    return ""


def spec_error(plan) -> str:
    """这个计划能不能跑？返回错误原文（空 = 能）。

    `selspec` 负责「这是什么写法」，**能不能编译由编译器说** —— 诚实闸问的就是这一句。
    """
    if not isinstance(plan, Plan):
        return ""
    if plan.error:
        return plan.error
    if plan.sub:
        for sub in plan.sub:
            err = spec_error(sub)
            if err:
                return err
        return ""
    for st in plan.steps:
        if st.kind == "desc":
            err = check_css(st.css)
            if err:
                return err
    return ""
