import codecs
import shutil
from pathlib import Path

from . import audio, preprocess, detect, metadata, epub_builder, komga

# 已是电子书格式的文件直接复制（含漫画归档与**单个**音频文件；
# 「音频目录」形态由 dispatch 的目录分支单独处理）
# 第 62 期起含 ``.txt``：TXT **只入库不转换** —— 阅读链路本来就走「派生 EPUB 缓存」
# （见 core/txtcache.py），再在入库时转一份落到 output 只是白占一份空间、还多一条
# 「转不动就整本进不来」的失败路径。分章仍在阅读时按 core/detect.py 现算。
EBOOK_EXT = {".epub", ".mobi", ".azw3", ".pdf", ".fb2", ".cbz", ".cbr",
             ".txt", *audio.AUDIO_EXTS}


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


def _guard(out_dir: Path, target: Path) -> None:
    """落盘前的跨库同名闸门（第 13 期）。

    延迟导入 ``library_rules``：pipeline 在 core 内部被广泛引用，顶层导入会
    增加循环依赖风险；这里只在真正要写盘时付出一次导入成本（之后命中 sys.modules）。
    """
    from . import library_rules
    try:
        rel = target.relative_to(out_dir).as_posix()
    except ValueError:                                  # 理论上不会发生，防御性放行
        return
    library_rules.guard_conflict(out_dir, rel)


def _emit(base_meta: dict, chapters: list, out_dir: Path, opts: dict) -> Path:
    """产出成品：EPUB。

    - **EPUB 始终生成**：在线阅读（library.chapter_html）只支持 EPUB，是阅读基础。
    - **落盘位置**由 ``output.layout`` 决定：komga 布局下有系列的书进
      ``系列名/系列名 #N.epub``（见 core/komga.py）；无系列仍旧平铺 ——
      转换出来的书**没有系列元数据**（epub_builder 不写 series），
      所以这里只能从书名推断，判不出就老实平铺。
    - 返回交付物路径。

    第 62 期删掉了「再按 ``output.format`` 用 Calibre 派生 MOBI / AZW3」那一段：
    派生格式只有外部阅读器用得上，而它的产物不进书目（``library`` 只读 EPUB 章节树），
    却要为此常驻一条可选外部依赖 + 一套降级提示。``output.format`` 因此只剩 ``epub``。
    """
    title = base_meta.get("title") or "untitled"
    cfg = opts.get("cfg") or {}
    series, index = komga.infer(
        title, base_meta.get("series", ""), base_meta.get("series_index", "")
    )
    epub = _place(out_dir, title, "epub", series, index, cfg)
    if epub.exists() and not opts.get("force"):
        return epub
    # 跨库同名闸门：名字到这里才最终确定（Komga 布局下带系列前缀），必须在此判定
    _guard(out_dir, epub)
    epub_builder.build_epub(base_meta, chapters, str(epub))
    opts["_notice"] = ""
    return epub


#: 打分只看这些字符（判据是「解出来像不像人话」）：
#: 常用汉字（U+4E00–U+9FFF）、中日韩标点（U+3000–U+303F）、全角符号（U+FF00–U+FFEF）。
_OK_RANGES = ((0x4E00, 0x9FFF), (0x3000, 0x303F), (0xFF00, 0xFFEF))
#: 罕见字块（扩展 A / 私用区 / 扩展 B 及以上）—— 真文本里几乎不出现，解错则成片出现。
_RARE_RANGES = ((0x3400, 0x4DBF), (0xE000, 0xF8FF), (0x20000, 0x2FA1F))

#: 中文标点：**这是最有力的判据**。GBK 与 Big5 把同一个标点编码在完全不同的字节上
#: （「，」GBK 是 A3AC、Big5 是 A141），所以拿错编码解出来的那一片全是怪符号，
#: 而两种编码解出的汉字都落在常用区、光看汉字分不出来。
_PUNCT = set("，。、；：？！“”‘’（）《》〈〉「」『』【】…—～·,.!?;:\"'()[]<>-")
#: 极高频汉字：正确解码下密集出现，错解下几乎不出现（与标点互为补充）。
_HOT = set("的一是了我不人在他有这那说着就都而及与和也你我们不是到时大地为子中你想上去来"
           "里年小么出能好下过面天心二三月四五六七八九十")


def _score_text(text: str) -> float:
    """一段候选解码的「像人话」得分（越大越像，负分基本可以断定解错了）。"""
    ok = rare = 0
    for ch in text:
        o = ord(ch)
        if any(lo <= o <= hi for lo, hi in _RARE_RANGES):
            rare += 1
        elif any(lo <= o <= hi for lo, hi in _OK_RANGES):
            ok += 1
        elif ch in _PUNCT or ch in _HOT:
            ok += 1
    total = len(text) or 1
    # 标点与高频字权重大：它们在错解里会成片消失，而「罕见字块」在错解里会成片出现。
    hits = sum(1 for ch in text if ch in _PUNCT or ch in _HOT)
    return (ok + hits * 3 - rare * 8) / total


def _sample_bytes(path: Path) -> bytes:
    """取一段用于判编码的样本：开头 256 KB；若它全是 ASCII 再补中段（见下）。"""
    head = 256 * 1024
    with open(path, "rb") as f:
        data = f.read(head)
        # 纯 ASCII 的开头（英文前言 / 版权页）判不出中文编码 —— 补一段中段再看。
        # 中段也是纯 ASCII 时**读全文**：宁可多读一次，也不把整本 GBK 判成 UTF-8
        # （错判的代价是满屏乱码，而它不会报错）。
        if data and max(data) < 0x80:
            try:
                size = path.stat().st_size
            except OSError:
                return data
            if size > head:
                f.seek(size // 2)
                more = f.read(64 * 1024)
                if more and max(more) < 0x80:
                    f.seek(0)
                    return f.read()
                return data + more
        return data


def _detect_encoding(path: Path) -> str:
    """探测文本编码 —— **按「解出来像不像人话」择优**，不靠「能解码就算」。

    ⚠️ 老实现是 ``for enc in ("utf-8-sig","utf-8","gb18030","gbk","big5")`` 逐个
    ``read_text`` 试，第一个不抛异常的胜出。那条链上 **``big5`` 是死分支**：
    GB18030 能解码绝大多数 Big5 字节序列而不抛异常，于是繁体书被判成 GB18030、
    解出一整本乱码却「成功」—— 调用方还叠加 ``errors="ignore"``，连失败兜底都不触发。
    读者看到的是满屏怪字，而不是「这本书打不开」。（大数据量的正确做法是装 chardet /
    charset-normalizer，本项目**不引第三方依赖**，所以用字符分布判据自己判。）

    ``utf-8`` 仍然先试：它是**自证**的（非 UTF-8 字节几乎必然解失败），没有误判空间。
    剩下的 GB18030 与 Big5 都能解汉字，才需要按标点 / 高频字 / 罕见字块算分择优。
    """
    data = _sample_bytes(path)
    if not data:
        return "utf-8"
    try:
        data.decode("utf-8-sig")               # ``utf-8-sig`` 兼容无 BOM 的输入，
        # 所以「解得开」不等于「有 BOM」—— 回报的名字要如实：**有 BOM 才报 utf-8-sig**
        # （两种编码读出来的文本都正确，区别只在开头那个 U+FEFF 会不会被吃掉）。
        return "utf-8-sig" if data.startswith(codecs.BOM_UTF8) else "utf-8"
    except Exception:                          # noqa: BLE001 —— 不是 UTF-8，往下按分布判
        pass
    best, best_score = "utf-8", float("-inf")
    for enc in ("gb18030", "big5hkscs", "big5"):
        try:
            text = data.decode(enc, "replace")
        except Exception:                                  # noqa: BLE001
            continue
        s = _score_text(text)
        if s > best_score:
            best, best_score = enc, s
    return best


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
    """文件分发：电子书 / 漫画 / 音频 / **TXT** 直接复制入库，其余跳过。

    复制路径同样遵循 ``output.layout``：这类文件（外部 EPUB / 漫画 CBZ·CBR / TXT）没有
    ``calibre:series`` 可读的解析环节，系列只能从**文件名**推断（见 core/komga.py）——
    这正是把漫画喂给 Komga 的主要场景。

    **目录**（含音频）整树复制为一本书目目录：有声书「一章一文件」就靠这条路径入库。

    ⚠️ 第 62 期：``.txt`` 不再走 ``convert_txt``（转成 EPUB 落 output），改为与 EPUB / PDF
    同路的**原样复制**。理由：阅读链路本来就不看 output 里的那份 EPUB，而是走
    ``txtcache`` 的派生缓存（按需生成、带源指纹、规则变了自动重建），入库时再转一份是
    重复劳动；更糟的是它多出一条失败路径 —— 转不动（超大 / 编码坏）的 TXT **整本进不来**，
    而现在无论多大、编码多怪都能入库并在线阅读。``convert_text`` 本身**保留**：
    书源下载拿到的正文没有磁盘文件，仍要靠它生成 EPUB。
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
        _guard(out_dir, target)
        _copy_tree(src, target)
        return ("copy", target)
    if src.suffix.lower() in EBOOK_EXT:
        cfg = opts.get("cfg") or {}
        # 上传/下载链路可能已带显式元数据（如书源给的系列名），优先采信它
        meta = opts.get("meta") or {}
        series, index = komga.infer(
            src.stem, meta.get("series", ""), meta.get("series_index", "")
        )
        target = _place(out_dir, src.stem, src.suffix.lstrip("."), series, index, cfg)
        _guard(out_dir, target)
        shutil.copy2(src, target)
        return ("copy", target)
    return ("skip", src)
