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
import re
import time
import xml.etree.ElementTree as ET

import httpx

from . import db

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
    db.update_podcast(pid,
                      title=meta["title"], author=meta["author"],
                      description=meta["description"], artwork_url=meta["artwork_url"],
                      categories=meta["categories"], explicit=1 if meta["explicit"] else 0,
                      last_fetched_at=time.time())
    added, updated = db.upsert_podcast_episodes(pid, episodes)
    return {"podcast": db.get_podcast(pid), "added": added, "updated": updated,
            "total": len(episodes)}


def subscribe(feed_url: str) -> dict:
    """订阅（或刷新已订阅的同一 feed）。**用户显式动作**才出网。"""
    url = str(feed_url or "").strip()
    meta, episodes = parse_feed(_fetch(url))
    existing = db.podcast_by_feed(url)
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
    """重新抓取已订阅的 feed（失败保留旧单集，不清空）。"""
    pod = db.get_podcast(podcast_id)
    if not pod:
        raise LookupError("订阅不存在")
    meta, episodes = parse_feed(_fetch(pod["feed_url"]))
    out = _apply(str(pod["id"]), pod["feed_url"], meta, episodes)
    out["created"] = False
    return out
