import httpx

from .base import SourceAdapter, register


@register
class GutenbergSource(SourceAdapter):
    """Project Gutenberg 公版书源（Gutendex API，免费合规）。"""

    name = "gutenberg"
    BASE = "https://gutendex.com/books/"

    async def search(self, client, title):
        r = await client.get(self.BASE, params={"search": title}, timeout=15)
        r.raise_for_status()
        return [
            {
                "title": b["title"],
                "author": (b["authors"][0]["name"] if b["authors"] else "未知"),
                "formats": b["formats"],
            }
            for b in r.json()["results"]
        ]

    async def download(self, client, item, dest):
        url = item["formats"].get("application/epub+zip")
        if not url:
            raise ValueError("该书无 EPUB 格式")
        async with client.stream("GET", url) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                async for chunk in r.aiter_bytes(8192):
                    f.write(chunk)
