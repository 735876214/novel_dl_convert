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
import json
import re
import time

import httpx

from .library import norm_key

#: 与其它外呼一致的超时口径：连接 8s、整体 20s
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
#: 目标都在**公网**（与 OPDS/KOReader 的内网相反）→ 保留 httpx 默认的 trust_env（用户可能要代理）
_HEADERS = {"User-Agent": "NovelForge/1.0 (+metadata)", "Accept": "application/json"}
#: 页面抓取型（Amazon / Goodreads / Kobo / Libro.fm / Lubimyczytac）用浏览器 UA + HTML 的 Accept，
#: 否则不少站点会直接回 403 或一份给爬虫看的空页面。**不保证有效**（见注册表 `fragile`）。
_BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def _raise_for_status(r, hints: dict = None) -> None:
    """把常见的失败码翻成**中文**说明，其余交给 httpx 抛。

    只在 :func:`_get_json` / :func:`_get_text` 里调 —— 14 家 provider 的错误口径因此一致，
    不会每家写一遍「429 是什么意思」。``hints`` 允许某家覆盖特定码的说法（如 Google 的 403）。
    """
    if hints and r.status_code in hints:
        raise RuntimeError(hints[r.status_code])
    if r.status_code == 429:
        raise RuntimeError("被限流（429）：稍后再试，或减少启用的元数据来源数量")
    if r.status_code in (401, 403):
        raise RuntimeError(f"被拒绝（{r.status_code}）：可能需要 API Key，或该地区/该站点不支持")
    r.raise_for_status()


def _get_json(url: str, params: dict = None, headers: dict = None, method: str = "GET",
              data: dict = None, hints: dict = None) -> dict:
    """**唯一出网口（JSON）**。14 家 provider 只经它访问公网。

    收口有两个目的：① 契约测试 monkeypatch 这一个函数就能给 14 家喂假响应，
    解析逻辑完全离线可测；② 限流 / 拒绝 / 超时的中文口径只有一处。
    """
    r = httpx.request(method, url, params=params, json=data,
                      headers={**_HEADERS, **(headers or {})}, timeout=TIMEOUT)
    _raise_for_status(r, hints)
    return r.json() or {}


def _get_text(url: str, params: dict = None, headers: dict = None, hints: dict = None) -> str:
    """**唯一出网口（HTML/文本）**。页面抓取型走它（浏览器 UA），失败同样翻中文。"""
    r = httpx.request("GET", url, params=params, timeout=TIMEOUT,
                      headers={**_BROWSER_HEADERS, **(headers or {})})
    _raise_for_status(r, hints)
    return r.text or ""


def _first_json(text: str) -> dict:
    """从「不是纯 JSON」的响应里抠出 JSON（Aladin 的 ``output=js`` 会带前后缀）。

    用 ``raw_decode`` 而不是 ``json.loads``：真实响应常是 ``var x = {...};`` ——
    尾随的分号/注释会让 ``loads`` 整体失败，而 ``raw_decode`` 只吃第一个完整 JSON 值。

    抠不到 / 解析失败 ⇒ ``{}``（调用方回落空列表，绝不让一家把整轮抓取带崩）。
    """
    m = re.search(r"[\[{]", text or "")
    if not m:
        return {}
    try:
        data, _ = json.JSONDecoder().raw_decode(text[m.start():])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _walk_dicts(node) -> list:
    """递归收集嵌套结构里的所有 dict（Kobo 的 ``__NEXT_DATA__`` 用：结构随站点改版而变，
    与其写死路径不如按「同时有 title 且像书的字段」扫）。"""
    out = []
    if isinstance(node, dict):
        out.append(node)
        for v in node.values():
            out.extend(_walk_dicts(v))
    elif isinstance(node, list):
        for v in node:
            out.extend(_walk_dicts(v))
    return out


OPENLIBRARY = "https://openlibrary.org/search.json"
OPENLIBRARY_COVER = "https://covers.openlibrary.org/b/id/{cover}-L.jpg"
GOOGLEBOOKS = "https://www.googleapis.com/books/v1/volumes"
ITUNES = "https://itunes.apple.com/search"
AUDNEXUS = "https://api.audnexus.com/books"
RANOBEDB = "https://ranobedb.org/api/v0"
HARDCOVER = "https://api.hardcover.app/v1/graphql"
COMICVINE = "https://comicvine.gamespot.com/api/volumes/"
ALADIN = "https://www.aladin.co.kr/ttb/api/ItemSearch.aspx"
AMAZON = "https://www.amazon.com/s"
GOODREADS = "https://www.goodreads.com/search"
#: Kobo 的搜索 URL 是「/区域/语言/」两段（机器人在两者不匹配时会拦）—— 两段都可配
KOBO = "https://www.kobo.com/{region}/{language}/search"
#: Audible 的 catalog 接口**按区域域名**分站（没有 marketplace 参数）
AUDIBLE_HOSTS = {
    "us": "api.audible.com",
    "uk": "api.audible.co.uk",
    "de": "api.audible.de",
    "jp": "api.audible.co.jp",
}
#: iTunes 封面：Apple 允许直接改 ``artworkUrl100`` 里的尺寸段
ITUNES_COVER_SIZES = {"high": "1000x1000", "standard": "100x100"}
LIBROFM = "https://libro.fm/search"
LUBIMYCZYTAC = "https://lubimyczytac.pl/szukaj/ksiazki"

#: 提供商分组顺序（第 57 期：设置页「提供商」按组渲染，与上游 BookOrbit 同构）
GROUPS = ("一般书籍目录", "有声读物", "漫画和小说", "极权目录")

#: 源元数据（前端据此渲染分组列表 / 开关 / 配置入口，避免前后端各写一份）。
#:
#: ⚠️ **14 家全部有抓取器**（`IMPLEMENTED` 与 `_FETCHERS` 逐字一致，契约测试钉住）——
#: 也就是说每一家都给开关，没有「能点但点了没用」的行。三档如实标注：
#: - `needs_config=True`：要 API Key / Token 才有效（未填时该行显示「需要设置」，
#:   抓取会回明确的中文错误而不是泛泛失败）；
#: - `fragile=True`：**页面抓取型**，站点改版就可能断，前端给「易失效」徽标；
#: - 其余：公开接口、即开即用。
#:
#: `key_field` = 配置落在 `metadata_fetch.<key_field>`（键名复用既有配置，不新造一份）；
#: fetcher 内部一律读 `opts["api_key"]`，由调用侧按本表拼装（见 `metafetch._options_for`）。
SOURCES = {
    # ---- 一般书籍目录 ----
    "googlebooks": {
        "label": "Google Books",
        "group": "一般书籍目录",
        "home": "https://books.google.com",
        "note": "无需 API Key。简介与封面通常更全；部分地区会被拒绝（返回 403）。",
        "implemented": True,
        "fragile": False,
        # 匿名额度低（实测常撞 429），填 Key 显著改善 —— 属「可选配置」而非「必须」
        "needs_config": False,
        "config_hint": "可选：填 API Key 可显著提高额度（匿名常撞 429）",
        # 行内「配置」项（第 57 期 E 段）：**注册表是唯一真值源**，前端只按 type 渲染。
        # `opt` = 传给 fetcher 的 `opts` 键名（缺省 api_key）；`type` = 控件形态。
        "config_fields": [
            {"key": "googlebooks_api_key", "opt": "api_key", "label": "API 密钥",
             "type": "secret", "placeholder": "未设置（可选）"},
        ],
    },
    "amazon": {
        "label": "Amazon",
        "group": "一般书籍目录",
        "home": "https://www.amazon.com/books",
        "note": "图书搜索页抓取。反爬严格，可能被要求验证或直接返回空，站点改版即失效。",
        "implemented": True,
        "fragile": True,
        "needs_config": False,
        "config_hint": "",
        # Amazon 反爬严格：带上登录后的 Cookie 能显著提高成功率（上游同款做法）。
        # 它**不是必需**（不填也能试），所以 needs_config 仍为 False。
        "config_fields": [
            {"key": "amazon_cookie", "opt": "cookie", "label": "COOKIE", "type": "secret",
             "placeholder": "session-id=…; ubid-main=…; x-main=…",
             "hint": "从浏览器复制 amazon.com 的 Cookie，不必带「Cookie」前缀"},
        ],
    },
    "goodreads": {
        "label": "Goodreads",
        "group": "一般书籍目录",
        "home": "https://www.goodreads.com",
        "note": "搜索页抓取（官方 API 已停发新 Key）。简介与评分齐全，但常触发反爬。",
        "implemented": True,
        "fragile": True,
        "needs_config": False,
        "config_hint": "",
    },
    "hardcover": {
        "label": "Hardcover",
        "group": "一般书籍目录",
        "home": "https://hardcover.app",
        "note": "GraphQL 接口，需要个人 API Token（hardcover.app → 账号设置里生成）。",
        "implemented": True,
        "fragile": False,
        "needs_config": True,
        "config_hint": "需要 Hardcover API Token（网页版账号设置 → Hardcover API）",
        "config_fields": [
            {"key": "hardcover_api_token", "opt": "api_key", "label": "API 密钥", "type": "secret",
             "placeholder": "eyJ...（在 hardcover.app/account/api 获取的令牌）"},
        ],
    },
    "openlibrary": {
        "label": "Open Library",
        "group": "一般书籍目录",
        "home": "https://openlibrary.org",
        "note": "无需 API Key。中文书的覆盖率一般，但语种/年份/ISBN 较规范。",
        "implemented": True,
        "fragile": False,
        "needs_config": False,
        "config_hint": "",
    },
    "itunes": {
        "label": "iTunes",
        "group": "一般书籍目录",
        "home": "https://itunes.apple.com",
        "note": "Apple 公开检索接口（无需 Key）。图书分类以英文为主，有声书与电子书分列。",
        "implemented": True,
        "fragile": False,
        "needs_config": False,
        "config_hint": "",
        "config_fields": [
            {"key": "itunes_cover_resolution", "opt": "resolution", "label": "封面分辨率",
             "type": "select", "options": [
                 {"value": "high", "label": "high（1000×1000，默认）"},
                 {"value": "standard", "label": "standard（100×100，接口原图）"},
             ]},
        ],
    },
    "kobo": {
        "label": "Kobo",
        "group": "一般书籍目录",
        "home": "https://www.kobo.com",
        "note": "搜索页抓取（书店接口非公开）。注：本项目 Kobo **同步**仍不做，这里只是元数据来源。",
        "implemented": True,
        "fragile": True,
        "needs_config": False,
        "config_hint": "",
        # Kobo 的 URL 分段是「/区域/语言/」—— 机器人在区域/语言不匹配时会拦（上游同款做法）
        "config_fields": [
            {"key": "kobo_region", "opt": "region", "label": "国家", "type": "select", "options": [
                {"value": "us", "label": "us"}, {"value": "uk", "label": "uk"},
                {"value": "ca", "label": "ca"}, {"value": "au", "label": "au"},
                {"value": "jp", "label": "jp"},
            ]},
            {"key": "kobo_language", "opt": "language", "label": "语言", "type": "select", "options": [
                {"value": "en", "label": "en"}, {"value": "zh", "label": "zh"},
                {"value": "ja", "label": "ja"},
            ]},
        ],
    },
    # ---- 有声读物 ----
    "audible": {
        "label": "Audible",
        "group": "有声读物",
        "home": "https://www.audible.com",
        "note": "有声书目录（时长 / 演播者 / 系列），走其公开 catalog 接口；区域站点结果不同。",
        "implemented": True,
        "fragile": True,
        "needs_config": False,
        "config_hint": "",
        # Audible 的 catalog 接口按**区域域名**分站（api.audible.com / .co.uk / .de …）
        "config_fields": [
            {"key": "audible_region", "opt": "region", "label": "地区", "type": "select", "options": [
                {"value": "us", "label": "us（api.audible.com）"},
                {"value": "uk", "label": "uk（api.audible.co.uk）"},
                {"value": "de", "label": "de（api.audible.de）"},
                {"value": "jp", "label": "jp（api.audible.co.jp）"},
            ]},
        ],
    },
    "audnexus": {
        "label": "AudNexus",
        "group": "有声读物",
        "home": "https://audnexus.com",
        "note": "有声书元数据聚合（演播者 / 章节 / 系列），公开接口、免 Key。",
        "implemented": True,
        "fragile": False,
        "needs_config": False,
        "config_hint": "",
    },
    "librofm": {
        "label": "Libro.fm",
        "group": "有声读物",
        "home": "https://libro.fm",
        "note": "独立书店有声书平台，搜索页抓取（接口未公开）。",
        "implemented": True,
        "fragile": True,
        "needs_config": False,
        "config_hint": "",
    },
    # ---- 漫画和小说 ----
    "comicvine": {
        "label": "Comic Vine",
        "group": "漫画和小说",
        "home": "https://comicvine.gamespot.com",
        "note": "漫画卷/期元数据，需要免费 API Key（comicvine.gamespot.com/api 申请）。",
        "implemented": True,
        "fragile": False,
        "needs_config": True,
        "config_hint": "需要 Comic Vine API Key（免费申请，注意其限流 200 次/小时）",
        "config_fields": [
            {"key": "comicvine_api_key", "opt": "api_key", "label": "API 密钥", "type": "secret",
             "placeholder": "在 comicvine.gamespot.com/api 免费申请的密钥"},
        ],
    },
    "ranobedb": {
        "label": "RanobeDB",
        "group": "漫画和小说",
        "home": "https://ranobedb.org",
        "note": "轻小说数据库（含系列册序），公开 API v0、免 Key；官方要求 ≤60 次/分钟。",
        "implemented": True,
        "fragile": False,
        "needs_config": False,
        "config_hint": "",
    },
    # ---- 地区性目录（上游分区名）----
    "lubimyczytac": {
        "label": "Lubimyczytac",
        "group": "极权目录",
        "home": "https://lubimyczytac.pl",
        "note": "波兰语书籍目录，搜索页抓取。",
        "implemented": True,
        "fragile": True,
        "needs_config": False,
        "config_hint": "",
    },
    "aladin": {
        "label": "Aladin",
        "group": "极权目录",
        "home": "https://www.aladin.co.kr",
        "note": "韩国 Aladin 书店目录，公开 TTB API，需要 TTBKey。",
        "implemented": True,
        "fragile": False,
        "needs_config": True,
        "config_hint": "需要 Aladin TTBKey（aladin.co.kr 开放 API 页面申请）",
        "config_fields": [
            {"key": "aladin_ttbkey", "opt": "api_key", "label": "TTB 密钥", "type": "secret",
             "placeholder": "ttb...（在 aladin.co.kr 开放 API 页面申请）"},
        ],
    },
}

#: 真正实现（有 fetcher）的源 id —— **必须与 `_FETCHERS` 的键完全一致**（契约测试钉住）。
IMPLEMENTED = ("googlebooks", "amazon", "goodreads", "hardcover", "openlibrary", "itunes",
               "kobo", "audible", "audnexus", "librofm", "comicvine", "ranobedb",
               "lubimyczytac", "aladin")

#: 默认启用顺序：**只留两家最可靠的**（Open Library + Google Books）。
#: 14 家都能用不代表默认全开 —— 每启用一家就多一轮外呼（还容易被限流），
#: 由用户在「元数据来源」页按需打开。
DEFAULT_ORDER = ("openlibrary", "googlebooks")


def is_implemented(source: str) -> bool:
    """该源是否真的能抓（防御性判断：14 家都有 fetcher，恒真；留给将来新增家）。"""
    return source in _FETCHERS


def needs_key(source: str) -> bool:
    """该源是否**必须**填 Key 才能用（未填时抓取回明确错误，前端显示「需要设置」）。"""
    meta = SOURCES.get(source) or {}
    return bool(meta.get("needs_config"))


def config_fields_of(source: str) -> list:
    """该源的**行内配置项**（注册表声明）。空列表 = 没有可配置项 ⇒ 前端不显示「配置」按钮。

    每项形状：``{key, opt, label, type, options?, placeholder?, hint?}``
    —— `key` 是 `metadata_fetch` 下的配置键名，`opt` 是传给 fetcher 的 `opts` 键名
    （缺省 ``api_key``），`type` ∈ ``secret | select``（secret 一律掩码回显）。
    """
    return [dict(f) for f in ((SOURCES.get(source) or {}).get("config_fields") or [])]


def secret_fields() -> tuple:
    """所有 **secret** 配置键名（掩码与 `has_<键名>` 回显按它循环，别漏一家）。"""
    return tuple(f["key"] for meta in SOURCES.values()
                 for f in (meta.get("config_fields") or []) if f.get("type") == "secret")


def key_field_of(source: str) -> str:
    """该源的**主密钥**键名（= 第一个 secret 项）；没有则空串。

    保留这个入口是为了兼容既有调用（掩码 / metafetch / probe / 系列抓取都按
    「一家一个主密钥」写的）；但它现在是**从 `config_fields` 派生**的，注册表里不再单独写一份。
    """
    for f in config_fields_of(source):
        if f.get("type") == "secret":
            return str(f["key"])
    return ""


def options_for(mf: dict, sources: list) -> dict:
    """按注册表给启用源拼检索配置：``{源: {opt 键: 值}}``。

    值取每个配置项的 ``key`` 在 `metadata_fetch` 下的配置；**空值不进 opts** ——
    fetcher 自带默认（如 iTunes 的分辨率、Kobo 的区域），缺键与空串行为一致。
    书籍抓取（`metafetch.plan` / `online_candidate`）与系列抓取（`series_meta`）共用这一份。
    """
    out = {}
    for sid in sources or []:
        opts = {}
        for f in config_fields_of(sid):
            val = str((mf or {}).get(f["key"]) or "").strip()
            if val:
                opts[str(f.get("opt") or "api_key")] = val
        if opts:
            out[sid] = opts
    return out


def provider_catalog() -> list:
    """提供商目录（注册表 → 列表，按 `GROUPS` 分组顺序）。前端「元数据来源」页直接吃它。

    顺带把 `config_fields` 的**头一项**派生成 `key_field` / `key_label` / `key_placeholder`：
    前端旧字段名照旧可用，而注册表只维护 `config_fields` 一份声明。
    """
    order = {g: i for i, g in enumerate(GROUPS)}
    items = []
    for sid, meta in SOURCES.items():
        fields = config_fields_of(sid)
        head = fields[0] if fields else {}
        items.append({**meta, "id": sid, "config_fields": fields,
                      "key_field": key_field_of(sid),
                      "key_label": head.get("label") or "API 密钥",
                      "key_placeholder": head.get("placeholder") or "未设置"})
    items.sort(key=lambda x: (order.get(x.get("group") or "", 99), list(SOURCES).index(x["id"])))
    return items
#: 语言代码归一：源里见过 "chi"/"zh"/"zh-CN"/"eng"… 统一成本项目用的短码
_LANG_MAP = {
    "chi": "zh", "zho": "zh", "zh-cn": "zh", "zh-tw": "zh", "zh-hans": "zh", "zh-hant": "zh",
    "eng": "en", "en-us": "en", "en-gb": "en", "jpn": "ja", "kor": "ko",
    "fre": "fr", "fra": "fr", "ger": "de", "deu": "de", "rus": "ru", "spa": "es",
    # 第 57 期：有声书/Apple 那几家回的是**全称**（"english" / "Chinese"），不归一就会把
    # "english" 原样写进书目（界面显示成 English 且与其它源的口径不一致）
    "english": "en", "chinese": "zh", "japanese": "ja", "korean": "ko",
    "french": "fr", "german": "de", "russian": "ru", "spanish": "es",
    "italian": "it", "portuguese": "pt", "polish": "pl", "arabic": "ar", "dutch": "nl",
}


def _clean(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


#: 少数源（实测 iTunes，Goodreads/Amazon 的抓取也可能）**返回带 HTML 的简介**：
#: ``<b><b>Frank Herbert's classic masterpiece…`` —— 直接落库会把标签带进书目，
#: 界面上就是一串 ``<b>``。所以候选入口统一剥标签 + 还原实体。
_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_html(text) -> str:
    """剥掉 HTML 标签并还原常见实体（**不是**完整的 HTML 解析，够用且零依赖）。"""
    if text is None:
        return ""
    s = _HTML_TAG.sub(" ", str(text))
    for ent, ch in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                    ("&quot;", '"'), ("&#39;", "'"), ("&apos;", "'")):
        s = s.replace(ent, ch)
    return _clean(s)


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
    """统一候选结构 —— 前端与写回逻辑都只认这一种形状。

    ⚠️ 文本字段一律走 :func:`_strip_html`（实测 iTunes 的简介带 ``<b>`` 标签，
    落库会把标签带进书目）；`tags` 里也见过带标签的值，同样处理。
    """
    return {
        "source": source,
        "title": _strip_html(kw.get("title")),
        "author": _strip_html(kw.get("author")),
        "publisher": _strip_html(kw.get("publisher")),
        "year": _year_of(kw.get("year")),
        "language": _lang_of(kw.get("language")),
        "isbn": _strip_html(kw.get("isbn")),
        "description": _strip_html(kw.get("description")),
        "tags": [t for t in (_strip_html(x) for x in (kw.get("tags") or [])) if t][:8],
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
    data = _get_json(OPENLIBRARY, params=params)
    return [_ol_entry(d) for d in (data.get("docs") or [])[:limit] if isinstance(d, dict)]


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
    data = _get_json(GOOGLEBOOKS, params=params, hints={
        429: "被限流（429）：稍后再试，或在设置里填 Google Books API Key 提高额度",
        # 常见于地区限制：Google 返回 403 且 reason 为 "The user location is not supported"
        403: "该地区不支持（Google 返回 403）",
    })
    return [_gb_entry(it) for it in ((data.get("items") or [])[:limit])
            if isinstance(it, dict)]


# ---------------- iTunes（公开 JSON，免 Key）----------------

def _itunes_entry(it: dict, size: str = "1000x1000") -> dict:
    """iTunes 单条 result → 统一候选。

    图书检索（``entity=ebook``）用 ``trackName``，有声书/合集可能只有 ``collectionName``；
    ``artworkUrl100`` 的尺寸段可任改（Apple 允许），默认取 1000×1000。
    """
    art = _clean(it.get("artworkUrl100"))
    return _entry(
        "itunes",
        title=it.get("trackName") or it.get("collectionName"),
        author=it.get("artistName"),
        publisher=it.get("publisher") or it.get("sellerName"),
        year=it.get("releaseDate"),
        language="",                    # 该接口不返回语言，别瞎猜
        description=it.get("description"),
        tags=it.get("genres") or [],
        cover_url=art.replace("100x100", size) if art else "",
        raw_id=it.get("trackId") or it.get("collectionId") or "",
    )


def _search_itunes(title: str, author: str, limit: int, opts: dict) -> list:
    term = f"{_clean(title)} {_clean(author)}".strip()
    # 封面分辨率（行内可配）：只认注册表给的取值，给了没见过的值就回落 high
    size = ITUNES_COVER_SIZES.get(_clean((opts or {}).get("resolution")).lower(), "1000x1000")
    data = _get_json(ITUNES, params={"term": term, "entity": "ebook",
                                     "limit": str(limit), "media": "ebook"})
    return [_itunes_entry(it, size) for it in (data.get("results") or [])[:limit]
            if isinstance(it, dict)]


# ---------------- AudNexus（有声书聚合，公开接口）----------------

def _audnexus_entry(d: dict) -> dict:
    """AudNexus 单条 → 统一候选（``authors``/``narrators`` 都是对象数组）。"""
    authors = d.get("authors") or []
    author = ", ".join(a.get("name") for a in authors
                       if isinstance(a, dict) and a.get("name")) or _clean(d.get("author"))
    genres = [g.get("name") if isinstance(g, dict) else g for g in (d.get("genres") or [])]
    return _entry(
        "audnexus",
        title=d.get("title") or d.get("name"),
        author=author,
        publisher=d.get("publisherName") or d.get("publisher"),
        year=d.get("releaseDate") or d.get("publicationDatetime"),
        language=d.get("language"),
        description=d.get("description") or d.get("summary"),
        tags=genres,
        cover_url=d.get("image") or d.get("imageUrl") or "",
        raw_id=d.get("asin") or "",
    )


def _search_audnexus(title: str, author: str, limit: int, opts: dict) -> list:
    data = _get_json(AUDNEXUS, params={"title": _clean(title), "author": _clean(author),
                                       "region": "us"})
    # 检索接口的形状随版本变过：列表键可能是 books / results，也可能直接回单本
    items = data.get("books") or data.get("results") or ([data] if data.get("asin") else [])
    return [_audnexus_entry(d) for d in items[:limit] if isinstance(d, dict)]


# ---------------- RanobeDB（轻小说库，公开 API v0）----------------

def _ranobedb_entry(d: dict) -> dict:
    """RanobeDB 单条 → 统一候选（**两段式**：列表无作者/简介，详情才有）。

    ⚠️ 封面只给了 ``filename``，官方文档没公布 CDN 前缀 → **留空**而不是拼一个猜的 URL
    （宁可没有封面，也不要给一个 404 的图）。
    """
    staff = [s for ed in (d.get("editions") or []) for s in (ed.get("staff") or [])]
    author = next((s.get("name") for s in staff if s.get("role_type") == "author"), "")
    if not author and staff:
        author = staff[0].get("name") or ""
    pubs = d.get("publishers") or []
    tags = [t.get("name") if isinstance(t, dict) else t for t in (d.get("tags") or [])]
    return _entry(
        "ranobedb",
        title=d.get("title") or d.get("romaji"),
        author=author,
        publisher=(pubs[0].get("name") if pubs and isinstance(pubs[0], dict) else ""),
        year=d.get("c_release_date") or d.get("start_date"),
        language=d.get("lang"),
        description=d.get("description"),
        tags=tags,
        raw_id=d.get("id") or "",
    )


def _search_ranobedb(title: str, author: str, limit: int, opts: dict) -> list:
    data = _get_json(f"{RANOBEDB}/books", params={"q": _clean(title), "limit": str(limit)})
    out = []
    for b in (data.get("books") or [])[:limit]:
        if not isinstance(b, dict):
            continue
        bid = b.get("id")
        detail = b
        if bid is not None:
            try:
                # 逐本补详情（列表不给作者/简介/出版社）。**单本失败只丢这一本**，
                # 用列表里已有的字段顶上 —— 一轮抓取不该被其中一本书拖垮。
                fetched = _get_json(f"{RANOBEDB}/book/{bid}")
                if isinstance(fetched, dict) and fetched:
                    detail = {**b, **fetched}
            except Exception:                       # noqa: BLE001
                pass
        out.append(_ranobedb_entry(detail))
    return out


# ---------------- Hardcover（GraphQL，需 Token）----------------

_HARDCOVER_Q = """
query Search($q: String!, $n: Int!) {
  books(where: {title: {_ilike: $q}}, limit: $n, order_by: {users_count: desc}) {
    title
    description
    release_date
    slug
    contributions { author { name } }
    publisher { name }
    image { url }
  }
}
"""


def _hardcover_entry(b: dict) -> dict:
    authors = [c.get("author", {}).get("name") for c in (b.get("contributions") or [])
               if isinstance(c, dict) and isinstance(c.get("author"), dict)]
    return _entry(
        "hardcover",
        title=b.get("title"),
        author=next((a for a in authors if a), ""),
        publisher=((b.get("publisher") or {}).get("name") or ""),
        year=b.get("release_date"),
        description=b.get("description"),
        cover_url=((b.get("image") or {}).get("url") or ""),
        raw_id=b.get("slug") or "",
    )


def _search_hardcover(title: str, author: str, limit: int, opts: dict) -> list:
    token = _clean((opts or {}).get("api_key"))
    if not token:
        raise RuntimeError("需要 API Key：请在「元数据来源」里填 Hardcover API Token")
    data = _get_json(HARDCOVER, method="POST", headers={"Authorization": f"Bearer {token}"},
                     data={"query": _HARDCOVER_Q,
                           "variables": {"q": f"%{_clean(title)}%", "n": int(limit)}})
    books = ((data.get("data") or {}).get("books") or [])
    return [_hardcover_entry(b) for b in books[:limit] if isinstance(b, dict)]


# ---------------- Comic Vine（需 API Key）----------------

def _comicvine_entry(v: dict) -> dict:
    return _entry(
        "comicvine",
        title=v.get("name"),
        publisher=((v.get("publisher") or {}).get("name") or ""),
        year=v.get("start_year"),
        description=v.get("description"),
        cover_url=((v.get("image") or {}).get("medium_url")
                   or (v.get("image") or {}).get("thumb_url") or ""),
        raw_id=v.get("id") or "",
    )


def _search_comicvine(title: str, author: str, limit: int, opts: dict) -> list:
    key = _clean((opts or {}).get("api_key"))
    if not key:
        raise RuntimeError("需要 API Key：请在「元数据来源」里填 Comic Vine API Key")
    data = _get_json(COMICVINE, params={
        "api_key": key, "format": "json", "filter": f"name:{_clean(title)}",
        "limit": str(limit),
        "field_list": "name,description,publisher,start_year,image,id",
    })
    results = data.get("results") or []
    return [_comicvine_entry(v) for v in results[:limit] if isinstance(v, dict)]


# ---------------- Aladin（韩国书店 TTB 接口，需 TTBKey）----------------

def _aladin_entry(it: dict) -> dict:
    return _entry(
        "aladin",
        title=it.get("title"),
        author=it.get("author"),
        publisher=it.get("publisher"),
        year=it.get("pubDate"),
        isbn=it.get("isbn13") or it.get("isbn"),
        description=it.get("description"),
        tags=[t for t in _clean(it.get("categoryName")).split(">") if t],
        cover_url=it.get("cover"),
        raw_id=it.get("itemId") or "",
    )


def _search_aladin(title: str, author: str, limit: int, opts: dict) -> list:
    key = _clean((opts or {}).get("api_key"))
    if not key:
        raise RuntimeError("需要 TTBKey：请在「元数据来源」里填 Aladin TTBKey")
    text = _get_text(ALADIN, params={
        "ttbkey": key, "Query": _clean(title), "QueryType": "Title",
        "MaxResults": str(limit), "start": "1", "SearchTarget": "Book",
        "output": "js", "Version": "20131101",
    }, headers={"Accept": "application/json"})
    items = _first_json(text).get("item") or []
    return [_aladin_entry(it) for it in items[:limit] if isinstance(it, dict)]


# ---------------- Amazon / Goodreads / Kobo / Audible / Libro.fm / Lubimyczytac ----------------
# ⚠️ 这六家是**页面抓取型**（注册表 `fragile=True`）：没有公开接口，只能解析 HTML，
#    站点改版就可能失效。纪律：**任何解析失败一律回落空列表** —— 宁可这家没结果，
#    也绝不能让它的异常打断整轮抓取（调用方 `search()` 已兜，但这里也自己兜一层）。

def _search_amazon(title: str, author: str, limit: int, opts: dict) -> list:
    # 行内配的 Cookie（可选）：Amazon 的反爬对「带登录 Cookie 的请求」宽松得多。
    # 只在真填了时才带这个头 —— 空串会变成一个空 Cookie 头，反而更容易被拦。
    cookie = _clean((opts or {}).get("cookie"))
    html = _get_text(AMAZON, params={"k": f"{_clean(title)} {_clean(author)}".strip(),
                                     "i": "stripbooks"},
                     headers={"Cookie": cookie} if cookie else None)
    out = []
    for asin, block in re.findall(r'data-asin="([A-Z0-9]{10})"(.*?)(?=data-asin=|$)', html, re.S):
        t = re.search(r'<span class="a-size-(?:medium|base-2|large) a-color-base a-text-normal">'
                      r'([^<]+)</span>', block)
        if not t:
            continue
        a = re.search(r'class="a-size-base[^"]*"[^>]*>([^<]+)</span>', block)
        out.append(_entry("amazon", title=t.group(1), author=a.group(1) if a else "",
                          raw_id=asin))
        if len(out) >= limit:
            break
    return out


def _search_goodreads(title: str, author: str, limit: int, opts: dict) -> list:
    html = _get_text(GOODREADS, params={"q": f"{_clean(title)} {_clean(author)}".strip()})
    out = []
    for block in re.findall(r"<tr itemscope.*?</tr>", html, re.S):
        t = re.search(r'class="bookTitle"[^>]*>\s*<span[^>]*>([^<]+)</span>', block)
        if not t:
            continue
        a = re.search(r'class="authorName"[^>]*>\s*<span[^>]*>([^<]+)</span>', block)
        u = re.search(r'href="(/book/show/[^"]+)"', block)
        out.append(_entry("goodreads", title=t.group(1), author=a.group(1) if a else "",
                          raw_id=(u.group(1) if u else "")))
        if len(out) >= limit:
            break
    return out


def _search_kobo(title: str, author: str, limit: int, opts: dict) -> list:
    """Kobo 搜索结果页把数据塞在 ``__NEXT_DATA__`` 里 → 抠 JSON 后按「像书的 dict」扫。

    URL 的「区域 / 语言」两段取行内配置（默认 us/en）—— 上游同款做法：机器人对
    「区域与语言不匹配」的请求会拦。
    """
    o = opts or {}
    html = _get_text(
        KOBO.format(region=_clean(o.get("region")) or "us",
                    language=_clean(o.get("language")) or "en"),
        params={"query": _clean(title)},
    )
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return []
    out = []
    for d in _walk_dicts(data):
        t = _clean(d.get("title"))
        # 「像书」= 有标题 + 有作者类字段 + 有详情链接（避免把页面上的按钮文案当书）
        if not t or not (d.get("authors") or d.get("contributor") or d.get("authorsText")):
            continue
        if not (d.get("url") or d.get("href") or d.get("slug")):
            continue
        authors = d.get("authors")
        if isinstance(authors, list):
            author_name = ", ".join(
                a.get("name") if isinstance(a, dict) else _clean(a) for a in authors
            ) if authors else _clean(d.get("authorsText"))
        else:
            author_name = _clean(authors or d.get("authorsText"))
        out.append(_entry("kobo", title=t, author=author_name,
                          publisher=_clean(d.get("publisher")),
                          description=_clean(d.get("description")),
                          cover_url=_clean(d.get("imageUrl") or d.get("cover")),
                          raw_id=_clean(d.get("url") or d.get("slug"))))
        if len(out) >= limit:
            break
    return out


def _search_audible(title: str, author: str, limit: int, opts: dict) -> list:
    """Audible 走 catalog 接口（JSON）而不是抓页面：更稳，但仍是**非公开**接口 → fragile。

    区域（行内可配，默认 us）决定打哪个分站域名；没见过的取值回落 us。
    """
    region = _clean((opts or {}).get("region")).lower() or "us"
    host = AUDIBLE_HOSTS.get(region, AUDIBLE_HOSTS["us"])
    data = _get_json(f"https://{host}/1.0/catalog/products", params={
        "keywords": _clean(title), "num_results": str(limit),
        "products_sort_by": "Relevance",
        "response_groups": "product_desc,contributors,media,series,publisher",
    })
    out = []
    for p in (data.get("products") or [])[:limit]:
        if not isinstance(p, dict):
            continue
        authors = ", ".join(a.get("name") for a in (p.get("authors") or [])
                            if isinstance(a, dict) and a.get("name"))
        imgs = p.get("product_images") or {}
        cover = imgs.get("500") or imgs.get("1000") or next(iter(imgs.values()), "") \
            if isinstance(imgs, dict) else ""
        out.append(_entry("audible", title=p.get("title"), author=authors,
                          publisher=p.get("publisher_name") or p.get("publisher_summary"),
                          year=p.get("publication_datetime") or p.get("release_date"),
                          language=p.get("language"),
                          description=p.get("publisher_summary"),
                          tags=[s.get("title") for s in (p.get("series") or [])
                                if isinstance(s, dict) and s.get("title")],
                          cover_url=cover, raw_id=p.get("asin") or ""))
    return out


def _search_librofm(title: str, author: str, limit: int, opts: dict) -> list:
    html = _get_text(LIBROFM, params={"q": _clean(title), "searchby": "keyword"})
    out = []
    # 结果卡片：标题链接 + 作者链接（类名以 audiobook / search-result 打头，做两种兜底）
    for href, t in re.findall(
            r'<a[^>]+class="[^"]*(?:audiobook|search-result)[^"]*__title[^"]*"[^>]*href="([^"]+)"'
            r'[^>]*>([^<]+)</a>', html)[:limit]:
        out.append(_entry("librofm", title=t, raw_id=href))
    if out and not author:
        return out
    if out:
        authors = re.findall(r'class="[^"]*(?:audiobook|search-result)[^"]*__author[^"]*"[^>]*>'
                             r'([^<]+)<', html)
        for i, it in enumerate(out[:len(authors)]):
            it["author"] = _clean(authors[i])
    return out


def _search_lubimyczytac(title: str, author: str, limit: int, opts: dict) -> list:
    html = _get_text(LUBIMYCZYTAC, params={"phrase": _clean(title)})
    titles = re.findall(r'class="authorAllBooks__singleTextTitle[^"]*"[^>]*href="([^"]+)"'
                        r'[^>]*>([^<]+)<', html)
    authors = re.findall(r'class="authorAllBooks__singleTextAuthor[^"]*"[^>]*>([^<]+)<', html)
    out = []
    for i, (href, t) in enumerate(titles[:limit]):
        out.append(_entry("lubimyczytac", title=t,
                          author=authors[i] if i < len(authors) else "", raw_id=href))
    return out


_FETCHERS = {
    "openlibrary": _search_openlibrary,
    "googlebooks": _search_googlebooks,
    "itunes": _search_itunes,
    "audnexus": _search_audnexus,
    "ranobedb": _search_ranobedb,
    "hardcover": _search_hardcover,
    "comicvine": _search_comicvine,
    "aladin": _search_aladin,
    "amazon": _search_amazon,
    "goodreads": _search_goodreads,
    "kobo": _search_kobo,
    "audible": _search_audible,
    "librofm": _search_librofm,
    "lubimyczytac": _search_lubimyczytac,
}


# ---------------- ISBN 精确匹配（第 8 期 D4）----------------
# 有 ISBN 的书直接按 ISBN 查，命中即为**同一版本**，比「书名+作者」相似度可靠得多。
# 放在 `_FETCHERS` 之后是为了「一张表看全 14 家」——这两家同样只经 `_get_json` 出网。

def _search_isbn_openlibrary(isbn: str, limit: int, opts: dict) -> list:
    data = _get_json(OPENLIBRARY, params={"q": f"isbn:{isbn}", "limit": str(limit),
                                          "fields": _OL_FIELDS})
    return [_ol_entry(d) for d in ((data.get("docs") or [])[:limit]) if isinstance(d, dict)]


def _search_isbn_googlebooks(isbn: str, limit: int, opts: dict) -> list:
    params = {"q": f"isbn:{isbn}", "maxResults": str(limit)}
    api_key = _clean((opts or {}).get("api_key"))
    if api_key:
        params["key"] = api_key
    data = _get_json(GOOGLEBOOKS, params=params, hints={403: "该地区不支持（Google 返回 403）"})
    return [_gb_entry(it) for it in ((data.get("items") or [])[:limit]) if isinstance(it, dict)]


#: 有 ISBN 精确检索能力的家（其余没有就跳过，由调用方回退「书名 + 作者」检索）
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
