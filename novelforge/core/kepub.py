"""KEPUB 导出（第 237 期）—— 给 Kobo 用的 EPUB 副本。

## 是什么

KEPUB = Kobo 用的 EPUB 变体。与普通 EPUB 的差别**只有三处**（Kobo 的阅读器
需要，其余阅读器照读不误）：

1. `META-INF/encryption.xml`：**不加密**（普通 EPUB 也可以不加密，但 Kobo 的
   部分固件会强制要求这个文件存在且声明「无 DRM」）。
2. `META-INF/com.apple.ibooks.display-options.xml`：声明「**不**做 iBooks 的
   字体替换 / 不隐藏目录」。
3. `<opf:meta property="dcterms:modified">` 与 `dcterms:date`：Kobo 按**修改
   时间**决定「这本是不是我刚加的」，缺了它新书会排在列表末尾。

## 与 Kobo 设备同步的关系（**如实说明，不夸大**）

Kobo 的**完整设备同步**（配对 token、KEPUB 投递到设备、阅读历史回传、双向进度）
是 XL 级工作量 —— 那是复刻 Kobo 私有协议。**本期不做**。

本期做的是**最小闭环**：把书导出成 KEPUB 副本，交给用户自己经 Calibre-Web
或 Kobo 桌面端投递。这是上游文档里对 Kobo 那条明确推荐的「最小可行」路径。

## 红线

- **不碰源文件**：产出是**副本**（写到 `CACHE_DIR` 或用户指定的目录），
  源书一个字节不改。
- **不落书文件旁**：默认写到缓存目录；用户要指定位置就指定，绝不覆盖源书。
"""
from __future__ import annotations

import pathlib
import zipfile

from . import zipkind

#: Kobo 要求的「无 DRM」声明（`encryption.xml`）。
#:
#: ⚠️ 内容**不能为空** —— 空的 `encryption.xml` 会被部分固件判为「加密但没给 key」。
ENCRYPTION_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<encryption xmlns="urn:oasis:names:tc:opendocument:xmlns:container"'
    ' xmlns:enc="http://www.w3.org/2001/04/xmlenc#">\n'
    '  <enc:EncryptedData>\n'
    '    <enc:EncryptionMethod Algorithm="http://www.idpf.org/2008/embedding"/>\n'
    '    <enc:CipherData>\n'
    '      <enc:CipherValue/>\n'
    '    </enc:CipherData>\n'
    '  </enc:EncryptedData>\n'
    '</encryption>\n'
)

#: Kobo 要求的 iBooks 显示选项（声明**不**做字体替换 / **不**隐藏目录）。
DISPLAY_OPTIONS_XML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<display_options>\n'
    '  <platform name="*">\n'
    '    <option name="font_merging">false</option>\n'
    '    <option name="hide_toc">false</option>\n'
    '  </platform>\n'
    '</display_options>\n'
)


def _rewrite_opf(opf_xml: str) -> str:
    """给 OPF 补 Kobo 需要的 `dcterms:modified` / `dcterms:date`。

    ⚠️ 已在 `<metadata>` 里有就不重复加（重复的 meta 标签会让部分校验器报错）。
    """
    import re
    from datetime import datetime, timezone

    text = opf_xml
    if "dcterms:modified" not in text:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        meta = (f'<meta property="dcterms:modified">{now}</meta>'
                f'<meta property="dcterms:date">{now}</meta>')
        # 插到 `<metadata …>` 开标签之后
        m = re.search(r"(<metadata[^>]*>)", text)
        if m:
            text = text[:m.end()] + meta + text[m.end():]
    return text


def export_kepub(src: pathlib.Path, dest: pathlib.Path) -> pathlib.Path:
    """把一本 EPUB 转成 KEPUB 副本。

    ⚠️ **源文件只读**：全程只 `read`，产出写到 `dest`。
    ⚠️ `dest` 与 `src` 同一个文件 ⇒ 拒绝（那会把源书改坏）。
    """
    src = pathlib.Path(src)
    dest = pathlib.Path(dest)
    if not src.is_file():
        raise FileNotFoundError(f"找不到源文件：{src}")
    try:
        if src.resolve() == dest.resolve():
            raise ValueError("目标不能与源书同一个文件")
    except OSError:
        pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    # ⚠️ 先写临时文件再 `replace` —— 中途失败不留半个文件（与全仓「副本禁原地写」同纪律）
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    try:
        with zipfile.ZipFile(src) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename in ("META-INF/encryption.xml",
                                    "META-INF/com.apple.ibooks.display-options.xml"):
                    continue                      # 原有的那些**不**照抄，我们自己写
                # 第 292 期：走统一入口（带解压后上限）；裸 `zin.read()` 是 zip 炸弹入口。
                data = zipkind.read_entry(zin, item.filename)
                if item.filename.endswith(".opf"):
                    data = _rewrite_opf(data.decode("utf-8", "ignore")).encode("utf-8")
                # ⚠️ `mimetype` 必须是**第一个**且**不压缩**（EPUB 规范）
                if item.filename == "mimetype":
                    zout.writestr(item, data, compress_type=zipfile.ZIP_STORED)
                else:
                    zout.writestr(item, data)
            zout.writestr("META-INF/encryption.xml", ENCRYPTION_XML)
            zout.writestr("META-INF/com.apple.ibooks.display-options.xml",
                          DISPLAY_OPTIONS_XML)
        tmp.replace(dest)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return dest


def export_book(bid: str, dest_dir: pathlib.Path = None) -> dict:
    """按 `book_id` 导出一本 KEPUB。

    返回 ``{"ok", "path", "bytes", "message"}``。
    ⚠️ **只支持 EPUB**：其它格式（PDF / CBZ / 有声书）Kobo 也读不了，
    如实说明而不是导出一个 Kobo 打不开的文件。
    """
    from .. import config
    from . import library

    book = library.by_id(str(bid))
    if not book:
        return {"ok": False, "message": "书不存在", "path": "", "bytes": 0}
    fmt = str(book.get("format") or "").upper()
    if fmt != "EPUB":
        return {"ok": False, "message": f"只支持 EPUB（这本是 {fmt or '未知格式'}）",
                "path": "", "bytes": 0}

    lib = library.get_library(str(book.get("library_id") or ""))
    src = None
    if lib:
        for root in library.roots_of(lib):
            cand = root / pathlib.PurePosixPath(str(book.get("name") or ""))
            if cand.is_file():
                src = cand
                break
    if src is None:
        return {"ok": False, "message": "找不到这本书的文件", "path": "", "bytes": 0}

    stem = pathlib.Path(str(book.get("name") or "book")).stem
    target_dir = pathlib.Path(dest_dir) if dest_dir else (
        pathlib.Path(config.CACHE_DIR) / "kepub")
    dest = target_dir / (stem + ".kepub.epub")
    try:
        out = export_kepub(src, dest)
    except Exception as e:                    # noqa: BLE001
        return {"ok": False, "message": f"导出失败：{e}", "path": "", "bytes": 0}
    return {"ok": True, "path": str(out), "bytes": out.stat().st_size, "message": ""}
