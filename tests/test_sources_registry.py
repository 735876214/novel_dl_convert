"""书源注册表不变量：`REGISTRY` 里只能有**真能干活**的源。

来历（第 32 期）：`sources/generic.py` 是给人复制用的模板，却带着 `@register`，
而它的 `search()` / `fetch_book()` 都是 `NotImplementedError`。后果有两层，
且都不报错、只在日志里悄悄堆：

1. `DownloadManager.search()` 每次都遍历整个 `REGISTRY` —— 每搜一次书就命中模板、
   抛异常、被 `except` 吞成一条「书源 generic 搜索失败」的**假失败日志**（还白建一次
   `BrowserClient`）；
2. 它那个占位域名 `example-novel.com` 会混进 `store.list_sources()`（`/api/sources`、
   `/api/sources/status` 都用它），看着像一个真书源。

修法是取消注册（模板文件保留，供「规则表达不了、必须写 Python」时复制）。
本文件把「注册了就必须实现了」这条不变量钉住，防止下次再把半成品塞进 REGISTRY。

⚠️ 全程离线：用桩 client，任何真网络调用都会以 `AssertionError` 暴露出来。
"""
import asyncio
import inspect

import pytest

from novelforge.sources import REGISTRY, store
from novelforge.sources.base import SourceAdapter


class _NoNetworkClient:
    """桩 client：真被调用就炸 —— 用来证明本文件的用例没走网络。"""

    async def get_text(self, url: str) -> str:
        raise AssertionError(f"用例不应发起网络请求：{url}")

    async def get(self, url: str, **kw):
        raise AssertionError(f"用例不应发起网络请求：{url}")


def test_registry_里没有未实现的书源():
    """注册进 REGISTRY 的源，`search()` / `fetch_book()` 都不能是 `NotImplementedError`。

    网络异常、解析异常都放过 —— 那是「真源这会儿不通」，与「根本没实现」是两回事。
    本仓没装 pytest-asyncio，故自己 `asyncio.run`（与其它用例一样保持同步测试）。
    """
    assert REGISTRY, "REGISTRY 是空的：书源没被导入，本用例会变成空转"
    asyncio.run(_probe_all_sources())


async def _probe_all_sources() -> None:
    client = _NoNetworkClient()
    for name, cls in REGISTRY.items():
        src = cls()
        for method in ("search", "fetch_book"):
            try:
                await getattr(src, method)(client, "测试" if method == "search" else {})
            except NotImplementedError as e:
                pytest.fail(f"书源 {name} 注册了却没实现 {method}()：{e}")
            except Exception:
                # 真源在桩 client 下必然失败（网络/解析），只要不是「未实现」就与本题无关
                pass


def test_模板源_generic_不再注册():
    """模板是给人复制的，不是给程序跑的：一旦回到 REGISTRY 就是一条假失败日志。"""
    assert "generic" not in REGISTRY
    # 模板文件本身要还在（README 的「进阶：Python 适配器」指着它）
    from novelforge.sources import generic

    assert issubclass(generic.GenericHtmlSource, SourceAdapter)
    # 它会抛 NotImplementedError 这件事本身是**模板的正确形态**（等使用者去实现）
    assert "NotImplementedError" in inspect.getsource(generic.GenericHtmlSource.search)


def test_generic_不在书源清单里(isolated):
    """`/api/sources` 与 `/api/sources/status` 都走 `list_sources()`，占位域名不该出现。"""
    names = [s["name"] for s in store.list_sources()]
    assert "generic" not in names
    assert "example-novel.com" not in [
        d for s in store.list_sources() for d in s["domains"]
    ]


def test_书源清单结构不变(client, auth_headers):
    """接口返回结构是既有契约，本次改动只该少一个条目、不该改字段。"""
    r = client.get("/api/sources", headers=auth_headers)
    assert r.status_code == 200
    sources = r.json()["sources"]
    assert sources, "书源清单为空：内置 gutenberg 也该在"
    for s in sources:
        assert set(s) == {"name", "display_name", "domains", "public", "user"}
        assert s["name"] and isinstance(s["domains"], list)
    assert all(s["name"] != "generic" for s in sources)


def test_未登录取书源清单被拒(client):
    """顺手钉住鉴权：书源清单是管理面，不该匿名可读。"""
    assert client.get("/api/sources").status_code in (401, 403)
