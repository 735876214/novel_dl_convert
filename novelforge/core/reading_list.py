"""阅读顺序 → 「卷 / 段 → 章」结构（**唯一真值源**，第 85 期）。

EPUB 路径（``library._reading_list``）与 TXT 路径（``txtcache.native_chapters``）都调这里，
免得两处各写一份分组规则。

⚠️ **叶子模块**：只依赖 :mod:`novelforge.core.detect`（更叶的一层），**不 import
``library`` / ``txtcache``** —— 那两者之间本来就用「函数内延迟导入」绕循环依赖
（``library.book_detail`` 里 ``from . import txtcache``），分组算法放进它们任一都会把环拉回来。

## 为什么「段」要单独存在

一本中文长篇的目录常常长这样（EPUB3 nav 两级）::

    楔子
    第一卷
      第一章
      第二章
    第二卷
      第三章
    番外

- **卷**：``第一卷`` 是「卷首」。识别有两条路径（先层级、后标题形态，见 :func:`_head_positions`）。
- **楔子 / 番外**：没有章号，且与卷**同级**（不属于任何卷）。旧实现把它们 append 进「当前卷」，
  于是卷尾的番外被塞进最后一卷；卷前的楔子虽然能落进一个无名卷，但标题若来自兜底
  （``第 N 章``）就把书自己写着的「楔子」彻底丢了。
  现在：这类条目**各自成段**（连续的同类合成一段），段上打 ``kind = "front" | "back"``，
  且**不给序号**。

## 两条不许动的口径

1. ``index`` **原样透传**：它是阅读进度 / 批注 / 书签的坐标（第 65 / 73 期反复钉过），
   本模块只决定「怎么分组与叫什么」，绝不重排、不跳号、不丢条。
2. **每段内从 1 重新计**：无编号条目**不参与**计数（用户第 85 期口径）。
"""
from __future__ import annotations

import re
import unicodedata

from . import detect

#: 「目录不清楚」的默认判据参数（见 :func:`toc_unclear`）
_TOC_UNCLEAR_RATIO = 0.5
_TOC_UNCLEAR_MIN = 3


def _head_positions(entries: list, depths: list, min_depth) -> tuple:
    """``(卷首下标集合, 是否**由层级**判定)``。

    ① **有层级时按层级**：最浅层、且**紧随其后的那条（带层级的）条目更深** ⇒ 它是「卷容器」
       —— 沿用旧实现的判定（第 82 期之前就在用）。
    ② **层级识别不出任何卷时，退回标题形态**（``第X卷`` / ``第X部`` / ``卷X``）。
       「卷与章同层的平铺 nav」以及 TXT 的两条路线（派生 EPUB 用 ``nav=False`` 组装、
       原生分章根本没有 nav）都走这一条 —— 这正是「有卷的书看不到卷」的根因。

    ⚠️ **刻意不做并集**：层级可用时就以层级为准。否则「第一部 概要」这种长在**卷内部**的章
    会被标题形态误判成卷首，把一卷切成两半。

    ⚠️ 第二个返回值不是装饰：两类卷首的**成员语义**不同，且两条路径的既有行为都靠它保住 ——
    「卷容器」是一页卷名页（改造前就不进章节），而标题形态认出的卷首本身是一条**普通章节**
    （TXT 的 index 连续性、以及「第 X 卷」那页的可读性都依赖它）。
    """
    heads: set = set()
    if min_depth is not None:
        mapped = [p for p in range(len(entries)) if depths[p] is not None]
        for n, p in enumerate(mapped):
            if depths[p] != min_depth:
                continue
            nxt = mapped[n + 1] if n + 1 < len(mapped) else None
            if nxt is not None and depths[nxt] > min_depth:
                heads.add(p)
    if heads:
        return heads, True
    return {p for p, e in enumerate(entries)
            if detect.is_volume_title(e.get("title") or "")}, False


def build_reading_list(entries: list) -> list:
    """把**按阅读顺序**的条目分成「卷 / 段 → 章」。

    ``entries``：``[{"title": str, "index": int, "depth": int | None}]``
      · ``index`` **原样**出现在结果里（阅读进度与批注的坐标，本函数不改它）；
      · ``depth`` 来自 EPUB 目录层级；TXT 路径给 ``None``（= 无层级信息）。

    返回：``[{"volume": str, "kind"?: "front" | "back", "chapters": [...]}]``，
    ``chapters`` 元素形如 ``{"num"?: int, "title": str, "index": int}`` ——
    **无编号条目不带 ``num``**，其余按「段内从 1 重新计」。

    分段的四条规则（顺序即优先级）：

    1. **卷首** ⇒ 开一个**卷段**。层级判出的「卷容器」**自己不进章节**（改造前就是这个口径：
       那是一页卷名页）；标题形态判出的卷首**自己是一条普通章节**（TXT 的 index 连续性靠它）。
    2. 无编号条目（**且在结构顶层**）⇒ 进「同 kind 的前后段」，没有就开一个（**不塞进卷里**）；
    3. **层级判卷**时的顶层普通章（``depth == min_depth``）⇒ 它和卷是同级条目，不塞进上一卷
       （后记 / 附录这类就落在这里）；
       ⚠️ 这一条**只在层级判卷时生效**：平铺目录的层级里**没有嵌套信息**（卷与章同层），
       拿它当「位置」用会让每一章都变成独立一段（本轮实测踩过）。
    4. 其余普通章 ⇒ 进当前段；当前段是「前后段」时另开一个**无名正文段**
       （前后段只装无编号条目，不混普通章）。
    """
    items = [e for e in (entries or []) if e]
    if not items:
        return []

    depths = [e.get("depth") for e in items]
    known = [d for d in depths if d is not None]
    min_depth = min(known) if known else None
    heads, by_depth = _head_positions(items, depths, min_depth)
    # 整本没有层级信息（TXT / 无 nav）时，一切条目都算「结构顶层」
    no_depth = all(d is None for d in depths)

    groups: list = []
    cur: "dict | None" = None

    def _open(volume: str, kind: str = "") -> dict:
        g: dict = {"volume": volume, "chapters": []}
        if kind:
            g["kind"] = kind
        groups.append(g)
        return g

    for pos, e in enumerate(items):
        title = (e.get("title") or "").strip()
        struct_top = no_depth or depths[pos] is None or depths[pos] == min_depth
        kind = detect.is_unnumbered_title(title) if struct_top else ""
        if pos in heads:
            cur = _open(title)
            if by_depth:
                continue            # 卷名页不进章节（改造前口径，别顺手改）
        elif kind:
            # 前后段：同 kind 且紧挨着就并进上一段（「楔子 + 序章」合成一段）
            if cur is None or cur.get("kind") != kind or cur.get("volume"):
                cur = _open("", kind)
        else:
            need_new = (
                cur is None
                or bool(cur.get("kind"))                                  # 前后段只装无编号条目
                or (by_depth and struct_top and bool(cur.get("volume")))  # 层级判卷时的顶层兄弟
            )
            if need_new:
                cur = _open("")
        ch: dict = {"title": title}
        if e.get("index") is not None:
            ch["index"] = e["index"]
        cur["chapters"].append(ch)

    # 段内从 1 重新计（前后段一律不给序号：无编号条目「不参与编号」）
    for g in groups:
        n = 0
        if g.get("kind"):
            continue
        for c in g["chapters"]:
            n += 1
            c["num"] = n
    return groups


def is_fallback_title(title: str, index) -> bool:
    """这条标题是不是**我们生成的兜底名**（``第 3 章`` / ``第 3 节``）。

    ⚠️ 判据必须卡到「**与它自己的阅读序位一模一样**」：真书里「第 3 章」是完全合法的标题，
    只看格式会把正常目录误判成「不清楚」、进而对外呼（那是要避免的）。而兜底名恰恰是
    「序号 == 序位 + 1」（``library._reading_list`` 用 ``第 {i + 1} 章``、``txtcache`` 用
    ``第 {i + 1} 节``，``i`` 就是阅读序位）—— 真书极少整本都长这样。
    """
    if index is None:
        return False
    t = (title or "").strip()
    return t in (f"第 {index + 1} 章", f"第 {index + 1} 节")


def toc_unclear(chapters: list, *, ratio: float = _TOC_UNCLEAR_RATIO,
                min_chapters: int = _TOC_UNCLEAR_MIN) -> bool:
    """本地目录是否**不清楚**（⇒ 值得去正版书城取一份）。

    唯一判据：**兜底标题的占比**（见 :func:`is_fallback_title`）。含义就是「这本电子书的
    目录里根本没写标题，整本是第 N 章」—— 那正是用户说的「目录不清楚」。

    刻意**不**把「没有卷层级」算进来：一整本平铺的长篇是常态，拿它当触发条件会让几乎
    每本书都去外呼一次（第 80 期口径：出网要克制、失败要能降级）。
    """
    items = [c for v in (chapters or []) for c in (v.get("chapters") or [])]
    if len(items) < min_chapters:
        return False
    bad = sum(1 for c in items if is_fallback_title(c.get("title", ""), c.get("index")))
    return bad / len(items) >= ratio


# ---------------- 书城目录覆盖层（第 85 期批次 B）----------------

#: 归一化时要剥掉的标点（用于**比较**，不改展示标题）
_PUNCT_RE = re.compile(r"[\s·・:：,，.。!！?？\-—_/\\()（）\[\]【】\"'“”‘’]+")


def norm_title(s) -> str:
    """标题归一：NFKC（全角 → 半角）+ 小写 + 去空白与标点。**只用于比较，不改展示标题**。

    单一真值源。`sources/toc_sources.py` 的 `norm_title` 是这里转出去的 ——
    匹配与对齐**必须**用同一套归一，否则会出现「搜索匹配上了、章节却一条都对不上」这种
    两边各自看着都对的鬼故事。
    """
    return _PUNCT_RE.sub("", unicodedata.normalize("NFKC", str(s or "")).lower())


def build_pairs(entries: list, local_chapters: list) -> list:
    """书城目录 ↔ 本地章节的对齐 → ``[(书城序号, 本地 index), ...]``（只产出有把握的）。

    ### 为什么必须有第二趟

    第一趟按「标题归一后完全相等」配。这趟最准，但**恰好最需要取目录的那类书一条也配不上**：
    本地标题全是兜底名（``第 N 章``）时，两边标题不可能相等 —— 而那正是用户报的症状。

    第二趟只用一条**能自检的不变式**：两边**剩下没配上的条数一样多**时，按剩余顺序一一对应。

    为什么只认「条数相等」这一条：条数一致说明两边切分粒度一致，此时顺序才可信。
    而「跳过书城的卷名页再顺序配」那种做法看着更聪明，一旦跳错一格就是**全书章名整体错位**
    （张冠李戴），比不配（保持本地名）难查得多 —— 对齐结果是派生数据，宁少不多。
    条数不一致就停在第一趟的结果上，剩下的本地条目由覆盖层原样保留。

    ### 只做有把握的

    对齐结果是**派生**数据：配错了的表现是「章名张冠李戴」，比不配（保持本地名）难查得多。
    所以宁少不多 —— 没配上的本地条目由覆盖层原样保留。
    """
    local = [c for c in (local_chapters or []) if c.get("index") is not None]
    if not entries or not local:
        return []
    pairs: list = []
    used: set = set()
    # 第一趟：标题归一后完全相等（同名多处按出现顺序依次配，不跨位抢）
    bucket: dict = {}
    for c in local:
        bucket.setdefault(norm_title(c.get("title")), []).append(int(c["index"]))
    taken: set = set()
    for i, e in enumerate(entries):
        q = bucket.get(norm_title((e or {}).get("title")))
        if not q:
            continue
        idx = q.pop(0)
        pairs.append((i, idx))
        used.add(idx)
        taken.add(i)
    # 第二趟：**剩下的条数一样多** ⇒ 按剩余顺序一一对应；不一样多就一条都不配
    rest_e = [i for i in range(len(entries)) if i not in taken]
    rest_l = [int(c["index"]) for c in local if int(c["index"]) not in used]
    if rest_e and len(rest_e) == len(rest_l):
        pairs.extend(zip(rest_e, rest_l))
    return pairs

# ---------------- 在线阅读的章节对齐（第 93 期）----------------

#: 窗口半径（本章 ± N 章 ⇒ 共 5 章）与命中门槛（5 章里对上 3 章）
ONLINE_WINDOW = 2
ONLINE_NEED = 3


def align_online(online_titles: list, local_chapters: list, pos: int,
                 *, window: int = ONLINE_WINDOW, need: int = ONLINE_NEED) -> int | None:
    """线上第 ``pos`` 章 ↔ 本地哪一章（用户拍板的判据，第 93 期）。

    用户口径（2026-10-03 原话）：「根据章节序号和章节名称进行匹配，若本章节及上下章节共 5 章
    能有 3 章对应上就认定为同一章节，以线上章节名称进行确定进度等数据」。

    做法：取线上 ``pos`` 前后各 ``window`` 章（越界**收窄**）为窗口，与**本地同序号**的那几章
    逐个比 :func:`norm_title`；命中数 ``>= min(need, 窗口实际章数)`` ⇒ 认定同一章，
    返回**本地那一章的 index**；否则返回 ``None``（**不猜**）。

    为什么按「同序号」比、而不是拿线上标题去本地找：线上与本地是同一本书的两份目录，
    **序号才是骨架**，标题只用来确认「这个骨架没偏」。整本漂移（比如线上多了一章卷首）
    会让同序号全错 —— 那时命中数达不到门槛，如实返回 ``None``，绝不硬配。
    边界（书首 / 书尾）窗口收窄，门槛随之降到「够数即可」（``min(need, total)``），
    既不会因为「前面没章可对」而永远配不上，也不会拿两章对上就认定整本。

    ⚠️ **唯一实现**：客户端必须用服务端给的 ``local_index``，不许自己再算一份 ——
    否则「这台机器记上了进度、那台没记」这类只能靠猜的鬼故事会重演。
    """
    try:
        p = int(pos)
    except (TypeError, ValueError):
        return None
    titles = list(online_titles or [])
    local = {int(c["index"]): c for c in (local_chapters or []) if c.get("index") is not None}
    if not titles or not local or p < 0:
        return None
    w = max(0, int(window))
    hits = total = 0
    for i in range(p - w, p + w + 1):
        if i < 0 or i >= len(titles):        # 越界收窄：书首 / 书尾窗口变小
            continue
        total += 1
        c = local.get(i)
        if c is None:                        # 本地没有这一章（本地更短）⇒ 不算命中
            continue
        q = norm_title(titles[i])
        if q and q == norm_title(c.get("title")):
            hits += 1
    if total == 0 or hits < min(max(1, int(need)), total):
        return None
    # 认定同一章 ⇒ 本地位置就是线上位置（骨架对齐）；本地没有这一章则不记（返回 None）
    return p if p in local else None


def text_to_xhtml(text) -> str:
    """纯文本 → 阅读器 / EPUB 用的 XHTML 片段（**唯一实现**，第 93 期收敛）。

    两个调用方共用它：① 追更把源站新章写进 EPUB（`DownloadManager._update_report_locked`）；
    ② 在线阅读把源站正文交给阅读器（`sources/online.py`）。它们要的是同一件事 ——
    「一段来路不明的文本，怎么变成能安全渲染的段落」。

    ⚠️ **每一行先 `escape` 再包 `<p>`**：源站正文里可能有 `<script>`、`onerror=`、
    未闭合的标签。**第三方标记永远不进 `v-html`** 是在线读的硬要求（在线读那条路
    在调用前还会把 HTML 正文压成纯文本，见 `sources/online.html_to_text`）。
    空行（只有空白）丢掉：源站正文里常有成串空行，转成 `<p></p>` 就是一片空档。
    """
    from xml.sax.saxutils import escape
    return "\n".join(f"<p>{escape(s)}</p>"
                     for s in (ln.strip() for ln in str(text or "").splitlines()) if s)


def _store_slots(entries: list) -> dict:
    """书城目录摊平成 ``{书城序号: {"title", "volume", "kind"}}``。

    卷名与 kind 由 :func:`build_reading_list` **直接给出** —— 书城那份也走同一套分组规则，
    于是「书城的第X卷」与「本地的第X卷」判定口径天然一致，不会长出两套卷名逻辑。

    ⚠️ 键必须是**原始条目下标**（不是分组后的位置）：层级判卷时「卷容器」不进章节，
    两种编号会错开，拿错就是整份映射错位一格。
    """
    if not entries:
        return {}
    norm = [{"title": (e or {}).get("title", ""), "depth": (e or {}).get("depth"), "index": i}
            for i, e in enumerate(entries)]
    slot: dict = {}
    for g in build_reading_list(norm):
        for c in g.get("chapters") or []:
            slot[int(c["index"])] = {"title": c.get("title", ""),
                                     "volume": g.get("volume", ""),
                                     "kind": g.get("kind", "")}
    return slot


def apply_toc_override(chapters: list, entries: list, mapping: dict,
                       *, min_ratio: float = 0.6) -> list:
    """把书城目录的**标题与卷名**套到本地章节上（覆盖层，第 85 期批次 B）。

    · `chapters`：本地结构（:func:`build_reading_list` 的输出）；
    · `entries`：书城目录 ``[{"title", "depth"}, ...]``（**书城顺序**）；
    · `mapping`：``{书城序号: 本地 index}``（`db.toc_map_get` 的落库形状，这里自己反转）。

    ## 三条不许破的口径

    1. **本地结构是骨架**：分段与顺序仍按本地（``index`` 顺序 = 读者实际翻页的顺序），
       本函数只**改名**与**补卷名**。书城那份**不参与排序** —— 两边章节数几乎不会相等
       （书城常有分卷页、缺失的免费章），拿它当骨架必然错位。
    2. **未映射的条目一条不丢、不改名**：拿不到真值就不编。
    3. **只在本地说「不清楚」时才补卷名**：本地无名段（``volume == ""``）映射到书城某个
       有名卷、且**映射比例够**（``>= min_ratio``）才改名；本地已有卷名的不动 ——
       EPUB 自带的 nav 层级通常比书城更准（书城的卷名常是「第一卷 三体世界」这种带副标题的长名）。

    返回**新对象**（不改入参）：详情页与阅读器可能同时持有旧引用，原地改会让两边看到不同的书。
    """
    out = [dict(g, chapters=[dict(c) for c in (g.get("chapters") or [])])
           for g in (chapters or [])]
    slot = _store_slots(entries)
    # `mapping` 是「书城序号 → 本地 index」，这里反转成「本地 index → 书城序号」
    by_local = {int(l): int(s) for s, l in (mapping or {}).items()}
    if not slot or not by_local:
        return out
    for g in out:
        hits, names = 0, {}
        for ch in g["chapters"]:
            hit = slot.get(by_local.get(ch.get("index")))
            if not hit:
                continue
            hits += 1
            if hit["title"]:
                ch["title"] = hit["title"]
            if hit["volume"]:
                names[hit["volume"]] = names.get(hit["volume"], 0) + 1
        total = len(g["chapters"]) or 1
        if not (g.get("volume") or "") and names and hits / total >= min_ratio:
            # 众数：一段里可能混到两个书城卷（本地分段与书城不同），取多数那个，不硬切
            g["volume"] = max(names.items(), key=lambda kv: kv[1])[0]
            g.pop("kind", None)     # 有了真卷名，就不再是匿名的「前后段」了
    return out
