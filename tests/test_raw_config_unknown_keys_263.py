"""**直接写 config.yaml 原文**时，不认识的键要**当场**说出来（第 263 期）。

## 缺陷

`PUT /api/config/raw`（设置页 → 高级 → 「直接编辑 config.yaml 原文」）让用户
**手写整个配置文件** ⇒ 最容易打错键名（`watcher.interva` 而不是
`watcher.interval`）⇒ 而那个键**不会被任何读点消费** ⇒ **写了等于没写**。

但回执只说「已保存（已备份为 xxx）」⇒ 用户**当场不知道**自己打错了
⇒ 得等下一次在设置页看到「配置里有不认识的键」红条才反应过来
（而那条红条说的是**配置里**有陌生键，不是「你刚写的那一条」）。

## 这里钉三件事

1. 写完**立刻**回执里带上**那些键**（`unknown_keys`）；
2. **不拒**（与「段类型不对」刻意不同）：那个会让服务起不来 ⇒ 必须拒；
   这个只是**惰性**，而且**写进去的是用户自己写的原文**（可能含**本版本还不认识**
   的键 ⇒ 那是**向前兼容**的用法，不该拦）；
3. 正常配置（没有陌生键）⇒ 回执里那个字段是**空列表**（形状恒定）。
"""
from __future__ import annotations

import pytest

from novelforge import config


@pytest.fixture
def own_cfg(tmp_path, monkeypatch):
    """把 config.yaml 指到用例专属目录（会话级共享 ⇒ 会互相污染）。"""
    d = tmp_path / "cfg"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CONFIG_DIR", d)
    monkeypatch.setattr(config, "CONFIG_FILE", d / "config.yaml")
    monkeypatch.setattr(config, "SETTINGS_FILE", d / "settings.json")
    return d


def test_写坏了的键_当场回执里说出来(client, auth_headers, own_cfg):
    r = client.put("/api/config/raw", headers=auth_headers,
                   json={"text": "watcher:\n  interva: 999\n"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unknown_keys"] == ["watcher.interva"], body


def test_不认识的顶层键也说出来(client, auth_headers, own_cfg):
    r = client.put("/api/config/raw", headers=auth_headers,
                   json={"text": "my_unknown: 42\n"})
    assert r.status_code == 200, r.text
    assert r.json()["unknown_keys"] == ["my_unknown"], r.json()


def test_正常配置_那个字段是空列表(client, auth_headers, own_cfg):
    """⚠️ 形状**恒定**（成功时也给空列表）⇒ 前端只读一处判据。"""
    r = client.put("/api/config/raw", headers=auth_headers,
                   json={"text": "watcher:\n  enabled: false\n  interval: 9\n"})
    assert r.status_code == 200, r.text
    assert r.json()["unknown_keys"] == [], r.json()


def test_不认识的键_照样写得进去(client, auth_headers, own_cfg):
    """⚠️ **不拒** —— 写进去的是用户自己写的原文（可能是**本版本还不认识**的键
    ⇒ 那是**向前兼容**的用法，不该拦）。"""
    text = "my_future_key: 42\n"
    r = client.put("/api/config/raw", headers=auth_headers, json={"text": text})
    assert r.status_code == 200, r.text
    assert (own_cfg / "config.yaml").read_text(encoding="utf-8") == text


def test_段类型不对_仍然拒_那是另一回事(client, auth_headers, own_cfg):
    """⚠️ **与「段类型不对」刻意不同**：那个会让**服务起不来** ⇒ **必须拒**；
    不认识的键只是**惰性** ⇒ 只报不拒。"""
    r = client.put("/api/config/raw", headers=auth_headers,
                   json={"text": 'watcher: "abc"\n'})
    assert r.status_code == 400, r.text
