"""版本标识同源（第 30 期）：/health 下发的 version 必须等于后端唯一常量。

防止再分叉出第二个真值源（历史坑：后端写死 0.5.0、前端又手写 v0.6，两处各说各话）。

第 95 期补了第二条：`_read_version()` 的**兜底值**不许再是一个像样的版本号 ——
它读不到 `VERSION` 时曾回一个具体的版本字面量，而那等于把「部署不完整」伪装成
「本应用就是那个版本」，且原有契约（只验非空 + 等于 APP_VERSION）根本发现不了。
"""
import pathlib
import re

from novelforge import server

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER_PY = ROOT / "novelforge" / "server.py"


def test_health_exposes_version_matching_single_source(client):
    # ⚠️ 路径是 `/health`，**不是** `/api/health`：`/health` 在鉴权中间件白名单内
    # （`server.py` 的 `_auth_middleware`），`/api/health` 根本没有这个路由、且会被中间件拦成 401。
    # 前端也调 `/health`（`lib/api.ts` 的 `health()`），三处必须同口径。
    r = client.get("/health")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "version" in body, "/health 必须下发 version"
    assert body["version"] == server.APP_VERSION
    assert body["version"], "版本号不应为空"


def test_版本真值源就是仓库根的VERSION文件():
    """`_read_version()` 必须原样给出仓库根 `VERSION` 的内容（别读别处、别加工）。"""
    expected = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    assert expected, "仓库根 VERSION 不该是空的"
    assert server._read_version() == expected
    assert server.APP_VERSION == expected


def test_没有第二份版本字面量():
    """§7.1：清掉「读不到 VERSION 就回一个像样版本号」那条兜底。

    早先 `_read_version()` 末尾是「记一条 warning + `return` 某个具体版本」，于是一台
    **缺了 VERSION 的部署**对外报的是一个**看起来完全正常**的版本号；
    而契约只验「非空且 == APP_VERSION」⇒ 谁都不会发现。

    现在兜底是一个**哨兵值**（`updater.parse_version()` 把它解析成 `(0, 0, 0)` ⇒
    任何真实版本都比它新，更新提示照常给出）。这条用例钉住：兜底不再是版本号，
    且 `server.py` 里除哨兵外**没有别的 `"数字.数字"` 形态字面量**。
    """
    src = SERVER_PY.read_text(encoding="utf-8")
    m = re.search(r'^_VERSION_UNKNOWN = "([^"]+)"', src, re.M)
    assert m, "找不到 `_VERSION_UNKNOWN` 哨兵定义"
    sentinel = m.group(1)
    assert not re.fullmatch(r"\d+(\.\d+)*", sentinel), \
        f"兜底值 {sentinel!r} 看起来像个真版本号 —— 它会掩盖「部署缺 VERSION」"
    assert "VERSION" in src and "read_text" in src, "版本真值源仍应是读 VERSION 文件"

    # 除哨兵外，不许再有 `"1.2.3"` 这种字面量（历史值就是 `"0.80.0"`）
    others = [v for v in re.findall(r'"(\d+\.\d+(?:\.\d+)?)"', src) if v != sentinel]
    assert not others, f"server.py 里又出现了版本形态的字面量：{others}"


def test_哨兵值让更新检查仍然可用():
    """哨兵不能把「检查更新」弄坏：`parse_version()` 要把它当 0，真实版本一律比它新。"""
    from novelforge.core import updater

    assert updater.parse_version(server._VERSION_UNKNOWN) == (0, 0, 0)
    assert updater.is_newer("0.94.0", server._VERSION_UNKNOWN) is True
