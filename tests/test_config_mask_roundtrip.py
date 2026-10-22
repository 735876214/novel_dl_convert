"""第 138 期：`GET /api/config` 的**掩码回显**与 `PUT /api/config` 的写入必须互为逆向。

缺陷形态（完全静默的数据丢失）：回显侧把已保存的凭据换成 ``••••••••``，而前端保存时按
**分区整段回传**（`useSettingsConfig` 用 `SECTION_KEYS` 把 GET 回来的草稿原样拼进 patch），
于是掩码字符串被当成新值写进 settings.json，覆盖掉真密钥。此时 `has_<键名>` 仍为真、
界面照旧显示「已配置」，只有真去抓取时 401 才暴露 —— 而旧值已经不可恢复。

此前只有 `llm.api_key` 一家在 `_merge` 里做了「掩码 = 保持原值」，`metadata_fetch` 的
5 个 secret 与 `komga.api_key` 全都没有 ⇒ 用户在元数据页 / Komga 页点**任一开关**（开关
提交的正是整段草稿）就会丢密钥。这组用例把「回显 → 原样回传」这条真实链路走一遍。
"""
from __future__ import annotations

import pytest

from novelforge import config, server

#: 回显侧会掩码的键（每段挑代表）+ 期望能被「原样回传」保住的场景。
SECRET_CASES = [
    ("metadata_fetch", "googlebooks_api_key"),
    ("metadata_fetch", "hardcover_api_token"),
    ("metadata_fetch", "comicvine_api_key"),
    ("metadata_fetch", "aladin_ttbkey"),
    ("metadata_fetch", "amazon_cookie"),
    ("komga", "api_key"),
    ("llm", "api_key"),
]


@pytest.fixture()
def cfg_file(tmp_path, monkeypatch):
    f = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", f)
    return f


def _live(section: str, key: str) -> str:
    return str((config.load_config().get(section) or {}).get(key) or "")


def test_写入侧的凭据键清单与回显侧同源():
    """掩码判据只能有一份：写侧的键集必须覆盖 `metasources.secret_fields()`。"""
    from novelforge.core import metasources

    keys = server._secret_cfg_keys()
    missing = [k for k in metasources.secret_fields() if k not in keys]
    assert not missing, f"回显会掩码但写侧不认识：{missing}（掩码会被原样写回）"
    assert "api_key" in keys


@pytest.mark.parametrize("section,key", SECRET_CASES)
def test_原样回传掩码不会覆盖真密钥(client, auth_headers, cfg_file, section, key):
    secret = f"REAL-{section}-{key}-1234"
    r = client.put("/api/config", headers=auth_headers, json={section: {key: secret}})
    assert r.status_code == 200, r.text
    assert _live(section, key) == secret

    echoed = client.get("/api/config", headers=auth_headers).json()["config"][section]
    assert echoed[key] == server._KEY_MASK, f"{section}.{key} 应该被掩码回显"

    # 前端行为：把整段草稿（含掩码）原样 PUT 回去
    r = client.put("/api/config", headers=auth_headers, json={section: echoed})
    assert r.status_code == 200, r.text
    assert _live(section, key) == secret, (
        f"掩码被写回，{section}.{key} 的真密钥被覆盖成 {_live(section, key)!r}"
    )


def test_清空凭据键等于回落默认(client, auth_headers, cfg_file):
    """空串是「用户真的要清空」：覆盖层里该键必须消失（不是存一个空串、也不是保留旧值）。"""
    client.put("/api/config", headers=auth_headers,
               json={"komga": {"api_key": "REAL-komga-key"}})
    assert _live("komga", "api_key") == "REAL-komga-key"
    r = client.put("/api/config", headers=auth_headers, json={"komga": {"api_key": ""}})
    assert r.status_code == 200, r.text
    assert _live("komga", "api_key") == ""


def test_非凭据键的空串照旧落库(client, auth_headers, cfg_file):
    """`update.image` 空串 = 回落环境变量 / 内置默认，是**有语义**的值，不能被当成「清空」吞掉。"""
    r = client.put("/api/config", headers=auth_headers,
                   json={"update": {"image": "ghcr.io/a/b:1"}})
    assert r.status_code == 200, r.text
    r = client.put("/api/config", headers=auth_headers, json={"update": {"image": ""}})
    assert r.status_code == 200, r.text
    ov = config.load_overrides()
    assert (ov.get("update") or {}).get("image", "MISSING") == ""


def test_掩码常量只有一处定义():
    """`_KEY_MASK` 是掩码字面量的唯一真值源；前端只在展示层出现同一个串。"""
    src = (server.__file__ and __import__("pathlib").Path(server.__file__).read_text(encoding="utf-8"))
    assert src.count('_KEY_MASK = "') == 1
