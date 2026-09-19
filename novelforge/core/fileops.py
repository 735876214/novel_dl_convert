"""成品文件操作：批量重命名与回收目录。

对应工具页里的三个「会改磁盘」的工具（实体管理 / 批量重命名 / 重复书籍）。

安全约定（三条硬约束，改这个模块前先读）：

1. **路径不越界**：所有文件名入参都过 :func:`safe_path` —— 不允许路径分隔符、
   ``..``、绝对路径、非法字符；解析后的父目录必须**恰好**是 ``OUTPUT_DIR``。
2. **一律「先预览、再应用」**：``plan_*`` 只算不改；``apply_rename`` 只接受前端
   回传的 ``{old, new}`` 条目并**再校验一遍**，不接受自由规则 ——
   避免同一套规则在前后端解释不一致时改错文件。
3. **删除即回收**：清理动作走 :func:`recycle_items`，把文件 move 进
   ``CACHE_DIR/recycle``（带时间戳前缀，重名自动加序号），**从不 unlink**。

第 18 期补充（第 4 条，与上面三条同等重要）：
4. **本模块只动「文件名」，不动「文件内容」**。改名 / 合并 / 重排册号需要的元数据
   一律写服务端（``db.set_override``），**不再回写 EPUB 的 OPF**（用户口径：
   元数据只存服务端，原书文件逐字节不变）。本模块里残留的 ``patch_epub_meta`` /
   ``rewrite_epub`` 等写文件的函数已**退出生产路径**（仅测试造夹具与副本出版用）。
"""
from __future__ import annotations

import pathlib
import re
import shutil
import time
import zipfile
from xml.sax.saxutils import escape

from .. import config
from . import activity_log, db, komga, library, metadata

RECYCLE_DIRNAME = "recycle"

# 跨平台都不安全的文件名字符（含控制字符）
_BAD_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
# 其它非法字符（路径分隔符、Windows 保留结尾的点和空格）
_BAD_TAIL = re.compile(r"[. ]+$")

#: 批量重命名规则里可用的占位符，前端据此给出提示。
#: 第 20 期扩到 9 个 —— **只加书目里真实存在的字段**（`library.books()` 的
#: year / publisher / language / series_index）；加不出真实值的一律不加。
PATTERN_FIELDS = ("{title}", "{author}", "{series}", "{series_index}", "{index}",
                  "{year}", "{publisher}", "{language}", "{ext}")


def output_dir(library_id=None) -> pathlib.Path:
    """**库根目录**（多书库）。

    不给 ``library_id`` 时返回默认库根（= 既有 ``OUTPUT_DIR``，兼容单库调用方）。
    ⚠️ 不要再用 ``config.OUTPUT_DIR`` 直接拼路径：多库下它只是**默认库**的根，
    对其它库的书会解析到错位置 —— 改名 / 回收 / 改元数据都会动到错文件。
    """
    if library_id:
        lib = library.get_library(library_id)
        if lib:
            return pathlib.Path(lib.get("root_path") or config.OUTPUT_DIR)
    return config.OUTPUT_DIR


def recycle_dir() -> pathlib.Path:
    d = config.CACHE_DIR / RECYCLE_DIRNAME
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------- 校验 ----------------

def safe_path(name: str, library_id=None) -> pathlib.Path:
    """把「文件名」或「系列/文件名」解析成**该书所属库根**下的真实路径，可疑输入抛 ValueError。

    **允许一层子目录**（Komga 布局的 ``系列名/书`` 结构，见 core/komga.py）。
    更深的层级一律拒绝：Komga 自己也不递归系列目录的子目录，
    而层级越深越容易藏路径穿越（``a/../../etc``）。

    ⚠️ 多书库（第 10 期）：基根由 ``library_id`` 决定，**不能**固定用 ``OUTPUT_DIR``
    （否则库内相对路径会被判「不在导出目录内」而全挂；反之若固定放宽到书库根，
    又会允许跨库穿越 —— 改名 / 回收可能动到别的库的文件）。
    """
    raw = (name or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("文件名为空")
    rel = pathlib.PurePosixPath(raw)
    if rel.is_absolute() or any(part in ("", ".", "..") for part in rel.parts):
        raise ValueError(f"非法文件名：{name}")
    if len(rel.parts) > 2:
        raise ValueError(f"路径层级过深（最多 系列/文件）：{name}")
    for part in rel.parts:
        if _BAD_CHARS.search(part):
            raise ValueError(f"文件名含非法字符：{name}")
    base = output_dir(library_id).resolve()
    p = (base / raw).resolve()
    # resolve 之后再判一次：符号链接可能把路径指到库根之外
    if p != base and base not in p.parents:
        raise ValueError(f"路径不在导出目录内：{name}")
    if len(p.relative_to(base).parts) > 2:
        raise ValueError(f"路径层级过深（最多 系列/文件）：{name}")
    return p


def sanitize_stem(stem: str) -> str:
    """把用户输入的「新名（不含扩展名）」清洗成安全文件名。"""
    s = _BAD_CHARS.sub("", (stem or "").strip())
    s = _BAD_TAIL.sub("", s)
    return s.strip()


# ---------------- 预览 ----------------

def _mk_item(old: str, new: str) -> dict:
    return {"old": old, "new": new, "conflict": False, "reason": ""}


def _mark_conflicts(items: list) -> list:
    """标出冲突：新名与原名相同、两条目撞名、目标已存在、新名非法。

    ⚠️ 条目带 ``library_id`` 时必须按**该库根**解析（第 13 期）：库内相对路径在
    别的库可能是同名文件，用默认库根去判会误报「目标文件已存在」或漏报。
    """
    olds = {it["old"] for it in items}
    taken: dict = {}
    for it in items:
        new = it["new"]
        if new == it["old"] and not it.get("meta_only"):
            it["conflict"], it["reason"] = True, "新名与原名相同"
        if new in taken:
            it["conflict"] = True
            it["reason"] = f"与「{taken[new]}」的目标名重复"
        else:
            taken[new] = it["old"]
        try:
            tgt = safe_path(new, it.get("library_id"))
        except ValueError as e:
            it["conflict"], it["reason"] = True, str(e)
            continue
        if tgt.exists() and new not in olds:
            it["conflict"], it["reason"] = True, "目标文件已存在"
    return items


def plan_entity_rename(kind: str, frm: str, to: str, library_id=None) -> dict:
    """把某作者 / 系列名批量改成另一个名字。

    ``library_id`` 给定时只处理**该库**的书（工具页的「范围：当前库」）；
    缺省 = 全部书库（既有行为不变）。条目一律带上 ``library_id``，
    apply 阶段据此取正确的库根 —— 否则多库下同名书会改到**错库**的文件上。

    - 作者：文件名里出现就替换；没出现则按本项目命名约定重建为
      ``《书名》作者：新名.epub``。apply 阶段还会同步改写 EPUB 内部
      ``dc:creator``，使工具页（按 OPF 聚合）能识别新作者。
    - 系列：通常只存在于 EPUB 内部元数据（``calibre:series``）、文件名里没有，
      因此生成「同名条目」，apply 阶段只改写 OPF 的 ``calibre:series``，不动文件名。
    """
    frm, to = (frm or "").strip(), (to or "").strip()
    if not frm or not to:
        raise ValueError("原名称与新名称都不能为空")
    if not sanitize_stem(to):
        raise ValueError("新名称含非法字符")
    field = "author" if kind == "author" else "series"

    items = []
    for b in library.books(library_id):
        cur = (b.get(field) or "").strip()
        if cur != frm:
            continue
        lid = b.get("library_id")
        p = pathlib.Path(b["name"])
        stem, suffix = p.stem, p.suffix
        if frm in stem:
            new_stem = stem.replace(frm, to, 1)
        elif field == "author":
            # 作者名没写在文件名里：按本项目命名约定重建，结果可预期
            new_stem = f"《{b['title']}》作者：{to}"
        elif field == "series":
            # 系列名只存在于 EPUB 内部元数据（calibre:series），文件名通常不含；
            # 改名即改写 OPF 元数据、不动文件名：生成「同名条目」，apply 阶段只更新元数据
            items.append({**_mk_item(b["name"], b["name"]), "meta_only": True,
                          "library_id": lid})
            continue
        else:
            continue
        new_stem = sanitize_stem(new_stem)
        if not new_stem:
            continue
        items.append({**_mk_item(b["name"], f"{new_stem}{suffix}"), "library_id": lid})

    return {"type": kind, "from": frm, "to": to, "library_id": str(library_id or ""),
            "items": _mark_conflicts(items)}


def plan_merge(kind: str, source: str, target: str, library_id=None) -> dict:
    """合并实体 = 把 ``source`` 名下所有书改挂到 ``target``，即一次改名预览。"""
    return plan_entity_rename(kind, source, target, library_id)


def plan_pattern_rename(scope: str, pattern: str, library_id=None) -> dict:
    """按规则生成「旧名 → 新名」预览。

    规则里可用 ``PATTERN_FIELDS`` 里的 9 个占位符（书名 / 作者 / 系列 / 系列序号 /
    本次范围序号 / 出版年 / 出版社 / 语言 / 扩展名）。
    ``scope`` 传扩展名（如 ``epub``，不带点）可只处理该格式；留空或 ``all`` 表示全部。
    ``library_id`` 给定时只处理该库的书（缺省 = 全部书库）；``{index}`` 序号
    按**本次范围**重新计数 —— 只改一个库时从 01 开始，符合「当前库」的预期；
    ``{series_index}`` 则是书目里的**系列序号原值**（读不到就是空串），两者语义不同。

    ⚠️ 替换顺序：先长后短 —— ``{series_index}`` 必须排在 ``{series}`` / ``{index}``
    之前处理，否则会被短 token 抢先吃掉一半（``str.replace`` 只看字面量，不认词边界）。
    """
    pat = (pattern or "").strip()
    if not pat:
        raise ValueError("重命名规则不能为空")
    if _BAD_CHARS.search(pat):
        raise ValueError("规则里不能含 \\ / : * ? \" < > | 这些字符")

    want = (scope or "").strip().lstrip(".").lower()
    items = []
    idx = 0
    for b in library.books(library_id):
        suffix = pathlib.Path(b["name"]).suffix
        if want and want != "all" and suffix.lstrip(".").lower() != want:
            continue
        idx += 1
        stem = pathlib.Path(b["name"]).stem
        # ⚠️ 先长后短：{series_index} 必须在 {series} / {index} 之前替换
        filled = (
            pat.replace("{series_index}", str(b.get("series_index") or ""))
            .replace("{title}", b["title"] or stem)
            .replace("{author}", b["author"] or "未知")
            .replace("{series}", b["series"] or "无系列")
            .replace("{index}", f"{idx:02d}")
            .replace("{year}", str(b.get("year") or ""))
            .replace("{publisher}", b.get("publisher") or "")
            .replace("{language}", b.get("language") or "")
            .replace("{ext}", suffix.lstrip("."))
        )
        new_stem = sanitize_stem(filled)
        if not new_stem:
            continue
        items.append({**_mk_item(b["name"], f"{new_stem}{suffix}"),
                      "library_id": b.get("library_id")})

    return {
        "scope": want or "all",
        "pattern": pat,
        "library_id": str(library_id or ""),
        "fields": list(PATTERN_FIELDS),
        "items": _mark_conflicts(items),
    }


# ---------------- EPUB 元数据改写 ----------------

# 可改写的字段全集。接口层据此校验，避免写进意料之外的东西。
METADATA_FIELDS = (
    "title", "author", "series", "series_index",
    "date", "publisher", "language", "description", "tags", "isbn",
)

# 单值字段 → OPF 元素。集中成一张表，而不是每个字段各写一段正则。
_SINGLE_ELEMENTS = {
    "title": "dc:title",
    "author": "dc:creator",
    "publisher": "dc:publisher",
    "language": "dc:language",
    "description": "dc:description",
    "date": "dc:date",
}


def _set_text_element(opf: str, tag: str, value: str) -> str:
    """替换（或插入）一个简单文本元素，如 ``<dc:title>…</dc:title>``。"""
    val = escape(value)
    pat = re.compile(rf"<{tag}[^>]*>.*?</{tag}>", re.S | re.I)
    if pat.search(opf):
        return pat.sub(f"<{tag}>{val}</{tag}>", opf, count=1)
    return opf.replace("</metadata>", f"<{tag}>{val}</{tag}></metadata>", 1)


def _set_meta_name(opf: str, name: str, value: str) -> str:
    """改写 ``<meta name="…" content="…"/>``（calibre:series / series_index 这类）。"""
    val = escape(value)
    m = re.search(rf'<meta[^>]+name="{re.escape(name)}"[^>]*/?>', opf, re.I)
    if m:
        tag = m.group(0)
        if re.search(r'content="[^"]*"', tag):
            new = re.sub(r'content="[^"]*"', f'content="{val}"', tag, count=1)
        elif tag.endswith("/>"):
            new = tag[:-2].rstrip() + f' content="{val}"/>'
        else:
            new = tag[:-1].rstrip() + f' content="{val}">'
        return opf.replace(tag, new, 1)
    return opf.replace("</metadata>", f'<meta name="{name}" content="{val}"/></metadata>', 1)


def _set_tags(opf: str, values: list) -> str:
    """整体替换 ``dc:subject`` 列表。

    刻意**整体替换**而非逐个增删：题材是一组值，部分更新会留下重复项，
    而「去重后的完整列表」才是调用方真正想表达的语义。
    """
    opf = re.sub(r"<dc:subject[^>]*>.*?</dc:subject>\s*", "", opf, flags=re.S | re.I)
    if not values:
        return opf
    block = "".join(f"<dc:subject>{escape(v)}</dc:subject>" for v in values)
    return opf.replace("</metadata>", f"{block}</metadata>", 1)


def _set_isbn(opf: str, value: str) -> str:
    """改写 ISBN。

    只认「值看起来像 ISBN」的那个 ``dc:identifier``（判定与 ``library._isbn_of`` 一致）——
    不能无脑改第一个 identifier，那可能是 UUID / URI 之类的书标识符。
    """
    val = escape(value)
    for m in re.finditer(r"<dc:identifier[^>]*>(.*?)</dc:identifier>", opf, re.S | re.I):
        text = re.sub(r"<[^>]+>", "", m.group(1))
        if re.search(r"[\dxX-]{10,17}", text):
            return opf[: m.start()] + f'<dc:identifier id="isbn">{val}</dc:identifier>' + opf[m.end():]
    return opf.replace("</metadata>", f'<dc:identifier id="isbn">{val}</dc:identifier></metadata>', 1)


def patch_opf_meta(opf: str, updates: dict) -> str:
    """按字段批量改写 OPF 文本。

    **未知字段一律忽略**：旧实现里非 author 的字段会静默落到 series 分支，
    等于把值写错地方。这里保持沉默但由调用方按 METADATA_FIELDS 先校验。
    """
    out = opf
    for field, value in (updates or {}).items():
        if field in _SINGLE_ELEMENTS:
            out = _set_text_element(out, _SINGLE_ELEMENTS[field], str(value or ""))
        elif field == "series":
            out = _set_meta_name(out, "calibre:series", str(value or ""))
        elif field == "series_index":
            out = _set_meta_name(out, "calibre:series_index", str(value or ""))
        elif field == "isbn":
            out = _set_isbn(out, str(value or ""))
        elif field == "tags":
            vals = value if isinstance(value, (list, tuple)) else ([value] if value else [])
            cleaned = [str(v).strip() for v in vals if str(v).strip()]
            # 去重且保序：调用方传 ['甲','乙','甲'] 时，写进去的必须是 ['甲','乙']。
            # 不能用 set() —— 那会打乱顺序，而题材的展示顺序是有意义的。
            out = _set_tags(out, list(dict.fromkeys(cleaned)))
    return out


def _patch_opf(opf: str, field: str, value: str) -> str:
    """单字段改写（保留给实体改名路径）。未知字段返回原文。"""
    if field not in METADATA_FIELDS:
        return opf
    return patch_opf_meta(opf, {field: value})


def _read_epub(path) -> tuple:
    """读出 ``(opf 路径, opf 文本, 全部条目 blob)``；失败返回 ``("", "", None)``。

    抽出来是因为「只改 OPF」与「还要增删条目（写入封面图）」两条路径需要同一套读法，
    各写一份迟早走样。定位 OPF 走 ``META-INF/container.xml``，找不到再退回扫 ``.opf``。
    """
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            opf_path = ""
            try:
                container = z.read("META-INF/container.xml").decode("utf-8", "ignore")
                m = re.search(r'full-path="([^"]+)"', container)
                if m:
                    opf_path = m.group(1)
            except Exception:
                opf_path = ""
            if not opf_path:
                opfs = [n for n in z.namelist() if n.lower().endswith(".opf")]
                if not opfs:
                    return ("", "", None)
                opf_path = opfs[0]
            opf = z.read(opf_path).decode("utf-8", "ignore")
            blob = {info.filename: (info, z.read(info)) for info in infos}
        return (opf_path, opf, blob)
    except Exception:
        return ("", "", None)


def _write_epub(path, blob) -> bool:
    """把 blob 写成新的 zip 并**原子替换**（失败时清理临时文件）。"""
    tmp = path.with_name(path.name + ".tmp-epub")
    try:
        with zipfile.ZipFile(tmp, "w") as z:
            for info, content in blob.values():
                z.writestr(info, content)
        tmp.replace(path)
        return True
    except Exception:
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        return False


def _rewrite_zip_opf(path: pathlib.Path, transform) -> bool:
    """把 OPF 取出 → 交给 transform 改写 → 写回 zip（其余条目原样保留）。

    返回 True 表示**成功**（transform 没产生改动也算成功）；任何异常返回 False。
    注意这里**只能改 OPF 文本**；要增删 zip 条目（如写入封面图）请用 :func:`rewrite_epub`。
    """
    opf_path, opf, blob = _read_epub(path)
    if blob is None:
        return False
    new_opf = transform(opf)
    if new_opf == opf:
        return True
    blob[opf_path] = (blob[opf_path][0], new_opf.encode("utf-8"))
    return _write_epub(path, blob)


# ---------------- 封面写入（元数据抓取用）----------------
# EPUB 加封面要动三处：① zip 里放图片 ② OPF 的 manifest 声明 ③ EPUB2 的 <meta name="cover">。
# zip 不能原地加条目，所以必须走 rewrite_epub（整包重写 + 原子替换）。

#: 封面条目的 id（EPUB3 的 properties 与 EPUB2 的 meta name 共用同一个）
COVER_ID = "cover-image"
_COVER_EXTS = {
    "image/jpeg": ".jpg", "image/jpg": ".jpg", "image/png": ".png",
    "image/webp": ".webp", "image/gif": ".gif",
}


def cover_paths(media_type: str, opf_path: str) -> tuple:
    """算出 ``(zip 内路径, OPF 里的 href)``。

    这两个**不是同一个值**：manifest 的 href 是**相对 OPF 所在目录**的，
    而 zip 内路径要从根算起。OPF 常见放在 `OEBPS/` 或 `EPUB/` 下，写错这一处
    就是「阅读器找不到封面」，故单独抽出来并测。
    """
    ext = _COVER_EXTS.get((media_type or "").lower(), ".jpg")
    name = f"_nf-cover{ext}"
    parent = str(pathlib.PurePosixPath(opf_path).parent)
    full = f"{parent}/{name}" if parent not in ("", ".") else name
    return full, name


def set_epub_cover(opf: str, href: str, media_type: str) -> str:
    """在 OPF 里声明封面：**EPUB3 的 properties 与 EPUB2 的 meta 都写**。

    两种都写是为了兼容：老阅读器只认 ``<meta name="cover">``，
    新阅读器与校验器认 ``properties="cover-image"``。
    写入前先清掉旧的封面声明，避免同一本书里出现两个封面条目。
    """
    href = escape(href)
    opf = re.sub(r'<item[^>]*properties="[^"]*cover-image[^"]*"[^>]*/?>\s*', "", opf, flags=re.I)
    opf = re.sub(r'<meta[^>]*name="cover"[^>]*/?>\s*', "", opf, flags=re.I)
    item = (f'<item id="{COVER_ID}" href="{href}" media-type="{escape(media_type)}"'
            f' properties="cover-image"/>')
    if re.search(r"<manifest[^>]*>", opf, re.I):
        opf = re.sub(r"(<manifest[^>]*>)", lambda m: m.group(1) + item, opf, count=1, flags=re.I)
    elif "</metadata>" in opf:          # 畸形 OPF（无 manifest）：挂在 metadata 后，聊胜于无
        opf = opf.replace("</metadata>", f"</metadata>{item}", 1)
    if "</metadata>" in opf:
        opf = opf.replace("</metadata>", f'<meta name="cover" content="{COVER_ID}"/></metadata>', 1)
    return opf


def rewrite_epub(path, *, updates: dict = None, transform=None, add_files: dict = None) -> bool:
    """改写 EPUB：**改 OPF + 增删 zip 条目**（``_rewrite_zip_opf`` 做不到增删条目）。

    - ``updates``：走 :func:`patch_opf_meta`，与「编辑元数据」同一套字段语义
    - ``transform``：直接变换 OPF 文本（比 updates 更底层，如插入封面声明）；给了它就忽略 updates
    - ``add_files``：``{zip 内路径: bytes}``，同名条目**替换**
    - OPF 与条目都没变化时返回 True 且**不重写文件**（避免无谓地改 mtime）
    """
    opf_path, opf, blob = _read_epub(path)
    if blob is None:
        return False
    new_opf = transform(opf) if transform else patch_opf_meta(opf, updates or {})
    adds = {k: v for k, v in (add_files or {}).items() if v}
    if new_opf == opf and not adds:
        return True
    blob[opf_path] = (blob[opf_path][0], new_opf.encode("utf-8"))
    for name, data in adds.items():
        if name in blob:
            blob[name] = (blob[name][0], data)
        else:
            zi = zipfile.ZipInfo(name)
            zi.compress_type = zipfile.ZIP_DEFLATED
            blob[name] = (zi, data)
    return _write_epub(path, blob)


def patch_epub_meta(path: pathlib.Path, updates: dict) -> list:
    """批量改写 EPUB 元数据，返回**被接受的字段名**列表（已按白名单过滤）。

    ⚠️ 第 18 期起**生产代码不再调用它** —— 元数据一律只存服务端（``meta_override`` /
    ``meta_online``），连改名 / 重排册号也不再回写文件。保留它是给两处用：
    ① 测试造「带元数据的真 EPUB」（见 tests 里的 ``_epub_with_series`` 等）；
    ② 将来若做「导出写回」，这里是现成的写入口。
    产品路径要写文件，只有 `core/publish.py` 写**副本**那一条（走 rewrite_epub）。

    返回值是「提交了哪些字段」，不是「哪些真的变了」—— 把同一个值再写一遍也在列表里。
    """
    fields = {k: v for k, v in (updates or {}).items() if k in METADATA_FIELDS}
    if not fields:
        return []
    if not _rewrite_zip_opf(path, lambda opf: patch_opf_meta(opf, fields)):
        raise ValueError("EPUB 元数据写入失败")
    return sorted(fields.keys())


# ---------------- 应用 ----------------

def _owning_library_id(path) -> str:
    """文件所在库的 id：按**真实路径的包含关系**判断，不依赖扫描缓存。

    ⚠️ 不能改用 ``_lib_of(名字)`` 来算：它靠 ``library.find`` 反查书目，而改名
    **刚做完**时扫描缓存（TTL 5s）里根本还没有新名字 → 反查失败 → ``book_id``
    退化成旧的**纯哈希**形态，于是写下的覆盖永远不会被列表读到
    （列表用的是「库$哈希」）。这类 bug 不报错、只是「改了没生效」，必须防死。
    """
    try:
        target = pathlib.Path(path).resolve()
    except Exception:                                 # noqa: BLE001
        return str(library.DEFAULT_LIBRARY_ID)
    best, best_len = "", -1
    for lib in library.libraries():
        root = str(lib.get("root_path") or "").strip()
        if not root:
            continue
        try:
            r = pathlib.Path(root).resolve()
        except Exception:                             # noqa: BLE001
            continue
        # 取**最深**的匹配：库根嵌套时按更具体的那个归属
        if (target == r or r in target.parents) and len(str(r)) > best_len:
            best, best_len = str(lib.get("id") or ""), len(str(r))
    return best or str(library.DEFAULT_LIBRARY_ID)


def _meta_override_for(name: str, field: str, value: str) -> dict:
    """把「改名后的新名字」记成**服务端元数据覆盖**（第 18 期：元数据不写文件）。

    ⚠️ ``book_id`` 由 basename 派生 → **改名后 id 就变了**，覆盖必须落在**新 id** 上，
    否则列表读到的还是旧 id 的覆盖（那条记录已经没有任何书指向它），等于没改。
    """
    path = safe_path(name, _lib_of(name))
    bid = library.book_id(name, _owning_library_id(path))
    db.set_override(bid, field, value)
    return {"name": name, "book_id": bid, "field": field, "value": value}


def apply_rename(items: list, meta_field: str | None = None, meta_value: str | None = None) -> dict:
    """执行改名。只认 ``{old, new}``；冲突项与非法项一律跳过并记失败日志。

    第 18 期起：**只改文件名，绝不改写 EPUB 内部元数据**（用户口径：元数据只存服务端）。
    实体改名 / 合并需要的「新名字」改为写 :func:`db.set_override` ——
    列表 / 详情 / 实体聚合立刻按新名字走，而原文件保持逐字节原样。
    """
    if not isinstance(items, list) or not items:
        raise ValueError("没有可应用的条目")

    renamed, errors, overrides = [], [], []
    for it in items:
        it = it if isinstance(it, dict) else {}
        old = str(it.get("old") or "").strip()
        new = str(it.get("new") or "").strip()
        if it.get("conflict"):
            errors.append({"old": old, "error": "存在冲突，已跳过"})
            continue
        try:
            src, dst = safe_path(old, _lib_of(old)), safe_path(new, _lib_of(new))
            if not src.is_file():
                raise ValueError("源文件不存在")
            if old == new:
                # 只改元数据（系列 / 作者改名时文件名不变）：不移动文件、不碰文件字节
                if meta_field and meta_value:
                    overrides.append(_meta_override_for(old, meta_field, meta_value))
                renamed.append({"old": old, "new": new})
                activity_log.log(activity_log.ACTION_RENAME, old, activity_log.STATUS_OK,
                                output=new, source="api", detail="仅更新服务端元数据")
                continue
            if dst.exists():
                raise ValueError("目标文件已存在")
            src.rename(dst)
        except Exception as e:
            errors.append({"old": old, "error": str(e)})
            activity_log.log(activity_log.ACTION_RENAME, old, activity_log.STATUS_FAIL,
                             detail=str(e), source="api")
            continue
        renamed.append({"old": old, "new": new})
        activity_log.log(activity_log.ACTION_RENAME, old, activity_log.STATUS_OK,
                         output=new, source="api")
        # 实体改名 / 合并：新名字记成服务端覆盖，使工具页（按生效元数据聚合）识别新名称
        if meta_field and meta_value:
            try:
                overrides.append(_meta_override_for(new, meta_field, meta_value))
            except Exception as e:              # noqa: BLE001 —— 文件已改名，元数据失败不算全败
                errors.append({"old": old, "error": f"文件已改名，但服务端元数据更新失败：{e}"})

    library.invalidate()
    return {"renamed": renamed, "errors": errors, "count": len(renamed),
            "overrides": overrides}


def _lib_of(name: str, item: dict = None):
    """条目所属的库 id：优先取前端回传的 ``library_id``，否则按名字反查书目。

    多书库下 `safe_path` 必须知道基根；这样即使预览项没带库信息，
    后端也能自己反查出来（避免默认落到默认库上改错文件）。
    """
    if isinstance(item, dict) and item.get("library_id"):
        return item["library_id"]
    b = library.find(name)
    return (b or {}).get("library_id")


def _prune_empty_dirs(library_id=None) -> int:
    """删掉**库根**下**空**的一层子目录（布局整理把系列目录搬空后留下的壳）。

    只删一层、只删空目录：``rmdir`` 对非空目录会抛错，这里天然安全 ——
    不会出现「手滑删掉还有书的目录」。
    """
    n = 0
    try:
        for d in output_dir().iterdir():
            if d.is_dir() and not d.name.startswith("."):
                try:
                    d.rmdir()
                    n += 1
                except OSError:
                    pass
    except Exception:
        pass
    return n


def plan_komga_layout() -> dict:
    """预览「整理为 Komga 库布局」：哪些书会移进系列目录（**只算不改**）。

    系列来源：EPUB 里的 ``calibre:series``（扫描时已读进 ``book["series"]``）优先，
    否则**从文件名推断**（见 core/komga.py）。两者都判不出的书原地不动 ——
    为了「整齐」去凭空造一个系列名，比平铺更糟。
    """
    bs = library.books()
    items = []
    for b in bs:
        name = str(b.get("name") or "")
        if not name:
            continue
        p = pathlib.PurePosixPath(name)
        series, index = komga.infer(
            p.stem, b.get("series") or "", b.get("series_index") or ""
        )
        if not series:
            continue
        new = komga.relpath_for(p.stem, p.suffix.lstrip("."), series, index, "komga")
        if new == name:
            continue
        items.append({
            "old": name,
            "new": new,
            "title": b.get("title") or p.stem,
            "author": b.get("author") or "",
            "series": series,
            "index": index,
            # 会改 basename 的条目要搬关联数据（进度/批注/评分/收藏）
            "id_changes": library.book_id(name, b.get("library_id"))
            != library.book_id(new, b.get("library_id")),
            "conflict": False,
            "reason": "",
        })

    # 两条目撞同一目标 → 双向标冲突；目标已存在 → 单条标冲突。
    # 前端据此渲染红色行并禁止勾选，apply 时也会再拦一次。
    seen: dict = {}
    for it in items:
        if it["new"] in seen:
            it["conflict"] = True
            it["reason"] = "与另一条目目标相同"
            seen[it["new"]]["conflict"] = True
            seen[it["new"]]["reason"] = "与另一条目目标相同"
            continue
        seen[it["new"]] = it
    for it in items:
        if it["conflict"]:
            continue
        try:
            dst = safe_path(it["new"], _lib_of(it.get("old", ""), it))
        except ValueError as e:
            it["conflict"] = True
            it["reason"] = str(e)
            continue
        if dst.exists():
            it["conflict"] = True
            it["reason"] = "目标已存在"

    movable = [i for i in items if not i["conflict"]]
    return {
        "items": items,
        "total": len(bs),
        "movable": len(movable),
        "unchanged": len(bs) - len(items),          # 无系列或已在目标位置
        "series_count": len({i["series"] for i in movable}),
        "id_changing": len([i for i in movable if i["id_changes"]]),
    }


def apply_komga_layout(items: list) -> dict:
    """执行布局整理。只认 ``{old, new}``，逐条**再校验一遍**。

    加卷号会改变 basename → ``book_id`` 变 → 必须用 ``db.remap_book_id`` 把
    进度 / 批注 / 评分 / 收藏搬过去（见 db.REMAP_TABLES）。这一步不能省：
    少了它，用户「整理一次书库」就等于把所有阅读进度清零。
    只挪目录（id 不变）时跳过搬迁，避免白写一趟 UPDATE。
    """
    if not isinstance(items, list) or not items:
        raise ValueError("没有可应用的条目")

    moved, errors, remapped = [], [], 0
    for it in items:
        it = it if isinstance(it, dict) else {}
        old = str(it.get("old") or "").strip()
        new = str(it.get("new") or "").strip()
        if it.get("conflict"):
            errors.append({"old": old, "error": "存在冲突，已跳过"})
            continue
        try:
            src, dst = safe_path(old, _lib_of(old)), safe_path(new, _lib_of(new))
            if not src.is_file():
                raise ValueError("源文件不存在")
            if src == dst:
                continue
            if dst.exists():
                raise ValueError("目标文件已存在")
            dst.parent.mkdir(parents=True, exist_ok=True)
            lib_id = _lib_of(old, it)
            old_id, new_id = library.book_id(old, lib_id), library.book_id(new, lib_id)
            shutil.move(str(src), str(dst))
        except Exception as e:
            errors.append({"old": old, "error": str(e)})
            activity_log.log(activity_log.ACTION_LAYOUT, old, activity_log.STATUS_FAIL,
                             detail=str(e), source="api")
            continue
        if old_id != new_id:
            db.remap_book_id(old_id, new_id)
            remapped += 1
        moved.append({"old": old, "new": new})
        activity_log.log(activity_log.ACTION_LAYOUT, old, activity_log.STATUS_OK,
                         output=new, source="api")

    pruned = _prune_empty_dirs()
    library.invalidate()
    return {"moved": moved, "errors": errors, "count": len(moved),
            "remapped": remapped, "pruned_dirs": pruned}


def recycle_items(names: list, reason: str = "") -> dict:
    """把若干成品文件移入回收目录（**不是删除**），返回回收目录路径。

    条目可以是**文件名**，也可以是 ``{"name": ..., "library_id": ...}``。
    多书库下同名文件可以同时存在于多个库，只给名字时 ``_lib_of`` 只能反查到其中之一
    （``library.find`` 命中多个就取第一个）—— 清理时给错库就等于移错了书。
    所以工具页在「全部书库」范围下一律带上 ``library_id``。
    """
    if not isinstance(names, list) or not names:
        raise ValueError("没有要清理的条目")

    dest_dir = recycle_dir()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    moved, errors = [], []
    for raw in names:
        item = raw if isinstance(raw, dict) else {"name": raw}
        label = str(item.get("name") or "").strip()
        try:
            src = safe_path(label, _lib_of(label, item))
            if not src.is_file():
                raise ValueError("文件不存在")
            dst = dest_dir / f"{stamp}_{src.name}"
            n = 1
            while dst.exists():
                dst = dest_dir / f"{stamp}_{n}_{src.name}"
                n += 1
            shutil.move(str(src), str(dst))
        except Exception as e:
            errors.append({"name": label, "error": str(e)})
            activity_log.log(activity_log.ACTION_RECYCLE, label, activity_log.STATUS_FAIL,
                             detail=str(e), source="api")
            continue
        moved.append({"name": label, "moved_to": dst.name,
                      "library_id": item.get("library_id") or _lib_of(label, item)})
        activity_log.log(activity_log.ACTION_RECYCLE, label, activity_log.STATUS_OK,
                         output=dst.name, detail=reason or "移入回收目录", source="api")

    library.invalidate()
    return {"moved": moved, "errors": errors, "recycle_dir": str(dest_dir)}


def resolve_duplicates(keep: str, remove: list) -> dict:
    """重复书籍处理：``remove`` 里的文件移入回收目录，``keep`` 仅用于日志备注。"""
    keep = (keep or "").strip()
    result = recycle_items(remove, reason=f"保留重复项：{keep}" if keep else "重复书籍清理")
    result["keep"] = keep
    return result


# ---------------- 同名冲突修复（第 13 期）----------------
# ``book_id`` 由 basename 派生（core/library.py），于是「A 库有三体.epub、B 库也有
# 三体.epub」会撞上同一个 id：进度 / 批注 / 评分只有一份，``library.by_id`` 会直接抛
# ``BookIdConflict``。修法只能是给其中一本改名 —— 而改名就换了 id，所以**必须**
# 连关联数据一起搬，否则「一键修复冲突」= 把阅读记录清空（详见下面的 docstring）。

def apply_conflict_rename(items: list) -> dict:
    """执行同名冲突修复改名。只认 ``{old, new, library_id?}``，逐条**再校验一遍**。

    与 :func:`apply_rename` 唯一的、也是最关键的区别：这里**每条都要搬关联数据**。
    冲突修复必然改 basename（不改就消不掉冲突），而 ``book_id`` 由 basename 派生 ——
    不调 ``db.remap_book_id`` 就等于把进度 / 批注 / 评分 / 收藏全丢掉，而用户点这个
    按钮的意图恰恰是「让数据不再张冠李戴」。

    ``library_id`` 缺省时按名字反查（见 :func:`_lib_of`）：多库下必须知道基根，
    否则 ``safe_path`` 会落到错的库上。只 rename，**从不 unlink**。
    """
    if not isinstance(items, list) or not items:
        raise ValueError("没有可应用的条目")

    renamed, errors, remapped = [], [], 0
    for it in items:
        it = it if isinstance(it, dict) else {}
        old = str(it.get("old") or "").strip()
        new = str(it.get("new") or "").strip()
        lib_id = _lib_of(old, it)
        if it.get("conflict"):
            errors.append({"old": old, "error": "存在冲突，已跳过"})
            continue
        try:
            if not old or not new:
                raise ValueError("缺少原名或新名")
            src, dst = safe_path(old, lib_id), safe_path(new, lib_id)
            if not src.is_file():
                raise ValueError("源文件不存在")
            if src == dst:
                raise ValueError("新名与原名相同，消不掉冲突")
            if dst.exists():
                raise ValueError("目标文件已存在")
            old_id, new_id = library.book_id(old, lib_id), library.book_id(new, lib_id)
            if old_id == new_id:
                raise ValueError("新名与原名的 id 相同（只换了目录），消不掉冲突")
            # 改完还得**不撞 id**，否则等于白改一趟：库内 + 跨库各查一遍。
            # （库内同名同样会撞 id，见 library.id_conflicts 的注释）
            if any(str(b.get("id")) == new_id for b in library.books(lib_id)):
                raise ValueError("新名仍与本库其它书撞名")
            if library.id_conflict_with(new, lib_id) is not None:
                raise ValueError("新名仍与其它库的书撞名")
            src.rename(dst)
        except Exception as e:
            errors.append({"old": old, "error": str(e)})
            activity_log.log(activity_log.ACTION_RENAME, old, activity_log.STATUS_FAIL,
                             detail=str(e), source="api")
            continue
        db.remap_book_id(old_id, new_id)
        remapped += 1
        renamed.append({"old": old, "new": new, "library_id": lib_id})
        activity_log.log(activity_log.ACTION_RENAME, old, activity_log.STATUS_OK,
                         output=new, source="api", detail="同名冲突修复")

    library.invalidate()
    return {"renamed": renamed, "errors": errors, "count": len(renamed),
            "remapped": remapped}
