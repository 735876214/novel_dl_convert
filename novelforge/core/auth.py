"""单用户轻登录：一个账号/PIN 做简单保护（防局域网他人误入），不做多租户/角色。

- 凭证哈希落库（core/db.users），由环境变量 AUTH_USER / AUTH_PIN 初始化。
- Token 为 HMAC-SHA256 签名的无状态串 ``{user}.{exp}.{sig}``，默认 30 天有效。
- 校验密钥取环境变量 AUTH_SECRET，未设置时回退到开发默认值（生产务必覆盖）。
"""
import hashlib
import hmac
import os
import time

from . import db


def _secret() -> bytes:
    return (os.getenv("AUTH_SECRET") or "novelforge-dev-secret-change-me").encode("utf-8")


def verify_pin(user: str, pin: str) -> bool:
    h = hashlib.sha256(f"{user}:{pin}".encode("utf-8")).hexdigest()
    c = db._connect()
    row = c.execute("SELECT pin_hash FROM users WHERE username=?", (user,)).fetchone()
    if not row:
        return False
    return hmac.compare_digest(row["pin_hash"], h)


def issue_token(user: str) -> str:
    exp = int(time.time()) + 60 * 60 * 24 * 30  # 30 天
    body = f"{user}.{exp}".encode("utf-8")
    sig = hmac.new(_secret(), body, hashlib.sha256).hexdigest()
    return f"{body.decode('utf-8')}.{sig}"


def verify_token(token: str) -> "str | None":
    try:
        user, exp, sig = token.split(".")
        exp = int(exp)
    except Exception:
        return None
    if time.time() > exp:
        return None
    body = f"{user}.{exp}".encode("utf-8")
    expected = hmac.new(_secret(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    return user
