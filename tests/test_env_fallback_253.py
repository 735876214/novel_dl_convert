"""**环境变量的兜底**不许被自己的界面废掉（第 253 期）。

## 缺陷

`metadata_fetch.cache_ttl` / `detail_fetch` 的环境变量是**兜底**
（`NOVELFORGE_METADATA_CACHE_TTL` / `NOVELFORGE_METADATA_DETAIL_FETCH`）：
「没人写过才用环境变量」。

而此前「**人写过**」的判据是 **`"cache_ttl" not in written`** ——
**只要键存在就算「人写过」**。可是**应用自己也会写下这些键**：

1. `POST /api/config/reset` 把 `DEFAULTS` 整份序列化进 config.yaml
   ⇒ 里面带着 `cache_ttl: null` / `detail_fetch: false`；
2. 设置页保存「元数据」分区时提交**整段** `metadata_fetch`
   （`SECTION_KEYS.metadata` = `['metadata_fetch', 'metadata_score']`），
   而回显里这两个键装的是**环境变量算出来的值** ⇒ 用户点一次「保存」，
   那个值就被**当成了用户的选择**写进 settings.json。

⇒ **环境变量被自己的界面废掉**，而且界面上看不出任何异常：

| 场景 | 期望 | 修前实测 |
|---|---|---|
| 全新部署 env=120/true | (120, True) | (120, True) ✔ |
| 「重置配置」之后 | (120, True) | **(None, False)** ✘ |
| 设置页保存元数据分区后，运维改 env=300/false | (300, False) | **(120, True)** ✘ |

## 这里钉四件事

1. **「人写过」= 值真的被改过**（不是「键在不在」）；
2. **应用自己写下的那份**（reset 写进 config.yaml 的默认值）**不算「人写过」**；
3. **回显带回来的环境变量值**不许被存进覆盖层（写入口丢掉它）；
4. **用户真的改了**（`0` = 关闭缓存 / 别的值）**照旧压过环境变量** ——
   否则设置页那两个控件就成了假交互。
"""
from __future__ import annotations

import pytest
import yaml

from novelforge import config


@pytest.fixture
def env_cache(monkeypatch):
    """设上那两个环境变量（部署者的口径）。"""
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "true")
    return config.load_config()


def _mf() -> tuple:
    mf = config.load_config()["metadata_fetch"]
    return mf.get("cache_ttl"), mf.get("detail_fetch")


def _reset_dump() -> str:
    """`POST /api/config/reset` 写进 config.yaml 的那份内容（DEFAULTS 序列化）。"""
    return yaml.safe_dump(config.DEFAULTS, allow_unicode=True, sort_keys=False)


# ---------------- ① 读路径：判据是「值被改过」 ----------------

def test_全新部署_环境变量兜底(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "true")
    assert _mf() == (120, True), _mf()


def test_重置配置之后_环境变量仍然兜底(monkeypatch, tmp_path):
    """⚠️ **本期的核心判据**。

    「重置配置」把 DEFAULTS 整份写进 config.yaml ⇒ 里面带着
    `cache_ttl: null` / `detail_fetch: false` ⇒ 修前那两个键**从此不再兜底**。
    """
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "true")
    (tmp_path / "config.yaml").write_text(_reset_dump(), encoding="utf-8")
    assert _mf() == (120, True), _mf()


def test_保存设置页整段之后_环境变量仍然兜底(client, auth_headers, monkeypatch, tmp_path):
    """设置页保存「元数据」分区时提交**整段** `metadata_fetch`
    （回显里装的就是环境变量算出来的值）⇒ 那个值**不是用户的选择**。

    ⚠️ 判据必须**改掉环境变量再看**：光看「保存后还是不是 120」**分辨不出来**
    （存进去的也是 120，读出来当然还是 120）—— 真正的症状是
    **运维后来改环境变量不再生效**（那个 120 被冻住了）。

    ⚠️ 走**真的写入口**（`PUT /api/config`）—— 写入口会把「只是回显回来的」
    那个值丢掉（见 `server._drop_env_echo`）；直接 `save_overrides` 绕过了它。
    """
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "true")
    echoed = dict(client.get("/api/config", headers=auth_headers).json()["config"]["metadata_fetch"])
    r = client.put("/api/config", headers=auth_headers, json={"metadata_fetch": echoed})
    assert r.status_code == 200, r.text
    # 运维改环境变量（容器编排里改 env 后重启是常规操作）
    monkeypatch.setenv(config._ENV_CACHE_TTL, "300")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "false")
    assert _mf() == (300, False), _mf()


def test_没有环境变量时_默认值照旧(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.delenv(config._ENV_CACHE_TTL, raising=False)
    monkeypatch.delenv(config._ENV_DETAIL_FETCH, raising=False)
    assert _mf() == (None, False), _mf()


# ---------------- ② 用户的明确选择必须压过环境变量 ----------------

def test_用户设了真值_压过环境变量(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "true")
    config.save_overrides({"metadata_fetch": {"cache_ttl": 999, "detail_fetch": True}})
    assert _mf() == (999, True), _mf()


def test_零是关闭缓存_压过环境变量(monkeypatch, tmp_path):
    """`cache_ttl=0` = 关闭缓存（**与「没设」是两件事**）⇒ 环境变量不得插手。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    config.save_overrides({"metadata_fetch": {"cache_ttl": 0}})
    assert config.load_config()["metadata_fetch"]["cache_ttl"] == 0


def test_用户关了_detail_fetch_压过环境变量(monkeypatch, tmp_path):
    """`detail_fetch` 默认是 `False`，而环境变量可能把它设成 `True`
    ⇒ 存着 `False` 有两种含义（「没人设过」/「用户特意关掉」）⇒ 都要判成「用户写过」。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "true")
    config.save_overrides({"metadata_fetch": {"detail_fetch": False}})
    assert config.load_config()["metadata_fetch"]["detail_fetch"] is False

def test_覆盖层优先级_高于_config_yaml(monkeypatch, tmp_path):
    """⚠️ settings.json（用户写的）**高于** config.yaml。

    修前收集「人写过的值」时顺序是 `(load_overrides(), file_sec)` ⇒ **config.yaml
    后写、优先级反而更高** ⇒ 「重置配置」留在 config.yaml 里的 `cache_ttl: null`
    把用户在 settings.json 里写的 `0` **盖掉**。
    """
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    (tmp_path / "config.yaml").write_text(_reset_dump(), encoding="utf-8")
    config.save_overrides({"metadata_fetch": {"cache_ttl": 0}})
    assert config.load_config()["metadata_fetch"]["cache_ttl"] == 0, \
        "settings.json 里用户写的 0 被 config.yaml 里的 null 盖掉了"


# ---------------- ③ 写入口：回显带回来的值不许被存成「用户的选择」 ----------------

def test_写入口_丢掉与环境变量相同的值(client, auth_headers, monkeypatch, tmp_path):
    """保存整段时，那个「只是回显回来的」环境变量值**不许**被存进覆盖层
    —— 否则运维后来改环境变量就不再生效。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    monkeypatch.setenv(config._ENV_DETAIL_FETCH, "true")
    echoed = dict(config.load_config()["metadata_fetch"])
    r = client.put("/api/config", headers=auth_headers, json={"metadata_fetch": echoed})
    assert r.status_code == 200, r.text
    stored = (config.load_overrides().get("metadata_fetch") or {})
    assert "cache_ttl" not in stored, stored
    assert "detail_fetch" not in stored, stored


def test_写入口_用户改成别的值照旧写入(client, auth_headers, monkeypatch, tmp_path):
    """用户**改了**值 ⇒ 必须写进去（意图不能丢）。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setenv(config._ENV_CACHE_TTL, "120")
    r = client.put("/api/config", headers=auth_headers,
                   json={"metadata_fetch": {"cache_ttl": 999}})
    assert r.status_code == 200, r.text
    assert (config.load_overrides().get("metadata_fetch") or {}).get("cache_ttl") == 999


def test_写入口_没有环境变量时照旧写入(client, auth_headers, monkeypatch, tmp_path):
    """没有环境变量 ⇒ 没什么可丢的 ⇒ 值照旧存进去。"""
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.delenv(config._ENV_CACHE_TTL, raising=False)
    r = client.put("/api/config", headers=auth_headers,
                   json={"metadata_fetch": {"cache_ttl": 300}})
    assert r.status_code == 200, r.text
    assert (config.load_overrides().get("metadata_fetch") or {}).get("cache_ttl") == 300
