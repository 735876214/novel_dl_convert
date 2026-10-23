"""CHANGELOG 取段（第 79 期收敛）：Release notes 与「新功能」页同源。

`changelog.section()` 是「取某版段落」的**唯一实现**，`.github/workflows/release.yml`
直接 `python3 -m novelforge.core.changelog <版本>` 调它 —— 所以这条链路值得一组离线契约：
文件读不到 / 版本找不到 / 段边界算错，后果都是**发布出一个内容不对（或空）的 Release**。

用例里的版本号一律从仓库根 `VERSION` 读，不写死 —— 否则每次改版本都会红。
"""
import pathlib
import re

from novelforge.core import changelog

REPO = pathlib.Path(__file__).resolve().parents[1]
VER = (REPO / "VERSION").read_text(encoding="utf-8").strip()


def test_取当前版本段_与文件原文切片一致():
    """`VERSION` 指向的版本必须在 CHANGELOG 里有段，且内容逐字等于原文切片。

    这条把「版本号与 CHANGELOG 脱节」变成红灯：改了 `VERSION` 却忘了补 CHANGELOG 段时，
    自动发布会在 CI 里失败（`main()` 以 1 退出），而不是建一个空 notes 的 Release。
    """
    text = changelog.section(VER)
    assert text, f"CHANGELOG.md 里没有 V{VER} 段（改版本号必须同批补段）"
    assert text.startswith("### "), "段落应从第一个分组标题开始（不含 `## V<版本> — <日期>` 那一行）"

    raw = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## V{re.escape(VER)}\b.*$", raw, re.M)
    assert m, "版本标题形状应为 `## V<版本> — <日期>`"
    nxt = re.compile(r"^## ", re.M).search(raw, m.end())
    expect = raw[m.end():(nxt.start() if nxt else len(raw))].strip()
    assert text == expect, "取段口径必须与「下一个 `## ` 之前」逐字一致"


def test_版本前缀可带可不带():
    """`V<版本>` / `<版本>` / 前后空白等价 —— CI 传的是 `${TAG#v}`（不带 V）。"""
    base = changelog.section(VER)
    assert base
    assert changelog.section(f"V{VER}") == base
    assert changelog.section(f" {VER} ") == base


def test_找不到版本段返回空串():
    """不存在的版本 / 空版本一律空串：调用方据此报错，而不是猜一段出来。"""
    assert changelog.section("9.9.9") == ""
    assert changelog.section("") == ""
    assert changelog.section(None) == ""


def test_命令行入口_成功与失败(capsys):
    """CI 的两条路：找到 ⇒ 0 且 notes 上屏；找不到 ⇒ 非 0 且**不产出空 notes**。

    第 150 期：这里原来硬断言「输出里含 `### 新功能`」—— 那是**撰写习惯**，不是取段的契约：
    一个以修复为主的版本，首个分组叫「修复：…」完全正当。改成「上屏内容 == `section()` 的结果」
    （真正要防的是「notes 是空的 / 掺了别的东西」），分组名不再被钉死。
    """
    assert changelog.main([VER]) == 0
    out = capsys.readouterr().out
    assert out.strip() == changelog.section(VER).strip(), "上屏内容必须就是这一版段落的原文"
    assert out.strip().startswith("### "), "段落应从第一个分组标题开始"

    assert changelog.main(["9.9.9"]) == 1
    assert "9.9.9" in capsys.readouterr().err


def test_解析与取段同源():
    """`parse()`（应用内「新功能」页）与 `section()`（Release notes）看的必须是同一段。"""
    entry = changelog.parse((REPO / "CHANGELOG.md").read_text(encoding="utf-8"))[0]
    assert entry["version"] == f"V{VER}", "CHANGELOG 的首段应当就是当前版本"
    assert entry["date"], "当前版本段必须带日期"
    text = changelog.section(VER)
    for group in entry["groups"]:
        assert f"### {group['tag']}" in text, f"取段里缺少分组 `{group['tag']}`"
        for item in group["items"]:
            assert item in text, f"取段里缺少条目：{item[:30]}…"
