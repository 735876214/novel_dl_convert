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
import os
import pathlib
import queue
import re
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlparse

import httpx

from .. import config
from . import db, fileops

TIMEOUT = 20.0
MAX_BYTES = 8 * 1024 * 1024
MAX_DESCRIPTION = 6000

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
    return {"podcast": db.get_podcast(pid), "added": added, "updated": updated,
            "total": len(episodes)}


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
    global _worker_started
    with _worker_lock:
        if _worker_started:
            return
        threading.Thread(target=_worker, name="podcast-download", daemon=True).start()
        _worker_started = True


def enqueue_download(eid: str) -> dict:
    """把一集加入下载队列（幂等：已下载 / 正在下载直接返回当前状态）。"""
    ep = db.get_podcast_episode(eid)
    if not ep:
        raise LookupError("单集不存在")
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


def save_progress(eid: str, position: float, duration: float = 0) -> dict:
    """写入播放位置；`duration > 0` 且听满阈值时同时记 played_at（第一次）。"""
    if not db.get_podcast_episode(eid):
        raise LookupError("单集不存在")
    return db.set_episode_progress(eid, float(position or 0), float(duration or 0))


def mark_played(eid: str, played: bool = True) -> dict:
    if not db.get_podcast_episode(eid):
        raise LookupError("单集不存在")
    return db.mark_episode_played(eid, bool(played))


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
