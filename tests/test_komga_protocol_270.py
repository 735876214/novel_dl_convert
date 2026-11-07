"""Komga 兼容面**第五轮**审计的契约（第 270 期）：只读凭据的边界。

文档对只读凭据的描述是「第 160 期建的**只读账号**（书库范围同样生效）」
（`docs/user-guide.md`）。但 `_komga_guard` 只做**认证** —— 它返回的 scope
**没有任何写入口用过**：

1. **只读凭据能建 / 改名 / 删收藏夹**：实测把一个「只读」凭据交给第三方客户端，
   那个客户端**删掉了管理员的「我的收藏」**（收藏夹就是本应用的「我的收藏」，全局用户数据）。
2. **`users/me` 对只读凭据也报 `roles: ["ADMIN","USER"]`**、`sharedLibraries[].role: "ADMIN"`
   ⇒ 客户端显示管理 / 编辑入口。权限声明与真实权限必须一致（AGENTS §1「不做假交互」）。
3. **只读凭据能列出全部收藏夹的名字**（成员已按可见性过滤，名字没过滤）⇒
   一个只许看 A 库的客户端能看到 B 库书的收藏夹叫什么。
"""
import base64
import io
import zipfile

import pytest

from novelforge import config
from novelforge.core import db, library


def _basic(user: str, pin: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pin}".encode()).decode()}


def _cbz(path, pages: int = 2):
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
def komga_on():
    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        yield {"X-API-Key": "test-key"}
    finally:
        config.save_overrides({})


@pytest.fixture
def two_libs(client, auth_headers, make_library, tmp_path):
    """A / B 两个库各一本书，返回 (A 库里的书, B 库里的书)。"""
    for lid, nm in (("ka", "A 库"), ("kb", "B 库")):
        root = tmp_path / lid
        root.mkdir(parents=True, exist_ok=True)
        make_library(lid, nm, "comic", root)
        _cbz(root / ("%s系列" % lid) / ("%s #1.cbz" % lid))
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    books = {b["library_id"]: b for b in library.books()}
    return books["ka"], books["kb"]


@pytest.fixture
def readonly_headers(client, auth_headers):
    r = client.post("/api/opds/credentials", headers=auth_headers,
                    json={"username": "reader1", "pin": "1234", "library_ids": ["ka"]})
    assert r.status_code == 200, r.text
    return _basic("reader1", "1234")


# ---------------------------------------------------------------- 1. 只读就是只读

def test_只读凭据不能建改删收藏夹(client, auth_headers, komga_on, two_libs,
                            readonly_headers):        # noqa: ARG001
    h = readonly_headers
    assert client.post("/api/v1/collections", json={"name": "只读建的"},
                       headers=h).status_code == 403
    # 管理员建一个，只读凭据改不动也删不掉
    cid = db.create_collection("我的收藏")
    assert client.patch(f"/api/v1/collections/{cid}", json={"name": "改名了"},
                        headers=h).status_code == 403
    assert client.delete(f"/api/v1/collections/{cid}", headers=h).status_code == 403
    assert [r["name"] for r in db.list_collections()] == ["我的收藏"], "夹被只读凭据动了"

    # 系列成员的增删同样不许
    s = client.get("/api/v1/series?size=5", headers=komga_on).json()["content"][0]
    assert client.put(f"/api/v1/collections/{cid}/series",
                      json={"seriesIds": [s["id"]]}, headers=h).status_code == 403
    assert client.delete(f"/api/v1/collections/{cid}/series/{s['id']}",
                         headers=h).status_code == 403


def test_管理员仍然能写收藏夹(client, auth_headers, komga_on):   # noqa: ARG001
    """只读的闸门不许把管理员一起挡掉。"""
    r = client.post("/api/v1/collections", json={"name": "管理员建的"}, headers=komga_on)
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert client.patch(f"/api/v1/collections/{cid}", json={"name": "改名"},
                        headers=komga_on).status_code == 200
    assert client.delete(f"/api/v1/collections/{cid}", headers=komga_on).status_code == 204


def test_只读凭据仍能写范围内的阅读进度(client, komga_on, two_libs, readonly_headers):
    """「只读」管的是**内容与收藏夹**，阅读进度是阅读器必须能写的。"""
    a, _b = two_libs
    assert client.put("/api/v1/books/" + a["id"] + "/read-progress",
                      json={"page": 1}, headers=readonly_headers).status_code == 204


# ---------------------------------------------------------------- 2. roles 与权限一致

def test_只读凭据的_roles_不含_ADMIN(client, komga_on, two_libs, readonly_headers):
    me = client.get("/api/v1/users/me", headers=readonly_headers).json()
    assert me["roles"] == ["USER"], me["roles"]
    assert {x["role"] for x in me["sharedLibraries"]} == {"USER"}, me["sharedLibraries"]


def test_管理员的_roles_仍是_ADMIN(client, komga_on, two_libs):   # noqa: ARG001
    me = client.get("/api/v1/users/me", headers=komga_on).json()
    assert "ADMIN" in me["roles"]


# ---------------------------------------------------------------- 3. 收藏夹的可见性

def test_只读凭据看不到范围外的收藏夹(client, auth_headers, komga_on, two_libs,
                              readonly_headers):
    a, b = two_libs
    mine = db.create_collection("A 的夹")
    db.add_books_to_collection(mine, [a["id"]])
    other = db.create_collection("B 的夹")
    db.add_books_to_collection(other, [b["id"]])

    got = [x["name"] for x in
           client.get("/api/v1/collections?size=20", headers=readonly_headers).json()["content"]]
    assert got == ["A 的夹"], f"只读凭据看到了范围外的夹：{got}"
    assert client.get(f"/api/v1/collections/{other}",
                      headers=readonly_headers).status_code == 404
    assert client.get(f"/api/v1/collections/{mine}",
                      headers=readonly_headers).status_code == 200
    # 管理员两本都看得到
    admin = [x["name"] for x in
             client.get("/api/v1/collections?size=20", headers=komga_on).json()["content"]]
    assert set(admin) == {"A 的夹", "B 的夹"}
