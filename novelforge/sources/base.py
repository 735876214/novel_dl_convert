"""书源适配器基类：search / fetch_book 为核心接口，其余为可选钩子。

设计目标（对应 denovel「写扩展脚本即可增加站点支持」）：
- 新增一个站点 = 新增一个继承 SourceAdapter 的类 + @register 装饰器，零改核心。
- 每个适配器自带浏览器标头与域名白名单（supports_url）。
- 可选 fetch_content（单章正文）、render（JS 渲染兜底）、decryption_js（原生 JS 解密）。
"""
from abc import ABC, abstractmethod

from ..core.network import DEFAULT_HEADERS

# 公开性：public=True 表示公版 / 合规来源，可被默认值放行；False 需用户显式开启
PUBLIC = True
NON_PUBLIC = False


class SourceAdapter(ABC):
    name: str = "base"
    # 类浏览器标头（可被覆盖）
    headers: dict = DEFAULT_HEADERS
    # 域名白名单：用于 /supported 与自动选源
    domains: list[str] = []
    # 是否公开合规来源（download.public_only 为 true 时只放行 public 源）
    public: bool = PUBLIC

    @abstractmethod
    async def search(self, client, title: str) -> list[dict]:
        """返回候选列表，每条至少含 {title, author, url}。"""
        ...

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


REGISTRY: dict[str, type["SourceAdapter"]] = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls
