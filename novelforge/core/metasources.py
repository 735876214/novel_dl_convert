"""元数据源适配：按「书名 + 作者」到公开书库检索候选。

内置两个**都不需要 API Key** 的源：

- **OpenLibrary**：`/search.json`，一次能拿到书名/作者/首版年/出版社/语言/ISBN/题材/封面 id。
- **Google Books**：`/books/v1/volumes`，volumeInfo 里信息更全（含简介），
  ⚠️ 但它在部分地区会被拒（返回 403 `User location is not supported`），必须能降级。

设计要点：

1. **只读**：这里只负责「查候选 + 打分」，把结果写回 EPUB 是 `metafetch` 的事。
2. **单源失败不影响其它源**：NAS 内网可能只通其中一个（甚至都不通），
   所以每个源独立捕获异常并把原因带回去，而不是整体抛错。
3. **连通性自检**：设置页需要一眼看出「哪个源现在可用」，故提供 :func:`probe`。
4. **打分复用查重那套相似度**：`library.norm_key` 归一化 + `difflib.SequenceMatcher`，
   与「重复书籍」的口径一致 —— 同一本书在两处的匹配判断不应该出现分歧。
"""
import difflib
import re
import time

import httpx

from .library import norm_key

#: 与其它外呼一致的超时口径：连接 8s、整体 20s
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
#: 目标都在**公网**（与 OPDS/KOReader 的内网相反）→ 保留 httpx 默认的 trust_env（用户可能要代理）
_HEADERS = {"User-Agent": "NovelForge/1.0 (+metadata)", "Accept": "application/json"}

OPENLIBRARY = "https://openlibrary.org/search.json"
OPENLIBRARY_COVER = "https://covers.openlibrary.org/b/id/{cover}-L.jpg"
GOOGLEBOOKS = "https://www.googleapis.com/books/v1/volumes"

#: 源元数据（前端据此渲染开关与说明，避免前后端各写一份）
SOURCES = {
    "openlibrary": {
        "label": "OpenLibrary",
        "home": "https://openlibrary.org",
        "note": "无需 API Key。中文书的覆盖率一般，但语种/年份/ISBN 较规范。",
    },
    "googlebooks": {
        "label": "Google Books",
        "home": "https://books.google.com",
        "note": "无需 API Key。简介与封面通常更全；部分地区会被拒绝（返回 403）。",
    },
}
DEFAULT_ORDER = ("openlibrary", "googlebooks")

#: 语言代码归一：源里见过 "chi"/"zh"/"zh-CN"/"eng"… 统一成本项目用的短码
_LANG_MAP = {
    "chi": "zh", "zho": "zh", "zh-cn": "zh", "zh-tw": "zh", "zh-hans": "zh", "zh-hant": "zh",
    "eng": "en", "en-us": "en", "en-gb": "en", "jpn": "ja", "kor": "ko",
    "fre": "fr", "fra": "fr", "ger": "de", "deu": "de", "rus": "ru", "spa": "es",
}


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _year_of(value) -> str:
    """从各种形态里抠出 4 位年份（源里可能是 2008 / '2008-05-01' / 2008.0）。"""
    m = re.search(r"(1[5-9]\d{2}|20\d{2})", str(value or ""))
    return m.group(1) if m else ""


def _lang_of(value) -> str:
    v = _clean(value).lower().replace("_", "-")
    if not v:
        return ""
    head = v.split("-")[0]
    return _LANG_MAP.get(v) or _LANG_MAP.get(head) or head


#: 语言优先级。OpenLibrary 的 `language` 是一个**无序**的列表（一本书有几十种译本的
#: 语言代码混在一起），直接取第一个会得到「德语版《傲慢与偏见》」这种荒谬结果 —— 实测踩到过。
#: 所以按「常见目标语言」优先挑，都不在里面才退回第一个。
_LANG_PRIORITY = ("zh", "en", "ja", "ko")


def _pick_lang(values) -> str:
    langs = [_lang_of(v) for v in (values or [])]
    langs = [x for x in langs if x]
    for want in _LANG_PRIORITY:
        if want in langs:
            return want
    return langs[0] if langs else ""


def _split_subjects(values) -> list:
    """OpenLibrary 的 subject 里混着 ``"Fiction, Romance, Historical"`` 这类**复合值**，
    按逗号拆开才是一个个独立题材（否则整串会被当成一个标签，还过不了黑名单）。"""
    out = []
    for v in (values or []):
        for part in str(v).split(","):
            t = _clean(part)
            if t:
                out.append(t)
    return list(dict.fromkeys(out))


def score_candidate(want_title: str, want_author: str, cand: dict) -> float:
    """候选与目标书的匹配分（0–1）。

    书名权重 0.7、作者 0.3：同名不同作者的书很常见（重名率高的网文尤其），
    但「书名几乎一致 + 作者缺失」也不该被一票否决 —— 所以作者缺失时给中性 0.5。

    ⚠️ 用 :func:`library.norm_key` 归一化，与「重复书籍」保持同一口径。
    """
    t = norm_key(want_title)
    ct = norm_key(cand.get("title"))
    if not t or not ct:
        return 0.0
    t_score = difflib.SequenceMatcher(None, t, ct).ratio()

    a, ca = norm_key(want_author), norm_key(cand.get("author"))
    if not a or not ca or a in ("未知", "unknown", "佚名"):
        a_score = 0.5
    else:
        a_score = difflib.SequenceMatcher(None, a, ca).ratio()
    return round(0.7 * t_score + 0.3 * a_score, 4)


def _entry(source: str, **kw) -> dict:
    """统一候选结构 —— 前端与写回逻辑都只认这一种形状。"""
    return {
        "source": source,
        "title": _clean(kw.get("title")),
        "author": _clean(kw.get("author")),
        "publisher": _clean(kw.get("publisher")),
        "year": _year_of(kw.get("year")),
        "language": _lang_of(kw.get("language")),
        "isbn": _clean(kw.get("isbn")),
        "description": _clean(kw.get("description")),
        "tags": [t for t in (_clean(x) for x in (kw.get("tags") or [])) if t][:8],
        "cover_url": _clean(kw.get("cover_url")),
        "raw_id": _clean(kw.get("raw_id")),
        "score": 0.0,
    }


#: OpenLibrary 检索要返回的字段（书名 / 作者检索与 ISBN 精确匹配共用）
_OL_FIELDS = "key,title,author_name,first_publish_year,publisher,language,isbn,subject,cover_i"


def _ol_entry(d: dict) -> dict:
    """OpenLibrary 单条 doc → 统一候选。"""
    cover = d.get("cover_i")
    return _entry(
        "openlibrary",
        title=d.get("title"),
        author=(d.get("author_name") or [""])[0],
        publisher=(d.get("publisher") or [""])[0],
        year=d.get("first_publish_year"),
        # 语言要**挑**而不是取第一个：多语言列表是无序的（见 _pick_lang 注释）
        language=_pick_lang(d.get("language")),
        isbn=(d.get("isbn") or [""])[0],
        tags=_split_subjects(d.get("subject")),
        cover_url=OPENLIBRARY_COVER.format(cover=cover) if cover else "",
        raw_id=d.get("key") or "",
    )


def _gb_entry(it: dict) -> dict:
    """Google Books 单条 item → 统一候选。"""
    v = it.get("volumeInfo") or {}
    ids = v.get("industryIdentifiers") or []
    isbn = next((i.get("identifier") for i in ids if i.get("type") == "ISBN_13"), "") or \
        next((i.get("identifier") for i in ids if i.get("type") == "ISBN_10"), "")
    img = ((v.get("imageLinks") or {}).get("thumbnail") or "")
    return _entry(
        "googlebooks",
        title=v.get("title"),
        author=(v.get("authors") or [""])[0],
        publisher=v.get("publisher"),
        year=v.get("publishedDate"),
        language=v.get("language"),
        isbn=isbn,
        description=v.get("description"),
        tags=v.get("categories") or [],
        # Google 的缩略图常是 http 且带 zoom 参数；统一成 https 并放大到最大尺寸
        cover_url=img.replace("http://", "https://").replace("&zoom=1", "&zoom=3") if img else "",
        raw_id=it.get("id") or "",
    )


# ---------------- OpenLibrary ----------------

def _search_openlibrary(title: str, author: str, limit: int, opts: dict) -> list:
    params = {
        "title": _clean(title),
        "limit": str(limit),
        "fields": _OL_FIELDS,
    }
    if author and norm_key(author) not in ("未知", "unknown", "佚名"):
        params["author"] = author
    r = httpx.get(OPENLIBRARY, params=params, timeout=TIMEOUT, headers=_HEADERS)
    if r.status_code == 429:
        raise RuntimeError("被限流（429）：稍后再试")
    r.raise_for_status()
    docs = (r.json() or {}).get("docs") or []
    return [_ol_entry(d) for d in docs[:limit]]


# ---------------- Google Books ----------------

def _search_googlebooks(title: str, author: str, limit: int, opts: dict) -> list:
    q = f'intitle:"{_clean(title)}"'
    if author and norm_key(author) not in ("未知", "unknown", "佚名"):
        q += f'+inauthor:"{author}"'
    params = {"q": q, "maxResults": str(limit)}
    # 填了 Key 就带上：匿名请求额度很低，实测很容易撞 429
    api_key = _clean((opts or {}).get("api_key"))
    if api_key:
        params["key"] = api_key
    r = httpx.get(GOOGLEBOOKS, params=params, timeout=TIMEOUT, headers=_HEADERS)
    if r.status_code == 429:
        raise RuntimeError("被限流（429）：稍后再试，或在设置里填 Google Books API Key 提高额度")
    if r.status_code == 403:
        # 常见于地区限制：Google 会返回 403 且 reason 为 "The user location is not supported"
        raise RuntimeError("该地区不支持（Google 返回 403）")
    r.raise_for_status()
    items = (r.json() or {}).get("items") or []
    return [_gb_entry(it) for it in items[:limit]]


# ---------------- ISBN 精确匹配（第 8 期 D4）----------------
# 有 ISBN 的书直接按 ISBN 查，命中即为**同一版本**，比「书名+作者」相似度可靠得多。

def _search_isbn_openlibrary(isbn: str, limit: int, opts: dict) -> list:
    params = {"q": f"isbn:{isbn}", "limit": str(limit), "fields": _OL_FIELDS}
    r = httpx.get(OPENLIBRARY, params=params, timeout=TIMEOUT, headers=_HEADERS)
    if r.status_code == 429:
        raise RuntimeError("被限流（429）：稍后再试")
    r.raise_for_status()
    return [_ol_entry(d) for d in ((r.json() or {}).get("docs") or [])[:limit]]


def _search_isbn_googlebooks(isbn: str, limit: int, opts: dict) -> list:
    params = {"q": f"isbn:{isbn}", "maxResults": str(limit)}
    api_key = _clean((opts or {}).get("api_key"))
    if api_key:
        params["key"] = api_key
    r = httpx.get(GOOGLEBOOKS, params=params, timeout=TIMEOUT, headers=_HEADERS)
    if r.status_code == 429:
        raise RuntimeError("被限流（429）：稍后再试")
    if r.status_code == 403:
        raise RuntimeError("该地区不支持（Google 返回 403）")
    r.raise_for_status()
    return [_gb_entry(it) for it in ((r.json() or {}).get("items") or [])[:limit]]


_FETCHERS = {
    "openlibrary": _search_openlibrary,
    "googlebooks": _search_googlebooks,
}
_ISBN_FETCHERS = {
    "openlibrary": _search_isbn_openlibrary,
    "googlebooks": _search_isbn_googlebooks,
}


def search_by_isbn(isbn: str, sources: list = None, limit: int = 3,
                   options: dict = None) -> "dict | None":
    """按 ISBN 精确检索（跨源，按顺序取第一个命中）。

    命中即返回该候选并打上 ``exact_isbn=True``、``score=1.0`` —— ISBN 一一对应**同一版本**，
    匹配度无需再用相似度估算。未命中或源失败返回 ``None``（调用方回退到书名 + 作者检索）。
    """
    digits = re.sub(r"[^0-9Xx]", "", str(isbn or "")).upper()
    if len(digits) < 10:
        return None
    order = [s for s in (sources or DEFAULT_ORDER) if s in SOURCES] or list(DEFAULT_ORDER)
    opts_map = options or {}
    for name in order:
        fn = _ISBN_FETCHERS.get(name)
        if not fn:
            continue
        try:
            entries = fn(digits, max(1, min(int(limit or 3), 10)), opts_map.get(name) or {})
        except Exception:                       # noqa: BLE001 —— 精确匹配失败即回退普通检索
            continue
        if entries:
            e = entries[0]
            e["isbn"] = digits
            e["exact_isbn"] = True
            e["score"] = 1.0
            return e
    return None


def search(source: str, title: str, author: str, limit: int = 5, opts: dict = None) -> dict:
    """单个源检索。返回 ``{ok, entries, error}`` —— **不抛异常**，失败信息带回给调用方。

    ``opts`` 是**该源的**配置（如 Google Books 的 ``api_key``）。
    """
    fn = _FETCHERS.get(source)
    if not fn or not _clean(title):
        return {"ok": False, "entries": [], "error": "源不可用或书名为空"}
    try:
        entries = fn(_clean(title), _clean(author), max(1, min(int(limit or 5), 20)), opts or {})
    except httpx.HTTPError as e:
        return {"ok": False, "entries": [], "error": f"连接失败：{e}"}
    except Exception as e:                                   # noqa: BLE001 —— 单源失败不能影响别的源
        return {"ok": False, "entries": [], "error": str(e)}
    return {"ok": True, "entries": entries, "error": ""}


def search_all(sources: list, title: str, author: str, limit: int = 5,
               options: dict = None) -> dict:
    """按给定顺序检索多个源，合并候选并按匹配分倒序。

    ``options`` 按源给配置，形如 ``{"googlebooks": {"api_key": "..."}}``。

    返回 ``{entries, sources: {源: {ok, count, error}}, best}``；
    ``best`` 是分数最高的候选（低于调用方阈值时由调用方决定要不要用）。
    """
    order = [s for s in (sources or DEFAULT_ORDER) if s in SOURCES] or list(DEFAULT_ORDER)
    opts_map = options or {}
    merged, report = [], {}
    for name in order:
        res = search(name, title, author, limit, opts_map.get(name))
        report[name] = {"ok": res["ok"], "count": len(res["entries"]), "error": res["error"]}
        for e in res["entries"]:
            e["score"] = score_candidate(title, author, e)
            merged.append(e)
    # 同源同书去重（同一 ISBN 或同名同作者只留分最高的那条）
    seen, uniq = set(), []
    for e in sorted(merged, key=lambda x: -x["score"]):
        key = (e["isbn"] or "") or f'{norm_key(e["title"])}|{norm_key(e["author"])}'
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    return {"entries": uniq, "sources": report, "best": uniq[0] if uniq else None}


# ---------------- 系列级检索（第 12 期 C3）----------------
# ⚠️ 外部源**没有「系列」这个实体**：OpenLibrary 的 search.json 既不返回系列字段、
#    也没有系列详情接口（作者侧能靠 /search/authors.json 拿真实体，系列没有对应物）。
#    所以这里只能「用系列名检索 + 用成员书一致性打分」挑最可信的候选 ——
#    可靠性**天然低于作者侧**，调用方必须把 score 如实展示，低于阈值就别用、不要编造。

def score_against_members(cand: dict, members: list) -> float:
    """候选与**系列成员书**的一致性分：对每本成员书算 :func:`score_candidate`，取最高。

    取**最高**而非平均是刻意的：一个系列常混有不同译本 / 不同版本，
    平均会把「精确命中某一册」这个强信号摊薄成中等分，反而更容易误判。
    """
    best = 0.0
    for m in members or []:
        title = str((m or {}).get("title") or "").strip()
        if not title:
            continue
        s = score_candidate(title, (m or {}).get("author") or "", cand)
        if s > best:
            best = s
    return round(best, 4)


def search_series(series_name: str, members: list, sources: list = None,
                  limit: int = 5, options: dict = None) -> dict:
    """按系列名检索，再按成员书一致性重打分。

    返回 ``{entries, sources, best, members}``；``entries`` 已按一致性分倒序，
    ``best`` 是最高分候选（**可能是 0 分** —— 那就说明没搜到能对上的东西，
    由调用方如实回「未找到」，不要拿个不相关的候选硬凑简介）。
    """
    res = search_all(sources, series_name, "", limit=limit, options=options)
    entries = []
    for e in res["entries"]:
        e = dict(e)
        e["score"] = score_against_members(e, members)
        entries.append(e)
    entries.sort(key=lambda x: -float(x.get("score") or 0.0))
    return {"entries": entries, "sources": res["sources"],
            "best": entries[0] if entries else None, "members": len(members or [])}


def probe(source: str, opts: dict = None) -> dict:
    """连通性自检（设置页用）。用一本几乎必然存在的书探路，返回耗时与结论。"""
    if source not in SOURCES:
        return {"ok": False, "message": f"未知源：{source}", "ms": 0}
    t0 = time.time()
    res = search(source, "Pride and Prejudice", "Jane Austen", 1, opts)
    ms = int((time.time() - t0) * 1000)
    if not res["ok"]:
        return {"ok": False, "message": res["error"] or "不可用", "ms": ms}
    if not res["entries"]:
        return {"ok": False, "message": "能连通但没返回结果（可能被限流）", "ms": ms}
    return {"ok": True, "message": f"可用（{ms} ms）", "ms": ms}
