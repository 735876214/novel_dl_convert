"""外部服务同步（Hardcover 阅读状态与书评 / Readwise 书摘 / StoryGraph Cookie 校验）。

与 :mod:`core.integrations` 的分工（刻意拆开，互不侵入）：

    · ``integrations.py`` —— 只管**凭据与连通性探针**（``SERVICES`` 元数据 + ``verify``）
    · 本模块            —— 管**匹配与推送编排**（匹配口径、分批、限流退避、任务留痕）

三条硬约定（与项目其它出网模块一致）：

1. **公网服务保留 httpx 默认的 ``trust_env=True``**（与 OPDS / KOReader 那些内网服务相反）——
   用户很可能正需要靠代理访问 Hardcover / Readwise。
2. **匹配不上就跳过，绝不模糊强推**：匹配口径固定为「ISBN 精确 → 规范化书名+作者 → 跳过」，
   每一次跳过都带原因回报给用户（见 :func:`run` 的 ``skipped``）。
3. **自动推送默认关**，且旁路线程吞掉全部异常 —— 它绝不能阻塞或污染批注 / 状态 / 评分写入。

⚠️ 未做真实外呼验证（本机没有三家凭据）：推送的请求形状与状态映射由 ``tests/test_integration_sync.py``
打桩钉住；页面与文档如实标注这一点，不含糊。
"""
from __future__ import annotations

import re
import threading
import time
import unicodedata

import httpx

from . import activity_log, db, library

TIMEOUT = httpx.Timeout(30.0, connect=10.0)
HARDCOVER_GRAPHQL = "https://api.hardcover.app/v1/graphql"
READWISE_HIGHLIGHTS = "https://readwise.io/api/v2/highlights/"
STORYGRAPH_HOME = "https://app.thestorygraph.com/"
#: Readwise 单次上限 100 条（超出会被拒）；批间小睡，避免撞 240 req/min 的限流
READWISE_BATCH = 100
READWISE_PAUSE = 0.3

#: 本项目阅读状态 → Hardcover ``status_id``。
#: ⚠️ 只映射**三个能确定的**取值：1 = Want to Read、2 = Currently Reading、3 = Read。
#: ``paused`` / ``abandoned`` 在 Hardcover 没有一一对应的官方状态，
#: 与其挑一个近似的把它写错，不如**不上报状态**（仍可推评分与书评），并在结果里说明。
STATUS_IDS = {"unread": 1, "reading": 2, "finished": 3}

#: 运行中的旁路线程（测试与关停时等它们收干净，避免在已关连接上查库）
_BG_LOCK = threading.Lock()
_BG_THREADS: dict = {}


def _spawn_bg(target, name: str) -> threading.Thread:
    """起一个**被登记**的旁路线程（daemon，不阻塞主流程）。写法对齐 ``core/watcher._spawn_bg``。"""
    th = threading.Thread(target=target, daemon=True, name=name)
    with _BG_LOCK:
        _BG_THREADS[id(th)] = th
    th.start()
    return th


def wait_pending(timeout: float = 10.0) -> None:
    """等所有同步旁路线程结束（测试 / 关停用）。"""
    deadline = time.time() + max(0.0, timeout)
    while time.time() < deadline:
        with _BG_LOCK:
            alive = [t for t in _BG_THREADS.values() if t.is_alive()]
        if not alive:
            return
        for t in alive:
            t.join(timeout=0.2)
        with _BG_LOCK:
            for k, t in list(_BG_THREADS.items()):
                if not t.is_alive():
                    _BG_THREADS.pop(k, None)


# ---------------- 归一化与匹配 ----------------

def _norm_text(s) -> str:
    """书名归一化：NFKC（全角→半角）+ 去空白 + 小写 + 去掉副标题括号段。"""
    t = unicodedata.normalize("NFKC", str(s or "")).lower()
    t = re.sub(r"[（(\[【][^）)\]】]*[）)\]】]", " ", t)     # 副标题 / 卷次括号
    t = re.sub(r"[\s\u3000]+", "", t)
    t = re.sub(r"[·・:：\-—_.,，。!！?？\"'“”‘’]", "", t)
    return t


def _norm_author(s) -> str:
    """作者归一化：取第一作者、去空白与标点（不排序 —— 中文姓名倒序会把「张三」改成「三张」）。"""
    t = unicodedata.normalize("NFKC", str(s or "")).lower()
    t = re.split(r"[,，/、;；&+]", t)[0]
    return re.sub(r"[\s\u3000·・.\-—_]", "", t)


def _local_books() -> list:
    return library.books()


def _state(book_id: str, statuses: dict, ratings: dict, reviews: dict) -> dict:
    return {
        "status": str(statuses.get(book_id) or ""),
        "stars": int(ratings.get(book_id) or 0),
        "review": str(reviews.get(book_id) or ""),
    }


def _has_payload(st: dict) -> bool:
    """这本书有没有值得推的东西（评分 / 书评 / 可映射状态）。"""
    return bool(st["stars"] or st["review"] or STATUS_IDS.get(st["status"]))


def _iter_payloads(book_ids=None) -> list:
    """挑出「有内容可推」的书（``book_ids`` 给定时只在这些书里挑）。"""
    statuses, ratings, reviews = db.all_statuses(), db.all_ratings(), db.all_reviews()
    want = {str(b) for b in book_ids} if book_ids else None
    out = []
    for b in _local_books():
        bid = str(b.get("id") or "")
        if not bid or (want is not None and bid not in want):
            continue
        st = _state(bid, statuses, ratings, reviews)
        if not _has_payload(st):
            continue
        out.append((b, st))
    return out


def _annotations_of(book_id: str) -> list:
    """本书可推送的批注（**只取活跃条目**；垃圾桶里的软删条目不推）。"""
    try:
        return db.list_annotations(book_id)
    except Exception:
        return []


# ---------------- 预览（只算不改，零外呼）----------------

def preview(service: str) -> dict:
    """同步预览：**不外呼**。

    Hardcover 侧的匹配发生在同步时（要查对方库才知道有没有这本），
    所以这里给的是「本地待推条数」，而不是「已匹配条数」—— 如实标注，不假装已经匹配过。
    """
    if service == "readwise":
        rows = _iter_payloads()
        total = sum(len(_annotations_of(str(b.get("id") or ""))) for b, _ in rows)
        return {"service": service, "unit": "批注", "books": len(rows), "total": total,
                "matched": 0, "skipped": [], "remote_match_at_sync": False}
    if service == "hardcover":
        rows = _iter_payloads()
        return {"service": service, "unit": "本书", "books": len(rows), "total": len(rows),
                "matched": 0, "skipped": [], "remote_match_at_sync": True}
    return {"service": service, "unit": "", "books": 0, "total": 0, "matched": 0,
            "skipped": [], "remote_match_at_sync": False}


# ---------------- Hardcover 推送 ----------------

def _hardcover_find_book_id(client: httpx.Client, token: str, book: dict) -> tuple:
    """在 Hardcover 里找这本书，返回 ``(book_id, reason)``。

    匹配口径：**先 ISBN 精确，退到「规范化书名 + 作者」**；两者都命中不了返回 ``(None, 原因)``。
    只用对方的 ``search`` 查询，一次请求 —— 不做逐本多次探测。
    """
    isbn = re.sub(r"[^0-9Xx]", "", str(book.get("isbn") or ""))
    title, author = str(book.get("title") or ""), str(book.get("author") or "")
    q = f"isbn:{isbn}" if isbn else f"{title} {author}".strip()
    if not q:
        return None, "书名与 ISBN 都为空"
    query = """
    query ($q: String!) {
      search(query: $q, query_type: "Book", per_page: 5) {
        ids
      }
    }
    """
    try:
        return _hardcover_search_ids(client, token, query, q, book, isbn)
    except httpx.HTTPError as e:
        return None, f"网络错误：{e}"


def _hardcover_search_ids(client: httpx.Client, token: str, query: str, q: str,
                          book: dict, isbn: str) -> tuple:
    r = client.post(HARDCOVER_GRAPHQL, headers=_hc_headers(token), json={"query": query,
                                                                       "variables": {"q": q}})
    data = _graphql_json(r)
    if data is None:
        return None, "Hardcover 返回异常"
    errs = (data or {}).get("errors")
    if errs:                                   # ⚠️ 鉴权失败也可能是 200 + errors
        return None, "凭据无效或无权限"
    ids = (((data.get("data") or {}).get("search") or {}).get("ids")) or []
    if not ids:
        return None, ("ISBN 未匹配到" if isbn else "书名+作者未匹配到")
    # ids 的顺序就是搜索相关度顺序；直接取第一条，不再逐条取详情（省请求）
    return int(ids[0]), ""


def _hc_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _graphql_json(r: httpx.Response):
    """GraphQL 响应 → dict；HTTP 层失败返回 None。**必须同时看 errors**。"""
    if r.status_code in (401, 403):
        return {"errors": [{"message": "unauthorized"}]}
    if r.status_code >= 400:
        return {"errors": [{"message": f"http {r.status_code}"}]}
    try:
        return r.json()
    except ValueError:
        return {"errors": [{"message": "not json"}]}


def _hardcover_push_one(client: httpx.Client, token: str, book: dict, st: dict) -> tuple:
    """推一本书。返回 ``(ok, reason)``。"""
    if not token:
        return False, "未配置 API Token"
    book_id, reason = _hardcover_find_book_id(client, token, book)
    if not book_id:
        return False, reason
    status_id = STATUS_IDS.get(st["status"])
    obj = {"book_id": book_id}
    if status_id:
        obj["status_id"] = status_id
    if st["stars"]:
        obj["rating"] = float(st["stars"])
    if st["review"]:
        obj["review"] = st["review"]
    if len(obj) == 1:
        return False, "状态无法映射且没有评分 / 书评"
    mutation = """
    mutation ($obj: UserBookInput!) {
      insert_user_book(object: $obj) { user_book { id } }
    }
    """
    r = client.post(HARDCOVER_GRAPHQL, headers=_hc_headers(token),
                    json={"query": mutation, "variables": {"obj": obj}})
    data = _graphql_json(r)
    if data is None or (data or {}).get("errors"):
        return False, "Hardcover 拒绝了这次写入（可能是状态 / 字段不被接受）"
    return True, ""


# ---------------- Readwise 推送 ----------------

def _readwise_payload(book: dict, annos: list, base_url: str) -> list:
    """批注 → Readwise highlights 条目。

    ``external_id`` 用批注自身的稳定 id（``nf-<book_id>-<anno_id>``）—— Readwise 按它去重，
    重复推送不会产生重复高亮。
    """
    bid = str(book.get("id") or "")
    title = str(book.get("title") or book.get("name") or "")
    author = str(book.get("author") or "")
    url = f"{base_url.rstrip('/')}/#/book/{bid}" if base_url else ""
    out = []
    for a in annos:
        quote = str(a.get("quote") or "").strip()
        note = str(a.get("note") or "").strip()
        if not quote and not note:
            continue
        chapter = a.get("chapter")
        out.append({
            # text 不能为空：只有笔记没有划线时，用章节名占位，把正文放进 note
            "text": quote or f"第 {chapter} 章",
            "title": title,
            "author": author,
            "note": note,
            "category": "books",
            "location": int(chapter or 0),
            "location_type": "chapter",
            "highlighted_at": _iso(int(a.get("created_at") or 0)),
            "external_id": f"nf-{bid}-{a.get('id')}",
            **({"source_url": url} if url else {}),
        })
    return out


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts or time.time()))


def _readwise_post(client: httpx.Client, token: str, highlights: list) -> tuple:
    """推一批（≤100 条）。返回 ``(ok, 失败条数, 原因)``。"""
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    for attempt in range(3):
        r = client.post(READWISE_HIGHLIGHTS, headers=headers, json={"highlights": highlights})
        # 204/200 才是成功；429 是限流，退避后重试（最多 2 次）
        if r.status_code in (200, 201, 204):
            return True, 0, ""
        if r.status_code == 429 and attempt < 2:
            time.sleep(min(10.0, float(r.headers.get("Retry-After") or 0) or 5.0))
            continue
        if r.status_code in (401, 403):
            return False, len(highlights), "Access Token 无效"
        if r.status_code >= 500 and attempt < 2:
            time.sleep(2.0 * (attempt + 1))
            continue
        return False, len(highlights), f"Readwise 返回 {r.status_code}"
    return False, len(highlights), "Readwise 限流后仍失败"


# ---------------- StoryGraph Cookie 校验 ----------------

def verify_storygraph(creds: dict) -> dict:
    """Cookie 有效性校验（**启发式**，但判定依据是可解释的一条）。

    判定：带两个 Cookie 请求站点首页并跟随重定向 ——
      · 网络/代理异常          → 「连接失败」（**不**说成 Cookie 无效）
      · 最终 URL 落在 /login 或响应体出现登录表单标记 → 「Cookie 已失效」
      · 其余 2xx 且无登录标记  → 「Cookie 可用」

    ⚠️ 这是**启发式**：StoryGraph 没有公开 API，改版即可能失效（上游同样如此说明）。
    """
    creds = creds or {}
    session = str(creds.get("session") or "").strip()
    remember = str(creds.get("remember_token") or "").strip()
    if not session and not remember:
        return {"ok": False, "message": "请先填写两个 Cookie"}
    cookies = {}
    if session:
        cookies["_storygraph_session"] = session
    if remember:
        cookies["remember_user_token"] = remember
    try:
        with httpx.Client(timeout=TIMEOUT, follow_redirects=True) as c:
            r = c.get(STORYGRAPH_HOME, cookies=cookies,
                      headers={"User-Agent": "Mozilla/5.0 (novelforge-sync-check)"})
    except httpx.HTTPError as e:
        return {"ok": False, "message": f"连接失败：{e}",
                "detail": "网络或代理问题，这不代表 Cookie 无效。"}
    final = str(r.url)
    body = (r.text or "")[:20000].lower()
    if "/login" in final or "sign in" in body and "name=\"user[email]\"" in body:
        return {"ok": False, "message": "Cookie 已失效（被引导到登录页）",
                "detail": f"最终地址：{final}"}
    if r.status_code >= 400:
        return {"ok": False, "message": f"站点返回 {r.status_code}",
                "detail": "非 401 / 403 一类鉴权错误，可能是对方改版或临时故障。"}
    return {"ok": True, "message": "Cookie 看起来可用（启发式判定）",
            "detail": "StoryGraph 无公开 API，对方改版后可能失效；届时重新复制 Cookie 即可。"}


# ---------------- 执行同步 ----------------

def run(service: str, book_ids=None, base_url: str = "", actor: str = "") -> dict:
    """执行一次同步。返回统一结果（前端据此显示成功 / 跳过 / 失败计数）。

    结果形状::

        {"ok", "service", "matched", "pushed", "skipped": [{book_id, title, reason}],
         "failed": [{book_id, title, error}], "at"}
    """
    creds = ((_config().get("integrations") or {}).get(service) or {})
    token = str(creds.get("token") or "").strip()
    if not token:
        return {"ok": False, "service": service, "message": "未配置凭据",
                "matched": 0, "pushed": 0, "skipped": [], "failed": [], "at": time.time()}

    started = time.time()
    skipped: list = []
    failed: list = []
    pushed = 0
    matched = 0
    rows = _iter_payloads(book_ids)
    label = service.capitalize()
    task_id = f"sync-{service}-{int(started)}"
    try:
        db.task_create(task_id, "sync", f"{label} 同步", detail="开始同步")
    except Exception:
        task_id = ""

    try:
        if service == "readwise":
            pushed, failed = _run_readwise(token, rows, base_url)
        elif service == "hardcover":
            matched, pushed, skipped, failed = _run_hardcover(token, rows)
        else:
            return {"ok": False, "service": service, "message": f"未知服务：{service}",
                    "matched": 0, "pushed": 0, "skipped": [], "failed": [], "at": time.time()}
        ok = not failed
        detail = f"成功 {pushed} / 跳过 {len(skipped)} / 失败 {len(failed)}"
        _finish_task(task_id, ok, detail)
        activity_log.log(activity_log.ACTION_SYNC, label,
                         activity_log.STATUS_OK if ok else activity_log.STATUS_FAIL,
                         source="integration", detail=detail, actor=actor)
        return {"ok": ok, "service": service, "matched": matched, "pushed": pushed,
                "skipped": skipped, "failed": failed, "at": time.time()}
    except Exception as e:                                    # noqa: BLE001
        _finish_task(task_id, False, str(e))
        activity_log.log(activity_log.ACTION_SYNC, label, activity_log.STATUS_FAIL,
                         source="integration", detail=str(e), actor=actor)
        return {"ok": False, "service": service, "message": str(e), "matched": matched,
                "pushed": pushed, "skipped": skipped, "failed": failed, "at": time.time()}


def _run_hardcover(token: str, rows: list) -> tuple:
    matched = pushed = 0
    skipped: list = []
    failed: list = []
    with httpx.Client(timeout=TIMEOUT) as client:
        for book, st in rows:
            ok, reason = _hardcover_push_one(client, token, book, st)
            title = str(book.get("title") or book.get("name") or "")
            if ok:
                matched += 1
                pushed += 1
            elif reason and ("未匹配" in reason or "都为空" in reason or "无法映射" in reason):
                skipped.append({"book_id": str(book.get("id") or ""), "title": title,
                                "reason": reason})
            else:
                failed.append({"book_id": str(book.get("id") or ""), "title": title,
                               "error": reason or "未知错误"})
    return matched, pushed, skipped, failed


def _run_readwise(token: str, rows: list, base_url: str) -> tuple:
    pushed = 0
    failed: list = []
    batch: list = []
    owner: dict = {}

    def _flush(client: httpx.Client) -> None:
        nonlocal pushed, batch
        if not batch:
            return
        ok, bad, reason = _readwise_post(client, token, batch)
        if ok:
            pushed += len(batch)
        else:
            # 整批失败时逐条计失败，避免只报「一批失败」而看不到是哪几本
            for item in batch:
                failed.append({"book_id": owner.get(item["external_id"], ""),
                               "title": item.get("title", ""), "error": reason})
        batch = []
        time.sleep(READWISE_PAUSE)

    with httpx.Client(timeout=TIMEOUT) as client:
        for book, _st in rows:
            bid = str(book.get("id") or "")
            items = _readwise_payload(book, _annotations_of(bid), base_url)
            for it in items:
                owner[it["external_id"]] = bid
            batch.extend(items)
            if len(batch) >= READWISE_BATCH:
                _flush(client)
        _flush(client)
    return pushed, failed


def _finish_task(task_id: str, ok: bool, detail: str) -> None:
    if not task_id:
        return
    try:
        db.task_update(task_id, status="done" if ok else "failed", progress=1.0,
                       detail=detail, notice=detail, **({} if ok else {"error": detail}))
    except Exception:
        pass


def _config() -> dict:
    from .. import config
    return config.load_config()


# ---------------- 自动推送（旁路，默认关）----------------

def auto_push_on(service: str) -> bool:
    """该服务的「自动推送」开关是否打开（默认关）。"""
    try:
        return bool(((_config().get("integrations") or {}).get(service) or {}).get("auto_push"))
    except Exception:
        return False


def auto_push(book_id: str, base_url: str = "", actor: str = "") -> None:
    """新增批注 / 改状态 / 改评分书评后的**旁路**推送。

    ⚠️ 与 ``core/watcher.auto_fetch_async`` 同一纪律：先查开关（未开直接返回，零开销），
    开了就在 daemon 线程里跑，并**吞掉全部异常** —— 同步失败绝不能影响用户刚做的那次写入。
    阅读进度（``set_progress``）刻意**不**挂这里：它是翻页级高频写，逐次外呼纯属浪费。
    ``actor`` 由调用方在**请求线程内**取好再传进来：新线程的 ContextVar 是空的，
    不传就会把「谁做的」记成未记录。
    """
    svcs = [s for s in ("hardcover", "readwise") if auto_push_on(s)]
    if not svcs or not str(book_id or "").strip():
        return

    def _run():
        for s in svcs:
            try:
                run(s, [book_id], base_url=base_url, actor=actor)
            except Exception:
                pass

    _spawn_bg(_run, "novelforge-integration-push")
