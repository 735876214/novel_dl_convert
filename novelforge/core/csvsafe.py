"""CSV 单元格的公式注入防护（第 132 期）。

**问题**：CSV 是「一堆纯文本格子」，而 Excel / LibreOffice / Google Sheets 打开它时会
**把以 ``=`` ``+`` ``-`` ``@`` 开头的格子当公式求值**（OWASP 称 CSV Injection / Formula
Injection）。书库导出里的书名 / 作者 / 系列 / 题材来自**书目元数据**（一本从外面拖进来的
EPUB 就能自带 ``=HYPERLINK("http://…?"&A1)`` 或 ``=cmd|'/c calc'!A0`` 这种 DDE 串），
批注导出里的 ``quote`` / ``note`` 则是**从书里复制出来的原文** —— 换句话说，
**这些格子里的字不归我们控制，却会被用户的表格软件执行**。

**修法**：以危险字符开头的**文本**格子前面加一个单引号。Excel 与 LibreOffice 都把它当
「后面是文本」的标记（显示时隐藏这个引号），值保持原样；OpenSSL/脚本解析 CSV 时看到的是
多一个 ``'`` 的字符串，宁可多一个引号，也不能让一段书里的文字变成命令。

**只动 ``str``**：数字列（评分 / 序号 / 进度 / 批注数 / 章节号 ……）原样交给 ``csv.writer``，
否则 ``-1`` 这种值会被前缀成文本、在 Excel 里失去数值语义。
"""

#: 会让表格软件把格子当公式的起始字符（OWASP CSV Injection 的完整集合：
#: ``=`` 公式、``+`` / ``-`` 表达式或被吞掉的前缀、``@`` 函数、``\t`` / ``\r`` 用来
#: 在某些实现里把危险字符挤到「第二个字符」绕过检查）。
RISKY_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

#: 前缀标记。用单引号而不是反引号 / 空格：Excel 与 LibreOffice 都原生认它。
GUARD = "'"


def cell(value):
    """把一个单元格值转成「表格软件不会执行它」的形态。

    只对 ``str`` 生效（见模块 docstring）；``None`` 留给 ``csv.writer`` 写成空串。
    """
    if isinstance(value, str) and value.startswith(RISKY_PREFIXES):
        return GUARD + value
    return value


def row(values):
    """整行套一层 :func:`cell` —— 各导出端点的 ``writerow`` 都该走这里。"""
    return [cell(v) for v in values]
