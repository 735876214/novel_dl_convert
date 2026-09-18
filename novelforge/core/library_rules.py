"""入库归库规则（第 10 期 D8）：一个新文件该落进哪个库。

优先级从「显式」到「推测」，越靠前越不该被后面的规则推翻：

1. **来源子文件夹名** —— 文件放在 ``LIBRARY_SOURCE_DIR/<子目录>/``（或监听目录的子目录）
   里，且子目录名等于某库的 ``source_subdir`` 或库名 → 直接用那个库。
   这是用户最明确的意图表达，不猜。
2. **格式** —— 扩展名 → 库类型（电子书 / 漫画 / 有声书）→ **类型匹配**的库。
   确定性最高（.cbz 就是漫画，没有歧义）；优先类型专用库，其次 ``mixed``。
3. **元数据关键词** —— 库 ``rules`` 里配的关键词命中书名 / 作者 / 系列 / 文件名 → 用该库。
   最容易误判，所以排在最后，且只在前面都没结论时才生效。
4. 都不中 → ``None``，由调用方回退**默认库**（``OUTPUT_DIR``）—— 与改造前行为一致。

``rules`` 字段两种写法都认：JSON（``{"keywords": [...], "subdirs": [...]}``）或
纯文本（逗号 / 顿号分隔的关键词），因为它是给人填的。
"""
import json
import pathlib

from .. import config
from . import library

#: 格式 → 库类型（与 library._exts_for_type 的划分保持一致）
_COMIC_EXT = (".cbz", ".cbr")
_EBOOK_EXT = (".epub", ".mobi", ".azw3", ".pdf", ".txt", ".fb2")


def _norm(text) -> str:
    return library.norm_key(str(text or ""))


def _type_of_name(name: str) -> str:
    ext = pathlib.PurePosixPath(str(name or "")).suffix.lower()
    if ext in _COMIC_EXT:
        return "comic"
    if ext in _EBOOK_EXT:
        return "ebook"
    from . import audio as _audio          # 延迟：避免与 audio 的导入顺序耦合
    if ext in _audio.AUDIO_EXTS:
        return "audiobook"
    return ""


def rules_of(lib: dict) -> dict:
    """解析库的 ``rules`` 字段 → ``{"keywords": [...], "subdirs": [...]}``。

    容错到底：坏 JSON / 奇怪类型都退化成「没有规则」，绝不让一条配置错误
    把入库主流程打崩（这是旁路增强，不是主流程）。
    """
    raw = str((lib or {}).get("rules") or "").strip()
    out = {"keywords": [], "subdirs": []}
    if not raw:
        return out
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                for k in ("keywords", "subdirs"):
                    vals = data.get(k)
                    if isinstance(vals, str):
                        vals = [vals]
                    if isinstance(vals, list):
                        out[k] = [str(v).strip() for v in vals if str(v).strip()]
                return out
        except Exception:
            return out
    # 纯文本：逗号 / 顿号 / 分号分隔，一律当关键词
    parts = [p.strip() for p in raw.replace("、", ",").replace(";", ",").split(",")]
    out["keywords"] = [p for p in parts if p]
    return out


def _subdir_of(src, base) -> str:
    """``src`` 相对 ``base`` 的**第一层子目录名**；不在 base 之下或就在根下 → ""。"""
    if not src or not base:
        return ""
    try:
        rel = pathlib.Path(str(src)).resolve().relative_to(pathlib.Path(str(base)).resolve())
    except Exception:
        return ""
    return rel.parts[0] if len(rel.parts) > 1 else ""


def _by_subdir(sub: str) -> "dict | None":
    """按来源子目录名匹配库：先比 ``source_subdir``，再宽容地比库名。"""
    if not sub:
        return None
    key = _norm(sub)
    libs = library.libraries()
    for l in libs:
        if _norm(l.get("source_subdir")) == key:
            return l
    for l in libs:
        if _norm(l.get("name")) == key:
            return l
    return None


def _by_format(name: str) -> "dict | None":
    """按格式匹配：优先**类型专用**库，其次 ``mixed``（含默认库）。"""
    t = _type_of_name(name)
    if not t:
        return None
    libs = library.libraries()
    exact = [l for l in libs if str(l.get("type") or "") == t]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return exact[0]            # 同类多个：按 sort_order 取第一个（预览页会提示指定）
    mixed = [l for l in libs if str(l.get("type") or "") in ("mixed", "")]
    return mixed[0] if mixed else None


def _haystack(src, name: str, meta: dict = None) -> str:
    """关键词匹配用的「全部可读文本」：文件名 + 元数据里人能认得的字段。"""
    m = meta or {}
    bits = [name or "", pathlib.PurePosixPath(str(name or "")).stem]
    bits.append(str(src or ""))
    for k in ("title", "author", "series", "publisher", "description"):
        bits.append(str(m.get(k) or ""))
    for t in (m.get("tags") or []):
        bits.append(str(t))
    return _norm(" ".join(bits))


def _by_keywords(text: str) -> "dict | None":
    if not text:
        return None
    for l in library.libraries():
        for kw in rules_of(l)["keywords"]:
            if _norm(kw) in text:
                return l
    return None


def decide(src=None, name: str = "", meta: dict = None, base_dir=None) -> "dict | None":
    """判定落库；返回库实体（dict）或 ``None``（表示「用默认库」）。"""
    filename = name or pathlib.PurePosixPath(str(src or "")).name
    if not filename:
        return None

    # 1) 来源子文件夹名（显式意图）
    for base in (base_dir, config.LIBRARY_SOURCE_DIR):
        hit = _by_subdir(_subdir_of(src, base))
        if hit:
            return hit

    # 2) 格式（确定性最高）
    hit = _by_format(filename)
    if hit and hit.get("type") in ("ebook", "comic", "audiobook"):
        return hit

    # 3) 元数据 / 文件名关键词（最容易误判，最后才用）
    hit = _by_keywords(_haystack(src, filename, meta))
    if hit:
        return hit

    # 4) 都不可靠 → 让调用方回退默认库（宁可落到默认库，也不要乱归）
    return None


def decide_for_path(src, base_dir=None) -> "dict | None":
    """``watcher.target_root`` 的入口（保持既有两参调用）。"""
    return decide(src=src, base_dir=base_dir)


def target_root(src=None, name: str = "", meta: dict = None, base_dir=None,
                default=None) -> pathlib.Path:
    """落库根目录：命中规则用命中的库，否则回退 ``default``（再退默认库根）。

    这是**摄入侧**取目标目录的唯一入口（上传 / 下载 / 监听三条链路共用），
    与读取侧 ``library.root_of()`` 对称。
    """
    lib = decide(src=src, name=name, meta=meta, base_dir=base_dir)
    if lib:
        return pathlib.Path(lib.get("root_path") or default or config.OUTPUT_DIR)
    if default is not None:
        return pathlib.Path(default)
    return library.root_of(library.DEFAULT_LIBRARY_ID)
