"""第 59 期：13 家元数据来源的**真联网体检**工具契约。

体检的价值不在「跑一遍」，而在**结论分类说得准**：

1. **不同故障必须分开**：「被限流（429）」要用户等一会或填 Key，「能连通但解析不到」
   基本只能等修复或换源 —— 把两者混成一个「不可用」，用户就只能瞎猜（`_classify_error`）；
2. **样本要按家给**：拿 "Dune" 去查 Aladin（韩）/ Lubimyczytac（波兰）/ RanobeDB（轻小说）
   本来就没结果，用统一样本会把好家误报成「无结果」—— 误报比不测更糟；
3. **缺密钥的家不发外呼**（与抓取口径一致）：拿一次注定失败的请求当「测试」是浪费往返；
4. **只读**：体检不改配置、不写库、不注册任何东西。

⚠️ 这些用例都**注入假 HTTP**（monkeypatch `metasources._get_json` / `_get_text`）——
真联网跑一遍是人工验收动作（本文件只保证逻辑正确，不保证站点今天可用）。
"""
import pytest

import novelforge.core.metasources as m


def _patch_raise(monkeypatch, message: str, calls: list = None):
    """所有出网口都抛同一条错误（用于快速验证分类与汇总，不碰公网）。"""
    def boom(*a, **k):
        if calls is not None:
            calls.append(a[0] if a else "")
        raise RuntimeError(message)
    monkeypatch.setattr(m, "_get_json", boom)
    monkeypatch.setattr(m, "_get_text", boom)


def test_体检样本覆盖全部来源():
    """漏一家的样本 ⇒ 它会用兜底样本 → 大概率「无结果」被误报成故障。"""
    assert set(m.HEALTH_SAMPLES) == set(m.SOURCES), set(m.SOURCES) ^ set(m.HEALTH_SAMPLES)
    for sid, (title, _author) in m.HEALTH_SAMPLES.items():
        assert title.strip(), f"{sid} 的样本书名不能为空"


@pytest.mark.parametrize("err,kind", [
    ("被限流（429）：稍后再试", "rate_limited"),
    ("被拒绝（403）：可能需要 API Key，或该地区/该站点不支持", "denied"),
    ("被拒绝（401）：可能需要 API Key", "denied"),
    ("被反爬拦截（验证码 / 机器人校验）：该来源需要降低频率", "blocked"),
    ("被反爬拦截（站点返回挑战页 HTTP 202）", "blocked"),
    ("被重定向（HTTP 302）：多半被反爬拦到验证页", "redirect"),
    ("接口返回错误（HTTP 400）", "http"),
    ("需要 API Key：请在「元数据来源」里填 Hardcover API Token", "missing_key"),
    ("需要 TTBKey：请在「元数据来源」里填 Aladin TTBKey", "missing_key"),
    # ⚠️ 第 104 期**故意改掉**这一行：`[Errno -2] Name or service not known` 是 EAI_NONAME，
    # 本来就是**解析失败**，此前归到「网络不可达」—— 而这两件事要用户做的事完全不同
    # （改本机 DNS vs 查网络）。分不开就是误报：用户会去修一个根本没坏的东西。
    ("连接失败：[Errno -2] Name or service not known", "dns"),
    ("域名解析失败：[Errno 11001] getaddrinfo failed（本机 DNS 解析不出该域名）", "dns"),
    # 污染是**交叉核对之后**才敢下的结论：本机解析与公共解析器完全不一致。
    ("连接超时：timed out；域名 openlibrary.org 在本机解析到 31.13.112.4，"
     "而公共解析器（8.8.8.8）给的是 199.59.149.201 —— 两者完全不一致 ⇒ "
     "多半是**本机 DNS 被污染**，不是站点故障", "dns_polluted"),
    ("连接失败：[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol",
     "tls"),
    ("连接失败：proxy connect failed", "proxy"),
    ("连接超时：timed out（TCP 都没建起来）", "connect_timeout"),
    ("连接失败：网络不可达", "network"),
    ("请求超时：timed out", "timeout"),
    ("Expecting value: line 1 column 1 (char 0)", "parse"),
    ("某些没见过的错误", "error"),
])
def test_故障分类要分得开(err, kind):
    """分类的意义是**告诉用户该做什么**：等一会 / 填 Key / 降频率 / 等修复，四件事不一样。"""
    assert m._classify_error(err) == kind


def test_缺密钥的家不发外呼(monkeypatch):
    calls: list = []
    _patch_raise(monkeypatch, "不该被调用", calls)

    out = m.health_one("hardcover", {})

    assert out["kind"] == "missing_key" and out["ok"] is False
    assert calls == [], "缺密钥不该发外呼（与抓取口径一致）"
    assert "密钥" in out["error"]


def test_有结果记为可用并带首条(monkeypatch):
    monkeypatch.setattr(m, "_get_json", lambda *a, **k: {"results": [
        {"trackName": "Dune", "artistName": "Frank Herbert", "artworkUrl100": "https://x/100x100bb.jpg"}]})

    out = m.health_one("itunes", {}, "Dune", "Frank Herbert")

    assert out["ok"] is True and out["kind"] == "ok" and out["count"] == 1
    assert out["first"] == "Dune · Frank Herbert", out
    assert out["fragile"] is False and out["group"]


def test_请求成功但零结果单列一类(monkeypatch):
    """抓取型（fragile）出故障的典型信号就是「请求成功、解析不到」—— 不能并进 ok。"""
    monkeypatch.setattr(m, "_get_text", lambda *a, **k: "")

    out = m.health_one("amazon", {}, "Dune", "")

    assert out["ok"] is False and out["kind"] == "empty"
    assert out["fragile"] is True
    assert "没解析到结果" in out["error"]


def test_一家失败不影响其它家(monkeypatch):
    def fake_json(url, params=None, headers=None, method="GET", data=None, hints=None):
        if "googleapis" in url:
            raise RuntimeError("被限流（429）：稍后再试")
        if "itunes" in url:
            return {"results": [{"trackName": "Dune", "artistName": "Frank Herbert"}]}
        raise RuntimeError("连接失败：网络不可达")

    monkeypatch.setattr(m, "_get_json", fake_json)
    monkeypatch.setattr(m, "_get_text", lambda *a, **k: "")

    out = m.health_check(sources=["googlebooks", "itunes", "openlibrary"])

    assert out["items"]["googlebooks"]["kind"] == "rate_limited"
    assert out["items"]["itunes"]["kind"] == "ok"
    assert out["items"]["openlibrary"]["kind"] == "network"
    assert out["summary"]["total"] == 3
    assert out["summary"]["usable"] == 1 and out["summary"]["problems"] == 2


def test_query_为空时按家给样本(monkeypatch):
    seen: list = []

    def fake_json(url, params=None, headers=None, method="GET", data=None, hints=None):
        seen.append(params or {})
        return {}

    monkeypatch.setattr(m, "_get_json", fake_json)
    monkeypatch.setattr(m, "_get_text", lambda *a, **k: "")

    m.health_check(sources=["itunes"])
    assert seen[-1].get("term") == "Dune Frank Herbert", seen

    # 显式给关键词 ⇒ 所有家都用它（不再按家换样本）
    seen.clear()
    m.health_check(sources=["itunes"], query="三体")
    assert seen[-1].get("term") == "三体", seen


def test_体检汇总与分类文案自洽(monkeypatch):
    _patch_raise(monkeypatch, "被限流（429）：稍后再试")

    out = m.health_check({})

    kinds = [i["kind"] for i in out["items"].values()]
    assert len(out["items"]) == len(m.SOURCES)
    # 三家需密钥的家不发外呼 ⇒ 记「未填密钥」，其余（公开接口与抓取型）都是限流
    assert kinds.count("missing_key") == 3, kinds
    assert kinds.count("rate_limited") == len(m.SOURCES) - 3, kinds
    assert out["summary"]["usable"] == 0
    assert out["summary"]["problems"] == len(m.SOURCES) - 3
    assert set(out["kind_labels"]) == set(m.HEALTH_KINDS)
    assert out["elapsed_ms"] >= 0 and out["ran_at"] > 0


def test_指定的源子集也能体检(monkeypatch):
    _patch_raise(monkeypatch, "被限流（429）")

    out = m.health_check({}, sources=["itunes", "openlibrary"])

    assert out["order"] == ["itunes", "openlibrary"]
    assert set(out["items"]) == {"itunes", "openlibrary"}


# ---------------- 网络归因（第 104 期）----------------

def _connect_timeout():
    import httpx
    return httpx.ConnectTimeout(
        "timed out", request=httpx.Request("GET", "https://openlibrary.org/search.json"))


def _patch_connect_timeout(monkeypatch):
    """所有出网口都抛同一条 `ConnectTimeout`（带 request ⇒ 归因知道打的是哪个主机）。"""
    def boom(*_a, **_k):
        raise _connect_timeout()

    monkeypatch.setattr(m, "_get_json", boom)
    monkeypatch.setattr(m, "_get_text", boom)


def test_检索失败附上结构化归因(monkeypatch):
    """`search` 的失败返回值多一个 `fail`：**纯函数**算出来的「哪一类、打的是哪个主机」。

    数据路径不为它多花任何往返（不做 DNS 核对），只是把异常里已有的信息带出去 ——
    诊断路径靠它决定要不要交叉核对。
    """
    import httpx

    def boom(*_a, **_k):
        raise httpx.ConnectError("x", request=httpx.Request("GET", "https://openlibrary.org/a"))

    monkeypatch.setitem(m._FETCHERS, "openlibrary", boom)

    res = m.search("openlibrary", "三体", "刘慈欣", 5)

    assert res["ok"] is False
    assert res["fail"] == {"kind": "network", "host": "openlibrary.org"}, res


def test_体检把DNS污染说清楚(monkeypatch):
    """本机解析到错地址 ⇒ 结论升级成 `dns_polluted`，并把两边地址写进原因。

    这是第 104 期的核心：此前一律报「超时」，用户会去修一个**根本没坏**的源。
    """
    from novelforge.core import netdiag as nd

    _patch_connect_timeout(monkeypatch)
    monkeypatch.setattr(nd, "compare", lambda host, **_k: {
        "host": host, "local": ["31.13.112.4"], "public": ["199.59.149.201"],
        "server": "8.8.8.8", "agrees": False, "polluted": True, "error": ""})

    out = m.health_one("openlibrary", {}, "Dune", "Frank Herbert")

    assert out["ok"] is False and out["kind"] == "dns_polluted", out
    assert "本机 DNS 被污染" in out["error"]
    assert "31.13.112.4" in out["error"] and "199.59.149.201" in out["error"]


def test_无法交叉核对时不乱指(monkeypatch):
    """公共解析器答不上来 ⇒ 分类保持「连接超时」，原因如实说无法核对，**不许提污染**。"""
    from novelforge.core import netdiag as nd

    _patch_connect_timeout(monkeypatch)
    monkeypatch.setattr(nd, "compare", lambda host, **_k: {
        "host": host, "local": [], "public": [], "server": "", "agrees": None,
        "polluted": False, "error": "公共解析器不可用，无法交叉核对（8.8.8.8 无应答）"})

    out = m.health_one("openlibrary", {}, "Dune", "Frank Herbert")

    assert out["kind"] == "connect_timeout", out
    assert "无法交叉核对" in out["error"]
    assert "污染" not in out["error"]


def test_探活也带同样的归因(monkeypatch):
    """「测试这一家」与体检是同一套口径（两处各写一份必然走散）。"""
    from novelforge.core import netdiag as nd

    _patch_connect_timeout(monkeypatch)
    monkeypatch.setattr(nd, "compare", lambda host, **_k: {
        "host": host, "local": ["31.13.112.4"], "public": ["199.59.149.201"],
        "server": "8.8.8.8", "agrees": False, "polluted": True, "error": ""})

    res = m.probe("openlibrary")

    assert res["ok"] is False
    assert "本机 DNS 被污染" in res["message"]


def test_归因缝没有联网也能跑(monkeypatch):
    """conftest 的 `_no_live_dns_in_tests` 把两个 I/O 缝换成「问不到」时：

    不能报污染（未知 ≠ 污染），但也不能因此抛异常 —— 体检照常给出「连接超时 + 无法核对」。
    """
    _patch_connect_timeout(monkeypatch)

    out = m.health_one("openlibrary", {}, "Dune", "Frank Herbert")

    assert out["kind"] == "connect_timeout", out
    assert "无法交叉核对" in out["error"]


# ---------------- 端点 ----------------

def test_体检端点只读且可回看上次结果(client, auth_headers, isolated, monkeypatch):  # noqa: ARG001
    """体检**不改配置**；`GET` 回上次结果（进程内缓存，重启即空 —— 如实说明）。"""
    before = client.get("/api/config", headers=auth_headers).json()["config"]["metadata_fetch"]
    _patch_raise(monkeypatch, "被限流（429）：稍后再试")

    r = client.post("/api/metadata/health", headers=auth_headers, json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["total"] == len(m.SOURCES)
    assert body["kind_labels"]["rate_limited"].startswith("被限流")

    after = client.get("/api/config", headers=auth_headers).json()["config"]["metadata_fetch"]
    # 「只读」要断言**前后一致**，不能断言绝对值为空 —— 别的用例可能已经往同一份隔离配置里
    # 存过密钥，那样写会变成「依赖测试执行顺序」的假失败。
    assert after["sources"] == before["sources"], "体检不能改启用的来源"
    assert after["hardcover_api_token"] == before["hardcover_api_token"], "体检不能写配置"
    assert after["has_hardcover_api_token"] == before["has_hardcover_api_token"]
    assert after["merge_sources"] == before["merge_sources"]

    last = client.get("/api/metadata/health", headers=auth_headers).json()
    assert last["ran_at"] == body["ran_at"], "GET 应回上次那次体检的结果"


def test_没体检过时如实说没有(client, auth_headers, isolated, monkeypatch):  # noqa: ARG001
    from novelforge import server

    # 缓存是**进程内全局**：同一进程里别的用例可能已经体检过 ⇒ 这里先显式清空，
    # 否则这条用例会因执行顺序不同而时绿时红。
    monkeypatch.setattr(server, "_METADATA_HEALTH", {})
    body = client.get("/api/metadata/health", headers=auth_headers).json()

    assert body["ran_at"] == 0 and body["items"] == {}
    assert "尚未体检过" in body["message"]
    assert body["kind_labels"], "分类文案即使没体检过也要给（前端据此渲染图例）"
