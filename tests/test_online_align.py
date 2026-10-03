"""第 93 期 · 在线阅读的章节对齐（`reading_list.align_online`）。

用户拍板的判据（2026-10-03 原话）：「根据章节序号和章节名称进行匹配，若本章节及上下章节
共 5 章能有 3 章对应上就认定为同一章节，以线上章节名称进行确定进度等数据」。

⚠️ 这是**唯一实现**（服务端算，客户端只用结果）。所以这里逐条钉住四种情形：
正常命中、够不上门槛、边界收窄、以及「整本漂移时宁可返回 None 也不硬配」。
"""
from novelforge.core import reading_list


def _local(titles: list) -> list:
    """本地章节（`library._reading_list` 的形状：只取对齐要用的两个键）。"""
    return [{"index": i, "title": t} for i, t in enumerate(titles)]


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


def test_整本漂移时返回None而不硬配():
    """线上多了一章卷首 ⇒ 同序号全错：命中数够不上门槛就如实说「对不上」。"""
    online = ["序章"] + [f"第{i}章 正文{i}" for i in range(1, 11)]
    local = _local([f"第{i}章 正文{i}" for i in range(1, 11)])
    assert reading_list.align_online(online, local, 5) is None


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
