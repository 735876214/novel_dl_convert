"""**界面文本不许混进开发历史**（第 222 期）。

`frontend/src/data/settingsNav.ts` 的 `note` 是**直接显示给用户**的设置页说明文字
（渲染点：`frontend/src/views/settings/SettingsPlaceholder.vue` 的 `{{ page.note }}`）。

它此前混着面向开发者的历史叙述 ——「已实现：…」「第 51 期补齐…」「上游该页 10 项全覆盖，
故无未支持对照卡」。用户在设置页看到「第 51 期」没有任何意义，而那段历史在
`docs/roadmap-gaps-remaining.md`（唯一叙事）与 `docs/bookorbit/bookorbit-settings-inventory.md`
（上游逐页对照）里都有。

所以这里钉：**`note` 里不许出现期号 / 「已实现」/ 「本项目实现」这类开发措辞**。

⚠️ 只查 `note` 字段，不查整个文件 —— 同一文件里**注释**就该带期号（那是给开发者看的），
`tests/test_settings_nav_contract.py` 也在查别的契约。
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAV = ROOT / "frontend" / "src" / "data" / "settingsNav.ts"

#: 开发历史的口味（任一命中即视为混进界面文本）
_DEV_MARKERS = (
    r"第\s*\d+\s*期",
    r"已实现",
    r"本项目实现",
    r"本项目把",
    r"上游该页",
    r"故无「未支持」对照卡",
)

_NOTE = re.compile(r"note:\s*'((?:[^'\\]|\\.)*)'")


def _notes() -> list[str]:
    return [m.group(1) for m in _NOTE.finditer(NAV.read_text(encoding="utf-8"))]


def test_note_里不许有开发历史():
    notes = _notes()
    assert len(notes) >= 20, f"只找到 {len(notes)} 条 note —— 解析口径坏了？"
    bad = []
    for n in notes:
        for mk in _DEV_MARKERS:
            if re.search(mk, n):
                bad.append(f"{mk} → {n[:70]}")
                break
    assert not bad, "设置页说明里混进了开发历史：\n  " + "\n  ".join(bad)


def test_note_仍说清功能与限制():
    """删历史**不能删成空壳** —— 用户要知道「有什么功能 / 有什么限制 / 什么未支持」。"""
    for n in _notes():
        assert len(n) >= 30, f"note 太短，多半是被删空了：{n!r}"
        assert n.strip(), "note 是空串"
