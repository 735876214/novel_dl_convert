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
import re
from urllib.parse import quote, urljoin

from .base import SourceAdapter, DEFAULT_HEADERS


# ---------------- 书源变量 `{var:<key>}`（第 86 期）----------------
# Legado 的 `loginUi` 表单值（番茄的「密钥」、聚合源的「模式 / 音色」）以 `{var:key}` 形式
# 出现在规则里。**缺失绝不静默留空**：留着原文请求会带着 `%7Bvar%3A密钥%7D` 出去，
# 站点回一个空页面，报错离原因十万八千里 —— 所以取值处统一先查变量齐不齐。

_VAR_RE = re.compile(r"\{var:([^}]+)\}")


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
    """按 css 规则从 html 抽取文本（text=true）或保留标签的 HTML（html=true）。"""
    node = _soup(html).select_one(rule.get("container", ""))
    if not node:
        return ""
    if rule.get("html"):
        return str(node)
    return node.get_text("\n", strip=True)


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
            chapters = await self._fetch_toc(client, bp, item["url"])
            return "\n\n".join(f"{c['title']}\n{c['body']}" for c in chapters)
        html = await client.get_text(item["url"])
        return await self._content(html, bp.get("content", {}))

    # ---- 取书：结构化章节（供目录式分章）----
    async def fetch_book_chapters(self, client, item: dict) -> list[dict]:
        self._check_vars()
        bp = self._RULE.get("book") or {}
        if bp.get("mode") == "toc":
            return await self._fetch_toc(client, bp, item["url"])
        # single：取全文后按 chapter 规则切分
        html = await client.get_text(item["url"])
        text = await self._content(html, bp.get("content", {}))
        ch = self._RULE.get("chapter") or {}
        if ch.get("mode") == "regex":
            return _split_regex(text, ch["regex"])
        from ..core import detect
        return detect.detect_chapters(text)

    async def _fetch_toc(self, client, bp: dict, book_url: str) -> list[dict]:
        toc = bp.get("toc", {})
        html = await client.get_text(book_url)
        links = _extract_links(html, toc, book_url)
        sem = asyncio.Semaphore(self._concurrency)

        bodies = {}

        async def _one(i: int, url: str):
            async with sem:
                try:
                    h = await client.get_text(url)
                    bodies[i] = await self._content(h, bp.get("content", {}))
                except Exception as e:  # 单章失败不中断整本
                    bodies[i] = f"（第 {i + 1} 章抓取失败：{e}）"

        await asyncio.gather(*(_one(i, u) for i, (_, u) in enumerate(links)))
        return [{"title": t, "body": bodies.get(i, "")} for i, (t, _) in enumerate(links)]

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

    # ---- 预览（廉价：目录 + 首章样本）----
    async def preview(self, client, item: dict) -> dict:
        self._check_vars()
        bp = self._RULE.get("book") or {}
        if bp.get("mode") == "toc":
            toc = bp.get("toc", {})
            html = await client.get_text(item["url"])
            links = _extract_links(html, toc, item["url"])
            toc_titles = [t for t, _ in links]
            sample = ""
            if links:
                try:
                    h = await client.get_text(links[0][1])
                    # 预览也要解密：否则用户看到的是乱码，会以为「这条源坏了」
                    sample = (await self._content(h, bp.get("content", {})))[:1500]
                except Exception:
                    sample = ""
            return {"toc": toc_titles, "sample": sample}
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
