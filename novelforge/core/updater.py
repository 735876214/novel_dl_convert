"""版本检查与一键更新（第 78 期；第 80 期接线补全）。

检查：定时（默认 6h）/ 启动 / 手动，调 GitHub API 取最新 Release 版本号，
与本地 ``server.APP_VERSION`` 比较。**出网失败静默忽略**（不阻塞、不报错）；
出网本身是**显式、可关、失败降级**的 —— ``update.check_enabled`` 关掉即完全不检查
（第 80 期起该开关保存即生效，见 ``server._apply_update_config``）。

更新：挂了 ``/var/run/docker.sock`` 时，拉取镜像并**重建自身容器**
（pull → 取自身 spec → 删旧 → 用新镜像重建 → 启动）。这是用户明确选择的
「应用真去更新」路径，代价是把宿主机 docker 控制权交给容器，所以**默认不挂载**
（见 ``docker-compose.yml`` 的注释：在 ``volumes`` 下取消注释 ``/var/run/docker.sock`` 那一行）。
未挂载时 ``updater_available()`` 为 ``False``，前端只展示「复制升级命令」。

⚠️ 安全面：本模块**只做两个动作** —— 拉取 `update.image` 指的那一个镜像、重建**自身容器**。
第 80 期起镜像名可由用户在设置页配置（含加速镜像源）：能改配置的人本来就能改 compose 的
``image``，且 ``NOVELFORGE_UPDATE_IMAGE`` 环境变量早已是同一个口子，故不算扩大攻击面
（写入前另有形状校验，见 ``server._validate_update_image``）。
即便如此，接口面也不给「任意容器 / 任意 exec」。
"""
import json
import logging
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import http.client  # noqa: F401 —— 仅类型引用；实际连接走 _UnixSocketConnection

_log = logging.getLogger("novelforge")

DOCKER_SOCK = "/var/run/docker.sock"
_REPO = "735876214/novel_dl_convert"
_GITHUB_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
_CACHE_KEY = "update_check"
# 内置默认镜像；`update.image` 与 `NOVELFORGE_UPDATE_IMAGE` 均可覆盖（第 80 期起 image 真生效）。
_DEFAULT_IMAGE = "ghcr.io/735876214/novel_dl_convert:latest"

# `auto_applied`（第 80 期）= 已经**自动更新尝试过**的远端版本号；成功失败都记，
# 保证同一个版本只尝试一次（否则 pull 失败后每轮检查都会重试一遍）。
_state = {"latest": None, "checked_at": 0, "has_update": False, "url": "", "error": "",
          "auto_applied": ""}
_lock = threading.Lock()
#: 当前后台检查线程的停止信号。**每次 `start_background` 换一个新的**（见该函数说明）。
_stop = threading.Event()
_thread: "threading.Thread | None" = None


# ---------------- 出网（可 monkeypatch，绝不真连进测试）----------------

def _http_get_json(url: str, token: str = "", timeout: int = 8):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "novelforge",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def parse_version(v: str) -> "tuple[int, ...]":
    v = (v or "").lstrip("vV").strip()
    out: "list[int]" = []
    for p in v.split("."):
        try:
            out.append(int(p))
        except ValueError:
            out.append(0)
    return tuple(out)


def is_newer(remote: str, local: str) -> bool:
    try:
        return parse_version(remote) > parse_version(local)
    except Exception:
        return False


def updater_available() -> bool:
    """是否挂了 docker.sock（默认不挂）。"""
    return os.path.exists(DOCKER_SOCK)


def _update_cfg() -> "dict":
    """读 `update` 段配置（读不到给空 dict）—— 本模块所有配置读点都走这里。

    延迟 import：`config` 在 import 期就固化各目录常量，且 server ↔ updater 有循环引用。
    """
    try:
        from .. import config
        return dict(config.load_config().get("update") or {})
    except Exception:  # noqa: BLE001 —— 配置读不到不该让旁路功能炸掉
        return {}


def configured_image(explicit: str = "") -> str:
    """镜像来源的**唯一读法**：显式入参 > 配置 `update.image` > 环境变量 > 内置默认。

    第 80 期起 `update.image` 真的生效。此前它只出现在白名单与 `GET /api/config` 回显里，
    后端**没有任何读点** —— 用户改完保存，一键更新照旧拉硬编码镜像（假配置）。
    """
    if (explicit or "").strip():
        return explicit.strip()
    val = str(_update_cfg().get("image") or "").strip()
    if val:
        return val
    return (os.getenv("NOVELFORGE_UPDATE_IMAGE") or "").strip() or _DEFAULT_IMAGE


def _split_image(image: str) -> "tuple[str, str]":
    """把镜像名拆成 (repo, tag)。

    只有**最后一个 `/` 之后**的冒号才算 tag —— 否则带端口的私有仓库
    （`localhost:5000/ns/img`）会把端口误判成 tag。镜像名可配之后这点必须对。
    """
    head, sep, tail = (image or "").rpartition("/")
    if ":" in tail:
        repo, _, tag = tail.partition(":")
        return f"{head}{sep}{repo}", (tag or "latest")
    return (image or _DEFAULT_IMAGE), "latest"


def _remote_latest() -> "tuple[str | None, str]":
    """返回 (版本号, release_url)，失败静默返回 ('', '')。"""
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN") or ""
    try:
        data = _http_get_json(_GITHUB_API, token)
        return (data.get("tag_name") or "").lstrip("vV"), data.get("html_url") or ""
    except Exception:
        pass
    # 兜底：/tags 取第一个
    try:
        tags = _http_get_json(f"https://api.github.com/repos/{_REPO}/tags?per_page=1", token)
        if tags:
            return tags[0].get("name", "").lstrip("vV"), f"https://github.com/{_REPO}/releases"
    except Exception:
        pass
    return None, ""


# ---------------- 检查与状态 ----------------

def _local_version() -> str:
    import novelforge.server as s  # 延迟导入，避免循环
    return s.APP_VERSION


def check(force: bool = False, local_version: str = "") -> "dict":
    local_version = local_version or _local_version()
    now = time.time()
    fresh = (now - _state["checked_at"]) < 3600
    if not force and fresh and _state["latest"]:
        return status(local_version)
    latest, url = _remote_latest()
    with _lock:
        _state["latest"] = latest
        _state["checked_at"] = now
        _state["url"] = url
        _state["has_update"] = bool(latest) and is_newer(latest, local_version)
        _state["error"] = "" if latest else "check_failed"
    _persist()
    return status(local_version)


def status(local_version: str = "") -> "dict":
    local_version = local_version or _local_version()
    # 两个开关的真值源是**配置**（不另存一份到 _state / app_state，免得两处说法不一致）。
    ucfg = _update_cfg()
    with _lock:
        return {
            "current": local_version,
            "latest": _state["latest"],
            "has_update": _state["has_update"],
            "checked_at": _state["checked_at"],
            "url": _state["url"],
            "updater_available": updater_available(),
            "error": _state["error"],
            # 第 80 期：把开关如实回显给前端（横幅要能说明「已开启自动更新」）。
            "check_enabled": bool(ucfg.get("check_enabled", True)),
            "auto_apply": bool(ucfg.get("auto_apply", False)),
        }


def _persist() -> None:
    try:
        import novelforge.core.db as db
        db.state_set(_CACHE_KEY, json.dumps({
            "latest": _state["latest"], "checked_at": _state["checked_at"],
            "has_update": _state["has_update"], "url": _state["url"], "error": _state["error"],
            "auto_applied": _state["auto_applied"],
        }))
    except Exception:
        pass


def _load_persisted() -> None:
    try:
        import novelforge.core.db as db
        raw = db.state_get(_CACHE_KEY, "")
        if raw:
            d = json.loads(raw)
            with _lock:
                for k in ("latest", "checked_at", "has_update", "url", "error",
                          "auto_applied"):
                    if k in d:
                        _state[k] = d[k]
    except Exception:
        pass


# ---------------- 后台定时（daemon，测试不养）----------------

def start_background(interval_hours: int = 6) -> None:
    """启动后台检查线程。首个周期后才首检（interval 小时级），避免启动期 / 测试期真连。

    第 80 期：`_stop` 改成**每次启动换一个新 Event**（本函数创建、交给新线程持有）。
    此前是模块级共享 Event + `clear()` 复用 —— 「先 stop 再 start」（改开关 / 改间隔）
    会与正在退出的旧线程抢同一个 Event：旧线程可能还没退出就被 `clear()`，于是继续睡
    下一个周期，结果是两个线程各查各的。各自持有后 `stop_background()` 只影响当前那个
    线程，新线程从干净状态开始 —— **不需要 join，也不会阻塞配置保存**。
    """
    _load_persisted()
    global _thread, _stop
    if _thread is not None and _thread.is_alive() and not _stop.is_set():
        return                                    # 已在跑且没被叫停 ⇒ 不重复起
    _stop = threading.Event()                     # 旧线程攥着旧 Event，不受影响
    _thread = threading.Thread(target=_loop, args=(max(1, int(interval_hours)), _stop),
                               name="update-check", daemon=True)
    _thread.start()


def _loop(interval_hours: int, stop: threading.Event) -> None:
    interval = max(1, int(interval_hours))
    while not stop.wait(interval * 3600):
        try:
            check(force=True)
        except Exception:  # noqa: BLE001 —— 旁路功能，绝不冒泡
            pass
        # 第 80 期：检查完看要不要自动更新（`maybe_auto_apply` 自身也不抛）。
        res = maybe_auto_apply()
        if res.get("auto") and res.get("ok"):
            _log.info("已自动应用更新：%s", res.get("image") or "")
        # 间隔每轮重读 ⇒ 改 `interval_hours` 不必重启线程（下一轮等待即用新值）。
        try:
            interval = max(1, int(_update_cfg().get("interval_hours") or interval))
        except Exception:  # noqa: BLE001
            pass


def stop_background() -> None:
    """叫停当前后台检查线程（不等它退出：它只睡在 Event 上，醒来即结束）。"""
    _stop.set()


def clear_has_update() -> None:
    """清掉「有新版」快照（关掉版本检查时调用，第 80 期）。

    不做这一步，「关掉检查」只是停了线程：侧栏 new 标记与「新功能」页横幅仍会照着
    上一次检查留下的旧快照继续提示 —— 与设置页 hint 的承诺不符。
    """
    with _lock:
        _state["has_update"] = False
    _persist()


# ---------------- 一键更新（docker.sock，默认不挂）----------------

class _UnixSocketConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect(DOCKER_SOCK)


def _docker(method: str, path: str, query: "dict | None" = None,
           body: "str | None" = None, timeout: int = 120) -> "tuple[int, str]":
    conn = _UnixSocketConnection(DOCKER_SOCK, timeout=timeout)
    url = path + ("?" + urllib.parse.urlencode(query) if query else "")
    headers = {"Content-Type": "application/json"} if body is not None else {}
    conn.request(method, url, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read().decode("utf-8", "replace")
    conn.close()
    return resp.status, data


def apply_update(image: str = "") -> "dict":
    """拉取 `update.image` 指的那个镜像并重建自身容器。返回 {ok, stage, ...}。

    未挂载 socket ⇒ 直接告知用户手动升级（降级，不做假交互）。
    """
    if not updater_available():
        return {"ok": False, "stage": "unavailable",
                "message": "未挂载 docker.sock。请在 compose 中启用可选挂载后重试，"
                            "或手动执行：docker compose pull && docker compose up -d"}
    image = configured_image(image)
    repo, tag = _split_image(image)
    try:
        st, _ = _docker("POST", "/images/create", query={"fromImage": repo, "tag": tag})
        if st != 200:
            return {"ok": False, "stage": "pull_failed", "message": f"镜像拉取失败（HTTP {st}）"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "pull_failed", "message": f"镜像拉取失败：{e}"}
    # 重建在延迟后台线程里做，先让本响应返回（否则重启会掐断响应）。
    threading.Thread(target=_recreate, args=(image,), name="update-apply", daemon=True).start()
    return {"ok": True, "stage": "restarting", "image": image}


def maybe_auto_apply() -> "dict":
    """`update.auto_apply` 开时，发现新版就自动应用一次（第 80 期接通）。

    此前这个开关只有 UI 控件、后端**没有任何读点** —— 打开它什么都不会发生（假开关）。
    现在：检查完 → 有新版 ∧ 挂了 socket ∧ 该版本**还没试过** ⇒ 直接 `apply_update()`。

    同一个远端版本只试一次（`auto_applied` 持久化，**先记后做**）：否则 pull 失败后
    每轮检查都会再拉一次（每 6h 一次、每次最长 120s 超时），用户端只表现为
    「一直没更新成功」。失败原因留给日志与 `/api/update/status` 的 `error` 字段。

    返回体带 `auto: True`，便于调用方分辨自动还是手动触发（不改 `apply_update` 的既有形状）。
    """
    try:
        if not bool(_update_cfg().get("auto_apply", False)):
            return {"ok": False, "stage": "disabled", "auto": True}
        with _lock:
            latest = _state["latest"]
            has_update = bool(_state["has_update"])
            tried = _state["auto_applied"]
        if not has_update or not latest:
            return {"ok": False, "stage": "no_update", "auto": True}
        if latest == tried:
            return {"ok": False, "stage": "already_tried", "auto": True}
        if not updater_available():
            # 默认不挂 socket ⇒ 自动更新无从执行，仍由前端提示手动升级（如实降级）。
            return {"ok": False, "stage": "unavailable", "auto": True}
        with _lock:
            _state["auto_applied"] = latest     # 先记后做：失败也不再对同一版本重试
        _persist()
        _log.info("检测到新版本 %s，按 update.auto_apply 自动更新", latest)
        return {**apply_update(), "auto": True}
    except Exception as e:  # noqa: BLE001 —— 旁路功能，绝不冒泡
        _log.exception("自动更新失败：%s", e)
        return {"ok": False, "stage": "error", "message": str(e), "auto": True}


def _recreate(image: str) -> None:
    """pull 之后：取自身 spec → 删旧容器 → 用新镜像重建 → 启动。

    watchtower 同款逻辑。任何一步失败都不该让服务卡死：兜底重启旧容器。
    """
    try:
        name = socket.gethostname()  # compose 设了 container_name；否则是短 id，docker 都认
        st, spec_raw = _docker("GET", f"/containers/{name}/json")
        spec = json.loads(spec_raw)
        cname = (spec.get("Name") or "").lstrip("/") or "novel_dl_convert"
        cfg = dict(spec.get("Config") or {})
        host = spec.get("HostConfig") or {}
        nets = (spec.get("NetworkSettings") or {}).get("Networks") or {}
        body = dict(cfg)
        body["Image"] = image
        body["HostConfig"] = host
        body["NetworkingConfig"] = {"EndpointsConfig": nets}
        # 删旧（force）+ 用新镜像重建（同名）
        _docker("DELETE", f"/containers/{cname}", query={"force": True})
        st2, new_raw = _docker("POST", "/containers/create",
                               query={"name": cname}, body=json.dumps(body))
        if st2 != 201:
            _docker("POST", f"/containers/{cname}/restart", query={"t": 10})
            return
        new_id = (json.loads(new_raw) or {}).get("Id")
        if new_id:
            _docker("POST", f"/containers/{new_id}/start")
    except Exception:  # noqa: BLE001 —— 异常兜底：保证旧容器先起来
        try:
            _docker("POST", f"/containers/{socket.gethostname()}/restart", query={"t": 10})
        except Exception:
            pass
