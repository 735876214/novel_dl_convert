"""请求里的数值收敛（第 127 期）—— 「客户端给的数」的唯一判据。

**要解决的问题**：项目的数值入口大多长这样 ——

    percent = float(payload.get("percent", 0.0))

它接得住 ``"abc"``（``TypeError`` / ``ValueError`` ⇒ 400），却接不住 **``1e400``** 与
**``NaN``**：JSON 规范里没有这两个字面量，可 Python 的 ``json`` 认它们，于是

· ``1e400`` 解析成 ``inf`` ⇒ 原样落进 SQLite 的 REAL 列（SQLite 存得下 ``inf``）；
  而同一个值又会被**原样回写**进响应，starlette 的 ``JSONResponse`` 用
  ``allow_nan=False`` 序列化 ⇒ ``ValueError: Out of range float values are not JSON
  compliant: inf`` ⇒ **整条响应 500**。实测一次 ``PUT /api/books/{bid}/progress``
  带 ``percent=1e400``，就让 ``GET /api/books``（书架首页）、``GET /api/stats``、
  ``GET /api/books/{bid}/progress`` 同时恒 500 —— 一个坏读数把应用的可读面整个打掉。
· ``NaN`` 更阴：它与**任何数比较都是 ``False``**，所以 ``if x <= 0 or x > 86400``
  这类两侧判据**一处都拦不住**它（实测 ``/api/books/{bid}/session`` 的
  ``seconds: NaN`` 直冲 SQLite，撞 NOT NULL 后才是 500）。
· ``int(1e400)`` 抛的是 ``OverflowError`` —— 不在 ``except (TypeError, ValueError)``
  的覆盖范围内，同样 500（实测 ``locator`` / ``chapter`` / ``start_off`` / ``stars``
  四处）。

**收敛规则只有这一份**（``server`` / ``koreader`` / ``komga_api`` 都从这里取）：
非数 / ``inf`` / ``NaN`` ⇒ 「不是数」；有限但**越界 ⇒ 夹到区间内**。夹而不报错是有意的 ——
写失败会让这次进度整个丢掉，而「读到 -3 章」与「读到第 0 章」对用户是一回事。
"""
import math

#: 章节 / 页码序号的合法上限。够大到不会挡住真书（一部连载 1 万章也才 4 位），
#: 又能在 ``int()`` 之前把 ``1e400`` 这类值收进可存储范围。
MAX_INDEX = 10 ** 9

#: 时间戳（epoch 秒）的合法上限：公元 9999-12-31，与 ``datetime`` 的上限同量级。
MAX_EPOCH = 253402300799.0

#: 「取多少条」的上限。存在理由见 :func:`row_limit`：SQLite 的整数是 64 位，
#: 而 10 万条已经远超任何页面的实际需要（``LIMIT 100000`` 与「不限」在单用户书库里等价）。
MAX_ROWS = 100_000


def finite(v) -> "float | None":
    """``v`` ⇒ 有限实数；**不是数 / inf / nan ⇒ ``None``**。

    ``None`` 这个返回值本身就是判据：调用方据此决定「400 / 回落默认值 / 当成未知」，
    不需要各自再写一遍 ``math.isfinite``。``bool`` 也不算数（``True`` 会被 ``float()``
    收成 1.0，那是 Python 的类型泄漏，不该顺着 API 传下去）。
    """
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def clamp(v: float, lo: float, hi: float) -> float:
    """把有限实数夹到 ``[lo, hi]``（``v`` 必须已经过 :func:`finite`）。"""
    return max(lo, min(v, hi))


def percent(v, default: float = 0.0) -> float:
    """阅读百分比：有限实数 ⇒ ``[0, 100]``；非数 / inf / nan ⇒ ``default``。

    与 :func:`index` 分开，是因为**百分比的区间是一个语义常量**（0–100），
    散写在各处的 ``min(100.0, ...)`` 一旦漏掉一处就会写出「读到 999%」的书。
    """
    f = finite(v)
    return default if f is None else clamp(f, 0.0, 100.0)


def index(v, default: int = 0) -> int:
    """章节 / 页码序号：有限实数 ⇒ ``[0, MAX_INDEX]`` 的整数；非数 ⇒ ``default``。

    负数**夹到 0**而不是报错：序号是位置，``-1`` 在调用方那里几乎总是「哨兵」或
    「减出来的差」，把它写进库只会让读者「在第 -2 章」。
    """
    f = finite(v)
    return default if f is None else int(clamp(f, 0.0, float(MAX_INDEX)))


def epoch(v, default: float = 0.0) -> float:
    """时间戳（epoch 秒）：有限实数 ⇒ ``[0, MAX_EPOCH]``；非数 ⇒ ``default``。

    ``0`` 在这套 API 里是「没有这个日期」的合法取值（见 ``db.set_status``），
    所以 ``default`` 也允许是 0。
    """
    f = finite(v)
    return default if f is None else clamp(f, 0.0, MAX_EPOCH)


def row_limit(v, minimum: int = 1, cap: int = MAX_ROWS) -> int:
    """要绑进 SQL ``LIMIT ?`` 的条数：``min(max(minimum, int(v)), cap)``。

    **为什么要有这个函数**（第 130 期）：SQLite 的 INTEGER 是 64 位有符号整数，
    ``sqlite3`` 在**绑定参数**时对超出范围的对象抛 ``OverflowError`` —— 而这个异常
    **不在任何调用点的 ``except`` 里**，于是 ``GET /api/tasks?limit=10**30`` 直接 500。
    ``limit`` 是查询串给的（``int`` / ``str`` 都可能，FastAPI 会先转一次但转不出范围），
    所以「夹住」这一步只能落在**绑定点**：它是唯一知道「这个整数要进 SQLite」的地方。

    低端语义留给调用方：``task_list`` 传 ``minimum=1``（0 条没有意义），
    ``recycle_list`` 传 ``minimum=0``（``0`` = 不截断，见其 docstring）。
    非数 / 非有限 ⇒ ``minimum``（与 :func:`finite` 的判据同源）。
    """
    f = finite(v)
    n = minimum if f is None else int(f)
    return min(max(minimum, n), cap)
