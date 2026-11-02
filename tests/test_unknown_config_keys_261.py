"""**不认识的配置键**要报出来（第 261 期）。

## 缺陷

config.yaml 里写了一个**不存在的键**（最常见是**拼错**）⇒ 那个设置
**静默失效**：

- 用户写 `watcher.interva: 999`（而不是 `watcher.interval`）⇒
  生效的是**默认值 5.0**；
- `config_error()` 是**空的**、`/health` **全绿**、设置页回显的也是默认值
  ⇒ **用户完全看不出来自己拼错了**；
- 而 `load_config()` 把那个键**照抄**进 `data`（`data[k] = v`）⇒ 它躺在配置里
  **无人消费也无人提示**。

⇒ 这正是本仓最忌讳的「假配置」形态：**写下了 ≠ 生效了，也没人说**。

## 这里钉四件事

1. **拼错的键被认出来**（顶层键与段的直接子键）；
2. **结构型**的键**不许误报**（`metadata_fetch.fields` 是一整张映射、
   `network.host_replace` 是用户自定的键值对、`watcher.ignore` 是模式列表
   ⇒ 它们的「子键」本来就没有固定名单 ⇒ 递归判会误报一大片）；
3. **两个来源**都算（config.yaml 与 settings.json）；
4. **不被丢掉**（那些键仍然进 `data`，不破坏任何东西）—— 本期只**报出来**。
"""
from __future__ import annotations

import pytest

from novelforge import config


@pytest.fixture
def own_cfg(tmp_path, monkeypatch):
    """把 config.yaml / settings.json 指到用例专属目录（会话级共享 ⇒ 会互相污染）。"""
    d = tmp_path / "cfg"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CONFIG_DIR", d)
    monkeypatch.setattr(config, "CONFIG_FILE", d / "config.yaml")
    monkeypatch.setattr(config, "SETTINGS_FILE", d / "settings.json")
    return d


def _write(d, text: str) -> None:
    (d / "config.yaml").write_text(text, encoding="utf-8")


# ---------------- ① 拼错的键被认出来 ----------------

def test_拼错的子键被认出来(own_cfg):
    _write(own_cfg, "watcher:\n  interva: 999\n")
    config.load_config()
    assert config.unknown_config_keys() == ["watcher.interva"], config.unknown_config_keys()


def test_不认识的顶层键被认出来(own_cfg):
    _write(own_cfg, "my_unknown_key: 42\n")
    config.load_config()
    assert config.unknown_config_keys() == ["my_unknown_key"], config.unknown_config_keys()


def test_拼错的键_设置静默失效(own_cfg):
    """⚠️ 本期要修的**症状**：写错了 ⇒ 生效的是默认值，而**零提示**。"""
    _write(own_cfg, "watcher:\n  interva: 999\n")
    cfg = config.load_config()
    assert cfg["watcher"]["interval"] == config.DEFAULTS["watcher"]["interval"], \
        "拼错的键本来就不生效（这是前提）"
    # 而现在**报出来了** ⇒ 用户查得到原因
    assert config.unknown_config_keys() == ["watcher.interva"]


# ---------------- ② 结构型的键不许误报 ----------------

@pytest.mark.parametrize("label,text", [
    ("metadata_fetch.fields（一整张映射）",
     "metadata_fetch:\n  fields:\n    title: overwrite\n    author: overwrite\n"),
    ("network.host_replace（用户自定的键值对）",
     "network:\n  host_replace:\n    old.com: new.com\n"),
    ("watcher.ignore（模式列表）",
     "watcher:\n  ignore: ['*.tmp', 'x']\n"),
    ("logging.retention（一层子段）",
     "logging:\n  retention:\n    enabled: true\n    keep: 3\n"),
])
def test_结构型的键不误报(own_cfg, label, text):
    _write(own_cfg, text)
    config.load_config()
    assert config.unknown_config_keys() == [], f"{label} 被误报了：{config.unknown_config_keys()}"


# ---------------- ③ 两个来源都算 ----------------

def test_settings_json_里的陌生键也算(own_cfg):
    (own_cfg / "settings.json").write_text(
        '{"metadata_fetch": {"cache_ttl": 30, "typo_key": 1}}', encoding="utf-8")
    config.load_config()
    assert config.unknown_config_keys() == ["metadata_fetch.typo_key"], \
        config.unknown_config_keys()


def test_正常配置不报(own_cfg):
    _write(own_cfg, "watcher:\n  enabled: false\n  interval: 9\n"
                    "logging:\n  max_entries: 100\n")
    config.load_config()
    assert config.unknown_config_keys() == [], config.unknown_config_keys()


# ---------------- ④ 不被丢掉 ----------------

def test_不认识的键不被丢掉(own_cfg):
    """⚠️ 本期只**报出来**，**不删** —— 删了可能破坏「未来版本新增的键」
    这类**向前兼容**的用法（老版本读不懂新键，但不该把它扔了）。"""
    _write(own_cfg, "my_unknown_key: 42\n")
    cfg = config.load_config()
    assert cfg.get("my_unknown_key") == 42, cfg.get("my_unknown_key")


# ---------------- 接口层：报出来 ----------------

def test_接口层报出陌生键(client, auth_headers, own_cfg):
    _write(own_cfg, "watcher:\n  interva: 999\n")
    config.load_config()
    body = client.get("/api/config", headers=auth_headers).json()
    assert body["config"]["_unknown_keys"] == ["watcher.interva"], body["config"]


def test_health的problems里说得出(client, auth_headers, own_cfg):
    _write(own_cfg, "watcher:\n  interva: 999\n")
    config.load_config()
    body = client.get("/api/health", headers=auth_headers).json()
    assert any("interva" in p for p in body["problems"]), body["problems"]
