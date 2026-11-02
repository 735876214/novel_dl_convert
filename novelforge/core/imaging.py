"""图片处理的**唯一实现**（第 248 期）：Pillow 能力判据 · 解码像素闸 · alpha 铺白底。

**为什么要有这个模块**：Pillow 是「装了就有、缺了也能跑」的**软依赖** —— 缺了它，
封面缩略、封面上传验图、PDF 页渲染三件事都不工作。而在这之前，散在四处的用法
**各自**静默降级，缺 Pillow 时用户看到的是：

- 上传封面回 **400「不是可识别的图片文件」** —— **说谎**：那不是坏图，是这台服务器缺依赖；
- PDF 页 / Komga 页面回 **404「页不存在」** —— 同样是假象，真因是服务器没有图片处理能力；
- 缩略图静默回原图 —— 用户要 480 宽，拿到 300 KB 原图，没有任何提示。

这与本项目其余可选依赖的纪律**直接冲突**：`core/mobicache.py` / `core/comics.py` /
`core/jssandbox.py` / `core/saferegex.py` 都走「缺依赖就**如实报** + 503 说清缺什么」
（见 `server.py` 里 `comics.backend_problem` 的用法）。Pillow 链路是**唯一一处破例**。

于是把这三件事收敛成**一处**：

- :func:`state` —— 「Pillow 能不能用」的**唯一判据**（能力接口、503 文案、`/health`
  的 problems 都问它）；
- :func:`open_image` —— 解码前的**像素闸**（解压炸弹，见下）；
- :func:`flatten` —— 「透明像素不能变黑」的**唯一实现**（铺白底）。

⚠️ **缩放与格式转换刻意分家**（`core/thumbs.py` 的模块头有详述）：本模块只管
「能不能解 / 能不能用 / alpha 怎么办」，**不管**缩到多宽、编成什么格式 ——
那是 `core/thumbs.py`（缩略图）与 `core/komga_api.py`（格式转换）各自的事。

**像素闸为什么必要**：Pillow 自带的 ``Image.MAX_IMAGE_PIXELS`` 只是**告警**
（默认只发 warning，超过两倍才抛异常），而纯色大图压缩率极高 —— 实测
12000×12000 的 PNG 只有 **450 KB**（远低于 8 MB 的体积上限），真解码却要
**411 MB** 内存。归档里的漫画页是**外部内容** ⇒ 这是一道真实的解压炸弹面。
"""
from __future__ import annotations

import io

#: 依赖名。写进文案，也与 `requirements.txt` 的声明对齐。
PKG_NAME = "Pillow"

#: 缺 Pillow 时的**统一**文案。能力接口、503 响应、`/health` 的 problems 共用它
#: —— **只有这一处**，别在别处再抄一句「需要 Pillow」。
REASON = f"服务器缺少图片处理能力（需 {PKG_NAME}）"

#: 解码后的**像素数**上限（宽 × 高）。
#:
#: 为什么是 40 M：按 RGBA 算约 **160 MB** 内存上界（单请求、单用户自托管够用），
#: 而真机上的正常封面/漫画页离它很远 —— 3000×4500 的书封 = 13.5 M，
#: 1500×2200 的漫画页 = 3.3 M，PDF 页按 2× 渲染 = 2 M。
MAX_PIXELS = 40_000_000


class MissingPillow(RuntimeError):
    """这台服务器没有 Pillow（**能力缺失**，不是「图片坏了」）。

    ⚠️ 两者必须分开：把「缺依赖」说成「图不对」，用户会去换图、重传、反复失败 ——
    而真因是服务端少装了一个包。
    """


class TooManyPixels(RuntimeError):
    """图片的像素数超过 :data:`MAX_PIXELS`（解压炸弹）。"""


def available() -> bool:
    """Pillow 能不能用（**唯一判据**；:func:`state` 与它同源）。

    只探「能不能 import」：真用的时候再 import 一次（模块级缓存，第二次是字典查找）。
    """
    try:
        import PIL.Image  # noqa: F401, PLC0415 —— 惰性导入：没这依赖时只有图片功能不可用
        return True
    except Exception:                                  # noqa: BLE001 —— 没装 = 常态，不是异常
        return False


def _version() -> str:
    try:
        from importlib.metadata import version as _pkg_version
        return str(_pkg_version(PKG_NAME) or "")
    except Exception:                                  # noqa: BLE001
        try:
            import PIL
            return str(getattr(PIL, "__version__", "") or "")
        except Exception:                              # noqa: BLE001
            return ""


def state() -> dict:
    """Pillow 可用性：``{"available", "version", "reason"}``。

    **本函数是唯一的「能不能做图片处理」判据**（能力接口、503 文案、`/health`
    的 problems 都问它）—— 与 `core/mobicache.py::state` / `core/jssandbox.py::state`
    同款：缺包或包坏了都**如实报**，不假装能做。
    """
    if not available():
        return {"available": False, "version": "", "reason": REASON}
    return {"available": True, "version": _version(), "reason": ""}


def open_image(data: bytes):
    """打开图片字节并做**像素闸**检查，返回已打开的 :class:`PIL.Image.Image`。

    调用方负责关闭（`with imaging.open_image(data) as im:` 最省事）。

    - 没装 Pillow ⇒ :class:`MissingPillow`；
    - 像素数超过 :data:`MAX_PIXELS` ⇒ :class:`TooManyPixels`（**不解码**）；
    - 不是图片 ⇒ Pillow 自己的异常（`UnidentifiedImageError` 等），原样抛出。

    ⚠️ **为什么要在 `open` 之后、`load` 之前查**：``Image.open`` 是**惰性**的 ——
    它只读文件头，像素数据还没解 ⇒ 这一步几乎不花钱，而 ``im.size`` 就是解码时
    真正要分配的尺寸 ⇒ 拿它当判据是准的（Pillow 自带的炸弹检查也读同一个头）。
    """
    if not available():
        raise MissingPillow(REASON)
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(data))
    except Image.DecompressionBombError as e:
        # Pillow 自带的闸（两倍 `MAX_IMAGE_PIXELS`）先于我们的闸触发时，把它统一
        # 翻译成同一个错 —— 否则「像素太多」会表现成两种不同的失败。
        raise TooManyPixels(f"图片尺寸过大（{e}）") from None
    try:
        w, h = im.size
        if w * h > MAX_PIXELS:
            raise TooManyPixels(f"图片尺寸过大（{w}×{h}，上限 {MAX_PIXELS} 像素）")
    except Exception:
        im.close()
        raise
    return im


def flatten(im):
    """带透明的图**铺白底**再交给编码器；其余直接转 RGB。

    ⚠️ 不能只 `convert("RGB")`：那一步只是**丢掉 alpha 通道**，透明像素的 RGB 通常是
    (0,0,0) ⇒ 图片整片发黑（`core/thumbs.py` 的模块头把这条记作「封面变黑」的成因；
    `core/komga_api.py` 的页面转码此前踩的就是这个坑）。

    **本函数是「透明像素不能变黑」的唯一实现**（第 248 期）—— 缩略图与格式转换都用它。
    """
    from PIL import Image

    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    if not has_alpha:
        return im if im.mode == "RGB" else im.convert("RGB")
    rgba = im.convert("RGBA")
    bg = Image.new("RGB", rgba.size, (255, 255, 255))
    bg.paste(rgba, mask=rgba.getchannel("A"))
    return bg
