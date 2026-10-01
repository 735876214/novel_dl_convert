"""第 80 期：`update` 段配置的**防回归契约** —— 把「假配置 / 假开关」钉死。

本期的缺陷形态很隐蔽：`update.image` / `update.auto_apply` 写是写得进（在
`server.EDITABLE["update"]` 白名单里）、`GET /api/config` 也回显得出、设置页保存还报
「已保存」；但**后端没有任何读点** —— 改完等于没改，用户只会觉得「这个开关时灵时不灵」。

所以这里钉三件事（任何一处漂移都该红）：

1. **白名单 ⇄ 设置页控件逐字一致**：`server.EDITABLE["update"]` 的元素集合 =
   前端 `settingsFields.ts` 的 `UPDATE_FIELDS[].path` 剥掉 `update.` 前缀后的集合。
   （多一个 = 界面没有的键能偷偷存；少一个 = 界面有控件但存不进去。）
2. **每个键都有真实读点**：在 `server.py` / `core/updater.py` 里能找到 `.get("<键>")`
   这种读法。这条正是本期缺陷的直接判据 —— 没有读点的键就是假配置。
3. **`config.DEFAULTS["update"]` 覆盖白名单**：否则「恢复默认」会把键丢掉，
   而 `GET /api/config` 靠整段回显，表现是设置页控件凭空消失。

顺带钉住写入口的镜像名校验（`)` 与 `PUT` 的联动），因为 `image` 现在真的会进
`docker pull` 的 query。

第 84 期：**没有新增配置键**（退避序列 / 保留份数都是模块级常量），故本文件的断言一条不改 ——
只把口径说明补在这里。加固的三件事都在既有四个键的行为里：启动即检（`check_enabled`）、
退避重试与更新前备份（`auto_apply`）。新增键时 `READ_POINTS` 与白名单会一起红，正是要的护栏。
"""
from __future__ import annotations

import pathlib
import re

from novelforge import config, server

ROOT = pathlib.Path(__file__).resolve().parents[1]
SETTINGS_FIELDS_TS = ROOT / "frontend" / "src" / "data" / "settingsFields.ts"

#: 白名单里的四个键 → 每个键**必须**存在的读点（文件, 源码里必须出现的片段）。
#: 键名以 `.get("<键>"` 的形式出现；读点多于一处是允许的，这里只要求「至少这些」。
READ_POINTS: dict[str, list[tuple[str, str]]] = {
    "check_enabled": [
        # server：配置保存 / 启动时的热应用判据
        ("novelforge/server.py", '.get("check_enabled"'),
        # updater：status 把它回显给「新功能」页
        ("novelforge/core/updater.py", '.get("check_enabled"'),
    ],
    "interval_hours": [
        ("novelforge/server.py", '.get("interval_hours"'),
        # updater：_loop 每轮重读，改间隔不必重启
        ("novelforge/core/updater.py", '.get("interval_hours"'),
    ],
    "image": [
        # updater：镜像来源的唯一读法
        ("novelforge/core/updater.py", '.get("image")'),
        # server：写入口的形状校验
        ("novelforge/server.py", '.get("image")'),
    ],
    "auto_apply": [
        # updater：自动更新的判据
        ("novelforge/core/updater.py", '.get("auto_apply"'),
    ],
}

_UPDATE_PATH_RE = re.compile(r"path:\s*'update\.([A-Za-z_][A-Za-z0-9_]*)'")


def _read(path: pathlib.Path) -> str:
    assert path.is_file(), f"缺少源文件：{path}"
    return path.read_text(encoding="utf-8")


def _frontend_update_keys() -> set[str]:
    """前端「更新」页的字段键（剥掉 `update.` 前缀）。"""
    text = _read(SETTINGS_FIELDS_TS)
    start = text.index("export const UPDATE_FIELDS")
    end = text.index("\n]", start)
    keys = set(_UPDATE_PATH_RE.findall(text[start:end]))
    assert keys, "settingsFields.ts 里没解析到 UPDATE_FIELDS 的 update.* 字段（正则大概过期了）"
    return keys


def test_白名单与设置页控件逐字一致():
    backend = set(server.EDITABLE["update"])
    frontend = _frontend_update_keys()
    assert backend == frontend, (
        "`server.EDITABLE['update']` 与设置页控件必须一一对应："
        f"只在后端 {sorted(backend - frontend)}；只在前端 {sorted(frontend - backend)}"
    )


def test_设置页分区键指向_update_段():
    """`SECTION_KEYS.update` 决定保存时提交哪个顶层键 —— 指错就整段存不进去。"""
    text = _read(SETTINGS_FIELDS_TS)
    m = re.search(r"update:\s*\[([^\]]*)\]", text)
    assert m, "settingsFields.ts 里找不到 SECTION_KEYS 的 update 条目"
    assert re.findall(r"'([A-Za-z_]+)'", m.group(1)) == ["update"]
    # 字段路径的前缀必须就是它（否则 saveSection 收集不到）
    assert all(f"update.{k}" in text for k in server.EDITABLE["update"])


def test_默认值覆盖白名单():
    keys = set(server.EDITABLE["update"])
    missing = keys - set(config.DEFAULTS["update"])
    assert not missing, (
        f"这些键没有默认值 ⇒ 「恢复默认」后设置页控件会凭空消失：{sorted(missing)}")


def test_每个键都有真实读点():
    """**本期缺陷的直接判据**：白名单里有、代码里没人读 = 假配置。"""
    for key, points in READ_POINTS.items():
        assert key in server.EDITABLE["update"], f"{key} 已不在白名单里，契约表要同步删"
        for rel, needle in points:
            src = _read(ROOT / rel)
            assert needle in src, (
                f"`{key}` 在 {rel} 里找不到读法 `{needle}` —— 它又变回「界面有、后端没有」的假配置了")


def test_读点契约表覆盖白名单每个键():
    """反向：白名单新增键却不登记读点，本文件必须报错（否则契约会被绕过）。"""
    assert set(READ_POINTS) == set(server.EDITABLE["update"])


# ---------------- 接口层：回显与写入口 ----------------

def test_get_config_回显_update_整段(client, auth_headers):
    r = client.get("/api/config", headers=auth_headers)
    assert r.status_code == 200, r.text
    up = r.json()["config"]["update"]
    assert set(server.EDITABLE["update"]) <= set(up), (
        f"GET /api/config 的 update 段少了键：{up}")


def test_保存开关后_status_如实回显(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    r = client.put("/api/config", headers=auth_headers,
                   json={"update": {"check_enabled": False, "auto_apply": True}})
    assert r.status_code == 200, r.text
    st = client.get("/api/update/status", headers=auth_headers).json()
    assert st["check_enabled"] is False, "关掉检查后 status 必须如实回显（前端据此收起提示）"
    assert st["auto_apply"] is True


def test_镜像名写入口校验_拒绝注入形状(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    bad = [
        "ghcr.io/a/b@sha256:deadbeef",   # digest 形式
        "../evil",                       # 路径穿越
        "bad image",                     # 空格
        "-leading-dash",                 # 首字符非法
    ]
    for img in bad:
        r = client.put("/api/config", headers=auth_headers, json={"update": {"image": img}})
        assert r.status_code == 400, f"{img!r} 应该被拒：{r.status_code} {r.text}"


def test_镜像名写入口校验_接受真实形状并回显(client, auth_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    good = [
        "ghcr.io/735876214/novel_dl_convert:latest",
        "harbor.local:5000/mirror/app:v0.81.0",   # 带端口的私有仓库（_split_image 认得）
        "app",                                     # 省略 tag ⇒ latest
        "",                                        # 留空 = 回落环境变量 / 内置默认
    ]
    for img in good:
        r = client.put("/api/config", headers=auth_headers, json={"update": {"image": img}})
        assert r.status_code == 200, f"{img!r} 不该被拒：{r.status_code} {r.text}"
        got = client.get("/api/config", headers=auth_headers).json()["config"]["update"]
        assert got["image"] == img
