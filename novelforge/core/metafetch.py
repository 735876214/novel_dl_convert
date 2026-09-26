"""元数据抓取引擎：候选 → 按策略决定改什么 → 预览 → 应用。

分工：`metasources` 只管查（网络）· 本模块管**决策与落库**。

**一律先预览、再应用**（与实体改名、查重同一范式）：
- :func:`plan` 只算不改，返回每本书的字段级「当前值 → 建议值 + 来源 + 置信度」
- :func:`apply` 只接受前端回传的**具体条目**，并再校验一遍（书还在、值非空）

两条硬规则：

1. **不按格式分流**：结果**只存服务端 DB**（``meta_online`` / ``meta_cover``），**绝不改写任何文件**，
   所以 EPUB / PDF / 漫画 / 有声书一律同等对待（有声书是**目录**型条目，不再要求「是文件」）。
   ``fileops`` 的 OPF/zip 重写能力保留给结构性重排（改名 / 系列），不在本链路调用。
   第 22 期起**手动编辑元数据也不再限 EPUB**（非 EPUB 没有 OPF 兜底原值层，「恢复」= 撤销覆盖后
   回落在线的抓取值、没有在线值即为空；「清空」= 写无值哨兵，抓取也不会把它填回来）。
2. **字段策略先于一切**：`fill_only`（只在原值为空时写）→ `overwrite`（第 8 期起的默认，
   见 :data:`DEFAULT_POLICY`）→ `skip`。策略按**每库**可覆写（见 :func:`_mf_of`）。
   但仍有两道闸压在策略之上，且**都比策略更硬**（第 35 期补记）：
   - **用户改过的字段**（``meta_override``）不覆盖 —— 抓来的没有用户自己的可信；
   - **显式锁定的字段**（``meta_locks``）永不改写 —— 即使策略写着 ``overwrite``。
     两者可叠加：没改过但上锁的字段，抓取同样不碰。
"""
import httpx

from . import customfields, db, fileops, lib_settings, library, metasources
from .library import norm_key

#: 封面下载上限：常见封面 100KB–2MB，超过 8MB 基本是异常图
MAX_COVER_BYTES = 8 * 1024 * 1024
_COVER_TIMEOUT = httpx.Timeout(20.0, connect=8.0)

#: 字段名 → 书对象里读当前值的键。
#: ⚠️ **字段名必须用 `date`**：`fileops.METADATA_FIELDS` 与 OPF 里都是 `dc:date`，
#: 而书库列表（`library.books()`）里这个值叫 `year` —— 两个名字各有归属，写反了
#: `patch_opf_meta` 会**静默忽略**（它只认 METADATA_FIELDS），表现为「预览里说要写，实际没写」。
_CURRENT = {
    "title": "title", "author": "author", "publisher": "publisher", "date": "year",
    "language": "language", "isbn": "isbn", "description": "description", "tags": "tags",
}
#: 同上：字段名 → 候选里的键（候选结构里年份叫 year）
_VALUE_KEYS = dict(_CURRENT)
#: 第 8 期：默认改为「在线优先覆盖本地」——抓取来的元数据默认写回（覆盖 OPF 原值），
#: 但**用户显式改过的字段（meta_override）受保护**，不会被再次抓取冲掉（见 plan/apply）。
#: 仍可在配置的 `fields` 里逐项改回 `fill_only` / `skip`。
DEFAULT_POLICY = "overwrite"

# ---------------- 跨源字段级合并（第 58 期）----------------
# 现状曾是「取匹配分最高的**一条**候选，所有字段都用它」—— 于是 A 源简介好、B 源年份规范时，
# 落库的只有赢家的那一套。本段改成**逐字段择优**，但合并是有前提的：
# **只有「确实像同一本书」的候选才允许参与** —— 把同名不同书的字段拼在一起，比不合并更糟。
#
#: 参与合并的**绝对**下限（与 `threshold` 无关，这里是「够不够像同一本」的独立闸）
MERGE_MIN_SCORE = 0.7
#: 参与合并的**相对**下限：距最佳候选不能太远（两道闸取严）
MERGE_RELATIVE = 0.9
#: 合并后的题材上限（与单候选 `_entry` 的 8 个同口径）
MERGE_MAX_TAGS = 8

#: 字段 → **该字段更可信的源**（命中者在该字段上插队，未命中按候选分数排）。
#: 依据是各家**返回内容本身**的取舍，不是主观偏好：
#:   · date / language / isbn：Open Library 的字段最规范（它的多语言列表还专门挑过）
#:   · description / cover：Google Books 的简介与封面通常更全
#:   · tags：Open Library 的 subject 拆开后更像书目题材
#: 表里没有的字段（title / author）按候选分数取 —— 「像不像同一本书」已经由分数保证。
#:
#: ⚠️ 键必须是**字段名**（与 `_VALUE_KEYS` 的键一致），不是书对象里的键 ——
#: 「年份」的字段名是 `date`（书目里才叫 `year`）。写成 `year` 不会报错，只会**静默失效**
#: （信任表查不到 ⇒ 退回按分数排），所以有专门测试钉住它。
FIELD_TRUST = {
    "date": ("openlibrary",),
    "language": ("openlibrary",),
    "isbn": ("openlibrary", "googlebooks"),
    "publisher": ("openlibrary", "googlebooks"),
    "description": ("googlebooks", "openlibrary"),
    "cover": ("googlebooks",),
    "tags": ("openlibrary", "googlebooks"),
    "title": (),
    "author": (),
}


def _cfg(cfg: dict) -> dict:
    return ((cfg or {}).get("metadata_fetch") or {})


def _mf_of(book: dict, mf: dict) -> dict:
    """**该书所属库**的生效 ``metadata_fetch``（第 13 期「每库覆盖」）。

    只并入该库**真正覆写过**的键（见 :func:`lib_settings.apply_to`），所以：
    库没覆写时结果与传入的 ``mf`` 完全一致 —— 既有行为不变；
    库覆写了就按库走，这正是「每库覆盖」的意义（如电子书库抓、混合库不抓）。
    """
    return lib_settings.apply_to(mf, (book or {}).get("library_id"), "metadata_fetch")


def _threshold_of(mf: dict, fallback: float) -> float:
    """从配置段取阈值并夹到合法区间；取不到 / 非法 → 用 ``fallback``。"""
    try:
        t = float((mf or {}).get("threshold"))
    except (TypeError, ValueError):
        return fallback
    return t if 0 < t <= 1 else fallback


#: AUTO-FINALIZE 的合并模式预设（第 52 期）：上游有 safe_merge / embedded_only 等多档，
#: 本项目复用既有的 `fields` 逐字段策略来表达。预设与逐字段策略**互斥呈现**——
#: 选预设即把 `fields` 整体写成该模式对应的策略。
FINALIZE_PRESETS = {
    "overwrite": "覆盖（在线值优先）",
    "fill_only": "安全合并（仅补空值）",
    "embedded_only": "仅用内嵌（不下载在线封面与远程字段）",
}
#: `fields` 字典包含的字段键（与 config.DEFAULTS.metadata_fetch.fields 一致）
_FINALIZE_FIELDS = ["title", "author", "publisher", "year", "language",
                    "isbn", "description", "tags", "cover"]


def preset_to_fields(preset: str) -> dict:
    """合并模式预设 → 既有的 `fields` 逐字段策略字典。

    - overwrite            → 所有字段 overwrite（在线优先覆盖本地，即 DEFAULT_POLICY）
    - fill_only / safe_merge → 所有字段 fill_only（只补原值为空的字段）
    - embedded_only        → 所有字段 skip（不下载在线封面 / 远程字段，只用文件内嵌元数据）
    - 未知预设             → 回落 overwrite，绝不静默丢配置
    """
    if preset in ("fill_only", "safe_merge"):
        mode = "fill_only"
    elif preset == "embedded_only":
        mode = "skip"
    else:
        mode = "overwrite"
    return {k: mode for k in _FINALIZE_FIELDS}


def _current_value(book: dict, field: str):
    if field == "tags":
        return list(book.get("tags") or [])
    return str(book.get(_CURRENT.get(field) or field) or "").strip()


def _candidate_values(cand: dict, blocklist: set) -> dict:
    """候选 → ``{字段: 值}``；题材先过黑名单（过滤「小说」这类没信息量的值）。"""
    out = {}
    for field, key in _VALUE_KEYS.items():
        if field == "tags":
            vals = [str(t).strip() for t in (cand.get("tags") or [])]
            vals = [t for t in vals if t and norm_key(t) not in blocklist]
            # 去重保序（题材顺序有展示意义）
            out[field] = list(dict.fromkeys(vals))[:8]
        else:
            out[field] = str(cand.get(key) or "").strip()
    return out


def merge_eligible(cands: list, best: dict) -> list:
    """挑出**允许参与合并**的候选：分数够高，且不显著低于最佳候选（两道闸取严）。

    这道闸是刻意的保守：合并的收益是「字段更全」，风险是「把同名不同书的字段拼起来」——
    后者是**不可逆的元数据污染**（用户看到的是一个真实存在但从未出版过的组合）。
    所以宁可只用最佳候选，也不放低分候选进来。
    """
    top = float((best or {}).get("score") or 0.0)
    if top <= 0:
        return []
    floor = max(MERGE_MIN_SCORE, MERGE_RELATIVE * top)
    return [c for c in (cands or []) if float(c.get("score") or 0.0) >= floor]


def merge_values(cands: list, blocklist: set) -> tuple:
    """逐字段合并：``({字段: 值}, {字段: {来源, 分数}}, 参与源, 封面)``。

    规则都能解释给人听，不搞黑箱：

    1. 每个字段先看 :data:`FIELD_TRUST` 里的**信任源**（按该表顺序），再看候选分数，
       取第一个非空值 —— 所以「简介来自 Google Books、年份来自 Open Library」是**可预期**的；
    2. **题材是合并而非择优**：多源题材按出现顺序去重拼起来（上限 :data:`MERGE_MAX_TAGS`）——
       各家的题材本来就不重合，取某一个源反而信息更少；
    3. 逐字段回传 `来源 / 分数`：写库账目对得上（谁给的值、多可信）；封面同理单列。
    """
    sources: list = []
    for c in cands:
        s = str(c.get("source") or "")
        if s and s not in sources:
            sources.append(s)

    def order(field: str) -> list:
        trust = FIELD_TRUST.get(field, ())
        rank = {s: i for i, s in enumerate(trust)}
        # 信任源优先；其余按分数倒序（sorted 稳定 ⇒ 同分时保持传入顺序 = 用户在页面排的源顺序）
        return sorted(cands,
                      key=lambda c: (0 if str(c.get("source") or "") in rank else 1,
                                     rank.get(str(c.get("source") or ""), 0),
                                     -float(c.get("score") or 0.0)))

    values: dict = {}
    origin: dict = {}
    for field, key in _VALUE_KEYS.items():
        if field == "tags":
            merged: list = []
            first = None
            for c in order("tags"):
                for t in (c.get("tags") or []):
                    t = str(t).strip()
                    if t and norm_key(t) not in blocklist and t not in merged:
                        merged.append(t)
                        if first is None:
                            first = c
            if merged:
                values["tags"] = merged[:MERGE_MAX_TAGS]
                origin["tags"] = {"source": str((first or {}).get("source") or ""),
                                  "score": float((first or {}).get("score") or 0.0)}
            continue
        for c in order(field):
            v = str(c.get(key) or "").strip()
            if v:
                values[field] = v
                origin[field] = {"source": str(c.get("source") or ""),
                                 "score": float(c.get("score") or 0.0)}
                break

    cover = None
    for c in order("cover"):
        url = str(c.get("cover_url") or "").strip()
        if url:
            cover = {"url": url, "source": str(c.get("source") or ""),
                     "score": float(c.get("score") or 0.0)}
            break
    return values, origin, sources, cover


def _custom_changes(book: dict, defs: list, values: dict, locked: set) -> dict:
    """自定义字段该补的默认值：``{key: {from, to, source, score}}``。

    三道闸里的**两道**在这里以另一种形式成立：
      · 「改过就保护」等价于「**已经有值行**就不动」—— 值表的「行存在」本身就表示
        用户管过这一项（哪怕值是空串），所以不需要再查 override；
      · 「显式锁」照挡（自定义字段的锁键就是字段键本身，与封面的 `cover` 无关）；
      · 「字段策略」**不适用**：`metadata_fetch.fields` 是按 OPF 字段名建的，没有自定义
        字段的键，所以这里固定「只在没有值行时写默认值」= fill_only 语义，界面也这么写。
    """
    out = {}
    for d in customfields.applicable(defs, book.get("library_id")):
        key = d["key"]
        if not d.get("default_value") or key in values or key in locked:
            continue
        out[key] = {"from": "", "to": d["default_value"],
                    "source": "自定义字段", "score": 1.0}
    return out


def plan(names: list = None, cfg: dict = None, limit: int = None, threshold: float = None) -> dict:
    """生成抓取预览（**只算不改**）。``names`` 为空表示整个书库。"""
    mf = _cfg(cfg)
    if not mf.get("enabled"):
        return {"enabled": False, "items": [], "message": "元数据抓取未启用"}
    # 第 57 期：只认**真的能抓**的源（14 家都有 fetcher ⇒ 恒真）—— 留着这道过滤是防
    # 「将来注册表先加条目、fetcher 还没写」的空档，那时也别白跑一次注定失败的外呼。
    sources = [s for s in (mf.get("sources") or list(metasources.DEFAULT_ORDER))
               if metasources.is_implemented(s)] or list(metasources.DEFAULT_ORDER)
    limit = max(1, min(int(limit or mf.get("limit") or 5), 20))
    # 阈值可能来自配置段（也可能整段缺失 / 被填成非法值）→ 一律兜底，不让 float(None) 把整页打崩
    raw_thr = threshold if threshold is not None else mf.get("threshold")
    try:
        threshold = float(raw_thr)
    except (TypeError, ValueError):
        threshold = 0.75
    if not (0 < threshold <= 1):
        threshold = 0.75
    # 字段策略不在这里一次性取：它可能**按库不同**（见循环里的 `b_policy`），
    # 这里只留库级都取不到时的兜底值（DEFAULT_POLICY）。
    blocklist = {norm_key(x) for x in (mf.get("genre_blocklist") or []) if str(x).strip()}
    options = metasources.options_for(mf, sources)

    books = library.books()
    if names:
        wanted = set(names)
        books = [b for b in books if b["name"] in wanted]

    items = []
    # 一次性取出全部用户覆盖，避免逐书查库；plan 只算不改，这里只读不写
    overrides = db.all_overrides()
    # 第 35 期：字段级锁定同样一次取全（与覆盖同一批范式，不逐书查库）
    locks = db.all_locks()
    # 第 35 期：自定义字段定义（含默认值）与各书现有值，同样一次取全
    defs = db.list_custom_fields()
    custom_values = db.all_custom_field_values()
    for b in books:
        locked = locks.get(b["id"], set())
        base = {
            "name": b["name"], "book_id": b["id"], "title": b.get("title") or "",
            "author": b.get("author") or "", "format": b.get("format") or "",
            # 多书库：回传库 id，`apply` 才能把路径解析到**该书的库根**（否则默认库误判）
            "library_id": b.get("library_id") or "",
            "candidates": [], "sources": {}, "best_score": 0.0,
            # 第 58 期：参与跨源字段级合并的源（空 = 未合并，只用最佳候选）
            "merged_from": [],
            "auto_ok": False, "changes": {}, "cover": None, "skipped": "", "error": "",
            # 该书被显式锁定的字段（含封面的独立键 `cover`）：界面逐字段标注「已锁定」，
            # 抓取侧一律不给这些字段产生改动（见下方两道闸）。
            "locked": sorted(locked),
        }
        # 第 13 期：策略（开关 / 字段 / 阈值）按**该书所属库**取。
        # 库没覆写过时 `_mf_of` 原样返回传入值 → 行为与改造前逐字段一致。
        mfb = _mf_of(b, mf)
        b_policy = mfb.get("fields") or {}
        b_threshold = _threshold_of(mfb, threshold)
        if not mfb.get("enabled"):
            base["skipped"] = "该库已关闭在线元数据抓取（每库覆盖）"
            items.append(base)
            continue

        # 自定义字段该补的默认值：与在线候选**无关**（值来自定义本身），所以先算好 ——
        # 下面「没有候选」那条早退出也要带上它，否则没候选的书永远补不上自定义字段。
        cust_changes = _custom_changes(b, defs, custom_values.get(b["id"], {}), locked)

        # 不按格式跳过：结果**只写服务端 DB**，与文件能不能改无关 —— PDF / 漫画 / 有声书一视同仁。
        # （曾按 `format != "EPUB"` 跳过，理由是「没有可写的 OPF」；该前提在本链路改为只落库后已失效。）

        # ISBN 精确匹配优先（第 8 期 D4）：有 ISBN 且在线查得到就直接用，置信度视为最高
        exact = metasources.search_by_isbn(b.get("isbn") or "", sources, 3, options)
        if exact:
            res = {"entries": [exact], "sources": {}, "best": exact}
        else:
            res = metasources.search_all(sources, b.get("title") or b["name"],
                                         b.get("author") or "", limit, options)
        best = res.get("best")
        base["candidates"] = res["entries"]
        base["sources"] = res["sources"]
        if not best:
            errs = [v.get("error") for v in res["sources"].values() if v.get("error")]
            base["error"] = errs[0] if errs else "没有找到候选"
            # 没有在线候选 ≠ 没有可写的东西：自定义字段的默认值不依赖在线源
            base["changes"] = dict(cust_changes)
            items.append(base)
            continue

        base["best_score"] = best["score"]
        base["auto_ok"] = best["score"] >= b_threshold
        # 第 58 期：**跨源字段级合并** —— 够格的候选不止一条、且来自 ≥2 家时逐字段择优，
        # 否则退回「只用最佳候选」的旧行为（逐字一致，含封面）。
        pool = merge_eligible(res["entries"], best) if mfb.get("merge_sources", True) else []
        if len({str(c.get("source") or "") for c in pool}) >= 2:
            vals, origin, merged_sources, cover_pick = merge_values(pool, blocklist)
            base["merged_from"] = merged_sources
        else:
            vals = _candidate_values(best, blocklist)
            origin = {f: {"source": best["source"], "score": best["score"]} for f in vals}
            cover_pick = ({"url": best["cover_url"], "source": best["source"],
                           "score": best["score"]} if best.get("cover_url") else None)
        # 自定义字段先放进来（键空间不同：它们不是 OPF 字段名，必不与下面重名）
        changes = dict(cust_changes)
        for field, value in vals.items():
            pol = b_policy.get(field) or DEFAULT_POLICY
            if pol == "skip" or not value:
                continue
            # 用户改过的字段受保护：抓取不覆盖，否则会冲掉本地修正
            if field in overrides.get(b["id"], {}):
                continue
            # 第 35 期：**显式锁定** —— 抓取永不改写该字段，即使策略是 ``overwrite``。
            # 与上一道闸独立：那道是「改过就保护」，这道能锁住一个从没改过的字段。
            if field in locked:
                continue
            cur = _current_value(b, field)
            if pol == "fill_only" and cur:
                continue          # 原值非空 → 默认不动（抓来的没有用户自己的可信）
            if isinstance(value, list) and sorted(value) == sorted(cur or []):
                continue
            if not isinstance(value, list) and str(value) == str(cur):
                continue
            # 来源 / 分数**逐字段**记（合并后同一本书的不同字段可能来自不同源）——
            # 预览界面据此如实展示「这个值是谁给的」，出了问题也追得回来。
            meta_src = origin.get(field) or {}
            changes[field] = {"from": cur, "to": value,
                              "source": meta_src.get("source") or best["source"],
                              "score": meta_src.get("score") or best["score"]}
        base["changes"] = changes

        cover_pol = b_policy.get("cover") or DEFAULT_POLICY
        # 封面锁用独立键 `cover`（第 35 期）：策略说覆盖也没用，锁在就不动它
        if cover_pick and cover_pol != "skip" and db.LOCK_COVER not in locked:
            has = bool(b.get("has_cover"))
            if (not has) or cover_pol == "overwrite":
                base["cover"] = {"url": cover_pick["url"],
                                 "action": "replace" if has else "add",
                                 "source": cover_pick["source"], "score": cover_pick["score"]}
        items.append(base)

    return {
        "enabled": True, "items": items, "sources": sources, "threshold": threshold,
        "auto": sum(1 for i in items if i["auto_ok"]),
        "total": len(items),
    }


def online_candidate(book: dict, cfg: dict = None, limit: int = None) -> "dict | None":
    """对单本书做一次在线检索，返回**最佳候选**的字段值（不上锁、不写库）。

    供详情页编辑器的「在线建议 / 恢复在线」使用：它只决定「在线说这本书是什么」，
    不参与任何落盘，因此和 :func:`plan` 一样是纯查询。
    """
    mf = _cfg(cfg)
    if not mf.get("enabled"):
        return None
    # 第 13 期：该书所属库覆盖过开关就按库走（库没覆写则与全局一致）
    mf = _mf_of(book, mf)
    if not mf.get("enabled"):
        return None
    # 第 57 期：只认**真的能抓**的源（14 家都有 fetcher ⇒ 恒真）—— 留着这道过滤是防
    # 「将来注册表先加条目、fetcher 还没写」的空档，那时也别白跑一次注定失败的外呼。
    sources = [s for s in (mf.get("sources") or list(metasources.DEFAULT_ORDER))
               if metasources.is_implemented(s)] or list(metasources.DEFAULT_ORDER)
    limit = max(1, min(int(limit or mf.get("limit") or 5), 20))
    blocklist = {norm_key(x) for x in (mf.get("genre_blocklist") or []) if str(x).strip()}
    options = metasources.options_for(mf, sources)
    # ISBN 精确匹配优先，否则回退书名 + 作者检索
    exact = metasources.search_by_isbn(book.get("isbn") or "", sources, 3, options)
    if exact:
        pool_raw = [exact]
    else:
        res = metasources.search_all(sources, book.get("title") or book.get("name") or "",
                                     book.get("author") or "", limit, options)
        pool_raw = res.get("entries") or []
    if not pool_raw:
        return None
    best = pool_raw[0]                 # search_all 已按分数倒序 ⇒ 第一条即最佳候选
    # 与 `plan` **同一套**门槛与择优规则：两处口径必须一致，否则「详情页的在线建议」与
    # 「抓取预览」会各说各话（同一条数据两种答案，比少一个功能更糟）。
    pool = merge_eligible(pool_raw, best) if mf.get("merge_sources", True) else []
    if len({str(c.get("source") or "") for c in pool}) >= 2:
        vals, origin, merged_sources, cover = merge_values(pool, blocklist)
    else:
        vals = _candidate_values(best, blocklist)
        origin = {f: {"source": best.get("source"), "score": best.get("score")} for f in vals}
        merged_sources = [str(best.get("source") or "")]
        cover = ({"url": best["cover_url"], "source": best.get("source"),
                  "score": best.get("score")} if best.get("cover_url") else None)
    return {"values": vals, "source": best.get("source"), "score": best.get("score"),
            "merged_from": merged_sources,
            # 逐字段来源：界面如实展示「这个值是哪个源给的」
            "field_sources": {f: (origin.get(f) or {}).get("source") or best.get("source")
                              for f in vals},
            "cover": cover}


def _download_cover(url: str) -> tuple:
    """下载封面 → ``(bytes, media_type)``。只接受图片类型，限制体积，并拦「太小的图」。

    ⚠️ 为什么还要管小图：`library._cover_usable` 用一个**最小体积阈值**判断封面是否可用
    （几十字节的光栅图会被当成 stub）。小图写进去后，书库与阅读器都会视为「没有封面」——
    与其留下这种半吊子状态（用户以为抓到了封面），不如在这里直接拒绝并说清原因。
    阈值**复用同一个常量**，免得两处各写一个数、日后走样。
    """
    if not str(url or "").lower().startswith(("http://", "https://")):
        raise ValueError("封面地址非法")
    with httpx.stream("GET", url, timeout=_COVER_TIMEOUT, follow_redirects=True) as r:
        if r.status_code >= 400:
            raise ValueError(f"封面下载失败（{r.status_code}）")
        mt = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not mt.startswith("image/"):
            raise ValueError(f"封面不是图片（{mt or '未知类型'}）")
        buf = bytearray()
        for chunk in r.iter_bytes(65536):
            buf.extend(chunk)
            if len(buf) > MAX_COVER_BYTES:
                raise ValueError("封面超过 8MB 上限")
    if not buf:
        raise ValueError("封面内容为空")
    if not mt.endswith("svg") and len(buf) < library._COVER_MIN_BYTES:
        raise ValueError(
            f"封面图太小（{len(buf)} 字节，需 ≥ {library._COVER_MIN_BYTES}）："
            "写入后书库会判为无效封面，故跳过"
        )
    return bytes(buf), mt


def apply(items: list, cfg: dict = None) -> dict:
    """应用抓取结果。每条 = ``{name, fields: {字段: 值}, cover: {url} | null}``。

    ⚠️ 只认前端回传的**具体值**，不接受「用第 N 个候选」这种间接指令 ——
    与实体改名同一原则：规则（或选择）若在两端解释不一致就会写错数据。

    第 17 期 T3：结果**只存服务器 DB**（数值 → ``meta_online``，封面 → ``meta_cover``），
    **绝不改写 Epub 文件**。列表 / 详情 / 封面接口都从服务端读取生效值。

    ``fields`` 里可能混着**自定义字段**（第 35 期）：它们按定义的类型校验后落到
    ``book_custom_values``，与 OPF 字段走不同的表 —— 两者靠「键是否在定义表里」分流。
    """
    applied, failed, covers = [], [], 0
    defs = db.list_custom_fields()      # 一次取全：每本书都要按适用书库筛一遍
    for it in items or []:
        it = it if isinstance(it, dict) else {}
        name = str(it.get("name") or "").strip()
        fields = it.get("fields") or {}
        cover = it.get("cover") or None
        if not name:
            continue
        try:
            # 多书库：基根取**该书所属库**（前端回传 library_id 优先，缺失则按名字反查），
            # 不能默认落到默认库根 —— 否则非默认库的书会被误判「文件不存在」。
            # ⚠️ 只校验「确实在这本书所属的库根下」（`safe_path` 的安全边界），**不再限定必须是
            # EPUB 文件**：有声书是**目录**、漫画 / PDF 是各自的容器，而结果本来就只写 DB。
            lid = fileops._lib_of(name, it)
            path = fileops.safe_path(name, lid)
            if not path.exists():
                raise ValueError("文件不存在")

            updates = {k: v for k, v in fields.items()
                       if k in fileops.METADATA_FIELDS and (v not in ("", None, []))}

            bid = it.get("book_id") or library.book_id(name, lid)
            # 第 35 期：被锁的字段一律不写。前端回传的是**具体值**，而这份值可能来自
            # 一个「上锁之前渲染的」预览页 —— 这里再挡一道，锁的语义才不会被过期页面绕过。
            locked = db.get_locks(bid)
            blocked = sorted(k for k in updates if k in locked)
            updates = {k: v for k, v in updates.items() if k not in locked}
            # 在线值只记服务端（供展示与「恢复在线」回退），不下写文件
            if updates:
                db.set_online(bid, {k: (v, "") for k, v in updates.items()})

            # 第 35 期：自定义字段走**另一张表**（book_custom_values），按定义的类型校验后写入。
            # 与元数据字段的区别：空串对自定义字段是**有意义的**（= 用户显式清空，
            # 抓取不会再补默认值），所以这里不做「空值跳过」。
            cdefs = {d["key"]: d for d in customfields.applicable(defs, lid)}
            blocked += sorted(k for k in fields if k in cdefs and k in locked)
            cust = {}
            for k, v in fields.items():
                if k not in cdefs or k in locked:
                    continue
                cust[k] = customfields.normalize(cdefs[k]["type"], v)
            if cust:
                db.set_custom_field_values(bid, cust)

            # 封面同样只存服务端缓存；下载失败不阻断元数据写回
            has_cover = False
            if cover and str(cover.get("url") or "").strip() and db.LOCK_COVER not in locked:
                try:
                    data, ctype = _download_cover(str(cover["url"]))
                    db.set_cover(bid, data, ctype)
                    has_cover = True
                except Exception:                    # noqa: BLE001 —— 封面失败不阻断
                    has_cover = False

            if not updates and not cust and not has_cover:
                # 被锁挡下的情况要说清楚「为什么没写」—— 否则前端只能看到一句
                # 「没有需要写入的内容」，会误以为是自己传空了
                if blocked:
                    raise ValueError("字段已锁定，未写入：" + "、".join(sorted(set(blocked))))
                raise ValueError("没有需要写入的内容")
        except Exception as e:                       # noqa: BLE001 —— 单本失败不影响其余
            failed.append({"name": name, "error": str(e)})
            continue
        # fields 里如实列出**这一本实际写了什么**（含自定义字段 —— 它们落在另一张表，
        # 但对调用方来说「这本书的这些字段写进去了」是同一件事）
        applied.append({"name": name, "fields": sorted([*updates.keys(), *cust.keys()]),
                        "cover": has_cover})
        if has_cover:
            covers += 1

    if applied:
        library.invalidate()
    return {"applied": applied, "failed": failed, "count": len(applied), "covers": covers}


def auto_fetch(name: str, cfg: dict = None, limit: int = 3) -> dict:
    """入库后自动抓取单本（供 watcher 在转换完成后调用）。

    三条自我约束：

    1. **只应用达到阈值的字段** —— 低于阈值的候选一律不动，留给用户在预览页人工决定；
    2. **在线优先覆盖本地**（默认策略已是 ``overwrite``），但用户通过编辑器显式改过的
       字段（``meta_override``）受保护、不会被这次自动抓取冲掉；
    3. **吞掉一切异常**：这是**旁路增强**，不能因为外网不通就影响入库主流程。

    返回 ``{ok, fields?, cover?, reason?}``，供活动日志记一笔。
    """
    try:
        p = plan(names=[name], cfg=cfg, limit=max(1, min(int(limit or 3), 5)))
        if not p.get("enabled"):
            return {"ok": False, "reason": "未启用"}
        if not p.get("items"):
            return {"ok": False, "reason": "书不在库中（可能还没扫到）"}
        it = p["items"][0]
        if it.get("skipped"):
            return {"ok": False, "reason": it["skipped"]}
        if not it.get("auto_ok"):
            return {"ok": False, "reason": "没有达到置信度阈值的候选",
                    "best": it.get("best_score", 0)}
        fields = {k: v["to"] for k, v in (it.get("changes") or {}).items()}
        cover = it.get("cover") or None      # 封面与 best 同源，既然 auto_ok 就可以用
        if not fields and not cover:
            return {"ok": False, "reason": "没有需要补的字段"}
        res = apply([{"name": name, "fields": fields, "cover": cover}], cfg=cfg)
        return {"ok": bool(res["count"]), "fields": sorted(fields),
                "cover": bool(cover), "failed": res["failed"]}
    except Exception as e:                    # noqa: BLE001 —— 旁路增强，绝不向上抛
        return {"ok": False, "reason": f"自动抓取异常：{e}"}
