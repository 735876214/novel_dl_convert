"""「外部名字 → 磁盘路径」这一层的判据（第 129 期）。

## 为什么必须有这一期

名字是外部输入（``/download/{name:path}`` 的路径、``/api/sources/{name}/...`` 的书源名），
而它不是「业务规则」层面的东西 —— 它要么能落在文件系统里，要么根本落不进去。
改前这条判据**只在规则文件那一侧有**（`sources.rules.rule_name_error`，第 120 期），
另外两头各缺一半：

1. **长度没人判** ⇒ 名字长过 255 字节时 `Path.resolve()` 照样成功，但 `stat()` /
   `is_file()` 抛 `OSError(ENAMETOOLONG)`（`pathlib._ignore_error` 只忽略
   ENOENT / ENOTDIR / EBADF / ELOOP / EINVAL，**不忽略它**）⇒ 「取不到就 404」的写法
   变成 **500**。实测（隔离实例）：`GET /download/<300 个 a>` 、
   `GET|DELETE /api/sources/<300 个 a>/cookie`、`GET /api/sources/<300 个 a>/login-spec`
   四处 500。
2. **Cookie 文件名不判名字** ⇒ `creds.cookie_file()` 只拼路径不看名字，与规则文件那一侧
   不一致：名字里带 `..` 就能把 Cookie 读出 / 写进 / 删掉 `COOKIE_DIR` 之外的文件
   （`status` / `save` / `clear` 三个口子都吃这个名字）。

本文件钉住三件事：长度判据在 `fileops` 的两个入口上、Cookie 路径必须过同一个名字判据、
以及那四个接口**回 4xx / 如实回「没有」**而不是 500。
"""
import pathlib

import pytest

from novelforge.core import fileops
from novelforge.sources import creds


# ---------------- 长度判据（fileops） ----------------

def test_超长名字按字节判而不是按字符判():
    """255 是**字节**上限：85 个汉字（255 字节）刚好放得下，86 个就超了。"""
    assert not fileops.name_too_long("中" * 85)          # 255 字节
    assert fileops.name_too_long("中" * 86)              # 258 字节
    assert fileops.name_too_long("a" * 256)
    assert not fileops.name_too_long("a" * 255)


def test_safe_path_超长名字抛_ValueError_而不是让_is_file_抛_OSError(tmp_path):
    """这是本期的主因：超长名字在 `is_file()` 上抛的是 OSError，接口就变 500 了。"""
    with pytest.raises(ValueError, match="太长"):
        fileops.safe_path("a" * 300)
    with pytest.raises(ValueError, match="太长"):
        fileops.safe_path("系列/" + "b" * 300)


def test_input_path_同一条判据(tmp_path):
    """收书目录那条入口（第 119 期）也得能挡住 —— 它同样会去 stat 这个名字。"""
    with pytest.raises(ValueError, match="太长"):
        fileops.input_path("a" * 300, base=tmp_path)


def test_正常名字照旧可用(tmp_path):
    """别把判据做过头：中文长名、两层路径都照旧。"""
    p = fileops.input_path("子目录/三体（第二部）.epub", base=tmp_path)
    assert p.name == "三体（第二部）.epub"


# ---------------- 名字判据（creds） ----------------

def test_cookie_路径必须过书源名判据(tmp_path, monkeypatch):
    """Cookie 文件名与规则文件名是**同一类东西**（书源名当文件名），判据只能有一份。

    ``..`` / 分隔符 / 前导点 / 超长 ⇒ 一律 ``ValueError``（写 / 删路径上当场拒）。
    """
    monkeypatch.setattr(creds, "cookie_dir", lambda: pathlib.Path(tmp_path))
    for bad in ("../x", "a/b", "..", ".hidden", "a" * 300, "", "   "):
        with pytest.raises(ValueError):
            creds.cookie_file(bad)
    # 合法的名字照旧：落在 cookie 目录里、带后缀
    f = creds.cookie_file(" 正常源 ")
    assert f.parent == pathlib.Path(tmp_path)
    assert f.name == "正常源.cookies.txt"


def test_名字非法时_status_如实回没有而不抛(tmp_path, monkeypatch):
    """读路径上非法名 = 不存在（与 `rules.rule_file_exists` 同口径）：查登录态不该 500。"""
    monkeypatch.setattr(creds, "cookie_dir", lambda: pathlib.Path(tmp_path))
    for bad in ("../x", "a" * 300):
        st = creds.status(bad)
        assert st["has"] is False
        assert st["domains"] == [] and st["names"] == []
        assert creds.clear(bad) is False


def test_合法名字的_status_与_clear_照旧工作(tmp_path, monkeypatch):
    monkeypatch.setattr(creds, "cookie_dir", lambda: pathlib.Path(tmp_path))
    st = creds.save("正常源", "sid=abc; Domain=.example.com", [])
    assert st["has"] is True and st["count"] == 1
    assert creds.clear("正常源") is True
    assert creds.status("正常源")["has"] is False


# ---------------- 接口层：不许 500 ----------------

def test_下载接口超长名回_400(client, auth_headers):
    """`/download/{name:path}` 直接把它当路径 stat ⇒ 改前 500，现在 400 且说清原因。"""
    r = client.get("/download/" + "a" * 300, headers=auth_headers)
    assert r.status_code == 400
    assert "太长" in r.text


def test_书源登录态三个接口对超长名不再_500(client, auth_headers):
    """四处 500 里的三处：GET/DELETE cookie 与 GET login-spec。"""
    name = "a" * 300
    r = client.get(f"/api/sources/{name}/cookie", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["has"] is False
    r = client.delete(f"/api/sources/{name}/cookie", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["cleared"] is False
    r = client.get(f"/api/sources/{name}/login-spec", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["cookie"]["has"] is False


def test_保存_Cookie_时名字非法回_400_而不是写进别处(client, auth_headers):
    """写路径上必须当场拒（这条同时钉住「不会写到 COOKIE_DIR 之外」）。"""
    r = client.post("/api/sources/" + "a" * 300 + "/cookie",
                    json={"text": "sid=abc; Domain=.example.com"}, headers=auth_headers)
    assert r.status_code == 400
    assert "太长" in r.text
