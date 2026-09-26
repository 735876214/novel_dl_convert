"""第 57 期：书源试搜端点（`POST /api/sources/test`）契约。

「手动添加书源（表单）」的两个承诺靠它兜底：

1. **保存前先试**：规则校验错误逐条回给用户看，而不是等服务端 500；
2. **试搜不落盘**：测试用的规则只存在于本次请求 —— 写盘的**唯一**入口仍是 `store.add_rule`
   （`POST /api/sources`），否则「随手测一下」就会污染用户的 `SOURCES_DIR`。
"""
import pathlib

from novelforge import config

#: 一条合法规则（校验全过），各用例按需改字段
_RULE = {
    "name": "my-test-source",
    "display_name": "测试源",
    "domains": ["example.com"],
    "search": {"url": "https://example.com/s?q={title}", "mode": "regex",
               "pattern": '<a href="(?P<url>[^"]+)">(?P<title>[^<]+)</a>'},
    "book": {"mode": "single", "content": {"mode": "css", "container": "#content", "text": True}},
    "chapter": {"mode": "auto"},
}


def _stub(items):
    async def _fn(self, cls, title):
        assert title, "试搜必须带关键词"
        return items
    return _fn


def _saved_names() -> set:
    d = pathlib.Path(config.SOURCES_DIR)
    return {p.name for p in d.glob("*.json")} if d.is_dir() else set()


def test_规则校验错误逐条返回(client, auth_headers, isolated):  # noqa: ARG001
    r = client.post("/api/sources/test", headers=auth_headers,
                    json={"rule": {"name": "x"}, "query": "三体"})
    body = r.json()

    assert r.status_code == 200, r.text
    assert body["ok"] is False and body["count"] == 0
    assert any("domains" in e for e in body["errors"]), body["errors"]
    assert any("search.url" in e for e in body["errors"]), body["errors"]


def test_非对象规则也被如实拒绝(client, auth_headers, isolated):  # noqa: ARG001
    r = client.post("/api/sources/test", headers=auth_headers,
                    json={"rule": "不是对象", "query": "三体"})
    body = r.json()

    assert body["ok"] is False
    assert body["errors"] == ["规则必须是一个 JSON 对象"], body


def test_试搜返回命中且绝不落盘(client, auth_headers, isolated, monkeypatch):  # noqa: ARG001
    from novelforge.sources import DownloadManager
    monkeypatch.setattr(DownloadManager, "test_source",
                        _stub([{"title": "三体", "author": "刘慈欣", "url": "https://example.com/1"}]))

    before = _saved_names()
    r = client.post("/api/sources/test", headers=auth_headers,
                    json={"rule": _RULE, "query": "三体"})
    body = r.json()

    assert body["ok"] is True and body["count"] == 1, body
    assert body["items"][0] == {"title": "三体", "author": "刘慈欣",
                                "url": "https://example.com/1"}
    assert _saved_names() == before, "试搜不能写盘"
    listed = client.get("/api/sources", headers=auth_headers).json()["sources"]
    assert "my-test-source" not in {s["name"] for s in listed}, "试搜不该注册该书源"


def test_已注册源可按名字试搜(client, auth_headers, isolated, monkeypatch):  # noqa: ARG001
    from novelforge.sources import DownloadManager
    monkeypatch.setattr(DownloadManager, "test_source",
                        _stub([{"title": "T", "author": "A", "url": "u"}]))

    r = client.post("/api/sources/test", headers=auth_headers,
                    json={"name": "gutenberg", "query": "三体"})

    assert r.status_code == 200 and r.json()["ok"] is True, r.text


def test_未知书源名字回404(client, auth_headers, isolated):  # noqa: ARG001
    r = client.post("/api/sources/test", headers=auth_headers,
                    json={"name": "根本不存在的源", "query": "x"})

    assert r.status_code == 404, r.text


def test_运行期错误转成文案而不是500(client, auth_headers, isolated, monkeypatch):  # noqa: ARG001
    """试搜失败的原因（网络 / 选择器不匹配）要如实显示给写规则的人，不能变成 500。"""
    from novelforge.sources import DownloadManager

    async def boom(self, cls, title):
        raise RuntimeError("连接失败：域名不在白名单内")

    monkeypatch.setattr(DownloadManager, "test_source", boom)

    r = client.post("/api/sources/test", headers=auth_headers,
                    json={"rule": _RULE, "query": "x"})
    body = r.json()

    assert r.status_code == 200, r.text
    assert body["ok"] is False and "域名不在白名单" in body["error"], body
