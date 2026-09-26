"""演播者实体（第 53 期）：扫描落盘、排序名回退链、回填、聚合、接口三态。

与作者实体同源同构但刻意精简（无 bio/photo/软删）。排序名两列分列、回退规则、回填只写
派生态列的铁律逐字对齐 test_author_sort_name.py，避免双标。

离线约定：造「带演播者的有声书」用构造的 M4B 字节（见 test_audio_narrators.py 的 builder），
不依赖真实音频 / 外呼。
"""
import pathlib
import urllib.parse

import pytest

from novelforge.core import db, library, narrators as narrators_mod


def _quote(name: str) -> str:
    return urllib.parse.quote(name)


def _atom(code: str, payload: bytes) -> bytes:
    return (8 + len(payload)).to_bytes(4, "big") + code.encode("latin1") + payload


def _build_mp4(narrators):
    items = b""
    for n in narrators:
        data = (1).to_bytes(4, "big") + b"\x00\x00\x00\x00" + n.encode("utf-8")
        items += _atom("\xa9nrt", _atom("data", data))
    ilst = _atom("ilst", items)
    meta = _atom("meta", b"\x00\x00\x00\x00" + ilst)
    return _atom("moov", meta)


@pytest.fixture
def narrator_fixture(isolated, default_root, monkeypatch):  # noqa: ARG001 —— 依赖 isolated 切目录
    """一本带演播者的真实（构造字节）有声书，让 `library.narrator_books()` 认得这位演播者。"""
    import novelforge.core.audio as audio_mod
    # 假文件没有真音频帧，tracks 会解析失败；直接桩掉，专注验证「演播者标签→落盘」链路。
    monkeypatch.setattr(
        audio_mod, "tracks",
        lambda p: {"total": 1, "files": [str(p)], "names": []},
    )
    name = "J.K. Rowling"  # 拉丁名 → 回填能产生派生排序名，便于测全链路
    p = pathlib.Path(default_root) / "Book.m4b"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_build_mp4([name]))
    library.invalidate()
    books = library.books()
    assert books, "扫描应产出至少一本"
    return name


# ---------------- 扫描落盘 ----------------

def test_扫描_提取演播者并落盘(narrator_fixture):  # noqa: ARG001
    bs = library.narrator_books(narrator_fixture)
    assert len(bs) == 1
    assert narrator_fixture in (bs[0].get("narrators") or [])


def test_聚合_按册数降序(narrator_fixture, default_root, monkeypatch):  # noqa: ARG001
    import novelforge.core.audio as audio_mod
    # 再加两本同名演播者的书，验证聚合按册数排序
    monkeypatch.setattr(
        audio_mod, "tracks",
        lambda p: {"total": 1, "files": [str(p)], "names": []},
    )
    for i in range(2):
        p = pathlib.Path(default_root) / f"Book{i}.m4b"
        p.write_bytes(_build_mp4([narrator_fixture]))
    library.invalidate()
    listing = library.narrators_list()
    entry = next(x for x in listing if x["name"] == narrator_fixture)
    assert entry["count"] == 3


# ---------------- 排序名回退链（纯逻辑，直接操作表行）----------------

def test_排序名回退链_本地覆盖优先于在线(isolated):  # noqa: ARG001
    db.set_narrator_sort_name_local("某人", "Local Name")
    db._connect().execute(
        "UPDATE narrators SET sort_name=? WHERE name=?", ("Online Name", "某人"))
    db._connect().commit()
    assert narrators_mod.sort_name_of(db.get_narrator("某人")) == "Local Name"
    info = narrators_mod.effective("某人")
    assert info["sort_name"] == "Local Name"
    assert info["sort_name_overridden"] is True


def test_排序名回退链_无本地覆盖时用在线值(isolated):  # noqa: ARG001
    db._connect().execute(
        "INSERT INTO narrators(name, sort_name) VALUES(?,?)", ("某人", "Online Name"))
    db._connect().commit()
    info = narrators_mod.effective("某人")
    assert info["sort_name"] == "Online Name"
    assert info["sort_name_overridden"] is False


def test_排序名两列全空时为空串_不回退到显示名(isolated):  # noqa: ARG001
    # 只插 name 行（不碰排序名两列），验证「没设排序名」≠「设成和显示名一样」
    db._connect().execute("INSERT INTO narrators(name) VALUES(?)", ("某人",))
    db._connect().commit()
    info = narrators_mod.effective("某人")
    assert info["sort_name"] == ""
    assert info["sort_name_overridden"] is False


def test_无行的演播者也能写入排序名_upsert(isolated):  # noqa: ARG001
    assert db.get_narrator("查无此人") is None
    narrators_mod.set_sort_name("查无此人", "Nobody")
    assert db.get_narrator("查无此人") is not None
    assert narrators_mod.effective("查无此人")["sort_name"] == "Nobody"


def test_撤销覆盖_空串回退到在线(isolated):  # noqa: ARG001
    db.set_narrator_sort_name_local("某人", "x")
    narrators_mod.set_sort_name("某人", "Local Name")
    narrators_mod.set_sort_name("某人", "")
    info = narrators_mod.effective("某人")
    assert info["sort_name"] == ""
    assert info["sort_name_overridden"] is False


def test_排序名首尾空白被裁掉(isolated):  # noqa: ARG001
    narrators_mod.set_sort_name("某人", "  Lu Xun  ")
    assert narrators_mod.effective("某人")["sort_name"] == "Lu Xun"


# ---------------- 回填（只写派生态列）----------------

def test_回填_为无排序名者补派生值(narrator_fixture):  # noqa: ARG001
    # 扫描只落 books.narrators，不写 narrators 表；回填按派生规则补 sort_name
    res = narrators_mod.backfill_sort_names()
    assert res["total"] >= 1
    # 拉丁名 → 派生排序名（"J.K. Rowling" → "Rowling, J.K." 之类）
    row = db.get_narrator(narrator_fixture)
    assert row and row["sort_name"] and row["sort_name"] != narrator_fixture
    # 回填只碰 sort_name 列，绝不动 sort_name_local
    assert row["sort_name_local"] == ""


def test_回填_已有排序名者跳过(narrator_fixture):  # noqa: ARG001
    db.set_narrator_sort_name(narrator_fixture, "预设排序名")
    before = db.get_narrator(narrator_fixture)["sort_name"]
    res = narrators_mod.backfill_sort_names()
    # 已存在 → 跳过，不被覆盖
    assert db.get_narrator(narrator_fixture)["sort_name"] == before
    assert res["filled"] == 0


# ---------------- 接口 ----------------

def test_接口_列表与详情都下发展示名(client, auth_headers, narrator_fixture):
    name = narrator_fixture
    r = client.post(f"/api/narrators/{_quote(name)}/sort-name",
                    json={"sort_name": "Rowling, J.K."}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["sort_name"] == "Rowling, J.K."
    assert r.json()["sort_name_overridden"] is True

    detail = client.get(f"/api/narrators/{_quote(name)}", headers=auth_headers).json()
    assert detail["sort_name"] == "Rowling, J.K."
    assert detail["sort_name_overridden"] is True

    items = {a["name"]: a for a in
             client.get("/api/narrators", headers=auth_headers).json()["items"]}
    assert items[name]["sort_name"] == "Rowling, J.K."


def test_接口_撤销覆盖后列表回落到空(client, auth_headers, narrator_fixture):
    name = narrator_fixture
    client.post(f"/api/narrators/{_quote(name)}/sort-name",
                json={"sort_name": "Rowling, J.K."}, headers=auth_headers)
    r = client.post(f"/api/narrators/{_quote(name)}/sort-name",
                    json={"sort_name": ""}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["sort_name"] == ""
    assert r.json()["sort_name_overridden"] is False


def test_接口_排序名_演播者不存在404(client, auth_headers):
    r = client.post(f"/api/narrators/{_quote('查无此人')}/sort-name",
                    json={"sort_name": "x"}, headers=auth_headers)
    assert r.status_code == 404


def test_接口_排序名_缺字段400(client, auth_headers, narrator_fixture):
    r = client.post(f"/api/narrators/{_quote(narrator_fixture)}/sort-name",
                    json={}, headers=auth_headers)
    assert r.status_code == 400


def test_接口_排序名_未认证401(client, narrator_fixture):
    r = client.post(f"/api/narrators/{_quote(narrator_fixture)}/sort-name",
                    json={"sort_name": "x"})
    assert r.status_code == 401


def test_接口_回填(client, auth_headers, narrator_fixture):  # noqa: ARG001
    r = client.post("/api/narrators/sort-name/backfill", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["total"] >= 1
