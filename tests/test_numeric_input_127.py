"""第 127 期：客户端数值的「有限性」（契约）。

**要钉住的现象**：一个不合法但**语法正确**的数字，能把应用的可读面整个打掉。

JSON 规范里没有 ``inf`` / ``NaN`` 这两个字面量，可 Python 的 ``json`` 认它们
（``1e400`` 解析成 ``inf``，``NaN`` 直接给 ``nan``），于是：

1. ``inf`` **存得进 SQLite 的 REAL 列**，却**序列化不进 JSON** —— starlette 的
   ``JSONResponse`` 用 ``allow_nan=False``，遇到 ``inf`` 抛
   ``ValueError: Out of range float values are not JSON compliant``。
   实测一条 ``PUT /api/books/{bid}/progress {"percent": 1e400}``（回 200、落库成功）
   之后，``GET /api/books``（书架首页）、``GET /api/stats``、
   ``GET /api/books/{bid}/progress`` **同时恒 500** —— 唯一能修的办法是手工改库。
2. ``NaN`` 与**任何数比较都是 ``False``** ⇒ ``if x <= 0 or x > 86400`` 这类两侧判据
   **一处都拦不住**它（``seconds: NaN`` 直冲 SQLite 的 NOT NULL 才是 500）。
3. ``int(1e400)`` 抛的是 ``OverflowError``，**不是** ``ValueError`` 的子类 ——
   ``except (TypeError, ValueError)`` 一个都接不住（``locator`` / ``chapter`` /
   ``start_off`` / ``stars`` 四处实测 500）。
4. 区间越界（``percent: -5`` / ``999``）此前**原样落库**：百分比直接决定「读完」判定，
   书架会把 999% 显示出来。

**本期的口径**（唯一判据 ``novelforge/core/numbers.py``）：

- 不是数 / ``inf`` / ``NaN`` ⇒ 入口 **400**（存不住，也不该存）；
- 有限但越界 ⇒ **夹住**（写失败会让这次进度整个丢掉，而「读到 -3 章」与
  「读到第 0 章」对用户是一回事）；
- 库里**已经**躺着脏值时，序列化层兜底（``_FiniteJSONResponse``）——
  「这一行数据坏了」是运维信息，不该变成「书架打不开」。
"""
import math

import pytest

from novelforge.core import db, komga_api, koreader, library, numbers

JSON_HEAD = {"Content-Type": "application/json"}


def _scan_one(root, name: str = "数值书.epub") -> str:
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"EPUB")
    library.invalidate()
    books = [b for b in library.books() if b["name"].endswith(name)]
    assert books, f"扫描没找到 {name}"
    return books[0]["id"]


def _raw(client, method: str, url: str, headers: dict, body: str):
    """用**原始 JSON 文本**发请求：``1e400`` / ``NaN`` 这类字面量必须原样进解析器。

    ``json=`` 参数会先过 ``json.dumps``（``allow_nan=True`` 时给 ``Infinity``），
    虽然也能解析，但写法离真实攻击面远了一层。
    """
    return client.request(method, url, headers={**headers, **JSON_HEAD}, content=body)


@pytest.fixture
def bid(client, auth_headers, default_root):
    return _scan_one(default_root)


# ---------------- 1. 毒化整页：进度 ----------------

def test_进度里的_inf_被拦在门口(client, auth_headers, bid):
    """``percent: 1e400`` ⇒ **400**（此前 200 + 落库 ⇒ 书架 / 统计 / 进度全 500）。"""
    r = _raw(client, "PUT", f"/api/books/{bid}/progress", auth_headers,
             '{"locator": 0, "percent": 1e400}')
    assert r.status_code == 400, r.text
    assert "有限数值" in r.text
    # 关键：一条毒行都没落进去，所有读接口照常
    assert client.get("/api/books", headers=auth_headers).status_code == 200
    assert client.get("/api/books?limit=5", headers=auth_headers).status_code == 200
    assert client.get("/api/stats?days=30", headers=auth_headers).status_code == 200
    rp = client.get(f"/api/books/{bid}/progress", headers=auth_headers)
    assert rp.status_code == 200
    assert rp.json()["percent"] == 0.0            # 仍是初始值：那次写入整个没发生
    assert math.isfinite(float((db.get_progress(bid) or {"percent": 0.0})["percent"]))


def test_locator_的_inf_不再_500(client, auth_headers, bid):
    """``locator: 1e400`` ⇒ 此前 ``int(1e400)`` 抛 OverflowError ⇒ 500；现在 400。"""
    r = _raw(client, "PUT", f"/api/books/{bid}/progress", auth_headers,
             '{"locator": 1e400, "percent": 1.0}')
    assert r.status_code == 400, r.text
    assert 0 <= int((db.get_progress(bid) or {"locator": 0})["locator"]) <= numbers.MAX_INDEX


# ---------------- 2. 毒化整页：状态 ----------------

def test_状态时间戳的_inf_不再毒化书架(client, auth_headers, bid):
    """``started_at: 1e400`` ⇒ 400（此前 200 + 落库 inf ⇒ ``GET /api/books`` 恒 500）。"""
    r = _raw(client, "PUT", f"/api/books/{bid}/status", auth_headers,
             '{"status": "reading", "started_at": 1e400}')
    assert r.status_code == 400, r.text
    got = client.get(f"/api/books/{bid}/status", headers=auth_headers)
    assert got.status_code == 200
    assert math.isfinite(float(got.json()["started_at"] or 0))
    assert client.get("/api/books", headers=auth_headers).status_code == 200


# ---------------- 3. 书签：此前「先落行再 500」 ----------------

def test_书签_percent_的_inf_回_400_而不是落一行坏数据(client, auth_headers, bid):
    """此前：写库成功、回写响应时 500 ⇒ 此后 ``GET .../bookmarks`` 恒 500。"""
    r = _raw(client, "POST", f"/api/books/{bid}/bookmarks", auth_headers,
             '{"anchor": "a1", "percent": 1e400, "chapter": 0, "label": "x"}')
    assert r.status_code == 400, r.text
    assert "有限数值" in r.text
    # 关键：一行都没落，列表也就还能读
    rl = client.get(f"/api/books/{bid}/bookmarks", headers=auth_headers)
    assert rl.status_code == 200
    assert rl.json()["items"] == []


def test_书签_chapter_的_inf_回_400(client, auth_headers, bid):
    r = _raw(client, "POST", f"/api/books/{bid}/bookmarks", auth_headers,
             '{"anchor": "a2", "percent": 1.0, "chapter": 1e400}')
    assert r.status_code == 400, r.text


# ---------------- 4. NaN 绕过两侧比较 ----------------

def test_会话秒数_NaN_回_400_而不是_500(client, auth_headers, bid):
    """``nan <= 0`` 与 ``nan > 86400`` **都是 False** ⇒ 原先一路写到 SQLite 才炸。"""
    r = _raw(client, "POST", f"/api/books/{bid}/session", auth_headers,
             '{"seconds": NaN}')
    assert r.status_code == 400, r.text
    assert "seconds" in r.text


def test_会话位置_NaN_回_400(client, auth_headers, bid):
    r = _raw(client, "POST", f"/api/books/{bid}/session", auth_headers,
             '{"seconds": 30, "start_percent": NaN}')
    assert r.status_code == 400, r.text


# ---------------- 5. OverflowError 不在 (TypeError, ValueError) 覆盖面里 ----------------

def test_批注_chapter_的_inf_回_400(client, auth_headers, bid):
    r = _raw(client, "POST", f"/api/books/{bid}/annotations", auth_headers,
             '{"quote": "好句子", "chapter": 1e400}')
    assert r.status_code == 400, r.text


def test_批注_start_off_的_inf_落成未知(client, auth_headers, bid):
    """锚偏移的契约是「非法一律 -1（不知道）」，不是 400 也不是 0。"""
    r = _raw(client, "POST", f"/api/books/{bid}/annotations", auth_headers,
             '{"quote": "好句子", "start_off": 1e400, "end_off": 1e400}')
    assert r.status_code == 200, r.text
    item = client.get(f"/api/books/{bid}/annotations", headers=auth_headers).json()["items"][0]
    assert item["start_off"] == -1
    assert item["end_off"] == -1


def test_评分_stars_的_inf_回_400_而不是_500(client, auth_headers, bid):
    """``int(1e400)`` ⇒ OverflowError；两个评分入口都要接住。"""
    r = _raw(client, "PUT", f"/api/books/{bid}/review", auth_headers,
             '{"stars": 1e400, "review": ""}')
    assert r.status_code == 400, r.text
    r = _raw(client, "PUT", f"/api/books/{bid}/rating", auth_headers, '{"stars": 1e400}')
    assert r.status_code == 400, r.text


# ---------------- 6. 有限越界：夹住，不落脏值 ----------------

def test_百分比越界被夹住(client, auth_headers, bid):
    assert _raw(client, "PUT", f"/api/books/{bid}/progress", auth_headers,
                '{"locator": 0, "percent": -5}').status_code == 200
    assert db.get_progress(bid)["percent"] == 0.0
    assert _raw(client, "PUT", f"/api/books/{bid}/progress", auth_headers,
                '{"locator": 0, "percent": 999}').status_code == 200
    assert db.get_progress(bid)["percent"] == 100.0


def test_序号负数被夹到零(client, auth_headers, bid):
    assert _raw(client, "PUT", f"/api/books/{bid}/progress", auth_headers,
                '{"locator": -3, "percent": 1.0}').status_code == 200
    assert db.get_progress(bid)["locator"] == 0
    r = _raw(client, "POST", f"/api/books/{bid}/bookmarks", auth_headers,
             '{"anchor": "a3", "chapter": -3, "percent": -5}')
    assert r.status_code == 200, r.text
    assert r.json()["server"]["chapter"] == 0
    assert r.json()["server"]["percent"] == 0.0


# ---------------- 7. 兜底：库里已有脏值也不许 500 ----------------

def test_库里已有_inf_时序列化兜底(client, auth_headers, bid):
    """绕过接口直接塞 ``inf``（模拟升级前已经写坏的库）—— 读接口仍须 200。"""
    db.set_progress(bid, 0, float("inf"))
    r = client.get("/api/books", headers=auth_headers)
    assert r.status_code == 200, r.text
    row = next(b for b in r.json()["items"] if b["id"] == bid)
    assert row["percent"] == 0.0                  # 兜底成 0，不是 inf
    assert client.get(f"/api/books/{bid}/progress", headers=auth_headers).status_code == 200


# ---------------- 8. 唯一判据本身 ----------------

@pytest.mark.parametrize("raw,expect", [
    (0, 0.0), ("12.5", 12.5), (100, 100.0),
    (-5, 0.0), (999, 100.0),                      # 有限越界 ⇒ 夹住
    (float("inf"), 0.0), (float("-inf"), 0.0), (float("nan"), 0.0),
    ("abc", 0.0), (None, 0.0), (True, 0.0),       # 非数 ⇒ 默认值（bool 不算数）
])
def test_percent_判据(raw, expect):
    assert numbers.percent(raw) == expect


def test_index_判据():
    assert numbers.index(3) == 3
    assert numbers.index(-3) == 0
    assert numbers.index(float("inf")) == 0
    assert numbers.index(float("nan")) == 0
    assert numbers.index(10 ** 12) == numbers.MAX_INDEX
    assert numbers.index("abc", default=-1) == -1
    assert numbers.MAX_INDEX <= 2 ** 63 - 1        # 必须存得进 SQLite 的 INTEGER


def test_epoch_判据():
    assert numbers.epoch(None) == 0.0
    assert numbers.epoch(float("inf")) == 0.0
    assert numbers.epoch(-1) == 0.0
    assert numbers.epoch(1e300) == numbers.MAX_EPOCH


def test_finite_不接受_bool():
    """``float(True) == 1.0`` 是 Python 的类型泄漏，不该顺着 API 传下去。"""
    assert numbers.finite(True) is None
    assert numbers.finite(5) == 5.0
    assert numbers.finite(float("inf")) is None


# ---------------- 9. 另两处同一判据（KOReader / Komga） ----------------

def test_koreader_nan_百分比不再等于读完():
    """此前 ``max(0.0, nan)`` ⇒ nan，``min(100.0, nan)`` ⇒ nan，落库就是「100%」。"""
    locator, percent = koreader.to_nf({"progress": "#/body/DocFragment[2]/body/div/p[1]",
                                       "percentage": float("nan")})
    assert locator == 1
    assert percent == 0.0


def test_koreader_超大章节号被夹住():
    locator, _ = koreader.to_nf({"progress": "9" * 40, "percentage": 0.5})
    assert 0 <= locator <= numbers.MAX_INDEX


def test_komga_页码_inf_不抛异常(client, monkeypatch):
    """``int(1e400)`` 的 OverflowError 在这里同样曾是 500。"""
    b = {"id": "lib$abc", "name": "x.cbz", "format": "CBZ", "pages": 10}
    monkeypatch.setattr(komga_api, "_is_paged", lambda _b: True)
    locator, percent = komga_api.apply_read_progress(b, {"page": float("inf")})
    assert locator == 0 and percent == 0.0        # 非法页码 ⇒ 不覆盖位置、百分比归零
    locator, percent = komga_api.apply_read_progress(b, {"page": 5})
    assert (locator, percent) == (4, 50.0)
