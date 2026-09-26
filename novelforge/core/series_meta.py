"""系列级元数据（第 12 期 C3 SYNOPSIS）。

系列在**文件层**没有实体：系列名来自各册 EPUB 的 ``calibre:series``，
``library.series_list()`` 也只是把书目按这个名字聚合。本模块给它补上
「简介 / 出版社 / 首发年 / 题材 / 册数」这层信息。

三条设计原则（都来自用户逐条拍板）：

1. **字段分层取「本地覆盖 > 本地聚合 > 在线补空」**
   - 聚合值（出版社 / 首发年 / 题材 / 实际拥有册数）**优先**：它是从成员书的 OPF
     直接汇总的**事实**，零猜测；
   - 在线值**仅在聚合为空时**补位（例如系列简介，本地根本无从推断）；
   - 用户本地编辑的覆盖值最高优先，且**再次抓取不会冲掉**。
2. **只存 DB，绝不写回 EPUB**。OPF 没有「系列简介」这个字段，唯一近似
   ``dc:description`` 属于**单册** —— 写进去就是覆盖掉某一册自己的简介；
   而「系列首发年」写进各册 ``dc:date`` 会让某本 2019 年出版的第 7 册变成 2015 年。
   代价（已确认接受）：其它软件**直读文件**看不到这些字段，连服务读则可见。
3. **两个册数语义必须分清**：``owned_count`` 是库里**实际拥有**的册数（本地聚合，必为真）；
   ``declared_count`` 是外部**声明**的系列总册数（可能为 0 = 未知）。
   **在线值不得覆盖 ``owned_count``**。
"""
from __future__ import annotations

import json
import threading
from collections import Counter

from .. import config
from . import activity_log, db, fileops, lib_settings, library, metasources

#: 可被本地覆盖的展示字段（与 :data:`db.SERIES_LOCAL_COLS` 一一对应）
FIELDS = ("description", "publisher", "first_year", "tags")

#: 字段中文标签（接口层与前端共用同一份，避免两处各写一套）
LABELS = {
    "description": "系列简介",
    "publisher": "出版社",
    "first_year": "首发年",
    "tags": "题材",
}

#: 候选与成员书的最低一致性分。低于它说明**连一本成员书都对不上**，
#: 此时宁可不给简介也不硬凑（作者侧同一思路：宁可放弃也不给错配）。
MIN_MATCH = 0.6

#: 「抓取全部系列」单次最多处理多少个：全库一次跑完必然超时
#: （见 server.py 关于 /api/metadata/plan 的既有教训），由前端分批循环。
FETCH_BATCH = 8


def _as_tags(value) -> list:
    """把「JSON 数组串 / list / 逗号或顿号串」一律归一成去重后的列表。"""
    if isinstance(value, (list, tuple)):
        items = list(value)
    else:
        text = str(value or "").strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            items = parsed if isinstance(parsed, list) else [text]
        else:
            items = text.replace("，", ",").replace("、", ",").split(",")
    out: list = []
    for x in items:
        s = str(x or "").strip()
        if s and s not in out:
            out.append(s)
    return out


def _aggregate(name: str) -> dict:
    """从**成员书的 OPF** 汇总系列级事实（零猜测）。

    出版社取「出现最多的那个」（一个系列换过出版社时，多数派比第一册更有代表性）；
    首发年取最早的一个；题材取并集（保序）；册数就是成员书本数。
    """
    bs = library.series_books(str(name or ""))

    pubs = [str(b.get("publisher") or "").strip() for b in bs]
    pubs = [p for p in pubs if p]
    publisher = ""
    if pubs:
        cnt = Counter(pubs)
        # 先按出现次数降序，再按**首次出现位置**升序 —— 平手时结果稳定可预期
        first_at = {}
        for i, p in enumerate(pubs):
            first_at.setdefault(p, i)
        publisher = sorted(cnt, key=lambda p: (-cnt[p], first_at[p]))[0]

    years = [str(b.get("year") or "").strip() for b in bs]
    years = [y for y in years if y]

    tags: list = []
    for b in bs:
        for t in _as_tags(b.get("tags")):
            if t not in tags:
                tags.append(t)

    return {
        "books": bs,
        "owned_count": len(bs),
        "publisher": publisher,
        "first_year": min(years) if years else "",
        "tags": tags,
    }


def _pick(row: dict, field: str, agg_value: str) -> tuple:
    """单值字段的生效值：本地覆盖 > 本地聚合 > 在线。返回 ``(值, 是否被本地覆盖)``。"""
    local = str(row.get(f"{field}_local") or "").strip()
    if local:
        return local, True
    if agg_value:
        return agg_value, False
    return str(row.get(field) or "").strip(), False


def effective(name: str) -> dict:
    """系列生效元数据（供系列页 / Komga / OPDS 三处展示）。

    字段语义见模块 docstring：``owned_count`` 与 ``declared_count`` **不可混用**。
    ``source`` / ``score`` 是在线抓取的来源与一致性打分（未命中时为低分），
    界面据此如实展示置信度，而不是把不确定的结果当确定值用。
    """
    name = str(name or "").strip()
    row = db.get_series_meta(name) or {}
    agg = _aggregate(name)

    description, desc_ov = _pick(row, "description", "")   # 本地无从推断系列简介
    publisher, pub_ov = _pick(row, "publisher", agg["publisher"])
    first_year, year_ov = _pick(row, "first_year", agg["first_year"])

    tags_local = _as_tags(row.get("tags_local"))
    if tags_local:
        tags, tags_ov = tags_local, True
    elif agg["tags"]:
        tags, tags_ov = agg["tags"], False
    else:
        tags, tags_ov = _as_tags(row.get("tags")), False

    return {
        "name": name,
        "description": description,
        "publisher": publisher,
        "first_year": first_year,
        "tags": tags,
        # 实际拥有数：永远来自本地聚合，**任何在线值都不得覆盖它**
        "owned_count": int(agg["owned_count"]),
        "declared_count": int(row.get("declared_count") or 0),
        "overridden": {
            "description": desc_ov, "publisher": pub_ov,
            "first_year": year_ov, "tags": tags_ov,
        },
        "source": str(row.get("source") or ""),
        "score": float(row.get("score") or 0.0),
        "fetched_at": float(row.get("fetched_at") or 0.0),
    }


def effective_light(name: str, row: dict = None) -> dict:
    """列表页用的**轻量**生效值：只做「本地覆盖 > 在线」，**不做聚合**。

    :func:`effective` 内部的 ``_aggregate`` 要扫一遍成员书目；而列表端点
    （Komga 的 series 列表、OPDS 系列导航、``GET /api/series``）会遍历**全部**系列 ——
    逐系列聚合 = N 次全库扫描，列表页会明显变慢。所以列表场景走这条。
    **不提供 ``owned_count``**：它必须来自聚合，宁可没有也不能瞎猜。
    """
    name = str(name or "").strip()
    row = row if row is not None else (db.get_series_meta(name) or {})

    def pick(field: str):
        local = str(row.get(f"{field}_local") or "").strip()
        if local:
            return local, True
        return str(row.get(field) or "").strip(), False

    description, desc_ov = pick("description")
    publisher, pub_ov = pick("publisher")
    first_year, year_ov = pick("first_year")
    tags_local = _as_tags(row.get("tags_local"))
    tags = tags_local or _as_tags(row.get("tags"))
    return {
        "name": name,
        "description": description,
        "publisher": publisher,
        "first_year": first_year,
        "tags": tags,
        "declared_count": int(row.get("declared_count") or 0),
        "overridden": {
            "description": desc_ov, "publisher": pub_ov,
            "first_year": year_ov, "tags": bool(tags_local),
        },
        "source": str(row.get("source") or ""),
        "score": float(row.get("score") or 0.0),
        "fetched_at": float(row.get("fetched_at") or 0.0),
    }


def state(name: str) -> dict:
    """逐字段明细（编辑器用）：生效值 / 在线值 / 聚合值 / 是否被本地覆盖。

    与 ``metastore.state()`` 同形状，前端据此渲染「已本地修改」徽标与「恢复在线」。
    """
    name = str(name or "").strip()
    row = db.get_series_meta(name) or {}
    agg = _aggregate(name)
    local_cols = {
        "description": "description_local", "publisher": "publisher_local",
        "first_year": "first_year_local", "tags": "tags_local",
    }
    out: dict = {}
    for f in FIELDS:
        if f == "tags":
            local_v = _as_tags(row.get(local_cols[f]))
            online_v = _as_tags(row.get(f))
            agg_v = list(agg["tags"])
            value = local_v if local_v else (agg_v or online_v)
            out[f] = {"value": value, "online": online_v, "aggregated": agg_v,
                      "local": local_v, "overridden": bool(local_v)}
            continue
        local_v = str(row.get(local_cols[f]) or "").strip()
        online_v = str(row.get(f) or "").strip()
        agg_v = str(agg.get(f) or "")
        out[f] = {"value": local_v or agg_v or online_v, "online": online_v,
                  "aggregated": agg_v, "local": local_v, "overridden": bool(local_v)}
    return out


def set_local(name: str, **fields) -> dict:
    """设置 / 清除本地覆盖（传空串 = 撤销该字段覆盖，回退到聚合或在线值）。

    只认 :data:`FIELDS` 里的字段 —— 与 ``metastore`` 只认 ``METADATA_FIELDS`` 同理，
    不校验就等于放任任意列名流进库里。
    """
    name = str(name or "").strip()
    if not name:
        raise ValueError("系列名为空")
    payload: dict = {}
    for f in FIELDS:
        if f not in fields:
            continue
        raw = fields[f]
        if f == "tags":
            payload["tags_local"] = json.dumps(_as_tags(raw), ensure_ascii=False)
        else:
            payload[f"{f}_local"] = str(raw or "").strip()
    if payload:
        db.set_series_local(name, **payload)
    return effective(name)


# ---------------- 在线抓取 ----------------
# 全程容错（照 authors.fetch_author）：任何异常都折算成 {ok: False, error}，
# **绝不向上抛** —— 这是旁路增强，不能因为它失败就把系列页整个弄挂。

def _owner_library(members: list) -> str:
    """系列的归属库：**全部成员同属一库**时用它，否则空串。

    跨库系列没有单一归属 —— 这时回退全局配置，而不是随手挑一个库的策略
    （挑错会让「按库配置」变得不可预期）。
    """
    libs = {str(b.get("library_id") or "") for b in members or []}
    libs.discard("")
    return libs.pop() if len(libs) == 1 else ""


def _fetch_cfg(cfg: dict = None, library_id=None) -> dict:
    """取元数据抓取配置（与 metafetch / 设置页同一份 ``metadata_fetch``）。

    第 13 期「每库覆盖」：给了 ``library_id`` 就并入该库覆写过的键；
    该库没覆写过（或传空）时与全局完全一致 —— 既有行为不变。
    """
    mf = ((cfg or config.load_config()).get("metadata_fetch") or {})
    if library_id:
        mf = lib_settings.apply_to(mf, library_id, "metadata_fetch")
    return mf


def fetch_one(name: str, cfg: dict = None) -> dict:
    """抓取单个系列的在线元数据，落库并返回结果。**不抛异常**。

    返回 ``{name, ok, score?, source?, matched_title?, sources, error?}``。
    命中要求候选与**成员书**的一致性分 ≥ :data:`MIN_MATCH` —— 外部源没有系列实体，
    分数低就是「没搜到能对上的东西」，如实回未找到，不给编造的简介。
    """
    name = str(name or "").strip()
    if not name:
        return {"name": name, "ok": False, "error": "系列名为空"}
    members = library.series_books(name)
    if not members:
        return {"name": name, "ok": False, "error": "系列不存在或没有成员书"}

    mf = _fetch_cfg(cfg, _owner_library(members))
    if not mf.get("enabled"):
        return {"name": name, "ok": False, "error": "在线元数据抓取未启用"}
    # 与书籍抓取同一口径：只用真的能抓的源，密钥按注册表 key_field 拼装（第 57 期）
    sources = [s for s in (mf.get("sources") or list(metasources.DEFAULT_ORDER))
               if metasources.is_implemented(s)] or list(metasources.DEFAULT_ORDER)
    options = metasources.options_for(mf, sources)

    try:
        res = metasources.search_series(name, members, sources=sources, limit=5, options=options)
    except Exception as e:                       # noqa: BLE001 —— 旁路增强，失败只回错误
        return {"name": name, "ok": False, "error": f"检索失败：{e}"}

    best = res.get("best") or {}
    score = float(best.get("score") or 0.0)
    base = {"name": name, "score": score, "matched_title": best.get("title") or "",
            "sources": res.get("sources") or {}}
    if not best or score < MIN_MATCH:
        return {**base, "ok": False,
                "error": "未找到可信的在线候选（检索结果与系列成员书都对不上）"}

    db.upsert_series_meta(
        name,
        description=best.get("description") or "",
        publisher=best.get("publisher") or "",
        first_year=best.get("year") or "",
        tags=json.dumps(best.get("tags") or [], ensure_ascii=False),
        # 两个源都不提供「系列总册数」，故恒为 0（= 未知），绝不拿成员数冒充
        declared_count=0,
        source=best.get("source") or "",
        score=score,
    )
    return {**base, "ok": True, "source": best.get("source") or "", "error": ""}


def fetch_all(names: list = None, limit: int = FETCH_BATCH, cfg: dict = None) -> dict:
    """批量抓取系列：逐个抓、单个失败不中断，返回成功 / 失败统计。

    **一次最多处理 ``limit`` 个**（默认 :data:`FETCH_BATCH`），并回 ``remaining``
    告诉调用方还剩多少 —— 全库一次跑完必然超时，所以由前端分批循环、显示进度。
    ``names`` 为空则取全部系列（仍受 ``limit`` 截断）。
    """
    all_names = [s["name"] for s in library.series_list()]
    known = set(all_names)
    wanted = [str(n).strip() for n in (names or []) if str(n or "").strip()]
    todo = [n for n in wanted if n in known] or (wanted or all_names)
    try:
        cap = max(1, min(int(limit or FETCH_BATCH), 50))
    except (TypeError, ValueError):
        cap = FETCH_BATCH

    batch, rest = todo[:cap], todo[cap:]
    ok = failed = 0
    items = []
    for n in batch:
        r = fetch_one(n, cfg=cfg)
        if r.get("ok"):
            ok += 1
        else:
            failed += 1
        items.append(r)
    return {"total": len(todo), "ok": ok, "failed": failed,
            "remaining": len(rest), "items": items}


# ---------------- 重排册号 ----------------
# ⚠️ 只改**服务端覆盖**（``meta_override.series_index``），
#    既不改文件名、也**不改写 EPUB 文件**（第 18 期统一口径：元数据只存服务端）。
#    文件名是 library.book_id 的来源（basename 派生）；文件名不动 → book_id 不变
#    → 阅读进度 / 批注 / 评分 / 收藏全部不断链。
#    操作本身可逆：返回里带每个条目的 old_index，按它再跑一次即可还原。

#: 串行化重排：一批覆盖是「先读后写」的组合，两个并发请求交叉会写出错乱的序号
_renumber_lock = threading.RLock()


def _series_order(members: list) -> list:
    """默认重排顺序：按当前 **系列序号升序**，缺序号的排最后（与前端展示口径一致）。"""
    def key(b: dict):
        raw = str(b.get("series_index") or "").strip()
        try:
            return (0, float(raw), str(b.get("name") or ""))
        except ValueError:
            return (1, 0.0, str(b.get("name") or ""))
    return sorted(members, key=key)


def renumber_plan(name: str, order: list = None) -> dict:
    """重排预览：返回逐条 ``{name, book_id, title, old_index, new_index, changed}``。

    **只算不改**。``order`` 为空则按当前顺序自动编号 1..N；给了 ``order``
    （前端逐册调整后的顺序，元素为书目相对路径）则按其顺序编号 ——
    传进来的名字必须真属于该系列，否则忽略（不让前端顺手改到别的系列的书）。
    """
    name = str(name or "").strip()
    members = library.series_books(name)
    if not members:
        raise ValueError("系列不存在或没有成员书")

    by_name = {str(b.get("name")): b for b in members}
    if order:
        picked = [by_name[str(n)] for n in order if str(n) in by_name]
        # 前端漏传的成员补在后面，保证「每条成员都有新序号」而不是静默丢失
        picked += [b for b in _series_order(members) if b not in picked]
    else:
        picked = _series_order(members)

    items = []
    for i, b in enumerate(picked, start=1):
        old = str(b.get("series_index") or "").strip()
        items.append({
            "name": str(b.get("name")), "book_id": str(b.get("id")),
            "title": str(b.get("title") or b.get("name")),
            "format": str(b.get("format") or "").upper(),
            "old_index": old, "new_index": str(i),
            "changed": old != str(i),
        })
    return {"series": name, "items": items,
            "total": len(items), "changing": sum(1 for x in items if x["changed"])}


def renumber_apply(name: str, items: list) -> dict:
    """按前端回传的**具体条目**写回序号（**只写服务端覆盖，不动文件**）。

    只接受 ``{name, new_index}``；``name`` 必须是该系列的成员（否则跳过）。

    - ``new_index`` **必须显式给出**：缺键 = 跳过；
    - 给**具体数字** = 写 ``meta_override.series_index``（该册的生效序号立刻变，
      列表 / 详情 / OPF 无关地一致）；
    - 给**空串** = **清空序号**（写 :data:`db.META_CLEAR` 哨兵）：该册在所有界面
      都显示「无序号」，并单列在返回的 ``cleared`` 里。文件本身依旧一个字节都不改。
    """
    name = str(name or "").strip()
    members = library.series_books(name)
    if not members:
        raise ValueError("系列不存在或没有成员书")
    if not isinstance(items, list) or not items:
        raise ValueError("items 必须是非空数组")

    by_name = {str(b.get("name")): b for b in members}
    done, skipped, cleared = [], [], []
    touched_libs = set()

    with _renumber_lock:
        for it in items:
            raw = str((it or {}).get("name") or "").strip()
            b = by_name.get(raw)
            if not b:
                skipped.append({"name": raw, "error": "不属于该系列"})
                continue
            if "new_index" not in (it or {}):
                skipped.append({"name": raw, "error": "缺少 new_index"})
                continue
            new_index = str((it or {}).get("new_index") or "").strip()
            old_index = str(b.get("series_index") or "").strip()
            bid = str(b.get("id") or "")
            if not bid:
                skipped.append({"name": raw, "error": "书目没有 book_id"})
                continue
            try:
                # 空串 = 用户显式要求「这一册没有序号」→ 写**哨兵**：覆盖值是列，
                # 存不了空串（空串在 set_override 里表示「撤销覆盖」）。
                # orig 只在首次建行时写入，代表「用户动手前文件里是什么」——
                # 与 server 的元数据编辑同义，供「无在线值时回退」使用。
                db.set_override(bid, "series_index",
                                new_index or db.META_CLEAR, orig=old_index)
            except Exception as e:               # noqa: BLE001 —— 逐条独立，一条失败不中断
                skipped.append({"name": raw, "error": str(e)})
                continue
            if b.get("library_id"):
                touched_libs.add(str(b["library_id"]))
            row = {"name": raw, "book_id": bid, "title": str(b.get("title") or raw),
                   "old_index": old_index, "new_index": new_index}
            done.append(row)
            if not new_index:
                cleared.append(row)

    # 失效受影响库的书目缓存，否则紧接着的读取还是 TTL 内的旧序号
    for lid in touched_libs or {""}:
        library.invalidate(lid or None)

    # 回读确认：真的从**生效值**（override > online > opf）里读回序号，
    # 而不是相信「写库没抛异常」。清空的那批也参与比对 —— 哨兵读回来必须是空串。
    verified = {}
    for x in library.series_books(name):
        verified[str(x.get("name"))] = str(x.get("series_index") or "").strip()
    mismatched = [d["name"] for d in done
                  if verified.get(d["name"]) != d["new_index"]]

    activity_log.log(activity_log.ACTION_METADATA, name,
                     activity_log.STATUS_OK if done else activity_log.STATUS_FAIL,
                     detail=f"重排系列序号：成功 {len(done)} 条"
                            + (f"（其中 {len(cleared)} 条恢复文件原值）" if cleared else "")
                            + (f"，跳过 {len(skipped)} 条" if skipped else ""),
                     source="api")
    return {"ok": True, "series": name, "renumbered": len(done),
            "items": done, "skipped": skipped, "cleared": cleared,
            "verified": verified, "mismatched": mismatched}
