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
import hashlib
import re

#: 单个路径片段的**字节**上限（POSIX ``PC_NAME_MAX`` 常见值：Linux ext4/xfs/btrfs、
#: macOS APFS、NTFS 都是 255 **字节**）。⚠️ 按字节而不是字符：中文一个字 3 字节
#: ⇒ 字符上「才 90 个」也可能超限。判据只在**这一处**定义，`fileops` / `komga` 都引用它。
NAME_MAX_BYTES = 255

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


def fit_segment(seg: str, limit: int = 255) -> str:
    """把一个路径片段压进**字节**上限（超限 ⇒ 截断 + 稳定后缀）。

    ⚠️ 第 283 期：文件系统按 **UTF-8 字节**限制单段名（ext4 / xfs / btrfs / APFS /
    NTFS 常见都是 255 ⇒ 中文约 85 字就到顶），而副本名是由**元数据**生成的
    （书名 / 作者 / 系列，书名本身允许到 200 **字符**）⇒ 一个 90 字的书名在 Linux 上
    直接 ``ENAMETOOLONG``：出版 / 入库 / 改名失败，而命名预览照常显示那个写不出来的名字。
    `NAME_MAX_BYTES` 早就是这个判据，但此前只用在**进来的**路径上
    （`safe_path` / `input_path`），**生成的**名字一路没判。

    截断规则：保留前 ``limit - 9`` 字节（按 UTF-8 边界切，不切半个字）+
    ``-<原名的 sha1 前 8 位>``。确定（同一本书每次算出同一个名字）且不同长名截断后
    不会撞成同一个。
    """
    raw = str(seg or "")
    limit = max(16, int(limit))
    if len(raw.encode("utf-8")) <= limit:
        return raw
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]
    budget = limit - len(digest) - 1
    head = raw.encode("utf-8")[:max(0, budget)].decode("utf-8", "ignore")
    return f"{head}-{digest}"
