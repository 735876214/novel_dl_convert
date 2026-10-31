"""下载文件名模式（第 196 期）：只改 Content-Disposition，不改磁盘文件。"""
from __future__ import annotations

from urllib.parse import unquote

from novelforge import config, server


def test_下载文件名按配置模式(client, auth_headers, isolated, monkeypatch):
    out = config.OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    (out / "三体.epub").write_bytes(b"book-bytes")

    monkeypatch.setattr(server.config, "load_config",
                        lambda: {"download": {"filename_pattern": "{name}-下载.{ext}"}})
    r = client.get("/download/三体.epub", headers=auth_headers)
    assert r.status_code == 200 and r.content == b"book-bytes"
    cd = unquote(r.headers["content-disposition"])
    assert "三体-下载.epub" in cd

    # 非法字符被清洗，不会把响应头 / 路径弄坏
    monkeypatch.setattr(server.config, "load_config",
                        lambda: {"download": {"filename_pattern": "{name}/坏.{ext}"}})
    r = client.get("/download/三体.epub", headers=auth_headers)
    assert r.status_code == 200
    assert "/" not in unquote(r.headers["content-disposition"]).split("filename=")[-1]
    assert (out / "三体.epub").read_bytes() == b"book-bytes"
