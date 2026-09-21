"""阅读阈值可配（第 40 期）：`reading.started_threshold` / `reading.finished_threshold`。

第 40 期把散在全仓的 11 处硬编码 `99.5` 与 4 处 `pct > 0` 收敛到
``core/lib_settings.reading_thresholds``（**唯一入口**）＋ 新增
``GET /api/reading-thresholds``（前端唯一入口）。这个文件钉四件事：

1. **默认值逐字节等价** —— 默认 ``0.0 / 99.5`` 下的判定必须与改造前写死的
   ``pct > 0`` / ``pct >= 99.5`` 一模一样。这是「本期不改变任何既有判定」的根据；
   默认值一旦被顺手对齐成上游 BookOrbit 的 99，用户的书会一夜之间从「读完」变「在读」。
2. **同源** —— 改全局阈值后，统计 / 成就 / Komga 三处口径**一起**变（不许只改一半）。
3. **隔离** —— 每库覆写只影响那个库，全局值与其它库纹丝不动。
4. **校验** —— ``started >= finished`` 一律拒：放过去就会出现「还没开始就算读完」。
"""
import pathlib
import re

import pytest

from novelforge import config
from novelforge.core import db, lib_settings, library, stats

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def restore_overrides():
    """全局覆写的快照 / 还原 —— 用例改了全局阈值就不许漏给下一个用例。"""
    before = config.load_overrides()
    try:
        yield
    finally:
        config.save_overrides(before)


def _book_with_percent(root, name: str, pct: float) -> str:
    """在 `root` 放一本占位书并把进度设成 `pct`；返回书目 id。"""
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"EPUB")
    library.invalidate()
    b = library.find(name)
    assert b, f"占位书没进书目：{name}"
    # ⚠️ 不写 reading_status 行：走的是「无状态行时按进度兜底推导」这条路，
    #    正是阈值真正起作用的那条（有状态行时状态是权威，不看阈值）。
    db.set_progress(b["id"], 1, pct)
    return b["id"]


# ---------------------------------------------------------------------------
# 1. 默认值逐字节等价（本期的「零行为变化」保证）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("pct", [0, 0.01, 1, 25, 50, 75, 99.49, 99.5, 99.9, 100])
def test_默认阈值与改造前的硬编码逐字节等价(isolated, pct):  # noqa: ARG001
    """默认值下，新判据与旧字面量给出**同一个**结论（逐档核对，不是抽样）。"""
    started, finished = lib_settings.reading_thresholds()
    assert (started, finished) == (0.0, 99.5), "默认值就是既有口径，不许顺手改"

    def 新(p):
        return "finished" if p >= finished else ("reading" if p > started else "unread")

    def 旧(p):                      # 第 40 期之前写在 stats.py 里的那段
        return "finished" if p >= 99.5 else ("reading" if p > 0 else "unread")

    assert 新(pct) == 旧(pct), f"{pct}% 的判定被改动了"


def test_默认值下统计口径不变(isolated, default_root, restore_overrides):  # noqa: ARG001
    """一本 99.5% 的书在默认口径下算「已读完」（= 老行为，边界含等号）。"""
    _book_with_percent(default_root, "刚好读完.epub", 99.5)
    assert stats.overview()["reading"]["finished"] == 1


# ---------------------------------------------------------------------------
# 2. 同源：统计 / 成就 / Komga 一起变
# ---------------------------------------------------------------------------

def test_改全局阈值统计口径随之变(isolated, default_root, restore_overrides):  # noqa: ARG001
    """⚠️ 两个落点都要盯：``reading.finished``（状态兜底）与 ``progress_funnel.completed``
    （进度漏斗）是**同一次改动的两处**，只改一处的变异体必须被抓住（实测：只盯前者会漏）。
    """
    _book_with_percent(default_root, "半本.epub", 50.0)

    ov = stats.overview()
    assert ov["reading"]["finished"] == 0          # 默认 99.5 → 还不算读完
    assert ov["progress_funnel"]["completed"] == 0
    assert ov["progress_funnel"]["reached50"] == 1

    config.save_overrides({"reading": {"finished_threshold": 50}})
    ov = stats.overview()
    assert ov["reading"]["finished"] == 1          # 阈值降到 50 → 立即算读完
    assert ov["progress_funnel"]["completed"] == 1, "漏斗那一档漏改 = 两个真相源"


def test_在读下界抬起来后未读档跟着变(isolated, default_root, restore_overrides):  # noqa: ARG001
    """``started_threshold`` 同理：抬到 5% 之后，读到 3% 的书回到「未读」而不是「在读」。"""
    _book_with_percent(default_root, "翻了两页.epub", 3.0)
    assert stats.overview()["reading"]["reading"] == 1
    config.save_overrides({"reading": {"started_threshold": 5}})
    ov = stats.overview()
    assert ov["reading"]["reading"] == 0
    assert ov["reading"]["unread"] == 1
    assert ov["progress_funnel"]["started"] == 0, "漏斗的「开始」档同样要跟着抬"


def test_成就与统计同源(isolated, default_root, restore_overrides):  # noqa: ARG001
    """「读完 N 本」类成就的度量值来自 `stats.overview()`，不许自带第二套判定。"""
    from novelforge.core import achievements
    _book_with_percent(default_root, "半本.epub", 60.0)
    assert achievements._metrics()["finished"] == 0.0
    config.save_overrides({"reading": {"finished_threshold": 50}})
    assert achievements._metrics()["finished"] == 1.0


def test_komga的completed同源(isolated, default_root, restore_overrides):  # noqa: ARG001
    """Komga 客户端的「读完」标记也读配置 —— 否则第三方 App 会显示成永远没读完。"""
    from novelforge.core import komga_api
    _book_with_percent(default_root, "半本.epub", 60.0)
    b = library.find("半本.epub")

    assert komga_api.read_progress_dto(b, db.get_progress(b["id"]))["completed"] is False
    config.save_overrides({"reading": {"finished_threshold": 50}})
    assert komga_api.read_progress_dto(b, db.get_progress(b["id"]))["completed"] is True


# ---------------------------------------------------------------------------
# 3. 每库覆写只影响那个库
# ---------------------------------------------------------------------------

def test_每库覆写只影响该库(isolated, default_root, make_library, tmp_path,
                            restore_overrides):  # noqa: ARG001
    """甲库把阈值降到 50，乙库仍按全局 99.5 判 —— 同一本书的百分比、两种结论。"""
    make_library("lib-b", "乙库", "mixed", tmp_path / "libraries" / "lib-b")
    _book_with_percent(default_root, "半本.epub", 60.0)
    lib_settings.set_overrides("default", {"reading.finished_threshold": 50})

    assert stats.overview(library_id="default")["reading"]["finished"] == 1
    assert stats.overview(library_id="lib-b")["reading"]["finished"] == 0
    assert stats.overview()["reading"]["finished"] == 0, "全局值不许被覆写污染"


# ---------------------------------------------------------------------------
# 4. 跨字段校验：没开始就算读完是个畸形
# ---------------------------------------------------------------------------

def test_在读下界不得大于等于已读完阈值(isolated, default_root, make_library,
                                        tmp_path):  # noqa: ARG001
    make_library("lib-a", "甲库", "mixed", tmp_path / "libraries" / "lib-a")
    for 坏 in ({"reading.started_threshold": 90, "reading.finished_threshold": 50},
               {"reading.started_threshold": 50, "reading.finished_threshold": 50}):
        with pytest.raises(ValueError, match="必须小于"):
            lib_settings.set_overrides("lib-a", 坏)


def test_阈值接口给出生效值(client, auth_headers, make_library, tmp_path,
                            restore_overrides):  # noqa: ARG001
    make_library("lib-a", "甲库", "mixed", tmp_path / "libraries" / "lib-a")
    url = "/api/reading-thresholds"

    assert client.get(url, headers=auth_headers).json() == {
        "library_id": "", "started": 0.0, "finished": 99.5}
    lib_settings.set_overrides("lib-a", {"reading.finished_threshold": 80})
    body = client.get(url, headers=auth_headers, params={"library_id": "lib-a"}).json()
    assert (body["started"], body["finished"]) == (0.0, 80.0)
    # 带库时是**生效值**，不带库时是全局值 —— 两者不能混
    assert client.get(url, headers=auth_headers).json()["finished"] == 99.5

    assert client.get(url, headers=auth_headers,
                      params={"library_id": "没有这个库"}).status_code == 404


def test_阈值越界与坏值一律回落(isolated, restore_overrides):  # noqa: ARG001
    """手改坏 config 一个字符不该把统计整页弄挂（与 `overrides` 同口径）。"""
    config.save_overrides({"reading": {"finished_threshold": "不是数字",
                                       "started_threshold": 999}})
    assert lib_settings.reading_thresholds() == (0.0, 99.5)


def test_percent类型与number类型区间不同(isolated):  # noqa: ARG001
    """`number` 是 0–1（比例），`percent` 是 0–100 —— 复用 number 会把 99.5 判成越界。"""
    assert lib_settings._validate("reading.finished_threshold", 99.5) == 99.5
    assert lib_settings._validate("reading.finished_threshold", 0.05) == 0.05
    with pytest.raises(ValueError):
        lib_settings._validate("reading.finished_threshold", 100.5)


# ---------------------------------------------------------------------------
# 5. 前端静态护栏：不许再写死阈值
# ---------------------------------------------------------------------------

#: 前端唯一允许出现阈值字面量的文件。
_FRONTEND_ENTRY = "frontend/src/lib/readingThresholds.ts"

#: 「拿阈值去做比较」的写法。刻意只匹**比较**而不是裸的 `99.5` ——
#: 文案（「默认 99.5%」）、注释（「别写死 99.5」）里出现这个数字是正常的、也是必要的，
#: 一刀切禁掉只会逼人把说明删掉。
_HARDCODED_CMP = re.compile(r"([<>]=?\s*99\.5\b|99\.5\s*[<>]=?)")


def test_前端不再写死阈值():
    """静态扫源码：`p >= 99.5` 这类判定只能出现在唯一入口里。

    这是一条**纯文本断言**，理由与 `tests/test_frontend_unit_contract.py` 同：
    仓内的硬前提是全量测试离线，从 pytest 里拉 node 会破坏它。
    但它盯的正是「只改后端、前端仍读 99.5」这个变异 —— 那会让统计说已读完、
    书架说在读，而两边的单测各自都是绿的。
    """
    src = ROOT / "frontend" / "src"
    offenders = []
    for p in src.rglob("*"):
        if p.suffix not in (".ts", ".vue") or not p.is_file():
            continue
        rel = p.relative_to(ROOT).as_posix()
        if rel == _FRONTEND_ENTRY:
            continue
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if _HARDCODED_CMP.search(line):
                offenders.append(f"{rel}:{i}: {line.strip()}")
    assert not offenders, (
        "这些地方又按字面量 99.5 判阅读状态了 —— 阈值已可配（设置页 / 每库覆写），"
        "写死就会出现两个真相源。改调 frontend/src/lib/readingThresholds.ts：\n  "
        + "\n  ".join(offenders))


def test_前端兜底值与后端默认值逐字节一致():
    """`FALLBACK` 与 `config.DEFAULTS['reading']` 必须相同。

    不同就会出现「首屏按 A 判、阈值拉回来之后跳成 B」的闪烁 —— 而且只在慢网络上出现，
    本地开发永远复现不了。这条把两个数字钉在一起。
    """
    ts = (ROOT / "frontend" / "src" / "lib" / "readingThresholds.ts").read_text(encoding="utf-8")
    m = re.search(r"FALLBACK[^=]*=\s*\{\s*started:\s*([\d.]+)\s*,\s*finished:\s*([\d.]+)\s*\}",
                  ts)
    assert m, "解析不到 readingThresholds.ts 的 FALLBACK 常量，正则大概过期了"
    d = config.DEFAULTS["reading"]
    assert (float(m.group(1)), float(m.group(2))) == (
        float(d["started_threshold"]), float(d["finished_threshold"])), (
        f"前端兜底 {m.group(1)}/{m.group(2)} 与后端默认 "
        f"{d['started_threshold']}/{d['finished_threshold']} 不一致")
