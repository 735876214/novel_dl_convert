"""官方书城「目录来源」：注册表 + **只取目录**（第 85 期批次 B）。

## 只取目录，绝不取正文

本模块只返回**章节标题与顺序**（外加可选的卷层级），**不调用规则的 `book.content`、
不抓任何一章的正文**。两条理由：用户口径本来就是「本地目录不清楚时去正版书城对一下目录」；
而只读目录页是最小侵入的抓法 —— 不复制付费内容，也不把整站页面的并发压力引到这台机器上。

## 与书源体系共用一套规则，不另开一套

· 规则字段照抄 `sources/rules.py` 顶部的 schema，`book.mode="toc"` 用的就是那份 `toc`
  提取器（本模块只做「不取正文」的裁剪）；
· 出网走 `DownloadManager._client`（**同一份** Cookie 目录 / host_replace / 重试口径）；
· 开关走 `DownloadManager.gate_reason(source, feature="toc")` —— 闸门只有一个入口
  （第 71 期定的），第 85 期给它加了「**用途**」维度：下载内容与取目录是两个开关。

## 注册表的诚实口径（AGENTS.md：不做假交互）

`status` 三档如实标注，**没有第四档「大概是好的」**：

· `available`         —— 内置规则且验证过；
· `needs_credentials` —— 规则在，但要登录凭据（Cookie）才拿得到目录；
· `unsupported`       —— 只有登记与说明，本批**没写规则**。

⚠️ 番茄 / 起点两条内置规则标 **`verified: False`**：URL 与选择器是按站点**公开页面结构**
写就的，但**没有在联网环境里验证过**（本机对外网络受限，见 `AGENTS.md` 的离线约定）。
界面必须如实显示「未验证」，并提供「试取目录」把失败原因原文摆出来 ——
拿不准就说不准，**不许显示成可用**。规则随接口回给前端，可一键复制到「书源管理」里改。
"""
from __future__ import annotations

# 归一化的**单一真值源在 core**：搜索匹配与章节对齐用同一套归一，否则会出现
# 「搜索匹配上了、章节却一条都对不上」这种两边各自看着都对的鬼故事。
from ..core.reading_list import norm_title
from . import creds
from . import rules as rules_mod

#: 注册表三档状态（别加第四档）
AVAILABLE = "available"
NEEDS_CREDENTIALS = "needs_credentials"
UNSUPPORTED = "unsupported"

#: 自动匹配的最低置信度：低于它**如实报「没匹配到」**，不做「大概是这本」的猜测 ——
#: 猜错的表现是「目录被另一本书的章节名覆盖」，比没匹配到难查得多。
MATCH_MIN = 0.62

#: 内置来源。`rule` 为 None = 本批没写规则（`status` 也就必须是 unsupported）。
SOURCES: tuple = (
    {
        "id": "fanqie",
        "label": "番茄小说",
        "home": "https://fanqienovel.com",
        "status": NEEDS_CREDENTIALS,
        "verified": False,
        "note": "目录页可匿名打开，但站点有风控与字体映射；建议在浏览器登录后把 Cookie "
                "放进凭据目录再取。规则未在本机验证过。",
        "rule": {
            "name": "fanqie-toc",
            "display_name": "番茄小说（只取目录）",
            "domains": ["fanqienovel.com"],
            "public": False,
            "search": {
                "url": "https://fanqienovel.com/search?query={title}",
                "mode": "regex",
                "pattern": r'<a[^>]+href="(?P<url>/(?:page|reader)/[^"]+)"[^>]*>'
                           r'(?P<title>[^<]{2,60})</a>',
            },
            # book.mode=toc 只要 `toc` 这一段；**刻意不写 `content`** ——
            # 我们只取目录，写了反而会让「这个规则能取正文」看起来成立。
            "book": {
                "mode": "toc",
                "toc": {
                    "mode": "regex",
                    "pattern": r'<a[^>]+href="(?P<href>/reader/[^"]+)"[^>]*>'
                               r'(?P<title>[^<]{1,60})</a>',
                },
            },
        },
    },
    {
        "id": "qidian",
        "label": "起点中文网",
        "home": "https://www.qidian.com",
        "status": NEEDS_CREDENTIALS,
        "verified": False,
        "note": "书目页的章节目录是**懒加载**的（需要浏览器渲染或站点接口），本批只写了直连 "
                "HTML 的规则 —— 大概率取不到；这只是一个起点，请在「书源管理」里改好后"
                "用「试取目录」验证。",
        "rule": {
            "name": "qidian-toc",
            "display_name": "起点中文网（只取目录）",
            "domains": ["qidian.com"],
            "public": False,
            "search": {
                "url": "https://www.qidian.com/so/{title}.html",
                "mode": "regex",
                "pattern": r'<a[^>]+href="(?P<url>//book\.qidian\.com/info/\d+)"[^>]*>'
                           r'(?P<title>[^<]{2,60})</a>',
            },
            "book": {
                "mode": "toc",
                "toc": {
                    "mode": "css",
                    "container": "#j-catalogWrap a[href*='/chapter/']",
                },
            },
        },
    },
    {
        "id": "weread",
        "label": "微信读书",
        "home": "https://weread.qq.com",
        "status": UNSUPPORTED,
        "verified": False,
        "note": "目录要登录态且接口带签名参数，本批**只登记、不宣称可用**。",
        "rule": None,
    },
    {
        "id": "zhangyue",
        "label": "掌阅",
        "home": "https://www.zhangyue.com",
        "status": UNSUPPORTED,
        "verified": False,
        "note": "目录接口需要 App 侧凭据，本批只登记。",
        "rule": None,
    },
    {
        "id": "jjwxc",
        "label": "晋江文学城",
        "home": "https://www.jjwxc.net",
        "status": UNSUPPORTED,
        "verified": False,
        "note": "目录页结构随反爬变化快，本批只登记；欢迎在「书源管理」里写好规则后回填。",
        "rule": None,
    },
)

_BY_ID: dict = {s["id"]: s for s in SOURCES}


def catalogue() -> list[dict]:
    """给接口用的注册表（含规则原文，便于用户复制到「书源管理」里修）。

    `usable` 一栏**不在这里算** —— 它取决于闸门（`download.toc_enabled`）与凭据，
    由调用方把 :func:`state_note` 的结果并进来，免得两处各写一份判定。
    """
    return [{k: v for k, v in s.items()} for s in SOURCES]


def by_id(source_id: str) -> dict | None:
    return _BY_ID.get(str(source_id or ""))


def cookie_name(source_id: str) -> str:
    """取目录时**实际读的** Cookie 文件名（第 86 期补的契约）。

    ⚠️ 第 85 期实测踩过的坑：取目录走 `DownloadManager._client(rule_class(source_id))`，
    而客户端是按**规则名**取文件名的 —— 番茄的规则名是 `fanqie-toc`，注册表 id 却是 `fanqie`。
    界面若按 id 显示 / 写入登录态，就会出现「明明保存了却还是匿名」这种最难查的静默失败。
    这里把「id → 文件名」钉成唯一一处；文件名的拼法本身仍在 `sources/creds.py`（唯一处）。
    未知 id 返回空串（调用方据此如实说「未知来源」，不编一个文件名出来）。
    """
    ent = by_id(source_id)
    if not ent:
        return ""
    return creds.cookie_name((ent.get("rule") or {}).get("name") or str(source_id))


def rule_class(source_id: str):
    """把某来源的内置规则编译成书源类（None = 没有规则）。"""
    ent = by_id(source_id)
    rule = (ent or {}).get("rule")
    return rules_mod.make_rule_class(rule) if rule else None


def state_note(ent: dict) -> str:
    """一条**可直接展示**的来源状态说明（界面与接口措辞只有这一份）。"""
    if not ent:
        return "未知来源"
    if ent.get("status") == UNSUPPORTED:
        return ent.get("note") or "本批未支持"
    if ent.get("status") == NEEDS_CREDENTIALS:
        return ent.get("note") or "需要登录凭据"
    return ent.get("note") or "可直接使用"


def validate_toc_rule(rule: dict) -> list[str]:
    """校验「只取目录」的规则：`rules.validate_rule` **去掉 `book.content` 那一条**。

    `rules.validate_rule` 对 `book.mode="toc"` 要求 `book.content`（取正文用）——
    那是**下载**路径的要求；取目录根本不读正文，要求它只会逼人写一段永远不用的假规则。
    其余校验逐条沿用，不另写一套（两份校验漂移比少一条校验危险得多）。
    """
    return [e for e in rules_mod.validate_rule(rule or {}) if "book.content" not in e]


def best_match(book: dict, candidates: list) -> tuple:
    """从搜索结果里挑最像这一本的一本，返回 ``(命中项 | None, 置信度)``。

    打分刻意简单可解释：**书名归一后完全相等 = 0.8 底分**，书名只是包含关系 = 0.5
    （同系列 / 带副标题常这样）；作者能对上再加 0.2，封顶 1.0。
    低于 :data:`MATCH_MIN` 一律返回 ``(None, 分数)`` —— 宁可如实说「没匹配到」。
    """
    want_t = norm_title(book.get("title"))
    want_a = norm_title(book.get("author"))
    best, best_score = None, 0.0
    for it in candidates or []:
        c_t, c_a = norm_title(it.get("title")), norm_title(it.get("author"))
        if not c_t or not it.get("url"):
            continue
        if want_t and c_t == want_t:
            score = 0.8
        elif want_t and (want_t in c_t or c_t in want_t):
            score = 0.5
        else:
            continue
        if want_a and c_a and (want_a == c_a or want_a in c_a or c_a in want_a):
            score += 0.2
        if score > best_score:
            best, best_score = it, min(score, 1.0)
    return (best, best_score) if best_score >= MATCH_MIN else (None, best_score)


def parse_toc(html: str, toc_rule: dict, base_url: str = "") -> list[dict]:
    """从书页 HTML 里提取目录 → ``[{"title", "depth"}, ...]``（书城顺序）。

    复用书源体系那份 `toc` 提取器（`rules._extract_links`），所以 CSS / regex 双通道、
    相对地址补全、`url_attr` 等口径与「下载」**完全一致** —— 不另写一套解析。

    第 85 期扩展（**可选字段，既有规则零影响**）：`toc.section_container` 给「卷 → 章」两级
    目录用 —— 写了它就按两层解析（卷 `depth=1`、章 `depth=2`），卷名取块内 `section_title`
    （默认 `h1,h2,h3`）；不写就是平铺（`depth=None`），此时「第X卷」这类卷首仍会在下游按
    **标题形态**被认出来（见 `core/reading_list.py` 的两条路线）。
    """
    toc_rule = toc_rule or {}
    section = toc_rule.get("section_container")
    if section:
        soup = rules_mod._soup(html)
        item_sel = toc_rule.get("container") or "a"
        attr = toc_rule.get("url_attr", "href")
        out: list = []
        for box in soup.select(section):
            head = box.select_one(toc_rule.get("section_title") or "h1, h2, h3")
            vol = head.get_text(" ", strip=True).strip() if head else ""
            if vol:
                out.append({"title": vol, "depth": 1})
            for n in box.select(item_sel):
                title = n.get_text(" ", strip=True).strip()
                if not title or not n.get(attr):
                    continue
                out.append({"title": title, "depth": 2})
        return out
    links = rules_mod._extract_links(html, toc_rule, base_url)
    return [{"title": t, "depth": None} for t, _ in links]


def _fail(source: str, note: str, **kw) -> dict:
    """失败结果：`ok=False` + **可直接展示的原因原文**（不要只说「失败」）。"""
    return {"source": source, "ok": False, "note": note, "entries": [],
            "store_ref": kw.get("store_ref", ""), "matched_title": kw.get("matched_title", ""),
            "matched_author": "", "confidence": float(kw.get("confidence", 0.0)),
            "manual": bool(kw.get("manual", False))}


async def fetch_toc(manager, source_id: str, *, book: dict, url: str = "",
                    query: str = "") -> dict:
    """取一本本地书在某来源上的目录（**只读目录页，不取任何正文**）。

    返回 `db.store_toc_save` 的形状。四种失败各有各的措辞：来源没登记、规则没实现、
    没匹配到（附最高置信度与阈值）、页面里没解析出章节（规则可能过期）——
    一股脑写「失败」等于什么都没说。

    `url` 有值 = **用户手动指定**（跳过匹配，`manual=True`、置信度记 1.0）；
    `query` 可覆盖搜索词（默认用书名）。闸门**不在这里判**：闸门只有一个入口，
    由调用方（路由 / 管理器）先问 `gate_reason(source, feature="toc")`，理由与
    「下载被拦时不该先入队」同源 —— 拦在业务逻辑之前。
    """
    ent = by_id(source_id)
    if not ent:
        return _fail(source_id, f"未知的目录来源：{source_id}")
    rule = ent.get("rule")
    if not rule:
        return _fail(source_id, f"「{ent['label']}」本批没有内置规则：{state_note(ent)}")

    cls = rule_class(source_id)
    src = cls()
    q = (query or book.get("title") or "").strip()
    manual = bool(url)
    matched, confidence, items = None, 0.0, []
    async with manager._client(src) as c:
        if manual:
            matched, confidence = {"title": ent["label"], "author": "", "url": url}, 1.0
        else:
            try:
                items = await src.search(c, q) or []
            except Exception as e:                                    # noqa: BLE001
                return _fail(source_id, f"在「{ent['label']}」搜索时失败：{e}")
            matched, confidence = best_match(book, items)
            if not matched:
                return _fail(source_id,
                             f"在「{ent['label']}」里没匹配到《{book.get('title')}》"
                             f"（最高置信度 {confidence:.2f}，阈值 {MATCH_MIN}）"
                             "—— 可以手动填书页地址重取",
                             confidence=confidence)
        try:
            html = await src.fetch_content(c, matched["url"])
        except Exception as e:                                        # noqa: BLE001
            return _fail(source_id, f"打开「{ent['label']}」的书页失败：{e}",
                         store_ref=matched["url"], confidence=confidence, manual=manual)
    entries = parse_toc(html, (rule.get("book") or {}).get("toc") or {}, matched["url"])
    if not entries:
        return _fail(source_id,
                     f"「{ent['label']}」的书页里没解析出章节 —— 规则大概过期了"
                     "（可在「书源管理」里贴着这份规则改）",
                     store_ref=matched["url"], matched_title=matched.get("title", ""),
                     confidence=confidence, manual=manual)
    return {
        "source": source_id, "ok": True, "note": "",
        "store_ref": matched["url"],
        "matched_title": matched.get("title", ""),
        "matched_author": matched.get("author", ""),
        "confidence": confidence, "manual": manual, "entries": entries,
    }
