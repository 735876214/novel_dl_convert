import re
import pathlib

# 知轩藏书等格式：《书名》（校对版全本）作者：远瞳
FILENAME_RE = re.compile(
    r"^(?:《(?P<title>.+?)》)?\s*(?:（[^）]*）)?\s*(?:作者[：:]\s*(?P<author>[^\.]+))?",
    re.U,
)


def from_filename(name: str) -> dict:
    stem = pathlib.Path(name).stem
    m = FILENAME_RE.search(stem)
    if m and m.group("title"):
        title = m.group("title").strip()
        author = (m.group("author").strip() if m.group("author") else "未知")
    else:
        title = stem.strip()
        author = "未知"
    return {"title": title, "author": author}


def from_body(head: str) -> dict:
    """从正文头部抠元数据。"""
    meta = {}
    for k, p in [
        ("author", r"作者[：:]\s*(.+)"),
        ("description", r"简介[：:]\s*(.+)"),
        ("cover", r"封面[：:]\s*(\S+)"),
    ]:
        m = re.search(p, head)
        if m:
            meta[k] = m.group(1).strip()
    return meta


def merge_meta(*metas: dict) -> dict:
    """多来源合并：已解析出的书名/作者优先于占位值。"""
    out = {}
    for m in metas:
        for k, v in m.items():
            if v and (k not in out or out[k] in ("未知", None)):
                out[k] = v
    return out
