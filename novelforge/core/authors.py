"""作者级元数据：OpenLibrary 作者检索 + 传记 / 头像本地缓存（第 8 期 D1/D2/D5）。

与书籍元数据同一原则（**在线优先、本地兜底、可编辑**）：

- ``authors`` 表同时存**在线** bio/photo 与**用户本地覆盖**（``bio_local`` / ``photo_local_path``）；
- 展示取 本地覆盖 > 在线；用户改过的不会被再次抓取冲掉；
- 头像一律下载到 ``CACHE_DIR/authors/``（**零外链**，与字体 / 封面同约定），
  经 ``/api/authors/{name}/photo`` 分发；
- 抓取全程容错：外网不通只返回 error，绝不向上抛（旁路增强）。
"""
import difflib
import hashlib
import pathlib
import time

import httpx

from .. import config
from . import db, library
from .library import norm_key

OL_AUTHOR_SEARCH = "https://openlibrary.org/search/authors.json"
OL_AUTHOR_DETAIL = "https://openlibrary.org{key}.json"
OL_PHOTO = "https://covers.openlibrary.org/a/id/{pid}-L.jpg"

_HEADERS = {"User-Agent": "NovelForge/1.0 (+metadata)", "Accept": "application/json"}
_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
MAX_PHOTO_BYTES = 8 * 1024 * 1024
#: 归一化名相似度低于此值视为「不像同一个人」，宁可放弃也不给错配的传记
_MIN_MATCH = 0.5


def authors_dir() -> pathlib.Path:
    """头像缓存目录（不存在则创建）。"""
    d = pathlib.Path(config.CACHE_DIR) / "authors"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _photo_basename(seed: str) -> str:
    return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16] + ".jpg"


def _name_score(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a, b).ratio()


def _best_match(name: str, docs: list) -> "dict | None":
    """在检索结果里挑最匹配的作者：归一化名相似度最高，平手取作品数多的。"""
    want = norm_key(name)
    best, best_score = None, -1.0
    for d in docs:
        cand = norm_key(d.get("name") or "")
        if not cand:
            continue
        score = _name_score(want, cand)
        if score > best_score:
            best, best_score = d, score
    if best is None or best_score < _MIN_MATCH:
        return None
    return best


def _download_photo(url: str, seed: str) -> str:
    """下载头像到 ``CACHE_DIR/authors/``，返回文件名（不含目录）。失败抛异常。"""
    with httpx.stream("GET", url, timeout=_TIMEOUT, headers=_HEADERS,
                      follow_redirects=True) as r:
        if r.status_code >= 400:
            raise ValueError(f"头像下载失败（HTTP {r.status_code}）")
        mt = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
        if not mt.startswith("image/"):
            raise ValueError(f"头像不是图片（{mt or '未知类型'}）")
        buf = bytearray()
        for chunk in r.iter_bytes(65536):
            buf.extend(chunk)
            if len(buf) > MAX_PHOTO_BYTES:
                raise ValueError("头像超过 8MB 上限")
    if not buf:
        raise ValueError("头像内容为空")
    fn = _photo_basename(seed)
    (authors_dir() / fn).write_bytes(bytes(buf))
    return fn


def fetch_author(name: str) -> dict:
    """抓取单个作者的在线信息（传记 + 头像），落库并返回结果。

    返回 ``{name, ok, bio?, has_photo?, error?}``；**不抛异常**。
    """
    name = str(name or "").strip()
    if not name:
        return {"name": name, "ok": False, "error": "作者名为空"}
    try:
        r = httpx.get(OL_AUTHOR_SEARCH, params={"q": name, "limit": "5"},
                      timeout=_TIMEOUT, headers=_HEADERS)
        r.raise_for_status()
        docs = (r.json() or {}).get("docs") or []
    except Exception as e:  # noqa: BLE001 - 旁路增强，任何异常都折算成失败
        return {"name": name, "ok": False, "error": f"作者检索失败：{e}"}

    match = _best_match(name, docs)
    if not match:
        return {"name": name, "ok": False, "error": "OpenLibrary 未找到匹配的作者"}

    key = match.get("key") or ""
    try:
        rd = httpx.get(OL_AUTHOR_DETAIL.format(key=key), timeout=_TIMEOUT, headers=_HEADERS)
        rd.raise_for_status()
        detail = rd.json() or {}
    except Exception as e:  # noqa: BLE001
        return {"name": name, "ok": False, "error": f"作者详情获取失败：{e}"}

    bio = detail.get("bio") or ""
    if isinstance(bio, dict):
        bio = bio.get("value") or ""
    bio = str(bio).strip()

    photos = detail.get("photos") or []
    photo_path = ""
    if photos:
        try:
            photo_path = _download_photo(OL_PHOTO.format(pid=photos[0]), f"{name}:{photos[0]}")
        except Exception:  # noqa: BLE001 - 头像失败不致命，传记仍可用
            photo_path = ""

    db.upsert_author(name, bio=bio, photo_path=photo_path, photo_source="openlibrary")
    return {"name": name, "ok": True, "bio": bio, "has_photo": bool(photo_path)}


def fetch_all() -> dict:
    """抓取全部作者（按 ``library.authors_list()`` 聚合）。返回 ``{total, ok, failed}``。"""
    names = [a["name"] for a in library.authors_list()]
    ok = failed = 0
    for n in names:
        if fetch_author(n).get("ok"):
            ok += 1
        else:
            failed += 1
    return {"total": len(names), "ok": ok, "failed": failed}


def effective(name: str) -> dict:
    """作者生效信息：bio（本地覆盖 > 在线）、头像有无、各覆盖标记、抓取时间。"""
    row = db.get_author(name) or {}
    bio_local = str(row.get("bio_local") or "").strip()
    photo_local = str(row.get("photo_local_path") or "").strip()
    photo_online = str(row.get("photo_path") or "").strip()
    return {
        "name": name,
        "bio": bio_local or str(row.get("bio") or ""),
        "bio_overridden": bool(bio_local),
        "has_photo": bool(photo_local or photo_online),
        "photo_overridden": bool(photo_local),
        "photo_source": str(row.get("photo_source") or ""),
        "fetched_at": float(row.get("fetched_at") or 0),
    }


def photo_path_for(name: str) -> "pathlib.Path | None":
    """生效头像的绝对路径（本地覆盖 > 在线）；无则 None。"""
    row = db.get_author(name) or {}
    base = str(row.get("photo_local_path") or "").strip() or str(row.get("photo_path") or "").strip()
    if not base:
        return None
    p = authors_dir() / base
    return p if p.is_file() else None


def set_bio(name: str, bio: str) -> dict:
    """设置/清除用户本地传记覆盖（空串 = 撤销覆盖）。"""
    db.set_author_bio_local(name, bio)
    return effective(name)


def set_photo(name: str, data: bytes, ext: str = "jpg") -> dict:
    """保存用户上传的本地头像（覆盖在线照片）。返回生效信息。"""
    ext = (ext or "jpg").lstrip(".").lower() or "jpg"
    fn = _photo_basename(f"local:{name}:{time.time()}")
    if not fn.endswith(f".{ext}"):
        fn = fn.rsplit(".", 1)[0] + f".{ext}"
    (authors_dir() / fn).write_bytes(data)
    db.set_author_photo_local(name, fn)
    return effective(name)


def clear_photo_override(name: str) -> dict:
    """撤销本地头像覆盖，回退到在线照片。"""
    db.set_author_photo_local(name, "")
    return effective(name)
