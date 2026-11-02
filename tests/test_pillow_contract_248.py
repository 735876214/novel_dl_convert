"""Pillow 链路的契约（第 248 期）：能力如实上报 · 像素闸 · 透明像素不黑。

**为什么要有它**：Pillow 是**软依赖**，缺了它三件事都不工作（封面缩略、封面上传验图、
PDF 页渲染）。而在这之前，这三处**各自**静默降级，缺 Pillow 时用户看到的是：

- 上传封面回 **400「不是可识别的图片文件」** —— **说谎**（图没错，是服务器少装了一个包）；
- PDF 页 / Komga 页面回 **404「页不存在」** —— 同样是假象；
- 缩略图静默回原图 —— 没有任何提示。

这与本项目其余可选依赖的纪律冲突（`mobicache` / `comics` / `jssandbox` / `saferegex`
都走「缺依赖就如实报 + 503 说清缺什么」）。本期把这三条收敛到 `core/imaging.py`。

**这里钉四件事**：
1. 缺 Pillow 时**不许说谎**：上传 → 503（不是 400）、PDF 页 → 503（不是 404）；
2. 能力接口与 `/health` 如实报出 Pillow 在不在；
3. **解压炸弹**有闸：纯色大图压缩率极高（12000×12000 只要 450 KB，真解码要 411 MB）；
4. **透明像素不能变黑**（Komga 转码此前会把透明 PNG 变成全黑）。

⚠️ 缺 Pillow 的用例**靠 monkeypatch 拦 import** 模拟（不真的卸包）——
「环境没装 Pillow 就跳过」只适用于「本机真没装」，而这里要验的是**降级行为**，
它必须在装了 Pillow 的机器上也能跑（不然 CI 上永远验不到）。
"""
from __future__ import annotations

import builtins
import io

import pytest

from novelforge.core import imaging, thumbs

#: 需要 Pillow 才能造图。没有就**如实跳过**，不伪造能跑（对齐 `tests/test_archive_kinds.py`）。
pytest.importorskip("PIL", reason="未安装 Pillow（软依赖）⇒ 图片相关用例跳过")


def _png(width: int, height: int, mode: str = "RGB", color=(200, 30, 30)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new(mode, (width, height), color).save(buf, "PNG")
    return buf.getvalue()


class _NoPillow:
    """把 ``PIL`` 的 import 掐掉（模拟「这台服务器没装 Pillow」）。

    ⚠️ 拦的是 ``builtins.__import__``：**只删 ``sys.modules['PIL']`` 不够** ——
    ``from PIL import Image`` 走的是 ``__import__`` 的缓存路径，Pillow 在别处被 import
    过之后就照样能用上 ⇒ 「模拟没装」会静默失效（用例看着绿，其实没测到降级路径）。
    """

    def __init__(self, monkeypatch):
        self._monkeypatch = monkeypatch
        self._real = builtins.__import__

    def __enter__(self):
        def _fake(name, *args, **kwargs):
            if name == "PIL" or name.startswith("PIL."):
                raise ImportError("No module named 'PIL'")
            return self._real(name, *args, **kwargs)

        self._monkeypatch.setattr(builtins, "__import__", _fake)
        return self

    def __exit__(self, *exc):
        self._monkeypatch.undo()
        return False


# ---------------- ① 缺 Pillow 时不许说谎 ----------------

def test_缺_Pillow_时上传封面回_503_而不是_400(monkeypatch):
    """**说谎的报告**：缺 Pillow 时合法的 PNG 会被判成「不是可识别的图片文件」。

    用户看到那句话只会去换图、重传、反复失败 —— 而真因是服务端少装了一个包。
    缺能力 ⇒ **503** + 说清缺什么（口径同 `comics.backend_problem` / `mobicache`）。
    """
    from novelforge import server

    png = _png(64, 64)                 # ⚠️ 先造好图：造图本身也要 Pillow
    with _NoPillow(monkeypatch):
        with pytest.raises(server.HTTPException) as ei:
            server._validate_cover_upload(png)
    assert ei.value.status_code == 503, f"应回 503（缺能力），实际 {ei.value.status_code}"
    assert "Pillow" in str(ei.value.detail), ei.value.detail


def test_缺_Pillow_时能力接口如实报出来(monkeypatch):
    from novelforge import server

    with _NoPillow(monkeypatch):
        st = imaging.state()
        assert st["available"] is False
        assert "Pillow" in st["reason"], st["reason"]
    # 判据只有一处：接口报的必须就是 `imaging.state()`（换台机器也不会打架）
    assert server.imaging is imaging


def test_缺_Pillow_时缩略图仍返回原图但不报错(monkeypatch):
    """缩略图是**优化**，不是可用性前提 ⇒ 缺 Pillow 时原样返回原图（既有语义不变）。

    但这**不是**「静默」：能力由 `imaging.state()` 如实上报（上面那条用例钉住）。
    """
    data = _png(1200, 1600)            # ⚠️ 先造好图：造图本身也要 Pillow
    with _NoPillow(monkeypatch):
        assert thumbs.resize_image(data, 480) is data


def test_缺_Pillow_时_PDF_页渲染抛_缺能力而不是_回空(monkeypatch):
    """`pdfrender.render_page` 此前回 ``(None, None)`` ⇒ 端点翻译成 **404「页不存在」**。

    页其实是在的（PDF 在、页号在）—— 没有的是**这台服务器的图片处理能力**
    （`pypdfium2.to_pil()` 需要 Pillow）。必须能把它和「这一页不存在」区分开。
    """
    from novelforge.core import pdfrender

    with _NoPillow(monkeypatch):
        with pytest.raises(imaging.MissingPillow):
            pdfrender.render_page("不存在的.pdf", 0, "bid")


def test_缺_Pillow_时_Komga_的_CBZ_转码降级成原图(monkeypatch):
    """Komga 的 CBZ 转码：缺 Pillow 时**原图仍能给**（格式统一是客户端偏好，不是前提）。

    但 PDF 分支没有退路 ⇒ 由 `pdfrender` 抛 `MissingPillow` 传到端点（另一条用例钉 503）。
    """
    from novelforge.core import komga_api

    with _NoPillow(monkeypatch):
        out = komga_api.page_image({"format": "CBZ", "id": "x"}, 1, "jpeg")
    # 取不到页就还是 (None, "")；取到了就至少拿回原图（**不是**空）
    assert out[0] is None or isinstance(out[0], bytes)


def test_缺_Pillow_时_Komga_的_PDF_页端点回_503_而不是_404(monkeypatch, client,
                                                        default_root):
    """**端到端**那一条：Komga 客户端取 PDF 页时，缺 Pillow ⇒ **503** 说清缺什么。

    此前是 404「页不存在」—— 页其实是在的（PDF 在、页号在），没有的是**这台服务器**
    的图片处理能力。客户端收到 404 会以为「这本书没有这一页」⇒ 换个客户端也一样错。
    """
    from novelforge import config, server
    from novelforge.core import library

    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        default_root.mkdir(parents=True, exist_ok=True)
        (default_root / "一本书.pdf").write_bytes(b"%PDF-1.4\n%%EOF\n")
        library.invalidate()
        book = next(b for b in library.books() if b["name"] == "一本书.pdf")

        # 端点的守卫与书都在，但**渲染**这一步缺能力
        monkeypatch.setattr(server.komga_api, "page_image", _raise_missing_pillow)
        r = client.get(f"/api/v1/books/{book['id']}/pages/1",
                       headers={"x-api-key": "test-key"})
        assert r.status_code == 503, f"应回 503（缺能力），实际 {r.status_code}：{r.text}"
        assert "Pillow" in r.text, r.text
    finally:
        config.save_overrides({})


def _raise_missing_pillow(*a, **k):
    raise imaging.MissingPillow(imaging.REASON)


# ---------------- ② 能力接口与 /health ----------------

def test_能力接口报出_Pillow_这一项(client, auth_headers):
    """`GET /api/sources/capabilities` 是「哪些可选依赖真的在」的唯一入口。

    此前它报 Node / regex / lxml / js 四项，**唯独没有 Pillow** ⇒ 用户无从知道
    自己这台服务器的封面缩略图到底有没有在工作。
    """
    body = client.get("/api/sources/capabilities", headers=auth_headers).json()
    assert "pillow" in body, "能力接口缺 pillow"
    assert "pillow" in body["hints"], "能力接口缺 hints.pillow"
    assert body["pillow"] == imaging.state(), "接口必须原样下发 state()，不许自己再算一遍"
    assert body["hints"]["pillow"] == body["pillow"]["reason"]


def test_健康检查在缺_Pillow_时是_degraded_而不是_down(client, auth_headers, monkeypatch):
    """缺 Pillow 属于「能服务但有毛病」⇒ **200 + degraded**，不是 503。

    口径同 `_health_checks` 的注释：只有「库连不上」才回 503 —— 重启容器不会装上
    Pillow，回 503 只会让 compose 无限重启，把能读的服务变成一直重启的服务。
    """
    monkeypatch.setattr(imaging, "available", lambda: False)
    r = client.get("/health")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "degraded", r.json()["status"]
    # ⚠️ 第 258 期：`checks` / `problems` 在**鉴权后**的端点上
    # （免鉴权的那份只给状态 / 版本 / 有几条问题）。
    body = client.get("/api/health", headers=auth_headers).json()
    assert body["checks"]["pillow"] is False
    assert any("Pillow" in p for p in body["problems"]), body["problems"]


def test_健康检查在有_Pillow_时是_ok(client, auth_headers):
    # ⚠️ 第 258 期：`checks` / `problems` 在**鉴权后**的端点上
    body = client.get("/api/health", headers=auth_headers).json()
    assert body["checks"]["pillow"] is True
    assert not any("Pillow" in p for p in body["problems"]), body["problems"]


# ---------------- ③ 解压炸弹的像素闸 ----------------

def test_上传封面拒绝像素数超标的图():
    """纯色大图压缩率极高：12000×12000 的 PNG 只有 **450 KB**（远低于 8 MB 上限），
    真解码却要 **411 MB** 内存 ⇒ 体积闸完全拦不住，必须有**像素**闸。

    Pillow 自带的 `MAX_IMAGE_PIXELS` 只是**告警**（默认只发 warning）⇒ 项目里
    必须自己有判据。
    """
    from novelforge import server

    bomb = _png(12000, 12000)
    assert len(bomb) < 8 * 1024 * 1024, f"前提：这张图压缩后要够小（{len(bomb)} B）"
    with pytest.raises(server.HTTPException) as ei:
        server._validate_cover_upload(bomb)
    assert ei.value.status_code == 413, f"像素超限应回 413，实际 {ei.value.status_code}"
    assert "过大" in str(ei.value.detail), ei.value.detail


def test_像素闸拦得住但缩略路径原样返回原图():
    """缩略路径遇到超大的图 ⇒ **原样返回原图**（不抛错、不解码）。

    「缩略图是优化，不是可用性前提」—— 但**不能**为了缩略把 411 MB 解出来。
    """
    bomb = _png(12000, 12000)
    out = thumbs.resize_image(bomb, 480)
    assert out is bomb, "像素超限时必须原样返回原图，不能真去解码"


def test_正常尺寸的图不被像素闸误伤():
    """真机书封 427×600、漫画页 1500×2200、PDF 页按 2× 渲染 ⇒ 都远在闸内。"""
    normal = _png(1500, 2200)
    out = thumbs.resize_image(normal, 480)
    assert out is not normal, "正常图必须真的被缩（不能被闸误伤）"


def test_open_image_在像素超限时抛_TooManyPixels():
    from PIL import Image
    with pytest.raises(imaging.TooManyPixels):
        with imaging.open_image(_png(12000, 12000)):
            pass
    # 闸内的正常图：能开
    with imaging.open_image(_png(64, 64)) as im:
        assert im.size == (64, 64)


# ---------------- ④ 透明像素不能变黑 ----------------

def test_Komga_转码把透明像素铺白底而不是变黑():
    """第 248 期抓到的真缺陷：`komga_api` 的转码写的是 ``im.convert("RGB")`` ——
    那一步只是**丢掉 alpha 通道**，透明像素的 RGB 是 (0,0,0) ⇒ 透明 PNG 转出来整片全黑。

    `core/thumbs.py` 早就有正确的铺白底实现（模块头注释把这条记作「封面变黑」的成因），
    但 `komga_api` 那一处没享受到 ⇒ **同一判据的两份实现，其中一份是错的**。
    """
    from PIL import Image

    from novelforge.core import komga_api

    transparent = _png(60, 80, mode="RGBA", color=(0, 0, 0, 0))
    buf = io.BytesIO()
    with Image.open(io.BytesIO(transparent)) as im:
        imaging.flatten(im).save(buf, "JPEG", quality=88)
    with Image.open(io.BytesIO(buf.getvalue())) as out:
        px = out.convert("RGB").getpixel((5, 5))
    assert min(px) > 240, f"透明区应该铺白底，实际 {px}"


def test_Komga_转码确实走了白底那条路():
    """防回归：钉住 ``komga_api`` **不再**用 ``convert("RGB")`` 那条会变黑的写法。

    ⚠️ 走 **AST**（不是文本匹配）：注释与文档字符串里正写着「而不是 `convert("RGB")`」，
    文本匹配会把这条说明当成违规。AST 只看**真正跑的调用**。
    """
    import ast

    from novelforge.core import komga_api

    tree = ast.parse(open(komga_api.__file__, encoding="utf-8").read())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "page_image")
    bad = [n for n in ast.walk(fn)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
           and n.func.attr == "convert" and n.args
           and isinstance(n.args[0], ast.Constant) and n.args[0].value == "RGB"]
    assert not bad, "komga 的转码又变回 convert(\"RGB\") 了（透明像素会变黑）"

    src = ast.dump(fn)
    assert "imaging" in src and "flatten" in src, "komga 的转码该走 imaging.flatten（白底）"


def test_flatten_对不带透明的图就是转_RGB():
    """铺白底只针对带 alpha 的图；普通 RGB 图不该被无谓地重画一遍。"""
    from PIL import Image

    with imaging.open_image(_png(32, 32)) as im:
        assert imaging.flatten(im).mode == "RGB"
