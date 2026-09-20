"""审计日志按操作者筛选（第 32 期）：精确匹配、候选清单、接口透传与向后兼容。

审计视图此前只能按 动作 / 结果 / 关键字 筛，操作者只显示不能筛（前端还如实标了
「日志接口尚未支持按 actor 过滤」）。本期补上：`recent()` 加 actor 过滤（**精确匹配**，
与 q 的子串语义刻意不同 —— 操作者是账号名，不是搜索词）、新增 `actors()` 给出候选清单、
`/api/logs` 透传并把候选一并下发。

⚠️ 日志的 jsonl 与内存缓冲都是**会话级**的（`conftest.py` 的 LOG_DIR 全用例共用同一个
临时目录，且不随用例重置）。所以：
  · 不调 `clear()` —— 那会抹掉同会话其它用例写入的条目；
  · 每个用例用 `tag`（用例独有后缀）命名 actor 与文件，「造 N 条断言 N 条」才成立，
    否则第二个用例起就会把上一个用例造的条目一起数进来。

离线约定：本文件不发起任何外呼。
"""
import itertools

import pytest

from novelforge.core import activity_log

_SEQ = itertools.count(1)


@pytest.fixture
def tag() -> str:
    """本用例独有的短标记，用作 actor 名与文件名的后缀（见文件头注的累积说明）。"""
    return f"t{next(_SEQ)}"


def _files(actor: str, tag: str) -> list[str]:
    """本用例造的那些条目（actor 已足够区分，前缀匹配是双保险）。"""
    return [str(e.get("file", "")) for e in activity_log.recent(limit=500, actor=actor)
            if str(e.get("file", "")).startswith(f"{tag}-")]


# ---------------- 过滤 ----------------

def test_按操作者过滤_只回该操作者的条目(tag):
    a, g = f"zz-a-{tag}", f"zz-g-{tag}"
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=a)
    activity_log.log("转换", f"{tag}-b.epub", "失败", detail="坏文件", actor=g)
    activity_log.log("清理", f"{tag}-c.epub", "成功", actor=a)
    assert _files(a, tag) == [f"{tag}-c.epub", f"{tag}-a.epub"]   # 新→旧


def test_操作者是精确匹配而非子串(tag):
    """造一个前缀相同的「另一个操作者」，它不该被前一个筛出来。

    这一条与 q 的子串语义刻意相反 —— 若哪天有人把 actor 改成子串匹配，这里会红。
    """
    a = f"zz-a-{tag}"
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=a)
    activity_log.log("转换", f"{tag}-b.epub", "成功", actor=a + "2")
    assert _files(a, tag) == [f"{tag}-a.epub"]


def test_空操作者等于不过滤(tag):
    """与既有 action / status / q 的空值语义一致：空 = 不筛。"""
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=f"zz-a-{tag}")
    assert (activity_log.recent(limit=500, actor="")
            == activity_log.recent(limit=500))


def test_操作者可与其它的过滤叠加(tag):
    a = f"zz-a-{tag}"
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=a)
    activity_log.log("清理", f"{tag}-c.epub", "成功", actor=a)
    assert _files(a, tag) == [f"{tag}-c.epub", f"{tag}-a.epub"]
    assert [e["file"] for e in activity_log.recent(limit=500, actor=a, action="清理")
            if str(e.get("file", "")).startswith(f"{tag}-")] == [f"{tag}-c.epub"]
    assert [e["file"] for e in activity_log.recent(limit=500, actor=a, status="失败")
            if str(e.get("file", "")).startswith(f"{tag}-")] == []


def test_无操作者的条目筛不出来(tag):
    """没有 actor 的条目不是「某人的」，故任何名字都筛不到它。

    这是本期的取舍：空 actor 是「没有记录」，不是一个可选项（前端另有单独计数提示）。
    """
    activity_log.log("添加", f"{tag}-d.epub", "成功")            # 不传 actor
    for who in (f"zz-a-{tag}", f"zz-g-{tag}"):
        assert f"{tag}-d.epub" not in _files(who, tag)


# ---------------- 候选清单 ----------------

def test_候选清单_含出现过的名字(tag):
    a, g = f"zz-a-{tag}", f"zz-g-{tag}"
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=a)
    activity_log.log("转换", f"{tag}-b.epub", "成功", actor=g)
    acts = activity_log.actors()
    assert a in acts
    assert g in acts


def test_候选清单_去重且有序(tag):
    a = f"zz-a-{tag}"
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=a)
    activity_log.log("转换", f"{tag}-b.epub", "成功", actor=a)   # 同一个操作者再写一条
    acts = activity_log.actors()
    assert acts.count(a) == 1
    assert acts == sorted(acts)


def test_候选清单_不含空操作者(tag):
    activity_log.log("添加", f"{tag}-d.epub", "成功")            # 不传 actor
    assert "" not in activity_log.actors()


def test_候选清单_不受筛选影响(tag):
    """筛一个人时清单里仍要有别人 —— 否则选中一个之后下拉会塌缩成一项，再也切不回去。"""
    a, g = f"zz-a-{tag}", f"zz-g-{tag}"
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=a)
    activity_log.log("转换", f"{tag}-b.epub", "成功", actor=g)
    before = activity_log.actors()
    activity_log.recent(limit=50, actor=a)
    assert activity_log.actors() == before


# ---------------- 接口 ----------------

def test_接口_按操作者筛选(client, auth_headers, tag):
    a, g = f"zz-a-{tag}", f"zz-g-{tag}"
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=a)
    activity_log.log("转换", f"{tag}-b.epub", "失败", detail="坏文件", actor=g)
    activity_log.log("清理", f"{tag}-c.epub", "成功", actor=a)

    r = client.get("/api/logs", params={"actor": a, "limit": 500}, headers=auth_headers)
    assert r.status_code == 200
    j = r.json()
    assert [i["file"] for i in j["items"]] == [f"{tag}-c.epub", f"{tag}-a.epub"]
    assert a in j["actors"]
    assert g in j["actors"]


def test_接口_不传操作者时照旧不过滤(client, auth_headers, tag):
    """防回归：新参数必须是**可选**的 —— 不传时输出与改动前一致（多点一个 actors 而已）。"""
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=f"zz-a-{tag}")
    activity_log.log("添加", f"{tag}-d.epub", "成功")            # 无 actor 的那条也不该被踢掉
    j = client.get("/api/logs", params={"limit": 500}, headers=auth_headers).json()
    for k in ("items", "count", "dir", "actors"):
        assert k in j, f"响应缺 {k}"
    files = {str(i.get("file", "")) for i in j["items"]}
    assert {f"{tag}-a.epub", f"{tag}-d.epub"} <= files


def test_接口_候选清单不随筛选参数变化(client, auth_headers, tag):
    a, g = f"zz-a-{tag}", f"zz-g-{tag}"
    activity_log.log("转换", f"{tag}-a.epub", "成功", actor=a)
    activity_log.log("转换", f"{tag}-b.epub", "成功", actor=g)
    kwargs = {"headers": auth_headers}
    x = client.get("/api/logs", params={"actor": a}, **kwargs).json()["actors"]
    y = client.get("/api/logs", params={"actor": g}, **kwargs).json()["actors"]
    z = client.get("/api/logs", **kwargs).json()["actors"]
    assert x == y == z


def test_接口_未认证401(client, tag):  # noqa: ARG001
    assert client.get("/api/logs", params={"actor": f"zz-a-{tag}"}).status_code == 401
