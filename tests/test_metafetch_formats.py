"""元数据抓取不再按格式分流（第 21 期）。

钉住三点：

1. **非 EPUB 不再被跳过**：漫画（CBZ）与有声书（**目录**型条目）都能进 `plan()` 拿到候选；
2. **`apply()` 也不再限 EPUB**：只保留「确实在该书所属库根下」这道安全边界 —— 有声书是目录，
   用 `is_file()` 会直接判「文件不存在」；结果本来只写 DB，与文件类型无关；
3. **手动编辑仍限 EPUB**（另一条路径：非 EPUB 没有 OPF 兜底原值层），本期不动。

⚠️ 全程离线：`metasources` 的两个检索入口与封面下载都被替换掉，**绝不外呼**。
"""
import pathlib

import pytest

from novelforge.core import library, metafetch, metasources

CANDIDATE = {
    "source": "fake", "title": "抓来的书名", "author": "抓来的作者",
    "publisher": "抓来的出版社", "year": "", "language": "", "isbn": "",
    "description": "", "tags": [], "cover_url": "", "raw_id": "x", "score": 0.95,
}


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """把在线检索与封面下载全部换成本地常量 —— 本文件绝不外呼。"""
    monkeypatch.setattr(metasources, "search_by_isbn", lambda *a, **k: None)
    monkeypatch.setattr(
        metasources, "search_all",
        lambda *a, **k: {"entries": [dict(CANDIDATE)], "sources": {}, "best": dict(CANDIDATE)},
    )
    monkeypatch.setattr(metafetch, "_download_cover", lambda url: (b"JPG", "image/jpeg"))


def _cbz(root, name: str) -> pathlib.Path:
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"PK")               # 内容无关紧要：扫描只按扩展名收书
    return p


def _audio_dir(root, name: str) -> pathlib.Path:
    """有声书是**目录**型条目（一章一文件）—— 这正是 apply 里 is_file() 会误判的地方。"""
    d = pathlib.Path(root) / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "01.mp3").write_bytes(b"MP3")
    return d


def _plan_items():
    # 显式给一份开启抓取的配置：不依赖部署时的默认值
    plan = metafetch.plan(cfg={"metadata_fetch": {"enabled": True, "threshold": 0.1,
                                                  "fields": {}, "sources": ["fake"]}})
    return {i["name"]: i for i in plan["items"]}


def test_漫画不再被跳过(isolated, default_root):  # noqa: ARG001
    _cbz(default_root, "漫画一本.cbz")
    library.invalidate()

    it = _plan_items()["漫画一本.cbz"]
    assert it["skipped"] == "", it
    assert it["best_score"] > 0
    assert it["auto_ok"] is True           # 0.95 ≥ 0.1
    assert "publisher" in it["changes"]    # 候选里的出版社进了建议值


def test_有声书目录不再被跳过(isolated, default_root):  # noqa: ARG001
    _audio_dir(default_root, "有声书一本")
    library.invalidate()

    it = _plan_items()["有声书一本"]
    assert it["skipped"] == "", it
    assert it["best_score"] > 0


def test_apply_非EPUB也能写入(isolated, default_root):  # noqa: ARG001
    """漫画与**有声书目录**都能落库（此前 `.epub` 后缀与 `is_file()` 两道闸门都会拦）。"""
    _cbz(default_root, "漫画一本.cbz")
    _audio_dir(default_root, "有声书一本")
    library.invalidate()

    res = metafetch.apply([
        {"name": "漫画一本.cbz", "library_id": "default",
         "fields": {"publisher": "抓来的出版社"}},
        {"name": "有声书一本", "library_id": "default",
         "fields": {"language": "zh"}},
    ])
    assert res["count"] == 2, res

    books = {b["name"]: b for b in library.books()}
    assert books["漫画一本.cbz"]["publisher"] == "抓来的出版社"
    assert books["有声书一本"]["language"] == "zh"


def test_apply_越界名仍被拦(isolated, default_root):  # noqa: ARG001
    """放开格式不等于放开边界：名字里带路径仍必须被 `safe_path` 拦下。"""
    res = metafetch.apply([{"name": "../evil.cbz", "library_id": "default",
                            "fields": {"publisher": "x"}}])
    assert res["count"] == 0
    assert res["failed"], res


def test_全局关闭抓取时不下发候选(isolated, default_root):  # noqa: ARG001
    """回归：删掉「按格式跳过」之后，**按开关跳过**这条必须还在（全局关闭时整体不下发）。"""
    _cbz(default_root, "漫画一本.cbz")
    library.invalidate()

    plan = metafetch.plan(cfg={"metadata_fetch": {"enabled": False, "threshold": 0.1,
                                                  "fields": {}, "sources": ["fake"]}})
    assert plan["enabled"] is False
    assert plan["items"] == []
