"""第 144 期（部署与运维面）的防回归判据。

这一期没有新增接口，全是「运维能看见什么」：
`/health` 说真话、镜像里该有的客户端真的有、健康检查认得自定义端口、死开关不再假装还在用。

⚠️ 为什么这些必须进 pytest：它们是**静态判据**（Dockerfile / compose 的字面量）和
**只读接口的语义**（`/health` 的 `status` / `problems`），没有任何运行时用例会顺带覆盖到；
上一轮（第 141 期）把 `/health` 的 `status` 从写死 `"ok"` 改成真话，就是因为没人钉住它。
"""
import pathlib

from fastapi.testclient import TestClient

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _client():
    from novelforge import server
    return TestClient(server.app), server


# ---------------- 镜像与编排的静态判据 ----------------

def test_镜像里带_pg_dump_客户端():
    """PG 后端下「更新前自动备份」唯一依赖 `pg_dump`（`core/backup.snapshot`）。

    第 144 期审计（部署面）：镜像里根本没有 `pg_dump` ⇒ 走 PostgreSQL 的部署
    每次更新都静默 `backup_failed`、连备份列表都是空的，而文档还写着「自动备份」。
    """
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = text.split("FROM python:", 1)[-1] if "FROM python:" in text else text
    assert "postgresql-client" in runtime, "运行阶段必须装 postgresql-client，否则 PG 备份永远失败"
    assert "pg_dump" in runtime, "装它的理由要写进注释（客户端主版本必须 ≥ 服务端）"


def test_健康检查认得自定义端口():
    """`PORT=9000` 时 HEALTHCHECK 还在探 8000 ⇒ 容器永远 unhealthy。

    全仓 9 处 8000 里只有这一处**拼在健康检查命令里**，其余都跟着 `$PORT` 走。
    """
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    hc = text.split("HEALTHCHECK", 1)[1].split("\n\n", 1)[0]
    assert "PORT" in hc, "HEALTHCHECK 必须跟着 $PORT 走"
    # 允许 `or '8000'` 这种**缺省值**，但端口不能拼进 URL 字面量里
    assert ":8000" not in hc, "健康检查里不该出现硬编码端口的 URL"


def test_死开关_ebook_convert_bin_不再出现():
    """`EBOOK_CONVERT_BIN` 这个能力第 62 期就被删了，但镜像与编排里还留着开关。

    文档说「用环境变量传入 ebook-convert 路径」—— 那个变量早已无人读取，
    设了也不会有任何效果（典型的「假交互」）。
    """
    for rel in ("Dockerfile", "docker-compose.yml", "docker-compose.test.yml"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        # 允许在注释里**解释它为什么被删**，但不许再留可打开的开关行
        assert "EBOOK_CONVERT_BIN=" not in text, f"{rel} 还留着可打开的 EBOOK_CONVERT_BIN 开关"


def test_compose_健康检查用_PORT():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    # compose 里有三个 healthcheck（PG / Redis / 应用），按「探 /health」挑应用那个
    chunks = [c[:400] for c in text.split("healthcheck:")[1:]]
    app = [c for c in chunks if "/health" in c]
    assert app, "compose 里找不到探 /health 的健康检查"
    hc = app[0]
    assert "PORT" in hc and ":8000" not in hc, f"应用的健康检查也要认 $PORT：{hc}"


# ---------------- /health 的两条新真话 ----------------

def test_设置文件读坏时_health_降级并说明原因():
    """设置覆盖层读不出来时服务照跑（按默认值），但 `/health` 必须报出来。

    第 144 期审计（部署面）：compose 里把 `/app/config` 换挂成目录、又按注释切 `user:` 之后，
    设置文件会变成不可读 —— 表现是「设置全回落默认值 + 保存报错 + `/health` 全绿」,
    用户唯一的线索是「我明明配过」。所以这条读不出来的事实必须出现在 `problems` 里。
    """
    from novelforge import config

    client, _ = _client()
    orig = config.overrides_error
    try:
        config.overrides_error = lambda: ValueError("坏掉的 JSON")
        body = client.get("/health").json()
    finally:
        config.overrides_error = orig
    assert body["checks"]["settings_readable"] is False
    assert any("设置覆盖层" in p and "坏掉的 JSON" in p for p in body["problems"]), body["problems"]
    assert body["status"] == "degraded"


def test_默认口令时_health_提醒改密码(client):
    """`AUTH_PIN` 缺省仍是 changeme —— 部署说明写着「务必改」，服务端就该自己报出来。

    用 conftest 的 `client` 夹具（它会建库、建表、种账号），不要自己 new 一个 TestClient：
    那样没有 `users` 表，改口令会直接 `no such table`。
    """
    from tests.conftest import TEST_PIN, TEST_USER
    from novelforge.core import db

    try:
        db.set_pin(TEST_USER, db.DEFAULT_PIN)
        body = client.get("/health").json()
    finally:
        db.set_pin(TEST_USER, TEST_PIN)          # 复原，别把退避之外的登录态带坏
    assert body["checks"]["default_pin"] is False
    assert any("初始口令" in p for p in body["problems"]), body["problems"]
    assert body["status"] == "degraded"
