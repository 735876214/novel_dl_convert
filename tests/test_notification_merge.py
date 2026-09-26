"""第 61 期：同类型通知的**合并**契约（10s 窗口、每次新消息重置窗口、角标不虚高）。

需求原文：「同类型通知若 10s 内重复多次，合并结果统一推送。后台每出现一次同类型消息，
10s 都会重置。」

三条必须钉住的：
1. **窗口内重复 → 只产生一条**通知（`merged` = 次数），而不是 N 条；
2. **窗口是尾随的**：每来一条同类型消息，窗口从头计时（连续不断 ⇒ 一直不落盘）；
3. **不同类型互不干扰**（动作 / 结果 / 主体任一不同就是另一条）。

⚠️ 合并只能**延迟落盘**（尾随去抖的必然结果）：窗口内不写文件，安静下来才写一次。
所以「内存里看得见」与「盘上已写入」是两件事，用例分开断言，并额外钉住 `flush_pending`
的兜底（进程退出前补写，见 activity_log._flush_at_exit）。

全部离线：日志目录指向 tmp_path，不碰真实配置与日志。
"""
import time

from novelforge.core import activity_log as al


def _reset(monkeypatch, tmp_path, window=10.0, enabled=True):
    """把日志落到 tmp 并清空一切缓冲（内存 + 合并缓冲）。"""
    al.set_dir(tmp_path)
    monkeypatch.setattr(al, "merge_cfg", lambda: {"enabled": enabled, "window": window})
    al._memory.clear()
    al._pending.clear()


def test_窗口内同类型重复只留一条(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path, window=10.0)

    entries = [al.log("元数据", "书甲.epub", "失败", detail=f"第 {i + 1} 次失败")
               for i in range(5)]

    # 全部并入同一条：同一个对象、计数为 5
    assert len({id(e) for e in entries}) == 1
    assert entries[-1]["merged"] == 5
    assert entries[-1]["detail"] == "第 5 次失败"        # 说明取最新的一条
    # 内存缓冲里也只有一条（角标因此不会虚高）
    assert len(al._memory) == 1
    assert len(al._pending) == 1


def test_窗口每次新消息都重置(monkeypatch, tmp_path):
    """尾随去抖：连续不断地来 ⇒ 一直不落盘；停够窗口才写一次。"""
    _reset(monkeypatch, tmp_path, window=0.4)

    al.log("转换", "书乙.txt", "成功")
    # 每 0.2s 来一条（小于 0.4s 窗口）：窗口被不断重置，始终不该落盘
    for i in range(4):
        time.sleep(0.2)
        al.log("转换", "书乙.txt", "成功", detail=f"重复 {i}")

    assert len(al._pending) == 1                 # 仍在缓冲里
    assert al._pending[al._merge_key({"action": "转换", "status": "成功", "file": "书乙.txt"})]["count"] == 5

    time.sleep(0.45)
    flushed = al.flush_pending()
    assert len(flushed) == 1
    assert flushed[0]["merged"] == 5
    assert not al._pending                        # 已结算


def test_不同类型互不合并(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path, window=10.0)

    al.log("元数据", "书甲.epub", "失败")
    al.log("元数据", "书甲.epub", "成功")          # 结果不同
    al.log("元数据", "书丙.epub", "失败")          # 主体不同
    al.log("转换", "书甲.epub", "失败")            # 动作不同

    assert len(al._pending) == 4
    assert len(al._memory) == 4


def test_关掉合并即回到逐条写盘(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path, window=10.0, enabled=False)

    for i in range(3):
        al.log("添加", f"书{i}.epub", "成功")

    assert not al._pending                        # 不进缓冲
    assert len(al._memory) == 3
    jsonl = tmp_path / al.JSONL_FILENAME
    assert jsonl.is_file() and len(jsonl.read_text(encoding="utf-8").strip().splitlines()) == 3


def test_force_flush把待合并的补写(monkeypatch, tmp_path):
    """退出路径（`_flush_at_exit`）用的就是这条：强制把还没到窗口的也写下去，不丢。"""
    _reset(monkeypatch, tmp_path, window=600)     # 很长的窗口：正常不会自己结算

    al.log("同步", "书丁.epub", "失败", detail="推给第三方失败")
    al.log("同步", "书丁.epub", "失败", detail="推给第三方失败（第二次）")

    assert len(al._pending) == 1
    out = al.flush_pending(force=True)
    assert len(out) == 1 and out[0]["merged"] == 2
    assert not al._pending


def test_合并后详情取最新且次数可见(monkeypatch, tmp_path):
    _reset(monkeypatch, tmp_path, window=10.0)

    e = al.log("刮削", "书戊.epub", "失败", detail="第一次原因")
    assert "merged" not in e                      # 首条还没有计数（就是一次）
    e = al.log("刮削", "书戊.epub", "失败", detail="第二次原因")
    assert e["merged"] == 2
    assert e["detail"] == "第二次原因"
