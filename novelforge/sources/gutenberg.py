from .base import SourceAdapter, register


@register
class GutenbergSource(SourceAdapter):
    """Project Gutenberg 公版书源（Gutendex API，免费合规，public=True）。"""

    name = "gutenberg"
    domains = ["gutendex.com", "gutenberg.org"]
    public = True
    BASE = "https://gutendex.com/books/"

    async def search(self, client, title):
        r = await client.get(self.BASE, params={"search": title}, timeout=15)
        r.raise_for_status()
        return [
            {
                "title": b["title"],
                "author": (b["authors"][0]["name"] if b["authors"] else "未知"),
                "url": b.get("formats", {}).get("text/html"),
                "formats": b["formats"],
            }
            for b in r.json()["results"]
        ]

    async def fetch_book(self, client, item) -> str:
        """优先取 UTF-8 纯文本；退而求其次任意 text/plain。"""
        formats = item.get("formats", {})
        url = (
            formats.get("text/plain; charset=utf-8")
            or next((v for k, v in formats.items() if k.startswith("text/plain")), None)
        )
        if not url:
            raise ValueError("该书无纯文本格式，无法转为 EPUB")
        text = await client.get_text(url)
        # Gutenberg 文本首尾常含许可证声明，简单裁掉常见标记之间的内容
        return _trim_gutenberg(text)


def _trim_gutenberg(text: str) -> str:
    """去掉 Gutenberg 文本尾部许可证与头部元信息（尽力而为，不影响正文分章）。"""
    markers_start = ["*** START OF", "***START OF", "*END OF THE PROJECT"]
    for m in markers_start:
        idx = text.find(m)
        if idx != -1:
            # 取到该标记所在行末尾
            nl = text.find("\n", idx)
            text = text[nl + 1:] if nl != -1 else text[idx + len(m):]
            break
    markers_end = ["*** END OF", "***END OF"]
    for m in markers_end:
        idx = text.find(m)
        if idx != -1:
            text = text[:idx]
            break
    return text.strip()
