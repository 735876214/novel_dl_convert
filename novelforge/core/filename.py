"""跨平台文件名安全：**一份判据，两处用途**（第 95 期收敛）。

`core/komga.py` 与 `core/fileops.py` 原先各写了一份**逐字相同**的正则
（`[\\/:*?"<>|\\x00-\\x1f]` + 结尾的 `[. ]+$`），而 `komga.py` 的注释也自陈「同规则但
故意不共用」——理由是 layering：`fileops` 依赖 `library`，而布局计算要能被 `pipeline`
**直接**调用，让 `komga` 反过来 import `fileops` 会把 library 拖进 pipeline 的导入链。

于是两边都要用的判据只能落在一个**谁都不依赖的叶子模块**里（本文件，只 import `re`）：
调用方各自保留自己那点差异（`clean_segment` 折叠内部空白、`sanitize_stem` 不折叠），
共用的是**「哪些字符不安全、什么结尾要去掉」这条判据本身**。

⚠️ 改动这里会同时影响「出版副本的相对路径」与「改名工具的清洗结果」——两者都写进
用户看得见的文件名，收尾请跑 `tests/test_naming_tokens.py` / `test_book_dock.py` /
`test_audiobook_publish.py` / `test_rename_server_side.py`。
"""
import re

#: 跨平台都不安全的文件名字符（含控制字符）
UNSAFE_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')

#: 结尾的点与空格：Windows 会静默吃掉它们，于是「实际落盘名」与预期不符
TRAILING_JUNK = re.compile(r"[. ]+$")


def strip_unsafe(text: str) -> str:
    """去掉不安全字符与结尾的「点 / 空格」。

    **不动内部空白** —— 要不要把连续空白折叠成一个空格由调用方决定
    (`komga.clean_segment` 折叠，`fileops.sanitize_stem` 不折叠，这是既有的行为差异)。
    """
    s = UNSAFE_CHARS.sub("", (text or "").strip())
    return TRAILING_JUNK.sub("", s)
