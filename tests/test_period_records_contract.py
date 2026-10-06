"""收尾记录的契约（第 107 期）。

`tests/period_close.py` 是工具，这里钉的是**它的判据**：每条对账规则都得有「故意破坏 ⇒ 报错」
的用例（否则规则只是愿望），并且 `check` 必须只读、`new` 必须幂等、行尾必须保住。

真实仓库那条用例（`test_真实仓库收尾记录无漂移`）是**活契约**：它让「三处记录一致」在每次
全量 pytest 里都被检查一次 —— 这就是「本地全量 pytest 是既有强制点」的具体落法。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

# `tests/` 没有 `__init__.py`（pytest 的 prepend 模式只把仓库根放进 sys.path）⇒ 显式加同级目录，
# 否则 `import period_close` 在「pytest 收集」与「直接跑脚本」两种入口下行为不一致。
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from period_close import (  # noqa: E402
    AGENTS,
    MEMORY,
    MEMORY_DIR,
    PERIODS,
    ROADMAP,
    TODO,
    VERSION,
    ScaffoldError,
    check_records,
    main,
    numbers_from_junit,
    scaffold,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

ROADMAP_STUB = """# 路线图（测试桩）

## 第 100 期（老一期）

内容。

## 第 107 期（新一期）

内容。
"""

TODO_STUB = """# TODO.md（测试桩）

**最后更新**：2026-10-06 —— 第 106 期**老一期**：
一句话。

## 0. 当前状态

- HEAD = 第 94 期提交 + 第 107 期新一期；`VERSION` = **0.94.0**
- 测试基线（第 107 期实测）：后端 **2311 例（2286 passed / 0 failed / 0 errors / 25 skipped）**，全量 274.56 s；

## 1. 待办

- 无。

## 2. 交付索引

> 细节一律进路线图。

|---|---|
| 107 | 新一期 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 107 期段 |
| 100 | 老一期 |

**更早的期次**：本仓无逐期记录（表尾脚注，**不在两条数据行之间**，不算裸行）。

## 3. 排期候选
"""

AGENTS_STUB = """# AGENTS.md（测试桩）

## 4. 常用命令

```bash
.venv/bin/python -m pytest                 # 当前基线 2311 例（2286 passed / 25 skipped；只增不减）
```

## 6. 提交与交付

- **每期收尾只写两处（第 106 期起）**：roadmap 本期段 + `MEMORY.md` 索引一行。
"""

MEMORY_STUB = """# MEMORY.md（测试桩）

## 硬约定

- 无。

## 逐期铁律索引（一期一行）

- **100** 老一期
- **107** 新一期
"""

PERIODS_STUB = """# 逐期铁律存档（测试桩，只读）

## 第 100 期铁律

内容。
"""


def _write(path: pathlib.Path, text: str, eol: str = "\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", eol).encode("utf-8"))


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """最小可用仓库：默认**无漂移**（对账 0 问题），各用例只在它身上破坏一处。"""
    _write(tmp_path / VERSION, "0.94.0\n")
    _write(tmp_path / ROADMAP, ROADMAP_STUB)
    _write(tmp_path / TODO, TODO_STUB)
    _write(tmp_path / AGENTS, AGENTS_STUB)
    _write(tmp_path / MEMORY, MEMORY_STUB)
    _write(tmp_path / PERIODS, PERIODS_STUB)
    _write(tmp_path / MEMORY_DIR / "2026-10-06.md", "# 当日日志（历史，允许存在）\n")
    return tmp_path


def _text(root: pathlib.Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8-sig")


def _patch(root: pathlib.Path, rel: str, old: str, new: str) -> None:
    path = root / rel
    text = path.read_text(encoding="utf-8-sig")
    assert text.count(old) == 1, f"{rel} 里 {old!r} 出现 {text.count(old)} 次"
    path.write_text(text.replace(old, new), encoding="utf-8")


def _problems(root: pathlib.Path, history: bool = False) -> list[str]:
    return check_records(root, history=history)[0]


def _snapshot(root: pathlib.Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ------------------------------------------------------------ 活契约


def test_真实仓库收尾记录无漂移() -> None:
    problems, _ = check_records(REPO_ROOT)
    assert problems == [], "收尾记录出现漂移：\n" + "\n".join(problems)


def test_桩仓库本身无漂移(repo: pathlib.Path) -> None:
    assert _problems(repo) == []


# ------------------------------------------------------------ R1 三处齐全


def test_缺_TODO_行报_R1(repo: pathlib.Path) -> None:
    _patch(repo, TODO, "| 107 | 新一期", "| 108 | 新一期")
    problems = _problems(repo)
    assert any("[R1]" in p and "§2 缺一行" in p for p in problems)


def test_缺索引行报_R1(repo: pathlib.Path) -> None:
    _patch(repo, MEMORY, "- **107** 新一期\n", "")
    problems = _problems(repo)
    assert any("[R1]" in p and "逐期索引缺一行" in p for p in problems)


# ------------------------------------------------------------ R2 索引自身


def test_索引里的幽灵期号报_R2(repo: pathlib.Path) -> None:
    _patch(repo, MEMORY, "- **107** 新一期\n", "- **107** 新一期\n- **999** 幽灵\n")
    problems = _problems(repo)
    assert any("[R2]" in p and "幽灵期号" in p for p in problems)


def test_索引标签认不出报_R2(repo: pathlib.Path) -> None:
    _patch(repo, MEMORY, "- **107** 新一期\n", "- **107** 新一期\n- **近期** 认不出的标签\n")
    problems = _problems(repo)
    assert any("[R2]" in p and "认不出" in p for p in problems)


def test_索引标签重复报_R2(repo: pathlib.Path) -> None:
    _patch(repo, MEMORY, "- **100** 老一期\n", "- **100** 老一期\n- **100** 老一期\n")
    problems = _problems(repo)
    assert any("[R2]" in p and "重复" in p for p in problems)


def test_历史期的缺行只给_warning(repo: pathlib.Path) -> None:
    _patch(repo, ROADMAP, "## 第 100 期（老一期）", "## 第 90 期（更老一期）")
    _patch(repo, MEMORY, "- **100** 老一期\n", "- **90** 更老一期\n")
    problems, warns = check_records(repo, history=True)
    assert problems == []
    assert any("历史豁免" in w for w in warns)


# ------------------------------------------------------------ R3 §0 与两处基线


def test_HEAD_链没提最新期号报_R3(repo: pathlib.Path) -> None:
    _patch(repo, TODO, "第 107 期新一期；", "第 106 期新一期；")
    _patch(repo, TODO, "（第 107 期实测）", "（第 106 期实测）")
    problems = _problems(repo)
    assert any("[R3]" in p and "HEAD 链没提到最新期号" in p for p in problems)


def test_两处基线不一致报_R3(repo: pathlib.Path) -> None:
    _patch(repo, AGENTS, "# 当前基线 2311 例", "# 当前基线 2312 例")
    problems = _problems(repo)
    assert any("[R3]" in p and "基线数字两处不一致" in p for p in problems)


# ------------------------------------------------------------ R4 / R5 收尾口径


def test_新建当日日志报_R4(repo: pathlib.Path) -> None:
    _write(repo / MEMORY_DIR / "2026-10-07.md", "# 又写当日日志了\n")
    problems = _problems(repo)
    assert any("[R4]" in p and "当日日志" in p for p in problems)


def test_存档被追加报_R5(repo: pathlib.Path) -> None:
    with (repo / PERIODS).open("a", encoding="utf-8") as fh:
        fh.write("\n## 第 107 期铁律\n\n不该出现在存档里。\n")
    problems = _problems(repo)
    assert any("[R5]" in p and "只读存档" in p for p in problems)


# ------------------------------------------------------------ R6 / R7 / R8


def test_新期号的行太长报_R6(repo: pathlib.Path) -> None:
    _patch(repo, TODO, "| 107 | 新一期", "| 107 | 新一期" + "很长" * 200)
    problems = _problems(repo)
    assert any("[R6]" in p and "只写一行" in p for p in problems)


def test_历史期的长行豁免_R6(repo: pathlib.Path) -> None:
    _patch(repo, TODO, "| 100 | 老一期 |", "| 100 | 老一期" + "很长" * 200 + " |")
    assert not any("[R6]" in p for p in _problems(repo))


def test_同一期在_S2_出现两次报_R6(repo: pathlib.Path) -> None:
    _patch(repo, TODO, "| 107 | 新一期", "| 107 | 新一期\n| 107 | 新一期")
    problems = _problems(repo)
    assert any("[R6]" in p and "出现了 2 次" in p for p in problems)


def test_S2_表里夹裸行报_R6(repo: pathlib.Path) -> None:
    # 真实事故形状：某一期的行**表头前缀被吃掉**，剩下的正文掉进表格里（第 105 期那条就这么留了十几期）
    _patch(repo, TODO, "| 100 | 老一期 |", "  老一期的正文，没有 `| 100 |` 前缀\n| 100 | 老一期 |")
    problems = _problems(repo)
    assert any("[R6]" in p and "裸行" in p for p in problems)


def test_版本字面量不一致报_R7(repo: pathlib.Path) -> None:
    _patch(repo, TODO, "`VERSION` = **0.94.0**", "`VERSION` = **0.95.0**")
    problems = _problems(repo)
    assert any("[R7]" in p and "0.95.0" in p for p in problems)


def test_fix_把版本字面量改回来(repo: pathlib.Path) -> None:
    _patch(repo, TODO, "`VERSION` = **0.94.0**", "`VERSION` = **0.95.0**")
    assert main(["check", "--root", str(repo), "--fix"]) == 0
    assert "**0.94.0**" in _text(repo, TODO)


def test_S2_历史行里的旧版本字面量不算漂移(repo: pathlib.Path) -> None:
    """§2 是**逐期历史索引**（与 roadmap 本期段同类），不是「当前态」声明。

    第 109 期第一次真正发版时实测：R7 与 `--fix` 一并扫表格行 ⇒ 一次把 **12 行**历史记录
    「（**不发版**，`VERSION` 仍 0.94.0）」改成 `1.0.0` —— 历史就成了谎话。
    现在 R7 只管 §0 头部与 `AGENTS.md` §4，历史行一律不碰。
    """
    _patch(repo, TODO, "| 100 | 老一期 |", "| 100 | 老一期（**不发版**，`VERSION` 仍 0.93.0） |")
    assert not any("[R7]" in p for p in _problems(repo))
    assert main(["check", "--root", str(repo), "--fix"]) == 0
    assert "`VERSION` 仍 0.93.0" in _text(repo, TODO), "历史行被 --fix 改写了"


def test_口径句被删报_R8(repo: pathlib.Path) -> None:
    _patch(repo, AGENTS, "每期收尾只写两处", "以前那套仪式")
    problems = _problems(repo)
    assert any("[R8]" in p for p in problems)


# ------------------------------------------------------------ new：落位


def test_new_一次把几处落位(repo: pathlib.Path) -> None:
    log = scaffold(repo, 108, "演练一期", numbers=(2400, 2370, 25), seconds="300.5")
    assert any("roadmap" in ln for ln in log)
    assert "## 第 108 期（演练一期）" in _text(repo, ROADMAP)
    assert "| 108 | 演练一期 —— 细节见 `docs/roadmap-gaps-remaining.md` 第 108 期段 |" in _text(repo, TODO)
    assert "第 108 期演练一期" in _text(repo, TODO)
    assert "- **108** 演练一期" in _text(repo, MEMORY)
    assert "后端 **2400 例（2370 passed / 0 failed / 0 errors / 25 skipped）**" in _text(repo, TODO)
    assert "全量 300.5 s" in _text(repo, TODO)
    assert "# 当前基线 2400 例（2370 passed / 25 skipped；只增不减）" in _text(repo, AGENTS)
    # 新的期号自己也要对得上账（否则工具在教人漂移）
    assert _problems(repo) == []


def test_new_索引行插在续行之后(repo: pathlib.Path) -> None:
    """上一条索引可能带续行说明（缩进的非列表行）。

    第 109 期第一次真发版时踩到：`new` 把新条目插在「最后一条 `- **N**` 行」之后，于是老条目的
    续行被留在了新条目底下（看起来像新条目在讲老一期的事）。现在插在**整段索引末尾**。
    """
    _patch(repo, MEMORY, "- **107** 新一期\n", "- **107** 新一期\n  续行说明（属于 107）。\n")
    scaffold(repo, 108, "演练一期")
    lines = [ln for ln in _text(repo, MEMORY).split("\n") if ln.strip()]
    assert lines[-2] == "  续行说明（属于 107）。", lines[-3:]
    assert lines[-1] == "- **108** 演练一期", lines[-3:]


def test_new_索引小节空了就整体拒绝(repo: pathlib.Path) -> None:
    _patch(repo, MEMORY, "- **100** 老一期\n- **107** 新一期\n", "")
    before = _snapshot(repo)  # 拍在 `_patch` 之后：`_patch` 会把行尾规范成 CRLF
    with pytest.raises(ScaffoldError):
        scaffold(repo, 108, "演练一期")
    assert _snapshot(repo) == before


def test_new_把旧口径的轮次数换成_VERSION_派生句(repo: pathlib.Path) -> None:
    _patch(
        repo,
        TODO,
        "；`VERSION` = **0.94.0**",
        "；`VERSION` = **0.94.0**\n"
        "  （**十二轮都刻意未升**：第 95 期甲、第 96 期乙，用户十二次都选「先不发版」；\n"
        "  单一真值源，`GET /health` 下发）；",
    )
    scaffold(repo, 108, "演练一期")
    text = _text(repo, TODO)
    assert "轮都刻意未升" not in text
    assert "自 v0.94.0 起未再升版" in text


def test_new_期号被占用就整体拒绝(repo: pathlib.Path) -> None:
    before = _snapshot(repo)
    with pytest.raises(ScaffoldError):
        scaffold(repo, 107, "重复落位")
    assert _snapshot(repo) == before


def test_new_没给数字就提示两处待改(repo: pathlib.Path) -> None:
    log = scaffold(repo, 108, "演练一期")
    assert any("--numbers" in ln and "待手改" in ln for ln in log)
    assert "# 当前基线 2311 例" in _text(repo, AGENTS)  # 没猜数字


def test_new_dry_run_不写文件(repo: pathlib.Path) -> None:
    before = _snapshot(repo)
    scaffold(repo, 108, "演练一期", dry_run=True)
    assert _snapshot(repo) == before


def test_check_只读(repo: pathlib.Path) -> None:
    before = _snapshot(repo)
    check_records(repo, history=True)
    assert _snapshot(repo) == before


def test_new_保住_CRLF(tmp_path: pathlib.Path) -> None:
    eol = "\r\n"
    _write(tmp_path / VERSION, "0.94.0\n", eol)
    _write(tmp_path / ROADMAP, ROADMAP_STUB, eol)
    _write(tmp_path / TODO, TODO_STUB, eol)
    _write(tmp_path / AGENTS, AGENTS_STUB, eol)
    _write(tmp_path / MEMORY, MEMORY_STUB, eol)
    _write(tmp_path / PERIODS, PERIODS_STUB, eol)
    scaffold(tmp_path, 108, "演练一期")
    for rel in (ROADMAP, TODO, AGENTS, MEMORY):
        raw = (tmp_path / rel).read_bytes()
        assert b"\r\n" in raw, f"{rel} 丢了 CRLF"
        assert raw.replace(b"\r\n", b"") .count(b"\n") == 0, f"{rel} 混进了裸 LF"
    assert check_records(tmp_path)[0] == []


# ------------------------------------------------------------ junit


def test_junit_取到三个数字(tmp_path: pathlib.Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text(
        '<?xml version="1.0" encoding="utf-8"?><testsuites>'
        '<testsuite name="a" tests="2400" failures="0" errors="0" skipped="25"/>'
        "</testsuites>",
        encoding="utf-8",
    )
    assert numbers_from_junit(xml) == (2400, 2375, 25)


def test_junit_读不到用例数就报错(tmp_path: pathlib.Path) -> None:
    xml = tmp_path / "junit.xml"
    xml.write_text('<?xml version="1.0" encoding="utf-8"?><testsuites></testsuites>', encoding="utf-8")
    with pytest.raises(ScaffoldError):
        numbers_from_junit(xml)


def test_new_的_CLI_入口可用(repo: pathlib.Path) -> None:
    assert main(["new", "--root", str(repo), "--period", "108", "--title", "演练一期"]) == 0
    assert main(["check", "--root", str(repo)]) == 0
    # 期号已占用 ⇒ 退 1 且什么都不改
    before = _snapshot(repo)
    assert main(["new", "--root", str(repo), "--period", "108", "--title", "再来一次"]) == 1
    assert _snapshot(repo) == before
