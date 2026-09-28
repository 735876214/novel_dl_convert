"""分章判据的**唯一真值源**（第 55 期起明确）。

「正文 → 章节列表」只有这一处实现：转换管线（`core/pipeline.py`）、书源
（`sources/*`）、AI 兜底（`core/ai_detect.py` 复用本模块的 bounds/split）与
原生 TXT 阅读器全部经此。改这里 = 同时改出版成品目录与阅读器章节流，
所以契约由 `tests/test_detect_chapters.py` 钉住，别在别处再写第二份切分。

**第 62 期两处口径变化**（都在 `CHAPTER_RULE_VERSION` 里记了一笔）：

1. **行首锚定**：所有模式都要求标记落在**行首**（允许行首空白，但不跨行）。
   此前「第 N 章」在正文段落中间照样算边界，于是正文里提一句「第 3 章讲过」
   就把段落切成了两章 —— 目录凭空多出条目，且正文被拦腰截断。
2. **补模式**：卷单独成行 / `卷一 起风` / `【第1章】` / `（一）` / 全角句点 `1．风`，
   并把 `序章|楔子|番外` 一类从「只捕获标记本身」改成**捕获整行**
   （`番外一 开始` 原先只拿到「番外」，「一 开始」被丢掉）。

**第 72 期三处口径变化**（同样记进 `CHAPTER_RULE_VERSION`）：

1. **置信判据加绝对条数兜底**（:func:`regex_confident`）：密度判据单独用会**误杀长章书** ——
   一本 25 章、平均 15k 字/章的书只有 25 个边界，`25×2000 < 373,187` 被判「正则无效」，
   明明边界条条属实却被丢掉。
2. **降级产物为空时回退正则边界**：缩进降级**一章正文都没读出来**（全顶格文本恒如此）时，
   宁可回到正则边界 —— 几个真边界好过 N 个空正文的假章。
3. **缩进降级认全角空格**：与 `_LEAD`（正则锚定那边，`[ \t　]*`）口径对齐。中文文本用
   全角空格缩进是常态，只认半角会把**每一段**都当成新章首。
"""
import re

#: 分章**规则版本号**：规则一改就 +1。``core/txtcache.py`` 把它写进派生缓存的指纹 ——
#: 否则存量 TXT 书的派生 EPUB 会一直沿用旧目录，改了规则**看不见效果**（缓存命中就返回，
#: 不会重切）；版本号一变即触发重建，活动日志里也留得下痕迹。
#: 第 72 期 +1：置信判据加绝对条数兜底、降级产物为空时回退正则、缩进降级认全角空格。
CHAPTER_RULE_VERSION = 3

#: 行首锚定：允许行首的行内空白（**含全角空格**，中文文本常用它缩进），但用
#: ``[ \t　]*`` 而**不是** ``\s*`` —— 后者能吃掉换行，等于没锚定（``^`` 从上一行
#: 行首起步、一路吃过空行再命中下一行的 `第`，起点也落在错误的位置上）。
_LEAD = r"^[ \t　]*"
#: 行尾（允许行尾空白与 CRLF 的 ``\r``：读盘时通用换行会吃掉它，但书源给的正文不会）
_END = r"[ \t　]*\r?$"
_SP = r"[ \t　]*"
_NUM = r"[零一二三四五六七八九十百千万亿两0-9]+"
_CHAP_UNIT = r"[章节回话集幕篇]"
_VOL_UNIT = r"[卷部]"
#: 卷标题 / 括号标题允许的**附加文字上限**：真正的标题行是短行，长段落不是。
#: 上限之外一律不认 —— 宁可漏一个标题，也不要让正文段落被误判成卷首。
_TITLE_MAX = 20
#: 卷首的两种写法：**数字在「卷/部」之前**（第一卷 / 第二部）与**在「卷」之后**（卷一）。
#: 两者都得列，不能写成「第?数字卷」—— ``第?`` 取空以后 ``_NUM`` 要去匹配「卷」，
#: 那是字符集外的字，整条模式在这个位置上直接失败（``卷一 起风`` 就是这么漏掉的）。
_VOL_HEAD = rf"(?:第{_SP}{_NUM}{_SP}{_VOL_UNIT}|卷{_SP}{_NUM})"
#: 卷首后面跟的标题：必须有**真分隔符**（分隔号或至少一个空格）。否则
#: 「一部分……」「第一卷的内容……」这类普通句子会被整行判成卷首。
_VOL_TAIL = rf"(?:[：:、\-——]{_SP}[^\n]{{1,{_TITLE_MAX}}}|[ \t　]+[^\n]{{1,{_TITLE_MAX}}})?"

# 多正则：覆盖常见章节标记（中文数字/阿拉伯/No./Chapter/序章番外等）
CHAPTER_PATTERNS = [
    # 卷 + 章 一行写全：第二卷 第三章 / 第二卷：第三章
    re.compile(_LEAD + rf"第{_SP}{_NUM}{_SP}{_VOL_UNIT}{_SP}[：:、]{_SP}第{_SP}{_NUM}{_SP}{_CHAP_UNIT}", re.M),
    # 第N章 / 第N回 / 第N节 …（**行首**）
    re.compile(_LEAD + rf"第{_SP}{_NUM}{_SP}{_CHAP_UNIT}", re.M),
    # 卷单独成行：第一卷 / 第二部 / 卷一 起风 / 第二部：风起
    re.compile(_LEAD + _VOL_HEAD + _VOL_TAIL + _END, re.M),
    # 括号形式：【第1章】/ [第三章] / （十二）
    re.compile(_LEAD + rf"[【\[（(]{_SP}第{_SP}{_NUM}{_SP}{_CHAP_UNIT}{_SP}[】\]）)]", re.M),
    # （一）这种整行括号数字：**只认中文数字** —— 「（1）」在正文里更像列表项 / 脚注编号，
    # 认它得不偿失（漏掉的「（1）」正文多半另有「第一章」可切）。
    re.compile(_LEAD + r"[（(]" + _SP + r"[零一二三四五六七八九十百千万亿两]+" + _SP
               + r"[）)][^\n]{0,12}" + _END, re.M),
    re.compile(_LEAD + r"No[、.．]" + _SP + r"\d+" + _SP + r".+", re.M),
    re.compile(_LEAD + r"Chapter" + _SP + r"\d+", re.M | re.I),
    # 序章 / 楔子 / 引子 / 前言 / 后记 / 番外 / 尾声：**捕获整行**（此前只捕获标记本身，
    # `番外一 开始` 的「一 开始」会被丢掉）。代价是「番外」开头且整行 ≤24 字的正文行
    # 会被误判成章首，而标题超过 24 字的真章首会被漏掉 —— 两头都罕见，比丢字强。
    re.compile(_LEAD + rf"(?:序章|序言|楔子|引子|前言|后记|后記|尾声|终章|番外)"
               rf"[^\n]{{0,{_TITLE_MAX}}}{_END}", re.M),
    re.compile(_LEAD + r"[0-9]+" + _SP + r"[\.、．·]" + _SP + r".+", re.M),
    re.compile(_LEAD + r"[一二三四五六七八九十]+" + _SP + r"[\.、．·]" + _SP + r".+", re.M),
]
#: :func:`_is_volume` 用的锚定版（``re.match`` 自带行首锚定，不需要 ``re.M``）
_VOL_HEAD_RE = re.compile(_VOL_HEAD)
# 仅当章节正文短于此值时才并入上一章（避免吞掉真实短章），默认不合并由调用方控制
MERGE_MIN_LEN = 20


def regex_bounds(text: str) -> list[tuple[int, str]]:
    """返回正则命中的 (字符偏移, 标题) 列表，已按偏移排序去重。

    去重口径：**同一个起点只留一个边界，取标题更长的那个**。同一个位置被两条模式
    同时命中是常态（``第二卷 第三章 风起`` 既被「卷+章」命中、又被「卷单独成行」
    整行命中），留下两个同偏移的边界会在 :func:`split_by_offsets` 里切出一个
    正文为空的假章（``text[pos:pos]``）。
    """
    best: dict[int, str] = {}
    for p in CHAPTER_PATTERNS:
        for m in p.finditer(text):
            title = m.group(0).strip()
            if not title:
                continue
            cur = best.get(m.start())
            if cur is None or len(title) > len(cur):
                best[m.start()] = title
    return sorted(best.items())


def _is_volume(title: str) -> bool:
    """这条边界是不是**卷首**（决定 ``vol`` 字段，供阅读器/成品做卷分组）。

    第 62 期放宽了两处：① ``卷一 起风`` 这种数字在后的写法此前不认；
    ② ``第.+[卷部]`` 的 ``.+`` 贪婪又要求**以**卷/部收尾，于是「第二卷 第一章」
    这种「卷+章写在一行」的写法反而不算卷首 —— 改成**前缀匹配**。
    """
    return bool(_VOL_HEAD_RE.match(title))


def split_by_offsets(text: str, bounds: list[tuple[int, str]], merge: bool = False) -> list[dict]:
    """按 (偏移, 标题) 切分正文为章节；带卷/章层级。

    边界 (pos_i, title_i) 表示 title_i 在文本中的位置；title_i 的正文是
    [pos_i, pos_{i+1})，末章正文为 [pos_n, 文末)。

    ⚠️ **首个边界之前的内容（书名 / 作者行）会被丢弃**，不并入首章 ——
    这是实现的实际行为（首章 body 在下一轮循环里被 [pos_0, pos_1) 覆写）；
    此前注释写「作为前言并入首章正文」，与实现不符，第 55 期按实际行为订正。
    契约由 `tests/test_detect_chapters.py` 钉住（改它是改出版成品，别顺手改）。

    merge=True 时按 MERGE_MIN_LEN 合并极小碎片章。
    """
    chaps, start = [], 0
    for i, (pos, title) in enumerate(bounds):
        vol = title if _is_volume(title) else "正文"
        if i == 0:
            # 首个章节标题之前的内容（书名/作者等）作为首章前置，不单独成章
            chaps.append({"title": title, "body": text[:pos].strip(), "vol": vol})
        else:
            # 上一章（chaps[-1]）的正文 = 上一章标题位置到本章标题位置
            chaps[-1]["body"] = text[start:pos].strip()
            chaps.append({"title": title, "body": "", "vol": vol})
        start = pos
    # 末章正文 = 最后一个标题位置到文本末尾
    if chaps:
        chaps[-1]["body"] = text[start:].strip()
    return _merge_small(chaps) if merge else chaps


def regex_confident(bounds: list[tuple[int, str]], text: str) -> bool:
    """正则边界是否可信：**密度**（平均 ≤2000 字/章）**或** 绝对条数（≥3 条）。

    密度判据单独用会把**长章书**误判成「没有章节」：一本 25 章、平均 15k 字/章的书
    只有 25 个边界，``25 × 2000 = 50,000 < 373,187`` ⇒ 判「正则无效」⇒ 退化缩进切分
    ⇒ 3723 个空正文假章（实测）。长章不是「命中太少」，所以补一条绝对条数兜底：
    行首锚定之后，3 条以上行首章标记基本不可能是巧合。

    **公开名**：它有两个消费者 —— :func:`detect_chapters`（决定用不用缩进降级）与
    ``core/ai_detect.HybridChapterDetector``（决定要不要花钱调 LLM）。第 72 期把后者
    里那份 ``len(bounds) * 2000 >= len(text)`` 的**第二份拷贝**收敛到这里
    （AGENTS.md：同一判据只许有一处实现），所以它不再是一个模块内部的细节。
    """
    return len(bounds) >= 3 or len(bounds) * 2000 >= len(text)


def detect_chapters(text: str, merge: bool = False) -> list[dict]:
    """章节识别：正则优先，命中率不足时退化为缩进切分。

    降级后若**一章正文都没读出来**（全顶格文本必然如此：顶格行全成了章标题、没有
    缩进行当正文），而正则**有**边界，就回到正则边界 —— 几个真边界好过 N 个空正文的
    假章（那种目录在阅读器里表现为「满屏标题、点进去没有正文」）。
    """
    bounds = regex_bounds(text)
    if bounds and regex_confident(bounds, text):  # 正则有效
        return split_by_offsets(text, bounds, merge)
    chaps = _split_by_indent(text)  # 缩进降级
    if bounds and not any((c.get("body") or "").strip() for c in chaps):
        return split_by_offsets(text, bounds, merge)
    return chaps


def detect_chapters_cfg(text: str, cfg: dict | None = None, merge: bool | None = None) -> list[dict]:
    """带配置的入口：hybrid/ai 且配置了 llm 时交由 AI 检测器，否则走正则。

    merge 控制是否合并极小碎片章；为 None 时默认不合并（由 CLI --merge 显式开启）。
    """
    cfg = cfg or {}
    cd = cfg.get("chapter_detection", {}) or {}
    mode = cd.get("mode", "hybrid")
    llm = cfg.get("llm", {}) or {}
    do_merge = bool(merge)
    if mode in ("ai", "hybrid") and llm.get("api_key"):
        from .ai_detect import HybridChapterDetector, _run_in_thread

        detector = HybridChapterDetector(cfg)
        # 在独立线程跑新事件循环，兼容 CLI（同步）与 Web 服务（已有运行中的 loop）；
        # 直接 asyncio.run 在事件中 loop 的线程会抛 RuntimeError，导致 AI 兜底静默失效。
        try:
            return _run_in_thread(detector.detect(text))
        except Exception:
            if cd.get("fallback", "regex") == "regex":
                return detect_chapters(text, do_merge)
            raise
    return detect_chapters(text, do_merge)


def _split_by_indent(text: str) -> list[dict]:
    """缩进降级：顶格行 = 章标题，其下的缩进行 = 该章正文。

    ⚠️ 缩进字符集必须与 `_LEAD`（正则锚定那边）**一致**：全角空格 `　` 也是缩进。
    只认半角时，用全角缩进的中文文本会被切成「一段一章、正文全空」（第 72 期实测）。
    """
    chaps, cur = [], None
    for ln in text.splitlines():
        if ln[:1] in (" ", "\t", "　") or not ln.strip():
            if cur is not None:
                cur["body"] += "\n" + ln
        else:
            if cur:
                chaps.append(cur)
            cur = {"title": ln.strip(), "body": "", "vol": "正文"}
    if cur:
        chaps.append(cur)
    for c in chaps:
        c["body"] = c["body"].strip()
    return chaps


def _merge_small(chaps: list[dict]) -> list[dict]:
    out = []
    for c in chaps:
        if out and len(c["body"]) < MERGE_MIN_LEN:
            out[-1]["body"] += "\n" + c["title"] + "\n" + c["body"]
        else:
            out.append(c)
    return out
