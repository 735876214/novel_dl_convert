import re

# 控制字符 + 零宽字符（含 BOM、零宽空格、RTL 标记等）
ZERO_WIDTH = re.compile(r"[\x00-\x1F\x7F-\x9F\u200B-\u200F\uFEFF]")

# 轻量自定义标记：保留 TXT 中常见的图片/链接/注释写法
CUSTOM_TAG_RE = re.compile(
    r"\[img=([^\]]*)\](.*?)\[/img\]"
    r"|\[link=([^\]]*)\](.*?)\[/link\]"
    r"|\[comment\](.*?)\[/comment\]", re.S
)


def preprocess(text: str) -> str:
    """清洗：全角空格当换行，清除控制符/零宽字符。"""
    text = "\r\n" + text.replace("\u3000", "\r\n")  # 全角空格视为换行
    return ZERO_WIDTH.sub("", text)


def paragraphs_to_html(text: str) -> str:
    """按行包裹为 <p>，转义特殊字符。"""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "".join(f"<p>{_esc(ln)}</p>" for ln in lines)


def apply_custom_tags(text: str) -> str:
    """可选：把 [img]/[link]/[comment] 转换为 HTML（默认管线未启用，按需调用）。"""
    def repl(m):
        if m.group(1) is not None:
            return f'<img src="{m.group(2)}" referrerpolicy="no-referrer" />'
        if m.group(3) is not None:
            return f'<a href="{m.group(3)}" target="_blank">{m.group(4)}</a>'
        return f"<!-- {m.group(5)} -->"

    return CUSTOM_TAG_RE.sub(repl, text)


def traditionalize(text: str, to_simplified: bool = True) -> str:
    """繁体 <-> 简体转换（依赖 opencc-python-reimplemented）。"""
    try:
        from opencc import OpenCC
        return OpenCC("t2s" if to_simplified else "s2t").convert(text)
    except Exception:
        return text


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
