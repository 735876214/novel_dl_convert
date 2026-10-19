"""第 120 期逻辑审计的两条修复 —— **接口级契约**（零网络）。

本轮盯的是第二类缺陷：**「看起来成功、实际没发生 / 发生了却不该发生」**。

## 一、书源名就是文件名（两个落盘文件的主干）

`SOURCES_DIR/<name>.json`（规则本体）与 `COOKIE_DIR/<name>.cookies.txt`（登录态）都用
书源名当主干，而此前 `name` **没有任何校验**。实测（探针）：

    add_rule({"name": "../../evil", ...})   # → CONFIG_DIR/evil.json（sources 目录之外！）

后果有两条，都不报错：

1. `load_user_sources()` 只扫 `SOURCES_DIR/*.json` ⇒ 重启后这条源**凭空消失**，
   用户会以为「导入了但没生效」；
2. `name = "../settings"` 会**覆盖 settings.json 覆盖层**（集成凭据 / 更新镜像全在里面）。

本轮的落点：名字判据收敛到 `rules.rule_name_error()`，路径收敛到 `rules.rule_file_path()`
（此前 8 处各拼一遍），三个入口（`validate_rule` / `register_rule` / `add_rule`）都过闸。

## 二、设置覆盖层「写不进去还回 ok」

`config.save_overrides()` 此前 `except Exception: pass` + 直接 `open(..., "w")`：

- 磁盘满 / 只读挂载 / 配置目录没权限 ⇒ 四个写接口仍回 `{"ok": true}`，界面显示「已保存」，
  重启后设置全没了（本项目最忌讳的「静默写不进」）；
- 写一半断电 ⇒ 半截 JSON ⇒ 下次启动读不出来 ⇒ **全部设置静默回默认值**。

现在：原子落盘（临时文件 + `os.replace`）、失败**抛 OSError**（接口据实回 500）、
读不出来时把文件改名留档（`settings.json.corrupt-<ts>`）并打日志，
四条写入口统一走 `config.mutate_overrides()`（同一把锁，避免并发保存互相抹键）。
"""
import json
import os
import pathlib
import threading

import pytest

from novelforge import config
from novelforge.core import customfields
from novelforge.sources import base, rules, store

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _rule(name) -> dict:
    """一条能过 `validate_rule` 的最小规则。"""
    return {
        "name": name,
        "domains": ["example.com"],
        "search": {"url": "https://example.com/s?q={title}", "mode": "css", "container": "li"},
    }


@pytest.fixture(autouse=True)
def _clean_sources(isolated):                                # noqa: ARG001
    """每个用例前清空书源目录与 REGISTRY（与 `test_source_import_api.py` 同口径）。"""
    d = pathlib.Path(config.SOURCES_DIR)
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob("*.json"):
        p.unlink()
    before = set(base.REGISTRY)
    yield
    for name in set(base.REGISTRY) - before:
        base.REGISTRY.pop(name, None)


# ---------------- 一、书源名 = 文件名 ----------------

@pytest.mark.parametrize("bad", ["../evil", "a/b", "a\\b", "..", ".hidden", "x" * 81])
def test_非法书源名写盘前就被拒(bad):
    """带路径分隔符 / `..` / 隐藏前缀 / 超长的名字一律拒绝，且**盘上什么都不留**。"""
    with pytest.raises(ValueError) as ei:
        store.add_rule(_rule(bad))
    assert "name" in str(ei.value)

    # 关键：不能有文件被写到 SOURCES_DIR 之外（历史缺陷就落在这里）
    cfg_dir = pathlib.Path(config.CONFIG_DIR)
    stray = [p for p in cfg_dir.rglob("*.json") if p.name != "settings.json"]
    assert stray == [], f"书源名穿越写出了目录外的文件：{stray}"
    assert list(pathlib.Path(config.SOURCES_DIR).glob("*.json")) == []


def test_validate_rule_把名字问题报成导入错误():
    """导入界面要能看见原因 —— 判据与写入口是同一份（`rule_name_error`）。"""
    errs = rules.validate_rule(_rule("../evil"))
    assert errs and "name" in errs[0]
    assert rules.validate_rule(_rule("我的源")) == []


def test_合法中文书源名照旧落盘():
    """收紧不能误伤正常名字（中文 / 空格 / emoji 都该能用）。"""
    path = store.add_rule(_rule("我的 源📚"))
    assert path == pathlib.Path(config.SOURCES_DIR) / "我的 源📚.json"
    assert path.is_file()
    assert json.loads(path.read_text(encoding="utf-8"))["name"] == "我的 源📚"
    assert "我的 源📚" in base.REGISTRY


def test_注册也拦坏名字():
    """手改过的规则文件 / 历史遗留的坏名字在注册处就被拒（否则 cookie 路径会跑出目录）。"""
    with pytest.raises(ValueError):
        store.register_rule(_rule("../evil"))


def test_规则文件名只有一个构造处():
    """静态契约：除了 `sources/rules.py`，谁都不许自己拼 `SOURCES_DIR/<name>.json`。

    这条盯的是「第二份实现」—— 本轮之前有 8 处各拼一遍，其中 store 的那处
    直接成了穿越入口（`SOURCES_DIR / f"{name}.json"` 里 `..` 会往上走）。
    """
    offenders = []
    for f in sorted((ROOT / "novelforge").rglob("*.py")):
        if f.name == "rules.py":
            continue
        text = f.read_text(encoding="utf-8")
        if '.json"' in text and "{name}.json" in text:
            offenders.append(str(f.relative_to(ROOT)))
    assert offenders == [], f"这些文件又在自己拼书源规则路径了：{offenders}"


# ---------------- 二、设置覆盖层 ----------------

@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """把 `SETTINGS_FILE` 挪进 tmp_path（`isolated` 已把 CONFIG_DIR 指过去，
    这里再独立一层，避免与别的用例共用一个文件）。"""
    p = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_FILE", p)
    return p


def test_写盘失败要抛异常不再假装成功(settings_file):
    """`settings.json` 被一个**目录**占住 ⇒ `os.replace` 必然失败 ⇒ 必须抛 OSError。

    历史行为是 `except Exception: pass`，接口照样回 `{"ok": true}`。
    """
    settings_file.mkdir()                       # 用目录占位：open 能写 tmp，replace 必失败
    with pytest.raises(OSError):
        config.save_overrides({"a": 1})
    # 临时文件不能留在配置目录里（它会出现在「配置备份 / 还原」的清单里）
    assert not (settings_file.parent / (settings_file.name + ".tmp")).exists()


def test_设置写入是原子的(settings_file, monkeypatch):
    """先落临时文件再 replace：replace 失败时**旧内容一个字节都不变**。"""
    config.save_overrides({"keep": 1})
    before = settings_file.read_text(encoding="utf-8")

    def _boom(*a, **k):
        raise OSError("模拟断电 / 只读挂载")

    monkeypatch.setattr(os, "replace", _boom)
    with pytest.raises(OSError):
        config.save_overrides({"keep": 2})
    assert settings_file.read_text(encoding="utf-8") == before
    assert not (settings_file.parent / (settings_file.name + ".tmp")).exists()


def test_损坏的覆盖层会留档而不是静默清空(settings_file, caplog):
    """读不出来 ⇒ 改名留档 + 打日志 + 按空覆盖层继续（设置页仍能打开）。"""
    settings_file.write_text("{ 这不是 JSON", encoding="utf-8")
    with caplog.at_level("WARNING"):
        assert config.load_overrides() == {}
    kept = list(settings_file.parent.glob("settings.json.corrupt-*"))
    assert len(kept) == 1, "坏文件必须留档，否则用户的凭据 / 开关就真的没了"
    assert "这不是 JSON" in kept[0].read_text(encoding="utf-8")
    assert not settings_file.exists()
    assert any("覆盖层读不出来" in r.message for r in caplog.records)


def test_并发保存不丢更新(settings_file):
    """「读—改—写」必须串行：两个线程各加 25 次，结果必须正好 50。

    没有锁时后写的那份会用自己读到的旧值覆盖先写的 —— 表现为「连着点两下保存，
    第一处设置撤回去了」，而且不报错。
    """
    config.save_overrides({"counter": 0})

    def _bump():
        for _ in range(25):
            config.mutate_overrides(
                lambda ov: ov.__setitem__("counter", int(ov.get("counter") or 0) + 1))

    ts = [threading.Thread(target=_bump) for _ in range(2)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert config.load_overrides()["counter"] == 50


def test_迁移删旧键不碰无关的键(settings_file):
    """`drop_legacy_override()` 走锁内读—改—写：只摘 `metadata_fetch.custom_fields`。"""
    config.save_overrides({"llm": {"model": "x"},
                           "metadata_fetch": {"cache_ttl": 10, "custom_fields": [{"name": "a"}]}})
    assert customfields.drop_legacy_override() is True
    ov = config.load_overrides()
    assert "custom_fields" not in ov["metadata_fetch"]
    assert ov["metadata_fetch"]["cache_ttl"] == 10           # 同段其它键不动
    assert ov["llm"] == {"model": "x"}                       # 别的段一个都不动
    # 没有可删的键时连盘都不碰
    before = settings_file.stat().st_mtime_ns
    assert customfields.drop_legacy_override() is False
    assert settings_file.stat().st_mtime_ns == before


def test_接口层不再直接调_save_overrides():
    """静态契约：四个写入口统一走 `mutate_overrides`（锁 + 原子写 + 失败抛）。"""
    text = (ROOT / "novelforge" / "server.py").read_text(encoding="utf-8")
    assert "config.save_overrides(" not in text
    assert "config.mutate_overrides(" in text


def test_配置保存失败回500而不是ok(client, auth_headers, settings_file):
    """真实接口：写不进去必须是 500，带原因 —— 不能让界面显示「已保存」。"""
    settings_file.mkdir()                        # 目录占位 ⇒ 写必失败
    r = client.put("/api/config", json={"naming": {"pattern": "{title}"}},
                   headers=auth_headers)
    assert r.status_code == 500
    assert "写入失败" in r.json()["detail"]
    # 读接口不受影响（设置页还能打开）
    assert client.get("/api/config", headers=auth_headers).status_code == 200
