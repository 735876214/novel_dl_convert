"""自定义图标（第 216 期）—— 只收 SVG 的 `<path d>` 片段。

为什么不存完整 SVG：图标最终会以 `v-html` 画进按钮（与内置图标同一条渲染路径），
完整 SVG 里的 `<script>` / `on*` / 外链 `<image>` 都会跟着进来。服务端只提取
`<path d="…">` 的 `d` 字符串、前端再重新拼成 `<path d=…/>`，可控且够用。

边界：只支持**线条型** path 图标（圆 / 矩形 / 多边形不转）—— 要支持它们就得再维护
一套「哪些元素可以保留」的白名单，收益低、攻击面大。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

MAX_SVG_BYTES = 256 * 1024
MAX_PATHS = 200
MAX_PATH_LEN = 20_000
NAME_MAX = 80


def icon_name(raw) -> str:
    name = str(raw or "").strip()
    if not name:
        raise ValueError("图标名不能为空")
    if len(name) > NAME_MAX:
        raise ValueError(f"图标名最多 {NAME_MAX} 个字符")
    return name


def _local(tag) -> str:
    return str(tag).rsplit("}", 1)[-1]


def parse_svg(raw) -> list:
    text = str(raw or "")
    if not text.strip():
        raise ValueError("SVG 内容不能为空")
    if len(text.encode("utf-8")) > MAX_SVG_BYTES:
        raise ValueError(f"SVG 超过 {MAX_SVG_BYTES // 1024} KB 上限")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        raise ValueError(f"SVG 解析失败：{e}") from None
    out: list = []
    for el in root.iter():
        if _local(el.tag) != "path":
            continue
        d = str(el.get("d") or "").strip()
        if not d:
            continue
        if len(d) > MAX_PATH_LEN:
            raise ValueError(f"单条 path 数据超过 {MAX_PATH_LEN} 字符上限")
        out.append(d)
        if len(out) > MAX_PATHS:
            raise ValueError(f"图标最多 {MAX_PATHS} 条 path")
    if not out:
        raise ValueError("没有找到 <path d=\"…\"> —— 自定义图标只支持线条型 path")
    return out
