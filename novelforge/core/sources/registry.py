"""来源声明表：一家源的全部事实**只写在这里一处**。

## 为什么有这个模块（第 102 期）

在这之前，一家源的信息散在 `core/metasources.py` 的 **7 张扁平表**里：

| # | 表 | 内容 |
|---|---|---|
| 1 | `SOURCES` | label / group / needs_config / fragile / config_fields |
| 2 | `_FETCHERS` | 检索函数 |
| 3 | `_ISBN_FETCHERS` | 按 ISBN 精确检索（子集） |
| 4 | `SOURCE_ID_FIELD` | 该源那条记录的标识落到哪个元数据字段（子集） |
| 5 | `LANG_AFFINITY` / `LANG_BROAD` | 语种亲和 |
| 6 | `HEALTH_SAMPLES` | 体检样本 |
| 7 | `IMPLEMENTED` | 真的能抓的源 id 元组 |

新增一家至少要动 6 处，而且**漏掉第 5 张表不会报错** —— 第 60 期就是因为这个才补了一条
契约测试（「每家在语种表里必须表态」）来兜底。本模块把 7 张表收成**一份声明**：
`Provider` 写全事实，`metasources` 的 7 张表全部由它**派生**。

## 三条边界（第 102 期刻意不做的）

1. **不搬实现**。`_search_*` 那些解析函数留在 `metasources.py` 原地 ——
   搬迁 1800 行解析代码是纯风险零收益。本模块的 `fetch` 字段只是**引用**它们。
2. **`SOURCES` 仍是 `dict[str, dict]`**。`metasources.SOURCES[id]["label"]` 这种取法在
   `server.py` / `metafetch` / `metascore` / 前端契约里到处在用（`provider_catalog()`
   直接 `{**meta}`）。所以 `Provider` 只在**内部**构造那张 dict，对外零破坏。
3. **不猜未来的源**。`Provider` 的字段全部**有当前用途**；不加「以后可能要」的开关
   （`AGENTS.md` §7.2）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .kinds import KINDS, KIND_ANIME, KIND_AUDIOBOOK, KIND_COMIC, KIND_EBOOK


@dataclass(frozen=True)
class Provider:
    """一家元数据来源的**全部事实**。

    `fetch_name` / `isbn_name` / `detail_name` 存的是 `metasources` 里函数的**名字**
    （避免循环 import：调用方在加载末尾按名字注入，见 `metasources._bind_declared`）。

    ⚠️ `frozen=True`：声明表在 import 期构造一次，运行期不该被改。
    """

    #: 源 id（配置里 `metadata_fetch.sources` 用的就是它，**改动即破坏用户配置**）
    id: str
    label: str
    #: 领域轴，取值见 `kinds.KINDS`
    kind: str
    #: 界面分组（`metasources.GROUPS` 里的一个）
    group: str
    home: str
    #: 界面上的说明文字（**纯文本**，设置页是插值渲染，见 `AGENTS.md` §5）
    note: str
    #: 检索函数名：`(title, author, limit, opts) -> list[候选]`。
    #: ⚠️ 存的是**函数名字符串**而不是函数对象：函数定义在 `core/metasources.py`，
    #: 而 `metasources` 要读本声明表 —— 互相 import 会成环。由
    #: `metasources._bind_declared()` 在本模块加载完成后按名字绑定，**绑不到就报错**。
    fetch_name: str = ""
    #: 可选：按 ISBN 精确检索的函数名 `(isbn, limit, opts) -> list[候选]`
    isbn_name: str = ""
    #: 可选：按该源自己的记录标识取详情的函数名 `(provider_id, opts) -> 候选 | None`
    detail_name: str = ""
    #: 该源那条记录的标识落到哪个元数据字段；空串 = 这家没有对应字段（**不硬塞别的字段**）
    id_field: str = ""
    #: 语种亲和（已被 `_lang_of` 归一的短码）；空元组 = 通吃
    langs: tuple = ()
    #: 必须填 Key 才有效（未填时抓取回明确中文错误，界面显示「需要设置」）
    needs_config: bool = False
    #: 「需要设置」时界面显示的**补充说明**（为什么需要 / 去哪申请）
    config_hint: str = ""
    #: 页面抓取型：站点改版就可能断，界面给「易失效」徽标
    fragile: bool = False
    #: 行内配置项声明 `(dict,)`，形状见 `metasources.config_fields_of`
    config_fields: tuple = ()
    #: 体检样本 `(title, author)`；空元组 = 用通用样本（见 `metasources.HEALTH_SAMPLES`）
    health_sample: tuple = ()
    #: 限流 `(次数, 秒)`；空元组 = 不限（如 `(1, 0.2)` = 每 0.2 秒最多 1 次）
    rate_limit: tuple = ()
    #: 检索结果缓存秒数；0 = 不缓存
    cache_ttl: int = 600
    #: 界面分组顺序（沿用上游 BookOrbit 的四个分区名）
    pass


#: 界面分组顺序（第 57 期：设置页「提供商」按组渲染，与上游 BookOrbit 同构）
GROUPS = ("一般书籍目录", "有声读物", "漫画和小说", "极权目录")


def _cfg_field(key: str, opt: str, label: str, **kw) -> dict:
    """行内配置项声明（形状与 `metasources.config_fields_of` 一致）。"""
    return {"key": key, "opt": opt, "label": label, **kw}


def _secret(key: str, opt: str, label: str, **kw) -> dict:
    return _cfg_field(key, opt, label, type="secret", **kw)


def _select(key: str, opt: str, label: str, options: list) -> dict:
    return _cfg_field(key, opt, label, type="select",
                      options=[{"value": v, "label": lb} for v, lb in options])


#: **全部来源声明**。顺序 = 界面上的默认呈现顺序（分组内按本表顺序）。
#:
#: ⚠️ **新增一家源只改这里**（加一条 `Provider`）+ 在 `metasources.py` 写它的解析函数。
#: 7 张派生表会自动跟上；契约测试会检查「声明与派生一致」。
DECLARED: tuple = (
    # ------------------------------------------------------------------ 一般书籍目录
    Provider(
        id="googlebooks", label="Google Books", kind=KIND_EBOOK, group="一般书籍目录",
        fetch_name="_search_googlebooks",
        isbn_name="_search_isbn_googlebooks",
        home="https://books.google.com",
        note="无需 API Key。简介与封面通常更全；部分地区会被拒绝（返回 403）。",
        # 匿名额度低（实测常撞 429），填 Key 显著改善 —— 属「可选配置」而非「必须」
        config_hint="可选：填 API Key 可显著提高额度（匿名常撞 429）",
        id_field="google_books_id",
        langs=(),                      # 通吃
        config_fields=(
            _secret("googlebooks_api_key", "api_key", "API 密钥",
                    placeholder="未设置（可选）"),
        ),
    ),
    Provider(
        id="amazon", label="Amazon", kind=KIND_EBOOK, group="一般书籍目录",
        fetch_name="_search_amazon",
        home="https://www.amazon.com/books",
        note="图书搜索页抓取。反爬严格，可能被要求验证或直接返回空，站点改版即失效。",
        fragile=True,
        id_field="amazon_id",
        langs=("en",),
        config_fields=(
            _secret("amazon_cookie", "cookie", "COOKIE",
                    placeholder="session-id=…; ubid-main=…; x-main=…",
                    hint="从浏览器复制 amazon.com 的 Cookie，不必带「Cookie」前缀"),
        ),
    ),
    Provider(
        id="goodreads", label="Goodreads", kind=KIND_EBOOK, group="一般书籍目录",
        fetch_name="_search_goodreads",
        home="https://www.goodreads.com",
        note="搜索页抓取（官方 API 已停发新 Key）。简介与评分齐全，但常触发反爬。",
        fragile=True,
        id_field="goodreads_id",
        langs=("en",),
    ),
    Provider(
        id="hardcover", label="Hardcover", kind=KIND_EBOOK, group="一般书籍目录",
        fetch_name="_search_hardcover",
        home="https://hardcover.app",
        note="GraphQL 接口，需要个人 API Token（hardcover.app → 账号设置里生成）。",
        needs_config=True,
        config_hint="需要 Hardcover API Token（网页版账号设置 → Hardcover API）",
        id_field="hardcover_id", langs=("en",),
        config_fields=(
            _secret("hardcover_api_token", "api_key", "API 密钥",
                    placeholder="eyJ...（在 hardcover.app/account/api 获取的令牌）"),
        ),
    ),
    Provider(
        id="openlibrary", label="Open Library", kind=KIND_EBOOK, group="一般书籍目录",
        fetch_name="_search_openlibrary",
        isbn_name="_search_isbn_openlibrary",
        detail_name="_detail_openlibrary",
        home="https://openlibrary.org",
        note="无需 API Key。中文书的覆盖率一般，但语种/年份/ISBN 较规范。"
             "按 ID 取详情走 works 文档（不带出版年/出版社/ISBN，那几项在 edition 上）。",
        id_field="openlibrary_id",
        langs=(),                      # 通吃
    ),
    Provider(
        id="itunes", label="iTunes", kind=KIND_EBOOK, group="一般书籍目录",
        fetch_name="_search_itunes",
        detail_name="_detail_itunes",
        home="https://itunes.apple.com",
        note="Apple 公开检索接口（无需 Key）。图书分类以英文为主，有声书与电子书分列。",
        id_field="itunes_id",
        langs=("en",),
        config_fields=(
            _select("itunes_cover_resolution", "resolution", "封面分辨率", [
                ("high", "high（1000×1000，默认）"),
                ("standard", "standard（100×100，接口原图）"),
            ]),
        ),
    ),
    Provider(
        id="kobo", label="Kobo", kind=KIND_EBOOK, group="一般书籍目录",
        fetch_name="_search_kobo",
        home="https://www.kobo.com",
        note="搜索页抓取（书店接口非公开）。注：本项目 Kobo **同步**仍不做，这里只是元数据来源。",
        fragile=True,
        id_field="kobo_id",
        langs=(),                      # 站点语种由配置项决定 ⇒ 通吃
        config_fields=(
            _select("kobo_region", "region", "国家", [
                ("us", "us"), ("uk", "uk"), ("ca", "ca"), ("au", "au"), ("jp", "jp"),
            ]),
            _select("kobo_language", "language", "语言", [
                ("en", "en"), ("zh", "zh"), ("ja", "ja"),
            ]),
        ),
    ),
    # ------------------------------------------------------------------ 有声读物
    Provider(
        id="audible", label="Audible", kind=KIND_AUDIOBOOK, group="有声读物",
        fetch_name="_search_audible",
        detail_name="_detail_audible",
        home="https://www.audible.com",
        note="有声书目录（时长 / 演播者 / 系列），走其公开 catalog 接口；区域站点结果不同。",
        fragile=True,
        id_field="audible_id",
        langs=("en",),
        rate_limit=(1, 0.5),
        config_fields=(
            _select("audible_region", "region", "地区", [
                ("us", "us（api.audible.com）"),
                ("uk", "uk（api.audible.co.uk）"),
                ("de", "de（api.audible.de）"),
                ("jp", "jp（api.audible.co.jp）"),
            ]),
        ),
    ),
    Provider(
        id="librofm", label="Libro.fm", kind=KIND_AUDIOBOOK, group="有声读物",
        fetch_name="_search_librofm",
        home="https://libro.fm",
        note="独立书店有声书平台，搜索页抓取（接口未公开）。",
        fragile=True,
        langs=("en",),
    ),
    # ------------------------------------------------------------------ 漫画和小说
    Provider(
        id="comicvine", label="Comic Vine", kind=KIND_COMIC, group="漫画和小说",
        fetch_name="_search_comicvine",
        home="https://comicvine.gamespot.com",
        note="漫画卷/期元数据，需要免费 API Key（comicvine.gamespot.com/api 申请）。",
        needs_config=True,
        config_hint="需要 Comic Vine API Key（免费申请，注意其限流 200 次/小时）",
        langs=("en",),
        rate_limit=(1, 18.0),          # 官方 200 次/小时 ⇒ 每 18 秒 1 次
        health_sample=("Saga", ""),
        config_fields=(
            _secret("comicvine_api_key", "api_key", "API 密钥",
                    placeholder="在 comicvine.gamespot.com/api 免费申请的密钥"),
        ),
    ),
    Provider(
        id="ranobedb", label="RanobeDB", kind=KIND_ANIME, group="漫画和小说",
        fetch_name="_search_ranobedb",
        home="https://ranobedb.org",
        note="轻小说数据库（含系列册序），公开 API v0、免 Key；官方要求 ≤60 次/分钟。",
        langs=("ja",),
        rate_limit=(1, 1.0),           # 官方 ≤60 次/分钟 ⇒ 每 1 秒 1 次
        health_sample=("狼と香辛料", "支倉凍砂"),
    ),
    # ------------------------------------------------------------------ 地区性目录
    Provider(
        id="lubimyczytac", label="Lubimyczytac", kind=KIND_EBOOK, group="极权目录",
        fetch_name="_search_lubimyczytac",
        home="https://lubimyczytac.pl",
        note="波兰语书籍目录，搜索页抓取。",
        fragile=True,
        langs=("pl",),
        health_sample=("Wiedźmin", "Andrzej Sapkowski"),
    ),
    Provider(
        id="aladin", label="Aladin", kind=KIND_EBOOK, group="极权目录",
        fetch_name="_search_aladin",
        home="https://www.aladin.co.kr",
        note="韩国 Aladin 书店目录，公开 TTB API，需要 TTBKey。",
        needs_config=True,
        config_hint="需要 Aladin TTBKey（aladin.co.kr 开放 API 页面申请）",
        id_field="aladin_id",
        langs=("ko",),
        health_sample=("채식주의자", "한강"),
        config_fields=(
            _secret("aladin_ttbkey", "api_key", "TTB 密钥",
                    placeholder="ttb...（在 aladin.co.kr 开放 API 页面申请）"),
        ),
    ),
)


def by_id() -> dict:
    """`{源 id: Provider}`。"""
    return {p.id: p for p in DECLARED}


def validate() -> None:
    """import 期契约校验：**声明表自身**必须自洽（派生表的一致性由用例钉住）。

    四条都是「漏了会静默出错」的项：

    1. id 唯一（重复会让后面那家覆盖前面）；
    2. kind 在 `kinds.KINDS` 里（拼错会让字段白名单查询静默返回空）；
    3. group 在 `GROUPS` 里（拼错会在界面上掉到「其它」分组）；
    4. `needs_config=True` 的家**必须**声明 secret 配置项 —— 这是最要紧的一条：
       `metasources.key_field_of()` 按「第一个 secret 项」推导主密钥键名，
       只写 `needs_config=True` 而忘了 `config_fields` 的话，界面会显示「需要设置」
       却**没有任何输入框**（用户没法设），而 `health_one` 又会因为读不到密钥而判
       `missing_key` —— 一家永远用不了的源，且看不出为什么。
    """
    seen = set()
    for p in DECLARED:
        if p.id in seen:
            raise ValueError(f"来源声明重复：{p.id}")
        seen.add(p.id)
        if p.kind not in KINDS:
            raise ValueError(f"{p.id} 的 kind 非法：{p.kind!r}")
        if p.group not in GROUPS:
            raise ValueError(f"{p.id} 的 group 非法：{p.group!r}")
        if p.needs_config and not any(f.get("type") == "secret" for f in p.config_fields):
            raise ValueError(f"{p.id} 声明了 needs_config 但没有 secret 配置项")
