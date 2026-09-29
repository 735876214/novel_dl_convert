"""CHANGELOG.md 解析（第 78 期）。

应用内「新功能」页面的**唯一数据源**，离线可读；GitHub Release 也从同一文件抽段。
解析规则（刻意简单、可预测）：

- ``## <版本> — <日期>`` 或 ``## <版本>`` ＝ 一个版本段（版本形如 ``V0.78.0``）；
  形如 ``## 更早（…）`` 的段版本字段取标题全文、日期为空。
- ``### <标签>`` ＝ 该版本下的一个分组（标签取自 ``新功能 / 优化 / 修复 / 生态``）。
- 以 ``- `` 开头的行＝该分组下的一条。
- 以 ``>`` 开头的块引用＝版本段备注（如「更早」段的说明）。

读不到文件时返回空列表（不是错误）—— 应用仍能跑，只是「新功能」页为空。
"""
import pathlib
import re

# 容器里 COPY 到 /app/CHANGELOG.md；开发态在仓库根。
_CANDIDATES = [
    pathlib.Path("/app/CHANGELOG.md"),
    pathlib.Path(__file__).resolve().parents[2] / "CHANGELOG.md",
]

_VERSION_RE = re.compile(r"^(V[\d.]+)\s*[—-]\s*(\S+)$")


def _load_text() -> str:
    for p in _CANDIDATES:
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            continue
    return ""


def parse(text: str) -> "list[dict]":
    """把 CHANGELOG 文本解析成版本条目列表。

    每项：``{"version": str, "date": str|None, "note": str, "groups": [{"tag": str, "items": [str]}]}``。
    """
    entries: "list[dict]" = []
    cur: "dict | None" = None
    group: "dict | None" = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.startswith("## "):
            if cur is not None:
                entries.append(cur)
            head = line[3:].strip()
            m = _VERSION_RE.match(head)
            if m:
                cur = {"version": m.group(1), "date": m.group(2), "note": "", "groups": []}
            else:
                cur = {"version": head, "date": None, "note": "", "groups": []}
            group = None
        elif line.startswith("### ") and cur is not None:
            group = {"tag": line[4:].strip(), "items": []}
            cur["groups"].append(group)
        elif line.startswith("- ") and cur is not None and group is not None:
            group["items"].append(line[2:].strip())
        elif line.startswith(">") and cur is not None:
            cur["note"] = (cur["note"] + line[1:].strip() + "\n").strip()
    if cur is not None:
        entries.append(cur)
    return entries


def load() -> "list[dict]":
    return parse(_load_text())
