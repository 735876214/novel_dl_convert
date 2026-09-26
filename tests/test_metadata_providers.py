"""第 57 期：14 家元数据提供商「全部真的能用」的契约。

这块的核心风险是**一致性**与**诚实性**，不是功能本身：

1. **注册表 ↔ 实现一致**：`IMPLEMENTED` 必须与 `_FETCHERS` 的键**完全相等**，
   且每家 `implemented=True` —— 否则又回到「开关能开、抓不到」的假交互；
2. **需要密钥的家**：没填密钥时给**明确的中文错误**，且探测**不发外呼**（省一次注定失败的请求）；
3. **密钥三处一致**：`config.DEFAULTS`、`server.EDITABLE`、注册表 `key_field` 指向同一批键名，
   回显一律**掩码** + `has_<键名>` 布尔。
"""
from novelforge import config
from novelforge.core import metasources

#: 注册表声明的**全部**配置键（4 个密钥 + Amazon Cookie + 4 个抓取参数）
_KEY_FIELDS = {"googlebooks_api_key", "hardcover_api_token", "comicvine_api_key", "aladin_ttbkey",
               "amazon_cookie", "itunes_cover_resolution", "kobo_region", "kobo_language",
               "audible_region"}
#: 页面抓取型（易失效）：站点改版就可能断，前端给「易失效」徽标
_FRAGILE = {"amazon", "goodreads", "kobo", "audible", "librofm", "lubimyczytac"}


def test_注册表覆盖上游十四家且分四组():
    items = metasources.provider_catalog()

    assert len(items) == 14, [i["id"] for i in items]
    assert len({i["id"] for i in items}) == 14, "id 不能重复"
    assert {i["group"] for i in items} == set(metasources.GROUPS)
    for meta in items:
        assert meta["label"] and meta["home"] and meta["note"], meta
        assert meta.get("implemented") is True, f"{meta['id']} 应当已接入"
        assert isinstance(meta.get("fragile"), bool), meta


def test_已实现清单与fetcher逐字一致():
    """`IMPLEMENTED` 是给注册表/前端看的，`_FETCHERS` 是真正能跑的 —— 两者必须相等。"""
    assert set(metasources.IMPLEMENTED) == set(metasources._FETCHERS)
    assert len(metasources._FETCHERS) == 14
    for sid in metasources.IMPLEMENTED:
        assert metasources.SOURCES[sid]["implemented"] is True, sid
        assert metasources.is_implemented(sid) is True, sid


def test_需要密钥与易失效两档标记准确():
    need = {s for s in metasources.SOURCES if metasources.needs_key(s)}
    fragile = {s for s in metasources.SOURCES if metasources.SOURCES[s].get("fragile")}

    assert need == {"hardcover", "comicvine", "aladin"}, need
    assert fragile == _FRAGILE, fragile
    for sid in need:
        assert metasources.key_field_of(sid), f"{sid} 需要密钥但没有 key_field"
    # 免密钥的家不该带 key_field（免得前端多渲染一个没用的输入框）
    assert {metasources.key_field_of(s) for s in ("openlibrary", "itunes", "ranobedb")} == {""}


def test_配置键三处登记一致():
    """注册表声明的**所有**配置键 = DEFAULTS 的键 ⊂ EDITABLE 允许写 —— 三处必须同步。

    第 57 期 E 段起不止「四个密钥」：还有 5 个抓取参数（含 Amazon 的 Cookie，
    它也是 secret、也要掩码）。所以这里按**注册表的全部 config_fields** 比，
    而不是手写一份键名清单（手写清单正是漏项的来源）。
    """
    declared = {f["key"] for s in metasources.SOURCES for f in metasources.config_fields_of(s)}

    assert declared == _KEY_FIELDS, declared ^ _KEY_FIELDS
    # 掩码集合 = 全部 secret（含 Cookie）；非 secret 的抓取参数不该被掩码
    assert set(metasources.secret_fields()) == {
        "googlebooks_api_key", "hardcover_api_token", "comicvine_api_key",
        "aladin_ttbkey", "amazon_cookie",
    }

    defaults = config.DEFAULTS["metadata_fetch"]
    for field in declared:
        assert field in defaults, f"config.DEFAULTS 缺少 {field}"
    for field in metasources.secret_fields():
        assert defaults[field] == "", f"敏感项 {field} 的默认值应当是空串"

    from novelforge import server
    editable = server.EDITABLE["metadata_fetch"]
    assert declared <= set(editable), declared - set(editable)


def test_默认启用顺序只含已实现的源():
    assert len(metasources.DEFAULT_ORDER) == 2, "默认只开两家最可靠的，别一上来就 14 家外呼"
    for sid in metasources.DEFAULT_ORDER:
        assert metasources.is_implemented(sid), f"{sid} 没实现却在默认顺序里"


def test_目录按分组顺序排列():
    items = metasources.provider_catalog()
    order = [metasources.GROUPS.index(i["group"]) for i in items]
    assert order == sorted(order), "分组必须按 GROUPS 的顺序连续出现"


def test_未填密钥的家检索返回明确错误():
    for sid in ("hardcover", "comicvine", "aladin"):
        r = metasources.search(sid, "三体", "刘慈欣")

        assert r["ok"] is False and r["entries"] == [], (sid, r)
        assert ("Key" in r["error"]) or ("TTBKey" in r["error"]), (sid, r)


def test_抓取计划只认已实现的源(isolated):  # noqa: ARG001
    from novelforge.core import metafetch

    cfg = {"metadata_fetch": {"enabled": True, "sources": ["amazon", "openlibrary"]}}
    out = metafetch.plan(cfg=cfg)

    assert out.get("enabled") is True and isinstance(out.get("items"), list)


def test_providers_端点给出分组与计数(client, auth_headers):
    r = client.get("/api/metadata/providers", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["total"] == 14
    assert body["implemented_count"] == 14
    assert body["active_count"] == 2, "默认启用 openlibrary + googlebooks"
    assert [g["name"] for g in body["groups"]] == list(metasources.GROUPS)

    by_id = {i["id"]: i for i in body["items"]}
    assert by_id["openlibrary"]["active"] is True and by_id["openlibrary"]["order"] == 1
    assert by_id["googlebooks"]["order"] == 2
    assert by_id["amazon"]["active"] is False and by_id["amazon"]["fragile"] is True
    # 「需要设置」= 要 Key 且还没填（前端过滤器的唯一数据源）
    assert by_id["hardcover"]["needs_setup"] is True
    assert by_id["hardcover"]["key_field"] == "hardcover_api_token"
    assert by_id["openlibrary"]["needs_setup"] is False
    assert by_id["amazon"]["needs_setup"] is False, "不需要配置 ≠ 需要设置"


def test_连通性探测对未填密钥的家不发外呼(client, auth_headers, monkeypatch):
    """没填密钥就如实回报「需要设置」，**一次外呼都不该发**。"""
    called: list = []

    def spy(sid, opts=None):
        called.append(sid)
        return {"ok": True, "message": "stub", "ms": 1}

    monkeypatch.setattr(metasources, "probe", spy)

    r = client.post("/api/metadata/probe", headers=auth_headers,
                    json={"sources": ["hardcover", "comicvine", "aladin", "openlibrary"]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]

    assert called == ["openlibrary"], f"只有免密钥的家该被真探测：{called}"
    for sid in ("hardcover", "comicvine", "aladin"):
        assert items[sid]["ok"] is False and "需要设置" in items[sid]["message"], items[sid]


def test_行内测试用输入框里的凭据且不落盘(client, auth_headers, isolated, monkeypatch):  # noqa: ARG001
    """行内「测试」的语义：**用当前输入框的值**试一次，且**不写进配置**。

    否则只有两条烂路：测的是上次保存的旧值，或者为了测试先保存一次（把「试一下」
    变成写操作）。这里同时钉住「传了 keys 就用 keys」与「没传就沿用已保存值」。
    """
    seen: list = []

    def spy(sid, opts=None):
        seen.append((sid, (opts or {}).get("api_key")))
        return {"ok": True, "message": "stub", "ms": 1}

    monkeypatch.setattr(metasources, "probe", spy)

    # ① 带着「刚输入、还没保存」的凭据 → 用它，且配置里不该出现它
    r = client.post("/api/metadata/probe", headers=auth_headers,
                    json={"sources": ["hardcover"], "keys": {"hardcover": "draft-token"}})
    assert r.status_code == 200, r.text
    assert seen == [("hardcover", "draft-token")], seen
    mf = client.get("/api/config", headers=auth_headers).json()["config"]["metadata_fetch"]
    assert mf["has_hardcover_api_token"] is False, "行内测试绝不能把凭据写进配置"

    # ② 不传 keys → 沿用已保存值（先保存一个）
    client.put("/api/config", headers=auth_headers,
               json={"metadata_fetch": {"hardcover_api_token": "saved-token"}})
    seen.clear()
    client.post("/api/metadata/probe", headers=auth_headers, json={"sources": ["hardcover"]})
    assert seen == [("hardcover", "saved-token")], seen


def test_行内配置项由注册表声明_前端文案从它派生():
    """`config_fields` 是唯一真值源：目录端点把首项派生成 key_label/key_placeholder。

    这样注册表只维护一份声明，前端也不必自己写文案。
    """
    catalog = {i["id"]: i for i in metasources.provider_catalog()}

    for sid in ("googlebooks", "hardcover", "comicvine", "aladin", "amazon"):
        item = catalog[sid]

        assert item["config_fields"], f"{sid} 缺少 config_fields"
        assert item["key_label"] and item["key_placeholder"], f"{sid} 未派生出文案"
        assert item["config_fields"][0]["label"] == item["key_label"]

    # 只配抓取参数、没有 secret 的家：仍要有配置项（否则前端不给「配置」按钮）
    for sid in ("itunes", "kobo", "audible"):
        fields = metasources.config_fields_of(sid)

        assert fields and all(f["type"] == "select" for f in fields), (sid, fields)
        assert metasources.key_field_of(sid) == "", f"{sid} 没有密钥字段"

    # 掩码要覆盖所有 secret（含 Amazon 的 Cookie）
    assert "amazon_cookie" in metasources.secret_fields()


def test_options_按配置项拼装且空值不进opts():
    """`options_for` 只把**非空**值装进 opts —— 缺键与空串行为一致（fetcher 自带默认）。"""
    mf = {"googlebooks_api_key": "gb", "hardcover_api_token": "",
          "amazon_cookie": "session-id=1;", "itunes_cover_resolution": "standard",
          "kobo_region": "uk", "kobo_language": "en", "audible_region": ""}

    opts = metasources.options_for(mf, ["googlebooks", "hardcover", "amazon", "itunes",
                                        "kobo", "audible", "openlibrary"])

    assert opts["googlebooks"] == {"api_key": "gb"}
    assert "hardcover" not in opts, "空密钥不该进 opts"
    assert opts["amazon"] == {"cookie": "session-id=1;"}
    assert opts["itunes"] == {"resolution": "standard"}
    assert opts["kobo"] == {"region": "uk", "language": "en"}
    assert "audible" not in opts and "openlibrary" not in opts


def test_配置回显按注册表掩码所有密钥(client, auth_headers, isolated):  # noqa: ARG001
    token = "secret-hardcover-token"
    saved = client.put("/api/config", headers=auth_headers,
                       json={"metadata_fetch": {"hardcover_api_token": token,
                                                "aladin_ttbkey": "ttb-xyz"}})
    assert saved.status_code == 200, saved.text

    mf = client.get("/api/config", headers=auth_headers).json()["config"]["metadata_fetch"]

    assert mf["has_hardcover_api_token"] is True
    assert mf["hardcover_api_token"] not in (token, ""), "该键必须掩码回显，不能回明文"
    assert mf["has_aladin_ttbkey"] is True
    assert mf["has_comicvine_api_key"] is False
    # 兼容旧字段名仍在
    assert mf["has_googlebooks_key"] is False
