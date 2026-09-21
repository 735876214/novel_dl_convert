"""自定义智能书架（`/api/smart-scopes`）：CRUD + 规则白名单。

第 37 期前侧栏「智能书架」组是**前端硬编码**的 5 条，这组接口一个测试都没有
（规则存储在后端、求值在前端，后端只做结构校验，很容易被当成「薄壳不值得测」）。
本期那 5 条内置下线，「最近添加 / 有批注」**只能**靠用户手搓规则重建，于是
「哪些字段/操作是合法的」从锦上添花变成了能力本身 —— 这里把它钉住：

- 白名单内：`status`（未读/在读/已完成）、`annotations`（批注数）、`added`（入库天数）；
- 白名单外：未知字段 / 字段不支持的操 / 空规则数组 → 一律 400，且**带着字段名**报错
  （前端管理页直接展示这句，说不清是哪个字段就等于没说）。
"""

from __future__ import annotations


def _create(client, headers, **payload) -> dict:
    r = client.post("/api/smart-scopes", json=payload, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _rules(*triples) -> list:
    return [{"field": f, "op": o, "value": v} for f, o, v in triples]


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

def test_一个都不建时列表为空(client, auth_headers):
    """不设默认：全新部署时一个智能书架都没有，等用户自己建。"""
    r = client.get("/api/smart-scopes", headers=auth_headers)
    assert r.status_code == 200 and r.json()["items"] == []


def test_增删改查走一遍(client, auth_headers):
    created = _create(client, auth_headers, name="科幻", match="all",
                      rules=_rules(("tag", "contains", "科幻"), ("stars", "at_least", "4")))
    sid = created["id"]

    listed = client.get("/api/smart-scopes", headers=auth_headers).json()["items"]
    assert [s["id"] for s in listed] == [sid]
    assert listed[0]["name"] == "科幻" and listed[0]["match"] == "all"
    assert listed[0]["rules"][0] == {"field": "tag", "op": "contains", "value": "科幻"}

    r = client.put(f"/api/smart-scopes/{sid}", headers=auth_headers,
                   json={"name": "太空歌剧", "match": "any",
                         "rules": _rules(("series", "contains", "基地"))})
    assert r.status_code == 200, r.text
    again = client.get("/api/smart-scopes", headers=auth_headers).json()["items"][0]
    assert again["name"] == "太空歌剧" and again["match"] == "any"

    assert client.delete(f"/api/smart-scopes/{sid}", headers=auth_headers).status_code == 200
    assert client.get("/api/smart-scopes", headers=auth_headers).json()["items"] == []
    # 再删一次 = 404（不是静默成功）
    assert client.delete(f"/api/smart-scopes/{sid}", headers=auth_headers).status_code == 404


# ---------------------------------------------------------------------------
# 规则白名单：内置书架下线后，靠这些字段把等价视图重建出来
# ---------------------------------------------------------------------------

def test_用_status_重建未读在读已完成(client, auth_headers):
    for value in ("unread", "reading", "finished"):
        _create(client, auth_headers, name=value, rules=_rules(("status", "equals", value)))
    assert len(client.get("/api/smart-scopes", headers=auth_headers).json()["items"]) == 3


def test_用_annotations_重建有批注(client, auth_headers):
    """「有批注」= 批注数至少 1。这是第 37 期补的字段，补之前它**造不出来**。"""
    s = _create(client, auth_headers, name="有批注",
                rules=_rules(("annotations", "at_least", "1")))
    listed = client.get("/api/smart-scopes", headers=auth_headers).json()["items"]
    assert listed[0]["rules"] == [{"field": "annotations", "op": "at_least", "value": "1"}]
    assert s["id"] == listed[0]["id"]


def test_用_added_重建最近添加(client, auth_headers):
    """「最近添加」= 入库至多 N 天。同样是第 37 期补的字段（值 = 距今天数）。"""
    _create(client, auth_headers, name="最近添加", rules=_rules(("added", "at_most", "30")))
    listed = client.get("/api/smart-scopes", headers=auth_headers).json()["items"]
    assert listed[0]["rules"][0]["field"] == "added"


def test_未知字段被拒且报出字段名(client, auth_headers):
    r = client.post("/api/smart-scopes", headers=auth_headers,
                    json={"name": "乱写", "rules": _rules(("不是字段", "equals", "x"))})
    assert r.status_code == 400
    assert "不是字段" in r.json()["detail"]


def test_字段不支持的操被拒(client, auth_headers):
    # status 只支持 equals；沿用 stars 的 at_least 就应当被拦
    r = client.post("/api/smart-scopes", headers=auth_headers,
                    json={"name": "乱写", "rules": _rules(("status", "at_least", "3"))})
    assert r.status_code == 400
    assert "status" in r.json()["detail"]


def test_空规则与坏_match_被拒(client, auth_headers):
    assert client.post("/api/smart-scopes", headers=auth_headers,
                       json={"name": "空", "rules": []}).status_code == 400
    assert client.post("/api/smart-scopes", headers=auth_headers,
                       json={"name": "坏", "rules": _rules(("tag", "equals", "x")),
                             "match": "some"}).status_code == 400
    assert client.post("/api/smart-scopes", headers=auth_headers,
                       json={"name": "  ", "rules": _rules(("tag", "equals", "x"))}).status_code == 400


def test_存进去的规则是干净三元组(client, auth_headers):
    """多传的键不许悄悄存下来 —— 前端求值只看 field/op/value，多余的键是隐性配置。"""
    _create(client, auth_headers, name="干净",
            rules=[{"field": "tag", "op": "equals", "value": "科幻", "多余的键": 1}])
    listed = client.get("/api/smart-scopes", headers=auth_headers).json()["items"]
    assert listed[0]["rules"] == [{"field": "tag", "op": "equals", "value": "科幻"}]
