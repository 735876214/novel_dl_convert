"""「首次使用引导 + 0 库边界」契约（第 38 期）。

第 37 期把书库改成**不设默认**之后，「0 个书库」成了全新部署的正常初始态。
可当时全前端没有一处告诉用户「先建书库」—— 反而有十几处把他指向「下载 / 上传 /
投递」，而那些动作在没有可接收的库时**全都会被后端 400 拒收**：

    {"detail":"还没有书库：请先到「设置 → 书库管理」新建一个书库并指定它的来源目录"}

第 38 期修的就是这件事。这条修法有两个**极易回潮**的点，所以用纯文本断言钉住
（仓内前端没有 vitest，配置契约就用 pytest 校验，与 `test_no_defaults_contract.py`
同一套做法）：

1. **判据必须走 `hasNoLibraries`**，不许再拿 `libraryEntities.length === 0` 直接判。
   `libraryEntities` 的初值是 `[]`、拉取失败还会被 `catch` 吞掉，`length === 0`
   分不清「真的没有库」和「还没拉到 / 拉失败」—— 拿它当判据会在每次进页面时
   闪一下「还没有书库」，而后端明明是通的。`hasNoLibraries` 额外要求
   `librariesLoaded`（成功取回过）才成立。

2. **空态必须三态分开**：`0 库` ≠ `有库但没书` ≠ `有筛选没命中`。
   第 38 期之前只有后两态，且把「没书」一概说成「到「探索发现」把书下载进来」
   —— 0 库时那是句错话。三态一旦被合并回去，用户又会拿到走不通的指引。

3. **摄入三处入口要有前置拦截**（探索发现下载 / 本地转换 / Book Dock 投递）。
   后端的拒收是对的，但发生在**用户看不见的地方**：下载会先报「已加入下载队列」
   再在后台失败，投递会把文件留在目录里被反复扫描却永不进库。

4. **所有「去建库」出口指向同一处** `/settings/libraries`（第 49 期起书库管理并入设置页）。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

LIBRARY_STORE = SRC / "stores" / "library.ts"
APP_VUE = SRC / "App.vue"
TOUR = SRC / "components" / "settings" / "GuidedTourModal.vue"
SHELF = SRC / "views" / "ShelfView.vue"
EXPLORE = SRC / "views" / "ExploreView.vue"
LOCAL = SRC / "views" / "tools" / "LocalConvertView.vue"
DOCK = SRC / "views" / "settings" / "pages" / "BookDockPage.vue"
SIDEBAR = SRC / "components" / "AppSidebar.vue"
LIBS_VIEW = SRC / "views" / "tools" / "LibrariesView.vue"
DASH = SRC / "views" / "DashboardView.vue"
NOTICE = SRC / "components" / "dashboard" / "FirstRunNotice.vue"

#: 建库的唯一去处（`?new=1` 直达新建弹窗，见 LibrariesView 的 onMounted）
#: 第 49 期起：书库管理从工具页并入设置页，路径 /tools/libraries → /settings/libraries
LIBRARIES_ROUTE = "/settings/libraries"

#: 必须按 0 库改口的文案宿主 —— 它们要么指错路，要么陈述错误事实
NO_LIBRARY_CALL_SITES = (SHELF, EXPLORE, LOCAL, DOCK, SIDEBAR, LIBS_VIEW, NOTICE)


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _code(p: Path) -> str:
    """去掉注释后的源码。

    有些断言要说「**不许出现**某个标识符」，可解释「为什么不许」的注释里必然
    要提到它 —— 不剥注释就会把注释当成违规（第 38 期写这几条时真踩了）。
    """
    src = _read(p)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)   # /* ... */ 与 /** 文档块 */
    src = re.sub(r"^\s*//.*$", "", src, flags=re.M)   # 整行 //
    return re.sub(r"//[^\n]*", "", src)               # 行尾 //


# ---------------------------------------------------------------------------
# ① 判据：只认 `hasNoLibraries`
# ---------------------------------------------------------------------------

def test_store_提供唯一的零库判据():
    """`hasNoLibraries` 必须**同时**要求「成功取回过」和「确实是 0 个」。

    只判 `length === 0` 的实现会在首屏闪出错误的「还没有书库」，所以这里钉的是
    `librariesLoaded` 这个必要条件，而不只是变量名存在。
    """
    src = _read(LIBRARY_STORE)
    m = re.search(r"const hasNoLibraries\s*=\s*computed\((.*?)\)\s*\n", src, re.S)
    assert m, "library.ts 里找不到 hasNoLibraries，请同步本测试"
    body = m.group(1)
    assert "librariesLoaded" in body, "hasNoLibraries 必须要求 librariesLoaded（否则拉取失败/未加载时误报 0 库）"
    assert "libraryEntities" in body and "length === 0" in body
    assert "librariesLoaded," in src and "hasNoLibraries," in src, "两者都要从 store 导出"


def test_拉取失败时不谎报零库():
    src = _read(LIBRARY_STORE)
    m = re.search(r"async function loadLibraries\(.*?\n  \}", src, re.S)
    assert m, "loadLibraries 的形状变了，请同步本测试"
    body = m.group(0)
    assert "librariesLoaded.value = true" in body, "只在**成功**取回后置位"
    # 失败分支不许置位（catch 里只能保持原样）
    catch = body[body.index("catch") :] if "catch" in body else ""
    assert "librariesLoaded.value = true" not in catch, "拉取失败不许把 librariesLoaded 置真"


def test_文案宿主不许直接拿_length_判零库():
    """改口的那些页面必须走 `hasNoLibraries`。

    `libraryEntities` 仍会被别处正当地用（`v-for` 列库、`loadLibraries` 的缓存判断），
    所以这里只钉「**判空**」这个用法：`libraryEntities.length === 0` 这类写法一处都不许有。
    """
    offenders: list[str] = []
    for f in NO_LIBRARY_CALL_SITES:
        src = _read(f)
        for pat in ("libraryEntities.length === 0", "libraryEntities.value.length === 0",
                    "!libraryEntities.length", "!libraryEntities.value.length"):
            if pat in src:
                offenders.append(f"{f.relative_to(ROOT)} 用了 {pat}")
    assert not offenders, "零库判据必须走 hasNoLibraries：" + "；".join(offenders)


# ---------------------------------------------------------------------------
# ② 三态：0 库 / 有库没书 / 有筛选没命中
# ---------------------------------------------------------------------------

def test_书架空态分三态且文案互不相同():
    # 剥注释：解释「0 库时为什么不能指去探索发现」的注释里必然写着「探索发现」
    src = _code(SHELF)
    m = re.search(r"const emptyKind\s*=\s*computed<.*?>\((.*?)\n\}\)\n", src, re.S)
    assert m, "ShelfView 的 emptyKind 形状变了，请同步本测试"
    body = m.group(1)
    assert "hasNoLibraries" in body, "第一态必须是「0 库」"
    assert "no-library" in body and "filtered" in body, "三态都要有"

    titles = re.search(r"const emptyTitle\s*=\s*computed\((.*?)\n\}\)\n", src, re.S)
    descs = re.search(r"const emptyDesc\s*=\s*computed\((.*?)\n\}\)\n", src, re.S)
    assert titles and descs, "emptyTitle / emptyDesc 的形状变了，请同步本测试"
    for name, block in (("标题", titles.group(1)), ("说明", descs.group(1))):
        literals = re.findall(r"return\s+'([^']+)'", block)
        assert len(literals) == len(set(literals)), f"空态{name}的三态文案必须互不相同：{literals}"

    # 0 库那一态要说「还没有书库」，且**不能**再出现把人指去下载的旧句子
    assert "还没有书库" in titles.group(1)
    assert "探索发现" not in descs.group(1).split("case 'filtered'")[0], \
        "0 库时说「去探索发现下载」是错的（会被 400 拒收）"


def test_零库时书架给出建库出口():
    src = _read(SHELF)
    assert "hasNoLibraries" in src and "新建书库" in src
    # 第 55 期：空态出口就地弹窗（不跳设置页）；顶栏「书库管理」跳转保留（管理语义不变）
    assert "createLib" in src, "空态「新建书库」要就地打开向导"
    assert "manageLibs" in src, "顶栏的书库管理入口保留"


# ---------------------------------------------------------------------------
# ③ 引导：复用既有组件，0 库时自动弹一次并把第一步换成建库
# ---------------------------------------------------------------------------

def test_引导第一步跟着真实状态走():
    src = _read(TOUR)
    assert "hasNoLibraries" in src, "引导词必须按真实状态分支（0 库时说「先建一个书库」）"
    assert "先建一个书库" in src
    assert "cta" in src, "该步要带一个可点的出口，而不是只让人记住一句话"
    # 原来的第一步在 0 库时描述一套还不存在的东西
    assert "按格式自动归库" in src, "有库时仍应保留原来的书架说明"


def test_引导在_shell_层按零库自动弹一次():
    src = _read(APP_VUE)
    assert "GuidedTourModal" in src, "引导要挂在 shell 层（原来只在个人资料页手动重放）"
    assert "hasNoLibraries" in src, "自动弹出的条件必须是真实的 0 库"
    assert "nf_tour_seen" in src, "「弹过就算看过」要有持久化标记，否则每次刷新都弹"


# ---------------------------------------------------------------------------
# ④ 摄入三处入口的前置拦截
# ---------------------------------------------------------------------------

def test_探索发现下载前先拦():
    src = _read(EXPLORE)
    m = re.search(r"function startDownload\(.*?\n\}", src, re.S)
    assert m, "startDownload 的形状变了，请同步本测试"
    body = m.group(0)
    assert "hasNoLibraries" in body, "0 库时要提前返回"
    # 拦截必须在发起请求**之前** —— 否则又是「已入队然后后台失败」
    call = re.search(r"\.download\(", body)
    assert call, "startDownload 里找不到下载调用，请同步本测试"
    head = body[: call.start()]
    assert "hasNoLibraries" in head, "拦截要发生在发请求之前"
    assert "return" in head, "拦截分支必须 return，不能继续往下走"


def test_本地转换上传前先拦():
    src = _read(LOCAL)
    for fn in ("convertFiles", "convertByPath"):
        m = re.search(rf"function {fn}\(.*?\n\}}", src, re.S)
        assert m, f"{fn} 的形状变了，请同步本测试"
        assert "hasNoLibraries" in m.group(0), f"{fn} 在 0 库时应提前拦下"


def test_book_dock_投递前先拦():
    src = _read(DOCK)
    m = re.search(r"async function onDrop\(.*?\n\}", src, re.S)
    assert m, "onDrop 的形状变了，请同步本测试"
    body = m.group(0)
    assert "hasNoLibraries" in body and "return" in body
    assert body.index("hasNoLibraries") < body.index("api.convertDrop"), "拦截要发生在投递之前"


# ---------------------------------------------------------------------------
# ⑤ 出口：所有「去建库」指向同一处
# ---------------------------------------------------------------------------

def test_建库出口就地弹窗不跳设置页():
    """第 55 期：0 库时的建库出口是**就地打开的新建书库向导**，不再跳 `/settings/libraries`。

    「管理」语义的入口（书架顶栏 manageLibs / 侧栏「更多」）仍指向设置页 —— 改的只是「新建」。
    """
    for f in (NOTICE, TOUR, DOCK, LOCAL):
        src = _read(f)
        assert "useLibraryWizardStore" in src, (
            f"{f.relative_to(ROOT)} 的建库出口没有就地打开向导"
        )
    for f in (NOTICE, TOUR):
        src = _read(f)
        assert LIBRARIES_ROUTE not in src, (
            f"{f.relative_to(ROOT)} 仍残留指向 {LIBRARIES_ROUTE} 的建库跳转（应改为就地弹窗）"
        )


def test_首屏提示条不在部件注册表里():
    """提示条**不能**注册成可关掉的部件：关掉之后首屏又回到「什么都没有」。"""
    src = _code(NOTICE)
    assert "WIDGET_META" not in src and "widgetById" not in src, "提示条不许接部件注册表"
    registry = _read(SRC / "components" / "dashboard" / "widgets" / "registry.ts")
    assert "FirstRunNotice" not in registry, "首屏引导不属于阅读部件，别登进注册表"


def test_仪表盘挂上了首屏提示条():
    src = _read(DASH)
    assert "FirstRunNotice" in src, "仪表盘要挂上 0 库提示条（0 库时首屏原本通篇不提「书库」）"
