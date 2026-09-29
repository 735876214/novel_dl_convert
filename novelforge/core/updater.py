"""版本检查与一键更新（第 78 期）。

检查：定时（默认 6h）/ 启动 / 手动，调 GitHub API 取最新 Release 版本号，
与本地 ``server.APP_VERSION`` 比较。**出网失败静默忽略**（不阻塞、不报错）—— 这
是第一处打破「零外部请求」取向的地方，故只此一处且可关闭。

更新：挂了 ``/var/run/docker.sock`` 时，拉取固定镜像并**重建自身容器**
（pull → 取自身 spec → 删旧 → 用新镜像重建 → 启动）。这是用户明确选择的
「应用真去更新」路径，代价是把宿主机 docker 控制权交给容器，所以**默认不挂载**
（见 ``docker-compose.yml`` 的注释：在 ``volumes`` 下取消注释 ``/var/run/docker.sock`` 那一行）。
未挂载时 ``updater_available()`` 为 ``False``，前端只展示「复制升级命令」。

⚠️ 安全面：本模块**只暴露两个硬编码动作**——拉取**固定镜像名**与重建**自身容器**。
即便 socket 权限等同 root，应用接口面也不会给出任意镜像 / 任意容器 / 任意 exec。
"""
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
import urllib.parse

import http.client  # noqa: F401 —— 仅类型引用；实际连接走 _UnixSocketConnection

DOCKER_SOCK = "/var/run/docker.sock"
_REPO = "735876214/novel_dl_convert"
_GITHUB_API = f"https://api.github.com/repos/{_REPO}/releases/latest"
_CACHE_KEY = "update_check"
# 固定镜像（配置可覆盖）；只允许拉这个，不给「任意镜像」的口子。
_DEFAULT_IMAGE = "ghcr.io/735876214/novel_dl_convert:latest"

# 进程内缓存；持久化进 app_state 跨重启保留。
_state = {"latest": None, "checked_at": 0, "has_update": False, "url": "", "error": ""}
_lock = threading.Lock()
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
    with _lock:
        return {
            "current": local_version,
            "latest": _state["latest"],
            "has_update": _state["has_update"],
            "checked_at": _state["checked_at"],
            "url": _state["url"],
            "updater_available": updater_available(),
            "error": _state["error"],
        }


def _persist() -> None:
    try:
        import novelforge.core.db as db
        db.state_set(_CACHE_KEY, json.dumps({
            "latest": _state["latest"], "checked_at": _state["checked_at"],
            "has_update": _state["has_update"], "url": _state["url"], "error": _state["error"],
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
                for k in ("latest", "checked_at", "has_update", "url", "error"):
                    if k in d:
                        _state[k] = d[k]
    except Exception:
        pass


# ---------------- 后台定时（daemon，测试不养）----------------

def start_background(interval_hours: int = 6) -> None:
    """启动后台检查线程。首个周期后才首检（interval 小时级），避免启动期 / 测试期真连。"""
    _load_persisted()
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, args=(max(1, int(interval_hours)),),
                               name="update-check", daemon=True)
    _thread.start()


def _loop(interval_hours: int) -> None:
    while not _stop.wait(interval_hours * 3600):
        try:
            check(force=True)
        except Exception:  # noqa: BLE001 —— 旁路功能，绝不冒泡
            pass


def stop_background() -> None:
    _stop.set()


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
    """拉取固定镜像并重建自身容器。返回 {ok, stage, ...}。

    未挂载 socket ⇒ 直接告知用户手动升级（降级，不做假交互）。
    """
    if not updater_available():
        return {"ok": False, "stage": "unavailable",
                "message": "未挂载 docker.sock。请在 compose 中启用可选挂载后重试，"
                            "或手动执行：docker compose pull && docker compose up -d"}
    image = image or os.getenv("NOVELFORGE_UPDATE_IMAGE") or _DEFAULT_IMAGE
    repo, _, tag = image.partition(":")
    tag = tag or "latest"
    try:
        st, _ = _docker("POST", "/images/create", query={"fromImage": repo, "tag": tag})
        if st != 200:
            return {"ok": False, "stage": "pull_failed", "message": f"镜像拉取失败（HTTP {st}）"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "stage": "pull_failed", "message": f"镜像拉取失败：{e}"}
    # 重建在延迟后台线程里做，先让本响应返回（否则重启会掐断响应）。
    threading.Thread(target=_recreate, args=(image,), name="update-apply", daemon=True).start()
    return {"ok": True, "stage": "restarting", "image": image}


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
