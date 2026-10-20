"""任务记录必须能自证「这个进度是活的还是死的」（第 131 期）。

## 为什么要有这一期

`tasks` 表里的 `running` 只由**进程内**的后台协程推进（`server._spawn_bg` → 各个
`_run_*`，收尾写 `failed` / `done`）。进程一死，那一行就**再没有下一个写入者**了 ——
可它仍然留着 `status='running'`、`progress=50`。

而 `GET /api/tasks` 只读表、不读进程状态，于是重启后任务页会**永远转圈**：
任何读它的人都分辨不出「还在跑」与「跑到一半进程没了」。这不是用户点错了，
是**记录说了谎** —— 与本项目「不做假数据 / 不做假交互」的口径直接冲突。

实测（隔离实例）：手工把一行置成 `running` / `progress=50` → 重启进程 →
`GET /api/tasks` 回来的还是 `running 50.0 ''`。修前修后对比见 roadmap 第 131 期。

与刮削的 `db.scrape_reset_running` **不是同一件事**：那张表（`scrape_items`）是
**可续跑**的持久队列，所以打回 `pending` 让 worker 接着跑；`tasks` 是**一次性动作的
进度条**，没有「从一半接着跑」的语义，只能如实标失败。
"""
from fastapi.testclient import TestClient

from conftest import TEST_PIN, TEST_USER

from novelforge.core import db
from novelforge.server import app


def test_把没跑完的任务收尾成失败(client):
    db.task_create("t131-running", "convert", "转换 长夜.txt", status="running", progress=50.0)
    db.task_create("t131-queued", "convert", "转换 短夜.txt", status="queued", progress=0.0)
    db.task_create("t131-done", "convert", "转换 已完.txt", status="done", progress=100.0)

    n = db.task_reset_interrupted()
    assert n == 2

    rows = {r["id"]: r for r in db.task_list(50)}
    for tid in ("t131-running", "t131-queued"):
        assert rows[tid]["status"] == "failed"
        assert rows[tid]["progress"] == 100.0
        assert rows[tid]["error"] == db.TASK_INTERRUPTED
    # 已经跑完的不许被动
    assert rows["t131-done"]["status"] == "done"
    assert rows["t131-done"]["error"] == ""


def test_幂等_第二次没有可收尾的(client):
    db.task_create("t131-b", "convert", "转换", status="running", progress=50.0)
    assert db.task_reset_interrupted() == 1
    assert db.task_reset_interrupted() == 0


def test_启动时真的会调用它(isolated):
    """走真实 lifespan：进程启动 → 上一次留下的 running 必须变成 failed。"""
    db.init()
    db.task_create("t131-boot", "convert", "转换 长夜.txt", status="running", progress=50.0)
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"user": TEST_USER, "pin": TEST_PIN})
        assert r.status_code == 200
        h = {"Authorization": f"Bearer {r.json()['token']}"}
        items = {i["id"]: i for i in c.get("/api/tasks", headers=h).json()["items"]}
        assert items["t131-boot"]["status"] == "failed"
        assert items["t131-boot"]["error"] == db.TASK_INTERRUPTED


def test_失败文案单一出处():
    """`TASK_INTERRUPTED` 是唯一出处：用例与界面都照它断言，别再写第二份字面量。"""
    assert "重启" in db.TASK_INTERRUPTED
    assert "重新操作" in db.TASK_INTERRUPTED
