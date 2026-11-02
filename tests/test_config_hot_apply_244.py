"""配置**保存后是否真的生效**（第 244 期）。

三处此前都是「能保存、能回显，行为不变」：

1. `watcher.settle_seconds` / `watcher.stable_rounds` —— 只在 `Watcher.__init__` 读一次，
   `_apply_watcher_config` 不热应用 ⇒ 改完直到重启才生效（而用户以为护栏已经加高）；
2. `logging.max_entries` —— **全仓没有任何读点**，内存缓冲恒为 2000 条（假配置）；
3. 书目列表的缓存键是「全量」语义，分页结果写进去会污染全量读（见
   `test_paged_cache_isolation_244.py`）。

这里盯住「保存 → 立刻生效」，不靠重启。
"""
from __future__ import annotations

from novelforge.core import activity_log, library


def test_watcher_稳定判定参数保存后立刻生效(client, auth_headers, isolated,
                                              monkeypatch):
    """`settle_seconds` / `stable_rounds` 是纯运行时参数 ⇒ 改了立即影响下一轮。"""
    from novelforge import server as server_mod
    from novelforge.core import watcher as watcher_mod

    # 测试里监听线程默认没起（不跑真目录）⇒ 造一个**不启动线程**的实例，
    # 只验「热应用」这条路（`_apply_watcher_config` 改的就是它的属性）。
    w = watcher_mod.FolderWatcher(cfg={"watcher": {}})
    monkeypatch.setattr(server_mod, "WATCHER", w)

    r = client.put("/api/config", headers=auth_headers,
                   json={"watcher": {"settle_seconds": 3.5, "stable_rounds": 4}})
    assert r.status_code == 200, r.text

    assert w.settle_seconds == 3.5, w.settle_seconds
    assert w.stable_rounds == 4, w.stable_rounds


def test_日志缓冲条数保存后立刻生效(client, auth_headers, isolated):
    """`logging.max_entries` 必须**真的有读点**（此前是个假配置）。"""
    r = client.put("/api/config", headers=auth_headers,
                   json={"logging": {"max_entries": 37}})
    assert r.status_code == 200, r.text

    assert activity_log.max_entries() == 37, activity_log.max_entries()
    assert activity_log._memory.maxlen == 37, activity_log._memory.maxlen

    # 塞 50 条 ⇒ 缓冲里只留最近 37 条
    for i in range(50):
        activity_log.log(activity_log.ACTION_METADATA, "条目%d" % i,
                         activity_log.STATUS_OK, source="test")
    assert len(activity_log._memory) == 37, len(activity_log._memory)

    client.put("/api/config", headers=auth_headers,
               json={"logging": {"max_entries": 2000}})


def test_日志缓冲条数夹到至少一条(client, auth_headers, isolated):
    """0 / 负数 ⇒ 夹到 1（不能是 0：`deque(maxlen=0)` 会把内存缓冲整个废掉）。"""
    r = client.put("/api/config", headers=auth_headers,
                   json={"logging": {"max_entries": 0}})
    assert r.status_code == 200, r.text
    assert activity_log.max_entries() == 1, activity_log.max_entries()
    assert activity_log._memory.maxlen == 1, activity_log._memory.maxlen

    client.put("/api/config", headers=auth_headers,
               json={"logging": {"max_entries": 2000}})


def test_监听间隔与稳定等待要夹下界(client, auth_headers, isolated, monkeypatch):
    """0 / 负数 / 极小数都要夹住。

    ⚠️ `settle_seconds=0` 最危险：`_stop.wait(0)` 立即返回 ⇒ `_wait_stable` 在
    **一瞬间**读完大小（通常相同）⇒ 立刻判「写入完成」⇒ **半截文件被复制进书库**。
    ⚠️ `interval=0.1` 让主循环每 0.1 秒轮询一次 ⇒ NAS 上 CPU 打满。
    夹边界的**唯一实现**在 `core/watcher.py`（`interval_of` / `settle_seconds_of`），
    `__init__` 与热应用共用。
    """
    from novelforge import server as server_mod
    from novelforge.core import watcher as watcher_mod

    w = watcher_mod.FolderWatcher(cfg={"watcher": {}})
    monkeypatch.setattr(server_mod, "WATCHER", w)

    r = client.put("/api/config", headers=auth_headers,
                   json={"watcher": {"interval": 0.1, "settle_seconds": 0}})
    assert r.status_code == 200, r.text
    assert w.interval == watcher_mod.MIN_INTERVAL, w.interval
    assert w.settle_seconds == watcher_mod.MIN_SETTLE_SECONDS, w.settle_seconds

    # 负数同样要夹（不能变成负的等待时间）
    client.put("/api/config", headers=auth_headers,
               json={"watcher": {"interval": -5, "settle_seconds": -1}})
    assert w.interval == watcher_mod.MIN_INTERVAL, w.interval
    assert w.settle_seconds == watcher_mod.MIN_SETTLE_SECONDS, w.settle_seconds


def test_构造监听器时也要夹下界(isolated):
    """读配置那条路（`__init__`）同样要夹 —— 环境变量 / 配置文件都能给 0。"""
    from novelforge.core import watcher as watcher_mod

    w = watcher_mod.FolderWatcher(cfg={"watcher": {"interval": 0, "settle_seconds": 0}})
    assert w.interval == watcher_mod.MIN_INTERVAL, w.interval
    assert w.settle_seconds == watcher_mod.MIN_SETTLE_SECONDS, w.settle_seconds


def test_被环境变量接管的键要如实回显(client, auth_headers, isolated, monkeypatch):
    """`AUTO_WATCH` / `WATCH_INTERVAL` 是**无条件覆盖** ⇒ 界面改了没用 ⇒ 必须说清。

    界面上那个输入框改了不起作用（部署时环境变量把它压回去）⇒ 不标注就是
    「假交互」（AGENTS §1：不做假交互）。后端如实回 `env_overridden`，
    前端据此禁用控件并说明原因（第 244 期）。
    """
    monkeypatch.setenv("AUTO_WATCH", "false")
    monkeypatch.setenv("WATCH_INTERVAL", "9")
    r = client.get("/api/config", headers=auth_headers).json()
    keys = list(r.get("env_overridden") or [])
    assert "watcher.enabled" in keys, keys
    assert "watcher.interval" in keys, keys


def test_没有环境变量时回显空表(client, auth_headers, isolated, monkeypatch):
    monkeypatch.delenv("AUTO_WATCH", raising=False)
    monkeypatch.delenv("WATCH_INTERVAL", raising=False)
    r = client.get("/api/config", headers=auth_headers).json()
    assert not (r.get("env_overridden") or []), r.get("env_overridden")
