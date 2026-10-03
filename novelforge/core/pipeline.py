import codecs
import shutil
from pathlib import Path

from . import audio, preprocess, detect, metadata, epub_builder, komga

# 已是电子书格式的文件直接复制（含漫画归档与**单个**音频文件；
# 「音频目录」形态由 dispatch 的目录分支单独处理）
# 第 62 期起含 ``.txt``：TXT **只入库不转换** —— 阅读链路本来就走「派生 EPUB 缓存」
# （见 core/txtcache.py），再在入库时转一份落到 output 只是白占一份空间、还多一条
# 「转不动就整本进不来」的失败路径。分章仍在阅读时按 core/detect.py 现算。
# 第 87 期：`.zip` 也在列 —— 它是**通用容器**，与 `.cbz` 走同一条「原样入库」的路；
# 入库后由扫描侧按**内容**分派形态（`core/zipkind.py`），不看后缀猜。
EBOOK_EXT = {".epub", ".mobi", ".azw3", ".pdf", ".fb2", ".cbz", ".cbr", ".zip",
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


#: 编码判据的采样窗口（字节）：开头取这么多；纯 ASCII 开头时再补一段中段。
_SAMPLE_HEAD = 256 * 1024
_SAMPLE_MID = 64 * 1024


def _read_from_char_boundary(f, offset: int, n: int) -> bytes:
    """从 ``offset`` 起读 ``n`` 字节，并让**起点落在字符边界**上。

    ⚠️ 中段起点 ``size // 2`` 是按字节算的，多半落在某个多字节字符**中间**。两段样本
    直接拼接时，接缝处那个续字节（``0x80–0xBF``）**不能当字符的开头** —— 而前缀判定
    只容忍**尾部**不完整、接缝在中间 ⇒ 照样抛错 ⇒ 一本真 UTF-8 的书被判成
    gb18030 / big5（实测：ASCII 前言 + 中文正文的书就中这一枪，与头部截断同因同果）。

    对齐两步：① 窗口内先找换行 —— ``0x0A`` 在 UTF-8 / GBK / Big5 里都**不可能**做后继
    字节，换行之后必然是字符边界；② 附近没有换行时跳过开头的续字节。
    """
    f.seek(offset)
    probe = f.read(4096)
    nl = probe.find(b"\n")
    if nl >= 0:
        f.seek(offset + nl + 1)
    else:
        skip = 0
        while skip < len(probe) and 0x80 <= probe[skip] <= 0xBF:
            skip += 1
        f.seek(offset + skip)
    return f.read(n)


def _sample_bytes(path: Path) -> bytes:
    """取一段用于判编码的样本：开头 256 KB；若它全是 ASCII 再补中段（见下）。"""
    with open(path, "rb") as f:
        data = f.read(_SAMPLE_HEAD)
        if not data or max(data) >= 0x80:
            return data
        # 纯 ASCII 的开头（英文前言 / 版权页）判不出中文编码 —— 补一段中段再看。
        # 中段也是纯 ASCII 时**读全文**：宁可多读一次，也不把整本 GBK 判成 UTF-8
        # （错判的代价是满屏乱码，而它不会报错）。
        try:
            size = path.stat().st_size
        except OSError:
            return data
        if size <= _SAMPLE_HEAD:
            return data
        # ``data`` 全是 ASCII ⇒ 尾部必然是字符边界（ASCII 字节不可能是多字节字符的一部分），
        # 所以只需把**中段起点**对齐，接缝两侧就都落在边界上。
        more = _read_from_char_boundary(f, size // 2, _SAMPLE_MID)
        if not more or max(more) < 0x80:
            f.seek(0)
            return f.read()
        return data + more


#: 编码探测**判据的版本号**：判据一改就 +1（与 `detect.CHAPTER_RULE_VERSION` 同理）。
#: `core/txtcache.py` 把它写进派生缓存的 state 与内存缓存键，`server.py` 的章节读缓存
#: 也带上它 —— 否则「判据改了、源文件一个字节没动」时，已缓存的正文（可能是乱码）
#: 会一直命中，**改了看不见效果**。
#:
#: 第 89 期 +1（1 → 2）：判据从「能解码就算（叠加 errors=\"ignore\"）」改为
#: 「BOM 确定性优先 + 候选逐个**严格**试解 + 不允许静默丢字节」。存量派生件（可能是
#: 旧判据解出的乱码 / 有洞的正文）必须**重建**，否则用户改完代码看到的还是老样子。
ENCODING_RULE_VERSION = 2


def _utf8_prefix_ok(data: bytes) -> bool:
    """``data`` 是否**可能是一段 UTF-8 的开头**。

    ⚠️ 样本是**按字节切**的（见 :func:`_sample_bytes`），末尾可能切在多字节字符中间 ——
    「尾部被切断」不构成「这不是 UTF-8」的证据。老实现直接 ``data.decode("utf-8-sig")``，
    于是**切点落在续字节的文件整本被判成 GB18030**：本机一本 1.1 MB 的中文 TXT 正好切在
    一个 3 字节字符的最后一字节之前（错位 262142-262143），整本解成乱码且**全程不报错**。
    （UTF-8 汉字 3 字节 ⇒ 任意切点有 2/3 概率落在字符中间，>256 KiB 的中文 TXT 成片中招。）

    改用**增量解码器**问「除尾部不完整序列外，是否全都合法」：尾部那段不完整序列被它
    暂存，不算错；而**中间**任何坏字节照旧抛错 —— 真 GBK / Big5 样本实测仍判 ``False``，
    容错没有放宽到「差不多就行」。解码器是**有状态**的，每次必须新建实例。
    """
    try:
        codecs.getincrementaldecoder("utf-8")().decode(data, final=False)
        return True
    except UnicodeDecodeError:
        return False


#: 无 BOM 判 UTF-16 时采样的字节窗口（足够看出 ASCII 的奇偶零字节分布，又不必读整篇）。
_UTF16_PROBE = 4096


def _looks_utf16(data: bytes) -> "str | None":
    """无 BOM 时判断「整篇是不是 UTF-16」——**明确判据**，不含糊、不猜。

    ⚠️ **刻意不覆盖「纯中文的无 BOM UTF-16」**：例如「中」= U+4E2D，两个字节都不是
    0x00，与随机字节无从区分 —— 那属于「不可判」，宁可交给下面的启发式并**如实报告**
    解出的编码与坏字节数，也不在这里硬猜一个。这里覆盖的是**含大量 ASCII** 的 UTF-16：
    英文书名 / 版权页 / 数字 / 标点 / 空格、乃至中英混排的书里 ASCII 占比往往很高，而
    ASCII 码位 < 0x80 ⇒ UTF-16LE 下**奇数位恒为 0x00**、UTF-16BE 下**偶数位恒为 0x00**，
    这是很强的结构信号（GB18030 / Big5 的正文里 0x00 根本不出现 —— 它是控制字符）。

    判据（只看开头 4 KB）：某一奇偶位上的 0x00 占比 ≥ 40%，且另一奇偶位 < 5%
    ⇒ 判为该字节序，返回 ``"utf-16-le"`` / ``"utf-16-be"``；否则返回 ``None``。
    返回显式字节序（而不是 ``"utf-16"``）：无 BOM 的 ``"utf-16"`` 解码器会按**本机**
    字节序解，是平台相关的行为，必须避免。
    """
    head = data[:_UTF16_PROBE]
    n = len(head) - (len(head) % 2)
    if n < 8:
        return None
    pairs = n // 2
    even_zero = sum(1 for i in range(0, n, 2) if head[i] == 0)
    odd_zero = sum(1 for i in range(1, n, 2) if head[i] == 0)
    if odd_zero / pairs >= 0.4 and even_zero / pairs < 0.05:
        return "utf-16-le"
    if even_zero / pairs >= 0.4 and odd_zero / pairs < 0.05:
        return "utf-16-be"
    return None


def _choose_encoding(data: bytes) -> "list[str]":
    """按**候选顺序**给出可能的编码（最可能在前），供 :func:`decode_file` 逐个严格试解。

    顺序的由来（**确定性证据优先于启发式猜测**，这是本期的第一原则）：

    1. **BOM** —— 由写出方显式写下，不含概率、判错概率为零 ⇒ 最高优先级。
       ``EF BB BF`` → UTF-8；``FF FE`` / ``FE FF`` → UTF-16；``FF FE 00 00`` /
       ``00 00 FE FF`` → UTF-32（先判，免得被当成 UTF-16 解坏）。
       ⚠️ **为什么 BOM 必须凌驾于启发式**：UTF-16LE 的开头 ``FF FE`` 不是合法 UTF-8
       ⇒ 没有这一步时会落到下面的 gb18030 打分，而 gb18030 几乎「总能解码成功」⇒
       **整本乱码且不报错**。BOM 是唯一能确定字节序、不依赖内容的证据。
    2. **无 BOM 但整篇像 UTF-16**（见 :func:`_looks_utf16`，判据明确）。
    3. **UTF-8 前缀合法** —— UTF-8 是**自证**的（非 UTF-8 字节几乎必然解失败），且
       `_sample_bytes` 会一直读到「有非 ASCII」为止 ⇒ 前缀合法 ≈ 真 UTF-8。只回一个
       候选：样本按字节切、尾部可能不完整，但**整篇**若真是 UTF-8 必能严格解出；万一
       夹了坏字节，也应当以 U+FFFD **就地占位**（见 :func:`decode_file`），而不是改判成
       gb18030 把整篇搅乱。
    4. 否则在 ``gb18030`` / ``big5hkscs`` / ``big5`` 里按「解出来像不像人话」打分排序
       —— 这两种编码都能解汉字，光看「能不能解码」分不出来，才需要标点 / 高频字 /
       罕见字块的分布判据。（本项目**不引第三方依赖**，所以自己算分，不用 chardet。）
    """
    if data.startswith(codecs.BOM_UTF32_LE) or data.startswith(codecs.BOM_UTF32_BE):
        return ["utf-32"]
    if data.startswith(codecs.BOM_UTF8):
        return ["utf-8-sig"]
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return ["utf-16"]
    guess = _looks_utf16(data)
    if guess is not None:
        return [guess]
    if _utf8_prefix_ok(data):
        return ["utf-8"]
    scored: "list[tuple[str, float]]" = []
    for enc in ("gb18030", "big5hkscs", "big5"):
        try:
            scored.append((enc, _score_text(data.decode(enc, "replace"))))
        except Exception:                                  # noqa: BLE001
            continue
    if not scored:
        return ["utf-8"]
    # 稳定排序：同分时保留 `("gb18030", "big5hkscs", "big5")` 的原始次序
    # （与旧实现的「严格大于才换」等价）。
    scored.sort(key=lambda kv: kv[1], reverse=True)
    return [enc for enc, _ in scored]


def _detect_encoding(path: Path) -> str:
    """探测文本编码 —— 返回**首选候选**的名字（见 :func:`_choose_encoding` 的判据与顺序）。

    ⚠️ 这**不是**「随便找个能解码的」。老实现是逐个 ``read_text`` 试、第一个不抛异常的
    胜出，那条链上 **``big5`` 是死分支**：GB18030 能解码绝大多数 Big5 字节序列而不抛异常
    ⇒ 繁体书被判成 GB18030、解出一整本乱码却「成功」，调用方再叠加 ``errors="ignore"``
    连失败兜底都不触发。现在的判据是「确定性证据（BOM / 自证）优先，其余按像不像人话打分」。

    需要「绝不静默丢字节」的**读全文**路径请用 :func:`decode_file` —— 它拿本函数的
    候选顺序去逐个**严格**试解，并在都不干净时如实上报坏字节数。本函数保留给
    「只想知道是哪个编码」的调用方（既有测试等都走它）。
    """
    data = _sample_bytes(path)
    if not data:
        return "utf-8"
    return _choose_encoding(data)[0]


def _decode_count(data: bytes, enc: str) -> "tuple[str, int, list[int]]":
    """严格解码；解不出的字节以 U+FFFD **替上**（不是丢掉），并数出丢了多少、丢在哪。

    返回 ``(文本, 坏字节数, 前若干坏字节的起始偏移)``；全部解出时是 ``(文本, 0, [])``。
    """
    # ``utf-16`` 解码器靠**开头的 BOM** 定字节序；逐段试解时 BOM 不在段首就会按本机
    # 字节序解错 ⇒ 先落成显式字节序并去掉 BOM（BOM 必在开头，由 `_choose_encoding` 认出）。
    if enc == "utf-16":
        if data.startswith(codecs.BOM_UTF16_BE):
            enc, data = "utf-16-be", data[2:]
        else:
            enc, data = "utf-16-le", data[2:]
    try:
        return data.decode(enc), 0, []
    except UnicodeDecodeError:
        pass
    out: "list[str]" = []
    bad = 0
    positions: "list[int]" = []
    pos, total = 0, len(data)
    while pos < total:
        try:
            out.append(data[pos:].decode(enc))
            break
        except UnicodeDecodeError as e:
            # ``e.start`` / ``e.end`` 是**相对 `data[pos:]`** 的偏移 ⇒ 坏段在**绝对坐标**
            # 上是 ``[pos + e.start, pos + e.end)``；下一轮从 ``pos + e.end`` 续解
            #（写成「加 e.end - e.start」会让 pos 几乎不动、把同一段正文反复追加 —— 实测过）。
            if e.start:
                out.append(data[pos:pos + e.start].decode(enc))
            out.append("\ufffd")
            bad += max(1, e.end - e.start)
            if len(positions) < 16:
                positions.append(pos + e.start)
            nxt = pos + e.end
            pos = nxt if nxt > pos else pos + 1
    return "".join(out), bad, positions


def decode_file(path: Path) -> "tuple[str, dict]":
    """把文本文件**如实**读成字符串：确定性判据优先，且**绝不静默丢字节**。

    返回 ``(文本, 报告)``，报告字段：

    - ``encoding``：本次**实际使用**的编码（如实回报，不是「猜中的那个」）；
    - ``undecodable``：无法解码、只能以 U+FFFD 呈现的**字节数**（0 = 全部解出）；
    - ``positions``：前若干坏字节的**起始偏移**（封顶 16 个，仅供诊断）。

    ⚠️ **为什么不再用 ``errors="ignore"``**：ignore 会让解不出的字节**无声消失** ——
    一本主体合法、中间夹了几个坏字节的书（下载被截断 / 混合编码 / 尾巴混进二进制）读出来
    「像成功了」，实则正文少了几处、**位置全错**；更糟的是这个结果会写进**派生 EPUB**
    （`core/txtcache.py`）与章节缓存，读者拿到的是一份**有洞的派生物**却全程不报错。

    这里的口径：候选编码**逐个严格试解**，取第一个能无错解开的；若一个都做不到，就选
    「错得最少」的那个，坏字节以 U+FFFD 顶上**并计数上报**（`decode_info` → 章节接口 →
    阅读器提示）。**宁可让读者看到少量「�」，也不要一段悄悄变短、位置漂移的正文。**
    """
    data = path.read_bytes()
    empty = {"encoding": "utf-8", "undecodable": 0, "positions": []}
    if not data:
        return "", dict(empty)
    candidates = _choose_encoding(_sample_bytes(path) or data)
    for enc in candidates:
        try:
            return data.decode(enc), {**empty, "encoding": enc}
        except UnicodeDecodeError:
            continue
    # 一个都不干净：挑坏字节最少的那个，如实呈现 + 计数（不丢字节）。
    best_enc = candidates[0]
    best_bad: "int | None" = None
    best_text, best_pos = "", []
    for enc in candidates:
        text, bad, positions = _decode_count(data, enc)
        if best_bad is None or bad < best_bad:
            best_enc, best_bad, best_text, best_pos = enc, bad, text, positions
    return best_text, {"encoding": best_enc, "undecodable": int(best_bad or 0),
                       "positions": best_pos}


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
    # 第 89 期：不再 ``errors="ignore"``（那会让解不出的字节无声消失、位置全错）。
    # 改走 `decode_file`：候选逐个严格试解，读不干净就把坏字节数以 U+FFFD 呈现并计数，
    # 报告回传给调用方（`opts["_decode"]`）写进活动日志。
    raw, report = decode_file(path)
    opts["_decode"] = report
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
