"""第 29 期：统计域的两处增补 —— 书库体检的百分比口径 + 体积榜（Top 50 Largest Books）。

对齐上游 `packages/types/src/statistics.ts` 的两个形状：
``LibraryIntegrityGauge``（:239）与 ``LargestBookItem``（:253）。两者都是**增补**，
所以这个文件钉的第一件事就是「旧的没丢」：

1. **原有 5 个计数键一个都不能少**（``missing_author`` / ``missing_language`` / ``no_cover`` /
   ``zero_size`` / ``unparsable``）—— 旧渲染路径与既有接口契约都读它们；
2. **百分比口径自洽**：``present`` / ``primary`` / ``metadata`` 三个覆盖率与 ``score``
   必须能从同一份数据算回来（分母是 ``total_books``）；
3. ⚠️ **回归钉死一条真缺陷**：``unparsable`` 原先是读 ``b["unparsable"]`` 统计的，
   而**书目字典根本没有这个键**（``library._scan_once`` 只下发 ``issues`` 列表）
   ⇒ 该计数恒为 0。现在三项文件侧计数一律读 ``issues``，与「缺失资源」页 / 库分面同源。
4. **体积榜**按 ``size`` 降序、字段为 ``id/title/size_bytes/format``，固定最多 50 条
   且**不受 ``top`` 影响**（``top`` 管的是作者/系列/出版社/题材四个计数器榜）。
"""
from __future__ import annotations

import pathlib

import pytest

from novelforge.core import epub_builder, fileops, library, metascore, stats

#: 元数据拉满（封面写不进 OPF，那 12 分拿不到）→ 得分 = 14+14+6+7+6+12+8+10+4+3 = 88，
#: 稳稳过 METADATA_OK(70)。
#: ⚠️ 页数那 4 分**拿得到**：EPUB 扫描会给估算页数（``pages_source=estimate``），
#: 故满分是 88 不是 84 —— 此处为第 33 期实测订正，原注释按「页数也拿不到」写、已过期。
_FULL_META = {
    "publisher": "江苏凤凰文艺",
    "date": "2012",
    "description": "一部关于银河帝国衰亡的短篇集。",
    "tags": ["科幻", "短篇"],
    "isbn": "9787539941123",
    "series": "银河帝国",
    "series_index": "1",
}


def _epub(root, name: str, *, title: str = "书", author: str = "作者",
          language: str = "zh", meta: dict | None = None) -> pathlib.Path:
    """真 EPUB（**能解析**，故不计入 unparsable）。``meta`` 里的是额外写进 OPF 的字段。"""
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub(
        {"title": title, "author": author, "language": language},
        [{"title": "第一章", "body_html": "<p>正文</p>"}],
        str(path),
    )
    if meta:
        assert fileops.patch_epub_meta(path, meta), f"OPF 改写失败：{name}"
    return path


def _scan(root) -> None:
    library.invalidate()


@pytest.fixture
def mixed(default_root):  # noqa: ARG001 —— 依赖 isolated 切目录
    """三本书，把体检的三个口径各顶到不同值：

    | 文件 | 大小 | issues | 元数据分 |
    | --- | --- | --- | --- |
    | ``满配.epub`` | >0 | 无 | 88（≥70，达标） |
    | ``薄.epub``   | >0 | 无 | 32（<70，不达标） |
    | ``坏.epub``   | >0 | unparsable | 28（只有书名 / 作者两项命中） |
    | ``空.epub``   | 0  | zero-bytes + unparsable | 28（同上） |

    四个分数是第 33 期实测值；四个分位（28 / 30 / 46 / 71.2）由它们线性插值而来，
    见 ``test_分位数增补p25与p75且既有两键不动``。
    """
    _epub(default_root, "满配.epub", title="满配", meta=_FULL_META)
    _epub(default_root, "薄.epub", title="薄", language="")   # 只差语言与出版信息
    (pathlib.Path(default_root) / "坏.epub").write_bytes(b"EPUB")
    (pathlib.Path(default_root) / "空.epub").write_bytes(b"")
    _scan(default_root)
    return default_root


# ---------------------------------------------------------------------------
# ① 向后兼容：原有 5 个计数键一个都不能少
# ---------------------------------------------------------------------------

def test_体检保留原有计数键_百分比是增补(mixed):  # noqa: ARG001
    g = stats.overview()["integrity"]

    for k in ("missing_author", "missing_language", "no_cover", "zero_size", "unparsable"):
        assert k in g, f"原有计数键丢了：{k}"
    # 增补的百分比口径
    for k in ("total_books", "present", "present_percent", "primary", "primary_percent",
              "metadata", "metadata_percent", "score"):
        assert k in g, f"增补键缺失：{k}"


def test_体检计数读的是issues而不是书目上不存在的键(mixed):  # noqa: ARG001
    """⚠️ 回归：``unparsable`` 曾读 ``b["unparsable"]`` —— 书目字典里**没有**这个键，
    该计数因此恒为 0（统计页永远显示「解析失败 0」）。

    现在读 ``issues``，与「缺失资源」页同源；坏包与空文件都该被数出来。
    """
    g = stats.overview()["integrity"]

    assert g["unparsable"] == 2, "坏包 + 空文件都该计入解析失败"
    assert g["zero_size"] == 1
    # 与缺失资源页用的是同一份数据（issues 列表）
    from_issues = [
        b for b in library.books()
        if "unparsable" in (b.get("issues") or [])
    ]
    assert len(from_issues) == g["unparsable"]


# ---------------------------------------------------------------------------
# ② 百分比口径自洽
# ---------------------------------------------------------------------------

def test_百分比口径自洽且可指回计数(mixed):  # noqa: ARG001
    ov = stats.overview()
    g = ov["integrity"]
    total = ov["books"]["total"]
    assert total == 4 and g["total_books"] == total

    # Present = 文件有实体内容（非 0 字节）；Primary = 主文件能被解析
    assert g["present"] == total - g["zero_size"] == 3
    assert g["primary"] == total - g["unparsable"] == 2

    for cnt_key, pct_key in (("present", "present_percent"),
                             ("primary", "primary_percent"),
                             ("metadata", "metadata_percent")):
        assert g[pct_key] == round(g[cnt_key] / total * 100, 1), f"{pct_key} 与计数对不上"

    # 综合分是三覆盖率的算术平均（不发明权重）
    assert g["score"] == round(
        (g["present_percent"] + g["primary_percent"] + g["metadata_percent"]) / 3, 1
    )


def test_综合分不虚高_坏文件一定拉低它(mixed):  # noqa: ARG001
    """兜底语义：有人只看 score 的话，它不能对坏文件视而不见。"""
    g = stats.overview()["integrity"]
    assert 0 < g["score"] < 100


# ---------------------------------------------------------------------------
# ③ 元数据覆盖率：阈值就是已公示的分档边界
# ---------------------------------------------------------------------------

def test_元数据达标的阈值就是分档边界70(mixed):  # noqa: ARG001
    """阈值刻意钉死在 70 —— 它就是 ``metascore`` 直方图里「70–89 良好」的下边界。

    另立一个数会让「体检说达标」与「完整度分布说良好」两处对不上。
    """
    assert metascore.METADATA_OK == 70.0

    g = stats.overview()["integrity"]
    bs = library.books()
    # 满配 88 达标；薄 32 不达标；坏 / 空 28 也不达标
    assert g["metadata"] == 1
    # 与逐书评分独立算一遍的结果一致
    assert g["metadata"] == sum(1 for b in bs if metascore.audit(b)["score"] >= 70.0)


def test_分位数增补p25与p75且既有两键不动(mixed):  # noqa: ARG001
    """第 33 期给 ``metadata_score`` 增补 P25 / P75 —— 分数分布图的阴影带两端。

    ``mixed`` 四本的分是 28 / 28 / 32 / 88（见夹具说明），线性插值下四个分位都能手算：
    P25 = 28、P50 = 30、P75 = 32+56×0.25 = 46、P90 = 32+56×0.7 = 71.2。
    既有的 p50 / p90 必须**原地不动**（既有图表与测试都读它们），增补只加键、不改值 ——
    故这里把四个键**一起**断言：改坏了哪一个都会红。
    """
    ms = stats.overview()["metadata_score"]

    assert (ms["p25"], ms["p50"], ms["p75"], ms["p90"]) == (28.0, 30.0, 46.0, 71.2)
    assert ms["p25"] <= ms["p50"] <= ms["p75"] <= ms["p90"], "分位必须单调"
    # 与逐书评分独立算一遍的结果一致（不是另起一套分位算法）
    scores = [metascore.audit(b)["score"] for b in library.books()]
    for k, p in (("p25", 25), ("p50", 50), ("p75", 75), ("p90", 90)):
        assert ms[k] == metascore.percentile(scores, p)


def test_metadata_score与体检用同一遍评分(mixed):  # noqa: ARG001
    """两处都从同一份 scores 出，不该出现「直方图说 1 本 90+、体检测到 0 本达标」。"""
    ov = stats.overview()
    gte90 = next(b for b in ov["metadata_score"]["buckets"] if b["key"] == "gte90")
    assert gte90["count"] == 0                       # 满分只有 88（封面写不进 OPF）
    assert ov["metadata_score"]["total"] == ov["books"]["total"]


# ---------------------------------------------------------------------------
# ④ 体积榜（Top 50 Largest Books）
# ---------------------------------------------------------------------------

def test_体积榜按大小降序且字段齐全(mixed):  # noqa: ARG001
    largest = stats.overview()["largest"]

    assert len(largest) == 4, "0 字节书是真实信号，不该被排除"
    sizes = [x["size_bytes"] for x in largest]
    assert sizes == sorted(sizes, reverse=True)
    for x in largest:
        assert set(x) == {"id", "title", "size_bytes", "format"}, x
        assert x["format"] == "EPUB"
        assert x["id"] and x["title"]


def test_空文件排在体积榜末位且大小为零(mixed):  # noqa: ARG001
    largest = stats.overview()["largest"]
    assert largest[-1]["size_bytes"] == 0
    assert largest[-1]["title"] == "空"


def test_体积榜不随top参数伸缩(default_root):  # noqa: ARG001
    """``top`` 管的是作者/系列/出版社/题材四个计数器榜，体积榜固定最多 50 条。

    混用会让统计页一加载就把四个计数器榜一起撑到 50 行。
    """
    # 要三个**不同**作者才验证得了 top 的伸缩（假文件解析不出作者，会全落进「未知」一格）
    for i, name in enumerate(("甲", "乙", "丙")):
        _epub(default_root, f"{name}.epub", title=name, author=f"作者{i}")
    _scan(default_root)

    narrow = stats.overview(top=1)
    wide = stats.overview(top=50)

    assert len(narrow["authors"]["top"]) == 1 and len(wide["authors"]["top"]) == 3
    assert len(narrow["largest"]) == len(wide["largest"]) == 3


def test_体积榜上限50条(default_root, make_book):  # noqa: ARG001
    for i in range(55):
        make_book(default_root, f"b{i:02d}.epub", b"x" * (i + 1))
    _scan(default_root)

    largest = stats.overview()["largest"]
    assert len(largest) == 50
    # 砍掉的是最小的那几本，榜首仍是最大的
    assert largest[0]["size_bytes"] == 55


def test_空库不炸(isolated):  # noqa: ARG001
    """体检与体积榜在空库上都得给得体结果（统计是展示型接口，不 400）。"""
    ov = stats.overview()

    assert ov["books"]["total"] == 0
    assert ov["largest"] == []
    g = ov["integrity"]
    assert (g["present_percent"], g["primary_percent"], g["metadata_percent"]) == (0.0, 0.0, 0.0)
    assert g["score"] == 0.0


# ---------------------------------------------------------------------------
# ⑤ 接口层：新字段上线，旧字段不丢
# ---------------------------------------------------------------------------

def test_接口_stats下发体检百分比与体积榜(client, auth_headers, mixed):  # noqa: ARG001
    r = client.get("/api/stats?top=50", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    g = body["integrity"]
    assert g["unparsable"] == 2 and g["zero_size"] == 1
    assert g["present_percent"] == 75.0 and g["primary_percent"] == 50.0
    assert g["metadata"] == 1
    assert body["largest"] and body["largest"][0]["size_bytes"] > 0


def test_接口_stats的top仍按原口径工作(client, auth_headers, mixed):  # noqa: ARG001
    """top 的既有语义（计数器榜长度）不能被本期改动牵动。"""
    r = client.get("/api/stats?top=1", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert len(r.json()["authors"]["top"]) == 1
    # 体积榜仍是最多 50 条的独立榜
    assert len(r.json()["largest"]) == 4
