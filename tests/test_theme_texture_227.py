"""背景纹理（第 227 期）：**清单与 CSS 规则必须一一对应**。

## 为什么用 pytest 而不是 vitest

`texture.css` 是**样式文件**，vitest 侧读它的 `?raw` 导入拿到的是**空串**
（CSS 在 vitest 里被样式管线处理掉，`?raw` 不生效）。而这份契约要盯的是
「CSS 源码里有没有某条规则」—— 那是**文本**问题，用 Python 侧读文件最直接
（与 `test_no_defaults_contract.py` 同一套做法：仓内前端没有 vitest 时就用
纯文本 + 常量断言校验）。

## 坏起来是什么样

少写一条规则 = 那一档「选了没变化」。**界面上看不出来**（用户只能看到
「好像没变」），所以必须在这里钉住。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
THEME_TS = ROOT / "frontend" / "src" / "stores" / "theme.ts"
TEXTURE_CSS = ROOT / "frontend" / "src" / "assets" / "theme" / "texture.css"
MAIN_CSS = ROOT / "frontend" / "src" / "assets" / "main.css"
BOOT_JS = ROOT / "frontend" / "public" / "boot.js"


def _texture_options() -> list:
    """从 `stores/theme.ts` 解析纹理清单（**唯一真值源**）。"""
    src = THEME_TS.read_text(encoding="utf-8")
    m = re.search(r"export const TEXTURE_OPTIONS[^=]*=\s*\[(.*?)\n\]", src, re.S)
    assert m, "TEXTURE_OPTIONS 的形状变了，请同步本测试"
    return re.findall(r"\{\s*value:\s*'([a-z0-9-]+)',\s*label:\s*'([^']+)'\s*\}", m.group(1))


def test_每档纹理都有对应的_CSS_规则():
    """清单里的每一档，`texture.css` 里必须有对应规则。"""
    options = _texture_options()
    assert len(options) >= 10, options
    css = TEXTURE_CSS.read_text(encoding="utf-8")
    for key, label in options:
        if key == "none":
            assert "html.texture-none" in css, "缺 texture-none 的规则"
            continue
        assert f"html.texture-{key} body" in css, (
            f"texture.css 里缺 texture-{key}（{label}）的规则 —— "
            "选了它界面却不会变"
        )


def test_档位键名安全():
    for key, _label in _texture_options():
        assert re.fullmatch(r"[a-z0-9-]+", key), key


def test_CSS_已接进全局样式():
    """`texture.css` 必须被 `main.css` 引入，否则整档纹理都不生效。"""
    main = MAIN_CSS.read_text(encoding="utf-8")
    assert "./theme/texture.css" in main, "texture.css 没被 main.css 引入"


def test_首屏预置脚本也套纹理_class():
    """`public/boot.js` 是**首屏渲染前**跑的内联替代（避免 FOUC）——
    它不套纹理 class 的话，刷新后会有一次「纹理闪一下再消失」。
    """
    boot = BOOT_JS.read_text(encoding="utf-8")
    assert "texture-" in boot, "boot.js 没有套纹理 class"
    assert "readStoredValue('texture'" in boot, "boot.js 没读 texture 键"


def test_强度不能落在_body_的_opacity_上():
    """`opacity` 是**复合**属性：设在 `body` 上会把**正文也一起变淡**，对比度崩。

    正确做法是只作用在纹理自己的颜色（`--texture-ink`）上。
    """
    css = TEXTURE_CSS.read_text(encoding="utf-8")
    bad = re.findall(r"html\[class\*='texture-'\]\s*body\s*\{[^}]*opacity\s*:", css)
    assert not bad, "纹理强度用了 body 的 opacity —— 会把正文一起变淡"
    assert "--texture-opacity" in css, "没有强度闸（--texture-opacity）"
