"""第 86 期：三类产物的**分流判据**（零网络）。

要钉住的是「书源自报产物类型，系统照它分流」这条口径，以及三个容易翻车的细节：

1. 判据在**规则里**（`book.mode`），不是让用户选、也不是靠猜；认不出来按 `text`（既有行为不变）；
2. 音频产物是**目录**，但判库要拿一个**带音频扩展名的代表文件名** —— 传目录名会让
   「只收音频的库」认不出来，那本书只能报「没有可接收的书库」；
3. `mark_recent` 只在**文本**链路里调：漫画/音频不产 txt，无条件调会把同一时间窗里
   别人的 txt 一起盖掉（监听线程于是漏掉真该处理的文件）。
"""
import asyncio
import inspect

import pytest

from novelforge import server
from novelforge.sources import store


def _rule(name: str, mode: str) -> dict:
    return {
        "name": name, "display_name": name, "domains": [f"{name}.com"], "public": False,
        "search": {"url": f"https://{name}.com/s?q={{title}}", "mode": "css", "container": ".i",
                   "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": mode, "content": {"mode": "css", "container": "#c"}},
    }


class _StubMgr:
    def __init__(self):
        self.calls: list = []

    async def download_to(self, item, root, input_dir, opts):
        self.calls.append(("text", str(root)))
        return f"{root}/文本.epub"

    async def download_comic(self, item, root, opts=None):
        self.calls.append(("comic", str(root)))
        return f"{root}/漫画.cbz"

    async def download_audio(self, item, root, opts=None):
        self.calls.append(("audio", str(root)))
        return f"{root}/有声书"


# ---------------- 判据 ----------------

def test_产物类型来自规则(isolated):                                    # noqa: ARG001
    store.add_rule(_rule("kind-comic", "comic"))
    store.add_rule(_rule("kind-audio", "audio"))
    store.add_rule(_rule("kind-toc", "toc"))
    assert server._product_kind("kind-comic") == "comic"
    assert server._product_kind("kind-audio") == "audio"
    assert server._product_kind("kind-toc") == "text", "toc 是文本链路（目录式分章）"
    # 内置适配器在磁盘上没有规则文件 ⇒ 按 text（既有行为一字不变）
    assert server._product_kind("gutenberg") == "text"
    assert server._product_kind("") == "text"
    assert server._product_kind("根本没有这个源") == "text"


def test_判库用的代表文件名要有正确的扩展名():
    assert server._KIND_PROBE_NAME["text"] == "{t}.epub"
    assert server._KIND_PROBE_NAME["comic"] == "{t}.cbz"
    name = server._KIND_PROBE_NAME["audio"].format(t="某书")
    assert name.endswith(".mp3"), \
        "音频产物是目录，但判库必须看到音频扩展名，否则只收音频的库认不出它"


# ---------------- 分流 ----------------

def test_按类型分流到对应下载器(tmp_path):
    mgr = _StubMgr()
    item = {"title": "某书", "url": "https://x.com/1"}
    for kind, want in (("text", "text"), ("comic", "comic"), ("audio", "audio")):
        asyncio.run(server._dispatch_product(mgr, kind, item, tmp_path, {}))
        assert mgr.calls[-1][0] == want
    # 认不出来的类型按文本走（绝不静默什么都不做）
    asyncio.run(server._dispatch_product(mgr, "???", item, tmp_path, {}))
    assert mgr.calls[-1][0] == "text"


def test_只有文本链路才标记txt已处理():
    """`mark_recent` 的调用必须挂在 `kind == "text"` 分支里（源码级断言，防回归）。"""
    src = inspect.getsource(server._run_download)
    assert 'kind == "text" and WATCHER is not None' in src
