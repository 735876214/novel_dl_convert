"""库类型 → 能力（第 10 期 D8「全量显隐」的**真值源**）。

分工刻意如此：

- 后端只说「**这个库类型有哪些能力**」；
- 前端说「**哪一行菜单需要哪个能力**」（菜单是前端的东西，它才是所有者）。

于是：加一个库类型只改这里，加一个菜单只改前端，两边不必互相追赶。

两条约定：

1. **只登记「有区分度的能力」**。通用条目（仪表盘 / 统计 / 日志…）前端**不声明需求**，
   因此不必在这里列全，少一处会漏改的清单。
2. **「全部书库」= 全部能力的并集**（见 :func:`features_for` 传空值的情形）。
   默认视图不做裁剪 —— 否则用户一进来就发现功能少了，却不知道是因为「没选库」。
"""
from . import db


# ---------------- 能力清单 ----------------

#: 能力 → 中文名（设置页 / 书库管理页展示用；前端可照搬，避免两处各写一套文案）
FEATURE_LABELS = {
    "ebook": "电子书阅读",
    "pdf": "PDF 阅读",
    "comic": "漫画阅读",
    "audio": "有声书播放",
    "annotations": "批注",
    "metadata": "元数据抓取",
    "authors": "作者元数据",
    "convert": "本地转换（TXT → EPUB）",
    "sources": "书源搜索与下载",
    "komga": "Komga 布局整理",
    "rename": "批量重命名",
    "duplicates": "重复书籍清理",
    "entity": "实体管理",
    "missing": "缺失资源",
    "logs": "转换日志",
    "output": "导出目录浏览",
    "opds": "OPDS 对外目录",
}

#: 与格式无关的通用能力（三类库都有）
_COMMON = {"rename", "duplicates", "entity", "missing", "logs", "output", "opds"}

#: 类型 → 能力集。判据是**现有实现真实支持的范围**，不是「理论上可以」：
#:   · 元数据抓取：字段语义与「文件原值兜底」都建立在 EPUB 的 OPF 上，漫画 / 音频
#:     暂无可用源与字段语义 → 仅 ebook（见 metafetch.plan 的跳过说明）
#:     （第 18 期起结果只存服务端 DB，不再改写文件 —— 但**能力范围没变**）
#:   · 本地转换产出 EPUB → 仅 ebook
#:   · 书源下载产出 EPUB → 仅 ebook
#:   · Komga 布局整理针对系列化目录（电子书 / 漫画）→ ebook + comic
FEATURES_BY_TYPE = {
    "ebook": _COMMON | {"ebook", "pdf", "annotations", "metadata", "authors",
                        "convert", "sources", "komga"},
    "comic": _COMMON | {"comic", "komga"},
    "audiobook": _COMMON | {"audio"},
    "mixed": _COMMON | {"ebook", "pdf", "comic", "audio", "annotations", "metadata",
                        "authors", "convert", "sources", "komga"},
}

#: 全部能力的并集（「全部书库」与未知类型都用它）
ALL_FEATURES = sorted(set().union(*FEATURES_BY_TYPE.values()))

#: 每库覆盖项（第 13 期）→ 所需能力。**这里是唯一真值源**：前端据此隐藏不适用的覆盖项，
#: `core/lib_settings.py` 据此把「这个库根本没有的能力」对应的覆写直接**剔除**（不返回、不生效）。
#: 键是全局配置的**点分路径**（与 `libraries.settings` 里存的一致）。
#: 未登记的键 = 无条件可用（如递归子目录 / 非 TXT 收取，任何类型的库投递时都可能需要）。
SETTING_CAPS = {
    "output.format": "convert",              # 派生 MOBI/AZW3 依赖 Calibre 转换能力
    "output.layout": "komga",                # Komga 布局（系列目录）只对电子书 / 漫画有意义
    "metadata_fetch.enabled": "metadata",     # 在线元数据抓取（服务侧存储，不下写 EPUB）
    "metadata_fetch.auto_on_import": "metadata",
    "metadata_fetch.threshold": "metadata",
    "metadata_fetch.fields": "metadata",
    "naming.pattern": "rename",
    "naming.scope": "rename",
    # 刮削出版（第 18 期）：副本的目标读者就是 Komga 这类外部阅读器，
    # 故沿用 komga 能力（电子书 / 漫画库可见，有声书库不出现该项 —— Komga 不收有声书）。
    "scrape.enabled": "komga",
    "opds.expose": "opds",              # 该书库是否出现在对外 OPDS 目录里
}


def setting_capability(key: str) -> str:
    """某覆盖项需要的能力键；空串 = 无条件可用。"""
    return str(SETTING_CAPS.get(str(key)) or "")


def allows_setting(library_type, key: str) -> bool:
    """该库类型是否允许覆写这一项（无所需能力则不允许 —— 免得「设了却没反应」）。"""
    cap = setting_capability(key)
    return not cap or visible(library_type, cap)


def features_for(library_type=None, library_id=None) -> list:
    """某库（或某类型）的能力清单。

    ``library_id`` 为空 / ``library_type`` 为空 → 返回**全部能力**：
    「全部书库」是默认视图，不裁剪。
    """
    t = str(library_type or "").strip().lower()
    if not t and library_id:
        lib = db.get_library(library_id) or {}
        t = str(lib.get("type") or "")
    if not t:
        return list(ALL_FEATURES)
    return sorted(FEATURES_BY_TYPE.get(t, ALL_FEATURES))


def visible(library_type, feature: str) -> bool:
    """单个能力是否可见（供内部判断，如 OPDS 是否暴露某库）。"""
    return str(feature) in features_for(library_type)


def labels() -> dict:
    return dict(FEATURE_LABELS)


def matrix() -> dict:
    """完整矩阵（前端一次取回缓存即可，不必按库来回请求）。"""
    return {"types": {t: sorted(v) for t, v in FEATURES_BY_TYPE.items()},
            "all": list(ALL_FEATURES), "labels": labels()}
