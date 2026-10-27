"""实体页支持的类型表 —— 「实体名是什么、落在哪个字段、是不是多值」的**唯一真值源**。

第 159 期从「作者 / 系列」扩到 6 类（题材 / 出版社 / 语言 / 演播者）。这张表同时被
`core.library.entities`（聚合）、`core.fileops`（改名预览 / 应用）与 `server`（入参校验）
使用 —— 三处各写一份 kind→field 映射时，加一类实体最容易漏掉其中一处，而漏掉的表现是
「改名预览 0 本」或「应用后字段没变」，都不报错。

收藏夹（第 7 类）**不在**这里：它有独立的数据表与页面（新建 / 改名 / 加书 / 移出），
塞进这张「书字段派生的实体」表里会造出第二套改入口。
"""
from __future__ import annotations

#: kind → (书对象上的字段名, 是否多值)
KINDS: dict = {
    "author": ("author", False),
    "series": ("series", False),
    "tag": ("tags", True),
    "publisher": ("publisher", False),
    "language": ("language", False),
    "narrator": ("narrators", True),
}

#: kind → 中文名（接口错误信息 / 前端下拉共用一份文案）
LABELS: dict = {
    "author": "作者",
    "series": "系列",
    "tag": "题材",
    "publisher": "出版社",
    "language": "语言",
    "narrator": "演播者",
}


def field_of(kind: str) -> tuple:
    """`kind` → `(字段名, 是否多值)`；未知类型抛 `ValueError`（接口层转 400）。"""
    try:
        return KINDS[str(kind)]
    except KeyError:
        raise ValueError(f"type 只能是 {' / '.join(KINDS)}") from None


def values_of(book: dict, kind: str) -> list:
    """一本书在该实体维度上的**生效值**（统一成列表）。

    多值字段（题材 / 演播者）返回去掉空白的各个标签；单值字段返回 0 或 1 项。
    空值一律不产生条目 —— 实体页不该出现一个叫「」的分组。
    """
    field, multi = field_of(kind)
    raw = (book or {}).get(field)
    if multi:
        return [str(t).strip() for t in (raw or []) if str(t).strip()]
    v = str(raw or "").strip()
    return [v] if v else []
