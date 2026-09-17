"""KOReader 进度互通（kosync 协议的服务端实现）。

KOReader 的「同步服务器」（kosync）协议本身很小，但有几个**必须精确**的细节，
错一个字节就匹配不上，所以都记在这里：

1. **鉴权用自定义头** ``x-auth-user`` / ``x-auth-key``，不是 HTTP Basic；
   而且 ``x-auth-key`` 是**密码的 MD5**（客户端先算好再发）。因此服务端也只存这个 MD5，
   从不接触明文密码 —— 万一索引泄露，也拿不到用户口令。
   （HTTP 头名实测：KOReader 的 ``KOSyncClient`` 用 ``x-auth-*`` 两个头。）

2. **文档标识是 partialMD5，不是整文件 MD5**。算法（摘自 KOReader ``frontend/util.lua``）::

       step, size = 1024, 1024
       for i = -1, 10:
           seek(1024 * 4^i);  update(read(1024))

   即采样 12 个点：偏移 256 / 1024 / 4096 / … / 1073741824，每点读 1024 字节后串联求 MD5。
   设计动机：KOReader 给 PDF 加高亮时会**往文件尾部追加数据**，采样点越靠后越稀疏，
   以降低「追加数据导致摘要变化」的概率。
   ⚠️ 两点容易写错：**不读文件第 0 字节**（首个采样在 256）；读不满 1024 字节
   （读到 EOF）就**停止采样**，而不是继续往后跳。
   另有 ``checksum_method = FILENAME`` 变体，用 ``md5(basename)`` —— 两种都索引。

3. **进度**：``percentage`` 是 0–1 浮点；``progress`` 对 EPUB 是 XPointer
   （形如 ``/body/DocFragment[20]/body/p[22]/img.0``），对 PDF/漫画是页码字符串。

本项目的进度是 ``(locator=位置序号, percent=0–100)``，两者的映射：
- EPUB：XPointer 的 ``DocFragment[N]`` ≈ spine 第 N 个文档 ≈ 本项目**章节 index + 1**
- PDF / 漫画：本项目的 locator 就是**页码 - 1**

⚠️ **NF → KOReader 的 XPointer 是近似值**：我们只知道用户读到第几章，不知道章节内的段落位置。
给出 ``DocFragment[N]`` 让 KOReader 跳到该章开头，另有准确的 ``percentage`` 兜底
（KOReader 在 ``percentage == body.percentage`` 时会判定「已同步」，所以不会误跳）。
"""
import hashlib
import pathlib
import re

#: XPointer 里的 DocFragment 序号（KOReader 对 EPUB 的分片标识）
_FRAGMENT = re.compile(r"DocFragment\[(\d+)\]")


def partial_md5(path) -> str:
    """KOReader 的 partialMD5（文档标识）。算法见模块 docstring，别改采样点。"""
    h = hashlib.md5()
    with open(path, "rb") as f:
        for i in range(-1, 11):          # -1..10 含两端，共 12 个采样点
            offset = int(1024 * (4 ** i))   # i=-1 → 256
            f.seek(offset)
            sample = f.read(1024)
            if not sample:               # 读到 EOF 就停（不是继续往后跳）
                break
            h.update(sample)
    return h.hexdigest()


def filename_md5(name: str) -> str:
    """``checksum_method = FILENAME`` 变体：md5(**basename**)，不含路径。"""
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return hashlib.md5(base.encode("utf-8")).hexdigest()


def xpointer_chapter(progress: str) -> int:
    """从 XPointer 解析章节序号（0 起）；解析不出返回 -1。"""
    m = _FRAGMENT.search(str(progress or ""))
    if not m:
        return -1
    try:
        return max(0, int(m.group(1)) - 1)   # DocFragment 从 1 起，本项目从 0 起
    except ValueError:
        return -1


def make_xpointer(locator: int) -> str:
    """章节序号 → XPointer（近似，只定位到章首；准确的百分比由 percentage 兜底）。"""
    try:
        n = max(1, int(locator) + 1)
    except (TypeError, ValueError):
        n = 1
    return f"/body/DocFragment[{n}]/text().0"


def to_nf(payload: dict) -> tuple:
    """KOReader 的上传体 → ``(locator, percent)``。

    locator 优先取 XPointer 的章节序号；PDF/漫画的 ``progress`` 是页码字符串，
    此时退回用「页码 - 1」。percent 一律用 ``percentage``（更权威）。
    """
    locator = xpointer_chapter(payload.get("progress"))
    if locator < 0:
        raw = str(payload.get("progress") or "").strip()
        if raw.isdigit():
            locator = max(0, int(raw) - 1)
        else:
            locator = 0
    try:
        percent = float(payload.get("percentage") or 0) * 100.0
    except (TypeError, ValueError):
        percent = 0.0
    percent = max(0.0, min(100.0, percent))
    return locator, percent


def from_nf(book: dict, prog: dict, device: str = "") -> dict:
    """本项目的进度 → KOReader 的 GET 响应体。

    ``timestamp`` 必须给：KOReader 用它做新旧比较，缺了会退回「百分比更大者胜」的旧逻辑。
    """
    percent = float((prog or {}).get("percent") or 0)
    locator = int((prog or {}).get("locator") or 0)
    fmt = str((book or {}).get("format") or "").upper()
    has_pages = fmt in ("PDF", "CBZ")
    return {
        "document": "",
        "progress": str(locator + 1) if has_pages else make_xpointer(locator),
        "percentage": round(max(0.0, min(100.0, percent)) / 100.0, 6),
        "device": device or "NovelForge",
        "device_id": "",
        "timestamp": int((prog or {}).get("updated_at") or 0),
    }


def scan_books(books: list, out_dir) -> list:
    """为书库建立「文档标识 → 书」索引（返回待写入的行）。

    算 partialMD5 要读 12 个采样点（不是整文件），几十本书是毫秒级；
    但没必要每次同步都算，所以结果落 `koreader_docs` 表并按 size/mtime 判过期。
    """
    out_dir = pathlib.Path(out_dir)
    rows = []
    for b in books:
        name = str(b.get("name") or "")
        if not name:
            continue
        path = out_dir / name
        if not path.is_file():
            continue
        try:
            st = path.stat()
            doc = partial_md5(path)
        except OSError:
            continue
        rows.append({
            "book_id": b["id"],
            "doc_md5": doc,
            "alt_md5": filename_md5(name),
            "size": int(st.st_size),
            "mtime": float(st.st_mtime),
        })
    return rows
