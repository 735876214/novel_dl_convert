"""建库前只读预扫（第 154 期）。

预扫必须与真正的扫描**同一套判据**（白名单 / 排除 / 目录合并），否则会出现
「预扫说 10 本、建完只有 7 本」。这里用空文件只验格式轴与路径闸门，不验 EPUB 解析。
"""
from __future__ import annotations

import pathlib

from novelforge import config


def _root(name: str) -> pathlib.Path:
    return pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / name


def test_预扫按白名单统计并报跳过(client, auth_headers):
    root = _root("prescan-a")
    root.mkdir(parents=True, exist_ok=True)
    (root / "一.epub").write_bytes(b"x")
    (root / "二.txt").write_bytes(b"x")
    (root / "三.pdf").write_bytes(b"x")
    (root / ".hidden.epub").write_bytes(b"x")
    sub = root / "子目录"
    sub.mkdir(exist_ok=True)
    (sub / "四.epub").write_bytes(b"x")

    r = client.post("/api/libraries/prescan", headers=auth_headers, json={
        "source_dirs": [str(root)], "type": "ebook", "allowed_exts": [".epub"],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["books"] == 2, body  # 顶层「一.epub」+ 子目录「四.epub」（扫描器会下探一层系列目录）
    assert body["by_ext"] == {"epub": 2}, body
    # 顶层非白名单文件算「跳过」；隐藏文件不算（与扫描的 is_hidden_name 一致）
    assert body["skipped_top"] == 2, body
    assert body["items"][0]["exists"] is True and body["items"][0]["readable"] is True


def test_预扫的目录闸门与不存在目录(client, auth_headers, tmp_path):
    r = client.post("/api/libraries/prescan", headers=auth_headers,
                    json={"source_dirs": [str(tmp_path)], "type": "ebook"})
    assert r.status_code == 400, r.text

    root = _root("prescan-empty")
    root.mkdir(parents=True, exist_ok=True)
    r = client.post("/api/libraries/prescan", headers=auth_headers,
                    json={"source_dirs": [str(root)], "type": "ebook"})
    assert r.status_code == 200, r.text
    assert r.json()["books"] == 0

    r = client.post("/api/libraries/prescan", headers=auth_headers,
                    json={"source_dirs": [str(root)], "type": "不存在的类型"})
    assert r.status_code == 400
    r = client.post("/api/libraries/prescan", headers=auth_headers,
                    json={"source_dirs": [], "type": "ebook"})
    assert r.status_code == 400
