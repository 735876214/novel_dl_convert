"""把「书里的 HTML」变成「可以塞进阅读器 DOM 的 HTML」（第 133 期）。

**问题**：阅读器把服务端给的一整段 HTML 直接 `v-html` 进页面 —— 而这段 HTML 的**来源是书**：
EPUB 的章节体本来就是 XHTML（`library.chapter_html` 只改写资源 URL、原样照发），TXT / MOBI 的
兜底路径还会把**章节标题裸拼**进 `<h2>`。于是「从外面下载来的一本书」里的
``<script>`` / ``onerror=`` / ``javascript:`` 就变成了**应用自己的脚本**：它与界面**同源**，
能读登录 token、能以用户身份调所有接口、能删书。这不是「书的样式有点怪」，是书在界面里执行。

**两个方向，两个函数**（判据只此一处，`epub_builder` / `library` / `txtcache` / `mobicache` 都调这里）：

- :func:`sanitize` —— 给**书里带来的 HTML**：删掉一切能执行的东西，保留正文结构与常见排版属性；
- :func:`heading` —— 给**我们自己拼的 HTML**：标题先转义再包 ``<h2>``（拼串时忘了转义，
  就等于把书名 / 章名当代码写进页面）。

**为什么用 lxml 而不是正则**：正则版净化可以被 ``<scr<script>ipt>``、属性里的引号变体、
``<svg onload>`` 之类绕过 —— 而「绕过一次」在这里的代价就是代码执行。lxml 已经是本项目的依赖
（`fb2cache` 用它解析 FB2），解析成树再删节点 / 删属性，判据落在**解析结果**上而不是字符上。
解析不了的（坏 HTML）退化成**转义后的纯文本** —— 宁可少一点排版，也不能把未知输入原样发出去。
"""
from __future__ import annotations

from lxml import etree, html as lxml_html

#: 这些节点连同**子树**一起删 —— 它们的「内容」是代码 / 另一篇文档，没有正文价值：
#: `script` 执行、`style` 能盖住界面做钓鱼、`iframe` / `object` / `applet` 载入别的文档、
#: `svg` / `math` 能藏 `onload` 与 `xlink:href="javascript:"`。
#:
#: ⚠️ **其余的「危险标签」不进这张表，靠允许清单降级**（`embed` / `link` / `meta` / `base` /
#: `input` / `button` / `form` / … 都不在 :data:`ALLOWED_TAGS` 里 ⇒ 变成没有属性的 `<span>`）。
#: 原因是**撕子树会连带丢掉兄弟节点**：libxml2 不认 `<embed>` 是空元素，会把它后面的内容
#: 全收成它的子树 —— 于是「删掉 embed」把后面几段正文一起带走了（实测：一句
#: `<embed src=x>` 就能让后面两个 `<p>` 消失）。降级成 span 则一定是无损的。
#: 净化口径的版本。**改动 :func:`sanitize` 的判据就要 +1** —— 章节 HTML 会进 Redis 缓存
#: （键里是「书 + 章 + 源文件指纹」），源文件没动时指纹不变 ⇒ 不 +1 的话旧缓存会继续下发
#: 旧形态，等于改判据看不见效果（与本项目 `*_RULE_VERSION` 同一条规矩）。
#: v2（第 134 期）：补上开头裸文本（`root.text`）—— v1 会把「第一个标签之前」的正文丢掉，
#: 不换版本号的话，已经读过一遍的书还会继续从缓存里拿到缺首段的 HTML。
CHAPTER_HTML_VERSION = 2

DROP_TAGS = frozenset({
    "script", "style", "iframe", "noscript", "template", "object", "applet",
    "svg", "math", "frame", "frameset",
})

#: **允许清单**（不是黑名单）：`<p>` `<img>` `<ruby>` 这些是正文排版需要的，其余一律降级。
#:
#: 为什么用允许清单：解析器对畸形输入的「复原」不可预测 —— 实测 ``<span<script>alert(1)``
#: 会被 lxml 解析成一个**名字叫 `span<script` 的标签**，黑名单按名字查就漏了。允许清单
#: 下不认识的名字统统变 ``<span>``（保留子树与文字、丢掉它自己的属性），这种输入也就没了。
ALLOWED_TAGS = frozenset({
    "a", "abbr", "address", "article", "aside", "b", "big", "blockquote", "br",
    "caption", "center", "cite", "code", "col", "colgroup", "dd", "del", "div",
    "dl", "dt", "em", "figcaption", "figure", "font", "footer", "h1", "h2", "h3",
    "h4", "h5", "h6", "header", "hr", "i", "img", "ins", "kbd", "li", "main",
    "mark", "nav", "ol", "p", "pre", "q", "rp", "rt", "ruby", "s", "samp",
    "section", "small", "span", "strike", "strong", "sub", "sup", "table",
    "tbody", "td", "tfoot", "th", "thead", "time", "tr", "tt", "u", "ul", "var", "wbr",
})

#: **属性允许清单**：排版需要的那些。事件属性（``on*``）、``srcdoc``、``srcset``、
#: ``formaction`` 之类都不在表里 ⇒ 自动消失，不用逐个写黑名单。
GLOBAL_ATTRS = frozenset({"class", "id", "title", "style", "lang", "dir"})
TAG_ATTRS = {
    "a": frozenset({"href", "name", "rel", "target"}),
    "img": frozenset({"src", "alt", "width", "height", "hspace", "vspace", "border"}),
    "td": frozenset({"colspan", "rowspan", "align", "valign", "width", "height"}),
    "th": frozenset({"colspan", "rowspan", "align", "valign", "width", "height", "scope"}),
    "table": frozenset({"border", "cellpadding", "cellspacing", "width", "summary"}),
    "col": frozenset({"span", "width"}), "colgroup": frozenset({"span", "width"}),
    "ol": frozenset({"start", "reversed", "type"}),
    "li": frozenset({"value"}), "hr": frozenset({"width", "size", "noshade"}),
}

#: 值里出现这些前缀就整条属性删掉（`javascript:` 之类在 `href` / `src` / `xlink:href` /
#: `action` 上都是执行入口）。判据前先去掉空白与控制字符 —— 浏览器解析 URL 时也会忽略它们。
_DANGEROUS_URL_SCHEMES = ("javascript:", "vbscript:", "data:text/html", "data:image/svg")


def escape(text: str) -> str:
    """最小转义（与 `epub_builder` / `preprocess` 的既有口径一致：只处理三个字符）。"""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def heading(title) -> str:
    """把章节标题包成 ``<h2>`` —— **必须先转义**（标题来自书里的行）。"""
    return f"<h2>{escape(title or '')}</h2>"


def _clean_url(value: str) -> bool:
    """``True`` = 这条 URL 属性可以留。"""
    v = "".join(ch for ch in value.lower() if ch not in " \t\r\n\x00")
    return not v.startswith(_DANGEROUS_URL_SCHEMES)


def _strip_element(el) -> None:
    """连子树一起摘掉，但**保留尾巴文字**（`<p>a<script>x</script>b</p>` 里的 `b` 不能丢）。

    ⚠️ 尾巴要接给**它自己的前一个兄弟**。写成「接给 ``parent[-1]``」是错的：那时后面的
    元素还没删，``parent[-1]`` 指向的是**后面**那个，文字会被顺手挪到它后面
    （``a<script>x</script>b<iframe></iframe>c`` 会变成 ``acb``）。
    """
    parent = el.getparent()
    if parent is None:
        return
    tail = el.tail
    prev = el.getprevious()
    parent.remove(el)
    if tail:
        if prev is not None:
            prev.tail = (prev.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail


def sanitize(markup: str) -> str:
    """净化一段「来自书」的 HTML 片段；返回同样结构的干净片段。"""
    if not markup:
        return ""
    if "<" not in markup:            # 纯文本：没有标签，原样返回
        return markup
    try:
        root = lxml_html.fragment_fromstring(markup, create_parent="div")
    except (etree.ParserError, etree.XMLSyntaxError, ValueError):
        return escape(markup)        # 解析失败 ⇒ 退化成纯文本，不发未知结构

    for el in list(root.iter()):
        if not isinstance(el.tag, str):          # 注释 / 处理指令：删
            _strip_element(el)
            continue
        tag = el.tag.lower()
        if tag in DROP_TAGS:
            _strip_element(el)
            continue
        if tag not in ALLOWED_TAGS:
            # 不认识的名字（含解析器复原出来的怪标签，如 `span<script`）⇒ 降级成 span：
            # 子树与文字都留着，它自己的属性全部丢掉，于是没有第二处判据要维护。
            el.tag = "span"
            el.attrib.clear()
            continue
        allowed = GLOBAL_ATTRS | TAG_ATTRS.get(tag, frozenset())
        for name in list(el.attrib):
            low = name.lower()
            value = el.attrib.get(name) or ""
            if low not in allowed or not _clean_url(value):
                del el.attrib[name]
            elif low == "style" and ("javascript:" in value.lower() or "expression(" in value.lower()):
                del el.attrib[name]
    # 用 XML 序列化：`<br/>` / `<img .../>` 保持自闭合（与库内既有 HTML 的字面形态一致，
    # 前端与 EPUB 阅读器两边都认），HTML 序列化会把它们写成 `<br>`。
    #
    # ⚠️ `root.text` 必须单独拼在最前面（第 134 期）：它是「第一个子元素**之前**」的裸文本，
    # 不在任何子元素的 `tostring()` 里。只拼子元素时，一段以裸文字开头的正文
    # （``第一段<p>第二段</p>`` —— 不少 EPUB 的 `<body>` 就是这样）会**整段丢掉开头**，
    # 而且缓存 24h 看不出来。解析器已经把实体解码成字符，这里必须重新转义。
    return escape(root.text or "") + "".join(
        etree.tostring(c, encoding="unicode", method="xml") for c in root
    )
