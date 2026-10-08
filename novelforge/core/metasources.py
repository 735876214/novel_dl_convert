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
import hashlib
import json
import logging
import re
import time
from concurrent import futures
from html import unescape as html_unescape

import httpx

from .. import config
from . import netdiag
from .library import norm_key
from .sources import Provider, kinds
from .sources import registry as _src_registry

_log = logging.getLogger("novelforge")

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

    只在 :func:`_get_json` / :func:`_get_text` 里调 —— 13 家 provider 的错误口径因此一致，
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
    """**唯一出网口（JSON）**。13 家 provider 只经它访问公网。

    收口有两个目的：① 契约测试 monkeypatch 这一个函数就能给 13 家喂假响应，
    解析逻辑完全离线可测；② 限流 / 拒绝 / 超时的中文口径只有一处。
    """
    r = httpx.request(method, url, params=params, json=data,
                      headers={**_HEADERS, **(headers or {})}, timeout=TIMEOUT)
    _raise_for_status(r, hints)
    return r.json() or {}


def _get_text(url: str, params: dict = None, headers: dict = None, hints: dict = None) -> str:
    """**唯一出网口（HTML/文本）**。页面抓取型走它（浏览器 UA），失败同样翻中文。

    顺带识别**反爬拦截页**（「请完成人机验证」这类）：站点这时回的是 **200 + 验证页**，
    若不当场判掉，解析器只会「解析不到结果」，用户就分不清「站点改版」与「被拦截」——
    这两件事要做的处置完全不同（前者等修复，后者降频率 / 带 Cookie）。
    """
    r = httpx.request("GET", url, params=params, timeout=TIMEOUT,
                      headers={**_BROWSER_HEADERS, **(headers or {})})
    _raise_for_status(r, hints)
    text = r.text or ""
    low = text[:4000].lower()
    # ⚠️ **AWS WAF 挑战页**（第 101 期真机核验）：Goodreads 与 Libro.fm **同一套机制** ——
    # 两家都在 AWS WAF 后面，命中时回一段约 2 KB 的挑战页（实测含 ``window.gokuProps``
    # + ``awswaf.com/…/challenge.js`` + ``<div id="challenge-container">``）。
    # ⚠️ 命中与否取决于 **IP 信誉**，同一 URL 换个时刻可能就正常 —— 所以文案要写成
    # 「可重试 / 降频 / 带 Cookie」，**不是**「站点挂了或改版了」，否则用户会白等修复。
    # ⚠️ 这段判据要放在 HTTP 202 兜底**之前**：Libro.fm 回的就是 202 + 这个页，
    # 若先命中 202 分支，用户看到的会是笼统的「HTTP 202 挑战页」而认不出是 WAF。
    if "gokuprops" in low or "awswaf" in low:
        raise RuntimeError("被反爬拦截（AWS WAF 挑战页）：Goodreads / Libro.fm 走同一套防护，"
                           "取决于出口 IP 信誉 —— 稍后重试、降低频率，或按需提供 Cookie")
    # HTTP 202 + 极小响应体 = 站点的 JS 挑战页。它**不是** 4xx/5xx，若不在这里判掉，
    # 解析器只会得到「解析不到结果」，用户就分不清「站点改版」与「被拦」——
    # 两者要做的事完全不同。这一条是**兜底**，覆盖「202 但没有 WAF 特征」的别的站点。
    if r.status_code == 202:
        raise RuntimeError("被反爬拦截（站点返回 HTTP 202 挑战页）：稍后重试或降低频率")
    for marker in ("validatecaptcha", "enter the characters you see below", "robot check",
                   "g-recaptcha", "cf-challenge", "checking your browser",
                   "attention required! | cloudflare", "人机验证", "访问验证"):
        if marker in low:
            raise RuntimeError("被反爬拦截（验证码 / 机器人校验）：该来源需要降低频率，"
                               "或按需提供 Cookie")
    # ⚠️ Amazon 的「JS 校验 + 跳转」页（第 99 期真机核验）：它**不含任何验证码关键词**，
    # 内容是 `200 OK` + 一段 `<meta http-equiv="refresh" content="5; URL='…&bm-verify=…'">`
    # + 混淆 `<script>var i=…</script>` + 空 `<iframe>`，约 2.3 KB。
    # 不在这里判掉的话，这家只会安静地返回 0 条，用户分不清「站点改版」与「被拦」——
    # 正是本函数要消除的那种混淆。判据取站点专属的 `bm-verify`（真结果页不含，实测）。
    if "bm-verify" in text[:4000]:
        raise RuntimeError("被反爬拦截（Amazon 的 JS 校验页）：该来源需要降低频率，"
                           "或按需提供 Cookie")
    return text


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


#: OpenLibrary 的站点根：检索（`/search.json`）与按 works key 取详情（`/works/OL…W.json`）
#: 是同一台主机 —— 主机名只写一次，两处派生（第 102 期）。
OPENLIBRARY_BASE = "https://openlibrary.org"
OPENLIBRARY = OPENLIBRARY_BASE + "/search.json"
OPENLIBRARY_COVER = "https://covers.openlibrary.org/b/id/{cover}-L.jpg"
GOOGLEBOOKS = "https://www.googleapis.com/books/v1/volumes"
ITUNES_BASE = "https://itunes.apple.com"
ITUNES = ITUNES_BASE + "/search"
#: iTunes 按 ``trackId`` 取详情（与检索同主机、同响应形状，只有参数不同）
ITUNES_LOOKUP = ITUNES_BASE + "/lookup"
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
#: Audible catalog 端点：检索尾段为空，按 ASIN 取详情尾段是 ``/ASIN``（同一形状）。
AUDIBLE_CATALOG = "https://{host}/1.0/catalog/products{tail}"
#: ⚠️ 检索与详情**必须逐字同组**（第 99 期真机核验：带一个非法组名（``publisher``）接口直接回
#: ``400``，整家永远 0 结果）—— 所以收口成一处常量，别让两条路径各写一份。
AUDIBLE_RESPONSE_GROUPS = "product_desc,contributors,media,series"
#: iTunes 封面：Apple 允许直接改 ``artworkUrl100`` 里的尺寸段
ITUNES_COVER_SIZES = {"high": "1000x1000", "standard": "100x100"}
LIBROFM = "https://libro.fm/search"
LUBIMYCZYTAC = "https://lubimyczytac.pl/szukaj/ksiazki"

#: 提供商分组顺序（第 57 期：设置页「提供商」按组渲染，与上游 BookOrbit 同构）
GROUPS = ("一般书籍目录", "有声读物", "漫画和小说", "极权目录")

#: 源元数据（前端据此渲染分组列表 / 开关 / 配置入口，避免前后端各写一份）。
#:
#: ⚠️ **13 家全部有抓取器**（`IMPLEMENTED` 与 `_FETCHERS` 逐字一致，契约测试钉住）——
#: 也就是说每一家都给开关，没有「能点但点了没用」的行。三档如实标注：
#: - `needs_config=True`：要 API Key / Token 才有效（未填时该行显示「需要设置」，
#:   抓取会回明确的中文错误而不是泛泛失败）；
#: - `fragile=True`：**页面抓取型**，站点改版就可能断，前端给「易失效」徽标；
#: - 其余：公开接口、即开即用。
#:
#: `key_field` = 配置落在 `metadata_fetch.<key_field>`（键名复用既有配置，不新造一份）；
#: fetcher 内部一律读 `opts["api_key"]`，由调用侧按本表拼装（见 `metafetch._options_for`）。
#: 源元数据（前端据此渲染分组列表 / 开关 / 配置入口，避免前后端各写一份）。
#:
#: ⚠️ **本表由 `core/sources/registry.py` 的 `DECLARED` 派生**（第 102 期）——
#: 一家源的 label / group / note / fragile / needs_config / config_fields 只写在那份声明里，
#: 这里不再手写。改一家源请改声明，别改这里（改了会在 import 期被覆盖）。
#:
#: 保持 `dict[str, dict]` 形状是**刻意的兼容边界**：`SOURCES[id]["label"]` 这种取法在
#: `server.py` / `metafetch` / `metascore` / 前端契约里到处在用（`provider_catalog()`
#: 直接 `{**meta}`）—— 第 102 期只收口声明，**不动取法**。
SOURCES = {
    p.id: {
        "label": p.label,
        "group": p.group,
        "home": p.home,
        "note": p.note,
        "implemented": True,
        "fragile": p.fragile,
        "needs_config": p.needs_config,
        "config_hint": p.config_hint,
        **({"config_fields": [dict(f) for f in p.config_fields]} if p.config_fields else {}),
        # 领域轴（第 102 期新增）：这家供给的是电子书 / 漫画 / 动画·轻小说 / 有声书。
        # 界面据此分组并可如实说明「这家不提供 ISBN」，不参与计分（见 core/sources/kinds.py）。
        "kind": p.kind,
        # 限流 `(次数, 秒)`；空 = 不限。`search()` 在调用 fetcher 前据此补足间隔。
        "rate_limit": list(p.rate_limit),
        # 检索缓存秒数；0 = 不缓存
        "cache_ttl": p.cache_ttl,
    }
    for p in _src_registry.DECLARED
}


#: 真正实现（有 fetcher）的源 id —— **由 `_FETCHERS` 派生**（第 102 期：不再手写一份，
#: 两份手写表迟早不一致）。契约测试仍钉住「声明里有 fetch 的 == 这张表」。
#:
#: ⚠️ 这里先给**占位**，真实值在**文件末尾**的 `_derive_final()` 里填 —— 因为 `_FETCHERS`
#: 及其引用的 `_search_*` 全定义在文件后段，此处直接引用会 import 期 `NameError`。
IMPLEMENTED = ()

#: 有「按 ID 取详情」通道的家（第 102 期）。同样是占位，末尾由 `_derive_final()` 填。
#: 公开它是因为 `metafetch` 要据此决定「库里记过 id 时走不走精确键」—— 私有绑定表
#: `_DETAIL_FETCHERS` 是产物，不是接口。
DETAIL_SOURCES = ()

#: 默认启用顺序：**只留两家最可靠的**（Open Library + Google Books）。
#: 13 家都能用不代表默认全开 —— 每启用一家就多一轮外呼（还容易被限流），
#: 由用户在「元数据来源」页按需打开。
DEFAULT_ORDER = ("openlibrary", "googlebooks")


def is_implemented(source: str) -> bool:
    """该源是否真的能抓（防御性判断：13 家都有 fetcher，恒真；留给将来新增家）。"""
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

    这是 `config_fields_of()` 的**派生读取器**（掩码 / metafetch / probe / 系列抓取都按
    「一家一个主密钥」写的）—— 注册表里**不**单独存一份键名，加字段只改 `config_fields`。
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
                      "key_placeholder": head.get("placeholder") or "未设置",
                      # 语种亲和（第 60 期）：界面可标「韩语 / 英语」或「多语种」，
                      # 让用户看得懂「按语种重排」会怎么排
                      "langs": list(LANG_AFFINITY.get(sid) or []),
                      "lang_broad": sid in LANG_BROAD})
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
    """剥掉 HTML 标签并还原实体（**不是**完整的 HTML 解析，够用且不必引第三方解析器）。

    实体还原用标准库 :func:`html.unescape`：手写对照表会漏（实测 Amazon 书名里有
    ``Frank Herbert&#x27;s``，只列几个常见实体的话它会原样留在书名里）。
    """
    if text is None:
        return ""
    return _clean(html_unescape(_HTML_TAG.sub(" ", str(text))))


def _soup(html: str):
    """把 HTML 解析成 BeautifulSoup 树；**没装 bs4 就返回 None**（调用方如实回落空列表）。

    bs4 已在 `requirements.txt` 里显式声明（书源引擎的 CSS 选择器通道
    `sources/rules.py::_selspec_nodes` 就用它），正常环境一定在；这里仍按
    「可选依赖缺失要**如实降级**、不静默假装成功」的既有口径兜一层 ——
    缺了就是这家源取不到值，而不是抛异常打断整轮抓取。
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:                                      # pragma: no cover - 依赖缺失分支
        return None
    try:
        return BeautifulSoup(html or "", "html.parser")
    except Exception:                                        # noqa: BLE001 —— 解析器不认的内容按「取不到」处理
        return None


def _year_of(value) -> str:
    """从各种形态里抠出 4 位年份（源里可能是 2008 / '2008-05-01' / 2008.0）。"""
    m = re.search(r"(1[5-9]\d{2}|20\d{2})", str(value or ""))
    return m.group(1) if m else ""


#: 卷号只认这几种形态：``1`` / ``12`` / ``1.5``（calibre 的 series_index 是浮点文本）
_SERIES_INDEX = re.compile(r"^\d+(?:\.\d+)?$")


def _series_index_of(value) -> str:
    """系列卷号（第 103 期）：**只认数字**，其余留空。

    为什么不当普通文本照收：卷号会参与**命名规则**（``{series_index}``）、缺册判定
    与 Komga 的 ``seriesIndex``，一个「Kindle Edition」这样的文本值会被当成「第几卷」
    用，后果比留空严重得多。有的源在这个位置放的是「1-3」（套装）或整串副标题，
    一律留空 —— 宁可少一个字段，也不给一个会被下游当数字用的错值。
    """
    s = _clean(value)
    return s if _SERIES_INDEX.match(s) else ""


def _best_series(candidates) -> tuple:
    """多支系列里挑一支：``[(系列名, 卷号), …]`` → ``(系列名, 卷号)``（无则空串）。

    ⚠️ **不能取第一条** —— 顺序不可信，两处实测：
      · Audible 的 ``series`` 数组：同一本书两次请求给出的先后不同
        （Dune 一次是「Dune #1, The Dune Sequence #12」，另一次倒过来）；
      · Goodreads 的 ``bookSeries`` 里还会挂「合集 / 合订本」这种更大粒度的系列，
        卷号往往是 12、13 这种大数字。
    规则：**卷号最小的那支** = 最具体的子系列。取不到数字卷号的项一律**排在后面**
    （有名字没卷号，也好过整项丢掉）。
    """
    best = None
    best_rank = None
    for name, index in (candidates or []):
        name = _clean(name)
        if not name:
            continue
        idx = _series_index_of(index)
        rank = (0, float(idx)) if idx else (1, 0.0)
        if best is None or rank < best_rank:
            best, best_rank = (name, idx), rank
    return best or ("", "")


def _lang_of(value) -> str:
    v = _clean(value).lower().replace("_", "-")
    if not v:
        return ""
    head = v.split("-")[0]
    return _LANG_MAP.get(v) or _LANG_MAP.get(head) or head


def language_tier(source: str, language: str) -> int:
    """源相对**某语种**的相关度档：0 专精本语种 / 1 通吃 / 2 专精别的语种。"""
    langs = LANG_AFFINITY.get(source)
    if not langs:
        return LANG_TIER_BROAD
    return LANG_TIER_SPECIFIC if language in langs else LANG_TIER_OTHER


def weight_of(weights, source: str) -> int:
    """某个来源的**用户自定义权重**；没设 / 设成非法值一律 0（= 不干预）。

    「权重」这东西必须有**唯一**的归一入口：三个调用点各写一遍 `int(...)`，
    迟早在某处漏掉一个负号或一个 `None`，表现是「设置了权重但顺序偶尔不对」。
    所以配置怎么存（字符串、负数、`None`、未知源 id）都在这里被收敛成「非负整数」。
    """
    try:
        n = int((weights or {}).get(source) or 0)
    except (TypeError, ValueError, AttributeError):
        return 0
    return n if n > 0 else 0


def reorder_for_language(sources: list, language: str, enabled: bool = True, weights=None) -> list:
    """按**用户权重**与书语种**稳定分档**重排来源。

    排序键是 `(-权重, 语种档)`，也就是：

    1. **权重高的永远在前面**（第 91 期新增，默认全 0 ⇒ 与第 60 期逐字一致）；
    2. 权重相同才比「专精本语种 → 通吃 → 专精别的语种」；
    3. 两者都相同 ⇒ **保持你设定的顺序**（`sorted` 稳定）——这不是「覆盖你的配置」，
       只是把明显不相关的家挪到后面；你在「元数据来源」里排的优先级仍然生效。

    四点刻意设计：

    1. **只排序、不筛选**：所有启用的家最终都会被查到（第 59 期体检也证明了
       「专精别的语种」的家偶尔真能命中），所以这里绝不因为语种或权重丢掉任何一家；
    2. 语种**未知 / 空**、或 `enabled=False` ⇒ **不按语种分档**（不猜）。语种来自书的
       `language` 字段（OPF `dc:language`），没填就是不知道。⚠️ 但**权重照旧生效** ——
       权重是你显式设的，`enabled` 管的只是「要不要按语种自动重排」这一件事；
    3. 若既没有语种可依据、又没有设过任何权重 ⇒ **原样返回**（与改造前逐字一致）；
    4. 语种档常量只用于排序，别在别处引用它们的数值。
    """
    srcs = [s for s in (sources or []) if s in SOURCES]
    if len(srcs) < 2:
        return srcs
    w = {s: weight_of(weights, s) for s in srcs}
    has_weight = any(w.values())
    lang = _lang_of(language)
    # 「未知」也算不知道：书目里这种占位很常见，若当成一个真实的语种码去分档，
    # 会把所有家有专精的都判成「专精别的语种」—— 那就是凭一个占位值瞎重排。
    by_lang = bool(enabled) and bool(lang) and lang.lower() not in LANG_UNKNOWN
    if not by_lang:
        # 没有语种可依据：只按权重排（档位一律相等 ⇒ 稳定排序保住用户顺序）
        return sorted(srcs, key=lambda s: -w[s]) if has_weight else srcs
    return sorted(srcs, key=lambda s: (-w[s], language_tier(s, lang)))


def dominant_language(items: list) -> str:
    """一组书里出现最多的语种（系列**没有自己的语种** → 由成员书投票）。

    平票时取**先出现**的那个（`max` 稳定 + 首次出现顺序），保证同一批数据每次结果一致 ——
    否则「重排」会变成不可复现的行为。
    """
    count: dict = {}
    for it in items or []:
        lang = _lang_of((it or {}).get("language"))
        if lang:
            count[lang] = count.get(lang, 0) + 1
    if not count:
        return ""
    top = max(count.values())
    for lang, n in count.items():
        if n == top:
            return lang
    return ""


#: 语言优先级。OpenLibrary 的 `language` 是一个**无序**的列表（一本书有几十种译本的
#: 语言代码混在一起），直接取第一个会得到「德语版《傲慢与偏见》」这种荒谬结果 —— 实测踩到过。
#: 所以按「常见目标语言」优先挑，都不在里面才退回第一个。
_LANG_PRIORITY = ("zh", "en", "ja", "ko")

# ---------------- 语种亲和 → 「按语种重排来源顺序」（第 60 期）----------------
# 目的：中文书不该先等波兰/韩国的目录转一圈，轻小说也不该先去 Google Books 试。
#
# ⚠️ 这张表是**人工写的判断**（依据是各站主营语种 / 抓的是哪个域名的站），**不是实测统计**。
# 所以它只用来「把明显不相关的家排到后面」，**不是**断言「这家查不到这本书」：
# 重排**只改顺序、不筛掉任何源** —— 所有启用的家最终都会被查到，只是先问相关的、后问不相关的。
#
# 契约：`set(LANG_AFFINITY) | set(LANG_BROAD) == set(SOURCES)` 且两者不相交（测试钉住）——
# 新增一家源必须显式表态「专精哪些语种」还是「通吃」，不能默默漏过。
#: 专精某些语种的源（语种码经 `_lang_of` 归一，如 "zh-CN"→"zh"）。
#: **由声明派生**（第 102 期）：`Provider.langs` 空元组 = 通吃，非空 = 专精这些语种。
LANG_AFFINITY = {p.id: tuple(p.langs) for p in _src_registry.DECLARED if p.langs}
#: 语种通吃：多语种都有一定覆盖 —— 任何语种都该排在「专精别的语种」之前
LANG_BROAD = tuple(p.id for p in _src_registry.DECLARED if not p.langs)

#: 分档常量（数字只用于排序，别在别处引用其数值）
LANG_TIER_SPECIFIC, LANG_TIER_BROAD, LANG_TIER_OTHER = 0, 1, 2

#: 「等于没说」的语种值（书目里常见「未知 / unknown / n/a」这类占位）。
#: ⚠️ 只在**重排**时当作「不知道」处理（`_lang_of` 本身不动 —— 它还要负责把源返回的值
#: 如实写进书目，改它的口径会波及落库）。
LANG_UNKNOWN = {"未知", "unknown", "n/a", "na", "none", "null", "-", "?", "??", "???",
                "undefined", "unk"}


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


#: 源 id → 它自己那条记录的**提供商 ID** 落在哪个元数据字段。
#:
#: ⚠️ 只有**真能拿到该源标识**的源才在这里。不在这里的 4 家（comicvine / ranobedb /
#: librofm / lubimyczytac）不是漏了 —— 它们的 ``raw_id`` 今天只是个**定位串**
#: （页面 URL），而本项目没有给它们开字段。「宁可少给不可错给」：把 URL 塞进一个叫
#: ``*_id`` 的字段，比留空更糟。将来要收，先给它们开字段、再从 URL 里抠真 ID。
SOURCE_ID_FIELD = {p.id: p.id_field for p in _src_registry.DECLARED if p.id_field}


def _goodreads_id(path: str) -> str:
    """``/book/show/12345.三体`` → ``12345``。

    Goodreads 的规范 ID 就是 URL 里那串数字，抓到的 ``href`` 是它唯一的载体。
    抠不出来（Goodreads 偶尔给 ``/book/show/三体`` 这种老式路径）就**留空**，
    不拿路径原样充数。
    """
    m = re.search(r"/book/show/(\d+)", _clean(path))
    return m.group(1) if m else ""


def _kobo_id(d: dict) -> str:
    """Kobo 的标识是它详情页 URL 末段那个 slug（Kobo 不对外给数字 ID）。

    取 ``slug`` 字段优先；只有 URL 时抠末段。**URL 抠不出来就留空**。
    """
    slug = _clean(d.get("slug"))
    if slug:
        return slug
    url = _clean(d.get("url") or d.get("href"))
    m = re.search(r"/(?:ebook|audiobook)/([^/?#]+)", url)
    return m.group(1) if m else ""


#: 多值字段（`tags` / `narrators`）落库条数上限 —— **单一真源**（第 116 期）。
#:
#: 候选侧（:func:`_entry`）与合并侧（``metafetch._candidate_values`` / ``merge_values``）
#: 都取这一份。原先散在**四处**各写死一个 8（`_entry` 的 `tags` / `narrators` 各一处、
#: `metafetch._candidate_values` 的 `vals[:8]`、`metafetch.MERGE_MAX_TAGS`）—— 同一判据的
#: 多份实现，改一处另几处照旧（§1「单一真值源」）。
#:
#: **为什么要分字段**（第 116 期）：
#: - ``tags`` 是「尽力而为的标签」：多源题材合并就靠它防爆（OpenLibrary 的 ``subject``
#:   拆开后常上百条），8 项是**刻意的策展上限**；
#: - ``narrators`` 是**这版录音的事实阵容**，不是「够用就行」的标签 —— 第 115 期真机
#:   Audible 的《Dune》有 12 位演播者，砍到 8 位就是**丢事实**（落库的阵容与实体不符）。
#:   32 项远超真实有声书阵容（第 115 期实测最多 12 位）。
#:
#: ⚠️ 上限**按字段取值**（``MULTI_VALUE_MAX[field]``），新增多值字段忘了登记会直接
#: ``KeyError``（启动/首测就炸），不会静默退回某个默认值。
MULTI_VALUE_MAX = {"tags": 8, "narrators": 32}


def _entry(source: str, **kw) -> dict:
    """统一候选结构 —— 前端与写回逻辑都只认这一种形状。

    ⚠️ 文本字段一律走 :func:`_strip_html`（实测 iTunes 的简介带 ``<b>`` 标签，
    落库会把标签带进书目）；`tags` 里也见过带标签的值，同样处理。

    第 63 期起多带一个 ``provider_id``：**必须是该源自己那条记录的标识**，
    由 fetcher 显式传（不要拿 ``raw_id`` 顶替 —— 后者对几家源是 URL）。
    它经 :data:`SOURCE_ID_FIELD` 落到对应字段；源没有对应字段就整条丢掉，
    绝不硬塞进别的字段。

    第 103 期起多带 ``series`` / ``series_index``：这两项**早就建模了**
    （``fileops.METADATA_FIELDS``、``kinds.FIELDS``、OPF 的 ``calibre:series``、
    命名规则的 ``{series}`` 都有），只是候选结构里一直没有它们的键，抓到了也
    **无处可放**（Audible 的系列名此前被塞进 ``tags``，正是这个缺口的副作用）。
    卷号一律走 :func:`_series_index_of`：**只认数字**。

    第 103 期起也多带 ``narrators``（演播者）：与 ``tags`` 一样的多值字段，空值为 ``[]``。
    第 116 期起这两个字段的上限按字段分开（见 :data:`MULTI_VALUE_MAX`）—— 原先统一 ``[:8]``，
    会把 12 位演播者的有声书砍成 8 位。

    第 113 期起多带 ``subtitle``（副标题）：与上面三项**不一样** —— 它自第 63 期就
    **整套建模好了**（``fileops.METADATA_FIELDS`` / ``metafetch._VALUE_KEYS`` /
    ``config.DEFAULTS`` 的字段策略 / 前端 ``POLICY_FIELDS`` / 元数据编辑器都有它），
    唯独候选结构这里**一直没有这个键** ⇒ 抓到了也无处可放。当前只有 Audible 供给它。
    """
    pid = _clean(kw.get("provider_id"))
    field = SOURCE_ID_FIELD.get(source)
    return {
        "source": source,
        "title": _strip_html(kw.get("title")),
        "author": _strip_html(kw.get("author")),
        "publisher": _strip_html(kw.get("publisher")),
        "year": _year_of(kw.get("year")),
        "language": _lang_of(kw.get("language")),
        "isbn": _strip_html(kw.get("isbn")),
        "description": _strip_html(kw.get("description")),
        # 第 113 期：副标题。下游（策略 / 数据库 / 前端）**早就都有它**，这里只是补上
        # 那个一直缺的键 —— 在此之前 fetcher 传 `subtitle=` 会被 `**kw` 静默吞掉。
        "subtitle": _strip_html(kw.get("subtitle")),
        "series": _strip_html(kw.get("series")),
        "series_index": _series_index_of(kw.get("series_index")),
        # 多值字段的条数上限按字段取（见 `MULTI_VALUE_MAX`）：tags 8 / narrators 32
        "tags": [t for t in (_strip_html(x) for x in (kw.get("tags") or [])) if t][
            :MULTI_VALUE_MAX["tags"]],
        # 第 103 期：演播者（有声书）。与 `tags` 同一种**多值字段**（清洗规则相同、上限不同）：
        # 空就是 `[]`，不写空串 —— 下游 `metafetch` 对这两个字段都按列表处理（合并规则不同：
        # 题材跨源拼、演播者只取一家，见那里的 `merge_values`）。
        "narrators": [n for n in (_strip_html(x) for x in (kw.get("narrators") or [])) if n][
            :MULTI_VALUE_MAX["narrators"]],
        "cover_url": _clean(kw.get("cover_url")),
        "raw_id": _clean(kw.get("raw_id")),
        #: 该源那条记录的标识 → 字段名由 SOURCE_ID_FIELD 决定；无字段的源恒为空
        "provider_field": field or "",
        "provider_id": pid if field else "",
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
        # OL 的 work key 本身就是它的标识（形如 /works/OL1234W）
        provider_id=d.get("key") or "",
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
        provider_id=it.get("id") or "",
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
        provider_id=it.get("trackId") or it.get("collectionId") or "",
    )


def _search_itunes(title: str, author: str, limit: int, opts: dict) -> list:
    term = f"{_clean(title)} {_clean(author)}".strip()
    # 封面分辨率（行内可配）：只认注册表给的取值，给了没见过的值就回落 high
    size = ITUNES_COVER_SIZES.get(_clean((opts or {}).get("resolution")).lower(), "1000x1000")
    data = _get_json(ITUNES, params={"term": term, "entity": "ebook",
                                     "limit": str(limit), "media": "ebook"})
    return [_itunes_entry(it, size) for it in (data.get("results") or [])[:limit]
            if isinstance(it, dict)]


# ---------------- RanobeDB（轻小说库，公开 API v0）----------------

def _ranobedb_index(series: dict, book_id) -> str:
    """本册在系列里的卷号 = 它在 ``series.books`` 里的位置 + 1。

    ``series`` 里**没有**卷号字段，但 ``books`` 是**按系列顺序**排的同系列书目列表
    （第 103 期真机核验：Sword Art Online 29 册，各自标题里的序号与它在表里的位置
    逐一吻合，28/29 直接对上，剩下那册是日文原名、序号也在标题里）。
    所以「位置 + 1」不是猜，是读它的排序。

    取不到（没有 series、books 为空、本书 id 不在表里）一律留空 —— 不拿书名里的
    数字去凑（那本第 29 册的日文书名是 ``ソードアート・オンライン29``，正则抠数字
    就是另一套脆弱逻辑了）。
    """
    ids = [b.get("id") for b in (series.get("books") or []) if isinstance(b, dict)]
    try:
        return str(ids.index(book_id) + 1)
    except ValueError:
        return ""


def _ranobedb_entry(d: dict) -> dict:
    """RanobeDB 单条 → 统一候选（**两段式**：列表无作者/简介/系列，详情才有）。

    ⚠️ 封面只给了 ``filename``，官方文档没公布 CDN 前缀 → **留空**而不是拼一个猜的 URL
    （宁可没有封面，也不要给一个 404 的图）。

    第 103 期真机核验的详情形状：``series`` 是**对象**，键为
    ``{books, id, lang, romaji, romaji_orig, tags, title, title_orig}``：
      · 系列名取 ``title``（``title_orig`` 是原文名，``romaji`` 实测为 null）；
      · 卷号见 :func:`_ranobedb_index`；
      · ⚠️ ``tags`` **只在系列上**，书的详情里没有（列表也没有）—— 以前这里读
        ``d["tags"]`` 于是**永远是空的**。系列题材兜底当书的题材：同一个系列共用
        题材本来就是 RanobeDB 自己的建模。
    """
    staff = [s for ed in (d.get("editions") or []) for s in (ed.get("staff") or [])]
    author = next((s.get("name") for s in staff if s.get("role_type") == "author"), "")
    if not author and staff:
        author = staff[0].get("name") or ""
    pubs = d.get("publishers") or []
    series = d.get("series") if isinstance(d.get("series"), dict) else {}
    tags = [t.get("name") if isinstance(t, dict) else t for t in (d.get("tags") or [])]
    if not tags:
        tags = [t.get("name") if isinstance(t, dict) else t
                for t in (series.get("tags") or [])]
    return _entry(
        "ranobedb",
        title=d.get("title") or d.get("romaji"),
        author=author,
        publisher=(pubs[0].get("name") if pubs and isinstance(pubs[0], dict) else ""),
        year=d.get("c_release_date") or d.get("start_date"),
        language=d.get("lang"),
        description=d.get("description"),
        series=series.get("title") or series.get("romaji") or series.get("title_orig"),
        series_index=_ranobedb_index(series, d.get("id")),
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
                # ⚠️ 第 103 期真机核验：详情响应把内容**套在一个 `book` 键里**
                # （`{"book": {id, description, publishers, editions, series, …}}`）。
                # 直接 `{**b, **fetched}` 只会并进一个 `book` 键，内层字段**一个都进不来**：
                # 作者 / 出版社 / 简介全空，而且**不报错**（表现为这家源永远给不出作者，
                # `score_candidate` 只剩书名那 0.7 分 < 默认阈值 0.75 ⇒ 候选在默认配置下
                # 永远进不了合并，整家源白挂）。所以先剥一层，剥不到再按扁平吃（接口形状
                # 随版本变过，留这条兜底免得哪天再变回去时整家**静默**变空）。
                inner = fetched.get("book") if isinstance(fetched, dict) else None
                if isinstance(inner, dict) and inner:
                    detail = {**b, **inner}
                elif isinstance(fetched, dict) and fetched:
                    detail = {**b, **fetched}
            except Exception:                       # noqa: BLE001
                pass
        out.append(_ranobedb_entry(detail))
    return out


# ---------------- Hardcover（GraphQL，需 Token）----------------

_HARDCOVER_Q = """
query Search($q: String!, $n: Int!) {
  books(where: {title: {_ilike: $q}}, limit: $n, order_by: {users_count: desc}) {
    id
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
        # Hardcover 的规范 ID 是数字 ``id``（第 63 期把它加进 GraphQL 选择集）；
        # ``slug`` 是另一回事，只留在 raw_id 里当定位串。
        provider_id=str(b.get("id") or ""),
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
        provider_id=it.get("itemId") or "",
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
    """Amazon 搜索结果页抓取。

    ⚠️ 选择器**照真实页面校准**（第 59 期体检发现旧写法一条都匹配不到；改后又发现
    用 ``a-text-normal`` 会抓到「Aug 25, 2020」这类辅助 span ⇒ **错字段比缺字段更糟**）：
    结果项 = ``data-asin="<10 位 ASIN>"`` 切片，**书名取该切片里 ``<h2>`` 的文本**
    （实测 16/16 都是真书名），封面取 ``s-image``。**作者尽力而为**：拿不到就留空，不猜。
    """
    cookie = _clean((opts or {}).get("cookie"))
    html = _get_text(AMAZON, params={"k": f"{_clean(title)} {_clean(author)}".strip(),
                                     "i": "stripbooks"},
                     headers={"Cookie": cookie} if cookie else None)
    out = []
    # 按「带真实 ASIN 的结果项」切片；页面上还有 data-asin="" 的占位块，跳过
    for m in re.finditer(r'data-asin="([A-Z0-9]{10})"(.*?)(?=data-asin="|$)', html, re.S):
        asin, block = m.group(1), m.group(2)
        h = re.search(r"<h2[^>]*>(.*?)</h2>", block, re.S)
        name = _strip_html(h.group(1)) if h else ""
        if len(name) < 2:
            continue
        a = re.search(r'class="a-size-base[^"]*a-color-secondary[^"]*"[^>]*>([^<]{2,80})</span>',
                      block)
        cover = re.search(r'class="s-image"[^>]*src="([^"]+)"', block) \
            or re.search(r'src="([^"]+)"[^>]*class="s-image"', block)
        out.append(_entry("amazon", title=name, author=a.group(1) if a else "",
                          cover_url=cover.group(1) if cover else "", raw_id=asin,
                          provider_id=asin))
        if len(out) >= limit:
            break
    return out


#: Goodreads 搜索结果页里承载书数据的 React Server Components (RSC) flight payload。
#: 页面把它一段段地推成 ``self.__next_f.push([1,"…"])``；**书对象在 payload 的 JSON 里**，
#: 不在 DOM 里 —— 详见 :func:`_search_goodreads` 的说明。
_RSC_PUSH = re.compile(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)</script>', re.S)
#: RSC 流的一行：``<hexid>:<payload>``。行号单独记，载荷才是内容。
_RSC_ROW = re.compile(r"^([0-9a-f]+):(.*)$", re.S)


def _walk_dicts(node):
    """递归产出嵌套结构里的所有 dict（列表 / dict 都下钻）。"""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk_dicts(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_dicts(v)


def _rsc_books(html: str) -> list:
    """从 Goodreads 结果页的 RSC flight payload 里取出 ``__typename == "Book"`` 的对象。

    **为什么不能只靠 DOM 解析**（第 101 期真机核验）：新结果页是 React Server
    Components 渲染的，``ul[data-testid="book-list-item"]`` 下确有 20 个 ``<li>``，
    但**只有第一张卡带完整详情**，其余卡的详情被放进 ``<template id="P:c">`` 占位符里
    —— 而 ``BeautifulSoup(html, "html.parser")`` **不解析 `<template>` 的内容**，
    于是 DOM 通道只拿得到 1 本书（其余 ``<li>`` 只有 class 名，没有书名/作者）。

    可靠来源是 flight payload：它含完整字段的 Book 对象。
    ⚠️ **必须逐行 ``json.loads`` 后按对象取字段，不能对整段文本抓同名 key** ——
    实测 ``title`` 出现 23 次而 Book 对象只有 19 个（多出来的是**系列名**等），
    全局抓取会让书名与系列串台。
    """
    books = []
    for payload in _rsc_rows(html).values():
        if '"legacyId"' not in payload:
            continue
        try:
            data = json.loads(payload)
        except ValueError:
            continue
        for node in _walk_dicts(data):
            if node.get("__typename") == "Book" and node.get("title"):
                books.append(node)
    return books


def _rsc_year(book: dict) -> str:
    """Book 的出版年：``details.publicationTime`` 是 **epoch 毫秒**（实测 1415692800000）。"""
    ms = (book.get("details") or {}).get("publicationTime")
    try:
        secs = int(ms) / 1000
    except (TypeError, ValueError):
        return ""
    if secs <= 0:
        return ""
    return time.strftime("%Y", time.gmtime(secs))


def _rsc_rows(html: str) -> dict:
    """把 RSC flight 流拆成 ``{行号: 载荷}``。

    flight 流每一行是 ``<hexid>:<payload>``；行与行之间可以互相**前向引用**
    （见 :func:`_rsc_ref`），所以必须先建好整张表再解析书对象。
    ⚠️ payload 未必是 JSON（实测 ``73:T4f5,Read the award…`` 这种前缀是 RSC 的
    类型标记 ``T<长度>,``，后面才是文本）—— 取值时再按需剥掉。
    """
    rows = {}
    for seg in _RSC_PUSH.findall(html or ""):
        try:
            text = json.loads(f'"{seg}"')
        except ValueError:
            continue
        for line in text.split("\n"):
            m = _RSC_ROW.match(line.strip())
            if m:
                rows[m.group(1)] = m.group(2)
    return rows


#: RSC 的带类型前缀值：``T<十六进制长度>,<正文>``（实测简介行就是这样）。
_RSC_TYPED = re.compile(r"^T[0-9a-f]+,", re.S)


def _rsc_value(rows: dict, value, _depth: int = 0):
    """解开一个字段的**前向引用**（``"$4d:props:children:…"``）。取不到就原样返回。

    为什么必须解：实测 20 本结果里**只有第 1 本**的简介/系列是内联的，其余都写成
    引用串。不解的话要么落进 ``'$73'`` 这种垃圾值，要么整片字段丢掉 —— 前者更糟，
    因为它看起来「有值」。解不出来（引用指向的行不存在）时返回 ``None``，
    让调用方按「这个字段没有」处理。
    """
    if _depth > 8 or not isinstance(value, str) or not value.startswith("$"):
        return value
    ref = value[1:]
    # 两种引用形态（实测都有）：
    #   ① 纯文本引用 —— ``"$73"``：整行就是内容（简介常这样写）；
    #   ② 路径引用  —— ``"$4d:props:children:…:series"``：行号 + 一串属性/下标路径。
    head, sep, path = ref.partition(":")
    if head not in rows:
        return None
    node = rows[head]
    # 带类型前缀的行（``T4f5,<正文>``）**只有纯文本引用才该剥前缀**；
    # 路径引用的行是 JSON，乱剥会把内容弄坏。
    if not sep:
        return _RSC_TYPED.sub("", node.strip())
    try:
        node = json.loads(node.strip())
    except ValueError:
        return None
    for part in [p for p in path.split(":") if p]:
        if isinstance(node, list):
            # React 元素是定长数组 ``["$", <type>, <key>, <props>]``（实测）：
            # 路径里的 ``props`` 指的是第 4 项，不是 list 的下标 —— 直接 ``int()`` 会崩。
            if part == "props" and len(node) == 4 and node[0] == "$":
                node = node[3]
                continue
            try:
                node = node[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(node, dict):
            if part not in node:
                return None
            node = node[part]
        else:
            return None
    return _rsc_value(rows, node, _depth + 1)


def _rsc_text(rows: dict, value) -> str:
    """取一个**文本字段**：先解引用，再剥掉 RSC 的类型标记前缀。"""
    got = _rsc_value(rows, value)
    if not isinstance(got, str):
        return ""
    return _RSC_TYPED.sub("", got)


def _rsc_authors(rows: dict, book: dict) -> str:
    """把主作者与其余作者连成一个字符串（多作者是常见情形，不能只取第一位）。"""
    names = []
    edges = [book.get("primaryContributorEdge")]
    extra = _rsc_value(rows, book.get("secondaryContributorEdges"))
    if isinstance(extra, list):
        edges.extend(extra)
    for edge in edges:
        edge = _rsc_value(rows, edge)
        if not isinstance(edge, dict):
            continue
        node = _rsc_value(rows, edge.get("node"))
        if not isinstance(node, dict):
            continue
        name = _clean(node.get("name"))
        if name and name not in names:
            names.append(name)
    return ", ".join(names)


def _rsc_series(rows: dict, book: dict) -> tuple:
    """Goodreads 的系列：``(系列名, 卷号)``，没有就给 ``("", "")``。

    实测 ``bookSeries`` 是**一层列表**，但列表里那项的 ``series`` 可能是内联字典，
    也可能是**路径引用字符串** —— 同一页的两本书就是两种写法（见夹具
    ``tests/fixtures/metasources/goodreads_search.html``）⇒ 必须再解一次引用。

    多项时按 :func:`_best_series` 取（卷号最小的那支，**不是**第一条）。
    """
    items = _rsc_value(rows, book.get("bookSeries"))
    if not isinstance(items, list):
        return "", ""
    pairs = []
    for item in items:
        item = _rsc_value(rows, item)
        if not isinstance(item, dict):
            continue
        series = _rsc_value(rows, item.get("series"))
        if not isinstance(series, dict):
            continue
        pairs.append((series.get("title"), item.get("seriesPlacement")))
    return _best_series(pairs)


def _search_goodreads(title: str, author: str, limit: int, opts: dict) -> list:
    """Goodreads 搜索结果页抓取 —— 数据在 **RSC flight payload** 里，不在 DOM 里。

    ⚠️ **旧实现（``<tr itemscope>`` + ``class="bookTitle"``）已彻底失效**（第 101 期真机核验）：
    真结果页里 ``<tr itemscope`` / ``bookTitle`` / ``authorName`` **各出现 0 次** ——
    该结构已被站点下线，旧正则只能匹配到 0 条，表现为**这整家静默返回 0 结果**。

    **为什么不能只靠 DOM 解析**：新结果页由 React Server Components 渲染，
    ``ul[data-testid="book-list-item"]`` 下确有 20 个 ``<li>``，但只有第一张卡带完整详情，
    其余卡的详情被放进 ``<template id="P:c">`` 占位符 —— 而 bs4 的 ``html.parser``
    **不解析 `<template>` 内容**，于是 DOM 通道只拿得到 1 本书。

    ⚠️ **必须按对象取字段，不能对整段文本抓同名 key**：实测 ``title`` 出现 23 次而
    Book 对象只有 19 个（多出来的是**系列名**），全局抓取会让书名与系列串台。

    ⚠️ Goodreads 与 Libro.fm 一样在 **AWS WAF** 后面：命中挑战页时 :func:`_get_text`
    会抛「被反爬拦截」（实测挑战页含 ``window.gokuProps`` + ``awswaf.com/…/challenge.js``）。
    是否被拦取决于 IP 信誉，**不是**「站点挂了」，也不是解析问题。

    ⚠️ payload 里**有**系列信息（``bookSeries`` → ``seriesPlacement`` + 系列名），
    第 103 期起接上了（见 :func:`_rsc_series`）：此前不返回不是因为解不出来，
    而是候选结构里没有 ``series`` / ``series_index`` 两个键，传了会被**静默丢掉**。
    """
    html = _get_text(GOODREADS, params={"q": f"{_clean(title)} {_clean(author)}".strip()})
    rows = _rsc_rows(html)
    out = []
    seen = set()
    for book in _rsc_books(html):
        url = _clean(book.get("webUrl"))
        # 同一本书可能在 payload 里出现多次（不同 RSC 行各带一份）⇒ 去重，否则结果灌水。
        key = _clean(book.get("legacyId")) or url
        if key and key in seen:
            continue
        seen.add(key)
        series, series_index = _rsc_series(rows, book)
        out.append(_entry("goodreads", title=_clean(_rsc_text(rows, book.get("title"))),
                          author=_rsc_authors(rows, book),
                          year=_rsc_year(book),
                          description=_strip_html(_rsc_text(rows, book.get("description"))),
                          series=series, series_index=series_index,
                          cover_url=_clean(_rsc_value(rows, book.get("imageUrl"))),
                          raw_id=url, provider_id=_goodreads_id(url)))
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
                          raw_id=_clean(d.get("url") or d.get("slug")),
                          provider_id=_kobo_id(d)))
        if len(out) >= limit:
            break
    return out


def _audible_region_host(opts: dict) -> str:
    """区域（行内可配，默认 us）→ 分站域名；没见过的取值回落 us。检索与详情共用。"""
    region = _clean((opts or {}).get("region")).lower() or "us"
    return AUDIBLE_HOSTS.get(region, AUDIBLE_HOSTS["us"])


def _audible_entry(p: dict) -> dict:
    """Audible catalog 的单条 ``product`` → 统一候选。

    ⚠️ 这是 Audible 的**唯一字段映射**：检索（``/products``）与按 ASIN 取详情
    （``/products/{asin}``）回的是**同形状**的单条（详情只是包在 ``{"product": {...}}`` 里）
    ⇒ 两条路径都走它，别抄第二份（§7.1；同 `_itunes_entry` / `_detail_itunes` 的规矩）。
    """
    authors = ", ".join(a.get("name") for a in (p.get("authors") or [])
                        if isinstance(a, dict) and a.get("name"))
    imgs = p.get("product_images") or {}
    cover = imgs.get("500") or imgs.get("1000") or next(iter(imgs.values()), "") \
        if isinstance(imgs, dict) else ""
    # 系列：`series` 是**对象数组**，常常挂多支（实测 Dune 同时属于「Dune」#1 与
    # 「The Dune Sequence」#12），且顺序不稳定 ⇒ 交给 `_best_series` 挑。
    series, series_index = _best_series([(s.get("title"), s.get("sequence"))
                                        for s in (p.get("series") or [])
                                        if isinstance(s, dict)])
    # 演播者（第 103 期）：`narrators` 是**顶层键**且真的随现有响应组返回
    # （真机实测 Dune 12 位、Dune Messiah 4 位），每项形如 `{"name": "Scott Brick"}`。
    # 注意 `contributors` 实测恒为 null —— 别绕道去解它。
    narrators = [n.get("name") for n in (p.get("narrators") or [])
                 if isinstance(n, dict) and n.get("name")]
    return _entry("audible", title=p.get("title"), author=authors,
                  publisher=p.get("publisher_name") or p.get("publisher_summary"),
                  year=p.get("publication_datetime") or p.get("release_date"),
                  language=p.get("language"),
                  description=p.get("publisher_summary"),
                  # 副标题（第 113 期）：**顶层键** `subtitle`，随现有的
                  # `response_groups`（`product_desc`）照旧返回 —— 第 103 期真机核过它存在。
                  # ⚠️ 别为了它去加 response_group：第 99 期实测，加一个非法组名
                  # （`publisher`）会让接口直接 400、**整家永远 0 结果**。
                  subtitle=p.get("subtitle"),
                  series=series, series_index=series_index,
                  narrators=narrators,
                  # ⚠️ 题材**不从这里来**：此前把系列名塞进了 `tags`（把值写错
                  # 地方，还污染题材黑名单与跨源合并）。实测现有
                  # `response_groups` 下 Audible 根本不返回题材
                  # （`thesaurus_subject_keywords` / `category_ladders` 都不在
                  # 响应里），所以 tags 就是空 —— 不为了好看去凑一个。
                  # ⚠️ **不要**为了拿题材去加 response_group：第 99 期核过，
                  # 带一个非法组名（`publisher`）会让接口直接 400、整家永远 0 结果。
                  tags=[],
                  cover_url=cover, raw_id=p.get("asin") or "",
                  provider_id=p.get("asin") or "")


def _search_audible(title: str, author: str, limit: int, opts: dict) -> list:
    """Audible 走 catalog 接口（JSON）而不是抓页面：更稳，但仍是**非公开**接口 → fragile。

    ⚠️ ``response_groups`` 里**不能带 ``publisher``**（第 99 期真机核验）：接口会直接回
    ``400 {"message":"Invalid response group(s) requested: publisher"}`` ⇒ 这家**永远 0 结果**。
    需注意 ``publisher_name`` / ``publisher_summary`` 两个**字段**照旧随 ``product_desc`` 返回，
    与那个非法的**响应组名**无关 —— 删掉它不会少拿出版方（实测 200 + ``publisher_name: "Macmillan Audio"``）。
    """
    host = _audible_region_host(opts)
    data = _get_json(AUDIBLE_CATALOG.format(host=host, tail=""), params={
        "keywords": _clean(title), "num_results": str(limit),
        "products_sort_by": "Relevance",
        "response_groups": AUDIBLE_RESPONSE_GROUPS,
    })
    return [_audible_entry(p) for p in (data.get("products") or [])[:limit]
            if isinstance(p, dict)]


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
    """Lubimyczytac 搜索结果页抓取。

    ⚠️ 选择器同样照真实页面校准过（第 59 期体检：旧的 ``authorAllBooks__*`` 早已废弃，
    现站用 ``book-card__title`` / ``book-card__author``）。

    ⚠️ **必须按卡片容器逐卡取，不能按三个独立列表按下标配对**（第 99 期真机核验）：
    实测一本多作者的书（``Latin American Thought``，作者 Karol Derwich + Magdalena
    Modrzejewska，两名之间是 ``, `` 分隔）会让「作者」这个列表与「书名」列表**长度和下标都对不上**
    —— 旧的三次 ``findall`` + 按下标取只拿得到第一位作者，其余静默丢失。
    改成在 ``div.book-card`` 容器内分别取标题与作者（多作者用 ``, `` 连接），
    既修好截断，也不再依赖三个列表的下标对齐。

    ⚠️ 书名优先取 ``title="…"`` 属性（比锚文本干净，锚文本带首尾空格）。
    """
    html = _get_text(LUBIMYCZYTAC, params={"phrase": _clean(title)})
    soup = _soup(html)
    if soup is None:
        return []
    out = []
    for card in soup.select("div.book-card"):
        a = card.select_one("a.book-card__title")
        if a is None:
            continue
        name = _clean(a.get("title")) or _clean(a.get_text())
        if not name:
            continue
        authors = [_clean(x.get_text()) for x in card.select("div.book-card__author a")]
        cover = card.select_one("img.book-card__cover-image")
        out.append(_entry("lubimyczytac", title=name,
                          author=", ".join([x for x in authors if x]),
                          cover_url=_clean(cover.get("src")) if cover is not None else "",
                          raw_id=_clean(a.get("href"))))
        if len(out) >= limit:
            break
    return out


#: 检索函数表：**键序 = 声明顺序**（`IMPLEMENTED` 由它派生，故顺序与 `registry.DECLARED` 一致）。
#: ⚠️ 函数体仍在本文件（第 102 期只收口**声明**，不搬 1800 行解析实现）。
_FETCHERS = {
    "googlebooks": _search_googlebooks,
    "amazon": _search_amazon,
    "goodreads": _search_goodreads,
    "hardcover": _search_hardcover,
    "openlibrary": _search_openlibrary,
    "itunes": _search_itunes,
    "kobo": _search_kobo,
    "audible": _search_audible,
    "librofm": _search_librofm,
    "comicvine": _search_comicvine,
    "ranobedb": _search_ranobedb,
    "lubimyczytac": _search_lubimyczytac,
    "aladin": _search_aladin,
}

#: 按 ID 取详情的函数表（第 102 期新能力）。**空 = 这家没有按 ID 取详情的能力**，
#: `detail()` 因此回一句明确的中文回绝（「这家没有按 ID 取详情的通道」），而不是
#: 回一条假装成功的记录 —— 界面上要分得清「这家没有」与「这家刚才失败了」（处置不同）。
#: ⚠️ 先只接**真有独立详情通道**的家；Goodreads / RanobeDB 的详情是在各自检索函数里
#: 顺手取的，没有单独的入口 —— 不为了凑数给它们造一个（§7.2 禁投机抽象）。
#: ⚠️ 而且只接**真机核过**的（接口存在 + 返回形状对得上）：第 102 期核过 itunes
#: （`/lookup?id=` 与 `/search` 同形状）与 openlibrary（`<key>.json`）；第 115 期核过
#: audible（`/products/{asin}` 回 `{"product": {…}}`、与检索同形状）；googlebooks
#: （匿名额度已 429）/ goodreads（302 反爬）没核过 ⇒ 不接。
_DETAIL_FETCHERS = {}


def _bind_declared() -> None:
    """把声明里声明的 fetch / fetch_detail 绑到本模块的表上（第 102 期）。

    ⚠️ 为什么在**函数里**做而不是 import 期顶层做：声明表要引用本模块的函数，
    而本模块要引用声明表 —— 顶层互相引用会成环。声明里 `fetch` 字段默认留空，
    由这里在**本模块加载完之后**注入。

    契约：声明里写了 `fetch` 却找不到同名函数 ⇒ **直接抛错**（静默忽略等于
    「源在声明里但抓不了」，正是第 102 期要消灭的那类静默失败）。
    """
    for p in _src_registry.DECLARED:
        want = getattr(p, "fetch_name", "")
        if want:
            fn = globals().get(want)
            if fn is None:
                raise ValueError(f"来源 {p.id} 声明的抓取函数不存在：{want}")
            _FETCHERS[p.id] = fn
        want_d = getattr(p, "detail_name", "")
        if want_d:
            fn = globals().get(want_d)
            if fn is None:
                raise ValueError(f"来源 {p.id} 声明的详情函数不存在：{want_d}")
            _DETAIL_FETCHERS[p.id] = fn
    missing = [p.id for p in _src_registry.DECLARED
               if p.fetch_name and p.id not in _FETCHERS]
    if missing:
        raise ValueError(f"这些来源声明了抓取函数但未绑定成功：{missing}")


#: 通用体检样本：绝大多数家都用这一本（命中率最高、界面上的说明也统一）。
#: ⚠️ 地区性目录必须用当地书名（声明里的 `health_sample`）：拿 "Dune" 去查 Aladin（韩）/
#: Lubimyczytac（波兰）/ RanobeDB（轻小说）本来就搜不到，那会把「这家是好的」误报成
#: 「无结果」—— 误报比不测更糟：用户会去修一个根本没坏的东西。
HEALTH_SAMPLE_DEFAULT = ("Dune", "Frank Herbert")


def _derive_final() -> None:
    """绑定声明后填上三张**依赖后段定义**的表（`_bind_declared` 之后调用）。"""
    global IMPLEMENTED, HEALTH_SAMPLES, DETAIL_SOURCES
    IMPLEMENTED = tuple(_FETCHERS)
    HEALTH_SAMPLES = {
        p.id: (tuple(p.health_sample) if p.health_sample else HEALTH_SAMPLE_DEFAULT)
        for p in _src_registry.DECLARED
    }
    # `_DETAIL_FETCHERS` 是**私有**的（它是绑定产物，不是给人读的接口）；
    # 但 `metafetch` 要按「这家有没有详情通道」决定走不走精确键 ⇒ 给一个只读的元组。
    # 用元组而不是 dict：调用方只能做成员判断，改不了绑定表。
    DETAIL_SOURCES = tuple(_DETAIL_FETCHERS)


# ---------------- ISBN 精确匹配（第 8 期 D4）----------------
# 有 ISBN 的书直接按 ISBN 查，命中即为**同一版本**，比「书名+作者」相似度可靠得多。
# 放在 `_FETCHERS` 之后是为了「一张表看全 13 家」——这两家同样只经 `_get_json` 出网。

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


#: 有 ISBN 精确检索能力的家（其余没有就跳过，由调用方回退「书名 + 作者」检索）。
#: ⚠️ 这里保留字面写出而非从声明派生：它引用的是**本文件下方**定义的函数，
#: 而声明表为了避开成环不写具体函数名（见 `_bind_declared`）。契约测试钉住
#: 「键集合 == 声明里 fetch_isbn 非空的家」。
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


# ---------------- 检索缓存 与 主动限流（第 102 期）----------------
#
# 这两个能力都是**进程内**的，刻意不落盘、也不进 `core/cache.py`（那是跨进程 / 跨重启的
# 缓存，语义与 TTL 口径都不同）。理由：这里的目的是「同一个用户连点两次预览别发两轮外呼」，
# 不是「重启后还能命中」—— 后者会带来「元数据看着是新的其实是昨天的」这类更难查的问题。

#: 检索结果缓存：``{(源, 归一化书名, 归一化作者, limit): (写入单调时刻, entries)}``。
#: ⚠️ 用 `time.monotonic()` 而非 `time.time()`：墙钟会被 NTP 回拨，回拨后 TTL 可能永不生效。
_SEARCH_CACHE: dict = {}
#: 缓存条目上限（超限按插入序淘汰最旧）。256 条 ≈ 几十本书 × 十几个源，够用且不会涨到吃内存。
_SEARCH_CACHE_MAX = 256

#: 每家的「上次调用时刻」（单调秒）。`search()` 在**调用 fetcher 之前**据此补足间隔。
_LAST_CALL: dict = {}


def _opts_key(opts: dict) -> str:
    """`opts` 的**指纹**，进缓存键。

    ⚠️ 必须参与键：同一本书换一个选项就会返回**不同结果** —— itunes 的
    `resolution` 直接决定封面是 100x100 还是 1000x1000，kobo 的 `region`/`language`
    决定返回哪国目录，付费源的 `api_key` 决定查到哪份数据。不参与就会出现
    「改了设置、结果没变」这类查不出来的错。
    用摘要而非原值：密钥不该以明文躺在缓存键里（键可能被日志/调试打印）。
    """
    if not opts:
        return ""
    blob = json.dumps({str(k): str(v) for k, v in sorted(opts.items())}, ensure_ascii=False)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]


def _cache_key(source: str, title: str, author: str, limit: int, opts: dict = None):
    # 用 `norm_key` 归一：与「重复书籍」同一口径，避免大小写/全半角差异导致缓存失效
    return (source, norm_key(title), norm_key(author), int(limit), _opts_key(opts or {}))


def _detail_key(source: str, provider_id: str, opts: dict = None):
    """详情缓存键。第一段是 ``"@detail"``。

    ⚠️ **必须与检索键分开**：详情回的是**单条**、检索回**列表**，共用键会让
    `search` 读到一个 dict、`detail` 读到一个 list，两边都解析不出东西（而且都不会报错）。
    第一段的字面量不同 ⇒ 与 `(源, 书名, 作者, limit, opts)` 必然不撞。
    """
    return ("@detail", source, norm_key(provider_id), _opts_key(opts or {}))


def clear_cache() -> int:
    """清空检索缓存，返回被丢弃的条目数。给测试与「设置页手动清一下」用。"""
    n = len(_SEARCH_CACHE)
    _SEARCH_CACHE.clear()
    return n


def cache_stats() -> dict:
    """缓存现状（条目数 / 上限）—— 设置页与体检报告想显示「省了多少外呼」时读它。

    ⚠️ 检索与**详情**共用一个存储（键不同，见 `_detail_key`），所以 `entries` 是两者之和。
    不拆成两个计数：这一层的用途只是「有没有在涨」，拆开既不指导任何决策，又要多维护一份状态。
    """
    return {"entries": len(_SEARCH_CACHE), "max": _SEARCH_CACHE_MAX}


def _cache_get(key, ttl: int):
    """命中且未过期则回缓存值；`ttl<=0` 视为不缓存（回 None）。"""
    if ttl <= 0:
        return None
    hit = _SEARCH_CACHE.get(key)
    if not hit:
        return None
    at, entries = hit
    if time.monotonic() - at > ttl:
        _SEARCH_CACHE.pop(key, None)
        return None
    return [dict(e) for e in entries]        # 浅拷贝每条：调用方会往候选里写 score


def _cache_put(key, entries, ttl: int) -> None:
    """写入缓存。

    ⚠️ **只缓存「成功且非空」的结果**（由调用方保证）：空结果一律不缓存 ——
    一次网络抖动 / 站点临时抽风会让这家源「假死」整个 TTL，用户看到的是
    「刚才还能用，现在什么都没了」，而实际早就恢复了。
    """
    if ttl <= 0:
        return
    if key not in _SEARCH_CACHE and len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
        # 按插入序淘汰最旧（dict 保序）。不做 LRU：这层的目的只是「短时间内重复点击」，
        # 精确的访问序统计不值得那份复杂度（AGENTS.md §7.2）。
        _SEARCH_CACHE.pop(next(iter(_SEARCH_CACHE)), None)
    _SEARCH_CACHE[key] = (time.monotonic(), [dict(e) for e in entries])


def _ttl_of(source: str) -> int:
    """该源的缓存秒数：**配置优先**（`metadata_fetch.cache_ttl`），留空则用声明里的值。

    ⚠️ 配置的 ``0`` 与「留空」是**两件事**：留空 = 「按各来源自己声明的值」（`None`），
    `0` = 「我不要缓存」。所以判断必须按 `is None`，不能写成 `if configured:` ——
    那样 `0` 会被当成「没配」而回落到声明值，用户关不掉缓存（假配置的一种）。

    ⚠️ 这里曾经写成裸 `except Exception` —— 而本模块当时**根本没 import config**，于是
    `config.load_config()` 抛的 `NameError` 被一起吞掉，`cache_ttl` 变成「能写进
    settings.json、界面上也有控件、但谁都不读」的假配置，好几个步骤都没人发现。
    教训：**兜底要兜得住「读不到」，但不能连「写错了」一起吞**。所以这里只接
    `TypeError` / `ValueError`（值本身不是数字），并且出声。
    """
    meta = SOURCES.get(source) or {}
    configured = None
    try:
        raw = (config.load_config().get("metadata_fetch") or {}).get("cache_ttl")
        if raw is not None and str(raw).strip() != "":
            configured = int(raw)
    except (TypeError, ValueError) as e:       # noqa: BLE001 —— 配置里填了个非数字
        _log.warning("metadata_fetch.cache_ttl 不是整数（%r），改用各来源声明的缓存时长：%s",
                     (config.load_config().get("metadata_fetch") or {}).get("cache_ttl"), e)
        configured = None
    if configured is not None:
        return max(0, configured)
    return max(0, int(meta.get("cache_ttl") or 0))


def _throttle(source: str) -> None:
    """主动限流：按声明的 `(次数, 秒)` 补足最小间隔。

    ⚠️ 只在**单进程内**生效（本项目是单进程 uvicorn）。不引入跨进程限流：
    那需要锁或外部存储，而收益只是「多 worker 部署下更稳」，本项目没有那种部署（§7.2）。

    ⚠️ 体检路径**旁路本函数**（见 `health_one`）：体检默认 4 路并发，与「串行补间隔」
    互相干扰；而体检本来就是要探「现在到底能不能用」，人为拖慢它没有意义。
    """
    meta = SOURCES.get(source) or {}
    rl = meta.get("rate_limit") or []
    if not rl or len(rl) < 2:
        return
    span = float(rl[1])
    if span <= 0:
        return
    now = time.monotonic()
    last = _LAST_CALL.get(source)
    if last is not None:
        wait = span - (now - last)
        if wait > 0:
            time.sleep(wait)
    _LAST_CALL[source] = time.monotonic()


def _error_text(exc: Exception) -> str:
    """把 fetcher 抛出的异常翻成**用户照着能做点什么**的中文说明。

    ⚠️ **只此一处**：`search` 与 `detail` 都需要这套口径（3xx 反爬 / 4xx-5xx 接口 /
    超时 / 连不上），两处各写一份必然走散 —— 第 102 期加 `detail` 时收敛到这里。

    ⚠️ 第 104 期补上**网络归因**：本机 DNS 被污染时 `openlibrary.org` 解析到 Facebook 网段、
    连接超时，原来的口径一律写「请求超时」/「连接失败」—— 用户会照着自己去修一个**根本没坏**
    的源。这里按**异常链**分档（`netdiag.classify_exc`，纯函数、零 I/O），**不查 DNS**：
    真正的交叉核对（本机解析 vs 公共解析）由诊断路径的 `netdiag.refine` 做。
    """
    if isinstance(exc, httpx.HTTPStatusError):
        # ⚠️ 必须按状态码分开说：3xx（httpx 的 raise_for_status 也管）多半是被反爬
        # 重定向到验证页，4xx/5xx 是接口本身的问题，两者要做的处置不一样。
        code = exc.response.status_code
        if 300 <= code < 400:
            return f"被重定向（HTTP {code}）：多半被反爬拦到验证页，需要降低频率或带 Cookie"
        if code == 404:
            # 按 ID 取详情时 404 是**常见**结果（记录下架 / 标识过期）。笼统写「接口返回错误」
            # 会让人以为站点坏了，跑去查一个根本没坏的东西（误报比不报更糟）。
            return "该地址不存在（HTTP 404）：记录可能已下架，或该来源的接口已改版"
        return f"接口返回错误（HTTP {code}）"
    kind = netdiag.classify_exc(exc)
    if kind == "dns":
        return (f"域名解析失败：{exc}"
                "（本机 DNS 解析不出该域名；解析被污染时也会这样，换一个 DNS 再试）")
    if kind == "tls":
        return f"TLS 握手失败：{exc}（证书 / 中间人 / 站点握手中断）"
    if kind == "proxy":
        return f"代理不可用：{exc}（检查代理环境变量）"
    if kind == "connect_timeout":
        return f"连接超时：{exc}（TCP 都没建起来：多半被阻断，或该地址已不对）"
    if kind == "timeout" or isinstance(exc, httpx.TimeoutException):
        return f"请求超时：{exc}"
    if kind == "network" or isinstance(exc, httpx.HTTPError):
        return f"连接失败：{exc}"
    return str(exc)


def search(source: str, title: str, author: str, limit: int = 5, opts: dict = None,
           force: bool = False) -> dict:
    """单个源检索。返回 ``{ok, entries, error}`` —— **不抛异常**，失败信息带回给调用方。

    ``opts`` 是**该源的**配置（如 Google Books 的 ``api_key``）。

    ``force=True`` = **诊断模式：旁路缓存与限流**。体检与「测试这一家」必须用它 ——
    那些功能的全部价值是「现在到底能不能用」，读缓存等于说谎；
    而体检默认 4 路并发 + 单家 12s 超时，若还串行补限流间隔（comicvine 声明 18s），
    它会把自己的 sleep 当成源超时 ⇒ **把健康源误报成 timeout**（误报比不测更糟：
    用户会去修一个根本没坏的东西）。
    """
    fn = _FETCHERS.get(source)
    if not fn or not _clean(title):
        return {"ok": False, "entries": [], "error": "源不可用或书名为空"}
    title, author = _clean(title), _clean(author)
    n_limit = max(1, min(int(limit or 5), 20))
    ttl = _ttl_of(source)
    key = _cache_key(source, title, author, n_limit, opts)
    if not force:
        cached = _cache_get(key, ttl)
        if cached is not None:
            return {"ok": True, "entries": cached, "error": ""}
    if not force:
        _throttle(source)
    try:
        entries = fn(title, author, n_limit, opts or {})
    except Exception as e:                                   # noqa: BLE001 —— 单源失败不能影响别的源
        # `fail` 是第 104 期加的**附加键**（调用方一律用 `.get`）：把异常里的
        # 「哪一类失败、打的是哪个主机」结构化地带出去，诊断路径（probe / health_one）
        # 靠它做 DNS 交叉核对。数据路径不看它，也不为它多花任何一次往返。
        return {"ok": False, "entries": [], "error": _error_text(e),
                "fail": netdiag.describe_exc(e)}
    # ⚠️ 只缓存**非空**结果：空结果不缓存（一次抖动不该让这家「假死」整个 TTL）
    if entries:
        _cache_put(key, entries, ttl)
    return {"ok": True, "entries": entries, "error": ""}


def search_all(sources: list, title: str, author: str, limit: int = 5,
               options: dict = None, force: bool = False) -> dict:
    """按给定顺序检索多个源，合并候选并按匹配分倒序。

    ``options`` 按源给配置，形如 ``{"googlebooks": {"api_key": "..."}}``。

    返回 ``{entries, sources: {源: {ok, count, error}}, best}``；
    ``best`` 是分数最高的候选（低于调用方阈值时由调用方决定要不要用）。
    """
    order = [s for s in (sources or DEFAULT_ORDER) if s in SOURCES] or list(DEFAULT_ORDER)
    opts_map = options or {}
    merged, report = [], {}
    for name in order:
        res = search(name, title, author, limit, opts_map.get(name), force=force)
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
                  limit: int = 5, options: dict = None, force: bool = False) -> dict:
    """按系列名检索，再按成员书一致性重打分。

    返回 ``{entries, sources, best, members}``；``entries`` 已按一致性分倒序，
    ``best`` 是最高分候选（**可能是 0 分** —— 那就说明没搜到能对上的东西，
    由调用方如实回「未找到」，不要拿个不相关的候选硬凑简介）。
    """
    res = search_all(sources, series_name, "", limit=limit, options=options, force=force)
    entries = []
    for e in res["entries"]:
        e = dict(e)
        e["score"] = score_against_members(e, members)
        entries.append(e)
    entries.sort(key=lambda x: -float(x.get("score") or 0.0))
    return {"entries": entries, "sources": res["sources"],
            "best": entries[0] if entries else None, "members": len(members or [])}


# ---------------- 按 ID 取详情（第 102 期）----------------
# 「我已经知道这本书是哪一条，别再按书名猜。」检索回的是**最像的**那条，而 `provider_id`
# 是**精确键**：库里已经记过 `openlibrary_id` / `itunes_id` 的书，用它回查那一刻的官方记录，
# 比拿书名再猜一次更准，也少一轮打分。
#
# ⚠️ **只绑定真机核验过的家**（第 102 期探针结论，脚本在 `$TMP`；未核验的与原因见
#   `docs/TODO.md` §1「按 ID 取详情：两家源仍未核验」那条）：
#   ✅ itunes      `/lookup?id=` 与检索**同响应形状**（实测 trackId=597944491）
#   ✅ openlibrary `/works/OL…W.json` 返回 works 文档（实测 /works/OL17267881W）
#   ✅ audible      `/1.0/catalog/products/{asin}` 回 `{"product": {…}}`（**与检索同形状的单条**）
#                   —— 第 115 期真机核验：ASIN `B002V1OF70` 得 12 位演播者 + subtitle + series
#   ⛔ googlebooks 匿名额度耗尽（连打 3 个查询全 429）⇒ 端点没核过，不声明
#   ⛔ goodreads   `/book/show/{id}` 回 302 反爬 ⇒ 拿不到真实文档
# 没核过就声明 = 用一个「不知道会回什么」的端点假装有这项能力，用户点了只得到一个看不懂的
# 失败（`AGENTS.md` §7「不做假能力」）。剩下的家在 :func:`detail` 里回**明确中文回绝**
# —— 「这家没有这条通道」和「这家有但刚才失败了」是两件事，用户要做的处置不同。


def _detail_audible(provider_id: str, opts: dict) -> dict:
    """Audible 按 ASIN 取详情；查不到回 ``None``。

    ``/1.0/catalog/products/{asin}`` 与检索**同一端点**（尾段多一段 ASIN）、**同一个
    ``response_groups``**、回的是**同形状**的单条（只是包在 ``{"product": {...}}`` 里）
    ⇒ 复用 :func:`_audible_entry`，不另写字段映射（§7.1）。

    ⚠️ 区域**必须**跟着走（``opts["region"]``）：UK/DE/JP 的 ASIN 在 US 站查不到；
    而 `_detail_key` 已把 ``opts`` 并进缓存键，所以不同区域不会互相串缓存。
    """
    pid = _clean(provider_id)
    if not pid:
        return None
    host = _audible_region_host(opts)
    data = _get_json(AUDIBLE_CATALOG.format(host=host, tail="/" + pid),
                     params={"response_groups": AUDIBLE_RESPONSE_GROUPS})
    p = data.get("product")
    return _audible_entry(p) if isinstance(p, dict) else None


def _detail_itunes(provider_id: str, opts: dict) -> dict:
    """iTunes 按 ``trackId`` 取详情；查不到回 ``None``。

    ``/lookup?id=`` 与 ``/search`` **同一响应形状**（都是 ``{"resultCount", "results": []}``），
    所以复用 :func:`_itunes_entry` —— 不另写一份字段映射（§7.1 发现第二份实现 = 缺陷）。
    """
    pid = _clean(provider_id)
    if not pid:
        return None
    size = ITUNES_COVER_SIZES.get(_clean((opts or {}).get("resolution")).lower(), "1000x1000")
    data = _get_json(ITUNES_LOOKUP, params={"id": pid})
    items = [it for it in (data.get("results") or []) if isinstance(it, dict)]
    return _itunes_entry(items[0], size) if items else None


def _ol_work_key(provider_id: str) -> str:
    """把库里存的 OpenLibrary 标识归一成 ``/works/OL…W``；认不出来回空串。

    `openlibrary_id` 字段里落的就是 provider 当时的 ``key``（``/works/OL1234W``），
    但用户可能从别处粘一个裸 id 或带 URL 的串过来 —— 这里只认 **works** 形态。
    editions 的 ``/books/OL…M`` 认不出来 ⇒ 由调用方如实回绝，而不是拿它去猜一个 works 地址
    （猜错会回一条**别的书**的记录，比失败更糟）。
    """
    key = _clean(provider_id)
    if not key:
        return ""
    m = re.search(r"/works/(OL\d+W)", key, re.I) or re.fullmatch(r"(OL\d+W)", key, re.I)
    return "/works/" + m.group(1).upper() if m else ""


def _ol_description(d: dict) -> str:
    """取 works 文档的简介。

    ⚠️ 真机核验：这里的 ``description`` 是**字典**（``{"type": "/type/text", "value": …}``），
    不是字符串。直接透给 `_entry` 会被 `str()` 成一坨 Python 字面量落进书目简介。
    """
    desc = d.get("description")
    if isinstance(desc, dict):
        return desc.get("value")
    return desc


def _ol_author_names(d: dict) -> str:
    """works 文档里只有作者**边的 key**（``authors[].author.key``），名字要逐条再查一次。

    ⚠️ 最多取 3 位、单个作者查不到就跳过：详情是**补字段**用的，不该因为第 4 位作者超时
    就让整条详情作废（宁可少一个作者名，也不要整条失败）。
    """
    names = []
    for edge in (d.get("authors") or [])[:3]:
        key = _clean(((edge or {}).get("author") or {}).get("key"))
        if not key:
            continue
        try:
            ad = _get_json(OPENLIBRARY_BASE + key + ".json")
        except Exception:                       # noqa: BLE001 —— 一个作者查不到不算详情失败
            continue
        if _clean(ad.get("name")):
            names.append(_clean(ad.get("name")))
    return ", ".join(names)


def _detail_openlibrary(provider_id: str, opts: dict) -> dict:
    """OpenLibrary 按 works key 取详情；key 不合法 / 查不到回 ``None``。

    ⚠️ **works 端点不返回**出版年 / 出版社 / ISBN —— 那些挂在 edition 上（要再查
    ``/works/OL…W/editions.json``）。这三项**留空，不猜**：宁可少几个字段，也不要凭空给一本
    书安一个出版年，用户没法分辨那是不是编的。
    """
    key = _ol_work_key(provider_id)
    if not key:
        return None
    d = _get_json(OPENLIBRARY_BASE + key + ".json")
    if not _clean(d.get("title")):
        return None
    covers = [c for c in (d.get("covers") or []) if isinstance(c, int) and c > 0]
    return _entry(
        "openlibrary",
        title=d.get("title"),
        author=_ol_author_names(d),
        language=_pick_lang(d.get("languages")),
        description=_ol_description(d),
        tags=_split_subjects(d.get("subjects")),
        cover_url=OPENLIBRARY_COVER.format(cover=covers[0]) if covers else "",
        raw_id=key,
        provider_id=key,
    )


def detail(source: str, provider_id: str, opts: dict = None) -> dict:
    """按**该源自己的记录标识**取详情。返回 ``{ok, entry, error}`` —— 与 :func:`search` 同纪律，不抛异常。

    ``opts`` 是**该源的**配置（与 :func:`search` 同一份，如 iTunes 的 ``resolution``）。
    缓存与限流都照常走（同一家的详情与检索共用限流窗口）—— 这里**不设** ``force``：
    没有哪个调用方需要「跳过缓存拿详情」，加了就是投机抽象（§7.2）。
    """
    if source not in SOURCES:
        return {"ok": False, "entry": None, "error": f"未知源：{source}"}
    fn = _DETAIL_FETCHERS.get(source)
    if not fn:
        return {"ok": False, "entry": None,
                "error": "这家来源没有「按 ID 取详情」的通道，请改用按书名检索"}
    pid = _clean(provider_id)
    if not pid:
        return {"ok": False, "entry": None, "error": "缺少该来源的记录标识"}
    ttl = _ttl_of(source)
    key = _detail_key(source, pid, opts)
    cached = _cache_get(key, ttl)
    if cached:
        return {"ok": True, "entry": cached[0], "error": ""}
    _throttle(source)
    try:
        entry = fn(pid, opts or {})
    except Exception as e:                                   # noqa: BLE001 —— 与 search 同纪律
        return {"ok": False, "entry": None, "error": _error_text(e)}
    if not entry:
        # 请求成功但没有这条记录：如实说「没返回」，不要说成「可用」——
        # 界面若据此显示「已同步」，用户会以为元数据是新的。
        return {"ok": False, "entry": None, "error": "该来源没有返回这条记录（标识可能已失效）"}
    _cache_put(key, [entry], ttl)
    return {"ok": True, "entry": entry, "error": ""}


def probe(source: str, opts: dict = None) -> dict:
    """连通性自检（设置页用）。用一本几乎必然存在的书探路，返回耗时与结论。

    ⚠️ `force=True`：自检的价值就是「现在到底能不能用」——读缓存等于说谎。
    （缓存命中会让一次真的断线也显示「可用」。）
    """
    if source not in SOURCES:
        return {"ok": False, "message": f"未知源：{source}", "ms": 0}
    t0 = time.time()
    res = search(source, "Pride and Prejudice", "Jane Austen", 1, opts, force=True)
    ms = int((time.time() - t0) * 1000)
    if not res["ok"]:
        # 诊断路径才做交叉核对（本机解析 vs 公共解析）：把「本机 DNS 给错地址」
        # 升级成 `dns_polluted` 并把证据写进原因。⚠️ 数据路径（`search` 本身）不做这件事。
        msg = res["error"] or "不可用"
        ref = netdiag.refine(res.get("fail") or {})
        if ref.get("note"):
            msg = f"{msg}；{ref['note']}"
        return {"ok": False, "message": msg, "ms": ms}
    if not res["entries"]:
        return {"ok": False, "message": "能连通但没返回结果（可能被限流）", "ms": ms}
    return {"ok": True, "message": f"可用（{ms} ms）", "ms": ms}


# ---------------- 13 家真联网体检（第 59 期）----------------
# 把「这家现在到底能不能用、为什么不能用」变成**一次可复现的检查**，而不是让用户一家家
# 点「测试」自己拼印象。**只读**：不改配置、不写库、不注册任何东西（与 `probe` 同一纪律）。
#
# 为什么不直接复用 `probe`：
#   ① probe 只回「可用/不可用」不分原因 —— 而「被限流」和「站点改版导致解析不到」
#      要用户做的事完全不同（前者等一会或填 Key，后者只能等修复 / 换源）；
#   ② 抓取型（`fragile`）**请求成功但 0 条结果**才是它出故障的典型信号，
#      probe 把这种情况算成不可用却不解释；
#   ③ 13 家要一起看（谁掉线、谁限流），逐个点「测试」看不出整体。

#: 体检样本 = **每一家最容易命中的书名**。
#: ⚠️ 地区性目录必须用当地书名：拿 "Dune" 去查 Aladin（韩）/ Lubimyczytac（波兰）/
#: RanobeDB（轻小说）本来就搜不到，那会把「这家是好的」误报成「无结果」——
#: 误报比不测更糟：用户会去修一个根本没坏的东西。
#: **由声明派生**（第 102 期）：`Provider.health_sample` 空元组 ⇒ 用通用样本。
#: 顺序 = 声明顺序（`health_check` 的并发与呈现都按它）。
#: ⚠️ 与 `IMPLEMENTED` 同理，真实值在文件末尾的 `_derive_final()` 里填。
HEALTH_SAMPLES = {}

#: 体检结论分类（界面直接用这份文案，不要在两端各写一套说法）。
#: `ok` 与 `empty` 是两种不同的「通」：前者有结果，后者请求成功但解析不到东西。
HEALTH_KINDS = {
    "ok": "可用（有结果）",
    "empty": "能连通但没解析到结果",
    "missing_key": "未填密钥",
    "rate_limited": "被限流（429）",
    "denied": "被拒绝（401/403）",
    "blocked": "被反爬拦截（验证码）",
    "redirect": "被重定向（多为反爬）",
    "http": "接口返回错误",
    "timeout": "超时",
    "connect_timeout": "连接超时（连不上）",
    "network": "网络不可达",
    # 第 104 期：把「本机 DNS 的问题」单列 —— 它要用户做的事（改 DNS）与「站点故障」
    # （等修复 / 换源）完全不同，混在「网络不可达」里用户只能瞎猜。
    "dns": "域名解析失败",
    "dns_polluted": "域名解析被污染（本机 DNS 给错地址）",
    "tls": "TLS 握手失败",
    "proxy": "代理不可用（检查代理环境变量）",
    "parse": "响应解析失败",
    "error": "其它错误",
}


def _classify_error(err: str, exc: Exception = None) -> str:
    """把失败归到 :data:`HEALTH_KINDS` 的一类 —— 分类的意义是「告诉用户该做什么」。

    ⚠️ 关键词匹配是**必需的**：`search()` 会把各家抛出的异常统一折成字符串（单源失败不能
    影响别的源），所以到这里时异常类型已经丢了，只能靠 `_raise_for_status` 写下的中文口径
    与 `json` 解析器的英文消息识别（两条都要跟住，改一处就得改另一处的文案）。
    """
    text = str(err or "")
    low = text.lower()
    if "被限流" in text or "429" in text:
        return "rate_limited"
    if "被反爬拦截" in text or "captcha" in low or "robot" in low:
        return "blocked"
    if "被重定向" in text or "redirect response" in low:
        return "redirect"
    if "被拒绝" in text or "401" in text or "403" in text:
        return "denied"
    if "接口返回错误" in text or "http 4" in low or "http 5" in low:
        return "http"
    if "需要 api key" in low or "需要 ttbkey" in low or "需要密钥" in text or "需要设置" in text:
        return "missing_key"
    # 第 104 期：把「解析不出来 / 解析到错地址」与「连不上」分开。
    # ⚠️ 必须排在「超时」/「连接失败」**之前**：DNS 失败的原文常常同时含
    # `timed out` 或 `连接失败`，先匹配那两个就永远分不出来。
    if "解析被污染" in text or "dns 被污染" in low:
        return "dns_polluted"
    if "域名解析" in text or "name or service not known" in low or "getaddrinfo" in low \
            or "gaierror" in low or "nodename nor servname" in low or "11001" in text:
        return "dns"
    if "tls" in low or "ssl" in low or "certificate verify failed" in low \
            or "unexpected_eof" in low:
        return "tls"
    if "代理" in text or "proxy" in low:
        return "proxy"
    if "连接超时" in text or "connecttimeout" in low or "connect timeout" in low:
        return "connect_timeout"
    if "超时" in text or "timeout" in low:
        return "timeout"
    # JSON 解析失败的原文是英文（json.JSONDecodeError）：换个报错口径这里就会漏分类，
    # 所以除了关键词还看异常类型（直接调 `health_one` 的路径拿得到异常对象）。
    if isinstance(exc, ValueError) or "json" in low or "expecting value" in low \
            or "expecting ',' delimiter" in low or "extra data" in low:
        return "parse"
    if "连接失败" in text or "connect" in low or "网络" in text:
        return "network"
    return "error"


def health_one(source: str, opts: dict = None, title: str = "", author: str = "",
               limit: int = 3) -> dict:
    """单家体检：``{id, label, group, fragile, needs_config, ok, kind, ms, count, first, error}``。

    `first` 回「命中的第一条：书名 · 作者」—— 让人一眼确认它返回的**确实是这本书**，
    而不是只看「可用」两个字就放心（可用但答非所问也是问题）。
    """
    meta = SOURCES.get(source) or {}
    base = {"id": source, "label": meta.get("label") or source,
            "group": meta.get("group") or "", "fragile": bool(meta.get("fragile")),
            "needs_config": bool(meta.get("needs_config"))}
    if source not in _FETCHERS:
        return {**base, "ok": False, "kind": "error", "ms": 0, "count": 0, "first": "",
                "error": "本项目没有该来源的抓取器"}
    if needs_key(source) and not _clean((opts or {}).get("api_key")):
        # 与抓取口径一致：没填密钥就**不发外呼** —— 体检也不该拿一次注定失败的请求当「测试」
        return {**base, "ok": False, "kind": "missing_key", "ms": 0, "count": 0, "first": "",
                "error": "未填密钥：填好后再体检这一家"}
    if not _clean(title):
        # 只给 source 时回落到**该家的地区样本**：否则 `search` 会以「书名为空」提前返回，
        # 体检结论变成「源不可用」—— 把人引去查一个根本没坏的源（误报比不测更糟）。
        sample = HEALTH_SAMPLES.get(source) or HEALTH_SAMPLE_DEFAULT
        title, author = sample[0], sample[1]
    t0 = time.time()
    # ⚠️ `force=True` = 诊断模式，**缓存与限流都旁路**（见 `search` 的说明）：体检是并发 4 路，
    # 不能被「串行补间隔」拖到自己的超时；用 force 也保证结论反映**当下** ——
    # 缓存命中会让一次真的断线也显示「可用」。
    res = search(source, title, author, limit, opts, force=True)
    ms = int((time.time() - t0) * 1000)
    entries = res.get("entries") or []
    if not res.get("ok"):
        err = res.get("error") or "不可用"
        # 同上：体检是诊断路径，值得为「到底是谁的问题」多花一次解析核对。
        ref = netdiag.refine(res.get("fail") or {})
        if ref.get("note"):
            err = f"{err}；{ref['note']}"
        return {**base, "ok": False, "kind": ref.get("kind") or _classify_error(err),
                "ms": ms, "count": 0, "first": "", "error": err}
    if not entries:
        return {**base, "ok": False, "kind": "empty", "ms": ms, "count": 0, "first": "",
                "error": "请求成功但没解析到结果：站点结构可能变了，或这家确实没有这本样本"}
    e = entries[0]
    return {**base, "ok": True, "kind": "ok", "ms": ms, "count": len(entries),
            "first": " · ".join(x for x in (str(e.get("title") or ""),
                                            str(e.get("author") or "")) if x),
            "error": ""}


def health_check(mf: dict = None, sources: list = None, query: str = "",
                 per_timeout: float = 12.0, workers: int = 4, limit: int = 3) -> dict:
    """全部（或指定几家）**真联网**体检：并发跑、单家超时、失败分类。

    - `query` 非空 ⇒ 所有家都用这个关键词；为空 ⇒ 用 :data:`HEALTH_SAMPLES` 的**各家样本**
      （地区性目录用当地书名，否则会误报「无结果」）；
    - 单家超时（默认 12s）到点即记为 `timeout`，**不拖住整轮** —— 体检的价值是「一次看清」，
      某一家卡住不该让另外 13 家的结论也拿不到；
    - 并发 4 路（`workers`）：13 家串行最坏要几分钟，用户会以为界面卡死；
    - **只读**：不改配置、不写库。
    """
    mf = mf or {}
    order = [s for s in (sources or list(SOURCES)) if s in SOURCES]
    options = options_for(mf, order)
    ask = _clean(query)
    t0 = time.time()
    items: dict = {}
    if not order:
        return {"items": {}, "order": [], "summary": {"total": 0}, "kind_labels": HEALTH_KINDS,
                "query": ask, "samples": not ask, "elapsed_ms": 0, "ran_at": time.time()}

    workers = max(1, int(workers))
    waves = (len(order) + workers - 1) // workers
    tasks = {}
    with futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for sid in order:
            title, author = HEALTH_SAMPLES.get(sid, ("Pride and Prejudice", "Jane Austen"))
            if ask:
                title, author = ask, ""
            tasks[pool.submit(health_one, sid, options.get(sid), title, author, limit)] = sid
        done, _pending = futures.wait(list(tasks), timeout=per_timeout * waves + 2.0)
        for fut in done:
            sid = tasks[fut]
            try:
                items[sid] = fut.result()
            except Exception as e:                      # noqa: BLE001 —— 体检本身绝不能被一家带崩
                meta = SOURCES.get(sid) or {}
                items[sid] = {"id": sid, "label": meta.get("label") or sid,
                              "group": meta.get("group") or "",
                              "fragile": bool(meta.get("fragile")),
                              "needs_config": bool(meta.get("needs_config")),
                              "ok": False, "kind": _classify_error(str(e), e), "ms": 0,
                              "count": 0, "first": "", "error": str(e)}
    # 到点还没回来的：如实记「超时」，而不是留空让界面显示成「可用」
    for fut, sid in tasks.items():
        if sid in items:
            continue
        meta = SOURCES.get(sid) or {}
        items[sid] = {"id": sid, "label": meta.get("label") or sid,
                      "group": meta.get("group") or "",
                      "fragile": bool(meta.get("fragile")),
                      "needs_config": bool(meta.get("needs_config")),
                      "ok": False, "kind": "timeout", "ms": int(per_timeout * 1000),
                      "count": 0, "first": "", "error": f"超过 {per_timeout:.0f}s 未返回"}

    kinds = [i["kind"] for i in items.values()]
    summary = {k: kinds.count(k) for k in HEALTH_KINDS}
    summary["total"] = len(order)
    # 「真能用」= 有结果；`empty` 单列（要么样本不适用，要么站点结构变了）；
    # 「待处理」= 除了 ok / missing_key 之外的都算问题（missing_key 是配置未做，不是故障）
    summary["usable"] = kinds.count("ok")
    summary["problems"] = sum(1 for k in kinds if k not in ("ok", "missing_key"))
    return {"items": items, "order": order, "summary": summary, "kind_labels": HEALTH_KINDS,
            "query": ask, "samples": not ask, "elapsed_ms": int((time.time() - t0) * 1000),
            "ran_at": time.time()}

#: 模块加载末尾统一绑定（第 102 期）。
#: ⚠️ 顺序要紧：先 `_bind_declared()` 填 `_FETCHERS`，再 `_derive_final()` 由它派生
#: `IMPLEMENTED` / `HEALTH_SAMPLES`。放在文件末尾是因为它们依赖本文件后段的定义。
_bind_declared()
_derive_final()
