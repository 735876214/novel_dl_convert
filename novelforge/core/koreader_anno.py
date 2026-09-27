"""读 KOReader 导出的批注文件（``<书名>.annotations.lua``）。

## 为什么是这个文件，而不是一个 HTTP 端点

第 63 期的计划里写的是「kosync 批注接收端点」。**那个东西不存在** —— 查证结果：

- 官方客户端 ``plugins/kosync.koplugin/api.json`` 只有 4 个方法，全是**进度**：
  ``/users/create``、``/users/auth``、``PUT /syncs/progress``、
  ``GET /syncs/progress/:document``。``main.lua`` / ``KOSyncClient.lua`` /
  ``KOSyncQueue.lua`` 里 ``annotation`` 零命中。
- 官方服务端 ``koreader/koreader-sync-server`` 的 ``config/routes.lua`` 同样只有进度。
- 社区有一个第三方 ``kosync-rs`` 定义了 ``/syncs/annotations/:document``，但它要配它
  自己的插件，**stock KOReader 不会去调**。

所以照原计划写一个 ``/koreader/syncs/annotations`` 端点，结果会是**一个没有任何真实
客户端会请求的接口** —— 界面上看着像接入了，其实是空的。这违反本项目的
「不造假数据」。**改成读 KOReader 真正产出的东西**：它自己就有批注跨设备同步，
走的是文件（PR #13372，2025.04 起）。

## 那个文件的格式（逐行取自上游源码，不是猜的）

`frontend/apps/reader/modules/readerannotation.lua`：

- ``getExportAnnotationsFilepath()``：``dir .. "/" .. 书名 .. ".annotations.lua"``，
  ``dir`` = 设置项 ``annotations_export_folder``，或书的 sidecar 目录
  （``<书>.sdr/``）。**导出发生在关书时**，且要 ``annotations_export_on_closing`` 为真。
- ``onExportAnnotations()`` 写四个顶层键：``device_id`` / ``datetime``
  （``os.date("%Y-%m-%d %H:%M:%S")``）/ ``paging``（是否固定版式）/ ``annotations``。
- 落盘走 ``util.writeToFile(dump(...), file, true, /*lua_dofile_ready*/ true, ...)``，
  而 ``writeToFile``（``frontend/util.lua``）在 ``lua_dofile_ready`` 为真时**加了前缀**：:

      "-- " .. filepath .. "\nreturn " .. data .. "\n"

  ⇒ 真文件的**第一行是 ``-- <该文件的绝对路径>`` 行注释**，第二行才以 ``return`` 开头。
  （``LuaSettings:open`` 用 ``pcall(dofile, file)`` 读回 —— 所以它必须是能 dofile 的代码块。
  本模块对「带不带 ``return``」两种都认，但**上游实际产出的一定是带 ``return`` 的那种**。）

序列化本身用 ``frontend/luasettings.lua`` 的 ``dump(self.data, nil, true)``，
而 ``dump``（``frontend/dump.lua``，75 行）产出的是**Lua 字面量**，不是 JSON：

- 表一律 ``[键] = 值,`` 逐行、4 空格缩进（**键总带方括号**，字符串键因此是
  ``["annotations"]``）；
- 字符串走 ``string.format("%q", s)`` —— 转义规则是 Lua 的，**不是 JSON 的**：
  ``"`` / ``\\`` / 换行 → 反斜杠 + 原字符（换行是「反斜杠后跟一个真换行」！），
  ``\\r`` → 反斜杠 r，``\\0`` → 反斜杠 0，其余控制字符原样输出；
- 数字/布尔走 ``tostring``；``nil`` 写成 ``nil`` —— 但 Lua 的 ``pairs`` **不遍历
  nil 值**，所以值为 nil 的键（``datetime_updated`` / ``note_format`` 等）
  **整个键都不出现在文件里**；
- 出现 ``--[[ LOOP:`` 注释意味着表里有环（本模块的数据不可能有，遇到了按错误处理）。

单条批注的字段见 ``buildAnnotation``（同文件），本模块只取其中这些：
``datetime``（创建时间，设备本地时间）、``datetime_updated``、``text``（划线的原文）、
``note``、``drawer``（样式）、``color``、``chapter``（**章节标题**，不是序号）、
``page`` / ``pos0`` / ``pos1``（位置）。

## 严格解析：看不懂就整份不收

``parse()`` 遇到任何不认识的构造（长字符串、十六进制数字、函数值、``LOOP`` 注释、
引号不闭合……）一律**抛异常**，绝不「尽力解析出一部分」。

理由是这份数据要写进用户的批注库：**解析出一半 = 静默丢一半**，而调用方拿到的是一个
成功的返回值。宁可整份拒收并报错，让用户看得见。

## 幂等与删除

导入走 :func:`novelforge.core.db.import_annotations`（按 ``(book_id, origin, anchor)``
应用层去重）。**导入永不删除**：这个格式里没有墓碑（上游的做法是拿文件级 ``datetime``
去猜哪条被删了，见 ``importAnnotations``），我们不去猜 —— 用户在设备上删掉的那条会留在
本项目里，这是如实的结果，不是 bug。要拿掉它，在本项目的垃圾桶里删。
"""
import pathlib
import re
import time

#: 来源标识，写进 `annotations.origin`。与 `db` 的来源枚举一致。
ORIGIN = "koreader"

#: 上游 `buildAnnotation` 里 `drawer` 的取值 → 本项目的 `style`。
#: 前两个是**真映射**（下划线、删除线语义一一对应）；`lighten` / `invert` 都是
#: 「在文字背景上做记号」，在本项目里就是 `highlight`。
DRAWER_TO_STYLE = {
    "underscore": "underline",
    "strikeout": "strikethrough",
    "lighten": "highlight",
    "invert": "highlight",
}

#: 上游调色板 → 本项目调色板（`frontend/src/data/annotationColors.ts`）。
#: 只映射**确有等价物**的；没列进来的（`olive` / `white` / `black` / `cyan` 之类）
#: 一律回落到本项目的默认色，**并计进 `unknown_colors` 计数**让调用方看得见 ——
#: 悄悄换个颜色显示也是失真。
COLOR_MAP = {
    "yellow": "yellow", "orange": "orange", "red": "red", "magenta": "magenta",
    "purple": "purple", "blue": "blue", "green": "green", "gray": "gray",
    # KOReader 的 cyan 是青蓝，本项目里最接近的一档是 teal
    "cyan": "teal",
}

#: 回落到这个色（与 `annotationColors.ts` 的 `DEFAULT_HIGHLIGHT_COLOR` 一致）
DEFAULT_COLOR = "yellow"

#: `datetime` / `datetime_updated` 的格式，取自上游 `os.date("%Y-%m-%d %H:%M:%S")`
_TS_FORMAT = "%Y-%m-%d %H:%M:%S"


class KoreaderAnnoError(ValueError):
    """文件读不懂（不是 KOReader 导出的、格式变了、被截断了……）。整份拒收。"""


# ---------------------------------------------------------------------------
# Lua 字面量解析（只认 LuaSettings/dump 会产出的那个子集）
# ---------------------------------------------------------------------------

_WS = " \t\r\n"
#: `dump` 在遇到表里有环时写出的注释；本模块的数据不该有环
_LOOP_MARK = "--[[ LOOP:"


class _Parser:
    def __init__(self, text: str):
        self.s = text
        self.i = 0

    # -- 基础 --------------------------------------------------------------
    def _skip_ws(self):
        while self.i < len(self.s):
            ch = self.s[self.i]
            if ch in _WS:
                self.i += 1
                continue
            if self.s.startswith(_LOOP_MARK, self.i):
                raise KoreaderAnnoError("文件里出现了 LOOP 注释 —— 数据成环，不敢解析")
            if self.s.startswith("--[[", self.i):
                end = self.s.find("]]", self.i)
                if end < 0:
                    raise KoreaderAnnoError("块注释没有收尾，文件可能被截断")
                self.i = end + 2
                continue
            if self.s.startswith("--", self.i):
                end = self.s.find("\n", self.i)
                self.i = len(self.s) if end < 0 else end + 1
                continue
            return

    def _expect(self, ch: str):
        self._skip_ws()
        if self.i >= len(self.s) or self.s[self.i] != ch:
            raise KoreaderAnnoError("期望 %r，实际卡在 %r" % (ch, self.s[self.i:self.i + 24]))
        self.i += 1

    # -- 值 ----------------------------------------------------------------
    def value(self):
        self._skip_ws()
        if self.i >= len(self.s):
            raise KoreaderAnnoError("文件提前结束")
        ch = self.s[self.i]
        if ch == "{":
            return self.table()
        if ch == '"':
            return self.string()
        if self.s.startswith("true", self.i):
            self.i += 4
            return True
        if self.s.startswith("false", self.i):
            self.i += 5
            return False
        if self.s.startswith("nil", self.i):
            self.i += 3
            return None
        return self.number()

    def table(self) -> dict:
        """读一张表。**数组与字典不分家**：Lua 里是一张，这里也读成一张。

        键统一转成字符串（``[1]`` → ``"1"``）：调用方拿的是字段名，
        再区分数字键没有意义。
        """
        self._expect("{")
        out: dict = {}
        while True:
            self._skip_ws()
            if self.i < len(self.s) and self.s[self.i] == "}":
                self.i += 1
                return out
            self._expect("[")
            key = self.value()
            self._expect("]")
            self._expect("=")
            out[_key_str(key)] = self.value()
            self._skip_ws()
            if self.i < len(self.s) and self.s[self.i] == ",":
                self.i += 1

    def string(self) -> str:
        """读一个字符串，转义规则按 **Lua 的** ``string.format("%q")``（见文件头）。"""
        self._expect('"')
        out: list = []
        while True:
            if self.i >= len(self.s):
                raise KoreaderAnnoError("字符串没有收尾的引号，文件可能被截断")
            ch = self.s[self.i]
            if ch == '"':
                self.i += 1
                return "".join(out)
            if ch != "\\":
                out.append(ch)
                self.i += 1
                continue
            self.i += 1
            if self.i >= len(self.s):
                raise KoreaderAnnoError("字符串以孤立的反斜杠结束")
            esc = self.s[self.i]
            self.i += 1
            if esc == "n":
                out.append("\n")
            elif esc == "t":
                out.append("\t")
            elif esc == "r":
                out.append("\r")
            elif esc == "a":
                out.append("\a")
            elif esc == "b":
                out.append("\b")
            elif esc == "f":
                out.append("\f")
            elif esc == "v":
                out.append("\v")
            elif esc == "\\":
                out.append("\\")
            elif esc == '"':
                out.append('"')
            elif esc == "'":
                out.append("'")
            elif esc == "\n":
                # Lua 的 `%q` 就是把换行写成「反斜杠 + 真换行」，不是 `\n` 两个字符
                out.append("\n")
            elif esc.isdigit():
                # `%q` 对控制字符产出十进制转义（`\0` 是它的特例）
                digits = esc
                while len(digits) < 3 and self.i < len(self.s) and self.s[self.i].isdigit():
                    digits += self.s[self.i]
                    self.i += 1
                code = int(digits)
                if code > 255:
                    raise KoreaderAnnoError("转义码 %s 超出单字节" % digits)
                out.append(chr(code))
            else:
                raise KoreaderAnnoError("不认识的转义 \\%s" % esc)

    def number(self):
        """十进制数。**不认十六进制** —— `dump` 走的是 `tostring`，不会产出 `0x`；
        认了反而是替一个不存在的写法兜底，等于给「文件被别的东西改过」放行。"""
        m = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?").match(self.s, self.i)
        if not m:
            raise KoreaderAnnoError("不认识的值，卡在 %r" % self.s[self.i:self.i + 24])
        raw = m.group(0)
        self.i = m.end()
        # `tostring(1)` 在 Lua 5.1 里给 "1"，在 5.3+ 给 "1.0" —— 两种都要能用
        if "." in raw or "e" in raw.lower():
            return float(raw)
        return int(raw)


def _key_str(key) -> str:
    if isinstance(key, bool):
        raise KoreaderAnnoError("布尔量当键了，不像 LuaSettings 的输出")
    if isinstance(key, float) and key.is_integer():
        return str(int(key))
    return str(key)


def parse(text: str) -> dict:
    """把一份 ``.annotations.lua`` 解析成 ``{device_id, datetime, paging, annotations}``。

    读不懂就抛 :class:`KoreaderAnnoError`，**不返回残缺结果**（见文件头）。
    ``annotations`` 一定是 list（上游写的是数组；不是数组就当错误）。
    """
    p = _Parser(text)
    # 落盘的是 `return { ... }`（LuaSettings 的 `flush` 写的是个可被 Lua 读回的文件）。
    # `return` **在注释之后才有意义**，所以先跳过空白与注释再认它。
    p._skip_ws()
    if p.s.startswith("return", p.i):
        p.i += len("return")
    root = p.value()
    p._skip_ws()
    if p.i < len(p.s):
        raise KoreaderAnnoError("文件末尾还有多余内容，卡在 %r" % p.s[p.i:p.i + 24])
    if not isinstance(root, dict):
        raise KoreaderAnnoError("顶层不是一张表")
    annos = root.get("annotations")
    if annos is None:
        annos = {}
    if not isinstance(annos, dict):
        raise KoreaderAnnoError("annotations 不是一张表")
    items = []
    for k in sorted(annos, key=_seq_key):
        item = annos[k]
        if not isinstance(item, dict):
            raise KoreaderAnnoError("annotations[%s] 不是一张表" % k)
        items.append(item)
    return {
        "device_id": str(root.get("device_id") or ""),
        "datetime": str(root.get("datetime") or ""),
        "paging": bool(root.get("paging")),
        "annotations": items,
    }


def _seq_key(k: str):
    """数组部分按下标排 —— ``dump`` 用 ``orderedPairs``，顺序基本就是插入序，
    但这里不指望它，按下标排一遍既稳又不丢。"""
    try:
        return (0, int(k))
    except (TypeError, ValueError):
        return (1, str(k))


# ---------------------------------------------------------------------------
# 映射到本项目的批注
# ---------------------------------------------------------------------------

def parse_ts(raw: str):
    """``"2026-09-27 10:00:00"`` → epoch；不认识就 ``None``（**不猜**）。

    这是**设备本地时间**，本项目只能原样当成本地时间存 —— 时区信息上游没给。
    """
    s = (raw or "").strip()
    if not s:
        return None
    for fmt in (_TS_FORMAT, "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    return None


def page_anchor(item: dict) -> str:
    """位置**原生标识** —— 用于导入去重与溯源，**不是**能定位的坐标（见 `db` 建表处）。

    - EPUB / 可重排版：``page`` 就是 XPointer 字符串（上游注释：``pos0 ... xPointer
      (== page)``）。它自己就唯一。
    - PDF / 固定版式：``page`` 是页码整数，真正的位置在 ``pos0`` / ``pos1`` 的
      ``{x, y}`` 表里（跨页还有 ``.page``）。所以拼一个含页码与两个坐标的串 ——
      只拿页码会把**同一页上的多条高亮**判成同一条，那几条里只有第一条导得进来。
    """
    page = item.get("page")
    if isinstance(page, dict):
        raise KoreaderAnnoError("page 是表，不是已知的两种形态（XPointer 串或页码）")
    if page is None:
        return ""
    if isinstance(item.get("pos0"), dict) or isinstance(item.get("pos1"), dict):
        def xy(v):
            if not isinstance(v, dict):
                return ""
            return "%s,%s@%s" % (v.get("x", ""), v.get("y", ""), v.get("page", ""))
        # 只拿页码会把**同一页上的多条高亮**判成同一条 —— 那几条里只有第一条导得进来
        return "pdf:%s|%s|%s" % (page, xy(item.get("pos0")), xy(item.get("pos1")))
    return str(page)


def to_items(parsed: dict) -> tuple:
    """解析结果 → ``(items, skipped, stats)``；``items`` 直接喂 :func:`db.import_annotations`。

    ``skipped`` 里每条是 ``{"reason": ..., "text": ...}`` —— **分开记原因不合并**
    （同 `db.import_annotations` 的计数纪律）：出问题时「为什么这条没进来」要看得出来。

    这里只做**本项目侧**的取舍，与协议无关：

    - **没有引文的丢掉**（``no_text``）。本项目把纯笔记建成 ``style='note'``（引文仍在），
      而设备上「没有 text 的条目」是书签不是笔记 —— 收进来会变成一条没有内容的空批注。
    - **没有位置的丢掉**（``no_position`` / ``bad_position``）。没位置就没法去重，
      收进来等于每次同步都多一份副本，而且每一次都成功、不报错。
    - **颜色/样式映射不上时照收，但计进 ``stats``**。换个颜色显示也是失真，
      只是没有「丢掉」那么严重；调用方要能把这件事说给用户听。
    """
    items, skipped = [], []
    stats = {"unknown_color": 0, "unknown_drawer": 0, "edited_text": 0, "no_timestamp": 0}
    for a in parsed.get("annotations") or []:
        text = str(a.get("text") or "").strip()
        note = str(a.get("note") or "")
        if not text:
            skipped.append({"reason": "no_text", "note": note})
            continue
        try:
            anchor = page_anchor(a)
        except KoreaderAnnoError as e:
            skipped.append({"reason": "bad_position", "detail": str(e), "text": text})
            continue
        if not anchor:
            skipped.append({"reason": "no_position", "text": text})
            continue

        raw_color = str(a.get("color") or "").lower()
        if raw_color and raw_color not in COLOR_MAP:
            stats["unknown_color"] += 1
        color = COLOR_MAP.get(raw_color, DEFAULT_COLOR)
        drawer = str(a.get("drawer") or "").lower()
        if drawer and drawer not in DRAWER_TO_STYLE:
            stats["unknown_drawer"] += 1
        style = DRAWER_TO_STYLE.get(drawer, "highlight")

        # 设备改过时间优先 —— 上游的合并语义也是 `datetime_updated or datetime`
        created = parse_ts(str(a.get("datetime_updated") or "")) or \
            parse_ts(str(a.get("datetime") or ""))
        if created is None:
            # 时间戳认不出来：落库时取导入时刻（`db.import_annotations` 的默认），
            # 但计一下 —— 「这条是什么时候划的」会因此不准，得让人知道
            stats["no_timestamp"] += 1
        if a.get("text_edited"):
            stats["edited_text"] += 1

        items.append({
            "anchor": anchor,
            "quote": text,
            "note": note,
            "color": color,
            "style": style,
            "created_at": created,
            # 上游的 `chapter` 是**章节标题**（`getTocTitleByPage` 的结果），不是序号 ⇒
            # 序号留 -1（未知），标题原样带上，界面显示标题、不给跳章链接
            "chapter": -1,
            "chapter_title": str(a.get("chapter") or ""),
        })
    return items, skipped, stats


# ---------------------------------------------------------------------------
# 找文件 + 导入
# ---------------------------------------------------------------------------

#: 导出文件的后缀。上游是 ``<书名>.annotations.lua``（``getExportAnnotationsFilepath``）。
#: 文件里**没有书的任何标识**（只有 device_id），所以书名是唯一能对上书的线索 ——
#: 这也是下面「按书找文件」而不是「按文件找书」的原因之一。
SUFFIX = ".annotations.lua"


def export_paths_for(book_file) -> list:
    """一本书的导出文件可能在哪两个位置（上游的默认落点），**按顺序**返回。

    1. 书的**旁边**：``<目录>/<书名>.annotations.lua``
    2. 书的 **sidecar 目录**里：``<目录>/<书名>.sdr/<书名>.annotations.lua``
       （``DocSettings:getSidecarDir`` 的命名就是 ``<文件名含扩展名>.sdr``）

    ⚠️ 上游还有一个 ``annotations_export_folder`` 设置项可以把导出挪到任意目录 ——
    **那个我们找不到**（设备上的设置，本项目无从得知）。所以界面必须如实说
    「只看这两处」，而不是让用户以为「没有 = 没导出」。
    """
    p = pathlib.Path(book_file)
    return [p.with_name(p.name + SUFFIX),
            p.parent / (p.name + ".sdr") / (p.name + SUFFIX)]


def scan_and_import(apply: bool = False) -> dict:
    """扫各库、按书找 KOReader 的导出文件并导入。

    ``apply=False``（默认）是**只看不写**：报出「会导多少条」，一条都不落库。
    界面上的「导入」按钮要先跑一次 dry-run 让人看到数字，再拿 ``apply=True`` 落库 ——
    这个动作会往用户的批注库里写东西，不该点一下就直接写。

    ## 为什么是「按书找文件」而不是「全盘找文件」

    反过来做（rglob 找 ``*.annotations.lua`` 再拿文件名对书）能顺带发现
    「有导出文件但书库里没这本书」，代价是**每次都要把整个书库走一遍** ——
    而书库可能挂在 NAS 上、有几十万个文件。第 62 期刚把请求路径上的全盘扫描消掉，
    这里不能再种一个回去。所以：书目索引里已经有每本书的路径，逐个 stat 两个候选位置。

    代价是**发现不了孤儿导出文件**（书不在库里 ⇒ 我们根本不会去看它）。
    这一点在返回值里如实体现：``unmatched`` 恒为空，不是「没有孤儿」的意思。

    返回 ``{"files": [...], "scanned": n, "with_file": n, "totals": {...}, "applied": bool}``。
    """
    from . import db, library
    files, totals = [], {"added": 0, "updated": 0, "unchanged": 0, "trashed": 0,
                         "no_anchor": 0, "no_quote": 0, "skipped": 0, "files": 0}
    for lib in library.libraries():
        roots = library.roots_of(lib)
        if not roots:
            continue
        for book in library.books(lib.get("id")):
            rel = str(book.get("name") or "")
            if not rel:
                continue
            for root in roots:
                book_file = root / pathlib.PurePosixPath(rel)
                if not book_file.is_file():
                    continue                       # 这个根下没有它，换下一个根
                for cand in export_paths_for(book_file):
                    if not cand.is_file():
                        continue
                    files.append(_import_one(db, cand, book, apply, totals))
                break
    return {"files": files, "scanned": len(files),
            "with_file": sum(1 for f in files if not f["error"]),
            # 恒为空：见上面「按书找文件」那段。留着这个键是为了让调用方不必改代码
            "unmatched": [], "totals": totals, "applied": bool(apply)}


def _import_one(db, path, book, apply: bool, totals: dict) -> dict:
    """读一个导出文件并（可选）导入。**单个文件出问题不影响别的文件**。"""
    row = {"path": str(path), "book": str(book.get("name") or ""),
           "book_id": str(book.get("id") or ""), "error": "",
           "items": 0, "skipped": 0, "stats": {}, "device_id": ""}
    try:
        parsed = parse(pathlib.Path(path).read_text(encoding="utf-8", errors="replace"))
    except (KoreaderAnnoError, OSError) as e:
        # 读不懂就整份跳过并报出原因 —— 不「尽力解析出一部分」（见文件头）
        row["error"] = str(e)
        return row
    row["device_id"] = parsed.get("device_id") or ""
    items, skipped, stats = to_items(parsed)
    row["items"] = len(items)
    row["skipped"] = len(skipped)
    row["stats"] = stats
    if apply and items:
        res = db.import_annotations(row["book_id"], ORIGIN, items)
        row["imported"] = res
        for k in ("added", "updated", "unchanged", "trashed", "no_anchor", "no_quote"):
            totals[k] += res.get(k, 0)
    totals["skipped"] += len(skipped)
    totals["files"] += 1
    return row
