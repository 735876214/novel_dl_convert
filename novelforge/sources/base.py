"""书源适配器基类：search / fetch_book 为核心接口，其余为可选钩子。

设计目标（对应 denovel「写扩展脚本即可增加站点支持」）：
- 新增一个站点 = 新增一个继承 SourceAdapter 的类 + @register 装饰器，零改核心。
- 每个适配器自带浏览器标头与域名白名单（supports_url）。
- 可选 fetch_content（单章正文）、render（JS 渲染兜底）、decryption_js（原生 JS 解密）。
"""
from abc import ABC, abstractmethod

from ..core.network import DEFAULT_HEADERS

# 公开性：public=True 表示公版 / 合规来源。
# ⚠️ 第 93 期起这只影响**书源列表里的徽章**（「公版 / 私有」），**不再参与任何过滤** ——
#    原先的「仅放行公版源」闸门（download.public_only）已按用户决定删除（见 DownloadManager.gate_reason）。
PUBLIC = True
NON_PUBLIC = False


class SourceAdapter(ABC):
    name: str = "base"
    # 类浏览器标头（可被覆盖）
    headers: dict = DEFAULT_HEADERS
    # 域名白名单：用于 /supported 与自动选源
    domains: list[str] = []
    # 是否公开合规来源（**仅标注**：书源列表的「公版 / 私有」徽章；不参与任何闸门判定）
    public: bool = PUBLIC

    @abstractmethod
    async def search(self, client, title: str) -> list[dict]:
        """返回候选列表，每条至少含 {title, author, url}。"""
        ...

    # ---- 可选钩子 ----
    async def search_page(self, client, title: str, page: int = 1) -> dict:
        """按页搜索（第 71 期）：返回 ``{"items": [...], "has_more": bool}``。

        默认实现给**不支持分页**的源兜底，关键在 ``page > 1`` 时返回空列表 ——
        否则界面的「加载更多」会把第一页原样再取一遍，用户看到的是成片重复。
        「没有更多」就如实说没有，不拿第一页冒充下一页。

        适配器要用真分页时覆写本方法：``GutenbergSource`` 用 gutendex 自带的
        ``next`` 字段判 ``has_more``；``RuleBasedSource`` 只在搜索 URL 模板含
        ``{page}`` 时才替换（不含时第 1 页与现状逐字节一致）。
        """
        if page > 1:
            return {"items": [], "has_more": False}
        return {"items": await self.search(client, title) or [], "has_more": False}

    @abstractmethod
    async def fetch_book(self, client, item: dict) -> str:
        """抓取整本书的纯文本（已拼接各章），供后续分章 / 转 EPUB。"""
        ...

    # ---- 可选钩子 ----
    async def fetch_content(self, client, url: str) -> str:
        """抓取单页 / 单章正文（HTML 或纯文本）。默认取 GET 文本。"""
        return await client.get_text(url)

    async def render(self, client, url: str) -> str:
        """需要 JS 渲染时（如 Cloudflare）的兜底；默认等价于 fetch_content。"""
        return await self.fetch_content(client, url)

    def supports_url(self, url: str) -> bool:
        """判断该 URL 是否由本适配器处理。"""
        return any(d in url for d in self.domains)

    def decryption_js(self) -> str | None:
        """站点专用解密 JS 片段。__args[0] 为待解密字符串，需 return 明文。"""
        return None

    # ---- 在线阅读（第 93 期）----

    def online_support(self) -> str:
        """这个源能不能**逐章在线阅读**；返回可直接展示的原因（空串 = 能）。

        默认「不能」：普通适配器（如 Gutenberg）只实现「整本取回」，而在线读要的是
        「书页 → 章节清单 → 单章正文」这条链，它没有。

        ⚠️ 返回**原因原文**而不是一个布尔：详情页要把这句话原样显示给用户
        （AGENTS.md：不做假交互 —— 灰掉的入口必须说清为什么灰）。
        """
        return "这个书源不支持逐章在线阅读：它只能整本取回，没有「书页 → 单章」这条链"

    def online_mode(self) -> str:
        """在线读的取法：``"toc"`` = 一章一页、按需取；``"single"`` = 只有整本一页。

        空串 = 不支持（与 :meth:`online_support` 一致）。两种取法的差别只落在
        **取数**上，缓存 / 对齐 / 展示三层完全相同。
        """
        return ""

    def content_may_be_html(self) -> bool:
        """`book.content` 取出来的正文**可能是 HTML** 吗？

        决定在线阅读要不要先把标记压成纯文本（见 `sources/online.html_to_text`）。
        两边都得做对：该剥没剥 ⇒ 源站标记进了 `v-html`；不该剥却剥了 ⇒ 正文被吃掉一段。
        """
        return False


REGISTRY: dict[str, type["SourceAdapter"]] = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls
