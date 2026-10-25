"""封面缩略图（第 152 期）：`?w=` 的纯函数与端点契约。

**为什么要它**：封面是原始尺寸下发的（实测 186 KB/张）。书架一屏 120 张、系列页 652 张，
全尺寸意味着几十 MB 的流量 —— 而卡片上只占 150–180 CSS px。「打开书架慢」里最容易被
漏掉的就是这一段：接口响应本身只有几十 KB，慢在图片上。

这里钉三件事：
1. 缩到目标宽度、编码成 JPEG（尺寸可断言）；
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


def test_缩到目标宽度并编码成_JPEG():
    out = thumbs.resize_jpeg(_png(1200, 1600), 480)
    with Image.open(io.BytesIO(out)) as im:
        assert im.format == "JPEG"
        assert im.width == 480
        assert im.height == 640, "高度按比例缩，不许拉伸"


def test_原图更窄时原样返回同一个对象():
    tiny = _png(100, 140)
    assert thumbs.resize_jpeg(tiny, 480) is tiny, "放大会糊，而且白白重编码一次"


def test_坏图与非法宽度都退回原图():
    broken = b"not-an-image"
    assert thumbs.resize_jpeg(broken, 480) is broken
    big = _png(1200, 1600)
    assert thumbs.resize_jpeg(big, 0) is big
    assert thumbs.resize_jpeg(big, -3) is big


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
        assert im.format == "JPEG"
        assert im.width == 320

    # 宽度先夹后进缓存键：越界值等价于上界（同一份字节，不该存两份缓存）
    over = client.get(f"/api/books/{b['id']}/cover?w=99999", headers=auth_headers)
    with Image.open(io.BytesIO(over.content)) as im:
        assert im.width == thumbs.MAX_WIDTH
