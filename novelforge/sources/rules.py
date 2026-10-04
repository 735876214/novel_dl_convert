"""数据驱动书源：用一段 JSON 规则描述站点，免写代码即可新增书源。

规则（Rule）字段约定：
{
  "name": "qidian",                       # 唯一标识（必填）
  "display_name": "起点中文网",             # 展示名（可选）
  "domains": ["qidian.com"],               # 域名白名单（必填，用于自动选源）
  "public": false,                         # 是否公版/合规（默认 false）
  "headers": {"User-Agent": "..."},        # 可选覆盖请求头
  "concurrency": 8,                        # 并发抓取章节上限
  "search": {                              # 搜索
    "url": "https://x.com/search?kw={title}",   # {title} 必用；{page} 可选（写了才支持翻页）
    "mode": "css",                         # css | regex
    "container": ".item",                  # css: 每条结果容器选择器
    "fields": {                            # 从容器内提取；值可写 "选择器" 或 "选择器::attr(href)"
      "title": ".name", "author": ".author",
      "url": "a::attr(href)", "cover": "img::attr(src)"
    }
    # regex 模式：
    # "mode": "regex", "pattern": "<a href=\"(?P<url>[^\"]+)\"[^>]*>(?P<title>[^<]+)</a>"
  },
  "book": {                                # 取书
    "mode": "toc",                         # toc（目录式）| single（整页即全文）
    "toc": {                               # mode=toc 时：从书页提取章节链接
      "mode": "css", "container": "#list a", "url_attr": "href"
      # 或 "mode": "regex", "pattern": "<a href=\"(?P<href>[^\"]+)\"[^>]*>(?P<title>[^<]+)</a>"
    },
    "content": {                           # 单章正文提取
      "mode": "css", "container": "#content", "text": true   # text=纯文本；html=保留标签
      # 或 "mode": "regex", "pattern": "<div id=\"content\">([\\s\\S]*?)</div>"
    }
    # single 模式：整页即全文，"content" 同上
  },
  "chapter": {                             # 分章方式（single 模式或全文后切分生效）
    "mode": "toc",                         # toc（结构化，直接用目录）| regex | auto
    "regex": "第\\s*\\d+\\s*章"             # mode=regex 时必填
  }
}

说明：
- `search.url` 里写 `{page}` 即支持翻页（如 `...&page={page}`）：只有写了它，「加载更多」
  才会真的去取下一页；不写就只取第一页，界面上不会出现一个点了没反应的按钮。
- 搜索结果里的 `url` / `cover` 写**相对地址也可以**：会按搜索页地址自动补成绝对地址
  （章节目录一直是这个口径）。补全只对相对地址生效，绝对地址原样保留。
- 书页 book.mode=toc 时，chapter 自动走「toc 结构化分章」（最干净）。
- book.mode=single 时，chapter.mode=regex 用该书源正则切全文；=auto 用全局检测。
- 所有解析支持 css / regex 双通道，离线可用（正则），也可写 CSS 选择器（需 beautifulsoup4）。
"""
import asyncio
import json
import logging
import pathlib
import re
from urllib.parse import quote, urljoin

from .base import SourceAdapter, DEFAULT_HEADERS
from .. import config

logger = logging.getLogger(__name__)


# ---------------- 书源变量 `{var:<key>}`（第 86 期）----------------
# Legado 的 `loginUi` 表单值（番茄的「密钥」、聚合源的「模式 / 音色」）以 `{var:key}` 形式
# 出现在规则里。**缺失绝不静默留空**：留着原文请求会带着 `%7Bvar%3A密钥%7D` 出去，
# 站点回一个空页面，报错离原因十万八千里 —— 所以取值处统一先查变量齐不齐。

_VAR_RE = re.compile(r"\{var:([^}]+)\}")


def load_rule(name: str) -> dict:
    """读一条书源的**规则本体**（用户书源 = ``SOURCES_DIR/<name>.json``；没有 / 坏文件 ⇒ ``{}``）。

    ⚠️ **唯一实现**（第 93 期收敛）：此前只有 `server._load_rule` 一份，而
    `core/landing` 也要问「这条源产出的是文本还是漫画」—— 于是要么反向 import `server`
    （循环依赖），要么抄第二份读法（两份必然漂移）。放在规则模块里两边都够得着。

    规则文件允许写成**数组**（Legado 导出的多源文件）：取第一条字典，与既有读法一字不差。
    """
    if not name:
        return {}
    f = pathlib.Path(config.SOURCES_DIR) / f"{name}.json"
    if not f.is_file():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
    except Exception:                                        # noqa: BLE001 —— 坏文件当没有
        return {}
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else {}
    return data if isinstance(data, dict) else {}


def product_kind(name: str) -> str:
    """这条书源产出的是哪一类产物：``comic`` / ``audio`` / ``text``（第 86 期）。

    判据**在规则里**（``book.mode``）—— 书源自报它给什么，不让用户猜、也不用另开配置键；
    认不出来的（含内置 Python 适配器：它们在磁盘上没有规则文件）一律按 ``text`` 走，
    既有行为一字不变。

    ⚠️ **唯一实现**（第 93 期收敛）：`server._product_kind` 与自动落地都要用它判
    「这本能不能自动落地」，两处各写一份的话，`text` 的界定一旦变化就会一半自动、
    一半不自动。
    """
    mode = str(((load_rule(str(name or "")).get("book") or {})).get("mode") or "").lower()
    return mode if mode in ("comic", "audio") else "text"


def load_vars(rule_name: str) -> dict:
    """读书源变量**值**（给人看的那份没有值，见 `db.source_vars_keys`）。

    只在这里读一次、随实例带走：取正文时一处一章地查库会把「读变量」变成 N 次 I/O。
    """
    if not rule_name:
        return {}
    try:
        from ..core import db
        return db.source_vars_get(str(rule_name))
    except Exception:                                        # noqa: BLE001 —— 读不到当没有
        return {}


def render_vars(text: str, variables) -> tuple:
    """把 `{var:<key>}` 换成值 → ``(文本, 缺失的键列表)``。调用方**必须**处理缺失。"""
    variables = dict(variables or {})
    missing: list = []

    def _sub(m):
        key = m.group(1).strip()
        if variables.get(key):
            return str(variables[key])
        if key not in missing:
            missing.append(key)
        return m.group(0)

    return _VAR_RE.sub(_sub, str(text or "")), missing


def render_rule_vars(rule, variables) -> tuple:
    """深度渲染整条规则里的 `{var:}` → ``(渲染后的副本, 缺失的键列表)``（不改入参）。"""
    if isinstance(rule, str):
        return render_vars(rule, variables)
    if isinstance(rule, dict):
        out, missing = {}, []
        for k, v in rule.items():
            nv, miss = render_rule_vars(v, variables)
            out[k], missing = nv, missing + [m for m in miss if m not in missing]
        return out, missing
    if isinstance(rule, list):
        out, missing = [], []
        for v in rule:
            nv, miss = render_rule_vars(v, variables)
            out.append(nv)
            missing += [m for m in miss if m not in missing]
        return out, missing
    return rule, []


def var_keys(rule) -> list:
    """规则里引用到的全部变量名（**不需要值**）—— 登录面板据此提示「还差哪几个」。"""
    out: list = []

    def _walk(x):
        if isinstance(x, str):
            out.extend(k.strip() for k in _VAR_RE.findall(x) if k.strip() not in out)
        elif isinstance(x, dict):
            for v in x.values():
                _walk(v)
        elif isinstance(x, list):
            for v in x:
                _walk(v)

    _walk(rule)
    return out


# ---------------- JSONPath 第三通道（第 86 期）----------------
# 酷我小说（`$.data.content` / JSON 版 `searchUrl`）与番茄的 `$.data.content` 都要用。
# **只实现真规则用得到的子集**：`$.a.b`、`$.a[0]`、`$.a[*]`、`$..key`；取不到就返回 None，
# 由调用方按「这次没取到」如实处理（而不是抛异常把整本书的抓取打断）。

_JP_TOKEN = re.compile(r"\.\.([^.\[]+)|\.([^.\[]+)|\[(\d+|\*)\]")


def _jp_tokens(expr: str) -> list:
    """`$.a.b[0][*]..c` → ``[("key","a"), ("key","b"), ("idx",0), ("all",None), ("deep","c")]``。"""
    out: list = []
    pos, expr = 0, str(expr or "").strip()
    if expr.startswith("$"):
        pos = 1
    while pos < len(expr):
        m = _JP_TOKEN.match(expr, pos)
        if not m:
            bare = re.match(r"[^.\[]+", expr[pos:])
            if not bare:
                break
            out.append(("key", bare.group(0)))
            pos += bare.end()
            continue
        if m.group(1) is not None:
            out.append(("deep", m.group(1)))
        elif m.group(2) is not None:
            out.append(("key", m.group(2)))
        elif m.group(3) == "*":
            out.append(("all", None))
        else:
            out.append(("idx", int(m.group(3))))
        pos = m.end()
    return out


def _jp_walk(node, toks: list):
    if not toks:
        return node
    kind, arg = toks[0]
    rest = toks[1:]
    if kind == "key":
        return _jp_walk(node.get(arg), rest) if isinstance(node, dict) else None
    if kind == "idx":
        if not isinstance(node, list) or not -len(node) <= arg < len(node):
            return None
        return _jp_walk(node[arg], rest)
    if kind == "all":
        if not isinstance(node, list):
            return None
        vals = [_jp_walk(v, rest) for v in node]
        return [v for v in vals if v is not None]
    # deep：递归找同名键（命中多个就是列表）
    hits: list = []

    def _scan(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k == arg:
                    hits.append(_jp_walk(v, rest) if rest else v)
                _scan(v)
        elif isinstance(x, list):
            for v in x:
                _scan(v)

    _scan(node)
    return hits or None


def json_path(data, path: str):
    """按 JSONPath 子集取值（`path` 为空 / `$` 时返回整个对象）。"""
    p = str(path or "").strip()
    if not p or p == "$":
        return data
    return _jp_walk(data, _jp_tokens(p))


def _json_body(raw: str):
    """把响应体当 JSON 解析（失败返回 None：站点回了 HTML 错误页是常见情况）。"""
    try:
        return json.loads(raw)
    except Exception:                                        # noqa: BLE001
        return None



# ---------------- 解析工具（bs4 延迟导入，未装也不影响模块导入）----------------

def _soup(html: str):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


#: **只有块级标签**才是分段信号（见 :func:`html_to_text`）。
_BLOCK_TAGS = frozenset({
    "address", "article", "aside", "blockquote", "dd", "div", "dl", "dt",
    "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "pre",
    "section", "table", "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
})


def html_to_text(raw: str) -> str:
    """HTML 正文 → **纯文本**（保留段落切分）。**唯一实现**。

    三个调用方共用它 —— 它们要的是同一件事：「源站那段东西，怎么变成读得下去的一段段文字」：
    ① `_extract_css` 按 css 规则取正文（`sources/rules.py`，**下载 / 追更 / 预览 / 在线读**全走它）；
    ② 在线读的 `sources/online.html_to_text`（`regex` / `js` / `html:true` 那几种「抓回来就是
    HTML」的模式，见 `SourceAdapter.content_may_be_html`）。

    分段口径：**块级标签与 `<br>` 断行，行内标签不断行**。

    ⚠️ 别退回 `node.get_text("\\n")` / `soup.get_text("\\n")`（每个标签边界都插换行）——
    `<b>` / `<em>` / `<a>` / `<span>` 只是包一层样式，当成分段信号会把**一句话剁成好几句**
    （第 93 期真机验证逮到：正文渲染成「第二段：/加粗/与/斜体/标记都…」各自成段）。
    真实站点用 `<span>` 逐字防采集、在正文里放 `<a>` 跳转链接的遍地都是。
    """
    text = str(raw or "")
    if "<" not in text:                     # 已经是纯文本 ⇒ 不必过解析器
        return text
    try:
        soup = _soup(text)
        for bad in soup(["script", "style"]):
            bad.decompose()
        for br in soup.find_all("br"):
            br.replace_with("\n")
        # 换行是**追加**在块级标签末尾，不是 `get_text` 的分隔符 —— 用分隔符就没法
        # 区分行内 / 块级。`strip=True` 会把追加进来的 "\n" 当空白吃掉，所以这里
        # 不 strip，改由下面按行去空白 + 丢空行（与 `core.reading_list.text_to_xhtml` 同口径）。
        for tag in soup.find_all(lambda t: t.name in _BLOCK_TAGS):
            tag.append("\n")
        lines = (ln.strip() for ln in soup.get_text("").splitlines())
        return "\n".join(ln for ln in lines if ln)
    except Exception:                       # noqa: BLE001 —— 解析器炸了也不能放过标记
        logger.warning("HTML 正文压纯文本失败，改用去标记兜底")
        # 兜底同样**只认块级标签**断行：宁可少断一段，也不把行内标签当成换行。
        block = "|".join(sorted(_BLOCK_TAGS))
        text = re.sub(rf"(?i)<(?:br|/?(?:{block}))\b[^>]*>", "\n", text)
        text = re.sub(r"<[^>]*>", "", text)
        lines = (ln.strip() for ln in text.splitlines())
        return "\n".join(ln for ln in lines if ln)


def _field_value(container, spec: str) -> str:
    """从容器内按 spec 取值：''/'./' 取自身文本，'选择器' 取文本，'选择器::attr(name)' 取属性。"""
    spec = spec or ""
    if "::attr(" in spec:
        sel, attr = spec.split("::attr(", 1)
        attr = attr.rstrip(")")
        node = container.select_one(sel) if sel.strip() else container
        return node.get(attr, "") if node else ""
    if spec.strip() in ("", "."):
        return container.get_text(" ", strip=True)
    node = container.select_one(spec)
    return node.get_text(" ", strip=True) if node else ""


def _extract_css(html: str, rule: dict):
    """按 css 规则从 html 抽取文本（默认）或保留标签的 HTML（``html: true``）。"""
    node = _soup(html).select_one(rule.get("container", ""))
    if not node:
        return ""
    if rule.get("html"):
        return str(node)
    return html_to_text(str(node))


def _extract_regex(html: str, rule: dict):
    """按 regex 规则抽取：优先取第一个命名/位置捕获组，无组则取整段匹配。"""
    pat = re.compile(rule.get("pattern", ""), re.S | re.I)
    m = pat.search(html)
    if not m:
        return ""
    if m.groups():
        return m.group(1) if len(m.groups()) == 1 else "\n".join(
            g for g in m.groups() if g
        )
    return m.group(0)


def _json_scalar(v) -> str:
    """JSON 取值结果压成字符串；**数组 / 对象一律当空**（见 `_extract_json` 的说明）。"""
    if v is None or isinstance(v, (dict, list)):
        return ""
    return str(v)


def _extract_json(raw: str, rule: dict) -> str:
    """json 模式取**标量**正文（第三通道，第 86 期）。

    ⚠️ 数组 / 对象返回空串：正文位置塞一个 JSON 数组进书里就是一段
    `[{"text": …}]` 的乱码。要数组请把路径写到标量为止（如 `$.data.content`）。
    """
    return _json_scalar(json_path(_json_body(raw), rule.get("path")))


def _extract(html: str, rule: dict) -> str:
    rule = rule or {}
    if rule.get("mode") == "regex":
        return _extract_regex(html, rule)
    if rule.get("mode") == "json":
        return _extract_json(html, rule)
    return _extract_css(html, rule)


def _absolutize(item: dict, base_url: str) -> dict:
    """把命中里的相对地址补成绝对地址（第 71 期）。

    真实站点的搜索结果几乎都用相对链接（`/book/123`、`?id=9`），而**取书与预览都直接拿
    `item["url"]` 去请求** —— 不补的话会以「Request URL is missing an 'http://' or
    'https://' protocol.」失败，那句报错离真正的原因（规则抓到的是相对地址）很远。

    与 `_extract_links`（章节目录一直就在做 urljoin）保持同一口径：
    本来就是绝对地址时 `urljoin` 是幂等的，对既有规则零影响。
    """
    for key in ("url", "cover"):
        if item.get(key):
            item[key] = urljoin(base_url, str(item[key]))
    return item


def _parse_search_json(raw: str, sp: dict, base_url: str = "") -> list:
    """JSON 版搜索（第三通道）：`path` 取结果数组，`fields` 的每个值都是**子路径**。"""
    arr = json_path(_json_body(raw), sp.get("path") or "$")
    if isinstance(arr, dict):
        arr = [arr]
    if not isinstance(arr, list):
        return []
    fields = sp.get("fields") or {}
    out = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        item = {k: _json_scalar(json_path(it, spec)) for k, spec in fields.items()}
        if item.get("url"):
            out.append(_absolutize(item, base_url))
    return out


def _parse_search(html: str, sp: dict, base_url: str = "") -> list[dict]:
    # 第三通道（第 86 期）：站点给的是 JSON（酷我是 `$.data.list` 这种）
    if sp.get("mode") == "json":
        return _parse_search_json(html, sp, base_url)
    if sp.get("mode") == "regex":
        pat = re.compile(sp.get("pattern", ""), re.S | re.I)
        out = []
        for m in pat.finditer(html):
            d = m.groupdict()
            if d:
                item = {k: (d.get(k) or "") for k in ("title", "author", "url", "cover") if k in d}
            else:
                g = m.groups()
                item = {"title": g[0] if g else "", "url": g[1] if len(g) > 1 else ""}
            if item.get("url"):
                out.append(_absolutize(item, base_url))
        return out
    # css
    soup = _soup(html)
    nodes = soup.select(sp.get("container", ""))
    fields = sp.get("fields", {})
    out = []
    for n in nodes:
        item = {k: _field_value(n, spec) for k, spec in fields.items()}
        if item.get("url"):
            out.append(_absolutize(item, base_url))
    return out


def _extract_links_json(raw: str, toc: dict, base_url: str) -> list:
    """JSON 版目录（第三通道）：`path` 取章节数组，`fields` 用子路径取标题 / 地址。"""
    arr = json_path(_json_body(raw), toc.get("path") or "$")
    if isinstance(arr, dict):
        arr = [arr]
    if not isinstance(arr, list):
        return []
    fields = toc.get("fields") or {}
    out = []
    for it in arr:
        if not isinstance(it, dict):
            continue
        href = _json_scalar(json_path(it, fields.get("url") or "$.url"))
        title = _json_scalar(json_path(it, fields.get("title") or "$.title")) or href
        if href:
            out.append((title, urljoin(base_url, href)))
    return out


def _extract_links(html: str, toc: dict, base_url: str) -> list[tuple[str, str]]:
    """返回 [(标题, 绝对URL)] 章节链接列表。"""
    if toc.get("mode") == "json":
        return _extract_links_json(html, toc, base_url)
    if toc.get("mode") == "regex":
        pat = re.compile(toc.get("pattern", ""), re.S | re.I)
        out = []
        for m in pat.finditer(html):
            d = m.groupdict()
            href = d.get("href") or (m.groups()[0] if m.groups() else "")
            title = d.get("title") or href
            if href:
                out.append((title or href, urljoin(base_url, href)))
        return out
    soup = _soup(html)
    nodes = soup.select(toc.get("container", ""))
    attr = toc.get("url_attr", "href")
    out = []
    for n in nodes:
        href = n.get(attr, "")
        if href:
            out.append((n.get_text(" ", strip=True) or href, urljoin(base_url, href)))
    return out


def _extract_pages(raw: str, rule: dict, base_url: str) -> list:
    """**资源地址清单**（漫画页 / 音频轨，第 86 期）：css / regex / json 三通道通用。

    与 `_extract_links` 的差别：这里只要地址（图和音没有标题），且**保留站点给的顺序** ——
    页序就是阅读顺序，不许重排、不许去重（真有重复页也是站点的事实）。
    """
    rule = rule or {}
    mode = rule.get("mode") or "css"
    if mode == "json":
        arr = json_path(_json_body(raw), rule.get("path") or "$")
        if isinstance(arr, dict):
            arr = [arr]
        out = []
        for it in (arr if isinstance(arr, list) else []):
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict):
                u = _json_scalar(json_path(it, rule.get("url") or "$.url"))
                if u:
                    out.append(u)
        return [urljoin(base_url, u) for u in out]
    if mode == "regex":
        pat = re.compile(rule.get("pattern") or "", re.S | re.I)
        out = []
        for m in pat.finditer(raw):
            g = m.groupdict().get("url") or (m.groups()[0] if m.groups() else "")
            if g:
                out.append(urljoin(base_url, g))
        return out
    soup = _soup(raw)
    attr = rule.get("url_attr") or "src"
    out = []
    for n in soup.select(rule.get("container") or ""):
        # ⚠️ 三个兜底都不是可选的：
        #   · 漫画站普遍**懒加载** —— `src` 是占位图，真地址在 `data-src` / `data-original`；
        #   · 音频 / 漫画规则常把 container 指到 `<a>` 上 —— 地址在 `href` 而不是 `src`。
        v = (n.get(attr) or n.get("data-src") or n.get("data-original") or n.get("href") or "")
        if v:
            out.append(urljoin(base_url, str(v)))
    return out


# ---------------- 书源类 ----------------

class RuleBasedSource(SourceAdapter):
    """由 JSON 规则驱动的书源；规则存于类属性 _RULE（由 make_rule_class 注入）。"""

    _RULE: dict = {}

    def __init__(self):
        rule = self._RULE
        # 第 86 期：`{var:<key>}` 在这里**一次渲染完**（含 headers / url / 选择器 / path），
        # 免得每个取值点各写一遍；缺哪个变量记下来，真正出网前如实报错。
        self.variables = load_vars(rule.get("name"))
        rule, self.missing_vars = render_rule_vars(rule, self.variables)
        self._RULE = rule
        hdrs = rule.get("headers")
        if hdrs:
            self.headers = {**DEFAULT_HEADERS, **hdrs}
        self._concurrency = int(rule.get("concurrency", 8) or 8)

    def decryption_js(self):
        """规则里的 ``decrypt_js``（Legado 的 ``@js:`` 片段移植过来后放这里）。

        约定与 :meth:`SourceAdapter.decryption_js` 一致：``__args[0]`` 是密文，
        片段用 ``return`` 交出明文（包装层由 `network.wrap_decrypt` 负责）。
        """
        return (self._RULE.get("decrypt_js") or "").strip() or None

    async def _content(self, html: str, spec: dict) -> str:
        """从页面取**正文**：``mode=js`` 交给 Node 通道，其余走 css / regex / json。

        ⚠️ `mode: "js"` 不是可选装饰：`legado.convert` 对「正文由 JS 算出」的源**就是**产出
        `{"mode": "js", "script": …}`（第 1 步定的形状）。`_extract` 不认这个 mode，
        它会落进 css 分支、拿到空 container 而**返回空串** —— 表现是「导入成功、下载成功、
        但书里一个字都没有」，几乎无法从现象反推原因。
        """
        if (spec or {}).get("mode") == "js":
            from ..core import network
            # 移植脚本读全局 `result`（`wrap_decrypt` 同时提供 `result` 与 `__args[0]`）
            return await network.run_decrypt(spec.get("script") or "", html)
        return await self._decrypt(_extract(html, spec))

    async def _decrypt(self, text: str) -> str:
        """按需跑站点解密片段：**没配就原样返回**（绝大多数站点不需要）。"""
        js = self.decryption_js()
        if not js or not text:
            return text
        from ..core import network
        return await network.run_decrypt(js, text)

    def _check_vars(self):
        """出网前检查变量：缺就**当场报**，绝不带着 `{var:…}` 去请求站点。

        带着原文请求的下场是站点回一个空页 / 404，报错离真正的原因很远 ——
        与「未登录就抓」是同一类静默失败。
        """
        if self.missing_vars:
            raise ValueError("缺少书源变量：" + "、".join(self.missing_vars)
                             + "（到书源管理页的「登录」里填写）")

    # ---- 搜索 ----
    async def search(self, client, title: str) -> list[dict]:
        return (await self.search_page(client, title, 1))["items"]

    async def search_page(self, client, title: str, page: int = 1) -> dict:
        """规则源分页（第 71 期）：**只在 ``search.url`` 模板含 ``{page}`` 时才替换**。

        两条纪律：
        1. **不含 ``{page}`` 的规则**，第 1 页按原模板取、``has_more=False`` ——
           不知道是否还有下一页就如实说没有：猜成「还有」会让界面挂一个点了没反应的
           「加载更多」，猜成「没有」只是少一个按钮，后者诚实得多；
        2. ``page=1`` 且含 ``{page}`` 时替换成 ``1``，与不分页的写法取到的是同一页。

        ``has_more`` 只有「模板支持分页**且**本页确实取到了结果」才为真：真到底了的那次
        会返回 0 条，于是下一页自然收敛成 False（不靠猜、靠事实自纠）。
        """
        self._check_vars()
        sp = self._RULE.get("search") or {}
        tpl = sp.get("url", "")
        if not tpl:
            return {"items": [], "has_more": False}
        page = max(1, int(page or 1))
        paged = "{page}" in tpl
        if page > 1 and not paged:
            return {"items": [], "has_more": False}
        url = tpl.replace("{title}", quote(title))
        if paged:
            url = url.replace("{page}", str(page))
        html = await client.get_text(url)
        # 把**请求用的** url 作为基准传给解析：命中里的相对链接要按它补全（见 `_absolutize`）
        items = _parse_search(html, sp, url)
        return {"items": items, "has_more": bool(paged and items)}

    # ---- 取书：整页全文 ----
    async def fetch_book(self, client, item: dict) -> str:
        self._check_vars()
        bp = self._RULE.get("book") or {}
        if bp.get("mode") == "toc":
            chapters = await self._fetch_toc(client, item["url"])
            return "\n\n".join(f"{c['title']}\n{c['body']}" for c in chapters)
        html = await client.get_text(item["url"])
        return await self._content(html, bp.get("content", {}))

    # ---- 取书：结构化章节（供目录式分章）----
    async def fetch_book_chapters(self, client, item: dict) -> list[dict]:
        self._check_vars()
        bp = self._RULE.get("book") or {}
        if bp.get("mode") == "toc":
            return await self._fetch_toc(client, item["url"])
        # single：取全文后按 chapter 规则切分
        html = await client.get_text(item["url"])
        text = await self._content(html, bp.get("content", {}))
        ch = self._RULE.get("chapter") or {}
        if ch.get("mode") == "regex":
            return _split_regex(text, ch["regex"])
        from ..core import detect
        return detect.detect_chapters(text)

    async def chapter_links(self, client, book_url: str) -> list[dict]:
        """书页 → 章节清单 ``[{"title", "url"}, ...]``（**唯一实现**，第 93 期）。

        「取整本」（:meth:`_fetch_toc`）、预览、**在线阅读**三条路共用它。三条路各写一遍
        `_extract_links` + 相对地址补全的话，改一处漏一处的表现是「某一条路上的章节点不开」，
        而且从现象完全看不出是解析口径不一致。
        """
        self._check_vars()
        bp = self._RULE.get("book") or {}
        html = await client.get_text(book_url)
        return [{"title": t, "url": u}
                for t, u in _extract_links(html, bp.get("toc", {}) or {}, book_url)]

    async def chapter_body(self, client, url: str) -> str:
        """单章正文（**唯一实现**）：`book.content` 提取 + 站点解密。

        ⚠️ 返回值**可能是 HTML**（取决于 `book.content` 的写法）—— 调用方按
        :meth:`content_may_be_html` 判断要不要剥标记，别自己猜。
        """
        self._check_vars()
        bp = self._RULE.get("book") or {}
        html = await client.get_text(url)
        return await self._content(html, bp.get("content", {}) or {})

    async def _fetch_toc(self, client, book_url: str) -> list[dict]:
        links = await self.chapter_links(client, book_url)
        sem = asyncio.Semaphore(self._concurrency)

        bodies = {}

        async def _one(i: int, url: str):
            async with sem:
                try:
                    bodies[i] = await self.chapter_body(client, url)
                except Exception as e:  # 单章失败不中断整本
                    bodies[i] = f"（第 {i + 1} 章抓取失败：{e}）"

        await asyncio.gather(*(_one(i, c["url"]) for i, c in enumerate(links)))
        return [{"title": c["title"], "body": bodies.get(i, "")}
                for i, c in enumerate(links)]

    async def fetch_media_urls(self, client, item: dict, key: str) -> list:
        """取一类**资源地址清单**（`book.comic` / `book.audio`）：只列地址，不下载。

        ⚠️ 只支持**一层**：书页 → 清单（图 / 轨）。有些站点要「书页 → 章节页 → 清单」两级，
        那种规则现在跑不了 —— 会拿到空清单，由调用方**如实报「这条规则没给出地址」**，
        而不是编一个看起来像成功的空产物。
        """
        self._check_vars()
        spec = (self._RULE.get("book") or {}).get(key) or {}
        if not spec or not item.get("url"):
            return []
        html = await client.get_text(item["url"])
        return _extract_pages(html, spec, item["url"])

    # ---- 在线阅读（第 93 期）----
    def online_support(self) -> str:
        """规则源能不能逐章在线读：要 `book.content`（正文）与 `book.toc`（章节清单）。

        ⚠️ 缺哪一样就说缺哪一样 —— 「这本书读不了」和「这条规则没写正文提取」
        对用户是两件事（后者要去书源管理里补规则）。
        """
        bp = self._RULE.get("book") or {}
        if not bp.get("content"):
            return "这条书源的规则里没有正文提取（book.content），不能逐章在线阅读"
        if self.online_mode() == "toc" and not (bp.get("toc") or {}):
            return "这条书源的规则里没有章节目录（book.toc），不能逐章在线阅读"
        return ""

    def online_mode(self) -> str:
        """``"toc"`` = 一章一页按需取；``"single"`` = 只有整本一页，取回后现切。

        `single` 模式本期**支持**（用户口径要的是「接我给的书源」，不少源就是整页全文）：
        取回整本后按既有 `detect.detect_chapters` / `chapter` 正则分章，逐章进缓存。
        代价说清楚：这种源**没法只取一章**，缓存被清掉后要重取整本。
        """
        return "toc" if ((self._RULE.get("book") or {}).get("mode") or "") == "toc" else "single"

    def content_may_be_html(self) -> bool:
        """`book.content` 取出来的是不是 HTML —— 决定在线读要不要先剥标记。

        · `css`（默认）走 `get_text()` ⇒ 纯文本；写了 ``"html": true`` ⇒ 原样 HTML；
        · `regex` 取的是**捕获组原文**（真实站点普遍就是一段 HTML 片段）；
        · `js` 交给脚本，返回什么都有可能；
        · `json` 只取标量（见 `_extract_json`）⇒ 纯文本。
        """
        spec = (self._RULE.get("book") or {}).get("content") or {}
        if spec.get("mode") in ("regex", "js"):
            return True
        return bool(spec.get("html"))

    # ---- 预览（廉价：目录 + 首章样本）----
    async def preview(self, client, item: dict) -> dict:
        self._check_vars()
        bp = self._RULE.get("book") or {}
        if bp.get("mode") == "toc":
            links = await self.chapter_links(client, item["url"])
            sample = ""
            if links:
                try:
                    # 预览也要解密：否则用户看到的是乱码，会以为「这条源坏了」
                    sample = (await self.chapter_body(client, links[0]["url"]))[:1500]
                except Exception:
                    sample = ""
            return {"toc": [c["title"] for c in links], "sample": sample}
        html = await client.get_text(item["url"])
        text = _extract(html, bp.get("content", {}))
        from ..core import detect
        chaps = detect.detect_chapters(text)
        return {
            "toc": [c["title"] for c in chaps[:50]],
            "sample": text[:1500],
        }


def _split_regex(text: str, pattern: str) -> list[dict]:
    """用单个正则把全文切成章节：每个匹配作为新章标题起点，正文至下一匹配。"""
    from ..core.detect import split_by_offsets, regex_bounds

    # 复用 detect 的偏移切分：把单条正则包装成多匹配形式
    pat = re.compile(pattern, re.M)
    bounds = sorted({(m.start(), m.group(0).strip()) for m in pat.finditer(text)})
    if not bounds:
        return [{"title": "正文", "body": text.strip()}]
    return split_by_offsets(text, bounds, merge=False)


def make_rule_class(rule: dict):
    """根据规则字典动态生成一个 SourceAdapter 子类并写入类属性。"""
    if not rule.get("name"):
        raise ValueError("规则缺少必填字段 name")
    if not rule.get("domains"):
        raise ValueError("规则缺少必填字段 domains")
    name = str(rule["name"])
    cls = type(f"RuleSource_{name}", (RuleBasedSource,), {})
    cls.name = name
    cls._RULE = rule
    cls.display_name = rule.get("display_name", name)
    cls.domains = list(rule.get("domains", []))
    cls.public = bool(rule.get("public", False))
    cls._concurrency = int(rule.get("concurrency", 8) or 8)
    return cls


def validate_rule(rule: dict) -> list[str]:
    """校验规则必填项，返回错误信息列表（空表示通过）。"""
    errs = []
    if not isinstance(rule, dict):
        return ["规则必须是一个 JSON 对象"]
    if not rule.get("name"):
        errs.append("缺少 name（唯一标识）")
    if not rule.get("domains"):
        errs.append("缺少 domains（域名白名单数组）")
    sp = rule.get("search") or {}
    if not sp.get("url"):
        errs.append("search.url 必填")
    if sp.get("mode") == "css" and not sp.get("container"):
        errs.append("search 为 css 模式时 container 必填")
    if sp.get("mode") == "regex" and not sp.get("pattern"):
        errs.append("search 为 regex 模式时 pattern 必填")
    if sp.get("mode") == "json" and not sp.get("path"):
        errs.append("search 为 json 模式时 path 必填（如 $.data.list）")
    bp = rule.get("book") or {}
    if bp.get("mode") == "toc":
        toc = bp.get("toc") or {}
        if toc.get("mode") == "css" and not toc.get("container"):
            errs.append("book.toc 为 css 模式时 container 必填")
        if toc.get("mode") == "regex" and not toc.get("pattern"):
            errs.append("book.toc 为 regex 模式时 pattern 必填")
        if toc.get("mode") == "json" and not toc.get("path"):
            errs.append("book.toc 为 json 模式时 path 必填（如 $.data.chapters）")
        if not bp.get("content"):
            errs.append("book.content（章节正文提取）必填")
    ch = rule.get("chapter") or {}
    if ch.get("mode") == "regex" and not ch.get("regex"):
        errs.append("chapter 为 regex 模式时 regex 必填")
    return errs


# ---------------- 转换诚实闸（第 94 期）----------------
# 「引擎能执行什么」的**唯一**真值源。任何格式的适配器产物都要过这里（见 sources/formats/），
# 不许由转换器自称可用。第 94 期实测的病：XIU2 那份 22 条真实 Legado 样本里，
# `legado.analyze` 判「可用」的 9 条中有 **6 条**产物引擎根本跑不了 ——
# `search.url` 里整段 `,{'method':'post',…}` 会被当成地址发出去、
# `#author tbody tr!0` / `.odd.0` 会让 `soup.select_one` **抛 SelectorSyntaxError**
# （搜索与目录的调用点没有 try 保护）、`.author text##作者：` 的替换段原样进正文、
# `class.section-list.-1@tag.a` 当 CSS 用。这不是「结果不准」，是「一搜就炸」。

#: 引擎**真实**支持的解析通道（= `_extract` / `_parse_search` / `_extract_links` /
#: `_extract_pages` 认的 `mode` 值域）。**唯一**声明处：审计从它读，别人不许再记一份。
MODES = ("css", "regex", "json")

#: 各通道字段允许的 mode —— 正文多一条 `js`（走 `RuleBasedSource._content`）。
_MODE_SLOTS = {"search": MODES, "book.toc": MODES, "book.content": MODES + ("js",),
               "book.comic": MODES, "book.audio": MODES}
#: `book.mode` / `chapter.mode` 的值域（**未知值的下场是静默降级**，所以也要审）
_BOOK_MODES = ("toc", "single")
_CHAPTER_MODES = ("toc", "regex", "auto")

#: 引擎**今天跑不了**的构造。每条：``{id, kinds, re, what, why, instead}``。
#: ⚠️ **阶段 2 每补一项能力就摘掉一条并补一个用例** ⇒ 这张表单调变短，不会先松后紧。
_UNSUPPORTED_CONSTRUCTS = (
    {
        "id": "url_option_dict", "kinds": ("url",),
        "re": re.compile(r",\s*\{"),
        "what": "URL 选项字典（`<地址>,{'method':'post','body':…}`）",
        "why": "本项目按 GET 取该地址，整段字典会当成地址的一部分发出去",
        "instead": "改用 GET 型书源，或到「书源管理」手写搜索地址与请求方式",
    },
    {
        "id": "legacy_placeholder", "kinds": ("url",),
        # 阅读 2.x 的搜索占位符是裸词（实测 `?keyword=searchKey&page=searchPage`）。
        # `legado.normalize_legacy` 会把它们归一成 `{{key}}`/`{{page}}` ⇒ 正常导入的 2.x 源
        # 走不到这一条；留着它是**兜底**：手写规则 / 本项目导出文件里若还带着裸词，
        # 引擎会原样发出去（搜什么都搜同一个词），必须当场说清。
        "re": re.compile(r"\bsearchKey\b|\bsearchPage\b"),
        "what": "阅读 2.x 的裸词搜索占位符（`searchKey` / `searchPage`）",
        "why": "本项目只认 `{title}` / `{page}`，裸词会原样拼进请求地址 ⇒ 搜什么都搜同一个词",
        "instead": "把 `searchKey` 改成 `{title}`、`searchPage` 改成 `{page}`",
    },
    {
        "id": "url_option_pipe", "kinds": ("url",),
        # 2.x 的**竖线选项**（实测 775 条：`…&q=searchKey|char=gbk`）。与 `,{...}` 是同一类
        # 东西（请求选项），但要说的话不同：这个错在**编码**，不是说错了请求方式。
        "re": re.compile(r"\|[a-zA-Z_-]+\s*="),
        "what": "URL 的竖线选项（`<地址>|char=gbk` / `|method=post`）",
        "why": "本项目会把整段选项当成地址的一部分发出去（多出一个 `|char=gbk` 的查询参数），"
               "而且不会按它指定的编码解码",
        "instead": "去掉 `|…` 那一段；若站点是 GBK，请在「书源管理」里把编码设成对应值",
    },
    {
        "id": "legado_index", "kinds": ("selector",),
        # ⚠️ 索引可以是负数、也可以写成区间（实测 `ul!0:1:-1:-2:-3 li!-3 a`、`.mySearch ul!-1`），
        #    只认 `!\d+` 会让这些条目掉到下一条「选择器不是合法 CSS」去 —— 结论一样（判 no），
        #    但给出的建议从「改写成 :nth-of-type(n+1)」退化成「这不是合法 CSS」，用户没法照做。
        "re": re.compile(r"!-?\d+(?::[-?\d]*)?|[\w\)\]]\.-?\d+(?=\s*$|[\s>,.\[:])"),
        "what": "「阅读」的索引语法（`tr!0` / `.odd.0` / `a.0` / `ul!-1` / `ul!0:1:-1`）",
        "why": "本项目只取第一个匹配，索引段会被原样丢给 CSS 解析器并直接报语法错",
        "instead": "改写成 CSS 的 `:nth-of-type(n+1)`",
    },
    {
        "id": "hash_hash_replace", "kinds": ("selector", "regex", "jsonpath"),
        "re": re.compile(r"##"),
        "what": "「阅读」的替换语法（`选择器##正则##替换`）",
        "why": "本项目取到的是原文，`##` 那一段会原样进结果",
        "instead": "把 `##正则##替换` 去掉，或改成不含替换的选择器",
    },
    {
        "id": "legado_sel_syntax", "kinds": ("selector",),
        "re": re.compile(r"@\s*(?:css|tag|text|textNodes|html|all|href|src|data-|js|attr)"
                         r"|(?:^|[\s>~,])(?:class|id|tag)\.", re.I),
        "what": "「阅读」的选择器语法（`class.` / `id.` / `tag.` / `@text` / `@css:` / `@attr(href)`）",
        "why": "本项目的选择器是标准 CSS（取值写 `::attr(href)`），这套前缀会被当成标签名 / 类名",
        "instead": "到「书源管理」改写成标准 CSS（如 `.foo > a::attr(href)`）",
    },
    {
        "id": "jsonpath_in_css", "kinds": ("selector",),
        # 取值项写成了 JSON 路径（`JSon:$.title` / `$.title`），而这条搜索通道是 **CSS**。
        # 实测 2.x 里成片出现：转换器按 `ruleSearchList` 定通道，字段却是 JSON 路径 ⇒
        # 那一段会被当成选择器丢给 CSS 解析器。报成「不是合法 CSS」用户看不懂，
        # 得直接告诉他「这一项的写法跟通道对不上」。
        "re": re.compile(r"^\s*(?:JSon|@json)\s*:|^\s*\$"),
        "what": "在 CSS 通道里写 JSON 路径（`JSon:$.title` / `$.title`）",
        "why": "这条搜索通道是按 CSS 选择器跑的，JSON 路径会被当成选择器解析（永远取不到值）",
        "instead": "把这一项改写成 CSS 选择器；若整份搜索本来就是 JSON 接口，"
                   "到「书源管理」把「搜索通道」改成 json",
    },
    {
        "id": "and_or", "kinds": ("selector",),
        # ⚠️ 单竖线也要认：阅读 2.x 的候选分隔符是**一个** `|`（实测
        #    `#result-list tag.li|class.rank-view-list tag.li|class.all-bo`），3.x 才用 `||`。
        #    只认 `||` 时这些条目会掉到「选择器不是合法 CSS」，等于没告诉用户该怎么改。
        "re": re.compile(r"\|\|?|&&"),
        "what": "多路候选（`|` / `||` 取首个非空 / `&&` 拼接）",
        "why": "本项目只有一条取值路，候选语法会被当成 CSS 解析错误",
        "instead": "在「书源管理」里选定其中一条",
    },
    {
        "id": "xpath", "kinds": ("selector",),
        "re": re.compile(r"^\(*\s*/"),
        "what": "XPath（`//div[@id=\"x\"]/p`）",
        "why": "本项目的选择器通道是 CSS，XPath 会被当成选择器语法错误",
        "instead": "改写成等价的 CSS 选择器",
    },
    {
        "id": "tpl_leftover", "kinds": ("url", "selector", "regex", "jsonpath"),
        "re": re.compile(r"\{\{"),
        "what": "没被转换的模板变量（`{{key}}` / `{{$.x}}`）",
        "why": "本项目只认 `{title}` / `{page}` / `{var:键}`，`{{…}}` 会原样拼进请求地址或选择器",
        "instead": "改写成 `{title}` / `{page}`，或在「书源管理」里填成写死的值",
    },
    {
        "id": "jsonpath_ext", "kinds": ("jsonpath",),
        "re": re.compile(r"\[\s*['\"]|\[\s*[^\]]*[,:]|\[\s*\?"),
        "what": "JSONPath 子集之外的语法（`['k']` / `[1:2]` / `[0,1]` / `[?(…)]`）",
        "why": "本项目只实现 `$.a.b` / `$.a[0]` / `$.a[*]` / `$..k`，其他写法会**取到错的值**",
        "instead": "改写成本项目支持的子集",
    },
)


def _snippet(value: str, limit: int = 120) -> str:
    """把出问题的原文截一段给用户看 —— 只说「有问题」不说「哪一段」等于让人自己找。"""
    s = " ".join(str(value or "").split())
    return s if len(s) <= limit else s[:limit] + "…"


def _dig(node, path: str):
    """按 ``"book.toc"`` 取嵌套字典（中间不是字典就当没有）。"""
    cur = node
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _spec_fields(prefix: str, spec) -> list:
    """一个通道字段（search / book.toc / book.content / comic / audio）里的**可执行值**。"""
    if not isinstance(spec, dict) or not spec:
        return []
    mode = str(spec.get("mode") or "css").strip().lower()
    # `fields` 不是字典（坏文件 / 手写错的规则）时当没有字段 —— 审计绝不许抛异常
    fields = spec.get("fields") if isinstance(spec.get("fields"), dict) else {}
    if mode == "regex":
        return [(f"{prefix}.pattern", "regex", spec.get("pattern"))]
    if mode == "json":
        # ⚠️ json 通道的路径键两代都写过：native 用 `path`，`legado.convert` 写的是 `container`
        #    （`_parse_search_json` / `_extract_links_json` 认的是 `path`）⇒ 两个都审。
        out = [(f"{prefix}.path", "jsonpath", spec.get("path") or spec.get("container"))]
        for k, v in fields.items():
            out.append((f"{prefix}.fields.{k}", "jsonpath", v))
        return out
    if mode == "js":
        return [(f"{prefix}.script", "js", spec.get("script"))]
    out = [(f"{prefix}.container", "selector", spec.get("container"))]
    for k, v in fields.items():
        out.append((f"{prefix}.fields.{k}", "selector", v))
    return out


def _exec_fields(rule: dict) -> list:
    """规则里**会被真的执行**的那些值 → ``[(字段路径, 种类, 值)]``。

    只列执行通道认的字段：簿记（`name` / `domains` / `legado`）与开关（`html` / `text` /
    `url_attr`）不是选择器，混进来只会产生假警报。
    """
    def _d(key) -> dict:
        """取值当字典用，不是字典就当成空的 —— 审计**绝不许**因为坏字段抛异常。"""
        v = rule.get(key)
        return v if isinstance(v, dict) else {}

    search = _d("search")
    out = [("search.url", "url", search.get("url"))]
    out += _spec_fields("search", search)
    bp = _d("book")
    if str(bp.get("mode") or "").strip().lower() == "toc":
        out += _spec_fields("book.toc", bp.get("toc") or {})
    out += _spec_fields("book.content", bp.get("content") or {})
    for key in ("comic", "audio"):
        out += _spec_fields(f"book.{key}", bp.get(key) or {})
    ch = _d("chapter")
    if str(ch.get("mode") or "").strip().lower() == "regex":
        out.append(("chapter.regex", "regex", ch.get("regex")))
    if rule.get("decrypt_js"):
        out.append(("decrypt_js", "js", rule.get("decrypt_js")))
    return [(f, k, v) for f, k, v in out if v is not None and str(v).strip()]


def _css_error(sel: str) -> str:
    """这个选择器能被 CSS 引擎编译吗？返回错误原文（空串 = 没问题 / 查不了）。

    ⚠️ 用 `soupsieve`（bs4 的依赖，`requirements.txt` 已声明）**真的编译一次** ——
    「这条选择器到底能不能跑」只有编译器说了算，正则猜不出来。
    ``::attr(x)`` 是本项目自己的取值后缀（不是 CSS），编译前先摘掉。
    装不上 soupsieve 就**如实不查**（返回空串），不假装查过。
    """
    core = str(sel or "").split("::attr(", 1)[0].strip()
    if core in ("", ".", "./"):
        return ""
    try:
        import soupsieve
    except Exception:                                        # noqa: BLE001 —— 装不上就不查
        return ""
    try:
        soupsieve.compile(core)
    except Exception as e:                                   # noqa: BLE001 —— 原文要给人看
        return f"{type(e).__name__}: {e}"
    return ""


def _regex_error(pattern: str) -> str:
    """正则能编译吗？（`_extract_regex` 在抓取期裸 `re.compile`，编不过 = 整次取书 500）"""
    try:
        re.compile(str(pattern or ""), re.S | re.I)
    except Exception as e:                                   # noqa: BLE001
        return f"{type(e).__name__}: {e}"
    return ""


def _audit_js(field: str, script: str) -> list:
    """JS 字段：用了 Android 专有桥就**做不到**（不是「还没做」）——判据与 `js_port` 同一份。"""
    from .legado import ANDROID_API_RE                       # 唯一一份定义在 legado
    missing = sorted({m.group(0) for m in ANDROID_API_RE.finditer(script)})
    if not missing:
        return []
    return [{"field": field, "construct": "android_bridge",
             "why": "该字段是 JS，且用了本项目无法执行的 Legado 专有 API：" + "、".join(missing),
             "instead": "这类源要在手机上用「阅读」App；本项目只能请你在「书源管理」里"
                        "手写等价规则（CSS / 正则 / JSON 路径）"}]


def _audit_value(field: str, kind: str, value) -> list:
    """一个值 → 它跑不动的理由（空列表 = 这一项引擎跑得动）。"""
    s = str(value)
    if kind == "js":
        return _audit_js(field, s)
    hits = [c for c in _UNSUPPORTED_CONSTRUCTS if kind in c["kinds"] and c["re"].search(s)]
    if hits:
        # ⚠️ 命中具体构造就**不再**报「语法错误」：编译器只会说「这个选择器不合法」，
        #    而上面那条会告诉他「`!0` 是阅读的索引语法、该改成什么」——后者才可照做。
        return [{"field": field, "construct": c["id"],
                 "why": f"{c['what']} —— {c['why']}（原文：{_snippet(s)}）",
                 "instead": c["instead"]} for c in hits]
    err = _css_error(s) if kind == "selector" else (_regex_error(s) if kind == "regex" else "")
    if not err:
        return []
    return [{"field": field, "construct": f"{kind}_syntax",
             "why": f"{'选择器不是合法 CSS' if kind == 'selector' else '正则编译不过'}："
                    f"{_snippet(s)}（{err}）",
             "instead": "到「书源管理」把这一项改写成" + ("标准 CSS 选择器" if kind == "selector" else "能编译的正则")}]


def _audit_modes(rule: dict) -> list:
    """`mode` 值域：**未知 mode 的下场是静默降级**（当 css 跑 / 当 single 跑），必须当场说。"""
    out = []
    for path, allowed in _MODE_SLOTS.items():
        node = _dig(rule, path)
        if not isinstance(node, dict) or not node.get("mode"):
            continue
        mode = str(node["mode"]).strip().lower()
        if mode not in allowed:
            out.append({"field": f"{path}.mode", "construct": "unknown_mode",
                        "why": f"mode「{mode}」引擎不认（只认 {' / '.join(allowed)}）",
                        "instead": "改成本项目支持的通道（未知 mode 不会被当成 css 静默跑）"})
    for path, allowed in (("book", _BOOK_MODES), ("chapter", _CHAPTER_MODES)):
        node = _dig(rule, path)
        mode = str((node or {}).get("mode") or "").strip().lower() if isinstance(node, dict) else ""
        if mode and mode not in allowed:
            out.append({"field": f"{path}.mode", "construct": "unknown_mode",
                        "why": f"「{mode}」不是合法的 {path}.mode（只认 {' / '.join(allowed)}）",
                        "instead": f"改成 {' / '.join(allowed)} 之一"})
    return out


def _audit_structure(rule: dict) -> list:
    """结构性缺口：**不会被任何报错抓住**、但会让源静静地什么都不给。

    只有一条：搜索没有「详情页地址」字段。引擎按 ``item.get("url")`` 判一条结果有没有效
    （`_parse_search` 与 `_parse_search_json` 都是），没有 url 字段 ⇒ 搜什么都回 0 条，
    界面只会说「没找到」—— 用户完全看不出是规则里缺了一项。
    （regex 模式不查：它的地址来自正则捕获组，命名组可以叫别的名字。）
    """
    sp = rule.get("search") or {}
    # ⚠️ `search` 可能压根不是字典（真实世界里的坏文件什么都有）—— 审计**绝不许抛异常**，
    #    脏输入如实报一条理由就行，把整次导入带崩才是最糟的结果。
    if not isinstance(sp, dict):
        return [{"field": "search", "construct": "no_url_field",
                 "why": f"搜索规则应该是一个对象，实际是 {type(sp).__name__}",
                 "instead": "到「书源管理」重新填写搜索规则"}]
    mode = str(sp.get("mode") or "css").strip().lower()
    fields = sp.get("fields") if isinstance(sp.get("fields"), dict) else {}
    if mode in ("css", "json") and not str(fields.get("url") or "").strip():
        return [{"field": "search.fields.url", "construct": "no_url_field",
                 "why": "搜索规则里没有「详情页地址」字段 —— 引擎靠它判断一条结果是否有效，"
                        "缺了就会永远搜不到（界面只会说「没找到」）",
                 "instead": "在「书源管理」里给搜索补一个地址字段（CSS 写法如 `a::attr(href)`）"}]
    return []


def audit_native_rule(rule) -> list:
    """native 规则 → ``[{field, why, instead}]``。**空列表 = 引擎确实跑得动**。

    ⚠️ 这是**转换诚实闸**：任何格式的适配器产物（Legado 3.x / 2.x 的转换结果、本项目导出
    文件里的规则、手写 native 规则）都要过这一关，**不许由转换器自称可用** ——
    `legado.analyze` 的 `supported` 就是由它的结论反推的。

    纯函数、零网络、**不抛异常**（脏输入如实报成一条理由，绝不把整次导入带崩）。
    """
    if not isinstance(rule, dict) or not rule:
        # ⚠️ 空字典也要单独说：`{}` 走下面的结构检查会报成「搜索规则里没有详情页地址」，
        #    那是**答非所问**（根本没规则，哪来的搜索字段）。
        return [{"field": "（规则）", "construct": "not_object",
                 "why": "规则不是一个 JSON 对象" if not isinstance(rule, dict) else "规则是空的",
                 "instead": "提供 JSON 对象 / 数组形式的书源文件"}]
    out = _audit_modes(rule) + _audit_structure(rule)
    for field, kind, value in _exec_fields(rule):
        out += _audit_value(field, kind, value)
    return out
