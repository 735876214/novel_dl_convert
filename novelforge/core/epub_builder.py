import re
import uuid
from pathlib import Path

from ebooklib import epub


def sanitize_html(html: str) -> str:
    """轻量净化：剥离 script/style 与事件属性，避免破坏 EPUB 结构。"""
    html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.I)
    html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.I)
    html = re.sub(r"\s(on\w+)\s*=\s*[\"'][^\"']*[\"']", "", html, flags=re.I)
    return html


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_epub(meta: dict, chapters: list, out_path: str,
               css: str = None, cover: str = None, nav: bool = True):
    """组装 EPUB：ebooklib 已保证 mimetype 首条目与标准结构。

    ``nav=False``（第 55 期，opt-in）：**不把 nav 目录页放进 spine** —— spine 只含
    正文章节，于是 ``library._reading_list`` 的章节 index 变成 0 基、与「原生 TXT
    分章」的索引空间完全对齐（TXT 派生 EPUB 两条路线不再差一位）；目录/NCX 仍然
    照常写入（标题不丢）。默认 ``True`` 保持既有全部调用方的产物逐字不变。
    """
    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(meta.get("title", "未命名"))
    book.set_language(meta.get("language", "zh"))
    book.add_author(meta.get("author", "未知"))
    if meta.get("description"):
        book.add_metadata("DC", "description", meta["description"])

    if cover:
        try:
            book.set_cover("cover.jpg", Path(cover).read_bytes())
        except Exception:
            pass

    if css:
        book.add_item(epub.EpubItem(
            file_name="style.css", media_type="text/css", content=css))

    items = []
    for i, ch in enumerate(chapters):
        content = sanitize_html(ch.get("body_html") or ch.get("body", ""))
        c = epub.EpubHtml(title=ch["title"], file_name=f"c{i:04d}.xhtml", lang="zh")
        c.content = f"<h2>{_esc(ch['title'])}</h2>{content}"
        book.add_item(c)
        items.append(c)

    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = (["nav"] if nav else []) + items
    epub.write_epub(out_path, book)
