import shutil
from pathlib import Path

from . import audio, preprocess, detect, metadata, epub_builder, ebook_convert, komga

# 已是电子书格式的文件直接复制（含漫画归档与**单个**音频文件；
# 「音频目录」形态由 dispatch 的目录分支单独处理）
EBOOK_EXT = {".epub", ".mobi", ".azw3", ".pdf", ".fb2", ".cbz", ".cbr", *audio.AUDIO_EXTS}


def _copy_tree(src: Path, dst: Path) -> None:
    """整树复制音频目录（跳过隐藏项与 macOS 垃圾），保留内部相对结构。"""
    dst.mkdir(parents=True, exist_ok=True)
    for c in src.rglob("*"):
        if c.is_dir() or c.name.startswith("."):
            continue
        if "__MACOSX" in c.parts or c.name in ("Thumbs.db", ".DS_Store"):
            continue
        t = dst / c.relative_to(src)
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(c, t)


def _layout(cfg: dict) -> str:
    return str((cfg.get("output") or {}).get("layout") or "flat").strip().lower()


def _place(out_dir: Path, stem: str, ext: str, series: str, index: str, cfg: dict) -> Path:
    """按 ``output.layout`` 算出落盘路径，并建好系列目录（Komga 布局时才有一层子目录）。"""
    rel = komga.relpath_for(stem, ext, series, index, _layout(cfg))
    target = out_dir / rel
    if target.parent != out_dir:
        target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _emit(base_meta: dict, chapters: list, out_dir: Path, opts: dict) -> Path:
    """产出成品：EPUB 必产，再按 ``output.format`` 派生 MOBI / AZW3。

    - **EPUB 始终生成**：在线阅读（library.chapter_html）只支持 EPUB，是阅读基础。
    - ``format`` 为 mobi/azw3 时用 Calibre 额外派生；不可用或失败则**降级**，
      把原因写进 ``opts["_notice"]``，由调用方写进活动日志 / 界面提示。
    - **落盘位置**由 ``output.layout`` 决定：komga 布局下有系列的书进
      ``系列名/系列名 #N.epub``（见 core/komga.py）；无系列仍旧平铺 ——
      转换出来的书**没有系列元数据**（epub_builder 不写 series），
      所以这里只能从书名推断，判不出就老实平铺。
    - 返回交付物路径：派生成功为派生文件，否则为 EPUB 本身。
    """
    title = base_meta.get("title") or "untitled"
    cfg = opts.get("cfg") or {}
    series, index = komga.infer(
        title, base_meta.get("series", ""), base_meta.get("series_index", "")
    )
    epub = _place(out_dir, title, "epub", series, index, cfg)
    if epub.exists() and not opts.get("force"):
        return epub
    epub_builder.build_epub(base_meta, chapters, str(epub))

    fmt = str((cfg.get("output") or {}).get("format") or "epub").strip().lower()
    if fmt not in ebook_convert.SUPPORTED:
        opts["_notice"] = ""
        return epub

    # 派生文件与原 EPUB **同目录同名**（komga 布局时就在系列目录里）
    target = epub.with_suffix(f".{fmt}")
    try:
        timeout = int(opts.get("ebook_convert_timeout") or ebook_convert.DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        timeout = ebook_convert.DEFAULT_TIMEOUT
    res = ebook_convert.convert(epub, target, timeout=timeout)
    if res["ok"]:
        opts["_notice"] = ""
        return Path(res["output"])
    opts["_notice"] = f"{fmt.upper()} 派生失败，已降级为 EPUB：{res['error']}"
    return epub


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

    out = _emit(base_meta, chapters, out_dir, opts)
    return out


def convert_txt(path: Path, out_dir: Path, opts: dict) -> Path:
    raw = path.read_text(encoding=_detect_encoding(path), errors="ignore")
    inner = dict(opts)
    inner.setdefault("filename", path.name)
    out = convert_text(raw, out_dir, inner)
    # 回传降级提示（派生格式失败的原因），供调用方写进活动日志
    opts["_notice"] = inner.get("_notice", "")
    return out


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

    out = _emit(base_meta, chapters, out_dir, opts)
    return out


def dispatch(src: Path, out_dir: Path, opts: dict):
    """文件分发：txt 走转换管线，电子书 / 漫画 / 音频直接复制，其余跳过。

    复制路径同样遵循 ``output.layout``：这类文件（外部 EPUB / 漫画 CBZ·CBR）没有
    ``calibre:series`` 可读的解析环节，系列只能从**文件名**推断（见 core/komga.py）——
    这正是把漫画喂给 Komga 的主要场景。

    **目录**（含音频）整树复制为一本书目目录：有声书「一章一文件」就靠这条路径入库。
    """
    if src.is_dir():
        if not audio.is_audio_dir(src):
            return ("skip", src)
        cfg = opts.get("cfg") or {}
        meta = opts.get("meta") or {}
        series, index = komga.infer(
            src.name, meta.get("series", ""), meta.get("series_index", "")
        )
        target = out_dir / komga.relpath_for_dir(src.name, series, index, _layout(cfg))
        _copy_tree(src, target)
        return ("copy", target)
    if src.suffix.lower() == ".txt":
        return ("convert", convert_txt(src, out_dir, opts))
    if src.suffix.lower() in EBOOK_EXT:
        cfg = opts.get("cfg") or {}
        # 上传/下载链路可能已带显式元数据（如书源给的系列名），优先采信它
        meta = opts.get("meta") or {}
        series, index = komga.infer(
            src.stem, meta.get("series", ""), meta.get("series_index", "")
        )
        target = _place(out_dir, src.stem, src.suffix.lstrip("."), series, index, cfg)
        shutil.copy2(src, target)
        return ("copy", target)
    return ("skip", src)
