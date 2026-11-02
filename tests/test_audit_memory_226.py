"""审计日志读取时**不能丢掉还没落盘的条目**（第 226 期）。

## 缺陷形态

活动日志有「合并窗口」：同类型的重复消息先并进内存，窗口走完才落盘。
于是**窗口内**的条目只存在于内存缓冲里，jsonl 尾部**还没有**它们。

而 `activity_log.recent()` 在「内存不足 limit 条」时会用 jsonl 尾部**重建**缓冲，
原先是「`_memory.clear()` → 只填 tail」⇒ **窗口内的条目被整段抹掉**。

表现：审计页在合并窗口内查「刚才那次登录」**查不到** —— 而那正是用户刚做的事。
这类缺陷极难肉眼定位（过一会儿窗口走完、条目落盘了，一切又正常了）。

## 用例

开一个**很长的**合并窗口（条���只进内存、不落盘），写一条日志，然后**立刻**读 ——
读到的结果里必须有它。
"""
from __future__ import annotations

from novelforge.core import activity_log as al


def test_窗口内的条目不会因重建缓冲而消失(isolated, monkeypatch):
    """**磁盘上已有历史** + 窗口内新写一条 ⇒ 读出来必须**两条都在**。

    ⚠️ 触发条件是「磁盘上已有 tail」：重建只在 `_read_tail()` 读到东西时才发生，
    而合并窗口内的条目**只在内存里** ⇒ 重建时它被 `_memory.clear()` 抹掉。
    """
    # 先关掉合并写两条 ⇒ 它们**落盘**了（磁盘 tail 存在）
    monkeypatch.setattr(al, "merge_cfg", lambda: {"enabled": False, "window": 0})
    al.log("历史动作", "历史.txt", al.STATUS_OK, detail="已落盘")
    al.log("历史动作", "历史2.txt", al.STATUS_OK, detail="已落盘")

    # 再开一个**很长的**窗口写一条 ⇒ 这条**只进内存**，磁盘上没有
    monkeypatch.setattr(al, "merge_cfg", lambda: {"enabled": True, "window": 3600})
    al.log("窗口动作", "窗口内.txt", al.STATUS_OK, detail="还在窗口里")

    # 读的时候：内存条数 < limit ⇒ 触发用磁盘 tail 重建缓冲
    items = al.recent(limit=200)
    names = {x.get("file") for x in items}
    assert "窗口内.txt" in names, f"窗口内的条目被重建缓冲抹掉了：{names}"
    assert {"历史.txt", "历史2.txt"} <= names, names


def test_重建缓冲后内存里的旧条目仍在(isolated, monkeypatch):
    """磁盘有历史 + 窗口内连续写多条 ⇒ 一次读出来**都在**，不能只剩磁盘那几条。"""
    monkeypatch.setattr(al, "merge_cfg", lambda: {"enabled": False, "window": 0})
    al.log("多条测试", "历史.txt", al.STATUS_OK, detail="已落盘")

    monkeypatch.setattr(al, "merge_cfg", lambda: {"enabled": True, "window": 3600})
    for i in range(5):
        al.log("多条测试", f"窗口{i}.txt", al.STATUS_OK, detail=f"第 {i} 条")

    items = al.recent(limit=200, action="多条测试")
    names = {x.get("file") for x in items}
    assert names == {"历史.txt"} | {f"窗口{i}.txt" for i in range(5)}, names
