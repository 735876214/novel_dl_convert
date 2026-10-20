"""查询串里的「取多少条」必须夹进 SQLite 能接受的整数范围（第 130 期）。

## 为什么要有这一期

第 127 期把**请求体**里的数值收敛了（`numbers.finite` / `percent` / `index` / `epoch`），
但漏了**查询串**：`limit` 是 GET 上的一个整数参数，FastAPI 只负责「转成 int」，
不负责范围 —— 而 `10**30` 转得出来（Python 的 int 无上限），却**绑不进 SQLite**：
`sqlite3` 在绑定参数时抛 `OverflowError: Python int too large to convert to SQLite
INTEGER`，这个异常不在任何调用点的 `except` 里 ⇒ 整页 500。

实测（隔离实例，`fuzzquery.py` 对全部 GET 路由的每个 query 参数灌 12 种敌意值）
抓到三处：`GET /api/sources/imports?limit=10**30`、`GET /api/sources/<name>/history?...`、
`GET /api/tasks?limit=10**30`，栈都停在 `db.py` 的 `WHERE ... LIMIT ?` 绑定上。

## 判据落在哪一层

落在**绑定点**（`db.py` 的各个 `LIMIT ?`），不落在 6 个接口上：绑定点是唯一知道
「这个整数要进 SQLite」的地方，新增一个接口忘了夹也不会再炸。判据本身只有一份
（`numbers.row_limit`），低端语义由调用方给（`task_list` 要 ≥1，`recycle_list` 的
``0`` 表示「不截断」）。
"""
from novelforge.core import db, numbers


# ---------------- 判据本身 ----------------

def test_row_limit_夹住上界():
    assert numbers.row_limit(10 ** 30) == numbers.MAX_ROWS
    assert numbers.row_limit(numbers.MAX_ROWS) == numbers.MAX_ROWS
    assert numbers.row_limit(numbers.MAX_ROWS + 1) == numbers.MAX_ROWS
    assert numbers.row_limit(7) == 7


def test_row_limit_非数回落最小值():
    """`abc` / `None` / `inf` / `NaN` 都不该让绑定炸 —— 回落最小值即可。"""
    for bad in ("abc", None, float("inf"), float("nan"), []):
        assert numbers.row_limit(bad) == 1
        assert numbers.row_limit(bad, minimum=0) == 0


def test_row_limit_低端语义由调用方给():
    """`-1` 在 `task_list` 里是「至少 1 条」，在 `recycle_list` 里是「不截断」。"""
    assert numbers.row_limit(-1) == 1
    assert numbers.row_limit(-1, minimum=0) == 0
    assert numbers.row_limit(0) == 1
    assert numbers.row_limit(0, minimum=0) == 0


# ---------------- 接口不再 500 ----------------

HUGE = str(10 ** 30)


def test_tasks_接口超大_limit_不再_500(client, auth_headers):
    db.task_create("t-130-a", "convert", "任务甲")
    r = client.get("/api/tasks", params={"limit": HUGE}, headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()


def test_sources_imports_超大_limit_不再_500(client, auth_headers):
    r = client.get("/api/sources/imports", params={"limit": HUGE}, headers=auth_headers)
    assert r.status_code == 200
    assert "items" in r.json()


def test_sources_history_超大_limit_不再_500(client, auth_headers):
    r = client.get("/api/sources/示例源/history", params={"limit": HUGE},
                   headers=auth_headers)
    # 源不存在是 404（那是业务语义），但**不许**是 500
    assert r.status_code < 500


def test_recycle_超大_limit_不再_500(client, auth_headers):
    r = client.get("/api/recycle", params={"limit": HUGE}, headers=auth_headers)
    assert r.status_code == 200


def test_book_move_batches_超大_limit_不再_500(client, auth_headers):
    r = client.get("/api/book-move/batches", params={"limit": HUGE}, headers=auth_headers)
    assert r.status_code == 200


# ---------------- 既有语义不许被这次收紧改掉 ----------------

def test_task_list_仍然只回_limit_条(client, auth_headers):
    for i in range(3):
        db.task_create(f"t-130-{i}", "convert", f"任务{i}")
    assert len(db.task_list(2)) == 2
    assert len(db.task_list(1)) == 1
    # 旧语义：0 / 负数 ⇒ 至少 1 条（夹上界不许把它变成 0 条或全部）
    assert len(db.task_list(0)) == 1


def test_recycle_list_的_0_仍然是不截断(client):
    """`recycle_list(0)` 是回收站页面的「全部」语义 —— 收紧上限不许动它。"""
    for i in range(3):
        db.recycle_add(f"/tmp/x{i}.txt", f"20260101-00000{i}_x{i}.txt", "test")
    assert len(db.recycle_list(0)) == 3
    assert len(db.recycle_list(2)) == 2
    assert len(db.recycle_list(10 ** 30)) == 3
