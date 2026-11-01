"""自定义图标（第 216 期）：只收 SVG path d，不存完整 SVG。"""
from __future__ import annotations

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <script>alert(1)</script>
  <path d="M4 4h16v16H4z"/>
  <path d="M8 12h8"/>
</svg>"""


def test_创建与列出只保留_path(client, auth_headers, isolated):
    r = client.post("/api/custom-icons", headers=auth_headers,
                    json={"name": "方块", "svg": SVG})
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["name"] == "方块"
    assert item["paths"] == ["M4 4h16v16H4z", "M8 12h8"]
    assert item["key"].startswith("custom-")

    items = client.get("/api/custom-icons", headers=auth_headers).json()["items"]
    assert [x["key"] for x in items] == [item["key"]]

    assert client.delete(f"/api/custom-icons/{item['key']}",
                         headers=auth_headers).status_code == 200
    assert client.delete(f"/api/custom-icons/{item['key']}",
                         headers=auth_headers).status_code == 404
    assert client.get("/api/custom-icons", headers=auth_headers).json()["items"] == []


def test_坏输入如实拒绝(client, auth_headers, isolated):
    cases = [
        {"name": " ", "svg": SVG},
        {"name": "x", "svg": ""},
        {"name": "x", "svg": "<not-svg"},
        {"name": "x", "svg": "<svg><circle cx='2' cy='2' r='1'/></svg>"},
        {"name": "x", "svg": "<svg><path d='" + "M0 0" * 6000 + "'/></svg>"},
    ]
    for body in cases:
        r = client.post("/api/custom-icons", headers=auth_headers, json=body)
        assert r.status_code == 400, (body, r.text)
