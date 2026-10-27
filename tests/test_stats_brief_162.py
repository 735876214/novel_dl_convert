"""``/api/stats?brief=1``：仪表盘专用的小份统计（第 162 期）。

**为什么值得钉**：仪表盘 9 个部件只读完整响应里 ~3.6% 的字节，却每次进站都拉整份
—— 而整份的成本大头（五年会话明细全表扫、逐本 metascore 审计、Top-50、图表序列）
全是**统计页专属**。brief 模式只算部件要的键；这里钉三条：

1. **部件读的键一个不缺、形状同形**（逐部件核过的清单，见 `stats._BRIEF_KEYS` 注释）；
2. **统计页专属的键一律缺席**（不是给空值 —— 缺席让前端走「数据未接入」空态，
   也让响应体积如实变小）；
3. **共用的聚合判据不分叉**：`reading.finished` 与完整份一致（同一批状态行、
   同一套阈值归类）。
"""
from conftest import TEST_PIN, TEST_USER


def _login(client) -> dict:
    tok = client.post(
        "/api/auth/login", json={"user": TEST_USER, "pin": TEST_PIN}
    ).json()["token"]
    return {"Authorization": f"Bearer {tok}"}


def test_brief_包含部件要的全部键(client, auth_headers):
    r = client.get("/api/stats?brief=1", headers=auth_headers)
    assert r.status_code == 200, r.text
    d = r.json()
    # 逐部件核过的清单（ReadingDna / DiversityScore / LibraryOverview / Streak /
    # Goal / Time / Rhythm / YearProjection / MonthlyChallenge 九件的并集）
    for key in ("books", "reading", "added_28d", "reading_28d", "authors",
                "series", "window", "hours", "added_month", "library_id"):
        assert key in d, f"brief 缺了部件要读的键：{key}"
    # 子形状也要齐（部件直接下钻到这些字段）
    assert {"total", "size", "by_format", "languages"} <= set(d["books"])
    assert {"finished", "streak", "days", "sessions", "seconds"} <= set(d["reading"])
    assert "total" in d["authors"] and "total" in d["series"]
    assert isinstance(d["added_28d"], list) and isinstance(d["reading_28d"], list)
    assert isinstance(d["hours"], list) and isinstance(d["added_month"], int)


def test_brief_统计页专属的键缺席(client, auth_headers):
    r = client.get("/api/stats?brief=1", headers=auth_headers)
    d = r.json()
    for heavy in ("session_timeline", "session_archetypes", "reading_pace",
                  "genre_reading", "genre_cooccurrence", "largest",
                  "library_metadata", "metadata_fields", "metadata_score",
                  "progress_funnel", "completion_monthly", "completion_latency",
                  "by_language", "by_format_size", "pages_by_format",
                  "added_monthly", "publication_yearly", "format_share_monthly",
                  "acquisition_lag", "recent", "weekdays", "integrity",
                  "avg_progress", "publishers", "genres", "years"):
        assert heavy not in d, f"brief 不该带统计页专属键：{heavy}"


def test_brief_与完整份的_finished_一致(client, auth_headers, default_root, make_book):
    """共用的判据不分叉：状态归类是同一份函数（stats._classify_status）。"""
    make_book(default_root, "brief-a.epub")
    make_book(default_root, "brief-b.epub")
    assert client.post("/api/libraries/default/scan", headers=auth_headers).json()["ok"]

    full = client.get("/api/stats", headers=auth_headers).json()
    brief = client.get("/api/stats?brief=1", headers=auth_headers).json()
    assert brief["reading"]["finished"] == full["reading"]["finished"]
    assert brief["books"]["total"] == full["books"]["total"]
    assert brief["books"]["by_format"] == full["books"]["by_format"]
    assert brief["books"]["languages"] == full["books"]["languages"]


def test_brief_体积显著小于完整份(client, auth_headers):
    """收益断言：不是「省了一两个键」，而是把图表序列那批大头全部留下。"""
    full = client.get("/api/stats", headers=auth_headers)
    brief = client.get("/api/stats?brief=1", headers=auth_headers)
    assert brief.status_code == full.status_code == 200
    assert len(brief.content) < len(full.content) / 4, (
        f"brief={len(brief.content)}B full={len(full.content)}B —— 收益没有兑现，"
        "多半是把重键又带回来了"
    )


def test_brief_跟随_days_参数(client, auth_headers):
    a = client.get("/api/stats?brief=1&days=7", headers=auth_headers).json()
    b = client.get("/api/stats?brief=1&days=28", headers=auth_headers).json()
    assert a["window"] == 7 and len(a["added_28d"]) == 7
    assert b["window"] == 28 and len(b["added_28d"]) == 28


def test_brief_未登录仍是_401(client):
    assert client.get("/api/stats?brief=1").status_code == 401


def test_默认不带_brief_输出与从前一致(client, auth_headers):
    """不传 brief ⇒ 走 overview，统计页的既有键一个不少（向后兼容）。"""
    d = client.get("/api/stats", headers=auth_headers).json()
    for key in ("session_timeline", "largest", "metadata_score", "integrity"):
        assert key in d
