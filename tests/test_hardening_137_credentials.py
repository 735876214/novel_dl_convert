"""第 137 期凭证加固的三条契约（+ 一条写探针卫生）。

这一轮修的都不是「逻辑写错」，而是**同一件事有了两条路 / 判据放在了错误的一层**：

1. **PIN 退避只在登录一条入口** —— `/opds` 与 `/api/v1` 同样校验 4 位 PIN 却完全不过闸，
   等于把「一万次穷举」送给局域网里任何人。判据必须只有一处（`auth.verify_pin`）。
2. **令牌里带 `pin_hash[:12]` 明文** —— 令牌会进 URL（媒体出口），反代日志 / 浏览器历史
   都会留档；那个哈希是无盐单轮 sha256，拿到 12 位就能离线撞出 PIN。
3. **Komga 会话 cookie 自造** —— 常量兜底密钥 + 只对用户名 HMAC + 无过期 + 不绑凭据版本：
   没设 AUTH_SECRET 的部署，谁都能算出 `hmac_sha256("novelforge-komga", "admin")` 拿到整库。

所以这里的断言分两层：**静态**钉住「旧写法不得复活 / 不得出现第二份实现」，
**功能**钉住「新判据真的生效」（令牌不含哈希前缀、改 PIN 废令牌、cookie 带 max_age 与 Secure）。
"""
import base64
import hashlib
import pathlib
import re

import pytest

from conftest import TEST_PIN, TEST_USER
from novelforge import config
from novelforge.core import auth, db, komga_api

ROOT = pathlib.Path(__file__).resolve().parents[1]
NF = ROOT / "novelforge"


def _src(rel: str) -> str:
    return (NF / rel).read_text(encoding="utf-8")


def _py_files():
    return list(NF.rglob("*.py"))


def _basic(pin: str = TEST_PIN, user: str = TEST_USER) -> dict:
    raw = f"{user}:{pin}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _pin_hash(user: str = TEST_USER) -> str:
    row = db._connect().execute(
        "SELECT pin_hash FROM users WHERE username=?", (user,)).fetchone()
    return str(row["pin_hash"] if row else "")


# ---------------------------------------------------------------------------
# ① 三个入口共用同一套退避（不得出现第二份失败计数）
# ---------------------------------------------------------------------------

def test_失败计数只有一处实现():
    """旧写法：`server.api_login` 自己维护 key/计数/阈值，OPDS 与 Komga 一点不设防。

    判据只许在 `core/auth.py`：别处出现失败计数 / 退避函数名 = 第二份实现。
    """
    names = ("_note_failure(", "_throttle_remaining(", "_clear_failures(", "_FAIL_FREE")
    offenders = []
    for p in _py_files():
        if p.name == "auth.py" and p.parent.name == "core":
            continue                       # 判据本身的实现处
        text = p.read_text(encoding="utf-8")
        for n in names:
            if n in text:
                offenders.append(f"{p.relative_to(ROOT).as_posix()}:{n}")
    assert offenders == [], f"PIN 退避出现了第二份实现：{offenders}"

    # 旧的公开垫片也不许回来：计数必须内建在 verify_pin 里，否则调用点又能绕过
    server = _src("server.py")
    for ghost in ("throttle_remaining", "note_failure", "clear_failures"):
        assert ghost not in server, f"server.py 里还留着旧的节流函数名：{ghost}"


def test_verify_pin_内建退避且要求来源IP():
    """`verify_pin(user, pin, host)` —— host 无默认值：漏传就相当于「不记 IP」，写不出这种事。"""
    sig = re.search(r"def verify_pin\(([^)]*)\)", _src("core/auth.py"))
    assert sig, "auth.verify_pin 不见了"
    assert sig.group(1).replace(" ", "") == "user:str,pin:str,host:str", \
        f"verify_pin 的签名变了（来源 IP 必须由调用方传入）：{sig.group(1)}"
    body = _src("core/auth.py")
    assert "raise Throttled(wait)" in body, "verify_pin 不再在退避期内拒绝"
    assert "_clear_failures(key)" in body, "成功后没清零（退避会一直挂到超时）"


def test_三个入口都把来源IP交给同一处校验(client, monkeypatch):
    """登录 / OPDS Basic / Komga Basic 必须走同一个函数，并把来源 IP 传进去。

    退避键是「账号 + IP」—— 少了 IP 这一维，全世界的失败会混成一个键。
    """
    seen = []
    real = auth.verify_pin

    def spy(user, pin, host):
        seen.append((user, host))
        return real(user, pin, host)

    monkeypatch.setattr(auth, "verify_pin", spy)

    r = client.post("/api/auth/login", json={"user": TEST_USER, "pin": TEST_PIN})
    assert r.status_code == 200, r.text

    # ⚠️ `save_overrides` 是**整份替换**（不是合并）：分两次写会让后一次把前一次的
    # `opds.enabled` 抹掉 —— 于是 `/opds` 一路 404，看着像「退避没生效」（第 137 期实测）。
    config.save_overrides({"opds": {"enabled": True},
                           "komga": {"enabled": True, "username": "admin", "api_key": ""}})
    try:
        assert client.get("/opds", headers=_basic()).status_code == 200
        assert client.get("/api/v1/libraries", auth=(TEST_USER, TEST_PIN)).status_code == 200
    finally:
        config.save_overrides({})

    assert len(seen) == 3, f"三个入口应各校验一次，实际 {seen}"
    assert {u for u, _ in seen} == {TEST_USER}
    assert {h for _, h in seen} == {"testclient"}, f"来源 IP 没传到校验点：{seen}"


def test_OPDS与Komga在退避期内被挡住而不是继续比对PIN(client):
    """这条才是本轮的核心：两个入口此前**无限次**可试。

    前几次是 401（凭据确实不对），退避生效后必须是 429 —— 再返回 401 就等于
    「继续陪你猜」。

    ⚠️ 退避期内**连正确的 PIN 也返回 429**（先看退避、后比对凭据 = fail closed），
    所以收尾不能靠「成功登录把计数清零」：那一步自己就会吃到 429（第 137 期实测）。
    清场直接清进程级状态 `auth._fails`。
    """
    # ⚠️ `save_overrides` 是**整份替换**（不是合并）：分两次写会让后一次把前一次的
    # `opds.enabled` 抹掉 —— 于是 `/opds` 一路 404，看着像「退避没生效」（第 137 期实测）。
    config.save_overrides({"opds": {"enabled": True},
                           "komga": {"enabled": True, "username": "admin", "api_key": ""}})
    try:
        opds = [client.get("/opds", headers=_basic("wrong-pin")).status_code for _ in range(8)]
        assert opds[0] == 401, f"凭据错首先该是 401：{opds}"
        assert 429 in opds, f"OPDS 完全没有退避（PIN 预言机）：{opds}"
        komga = [client.get("/api/v1/libraries",
                            auth=(TEST_USER, "wrong-pin")).status_code for _ in range(3)]
        assert 429 in komga, f"Komga Basic 没有退避：{komga}"
        # 退避期内正确 PIN 也挡住（顺序：先查退避 → 再比对凭据）
        assert client.post("/api/auth/login",
                           json={"user": TEST_USER, "pin": TEST_PIN}).status_code == 429
    finally:
        config.save_overrides({})
        auth._fails.clear()
    # 清零是真的：紧接着再错一次是 401，不是 429
    assert client.post("/api/auth/login",
                       json={"user": TEST_USER, "pin": "wrong-pin"}).status_code == 401


# ---------------------------------------------------------------------------
# ② 令牌里的版本段不可由 pin_hash 推出
# ---------------------------------------------------------------------------

def test_令牌里不含凭据哈希前缀(isolated):
    """旧写法把 `pin_hash[:12]` 明晃晃拼进令牌，而令牌会进 URL / 日志 / 浏览器历史。

    PIN 只有 4–6 位、`_pin_matches` 是无盐单轮 sha256 —— 那 12 位就是「离线穷举的起点」。
    """
    token = auth.issue_token(TEST_USER)
    pin_hash = _pin_hash()
    assert pin_hash, "测试账号没落库"
    assert pin_hash[:12] not in token, "令牌里还带着 pin_hash 前缀"
    user, exp, ver, sig = token.split(".")
    assert ver != pin_hash[:12]
    assert exp.isdigit() and sig and auth.verify_token(token) == TEST_USER


def test_凭据版本段过密钥_换密钥就变(isolated, monkeypatch):
    """版本段必须是**服务端指纹**（HMAC 过密钥），而不是凭据哈希的函数。

    换了 AUTH_SECRET，同一份 `pin_hash` 必须给出不同的版本段 —— 否则「看到令牌」
    就等于「拿到 `hn(pin_hash)` 的一个可离线爆破的样本」。
    """
    pin_hash = _pin_hash()
    v1 = auth.issue_token(TEST_USER).split(".")[2]
    monkeypatch.setenv("AUTH_SECRET", "another-secret-for-this-test")
    v2 = auth.issue_token(TEST_USER).split(".")[2]
    assert _pin_hash() == pin_hash, "本用例不该动凭据"
    assert v1 != v2, "版本段与密钥无关 ⇒ 它是 pin_hash 的直出，不是服务端指纹"


def test_改PIN即作废旧令牌(isolated):
    """第 136 期的语义不许退化：改密码 ⇒ 旧票下次请求就失效。"""
    token = auth.issue_token(TEST_USER)
    assert auth.verify_token(token) == TEST_USER
    db.set_pin(TEST_USER, "another-pin-9")
    assert auth.verify_token(token) is None, "改 PIN 后旧令牌还能用"
    assert auth.verify_token(auth.issue_token(TEST_USER)) == TEST_USER


# ---------------------------------------------------------------------------
# ③ Komga 会话 = auth 签发的那张令牌（带 max_age / secure）
# ---------------------------------------------------------------------------

def test_Komga不再自造会话令牌():
    """删干净：常量兜底密钥与「只对用户名 HMAC」的会话函数都不许留（含兜底常量字面量）。"""
    text = _src("core/komga_api.py")
    for ghost in ("_SESSION_SECRET", "def session_token", "_session_user",
                  "novelforge-komga"):
        assert ghost not in text, f"Komga 自造会话令牌的残留：{ghost}"
    # cookie 里的值必须是应用那张令牌
    assert "auth_mod.verify_token(tok)" in text, "会话 cookie 没走 auth.verify_token"
    # 模块别名两种写法都算（`auth.` / `auth_mod.`），但**必须**是 auth.verify_pin
    assert re.search(r"\bauth(_mod)?\.verify_pin\(", text), \
        "Komga Basic 没走带退避的 auth.verify_pin"


def test_Komga会话cookie带max_age与Secure(client):
    """cookie 三项缺一不可：由 auth 签发（HttpOnly + Max-Age=TOKEN_TTL）、按实际 TLS 打 Secure。"""
    config.save_overrides({"komga": {"enabled": True, "username": "admin", "api_key": ""}})
    try:
        r = client.post("/api/v1/login", auth=(TEST_USER, TEST_PIN))
        assert r.status_code == 204, r.text
        cookie = r.headers.get("set-cookie", "").lower()
        assert f"max-age={auth.TOKEN_TTL}" in cookie, f"cookie 没有过期（永不过期）：{cookie}"
        assert "httponly" in cookie
        assert "secure" not in cookie, "明文部署不该打 Secure（那样 cookie 根本发不出去）"
        # 令牌本体就是 auth 签发的那张（不是自造的 32 位裸 HMAC）
        token = client.cookies.get(komga_api.SESSION_COOKIE)
        assert token and auth.verify_token(token) == TEST_USER
        # cookie 这条认证通道真的能用（不带 Basic / X-API-Key）
        assert client.get("/api/v1/libraries").status_code == 200

        # TLS 判据来自请求实际协议（反代给 X-Forwarded-Proto）
        r2 = client.post("/api/v1/login", auth=(TEST_USER, TEST_PIN),
                         headers={"x-forwarded-proto": "https"})
        assert "secure" in r2.headers.get("set-cookie", "").lower(), \
            "https 下必须打 Secure（判据：_request_scheme）"
    finally:
        config.save_overrides({})


def test_Komga会话随改PIN失效(client):
    """自造令牌的另一半缺陷：不绑凭据版本 ⇒ 改完 PIN 也踢不掉已下发的那张 cookie。"""
    config.save_overrides({"komga": {"enabled": True, "username": "admin", "api_key": ""}})
    try:
        assert client.post("/api/v1/login", auth=(TEST_USER, TEST_PIN)).status_code == 204
        assert client.get("/api/v1/libraries").status_code == 200
        db.set_pin(TEST_USER, "another-pin-9")
        assert client.get("/api/v1/libraries").status_code == 401, "改 PIN 后旧 cookie 还能进"
    finally:
        config.save_overrides({})


def test_Secure判据只有一处且来自请求协议():
    """`_request_scheme` 是「客户端实际协议」的唯一判据（OPDS 链接与 cookie 共用）。

    刻意**不用** `network.verify_tls`：那个开关管的是出站抓书源时校不校验证书，
    与本部署自己是不是 HTTPS 无关 —— 拿它当判据会让明文部署误以为在 TLS 后面。
    """
    server = _src("server.py")
    assert server.count('headers.get("x-forwarded-proto")') == 1, \
        "X-Forwarded-Proto 的解析被抄成了第二份"
    assert "secure=_request_scheme(request)" in server, "cookie 的 Secure 没走统一判据"
    assert "verify_tls_enabled" not in server.split("_request_scheme")[1][:2000], \
        "Secure 判据不该拿 network.verify_tls（出站口径）"


# ---------------------------------------------------------------------------
# 附带：`GET /api/libraries` 的写探针不得在用户目录留垃圾 / 互相踩
# ---------------------------------------------------------------------------

def test_写探针名字唯一且一定清理():
    """固定名 `.nf-write-probe` 的两个后果：并发请求互相 unlink（可写被报成只读）、
    异常路径把垃圾永久留在用户的**书目录**里。"""
    text = _src("server.py")
    start = text.index("def _writable_dir(")
    body = text[start:text.index("def _library_dto(", start)]
    assert '".nf-write-probe"' not in body, "探针退回固定名（并发会互相踩）"
    assert "uuid.uuid4().hex" in body, "探针名没有随机后缀"
    assert "finally:" in body, "清理没走 finally（异常时垃圾留在书目录）"
    assert "unlink(missing_ok=True)" in body


def test_写探针在只读目录下也留不下东西(tmp_path):
    """真实跑一遍：可写目录返回 True 且不留文件；只读目录返回 False 且不留文件。"""
    from novelforge import server as server_mod

    ok_dir = tmp_path / "writable"
    ok_dir.mkdir()
    assert server_mod._writable_dir(ok_dir) is True
    assert list(ok_dir.iterdir()) == [], "写探针没清理干净"

    bad_dir = tmp_path / "missing"          # 不存在的目录 = write_text 必抛
    assert server_mod._writable_dir(bad_dir) is False
    assert not bad_dir.exists(), "探针把不该建的目录建出来了"
