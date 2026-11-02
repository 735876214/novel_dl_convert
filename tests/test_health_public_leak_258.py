"""**免鉴权的 `/health` 不许泄露内部事实**（第 258 期）。

## 缺陷

`/health` 是**免鉴权**端点（登录前的预检就靠它）⇒ 任何人都能拿到它的响应。
而它此前把**内部事实**全发出去：

| 泄露的 | 为什么算「内部事实」 |
|---|---|
| `input` / `output` / `logs` | NAS 上的**绝对路径**（收书 / 导出 / 日志目录在哪儿） |
| `checks.default_pin` | **账号是不是还在用初始口令** `changeme`（局域网 8992 直通时这是安全信息） |
| `checks.cache` | 有没有配 Redis（部署形态） |
| `problems` | 带**绝对路径**的人话清单（配置目录、目录建不出来…） |

⇒ 任何人（**不用登录**）都能拿到这些。

## 这里钉四件事

1. **免鉴权的响应里没有**绝对路径；
2. **免鉴权的响应里没有** `default_pin` / `cache` 这类内部事实；
3. **`problems` 只给条数**（人话清单在鉴权后的端点上）；
4. **完整快照在鉴权后的 `GET /api/health`**，且**读的是同一份判据**
   （`_health_checks()`，不另算一份 —— 各算一遍就会漂）。
"""
from __future__ import annotations

import json


def _flat(obj, prefix: str = "") -> set[str]:
    """把响应压成键路径集合（与客户端契约那套同一手法）。"""
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.add(p)
            out |= _flat(v, p)
    elif isinstance(obj, list):
        p = f"{prefix}[]"
        out.add(p)
        if obj:
            out |= _flat(obj[0], p)
    return out


def test_免鉴权的health_不给绝对路径(client):
    """⚠️ 核心判据：**任何人**（不用登录）都不能拿到 NAS 的目录结构。"""
    body = client.get("/health").json()
    blob = json.dumps(body, ensure_ascii=False)
    for frag in ("input", "output", "logs"):
        assert frag not in _flat(body), f"免鉴权响应里不该有「{frag}」：{sorted(_flat(body))}"
    # 路径形态的字符串也不该出现（Windows 盘符 / POSIX 绝对路径）
    assert ":\\" not in blob, blob[:300]
    assert "/app/" not in blob, blob[:300]


def test_免鉴权的health_不给内部事实(client):
    """`default_pin`（还在用默认口令？）与 `cache`（有没有 Redis）都是内部事实。"""
    paths = _flat(client.get("/health").json())
    assert not any(p.startswith("checks.") for p in paths), sorted(paths)
    assert "checks.default_pin" not in paths
    assert "checks.cache" not in paths


def test_免鉴权的health_只给条数不给人话清单(client):
    """`problems` 的人话带**绝对路径** ⇒ 只给条数。"""
    body = client.get("/health").json()
    assert "problems" not in body, body
    assert isinstance(body.get("problem_count"), int), body


def test_免鉴权的health_仍给前端要的那几样(client):
    """⚠️ **不能把前端要的东西也一起砍掉** ——
    侧栏（免鉴权）要 `version`（版本号 / 更新提示）、`updater_available`（能不能一键更新）。"""
    body = client.get("/health").json()
    assert {"status", "version"} <= set(body), sorted(body)
    assert "updater_available" in body, sorted(body)


def test_鉴权后有完整快照(client, auth_headers):
    """那些内部事实**挪到鉴权后**（不是删掉）。"""
    r = client.get("/api/health", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert {"status", "version", "checks", "problems", "input", "output", "logs"} <= set(body), \
        sorted(body)
    assert "default_pin" in body["checks"], body["checks"]
    assert body["input"], body


def test_两个端点读同一份判据(client, auth_headers):
    """⚠️ 公共端点与鉴权端点**读的是同一份** `_health_checks()`
    —— 各算一遍就会漂（两个端点对同一件事给出不同结论）。"""
    pub = client.get("/health").json()
    det = client.get("/api/health", headers=auth_headers).json()
    assert pub["status"] == det["status"], (pub["status"], det["status"])
    assert pub["problem_count"] == len(det["problems"]), (pub, det)


def test_鉴权端点需要登录(client):
    """⚠️ 完整快照**必须鉴权**（免鉴权拿它等于没改）。"""
    r = client.get("/api/health")
    assert r.status_code in (401, 403), r.status_code
