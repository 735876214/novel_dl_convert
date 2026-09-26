"""演播者标签解析（第 53 期）：audio_meta.extract 的单元测试 + 扫描落盘集成。

零依赖解析器，覆盖 m4b/mp3/m4a/opus/ogg/flac；一切解析失败降级为空，不影响扫描。
离线约定：造「有声书」用构造的音频标签字节（见下方 builder），不依赖真实音频文件 / 外呼。
"""
import pathlib

import pytest

from novelforge.core import audio_meta


# ---------------- 构造「标准标签字节」的 helper（与真实容器约定一致）----------------

def _atom(code: str, payload: bytes) -> bytes:
    # size 含 8 字节头部（真实容器约定，audio_meta._atoms 据此解析）
    return (8 + len(payload)).to_bytes(4, "big") + code.encode("latin1") + payload


def _build_mp4(narrators):
    items = b""
    for n in narrators:
        data = (1).to_bytes(4, "big") + b"\x00\x00\x00\x00" + n.encode("utf-8")
        items += _atom("\xa9nrt", _atom("data", data))  # ©nrt：演播者
    ilst = _atom("ilst", items)
    meta = _atom("meta", b"\x00\x00\x00\x00" + ilst)
    return _atom("moov", meta)


def _build_vorbis(narrators, is_opus=True):
    vendor = b"libtest"
    comments = b""
    for n in narrators:
        line = f"NARRATOR={n}".encode("utf-8")
        comments += len(line).to_bytes(4, "little") + line
    block = (len(vendor).to_bytes(4, "little") + vendor
             + len(narrators).to_bytes(4, "little") + comments)
    return (b"OpusTags" + block) if is_opus else (b"\x03vorbis" + block)


def _syncsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def _build_mp3(narrators):
    frames = b""
    for n in narrators:
        # TXXX：编码(1) + 描述"narrator" + \0 + 值
        fdata = b"\x00" + "narrator".encode("utf-8") + b"\x00" + n.encode("utf-8")
        frames += b"TXXX" + len(fdata).to_bytes(4, "big") + b"\x00\x00" + fdata
    return b"ID3" + bytes([3, 0]) + b"\x00" + _syncsafe(len(frames)) + frames


def _build_ogg(narrators):
    pkt = _build_vorbis(narrators, True)
    segs = bytes([len(pkt)])
    # OggS ver htype granule(8) serial(4) pageno(4) crc(4) nsegs seg pkt
    return (b"OggS" + b"\x00\x00" + b"\x00" * 8 + b"\x00" * 4 + b"\x00" * 4 + b"\x00" * 4
            + bytes([len(segs)]) + segs + pkt)


def _build_flac(narrators):
    vb = _build_vorbis(narrators, False)[7:]  # 去掉 \x03vorbis 前缀，FLAC 块内即裸 vorbis 注释
    return b"fLaC" + bytes([0x84]) + len(vb).to_bytes(3, "big") + vb


@pytest.mark.parametrize("ext,builder,narrators", [
    ("m4b", _build_mp4, ["小明", "小红"]),
    ("mp3", _build_mp3, ["Jane Voice"]),
    ("m4a", _build_mp4, ["单一演播者"]),
    ("opus", lambda ns: _build_ogg(ns), ["Luke Daniels"]),
    ("ogg", _build_ogg, ["Luke Daniels"]),
    ("flac", _build_flac, ["Foo Bar"]),
])
def test_extract_各格式提取演播者(ext, builder, narrators, tmp_path):
    p = tmp_path / f"x.{ext}"
    p.write_bytes(builder(narrators))
    assert audio_meta.extract(p) == {"narrators": narrators}


def test_extract_中文TXXX描述(tmp_path):
    # 描述用「演播」/「旁白」也应命中（UTF-8 标签用 enc=3）
    frames = b""
    for desc in ("演播", "旁白"):
        fdata = b"\x03" + desc.encode("utf-8") + b"\x00" + "张三".encode("utf-8")
        frames += b"TXXX" + len(fdata).to_bytes(4, "big") + b"\x00\x00" + fdata
    data = b"ID3" + bytes([3, 0]) + b"\x00" + _syncsafe(len(frames)) + frames
    p = tmp_path / "x.mp3"
    p.write_bytes(data)
    # 两条都命中 → 合并为两个演播者
    assert audio_meta.extract(p) == {"narrators": ["张三", "张三"]}


def test_extract_非音频返回空(tmp_path):
    p = tmp_path / "x.txt"
    p.write_bytes(b"not audio at all")
    assert audio_meta.extract(p) == {}


def test_extract_解析异常降级为空(tmp_path):
    # 截断的 M4B：moov 不完整，解析应抛内部异常并被吞掉返回 {}
    p = tmp_path / "x.m4b"
    p.write_bytes(b"\x00\x00\x00\x08moov")  # 声明 8 字节但内容不全
    assert audio_meta.extract(p) == {}


def test_extract_不支持的扩展名返回空(tmp_path):
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4 fake")
    assert audio_meta.extract(p) == {}
