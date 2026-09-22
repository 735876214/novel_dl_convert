"""入库归库规则（第 10 期 D8）：一个新文件该落进哪个库。

优先级从「显式」到「推测」，越靠前越不该被后面的规则推翻：

0. **前置闸门：收了必须看得见**（第 40 期）—— 库的**生效扫描白名单**收不了的格式，
   三条规则都不算它（见 :func:`_accepts`）。这不是一条「优先级」，而是所有规则共同的
   **候选条件**：路由到一个扫不到它的库＝**隐形文件**（文件落盘了、书目里却没有），
   比直接拒收更糟 —— 用户看得见失败，看不见消失。

   ⚠️ 这条**也管第 1 条**（来源子目录）。第 40 期明确改过这个语义：以前把 ``.epub``
   放进一个 ``type=comic`` 的库的来源目录，系统会照办并让文件消失（`test_library_rules`
   曾把这个行为断言为「显式摆放意图高于格式推断」）。**显式意图能让系统「不猜」，
   但不能让系统「装作收下了」** —— 现在改为拒收，并用 :func:`no_library_reason`
   说清「是格式不匹配」而不是「规则不命中」。
1. **来源子目录名** —— 文件放在 ``LIBRARY_SOURCE_DIR/<子目录>/``（或监听目录的子目录、
   或某库来源文件夹的子目录）里，且子目录名等于某库的**库名** → 直接用那个库。
   （第 41 期起不再有 ``source_subdir`` 概念，只按库名匹配。）这是用户最明确的意图表达，不猜。
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


def _accepts(lib: dict, filename: str) -> bool:
    """这个库**收了也看得见**吗 —— 判据是该库的生效扫描白名单（第 40 期）。

    路由到一个扫不到它的库 = **隐形文件**：文件落盘了、书目里却找不到。这比
    **直接拒收更糟** —— 用户看得见失败（日志 + 失败计数），看不见消失。所以候选
    过滤里就把它排掉，让 :func:`decide` 返回 ``None`` 走既有拒收路径。

    ⚠️ 库的 ``allowed_exts`` 收窄之后才可能撞上，但**这不是本期引入的新问题**：
    白名单按**类型**推导时就已存在（``type=ebook`` 的库把来源文件夹
    指向漫画目录，投进去的 ``.cbz`` 当场隐形）。本条只是把这条路封死。

    容错：判不了就**放行** —— 这是旁路增强，不该把入库主流程打崩（判错了顶多
    退回改造前的行为，而不是把一个本来能入库的文件拒掉）。
    """
    try:
        return library.accepts_ext(lib, filename)
    except Exception:                       # noqa: BLE001
        return True


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


def _by_subdir(sub: str, filename: str = "") -> "dict | None":
    """按库名匹配库（第 41 期：来源子目录名概念已移除，来源文件夹是绝对路径、
    不再有相对子目录名；此处回落为直接比库名）。"""
    if not sub:
        return None
    key = _norm(sub)
    for l in library.libraries():
        if _norm(l.get("name")) == key and _accepts(l, filename):
            return l
    return None


def _by_format(name: str) -> "dict | None":
    """按格式匹配：优先**类型专用**库，其次 ``mixed``（含默认库）。

    候选**先按生效白名单过滤**（第 40 期）：库收窄过格式之后，「类型对得上」不再
    等于「扫得到」—— 不过滤就会把 ``.pdf`` 送进一个只收 ``.epub`` 的 ebook 库。
    """
    t = _type_of_name(name)
    if not t:
        return None
    libs = [l for l in library.libraries() if _accepts(l, name)]
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


def _by_keywords(text: str, filename: str = "") -> "dict | None":
    if not text:
        return None
    for l in library.libraries():
        if not _accepts(l, filename):
            continue
        for kw in rules_of(l)["keywords"]:
            if _norm(kw) in text:
                return l
    return None


def decide(src=None, name: str = "", meta: dict = None, base_dir=None) -> "dict | None":
    """判定落库；返回库实体（dict）或 ``None``（表示**没有可接收的库**）。

    ``None`` 有两种成因，调用方看到的处理完全一样（拒收）：书库表为空，
    或者这个文件谁家的规则都不命中。判据就是「库的 ``rules`` 是不是路由表」——
    路由表不命中就不猜，见 :func:`resolve_target`。

    ⚠️ 第 40 期起多了一条**候选过滤**：库的生效扫描白名单收不了这个格式的，
    直接不算候选（见 :func:`_accepts`）—— 路由到一个「收了也看不见」的库会造出
    **隐形文件**（文件落盘了、书目里没有），比拒收更糟。三条规则都用它。
    """
    filename = name or pathlib.PurePosixPath(str(src or "")).name
    if not filename:
        return None

    # 1) 库名（显式意图）—— 来源子目录名概念已移除（第 41 期），此处回落为按库名匹配
    bases = [base_dir] + [r["path"] for r in config.LIBRARY_SOURCE_ROOTS]
    for base in bases:
        hit = _by_subdir(_subdir_of(src, base), filename)
        if hit:
            return hit

    # 2) 格式（确定性最高）
    hit = _by_format(filename)
    if hit and hit.get("type") in ("ebook", "comic", "audiobook"):
        return hit

    # 3) 元数据 / 文件名关键词（最容易误判，最后才用）
    hit = _by_keywords(_haystack(src, filename, meta), filename)
    if hit:
        return hit

    # 4) 都不可靠 → None。**没有默认库可退**，调用方一律拒收（见 resolve_target）
    return None


def decide_for_path(src, base_dir=None) -> "dict | None":
    """``watcher.target_root`` 的入口（保持既有两参调用）。"""
    return decide(src=src, base_dir=base_dir)


class IngestConflict(Exception):
    """入库时命中**跨库同名**：同名同扩展的文件已经在**别的库**里了。

    带 ``suggest``（建议的新文件名，与迁移侧同一套 ``X (2).ext`` 文案）与
    ``existing``（撞上的那本书）。**同库同名不会走到这里** —— 那是「重新转换
    一版」的正常覆盖流程。

    刻意继承 ``Exception`` 而不是 ``RuntimeError``：调用方（watcher / 下载任务 /
    上传）现成的 ``except Exception`` 兜底就会把它记成一次失败并带上可读原因，
    **不会中断扫描线程或任务循环**（第 13 期「后台路径记日志并跳过，不向后抛」）。
    交互路径（上传 / convert-path）额外把它翻成 400 + 建议名。
    """

    def __init__(self, message: str, suggest: str = "", existing: dict = None):
        super().__init__(message)
        self.suggest = suggest
        self.existing = existing


def library_id_of_root(root) -> str:
    """由**库根**反查库 id；不在任何已登记库根内时返回空串。

    摄入闸门用它判断「同名的那本是不是**别的**库」—— 判据必须是库身份，
    不能只看目录是否相同（两个库的根可以长得像，也可能指向同一个位置）。
    """
    try:
        want = pathlib.Path(root).resolve()
    except Exception:
        return ""
    for l in library.libraries():
        for d in library.roots_of(l):
            try:
                if d == want:
                    return str(l.get("id") or "")
            except Exception:
                continue
    return ""


def guard_conflict(out_dir, rel: str) -> None:
    """产出**前**的同名冲突闸门；命中就抛 :class:`IngestConflict`。

    第 17 期起 ``book_id`` 是「库$哈希」，跨库同名天然隔离；本闸门只拦
    **同库内不同路径的同名书**（同 id 撞车，会让 ``by_id`` 抛 ``BookIdConflict``）。

    放在「最终落盘相对路径已知」的那一刻（``pipeline.dispatch`` / ``_emit`` /
    watcher 自实现的复制分支），因此 Komga 布局下改成 ``系列/系列 #N.epub``
    也照样按**真正要写的名字**判定，不会因为只看源文件名而漏判。

    ``out_dir`` 必须是**目标库根**（摄入侧一律来自 :func:`resolve_target`）；
    同库内已有同名文件**一律放行**（覆盖是正常流程），这是本期最易误伤的点。
    """
    base = pathlib.PurePosixPath(str(rel or "")).name
    if not base:
        return
    lib_id = library_id_of_root(out_dir)
    if not lib_id:
        return          # 落点不属于任何已登记库 ⇒ 谈不上「跨库同名」，放行给上游拒收
    hit = library.id_conflict_with(base, lib_id)
    if not hit:
        return
    other = str(hit.get("library_id") or "")
    lib_name = ""
    for l in library.libraries():
        if str(l.get("id") or "") == other:
            lib_name = str(l.get("name") or other)
            break
    suggest = library.suggest_name(base, lib_id, out_dir)
    raise IngestConflict(
        f"已存在同名文件「{base}」（在「{lib_name or other}」中，不同路径）——"
        f"同 id 不同路径会撞车，阅读进度 / 批注无法区分归属。"
        f"建议改名为「{suggest}」，或到「工具 → 书库管理 → 同名冲突」一键修复",
        suggest=suggest,
        existing={"name": hit.get("name"), "library_id": other, "library_name": lib_name},
    )


def resolve_target(src=None, name: str = "", meta: dict = None, base_dir=None) -> dict:
    """摄入目标的**决策结构**：``{library, library_id, root, conflict, suggest, existing}``。

    判据与 :func:`target_root` 完全同源，只是把「命中的库实体」也交出来 ——
    调用方需要库 id 才能取**该库的生效配置**（第 13 期「每库覆盖」：
    落盘布局 / 转换产物 / 非 txt 收取都可能逐库不同，见 :mod:`core.lib_settings`）。

    ⚠️ ``library`` 为 ``None``（连带 ``root=None``、``library_id=""``）表示
    **没有可接收的书库**：书库表为空，或者这个文件谁家的规则都不命中。

    本项目**没有默认库**（见 `core/library.py` 顶部说明），所以这时调用方
    **必须拒收**：文件留在原地、按可读原因记日志。**不许**自己猜一个库当落点 ——
    猜错的代价是书进了没人管的目录，用户还得手工找回来。

    ``effective_library_id`` 是**真正拥有该根目录的库**，冲突判据用它。
    ``conflict`` 为真 = ``name`` 的 basename 已经在**别的库**里（同名同扩展，
    见 :func:`guard_conflict`）；此时 ``suggest`` 是建议的新名字，``existing``
    是撞上的那本。**同库同名不算冲突**，一定放行。
    """
    lib = decide(src=src, name=name, meta=meta, base_dir=base_dir)
    lib_id = str((lib or {}).get("id") or "")
    if lib:
        rs = library.roots_of(lib)
        root = rs[0] if rs else pathlib.Path(config.OUTPUT_DIR)
        effective_id = lib_id or library_id_of_root(root) or ""
    else:
        root = None
        effective_id = ""

    base = name or pathlib.PurePosixPath(str(src or "")).name
    hit = library.id_conflict_with(base, effective_id) if (base and effective_id) else None
    return {
        "library": lib,
        "library_id": lib_id,
        "effective_library_id": effective_id,
        "root": root,
        "conflict": hit is not None,
        "existing": hit,
        "suggest": library.suggest_name(base, effective_id, root) if hit and base else "",
    }


def target_root(src=None, name: str = "", meta: dict = None,
                base_dir=None) -> "pathlib.Path | None":
    """落库根目录；**没有可接收的库时返回 None**（调用方拒收）。

    这是**摄入侧**取目标目录的唯一入口（上传 / 下载 / 监听三条链路共用），
    与读取侧 ``library.root_of()`` 对称。需要库实体 / 冲突信息时用 :func:`resolve_target`。
    """
    return resolve_target(src=src, name=name, meta=meta, base_dir=base_dir)["root"]


def no_library_reason(libs=None, name: str = "") -> str:
    """拒收时给人看的原因。**三种成因分开说**，否则用户不知道该去改哪儿：

    ① 一个书库都没有；② 有库但规则都不命中；③ **规则命中了，但那个库的
    「允许的格式」收不了它**（第 40 期新增，见 :func:`_accepts`）。

    ⚠️ ③ 尤其不能并进 ② —— 那是**假话**：用户明明把文件放进了对的来源目录，
    却被告知「规则不命中」，于是他去改规则，而真正该改的是那个库的允许格式。
    """
    try:
        all_libs = list(library.libraries() if libs is None else libs)
    except Exception:                       # noqa: BLE001
        all_libs = []
    if not all_libs:
        return "还没有书库：请先到「工具 → 书库管理」新建一个书库并指定它的来源目录"
    if name and not any(_accepts(l, name) for l in all_libs):
        ext = pathlib.PurePosixPath(str(name)).suffix.lower()
        return (f"没有收得了「{name}」的书库：现有书库的「允许的格式」里都没有 "
                f"{ext or '（无扩展名的文件）'}。到「书库管理」编辑对应书库的格式清单"
                "把它加进去，或换一个受支持的格式")
    return ("没有可接收这个文件的书库：现有书库的来源子目录 / 格式 / 关键词规则都不命中。"
            "把它放进某个库的来源子目录，或到书库管理给该库补一条规则")
