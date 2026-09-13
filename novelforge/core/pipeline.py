import shutil
from pathlib import Path

from . import preprocess, detect, metadata, epub_builder

# 已是电子书格式的文件直接复制
EBOOK_EXT = {".epub", ".mobi", ".azw3", ".pdf", ".fb2"}


def _detect_encoding(path: Path) -> str:
    """多层编码检测（kaf-cli 思路）。"""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5"):
        try:
            path.read_text(encoding=enc)
            return enc
        except Exception:
            continue
    return "utf-8"


def convert_text(raw: str, out_dir: Path, opts: dict, meta: dict | None = None) -> Path:
    """把一段纯文本（本地读取或下载得到）转为 EPUB。"""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    raw = preprocess.preprocess(raw)
    if opts.get("traditionalize"):
        raw = preprocess.traditionalize(raw)

    base_meta = metadata.merge_meta(
        meta or {},
        metadata.from_filename(opts.get("filename", "") or ""),
        metadata.from_body(raw[:2000]),
    )

    cfg = opts.get("cfg") or {}
    chapters = detect.detect_chapters_cfg(raw, cfg, opts.get("merge", False))
    for ch in chapters:
        ch["body_html"] = preprocess.paragraphs_to_html(ch["body"])

    out = out_dir / f"{base_meta['title']}.epub"
    if out.exists() and not opts.get("force"):
        return out
    epub_builder.build_epub(base_meta, chapters, str(out))
    return out


def convert_txt(path: Path, out_dir: Path, opts: dict) -> Path:
    raw = path.read_text(encoding=_detect_encoding(path), errors="ignore")
    opts = dict(opts)
    opts.setdefault("filename", path.name)
    return convert_text(raw, out_dir, opts)


def convert_chapters(chapters: list[ dict], out_dir: Path, opts: dict, meta: dict | None = None) -> Path:
    """把「已结构化好的章节列表」直接转 EPUB（书源目录式分章时使用，最干净）。

    chapters: [{title, body}, ...]；chapter_regex 不为空时先按该书源正则再切一次。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    regex = (opts.get("chapter_regex") or "").strip()
    if regex:
        from .detect import split_by_offsets, regex_bounds
        import re as _re
        merged = []
        for ch in chapters:
            text = f"{ch['title']}\n{ch['body']}"
            bounds = sorted({(m.start(), m.group(0).strip()) for m in _re.compile(regex, _re.M).finditer(text)})
            if bounds:
                merged.extend(split_by_offsets(text, bounds, merge=False))
            else:
                merged.append(ch)
        chapters = merged

    if not chapters:
        raise ValueError("章节为空，无法生成 EPUB")

    base_meta = metadata.merge_meta(
        meta or {},
        metadata.from_filename(opts.get("filename", "") or chapters[0]["title"]),
        metadata.from_body(chapters[0]["body"][:2000]),
    )
    for ch in chapters:
        ch["body_html"] = preprocess.paragraphs_to_html(ch["body"])

    out = out_dir / f"{base_meta['title']}.epub"
    if out.exists() and not opts.get("force"):
        return out
    epub_builder.build_epub(base_meta, chapters, str(out))
    return out


def dispatch(src: Path, out_dir: Path, opts: dict):
    """文件分发：txt 走转换管线，电子书格式直接复制，其余跳过。"""
    if src.suffix.lower() == ".txt":
        return ("convert", convert_txt(src, out_dir, opts))
    if src.suffix.lower() in EBOOK_EXT:
        shutil.copy2(src, out_dir / src.name)
        return ("copy", out_dir / src.name)
    return ("skip", src)
