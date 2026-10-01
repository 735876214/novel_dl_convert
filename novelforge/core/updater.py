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

#: 自动更新失败后的**退避序列（小时）**，封顶 24h（第 84 期）。
#:
#: 第 80 期是「先记已尝试、再执行」：pull 失败也算记过，此后每轮都 `already_tried`
#: ⇒ **失败一次就永久卡死**，只能手动介入。而 NAS 上镜像拉不下来恰恰是最常见的失败
#: 原因 —— 也就是最需要重试、最不可能自愈的那一种。第 84 期改为「按退避到点时间戳重试」。
_BACKOFF_HOURS = (1, 6, 24)

#: `apply_update` 成功路径的 stage。用来区分「这个版本已经成功换上去了，别再拉」
#: 与「试过了但失败了，退避到点可以再试」—— 两者都记在 `auto_applied` 里。
_AUTO_OK_STAGE = "restarting"

# 第 84 期：`auto_*` 四元组取代第 80 期的「一记了之」。
#   auto_applied      上次**尝试过**的远端版本（不论成败；版本一变失败计数即清零）
#   auto_failures     对该版本的连续失败次数（退避长度的依据）
#   auto_retry_at     下次允许重试的时间戳（0 = 不在退避窗口内）
#   last_auto_result  上次尝试的 stage（"" / restarting / pull_failed / backup_failed / unavailable）
#   auto_message      上次失败的人话原因（界面横幅要显示它，`stage` 本身太干）
_state = {"latest": None, "checked_at": 0, "has_update": False, "url": "", "error": "",
          "auto_applied": "", "auto_failures": 0, "auto_retry_at": 0.0,
          "last_auto_result": "", "auto_message": ""}
#: 持久化到 app_state 的键。**改这里等于改落库形状**（`tests/test_updater.py` 的
#: 往返用例专门钉它，漏一个键就是「重启后静默丢状态」）。
_PERSIST_KEYS = ("latest", "checked_at", "has_update", "url", "error",
                 "auto_applied", "auto_failures", "auto_retry_at",
                 "last_auto_result", "auto_message")
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
            # 第 84 期：自动更新的**退避状态**如实回显 —— 前端要能显示
            # 「自动更新失败：<原因>，将于 <某时> 重试」，而不是让用户对着
            # 一个「有更新」标记猜为什么一直没升上去。
            "auto_failures": _state["auto_failures"],
            "auto_retry_at": _state["auto_retry_at"],
            "last_auto_result": _state["last_auto_result"],
            "auto_message": _state["auto_message"],
        }


def _persist() -> None:
    try:
        import novelforge.core.db as db
        db.state_set(_CACHE_KEY, json.dumps({k: _state[k] for k in _PERSIST_KEYS}))
    except Exception:
        pass


def _load_persisted() -> None:
    try:
        import novelforge.core.db as db
        raw = db.state_get(_CACHE_KEY, "")
        if raw:
            d = json.loads(raw)
            with _lock:
                for k in _PERSIST_KEYS:
                    if k in d:
                        _state[k] = d[k]
    except Exception:
        pass


# ---------------- 后台定时（daemon，测试不养）----------------

def start_background(interval_hours: int = 6) -> None:
    """启动后台检查线程。**启动即跑一轮**（`_tick`），之后每 interval 小时一轮。

    第 80 期：`_stop` 改成**每次启动换一个新 Event**（本函数创建、交给新线程持有）。
    此前是模块级共享 Event + `clear()` 复用 —— 「先 stop 再 start」（改开关 / 改间隔）
    会与正在退出的旧线程抢同一个 Event：旧线程可能还没退出就被 `clear()`，于是继续睡
    下一个周期，结果是两个线程各查各的。各自持有后 `stop_background()` 只影响当前那个
    线程，新线程从干净状态开始 —— **不需要 join，也不会阻塞配置保存**。

    第 84 期：**首轮不再等一个 interval**。此前「等 6h 再首检」 ⇒ 每次容器重启
    （包括自动更新重建容器后的那次启动）都不校验自己是否真到最新，界面就一直挂着
    「有更新」。改成启动即检还有个额外收益：退避状态是持久化的，启动即检能立刻把
    「上次自动更新失败、退避到 X 时」如实显示出来。
    ⚠️ 出网是**显式、可关、失败降级**的（`check` 内部吞掉一切异常），所以启动即检
    不会让服务起不来；`check_enabled=false` 时 `server._apply_update_config` 压根不起线程。
    """
    _load_persisted()
    global _thread, _stop
    if _thread is not None and _thread.is_alive() and not _stop.is_set():
        return                                    # 已在跑且没被叫停 ⇒ 不重复起
    _stop = threading.Event()                     # 旧线程攥着旧 Event，不受影响
    _thread = threading.Thread(target=_loop, args=(max(1, int(interval_hours)), _stop),
                               name="update-check", daemon=True)
    _thread.start()


def _tick() -> None:
    """一轮「检查 + 判自动更新」。启动首轮与定时轮询共用它。

    抽出来是为了**只有一份逻辑**：第 84 期之前这里是 `_loop` 的循环体，改「启动要不要
    也检」时得同时记得改两处 —— 那种「两处各写一份」的形状正是本模块第 80 期那个
    永久卡死缺陷的邻居（同一个版本只在 `_loop` 里被跳过，`apply_update` 手动那条路
    完全不知道有退避这回事）。
    """
    try:
        check(force=True)
    except Exception:  # noqa: BLE001 —— 旁路功能，绝不冒泡
        pass
    # 检查完看要不要自动更新（`maybe_auto_apply` 自身也不抛）。
    res = maybe_auto_apply()
    if res.get("auto") and res.get("ok"):
        _log.info("已自动应用更新：%s", res.get("image") or "")


def _loop(interval_hours: int, stop: threading.Event) -> None:
    interval = max(1, int(interval_hours))
    _tick()                                        # 第 84 期：启动即检（不等一个间隔）
    while not stop.wait(interval * 3600):
        _tick()
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


def apply_update(image: str = "", reason: str = "manual") -> "dict":
    """拉取 `update.image` 指的那个镜像并重建自身容器。返回 {ok, stage, ...}。

    未挂载 socket ⇒ 直接告知用户手动升级（降级，不做假交互）。

    第 84 期：拉镜像**之前**先做一次数据快照（`core.backup.snapshot`），失败即
    ``stage="backup_failed"`` 且**不进入拉取**。这是「删掉自己、重建自己」这种更新
    方式唯一的数据安全网 —— 没有它，一次写坏数据的更新就等于用户的书库没了。
    备份落 `BACKUP_DIR`（持久卷），所以容器重建之后备份还在。

    :param reason: 备份文件名的分组标记（``manual`` / ``auto``），用于分别轮转。
    """
    if not updater_available():
        return {"ok": False, "stage": "unavailable",
                "message": "未挂载 docker.sock。请在 compose 中启用可选挂载后重试，"
                            "或手动执行：docker compose pull && docker compose up -d"}
    from . import backup

    try:
        snap = backup.snapshot(reason)
    except backup.SnapshotError as e:
        _log.error("更新前备份失败，已中止本次更新：%s", e)
        return {"ok": False, "stage": "backup_failed", "message": str(e)}
    except Exception as e:  # noqa: BLE001 —— 备份模块自身炸了也不能带着数据风险往下走
        _log.exception("更新前备份异常，已中止本次更新")
        return {"ok": False, "stage": "backup_failed", "message": f"更新前备份失败：{e}"}
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
    return {"ok": True, "stage": "restarting", "image": image,
            "backup": snap.get("path", "")}


def _fmt_ts(ts: float) -> str:
    """时间戳 → 「2026-10-01 08:30」这种本地格式（给界面横幅用，别把裸 epoch 甩给用户）。"""
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(ts)))
    except Exception:  # noqa: BLE001
        return ""


def _backoff_seconds(failures: int) -> int:
    """第 N 次失败后要等多久（秒）。序列 1h → 6h → 24h 封顶。

    「封顶」很重要：不封顶的话第 4 次失败后要等 48h、48h、96h …… 用户会觉得
    「自动更新坏了」，而实际上它只是被自己上一次的失败推到了两天之后。
    """
    n = max(1, int(failures))
    hours = _BACKOFF_HOURS[min(n, len(_BACKOFF_HOURS)) - 1]
    return hours * 3600


def _record_auto_attempt(latest: str) -> None:
    """**尝试前**记一次（版本 + 进入退避），成功后再清零。

    为什么还是「先记」：这一条要防的不是「失败被当成已试过」（那是第 84 期修的缺陷），
    而是**同一个版本并发两轮**同时去拉 —— `_loop` 的首轮与定时轮、或用户手点「立即更新」
    与自动更新撞在一起。记下版本就等于占住了这个版本的一次尝试机会。
    失败后在 :func:`_record_auto_failure` 里把计数与重试时间写上，退避到点可再试。
    """
    with _lock:
        if _state["auto_applied"] != latest:
            # 换了版本 ⇒ 上一版的失败计数与退避都不作数（新版本是全新机会）
            _state["auto_failures"] = 0
            _state["auto_retry_at"] = 0.0
            _state["auto_message"] = ""
        _state["auto_applied"] = latest
    _persist()


def _record_auto_failure(latest: str, stage: str, message: str) -> None:
    """失败 ⇒ 计数 +1、退避到点时间、记下人话原因。退避封顶 24h。"""
    with _lock:
        n = int(_state["auto_failures"] or 0) + 1
        _state["auto_failures"] = n
        _state["auto_retry_at"] = time.time() + _backoff_seconds(n)
        _state["last_auto_result"] = stage
        _state["auto_message"] = (message or "")[:200]
        _state["auto_applied"] = latest
    _log.warning("自动更新 %s 失败（第 %d 次，%s），%.0f 秒后重试：%s",
                 latest, n, stage, _backoff_seconds(n), message)


def _record_auto_success(latest: str) -> None:
    """成功 ⇒ 记下版本、清零失败计数与退避。"""
    with _lock:
        _state["auto_applied"] = latest
        _state["auto_failures"] = 0
        _state["auto_retry_at"] = 0.0
        _state["last_auto_result"] = _AUTO_OK_STAGE
        _state["auto_message"] = ""
    _persist()


def maybe_auto_apply() -> "dict":
    """`update.auto_apply` 开时，发现新版就自动应用（第 80 期接通；第 84 期改为退避重试）。

    第 80 期那个「先记已尝试、再执行」的形状有个真缺陷：pull 失败也算记过，此后
    每轮检查都 `already_tried` ⇒ **失败一次就永久卡死，只能手动介入**。而 NAS 上
    「镜像拉不下来」恰恰是最常见的失败原因 —— 也就是最需要重试的那一种。

    第 84 期的判定链（顺序即优先级）：

    1. 开关关 → ``disabled``
    2. 同一版本**已经成功换上去了** → ``already_tried``（成功过就别再拉同一个）
    3. 无新版 → ``no_update``
    4. 同一版本试过、失败、且**还在退避窗口内** → ``defer``（``message`` 给出重试时间）
    5. 未挂 socket → ``unavailable``（环境不具备，**不记失败**：用户只是没挂 socket，
       凭什么因此背上一个「失败」和被推后的重试时间）
    6. 其余 ⇒ `apply_update(reason="auto")`；成功清零、失败进退避。

    返回体带 `auto: True`，便于调用方分辨自动还是手动触发（不改 `apply_update` 的既有形状）。
    """
    try:
        if not bool(_update_cfg().get("auto_apply", False)):
            return {"ok": False, "stage": "disabled", "auto": True}
        with _lock:
            latest = _state["latest"]
            has_update = bool(_state["has_update"])
            tried = _state["auto_applied"]
            failures = int(_state["auto_failures"] or 0)
            retry_at = float(_state["auto_retry_at"] or 0)
            last_result = _state["last_auto_result"]
        # ⚠️ **`already_tried` 必须判在 `no_update` 之前**（第 86 期：一次成功自动更新之后
        # `has_update` 会被合法清掉，于是「同一版本已经换过了」会被误报成「没有新版本」）。
        # 顺序反了的表现是**偶发**：谁先跑完取决于「重建容器」那个后台线程与本函数的竞速，
        # 全量运行（别的用例在抢 CPU）时才会翻出来 —— 四条 updater 用例都栽在这里。
        # 判据带 `latest and`：`latest` 还是空串（从未检查过）时不许把 `"" == ""` 当成已试过。
        if latest and latest == tried and last_result == _AUTO_OK_STAGE:
            return {"ok": False, "stage": "already_tried", "auto": True}
        if not has_update or not latest:
            return {"ok": False, "stage": "no_update", "auto": True}
        if latest == tried and failures > 0 and retry_at > time.time():
            return {"ok": False, "stage": "defer", "auto": True,
                    "message": f"上次自动更新失败，退避到 {_fmt_ts(retry_at)} 再试"}
        if not updater_available():
            # 默认不挂 socket ⇒ 自动更新无从执行，仍由前端提示手动升级（如实降级）。
            return {"ok": False, "stage": "unavailable", "auto": True}
        _record_auto_attempt(latest)
        _log.info("检测到新版本 %s，按 update.auto_apply 自动更新", latest)
        res = apply_update(reason="auto")
        if res.get("ok"):
            _record_auto_success(latest)
        else:
            _record_auto_failure(latest, str(res.get("stage") or "error"),
                                 str(res.get("message") or ""))
        return {**res, "auto": True}
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
