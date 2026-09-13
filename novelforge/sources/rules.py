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
    "url": "https://x.com/search?kw={title}",
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
- 书页 book.mode=toc 时，chapter 自动走「toc 结构化分章」（最干净）。
- book.mode=single 时，chapter.mode=regex 用该书源正则切全文；=auto 用全局检测。
- 所有解析支持 css / regex 双通道，离线可用（正则），也可写 CSS 选择器（需 beautifulsoup4）。
"""
import asyncio
import re
from urllib.parse import quote, urljoin

from .base import SourceAdapter, DEFAULT_HEADERS


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


def _extract(html: str, rule: dict) -> str:
    rule = rule or {}
    if rule.get("mode") == "regex":
        return _extract_regex(html, rule)
    return _extract_css(html, rule)


def _parse_search(html: str, sp: dict) -> list[dict]:
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
                out.append(item)
        return out
    # css
    soup = _soup(html)
    nodes = soup.select(sp.get("container", ""))
    fields = sp.get("fields", {})
    out = []
    for n in nodes:
        item = {k: _field_value(n, spec) for k, spec in fields.items()}
        if item.get("url"):
            out.append(item)
    return out


def _extract_links(html: str, toc: dict, base_url: str) -> list[tuple[str, str]]:
    """返回 [(标题, 绝对URL)] 章节链接列表。"""
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


# ---------------- 书源类 ----------------

class RuleBasedSource(SourceAdapter):
    """由 JSON 规则驱动的书源；规则存于类属性 _RULE（由 make_rule_class 注入）。"""

    _RULE: dict = {}

    def __init__(self):
        rule = self._RULE
        hdrs = rule.get("headers")
        if hdrs:
            self.headers = {**DEFAULT_HEADERS, **hdrs}
        self._concurrency = int(rule.get("concurrency", 8) or 8)

    # ---- 搜索 ----
    async def search(self, client, title: str) -> list[dict]:
        sp = self._RULE.get("search") or {}
        url = sp.get("url", "").replace("{title}", quote(title))
        if not url:
            return []
        html = await client.get_text(url)
        return _parse_search(html, sp)

    # ---- 取书：整页全文 ----
    async def fetch_book(self, client, item: dict) -> str:
        bp = self._RULE.get("book") or {}
        if bp.get("mode") == "toc":
            chapters = await self._fetch_toc(client, bp, item["url"])
            return "\n\n".join(f"{c['title']}\n{c['body']}" for c in chapters)
        html = await client.get_text(item["url"])
        return _extract(html, bp.get("content", {}))

    # ---- 取书：结构化章节（供目录式分章）----
    async def fetch_book_chapters(self, client, item: dict) -> list[dict]:
        bp = self._RULE.get("book") or {}
        if bp.get("mode") == "toc":
            return await self._fetch_toc(client, bp, item["url"])
        # single：取全文后按 chapter 规则切分
        html = await client.get_text(item["url"])
        text = _extract(html, bp.get("content", {}))
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
                    bodies[i] = _extract(h, bp.get("content", {}))
                except Exception as e:  # 单章失败不中断整本
                    bodies[i] = f"（第 {i + 1} 章抓取失败：{e}）"

        await asyncio.gather(*(_one(i, u) for i, (_, u) in enumerate(links)))
        return [{"title": t, "body": bodies.get(i, "")} for i, (t, _) in enumerate(links)]

    # ---- 预览（廉价：目录 + 首章样本）----
    async def preview(self, client, item: dict) -> dict:
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
                    sample = _extract(h, bp.get("content", {}))[:1500]
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
    bp = rule.get("book") or {}
    if bp.get("mode") == "toc":
        toc = bp.get("toc") or {}
        if toc.get("mode") == "css" and not toc.get("container"):
            errs.append("book.toc 为 css 模式时 container 必填")
        if toc.get("mode") == "regex" and not toc.get("pattern"):
            errs.append("book.toc 为 regex 模式时 pattern 必填")
        if not bp.get("content"):
            errs.append("book.content（章节正文提取）必填")
    ch = rule.get("chapter") or {}
    if ch.get("mode") == "regex" and not ch.get("regex"):
        errs.append("chapter 为 regex 模式时 regex 必填")
    return errs
