"""文档里写的「界面在哪」必须与前端注册表一致（第 143 期）。

**为什么要有这个文件**：第 143 期（十轮审计第 8 轮）查出 `docs/user-guide.md` 成片的
界面路径漂移 —— 说的是「36 个设置页」（实为 37）、「工具 9 个标签」（实为 8）、
「设置 → 网络 → 书源导入」（没有「网络」这个分组）、「工具 → 书库管理 → 副本与容器」
（第 49 期已迁到设置页）。这些**都不会让任何用例变红**：
`tests/test_settings_nav_contract.py` 只核「注册表 ↔ 路由映射」，
`tests/check_doc_anchors.py` 只核 `file:line` 锚点 —— 裸路径与页名没人管。

本文件把「文档里的界面契约」也钉住，判据全部落在**代码里的真值源**上：

* 设置页页名 / 数量 → `frontend/src/data/settingsNav.ts`
* 工具标签名 / 数量 → `frontend/src/views/tools/ToolsLayout.vue` 的 `SECTIONS`
* `rules.MODES` 这个符号 → `novelforge/sources/rules.py`（文档里点名的真值源必须真存在）
* `logging.retention` 的键 → `config.DEFAULTS`

⚠️ 改界面注册表就必须同批改文档（反之亦然）—— 这正是「加 / 删功能都要彻底」的一部分。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAV_TS = ROOT / "frontend/src/data/settingsNav.ts"
TOOLS_VUE = ROOT / "frontend/src/views/tools/ToolsLayout.vue"
GUIDE = ROOT / "docs/user-guide.md"
README = ROOT / "README.md"
RULES_PY = ROOT / "novelforge/sources/rules.py"


# ---------------- 真值源解析（前端 TS / Vue，无 Node 依赖）----------------

def _nav_pages() -> "list[tuple[str, str, str]]":
    """`settingsNav.ts` 里的 `p('path', 'Label', 'zh'` 三元组（path / label / zh）。"""
    text = NAV_TS.read_text(encoding="utf-8")
    return re.findall(r"p\('([^']+)',\s*'([^']*)',\s*'([^']*)'", text)


def _nav_zh() -> "set[str]":
    return {zh for _, _, zh in _nav_pages()}


def _tools_labels() -> "list[str]":
    """`ToolsLayout.vue` 的 `SECTIONS` 标签（顺序即界面顺序）。"""
    text = TOOLS_VUE.read_text(encoding="utf-8")
    # ⚠️ 别用 `.split("]", 1)` 截数组：`SECTIONS` 里带注释，注释里的
    # `features.labels()["convert"]` 也有 `]`，会提前截断（本次就是这么红了一次）。
    m = re.search(r"const SECTIONS: ToolSection\[\] = \[(.*?)\n\]", text, re.S)
    assert m, "ToolsLayout 的 SECTIONS 声明格式变了，本用例跟着改"
    return re.findall(r"label:\s*'([^']+)'", m.group(1))


def _guide_settings_rows() -> "list[tuple[str, list[str]]]":
    """user-guide §9 的设置页表：`| **你**（12） | 个人资料 · 主题 · … |`。"""
    text = GUIDE.read_text(encoding="utf-8")
    rows = []
    for m in re.finditer(r"^\| \*\*([^|*]+)\*\*（(\d+)） \| ([^|]+) \|$", text, re.M):
        names = [n.strip() for n in m.group(3).split("·") if n.strip()]
        rows.append((m.group(1).strip(), names))
    return rows


# ---------------- 设置页：页名与数量 ----------------

def test_设置页页名全部来自注册表():
    """文档里写的每一个设置页名都必须是 `settingsNav.ts` 里真实存在的 `zh`。"""
    known = _nav_zh()
    assert known, "解析不到 settingsNav 的页名，解析器该跟着注册表格式一起改"
    unknown = [(g, n) for g, names in _guide_settings_rows() for n in names if n not in known]
    assert not unknown, f"user-guide 里的设置页名在 settingsNav 里不存在：{unknown}"


def test_设置页数量与标题里的数字一致():
    """表里各页数之和 == 注册表页数 == 标题括号里的数字（三处同一个事实）。"""
    rows = _guide_settings_rows()
    assert rows, "user-guide §9 的设置页表解析不到"
    assert sum(len(names) for _, names in rows) == len(_nav_pages()) == 37
    text = GUIDE.read_text(encoding="utf-8")
    m = re.search(r"## 9\. 设置（(\d+) 页 / (\d+) 组", text)
    assert m, "user-guide §9 标题格式变了，本用例跟着改"
    assert int(m.group(1)) == len(_nav_pages())
    assert int(m.group(2)) == len(rows)


def test_设置页路由不带分组段():
    """路由是 `#/settings/<path>` —— 分组只决定侧栏归类，不进 URL。"""
    text = GUIDE.read_text(encoding="utf-8")
    assert "路由**不带分组段**" in text
    assert "#/settings/<组>/<页>" not in text


# ---------------- 工具标签：名与数量 ----------------

def test_工具标签数量与名字都来自_ToolsLayout():
    labels = _tools_labels()
    assert labels, "解析不到 ToolsLayout 的 SECTIONS"
    text = GUIDE.read_text(encoding="utf-8")
    m = re.search(r"## 8\. 工具（单页 \+ 顶部标签栏，(\d+) 个）", text)
    assert m, "user-guide §8 标题格式变了，本用例跟着改"
    assert int(m.group(1)) == len(labels)
    listed = re.search(r"## 8\. 工具[^\n]*\n\n([^\n]+)", text)
    assert listed
    # 文档会在标签后面补一句说明（`重复书籍（同作者 + …）`）—— 只比标签本体
    names = [re.split(r"[（(]", n.strip())[0].strip()
             for n in listed.group(1).rstrip("。").split("/")]
    assert names == labels, f"user-guide 的工具标签 {names} != 界面实际 {labels}"


# ---------------- 文档点名的真值源必须真存在 ----------------

def test_文档点名的_rules_MODES_符号存在():
    """四个文档都写「引擎能执行什么」只有 `rules.MODES` 一处说了算 —— 那个符号必须真存在。

    第 143 期审计：文档写的是 `rules._MODES`（**不存在**），全仓唯一 `_MODES` 是
    `selspec.py` 里另一样东西（阅读选择器语法名）。文档自证真值源却指错了名字。
    """
    assert re.search(r"^MODES\s*=", RULES_PY.read_text(encoding="utf-8"), re.M)
    for doc in ("docs/architecture.md", "docs/roadmap-gaps-remaining.md", "AGENTS.md"):
        text = (ROOT / doc).read_text(encoding="utf-8")
        assert "rules._MODES" not in text.split("## 第 143 期")[0], f"{doc} 仍写着不存在的 rules._MODES"
    assert "rules.MODES" in (ROOT / "docs/architecture.md").read_text(encoding="utf-8")


def test_README_写明日志留存策略的每个键():
    """`config.DEFAULTS["logging"]["retention"]` 的键必须都能在 README 配置表里找到。

    第 143 期审计：这张表漏了 `retention` 整段 —— 一个「默认关闭、打开就轮转」的开关
    在文档里根本不存在，用户不知道该去改什么。
    """
    import novelforge.config as config

    retention = config.DEFAULTS["logging"]["retention"]
    text = README.read_text(encoding="utf-8")
    block = text[text.index("logging:"): text.index("update:")]
    missing = [k for k in retention if f"{k}:" not in block]
    assert not missing, f"README 的 logging 段缺这些键：{missing}"
