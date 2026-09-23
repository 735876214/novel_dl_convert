"""第 43 期：偏好载荷新增 `shelf` 块（承载书架「系列默认折叠」）。

块名是**前后端两处真值源**（后端 `server.PREFS_BLOCKS`、前端 `prefsPayload.ts` 的
`PAYLOAD_BLOCKS`）。两处漂移的表现很隐蔽：推上去被 400 拒（前端还以为存了）、
或拉回来时前端认不出这一块（静默丢字段）。所以这里既钉行为、也钉两端逐字一致。
"""
from __future__ import annotations

import pathlib
import re

from novelforge import server

ROOT = pathlib.Path(__file__).resolve().parents[1]
PREFS_PAYLOAD_TS = ROOT / "frontend" / "src" / "lib" / "prefsPayload.ts"


def test_后端块白名单含shelf():
    assert "shelf" in server.PREFS_BLOCKS


def test_创建含shelf块的模式成功(client, auth_headers):
    r = client.post(
        "/api/prefs/profiles",
        headers=auth_headers,
        json={"name": "测试模式", "payload": {"shelf": {"collapseSeries": True}}},
    )
    assert r.status_code == 200, r.text
    assert r.json()["payload"]["shelf"]["collapseSeries"] is True


def test_未知块被拒(client, auth_headers):
    r = client.post(
        "/api/prefs/profiles",
        headers=auth_headers,
        json={"name": "坏模式", "payload": {"nope": {}}},
    )
    assert r.status_code == 400


def test_前端块清单与后端逐字一致():
    """`PAYLOAD_BLOCKS` 必须与后端 `PREFS_BLOCKS` 完全一致（顺序无关，集合相等）。"""
    ts = PREFS_PAYLOAD_TS.read_text(encoding="utf-8")
    m = re.search(r"PAYLOAD_BLOCKS\s*=\s*\[([^\]]*)\]", ts)
    assert m, "prefsPayload.ts 里找不到 PAYLOAD_BLOCKS"
    front = set(re.findall(r"'([a-z]+)'", m.group(1)))
    assert front == set(server.PREFS_BLOCKS), (
        f"前端 {sorted(front)} vs 后端 {sorted(server.PREFS_BLOCKS)}"
    )
