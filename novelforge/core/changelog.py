"""CHANGELOG.md 解析（第 78 期）。

应用内「新功能」页面的**唯一数据源**，离线可读；GitHub Release 也从同一文件抽段。
解析规则（刻意简单、可预测）：

- ``## <版本> — <日期>`` 或 ``## <版本>`` ＝ 一个版本段（版本形如 ``V0.78.0``）；
  形如 ``## 更早（…）`` 的段版本字段取标题全文、日期为空。
- ``### <标签>`` ＝ 该版本下的一个分组（标签取自 ``新功能 / 优化 / 修复 / 生态``）。
- 以 ``- `` 开头的行＝该分组下的一条。
- 以 ``>`` 开头的块引用＝版本段备注（如「更早」段的说明）。

读不到文件时返回空列表（不是错误）—— 应用仍能跑，只是「新功能」页为空。

**取某版段落只有一处实现**（第 79 期收敛）：:func:`section`（原文切片，Release notes 用）
与 :func:`parse`（结构化，应用内用）共用同一套「以 ``## `` 开头的行为分界」的判据；
CI 侧原先在内联脚本里又写了一份正则 + 切片，现改为调
``python3 -m novelforge.core.changelog <版本>``（见 :func:`main`）。
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


def _version_of(head: str) -> str:
    """段标题 → 可比较的版本串（去掉 ``V`` 前缀；非版本标题原样返回）。"""
    m = _VERSION_RE.match(head)
    return (m.group(1) if m else head).lstrip("vV")


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


def section(version: str) -> str:
    """某个版本段的**原文**（Markdown，不含 ``## 标题`` 那一行）；找不到返回空串。

    给 GitHub Release 的 notes 用。与 :func:`parse` 是**同一份判据**（``## `` 开头分行），
    所以 Release 上的内容与应用内「新功能」页看到的永远是同一段文字。

    ``version`` 可带可不带 ``V`` 前缀（``"V0.79.0"`` / ``"0.79.0"`` 等价）。
    """
    want = str(version or "").strip().lstrip("vV")
    if not want:
        return ""
    out: "list[str] | None" = None
    for line in _load_text().splitlines():
        if line.startswith("## "):
            if out is not None:
                break                       # 撞到下一段 ⇒ 本节结束
            if _version_of(line[3:].strip()) == want:
                out = []
            continue
        if out is not None:
            out.append(line)
    return "\n".join(out or []).strip()


def main(argv: "list[str] | None" = None) -> int:
    """命令行入口：``python -m novelforge.core.changelog <版本>`` → 打印该版本段原文。

    找不到对应版本段时**打印到 stderr 并以 1 退出** —— CI 里要的正是「CHANGELOG 缺段
    就让发布失败」，而不是建一个空 notes 的 Release。
    """
    import sys
    args = list(sys.argv[1:] if argv is None else argv)
    want = args[0] if args else ""
    text = section(want)
    if not text:
        print(f"CHANGELOG.md 未找到对应版本段：{want or '(未给版本)'}", file=sys.stderr)
        return 1
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
