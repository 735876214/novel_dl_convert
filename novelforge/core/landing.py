"""把源站的章节**落到这本书自己的位置**（第 93 期 E3 / E4）。

用户拍板的「覆盖」口径（2026-10-03 原话）：

> 默认将本地书进行覆盖。但是正常来讲在我读前 5 章的时候本地还没有书，
> 只有在线源出现更新了才会涉及覆盖，需要书源自动搜索更新章节、自动下载、自动覆盖。

落实成**一个触发器、两条路径**（触发器 = 在线阅读满 5 章，见 :func:`should_sync`）：

======================  ==========  ===========================================================
本地状态                走哪条       做什么
======================  ==========  ===========================================================
**读不了**（没有可读章    ``first``    整本抓下来 → 落到**这本书自己的目录、自己的名字**上
节：文件缺失 / 0 字节 /
解析不出章节）
**能读**                 ``append``   先用 5 章窗口规则对齐源站目录：
                                    · 对得上 ⇒ 追加源站多出来的尾部章节（走**追更同一函数**）
                                    · 对不上 ⇒ **盘上文件零改动**，如实报告
======================  ==========  ===========================================================

三条硬口径（都有测试钉住）：

1. **绝不新建第二条书目**。落点由**这本书自己**决定（``book["path"]`` 的父目录 +
   ``book["name"]`` 的名字），**不是** `library_rules.resolve_target` 猜出来的库根。
   猜库的后果：书架上多出一本同名的，而用户的进度 / 绑定 / 批注还留在旧的那本上
   （第 87 期的同名判定会把它们列成一堆冲突）。同名 ⇒ 同一个 ``book_id`` ⇒ 一切保留。
2. **留档（``<名>.meta.json``）的拼法只有一处**（`autoupdate.sidecar_of`）—— 它既回答
   「这本书追更看哪儿」，也回答「落地往哪儿写」。本模块**不**自己拼一遍路径。
3. **对不上就一个字都不写**。源站换了版 / 目录缺章时，把新章追加到旧目录后面会写出一本
   前后接不上的书，而进度按章号对齐 ⇒ 读者被送到错的地方。宁可报清楚，也不静默改坏一本书。

4. **追更改不到这本书就不动手**（:func:`updatable`）。追更只维护「收书目录里的原件 +
   本项目的成品 EPUB」两份；用户自己导入的书（书库来源目录里的 `.txt` / `.pdf` / 别处的
   EPUB）两份都不沾。真机验证逮到过：报告写着「对齐后追加了 12 章」，而这本书的字节
   **与执行前完全一致** —— 假报告比不做还糟（用户以为本地补齐了，翻开来还是旧的）。
   所以先在 :func:`_append` 里问一句「改得到吗」，问不到就如实说明并指向显式覆盖。

⚠️ **写盘边界**：本模块只写「这本书自己的成品 / 留档 txt 与 sidecar / 监听状态」。
   **源文件（用户自己导入的书）永不写** —— 增量那条路靠上面第 4 条**拒绝**来保证，
   整本重写那条路（`first` / 显式 `overwrite`）才是本模块唯一会盖到用户原文件的地方，
   而那两处的前置条件分别是「本地已经读不了」与「用户点过二次确认」。
   删除一律走回收站（本模块根本不删任何书文件）。
   ⚠️ 已知边界（如实记录，不在本期修）：成品 EPUB 由 `pipeline` / `epub_builder` 直接写
   ``out_path``，**不是**「临时文件 + replace」—— 与既有下载链路同一性质（`_run_download`
   也是这么写的）。本模块只保证：先落到同盘的暂存目录、再用 ``Path.replace`` 原子搬到
   这本书的位置上（见 :func:`_first_landing`），所以**搬到一半**不会留下半本书。
"""
import json
import logging
import os
import pathlib
import secrets
import shutil

from .. import config
from . import library, lib_settings, reading_list

_log = logging.getLogger("novelforge")

#: 自动落地的触发门槛（用户口径：「在线阅读超过 5 章后，自动将书下载到本地」）。
#: 判据是 ``len(seen) > SYNC_AFTER``（``seen`` 去重、上限 64，见 `db.ONLINE_SEEN_MAX`）。
SYNC_AFTER = 5

#: 「成品」的后缀白名单：落地成功后要在暂存目录里**认出**产物。按后缀找而不是按名字算
#: ——`pipeline._place` 在 Komga 布局下会把它塞进系列子目录、还会带系列前缀，
#: 按名字算出来的是一个「应该在那儿」的猜测，而这里要的是「实际产出了什么」。
#: （`.txt` 不在其中：它是**原件**而不是成品，落地时按这本书自己的后缀单独认，见
#: `_first_landing` 里那段注释。）
_PRODUCT_SUFFIXES = (".epub", ".cbz", ".mp3")

MISALIGNED = ("源站目录与本地不一致（5 章窗口里不足 3 章同名），未自动写入"
              "（避免进度错位）—— 确认要换成源站这一版，请用「用源站整本覆盖本地」")


# ---------------- 读：这本书自己是谁 ----------------

def book_dir(book: dict):
    """这本书**所在的那个目录**（落点）。判不出来返回 ``None``。

    用 ``book["path"]``（扫描/索引给的绝对路径）的父目录，而**不是**某本书库的根：
    Komga 布局下书在 ``系列/`` 子目录里，拿库根当落点会把书搬出系列、还可能与别的
    同名书撞上。多根书库、以及「书在哪个根」这类问题也一并绕开了 —— 落点是**读出来的**，
    不是推出来的。
    """
    p = str((book or {}).get("path") or "")
    if not p:
        return None
    return pathlib.Path(p).parent


def book_name(book: dict) -> str:
    """这本书的**文件名**（含扩展名，逐字用 ``book["name"]``）。

    「落到这本书自己的位置」= 用**这个名字**覆盖它自己 —— 于是 ``book_id``
    （由 basename 派生）不变，进度 / 绑定 / 批注全部还在原来的那本上。
    """
    return pathlib.PurePosixPath(str((book or {}).get("name") or "")).name


def book_stem(book: dict) -> str:
    """书名（去扩展名）—— 留档 txt / sidecar / 产物的基名都用它。"""
    return pathlib.PurePosixPath(book_name(book)).stem


def local_chapters(book: dict) -> list:
    """这本书**本地**的扁平章节表（``[{index, title}...]``）。

    ⚠️ **唯一实现**（第 93 期收敛）：在线阅读的三个读点（`server._local_chapters`）
    与自动落地读的是同一份 `library.book_detail`，两处各取一份的话，「本地有没有内容」
    这个判据会在两个地方各错一次。

    读不出详情（缺文件 / 详情异常）⇒ 空表：调用方据此如实说「本地读不了」，
    而不是拿一份假目录去对齐（`align_online` 拿到空表会返回 ``None``）。
    """
    try:
        detail = library.book_detail(str((book or {}).get("name") or ""),
                                     (book or {}).get("library_id")) or {}
    except Exception as e:                              # noqa: BLE001 —— 详情坏了不该让整条链 500
        _log.info("读本地目录失败（%s）：%s", (book or {}).get("name"), e)
        return []
    return [c for g in (detail.get("chapters") or []) for c in (g.get("chapters") or [])]


def readable(book: dict) -> bool:
    """本地有没有**可读内容**（判据 = 本地章节表非空）。

    「文件缺失 / 0 字节 / 解析不出章节」三种情形都落在这一条上 —— 用户的「在我读前 5 章
    的时候本地还没有书」说的正是它。
    """
    return bool(local_chapters(book))


# ---------------- 判：追更改得到这本书吗 ----------------

def _same_path(a, b) -> bool:
    """两个路径指同一个文件吗（解析成绝对 + 大小写归一 —— win32 上尤其必要）。"""
    if a is None or b is None or not str(a) or not str(b):
        return False
    try:
        return os.path.normcase(str(pathlib.Path(a).resolve())) == \
            os.path.normcase(str(pathlib.Path(b).resolve()))
    except OSError:
        return False


def update_writes(book: dict) -> list:
    """追更**实际会写**的那两份文件（`manager._update_report_locked` 的两个写点）。

    · 收书目录里的原件 ``<stem>.txt``（`autoupdate.sidecar_of` 的去后缀）—— 它自己
      也可能就是书架上的那一本（单目录部署 / 只有 txt 产物时）；
    · 成品 ``<output_dir>/<stem>.epub`` —— ``output_dir`` 优先取**现有留档**里的那份
      （它是权威，追更一直在维护），没有留档时就是这本书自己所在的目录
      （与 :func:`ensure_sidecar` 新建时的取值一致）。
    """
    out_dir = None
    try:
        from . import autoupdate
        sc = autoupdate.sidecar_of(book)
        if sc is not None and sc.is_file():
            out_dir = pathlib.Path(
                str(json.loads(sc.read_text(encoding="utf-8")).get("output_dir") or ""))
    except Exception as e:                              # noqa: BLE001 —— 坏留档当没有，别炸整条链
        _log.info("读留档的 output_dir 失败（按这本书所在目录算）：%s", e)
        out_dir = None
    if out_dir is None or not str(out_dir):
        out_dir = book_dir(book)
    stem = book_stem(book)
    cands = [pathlib.Path(config.INPUT_DIR) / f"{stem}.txt"]
    if out_dir is not None:
        cands.append(pathlib.Path(out_dir) / f"{stem}.epub")
    return cands


def updatable(book: dict) -> tuple:
    """这本书**能被自动追更改到**吗 ⇒ ``(会改到的那个文件, 不能改的原因)``。

    :func:`update_writes` 那两份里必须有**一份就是这本书自己的文件**，否则「追加新章」这件事
    落到盘上只有两个结局：书一个字没变（用户自己的 ``.txt`` / ``.pdf`` / 别处的 EPUB），
    或者在一个跟这本书无关的位置凭空长出一个 txt。两种都会让报告变成**假话** ——
    真机验证逮到过：报告写着「对齐后追加了 12 章」，而这本书的字节与执行前**完全一致**。

    这是本轮唯一一处「宁可报清楚，也不做半个动作」的判据，与 `MISALIGNED` 同性质。
    """
    here = str((book or {}).get("path") or "")
    if not here:
        return None, f"算不出《{(book or {}).get('name')}》的文件路径"
    for c in update_writes(book):
        if _same_path(c, here):
            return c, ""
    return None, (f"自动追更只写「收书目录里的原件」与「本项目的成品 EPUB」两份，"
                  f"《{book.get('name')}》两处都不是 —— 换不到它的内容"
                  "（就地改写会动到追更职责之外的那一份文件，例如你自己导入的原书）。"
                  "要让这本书跟着源站走，请在在线阅读卡里点「用源站整本覆盖本地」")


# ---------------- 判：要不要动，和对得上吗 ----------------

def should_sync(row: dict, *, after: int = SYNC_AFTER) -> tuple:
    """要不要为这本书自动落地 ⇒ ``(要不要, 原因)``；原因是**跳过时的如实说明**。

    两条判据缺一不可：

    · **读满 5 章以上**（``len(seen) > after``）：用户口径的触发器。`seen` 是**去重**的
      （`db.online_bind_mark_seen`），所以「反复翻回第 2 章」不会把门槛刷过去。
    · **``auto_task`` 为空**：自动落地**只触发一次**的凭据。失败也不重试轰炸 ——
      重试的依据在任务中心，不是「再来一轮」。

    ⚠️ 本函数**只判、不做**：它不建任务、不写库（调用方拿到 True 之后自己建任务并写
    ``auto_task``）—— 判据与副作用分开，才好在测试里逐条钉。
    """
    if not row:
        return False, "这本书没有绑定书源"
    if str(row.get("auto_task") or ""):
        return False, "自动落地已经触发过一次（失败也不重复轰炸，见任务中心）"
    seen = len(row.get("seen") or [])
    if seen <= int(after):
        return False, f"在线阅读 {seen} 章，还没到自动落地的门槛（超过 {int(after)} 章）"
    return True, ""


def aligned_tail(online_titles: list, local: list):
    """源站目录与本地目录对得上吗 ⇒ ``(shift, known)``；对不上 ⇒ ``None``。

    判据 = `reading_list.align_shift`（用户拍板的「本章节及上下章节共 5 章能有 3 章对应上」，
    **唯一实现**），返回的位移把本地 index 映到线上 index。追加要的是**边界**：
    本地末章在源站目录里的位置对得上，才敢把源站多出来的那几章追加到本地末尾 ——
    追加**不动既有章的 index**，所以进度不会漂移。

    ``known`` = **本地已经落地到源站的第几章**（源站 ``chapters[known:]`` 就是那几章新章）。
    ⚠️ 它**不是** ``len(local)``：本地章节表是按 spine 下标给的，成品 EPUB 首条是 nav 目录页
    ⇒ 本地条数比源站章数多（`align_shift` 注释里那件事）。把它当成章数交给追更，
    追更会从**错的位置**开始追加（少下一章 / 重复下一章，两边都不报错）。

    ⚠️ 还要求**本地末章自己**在位移下标题对得上（`align_shift` 的锚点允许往前退，
    这里把边界钉死）：边界对不上就不追加，如实报「对不上」—— 这是「一个字都不写」那条口径。
    """
    if not local or not online_titles:
        return None
    shift = reading_list.align_shift(online_titles, local)
    if shift is None:
        return None
    tail = max(int(c["index"]) for c in local if c.get("index") is not None)
    titles = list(online_titles)
    j = tail + shift
    if j < 0 or j >= len(titles):
        return None
    mine = reading_list.norm_title(_title_at(local, tail))
    if not mine or mine != reading_list.norm_title(titles[j]):
        return None
    return shift, j + 1


def _title_at(local: list, index: int) -> str:
    """本地章节表里 ``index`` 那一章的标题（读不到 ⇒ 空串）。"""
    for c in local:
        if c.get("index") is not None and int(c["index"]) == index:
            return str(c.get("title") or "")
    return ""


# ---------------- 写：留档 ----------------

def ensure_sidecar(book: dict, row: dict, local: list, known: int) -> tuple:
    """确保这本书有一份**指向当前绑定**的留档 ⇒ ``(路径, 拒绝原因)``。

    三条分支（第二条是安全阀，别删）：

    · **没有留档** ⇒ 按绑定造一份。字段与 `manager.write_sidecar` **同形**，
      并补上两样只有这里才知道的东西：``chapters`` = **本地已有几章**（追更据此算起点）、
      ``last_title`` = 本地末章名。
      ⚠️ ``chapters`` 收的是 ``known``（**源站章号**，由 `aligned_tail` 算出来），
      **不是** ``len(local)`` —— 后者含 nav 目录页这类本地独有的条目，追更照它算起点会
      少下一章（静默丢章）。
    · **有留档，且指向同一个源与同一页** ⇒ 原样返回。那份是权威 —— 追更一直在维护它
      （``chapters`` 随每次追更更新），重写它等于把权威换成一份我们自己算的近似值。
    · **有留档，但指向别的源 / 别的页** ⇒ **拒绝并说明**。本地这本书是另一个来源
      （或同一源的另一个书页）下载来的，把两套目录混在一起追加，会写出一本前后接不上的书；
      而用户很可能只是把在线读绑到了另一个站上。要换版本得显式「用源站整本覆盖本地」。

    ⚠️ 路径拼法**只有一处**（`autoupdate.sidecar_of`）—— 这里不自己拼。
    """
    from . import autoupdate
    path = autoupdate.sidecar_of(book)
    if path is None:
        return None, f"算不出《{book.get('name')}》的留档路径"
    src, url = str(row.get("source") or ""), str(row.get("url") or "")
    if path.is_file():
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
        except Exception:                               # noqa: BLE001 —— 坏留档当没有，重新写
            old = None
        if isinstance(old, dict):
            if (old.get("source") or "") == src and (old.get("url") or "") == url:
                return path, ""
            return None, (f"本地这本书的留档来自另一个来源（{old.get('source') or '?'} / "
                          f"{old.get('url') or '?'}），与当前绑定的（{src} / {url}）不是同一份 —— "
                          "为避免两套目录混在一起，没有自动写入本地；"
                          "要换成当前这一版，请用「用源站整本覆盖本地」")
    bdir = book_dir(book)
    if bdir is None:
        return None, f"算不出《{book.get('name')}》所在的目录"
    last = _title_at(local, max((int(c["index"]) for c in (local or [])
                                 if c.get("index") is not None), default=-1))
    meta = {"source": src, "url": url, "title": row.get("title") or book.get("title") or "",
            "output_dir": str(bdir), "chapters": int(known or 0)}
    if last:
        meta["last_title"] = last
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_text(path, json.dumps(meta, ensure_ascii=False))
    return path, ""


def _write_text(path: pathlib.Path, text: str) -> None:
    """原子写一个文本文件（``.part`` + ``Path.replace``）—— 与全仓其它写点同一手法。

    留档写一半就会被当成「本地已有这么多章」，于是下次追更从错误的位置开始、
    **静默丢章** —— 这类半成品比没有更糟。
    """
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ---------------- 落地 / 更新 ----------------

async def _first_landing(mgr, book: dict, row: dict) -> dict:
    """**首次落地**：整本抓到这本书自己的位置上（本地读不了时的唯一出路）。

    步骤与每一步的「为什么」：拉到**同盘的暂存目录**（书所在目录下的 ``.nfstage-*``，
    扫描器跳过 ``.`` 开头的目录 ⇒ 中途不会被收进书架）→ 按**这本书自己的后缀**认产物
    → 原子搬到这本书的名字上 → 留档 txt / sidecar 搬进收书目录（并把 ``output_dir``
    改回**最终**位置）→ 把这个 txt 在监听器里登记为已处理。

    ⚠️ 「按后缀认产物」不是洁癖：EPUB 的字节写进 ``.txt`` 的名字，得到的是**一本名不副实的书**
    —— 扫描器按后缀派阅读器，TXT 阅读器拿 zip 当文本解，打开是一屏乱码（真机验证逮到）。
    产物里没有这本书的格式时就**如实拒绝**，而不是硬塞一个进去。
    （``.txt`` 书的「产物」是管线同时产出的**源文本原件** ``<stem>.txt``，不是 EPUB。）

    ⚠️ 最后一步**不能省**：留档 txt 写在**被监听**的收书目录里，
    不登记就会被监听线程当成新文件收一次 ⇒ 书架上多出一本 ``<名>.txt``
    （正是「绝不新建第二条书目」要避免的事）。
    """
    from . import autoupdate, watcher as watcher_mod
    bdir = book_dir(book)
    name, stem = book_name(book), book_stem(book)
    if bdir is None or not name:
        return _skip(f"算不出《{book.get('name')}》的落点（缺 path / name），没有写任何文件")
    stage = bdir / f".nfstage-{secrets.token_hex(4)}"
    stage.mkdir(parents=True, exist_ok=True)
    try:
        opts = {"force": True, "merge": True, "filename": stem,
                "cfg": lib_settings.config_for(book.get("library_id") or None)}
        # `source` 是 `DownloadManager.download_to` 认书源的**唯一读法**（`source_of`）；
        # `title` = 这本书自己的书名（逐字）：`download_to` 用它清洗出 txt / 产物的名字，
        # 再配上显式的 `filename` 与 `txt_stem`，产出的就是**这本书自己**。
        # ⚠️ 不传 `formats`：绑定表只存了书页地址（第 93 期 B），需要 `formats` 的书源
        # （目前只有内置的 Gutenberg）会在这里如实报错，而不是拿一份编造的格式表去请求。
        item = {"source": row.get("source") or "", "url": row.get("url") or "", "title": stem}
        await mgr.download_to(item, stage, stage, opts, txt_stem=stem)
        products = sorted(p for p in stage.rglob("*")
                          if p.is_file() and p.suffix.lower() in _PRODUCT_SUFFIXES)
        txt_src = stage / f"{stem}.txt"
        # ⚠️ **产物形态必须与这本书自己的后缀一致**。把 EPUB 的字节写进 `.txt` 的名字，
        # 得到的是「一本名不副实的书」：扫描器按后缀派阅读器，TXT 阅读器拿 zip 当文本解
        # ⇒ 打开是一屏乱码（真机验证逮到：`落地测试.txt` 的头四个字节是 `PK\x03\x04`）。
        # 而**同名（含后缀）**正是 `book_id` 不变、进度/绑定/批注全保留的前提。
        want = pathlib.Path(name).suffix.lower()
        picked = [txt_src] if want == ".txt" and txt_src.is_file() \
            else [p for p in products if p.suffix.lower() == want]
        if len(picked) != 1:
            got = "、".join(sorted({p.suffix for p in products})) or "没有成品"
            return _skip(f"源站这次产出的是 {got}，与《{name}》的格式对得上的是 "
                         f"{len(picked)} 份 —— 就地替换会写出一本名不副实的书"
                         "（阅读器按后缀派），所以没有写进书库；要这一版请手动下载")
        dest = bdir / name
        if picked[0] == txt_src:
            # txt 书：原件既**就是**这本书、又是追更的留档 ⇒ 两处各留一份（copy 不是 move，
            # 否则下面那段就再也找不到 txt 了）。
            txt_dest = pathlib.Path(config.INPUT_DIR) / f"{stem}.txt"
            txt_dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(txt_src, txt_dest)
        picked[0].replace(dest)                      # 同盘 ⇒ 原子覆盖这本书自己
        txt_dest = pathlib.Path(config.INPUT_DIR) / f"{stem}.txt"
        txt_dest.parent.mkdir(parents=True, exist_ok=True)
        if txt_src.is_file():
            txt_src.replace(txt_dest)
        meta_src = stage / f"{stem}.meta.json"
        if meta_src.is_file():
            meta = json.loads(meta_src.read_text(encoding="utf-8"))
            meta["output_dir"] = str(bdir)           # 暂存目录只在这次调用里活着
            _write_text(txt_dest.with_suffix(".meta.json"),
                        json.dumps(meta, ensure_ascii=False))
        _mark_done(txt_dest, watcher_mod)            # 见 docstring 最后一条
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    library.invalidate()
    _log.info("自动落地完成：《%s》 → %s", stem, dest)
    return {"mode": "first", "added": 0, "note": "",
            "title": stem, "epub": str(dest), "path": str(dest),
            "detail": f"本地读不了（没有可读章节），已按源站整本落到 {name}"}


async def _append(mgr, book: dict, row: dict, local: list) -> dict:
    """**更新已有的本地副本**：对齐则追加尾部新章（走追更**同一函数**，index 不漂移）。"""
    from . import autoupdate, watcher as watcher_mod
    from ..sources import online as online_mod
    try:
        data = await online_mod.index_of(mgr, book.get("id") or "", row.get("source") or "",
                                         row.get("url") or "")
    except Exception as e:                              # noqa: BLE001 —— 原因原文交给用户
        return _skip(f"取源站目录失败：{e}")
    titles = [e.get("title") or "" for e in (data.get("entries") or [])]
    align = aligned_tail(titles, local)
    if align is None:
        return _skip(MISALIGNED)
    _shift, known = align
    if len(titles) <= known:
        return _skip(f"源站 {len(titles)} 章，不比本地已落地的 {known} 章多 —— 没有可追加的章节")
    # 先确认追更**改得到这本书**，再决定要不要建留档：反过来的话，一次注定没用的
    # 调用会在收书目录里留下一个原件 txt 与一份留档（用户自己的书一个字没变）。
    target, why = updatable(book)
    if target is None:
        return _skip(why)
    sidecar, why = ensure_sidecar(book, row, local, known)
    if sidecar is None:
        return _skip(why)
    try:
        # ⚠️ **协程壳**，不是同步的 `update_book`：本函数跑在事件循环里，
        # 同步壳内部的 `asyncio.run` 会直接抛（见 `update_book_async` 的 docstring）。
        res = await autoupdate.update_book_async(book, mgr, origin="online")
    except autoupdate.Blocked as e:
        return _skip(f"{e}")
    except Exception as e:                              # noqa: BLE001 —— 原因原文交给用户
        return _skip(f"追更失败：{e}")
    txt_dest = pathlib.Path(config.INPUT_DIR) / f"{book_stem(book)}.txt"
    _mark_done(txt_dest, watcher_mod)
    return {"mode": "append", "added": int(res.get("added") or 0),
            "note": str(res.get("note") or ""), "title": book_stem(book),
            "epub": str(res.get("epub") or ""), "path": str(sidecar),
            "detail": f"源站 {len(titles)} 章、本地已落地 {known} 章：对齐后追加了 "
                      f"{int(res.get('added') or 0)} 章"}


def _mark_done(txt_path: pathlib.Path, watcher_mod) -> None:
    """把刚落地的留档 txt 登记为「已处理」（**精确到这一个文件**）。

    `_run_download` 用的是 ``mark_recent(30, ".txt")``（把最近 30 秒里**所有** txt 都盖掉）——
    那是它只知道产出目录、不知道 txt 确切名字的将就做法。这里我们知道是哪一份，
    就只盖那一份：同一时间窗里用户自己刚丢进收书目录的文件不该被顺手跳过。

    ⚠️ 监听器**没起**时也照记（`current()` 可能为 ``None``）：没起 = 本来就不会重复转换；
    而漏记的代价是多出一本同名 txt 书，比多盖一个文件严重得多。
    """
    w = watcher_mod.current() if watcher_mod is not None else None
    if w is None or not txt_path.is_file():
        return
    try:
        w.mark_processed(txt_path)
    except Exception as e:                              # noqa: BLE001 —— 登记失败不该让落地判负
        _log.warning("登记已处理失败（%s）：%s", txt_path, e)


def _skip(note: str) -> dict:
    """一份**什么都没做**的如实报告（``mode="skip"``，原因在 ``note``）。"""
    return {"mode": "skip", "added": 0, "note": note, "title": "", "epub": "",
            "path": "", "detail": note}


async def sync(mgr, book: dict, row: dict, *, overwrite: bool = False,
               allow_first: bool = False) -> dict:
    """**自动落地的唯一入口**：把源站内容落到这本书自己的位置上，返回如实报告。

    返回 ``{"mode", "added", "note", "title", "epub", "path", "detail"}``；
    ``mode`` 只有三档：``first``（首次落地整本）/ ``append``（对齐后追加）/ ``skip``（没动）。

    · ``overwrite=True`` ⇒ **无视本地有没有内容，整本重来**。这是用户显式动作
      （详情页的「用源站整本覆盖本地」，二次确认过），代价写在他的眼皮底下：
      章节结构按源站那一版走，进度按**章号**重新对齐。
    · ``allow_first=False`` ⇒ 本地读不了时**不**整本落地，只如实说明。
      定时追更那条路用它：用户没读过的书不该被它悄悄下一本。触发器只有
      :func:`should_sync` 那一处（在线阅读过闸门之后）。

    ⚠️ 本函数**不建任务、不写 ``auto_task``**：那是调用方的账（见 `server._run_sync` /
    `autoupdate._run_binding`）—— 这里只做「文件该怎么动」这一件事，好在测试里单独跑。
    """
    if not book:
        return _skip("书籍不存在（可能刚被删除）")
    if not row:
        return _skip("这本书没有绑定书源")
    kind = _product_kind(row.get("source") or "")
    if kind != "text":
        return _skip(f"这本书的书源产物是「{'漫画' if kind == 'comic' else '有声'}」，"
                     "本期只支持文本自动落地 —— 请手动下载")
    local = local_chapters(book)
    if overwrite or not local:
        if not overwrite and not allow_first:
            return _skip("本地没有可读内容：在在线阅读里读满 "
                         f"{SYNC_AFTER + 1} 章会自动落到本地（或手动点「用源站整本覆盖本地」）")
        return await _first_landing(mgr, book, row)
    return await _append(mgr, book, row, local)


def _product_kind(source: str) -> str:
    """这条书源产出的是哪一类产物（`sources.rules.product_kind`，唯一实现）。"""
    from ..sources import rules
    return rules.product_kind(source)
