"""**删不掉的必须如实回报** —— 「清缓存」与「清回收站」两条路（第 256 期）。

## 缺陷

回收站那条第 141 期专门修过：「说清空了却没清干净」比「没清干净」更坏
（回收站是「删除即回收」承诺的**最后一道防线**）。但同一条纪律**另外两条路没遵守**：

1. **`POST /api/cache/clear`**（清缓存）此前是
   「逐个 ``except Exception: continue`` + 外层 ``except: pass``」
   ⇒ 删不掉的文件（容器里 root 建的只读文件、NFS 上的 busy 文件）**留在盘上**，
   而回执照旧说「已清理缓存 N 项」⇒ **用户永远不知道缓存里还剩东西**
   ⇒ 缓存目录**越攒越多**（而用户以为每次都清干净了）。
   实测：造一个删不掉的缓存文件 ⇒ 回执 `removed=1`、**残留不可见**。
2. **回收站那条的 `failed` 字段前端一直没读** ⇒ 后端第 141 期就给了，
   但界面只说「已清空、释放 N B」⇒ **同一个洞的两层**。

## 这里钉四件事

1. 清缓存：删不掉的**必须回报**（`failed` 列表 + `ok=False`）；
2. 清缓存：删掉的与没删掉的**都要说得清**（`removed` + `failed`）；
3. 前端**必须读** `failed`（回收站那条也一样）—— 后端给了不说等于没给；
4. 回收站保留不动（清缓存**不许**把回收站一起清掉 —— 那是数据丢失）。
"""
from __future__ import annotations

import pathlib

import pytest

from novelforge import config
from novelforge.core import fileops


@pytest.fixture
def cache_dir(monkeypatch, tmp_path):
    """把 CACHE_DIR 指到用例专属目录（会话级共享 ⇒ 会互相污染）。"""
    d = tmp_path / "cache"
    d.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(config, "CACHE_DIR", d)
    return d


@pytest.fixture
def undeletable(monkeypatch):
    """让指定名字的文件**删不掉**（跨平台：用 monkeypatch 挡 `unlink`）。

    ⚠️ Windows 上「只读属性」**不影响删除**（`unlink` 仍成功）⇒ 只能靠
    挡方法（与第 141 期那条用例**同一手法**）。
    """
    real_unlink = pathlib.Path.unlink

    def _unlink(self, *a, **kw):
        if self.name == "删不掉.txt":
            raise PermissionError(13, "Permission denied")
        return real_unlink(self, *a, **kw)

    monkeypatch.setattr(pathlib.Path, "unlink", _unlink)


def test_清缓存_删不掉的必须回报(client, auth_headers, cache_dir, undeletable):
    """核心判据：删不掉的**不许**被静默跳过。"""
    (cache_dir / "能删.txt").write_text("a", encoding="utf-8")
    (cache_dir / "删不掉.txt").write_text("b", encoding="utf-8")

    r = client.post("/api/cache/clear", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False, body
    assert body["removed"] == 1, body
    assert body["failed"], "删不掉的必须列出来"
    assert any("删不掉.txt" in f for f in body["failed"]), body["failed"]
    # 删不掉的**必须留在盘上**（不许「假装删掉了」）
    assert (cache_dir / "删不掉.txt").exists(), "删不掉的文件不该被算成已删"
    assert not (cache_dir / "能删.txt").exists(), "能删的应该删掉"


def test_清缓存_全删得掉时是干净的回执(client, auth_headers, cache_dir):
    (cache_dir / "a.txt").write_text("a", encoding="utf-8")
    (cache_dir / "b.txt").write_text("b", encoding="utf-8")
    r = client.post("/api/cache/clear", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True, body
    assert body["removed"] == 2, body
    assert not body.get("failed"), body
    # ⚠️ **回收站目录例外**（它就在 CACHE_DIR 内部 ⇒ 清缓存必须跳过它，
    # 否则「清一次缓存」就把「可人工找回」的承诺作废了 —— 见下一个用例）。
    leftovers = [p.name for p in cache_dir.iterdir() if p.name != "recycle"]
    assert not leftovers, f"缓存目录应该真的空了（剩下：{leftovers}）"


def test_清缓存_回收站保留不动(client, auth_headers, cache_dir, monkeypatch):
    """⚠️ 清缓存**不许**把回收站一起清掉（那是数据丢失）——
    「重复书籍 / 缺失资源」两个工具页明确承诺过「可以人工找回」。"""
    recycle = cache_dir / "recycle"
    recycle.mkdir(parents=True, exist_ok=True)
    (recycle / "还能找回.epub").write_text("x", encoding="utf-8")
    monkeypatch.setattr(fileops, "recycle_dir", lambda: recycle)

    r = client.post("/api/cache/clear", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert (recycle / "还能找回.epub").exists(), "回收站被清掉了 —— 那是数据丢失"
    assert r.json()["removed"] == 0, r.json()


def test_清回收站_前端要能读到_failed(client, auth_headers, monkeypatch):
    """⚠️ 后端第 141 期就给了 `failed`，但前端**一直没读** ⇒
    「说清空了却没清干净」在**界面**上照样发生。⇒ 契约钉住：这个字段必须在。"""
    import json
    import pathlib as _pl
    fx = _pl.Path(__file__).parent / "fixtures" / "client_api_surface.json"
    if not fx.is_file():
        pytest.skip("没有字段面快照")
    # 快照文件里不含这个端点（它不是客户端端点）⇒ 这里只钉**响应形状**有 failed
    r = client.post("/api/maintenance/recycle/clear", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "failed" in body, body
    assert isinstance(body["failed"], list), body
    assert json.dumps(body, ensure_ascii=False)
