"""第 86 期：下载产物的 sidecar 契约（**来源 + 最新章节**）。

产品承诺是「下载后就能看出这本书**来自哪个源、最新章节是哪一章**」。
`update()` 也会回写 `last_title`，但那是**下一次**抓取时的事 —— 中间这段时间 sidecar 里
如果没有它，界面与用户看到的就只有一句「不知道」。所以下载当时就得写下来。
"""
import json

from novelforge.sources.manager import DownloadManager


def _mgr() -> DownloadManager:
    return DownloadManager({"download": {"enabled": True}})


def test_sidecar带来源与最新章节(tmp_path):
    mgr = _mgr()
    txt = tmp_path / "book.txt"
    txt.write_text("x", encoding="utf-8")
    mgr.write_sidecar(txt, {"title": "示例书", "url": "https://x.com/1",
                            "formats": {"text/html": "https://x.com/1"},
                            "source": "gutenberg", "_source": "gutenberg"},
                      tmp_path, last_title="第十章 结局")
    meta = json.loads(txt.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert meta["source"] == "gutenberg" and meta["url"] == "https://x.com/1"
    assert meta["title"] == "示例书" and meta["output_dir"] == str(tmp_path)
    assert meta["last_title"] == "第十章 结局", "下载当时就要能看出最新章节"


def test_不知道最新章节就不写这个键(tmp_path):
    """不许编：拿不到末章标题时**不写** `last_title`，而不是塞一个空串或「未知」。"""
    mgr = _mgr()
    txt = tmp_path / "b2.txt"
    txt.write_text("x", encoding="utf-8")
    mgr.write_sidecar(txt, {"title": "另一本"}, tmp_path)
    meta = json.loads(txt.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert "last_title" not in meta
    assert meta["source"] == "", "拿不到来源时也不编一个出来（空串如实表达「不知道」）"
