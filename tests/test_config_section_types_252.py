"""**配置的段类型写坏** ⇒ 服务要还能起来（第 252 期）。

## 缺陷

`config.yaml` 里某个**顶层段**被写成别的类型（典型：`watcher: "abc"`）时：

- `config.load_config()` 把那个字符串**整个塞进** `data["watcher"]`；
- 后续 `data.setdefault("watcher", {})["enabled"] = …` 抛 `TypeError`；
- `(cfg.get("watcher") or {}).get(...)` 抛 `AttributeError`；

⇒ `load_config()` **抛** ⇒ **每个 API 都 500**（每个 API 都调它），
**连启动路径都抛**（`server.lifespan` 里那句 `(cfg.get("watcher") or {}).get(...)`）
⇒ **容器根本起不来**。自愈路径只剩「手改 config.yaml」。

实测（本轮）：`LOAD RAISED: AttributeError 'str' object has no attribute 'get'`。

## 这里钉三件事

1. **读路径降级**：段类型不对 ⇒ 该段回默认值、**其余段照旧**、`load_config()` **不抛**；
2. **写入口拦**：`PUT /api/config/raw` 拒掉写坏的段（400 + 说清是哪个段）——
   坏配置**不该**能从界面上写进去；
3. **如实留证**：降级要**看得见**（`/health` 的 `problems` + `checks.bad_sections`、
   `GET /api/config` 的 `_bad_sections`）—— 否则用户以为自己的设置还在。
"""
from __future__ import annotations

import pathlib

import pytest

from novelforge import config


@pytest.fixture
def own_cfg(tmp_path, monkeypatch):
    """把 config.yaml 指到**本用例专属**目录（会话级共享 ⇒ 会互相污染）。"""
    own = tmp_path / "cfg"
    own.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CONFIG_DIR", own)
    monkeypatch.setattr(config, "CONFIG_FILE", own / "config.yaml")
    monkeypatch.setattr(config, "SETTINGS_FILE", own / "settings.json")
    return own


def _write(own: pathlib.Path, text: str) -> None:
    (own / "config.yaml").write_text(text, encoding="utf-8")


# ---------------- ① 读路径：降级而不是抛 ----------------

def test_段类型写坏_读路径不抛(own_cfg):
    """核心判据：`load_config()` **不许抛**（抛 ⇒ 每个 API 500 + 服务起不来）。"""
    _write(own_cfg, 'watcher: "abc"\n')
    cfg = config.load_config()          # 此前抛 AttributeError
    assert isinstance(cfg.get("watcher"), dict), cfg.get("watcher")


def test_段类型写坏_该段回默认值(own_cfg):
    _write(own_cfg, 'watcher: "abc"\n')
    cfg = config.load_config()
    # ⚠️ `enabled` 会被环境变量（`AUTO_WATCH`）在降级**之后**再覆盖一次
    # ⇒ 不断言它的具体值，只断言「该段是默认值那份」的其余键。
    assert cfg["watcher"]["interval"] == config.DEFAULTS["watcher"]["interval"]
    assert cfg["watcher"]["ignore"] == config.DEFAULTS["watcher"]["ignore"]


def test_段类型写坏_其余段照旧(own_cfg):
    """降级**只影响坏的那一段** —— 别把整个文件都丢了。"""
    _write(own_cfg, 'watcher: "abc"\nlogging:\n  max_entries: 77\n')
    cfg = config.load_config()
    assert cfg["logging"]["max_entries"] == 77, cfg["logging"]


def test_段类型写坏_启动路径不抛(own_cfg, monkeypatch):
    """`server.lifespan` 里那句 `(cfg.get("watcher") or {}).get("enabled", True)`
    此前直接抛 ⇒ **容器起不来**。这里照抄那句，钉住它不抛。"""
    _write(own_cfg, 'watcher: "abc"\n')
    cfg = config.load_config()
    assert isinstance(bool((cfg.get("watcher") or {}).get("enabled", True)), bool)


def test_空段也要降级(own_cfg):
    """⚠️ YAML 里 `watcher:`（键下面什么都没有）解析出来是 **None**，
    而它**同样会抛**：`data.setdefault("watcher", {})["enabled"] = …` 对 None 抛 TypeError。

    而这恰恰是用户**最可能**写坏的方式（少写一个子键）。
    ⇒ 空段也必须降级，不能当成「没写」。
    """
    _write(own_cfg, "watcher:\n")
    cfg = config.load_config()          # 此前抛 TypeError
    assert isinstance(cfg.get("watcher"), dict), cfg.get("watcher")
    assert config.bad_sections() == ["watcher"], config.bad_sections()


def test_段类型写坏_降级要留证(own_cfg):
    """降级必须**看得见** —— 否则用户以为自己的设置还在。"""
    _write(own_cfg, 'watcher: "abc"\n')
    config.load_config()
    assert config.bad_sections() == ["watcher"], config.bad_sections()


def test_好配置_没有坏段(own_cfg):
    _write(own_cfg, "watcher:\n  enabled: false\n")
    config.load_config()
    assert config.bad_sections() == [], config.bad_sections()


def test_标量键写错不算坏段(own_cfg):
    """`traditionalize` 是**标量**键（不是段）⇒ 写错只是取值怪，不会抛 ⇒ 不算坏段。"""
    _write(own_cfg, "traditionalize: 3\n")
    config.load_config()
    assert config.bad_sections() == [], config.bad_sections()


# ---------------- ② 写入口：拒掉写坏的段 ----------------

def test_raw写入口_拒掉类型写坏的段(client, auth_headers, own_cfg):
    for text in ('watcher: "abc"\n', "watcher:\n", "watcher: [1, 2]\n"):
        r = client.put("/api/config/raw", headers=auth_headers, json={"text": text})
        assert r.status_code == 400, (text, r.status_code, r.text)
        assert "watcher" in r.text, r.text


def test_raw写入口_坏段没落到盘上(client, auth_headers, own_cfg):
    """被拒 ⇒ **文件没变**（否则用户改回来也没用）。"""
    r = client.put("/api/config/raw", headers=auth_headers, json={"text": 'watcher: "abc"\n'})
    assert r.status_code == 400, r.text
    assert not (own_cfg / "config.yaml").exists(), "被拒的配置不该落盘"


def test_raw写入口_好配置照旧能写(client, auth_headers, own_cfg):
    r = client.put("/api/config/raw", headers=auth_headers,
                   json={"text": "watcher:\n  enabled: false\n"})
    assert r.status_code == 200, r.text
    assert (own_cfg / "config.yaml").is_file()


def test_还原备份_拒掉段类型写坏的备份(client, auth_headers, own_cfg, monkeypatch):
    """**还原也是写入口** ⇒ 同一把闸。

    备份是 config.yaml 的**副本**，而 config.yaml 可能早就被写坏过（旧版本写入的 /
    手改的）⇒ 还原它 = 把坏配置再放回盘上。
    """
    import yaml
    backups_dir = own_cfg.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "BACKUP_DIR", backups_dir)
    (backups_dir / "config-bad.yaml").write_text(
        yaml.safe_dump({"watcher": "abc"}), encoding="utf-8")
    r = client.post("/api/config/restore", headers=auth_headers,
                    json={"name": "config-bad.yaml"})
    assert r.status_code == 400, r.text
    assert "watcher" in r.text, r.text
    assert not (own_cfg / "config.yaml").exists(), "被拒的还原不该落盘"


def test_还原备份_好备份照旧能还原(client, auth_headers, own_cfg, monkeypatch):
    import yaml
    backups_dir = own_cfg.parent / "backups"
    backups_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "BACKUP_DIR", backups_dir)
    (backups_dir / "config-ok.yaml").write_text(
        yaml.safe_dump({"watcher": {"enabled": False}}), encoding="utf-8")
    r = client.post("/api/config/restore", headers=auth_headers,
                    json={"name": "config-ok.yaml"})
    assert r.status_code == 200, r.text
    assert (own_cfg / "config.yaml").is_file()


# ---------------- ③ 接口层：如实回报 ----------------

def test_health_报出坏段(client, auth_headers, own_cfg):
    """`/health` 的 `problems` 里要**说得出**是哪个段。

    ⚠️ 只走 `problems`（**人话清单**），**不给 `checks` 加新字段** ——
    `/health` 是**免鉴权**端点，而 `tests/test_client_contract.py` 的「字段面快照」
    钉死了它的形状（多一个字段就红）⇒ 机器可读的那份放在**鉴权后**的
    `GET /api/config` 的 `_bad_sections`（见下一个用例）。
    """
    _write(own_cfg, 'watcher: "abc"\n')
    config.load_config()
    # ⚠️ 第 258 期：人话清单在**鉴权后**的端点上（免鉴权的那份只给条数）
    body = client.get("/api/health", headers=auth_headers).json()
    assert any("watcher" in p for p in body["problems"]), body["problems"]


def test_get_config_报出坏段(client, auth_headers, own_cfg):
    """机器可读的那份在**鉴权后**的 `GET /api/config._bad_sections`
    （`/health` 是免鉴权的 ⇒ 不在那里加字段，理由见上一个用例的注释）。"""
    _write(own_cfg, 'watcher: "abc"\n')
    config.load_config()
    body = client.get("/api/config", headers=auth_headers).json()
    assert body["config"]["_bad_sections"] == ["watcher"], body["config"]


def test_坏段时_api照样能用(client, auth_headers, own_cfg):
    """**服务还能用** —— 降级的意义就在这儿（此前是每个 API 都 500）。"""
    _write(own_cfg, 'watcher: "abc"\n')
    r = client.get("/api/config", headers=auth_headers)
    assert r.status_code == 200, r.text
