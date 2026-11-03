"""**兜底链**上的键要标出「当前值来自环境变量」（第 264 期）。

## 缺陷

`metadata_fetch.cache_ttl` / `detail_fetch` 的环境变量是**兜底**
（`NOVELFORGE_METADATA_CACHE_TTL` / `NOVELFORGE_METADATA_DETAIL_FETCH`）：
「没人写过的才用环境变量」。

但 `GET /api/config` 只回 `env_overridden` —— 那份列表只含
**无条件覆盖**的两个键（`AUTO_WATCH` / `WATCH_INTERVAL`，第 244 期）⇒
**兜底链上的两个键不在其中** ⇒ 界面**看不出**当前那个 `120` 是部署者设的、
还是用户自己设的。

⇒ 用户改完发现「没生效」⇒ **误判**（实际是自己没点保存、或被别的机制盖了）。

## 这里钉四件事

1. **只列「此刻真的由环境变量在供值」的**键（`env_fallback`）；
2. **用户已经特意改过** ⇒ **不列**（那个值是用户自己的，不是环境变量的）——
   误标比不标更糟；
3. **与 `env_overridden` 分开**（那是**无条件覆盖** ⇒ 界面**禁用**输入框；
   这里是**兜底** ⇒ 界面**不禁用**，只**标注**来源）；
4. **判据读的是「原始来源」**（settings.json / config.yaml），
   **不能**读 `load_config()` 的结果（那份**已经**把环境变量的值合进去了
   ⇒ 拿它判「用户改过没有」**逻辑自指**）。
"""
from __future__ import annotations

import pytest

from novelforge import config


@pytest.fixture
def env_on(monkeypatch, tmp_path):
    """设上那两个环境变量（部署者的口径），配置目录指到用例专属路径。"""
    d = tmp_path / "cfg"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CONFIG_DIR", d)
    monkeypatch.setattr(config, "CONFIG_FILE", d / "config.yaml")
    monkeypatch.setattr(config, "SETTINGS_FILE", d / "settings.json")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "true")
    return d


# ---------------- ① 只列真正由环境变量供值的 ----------------

def test_全新部署_两个键都在(env_on):
    out = config.env_fallback()
    assert "metadata_fetch.cache_ttl" in out, out
    assert "metadata_fetch.detail_fetch" in out, out


def test_没有环境变量_是空列表(monkeypatch, tmp_path):
    d = tmp_path / "cfg"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CONFIG_DIR", d)
    monkeypatch.setattr(config, "CONFIG_FILE", d / "config.yaml")
    monkeypatch.setattr(config, "SETTINGS_FILE", d / "settings.json")
    monkeypatch.delenv(config._ENV_CACHE_TTL, raising=False)
    monkeypatch.delenv(config._ENV_DETAIL_FETCH, raising=False)
    assert config.env_fallback() == [], config.env_fallback()


# ---------------- ② 用户特意改过 ⇒ 不列 ----------------

def test_用户改过_cache_ttl_就不列它(env_on):
    config.save_overrides({"metadata_fetch": {"cache_ttl": 999}})
    out = config.env_fallback()
    assert "metadata_fetch.cache_ttl" not in out, out
    assert "metadata_fetch.detail_fetch" in out, out


def test_用户改过_detail_fetch_就不列它(env_on):
    config.save_overrides({"metadata_fetch": {"detail_fetch": False}})
    out = config.env_fallback()
    assert "metadata_fetch.detail_fetch" not in out, out
    assert "metadata_fetch.cache_ttl" in out, out


def test_两个都改过_是空列表(env_on):
    config.save_overrides({"metadata_fetch": {"cache_ttl": 999, "detail_fetch": False}})
    assert config.env_fallback() == [], config.env_fallback()


# ---------------- ③ 与 env_overridden 分开 ----------------

def test_与无条件覆盖的那份分开(monkeypatch, tmp_path):
    """⚠️ 两类**必须**分开报：
    `env_overridden` = **无条件覆盖**（界面**禁用**输入框）·
    `env_fallback` = **兜底**（界面**不禁用**，只**标注**来源）。"""
    d = tmp_path / "cfg"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CONFIG_DIR", d)
    monkeypatch.setattr(config, "CONFIG_FILE", d / "config.yaml")
    monkeypatch.setattr(config, "SETTINGS_FILE", d / "settings.json")
    monkeypatch.setenv("AUTO_WATCH", "true")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    over = config.env_overridden()
    fall = config.env_fallback()
    assert "watcher.enabled" in over, over
    assert "metadata_fetch.cache_ttl" not in over, over
    assert "metadata_fetch.cache_ttl" in fall, fall
    assert "watcher.enabled" not in fall, fall


# ---------------- ④ 判据读原始来源（不是 load_config 的结果）----------------

def test_判据读原始来源而不是合并结果(env_on):
    """⚠️ 若读 `load_config()` 的结果 ⇒ 那份**已经**把环境变量的值合进去了
    ⇒ 拿它判「用户改过没有」**必然**是「改过」⇒ 逻辑自指（列表会永远是空）。"""
    # 环境变量的值合进了 load_config 的结果
    assert config.load_config()["metadata_fetch"]["cache_ttl"] == 120
    # 但「用户没写过」⇒ 仍在列表里
    assert "metadata_fetch.cache_ttl" in config.env_fallback(), config.env_fallback()


# ---------------- 接口层 ----------------

def test_接口下发_env_fallback(client, auth_headers, env_on):
    body = client.get("/api/config", headers=auth_headers).json()
    fb = body.get("env_fallback") or []
    assert "metadata_fetch.cache_ttl" in fb, fb
