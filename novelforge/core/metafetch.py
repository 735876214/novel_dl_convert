"""元数据抓取引擎：候选 → 按策略决定改什么 → 预览 → 应用。

分工：`metasources` 只管查（网络）· 本模块管**决策与落盘** · `fileops` 管 OPF/zip 重写。

**一律先预览、再应用**（与批量重命名、查重同一范式）：
- :func:`plan` 只算不改，返回每本书的字段级「当前值 → 建议值 + 来源 + 置信度」
- :func:`apply` 只接受前端回传的**具体条目**，并再校验一遍（书还在、是 EPUB、值非空）

两条硬规则：

1. **只写 EPUB**：PDF / CBZ / MOBI 没有可写的 OPF，plan 里直接标为「跳过」并说明原因，
   而不是假装能改（那会让用户以为抓取失败了）。
2. **字段策略先于一切**：`fill_only`（默认，只在原值为空时写）→ `overwrite` → `skip`。
   默认 fill_only 是刻意的：抓取来的元数据**没有用户自己写/改过的值可信**。
"""
import httpx

from . import fileops, library, metasources
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
DEFAULT_POLICY = "fill_only"


def _cfg(cfg: dict) -> dict:
    return ((cfg or {}).get("metadata_fetch") or {})


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


def plan(names: list = None, cfg: dict = None, limit: int = None, threshold: float = None) -> dict:
    """生成抓取预览（**只算不改**）。``names`` 为空表示整个书库。"""
    mf = _cfg(cfg)
    if not mf.get("enabled"):
        return {"enabled": False, "items": [], "message": "元数据抓取未启用"}
    sources = [s for s in (mf.get("sources") or list(metasources.DEFAULT_ORDER))
               if s in metasources.SOURCES] or list(metasources.DEFAULT_ORDER)
    limit = max(1, min(int(limit or mf.get("limit") or 5), 20))
    # 阈值可能来自配置段（也可能整段缺失 / 被填成非法值）→ 一律兜底，不让 float(None) 把整页打崩
    raw_thr = threshold if threshold is not None else mf.get("threshold")
    try:
        threshold = float(raw_thr)
    except (TypeError, ValueError):
        threshold = 0.75
    if not (0 < threshold <= 1):
        threshold = 0.75
    policy = mf.get("fields") or {}
    blocklist = {norm_key(x) for x in (mf.get("genre_blocklist") or []) if str(x).strip()}
    options = {"googlebooks": {"api_key": mf.get("googlebooks_api_key") or ""}}

    books = library.books()
    if names:
        wanted = set(names)
        books = [b for b in books if b["name"] in wanted]

    items = []
    for b in books:
        base = {
            "name": b["name"], "book_id": b["id"], "title": b.get("title") or "",
            "author": b.get("author") or "", "format": b.get("format") or "",
            "candidates": [], "sources": {}, "best_score": 0.0,
            "auto_ok": False, "changes": {}, "cover": None, "skipped": "", "error": "",
        }
        # ⚠️ `library.books()` 的 format 本来就是大写（"EPUB"），这里必须与 "EPUB" 比 ——
        # 写成 `.upper() != "epub"` 会让**每本 EPUB 都被当成非 EPUB 跳过**（实测踩过）
        if (b.get("format") or "").upper() != "EPUB":
            base["skipped"] = "非 EPUB：没有可写的 OPF（PDF / CBZ 的元数据抓取暂不支持）"
            items.append(base)
            continue

        res = metasources.search_all(sources, b.get("title") or b["name"], b.get("author") or "",
                                     limit, options)
        best = res.get("best")
        base["candidates"] = res["entries"]
        base["sources"] = res["sources"]
        if not best:
            errs = [v.get("error") for v in res["sources"].values() if v.get("error")]
            base["error"] = errs[0] if errs else "没有找到候选"
            items.append(base)
            continue

        base["best_score"] = best["score"]
        base["auto_ok"] = best["score"] >= threshold
        vals = _candidate_values(best, blocklist)
        changes = {}
        for field, value in vals.items():
            pol = policy.get(field) or DEFAULT_POLICY
            if pol == "skip" or not value:
                continue
            cur = _current_value(b, field)
            if pol == "fill_only" and cur:
                continue          # 原值非空 → 默认不动（抓来的没有用户自己的可信）
            if isinstance(value, list) and sorted(value) == sorted(cur or []):
                continue
            if not isinstance(value, list) and str(value) == str(cur):
                continue
            changes[field] = {"from": cur, "to": value, "source": best["source"],
                              "score": best["score"]}
        base["changes"] = changes

        cover_pol = policy.get("cover") or DEFAULT_POLICY
        if best.get("cover_url") and cover_pol != "skip":
            has = bool(b.get("has_cover"))
            if (not has) or cover_pol == "overwrite":
                base["cover"] = {"url": best["cover_url"],
                                 "action": "replace" if has else "add",
                                 "source": best["source"], "score": best["score"]}
        items.append(base)

    return {
        "enabled": True, "items": items, "sources": sources, "threshold": threshold,
        "auto": sum(1 for i in items if i["auto_ok"]),
        "total": len(items),
    }


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
    与 `apply_rename` 同一原则：规则若在两端解释不一致就会写错数据。
    """
    mf = _cfg(cfg)
    customs = {}
    for cf in (mf.get("custom_fields") or []):
        name = str((cf or {}).get("name") or "").strip()
        val = str((cf or {}).get("value") or "").strip()
        if name and val:
            customs[name] = val

    applied, failed, covers = [], [], 0
    for it in items or []:
        it = it if isinstance(it, dict) else {}
        name = str(it.get("name") or "").strip()
        fields = it.get("fields") or {}
        cover = it.get("cover") or None
        if not name:
            continue
        try:
            path = fileops.safe_path(name)           # 复用越界/非法字符校验
            if not path.is_file():
                raise ValueError("文件不存在")
            if path.suffix.lower() != ".epub":
                raise ValueError("只有 EPUB 支持写回元数据")

            updates = {k: v for k, v in fields.items()
                       if k in fileops.METADATA_FIELDS and (v not in ("", None, []))}

            add_files = None
            href = mt = ""
            if cover and str(cover.get("url") or "").strip():
                data, mt = _download_cover(str(cover["url"]))
                opf_path, _, _ = fileops._read_epub(path)
                if not opf_path:
                    raise ValueError("无法定位 EPUB 的 OPF")
                zip_rel, href = fileops.cover_paths(mt, opf_path)
                add_files = {zip_rel: data}

            def _transform(opf, _u=updates, _h=href, _m=mt, _c=customs):
                out = fileops.patch_opf_meta(opf, _u)
                for k, v in _c.items():              # 自定义字段 → <meta name content>
                    out = fileops._set_meta_name(out, k, v)
                if _h:
                    out = fileops.set_epub_cover(out, _h, _m)
                return out

            if not updates and not add_files and not customs:
                raise ValueError("没有需要写入的内容")
            if not fileops.rewrite_epub(path, transform=_transform, add_files=add_files):
                raise ValueError("EPUB 写入失败（可能是只读或损坏）")
        except Exception as e:                       # noqa: BLE001 —— 单本失败不影响其余
            failed.append({"name": name, "error": str(e)})
            continue
        applied.append({"name": name, "fields": sorted(updates.keys()),
                        "cover": bool(add_files)})
        if add_files:
            covers += 1

    if applied:
        library.invalidate()
    return {"applied": applied, "failed": failed, "count": len(applied), "covers": covers}


def auto_fetch(name: str, cfg: dict = None, limit: int = 3) -> dict:
    """入库后自动抓取单本（供 watcher 在转换完成后调用）。

    三条自我约束：

    1. **只应用达到阈值的字段** —— 低于阈值的候选一律不动，留给用户在预览页人工决定；
    2. **只补空字段**（`fill_only` 策略已在 plan 里生效），绝不用抓来的值盖掉用户自己写的；
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
