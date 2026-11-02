"""书目**规则筛选**（第 221 期）—— 把「筛一批书」的临时口径也交给服务端。

第 218 期把**智能书架**（存下来的规则）的求值搬到了服务端；书架页自己的那五项
临时筛选（格式 / 语言 / 题材 / 封面 / 阅读状态）却还在**前端**做 —— 于是同一件事
有两处实现：

- 前端那五项只在**已加载的页**上筛（`shelfLoadedBooks`），大库里「筛一个排在很后面的
  格式」要靠「自动续拉最多 5 页」去碰运气；命中不到就显示「没有符合条件的书」，
  而库里其实有 —— 第 88 期 C 批的「诚实空态」只能说到这里为止。
- 前端那五项与智能书架的规则**语义不同**（例如状态：前端用 `statusBucket` 三档，
  规则用八档真实状态），两套口径在同一页上并存。

本期做两件事：

1. **临时筛选也走服务端**：``GET /api/books`` 接受一条**内联规则**（``rules`` + ``match``），
   与 ``scope_id``（已存的书架）**共用同一条求值路径**（``core/bookrules.py``）。
   前端把五项筛选翻译成一条规则发过去，服务端算完再分页。
2. **规则筛选器 UI**：书架的筛选面板里可以**直接用规则**（字段 + 操作 + 值），
   实时预览命中数（走 ``POST /api/smart-scopes/preview``），命中后按服务端结果取书。

⚠️ **内联规则不进库**：它是一次性的筛选口径，不产生新表、不留历史。想要复用就
「存成智能书架」（``POST /api/smart-scopes``）—— 那是**另一件事**，入口在智能书架页。

⚠️ **求值仍在 Python 层**（不是 SQL）：书目元数据有 ``meta_override`` 覆盖层，
SQL 直接筛会漏掉用户改过的标题 / 作者；本期省的是「同一判据两份实现」与
「筛选口径与服务端结果对不上」，不是 DB 读。
"""
from __future__ import annotations

from . import bookrules

#: 内联筛选的规则条数上限（一次筛选最多多少条规则）。
#:
#: 理由：规则是**用户每次筛选临时拼**的，不是配置。上限太小会挡住「作者 A 且
#: 题材 B 且 评分至少 4 且 有封面」这类正常组合；太大则一次请求能拖着上千条规则
#: 做 O(规则数 × 书目数) 的求值。60 条已远超真实使用（正常在 5 条以内），
#: 又不至于让一条请求变成无界计算。
MAX_INLINE_RULES = 60


def parse_inline(payload) -> tuple:
    """解析内联筛选的 ``(rules, match)``。

    - ``payload`` 为空 / None ⇒ ``([], "all")``（调用方按「不筛选」处理）。
    - ``rules`` 非空 ⇒ 交给 :func:`bookrules.validate` 校验（未知字段 / 非法操作 /
      非法数值一律拒绝，消息可直接展示）。
    - ``match`` 缺省 ``all``。

    校验失败抛 :class:`ValueError`（由路由转成 400）。
    """
    if not payload:
        return [], "all"
    if not isinstance(payload, dict):
        raise ValueError("筛选规则必须是对象")
    rules = payload.get("rules") or []
    if not isinstance(rules, list):
        raise ValueError("筛选规则必须是数组")
    if len(rules) > MAX_INLINE_RULES:
        raise ValueError(f"筛选规则最多 {MAX_INLINE_RULES} 条")
    if not rules:
        return [], "all"
    match = str(payload.get("match") or "all")
    return bookrules.validate(rules, match)


def rules_from_query(q: str) -> tuple:
    """把查询串（``rules`` 参数）里的 JSON 解析成 ``(rules, match)``。

    查询串不是 JSON 本体而是**URL 编码后的 JSON**（``{"rules": [...], "match": "all"}``），
    解析失败抛 :class:`ValueError`。
    """
    import json

    if not q or not str(q).strip():
        return [], "all"
    try:
        payload = json.loads(str(q))
    except (ValueError, TypeError):
        raise ValueError("筛选规则不是合法的 JSON") from None
    return parse_inline(payload)
