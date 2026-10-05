"""视觉层契约：组件里**不许自创颜色**（`docs/DESIGN.md` §9 第一条）。

## 为什么有这条用例

`docs/DESIGN.md` 第 4 行写死「组件里禁止硬编码颜色/圆角/阴影 —— 一律用这里的 token 与
Tailwind 语义类」，§9 第一条又点名「❌ 在 `.vue` 里写十六进制/oklch 字面量」。
但这三条纪律**在代码里没有任何守卫**：第 95 期逐文件核查时抓到三处真实违规，
全都活得好好的（`docs/agents-audit-95.md` §5 批次 1）：

1. `frontend/src/views/ReadingActivityView.vue` 的热力图用了 `#2563eb` 那一列 ——
   而 `docs/DESIGN.md` §1 的「历史提醒」明写**那套原型配色已作废**；
2. `frontend/src/components/settings/SettingsSearchPanel.vue` 的遮罩写成 `bg-[#0f172a]/25`，
   而项目早有 `bg-scrim`；
3. `frontend/src/components/charts/library/LibraryIntegrityGaugeChart.vue` 把评分坡写死成
   五个 Tailwind 色（末档那个蓝还是自创的），而 `--score-*` 四个 token 就摆在那里没人用。

## 这条用例**刻意只查两件事**（避免变成噪声源）

- **① 任意值颜色工具类**：`bg-[#…]` / `text-[#…]` / `border-[#…]` 这类写法。
  在展示层它**永远**有语义 token 可换（`bg-scrim`、`bg-card`、`text-muted-foreground`…），
  所以零容忍不冤枉任何人。
- **② 已作废的原型配色**：`#2563eb` / `#6366f1`。`docs/DESIGN.md` §1 已明令作废。

**刻意不管**的东西（都不是「自创配色」，管了只会长出一张谁也不敢动的豁免表）：
ECharts 需要的具体色串（它的 `fillerColor` / `label.color` 不认 `var()`）、
把 CSS 变量解析成色串的中转代码（`lib/charts.cssVarHex()` 的调用方）、
主题定义文件（`assets/theme/*.css` 本来就是 token 的家）、
以及集中声明调色板的 `lib/`、`data/` 模块（它们不在 `.vue` 里，本用例只扫 `.vue`）。

**豁免**：确有必要时在该行加注释 `design-token-ok`，用例会跳过那一行 ——
但请在同一个注释里写清为什么（审查的人只能看到这行字）。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"

#: 单行豁免标记（连同理由写在同一个注释里）
OPT_OUT = "design-token-ok"

#: ① 任意值颜色工具类：`bg-[#0f172a]` / `text-[#2563eb]/25` 之类
_ARBITRARY_COLOR_CLASS = re.compile(
    r"\b(?:bg|text|border|ring|outline|fill|stroke|from|via|to|divide|decoration|caret|accent)"
    r"-\[#[0-9a-fA-F]{3,8}\]"
)

#: ② `docs/DESIGN.md` §1 明令作废的原型配色
_OBSOLETE_COLORS = ("#2563eb", "#6366f1")


def _vue_files() -> list:
    return sorted(SRC.rglob("*.vue"))


def _lines(path: pathlib.Path) -> list:
    return path.read_text(encoding="utf-8").splitlines()


def _scan(pattern: re.Pattern) -> list:
    """返回违规的 ``(相对路径, 行号, 原文)``；带豁免标记的行跳过。"""
    hits: list = []
    for f in _vue_files():
        for i, line in enumerate(_lines(f), 1):
            if OPT_OUT in line:
                continue
            if pattern.search(line):
                hits.append((str(f.relative_to(ROOT)).replace("\\", "/"), i, line.strip()))
    return hits


def test_扫描范围不是空的():
    """自检：路径写错时下面两条会「零命中 ⇒ 全绿」，那是最危险的一种绿。"""
    files = _vue_files()
    assert len(files) > 100, f"只扫到 {len(files)} 个 .vue —— SRC 路径大概写错了：{SRC}"


def test_没有用任意值写死颜色():
    hits = _scan(_ARBITRARY_COLOR_CLASS)
    detail = "\n".join(f"  {p}:{n}  {s}" for p, n, s in hits)
    assert not hits, (
        "组件里不许写任意值颜色工具类（`bg-[#0f172a]/25` 这类）——\n"
        "改用语义 token：浮层遮罩用 `bg-scrim`、卡片 `bg-card`、次要文字 `text-muted-foreground`…\n"
        "（见 `docs/DESIGN.md` §3 语义 token / §9 不要做）\n"
        f"确有必要时在该行加 `{OPT_OUT}` 注释并写明理由。\n{detail}"
    )


def test_没有用已作废的原型配色():
    offenders: list = []
    for f in _vue_files():
        for i, line in enumerate(_lines(f), 1):
            if OPT_OUT in line:
                continue
            for c in _OBSOLETE_COLORS:
                if c in line:
                    offenders.append((str(f.relative_to(ROOT)).replace("\\", "/"), i, c, line.strip()))
    detail = "\n".join(f"  {p}:{n}  {c}  {s}" for p, n, c, s in offenders)
    assert not offenders, (
        "`docs/DESIGN.md` §1 已明令作废这套原型配色（现行主题是 oklch token 体系）：\n"
        f"  {', '.join(_OBSOLETE_COLORS)}\n"
        "看到旧色值一律按过时处理 —— 热力图一类「一色多档」请走 "
        "`@/lib/charts` 的 `chartShades()`（栈内唯一的图表配色入口）。\n"
        f"确有必要时在该行加 `{OPT_OUT}` 注释并写明理由。\n{detail}"
    )


# ---------------------------------------------------------------------------
# 正向钉：第 95 期修掉的那三处，各自必须落在**既有 token / 既有入口**上
# （只钉「不再自己造色」，不钉具体写法 —— 换个 token 只要不再自创就仍然通过）
# ---------------------------------------------------------------------------

def test_评分坡取自固定色板token():
    """`--score-*`（`docs/DESIGN.md` §4 的「事实」色板）是评分坡的唯一来源。

    这条同时挡住「又写回一列十六进制」：下面断言该文件里**不含**裸十六进制色值。
    """
    src = (SRC / "components" / "charts" / "library" / "LibraryIntegrityGaugeChart.vue")
    text = src.read_text(encoding="utf-8")
    assert "--score-red" in text and "--score-green" in text, \
        "评分坡要取 `--score-*` 四个 token，别自己造色"
    assert "cssVarHex" in text, \
        "CSS 变量 → 色串只有 `@/lib/charts` 的 `cssVarHex()` 一处实现，别在组件里再抄一遍"
    bare = [ln.strip() for ln in text.splitlines()
            if re.search(r"#[0-9a-fA-F]{3,8}\b", ln) and OPT_OUT not in ln]
    assert not bare, f"评分坡里还有裸十六进制色值：{bare}"


def test_热力图色阶走图表配色入口():
    """「一色多档」的唯一入口是 `@/lib/charts` 的 `chartShades()`（与另一张热力图同口径）。"""
    src = SRC / "views" / "ReadingActivityView.vue"
    text = src.read_text(encoding="utf-8")
    assert "chartShades(" in text, "热力图色阶要由 `chartShades()` 派生"
    bare = [ln.strip() for ln in text.splitlines()
            if re.search(r"#[0-9a-fA-F]{6}\b", ln) and OPT_OUT not in ln]
    assert not bare, f"热力图里还有裸十六进制色值：{bare}"


def test_搜索浮层遮罩用scrim_token():
    """浮层遮罩只有 `bg-scrim` 一个写法（`--scrim` 的语义用途）。"""
    src = SRC / "components" / "settings" / "SettingsSearchPanel.vue"
    assert "bg-scrim" in src.read_text(encoding="utf-8"), \
        "浮层遮罩要用 `bg-scrim`，不要自己调一个半透明深色"
