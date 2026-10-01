"""第 71 期：下载闸门（`download.enabled` / `download.public_only`）**真的拦得住**。

起因是一条假开关：设置页写着「开放搜索 / 下载 —— 关闭时书源仅做规则管理，不可搜索下载」
（`frontend/src/data/settingsFields.ts`），而第 71 期之前那段判定只作用于**展示**
（`store.sources_status()` 算 `usable`、`manager._visible_sources()` 是一段无人调用的死代码、
CLI 里另写了一份）—— `/api/search`、`/api/download`、`/api/preview` 谁都不检查它。
于是关掉之后照搜照下，界面上那句承诺是假的。

本文件把四件事钉在一起：

1. 关掉下载 ⇒ 三个端点一律 400，且**原因里带出口**（不能只说「不行」）；
   ⚠️ 拒绝必须发生在**业务逻辑之前**：用例把 `DownloadManager.search/preview` 换成会
   直接失败的桩，被拒时它们一个都不许被调到；
2. **不进队列**：被闸门或「未知书源」挡下的下载不该先落一条注定失败的任务 ——
   用户要跑到任务中心才发现，等于一次白问（与第 38 期「0 库提前拦」同口径）；
3. `public_only` 为真 ⇒ 非公版源在**搜索里被跳过并注明原因**（而不是搜出来、点下载才拒），
   在下/预览时被拒；放行的源照常入队，且任务详情里的来源名不为空
   （第 71 期之前读的是不存在的键 ⇒ 任务中心「来源」一栏一直是空的）；
4. **试搜（`/api/sources/test`）刻意不受闸门限制**：它是管理面自检（第 57 期语义），
   一起拦掉的话，用户就再也没法确认自己写的规则还能不能用。

⚠️ 全程零网络：各书源换成本文件的桩，后台下载换成空操作。
"""
import pytest

from novelforge import config, server
from novelforge.core import db
from novelforge.sources import DownloadManager, REGISTRY, store
from novelforge.sources.base import SourceAdapter


class _StubSource(SourceAdapter):
    """假书源：抽象方法都实现，且**永不联网**。

    「闸门必须先于业务逻辑」这件事不靠这里断言，而由各用例显式替换
    `DownloadManager.search/preview` 为必失败的桩来钉（见本文件第一条用例）。
    """

    items: list = []

    async def search(self, client, title):  # noqa: ANN001
        return [dict(it) for it in self.items]

    async def fetch_book(self, client, item):  # pragma: no cover —— 本文件从不让它真取书
        raise AssertionError("闸门用例不该真的取书")


def _mk(name: str, display: str, public: bool, items=()) -> type:
    return type(
        f"Stub_{name}",
        (_StubSource,),
        {"name": name, "display_name": display, "public": public, "items": list(items)},
    )


@pytest.fixture
def stubs(monkeypatch):
    """本用例的 REGISTRY：**先把真源全摘掉**（内置 gutenberg 会真的联网），再塞两个桩。

    `monkeypatch` 的 delitem/setitem 会在用例结束后逐项还原 —— 不动全局书源表。
    """
    for name in list(REGISTRY):
        monkeypatch.delitem(REGISTRY, name)
    monkeypatch.setitem(REGISTRY, "stub-public", _mk(
        "stub-public", "公版桩源", True, [{"title": "三体", "author": "刘慈欣", "url": "https://e.com/1"}]))
    monkeypatch.setitem(REGISTRY, "stub-paid", _mk(
        "stub-paid", "非公版桩源", False, [{"title": "付费书", "author": "某人", "url": "https://e.com/2"}]))
    return {"public": "stub-public", "paid": "stub-paid"}


def _set_download(monkeypatch, tmp_path, *, enabled: bool, public_only: bool = True) -> None:
    """把 settings.json 覆盖层指到本用例的临时文件（不动真实配置、也不影响别的用例）。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"download": {"enabled": enabled, "public_only": public_only}})


async def _noop_run_download(tid: str, item: dict, actor: str = "系统",
                            kind: str = "text") -> None:
    """把后台下载换成空操作：本文件测的是**入口拦截**，不是下载本身。

    少了这一步，后台任务会在测试结束、库已关闭之后才动手（第 39 期那类
    「线程攥着旧连接查库」的随机失败）。

    ⚠️ 签名要**跟着 `server._run_download` 走**（第 86 期给它加了 `kind`：文本 / 漫画 / 音频
    三类产物分流）。这里刻意**写全参数**而不是 `*args`：哪天又加参数，这条桩会当场报错，
    而不是把新参数悄悄吞掉 —— 那正好是「测试还绿着、线上已经不对」的经典成因。
    """
    return None


def test_关掉下载时搜索被拒且给出出口(client, auth_headers, isolated, monkeypatch, tmp_path):  # noqa: ARG001
    """拒绝要发生在**搜索之前**，而且原因里得有出口 —— 只说「不行」等于把人堵在原地。"""
    _set_download(monkeypatch, tmp_path, enabled=False)

    async def _must_not_run(self, *a, **k):  # noqa: ANN001
        raise AssertionError("闸门已经拒了，却还是去搜索了")

    monkeypatch.setattr(DownloadManager, "search", _must_not_run)

    r = client.post("/api/search", headers=auth_headers, json={"title": "三体"})

    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "下载功能未开启" in detail, detail
    assert "网络与下载" in detail, f"要给出出口（设置 → 网络与下载）：{detail}"


def test_关掉下载时下载被拒且不进队列(client, auth_headers, isolated, monkeypatch, tmp_path):
    """一次注定失败的往返没必要发：任务表里不该多出一条「已入队」再后台失败的任务。"""
    _set_download(monkeypatch, tmp_path, enabled=False)
    monkeypatch.setattr(server, "_run_download", _noop_run_download)

    r = client.post("/api/download", headers=auth_headers,
                    json={"source": "stub-public", "title": "三体", "url": "https://e.com/1"})

    assert r.status_code == 400, r.text
    assert "下载功能未开启" in r.json()["detail"]
    assert db.task_list(100) == [], "被闸门挡下的下载不该留下任务"


def test_关掉下载时预览被拒(client, auth_headers, isolated, monkeypatch, tmp_path, stubs):  # noqa: ARG001
    """预览也是真的去外呼书源，不拦就是给这个闸门留了一扇窗。"""
    _set_download(monkeypatch, tmp_path, enabled=False)

    async def _must_not_run(self, item):  # noqa: ANN001
        raise AssertionError("闸门已经拒了，却还是去预览了")

    monkeypatch.setattr(DownloadManager, "preview", _must_not_run)

    r = client.get("/api/preview", headers=auth_headers,
                   params={"source": "stub-public", "url": "https://e.com/1"})

    assert r.status_code == 400, r.text
    assert "下载功能未开启" in r.json()["detail"]


def test_仅放行公版源时非公版源被跳过并注明原因(client, auth_headers, isolated, monkeypatch, tmp_path, stubs):
    """非公版源**在搜索阶段就如实标出来**。

    另一种做法（搜出来、等点下载时才拒）是一条「点了才报错」的死路 ——
    与本项目「不做假交互」的纪律冲突，所以这里把现行做法钉住。
    """
    _set_download(monkeypatch, tmp_path, enabled=True, public_only=True)

    r = client.post("/api/search", headers=auth_headers, json={"title": "三体"})

    assert r.status_code == 200, r.text
    body = r.json()
    rows = {s["name"]: s for s in body["sources"]}
    assert rows[stubs["public"]]["ok"] is True and rows[stubs["public"]]["count"] == 1
    assert rows[stubs["paid"]]["skipped"] is True
    assert "不是公版源" in rows[stubs["paid"]]["reason"], rows[stubs["paid"]]
    assert [it["title"] for it in body["results"]] == ["三体"], "被跳过源的结果不该出现"


def test_仅放行公版源时非公版源不能下载也不能预览(client, auth_headers, isolated, monkeypatch, tmp_path, stubs):
    _set_download(monkeypatch, tmp_path, enabled=True, public_only=True)
    monkeypatch.setattr(server, "_run_download", _noop_run_download)

    d = client.post("/api/download", headers=auth_headers,
                    json={"source": stubs["paid"], "title": "付费书", "url": "https://e.com/2"})
    p = client.get("/api/preview", headers=auth_headers,
                   params={"source": stubs["paid"], "url": "https://e.com/2"})

    assert d.status_code == 400 and "不是公版源" in d.json()["detail"], d.text
    assert p.status_code == 400 and "不是公版源" in p.json()["detail"], p.text
    assert db.task_list(100) == [], "被闸门挡下的下载不该留下任务"


def test_放行时下载照常入队且任务详情带源名(client, auth_headers, isolated, monkeypatch, tmp_path, stubs):
    """放行的路径也要钉：闸门不该拦错人，任务详情里的来源不能是空的。"""
    _set_download(monkeypatch, tmp_path, enabled=True, public_only=True)
    monkeypatch.setattr(server, "_run_download", _noop_run_download)

    r = client.post("/api/download", headers=auth_headers,
                    json={"source": stubs["public"], "title": "三体", "url": "https://e.com/1",
                          "format": "epub"})

    assert r.status_code == 200, r.text
    row = db.task_get(r.json()["task_id"])
    # 第 71 期之前这里读 `item["source"]`，而结果条目里只有 `_source` ⇒ 详情一直是空的
    assert row["detail"].startswith(stubs["public"]), row
    assert "epub" in row["detail"], row


def test_未知书源即时拒绝而不进队列(client, auth_headers, isolated, monkeypatch, tmp_path, stubs):  # noqa: ARG001
    """源名对不上就直接拒：先建任务再后台失败，用户得跑到任务中心才知道白等了。"""
    _set_download(monkeypatch, tmp_path, enabled=True, public_only=True)
    monkeypatch.setattr(server, "_run_download", _noop_run_download)

    r = client.post("/api/download", headers=auth_headers,
                    json={"source": "根本不存在的源", "title": "x", "url": "u"})

    assert r.status_code == 400, r.text
    assert "未知书源" in r.json()["detail"]
    assert db.task_list(100) == []


def test_试搜不受下载闸门限制(client, auth_headers, isolated, monkeypatch, tmp_path):  # noqa: ARG001
    """管理面自检豁免（第 57 期语义）：下载关着也要能验证「我写的规则还能不能用」。

    取舍的另一面也写清楚：试搜是**只读的一次性小请求**、规则不落盘、结果只给作者本人看，
    不构成「开放下载」。
    """
    _set_download(monkeypatch, tmp_path, enabled=False)

    async def _stub_test_source(self, cls, title):  # noqa: ANN001
        return [{"title": "三体", "author": "刘慈欣", "url": "https://e.com/1"}]

    monkeypatch.setattr(DownloadManager, "test_source", _stub_test_source)

    r = client.post("/api/sources/test", headers=auth_headers,
                    json={"name": "gutenberg", "query": "三体"})

    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True and r.json()["count"] == 1


def test_界面显示的原因与接口拒绝的原因是同一句(client, auth_headers, isolated, monkeypatch, tmp_path, stubs):  # noqa: ARG001
    """措辞只有一份（`gate_reason()`）——否则「书源管理页说 A、探索发现报 B」又会漂移。"""
    _set_download(monkeypatch, tmp_path, enabled=False)

    shown = {s["name"]: s for s in store.sources_status()}["stub-public"]
    assert shown["usable"] is False
    rejected = client.post("/api/search", headers=auth_headers, json={"title": "x"}).json()["detail"]

    assert rejected == shown["blocked_reason"], (rejected, shown["blocked_reason"])
