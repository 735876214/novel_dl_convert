"""设置页注册表契约测试（纯文本断言，不碰 DB、不需要夹具）。

为什么用 pytest 校验前端数据而不是写前端单测：仓内前端没有 vitest/jest，也不打算为此
新增依赖；而 `settingsNav.ts` 与 `router/index.ts` 之间的约定属于**配置契约**，一旦走样
只会在运行期表现为 `console.error`（标 ready 却没注册组件）或侧栏静默漏页。放进 pytest
即随现有门禁执行。

钉住的四件事：
1. 上游 41 页「要么有落点，要么在 `REMOVED_UPSTREAM` 里显式声明已移除」—— 放行已裁决
   移除的页（对照记录在 `docs/bookorbit-settings-inventory.md`），但不放过静默漏页；
2. `path` / `name` 全局唯一（重复会被 vue-router 静默覆盖，侧栏还会出现重复 key）；
3. `status === 'ready'` 的页必须已注册组件，且组件表里没有多余条目；
4. 占位页（第 49 期后应为**空集**）必须同时带 `upstream` 与 `note`。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAV_TS = ROOT / "frontend" / "src" / "data" / "settingsNav.ts"
ROUTER_TS = ROOT / "frontend" / "src" / "router" / "index.ts"

# 上游 BookOrbit 设置页共 41 页（页面 <h2>），出处：docs/bookorbit-settings-inventory.md §1.3。
# 已实现的页由自己的 upstream.title 承载，未实现的页由只读占位页承载。
UPSTREAM_TITLES = [
    "Profile", "Theme", "Book Covers", "Icons", "Layout", "Behavior", "Language",
    "eBook", "PDF", "Comics", "Audiobook", "Fonts", "General", "Notifications",
    "Privacy & Sharing", "Restrictions", "Libraries", "Providers", "Field-Level Rules",
    "Custom Fields", "Confidence Score", "Books", "Author Auto-Fetch", "Genre Blocklist",
    "File Naming", "Maintenance", "Kobo", "KOReader", "OPDS", "Email", "Hardcover",
    "Readwise", "StoryGraph", "Users", "Account Activity", "Magic Links", "OIDC / SSO",
    "Requests", "Book Dock", "Server Fonts", "Audit Log",
]

# 上游有、本项目不做 → 只读占位页。双向断言：既不能少（漏页），也不能多（新增占位页属于
# 「又决定不做一页」，应当显式改这里，避免悄悄退化）。
# 第 49 期：libraries 转为真实操作页（设置页承载书库管理），其余 12 个占位页经裁决**删除**
# ⇒ 占位页集合清零（机制保留，供将来复用）。
EXPECTED_PLACEHOLDERS: set[str] = set()

# 第 49 期裁决移除的 11 个上游页（按上游标题声明）：删条目即删路由，逐页理由与上游结构
# 对照保留在 docs/bookorbit-settings-inventory.md。**显式列出**是为保住「上游页不静默漏掉」
# 的性质：上游若新增一页，必须二选一 —— 给它落点，或加进这里并说明为何不做。
REMOVED_UPSTREAM = {
    "Icons",
    "Language",
    "Privacy & Sharing",
    "Restrictions",
    "Kobo",
    "Email",
    "Users",
    "Account Activity",
    "Magic Links",
    "OIDC / SSO",
    "Requests",
}

#: 第 49 期移除页的**设置页 path**（与 REMOVED_UPSTREAM 对应；含本项目补充的 koreader-upstream）。
#: 断言它们既不在注册表、也不在组件表 —— 防止「删了条目却漏删组件」的半删状态。
REMOVED_PAGE_PATHS = {
    "appearance/icons",
    "appearance/language",
    "account/privacy",
    "account/restrictions",
    "kobo",
    "koreader-upstream",
    "email",
    "admin/users",
    "admin/account-activity",
    "admin/magic-links",
    "admin/oidc",
    "admin/requests",
}

# 本项目补充项：上游没有这一页，界面上要标「本项目补充」
# 第 49 期：koreader-upstream 随「上游对照占位页清理」一并删除，只剩 komga。
EXPECTED_OWN = {"komga"}

PAGE_RE = re.compile(r"^\s*p\('([^']+)', '([^']+)', '([^']+)', '(ready|placeholder)', \{", re.M)
COMPONENT_RE = re.compile(r"^\s{2}'?([\w\-/]+)'?:", re.M)


def _read(path: Path) -> str:
    assert path.exists(), f"缺少源文件：{path}"
    return path.read_text(encoding="utf-8")


def _pages() -> list[tuple[str, str, str, str]]:
    """(path, label, zh, status) 列表，按文件中出现顺序。"""
    return PAGE_RE.findall(_read(NAV_TS))


def _blocks() -> dict[str, str]:
    """path → 该页 `p(...)` 调用的文本块（用于检查块内是否带 upstream / note）。

    以 `\\n      }),\\n`（6 空格缩进的收尾）为界，而**不能**切到下一个 `p(`：
    页与页之间还夹着分组对象，那样会把下一组的 `own: true` 也算进上一页。
    """
    text = _read(NAV_TS)
    out: dict[str, str] = {}
    for m in PAGE_RE.finditer(text):
        end = text.find("\n      }),\n", m.start())
        out[m.group(1)] = text[m.start(): end if end != -1 else len(text)]
    return out


def _registered_components() -> set[str]:
    text = _read(ROUTER_TS)
    start = text.index("export const SETTINGS_PAGE_COMPONENTS")
    block = text[start:text.index("\n}", start)]
    return {m.group(1) for m in COMPONENT_RE.finditer(block)}


def test_page_count_and_uniqueness() -> None:
    pages = _pages()
    assert len(pages) == 36, (
        f"设置页数量应为 36（第 49 期删 12 页后：上游 30 有落点 + 本项目补充 6），实际 {len(pages)}"
    )
    paths = [p[0] for p in pages]
    assert len(set(paths)) == len(paths), f"路由 path 重复：{_dups(paths)}"
    # name 由 path 派生（settings- + path 里的 / 换成 -），path 唯一即 name 唯一
    names = ["settings-" + p.replace("/", "-") for p in paths]
    assert len(set(names)) == len(names), f"路由 name 重复：{_dups(names)}"


def test_status_values_are_legal() -> None:
    bad = [p for p in _pages() if p[3] not in {"ready", "placeholder"}]
    assert not bad, f"status 取值非法：{bad}"


def test_说明文案是纯文本不带标记符号() -> None:
    """`note` 由 `SettingsPlaceholder.vue` 用 `{{ page.note }}` **插值**渲染。

    也就是说 markdown 与 HTML 都不会被解析：写 `**重点**` 会把星号原样显示给用户。
    想做强调得改渲染方式（v-html + 受控标签），那是另一件事 —— 在那之前这里必须保持纯文本。
    """
    notes = re.findall(r"note:\s*'([^']*)'", _read(NAV_TS))
    assert notes, "一个 note 都没解析到，正则大概过期了"
    bad = [n for n in notes if "**" in n or "`" in n or "<strong>" in n]
    assert not bad, f"这些说明文案带了会被原样显示的标记符号：{bad[:2]}"


def test_every_upstream_page_is_landed_or_explicitly_removed() -> None:
    """上游 41 页：要么有落点，要么在 `REMOVED_UPSTREAM` 里显式声明已移除。

    第 49 期把「逐页有落点」放宽为「有落点或显式已移除」—— 删除是**裁决**，不是遗忘；
    上游新增一页时这条测试会逼出一个明确决定。两侧都查：既不许漏，也不许自相矛盾。
    """
    text = _read(NAV_TS)
    landed = {t for t in UPSTREAM_TITLES if f"title: '{t}'" in text}
    missing = [t for t in UPSTREAM_TITLES if t not in landed and t not in REMOVED_UPSTREAM]
    assert not missing, f"上游设置页既无落点也未声明移除：{missing}"
    both = landed & REMOVED_UPSTREAM
    assert not both, f"这些页既声明已移除、又仍是落点：{sorted(both)}"


def test_placeholder_pages_have_upstream_and_note() -> None:
    blocks = _blocks()
    placeholders = [p[0] for p in _pages() if p[3] == "placeholder"]
    assert set(placeholders) == EXPECTED_PLACEHOLDERS, (
        "占位页清单与预期不一致："
        f"多出 {sorted(set(placeholders) - EXPECTED_PLACEHOLDERS)}；"
        f"缺少 {sorted(EXPECTED_PLACEHOLDERS - set(placeholders))}"
    )
    for path in placeholders:
        block = blocks[path]
        assert "upstream: {" in block, f"占位页 {path} 未给出上游页面结构（upstream）"
        assert "note: '" in block, f"占位页 {path} 未写明本项目为何不提供（note）"


def test_ready_pages_match_registered_components() -> None:
    ready = {p[0] for p in _pages() if p[3] == "ready"}
    registered = _registered_components()
    assert ready == registered, (
        "「标记 ready」与「已注册组件」必须一一对应，否则运行期会 console.error："
        f"ready 未注册 {sorted(ready - registered)}；已注册但非 ready {sorted(registered - ready)}"
    )


def test_removed_pages_are_gone() -> None:
    """第 49 期移除的 12 页：既不在注册表，也不注册组件（防「删条目漏删组件」的半删状态）。"""
    pages = {p[0] for p in _pages()}
    registered = _registered_components()
    still_pages = sorted(REMOVED_PAGE_PATHS & pages)
    still_registered = sorted(REMOVED_PAGE_PATHS & registered)
    assert not still_pages, f"已移除页仍在注册表：{still_pages}"
    assert not still_registered, f"已移除页仍注册了组件：{still_registered}"


def test_settings_home_points_to_existing_page() -> None:
    text = _read(NAV_TS)
    home = re.search(r"export const SETTINGS_HOME = '([^']+)'", text)
    assert home, "未找到 SETTINGS_HOME"
    path = home.group(1).removeprefix("/settings/")
    assert path in {p[0] for p in _pages()}, f"SETTINGS_HOME 指向不存在的页：{home.group(1)}"


def test_system_alias_redirects_to_file_naming() -> None:
    """上游实测存在别名路由 /settings/system → 文件命名（inventory §7.1 #4）。"""
    router = _read(ROUTER_TS)
    assert "path: 'system'" in router, "缺少 /settings/system 别名子路由"
    assert "name: 'settings-library-file-naming'" in router, "别名未指向文件命名页"
    assert "library/file-naming" in {p[0] for p in _pages()}, "别名目标页不存在"


def test_own_pages_are_marked() -> None:
    blocks = _blocks()
    marked = {path for path, block in blocks.items() if "own: true" in block}
    assert marked == EXPECTED_OWN, (
        "「本项目补充」标记应恰好覆盖上游没有的页："
        f"多标 {sorted(marked - EXPECTED_OWN)}；漏标 {sorted(EXPECTED_OWN - marked)}"
    )


def _dups(items: list[str]) -> list[str]:
    seen: set[str] = set()
    return sorted({i for i in items if i in seen or seen.add(i)})
