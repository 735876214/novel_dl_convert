"""OPDS / KOReader 两个出口的审计契约（第 271 期）。

Komga 那五轮总结出来的六类问题里，有四类在别的出口同样成立 —— 这一轮拿 OPDS 与
KOReader 各验一遍：

1. **分页参数不该硬拒**：`/opds/*` 的 12 个端点都是 `Query(1, ge=1)`，而
   `opds.acquisition_feed` **本来就会把页夹到 `[1, pages]`** ⇒ `ge=1` 只是把
   「能救的输入」变成 **422**（与第 266 期 Komga 的 `size=1000` 同一个错误）。
2. **写入口不校验对象还在不在**：`PUT /koreader/syncs/progress` 只查
   `koreader_docs` 索引行 —— 而**删书不清索引**（要等一次「扫描书库」整表重建）⇒
   给一本**已删的书**写进 `progress`，留下一条谁都看不见、也清不掉的孤儿行
   （孤儿扫描要求「该库还有索引书」，那本书恰是最后一本时连扫描都够不着）。
   `GET /koreader/syncs/progress/{document}` 早就校验了，PUT 漏了。
3. **认证必须有失败退避**：`_ko_guard` 直接 `hmac.compare_digest`，**没有任何退避** ——
   而 kosync 的 key 就是**用户密码的 MD5**：攻击者本地算 `md5(猜测)` 直接提交，
   尝试次数不受限 ⇒ 一个没有闸门的口令预言机（第 137 期 `/api/v1` 那条同形）。
"""
import base64
import hashlib
import io
import zipfile

import pytest

from novelforge import config
from novelforge.core import db, koreader, library

KO_USER = "koreader"
KO_PW = "pw-271"


def _basic(user: str, pin: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pin}".encode()).decode()}


def _ko_headers(pw: str = KO_PW) -> dict:
    return {"X-Auth-User": KO_USER, "X-Auth-Key": hashlib.md5(pw.encode()).hexdigest()}


@pytest.fixture
def opds_on():
    config.save_overrides({"opds": {"enabled": True}})
    try:
        yield _basic("admin", "test1234")
    finally:
        config.save_overrides({})


@pytest.fixture
def kosync_on():
    config.save_overrides({"koreader": {"enabled": True, "username": KO_USER,
                                        "key": hashlib.md5(KO_PW.encode()).hexdigest()}})
    try:
        yield _ko_headers()
    finally:
        config.save_overrides({})


def _cbz(path, pages: int = 3):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(pages):
            b = io.BytesIO()
            Image.new("RGB", (30, 40), (i * 20, 0, 0)).save(b, "PNG")
            z.writestr(f"{i + 1:03d}.png", b.getvalue())
    path.write_bytes(buf.getvalue())


@pytest.fixture
def one_lib(client, auth_headers, make_library, tmp_path):
    root = tmp_path / "L"
    root.mkdir(parents=True, exist_ok=True)
    make_library("L", "库", "comic", root)
    for i in (1, 2, 3):
        _cbz(root / "系列" / f"系列 #{i}.cbz")
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    return root


# ---------------------------------------------------------------- 1. OPDS 分页

def test_opds的页码被夹住而不是_422(client, opds_on, one_lib):   # noqa: ARG001
    first = client.get("/opds/all?page=1", headers=opds_on)
    zero = client.get("/opds/all?page=0", headers=opds_on)
    assert zero.status_code == 200, f"page=0 -> {zero.status_code}（feed 会夹到第一页）"
    assert zero.text.count("<entry>") == first.text.count("<entry>") == 3
    # 翻过头：夹到最后一页（不是报错，也不是空）
    over = client.get("/opds/all?page=999", headers=opds_on)
    assert over.status_code == 200 and over.text.count("<entry>") == 3
    # 非数字仍是真的坏输入
    assert client.get("/opds/all?page=abc", headers=opds_on).status_code == 422


def test_opds其余分页端点同样(client, opds_on, one_lib):      # noqa: ARG001
    for ep in ("/opds/recent", "/opds/authors", "/opds/series", "/opds/tags",
               "/opds/search?q=系列"):
        r = client.get(ep + ("&page=0" if "?" in ep else "?page=0"), headers=opds_on)
        assert r.status_code == 200, f"{ep} -> {r.status_code}"


# ---------------------------------------------------------------- 2. 已删的书

def test_koreader不给已删的书推进度(client, auth_headers, kosync_on, one_lib):
    b = library.books()[0]
    rows = koreader.scan_books(library.books(), one_lib)
    db.replace_koreader_docs(rows)
    doc = next(r["doc_md5"] for r in rows if r["book_id"] == b["id"])

    ok = client.put("/koreader/syncs/progress",
                    json={"document": doc, "progress": "2", "percentage": 0.5},
                    headers=kosync_on)
    assert ok.status_code == 200
    assert (db.get_progress(b["id"]) or {}).get("percent") == 50.0

    assert client.delete("/api/books/" + b["id"], headers=auth_headers).status_code == 200
    library.invalidate()

    r = client.put("/koreader/syncs/progress",
                   json={"document": doc, "progress": "3", "percentage": 0.9},
                   headers=kosync_on)
    assert r.status_code == 404, f"给已删的书推进度应当 404，实际 {r.status_code}"
    # 删书是**软删除**（进度行按设计留着）⇒ 这里要看的是「第二次 PUT 没写进去」
    assert (db.get_progress(b["id"]) or {}).get("percent") == 50.0,         "已删的书又被写进了一次进度（那条行谁都看不见也清不掉）"


def test_koreader的_GET_早就校验了(client, auth_headers, kosync_on, one_lib):
    """对照：GET 那条本来就是 404 —— 本期只是把 PUT 拉齐。"""
    b = library.books()[0]
    rows = koreader.scan_books(library.books(), one_lib)
    db.replace_koreader_docs(rows)
    doc = next(r["doc_md5"] for r in rows if r["book_id"] == b["id"])
    client.delete("/api/books/" + b["id"], headers=auth_headers)
    library.invalidate()
    assert client.get("/koreader/syncs/progress/" + doc,
                      headers=kosync_on).status_code == 404


# ---------------------------------------------------------------- 3. 认证退避

def test_koreader认证有失败退避(client, kosync_on, one_lib):     # noqa: ARG001
    bad = {"X-Auth-User": KO_USER, "X-Auth-Key": hashlib.md5("猜错的口令".encode("utf-8")).hexdigest()}
    codes = [client.get("/koreader/users/auth", headers=bad).status_code for _ in range(6)]
    assert codes[:5] == [401] * 5, codes
    # 第 6 次起进入退避：**连正确口令也先被挡住**（否则「被挡住」本身就是可探测的差异）
    assert client.get("/koreader/users/auth", headers=kosync_on).status_code == 429, \
        "kosync 的认证没有失败退避 —— 那是一个可以无限次试的口令预言机"


def test_koreader正常凭据照旧可用(client, kosync_on, one_lib):   # noqa: ARG001
    assert client.get("/koreader/users/auth", headers=kosync_on).status_code == 200
