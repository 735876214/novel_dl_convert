"""单用户轻登录：一个账号/PIN 做简单保护（防局域网他人误入），不做多租户/角色。

- 凭证哈希落库（core/db.users），由环境变量 AUTH_USER / AUTH_PIN 初始化。
- Token 为 HMAC-SHA256 签名的无状态串 ``{user}.{exp}.{ver}.{sig}``，默认 ``TOKEN_TTL``（30 天）。
- 校验密钥取环境变量 AUTH_SECRET，未设置时回退到开发默认值（生产务必覆盖）。

三条口径（第 136 / 137 期，都是为了「状态说谎」与「闸门只在一条路上」）：

1. **令牌绑定凭据版本**（``ver`` = 凭据指纹）：改密码 / 删账号 ⇒ 旧令牌下一次请求就失效
   （此前签名只覆盖 ``user.exp``，别的设备上那张旧票还能再用 30 天，用户以为「已经踢下线」了）。
   ⚠️ 指纹**必须是不可逆的**（第 137 期修的缺陷）：此前这里拼的是 ``pin_hash[:12]`` 明文，
   而令牌会进 URL（`server._MEDIA_TOKEN_PATHS` / `_with_asset_token`），反代日志与浏览器历史
   都会留档 —— PIN 只有 4–6 位、`_pin_matches` 又是无盐单轮 sha256，拿到那 12 位就能离线
   穷举出 PIN。现在改用 ``HMAC(secret, "user:pin_hash")`` 的截断：外部看到令牌也反推不回凭据，
   而「改 PIN ⇒ 旧令牌失效」的语义不变。
2. **PIN 校验带节流**（内建在 :func:`verify_pin` 里）：PIN 通常只有 4–6 位，没有次数限制时
   局域网里一个 for 循环就能穷举。同一「账号 + 来源 IP」连续失败按指数退避挡在 429。
3. **节流只有这一处实现**（第 137 期修的缺陷）：登录、OPDS Basic、Komga Basic 三条入口
   全部走 :func:`verify_pin`。此前节流挂在 `/api/auth/login` 自己身上，`/opds` 与 `/api/v1`
   虽然同样校验 PIN 却完全不过闸 —— 那两个入口就是没有闸门的 4 位 PIN 预言机。
   所以来源 IP 由调用方传进来（:func:`client_host` 是**唯一**取法），本模块不碰请求对象。
"""
import hashlib
import hmac
import json
import os
import threading
import time

from . import db

#: 令牌有效期（秒）。**唯一一份**：Komga 会话 cookie 的 ``max_age`` 也用它，
#: 别再在别处写第二个 30 天。
TOKEN_TTL = 60 * 60 * 24 * 30  # 30 天

#: 连续失败多少次之后开始退避。
_FAIL_FREE = 5
#: 退避上限（秒）。再多的失败也不会超过它 —— 否则用户自己被锁在门外没法自救。
_FAIL_CAP = 15 * 60

#: ``"账号|来源IP" -> (失败次数, 下次允许尝试的时刻)``。单进程内即够：单用户自托管，
#: 重启清零反而是「管理员救自己」的最后一条路。
_fails: "dict[str, tuple[int, float]]" = {}
_fails_lock = threading.Lock()


class Throttled(Exception):
    """本轮被退避挡住（``wait`` 秒后才允许再试）。

    三个入口的错误形状各不相同（登录是 429 + 中文提示、OPDS / Komga 是 401 + ``WWW-Authenticate``），
    所以这里只表达「被挡住了、还要等多久」，各自转成自己的响应 —— 但**判据只有这一处**。
    """

    def __init__(self, wait: float):
        super().__init__(f"throttled:{int(wait)}")
        self.wait = float(wait)


def _secret() -> bytes:
    return (os.getenv("AUTH_SECRET") or "novelforge-dev-secret-change-me").encode("utf-8")


def _cred_version(user: str) -> str:
    """凭据版本段（``pin_hash`` 的**不可逆**服务端指纹；账号不存在则空串）。

    只截 12 位十六进制：它只用来「区分改没改过密码」，不是保密值 —— 而令牌要短。
    但**输入必须过 HMAC**：直接把 ``pin_hash[:12]`` 放进令牌等于把凭据的半截明文送进日志。
    """
    c = db._connect()
    row = c.execute("SELECT pin_hash FROM users WHERE username=?", (user,)).fetchone()
    if not row:
        return ""
    raw = str(row["pin_hash"] or "")
    return hmac.new(_secret(), f"{user}:{raw}".encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def client_host(request) -> str:
    """请求的来源 IP —— 三条入口（登录 / OPDS / Komga）与退避键的**唯一**取法。

    ``request`` 是 FastAPI 的 ``Request``（鸭子类型即可，测试桩可以是 ``None``）。
    """
    c = getattr(request, "client", None)
    return str(getattr(c, "host", "") or "")


def _throttle_remaining(key: str) -> float:
    """还要等多少秒才允许再试（0 = 现在就可以试）。"""
    with _fails_lock:
        row = _fails.get(key)
        if not row:
            return 0.0
        wait = row[1] - time.time()
        return wait if wait > 0 else 0.0


def _note_failure(key: str) -> None:
    """记一次失败；超过免罚次数后按指数退避（30 s 起，翻倍到 15 min 封顶）。"""
    with _fails_lock:
        n, _ = _fails.get(key, (0, 0.0))
        n += 1
        if n <= _FAIL_FREE:
            _fails[key] = (n, 0.0)
            return
        backoff = min(_FAIL_CAP, 30 * (2 ** (n - _FAIL_FREE - 1)))
        _fails[key] = (n, time.time() + backoff)


def _clear_failures(key: str) -> None:
    with _fails_lock:
        _fails.pop(key, None)


def uses_default_pin() -> bool:
    """是否还有账号在用初始占位口令（`db.DEFAULT_PIN`）。

    比的是**哈希**（与 :func:`_pin_matches` 同一把尺子、同一处实现），所以用户改过口令之后
    自然为 False。`/health` 的 `problems` 与设置页据此提示 —— 默认交付一个口令公开的入口，
    又什么都不说的话，NAS 用户永远不会去改它。
    """
    try:
        c = db._connect()
        rows = c.execute("SELECT username, pin_hash FROM users").fetchall()
    except Exception:                     # noqa: BLE001 —— 探活不该因为查不到而炸
        return False
    return any(hmac.compare_digest(str(r["pin_hash"]), db.pin_hash(str(r["username"]), db.DEFAULT_PIN))
               for r in rows)


def _pin_matches(user: str, pin: str) -> bool:
    h = db.pin_hash(user, pin)
    c = db._connect()
    row = c.execute("SELECT pin_hash FROM users WHERE username=?", (user,)).fetchone()
    if not row:
        return False
    return hmac.compare_digest(row["pin_hash"], h)


def verify_pin(user: str, pin: str, host: str) -> bool:
    """校验 PIN，**内建失败退避**（PIN 的唯一校验点，三个入口都必须走这里）。

    被退避挡住时抛 :class:`Throttled`；否则返回校验结果（失败已记账、成功即清零）。

    ``host`` 是来源 IP（调用方传 :func:`client_host` 的结果）。键里带账号：换一个 IP 继续试
    仍会被**账号**维度的退避挡住 —— 这正是让「一万次穷举」变贵的那个判据。
    """
    key = f"{user}|{host}"
    wait = _throttle_remaining(key)
    if wait > 0:
        raise Throttled(wait)
    if _pin_matches(user, pin):
        _clear_failures(key)
        return True
    _note_failure(key)
    return False


def verify_client(username: str, pin: str, host: str) -> "dict | None":
    """校验**只读客户端凭据**（第 160 期）：成功返回凭据行（含 library_ids），失败 `None`。

    与 :func:`verify_pin` 分开是刻意的：那张表是**管理员账号**，这张表只能读
    `/opds/*`。退避共用同一套实现，但键加 `client:` 前缀 —— 两套凭据的失败计数
    互不连坐（管理员输错不该把正在用的阅读器锁了，反之亦然）。

    ⚠️ 失败一律 `_note_failure`，**包括用户名不存在**：否则「哪些用户名存在」可以
    靠响应时间/退避差异探出来。
    """
    key = f"client:{username}|{host}"
    wait = _throttle_remaining(key)
    if wait > 0:
        raise Throttled(wait)
    row = db.get_client_credential(username)
    if not row or not row.get("enabled"):
        _note_failure(key)
        return None
    if not hmac.compare_digest(str(row.get("pin_hash") or ""), db.pin_hash(username, pin)):
        _note_failure(key)
        return None
    _clear_failures(key)
    db.touch_client_credential(row["id"])
    return row


def client_library_scope(cred: dict) -> "frozenset | None":
    """凭据允许的书库 id 集合；`None` = 不限定（全部可见库）。

    存的是 JSON 数组文本；坏值按「不限定」处理会**放大**权限，所以坏值一律回空集合
    （即什么都看不到）—— 宁可让客户端 404，也不要把本该受限的账号放成全库。
    """
    raw = (cred or {}).get("library_ids")
    if isinstance(raw, list):
        arr = raw
    else:
        text = str(raw or "").strip()
        if not text:
            return None
        try:
            arr = json.loads(text)
        except Exception:
            return frozenset()
    if not isinstance(arr, list):
        return frozenset()
    ids = {str(x) for x in arr if str(x or "").strip()}
    return frozenset(ids) if ids else None


def issue_token(user: str) -> str:
    exp = int(time.time()) + TOKEN_TTL
    body = f"{user}.{exp}.{_cred_version(user)}"
    sig = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def verify_token(token: str) -> "str | None":
    try:
        user, exp, ver, sig = token.split(".")
        exp = int(exp)
    except Exception:
        return None
    if time.time() > exp:
        return None
    body = f"{user}.{exp}.{ver}"
    expected = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    # 密码改过 / 账号已删 ⇒ 这张票作废（同一个 secret 下的旧票也一并作废）
    if not hmac.compare_digest(ver, _cred_version(user)):
        return None
    return user
