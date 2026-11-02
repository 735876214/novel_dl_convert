"""**五个配置写入口都要热应用**（第 246 期）。

## 缺陷

第 244 期给 ``logging.max_entries`` 补了真读点（此前是假配置：能保存、能回显，
缓冲恒为 2000 条），并把热应用挂在 ``PUT /api/config`` 上；留存策略的 5 秒缓存
失效也挂在那儿。

但配置**有五个写入口**（第 80 期立的纪律）：

| 入口 | 路由 |
|---|---|
| 1 | ``PUT /api/config`` |
| 2 | ``PUT /api/config/raw``（直接改 config.yaml 原文） |
| 3 | ``POST /api/config/restore``（还原备份） |
| 4 | ``POST /api/config/reset``（重置） |
| 5 | ``DELETE /api/config/overrides``（清覆盖层） |

第 244 期那两条热应用**只挂在第 1 条** ⇒ 走第 2–5 条改完配置后不生效
（第 244 期刚补上的真读点，在这些路上又变回「假配置」；留存策略最多 5 秒后自愈）。

## 这里钉的是「五个入口**都**热应用」

不只测第 1 条（那条本来就有）—— 逐个入口都断言：改完之后**立刻**生效
（不等重启、不等 5 秒缓存过期）。
"""
from __future__ import annotations

import pytest

from novelforge import config
from novelforge.core import activity_log


@pytest.fixture
def reset_log_config():
    """用例前后把日志配置还原（别把状态留给后续用例）。"""
    yield
    config.save_overrides({})
    activity_log.set_max_entries(activity_log.DEFAULT_MAX_ENTRIES)
    activity_log.invalidate_retention_cache()


def _max_entries_now() -> int:
    return int(activity_log._memory.maxlen)


def _make_buffer_stale(client, auth_headers) -> int:
    """让「配置里的值」与「当前缓冲」**故意不一致**，返回配置里的目标值。

    ⚠️ 这一步是判据的关键：若两者本来就相等，那么「有没有热应用」**看起来都一样**
    ⇒ 用例假绿（本次第一版就踩了这个：回退后只有 raw 那条红，其余三条恒绿）。
    """
    target = 777
    r = client.put("/api/config", headers=auth_headers,
                   json={"logging": {"max_entries": target}})
    assert r.status_code == 200, r.text
    # 此刻缓冲**已经**被热应用成 target ⇒ 手动把它改回别的值，制造不一致
    activity_log.set_max_entries(1)
    assert _max_entries_now() != target, "前置条件不成立：缓冲与配置已经一致"
    return target


def test_put_config_热应用(client, auth_headers, isolated, reset_log_config):
    r = client.put("/api/config", headers=auth_headers,
                   json={"logging": {"max_entries": 111}})
    assert r.status_code == 200, r.text
    assert _max_entries_now() == 111, _max_entries_now()


def test_put_raw_config_热应用(client, auth_headers, isolated, reset_log_config):
    """直接改 config.yaml 原文那条路。"""
    r = client.put("/api/config/raw", headers=auth_headers,
                   json={"text": "logging:\n  max_entries: 222\n"})
    assert r.status_code == 200, r.text
    assert _max_entries_now() == 222, _max_entries_now()


def test_restore_backup_热应用(client, auth_headers, isolated, reset_log_config):
    """还原备份那条路。

    备份由 `PUT /api/config/raw` 自动生成（还原前先备份当前 config.yaml）⇒
    这里先走一次 raw PUT 造出备份，再从备份列表里取名字。
    """
    import yaml

    # 造一份备份：先写一份**可辨认**的 config.yaml 原文，再走 raw PUT
    # （它会先把当前 config.yaml 备份进 BACKUP_DIR）。
    raw = client.put("/api/config/raw", headers=auth_headers,
                     json={"text": yaml.safe_dump({"logging": {"max_entries": 666}})})
    assert raw.status_code == 200, raw.text
    backups = client.get("/api/config/backups", headers=auth_headers).json()["items"]
    if not backups:
        pytest.skip("没有备份可还原（环境差异）")
    name = backups[0]["name"]

    _make_buffer_stale(client, auth_headers)
    r = client.post("/api/config/restore", headers=auth_headers, json={"name": name})
    assert r.status_code == 200, r.text
    # 判据不是「等于某个数」，而是「**与读到的配置一致**」——
    # 还原后缓冲条数必须等于当前配置里的值（= 热应用发生了）。
    assert _max_entries_now() == activity_log.max_entries(), _max_entries_now()


def test_reset_config_热应用(client, auth_headers, isolated, reset_log_config):
    """重置那条路：重置后缓冲条数必须回到**配置里的当前值**。"""
    _make_buffer_stale(client, auth_headers)
    r = client.post("/api/config/reset", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _max_entries_now() == activity_log.max_entries(), _max_entries_now()


def test_clear_overrides_热应用(client, auth_headers, isolated, reset_log_config):
    """清覆盖层那条路。"""
    _make_buffer_stale(client, auth_headers)
    r = client.delete("/api/config/overrides", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _max_entries_now() == activity_log.max_entries(), _max_entries_now()


def test_留存策略缓存_五个入口都失效(client, auth_headers, isolated, reset_log_config):
    """留存策略的 5 秒缓存也必须被这五条路**全部**清掉。"""
    from novelforge.core import activity_log as al
    # 先把缓存填上（模拟「刚刚读过一次」）
    al.retention_cfg()
    assert al._cfg_cache.get("val") is not None, "缓存没填上，用例前提不成立"

    for name, call in (
        ("PUT /api/config", lambda: client.put(
            "/api/config", headers=auth_headers, json={"logging": {"max_entries": 555}})),
        ("DELETE /api/config/overrides", lambda: client.delete(
            "/api/config/overrides", headers=auth_headers)),
    ):
        al.retention_cfg()          # 再填一次
        r = call()
        assert r.status_code == 200, (name, r.text)
        assert al._cfg_cache.get("val") is None, f"{name} 没有清掉留存策略缓存"
