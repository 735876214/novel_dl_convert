"""阅读字体：上传 / 列表 / 分发。

背景：此前**后端零字体能力**——阅读器只能选 3 个内置 CSS 字体栈，
用户想读自己装的宋体 / 思源没有入口。这里补齐。

设计要点：
- 字体是**可选附属资源**：不解析内部名称也能用（回落文件名），
  TTF/OTF 会尽力读出 `name` 表里的字体族名，界面显示更像样；
  WOFF/WOFF2 是压缩格式，读族名要先解压，这里不做，直接回落文件名。
- 只用标准库解析 name 表（不引入 fontTools）：项目要求零外部依赖/零外部请求，
  而 name 表结构简单（表目录 + 12 字节记录项），自己解析约 40 行且全程容错。
- 删除是**真删**（unlink），与工具页「删除即移入回收目录」不同 ——
  那条纪律保护的是**书籍内容**（误删不可恢复），而字体是用户自己上传的
  附属资源，留在回收站只会变成垃圾。
"""
import os
import pathlib
import struct
import time

from .. import config

# 白名单：与上游一致（TTF / OTF / WOFF / WOFF2）
FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2"}
# 单个上限 50MB、总量 200 —— 采上游「Server Fonts」口径（本项目单用户，无每用户配额）
MAX_FONT_BYTES = int(os.getenv("MAX_FONT_BYTES") or 50 * 1024 * 1024)
MAX_FONTS = int(os.getenv("MAX_FONTS") or 200)


def fonts_dir() -> pathlib.Path:
    d = config.FONTS_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_name(filename: str) -> str:
    """只保留基名并剔除路径分隔符与可疑字符（防路径穿越写进其它目录）。"""
    base = pathlib.PurePath(filename or "").name
    keep = [c for c in base if c.isalnum() or c in "._- " or ord(c) > 127]
    name = "".join(keep).strip().strip(".")
    return name or "font"


def _ttf_names(data: bytes) -> tuple:
    """从 TTF/OTF 的 `name` 表读出 (字体族名, 子样式)。任何异常都返回 ("", "")。

    结构：表目录 12 字节头 + 每张表 16 字节记录；name 表内是
    6 字节头（格式/记录数/字符串区偏移）+ 每条 12 字节记录。
    """
    try:
        if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            return ("", "")  # 非 TTF/OTF（如 WOFF、ttcf 字体集合）不解析
        num_tables = struct.unpack(">H", data[4:6])[0]
        name_off = 0
        for i in range(min(num_tables, 64)):
            off = 12 + i * 16
            if off + 16 > len(data):
                return ("", "")
            rec = data[off:off + 16]
            if rec[:4] == b"name":
                name_off = struct.unpack(">I", rec[8:12])[0]
                break
        if not name_off or name_off + 6 > len(data):
            return ("", "")
        count, str_off = struct.unpack(">HH", data[name_off + 2:name_off + 6])
        str_base = name_off + str_off
        found: dict = {}
        rank: dict = {}
        for i in range(min(count, 256)):
            rec = data[name_off + 6 + i * 12: name_off + 6 + (i + 1) * 12]
            if len(rec) < 12:
                break
            pid, eid, lid, nid, length, offset = struct.unpack(">HHHHHH", rec)
            if nid not in (1, 2) or not length:
                continue
            raw = data[str_base + offset: str_base + offset + length]
            try:
                text = raw.decode("mac-roman" if pid == 1 else "utf-16-be", errors="ignore")
            except Exception:
                continue
            text = " ".join(text.split())
            if not text:
                continue
            # 优先级：Windows/Unicode 英文 > 其它 Unicode > Mac；同优先级取先出现的
            prio = 0 if (pid == 3 and lid == 0x409) else (1 if pid in (0, 3) else 2)
            if nid not in found or prio < rank[nid]:
                found[nid] = text
                rank[nid] = prio
        return (found.get(1, ""), found.get(2, ""))
    except Exception:
        return ("", "")


def _style_to_weight_italic(subfamily: str) -> tuple:
    """子样式串 → (weight:int|None, italic:bool|None)。

    只解析**明确**的字重 / 斜体词；组合式（"Bold Italic"）二者都给；
    未知串（如 "Caption" / "Display"）一律不猜，返回 (None, None) 让调用方回落 OS/2。
    """
    if not subfamily:
        return (None, None)
    s = subfamily.lower()
    italic = ("italic" in s) or ("oblique" in s)
    base = s.replace("italic", " ").replace("oblique", " ")
    table = {
        "thin": 100, "hairline": 100,
        "extralight": 200, "ultralight": 200,
        "light": 300,
        "regular": 400, "normal": 400, "book": 400, "roman": 400,
        "medium": 500,
        "semibold": 600, "demibold": 600,
        "bold": 700,
        "extrabold": 800, "ultrabold": 800,
        "black": 900, "heavy": 900,
    }
    weight = None
    for tok in "".join(c if c.isalnum() else " " for c in base).split():
        if tok in table:
            weight = table[tok]
            break
    return (weight, italic)


def _metrics(data: bytes) -> tuple:
    """从 OS/2 表读 usWeightClass，从 head 表读 macStyle（bit1 = 斜体）。读不到返回 (None, False)。"""
    try:
        if len(data) < 12 or data[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
            return (None, False)
        num = struct.unpack(">H", data[4:6])[0]
        table_off: dict = {}
        for i in range(min(num, 64)):
            off = 12 + i * 16
            if off + 16 > len(data):
                break
            rec = data[off:off + 16]
            table_off[rec[:4]] = struct.unpack(">I", rec[8:12])[0]
        weight = None
        italic = False
        if b"OS/2" in table_off:
            o = table_off[b"OS/2"]
            if o + 4 <= len(data):
                w = struct.unpack(">H", data[o + 2:o + 4])[0]  # version(2) 之后即 usWeightClass
                if 1 <= w <= 1000:
                    weight = w
        if b"head" in table_off:
            o = table_off[b"head"]
            if o + 46 <= len(data):
                mac = struct.unpack(">H", data[o + 44:o + 46])[0]
                italic = bool(mac & 0x2)
        return (weight, italic)
    except Exception:
        return (None, False)


def _font_meta(data: bytes) -> tuple:
    """解析一个字体文件，返回 (family, style, weight, italic, family_key)。

    family_key 是族名归一（小写去空白），用于把同一族的多个变体**归为一组**，
    让 @font-face 共享同一个 font-family 名、按 font-weight / font-style 区分 ——
    这样阅读器里「选加粗」能命中真实的 Bold 文件，而不是浏览器合成的伪粗体。

    字重 / 斜体的来源优先级：子样式串（人写标签）> OS/2 / head 表（机器可读）。
    族名解析不出（如 WOFF / WOFF2，或 name 表缺失）则 family_key = "" —— 不强行归组，
    退回「每个文件一条」的现状。
    """
    family, style = _ttf_names(data)
    sub_weight, sub_italic = _style_to_weight_italic(style)
    weight, italic = sub_weight, sub_italic
    if data[:4] in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        os2_w, head_italic = _metrics(data)
        if weight is None and os2_w is not None:
            weight = os2_w
        # 子样式没能给出斜体信息时，回落 head 表（有些字体只在 head 标 italic）
        if style:
            if sub_italic is False and head_italic:
                italic = True
        else:
            italic = head_italic
    family_key = "".join(family.lower().split())
    return family, style, weight, italic, family_key


def list_fonts() -> dict:
    """字体列表。id = 文件名（前端用它拼 /api/fonts/{id}/file）。"""
    items = []
    for p in sorted(fonts_dir().iterdir()):
        if not p.is_file() or p.suffix.lower() not in FONT_EXTS:
            continue
        try:
            st = p.stat()
            data = p.read_bytes() if p.suffix.lower() in (".ttf", ".otf") else b""
        except OSError:
            continue
        family, style, weight, italic, family_key = _font_meta(data)
        items.append({
            "id": p.name,
            "name": family or p.stem,
            # 族名没解析出来时，别硬编一个「Regular」假装知道
            "style": style or ("" if family else "字体名未解析，显示文件名"),
            "size": st.st_size,
            "format": p.suffix.lower().lstrip("."),
            "mtime": st.st_mtime,
            "weight": weight,
            "italic": italic,
            "family_key": family_key,
        })
    return {"items": items, "max_bytes": MAX_FONT_BYTES, "max_count": MAX_FONTS}


def save_font(filename: str, data: bytes) -> dict:
    """保存上传的字体。抛 ValueError（由 server 转 400/413）。"""
    name = _safe_name(filename)
    ext = pathlib.PurePath(name).suffix.lower()
    if ext not in FONT_EXTS:
        raise ValueError("仅支持 TTF / OTF / WOFF / WOFF2")
    if not data:
        raise ValueError("字体文件为空")
    if len(data) > MAX_FONT_BYTES:
        raise ValueError("字体超过大小上限（%d MB）" % (MAX_FONT_BYTES // 1024 // 1024))
    d = fonts_dir()
    existing = [p for p in d.iterdir() if p.is_file() and p.suffix.lower() in FONT_EXTS]
    if len(existing) >= MAX_FONTS:
        raise ValueError("字体数量已达上限（%d）" % MAX_FONTS)
    target = d / name
    # 重名加序号，不覆盖已有字体（用户可能上传同名不同版本）
    i = 1
    stem, suffix = pathlib.PurePath(name).stem, pathlib.PurePath(name).suffix
    while target.exists():
        target = d / f"{stem}-{i}{suffix}"
        i += 1
    target.write_bytes(data)
    family, style, weight, italic, family_key = (
        _font_meta(data) if ext in (".ttf", ".otf") else ("", "", None, None, "")
    )
    return {
        "id": target.name,
        "name": family or target.stem,
        "style": style or ("" if family else "字体名未解析，显示文件名"),
        "size": len(data),
        "format": ext.lstrip("."),
        "mtime": time.time(),
        "weight": weight,
        "italic": italic,
        "family_key": family_key,
    }


def font_path(fid: str):
    """取字体文件路径；不在字体目录 / 扩展名非法 / 不存在 → None。"""
    name = _safe_name(fid)
    if name != (fid or "").strip() or pathlib.PurePath(name).suffix.lower() not in FONT_EXTS:
        return None
    p = fonts_dir() / name
    if not p.is_file():
        return None
    return p


def delete_font(fid: str) -> bool:
    p = font_path(fid)
    if not p:
        return False
    try:
        p.unlink()
        return True
    except OSError:
        return False
