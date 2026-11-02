"""**探活端点必须永远能回话**（第 257 期）。

## 缺陷

`/health` 是**最后一道能说话的地方**：

- Docker HEALTHCHECK **只判 HTTP 200** ⇒ `/health` 一旦 500，
  编排层就会**反复重启容器**（而服务其实好好的，只是某个探针炸了）；
- 用户自己的监控（Uptime 之类）也靠它 ⇒ 500 = 自己的监控一直报警。

而 `_health_checks()` 此前**只有「读配置」那一处**兜了异常
（第 251 期加的）⇒ **任何一项探针抛异常，整个端点就 500**。

**实测（修前）**：把 `db.ping` 换成会抛异常的桩 ⇒
`_health_checks RAISED: RuntimeError 探针自己炸了` ⇒ `/health` 500。

## 这里钉四件事

1. **一个探针抛异常 ⇒ 端点照样回话**（其余探针照旧）；
2. **抛异常的那项降级成「探不出」**（不是「正常」！——
   `default_pin` 的探针炸了却报「没人在用默认口令」，**恰恰掩盖了它本该报告的事**）；
3. **降级要留痕**：进 `problems`（用户看得到「哪一项探针坏了」）；
4. **状态码仍然对**：库连不上 ⇒ 503（只有这一种）；其余 ⇒ 200 + `degraded`。
"""
from __future__ import annotations

from novelforge import server
from novelforge.core import cache, db


def test_一个探针抛异常_端点照样回话(client, monkeypatch):
    """核心判据：`/health` **不许 500**。"""
    monkeypatch.setattr(db, "ping", lambda: (_ for _ in ()).throw(RuntimeError("炸了")))
    r = client.get("/health")
    assert r.status_code in (200, 503), r.text
    body = r.json()
    assert "status" in body and "checks" in body and "problems" in body, body


def test_抛异常的探针降级成探不出(client, monkeypatch):
    """⚠️ 降级成「探不出」而不是「正常」——
    `default_pin` 的探针炸了却报「没人在用默认口令」，**恰恰掩盖了它本该报告的事**。"""
    monkeypatch.setattr(db, "ping", lambda: (_ for _ in ()).throw(RuntimeError("炸了")))
    body = client.get("/health").json()
    assert body["checks"]["db"] is False, body["checks"]


def test_降级要留痕_说得出哪个探针坏了(client, monkeypatch):
    """降级必须**看得见** —— 否则「探针炸了」会被伪装成「那项正常」。"""
    monkeypatch.setattr(db, "ping", lambda: (_ for _ in ()).throw(RuntimeError("炸了")))
    body = client.get("/health").json()
    assert any("探针" in p for p in body["problems"]), body["problems"]
    assert any("db" in p for p in body["problems"]), body["problems"]


def test_一个探针坏_其余探针照旧回话(client, monkeypatch):
    """一个坏了**不许**连累其余（否则一次异常就让全部信息都瞎了）。"""
    monkeypatch.setattr(cache, "health", lambda: (_ for _ in ()).throw(RuntimeError("炸了")))
    body = client.get("/health").json()
    # 其余探针的值照旧给（不是默认值）
    assert body["checks"]["db"] is True, body["checks"]
    assert body["checks"]["config_dir_writable"] is True, body["checks"]
    assert body["checks"]["pillow"] is True, body["checks"]


def test_库连不上仍然是_503(client, monkeypatch):
    """⚠️ 只有「库连不上」才 503（其余回 503 只会让 compose 无限重启）。"""
    monkeypatch.setattr(db, "ping", lambda: False)
    r = client.get("/health")
    assert r.status_code == 503, r.text
    assert r.json()["status"] == "down"


def test_探针坏了不等于_down(client, monkeypatch):
    """探针**自己**炸了 ≠ 库连不上 ⇒ 不该报 `down`。"""
    monkeypatch.setattr(cache, "health", lambda: (_ for _ in ()).throw(RuntimeError("炸了")))
    body = client.get("/health").json()
    assert body["status"] != "down", body
    assert body["status"] == "degraded", body


def test_判据只有一处():
    """⚠️ 探针的兜底判据**只有一处**（`server._health_probe`）——
    别在别处再包一遍 try（那就是两份实现）。"""
    import inspect
    src = inspect.getsource(server._health_checks)
    assert "_health_probe(" in src
    # 旧的散装 try 只剩「读配置」那一处（第 251 期立的，有注释说明）
    assert src.count("except Exception:") <= 2, src.count("except Exception:")
