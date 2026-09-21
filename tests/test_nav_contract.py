"""侧栏导航注册表契约测试（纯文本断言，不碰 DB、不需要夹具）。

与 `test_settings_nav_contract.py` 同一路数：前端没有单测框架，而侧栏这类**配置契约**
一旦走样只会在运行期表现为「重复 key 告警」「徽标永远不出现」或「显示一个写死的假数字」。
放进 pytest 就随现有门禁执行。

钉住两件事：
1. **动态计数项不许写死数字**（`countSource` 声明了来源，就不能再有静态 `count`）——
   写死即假数据，而假数据在界面上与真数据长得一模一样；
2. **id 全局唯一**（重复 id 会让 vue-router 与侧栏 key 同时出问题）。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV_TS = ROOT / "frontend" / "src" / "data" / "nav.ts"

#: 「浏览」组三项必须走 `/api/browse-counts`（第 34 期）—— 与各自目标页同源的那份数字。
BROWSE_ITEMS = ("authors", "series", "annotations")

#: 这三项的计数键 = 菜单 id，后端响应字段名逐字一致；改名会让胶囊静默消失。
BROWSE_COUNT_KEYS = {"authors", "series", "annotations"}


def _text() -> str:
    return NAV_TS.read_text(encoding="utf-8")


def _item_objects() -> list[str]:
    """把 `items: [...]` 里的**单个对象字面量**切出来（按 `{ ... }` 配对切，不跨对象）。"""
    out: list[str] = []
    for m in re.finditer(r"\{\s*id:\s*'[^']+'[^{}]*\}", _text()):
        out.append(m.group(0))
    return out


def _find(item_id: str) -> str:
    for obj in _item_objects():
        if re.search(r"id:\s*'%s'" % re.escape(item_id), obj):
            return obj
    raise AssertionError(f"nav.ts 里找不到菜单项 {item_id}")


def test_浏览组三项都声明动态计数来源():
    for item_id in BROWSE_ITEMS:
        obj = _find(item_id)
        assert "countSource: 'browse'" in obj, f"{item_id} 没声明 countSource: 'browse'：{obj}"


def test_动态计数项不许写死数字():
    """`count` 是静态值 —— 与 countSource 同时出现时，界面到底显示哪个会变成看渲染顺序。"""
    for obj in _item_objects():
        if "countSource:" in obj:
            assert not re.search(r"\bcount:\s*\d", obj), f"动态计数项不该另有静态 count：{obj}"


def test_任务中心仍用运行中计数():
    assert "countSource: 'running'" in _find("tasks")


def test_菜单id全局唯一():
    ids = re.findall(r"id:\s*'([^']+)'", _text())
    dupes = {i for i in ids if ids.count(i) > 1}
    assert not dupes, f"菜单 id 重复（会让侧栏出现重复 key）：{sorted(dupes)}"


def test_浏览计数键与后端响应字段同名():
    """前端按 id 到响应里取字段 —— 这里把两侧的名字对齐关系写成契约。"""
    assert BROWSE_COUNT_KEYS == set(BROWSE_ITEMS)
    assert all(re.search(r"id:\s*'%s'" % i, _text()) for i in BROWSE_COUNT_KEYS)


def test_库组的更多行同时给出计数来源与去向():
    """「查看全部书库（N）」原来只说 label：括号里是书库数、点下去却是书架。

    契约改为「label + countSource + to」三件一起声明 —— 少一件就会重新出现
    「读数口径与点击去向不一致」这个含糊。
    """
    m = re.search(r"more:\s*\{([^}]*)\}", _text())
    assert m, "nav.ts 里没有 more 行"
    body = m.group(1)
    assert "label:" in body and "to:" in body and "countSource:" in body, \
        f"more 行缺声明（label / to / countSource 要一起给）：{body}"
