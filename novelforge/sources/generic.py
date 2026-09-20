"""可扩展站点模板：演示如何写一个真实的小说站适配器。

denovel 的核心体验之一是「写扩展脚本即可增加站点支持」。本文件是一个**模板**：
把 domains / 解析选择器 / 解密 JS 换成你的目标站点即可，核心（并发抓取、Cookie
持久化、JS 解密、转 EPUB）全部复用，无需改其它代码。

使用步骤：
1. 复制本文件为 my_site.py，改 name / domains / 解析逻辑。
2. 在 search() 里用 BeautifulSoup/lxml 解析搜索结果列表。
3. 在 fetch_book() 里取目录页 → 列出章节 URL → 并发抓取正文 → 拼接。
4. 若站点有字体加密 / 内容混淆，在 decryption_js() 返回解密片段，render() 会自动调用。
5. **给自己的类加 `@register`**（本文件刻意不加，见下）。

⚠️ 本模板类**不注册**：它的 `search()` / `fetch_book()` 都是 `NotImplementedError`，
一旦进 `REGISTRY`，`DownloadManager.search()` 就会每次都命中它、抛异常，被吞成一条
「书源 generic 搜索失败」的**假失败日志**（还会白建一次 BrowserClient）；同时它那个
占位域名 `example-novel.com` 会混进 `/api/sources` 的书源清单，看着像一个真书源。

不写代码就加站点，走 `rules.py` 的 JSON 规则（`CONFIG_DIR/sources/*.json`，见 `store.py`）：
那才是当前的推荐路径，本模板只服务「规则表达不了、必须写 Python」的场景。
"""
from .base import SourceAdapter
from ..core import network


class GenericHtmlSource(SourceAdapter):
    name = "generic"
    # 改成你的站点主域名（用于 /supported 自动选源）
    domains = ["example-novel.com"]
    public = False  # 非公版源，需用户在 config 中显式开启 download

    SEARCH_URL = "https://example-novel.com/search?q={title}"
    # 并发抓取章节数的上限（防 OOM / 被封）
    CONCURRENCY = 8

    def decryption_js(self) -> str | None:
        """站点专用解密 JS。__args[0] 为加密字符串，必须 return 明文。

        示例（番茄类字体映射解密示意）：
            const s = __args[0];
            const map = {"\\uE000":"我","\\uE001":"你"};  // 真实映射表来自 charset.json
            return s.split("").map(ch => map[ch] || ch).join("");
        """
        return None

    async def search(self, client, title):
        # TODO: 按站点结构解析搜索页，返回 [{"title","author","url","formats":{}}]
        raise NotImplementedError(
            "请实现 search()：GET SEARCH_URL → 解析结果列表（建议用 BeautifulSoup）"
        )

    async def _fetch_chapters_concurrent(self, client, chapter_urls: list[str]) -> list[str]:
        """并发抓取章节正文（带信号量限流，对应 denovel 多线程漫画式并发）。"""
        sem = __import__("asyncio").Semaphore(self.CONCURRENCY)
        bodies = [None] * len(chapter_urls)

        async def _one(i, url):
            async with sem:
                try:
                    html = await client.get_text(url)
                    if self.decryption_js():
                        html = await network.run_js(self.decryption_js(), html)
                    bodies[i] = self._extract_paragraphs(html)
                except Exception as e:
                    bodies[i] = f"（第 {i + 1} 章抓取失败：{e}）"

        await __import__("asyncio").gather(
            *(_one(i, u) for i, u in enumerate(chapter_urls))
        )
        return [b for b in bodies if b]

    @staticmethod
    def _extract_paragraphs(html: str) -> str:
        """从章节 HTML 抽取正文纯文本。站点不同请替换选择器。

        默认实现：去除标签与脚本后，按换行合并非空行；生产环境建议用
        BeautifulSoup 定位正文容器（如 <div id="content">）。"""
        import re

        html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
        html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.I)
        text = re.sub(r"<[^>]+>", "\n", html)
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        return "\n".join(lines)

    async def fetch_book(self, client, item) -> str:
        # TODO: 取目录页 → 解析章节 URL 列表 chapter_urls
        # bodies = await self._fetch_chapters_concurrent(client, chapter_urls)
        # return "\\n\\n".join(bodies)
        raise NotImplementedError(
            "请实现 fetch_book()：取目录页 → 列出章节 URL → 调用 _fetch_chapters_concurrent"
        )
