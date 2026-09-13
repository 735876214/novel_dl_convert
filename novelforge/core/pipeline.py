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


def convert_txt(path: Path, out_dir: Path, opts: dict) -> Path:
    raw = path.read_text(encoding=_detect_encoding(path), errors="ignore")
    raw = preprocess.preprocess(raw)
    if opts.get("traditionalize"):
        raw = preprocess.traditionalize(raw)

    meta = metadata.merge_meta(
        metadata.from_filename(path.name),
        metadata.from_body(raw[:2000]),
    )

    chapters = detect.detect_chapters(raw)
    for ch in chapters:
        ch["body_html"] = preprocess.paragraphs_to_html(ch["body"])

    out = out_dir / f"{meta['title']}.epub"
    if out.exists() and not opts.get("force"):
        return out
    epub_builder.build_epub(meta, chapters, str(out))
    return out


def dispatch(src: Path, out_dir: Path, opts: dict):
    """文件分发：txt 走转换管线，电子书格式直接复制，其余跳过。"""
    if src.suffix.lower() == ".txt":
        return ("convert", convert_txt(src, out_dir, opts))
    if src.suffix.lower() in EBOOK_EXT:
        shutil.copy2(src, out_dir / src.name)
        return ("copy", out_dir / src.name)
    return ("skip", src)
