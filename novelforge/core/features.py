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
    "opds_sources": "OPDS 订阅下载",
    "komga": "Komga 布局整理",
    "rename": "批量重命名",
    "duplicates": "重复书籍清理",
    "entity": "实体管理",
    "missing": "缺失资源",
    "logs": "转换日志",
    "output": "导出目录浏览",
}

#: 与格式无关的通用能力（三类库都有）
_COMMON = {"rename", "duplicates", "entity", "missing", "logs", "output"}

#: 类型 → 能力集。判据是**现有实现真实支持的范围**，不是「理论上可以」：
#:   · 元数据抓取只写 EPUB 的 OPF → 仅 ebook（漫画 / 音频暂不支持，见 metafetch.plan 的跳过说明）
#:   · 本地转换产出 EPUB → 仅 ebook
#:   · 书源下载产出 EPUB → 仅 ebook
#:   · OPDS 订阅可下 EPUB / CBZ → ebook + comic
#:   · Komga 布局整理针对系列化目录（电子书 / 漫画）→ ebook + comic
FEATURES_BY_TYPE = {
    "ebook": _COMMON | {"ebook", "pdf", "annotations", "metadata", "authors",
                        "convert", "sources", "opds_sources", "komga"},
    "comic": _COMMON | {"comic", "opds_sources", "komga"},
    "audiobook": _COMMON | {"audio"},
    "mixed": _COMMON | {"ebook", "pdf", "comic", "audio", "annotations", "metadata",
                        "authors", "convert", "sources", "opds_sources", "komga"},
}

#: 全部能力的并集（「全部书库」与未知类型都用它）
ALL_FEATURES = sorted(set().union(*FEATURES_BY_TYPE.values()))


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
