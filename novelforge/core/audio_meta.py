"""有声书标签解析（第 53 期）：从 m4b/mp3/m4a/opus/ogg/flac 提取演播者（narrators）。

零依赖（纯标准库），覆盖主流有声书容器：

- M4B / M4A / MP4：iTunes ``ilst`` 原子，``©nrt``（narrator）为主，
  ``----`` 自由表（mean ``com.apple.iTunes`` + name ``narrator``）为辅；
- MP3：ID3v2 的 ``TXXX`` 自由文本（描述含 narrator / 演播 / 旁白）；
- FLAC / OGG / OPUS：Vorbis 注释的 ``NARRATOR`` 字段。

一切解析失败都**降级为空**（不影响入库）；只在扫描期对变化文件重解，结果进
``books`` 的 ``narrators`` 字段，绝不写任何文件。解析只读文件头（+ M4B 可能的尾部
``moov``），各上限 2MB，避免巨型有声书整文件入内存拖慢扫描。
"""
from __future__ import annotations

import pathlib

_HEAD_KB = 2048
_TAIL_KB = 2048

_AUDIO_EXTS = {".m4b", ".m4a", ".mp4", ".mp3", ".flac", ".ogg", ".opus"}


def extract(path) -> dict:
    """读音频标签，返回 ``{"narrators": [...]}``；无 / 解析失败返回空 dict。

    ``path`` 应为**单个音频文件**（目录形态请先取首轨文件，见 ``audio.first_audio_file``）。
    """
    try:
        p = pathlib.Path(path)
        ext = p.suffix.lower()
        if ext not in _AUDIO_EXTS:
            return {}
        head, tail = _read_regions(p)
    except Exception:
        return {}

    try:
        if ext in (".m4b", ".m4a", ".mp4"):
            res = _parse_mp4(head)
            if not res.get("narrators") and tail:
                res = _parse_mp4(tail) or res
            return res
        if ext == ".mp3":
            return _parse_mp3(head)
        if ext == ".flac":
            return _parse_flac(head)
        if ext in (".ogg", ".opus"):
            return _parse_ogg(head)
    except Exception:
        return {}
    return {}


def _read_regions(p: pathlib.Path):
    """读文件头（与 M4B 可能的尾部 ``moov``），各上限 2MB，避免巨型有声书整文件入内存。"""
    size = p.stat().st_size
    with p.open("rb") as f:
        head = f.read(_HEAD_KB * 1024)
        tail = b""
        if size > (_HEAD_KB + _TAIL_KB) * 1024:
            try:
                f.seek(-_TAIL_KB * 1024, 2)
                tail = f.read(_TAIL_KB * 1024)
            except OSError:
                tail = b""
    return head, tail


# ---------------- MP4 / M4B / M4A ----------------

def _atoms(data: bytes, start=0, end=None):
    """迭代根层 box，产出 ``(code:str, payload:bytes)``（code 用 latin1 解码，``©nrt`` 即其字面）。"""
    if end is None:
        end = len(data)
    i = start
    while i + 8 <= end:
        size = int.from_bytes(data[i:i + 4], "big")
        code = data[i + 4:i + 8].decode("latin1")
        if size < 8:
            break
        yield code, data[i + 8:i + size]
        i += size


def _parse_mp4(data: bytes) -> dict:
    moov = None
    for code, payload in _atoms(data):
        if code == "moov":
            moov = payload
            break
    if not moov:
        return {}

    # meta 可能在 moov 直接子级，或在 moov -> udta 之下
    meta = None
    for code, payload in _atoms(moov):
        if code == "meta":
            meta = payload
            break
    if meta is None:
        for code, payload in _atoms(moov):
            if code == "udta":
                for _c, _p in _atoms(payload):
                    if _c == "meta":
                        meta = _p
                        break
            if meta:
                break
    if not meta:
        return {}
    # meta box：4 字节 version+flags 之后才是子 box
    body = meta[4:] if len(meta) > 4 else meta
    ilst = None
    for code, payload in _atoms(body):
        if code == "ilst":
            ilst = payload
            break
    if not ilst:
        return {}

    narrators = []
    for code, payload in _atoms(ilst):
        if code == "©nrt":  # 字节 0xA9 0x6E 0x72 0x74，latin1 解码即 "©nrt"
            val = _mp4_data_text(payload)
            if val:
                narrators.append(val)
        elif code == "----":
            name, val = _mp4_freeform(payload)
            if name and name.lower() == "narrator" and val:
                narrators.append(val)
    return {"narrators": narrators}


def _mp4_data_text(payload: bytes) -> str:
    # payload 是 item 内容（含一个 ``data`` 子盒）；取 data 盒内容跳过 8 字节头部后的
    # [4 字节类型][4 字节 locale][值]，再跳过前 8 字节即得值。
    for _code, p in _atoms(payload):
        if _code == "data" and len(p) >= 8:
            return p[8:].decode("utf-8", "replace").strip()
    return ""


def _mp4_freeform(payload: bytes):
    """``----`` 自由表：name box 给字段名、data box 给值。"""
    name = val = None
    for _code, p in _atoms(payload):
        if _code == "name" and len(p) >= 4:
            name = p[4:].decode("utf-8", "replace").strip()
        elif _code == "data" and len(p) >= 8:
            val = p[8:].decode("utf-8", "replace").strip()
    return name, val


# ---------------- MP3 (ID3v2) ----------------

def _syncsafe(b: bytes) -> int:
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _parse_mp3(data: bytes) -> dict:
    if data[:3] != b"ID3" or len(data) < 10:
        return {}
    vmaj = data[3]
    if vmaj not in (2, 3, 4):
        return {}
    end = 10 + _syncsafe(data[6:10])
    pos = 10
    narrators = []
    while pos + 10 <= end and pos + 10 <= len(data):
        if vmaj == 2:
            fid = data[pos:pos + 3].decode("latin1", "replace")
            if not fid.strip("\x00"):
                break
            fsize = int.from_bytes(data[pos + 3:pos + 6], "big")
            p = pos + 6
            step = 6
        else:
            fid = data[pos:pos + 4].decode("latin1", "replace")
            if not fid.strip("\x00"):
                break
            fsize = int.from_bytes(data[pos + 4:pos + 8], "big") if vmaj == 3 else _syncsafe(data[pos + 4:pos + 8])
            p = pos + 10
            step = 10
        if fsize <= 0 or p + fsize > len(data):
            break
        fdata = data[p:p + fsize]
        if fid == "TXXX":
            desc, val = _id3_freeform(fdata)
            if val and ("narrator" in desc.lower() or "演播" in desc or "旁白" in desc):
                narrators.append(val)
        pos += step + fsize
    return {"narrators": narrators}


def _id3_freeform(fdata: bytes):
    """TXXX：编码字节 + 描述\\0值。返回 ``(描述, 值)``。"""
    if not fdata:
        return "", ""
    enc = fdata[0]
    body = fdata[1:]
    if enc == 0:
        text = body.decode("latin1", "replace")
        sep = "\x00"
    elif enc == 3:
        text = body.decode("utf-8", "replace")
        sep = "\x00"
    else:
        text = body.decode("utf-16", "replace")
        sep = "\x00\x00"
    if sep in text:
        desc, val = text.split(sep, 1)
    else:
        desc, val = "", text
    return desc.strip(), val.strip()


# ---------------- FLAC ----------------

def _parse_flac(data: bytes) -> dict:
    if data[:4] != b"fLaC" or len(data) < 5:
        return {}
    pos = 4
    n = len(data)
    while pos + 4 <= n:
        header = data[pos]
        btype = header & 0x7F
        blen = int.from_bytes(data[pos + 1:pos + 4], "big")
        pos += 4
        bdata = data[pos:pos + blen]
        pos += blen
        if btype == 4:  # VORBIS_COMMENT
            return _parse_vorbis_comment(bdata)
        if header & 0x80:
            break
    return {}


# ---------------- OGG / OPUS（Vorbis 注释包）----------------

def _parse_ogg(data: bytes) -> dict:
    for pkt in _ogg_packets(data):
        if pkt[:8] == b"OpusTags":
            return _parse_vorbis_comment(pkt[8:])
        if pkt[:7] == b"\x03vorbis":
            return _parse_vorbis_comment(pkt[7:])
    return {}


def _ogg_packets(data: bytes):
    """把 OGG 页重组为逻辑包（处理跨页续包）。"""
    pos = 0
    n = len(data)
    packets = []
    cur = None
    while pos + 27 <= n and data[pos:pos + 4] == b"OggS":
        pos += 4  # 捕获模式 OggS
        pos += 1  # version（恒 0）
        flags = data[pos]  # header type：bit1 = 续包
        pos += 1
        pos += 8 + 4 + 4 + 4  # granule / serial / pageno / crc
        if pos >= n:
            break
        nsegs = data[pos]
        pos += 1
        seg = list(data[pos:pos + nsegs])
        pos += nsegs
        if len(seg) != nsegs:
            break
        payload = b""
        for s in seg:
            payload += data[pos:pos + s]
            pos += s
        if flags & 0x01:  # 续包：本页开头是上一包的余下部分
            cur = (cur or b"") + payload
        else:
            if cur is not None:
                packets.append(cur)
            cur = payload
        if seg and seg[-1] < 255:  # 末段 < 255 ⇒ 本包结束
            if cur is not None:
                packets.append(cur)
            cur = None
    if cur is not None:
        packets.append(cur)
    return packets


# ---------------- Vorbis 注释（FLAC / OGG / OPUS 共用）----------------

def _parse_vorbis_comment(block: bytes) -> dict:
    pos = 0
    n = len(block)
    if n < 4:
        return {}
    vlen = int.from_bytes(block[pos:pos + 4], "little")
    pos += 4
    pos += vlen
    if pos + 4 > n:
        return {}
    clen = int.from_bytes(block[pos:pos + 4], "little")
    pos += 4
    narrators = []
    for _ in range(clen):
        if pos + 4 > n:
            break
        l = int.from_bytes(block[pos:pos + 4], "little")
        pos += 4
        raw = block[pos:pos + l]
        pos += l
        line = raw.decode("utf-8", "replace")
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip().upper() == "NARRATOR" and v.strip():
                narrators.append(v.strip())
    return {"narrators": narrators}
