"""**鸿蒙客户端契约**：把「一个外部客户端读得懂这些接口」钉成用例。

## 为什么要有这份测试

鸿蒙端（`clients/harmony/`，ArkTS + ArkUI 原生，侧载安装）是**纯瘦客户端**：
端内不建库、不落章节、不存进度，**唯一真值源全在 NAS**。它只依赖下面这八组接口：

| 组 | 端点 | 客户端拿它干什么 |
|---|---|---|
| 登录 | `POST /api/auth/login` | 换一个能直接存 30 天的无状态令牌 |
| 书架 | `GET /api/books` | 分页列表 + 服务端已算好的进度 / 批注数 / 状态 |
| 详情 | `GET /api/books/{bid}` | 简介 + 章节目录（`index` 就是章节接口的入参） |
| 正文 | `GET /api/books/{bid}/chapter/{index}` | 已净化的 HTML + **真实** `total` |
| 进度 | `GET/PUT /api/books/{bid}/progress` | 跨端续读的唯一读点 / 写点 |
| 批注 | `GET/POST /api/books/{bid}/annotations` | 高亮与笔记 |
| 时长 | `POST /api/books/{bid}/session` | 30 秒心跳（`session_uid` upsert 一段一行） |
| 偏好 | `GET/PUT /api/prefs/devices/{did}` | 端上阅读偏好，服务端存档 |

这些接口**本来就是存在的**，本文件不测业务正确性（那是各模块自己的用例的事），
只钉一件事：**字段名与形状不许在无人察觉的情况下改**。

## 判据怎么定的（三条，别混用）

1. **服务端自己组装的响应**（登录 / 书架分页壳 / 章节 / 进度 / 会话）——
   断言**顶层键集合精确相等**。这些形状是本仓 `server.py` 一行行写出来的，
   没有「按格式天然不同」的余地，漂移必然是改动导致的。
2. **按行透传的响应**（书架卡片 / 批注条目 / 设备档案）—— 断言**必需子集**
   （`CARD_KEYS` / `ANNO_KEYS` / `DEVICE_KEYS`），因为它们的字段数随书格式 / 库配置合法变化。
   另外**显式禁止**服务器绝对路径 `path` 出现在这几个响应里（第 63 期 5/6 的边界）：
   它是内部字段，一旦漏发就等于把 NAS 的目录结构白送给任何持有令牌的客户端。
3. **字段面快照**（第 3 组之外的纵深）—— 上面两条只覆盖「我想得到的字段」；
   快照用例把八组端点的响应**压成键路径集合**整体比对，**多一个少一个都红**。
   快照不是自动更新的：任何字段变化都要人看一眼再重写
   （`NF_CLIENT_SURFACE_WRITE=1` + 跑本文件），这正是门禁的意义。

⚠️ 本文件是**只加不改**的护栏，不是行为规格：真的需要改字段时，**同批改这里**
并说明理由，别让下一个人靠猜。
"""

from __future__ import annotations

import json
import os
import pathlib

import pytest

from novelforge import config

#: 字段面快照（键路径集合）。重写方式见文件末尾那节说明。
SURFACE_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "client_api_surface.json"

#: 书架卡片里客户端**一定会用到**的字段。少一个就是端上白屏 / 进度丢失。
CARD_KEYS = {
    "id", "name", "format", "library_id",
    "has_description",                      # 不是 description：卡片只发「有没有」
    "percent", "updated_at", "annotation_count",
    "stars", "status", "collection_ids",
}

#: 批注条目（`db._ANNO_COLS` 的形状，13 列）。
ANNO_KEYS = {
    "id", "chapter", "quote", "color", "note", "created_at",
    "origin", "style", "anchor", "start_off", "end_off", "chapter_title",
}

#: 设备档案行（`pref_devices` 表 + `payload` 反序列化成对象）。
DEVICE_KEYS = {"id", "name", "payload", "active_profile_id", "created_at", "last_seen"}


def _pick(client, auth_headers, make_library, make_epub, lid: str = "lib-client"):
    """建一个独立库、放一本可读的 EPUB，返回 `(库根, 书 id)`。"""
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / f"client-{lid}"
    make_library(lid, "契约库", "ebook", root)
    make_epub(root, "契约书.epub")
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    bid = next(b["id"] for b in items if b["name"] == "契约书.epub")
    return root, bid


# ---------------------------------------------------------------------------
# 1. 登录
# ---------------------------------------------------------------------------

def test_login_returns_storable_token(client):
    """`{token, user}` —— 端上就靠这两个值，**不多不少**。"""
    from tests.conftest import TEST_PIN, TEST_USER

    r = client.post("/api/auth/login", json={"user": TEST_USER, "pin": TEST_PIN})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"token", "user"}, f"登录响应键漂移：{sorted(body)}"
    assert body["user"] == TEST_USER
    # 令牌是**无状态 HMAC 串**（`user.exp.ver.sig`）：端上不需要刷新机制，
    # 只要它能被原样塞进 `Authorization: Bearer`。分段数漂移 ⇒ 端上存了也用不了。
    assert isinstance(body["token"], str) and body["token"].count(".") == 3


def test_login_failure_is_detail_only(client):
    """401 只带 `detail`：端上据此显示「账号或密码错误」，不该去解析别的字段。

    ⚠️ 用**不存在的账号**探针：登录错误会按「账号 + IP」累计退避
    （`auth_mod.throttle_remaining`），拿真账号试错会把后面的用例一起打成 429。
    """
    r = client.post("/api/auth/login", json={"user": "契约探针", "pin": "wrong"})
    assert r.status_code == 401, r.text
    assert set(r.json()) == {"detail"}


# ---------------------------------------------------------------------------
# 2. 书架分页
# ---------------------------------------------------------------------------

def test_books_paging_wrapper(client, auth_headers, make_library, make_epub):
    """分页壳的六个键，以及 `has_more` / `limit` 回显口径。"""
    _pick(client, auth_headers, make_library, make_epub)

    r = client.get("/api/books", headers=auth_headers, params={"limit": 1, "offset": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"items", "total", "scanning", "limit", "offset", "has_more"}, \
        f"分页壳键漂移：{sorted(body)}"
    assert body["limit"] == 1 and body["offset"] == 0
    assert body["total"] >= 1
    assert body["has_more"] is (0 + len(body["items"]) < body["total"])

    # `limit=0` ⇒ 不限（回显 `null`）；端上「一次拿全」就靠这条，别自己写死大数字。
    body0 = client.get("/api/books", headers=auth_headers, params={"limit": 0}).json()
    assert body0["limit"] is None
    assert body0["offset"] == 0

    # 非法参数一律 **400**（不是 422）：端上 `request()` 对两者的展示不同。
    assert client.get("/api/books", headers=auth_headers,
                      params={"limit": "abc"}).status_code == 400
    assert client.get("/api/books", headers=auth_headers,
                      params={"offset": -1}).status_code == 400


def test_book_card_fields_and_no_absolute_path(client, auth_headers, make_library, make_epub):
    """卡片字段必需子集 + **绝不发绝对路径 / 简介正文**。"""
    _pick(client, auth_headers, make_library, make_epub)
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    assert items, "书架为空，契约无从校验"
    card = items[0]
    missing = CARD_KEYS - set(card)
    assert not missing, f"书架卡片缺字段：{sorted(missing)}"
    assert "path" not in card, "卡片发了服务器绝对路径（第 63 期 5/6 的边界）"
    assert "description" not in card, "卡片发了简介正文，应只发 has_description"


# ---------------------------------------------------------------------------
# 3. 详情 / 正文
# ---------------------------------------------------------------------------

def test_book_detail_chapters_index_is_chapter_api_input(
        client, auth_headers, make_library, make_epub):
    """详情必须给出 `chapters[].index`，且它就是章节接口的入参。

    端上**不自己造章节序号**：`num` 可能是缺省的（无编号条目），唯一叫法是服务端给的
    `index`；拿 `num + 1` 去请求章节是端上最容易犯的错，这条用例把入口钉住。
    """
    _pick(client, auth_headers, make_library, make_epub)
    bid = client.get("/api/books", headers=auth_headers).json()["items"][0]["id"]

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    for k in ("id", "name", "format", "chapters"):
        assert k in detail, f"详情缺字段 {k}"
    assert detail["id"] == bid
    assert "path" not in detail, "详情发了服务器绝对路径"
    # ⚠️ `chapters` 是**按卷分组**的：[{volume, chapters: [{title, index, num}]}]。
    # 端上要的是叶子，不是组 —— 直接 `chapters[0]["index"]` 会 KeyError，
    # 这条断言把这个形状钉住（鸿蒙端第一版就栽在这里）。
    groups = detail["chapters"]
    assert groups, "EPUB 详情没有章节"
    assert set(groups[0]) >= {"volume", "chapters"}, f"卷分组缺字段：{sorted(groups[0])}"
    leaves = [c for g in groups for c in g["chapters"]]
    assert leaves, "卷分组里没有叶子章节"
    first = leaves[0]
    assert "index" in first and "title" in first

    ch = client.get(f"/api/books/{bid}/chapter/{first['index']}", headers=auth_headers)
    assert ch.status_code == 200, f"章节接口不认详情给的 index：{ch.text}"


def test_chapter_shape(client, auth_headers, make_library, make_epub):
    """`{index, total, title, html}` —— `total` 是**全书章数**，端上不要自己数。"""
    _pick(client, auth_headers, make_library, make_epub)
    bid = client.get("/api/books", headers=auth_headers).json()["items"][0]["id"]

    body = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers).json()
    assert set(body) <= {"index", "total", "title", "html", "text_encoding"}
    assert {"index", "total", "title", "html"} <= set(body)
    assert body["index"] == 0
    assert isinstance(body["total"], int) and body["total"] >= 1
    assert isinstance(body["html"], str) and body["html"].strip(), "正文为空"


# ---------------------------------------------------------------------------
# 4. 进度：唯一真值源
# ---------------------------------------------------------------------------

def test_progress_roundtrip(client, auth_headers, make_library, make_epub):
    """「没写过」与「写过了」的形状必须可区分 —— 跨端续读全靠它。

    - 没写过：`locator=0 percent=0 cfi='' file_rel=null`（`file_rel` 是 **null**，
      不是空串 —— 空串是「确实写过一行、只是不知道文件」）；
    - 写过：回读到的 locator / percent / file_rel 与写入一致，`updated_at` 是数值
      （端上拿它当「本机上次写入」的比较基准）。
    """
    _pick(client, auth_headers, make_library, make_epub)
    bid = client.get("/api/books", headers=auth_headers).json()["items"][0]["id"]

    before = client.get(f"/api/books/{bid}/progress", headers=auth_headers).json()
    assert set(before) == {"locator", "percent", "cfi", "file_rel"}
    assert before["locator"] == 0 and before["percent"] == 0
    assert before["file_rel"] is None, "「这一行不存在」必须回 null，不能回空串"

    put = client.put(f"/api/books/{bid}/progress", headers=auth_headers,
                     json={"locator": 3, "percent": 4.5, "file_rel": ""})
    assert put.status_code == 200, put.text
    assert set(put.json()) == {"ok", "updated_at"}
    assert put.json()["ok"] is True
    assert isinstance(put.json()["updated_at"], (int, float))

    after = client.get(f"/api/books/{bid}/progress", headers=auth_headers).json()
    assert {"locator", "percent", "cfi", "updated_at", "file_rel"} <= set(after)
    assert after["locator"] == 3
    assert abs(after["percent"] - 4.5) < 1e-6
    assert after["file_rel"] == ""

    # 越界 / 非有限值不许 500：夹住或 400，端上都能拿到一句中文 `detail`。
    # ⚠️ 非有限值要用**字符串** `"inf"` 送：JSON 本身没有 inf 字面量，
    # 写 Python 的 `1e400` 会在 TestClient 序列化阶段就炸（端上永远碰不到那条分支）。
    bad = client.put(f"/api/books/{bid}/progress", headers=auth_headers,
                     json={"locator": 1, "percent": "inf"})
    assert bad.status_code == 400, bad.text
    assert "detail" in bad.json()


# ---------------------------------------------------------------------------
# 5. 阅读时长（心跳 upsert）
# ---------------------------------------------------------------------------

def test_session_heartbeat(client, auth_headers, make_library, make_epub):
    """带 `session_uid` = 心跳（一段一行，`seconds` 是累计值），回显同一个 uid。"""
    _pick(client, auth_headers, make_library, make_epub)
    bid = client.get("/api/books", headers=auth_headers).json()["items"][0]["id"]

    uid = "hm-contract-0001"
    for secs in (30, 60):
        r = client.post(f"/api/books/{bid}/session", headers=auth_headers,
                        json={"session_uid": uid, "seconds": secs, "source": "web"})
        assert r.status_code == 200, r.text
        assert set(r.json()) == {"ok", "session_uid"}
        assert r.json()["session_uid"] == uid

    # 不带 uid = 一次独立上报，回显空串（端上「一次性补报」用它）。
    r2 = client.post(f"/api/books/{bid}/session", headers=auth_headers, json={"seconds": 5})
    assert r2.status_code == 200 and r2.json()["session_uid"] == ""

    # 越界时长必须 400 —— 端上算错（例如后台计时没停）时不能把脏数据写进统计。
    r3 = client.post(f"/api/books/{bid}/session", headers=auth_headers,
                     json={"seconds": 0, "session_uid": uid})
    assert r3.status_code == 400, r3.text


# ---------------------------------------------------------------------------
# 6. 批注
# ---------------------------------------------------------------------------

def test_annotations(client, auth_headers, make_library, make_epub):
    """`POST {quote, chapter, start_off}` → `{id, ok}`；条目是 13 列的形状。

    `start_off` / `end_off` 缺省必须回落 **-1（不知道）而不是 0**：
    0 是「章首」这个合法偏移，兜成 0 会把每条无锚批注都画到章首，且不报错。
    """
    _pick(client, auth_headers, make_library, make_epub)
    bid = client.get("/api/books", headers=auth_headers).json()["items"][0]["id"]

    r = client.post(f"/api/books/{bid}/annotations", headers=auth_headers,
                    json={"quote": "契约引文", "chapter": 0, "start_off": 12, "end_off": 18,
                          "note": "备注", "color": "yellow"})
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"id", "ok"}

    # 不带锚点的那条：两个偏移都必须是 -1。
    client.post(f"/api/books/{bid}/annotations", headers=auth_headers,
                json={"quote": "无锚引文", "chapter": 0})

    items = client.get(f"/api/books/{bid}/annotations", headers=auth_headers).json()["items"]
    assert len(items) == 2
    for it in items:
        missing = ANNO_KEYS - set(it)
        assert not missing, f"批注条目缺字段：{sorted(missing)}"
    by_quote = {it["quote"]: it for it in items}
    assert by_quote["契约引文"]["start_off"] == 12
    assert by_quote["契约引文"]["end_off"] == 18
    assert by_quote["无锚引文"]["start_off"] == -1, "无锚批注被兜成 0（会画到章首）"
    assert by_quote["无锚引文"]["end_off"] == -1

    # quote 是必填：端上「选中为空」时不该发出请求，但服务端也必须挡。
    assert client.post(f"/api/books/{bid}/annotations", headers=auth_headers,
                       json={"chapter": 0}).status_code == 400


# ---------------------------------------------------------------------------
# 7. 设备偏好档案
# ---------------------------------------------------------------------------

def test_prefs_device_roundtrip(client, auth_headers):
    """`payload` 进出都是**对象**（不是 JSON 字符串），且块名受 7 块白名单约束。

    端上唯一的读写口。**PUT 是整体替换** —— 这是端上最容易踩的坑：
    只写自己认识的键会把 Web 端偏好清空，所以端上必须「读-改-写」。
    本用例只钉服务端的形状与拒绝口径。
    """
    did = "hm-contract-device"
    assert client.get(f"/api/prefs/devices/{did}", headers=auth_headers).status_code == 404, \
        "不存在的设备必须 404 —— 端上据此判定「新设备」"

    r = client.put(f"/api/prefs/devices/{did}", headers=auth_headers,
                   json={"name": "鸿蒙阅读器", "payload": {"reader": {"size": 20, "theme": "light"}}})
    assert r.status_code == 200, r.text
    body = r.json()
    missing = DEVICE_KEYS - set(body)
    assert not missing, f"设备行缺字段：{sorted(missing)}"
    assert isinstance(body["payload"], dict), "payload 必须已反序列化成对象"
    assert body["payload"]["reader"]["size"] == 20
    assert body["name"] == "鸿蒙阅读器"

    # 未知块 ⇒ 400（不是静默丢弃）：端上写错块名必须当场发现。
    bad = client.put(f"/api/prefs/devices/{did}", headers=auth_headers,
                     json={"payload": {"harmony": {"x": 1}}})
    assert bad.status_code == 400 and "未知的偏好块" in bad.json()["detail"]

    # 空对象也不收（`_check_payload` 要求非空）。
    assert client.put(f"/api/prefs/devices/{did}", headers=auth_headers,
                      json={"payload": {}}).status_code == 400

    # 不传 `active_profile_id` ⇒ **保留原值**（端上推配置不该顺手清掉来源标记）。
    prof = client.post("/api/prefs/profiles", headers=auth_headers,
                       json={"name": "鸿蒙档案", "payload": {"reader": {"size": 22}}}).json()
    pid = prof["id"]
    client.put(f"/api/prefs/devices/{did}", headers=auth_headers,
               json={"name": "鸿蒙阅读器", "payload": {"reader": {"size": 22}},
                     "active_profile_id": pid})
    keep = client.put(f"/api/prefs/devices/{did}", headers=auth_headers,
                      json={"name": "鸿蒙阅读器", "payload": {"reader": {"size": 24}}})
    assert keep.json()["active_profile_id"] == pid, "省略 active_profile_id 时被清空了"

    # 显式 null 才清空 —— 端上「解除引用」只能用这一种写法。
    cleared = client.put(f"/api/prefs/devices/{did}", headers=auth_headers,
                         json={"name": "鸿蒙阅读器", "payload": {"reader": {"size": 24}},
                               "active_profile_id": None})
    assert cleared.json()["active_profile_id"] is None

    # 指向不存在的档案 ⇒ 400（不是静默写入一个悬空 id）。
    assert client.put(f"/api/prefs/devices/{did}", headers=auth_headers,
                      json={"name": "x", "payload": {"reader": {"size": 1}},
                            "active_profile_id": 999999}).status_code == 400


def test_prefs_device_id_shape(client, auth_headers):
    """`_DEVICE_ID_RE = ^[A-Za-z0-9_-]{8,64}$` —— 端上生成的 id 必须过这一关。

    过不了就是 400「设备 id 非法」，而端上若不处理会表现为「偏好永远存不上」。
    """
    for bad in ("short", "含中文的设备标识啊", "a" * 65, "has space 1234"):
        r = client.put(f"/api/prefs/devices/{bad}", headers=auth_headers,
                       json={"name": "x", "payload": {"reader": {"size": 1}}})
        assert r.status_code == 400, f"{bad!r} 应被拒：{r.text}"

    ok = "a" * 64
    assert client.put(f"/api/prefs/devices/{ok}", headers=auth_headers,
                      json={"name": "x", "payload": {"reader": {"size": 1}}}).status_code == 200


# ---------------------------------------------------------------------------
# 8. 版本协商 + 字段面快照
#
# 这两条回答的是同一个问题：**后端改动会不会在无人察觉的情况下打坏客户端？**
# 它们**替代**了「把前后端拆成两个仓库/两个部署单元」那条路 —— 物理拆分并不解决
# 「字段悄悄改名」，只会新增「前端 bundle 与后端版本错配」这个新风险
# （理由与代价清单见 `docs/harmonyos-client-plan.md` §3.B）。
# ---------------------------------------------------------------------------

def _paths(obj, prefix: str = "") -> set[str]:
    """把一段 JSON 压成**键路径集合**：字典逐键下钻，列表只看第一个元素。

    只看第一个元素是够的：同一数组的元素是同一个生产者用同一段代码拼出来的；
    取全集会把「这本有 ISBN、那本没有」这类**数据差异**也算进形状里，噪声大于信号。
    """
    out: set[str] = set()
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{prefix}.{k}" if prefix else str(k)
            out.add(p)
            out |= _paths(v, p)
    elif isinstance(obj, list):
        p = f"{prefix}[]"
        out.add(p)
        if obj:
            out |= _paths(obj[0], p)
    return out


def _collect_surface(client, auth_headers, make_library, make_epub) -> dict[str, list[str]]:
    """按**端上真实用法**把八组端点各调一次，返回 `{标签: 排序后的键路径}`。

    先造数据再读（写进度 / 写一条批注 / 写一次设备偏好），否则「没有记录」
    那条分支的形状会把「有记录」的字段盖掉。
    """
    from tests.conftest import TEST_PIN, TEST_USER

    _pick(client, auth_headers, make_library, make_epub)
    bid = client.get("/api/books", headers=auth_headers).json()["items"][0]["id"]
    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    leaf = next(c for g in detail["chapters"] for c in g["chapters"])

    # 顺序照端上真实动作：开书先取正文（派生件在这一步生成），再写进度 ——
    # 反过来写，服务端可能因为「派生件还没建」给出更瘦的进度响应，快照就钉歪了。
    client.get(f"/api/books/{bid}/chapter/{leaf['index']}", headers=auth_headers)
    client.put(f"/api/books/{bid}/progress", headers=auth_headers,
               json={"locator": 1, "percent": 2.0, "file_rel": ""})
    client.post(f"/api/books/{bid}/annotations", headers=auth_headers,
                json={"quote": "快照引文", "chapter": 0, "start_off": 1, "end_off": 2})
    did = "hm-surface-device"
    client.put(f"/api/prefs/devices/{did}", headers=auth_headers,
               json={"name": "快照设备", "payload": {"reader": {"size": 20}}})

    calls = [
        ("login", "post", "/api/auth/login", {"json": {"user": TEST_USER, "pin": TEST_PIN}}),
        ("books", "get", "/api/books", {}),
        ("detail", "get", f"/api/books/{bid}", {}),
        ("chapter", "get", f"/api/books/{bid}/chapter/{leaf['index']}", {}),
        ("progress", "get", f"/api/books/{bid}/progress", {}),
        ("session", "post", f"/api/books/{bid}/session", {"json": {"seconds": 30}}),
        ("annotations", "get", f"/api/books/{bid}/annotations", {}),
        ("device", "get", f"/api/prefs/devices/{did}", {}),
        ("health", "get", "/health", {}),
    ]
    surface: dict[str, list[str]] = {}
    for label, method, url, kw in calls:
        kw.setdefault("headers", auth_headers)
        r = client.request(method.upper(), url, **kw)
        assert r.status_code == 200, f"{label} {url} → {r.status_code} {r.text[:200]}"
        surface[label] = sorted(_paths(r.json()))
    return surface


def test_version_is_single_source(client):
    """`/health` 与 `/openapi.json` 的版本号都必须等于仓库根 `VERSION`。

    端上的版本协商只有这一个判据：`GET /health`（免鉴权、登录前就能问）拿 `version`，
    与端上硬编码的 `MIN_SERVER_VERSION` 比；不匹配就提示升级，而不是让用户面对
    「书架空白 / 字段莫名缺失」。**侧载没有自动更新通道**，这条比 Web 端更要紧。

    顺带钉住「版本号唯一真值源」（AGENTS §6）：`VERSION` 是文件真值源，
    `/health.version`（`server.APP_VERSION`）与 OpenAPI 的 `info.version` 都从它派生 ——
    谁要是再写一份版本字面量，这里会红。
    """
    ver = (pathlib.Path(__file__).resolve().parents[1] / "VERSION").read_text(
        encoding="utf-8").strip()
    assert ver, "仓库根 VERSION 是空的"

    h = client.get("/health")          # 不带任何头：登录前的预检就靠它免鉴权
    assert h.status_code == 200, h.text
    body = h.json()
    assert {"status", "checks", "problems", "version"} <= set(body), sorted(body)
    assert body["version"] == ver, f"/health 版本与 VERSION 不一致：{body['version']} != {ver}"

    spec = client.get("/openapi.json")  # 非 `/api` 前缀同样免鉴权（中间件 :445 只拦 /api）
    assert spec.status_code == 200, spec.text[:200]
    assert spec.json()["info"]["version"] == ver


def test_response_surface_matches_snapshot(client, auth_headers, make_library, make_epub):
    """八组端点的**字段面**与快照逐端点比对：少一个字段、多一个字段都要人看一眼。

    说明两点，免得下一个人以为是测试写死了：

    - **多一个字段也失败**是刻意的。客户端会忽略未知字段，但「多发一个字段」有时正是
      事故形态（例如把 `path` / `description` 漏发出去，见文件开头第 2 条判据）。
      要加字段就同批重写快照 —— 那一步就是「人看一眼」。
    - **重写快照**：`NF_CLIENT_SURFACE_WRITE=1` 跑本文件，会把当前形状写回
      `tests/fixtures/client_api_surface.json`（那一遍用例 skip 以提醒你 diff）。
      不许在 CI 里设这个变量。
    """
    got = _collect_surface(client, auth_headers, make_library, make_epub)

    if os.environ.get("NF_CLIENT_SURFACE_WRITE"):
        SURFACE_FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        SURFACE_FIXTURE.write_text(
            json.dumps(got, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8")
        pytest.skip(f"已重写快照 {SURFACE_FIXTURE.as_posix()}（请 git diff 逐条确认）")

    want = json.loads(SURFACE_FIXTURE.read_text(encoding="utf-8"))
    problems: list[str] = []
    for label in sorted(want):
        missing = sorted(set(want[label]) - set(got.get(label, ())))
        added = sorted(set(got.get(label, ())) - set(want[label]))
        if missing:
            problems.append(f"{label} 少了字段：{missing}")
        if added:
            problems.append(f"{label} 多了字段：{added}")
    for label in sorted(set(got) - set(want)):
        problems.append(f"快照里没有这组端点：{label}")

    assert not problems, (
        "客户端可见的字段面变了（鸿蒙端会跟着坏）：\n  "
        + "\n  ".join(problems)
        + "\n确认无误后：NF_CLIENT_SURFACE_WRITE=1 跑本文件重写快照，再 git diff 核对。"
    )

