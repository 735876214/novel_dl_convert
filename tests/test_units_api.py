"""序号单元合集的**服务端契约**（第 73 期）：话清单、单话、单页、封面、令牌口子。

判据本体在 ``tests/test_units.py``、扫描链路在 ``tests/test_units_scan.py``；
这里只钉 HTTP 面，四条要求：

1. **清单与卡片同源**：`/units` 的条数必须等于卡片上的 `tracks`（同一个 `units.units`），
   否则书架说 4 话、点进去是 3 条；
2. **越界一律 404**（AGENTS.md 要求新增接口有 404 断言）：话越界、页越界、书不存在；
3. **鉴权面不扩大**：`?token=` 只开在 `<audio src>` / `<img src>` 那两条路径上
   （单话、单页），其余（含**话清单本身**）仍只认 Bearer；
4. **嵌套有声书修好了**：`《书名》/第1卷/第1话.mp3` 的 `/audio` 此前一条轨都列不出来
   （`audio.tracks` 只看直接子文件），现在列得出、也取得到 —— 前端播放器协议不变。
"""
import pathlib
import struct
import zlib
import zipfile

import pytest

from novelforge.core import library

BOOK_DIR = "《转生魔女宣告毁灭（1-43话）》"
#: 4 话：三份 PDF + 一份漫画（CBZ），序号写法照用户实况（`第二话` / `第03话` / `4 第4话`）
UNIT_FILES = ["第1卷/第1话.pdf", "第1卷/第二话.pdf", "第1卷/第03话.cbz", "第1卷/4 第4话.pdf"]
COMIC_UNIT_INDEX = 2                       # 第03话.cbz 在话序里的位置


def _png(color: bytes = b"\xff\x00\x00") -> bytes:
    """一张 1×1 的合法 PNG（漫画话里的「一页」）。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)     # 1×1、8bit、truecolor
    raw = zlib.compress(b"\x00" + color)                     # 一行：filter 0 + RGB
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def _write(path: pathlib.Path, data: bytes) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


@pytest.fixture
def env(isolated, tmp_path: pathlib.Path, make_library):  # noqa: ARG001 —— 依赖 isolated 切目录
    """一个漫画库（含一棵 4 话的树）+ 一个有声书库（含一棵嵌套的 3 话树）。"""
    root = tmp_path / "comic"
    make_library("c1", "漫画库", "comic", root)
    d = root / BOOK_DIR
    _write(d / "第1卷" / "第1话.pdf", b"%PDF-1.4 first")
    _write(d / "第1卷" / "第二话.pdf", b"%PDF-1.4 second")
    _write(d / "第1卷" / "4 第4话.pdf", b"%PDF-1.4 fourth")
    with zipfile.ZipFile(d / "第1卷" / "第03话.cbz", "w") as z:
        z.writestr("001.png", _png(b"\x00\xff\x00"))
        z.writestr("002.png", _png(b"\x00\x00\xff"))
    # 封面埋在子树里（第 73 期起扫得到、也发得出来）
    _write(d / "第1卷" / "cover.jpg", b"\xff\xd8\xff\xe0 fake jpeg")

    aroot = tmp_path / "audio"
    make_library("a1", "有声书库", "audiobook", aroot)
    ad = aroot / "《书名》"
    for i in (1, 2, 3):
        _write(ad / "第1卷" / f"第{i}话.mp3", b"ID3 audio %d" % i)     # noqa: UP031
    _write(ad / "第1卷" / "cover.jpg", b"\xff\xd8\xff\xe0 fake jpeg")

    books = {b["name"]: b for b in library.books("c1")}
    abook = library.books("a1")[0]
    assert list(books) == [BOOK_DIR] and books[BOOK_DIR]["format"] == "UNITS"
    return {"bid": books[BOOK_DIR]["id"], "abid": abook["id"], "root": d, "aroot": ad}


# ---------------------------------------------------------------------------
# ① 话清单：与卡片同源，且没被 `{param}` 那条路由吃掉
# ---------------------------------------------------------------------------

def test_话清单与卡片话数同源(client, auth_headers, env):
    """`/units` ⇒ 4 条、序号 1..4；条数与卡片 `tracks`、与详情页的 `units` 逐字一致。"""
    r = client.get(f"/api/books/{env['bid']}/units", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 4 and len(body["items"]) == 4
    assert [it["name"] for it in body["items"]] == UNIT_FILES
    assert [it["num"] for it in body["items"]] == [1, 2, 3, 4]
    assert [it["kind"] for it in body["items"]] == ["pdf", "pdf", "comic", "pdf"]
    assert [it["index"] for it in body["items"]] == [0, 1, 2, 3]

    # 卡片上的话数（索引里的 `tracks`）与详情页的清单都必须与它一致 —— 三处一个数
    card = library.by_id(env["bid"])
    assert card["tracks"] == body["total"] == 4
    detail = client.get(f"/api/books/{env['bid']}", headers=auth_headers).json()
    assert [it["name"] for it in detail["units"]] == UNIT_FILES


def test_越界与不存在一律404(client, auth_headers, env):
    """话越界 / 书不存在 ⇒ 404（新增接口必须有这条断言）。"""
    assert client.get(f"/api/books/{env['bid']}/units/4", headers=auth_headers).status_code == 404
    assert client.get(f"/api/books/{env['bid']}/units/-1", headers=auth_headers).status_code == 404
    assert client.get("/api/books/nope/units", headers=auth_headers).status_code == 404
    assert client.get("/api/books/nope/units/0", headers=auth_headers).status_code == 404


def test_不是合集的书给400(client, auth_headers, default_root):
    """电子书库里的 EPUB（`format == "EPUB"`）走不到这条路 ⇒ 400，不是 500 也不是空清单。"""
    p = default_root / "三体.epub"
    _write(p, b"EPUB")
    bid = [b for b in library.books() if b["name"] == "三体.epub"][0]["id"]
    r = client.get(f"/api/books/{bid}/units", headers=auth_headers)
    assert r.status_code == 400 and "合集" in r.json()["detail"]


# ---------------------------------------------------------------------------
# ② 单话字节流 / 漫画话的页
# ---------------------------------------------------------------------------

def test_单话字节流带Range(client, auth_headers, env):
    """`/units/{index}` 给出这一话的原始字节，且支持 Range（音频话拖动必需）。"""
    r = client.get(f"/api/books/{env['bid']}/units/0", headers=auth_headers)
    assert r.status_code == 200 and r.content == b"%PDF-1.4 first"
    assert r.headers["content-type"].startswith("application/pdf")

    part = client.get(f"/api/books/{env['bid']}/units/0",
                      headers={**auth_headers, "Range": "bytes=0-3"})
    assert part.status_code == 206 and part.content == b"%PDF"


def test_漫画话的页与越界(client, auth_headers, env):
    """CBZ 话：页清单两条、取得到第 1 页的 PNG 字节；PDF 话没有「页」这个概念。"""
    i = COMIC_UNIT_INDEX
    pages = client.get(f"/api/books/{env['bid']}/units/{i}/pages", headers=auth_headers)
    assert pages.status_code == 200
    assert pages.json()["total"] == 2
    assert [p["name"] for p in pages.json()["pages"]] == ["001.png", "002.png"]

    page = client.get(f"/api/books/{env['bid']}/units/{i}/page/0", headers=auth_headers)
    assert page.status_code == 200 and page.content.startswith(b"\x89PNG")
    assert page.headers["content-type"] == "image/png"

    assert client.get(f"/api/books/{env['bid']}/units/{i}/page/2",
                      headers=auth_headers).status_code == 404, "页越界必须 404"
    # PDF 话：`pages` 是漫画归档专有（与 `/comic` 对非归档书的态度一致）
    assert client.get(f"/api/books/{env['bid']}/units/0/pages",
                      headers=auth_headers).status_code == 400
    # 话越界时连归档都取不到 ⇒ 404（先判话、再判格式）
    assert client.get(f"/api/books/{env['bid']}/units/9/pages",
                      headers=auth_headers).status_code == 404


# ---------------------------------------------------------------------------
# ③ 令牌口子：只开在 <audio src> / <img src> 那两条上
# ---------------------------------------------------------------------------

def test_令牌只开在单话与单页上(client, auth_headers, env):
    """无 Authorization、只带 `?token=` 时：单话 / 单页放行，**其余一律 401**。

    这几条路径对应浏览器原生请求（`<audio src>` / `<img src>`，带不了请求头）。
    少开一条 ⇒ 音频话与漫画话都读不出来；多开一条 ⇒ 鉴权面被悄悄放宽 ——
    所以列表接口也要断言 401。
    """
    # 令牌取自 `auth_headers` 那次真实登录（不在用例里再抄一份凭据）
    tok = auth_headers["Authorization"].removeprefix("Bearer ")
    i = COMIC_UNIT_INDEX
    assert client.get(f"/api/books/{env['bid']}/units/1?token={tok}").status_code == 200
    assert client.get(f"/api/books/{env['bid']}/units/{i}/page/0?token={tok}").status_code == 200
    # 反例：这些**不**在口子里（原样 401）
    assert client.get(f"/api/books/{env['bid']}/units?token={tok}").status_code == 401
    assert client.get(f"/api/books/{env['bid']}/units/{i}/pages?token={tok}").status_code == 401
    assert client.get(f"/api/books/{env['bid']}/file?token={tok}").status_code == 401


# ---------------------------------------------------------------------------
# ④ 嵌套有声书 / 封面（都是「树里不止一层」的家族）
# ---------------------------------------------------------------------------

def test_嵌套有声书的轨与单轨(client, auth_headers, env):
    """`《书名》/第1卷/第1话.mp3` ×3 ⇒ `/audio` 列 3 轨、`/audio/2` 取得到。

    ⚠️ **改造前必红**：整棵树扫不出来（`_iter_book_entries` 只下探一层），
    就算扫出来了 `audio.tracks` 也只看直接子文件 ⇒ 0 轨、播放器空白。
    """
    r = client.get(f"/api/books/{env['abid']}/audio", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 3
    assert [it["name"] for it in r.json()["items"]] == [
        "第1卷/第1话.mp3", "第1卷/第2话.mp3", "第1卷/第3话.mp3"], \
        "轨名是**相对树根**的路径（嵌套树里首轨在子目录里）"

    assert client.get(f"/api/books/{env['abid']}/audio/2",
                      headers=auth_headers).content == b"ID3 audio 3"
    assert client.get(f"/api/books/{env['abid']}/audio/3",
                      headers=auth_headers).status_code == 404

    # 全音频的树仍是有声书（前端进播放器）：合集端点对它 400，分工不含糊
    assert client.get(f"/api/books/{env['abid']}/units",
                      headers=auth_headers).status_code == 400


def test_封面能在子树里(client, auth_headers, env):
    """封面埋在 `第1卷/` 里也要发得出来。

    ⚠️ **改造前必红**：`audio.cover_in_dir` 只看直接子文件 ⇒ 404，而卡片上
    `has_cover` 是扫描时用「树内」判据算的 ⇒ 卡片说有封面、点开没有。
    """
    for bid, label in ((env["bid"], "合集"), (env["abid"], "嵌套有声书")):
        r = client.get(f"/api/books/{bid}/cover", headers=auth_headers)
        assert r.status_code == 200, f"{label}的封面没发出来：{r.status_code}"
        assert r.content.startswith(b"\xff\xd8")


def test_目录型书没有封面时404(client, auth_headers, tmp_path, make_library):
    """树里没有封面 ⇒ 404（前端回退渐变占位），不是 500。"""
    root = tmp_path / "comic2"
    make_library("c2", "漫画库二", "comic", root)
    d = root / "《没有封面》"
    _write(d / "第1话.pdf", b"%PDF-1.4 a")
    _write(d / "第2话.pdf", b"%PDF-1.4 b")
    bid = library.books("c2")[0]["id"]
    assert client.get(f"/api/books/{bid}/cover", headers=auth_headers).status_code == 404
