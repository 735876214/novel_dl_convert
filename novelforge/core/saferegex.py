"""执行期正则的**唯一**入口：带超时；拿不到超时能力就**显式降级**（绝不假装有超时）。

## 为什么需要这一层

书源规则里的 ``pattern`` 是**用户 / 第三方书源文件**给的，直接在正文上跑等于把
ReDoS（灾难性回溯）的开关交给对方：一条 ``(a|a)*$`` 配上一段几十 KB 的正文，
`re` 就能把 worker 卡死几分钟 —— 而调用方（`rules._extract_regex` 等）**没有超时保护**，
表现是「这本书永远转不完」，没有任何日志指向正则。

## 两条铁律

1. **能超时就真超时**：装了 `regex` 就用它的 `timeout=`（它的超时是真的能中断匹配的，
   实测 ``(a|a)*$`` + 30 个 `a` 在 0.1 秒时抛 `TimeoutError`），超时映射成 :class:`RegexTimeout`。
2. **不能超时就如实说**：没装 `regex` 时**不撒谎**（:func:`state` 的 ``timeout=False``），
   且用**输入长度上限**把风险压住 —— 超长输入直接拒绝，理由说清是「降级」而不是「你的页面有问题」。
   绝不静默地跑一遍没有保护的正则然后假装没事。

规范/常量类正则（项目自己写死的模式、输入短且可信）**继续用标准库 `re`**，不绕这一层：
把它们也搬进来只会让「哪里真的需要超时保护」变得看不出来。
"""
import re

try:                                    # 「有没有超时能力」只有这一处判据
    import regex as _regex

    _AVAILABLE = True
except ImportError:                     # pragma: no cover - 取决于运行环境
    _regex = None
    _AVAILABLE = False

#: 执行期正则的默认超时（秒）。1 秒对「在一页 HTML 里找一个子串」是极宽裕的量级：
#: 超了基本就是回溯爆炸，而不是页面太大。
DEFAULT_TIMEOUT = 1.0

#: 降级路径（没有 `regex`）能接受的输入长度上限（字符）。
#:
#: ⚠️ **这是钝器，不是防线**：它挡不住「刚好在阈值内」的灾难性回溯。定 8 MiB 是为了
#: 不去误伤正常的书 —— 章节页普遍在 100 KB 以内，只有把**整本书拼成一个大字符串**再匹配
#: （`rules._split_regex`）才可能上到 MB 级，而十万字的小说大约 300 KB 文本、百万字约 3 MB。
#: 阈值以下的风险**如实承认**：降级状态在 `/api/sources/capabilities` 里就标 `timeout:false`，
#: 绝不因为「有了个上限」就假装有超时保护。
FALLBACK_MAX_INPUT = 8 * 1024 * 1024


class RegexTimeout(RuntimeError):
    """正则匹配超时（疑似 ReDoS）。调用方应当**只废掉这一项**，不要中断整次取书。"""


class RegexInputTooLong(RuntimeError):
    """降级路径（没有 `regex`）下输入超过 `FALLBACK_MAX_INPUT`，拒绝执行。"""


def available() -> bool:
    """有 `regex` 模块吗 —— 「执行期正则**能不能真超时**」的**唯一**判据。

    注意它问的不是「这一层能不能用」（降级路径也会用）；问的是**有没有超时能力**。
    """
    return _AVAILABLE


def state() -> dict:
    """给 `/api/sources/capabilities` 与设置页看的如实状态。

    ``timeout=False`` 是**如实报告**，不是错误：降级路径仍在跑，只是换了护栏
    （输入长度上限）。
    """
    if _AVAILABLE:
        return {"available": True, "timeout": True, "max_input": 0, "reason": "",
                "version": getattr(_regex, "__version__", "")}
    return {
        # `available` == 「有真超时」：降级路径仍在跑正则，但**没有**超时能力，
        # 所以这里必须是 False —— 否则调用方会把「有兜底」误读成「安全」。
        "available": False, "timeout": False, "max_input": FALLBACK_MAX_INPUT,
        "reason": "未安装 regex 模块 ⇒ 执行期正则**没有超时保护**，改用"
                  f"「输入长度上限 {FALLBACK_MAX_INPUT} 字符」兜底"
                  "（`pip install regex` 可恢复真正的超时）",
    }


class _Pattern:
    """`re.Pattern` 的最小同形包装：只暴露引擎真正用到的那几个方法。

    刻意**不做**成 `re.Pattern` 的子类 —— 那样降级路径的「没有超时」会被类型掩盖。
    """

    __slots__ = ("_pat", "_timeout", "_pattern_text")

    def __init__(self, pattern, flags: int = 0, timeout: float = DEFAULT_TIMEOUT):
        self._pattern_text = pattern
        self._timeout = float(timeout or DEFAULT_TIMEOUT)
        if _AVAILABLE:
            try:
                # ⚠️ `timeout=` **不能**写在 `compile()` 上 —— 实测 `regex` 会报
                # `ValueError: unused keyword argument 'timeout'`，它只认**逐次调用**的 `timeout=`。
                self._pat = _regex.compile(pattern, flags)
            except _regex.error as e:
                # `regex.error` 既不是 `re.error` 也不是 `ValueError`（实测），而调用方
                # （`selspec._replace_of` / `rules._regex_error` …）认的是 `re.error` ⇒ 在这里归一。
                raise re.error(str(e)) from e
        else:
            self._pat = re.compile(pattern, flags)

    # ---- 超时 / 降级的统一入口 ----
    def _guard(self, text) -> str:
        s = text if isinstance(text, str) else str(text or "")
        if not _AVAILABLE and len(s) > FALLBACK_MAX_INPUT:
            raise RegexInputTooLong(
                f"输入 {len(s)} 字符，超过降级路径的上限 {FALLBACK_MAX_INPUT}"
                "（本机没装 regex ⇒ 正则没有超时保护，只能靠限制长度兜底）")
        return s

    def _timeout_msg(self) -> str:
        return f"正则匹配超时（{self._timeout}s，疑似 ReDoS）：{self._pattern_text!r}"

    def _call(self, name: str, *args, **kw):
        if _AVAILABLE:
            kw.setdefault("timeout", self._timeout)
        fn = getattr(self._pat, name)
        try:
            return fn(*args, **kw)
        except TimeoutError as e:                       # `regex` 模块的超时
            raise RegexTimeout(self._timeout_msg()) from e

    def _lazy(self, it):
        """`finditer` 是**惰性**的：超时在迭代过程中才抛 ⇒ 必须在这里收，`_call` 收不到。

        （`rules._parse_search` / `_extract_pages` / `_split_regex` 用的都是 `finditer`，
        直接把迭代器交出去等于把唯一会超时的那一段漏到护栏之外。）
        """
        while True:
            try:
                m = next(it)
            except StopIteration:
                return
            except TimeoutError as e:
                raise RegexTimeout(self._timeout_msg()) from e
            yield m

    # ---- 与 `re` 同形的用法 ----
    def search(self, text, *a, **kw):
        return self._call("search", self._guard(text), *a, **kw)

    def match(self, text, *a, **kw):
        return self._call("match", self._guard(text), *a, **kw)

    def fullmatch(self, text, *a, **kw):
        return self._call("fullmatch", self._guard(text), *a, **kw)

    def findall(self, text, *a, **kw):
        return self._call("findall", self._guard(text), *a, **kw)

    def finditer(self, text, *a, **kw):
        return self._lazy(self._call("finditer", self._guard(text), *a, **kw))

    def sub(self, repl, text, *a, **kw):
        return self._call("sub", repl, self._guard(text), *a, **kw)

    @property
    def pattern(self):
        return self._pattern_text


def compile(pattern, flags: int = 0, timeout: float = DEFAULT_TIMEOUT) -> _Pattern:
    """编译一条**执行期**正则（模式来自书源规则 ⇒ 需要超时保护）。

    编不过就照常抛 `re.error` —— 调用方（`rules._extract_regex` 等）按既有约定处理。
    """
    return _Pattern(pattern, flags, timeout)
