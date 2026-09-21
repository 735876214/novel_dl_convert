"""侧栏导航注册表契约测试（纯文本断言，不碰 DB、不需要夹具）。

与 `test_settings_nav_contract.py` 同一路数：前端没有单测框架，而侧栏这类**配置契约**
一旦走样只会在运行期表现为「重复 key 告警」「徽标永远不出现」或「显示一个写死的假数字」。
放进 pytest 就随现有门禁执行。

钉住四件事：
1. **动态计数项不许写死数字**（`countSource` 声明了来源，就不能再有静态 `count`）——
   写死即假数据，而假数据在界面上与真数据长得一模一样；
2. **id 全局唯一**（重复 id 会让 vue-router 与侧栏 key 同时出问题）；
3. **侧栏入口 / `PATH_BY_ID` / 路由注册三处成对**（少一处就是「点了没反应」或「页面存在但进不去」）；
4. **实体总览与「探索发现」不撞名**（一个是本地书目，一个是外部书源检索，混起来用户会以为在做同一件事）。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV_TS = ROOT / "frontend" / "src" / "data" / "nav.ts"
ROUTER_TS = ROOT / "frontend" / "src" / "router" / "index.ts"
SIDEBAR_VUE = ROOT / "frontend" / "src" / "components" / "AppSidebar.vue"
BROWSE_VUE = ROOT / "frontend" / "src" / "views" / "BrowseView.vue"

#: 实体总览的六个维度（第 34 期）。上游把「题材」与「标签」拆成两个字段，
#: 本项目只有一个 `tags`（dc:subject）⇒ 拆成两个维度就是把同一份数据列两遍，属假交互。
EXPECTED_BROWSE_DIMS = ["author", "series", "genre", "publisher", "language", "collection"]

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


# ---------------------------------------------------------------------------
# 实体总览（第 34 期）
# ---------------------------------------------------------------------------

def test_实体总览的路由入口与路径三处成对():
    """侧栏项、`PATH_BY_ID`、router 注册 —— 少任何一处都是「点了没反应」或「进不去」。"""
    obj = _find("browse")
    assert "label: '实体总览'" in obj, f"侧栏项名字不对：{obj}"
    assert "browse: '/browse'" in SIDEBAR_VUE.read_text(encoding="utf-8"), \
        "AppSidebar 的 PATH_BY_ID 缺 browse → /browse"
    router = ROUTER_TS.read_text(encoding="utf-8")
    assert re.search(r"path:\s*'/browse'[^}]*name:\s*'browse'", router), \
        "router/index.ts 没注册 /browse（或 path 与 name 不成对）"


def test_实体总览不与探索发现撞名():
    """`/explore` 是**外部书源检索**，/browse 是**本地书目浏览** —— 两件事，名字必须分开。"""
    label = re.search(r"id:\s*'browse',\s*label:\s*'([^']+)'", _find("browse"))
    assert label, "侧栏项缺少 label"
    assert label.group(1) not in ("浏览", "探索发现"), \
        f"新页名字与既有入口撞车：{label.group(1)}"
    router = ROUTER_TS.read_text(encoding="utf-8")
    assert "path: '/explore'" in router and "path: '/browse'" in router, \
        "两条路由必须同时存在且各自独立"


def test_浏览页的维度清单是六个且不含重复的题材标签():
    src = BROWSE_VUE.read_text(encoding="utf-8")
    dims = re.findall(r"\{\s*key:\s*'(\w+)',\s*label:", src)
    assert dims == EXPECTED_BROWSE_DIMS, \
        f"实体总览的维度清单变了（本项目只有 tags 一个题材类字段，别再拆一个「标签」）：{dims}"


def test_浏览页不直连外网接口():
    """这一页只读本地书目：真的**调用** `/api/search` 就说明它被当成「探索发现」了。

    ⚠️ 先剥注释再判定：本页顶部就写着「与 `/explore`（`POST /api/search`）不是一回事」，
    把说明文字也算进来会得到一条永远修不掉的假警报（第 32 期「期望写得比事实严」的同类教训）。
    """
    src = re.sub(r"/\*.*?\*/", "", BROWSE_VUE.read_text(encoding="utf-8"), flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    for forbidden in ("/api/search", "api.search(", "/api/download"):
        assert forbidden not in src, f"实体总览不该出现外部书源检索的调用：{forbidden}"
