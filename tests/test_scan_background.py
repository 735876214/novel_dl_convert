"""第 88 期：把「脏库刷新」移出请求路径 + 扫描状态可见 + 导入标脏。**零外网**。

本文件钉的是**语义**而不是实现细节，四条主线：

1. **脏库请求不阻塞**：索引已存在、库被标脏时，读请求只**派**一次后台刷新，
   自己拿到现有索引就返回 —— 请求线程**绝不**扫盘（库在 NAS 上时那就是「打开书库
   要等几十秒」的根因）。这里用「把 ``_refresh_locked`` 换成会长时间阻塞的桩」
   把后台按在原地，再断言请求耗时远小于那个阻塞时长、且响应如实标出「这个库正在扫」。
2. **后台扫完能看到新条目**：派活之后等它收干净（``wait_pending``），下一次读必须
   看到新文件 —— 否则「刷新被派了但结果永远看不到」这种缺陷没有任何界面表现。
3. **冷启动（索引为空）仍拿得到数据**：库从没扫过时**同步**扫（否则用户打开书库
   什么都看不到）。这条按实现语义断成「同步」——**不写**「同步或异步都行」那种
   永远绿的含糊断言。
4. **``/convert`` / ``/convert-path`` 真的调了 ``invalidate``**：此前漏了，于是刚导入
   的书要等监听线程的全量兜底（默认 60s）才出现。用 monkeypatch **计数**钉住，
   不能只看库后来脏没脏（那只证明「某处标了脏」）。

测试纪律（本仓实测踩过的坑，照抄 ``tests/conftest.py`` 的说明）：

- 碰书库 / DB 的用例一律声明 ``isolated``（经 ``default_root`` / ``client`` 等夹具间接依赖）；
- ``bytes`` 字面量只能是 ASCII（要中文就 ``"…".encode("utf-8")``）；
- 往 ``default_root`` 写文件前先 ``mkdir(parents=True, exist_ok=True)``；
- **绝不让后台线程在测试里真等** —— 用 ``threading.Event`` 精确控制何时放行，
  并**一定**在 ``finally`` 里放行 + ``wait_pending``，否则整个 pytest 会被拖住。
"""
import pathlib
import threading
import time

import pytest

from novelforge import config
from novelforge.core import catalog, library, library_rules, pipeline


def _put(root: pathlib.Path, name: str) -> pathlib.Path:
    """往库根放一本占位书（扫描只按扩展名收书，不需要真 EPUB）。"""
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    p.write_bytes(b"EPUB")
    return p


def _books(lid: str) -> set:
    """当前书目里的 ``name`` 集合。"""
    return {b["name"] for b in library.books(lid)}


# ---------------------------------------------------------------------------
# ① 脏库请求不阻塞 + 响应标出「正在建立索引」
# ---------------------------------------------------------------------------

def test_脏库请求不阻塞且标出正在扫(default_root, test_lib_id, monkeypatch):
    """索引已存在、库被标脏 ⇒ 读请求**不扫盘、不被拖住**，且响应 ``scanning`` 含该库。

    「不扫盘」用一个**会长时间阻塞**的 ``_refresh_locked`` 桩来证明：真在请求线程里
    扫盘的话，这次请求必然被那个桩按住（本用例就红）。这是唯一能在功能测试里钉住
    「没有做某件昂贵的事」的手法（与 ``test_catalog`` 里「换成会爆炸的桩」同源）。
    """
    lid = test_lib_id
    _put(default_root, "第一本.epub")
    # 冷启动第一次：索引为空 ⇒ 同步扫（不经过后台，所以可以放心在下面替换 _refresh_locked）
    assert _books(lid) == {"第一本.epub"}

    # 从这里起，后台刷新会被按在这个 Event 上（10 秒 = 「NAS 上一轮刷新要很久」的替身）
    release = threading.Event()

    def _blocked(lib, force):                      # noqa: ARG001 —— 桩掉的正是「扫盘」那一步
        release.wait(10)
        return {"scanned": 0, "added": 0, "removed": 0, "unchanged": 0, "skipped": False}

    monkeypatch.setattr(catalog, "_refresh_locked", _blocked)

    _put(default_root, "第二本.epub")
    library.invalidate(lid)                        # 写操作之后照例标脏
    assert catalog._needs_refresh(lid) is True, "标脏之后没被判成脏"

    try:
        t0 = time.monotonic()
        library.books(lid)                         # 请求路径：只派后台、自己不扫
        dt = time.monotonic() - t0
        assert dt < 1.0, f"脏库的读被后台刷新拖住了 {dt:.3f}s（请求线程在扫盘）"

        # 等后台**真的**进入扫描（`_scan_begin` 在 `refresh_library` 里、`_refresh_locked` 之前）
        deadline = time.monotonic() + 3.0
        while lid not in catalog.scanning_libraries() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert lid in catalog.scanning_libraries(), "后台刷新没被标记成「正在扫」"

        # 再读一次：仍然不阻塞，且这一次**【确定】**能看到 scanning 里含该库
        t0 = time.monotonic()
        library.books(lid)
        dt = time.monotonic() - t0
        assert dt < 1.0, f"脏库的读被拖住了 {dt:.3f}s"
        assert lid in catalog.scanning_libraries()
    finally:
        release.set()                              # 一定放行：后台线程不许在测试里真等
        assert catalog.wait_pending(5.0) == 0, "后台刷新没收干净（收尾纪律）"


def test_books接口的扫描中字段(client, auth_headers, default_root, test_lib_id):
    """``GET /api/books`` 的响应**新增** ``scanning`` 字段，且是「正在扫的库 id 列表」。

    只要**追加**、不改既有字段（向后兼容）：``items`` / ``total`` 照旧还在。
    这里不打桩（真让后台扫完），只钉字段**形状**。
    """
    _put(default_root, "甲.epub")
    r = client.get("/api/books", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body
    assert isinstance(body.get("scanning"), list), "GET /api/books 缺 scanning 字段或类型不对"
    assert set(body["scanning"]).issubset({str(x) for x in body["scanning"]})
    assert catalog.wait_pending(5.0) == 0


# ---------------------------------------------------------------------------
# ② 后台刷新跑完后，下一次读能看到新条目
# ---------------------------------------------------------------------------

def test_后台刷新完成后下一次读能看到新条目(default_root, test_lib_id):
    """派活 → 等它收干净 → 下一次读必须看到新书（``added`` 生效）。"""
    lid = test_lib_id
    _put(default_root, "第一本.epub")
    assert _books(lid) == {"第一本.epub"}          # 冷启动：同步扫

    _put(default_root, "第二本.epub")
    library.invalidate(lid)
    library.books(lid)                             # 脏库：派后台刷新（本请求可能仍是旧索引）
    assert catalog.wait_pending(5.0) == 0, "后台刷新没收干净"
    assert _books(lid) == {"第一本.epub", "第二本.epub"}, "后台刷新跑完了，新书还是看不见"


# ---------------------------------------------------------------------------
# ③ 冷启动（索引为空）仍能拿到数据 —— **同步**扫，按实现语义断言
# ---------------------------------------------------------------------------

def test_冷启动索引为空时同步扫出数据(default_root, test_lib_id):
    """库从没扫过（``book_index`` 里没有行）⇒ ``_settle`` **同步**扫，本次就读得到。

    为什么必须是同步：异步的话「打开一个新库」会先是空书架、几百毫秒后才出现书 ——
    对用户就是「我加的库是空的？」。所以这条**不能**写成「同步或异步都行」的含糊断言：
    这里同时钉住「本次就有数据」与「**没有**派出后台刷新」。
    """
    lid = test_lib_id
    _put(default_root, "唯一一本.epub")

    assert catalog._index_has_rows(lid) is False, "用例前提不成立：冷启动前索引应非空（空）"
    assert _books(lid) == {"唯一一本.epub"}, "冷启动没同步扫出来（用户会看到空书架）"
    assert catalog._index_has_rows(lid) is True
    # 同步那条路不会派后台线程 —— 没有「扫一半、读一半」的窗口
    assert catalog.wait_pending(5.0) == 0
    st = catalog.scan_state(lid)
    assert st["scanning"] is False


# ---------------------------------------------------------------------------
# ④ 导入接口确实标脏（/convert 与 /convert-path）
# ---------------------------------------------------------------------------

def _stub_convert(monkeypatch, default_root, lid):
    """把导入链路里「与库无关」的两头换成桩，只留下「标不标脏」这一点被观察。

    换了三处（都在**被测代码之外**，不改被测行为）：
      · ``library_rules.target_root`` 直接给库根 —— 免去构造「来源子目录名 / 格式 / 关键词」
        这套路由所需的目录布局（与本用例要钉的「标脏」无关）；
      · ``library_rules.library_id_of_root`` 直接给库 id（同上）；
      · ``pipeline.dispatch`` 假装复制成功（返回 ``("copy", 落点)``）—— 真去复制一本书
        会去动会话级 INPUT_DIR，且与「标脏」无关。
    只把 ``library.invalidate`` 包一层**计数**：要看的就是「到底调没调、带的是哪个库」。
    """
    dst = _put(default_root, "导入.epub")
    monkeypatch.setattr(library_rules, "target_root", lambda **kw: pathlib.Path(default_root))
    monkeypatch.setattr(library_rules, "library_id_of_root", lambda root: lid)
    monkeypatch.setattr(pipeline, "dispatch",
                        lambda src, out_dir, opts: ("copy", dst))
    calls = []
    real = library.invalidate
    monkeypatch.setattr(library, "invalidate",
                        lambda library_id=None: (calls.append(library_id), real(library_id))[1])
    return calls


def test_convert入库后标脏(client, auth_headers, default_root, test_lib_id, monkeypatch):
    """``POST /convert`` 成功入库后必须 ``library.invalidate(<该库>)``。

    此前漏了这一句：刚导入的书不入索引，只能等监听线程的全量兜底（默认 60s）——
    这就是「导入后要等很久」。用计数钉住「**真的调了**」，而不是「库后来脏没脏」。
    """
    calls = _stub_convert(monkeypatch, default_root, test_lib_id)
    r = client.post("/convert", data={"traditionalize": "false"},
                    files={"file": ("导入.epub", b"EPUB")}, headers=auth_headers)
    assert r.status_code == 200, r.text
    assert calls == [test_lib_id], f"入库后没按库标脏（实际调用：{calls}）"
    assert catalog.wait_pending(5.0) == 0


def test_convert_path入库后标脏(client, auth_headers, default_root, test_lib_id, monkeypatch):
    """``POST /convert-path`` 与 ``/convert`` 同口径 —— 成功入库后标脏。"""
    calls = _stub_convert(monkeypatch, default_root, test_lib_id)
    # /convert-path 读的是 INPUT_DIR 下的相对路径：先真放一个文件（它是「来源」不是库文件）
    src = pathlib.Path(config.INPUT_DIR)
    src.mkdir(parents=True, exist_ok=True)
    (src / "来源.epub").write_bytes(b"EPUB")

    r = client.post("/convert-path", data={"path": "来源.epub", "traditionalize": "false"},
                    headers=auth_headers)
    assert r.status_code == 200, r.text
    assert calls == [test_lib_id], f"入库后没按库标脏（实际调用：{calls}）"
    assert catalog.wait_pending(5.0) == 0


# ---------------------------------------------------------------------------
# ⑤ scan_state / scan-state 的字段形状（前端契约）
# ---------------------------------------------------------------------------

_STATE_FIELDS = {"library_id", "name", "scanning", "started_at", "finished_at",
                 "seconds", "added", "removed", "scanned", "error"}


def test_scan_state字段形状(client, auth_headers, default_root, test_lib_id):
    """``catalog.scan_state`` 与 ``GET /api/libraries/scan-state`` 的字段都要稳定。

    前端那一路靠这组字段：``scanning`` 决定显不显示「正在建立索引…」，
    ``seconds`` / ``added`` / ``removed`` 是「上次扫成什么样」。
    """
    _put(default_root, "书.epub")
    # ⚠️ 必须先标脏：`client` 夹具起过一次 lifespan，启动预热已经把这个（当时还是空的）
    # 库扫过一遍 ⇒ 不标脏的话 `_needs_refresh` 为假、这次读根本不会重扫，状态里全是 0。
    library.invalidate(test_lib_id)
    library.books(test_lib_id)                     # 触发一次真刷新，状态才有「上次结果」
    assert catalog.wait_pending(5.0) == 0, "刷新没收干净"

    # 单库形状（catalog.scan_state(lid)）
    st = catalog.scan_state(test_lib_id)
    assert _STATE_FIELDS.issubset(set(st)), f"单库状态缺字段：{_STATE_FIELDS - set(st)}"
    assert st["library_id"] == test_lib_id
    assert st["scanning"] is False                 # 同步扫已结束
    assert st["scanned"] >= 1

    # 聚合形状（catalog.scan_state()）
    agg = catalog.scan_state()
    assert set(agg) == {"items", "scanning"}
    assert agg["items"] and _STATE_FIELDS.issubset(set(agg["items"][0]))
    assert isinstance(agg["scanning"], list)

    # HTTP 形状
    r = client.get("/api/libraries/scan-state", headers=auth_headers)
    assert r.status_code == 200, r.text
    j = r.json()
    assert set(j) == {"items", "scanning"}
    item = next((x for x in j["items"] if x["library_id"] == test_lib_id), None)
    assert item is not None, "scan-state 没列出本用例的库"
    assert _STATE_FIELDS.issubset(set(item))
    assert item["scanning"] is False

    # 未扫过的库给零值而不是缺字段
    empty = catalog.scan_state("这不是一个库")
    assert _STATE_FIELDS.issubset(set(empty))
    assert empty["scanning"] is False and empty["scanned"] == 0


def test_scan_state_单库与聚合一致(client, auth_headers, default_root, test_lib_id):
    """``scan_state(lid)`` 与聚合 ``items`` 里的同一库必须一致（同一个真值源）。"""
    _put(default_root, "书.epub")
    library.books(test_lib_id)
    one = catalog.scan_state(test_lib_id)
    agg = next(x for x in catalog.scan_state()["items"] if x["library_id"] == test_lib_id)
    assert one == agg
