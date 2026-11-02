"""封面缩略图（第 152 期立，第 208 期改编码）：`?w=` 的纯函数与端点契约。

**为什么要它**：封面是原始尺寸下发的（实测 186 KB/张）。书架一屏 120 张、系列页 652 张，
全尺寸意味着几十 MB 的流量 —— 而卡片上只占 150–180 CSS px。「打开书架慢」里最容易被
漏掉的就是这一段：接口响应本身只有几十 KB，慢在图片上。

这里钉三件事：
1. 缩到目标宽度、编码成 **WebP**（尺寸与格式可断言）；
2. **原图本来就比目标窄时原样返回**（不放大、不重编码 —— 字节级同一对象）；
3. 坏图 / 非法宽度**一律退化成原图**（缩略图是优化，不能变成可用性前提）。
"""
import io
import zipfile

from PIL import Image

from novelforge.core import library, thumbs


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def test_缩到目标宽度并编码成_WebP():
    out = thumbs.resize_image(_png(1200, 1600), 480)
    with Image.open(io.BytesIO(out)) as im:
        assert im.format == "WEBP"
        assert im.width == 480
        assert im.height == 640, "高度按比例缩，不许拉伸"


def test_原图更窄时原样返回同一个对象():
    tiny = _png(100, 140)
    assert thumbs.resize_image(tiny, 480) is tiny, "放大会糊，而且白白重编码一次"


def test_坏图与非法宽度都退回原图():
    broken = b"not-an-image"
    assert thumbs.resize_image(broken, 480) is broken
    big = _png(1200, 1600)
    assert thumbs.resize_image(big, 0) is big
    assert thumbs.resize_image(big, -3) is big


def test_宽度夹在合法区间():
    assert thumbs.clamp_width(0) == 0
    assert thumbs.clamp_width(-5) == 0
    assert thumbs.clamp_width("abc") == 0
    assert thumbs.clamp_width(10) == thumbs.MIN_WIDTH
    assert thumbs.clamp_width(99999) == thumbs.MAX_WIDTH


def test_端点按_w_出缩略图且默认仍是原图(isolated, default_root, client,  # noqa: ARG001
                                                  auth_headers):
    """漫画（归档首页）这条分支走 `_cover_cached`，缩略与非缩略都要能取。"""
    from novelforge.core import comics

    default_root.mkdir(parents=True, exist_ok=True)
    big = _png(1200, 1600)
    comics.write_cbz(default_root / "大封面.cbz", [("0001.png", big), ("0002.png", big)])
    library.invalidate()
    b = next(x for x in library.books() if x["name"] == "大封面.cbz")

    # 缺省（w=0）：与改造前逐字相同 —— 原始字节
    raw = client.get(f"/api/books/{b['id']}/cover", headers=auth_headers)
    assert raw.status_code == 200
    assert raw.content == big, "不带 ?w= 时必须还是原图（既有调用方不受影响）"

    small = client.get(f"/api/books/{b['id']}/cover?w=320", headers=auth_headers)
    assert small.status_code == 200
    with Image.open(io.BytesIO(small.content)) as im:
        assert im.format == "WEBP"
        assert im.width == 320
    assert small.headers["content-type"].startswith("image/webp"), small.headers["content-type"]

    # 宽度先夹后进缓存键：越界值等价于上界（同一份字节，不该存两份缓存）
    over = client.get(f"/api/books/{b['id']}/cover?w=99999", headers=auth_headers)
    with Image.open(io.BytesIO(over.content)) as im:
        assert im.width == thumbs.MAX_WIDTH


def test_透明像素铺白底而不是发黑():
    """第 208 期顺手修的真缺陷：原来只 `convert("RGB")` —— 那一步是**丢掉 alpha 通道**，
    透明像素的 RGB 通常是 (0,0,0) ⇒ 缩略图整片发黑。模块头注释一直写着「铺白底」，
    代码却没铺（注释比代码诚实，属于判据与实现不一致）。
    """
    buf = io.BytesIO()
    Image.new("RGBA", (1200, 1600), (0, 0, 0, 0)).save(buf, "PNG")
    out = thumbs.resize_image(buf.getvalue(), 480)
    with Image.open(io.BytesIO(out)) as im:
        px = im.convert("RGB").getpixel((10, 10))
    assert min(px) > 240, f"透明区应该铺白底，实际 {px}"


def test_没有重编码时媒体类型仍是原图(isolated, default_root, client,  # noqa: ARG001
                                          auth_headers):
    """原图比目标宽度窄 ⇒ `resize_image` 原样返回 ⇒ 媒体类型**必须**还是原图的
    （第 208 期改成 WebP 后这条更要紧：给 PNG 贴 `image/webp` + `nosniff` = 直接拒显）。"""
    from novelforge.core import comics

    default_root.mkdir(parents=True, exist_ok=True)
    small = _png(50, 70)
    comics.write_cbz(default_root / "小封面.cbz", [("0001.png", small)])
    library.invalidate()
    b = next(x for x in library.books() if x["name"] == "小封面.cbz")

    r = client.get(f"/api/books/{b['id']}/cover?w=480", headers=auth_headers)
    assert r.status_code == 200
    assert r.content == small, "比目标还小 ⇒ 原样返回，不放大、不重编码"
    assert r.headers["content-type"].startswith("image/png"), r.headers["content-type"]


def test_宽度够小但字节很重也要重编码():
    """真机书封普遍 427×600 却有 **392 KB**（抓来的 JPEG 质量给到 95+）。第 208 期的第一版
    只按「宽度是否超过目标」判，于是这些图**原样下发** —— 书架一屏 120 张仍是 30+ MB，
    WebP 一点没生效。判据必须是**字节**（`thumbs.REENCODE_OVER`）。
    """
    im = Image.new("RGB", (427, 600))
    px = im.load()
    for y in range(600):
        for x in range(427):
            px[x, y] = ((x * 7 + y * 13) % 256, (x * 31 + y * 17) % 256, (x * 11 + y * 29) % 256)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=98)
    raw = buf.getvalue()
    assert len(raw) > thumbs.REENCODE_OVER, f"前提：这张图要够重（{len(raw)} B）"

    out = thumbs.resize_image(raw, 480)
    assert out is not raw, "宽度没超目标但字节很重 ⇒ 仍要重编码"
    with Image.open(io.BytesIO(out)) as im2:
        assert im2.format == "WEBP"
        assert im2.size == (427, 600), "不放大，只重压"
    assert len(out) < len(raw), "重编码必须真的更小"


def test_带_EXIF_方向的封面按显示方向重编码():
    """第 213 期审计抓到的：浏览器显示 JPEG 会按 EXIF `Orientation` 自动旋转，而**重编码会
    丢掉 EXIF** —— 不先转正，带方向标记的封面会被转 90°。

    1200×1600 + 方向 6（顺时针 90°）⇒ 浏览器里是 **1600×1200**；缩到 480 宽应得
    **480×360**，而不是按原始像素算出的 480×640。
    """
    im = Image.new("RGB", (1200, 1600), (200, 30, 30))
    exif = Image.Exif()
    exif[0x0112] = 6                       # Orientation: rotate 90 CW
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=98, exif=exif)

    out = thumbs.resize_image(buf.getvalue(), 480)
    with Image.open(io.BytesIO(out)) as o:
        assert o.size == (480, 360), f"应按 EXIF 转正后再缩，实际 {o.size}"
        assert o.getexif().get(0x0112) is None, "重编码后不该再带方向标记"


def test_目录类客户端也要缩略封面():
    """第 219 期审计：OPDS（2 个）与 Komga（3 个）的封面端点此前**都不传 `w`** ⇒
    客户端每本拿约 300 KB 原图（书封才 427×600），一次列几百本系列就是几十 MB。

    判据收敛成 `server._CATALOG_COVER_WIDTH` 一处；这条用例钉的是**没有端点漏传** ——
    少一个就是「某个客户端继续下原图」，而那种事肉眼看不出来。
    """
    import pathlib
    import re

    from novelforge import server

    text = pathlib.Path(server.__file__).read_text(encoding="utf-8")
    calls = [c for c in re.findall(r"api_book_cover\([^)]*\)", text)
             if not c.startswith("api_book_cover(bid:")]
    assert len(calls) == 5, f"预期 OPDS×2 + Komga×3 共 5 个调用点，实际 {calls}"
    for c in calls:
        assert "_CATALOG_COVER_WIDTH" in c, f"这个封面端点没带宽度：{c}"
    assert server._CATALOG_COVER_WIDTH == 480
