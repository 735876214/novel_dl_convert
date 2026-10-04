"""第 93 期 · 在线阅读的章节对齐（`reading_list.align_shift` / `align_online` / `align_map`）。

用户拍板的判据（2026-10-03 原话）：「根据章节序号和章节名称进行匹配，若本章节及上下章节
共 5 章能有 3 章对应上就认定为同一章节，以线上章节名称进行确定进度等数据」。

⚠️ 这是**唯一实现**（服务端算，客户端只用结果）。所以这里逐条钉住：
正常命中、够不上门槛、边界收窄、**位移**（本地目录与源站目录差几章）、歧义、
以及「整本换了标题就一个字都不认」。

### 为什么这一版要**求位移**

本文件最初按「同下标比」实现，第 93 期真机验证时发现它对本项目**自己下载的书**一本都
对不上：成品 EPUB 的 spine 首条是 nav 目录页（`epub_builder.build_epub` 默认 ``nav=True``），
而章节 index 就是 spine 下标（`library._reading_list`）⇒ 本地 index 恒比源站章号大 1。
位移是**事实**，只能求出来，不能假定为 0（见 `align_shift` 的注释）。
"""
from novelforge.core import reading_list


def _local(titles: list, *, start: int = 0) -> list:
    """本地章节（`library._reading_list` 的形状：只取对齐要用的两个键）。"""
    return [{"index": i + start, "title": t} for i, t in enumerate(titles)]


_ONLINE = [f"第{i + 1}章 线上标题{i}" for i in range(10)]


def test_五章窗口命中三章即认定为同一章():
    local = _local([f"第{i + 1}章 本地标题{i}" for i in range(10)])
    # 只有 0 / 2 / 3 三章归一后与线上一致（其余标题不同）⇒ 恰好 3 命中 = 门槛
    local[0]["title"] = _ONLINE[0]
    local[2]["title"] = _ONLINE[2]
    local[3]["title"] = _ONLINE[3]
    local[4]["title"] = "完全不同的标题"
    assert reading_list.align_online(_ONLINE, local, 2) == 2


def test_只命中两章就不认():
    local = _local([f"第{i + 1}章 本地标题{i}" for i in range(10)])
    local[0]["title"] = _ONLINE[0]
    local[4]["title"] = _ONLINE[4]
    assert reading_list.align_online(_ONLINE, local, 2) is None


def test_归一化生效_全角标点与大小写不影响命中():
    online = ["第1章 ABC", "第2章 DEF", "第3章 GHI", "第4章 JKL", "第5章 MNO"]
    local = _local(["第１章 abc", "第2章 D E F", "第3章 gh,i", "第4章 jkl", "第5章 mno"])
    assert reading_list.align_online(online, local, 2) == 2


def test_书首边界_窗口收窄到三章_门槛随之降到三章():
    """边界上「只有 3 章可比」⇒ 门槛 `min(3, 可用数)` = 3（与 5 章取 3 是同一个尺度）。"""
    local = _local([_ONLINE[0], _ONLINE[1], _ONLINE[2], "x", "y"])
    assert reading_list.align_online(_ONLINE, local, 0) == 0, "3 章可比时对上 3 章 ⇒ 认"

    local2 = _local([_ONLINE[0], _ONLINE[1], "本地另一章", "x", "y"])
    assert reading_list.align_online(_ONLINE, local2, 0) is None, "只对上 2 章 ⇒ 不认（比 5 章窗口更严）"


def test_书尾边界同理():
    titles = [f"第{i + 1}章 线上" for i in range(5)]
    local = _local([f"第{i + 1}章 线上" for i in range(5)])
    assert reading_list.align_online(titles, local, 4) == 4


# ---------------- 位移（本文件存在的主要理由）----------------

def test_本地首条是nav目录页时位移为负一():
    """**本项目自己下载的书就是这个形状**：本地比源站多一条前置页（nav 目录页）。

    按同下标硬比会 0 命中（本地第 0 章是「三体」、源站第 0 章是「第1章」）——
    真机验证时「一本都对不上」的根因就在这。位移求出来之后，线上第 0 章 = 本地第 1 章。
    """
    local = _local(["三体"]) + _local(_ONLINE, start=1)
    assert reading_list.align_shift(_ONLINE, local) == -1
    assert reading_list.align_online(_ONLINE, local, 0) == 1
    assert reading_list.align_online(_ONLINE, local, 9) == 10


def test_源站多一条序章时位移为正一():
    """反方向同一个机制：源站目录里多一条本地没有的前置条目。"""
    online = ["序章"] + [f"第{i}章 正文{i}" for i in range(1, 11)]
    local = _local([f"第{i}章 正文{i}" for i in range(1, 11)])
    assert reading_list.align_shift(online, local) == 1
    assert reading_list.align_online(online, local, 5) == 4


def test_本地尾部多一条后记时仍能对齐():
    """锚点从末章**往前退**：源站只改了尾部个别标题（或本地尾部多一页）不该整本放弃。

    这里本地最后一条是「后记」，源站目录里没有它 —— 退到「第10章」当锚点照样求出位移。
    """
    online = [f"第{i}章 正文{i}" for i in range(1, 11)]
    local = _local(["三体"]) + _local(online, start=1)
    local.append({"index": 11, "title": "后记"})
    assert reading_list.align_shift(online, local) == -1
    assert reading_list.align_online(online, local, 9) == 10


def test_整本换了标题就一个字都不认():
    """标题全都对不上 ⇒ 没有候选位移 ⇒ `None`（宁可提示「对不上」，也不硬配）。"""
    online = [f"新版标题{i}" for i in range(10)]
    local = _local([f"旧版标题{i}" for i in range(10)])
    assert reading_list.align_shift(online, local) is None
    assert reading_list.align_online(online, local, 3) is None


def test_位移有歧义时不猜():
    """同一套标题在本地/线上都重复出现 ⇒ 多个位移都能通过 ⇒ **返回 `None`**。

    「猜一个」在这里就是「把进度写到别人身上」，所以有歧义一律不认。
    """
    online = ["正文"] * 10
    local = _local(["正文"] * 10)
    assert reading_list.align_shift(online, local) is None


def test_align_map_整本映射一次求出():
    local = _local(["三体"]) + _local(_ONLINE, start=1)
    assert reading_list.align_map(_ONLINE, local) == {i: i + 1 for i in range(10)}

    other = _local([f"无关{i}" for i in range(5)])
    assert reading_list.align_map(_ONLINE, other) == {}, "对不上就没有映射（不是空值映射）"


def test_线上位置超出本地范围时返回None():
    """本地比线上短（读到本地还没有的那一章）⇒ 不记本地进度。"""
    local = _local([f"第{i + 1}章 线上标题{i}" for i in range(3)])
    assert reading_list.align_online(_ONLINE, local, 7) is None


def test_空输入与非法位置():
    local = _local(_ONLINE[:5])
    assert reading_list.align_online([], local, 0) is None
    assert reading_list.align_online(_ONLINE, [], 0) is None
    assert reading_list.align_online(_ONLINE, None, 0) is None
    assert reading_list.align_online(_ONLINE, local, -1) is None
    assert reading_list.align_online(_ONLINE, local, None) is None
    assert reading_list.align_online(_ONLINE, local, "不是数字") is None
    assert reading_list.align_shift([], local) is None
    assert reading_list.align_shift(_ONLINE, []) is None
    assert reading_list.align_map(None, None) == {}
