"""每库覆盖（第 13 期）：配置第四层 ``生效值 = 每库覆写 ?? 全局值``。

测的是三条设计约束本身（见 ``core/lib_settings`` 模块注释），而不是实现细节：

1. 稀疏存储 → 没覆写的库**自动跟着全局变**；
2. **不改** ``config.load_config()`` 语义（全局消费者一行都不用动）；
3. 与能力矩阵联动 → 库类型没这能力，覆写项**不返回也不生效**。

外加界面依赖的两点：``overrides`` 原始覆写（``policy_map`` 逐字段判「继承 / 覆盖」要用）、
坏 JSON 降级（手改坏一个字符不该把整页弄挂）。
"""
import json

import pytest

from novelforge import config
from novelforge.core import db, lib_settings

# ---------------------------------------------------------------------------
# 读：继承 / 覆写 / 隔离
# ---------------------------------------------------------------------------

def test_new_library_inherits_global(isolated, make_library, tmp_path):
    """没覆写过 = 逐字节等于全局值（本期「零行为变化」的根据）。"""
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)

    res = lib_settings.effective(lid)

    assert res["overrides"] == {}
    assert res["values"] == res["global"]
    assert not any(res["overridden"].values())
    assert res["library_type"] == "ebook"
    assert res["name"] == "甲库"


def test_override_touches_only_that_library(isolated, make_library, tmp_path):
    """覆写只作用于本库：全局值与其它库都不受影响。"""
    a, b = "lib-a", "lib-b"
    make_library(a, "甲库", "ebook", tmp_path / "libraries" / a)
    make_library(b, "乙库", "ebook", tmp_path / "libraries" / b)
    before = config.load_config()["watcher"]["recursive"]

    res = lib_settings.set_overrides(a, {"watcher.recursive": True})

    assert res["values"]["watcher.recursive"] is True
    assert res["overridden"]["watcher.recursive"] is True
    assert res["global"]["watcher.recursive"] == before

    other = lib_settings.effective(b)
    assert other["overridden"]["watcher.recursive"] is False
    assert other["values"]["watcher.recursive"] == before
    assert config.load_config()["watcher"]["recursive"] == before


def test_clear_overrides_restores_inherit(isolated, make_library, tmp_path):
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    lib_settings.set_overrides(lid, {"output.layout": "komga"})

    res = lib_settings.clear_overrides(lid)

    assert res["overridden"]["output.layout"] is False
    assert res["values"] == res["global"]


def test_clear_selected_keys_only(isolated, make_library, tmp_path):
    """``keys`` 给定时只清这几项，其余覆写保留。"""
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    lib_settings.set_overrides(lid, {"output.layout": "komga", "watcher.recursive": True})

    res = lib_settings.clear_overrides(lid, ["output.layout"])

    assert res["overridden"]["output.layout"] is False
    assert res["overridden"]["watcher.recursive"] is True


# ---------------------------------------------------------------------------
# config_for / apply_to：两个消费入口
# ---------------------------------------------------------------------------

def test_config_for_applies_override_without_polluting(isolated, make_library, tmp_path):
    """``config_for`` 返回**深拷贝**：改它不能回流到全局配置。"""
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    base_layout = config.load_config()["output"]["layout"]
    lib_settings.set_overrides(lid, {"output.layout": "komga"})

    cfg = lib_settings.config_for(lid)
    assert cfg["output"]["layout"] == "komga"

    cfg["output"]["layout"] = "flat"                # 拿返回值乱改
    assert lib_settings.config_for(lid)["output"]["layout"] == "komga"
    assert lib_settings.config_for(None)["output"]["layout"] == base_layout
    assert config.load_config()["output"]["layout"] == base_layout


def test_apply_to_keeps_values_of_untouched_keys(isolated, make_library, tmp_path):
    """库没覆写 → 原样返回；覆写 → 只并那一项，调用方显式传的值不被丢掉。"""
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    base = {"pattern": "全局规则", "scope": "all"}

    assert lib_settings.apply_to(base, lid, "naming") == base

    lib_settings.set_overrides(lid, {"naming.pattern": "{title}"})
    out = lib_settings.apply_to(base, lid, "naming")

    assert out == {"pattern": "{title}", "scope": "all"}
    assert base == {"pattern": "全局规则", "scope": "all"}   # 不改入参


# ---------------------------------------------------------------------------
# policy_map：逐字段合并 / 逐字段恢复
# ---------------------------------------------------------------------------

def test_policy_map_merges_by_field_and_resets_by_field(isolated, make_library, tmp_path):
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    global_fields = config.load_config()["metadata_fetch"]["fields"] or {}

    lib_settings.set_overrides(lid, {"metadata_fetch.fields": {"tags": "skip", "authors": "fill_only"}})
    res = lib_settings.set_overrides(lid, {"metadata_fetch.fields": {"tags": None}})

    # 只摘掉 tags，authors 的覆写留着
    assert res["overrides"]["metadata_fetch.fields"] == {"authors": "fill_only"}
    merged = res["values"]["metadata_fetch.fields"]
    assert merged["authors"] == "fill_only"
    assert merged.get("tags") == global_fields.get("tags")     # 该字段回到全局


def test_policy_map_all_fields_reset_drops_the_override(isolated, make_library, tmp_path):
    """字段全部恢复继承后，整个 ``metadata_fetch.fields`` 覆写应当消失（不留空壳）。"""
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    lib_settings.set_overrides(lid, {"metadata_fetch.fields": {"tags": "skip"}})

    res = lib_settings.set_overrides(lid, {"metadata_fetch.fields": {"tags": None}})

    assert "metadata_fetch.fields" not in res["overrides"]
    assert res["overridden"]["metadata_fetch.fields"] is False


# ---------------------------------------------------------------------------
# 能力联动：漫画库没有元数据能力
# ---------------------------------------------------------------------------

def test_comic_library_exposes_metadata_but_not_convert(isolated, make_library, tmp_path):
    """第 21 期：抓取不再按格式分流 → 漫画库也暴露并接受它；**本地转换**仍只给电子书库。"""
    lid = "comic-a"
    make_library(lid, "漫画库", "comic", tmp_path / "libraries" / lid)

    keys = [s["key"] for s in lib_settings.schema("comic")]
    assert "metadata_fetch.fields" in keys        # 抓取对漫画库同样适用
    assert "output.format" not in keys            # 派生 MOBI 依赖 Calibre 转换能力，漫画库没有
    assert "watcher.recursive" in keys            # 未登记能力的项 = 无条件可用

    lib_settings.set_overrides(lid, {"metadata_fetch.enabled": True})
    assert lib_settings.effective(lid)["values"]["metadata_fetch.enabled"] is True

    with pytest.raises(ValueError):
        lib_settings.set_overrides(lid, {"output.format": "mobi"})

    assert "output.format" not in lib_settings.effective(lid)["values"]


def test_stale_override_does_not_activate_after_type_change(isolated, make_library, tmp_path):
    """库里残留着「类型改过之前」写的覆写：能力不匹配 → **不生效**（也不应该突然活过来）。"""
    lid = "comic-a"
    make_library(lid, "漫画库", "comic", tmp_path / "libraries" / lid)
    # 用**仍然不匹配**的能力项：漫画库没有 convert（第 21 期起它已经有了 metadata）
    db.update_library(lid, settings=json.dumps({"output.format": "mobi"}))

    res = lib_settings.effective(lid)
    assert "output.format" not in res["values"]
    assert lib_settings.config_for(lid)["output"]["format"] == \
        config.load_config()["output"]["format"]


# ---------------------------------------------------------------------------
# 校验：坏值一律 ValueError（接口层翻成 400）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("patch", [
    {"output.format": "pdf"},                       # 枚举外
    {"output.layout": "tree"},                      # 枚举外
    {"metadata_fetch.threshold": 1.5},              # 区间外
    {"metadata_fetch.threshold": "abc"},            # 非数字
    {"naming.pattern": "a/b.epub"},                 # 路径分隔符（会被当文件名用）
    {"naming.pattern": "   "},                      # 空
    {"metadata_fetch.fields": ["tags"]},            # 类型不对
    {"metadata_fetch.fields": {"tags": "maybe"}},   # 策略枚举外
    {"nope.key": 1},                                # 未登记项
])
def test_validation_rejects_bad_values(isolated, make_library, tmp_path, patch):
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)

    with pytest.raises(ValueError):
        lib_settings.set_overrides(lid, patch)


def test_number_is_normalized_to_float(isolated, make_library, tmp_path):
    """界面上传的多半是字符串；归一化在**内核**做，免得两套口径。"""
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)

    res = lib_settings.set_overrides(lid, {"metadata_fetch.threshold": "0.55"})

    assert res["values"]["metadata_fetch.threshold"] == 0.55


def test_unknown_library_raises(isolated):
    with pytest.raises(ValueError):
        lib_settings.set_overrides("不存在的库", {"watcher.recursive": True})
    with pytest.raises(ValueError):
        lib_settings.clear_overrides("不存在的库")


# ---------------------------------------------------------------------------
# 坏 JSON 降级
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad", ["{不是 json", "[1, 2]", '"字符串"'])
def test_bad_settings_json_degrades_to_inherit(isolated, make_library, tmp_path, bad):
    """手改坏一个字符不该把书库页整页弄挂 —— 一律当「没有覆写」。"""
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    db.update_library(lid, settings=bad)

    assert lib_settings.overrides(lid) == {}
    res = lib_settings.effective(lid)               # 不抛
    assert res["values"] == res["global"]


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------

def test_settings_api_roundtrip(client, auth_headers, make_library, tmp_path):
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    url = f"/api/libraries/{lid}/settings"

    r = client.get(url, headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["values"] == body["global"]
    assert body["schema"], "ebook 库应当有可覆写项"

    r = client.put(url, headers=auth_headers, json={"output.layout": "komga"})
    assert r.status_code == 200, r.text
    assert r.json()["overridden"]["output.layout"] is True

    r = client.put(url, headers=auth_headers, json={"output.layout": "tree"})
    assert r.status_code == 400

    r = client.put(url, headers=auth_headers, json={})
    assert r.status_code == 400

    r = client.delete(url, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["overridden"]["output.layout"] is False

    assert client.get(url, headers=auth_headers).json()["overrides"] == {}


def test_settings_api_partial_reset_and_404(client, auth_headers, make_library, tmp_path):
    lid = "lib-a"
    make_library(lid, "甲库", "ebook", tmp_path / "libraries" / lid)
    url = f"/api/libraries/{lid}/settings"
    client.put(url, headers=auth_headers,
               json={"output.layout": "komga", "watcher.recursive": True})

    r = client.delete(url, headers=auth_headers, params={"keys": "output.layout"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["overridden"]["output.layout"] is False
    assert body["overridden"]["watcher.recursive"] is True

    assert client.get("/api/libraries/没有这个库/settings", headers=auth_headers).status_code == 404
    assert client.put("/api/libraries/没有这个库/settings", headers=auth_headers,
                      json={"output.layout": "komga"}).status_code == 404
    assert client.delete("/api/libraries/没有这个库/settings", headers=auth_headers).status_code == 404
