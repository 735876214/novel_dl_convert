"""read-along / 媒体叠加 EPUB（第 188 期）。

只认 EPUB3 SMIL：`<par><text src="章节#片段"/><audio src clipBegin clipEnd/></par>`。
没有叠加 / 部分章节缺叠加都如实标注；音频按需提取到缓存，源文件只读。
"""
from __future__ import annotations

import pathlib
import zipfile

from novelforge import config

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""


def _opf(overlay_docs: int, total_docs: int = 1) -> str:
    items = []
    spine = []
    for i in range(1, total_docs + 1):
        overlay = f' media-overlay="smil{i}"' if i <= overlay_docs else ""
        items.append(f'<item id="c{i}" href="Text/{i}.xhtml" media-type="application/xhtml+xml"{overlay}/>')
        spine.append(f'<itemref idref="c{i}"/>')
    for i in range(1, overlay_docs + 1):
        items.append(f'<item id="smil{i}" href="Text/{i}.smil" media-type="application/smil+xml"/>')
    items.append('<item id="aud" href="Audio/a.mp3" media-type="audio/mpeg"/>')
    return f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>朗读测试</dc:title><dc:language>zh</dc:language></metadata>
  <manifest>{''.join(items)}</manifest>
  <spine>{''.join(spine)}</spine>
</package>
"""


def _smil(bad: bool = False) -> str:
    audio = "../../secret.mp3" if bad else "../Audio/a.mp3"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<smil xmlns="http://www.w3.org/ns/SMIL" version="3.0">
  <body><seq>
    <par><text src="1.xhtml#p1"/><audio src="{audio}" clipBegin="0s" clipEnd="1.5s"/></par>
    <par><text src="1.xhtml#p2"/><audio src="../Audio/a.mp3" clipBegin="0:00:02.000" clipEnd="3s"/></par>
  </seq></body>
</smil>
"""


def _build(root, name="朗读.epub", *, overlay_docs=1, total_docs=1, bad_audio=False):
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("OEBPS/content.opf", _opf(overlay_docs, total_docs))
        for i in range(1, total_docs + 1):
            z.writestr(f"OEBPS/Text/{i}.xhtml",
                       f'<html xmlns="http://www.w3.org/1999/xhtml"><body>'
                       f'<p id="p1">第 {i} 章第一句</p><p id="p2">第二句</p></body></html>')
        for i in range(1, overlay_docs + 1):
            z.writestr(f"OEBPS/Text/{i}.smil", _smil(bad_audio))
        z.writestr("OEBPS/Audio/a.mp3", b"ID3\x04\x00\x00\x00" + b"\x00" * 32)
    return p


def _setup(client, auth_headers, make_library, *, lid="lib-ra", root_name="readaloud", **kw):
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / root_name
    make_library(lid, "朗读库", "ebook", root)
    ep = _build(root, **kw)
    cards = client.get("/api/books", headers=auth_headers).json()["items"]
    bid = next(b["id"] for b in cards if b["name"] == ep.name)
    return root, ep, bid


def test_媒体叠加解析与朗读位置(client, auth_headers, make_library):
    _root, _ep, bid = _setup(client, auth_headers, make_library)
    r = client.get(f"/api/books/{bid}/read-aloud", headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["available"] is True and data["status"] == "ready" and data["total"] == 2
    c0, c1 = data["cues"]
    assert c0["text_href"] == "OEBPS/Text/1.xhtml" and c0["fragment"] == "p1"
    assert c0["audio_href"] == "OEBPS/Audio/a.mp3"
    assert c0["clip_begin"] == 0 and c0["clip_end"] == 1.5
    assert c0["chapter_index"] == 0
    assert c1["clip_begin"] == 2.0 and c1["clip_end"] == 3.0

    r = client.put(f"/api/books/{bid}/read-aloud/sync", headers=auth_headers,
                   json={"cue_index": 1, "position_sec": 2.5})
    assert r.status_code == 200
    assert r.json()["cue_index"] == 1 and r.json()["position_sec"] == 2.5
    assert client.get(f"/api/books/{bid}/read-aloud", headers=auth_headers).json()["sync"]["cue_index"] == 1

    for bad in ({"cue_index": 2, "position_sec": 0}, {"cue_index": -1, "position_sec": 0},
                {"cue_index": 0, "position_sec": -1}):
        assert client.put(f"/api/books/{bid}/read-aloud/sync", headers=auth_headers,
                          json=bad).status_code == 400


def test_音频按需提取到缓存_带令牌可播放(client, auth_headers, make_library):
    _root, ep, bid = _setup(client, auth_headers, make_library)
    token = auth_headers["Authorization"][7:]
    href = "OEBPS/Audio/a.mp3"
    assert client.get(f"/api/books/{bid}/read-aloud/audio", params={"p": href}).status_code == 401

    r = client.get(f"/api/books/{bid}/read-aloud/audio",
                   params={"p": href, "token": token})
    assert r.status_code == 200, r.text
    assert r.content.startswith(b"ID3")
    assert r.headers["content-type"] == "audio/mpeg"
    cached = pathlib.Path(config.CACHE_DIR) / "read-aloud" / bid
    assert cached.is_dir() and any(cached.iterdir())
    assert ep.read_bytes()  # 源文件仍在

    # 只允许媒体叠加里登记过的音频
    assert client.get(f"/api/books/{bid}/read-aloud/audio",
                      params={"p": "META-INF/container.xml", "token": token}).status_code == 404


def test_导出无音频副本_源文件不变(client, auth_headers, make_library):
    _root, ep, bid = _setup(client, auth_headers, make_library)
    before = ep.read_bytes()
    r = client.post(f"/api/books/{bid}/read-aloud/export", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/epub+zip"
    out = pathlib.Path(config.CACHE_DIR) / "read-aloud-export" / f"{bid}.epub"
    assert out.is_file()
    with zipfile.ZipFile(out) as z:
        names = set(z.namelist())
        assert "OEBPS/Audio/a.mp3" not in names
        assert "OEBPS/Text/1.smil" not in names
        assert "OEBPS/Text/1.xhtml" in names
        opf = z.read("OEBPS/content.opf").decode("utf-8")
        assert "media-overlay" not in opf
        assert "application/smil+xml" not in opf
    assert ep.read_bytes() == before


def test_没有媒体叠加与部分叠加如实说明(client, auth_headers, make_library):
    _root, _ep, bid = _setup(client, auth_headers, make_library, overlay_docs=0)
    data = client.get(f"/api/books/{bid}/read-aloud", headers=auth_headers).json()
    assert data["available"] is False and data["status"] == "unsupported"
    assert "没有可用的媒体叠加" in data["reason"]
    assert client.put(f"/api/books/{bid}/read-aloud/sync", headers=auth_headers,
                      json={"cue_index": 0, "position_sec": 0}).status_code == 400

    _root, _ep, bid2 = _setup(client, auth_headers, make_library,
                              lid="lib-ra2", root_name="readaloud2",
                              name="部分.epub", overlay_docs=1, total_docs=2)
    data = client.get(f"/api/books/{bid2}/read-aloud", headers=auth_headers).json()
    assert data["available"] is True and data["status"] == "partial"
    assert "部分章节" in data["reason"]
