"""外部服务集成（Hardcover / Readwise / StoryGraph）：凭据存储 + 连通性验证。

三家鉴权方式完全不同，而且**没有一家用 OAuth**：

- **Hardcover**：GraphQL（``https://api.hardcover.app/v1/graphql``），
  ``Authorization: Bearer <token>``，token 在账号设置页生成。
  ⚠️ GraphQL 的**鉴权失败也可能返回 200 + ``errors``**，所以不能只看状态码。
- **Readwise**：REST，``Authorization: Token <token>``；验证端点是 ``GET /api/v2/auth/``，
  ⚠️ 它**用 204 表示成功**（不是 200）——按 200 判断会把有效凭据误判为失败。
- **StoryGraph**：**没有公开 API**。上游（BookOrbit）存的是登录态 Cookie
  （``_storygraph_session`` + ``remember_user_token``）并自己注明「可能因对方改版失效」。
  所以这里**不做网络验证**：只保存凭据，并在界面上如实说明 ——
  与其放一个假装能验证的按钮，不如讲清它验证不了（见执行约定「不做假交互」）。

⚠️ 与 OPDS / KOReader 相反：那些是**内网**服务，必须 ``trust_env=False`` 绕开系统代理；
而这里的目标都在**公网**，用户很可能正需要靠代理访问，所以**保留 httpx 默认的 trust_env=True**。
"""
import httpx

#: 连接 8s / 整体 20s：只是个探针，不该让用户等
TIMEOUT = httpx.Timeout(20.0, connect=8.0)

HARDCOVER_GRAPHQL = "https://api.hardcover.app/v1/graphql"
READWISE_AUTH = "https://readwise.io/api/v2/auth/"

#: 服务元数据（前端据此渲染表单与说明，避免前后端各写一份字段定义）
SERVICES = {
    "hardcover": {
        "label": "Hardcover",
        "desc": "把阅读状态与书评同步到 Hardcover",
        "fields": [{"key": "token", "label": "API Token", "type": "password",
                    "hint": "在 Hardcover 账号设置 → API 里生成"}],
        "verify": True,
        "doc": "https://docs.hardcover.app/api/getting-started/",
    },
    "readwise": {
        "label": "Readwise",
        "desc": "把书摘推送到 Readwise",
        "fields": [{"key": "token", "label": "API Token", "type": "password",
                    "hint": "在 readwise.io/access_token 获取"}],
        "verify": True,
        "doc": "https://readwise.io/api_deets",
    },
    "storygraph": {
        "label": "StoryGraph",
        "desc": "把阅读进度同步到 The StoryGraph",
        "fields": [
            {"key": "session", "label": "_storygraph_session", "type": "password",
             "hint": "浏览器里登录 StoryGraph 后从 Cookie 复制"},
            {"key": "remember_token", "label": "remember_user_token", "type": "password",
             "hint": "同上，另一个 Cookie"},
        ],
        "verify": False,
        "doc": "https://app.thestorygraph.com/",
        "note": "StoryGraph **没有公开 API**：这里存的是登录态 Cookie，无法自动验证，"
                "且可能因对方改版而失效（上游同样如此说明）。",
    },
}


def spec(service: str) -> dict:
    return SERVICES.get(service) or {}


def verify(service: str, creds: dict) -> dict:
    """连通性验证。返回 ``{ok, message, detail?}``。

    只对**能验证的**服务发请求；StoryGraph 直接返回 ``unsupported``，
    让前端据此不显示「验证」按钮，而不是给一个永远失败的假按钮。
    """
    creds = creds or {}
    if service == "hardcover":
        return _verify_hardcover(str(creds.get("token") or ""))
    if service == "readwise":
        return _verify_readwise(str(creds.get("token") or ""))
    if service == "storygraph":
        return {
            "ok": False,
            "unsupported": True,
            "message": "StoryGraph 没有公开 API，无法自动验证",
            "detail": "凭据会照常保存；是否仍然有效只能在 StoryGraph 网页上确认。",
        }
    return {"ok": False, "message": f"未知服务：{service}"}


def _verify_hardcover(token: str) -> dict:
    token = token.strip()
    if not token:
        return {"ok": False, "message": "请先填写 API Token"}
    try:
        r = httpx.post(
            HARDCOVER_GRAPHQL,
            timeout=TIMEOUT,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"query": "{ me { id username } }"},
        )
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"连接失败：{e}"}
    if r.status_code in (401, 403):
        return {"ok": False, "message": "Token 无效或无权限"}
    if r.status_code >= 400:
        return {"ok": False, "message": f"服务返回 {r.status_code}"}
    try:
        data = r.json()
    except ValueError:
        return {"ok": False, "message": "返回内容不是 JSON（可能被代理拦截）"}
    # ⚠️ GraphQL 的鉴权失败常常是 200 + errors —— 只看状态码会误判为成功
    if data.get("errors"):
        return {"ok": False, "message": "Token 无效",
                "detail": str(data.get("errors"))[:200]}
    me = (data.get("data") or {}).get("me")
    name = ""
    if isinstance(me, list) and me:
        name = str((me[0] or {}).get("username") or "")
    elif isinstance(me, dict):
        name = str(me.get("username") or "")
    return {"ok": True, "message": f"Token 有效{f'（{name}）' if name else ''}"}


def _verify_readwise(token: str) -> dict:
    token = token.strip()
    if not token:
        return {"ok": False, "message": "请先填写 API Token"}
    try:
        r = httpx.get(
            READWISE_AUTH,
            timeout=TIMEOUT,
            headers={"Authorization": f"Token {token}"},
        )
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"连接失败：{e}"}
    # ⚠️ Readwise 用 **204** 表示验证通过（不是 200）
    if r.status_code == 204:
        return {"ok": True, "message": "Token 有效"}
    if r.status_code in (401, 403):
        return {"ok": False, "message": "Token 无效"}
    return {"ok": False, "message": f"服务返回 {r.status_code}"}
