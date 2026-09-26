"""第 56 期：进度写入时间戳契约（多设备提示的比较基准）。

阅读器要判断「这条进度是不是别的设备刚写的」，靠的是**服务端写入时间戳**：
- `PUT /api/books/{bid}/progress` 回带本次写入的 `updated_at` ⇒ 前端更新「本机已知」；
- `GET /api/books/{bid}/progress` 带回 `updated_at` ⇒ 轮询时与「本机已知」比较，
  只有更新的写入才提示；两条都不能少，少一条这个机制就退化成「自己的保存也提示」。

另外钉住：**没有进度行**时 GET 不给 `updated_at`（前端按「没有基准」处理是否提示，
不能凭空造一个 0 当基准 —— 那会让首次进入阅读器就弹提示）。
"""
from novelforge.core import db


def test_写入返回时间戳且递增(client, auth_headers):  # noqa: ARG001
    r1 = client.put("/api/books/lib$x/progress", headers=auth_headers,
                    json={"locator": 1, "percent": 10.0})
    assert r1.status_code == 200, r1.text
    at1 = r1.json().get("updated_at")
    assert isinstance(at1, (int, float)) and at1 > 0, r1.json()

    r2 = client.put("/api/books/lib$x/progress", headers=auth_headers,
                    json={"locator": 2, "percent": 20.0})
    at2 = r2.json()["updated_at"]
    assert at2 >= at1, "第二次写入的时间戳不能倒退"


def test_读取带回同一时间戳(client, auth_headers):  # noqa: ARG001
    at = client.put("/api/books/lib$y/progress", headers=auth_headers,
                    json={"locator": 3, "percent": 33.0}).json()["updated_at"]

    body = client.get("/api/books/lib$y/progress", headers=auth_headers).json()

    assert body["updated_at"] == at, "GET 的 updated_at 必须与最近一次 PUT 一致"
    assert body["locator"] == 3 and body["percent"] == 33.0


def test_没有进度行时不给时间戳(client, auth_headers):  # noqa: ARG001
    body = client.get("/api/books/lib$never/progress", headers=auth_headers).json()

    assert body["locator"] == 0 and body["percent"] == 0
    assert "updated_at" not in body, "没有行就没有基准，不能造一个 0 出来"


def test_其它来源写进度同样刷新时间戳(isolated):  # noqa: ARG001
    """KOReader / Komga / 完成标记都经 `db.set_progress`（不带 cfi）——
    它们写进去的进度也要刷新时间戳，否则「别的设备（KOReader）读了一段」不会被提示。"""
    at = db.set_progress("lib$z", 4, 44.0)

    row = db.get_progress("lib$z")
    assert row["updated_at"] == at
    assert row["cfi"] == "", "非 NF 来源写入仍按第 54 期语义清掉精确坐标"
