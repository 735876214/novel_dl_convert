"""播客订阅与 RSS 解析（第 173 期）—— 播客域的唯一判据源。

## 为什么播客**不是**一种「书库」

书库在本项目里的语义是「**一个要被扫描的目录**」（`library.books()` 遍历文件、索引、
逐库白名单）。播客没有目录：它是一份远端 RSS，单集的音频在别人服务器上。把播客硬塞成
libtype 会让建库向导要求「内容来源目录」、扫描器对着空目录报「没有书」，而真正的内容
来源（feed URL）无处可放。所以播客是**订阅子系统**：自己的两张表、自己的页面，
与 `books / libraries` 零耦合（也就没有 book_id 的 remap 问题）。

## 出网边界

只由**用户显式动作**触发（订阅 / 刷新），后端发起，`http(s)` only，超时 20 s，
响应上限 8 MiB，跟随重定向；失败一律转成可读中文，不阻塞其它功能。
不解析 Atom —— 播客生态几乎全是 RSS 2.0，Atom 分支没有真实样本，按第 96 期口径
「拿到真实样本再立项」，这里如实拒绝而不是猜着解析。
"""
from __future__ import annotations

import email.utils
import html
import json
import os
import pathlib
import queue
import re
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlencode, urlparse

import httpx

from .. import config
from . import db, fileops

TIMEOUT = 20.0
MAX_BYTES = 8 * 1024 * 1024
MAX_DESCRIPTION = 6000
#: 合集名上限（第 185 期）：超长名字只会把侧栏撑坏，截断会让两个名字撞成同一个。
COLLECTION_NAME_MAX = 80


def collection_name(raw) -> str:
    """合集名的唯一规整口（创建与改名共用）。空名拒绝，首尾空白不计。"""
    name = str(raw or "").strip()
    if not name:
        raise ValueError("合集名不能为空")
    if len(name) > COLLECTION_NAME_MAX:
        raise ValueError(f"合集名最多 {COLLECTION_NAME_MAX} 个字符")
    return name


# ---------------- 智能播放列表（第 186 期）----------------
# 单集轴的规则（与书级 smart_scopes 的语义同构：空值恒真、all=且 / any=或），
# 但字段集不同 —— 单集没有作者/系列，只有时长 / 发布天数 / 播放状态 / 下载状态。
PLAYLIST_NAME_MAX = 80
PLAYLIST_FIELDS = {
    "title": ("contains", "not_contains", "equals"),
    "podcast": ("contains", "not_contains", "equals"),
    "status": ("equals",),
    "duration": ("at_least", "at_most"),
    "published": ("at_least", "at_most"),
    "downloaded": ("equals",),
    "explicit": ("equals",),
}
PLAYLIST_MAX_ITEMS = 200


def playlist_name(raw) -> str:
    name = str(raw or "").strip()
    if not name:
        raise ValueError("播放列表名不能为空")
    if len(name) > PLAYLIST_NAME_MAX:
        raise ValueError(f"播放列表名最多 {PLAYLIST_NAME_MAX} 个字符")
    return name


def playlist_match(raw) -> str:
    match = str(raw or "all")
    if match not in ("all", "any"):
        raise ValueError("match 只能是 all 或 any")
    return match


def playlist_rules(raw) -> list:
    """规整并校验规则；范围外的字段 / 操作 / 取值一律 400（不静默丢弃）。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("rules 必须是数组")
    out = []
    for r in raw:
        if not isinstance(r, dict):
            raise ValueError("每条规则必须是对象")
        field = str(r.get("field") or "")
        op = str(r.get("op") or "")
        value = str(r.get("value") or "").strip()
        if field not in PLAYLIST_FIELDS:
            raise ValueError(f"未知字段：{field}")
        if op not in PLAYLIST_FIELDS[field]:
            raise ValueError(f"字段 {field} 不支持操作 {op}")
        if len(value) > 200:
            raise ValueError("规则值最多 200 个字符")
        if field in ("duration", "published"):
            if value:
                try:
                    n = float(value)
                except ValueError:
                    raise ValueError(f"{field} 的规则值必须是数字") from None
                if n < 0:
                    raise ValueError(f"{field} 的规则值不能为负")
        elif field == "status" and value and value not in ("unplayed", "playing", "played"):
            raise ValueError("status 只能是 unplayed / playing / played")
        elif field in ("downloaded", "explicit") and value and value not in ("yes", "no"):
            raise ValueError(f"{field} 只能是 yes / no")
        out.append({"field": field, "op": op, "value": value})
    return out


def playlist_items(raw) -> list:
    """队列快照：只留播放需要的四个字段，最多 200 条。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("items 必须是数组")
    out = []
    for it in raw[:PLAYLIST_MAX_ITEMS]:
        if not isinstance(it, dict):
            continue
        eid = str(it.get("episode_id") or "").strip()
        if not eid:
            continue
        out.append({
            "episode_id": eid,
            "title": str(it.get("title") or "")[:300],
            "podcast_id": str(it.get("podcast_id") or ""),
            "podcast_title": str(it.get("podcast_title") or "")[:300],
        })
    return out



_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
    "Accept": "application/rss+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _fetch(url: str) -> str:
    """取订阅文件（带超时 / 体积上限 / 重定向）。失败转 `ValueError`（接口层 400）。"""
    u = str(url or "").strip()
    if not re.match(r"^https?://", u, re.I):
        raise ValueError("订阅地址必须是 http:// 或 https://")
    chunks: list = []
    size = 0
    try:
        with httpx.stream("GET", u, headers=_HEADERS, timeout=TIMEOUT,
                          follow_redirects=True) as r:
            r.raise_for_status()
            for chunk in r.iter_bytes(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError(f"订阅文件超过上限（{MAX_BYTES // 1024 // 1024} MB）")
                chunks.append(chunk)
    except httpx.HTTPStatusError as e:
        raise ValueError(f"抓取订阅失败：HTTP {e.response.status_code}") from None
    except httpx.HTTPError as e:
        raise ValueError(f"抓取订阅失败：{type(e).__name__}") from None
    return b"".join(chunks).decode("utf-8", "replace")


#: 目录搜索（第 187 期）：iTunes Search API，用户显式点搜索才出网。
DIRECTORY_LIMIT = 20
DIRECTORY_URL = "https://itunes.apple.com/search"


def directory_search(term: str, limit: int = DIRECTORY_LIMIT) -> list:
    """按名字搜播客目录；只返回**带 feedUrl** 的结果（可直接订阅）。

    开关在 `config.DEFAULTS["podcasts"]["directory_search"]`（默认开）。关闭时抛
    `PermissionError`（接口层 403），与「网络不通」区分开 —— 前者是用户的选择，
    后者是失败降级（UI 仍可手动填 RSS 地址）。
    """
    cfg = (config.load_config() or {}).get("podcasts") or {}
    if not bool(cfg.get("directory_search", True)):
        raise PermissionError("播客目录搜索已在「设置 → 网络与下载」关闭")
    q = str(term or "").strip()
    if not q:
        raise ValueError("请输入要搜索的播客名")
    if len(q) > 100:
        q = q[:100]
    url = DIRECTORY_URL + "?" + urlencode({
        "media": "podcast", "entity": "podcast", "limit": max(1, min(int(limit), 50)), "term": q,
    })
    raw = _fetch(url)
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("目录服务返回的不是有效 JSON") from None
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        raise ValueError("目录服务返回格式不对")

    out: list = []
    seen: set = set()
    for r in results:
        if not isinstance(r, dict):
            continue
        feed = str(r.get("feedUrl") or "").strip()
        if not re.match(r"^https?://", feed, re.I) or feed in seen:
            continue
        seen.add(feed)
        genres = r.get("genres")
        out.append({
            "title": str(r.get("collectionName") or r.get("trackName") or "").strip(),
            "author": str(r.get("artistName") or "").strip(),
            "feed_url": feed,
            "artwork_url": str(r.get("artworkUrl600") or r.get("artworkUrl100") or "").strip(),
            "categories": [str(g) for g in genres if g] if isinstance(genres, list) else [],
            "episode_count": int(r.get("trackCount") or 0),
            "itunes_id": str(r.get("collectionId") or ""),
        })
        if len(out) >= max(1, min(int(limit), 50)):
            break
    return out


def _local(tag) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _children(el, name: str) -> list:
    return [c for c in list(el) if _local(c.tag) == name]


def _child(el, name: str):
    for c in list(el):
        if _local(c.tag) == name:
            return c
    return None


def _text(el, *names: str) -> str:
    for n in names:
        c = _child(el, n)
        if c is not None:
            v = "".join(c.itertext()).strip()
            if v:
                return v
    return ""


def _clean_html(text: str) -> str:
    s = re.sub(r"<[^>]+>", " ", str(text or ""))
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s[:MAX_DESCRIPTION]


def _explicit(raw: str) -> bool:
    return str(raw or "").strip().lower() in ("yes", "true", "explicit", "1")


def _epoch(raw: str) -> float:
    s = str(raw or "").strip()
    if not s:
        return 0.0
    try:
        dt = email.utils.parsedate_to_datetime(s)
        return float(dt.timestamp()) if dt else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def parse_duration(raw: str) -> int:
    """`itunes:duration` → 秒。支持 `1234` / `12:34` / `1:02:03`；认不出返回 0。"""
    s = str(raw or "").strip()
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    parts = s.split(":")
    if not 1 <= len(parts) <= 3:
        return 0
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if any(n < 0 for n in nums):
        return 0
    sec = 0
    for n in nums:
        sec = sec * 60 + n
    return sec


def parse_feed(xml_text: str) -> "tuple[dict, list]":
    """RSS 2.0 → `(频道元信息, 单集列表)`。Atom / 非 RSS 一律 `ValueError`。"""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise ValueError(f"订阅不是合法的 XML：{e}") from None
    if _local(root.tag) != "rss":
        if _local(root.tag) == "feed":
            raise ValueError("暂不支持 Atom 格式的播客源（目前只解析 RSS 2.0）")
        raise ValueError("这不是一份 RSS 播客源（根元素不是 <rss>）")
    channel = _child(root, "channel")
    if channel is None:
        raise ValueError("RSS 里没有 <channel>")
    title = _text(channel, "title")
    if not title:
        raise ValueError("RSS 频道缺少标题")

    # 封面可能是 `<itunes:image href>` 或 RSS 的 `<image><url>`；两者同名（local name）。
    image = ""
    for c in _children(channel, "image"):
        if c.get("href"):
            image = str(c.get("href") or "").strip()
            break
    if not image:
        for c in _children(channel, "image"):
            u = _text(c, "url")
            if u:
                image = u
                break

    cats = []
    for c in _children(channel, "category"):
        txt = str(c.get("text") or "").strip() or "".join(c.itertext()).strip()
        if txt and txt not in cats:
            cats.append(txt)

    meta = {
        "title": title,
        "author": _text(channel, "author", "managingEditor", "creator"),
        "description": _clean_html(_text(channel, "summary", "description", "subtitle")),
        "artwork_url": image,
        "categories": cats,
        "explicit": _explicit(_text(channel, "explicit")),
    }

    episodes = []
    for item in _children(channel, "item"):
        enc = _child(item, "enclosure")
        audio_url = str((enc.get("url") if enc is not None else "") or "").strip()
        if not audio_url:
            continue                                   # 没有音频地址的单集没法播，不建条目
        guid = _text(item, "guid") or audio_url
        tr = _child(item, "transcript")
        episodes.append({
            "guid": guid,
            "title": _text(item, "title") or "未命名单集",
            "description": _clean_html(_text(item, "summary", "description", "subtitle")),
            "published_at": _epoch(_text(item, "pubDate", "published", "updated")),
            "duration_sec": parse_duration(_text(item, "duration")),
            "audio_url": audio_url,
            "audio_type": str((enc.get("type") if enc is not None else "") or ""),
            "episode_no": _int(_text(item, "episode")),
            "season_no": _int(_text(item, "season")),
            "explicit": _explicit(_text(item, "explicit")),
            "transcript_url": str((tr.get("url") if tr is not None else "") or "").strip(),
            "transcript_type": str((tr.get("type") if tr is not None else "") or "").strip(),
        })
    return meta, episodes


def _int(raw: str) -> int:
    try:
        return max(0, int(str(raw or "").strip()))
    except (TypeError, ValueError):
        return 0


def _apply(pid: str, feed_url: str, meta: dict, episodes: list) -> dict:
    now = time.time()
    db.update_podcast(pid,
                      title=meta["title"], author=meta["author"],
                      description=meta["description"], artwork_url=meta["artwork_url"],
                      categories=meta["categories"], explicit=1 if meta["explicit"] else 0,
                      last_fetched_at=now, last_attempt_at=now, last_ok_at=now,
                      last_error="", fail_count=0)
    added, updated = db.upsert_podcast_episodes(pid, episodes)
    auto_queued = _auto_download(pid)
    return {"podcast": db.get_podcast(pid), "added": added, "updated": updated,
            "total": len(episodes), "auto_queued": auto_queued}


def _record_failure(pid: str, exc: Exception) -> None:
    """失败的**落账**：只记最近尝试 / 原因 / 连续失败数，**不动**已抓到的单集。"""
    pod = db.get_podcast(pid) or {}
    db.update_podcast(pid, last_attempt_at=time.time(),
                      last_error=str(exc)[:500],
                      fail_count=int(pod.get("fail_count") or 0) + 1)


def subscribe(feed_url: str) -> dict:
    """订阅（或刷新已订阅的同一 feed）。**用户显式动作**才出网。"""
    url = str(feed_url or "").strip()
    existing = db.podcast_by_feed(url)
    try:
        meta, episodes = parse_feed(_fetch(url))
    except ValueError as e:
        if existing and not existing.get("deleted"):
            _record_failure(existing["id"], e)
        raise
    if existing:
        pid = existing["id"]
        if existing.get("deleted"):
            db.revive_podcast(pid)
    else:
        pod = db.create_podcast(
            url, title=meta["title"], author=meta["author"],
            description=meta["description"], artwork_url=meta["artwork_url"],
            categories=meta["categories"], explicit=meta["explicit"])
        pid = pod["id"]
    out = _apply(pid, url, meta, episodes)
    out["created"] = existing is None
    return out


def refresh(podcast_id: str) -> dict:
    """重新抓取已订阅的 feed（失败保留旧单集，只把失败落账）。"""
    pod = db.get_podcast(podcast_id)
    if not pod:
        raise LookupError("订阅不存在")
    try:
        meta, episodes = parse_feed(_fetch(pod["feed_url"]))
    except ValueError as e:
        _record_failure(str(pod["id"]), e)
        raise
    out = _apply(str(pod["id"]), pod["feed_url"], meta, episodes)
    out["created"] = False
    return out


def refresh_all() -> dict:
    """刷新全部订阅（逐条隔离：一条失败不影响其它）。"""
    ok = failed = 0
    items = []
    for p in db.list_podcasts():
        try:
            r = refresh(str(p["id"]))
            ok += 1
            items.append({"id": p["id"], "title": p["title"], "ok": True,
                          "added": r["added"], "updated": r["updated"]})
        except (LookupError, ValueError) as e:
            failed += 1
            items.append({"id": p["id"], "title": p["title"], "ok": False,
                          "error": str(e)})
    return {"ok": ok, "failed": failed, "items": items}


# ---------------- 单集下载（第 175 期）----------------
# 下载落 `CACHE_DIR/podcast-audio`（派生数据，可清理）；清理**移入回收站**而不是删。
# 串行 worker：一个进程一个队列，避免「批量下载 200 集」时开 200 个线程把站点打挂。
# 全部状态落在 `podcast_episodes.download_state`，接口与页面都从那里读，不另建内存状态。

DOWNLOAD_DIRNAME = "podcast-audio"
MAX_AUDIO_BYTES = 2 * 1024 * 1024 * 1024
_AUDIO_SUFFIXES = (".mp3", ".m4a", ".m4b", ".aac", ".ogg", ".opus", ".wav", ".flac")
_q: "queue.Queue[str]" = queue.Queue()
_worker_started = False
_worker_lock = threading.Lock()
#: 下载 worker 的线程句柄（第 242 期）：**daemon 线程句柄丢弃就收不干净** ——
#: 它会写库（`db.set_episode_download`），残留线程在用例级隔离下会攥着已关闭的连接
#: 干活（全量跑实测过 segfault）。范式同 `core/sync.py` 的 `_BG_THREADS`。
_worker_thread: "threading.Thread | None" = None


def _download_dir(podcast_id: str) -> pathlib.Path:
    d = config.CACHE_DIR / DOWNLOAD_DIRNAME / str(podcast_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _audio_suffix(url: str) -> str:
    suf = pathlib.PurePosixPath(urlparse(str(url or "")).path).suffix.lower()
    return suf if suf in _AUDIO_SUFFIXES else ".mp3"


def _download_bytes(url: str, tmp: pathlib.Path) -> int:
    """把音频写到 `tmp`，返回字节数。**单独抽出便于测试打桩**（离线用例不打真网）。"""
    size = 0
    with httpx.stream("GET", url, headers=_HEADERS, timeout=TIMEOUT,
                      follow_redirects=True) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(65536):
                size += len(chunk)
                if size > MAX_AUDIO_BYTES:
                    raise ValueError(f"音频超过上限（{MAX_AUDIO_BYTES // 1024 // 1024 // 1024} GB）")
                f.write(chunk)
    return size


def _download_one(eid: str) -> None:
    ep = db.get_podcast_episode(eid)
    if not ep or not ep.get("audio_url"):
        return
    d = _download_dir(ep["podcast_id"])
    dest = d / f"{str(eid)[:16]}{_audio_suffix(ep['audio_url'])}"
    tmp = dest.with_name(dest.name + ".part")
    try:
        size = _download_bytes(ep["audio_url"], tmp)
        os.replace(tmp, dest)                       # 原子落位：半成品永不以真名出现
        db.set_episode_download(eid, "downloaded", local_path=str(dest), size=size)
    except Exception as e:                          # noqa: BLE001 —— 逐条隔离，状态如实落库
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        db.set_episode_download(eid, "failed", error=f"{type(e).__name__}: {e}")


def _worker() -> None:
    while True:
        eid = _q.get()
        try:
            _download_one(eid)
        finally:
            _q.task_done()


def _ensure_worker() -> None:
    global _worker_started, _worker_thread
    with _worker_lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker, name="podcast-download", daemon=True)
        _worker_thread = t
        t.start()
        _worker_started = True


def wait_pending(timeout: float = 10.0) -> int:
    """等下载队列**排空** → 返回仍未干完的数量（``0`` = 收干净了）。

    与 `core/sync.py` / `core/watcher.py` / `core/catalog.py` 同一契约（第 170 期统一）：
    调用点在测试的收尾里（`tests/conftest.py::_quiesce_background`，**必须在
    `db.close()` 之前**）—— 这个 worker 会写库，晚一步动手就会在已关闭的连接上写。

    ⚠️ 判据是「**队列排空**」而不是「线程结束」：这个 worker 是 `while True` 的**常驻**
    线程（设计上就阻塞在 `_q.get()` 等下一个任务），它**永远不会结束** ⇒ 按「线程活着」
    判会永远返回非 0，收尾就会硬失败。`queue.join()` 才是对的语义（每个任务在
    `finally` 里 `task_done()` ⇒ 队列空 ⇒ join 返回）。
    """
    deadline = time.time() + max(0.0, timeout)
    while True:
        if _q.unfinished_tasks == 0:
            return 0
        if time.time() >= deadline:
            return int(_q.unfinished_tasks)
        time.sleep(0.05)


def _stale_download(eid: str, ep: dict) -> bool:
    """这一集的 ``downloading`` 是不是**残留**（进程被 kill / 重启留下的）。

    判据：**既没有下载中的临时件、也没有已完成的副本** ⇒ 此刻没人在下它。
    （下载中的临时件是 ``<最终名>.part``，见 `_download_one`。）

    ⚠️ 为什么需要它：``downloading`` 状态**只被设置、从不被清理**（第 242 期审计发现）——
    进程被 kill / 容器重启后，那一集永远卡在「下载中」，而 `enqueue_download` 见到
    `downloading` 会**直接跳过** ⇒ 那一集**再也下不了**（用户只能删了重订）。
    """
    if str(ep.get("download_state") or "") != "downloading":
        return False
    lp = str(ep.get("local_path") or "")
    if lp and pathlib.Path(lp).is_file():
        return False                        # 已有成品 ⇒ 不是残留
    try:
        d = _download_dir(str(ep.get("podcast_id") or ""))
        for f in d.glob("*.part"):
            return False                    # 有临时件 ⇒ 真的在下（或刚被杀）
    except OSError:
        return False
    return True


def reset_stale_downloads() -> int:
    """把残留的 ``downloading`` 复位成「未下载」→ 返回复位的条数。

    惰性调用点：`enqueue_download`（用户再点一次下载时）与 `list_local`（列本地副本时）。
    **不主动扫全表** —— 那是后台任务才该做的事。
    """
    n = 0
    for ep in db.list_all_podcast_episodes():
        if _stale_download(str(ep.get("id") or ""), ep):
            db.set_episode_download(str(ep.get("id") or ""), "", error="")
            n += 1
    return n


def enqueue_download(eid: str) -> dict:
    """把一集加入下载队列（幂等：已下载 / 正在下载直接返回当前状态）。"""
    ep = db.get_podcast_episode(eid)
    if not ep:
        raise LookupError("单集不存在")
    # 第 242 期：先把**残留**的 `downloading` 复位（进程被杀后它会卡住「下载中」，
    # 而下面这行见到 `downloading` 就跳过 ⇒ 那一集再也下不了）。
    if _stale_download(eid, ep):
        db.set_episode_download(eid, "", error="")
        ep = db.get_podcast_episode(eid) or ep
    if ep["download_state"] in ("downloading", "downloaded"):
        return {"ok": True, "state": ep["download_state"]}
    if not ep.get("audio_url"):
        raise ValueError("这一集没有音频地址")
    db.set_episode_download(eid, "downloading")
    _ensure_worker()
    _q.put(str(eid))
    return {"ok": True, "state": "downloading"}


def download_all(podcast_id: str) -> dict:
    """把该订阅下**还没下载**的单集全部排队。"""
    if not db.get_podcast(podcast_id):
        raise LookupError("订阅不存在")
    queued = 0
    for ep in db.list_podcast_episodes(podcast_id, limit=2000):
        if ep["download_state"] in ("downloading", "downloaded"):
            continue
        if not ep.get("audio_url"):
            continue
        db.set_episode_download(ep["id"], "downloading")
        _ensure_worker()
        _q.put(ep["id"])
        queued += 1
    return {"ok": True, "queued": queued}


def clean_download(eid: str) -> dict:
    """清理本地副本：**移入回收站**（从不直接删），并清掉下载状态。"""
    ep = db.get_podcast_episode(eid)
    if not ep:
        raise LookupError("单集不存在")
    local = str(ep.get("local_path") or "")
    moved = ""
    if local:
        p = pathlib.Path(local)
        if p.is_file():
            moved = str(fileops.recycle_path(p, reason="清理播客下载"))
    db.clear_episode_download(eid)
    return {"ok": True, "moved_to": moved}


def local_audio_path(eid: str) -> "pathlib.Path | None":
    ep = db.get_podcast_episode(eid)
    if not ep or ep.get("download_state") != "downloaded":
        return None
    p = pathlib.Path(str(ep.get("local_path") or ""))
    return p if p.is_file() else None


# ---------------- 播放进度（第 176 期）----------------
# 位置只增不减（拖回去重听不改小），听满 95% 记 played_at；手动「标未播」才会清零。

PLAYED_THRESHOLD = 0.95


# ---------------- 官方转录（第 182 期）----------------
# 只读 feed 里 `<podcast:transcript>` 指向的文件（SRT / VTT / JSON / 纯文本），
# **不做 ASR**：没有转录地址就如实说没有，不假装能转写。

MAX_TRANSCRIPT_CHARS = 200_000

_TS_LINE = re.compile(
    r"^\s*(?:\d+\s*$|\d{1,2}:\d{2}(?::\d{2})?[.,]\d{3}\s*-->.*|WEBVTT.*)$", re.I)


def _plain_transcript(raw: str, kind: str) -> str:
    """SRT / VTT → 纯文本行；JSON（podcast 转录规范）取 segments 的正文。"""
    text = str(raw or "").replace("\ufeff", "")
    if "json" in (kind or "").lower() or text.lstrip().startswith("{"):
        try:
            data = json.loads(text)
        except Exception:                         # noqa: BLE001 —— 不是 JSON 就按文本走
            data = None
        if isinstance(data, dict):
            segs = data.get("segments") or data.get("transcript") or []
            if isinstance(segs, list):
                parts = []
                for s in segs:
                    if isinstance(s, dict):
                        v = s.get("text") or s.get("body") or ""
                        if v:
                            parts.append(str(v).strip())
                if parts:
                    text = "\n".join(parts)
    lines = [ln.strip() for ln in text.splitlines()]
    out = [ln for ln in lines if ln and not _TS_LINE.match(ln)]
    return "\n".join(out)[:MAX_TRANSCRIPT_CHARS]


def transcript(eid: str) -> dict:
    """取单集官方转录：有缓存直接用；没有就按 feed 给的地址抓一次并缓存。"""
    info = db.get_episode_transcript(eid)
    if info is None:
        raise LookupError("单集不存在")
    if info["text"]:
        return {"available": True, "kind": info["type"], "text": info["text"]}
    if not info["url"]:
        return {"available": False, "kind": "", "text": "",
                "reason": "该单集没有官方转录（本项目不做 ASR 转写）"}
    raw = _fetch(info["url"])
    text = _plain_transcript(raw, info["type"])
    if not text:
        return {"available": False, "kind": info["type"], "text": "",
                "reason": "转录文件里没有可显示的文本"}
    db.save_episode_transcript(eid, text)
    return {"available": True, "kind": info["type"], "text": text}


# ---------------- 自动策略（第 181 期）----------------
# 自动下载「最新 N 集」在**刷新之后**执行（订阅 / 刷新是用户显式动作）；
# 听完清理只在 `played_at` 刚被记下时触发，且**只清本地副本**（移入回收站）。

MAX_AUTO_KEEP = 50


def auto_settings(podcast_id: str) -> dict:
    pod = db.get_podcast(podcast_id)
    if not pod:
        raise LookupError("订阅不存在")
    return {k: pod[k] for k in ("auto_download", "auto_keep", "auto_clean")}


def set_auto(podcast_id: str, *, auto_download=None, auto_keep=None, auto_clean=None) -> dict:
    """设置自动策略：`auto_keep` 0..50（0 = 关闭自动下载）。"""
    pod = db.get_podcast(podcast_id)
    if not pod:
        raise LookupError("订阅不存在")
    fields = {}
    if auto_download is not None:
        fields["auto_download"] = 1 if auto_download else 0
    if auto_clean is not None:
        fields["auto_clean"] = 1 if auto_clean else 0
    if auto_keep is not None:
        try:
            keep = int(auto_keep)
        except (TypeError, ValueError):
            raise ValueError("auto_keep 必须是整数") from None
        if not 0 <= keep <= MAX_AUTO_KEEP:
            raise ValueError(f"auto_keep 必须在 0–{MAX_AUTO_KEEP} 之间")
        fields["auto_keep"] = keep
        fields["auto_download"] = 1 if keep > 0 else 0
    db.update_podcast(podcast_id, **fields)
    return auto_settings(podcast_id)


def _auto_download(podcast_id: str) -> int:
    """按策略把「最新 N 集」里还没下载的排队；返回新排队数。"""
    pod = db.get_podcast(podcast_id)
    if not pod or not pod["auto_download"] or pod["auto_keep"] <= 0:
        return 0
    queued = 0
    for ep in db.list_podcast_episodes(podcast_id, limit=pod["auto_keep"]):
        if ep["download_state"] in ("downloading", "downloaded"):
            continue
        if not ep.get("audio_url"):
            continue
        db.set_episode_download(ep["id"], "downloading")
        _ensure_worker()
        _q.put(ep["id"])
        queued += 1
    return queued


def _maybe_clean(eid: str) -> None:
    """听完清理：仅当该订阅开了 auto_clean 且本地有副本时，把副本移入回收站。"""
    ep = db.get_podcast_episode(eid)
    if not ep or not ep.get("played_at"):
        return
    pod = db.get_podcast(ep["podcast_id"])
    if pod and pod["auto_clean"] and ep["download_state"] == "downloaded":
        clean_download(eid)


def save_progress(eid: str, position: float, duration: float = 0) -> dict:
    """写入播放位置；`duration > 0` 且听满阈值时同时记 played_at（第一次）。"""
    if not db.get_podcast_episode(eid):
        raise LookupError("单集不存在")
    ep = db.set_episode_progress(eid, float(position or 0), float(duration or 0))
    _maybe_clean(eid)
    return ep


def mark_played(eid: str, played: bool = True) -> dict:
    if not db.get_podcast_episode(eid):
        raise LookupError("单集不存在")
    ep = db.mark_episode_played(eid, bool(played))
    if played:
        _maybe_clean(eid)
    return ep


# ---------------- OPML（导入 / 导出，第 174 期）----------------

MAX_OPML_BYTES = 2 * 1024 * 1024
MAX_OPML_FEEDS = 500


def opml_export() -> str:
    """全部订阅 → OPML 2.0（播客客户端通用的订阅清单）。"""
    from xml.sax.saxutils import quoteattr

    rows = []
    for p in db.list_podcasts():
        title = p["title"] or p["feed_url"]
        rows.append(
            '    <outline type="rss" text={t} title={t} xmlUrl={u}/>'.format(
                t=quoteattr(title), u=quoteattr(p["feed_url"])))
    nl = chr(10)
    return nl.join([
        '<?xml version="1.0" encoding="utf-8"?>',
        '<opml version="2.0">',
        '  <head><title>NovelForge 播客订阅</title></head>',
        '  <body>',
        *rows,
        '  </body>',
        '</opml>',
        '',
    ])


def opml_import(text: str) -> dict:
    """导入 OPML：逐条订阅，**一条失败不影响其它**，逐条回报结果。

    只认带 `xmlUrl` 的 outline（目录型 outline 只是分组，不订阅）。
    """
    raw = str(text or "")
    if len(raw.encode("utf-8", "replace")) > MAX_OPML_BYTES:
        raise ValueError("OPML 文件过大（上限 2 MB）")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise ValueError(f"OPML 不是合法的 XML：{e}") from None
    urls = []
    seen = set()

    def walk(el) -> None:
        for ch in list(el):
            u = str(ch.get("xmlUrl") or "").strip()
            if u and u not in seen:
                seen.add(u)
                urls.append(u)
            walk(ch)

    walk(root)
    if len(urls) > MAX_OPML_FEEDS:
        raise ValueError(f"一次最多导入 {MAX_OPML_FEEDS} 个订阅")
    added = refreshed = 0
    failed = []
    for u in urls:
        try:
            r = subscribe(u)
            if r.get("created"):
                added += 1
            else:
                refreshed += 1
        except ValueError as e:
            failed.append({"feed_url": u, "error": str(e)})
    return {"total": len(urls), "added": added, "refreshed": refreshed,
            "failed": failed}
