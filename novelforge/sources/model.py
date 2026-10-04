"""UnifiedBookSource —— 本项目书源规则（native）的**类型化契约**（第 94 期）。

## 它是什么、不是什么

用户口径要的是「内部统一模型，字段与 Legado 的 BookSource JSON 兼容」。落地形态：

- **执行模型仍是 native schema** —— `sources/rules.py` 顶部那段 docstring 就是**唯一**真值源，
  本文件的 :class:`UnifiedBookSource` 只是把它写成类型（读者对照 + 类型检查用）；
  :func:`to_native` 是**恒等函数**：不存在「统一模型 ⇄ native」的第二套互转（第二份拷贝 = 缺陷）。
- **Legado 兼容由转换承担**：`legado.convert()` 逐字段产出 native。那里做的是**值级变换**
  （选择器语法 / 模板变量 / 选项字典 / `@html`），不是一张改名表能表达的 ——
  所以本模块**不**提供「Legado 字段名 → native 字段名」的表：那张表会诱导别人拿它当转换入口，
  然后与 `convert` 各说各话。
- :data:`LEGACY_ALIASES` 管的是另一件事：**阅读 2.x 方言 → 3.x 键名**的归一，由
  `legado.normalize_legacy()` **唯一**消费（`formats/legado2.py` 只调它，不另写第二套）。

⚠️ 计划里这张表叫 `LEGADO_ALIASES`、语义写作「Legado → native」。落地时**收窄**成
「2.x → 3.x 键名」并改了名，理由见上一条 —— 这是有意的口径收窄，不是漏实现。
"""
from typing import NotRequired, TypedDict

__all__ = ["UnifiedBookSource", "LEGACY_ALIASES", "to_native"]


class UnifiedBookSource(TypedDict):
    """一条书源规则（= `SOURCES_DIR/<name>.json` 的内容）。取值语义见 `rules.py` docstring。"""

    # —— 必填 ——
    name: str                               # 唯一标识（也是规则文件名）
    domains: list[str]                      # 域名白名单（自动选源 + 判冲突都靠它）
    search: dict                            # 搜索：url / mode / container|path|pattern / fields

    # —— 可选：元信息 ——
    display_name: NotRequired[str]
    public: NotRequired[bool]
    headers: NotRequired[dict]              # 覆盖请求头（Legado 的 `header`）
    concurrency: NotRequired[int]           # 取整本时的抓取并发
    decrypt_js: NotRequired[str]            # 站点解密片段（Legado 的 `@js:` 移植过来）

    # —— 可选：取书 ——
    book: NotRequired[dict]                 # mode(toc|single) / toc / content / comic / audio
    chapter: NotRequired[dict]              # single 模式下的分章方式（toc|regex|auto）

    # —— 可选：**簿记**（不参与执行，只服务去重与溯源）——
    legado: NotRequired[dict]               # dedup_key / rule_hash / source_type / group / weight


#: 阅读 **2.x** 的键名 → 3.x 的键名（点号 = 嵌套路径）。
#:
#: ⚠️ **唯一**的方言归一表，且只收**实测出现过**的键 —— 样本是
#: `yeyulingfeng01/yuedu.github.io@1.1/202003.txt`（1537 条真实书源）的键频统计，
#: 括号里是条数。**没见过的键一个字都不猜**（不确定的键保持原样，由 `analyze` 如实报告）。
LEGACY_ALIASES: dict[str, str] = {
    "enable": "enabled",                            # 1537 —— 注意不是 `enabled`
    "ruleSearchUrl": "searchUrl",                   # 1534
    "ruleSearchList": "ruleSearch.bookList",        # 1531
    "ruleSearchName": "ruleSearch.name",            # 1531
    "ruleSearchAuthor": "ruleSearch.author",        # 1519
    "ruleSearchKind": "ruleSearch.kind",            # 1477
    "ruleSearchNoteUrl": "ruleSearch.bookUrl",      # 1530
    "ruleSearchLastChapter": "ruleSearch.lastChapter",   # 1452
    "ruleSearchCoverUrl": "ruleSearch.coverUrl",    # 1417
    "ruleSearchIntroduce": "ruleSearch.intro",      # 626
    "ruleChapterList": "ruleToc.chapterList",       # 1536
    "ruleChapterName": "ruleToc.chapterName",       # 1526
    "ruleContentUrl": "ruleToc.chapterUrl",         # 1532
    "ruleChapterUrl": "ruleBookInfo.tocUrl",        # 1391 —— 2.x 的「目录页地址」
    "ruleChapterUrlNext": "ruleToc.nextTocUrl",     # 1316
    "ruleBookContent": "ruleContent.content",       # 1534
    "ruleContentUrlNext": "ruleContent.nextContentUrl",  # 1274
    "ruleBookName": "ruleBookInfo.name",            # 1457
    "ruleBookAuthor": "ruleBookInfo.author",        # 1454
    "ruleBookKind": "ruleBookInfo.kind",            # 619
    "ruleBookLastChapter": "ruleBookInfo.lastChapter",   # 650
    "ruleIntroduce": "ruleBookInfo.intro",          # 1486
    "ruleCoverUrl": "ruleBookInfo.coverUrl",        # 1467
    "ruleBookUrlPattern": "ruleBookInfo.bookUrlPattern",  # 562
    "ruleBookInfoInit": "ruleBookInfo.init",        # 378
}

#: 「发现页」两代的名字：2.x 的 `ruleFind*` 与 3.x 的 `exploreUrl` / `ruleExplore.*`。
#: 本项目**没有发现页功能** ⇒ 两代都如实报告「已忽略」，但**不判不可执行**
#: （它不影响搜索 / 目录 / 正文这条主链，判死会把 1321 条本来能用的源误杀）。
EXPLORE_KEYS = ("ruleFindUrl", "ruleFindList", "ruleFindName", "ruleFindNoteUrl",
                "ruleFindAuthor", "ruleFindCoverUrl", "ruleFindIntroduce", "ruleFindKind",
                "ruleFindLastChapter", "exploreUrl", "ruleExplore", "enabledExplore")


def to_native(u: UnifiedBookSource) -> dict:
    """统一模型 → native 规则。**恒等函数**（不是「转换」）—— 见模块 docstring。"""
    return dict(u or {})
