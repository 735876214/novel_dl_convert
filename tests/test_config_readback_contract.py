"""配置「写得进去、读得回来、真的有人读」契约（第 102 期）。

背景：本仓设置页的一个配置项要同时落在**四个**地方 ——

1. 默认值 `config.DEFAULTS[...]`（没有它，键在界面上是空的、`load_config` 也不认）；
2. 可写白名单 `server.EDITABLE[...]`（不在里面 ⇒ 前端发了也被 `_sanitize_config` 丢掉）；
3. 界面控件（没有控件 ⇒ 用户根本改不到）；
4. **真实读点**（没有任何代码读它 ⇒ 改完什么都不会发生）。

`server.py` 里那段注释把第 2 点写得很清楚：「新增可写配置项时两处都要加，否则能写进
settings.json 但读不回来」。历史上漏过不止一次，所以这里对第 102 期新增的两个键
（`metadata_fetch.cache_ttl` / `metadata_fetch.detail_fetch`）逐点钉住。

⚠️ 静态断言只能证明**名字**写对了，证明不了链路通 —— 所以后面几条走真的
`PUT /api/config` → `GET /api/config` 往返，并用 `config.load_config()`
（引擎真正读的那条路）复验一次。

⚠️ 写配置的用例必须把 `config.SETTINGS_FILE` 指到本用例专属文件：否则这条用例会把键
留在会话级 settings.json 里，后面的用例读到的就是它（`tests/test_network_limits.py:355`
踩过这个坑，污染别的用例最难查）。
"""

import pathlib
import re

import pytest

from novelforge import config
from novelforge.core import metafetch, metasources

ROOT = pathlib.Path(__file__).resolve().parents[1]

# 第 102 期新增的两个键；下面多条用例按它参数化，免得漏掉一个
NEW_KEYS = ("cache_ttl", "detail_fetch")


# ---------------- 四个同步点（静态） ----------------

def test_默认值里有这两个键():
    mf = config.DEFAULTS["metadata_fetch"]
    assert mf["cache_ttl"] is None, \
        "缓存有效期默认必须是 None（= 按各来源自己声明的值），写死 600 会让各来源的声明变成死配置"
    assert mf["detail_fetch"] is False, \
        "按 ID 取详情默认必须关：多数书抓过一遍就带上了记录标识，默认开会改掉既有书的抓取结果"


def test_可写白名单与默认值同步():
    """漏进 `EDITABLE` ⇒ 前端发了被静默丢掉；多出 `DEFAULTS` 没有的键 ⇒ 写进 settings.json 也没人认。"""
    from novelforge import server

    editable = set(server.EDITABLE["metadata_fetch"])
    assert set(NEW_KEYS) <= editable, "这两个键必须可写，否则界面上点了没用"
    assert editable <= set(config.DEFAULTS["metadata_fetch"]), \
        f"EDITABLE 里有默认值没有的键（大概是拼错了）：{sorted(editable - set(config.DEFAULTS['metadata_fetch']))}"


def test_设置页有对应控件():
    """第 3 个同步点：白名单有了、界面没控件 ⇒ 用户改不到（与假配置是同一种病）。

    直接读前端页面源码比对 —— 靠人眼核对这两处，本仓历史上漏过不止一次
    （见 `tests/test_network_limits.py:327` 的同一做法）。
    """
    vue = (ROOT / "frontend" / "src" / "views" / "settings" / "pages"
           / "MetadataPage.vue").read_text(encoding="utf-8")
    for key in NEW_KEYS:
        assert f"metadata_fetch.{key}" in vue, f"设置页缺 metadata_fetch.{key} 的控件"
    # 「留空 = 按来源默认」与「0 = 关闭缓存」是两个语义，输入框必须能把它们分开：
    # 值绑到 `mf.cache_ttl ?? ''`（空值渲染成空串），清空后走 ttlInput 回 **null**。
    assert "mf.cache_ttl ?? ''" in vue, "缓存输入框必须把「未设置」渲染成空串，否则用户没法恢复默认"
    assert "ttlInput($event)" in vue, "清空输入框必须回 null（回落默认），不能回落到 0（那是关缓存）"


def test_每个键都有真实读点():
    """假配置的直接判据：引擎里搜不到这个键 ⇒ 改完什么都不发生。"""
    ms = (ROOT / "novelforge" / "core" / "metasources.py").read_text(encoding="utf-8")
    assert '.get("cache_ttl")' in ms, "cache_ttl 在 metasources 里没有读点"
    mf = (ROOT / "novelforge" / "core" / "metafetch.py").read_text(encoding="utf-8")
    assert 'get("detail_fetch")' in mf, "detail_fetch 在 metafetch 里没有读点"


def test_环境变量名是常量而不是散落的字面量():
    """测试要按名字设环境变量、文档要按名字写 —— 散写字面量迟早两边走样。"""
    src = (ROOT / "novelforge" / "config.py").read_text(encoding="utf-8")
    assert '_ENV_CACHE_TTL = "NOVELFORGE_METADATA_CACHE_TTL"' in src
    assert '_ENV_DETAIL_FETCH = "NOVELFORGE_METADATA_DETAIL_FETCH"' in src
    # 兜底块必须真的用上这两个常量（定义了不用 = 环境变量永远不生效）
    assert src.count("os.getenv(_ENV_CACHE_TTL)") == 1
    assert src.count("os.getenv(_ENV_DETAIL_FETCH)") == 1


# ---------------- 往返（PUT → GET → load_config） ----------------

def test_回写后读得回来且兄弟键没被动过(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")

    r = client.put("/api/config", headers=auth_headers,
                   json={"metadata_fetch": {"cache_ttl": 120, "detail_fetch": True}})
    assert r.status_code == 200, r.text

    after = client.get("/api/config", headers=auth_headers).json()["config"]["metadata_fetch"]
    assert after["cache_ttl"] == 120, "写进去读不回来就是假配置"
    assert after["detail_fetch"] is True
    assert after["limit"] == config.DEFAULTS["metadata_fetch"]["limit"], "只改这两个键不该动别的"

    # 引擎真正读的那条路也要认（界面回读走的是同一份 config，但两处口径必须一致）
    live = config.load_config()["metadata_fetch"]
    assert live["cache_ttl"] == 120 and live["detail_fetch"] is True


def test_留空等于按来源默认而不是关闭缓存(client, auth_headers, monkeypatch, tmp_path):
    """⚠️ 本用例钉的是最容易写错的一处：`None`（留空）与 `0`（关闭）是**两件事**。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.delenv(config._ENV_CACHE_TTL, raising=False)

    r = client.put("/api/config", headers=auth_headers,
                   json={"metadata_fetch": {"cache_ttl": ""}})
    assert r.status_code == 200, r.text
    after = client.get("/api/config", headers=auth_headers).json()["config"]["metadata_fetch"]
    assert after["cache_ttl"] is None, "空串必须存成 None（回落各来源声明），不是 0"
    # 各来源声明的值真的被用上了（不是「配置为 None 于是缓存整个关掉」）
    assert metasources._ttl_of("openlibrary") == metasources.SOURCES["openlibrary"]["cache_ttl"] > 0


def test_零是关闭缓存(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")

    r = client.put("/api/config", headers=auth_headers,
                   json={"metadata_fetch": {"cache_ttl": 0}})
    assert r.status_code == 200, r.text
    assert metasources._ttl_of("openlibrary") == 0, "0 必须真的把缓存关掉（TTL 0 = 立即过期）"


@pytest.mark.parametrize("bad", [-1, "很久", 99999999])
def test_接口拒绝负数非数字与过长(bad, client, auth_headers, monkeypatch, tmp_path):
    """静默回落到「按来源默认」比报错更糟：用户改完没反应，还会以为是自己记错了。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")

    r = client.put("/api/config", headers=auth_headers,
                   json={"metadata_fetch": {"cache_ttl": bad}})
    assert r.status_code == 400, f"{bad!r} 应当被拒绝"
    assert "缓存有效期" in r.json()["detail"]


def test_被拒的值不会被写进配置(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")

    client.put("/api/config", headers=auth_headers,
               json={"metadata_fetch": {"cache_ttl": 120}})
    client.put("/api/config", headers=auth_headers,
               json={"metadata_fetch": {"cache_ttl": -5}})
    assert config.load_config()["metadata_fetch"]["cache_ttl"] == 120, \
        "被拒绝的请求不能留下任何痕迹（一半写进去最麻烦）"


# ---------------- 环境变量：只兜底，不覆盖 ----------------

def test_环境变量只在没人写过时兜底(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "true")

    cfg = config.load_config()["metadata_fetch"]
    assert cfg["cache_ttl"] == 120 and cfg["detail_fetch"] is True, \
        "没人写过时环境变量必须生效（容器部署只给环境变量的场景）"

    # 人写过之后就得以人写的为准：否则「在界面上改了、保存后没变」无法解释
    config.save_overrides({"metadata_fetch": {"cache_ttl": 30, "detail_fetch": False}})
    cfg2 = config.load_config()["metadata_fetch"]
    assert cfg2["cache_ttl"] == 30, "环境变量不能盖掉用户自己写的值"
    assert cfg2["detail_fetch"] is False


def test_环境变量填错时忽略而不是让服务起不来(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "十分钟")

    assert config.load_config()["metadata_fetch"]["cache_ttl"] is None


# ---------------- 开关真的接进了抓取链路 ----------------

def _stub_detail(record: list):
    """替身：`metasources.detail`（记录调用，回一条真形状的候选）。"""
    def fn(source, provider_id, opts=None):
        record.append((source, provider_id))
        return {"ok": True, "error": "",
                "entry": metasources._entry(source, title="Dune", author="Frank Herbert",
                                            provider_id=provider_id)}
    return fn


def _enable(monkeypatch, tmp_path, enabled: bool) -> None:
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"metadata_fetch": {"enabled": True, "detail_fetch": enabled}})


BOOK = {"id": "b1", "title": "Dune", "author": "Frank Herbert", "language": "en",
        "openlibrary_id": "/works/OL1W"}


def test_开关关着时不会走精确键(monkeypatch, tmp_path):
    """默认关的开关**必须真的什么都不做** —— 否则「默认关」只是句空话。"""
    _enable(monkeypatch, tmp_path, False)
    calls: list = []
    monkeypatch.setattr(metasources, "detail", _stub_detail(calls))
    fallback = metasources._entry("googlebooks", title="Dune", author="Frank Herbert",
                                  provider_id="gb1")
    monkeypatch.setattr(metasources, "search_all",
                        lambda *a, **k: {"entries": [fallback], "sources": {}, "best": fallback})

    got = metafetch.online_candidate(dict(BOOK), cfg=config.load_config())
    assert calls == [], "开关关着还去问详情通道，就是偷偷改了用户没开的行为"
    assert got and got["source"] == "googlebooks", "关着时必须走原来的按书名检索"


def test_开关打开后按精确键回查(monkeypatch, tmp_path):
    _enable(monkeypatch, tmp_path, True)
    calls: list = []
    monkeypatch.setattr(metasources, "detail", _stub_detail(calls))
    monkeypatch.setattr(metasources, "search_all",
                        lambda *a, **k: pytest.fail("有记录标识时不该退回按书名猜"))

    got = metafetch.online_candidate(dict(BOOK), cfg=config.load_config())
    assert calls == [("openlibrary", "/works/OL1W")], "必须拿库里记的那个标识原样回查"
    assert got and got["source"] == "openlibrary"
    assert got["values"]["title"] == "Dune"
    assert got["values"]["openlibrary_id"] == "/works/OL1W", "回查到的标识要照旧落回字段"
    assert got["score"] == 1.0, \
        "精确回查的分数必须是 1.0：照抄 _entry 的 0.0 会让它被 threshold 挡在门外（功能开了却不生效）"


def test_不传配置时它什么都查不到是既有语义():
    """⚠️ 记录一个**既有陷阱**（不是本期引入的）：`_cfg(cfg)` 只从**传入的** dict 里取
    `metadata_fetch`，所以 `online_candidate(book)`（不传 `cfg`）会静默返回 `None` ——
    看起来像「这家源没结果」，实际是「压根没去查」。仓内所有调用方都传了
    （`server.py:3073` 传 `cfg=config.load_config()`），这里把现状钉住：**别指望默认值**。
    """
    assert metafetch._cfg(None) == {}
    assert metafetch.online_candidate({"title": "Dune"}) is None


def test_没有标识的书不受开关影响(monkeypatch):
    """`_detail_first` 直接单测：没有标识 / 该家没有详情通道 ⇒ 回空表，一次都不外呼。"""
    calls: list = []
    monkeypatch.setattr(metasources, "detail", _stub_detail(calls))

    assert metafetch._detail_first({"openlibrary_id": ""}, ["openlibrary"], {}) == []
    assert metafetch._detail_first({}, ["openlibrary"], {}) == []
    # googlebooks 有 id_field 但**没有**详情通道 ⇒ 也该跳过（不为了凑数硬走）
    assert "googlebooks" not in metasources.DETAIL_SOURCES
    assert metafetch._detail_first({"googlebooks_id": "gb1"}, ["googlebooks"], {}) == []
    assert calls == [], "没有可用标识就不该外呼"


def test_详情通道表与注册表声明一致():
    """`DETAIL_SOURCES` 是 `metafetch` 用的那张；它必须与各家的 `detail_name` 一致。"""
    from novelforge.core.sources import registry as src_registry

    declared = {p.id for p in src_registry.DECLARED if p.detail_name}
    assert set(metasources.DETAIL_SOURCES) == declared
    assert set(metasources.DETAIL_SOURCES) <= set(metasources.SOURCES)
