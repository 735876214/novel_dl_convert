"""read-along / 媒体叠加 EPUB（第 188 期）—— 解析与音频提取的唯一判据源。

只认 **EPUB3 media overlays（SMIL）**：OPF manifest 的 content item 带
``media-overlay="<smil-id>"``，SMIL 里每个 ``<par>`` 用
``<text src="chapter.xhtml#frag"/>`` + ``<audio src="…" clipBegin="…" clipEnd="…"/>``
把一句话与一段音频对齐。

边界（如实说明，不假装支持）：
- 没有 SMIL / SMIL 里没有可用句子 / 音频资源缺失 ⇒ ``status=unsupported``；
- 部分章节没有叠加 / 部分音频缺失 ⇒ ``status=partial``（能读的句子照常能读）；
- 音频只从书文件**按需提取到缓存目录**，源文件一个字节都不改；
- 非标准的时间码（解析不出起止）逐句丢弃，不猜。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import posixpath
import time
import zipfile
import xml.etree.ElementTree as ET
from urllib.parse import unquote

from .. import config
from . import library, xmlsafe

MAX_XML_BYTES = 4 * 1024 * 1024
CONTAINER = "META-INF/container.xml"


def _local(tag) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _children(el, name: str) -> list:
    return [c for c in list(el) if _local(c.tag) == name]


def _first(el, name: str):
    for c in list(el):
        if _local(c.tag) == name:
            return c
    return None


def _attr(el, name: str) -> str:
    for k, v in (el.attrib or {}).items():
        if _local(k) == name:
            return str(v or "").strip()
    return ""


def join_entry(base_file: str, href: str) -> "str | None":
    """把 href 解析成 zip 内相对路径（相对 ``base_file`` 所在目录）。

    拒绝绝对路径与逃出根目录的 ``..`` —— 书是外部文件，不能让它把请求带到
    zip 之外（虽然这里只读 zip，但越界路径只会变成「资源不存在」的噪音）。
    """
    raw = unquote(str(href or "")).split("#", 1)[0].split("?", 1)[0].strip()
    if not raw or raw.startswith("/"):
        return None
    base_dir = posixpath.dirname(str(base_file or ""))
    p = posixpath.normpath(posixpath.join(base_dir, raw))
    if p in ("", ".", "..") or p.startswith("../"):
        return None
    return p


def _seconds(raw) -> "float | None":
    """SMIL 时间码：``1.5s`` / ``1500ms`` / ``0:00:01.500`` / ``00:01:02``。"""
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("ms"):
            return float(s[:-2]) / 1000.0
        if s.endswith("s"):
            return float(s[:-1])
        if ":" in s:
            parts = s.split(":")
            if len(parts) != 3:
                return None
            h, m, sec = parts
            return float(h) * 3600 + float(m) * 60 + float(sec)
        return float(s)
    except ValueError:
        return None


def _read(z: zipfile.ZipFile, name: str) -> bytes:
    """读一个 XML 条目（**带真实上限**）。

    ⚠️ 第 242 期：此前查的是 `info.file_size` —— 那是**压缩包自己声称的**大小，
    精心构造的归档可以声称 12 KB、实际解出 4 GB（见 `comics.read_capped` 的注释）
    ⇒ 那是**假安全**。改走 `zipkind.read_entry`（**按实际读到的字节数掐**），
    `limit` 仍传本模块自己的阈值，不放宽。
    """
    from . import zipkind

    return zipkind.read_entry(z, name, MAX_XML_BYTES)


def _unsupported(path: pathlib.Path, reason: str) -> dict:
    return {"status": "unsupported", "reason": reason, "cues": [],
            "epub_path": str(path), "mtime": _mtime(path), "size": _size(path)}


def _mtime(path: pathlib.Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


def _size(path: pathlib.Path) -> int:
    try:
        return int(path.stat().st_size)
    except OSError:
        return 0


def _parse_smil(data: bytes, smil_path: str, names: set) -> "tuple[list, int]":
    """→ (可用 cues, 被丢弃的 par 数)。"""
    try:
        root = xmlsafe.fromstring(data)
    except ET.ParseError:
        return [], 0
    out: list = []
    dropped = 0
    for par in root.iter():
        if _local(par.tag) != "par":
            continue
        text_el = _first(par, "text")
        audio_el = _first(par, "audio")
        if text_el is None or audio_el is None:
            dropped += 1
            continue
        text_href = join_entry(smil_path, _attr(text_el, "src"))
        audio_href = join_entry(smil_path, _attr(audio_el, "src"))
        begin = _seconds(_attr(audio_el, "clipBegin") or _attr(audio_el, "clip-begin"))
        end = _seconds(_attr(audio_el, "clipEnd") or _attr(audio_el, "clip-end"))
        if not text_href or not audio_href or begin is None or end is None or end <= begin:
            dropped += 1
            continue
        if audio_href not in names:
            dropped += 1
            continue
        frag = ""
        src = unquote(_attr(text_el, "src"))
        if "#" in src:
            frag = src.split("#", 1)[1]
        out.append({
            "text_href": text_href,
            "fragment": frag,
            "audio_href": audio_href,
            "clip_begin": round(begin, 3),
            "clip_end": round(end, 3),
        })
    return out, dropped


def inspect(path) -> dict:
    """解析一本书的媒体叠加。纯读，不写任何文件。"""
    p = pathlib.Path(path)
    if p.suffix.lower() != ".epub":
        return _unsupported(p, "只有 EPUB 支持媒体叠加（read-along）")
    if not p.is_file():
        return _unsupported(p, "书文件不存在")
    try:
        z = zipfile.ZipFile(p)
    except (OSError, zipfile.BadZipFile):
        return _unsupported(p, "不是有效的 EPUB（zip）")

    with z:
        names = set(z.namelist())
        if CONTAINER not in names:
            return _unsupported(p, "EPUB 缺少 META-INF/container.xml")
        try:
            container = xmlsafe.fromstring(_read(z, CONTAINER))
        except (ET.ParseError, KeyError, ValueError):
            return _unsupported(p, "EPUB 的 container.xml 读不出来")
        rootfile = next((el for el in container.iter() if _local(el.tag) == "rootfile"), None)
        opf_path = _attr(rootfile, "full-path") if rootfile is not None else ""
        if not opf_path or opf_path not in names:
            return _unsupported(p, "EPUB 的包文件（OPF）不存在")
        try:
            opf = xmlsafe.fromstring(_read(z, opf_path))
        except (ET.ParseError, KeyError, ValueError):
            return _unsupported(p, "EPUB 的包文件（OPF）读不出来")

        manifest = next((el for el in opf.iter() if _local(el.tag) == "manifest"), None)
        spine = next((el for el in opf.iter() if _local(el.tag) == "spine"), None)
        items: dict = {}
        for el in (list(manifest) if manifest is not None else []):
            if _local(el.tag) != "item":
                continue
            iid = _attr(el, "id")
            if iid:
                items[iid] = el

        spine_ids = []
        for el in (list(spine) if spine is not None else []):
            if _local(el.tag) == "itemref":
                ref = _attr(el, "idref")
                if ref:
                    spine_ids.append(ref)
        content_paths = set()
        for iid in spine_ids:
            it = items.get(iid)
            href = join_entry(opf_path, _attr(it, "href")) if it is not None else None
            if href:
                content_paths.add(href)

        cues: list = []
        covered: set = set()
        dropped_total = 0
        overlay_count = 0
        for el in items.values():
            overlay_id = _attr(el, "media-overlay")
            if not overlay_id:
                continue
            smil_item = items.get(overlay_id)
            if smil_item is None:
                continue
            smil_path = join_entry(opf_path, _attr(smil_item, "href"))
            if not smil_path or smil_path not in names:
                continue
            try:
                data = _read(z, smil_path)
            except (KeyError, ValueError):
                continue
            got, dropped = _parse_smil(data, smil_path, names)
            overlay_count += 1
            dropped_total += dropped
            if got:
                cues.extend(got)
                covered.add(join_entry(opf_path, _attr(el, "href")) or "")

    if not cues:
        return _unsupported(p, "这本书没有可用的媒体叠加（SMIL）")
    # 句子属于第几章 = spine 下标（阅读进度 / 批注同一坐标）。章节顺序只问 library 一处。
    spine_pos = {href: i for i, href in enumerate(library._spine(p))}
    for i, cue in enumerate(cues):
        cue["ordinal"] = i
        cue["chapter_index"] = spine_pos.get(cue["text_href"], -1)
    partial = bool(content_paths - covered) or dropped_total > 0 or overlay_count == 0
    if partial:
        reason = "部分章节没有媒体叠加" if content_paths - covered else "部分音频资源缺失"
        if dropped_total and not (content_paths - covered):
            reason = "部分句子缺少音频或时间码"
        return {"status": "partial", "reason": reason, "cues": cues,
                "epub_path": str(p), "mtime": _mtime(p), "size": _size(p)}
    return {"status": "ready", "reason": "", "cues": cues,
            "epub_path": str(p), "mtime": _mtime(p), "size": _size(p)}


def cache_audio(bid: str, epub_path, audio_href: str) -> "pathlib.Path | None":
    """把某一轨音频从 EPUB 提取到缓存目录（临时文件 + `os.replace`），返回路径。

    只允许 ``audio_href`` 是书内真实存在的条目；目标名用哈希，避免路径穿越。
    """
    p = pathlib.Path(epub_path)
    href = str(audio_href or "").strip()
    if not href or p.suffix.lower() != ".epub":
        return None
    target_dir = config.CACHE_DIR / "read-aloud" / str(bid)
    suffix = pathlib.PurePosixPath(href).suffix.lower()
    suffix = suffix if re_safe_suffix(suffix) else ".bin"
    target = target_dir / (hashlib.sha1(href.encode("utf-8")).hexdigest() + suffix)
    if target.is_file() and target.stat().st_size > 0:
        return target
    try:
        with zipfile.ZipFile(p) as z:
            if href not in z.namelist():
                return None
            target_dir.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + f".{int(time.time() * 1000)}.tmp")
            with z.open(href) as src, open(tmp, "wb") as dst:
                while True:
                    chunk = src.read(65536)
                    if not chunk:
                        break
                    dst.write(chunk)
            os.replace(tmp, target)
    except (OSError, zipfile.BadZipFile, KeyError):
        return None
    return target if target.is_file() and target.stat().st_size > 0 else None


def re_safe_suffix(suffix: str) -> bool:
    return bool(suffix) and len(suffix) <= 8 and all(c.isalnum() or c == "." for c in suffix)
