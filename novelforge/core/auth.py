"""单用户轻登录：一个账号/PIN 做简单保护（防局域网他人误入），不做多租户/角色。

- 凭证哈希落库（core/db.users），由环境变量 AUTH_USER / AUTH_PIN 初始化。
- Token 为 HMAC-SHA256 签名的无状态串 ``{user}.{exp}.{ver}.{sig}``，默认 30 天有效。
- 校验密钥取环境变量 AUTH_SECRET，未设置时回退到开发默认值（生产务必覆盖）。

两条口径（第 136 期，都是为了「状态说谎」）：

1. **令牌绑定凭据版本**（``ver``）：签名里带上 ``pin_hash`` 的前 12 位。此前签名只覆盖
   ``user.exp`` —— 改完密码，别的设备上那张旧票还能再用 30 天，用户以为「已经踢下线」了。
   现在改密码 / 删账号 ⇒ 旧令牌下一次请求就失效（代价：升级后需重新登录一次，如实告知）。
2. **登录失败节流**：PIN 通常只有 4–6 位，此前没有任何次数限制 —— 局域网里一个 for 循环
   就能穷举。现在同一「账号 + 来源 IP」连续失败会按指数退避挡在 429。
"""
import hashlib
import hmac
import os
import threading
import time

from . import db

#: 连续失败多少次之后开始退避。
_FAIL_FREE = 5
#: 退避上限（秒）。再多的失败也不会超过它 —— 否则用户自己被锁在门外没法自救。
_FAIL_CAP = 15 * 60

#: ``key -> (失败次数, 下次允许尝试的时刻)``。单进程内即够：单用户自托管，重启清零
#: 反而是「管理员救自己」的最后一条路。
_fails: "dict[str, tuple[int, float]]" = {}
_fails_lock = threading.Lock()


def _secret() -> bytes:
    return (os.getenv("AUTH_SECRET") or "novelforge-dev-secret-change-me").encode("utf-8")


def _cred_version(user: str) -> str:
    """该账号当前凭据的版本号（``pin_hash`` 前 12 位；账号不存在则空串）。

    取前 12 位而不是全长：它只用来「区分改没改过密码」，不是保密值 —— 而令牌要短。
    """
    c = db._connect()
    row = c.execute("SELECT pin_hash FROM users WHERE username=?", (user,)).fetchone()
    if not row:
        return ""
    return str(row["pin_hash"] or "")[:12]


def verify_pin(user: str, pin: str) -> bool:
    h = hashlib.sha256(f"{user}:{pin}".encode("utf-8")).hexdigest()
    c = db._connect()
    row = c.execute("SELECT pin_hash FROM users WHERE username=?", (user,)).fetchone()
    if not row:
        return False
    return hmac.compare_digest(row["pin_hash"], h)


def issue_token(user: str) -> str:
    exp = int(time.time()) + 60 * 60 * 24 * 30  # 30 天
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


def throttle_remaining(key: str) -> float:
    """还要等多少秒才允许再试（0 = 现在就可以试）。"""
    with _fails_lock:
        row = _fails.get(key)
        if not row:
            return 0.0
        wait = row[1] - time.time()
        return wait if wait > 0 else 0.0


def note_failure(key: str) -> None:
    """记一次失败；超过免罚次数后按指数退避（30 s 起，翻倍到 15 min 封顶）。"""
    with _fails_lock:
        n, _ = _fails.get(key, (0, 0.0))
        n += 1
        if n <= _FAIL_FREE:
            _fails[key] = (n, 0.0)
            return
        backoff = min(_FAIL_CAP, 30 * (2 ** (n - _FAIL_FREE - 1)))
        _fails[key] = (n, time.time() + backoff)


def clear_failures(key: str) -> None:
    with _fails_lock:
        _fails.pop(key, None)
