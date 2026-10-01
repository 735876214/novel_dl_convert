"""第 80 期：`core/updater.py` 的**完全离线**契约测试。

为什么必须有这一份：第 78 期上线「版本检查 + 一键更新」后，`update` 段四个配置键里
有两个是**假开关** —— `image` 只在白名单与回显里，后端没有任何读点；`auto_apply`
连读点都没有（打开它什么都不会发生）。修好之后必须把这层接线钉住，否则下次重构
又会悄悄退化成「界面有、后端没有」。

测试纪律（与 conftest 一致）：

* **绝不真连**：出网缝 `_http_get_json` 与 docker 缝 `_docker` 一律换成替身；
  「未预设的出网请求」直接抛错，于是「不该出网时确实没出网」也成了断言。
* **不养后台线程**：`start_background` 起来的线程在夹具收尾时 `stop_background()` + `join`。
* 碰 DB 的用例（持久化往返）显式依赖 `isolated`（夹具 `up` 已带上）。
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from novelforge.core import backup as backup_mod
from novelforge.core import updater

#: 手动检查路径与兜底 tags 路径（与 `_remote_latest` 里的拼接逐字一致）。
GITHUB_LATEST = updater._GITHUB_API
GITHUB_TAGS = f"https://api.github.com/repos/{updater._REPO}/tags?per_page=1"

#: 测试里的「本地版本」固定成一个值，避免用例受 `VERSION` 文件影响。
LOCAL = "0.80.0"


def _default_update_cfg() -> dict:
    """与 `config.DEFAULTS["update"]` 同形（image 留空 = 用内置默认镜像）。"""
    return {"check_enabled": True, "interval_hours": 6, "image": "", "auto_apply": False}


class _Net:
    """假的 GitHub 出网缝（替换 `updater._http_get_json`）。"""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.responses: dict[str, object] = {}

    def ok(self, url: str, data) -> None:
        self.responses[url] = data

    def fail(self, url: str) -> None:
        self.responses[url] = RuntimeError("网络不可达（测试预设）")

    def get(self, url: str, token: str = "", timeout: int = 8):
        self.calls.append(url)
        if url not in self.responses:
            raise RuntimeError(f"测试未预设的出网请求：{url}")
        r = self.responses[url]
        if isinstance(r, Exception):
            raise r
        return r


class _Docker:
    """假的 docker API 缝（替换 `updater._docker`）。

    默认一切返回 200 —— `apply_update` 只看 `/images/create` 的状态码。
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.status = 200

    def call(self, method: str, path: str, query=None, body=None, timeout: int = 120):
        self.calls.append({"method": method, "path": path,
                           "query": dict(query or {}), "body": body})
        return self.status, "{}"

    def paths(self) -> list[str]:
        return [c["path"] for c in self.calls]


@pytest.fixture
def up(isolated, monkeypatch, tmp_path):  # noqa: ARG001 —— isolated 提供一套空库
    """隔离 updater 的模块级状态 + 两条外部缝 + `update` 段配置。

    刻意把 `DOCKER_SOCK` 指到一个**不存在**的路径：默认「未挂载」是产品的真实默认，
    想测已挂载的用例用 `_mount_socket(up)` 显式建出来。
    """
    from novelforge import config as config_mod

    monkeypatch.setattr(updater, "_state", {
        "latest": None, "checked_at": 0, "has_update": False, "url": "",
        "error": "", "auto_applied": "", "auto_failures": 0,
        "auto_retry_at": 0.0, "last_auto_result": "", "auto_message": "",
    })
    monkeypatch.setattr(updater, "_thread", None)
    monkeypatch.setattr(updater, "_stop", threading.Event())
    monkeypatch.setattr(updater, "DOCKER_SOCK", str(tmp_path / "docker.sock"))

    net, docker = _Net(), _Docker()
    monkeypatch.setattr(updater, "_http_get_json", net.get)
    monkeypatch.setattr(updater, "_docker", docker.call)

    box = SimpleNamespace(net=net, docker=docker, tmp=tmp_path,
                          cfg=_default_update_cfg())

    def _push_cfg() -> None:
        monkeypatch.setattr(config_mod, "load_config",
                            lambda: {"update": dict(box.cfg)})

    def set_cfg(**kw) -> None:
        box.cfg = {**box.cfg, **kw}
        _push_cfg()

    box.set_cfg = set_cfg
    _push_cfg()
    try:
        yield box
    finally:
        updater.stop_background()          # 叫停本次用例起的后台线程
        t = updater._thread
        if t is not None and t.is_alive():
            t.join(timeout=5)
        # ⚠️ **超时后线程还活着就必须响亮报错**（第 86 期加）：`updater._state` 是**模块级**
        # 全局，而 monkeypatch 会在用例结束把它复原 —— 一个跑到下一个用例里的线程会
        # 边跑边改写新用例的 `_state`，症状正是「每次失败的用例都不同、单跑全过」。
        # 宁可在这里当场炸掉（指出真正的元凶），也不要让它继续污染下游用例。
        assert t is None or not t.is_alive(), (
            "上一个用例的后台线程在 5 秒内没停下来：它会继续改写模块级 _state，"
            "把失败嫁祸给后面的用例（见本夹具注释）")


def _mount_socket(up) -> None:
    """把 docker.sock「挂上」（建一个空文件即可，真连被 `_docker` 替身拦住）。"""
    p = up.tmp / "docker.sock"
    p.write_bytes(b"")
    updater.DOCKER_SOCK = str(p)


# ---------------- 版本比较 ----------------

def test_parse_version_去前缀并按点分段():
    assert updater.parse_version("v1.2.3") == (1, 2, 3)
    assert updater.parse_version("V0.80.0") == (0, 80, 0)
    assert updater.parse_version(" 0.9 ") == (0, 9)


def test_parse_version_非数字段落零():
    # `1.2.3-rc1` 的第三段不是纯数字 ⇒ 落 0（宁可判「不更新」，也不能抛）
    assert updater.parse_version("1.2.3-rc1") == (1, 2, 0)
    # 空串会 split 出一段空 → 0，最终是 (0,)
    assert updater.parse_version("") == (0,)


def test_is_newer_按数值段比较而非字符串():
    assert updater.is_newer("0.80.0", "0.79.0") is True
    assert updater.is_newer("0.79.0", "0.80.0") is False
    assert updater.is_newer("0.79.0", "0.79.0") is False
    # 字符串比较会把 "0.9.0" 判成比 "0.80.0" 新 —— 必须按数值段
    assert updater.is_newer("0.9.0", "0.80.0") is False
    assert updater.is_newer("v0.80.0", "0.80.0") is False


# ---------------- 是否挂了 docker.sock ----------------

def test_updater_available_看的是_socket_在不在(up):
    assert updater.updater_available() is False      # 夹具指到不存在的路径
    assert up.docker.calls == []                     # 判定本身**不得**碰 docker
    _mount_socket(up)
    assert updater.updater_available() is True


# ---------------- status 形状与开关回显 ----------------

def test_status_字段齐全且开关取自配置(up):
    st = updater.status(local_version=LOCAL)
    for k in ("current", "latest", "has_update", "checked_at", "url",
              "updater_available", "error", "check_enabled", "auto_apply",
              "auto_failures", "auto_retry_at", "last_auto_result",
              "auto_message"):
        assert k in st, f"status 少了 {k}"
    assert st["current"] == LOCAL
    assert st["has_update"] is False
    assert st["updater_available"] is False
    # 第 80 期：两个开关的真值源是**配置**（_state 里不另存一份，免得两处说法不一致）
    assert st["check_enabled"] is True and st["auto_apply"] is False
    up.set_cfg(check_enabled=False, auto_apply=True)
    st2 = updater.status(local_version=LOCAL)
    assert st2["check_enabled"] is False and st2["auto_apply"] is True


# ---------------- check：三条出网路径 ----------------

def test_check_走_releases_latest_成功(up):
    up.net.ok(GITHUB_LATEST, {"tag_name": "v0.81.0", "html_url": "https://x/rel"})
    st = updater.check(force=True, local_version=LOCAL)
    assert up.net.calls == [GITHUB_LATEST]
    assert st["latest"] == "0.81.0"          # tag 前缀 v 被去掉
    assert st["has_update"] is True
    assert st["url"] == "https://x/rel"
    assert st["error"] == ""


def test_check_失败时回落_tags(up):
    up.net.fail(GITHUB_LATEST)
    up.net.ok(GITHUB_TAGS, [{"name": "v0.81.0"}])
    st = updater.check(force=True, local_version=LOCAL)
    assert up.net.calls == [GITHUB_LATEST, GITHUB_TAGS]
    assert st["latest"] == "0.81.0"
    assert st["has_update"] is True
    assert st["url"] == f"https://github.com/{updater._REPO}/releases"
    assert st["error"] == ""


def test_check_两条路都失败记_check_failed(up):
    up.net.fail(GITHUB_LATEST)
    up.net.fail(GITHUB_TAGS)
    st = updater.check(force=True, local_version=LOCAL)
    assert st["latest"] is None
    assert st["has_update"] is False
    assert st["error"] == "check_failed"


def test_check_本地已是最新时不报更新(up):
    up.net.ok(GITHUB_LATEST, {"tag_name": "v0.80.0", "html_url": "u"})
    st = updater.check(force=True, local_version=LOCAL)
    assert st["latest"] == "0.80.0"
    assert st["has_update"] is False


def test_check_非force且一小时内缓存命中不重复出网(up):
    up.net.ok(GITHUB_LATEST, {"tag_name": "v0.81.0", "html_url": "u"})
    assert updater.check(force=True, local_version=LOCAL)["latest"] == "0.81.0"
    assert len(up.net.calls) == 1
    # 换掉预设响应：若它真又出网，第二次结果就会变成 9.9.9
    up.net.ok(GITHUB_LATEST, {"tag_name": "v9.9.9", "html_url": "u2"})
    st = updater.check(force=False, local_version=LOCAL)
    assert st["latest"] == "0.81.0"
    assert len(up.net.calls) == 1, "一小时内非 force 检查不该重复出网"


def test_check_force_绕过缓存(up):
    up.net.ok(GITHUB_LATEST, {"tag_name": "v0.81.0", "html_url": "u"})
    updater.check(force=True, local_version=LOCAL)
    up.net.ok(GITHUB_LATEST, {"tag_name": "v0.82.0", "html_url": "u2"})
    st = updater.check(force=True, local_version=LOCAL)
    assert st["latest"] == "0.82.0"
    assert len(up.net.calls) == 2


def test_clear_has_update_清掉快照并落库(up):
    up.net.ok(GITHUB_LATEST, {"tag_name": "v0.99.0", "html_url": "u"})
    assert updater.check(force=True, local_version=LOCAL)["has_update"] is True
    updater.clear_has_update()
    assert updater.status(local_version=LOCAL)["has_update"] is False
    # 落库了：重放持久层仍是「无更新」（关检查后重启也不该又冒提示）
    updater._state["has_update"] = True
    updater._load_persisted()
    assert updater.status(local_version=LOCAL)["has_update"] is False


# ---------------- 镜像来源（唯一读法）与拆分 ----------------

def test_split_image_只认最后一段冒号():
    assert updater._split_image("ghcr.io/a/b:latest") == ("ghcr.io/a/b", "latest")
    # 带端口的私有仓库：端口不能被当成 tag
    assert updater._split_image("localhost:5000/ns/img") == ("localhost:5000/ns/img", "latest")
    assert updater._split_image("localhost:5000/ns/img:v0.81.0") == (
        "localhost:5000/ns/img", "v0.81.0")
    # 没写 tag ⇒ latest
    assert updater._split_image("ghcr.io/a/b") == ("ghcr.io/a/b", "latest")


def test_configured_image_四级优先级(up, monkeypatch):
    monkeypatch.setenv("NOVELFORGE_UPDATE_IMAGE", "env/from-env:1")   # ③
    assert updater.configured_image() == "env/from-env:1"
    up.set_cfg(image="cfg/from-config:2")                             # ②
    assert updater.configured_image() == "cfg/from-config:2"
    assert updater.configured_image("explicit/from-call:3") == "explicit/from-call:3"  # ①
    # 空 / 空白入参不算「显式」⇒ 回落下一级
    assert updater.configured_image("   ") == "cfg/from-config:2"
    # ④ 全部缺席 ⇒ 内置默认
    up.set_cfg(image="")
    monkeypatch.delenv("NOVELFORGE_UPDATE_IMAGE")
    assert updater.configured_image() == updater._DEFAULT_IMAGE


# ---------------- 持久化往返（含 auto_applied）----------------

def test_持久化往返带退避状态(up):
    updater._state.update({"latest": "0.81.0", "checked_at": 1700000000.0,
                           "has_update": True, "url": "https://x", "error": "",
                           "auto_applied": "0.81.0", "auto_failures": 2,
                           "auto_retry_at": 1700001000.0,
                           "last_auto_result": "pull_failed",
                           "auto_message": "镜像拉取失败（HTTP 500）"})
    updater._persist()
    updater._state.update({"latest": None, "checked_at": 0, "has_update": False,
                           "url": "", "error": "", "auto_applied": "",
                           "auto_failures": 0, "auto_retry_at": 0.0,
                           "last_auto_result": "", "auto_message": ""})
    updater._load_persisted()
    assert updater._state["latest"] == "0.81.0"
    assert updater._state["has_update"] is True
    assert updater._state["url"] == "https://x"
    # ⚠️ 第 84 期重点：漏写键元组 ⇒ `auto_failures` / `auto_retry_at` 静默丢失，
    #    表现是「每次重启后把退避计数清零、对同一版本重新猛拉一遍」，正是要消掉的缺陷
    assert updater._state["auto_applied"] == "0.81.0"
    assert updater._state["auto_failures"] == 2
    assert updater._state["auto_retry_at"] == 1700001000.0
    assert updater._state["last_auto_result"] == "pull_failed"
    assert updater._state["auto_message"] == "镜像拉取失败（HTTP 500）"


# ---------------- 后台线程（不真连：首轮只等待）----------------

def test_start_background_幂等且换新stop(up):
    updater.start_background(interval_hours=6)
    first_thread, first_stop = updater._thread, updater._stop
    assert first_thread is not None and first_thread.is_alive()
    updater.start_background(interval_hours=6)         # 已在跑 ⇒ 不重复起
    assert updater._thread is first_thread
    # 换间隔 = 先 stop 再 start（server._apply_update_config 的做法）：必须是新线程 + 新 Event
    updater.stop_background()
    updater.start_background(interval_hours=1)
    assert first_stop.is_set()
    assert updater._thread is not first_thread
    assert updater._stop is not first_stop
    updater.stop_background()
    updater._thread.join(timeout=5)
    assert not updater._thread.is_alive()


# ---------------- apply_update：降级与拉取 ----------------

def test_apply_update_未挂载直接降级且不碰docker(up):
    res = updater.apply_update()
    assert res["ok"] is False
    assert res["stage"] == "unavailable"          # 既有 stage 枚举不变
    assert "docker compose" in res["message"]     # 如实给出手动命令
    assert up.docker.calls == []                  # 「未挂载」分支绝不能去连


def test_apply_update_按配置镜像拉取并触发重建(up, monkeypatch):
    _mount_socket(up)
    up.set_cfg(image="harbor.local:5000/mirror/novel_dl_convert:v0.81.0")
    done = threading.Event()
    monkeypatch.setattr(updater, "_recreate", lambda image: done.set())
    # 第 84 期：拉镜像前先快照。用替身跳掉真备份（避免依赖测试里的真实 DB 文件）
    monkeypatch.setattr(
        "novelforge.core.backup.snapshot",
        lambda reason: {"ok": True, "path": "/fake/backup.db", "kind": "sqlite",
                        "size": 1, "removed": []})
    res = updater.apply_update()
    assert res == {"ok": True, "stage": "restarting",
                   "image": "harbor.local:5000/mirror/novel_dl_convert:v0.81.0",
                   "backup": "/fake/backup.db"}
    pull = up.docker.calls[0]
    assert pull["method"] == "POST" and pull["path"] == "/images/create"
    # 绑定替身里 urlencode 结果：fromImage 不带 tag，tag 单独传（与 _split_image 对应）
    assert pull["query"] == {"fromImage": "harbor.local:5000/mirror/novel_dl_convert",
                             "tag": "v0.81.0"}
    assert done.wait(5), "重建线程没被启动（pull 成功后必须去 _recreate）"


def test_apply_update_入参镜像优先于配置(up):
    _mount_socket(up)
    up.set_cfg(image="cfg/app:1")
    with_background = updater.apply_update("explicit/app:2")
    assert with_background["image"] == "explicit/app:2"
    assert up.docker.calls[0]["query"]["tag"] == "2"


def test_apply_update_拉取失败不重建(up, monkeypatch):
    _mount_socket(up)
    up.docker.status = 500
    called = []
    monkeypatch.setattr(updater, "_recreate", lambda image: called.append(image))
    res = updater.apply_update()
    assert res["ok"] is False and res["stage"] == "pull_failed"
    assert called == []


# ---------------- maybe_auto_apply（第 80 期接通的假开关）----------------

def _found_new_version(up, tag: str = "v0.81.0") -> None:
    """让一次真实检查「发现新版」（出网走替身）。"""
    up.net.ok(GITHUB_LATEST, {"tag_name": tag, "html_url": "u"})
    st = updater.check(force=True, local_version=LOCAL)
    assert st["has_update"] is True, st


def test_maybe_auto_apply_开关关时不动作(up):
    _found_new_version(up)
    res = updater.maybe_auto_apply()
    assert res["stage"] == "disabled" and res["auto"] is True
    assert up.docker.calls == []
    assert updater._state["auto_applied"] == ""


def test_maybe_auto_apply_无新版时不动作(up):
    up.set_cfg(auto_apply=True)
    res = updater.maybe_auto_apply()
    assert res["stage"] == "no_update" and res["auto"] is True
    assert up.docker.calls == []


def test_maybe_auto_apply_未挂socket时如实降级且不记尝试(up):
    up.set_cfg(auto_apply=True)
    _found_new_version(up)
    res = updater.maybe_auto_apply()
    assert res["stage"] == "unavailable" and res["auto"] is True
    assert up.docker.calls == []
    # ⚠️ 「没挂载」不算尝试过：记上就永远不可能自动更新了
    assert updater._state["auto_applied"] == ""


def test_maybe_auto_apply_首次自动拉取并记录已尝试(up, monkeypatch):
    up.set_cfg(auto_apply=True, image="mirror/app:1")
    _mount_socket(up)
    _found_new_version(up)
    done = threading.Event()
    monkeypatch.setattr(updater, "_recreate", lambda image: done.set())
    res = updater.maybe_auto_apply()
    assert res["auto"] is True and res["ok"] is True and res["stage"] == "restarting"
    assert done.wait(5)
    assert updater._state["auto_applied"] == "0.81.0"
    assert up.docker.calls[0]["path"] == "/images/create"
    # 同一版本再来一轮 ⇒ 不再拉（否则每 6h 重试一次，用户只看到「一直没更新成功」）
    calls = len(up.docker.calls)
    assert updater.maybe_auto_apply()["stage"] == "already_tried"
    assert len(up.docker.calls) == calls


def test_maybe_auto_apply_pull失败进退避_defer(up, monkeypatch):
    # 第 84 期语义：pull 失败**不再永久卡死**，而是记一次失败、退避到点后再试。
    up.set_cfg(auto_apply=True, image="mirror/app:1")
    _mount_socket(up)
    _found_new_version(up)
    up.docker.status = 500                      # 拉取失败
    res = updater.maybe_auto_apply()
    assert res["ok"] is False and res["stage"] == "pull_failed"
    assert updater._state["auto_applied"] == "0.81.0"   # 失败也已记录版本
    assert updater._state["auto_failures"] == 1
    assert updater._state["auto_retry_at"] > time.time()
    # 退避窗口内再来一轮 ⇒ defer（不再拉），且失败计数不涨
    assert updater.maybe_auto_apply()["stage"] == "defer"
    assert len(up.docker.calls) == 1
    assert updater._state["auto_failures"] == 1
    # 退避到点（把时间推到窗口之后）⇒ 重新拉（拉取仍失败则再退避）
    monkeypatch.setattr(updater, "time", SimpleNamespace(
        time=lambda: updater._state["auto_retry_at"] + 1,
        strftime=time.strftime, localtime=time.localtime))
    up.docker.calls.clear()
    res2 = updater.maybe_auto_apply()
    assert res2["stage"] == "pull_failed"      # 到点 ⇒ 真去拉了
    assert len(up.docker.calls) == 1
    assert updater._state["auto_failures"] == 2


def test_maybe_auto_apply_退避序列封顶24h(up, monkeypatch):
    # 连续失败 ⇒ 退避间隔 1h → 6h → 24h，且封顶 24h（不无限拉长）
    up.set_cfg(auto_apply=True, image="mirror/app:1")
    _mount_socket(up)
    _found_new_version(up)
    up.docker.status = 500
    now = [1_700_000_000.0]

    def fake_time() -> float:
        return now[0]

    monkeypatch.setattr(updater, "time", SimpleNamespace(
        time=fake_time, strftime=time.strftime, localtime=time.localtime))
    expected = [3600, 6 * 3600, 24 * 3600, 24 * 3600]   # 第 4 次起封顶 24h
    for i, exp in enumerate(expected, start=1):
        updater.maybe_auto_apply()          # 拉取失败 ⇒ 退避
        assert updater._state["auto_failures"] == i
        # 退避到点时间戳 = 上次 now + exp；推到该点后下一轮才重试
        now[0] = updater._state["auto_retry_at"] + 1
    assert updater._state["auto_retry_at"] - fake_time() <= 24 * 3600 + 1


def test_maybe_auto_apply_换版本清零失败计数(up, monkeypatch):
    # 同一版本退避中时出了更新的版本 ⇒ 失败计数清零、直接去拉新版本
    up.set_cfg(auto_apply=True, image="mirror/app:1")
    _mount_socket(up)
    _found_new_version(up, tag="v0.81.0")
    up.docker.status = 500
    assert updater.maybe_auto_apply()["stage"] == "pull_failed"
    assert updater._state["auto_failures"] == 1
    # 出了 0.82.0
    up.net.ok(GITHUB_LATEST, {"tag_name": "v0.82.0", "html_url": "u2"})
    updater.check(force=True, local_version=LOCAL)
    up.docker.status = 200
    res = updater.maybe_auto_apply()
    assert res["stage"] == "restarting"
    assert updater._state["auto_failures"] == 0
    assert updater._state["auto_applied"] == "0.82.0"


def test_maybe_auto_apply_未挂socket不记失败(up):
    # 默认不挂 socket：自动更新无从执行，但**不应**因此背上「失败」+ 退避倒计时
    up.set_cfg(auto_apply=True)
    _found_new_version(up)
    res = updater.maybe_auto_apply()
    assert res["stage"] == "unavailable" and res["auto"] is True
    assert up.docker.calls == []
    assert updater._state["auto_applied"] == ""
    assert updater._state["auto_failures"] == 0
    assert updater._state["auto_retry_at"] == 0.0


def test_apply_update_快照失败即中止更新(up, monkeypatch):
    # 第 84 期硬要求：备份失败 = 不准带数据风险继续更新
    _mount_socket(up)
    up.set_cfg(image="mirror/app:1")

    def boom(reason):
        raise backup_mod.SnapshotError("测试预设：pg_dump 失败")

    monkeypatch.setattr("novelforge.core.backup.snapshot", boom)
    res = updater.apply_update()
    assert res["ok"] is False and res["stage"] == "backup_failed"
    assert "pg_dump" in res["message"]
    assert up.docker.calls == [], "备份失败还去拉镜像 = 没有安全网"


def test_maybe_auto_apply_持久化后重启不再重试(up, monkeypatch):
    up.set_cfg(auto_apply=True, image="mirror/app:1")
    _mount_socket(up)
    _found_new_version(up)
    monkeypatch.setattr(updater, "_recreate", lambda image: None)
    updater.maybe_auto_apply()
    # 模拟重启：内存态清空后从 app_state 恢复
    updater._state.update({"latest": None, "checked_at": 0, "has_update": False,
                           "url": "", "error": "", "auto_applied": "",
                           "auto_failures": 0, "auto_retry_at": 0.0,
                           "last_auto_result": "", "auto_message": ""})
    updater._load_persisted()
    assert updater._state["auto_applied"] == "0.81.0"
    assert updater.maybe_auto_apply()["stage"] == "already_tried"
