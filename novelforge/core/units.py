"""序号单元（漫画 / 有声书「一话一文件」目录）：判据、清单与体积指纹。

**要解决的问题**（第 73 期）：漫画库 / 有声书库里，一本书的实际形态常常是

    根目录/《转生魔女宣告毁灭（1-43话）》/若干级文件夹/第1话.pdf
                                                  …/第二话.pdf
                                                  …/第03话.pdf
                                                  …/4 第4话.pdf

文件名里的序号写法**不统一**（阿拉伯 / 中文数字 / 前导零 / 前缀序号），而扫描层
按「一个文件 = 一本书」处理 ⇒ 书架上是 43 本各自独立的书（书名就是 `第1话`），
既看不出同属一本，也读不成连续的一话。`library._iter_book_entries` 里那句
「只下探一层」还让更深的文件**根本扫不到**。

本模块的判据：**一棵子树里有 ≥2 个能解析出序号的媒体文件 ⇒ 整棵树 = 一本书**，
「话」按序号排序。它同时修掉嵌套的**有声书**目录（`《书名》/第1卷/第1话.mp3`
此前会把 `第1卷` 当成一本书，书名就是「第1卷」）。

⚠️ **判据只许有一处实现**（AGENTS.md）：`library`（枚举 + 探测 + 增量闸门）、
`catalog`（索引与排序键）、`migrate`（搬家）、`server`（话清单与单话字节流）
**全部**读本模块，任何一处另写一套「什么算一话」都会让卡片数字与阅读器对不上。

⚠️ **与 `komga.infer` 是两套不同判据，刻意不合并**：那套（`core/komga.py`）解析的是
**系列名 + 册号**（`书名 - 第3卷`），要一个 ≥2 字的系列名；实测对 `第1话` / `4 第4话` /
`01` 一律返回空 —— 它服务的是「一本书属于哪个系列」，这里服务的是「哪些文件属于同一本
书的连续话」。两者目的一样、输入完全不同，硬凑成一处只会同时弄坏两边。

只做「读」：枚举与统计，不碰磁盘写入。
"""
import os
import pathlib
import re

from . import audio, comics

#: 序号单元的单位词（简繁并列）。**只有这些词**算「话」的单位 —— 这是「不过度合并」的第一道闸。
UNIT_WORDS = ("话", "話", "卷", "回", "册", "集", "部", "篇", "幕", "章")

#: 树内算「一话」的扩展名（**固定集合**，不随库白名单变 —— 理由见 `media_files`）。
#: 图片（`comics.IMAGE_EXTS`）**不在**其中：散图目录的渲染形态是另一件事，本期不做。
UNIT_EXTS = tuple(comics.COMIC_EXTS) + (".pdf",) + tuple(audio.AUDIO_EXTS)

#: 序号上界。超过它一律**不算**序号 —— 否则 `2024.pdf`（年份）、`第20240101话`
#: （日期）会被当成「第 2024 话 / 第 20240101 话」。
_MAX_UNIT = 999

#: 下探深度上限（「若干级文件夹」的实测深度 + 余量）。环路（符号链接）也靠它兜住。
_MAX_DEPTH = 4

#: 单棵树的媒体文件数上限。超限 ⇒ **整棵树不合并**（保守：宁可退回今天的行为，
#: 也不把一棵意外的大树吞成一本书）。
_MAX_FILES = 5000

#: 中文数字 → 值。含大写（壹贰叁…），扫描版文件名里两种都常见。
_CN_DIGITS = {
    "〇": 0, "零": 0, "一": 1, "壹": 1, "二": 2, "两": 2, "贰": 2, "貳": 2,
    "三": 3, "叁": 3, "参": 3, "四": 4, "肆": 4, "五": 5, "伍": 5, "六": 6, "陆": 6,
    "七": 7, "柒": 7, "八": 8, "捌": 8, "九": 9, "玖": 9,
}
_CN_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_CN_SMALL = {"廿": 20, "卅": 30, "卌": 40}

#: 数的部分：阿拉伯数字或中文数字（`十二` 这种带位值的也有）
_NUM = r"(?:\d{1,4}|[〇零一二三四五六七八九十百千两廿卅壹贰叁肆伍陆柒捌玖拾佰仟]{1,4})"
_WORDS = "|".join(UNIT_WORDS)

#: 形如 `第12话` / `第十二話` / `第03卷`：**单元标记必须在最前面**（这是「不过度合并」的
#: 第二道闸）。标记之后可以有内容（`第1话 番外` / `第01话 某标题` 都是常见写法）。
_MARK_RE = re.compile(rf"^第(?P<num>{_NUM})(?P<word>{_WORDS})")

#: 形如 `4 第4话` / `04-第4話`：**纯数字前缀 + 分隔符** + 上面的标记。
_PREFIX_MARK_RE = re.compile(rf"^(?P<pre>\d{{1,4}})[\s\-_.、]+(?P<rest>第(?P<num>{_NUM})(?P<word>{_WORDS}))")

#: 纯数字文件名（`01.pdf` / `007.cbz`）
_BARE_NUM_RE = re.compile(r"^\d{1,4}$")

#: 排「解析不出序号」的那些话用的键：它们一律排在**最后**，不猜位置。
#: 复用 `comics` 的实现（`audio` 里那份是**先前就存在**的同款实现，本期不新增第三份）。
_NATURAL_KEY = comics._natural_key
_INF = float("inf")


def cn_to_int(s) -> "int | None":
    """中文数字 / 阿拉伯数字 → 整数；不是数返回 ``None``。

    支持两类写法：**位值式**（`十二`=12、`二十三`=23、`一百零三`=103、`廿五`=25）
    与**逐位式**（`一〇一`=101 —— 全由数字字组成时按逐位拼）。
    """
    t = str(s or "").strip()
    if not t:
        return None
    if t.isdigit():                      # Python 的 isdigit 认全角数字，int() 也认
        try:
            return int(t)
        except ValueError:
            return None
    if all(ch in _CN_DIGITS for ch in t):
        return int("".join(str(_CN_DIGITS[ch]) for ch in t))
    total, cur = 0, 0
    for ch in t:
        if ch in _CN_DIGITS:
            cur = _CN_DIGITS[ch]
        elif ch in _CN_UNITS:
            total += (cur or 1) * _CN_UNITS[ch]     # `十二` = 十 后面没数 ⇒ 1×10
            cur = 0
        elif ch in _CN_SMALL:
            total += _CN_SMALL[ch]
            cur = 0
        else:
            return None
    return total + cur


def parse_unit(stem: str) -> "int | None":
    """文件名（不含扩展名）→ 序号；**不是序号返回 ``None``**。

    收三种形态，都要求标记在**开头**（前面只能有一个与其相等的纯数字前缀）：

    | 形态 | 例子 | 说明 |
    |---|---|---|
    | 单元标记 | `第12话` `第十二話` `第03卷` `第1话 番外` | 标记之后的内容不影响判定 |
    | 前缀序号 + 标记 | `4 第4话` `04-第4話` | 前缀必须**等于**单元号 |
    | 纯数字 | `01` `007` | `1 <= n <= _MAX_UNIT`，超界不算 |

    **刻意不收**（这就是「看着不像连载的目录不合并」的全部实现）：
    `《甲》(第1卷).cbz`（标记不在开头 —— 一个文件夹里几本独立漫画正是这个形状）、
    `作品名 第1话.pdf`（标题在前）、`第1-43话.pdf`（那是**范围**不是某一话）、
    `4x 第4话.pdf`（前缀不是纯数字）、`2024.pdf`（裸数字超界）、`vol.1.cbz`（不是中文单位词）。

    ⚠️ `4 第4话` 要求前缀**等于**号码：不一致说明那个前缀是别的东西
    （页数 / 批次 / 另一个编号体系），不是同一个序号体系的两处写法。
    """
    s = str(stem or "").strip()
    if not s:
        return None
    m = _PREFIX_MARK_RE.match(s)
    if m:
        num = cn_to_int(m.group("num"))
        pre = cn_to_int(m.group("pre"))
        if num and pre == num and 1 <= num <= _MAX_UNIT:
            return num
        return None
    m = _MARK_RE.match(s)
    if m:
        num = cn_to_int(m.group("num"))
        if num and 1 <= num <= _MAX_UNIT:
            return num
        return None
    if _BARE_NUM_RE.match(s):
        num = int(s)
        if 1 <= num <= _MAX_UNIT:
            return num
    return None


def is_unit_file(path) -> bool:
    """扩展名是不是「一话」的媒体类型（只看扩展名）。"""
    return pathlib.PurePath(str(path)).suffix.lower() in UNIT_EXTS


def kind_of(path) -> str:
    """这一话的形态：``"audio"`` / ``"comic"``（CBZ/CBR）/ ``"pdf"``；都不认识返回空串。

    阅读器据此选渲染方式（音频播放器 / 逐页看图 / pdf.js）。
    """
    ext = pathlib.PurePath(str(path)).suffix.lower()
    if ext in audio.AUDIO_EXTS:
        return "audio"
    if ext in comics.COMIC_EXTS:
        return "comic"
    if ext == ".pdf":
        return "pdf"
    return ""


def media_files(d, exts=None) -> "list | None":
    """树内**媒体**文件 ``[(Path, 相对树根的 posix 路径), ...]``，按遍历顺序。

    - 扩展名取 ``exts``（枚举侧传**该库的生效白名单**），缺省用固定的 :data:`UNIT_EXTS`；
    - 隐藏项（名字以 ``.`` 开头）一律跳过 —— 与 :func:`audio._audio_files` 同口径；
    - 下探深度 ≤ :data:`_MAX_DEPTH`；文件数 > :data:`_MAX_FILES` ⇒ 返回 ``None``
      （**超限与「空树」必须能区分**：前者要退回今天的行为，后者只是没东西）。

    ⚠️ **库级排除图案（`exclude`）刻意不在这里应用**：它的语义是「这些条目不进书目」，
    而一棵通过了单元判据的树**整棵就是一个条目** —— 图案作用的对象已经消失了。
    更要紧的是**增量闸门拿不到图案**（`library._cheap_facts(f)` 只拿到路径，
    见那里的「只能依赖文件自身」），若这里应用、那里不应用，卡片上的话数与
    阅读器里的话数就会不一致。所以树内部的「话」只按扩展名与可见性判定。
    """
    allowed = tuple(exts) if exts else UNIT_EXTS
    files = _all_files(d)
    if files is None:
        return None
    return [(p, rel) for p, rel in files if p.suffix.lower() in allowed]


def _all_files(d) -> "list | None":
    """树内**全部**文件（不限扩展名）；超限返回 ``None``。

    第二个用户是 :func:`dir_fingerprint` —— 体积指纹必须看得见树里的**每一个**文件
    （封面、扫描图、被替换的一话），只算媒体文件会让「加了一张封面」在增量闸门上
    完全看不见（卡片会一直显示旧值，且不报错）。
    """
    out: list = []
    if not _walk(pathlib.Path(d), "", out, 0):
        return None
    return out


def _walk(dirp: pathlib.Path, rel: str, out: list, depth: int) -> bool:
    """递归收集**全部文件**；**超限返回 ``False``**（一路把 ``False`` 传上去）。

    与 `library._iter_book_entries` 一样用 ``os.scandir``（`DirEntry` 的类型不发 syscall，
    NAS 上每文件省一次毫秒级往返），排序也按 ``Path`` 比 —— 与全量扫描同序。
    """
    try:
        with os.scandir(dirp) as it:
            entries = sorted(((pathlib.Path(e.path), e) for e in it), key=lambda t: t[0])
    except Exception:                     # 权限 / 目录消失 / SMB 抖动：这一层当空
        return True
    for p, ent in entries:
        if p.name.startswith("."):
            continue
        try:
            is_file, is_dir = ent.is_file(), ent.is_dir()
        except OSError:
            continue
        child = f"{rel}/{p.name}" if rel else p.name
        if is_file:
            out.append((p, child))
            if len(out) > _MAX_FILES:
                return False
        elif is_dir and depth < _MAX_DEPTH:
            if not _walk(p, child, out, depth + 1):
                return False
    return True


def _entries(d, exts=None) -> list:
    """``[(Path, rel, 序号或 None)]`` —— 本模块一切判据的共同底座。"""
    files = media_files(d, exts)
    if not files:
        return []
    return [(p, rel, parse_unit(p.stem)) for p, rel in files]


def _numbers(entries) -> set:
    """清单里**解析得出的**序号集合（去重）。

    「≥2 个**不同**序号」才是合并判据（见 :func:`is_unit_dir`）—— 所以要的是集合，
    不是计数：`《甲》/第1话.cbz` + `《乙》/第1话.cbz` 两个文件都解析得出序号，
    但它们是两本书的第一话，不是一部连载。
    """
    return {n for _, _, n in entries if n}


#: 会做序号单元合并的库类型（用户拍的板：漫画库 / 有声书库）。
#: ⚠️ 库类型的取值就是这四个：``ebook`` / ``comic`` / ``audiobook`` / ``mixed``
#: （``library._exts_for_type``、``migrate.TYPE_LABELS``）—— 没有 ``audio`` 这个值，
#: 写成 ``"audio"`` 一个库都匹配不上，而且不报错。
MERGE_LTYPES = ("comic", "audiobook")


def merges_for(ltype) -> bool:
    """这个库类型要不要做序号单元合并 —— **口径只有这一处**。

    两个消费点，判的必须是同一件事：

    - `library._iter_book_entries`（枚举：这棵树算不算**一个**条目）；
    - `migrate.compat_reason`（搬家闸门：搬过去还认不认得出这本书）。

    第二处若另写一份字面量，迟早出现「预览说能搬、搬完一本被拆成 43 本」。
    """
    return str(ltype or "").lower() in MERGE_LTYPES


def is_unit_dir(d, exts=None) -> bool:
    """这棵子树是不是「序号单元」：**≥2 个**可解析序号、且**序号不全相同**。

    「≥2」是判据的一部分，不是随手的阈值：单独一话说明不了这是个连载
    （`《书名》/第1话.pdf` 只有一本，退回今天的处理即可）。

    「不全相同」是同一件事的第二道闸，防的是**把容器当成书**：素材库常见的
    `作者/《甲》/第1话.cbz` + `作者/《乙》/第1话.cbz` 两个文件都解析得出序号，
    但那是两本书各自的第一话 —— 只看个数会把整个作者目录粘成一本。

    宁可少合并，不可错合并：少合并退回的是今天的行为（每个文件一本书，看得见、
    懂），错合并会把几本独立的书粘成一本（用户只能靠改名目录来救）。

    超限（文件数 > :data:`_MAX_FILES`）一律**不合并** —— 与 :func:`dir_fingerprint`
    的 ``None`` 条件同一个判据（`shape_of`），否则会出现「合并了却没有指纹」的条目，
    增量闸门会退回非递归口径、树深处新增的话看不见。
    """
    # `_entries` 对「空树」与「超限」都返回 `[]`（**同一个**结果：不合并 —— 见 docstring）。
    return len(_numbers(_entries(d, exts))) >= 2


def shape_of(d) -> str:
    """目录型条目**自身**的形态：``"audio"``（平铺音频目录）/ ``"units"``（序号单元树）/ ``""``。

    ⚠️ **只看目录自身** —— 不看库白名单、不看排除图案、不看库类型。理由是硬约束：
    ``library._probe_entry`` 只能依赖文件自身（增量刷新的立足点），而卡片上的形态
    必须与枚举侧一致。库「收不收」是另一件事，由 :func:`collected_by` 回答。

    ⚠️ **顺序：先平铺音频，后序号单元**，而且只在这里写一次。一个平铺目录可以同时
    满足两条判据（`01.mp3`…`12.mp3` 是音轨，也是一串序号），取音频形态才能让
    「N 轨 + 播放器」这套**改造前就有的**行为逐字不变（编号轨的有声书是常态）。
    枚举、探测、:func:`tracks_of`、:func:`dir_fingerprint` 四处的判断都落在这一条上：
    各判各的就会出现「卡片说 12 话、播放器列 12 轨但顺序不同」这类对不上。
    """
    p = pathlib.Path(d)
    if audio.is_audio_dir(p):
        return "audio"
    if is_unit_dir(p):
        return "units"
    return ""


def audio_allowed(exts) -> bool:
    """这个白名单里有没有音频扩展名 —— 「这个库收不收音频目录」。

    改造前写作 `library._iter_book_entries` 里的 ``allow_audio_dir`` 字面量，
    第 73 期起它同时被 :func:`collected_by`（搬家闸门经它）读 —— 一个判据两处写，
    迟早出现「预览说能搬、搬完书架上什么都没有」。
    """
    allowed = tuple(exts or ())
    return any(e in allowed for e in audio.AUDIO_EXTS)


def collected_by(d, exts, allow_units: bool) -> str:
    """这个库会不会把这个目录收**成一条书**，收成什么形态（``""`` = 收不到）。

    与 :func:`shape_of` **同序**，只多一层「库收不收」：

    - ``"audio"``：白名单含音频扩展名（:func:`audio_allowed`）；
    - ``"units"``：库会合并序号单元（``allow_units`` = :func:`merges_for` 的结果）
      **且**树里至少有一个文件的扩展名在白名单里 —— 否则整棵树对这个库隐形，
      与改造前「下探一层也收不到东西」的结果一致。

    两个消费点读同一份：`library._iter_book_entries`（收不收）与
    `migrate.compat_reason`（搬过去还认不认得出）。
    """
    p = pathlib.Path(d)
    allowed = tuple(exts or ())
    if audio_allowed(allowed) and audio.is_audio_dir(p):
        return "audio"
    if allow_units and is_unit_dir(p):
        files = media_files(p)
        if files and any(f.suffix.lower() in allowed for f, _ in files):
            return "units"
    return ""


def units(d, exts=None) -> list:
    """「话」清单：``[{index, name, num, kind, size}, ...]``，已排序、`index` 从 0 起。

    - 排序键 ``(序号, 自然序)``；**解析不出序号的排在最后**（`序章` / `番外` / `后记`
      这类如实按自然序排，不猜位置）；
    - 清单**包含**解析不出序号的文件（它们也是这本书的一部分），所以「话数」=
      树内媒体文件数；
    - ``name`` 是**相对树根**的 posix 路径（嵌套树显示 `第1卷/第1话.pdf`，平铺时
      就等于文件名）；**不含绝对路径** —— 这个列表要直接下发给前端。
    """
    items = []
    for p, rel, num in _entries(d, exts):
        try:
            size = p.stat().st_size
        except OSError:
            size = 0
        items.append({"index": 0, "name": rel, "num": num or 0,
                      "kind": kind_of(p), "size": size})
    items.sort(key=lambda it: (it["num"] or _INF, _NATURAL_KEY(it["name"])))
    for i, it in enumerate(items):
        it["index"] = i
    return items


def unit_path(d, index: int):
    """第 index 话的绝对路径；越界 / 不是单元树 → ``None``（与 ``audio.track_path`` 同款）。"""
    files = [p for p, _, _ in _sorted_entries(d)]
    return files[index] if 0 <= index < len(files) else None


def _sorted_entries(d, exts=None) -> list:
    """``[(Path, rel, num)]``，排序口径与 :func:`units` **逐字一致** ——
    两处若各排各的，「卡片说 4 话、点进去是第 3 话」这种错位就出来了。"""
    items = _entries(d, exts)
    items.sort(key=lambda t: (t[2] or _INF, _NATURAL_KEY(t[1])))
    return items


def dir_fingerprint(d, exts=None):
    """序号单元树的 ``(体积, mtime, 文件数)``；**不是单元树返回 ``None``**。

    「不是单元树」判的是 :func:`shape_of` —— 平铺音频目录（含编号轨）因此仍走
    `audio.dir_size_and_mtime`，改造前的口径**逐字不变**。

    这是「话清单有没有变」的**便宜判据**（增量刷新闸门与探测共用，见
    `library._cheap_facts` 那段「必须同源」的说明）。今天它必须是**递归**的：
    改造前目录条目用的是 ``audio.dir_size_and_mtime``（只看直接子文件），
    嵌套树里新增一话在 `(size, mtime)` 上**完全看不见** —— 增量刷新不会重探，
    用户加了一话，书架上是 0 变化、也不报错。

    覆盖树内**全部**文件（含封面等非媒体文件、含解析不出序号的）：闸门判的是
    「有没有变」，宁可比话清单多算几个文件（多算只多一次无害的重探），不能漏算
    （漏算 = 加了封面/换了一话却永远不重探）。
    """
    if shape_of(d) != "units":
        return None
    files = _all_files(d)
    if files is None:
        return None
    total, newest = 0, 0.0
    for p, _rel in files:
        try:
            st = p.stat()
        except OSError:
            continue
        total += st.st_size
        newest = max(newest, st.st_mtime)
    return (total, newest, len(files))


def first_audio(d):
    """树内第一个**音频**话的路径；没有返回 ``None``。

    演播者标签解析用（`audio_meta.extract` 要一个真实的音频文件）。平铺音频目录也能用
    —— 它的排序口径与 :func:`audio._audio_files` 对「全是音频」的目录是同一个结果。
    """
    for p, _, _ in _sorted_entries(d):
        if kind_of(p) == "audio":
            return p
    return None


def cover_in_tree(d) -> str:
    """树内封面（**相对树根**的 posix 路径，如 `cover.jpg` / `第1卷/cover.jpg`）；无则空串。

    逐层下探找 :func:`audio.cover_in_dir` 认得的那些名字（`cover` / `folder` / `poster`
    / `front` / `album`）。复用 `audio` 那套名字表而不是再抄一份 —— 封面是树根时
    返回值与改造前**逐字相同**（平铺音频目录的行为不变）。
    """
    return _first_cover(pathlib.Path(d), "", 0)


def _first_cover(dirp: pathlib.Path, prefix: str, depth: int) -> str:
    name = audio.cover_in_dir(dirp)
    if name:
        return f"{prefix}{name}"
    if depth >= _MAX_DEPTH:
        return ""
    try:
        with os.scandir(dirp) as it:
            subs = sorted(((pathlib.Path(e.path), e) for e in it), key=lambda t: t[0])
    except Exception:
        return ""
    for sub, ent in subs:
        if sub.name.startswith("."):
            continue
        try:
            if not ent.is_dir():
                continue
        except OSError:
            continue
        found = _first_cover(sub, f"{prefix}{sub.name}/", depth + 1)
        if found:
            return found
    return ""


# ---------------- 音频端点的统一入口（平铺 / 嵌套两种形态）----------------
# 「轨」与「话」是同一份清单的两个名字：平铺音频目录是「一章一文件」，嵌套树
# （`《书名》/第1卷/第1话.mp3`）是同一件事多了一层目录。两者的**取值来源**必须
# 只有一处判断，否则列表与单轨会各用各的序号。
#
# ⚠️ 平铺优先走 `audio.tracks`（**逐字不变**）：它按自然序排，而 `units` 会把
# 「解析不出序号」的名字排到最后 —— 对 `intro.mp3 / chapter2.mp3 / finale.mp3`
# 这种本来就存在的目录，改用 units 会让播放顺序变化，那是回归不是修 bug。
# 「有没有直接子音频文件」正是 `shape_of` 的第一条判据，所以这里的顺序与它同一条。

def tracks_of(path) -> dict:
    """「轨 / 话」清单：平铺音频 / 单文件走 ``audio.tracks``，**序号单元树**走 :func:`units`。"""
    tr = audio.tracks(path)
    if tr["total"]:
        return tr
    items = units(path)
    return {"items": items, "total": len(items)}


def track_at(path, index: int):
    """第 index 轨 / 话的绝对路径；越界返回 ``None``。与 :func:`tracks_of` 同判断。"""
    p = audio.track_path(path, index)
    if p is not None:
        return p
    return unit_path(path, index)
