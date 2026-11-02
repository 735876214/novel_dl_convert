"""自定义图标的**安全判据**（第 249 期补测）。

## 为什么补这个

`core/customicons.py` 是**安全相关**的模块（第 216 期）：自定义图标最终会以
`v-html` 画进按钮（与内置图标同一条渲染路径）⇒ 服务端**只提取** `<path d="…">`
的 `d` 字符串，前端再拼成 `<path d=…/>` ⇒ 完整 SVG 里的 `<script>` / `on*` /
外链 `<image>` 不会跟着进来。

而这个模块此前**零测试**（`tests/` 里连名字都不出现）⇒ 那套判据**没有网**：
改动它（哪怕只是「顺手支持一下 circle」）不会有任何用例拦住回归。

## 这里钉六件事

1. 只取 `<path d>` 的 `d`；`<circle>` / `<rect>` 等**不收**（注释里明说只支持线条型）；
2. `<script>` / `<image>` / `on*` **不进结果**（结果里只有 `d` 字符串）；
3. SVG 超过 `MAX_SVG_BYTES` ⇒ 拒绝；
4. 单条 `d` 超过 `MAX_PATH_LEN` ⇒ 拒绝；
5. path 数超过 `MAX_PATHS` ⇒ 拒绝；
6. 找不到任何 `<path d>` ⇒ 拒绝（不产出空图标）。
"""
from __future__ import annotations

import pytest

from novelforge.core import customicons


def test_只取_path_的_d():
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><path d="M1 1 L2 2"/></svg>'
    assert customicons.parse_svg(svg) == ["M1 1 L2 2"]


def test_非_path_元素不收():
    """圆 / 矩形不转（要支持它们得再维护一份元素白名单，收益低、攻击面大）。"""
    svg = ('<svg xmlns="http://www.w3.org/2000/svg">'
           '<circle cx="1" cy="1" r="1"/><rect x="0" y="0" width="2" height="2"/></svg>')
    with pytest.raises(ValueError) as e:
        customicons.parse_svg(svg)
    assert "没有找到" in str(e.value)


def test_脚本与外链不会进结果():
    """⚠️ 这是本模块存在的**全部理由**：结果只应是 `d` 字符串。

    `<script>` / `<image href=…>` / `onload=` 都不该以任何形式出现在结果里
    （前端会把结果直接拼进 `v-html`）。
    """
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)">'
        '<script>alert(2)</script>'
        '<image href="http://evil/x.png"/>'
        '<path d="M0 0 L1 1" onclick="alert(3)"/>'
        '</svg>')
    out = customicons.parse_svg(svg)
    assert out == ["M0 0 L1 1"], out
    joined = "".join(out)
    for bad in ("script", "alert", "onload", "onclick", "image", "evil", "http"):
        assert bad not in joined, f"结果里混进了 {bad!r}：{out}"


def test_超过_svg_上限要拒绝():
    big = '<svg xmlns="http://www.w3.org/2000/svg"><path d="' + ("M1 1 " * 40000) + '"/></svg>'
    with pytest.raises(ValueError) as e:
        customicons.parse_svg(big)
    assert "上限" in str(e.value)


def test_单条_path_太长要拒绝():
    d = "M1 1 " + ("L2 2 " * 5000)
    svg = f'<svg xmlns="http://www.w3.org/2000/svg"><path d="{d}"/></svg>'
    with pytest.raises(ValueError) as e:
        customicons.parse_svg(svg)
    assert "上限" in str(e.value)


def test_path_太多要拒绝():
    paths = "".join(f'<path d="M{i} 0"/>' for i in range(customicons.MAX_PATHS + 5))
    svg = f'<svg xmlns="http://www.w3.org/2000/svg">{paths}</svg>'
    with pytest.raises(ValueError) as e:
        customicons.parse_svg(svg)
    assert "最多" in str(e.value)


def test_坏_xml_要说人话():
    with pytest.raises(ValueError) as e:
        customicons.parse_svg("<svg><path d='M1 1'")
    assert "解析失败" in str(e.value)


def test_空内容要拒绝():
    with pytest.raises(ValueError):
        customicons.parse_svg("   ")


def test_图标名长度上限():
    assert customicons.icon_name("  我的图标  ") == "我的图标"
    with pytest.raises(ValueError):
        customicons.icon_name("")
    with pytest.raises(ValueError):
        customicons.icon_name("x" * (customicons.NAME_MAX + 1))
