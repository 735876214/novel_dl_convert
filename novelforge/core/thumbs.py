"""封面缩略图（第 152 期）：把封面压到指定宽度再下发。

**为什么需要**：书封面是**原始尺寸**的图（实测一本有声书的封面 186 KB）。书架一屏 120 张、
系列页 652 张，全尺寸下发意味着几十 MB 的流量 —— 而卡片上它们只占 150–180 CSS px
（2x 屏 ≈ 360 物理像素）。这是「打开书架慢」里最容易被漏掉的一段：接口本身只有几十 KB。

**只做一件事**：等比缩到给定宽度，编码成 JPEG。所有判断都收在本模块：
- 宽度先夹到 ``MIN_WIDTH..MAX_WIDTH``（调用方传什么都安全）；
- 原图本来就比目标窄 ⇒ **原样返回**（放大会糊，且白白重新编码）；
- 任何解码/编码失败 ⇒ **原样返回**（缩略图是优化，不是可用性前提 —— 拿不到图比拿不到图更糟）；
- 带了 alpha 的 PNG 铺白底再转 JPEG（透明像素转成黑色是最常见的「封面变黑」来源）。

⚠️ 这是「封面缩略」的**唯一实现**：`server._cover_cached` 是唯一调用方。别在端点里
再抄一份 ``Image.open``（本项目已有 ``komga_api`` 的「转 JPEG」那一段，它做的是**格式转换**
不是缩放，两者的判据不同，刻意不合并 —— 合并会让漫画页转码跟着受缩略图策略影响）。
"""
from __future__ import annotations

import io

#: 允许的宽度区间。低于 64 看不清、高于 1024 就比原始封面还费流量。
MIN_WIDTH = 64
MAX_WIDTH = 1024

#: 编码质量。82 在封面这种大面积渐变的图上肉眼无差，体积约为 92 的一半。
QUALITY = 82


def clamp_width(width: int) -> int:
    """把调用方给的宽度夹进合法区间；非数字 / 非正数 → 0（= 不缩）。"""
    try:
        w = int(width)
    except (TypeError, ValueError):
        return 0
    if w <= 0:
        return 0
    return max(MIN_WIDTH, min(MAX_WIDTH, w))


def resize_jpeg(data: bytes, width: int) -> bytes:
    """等比缩到 ``width`` 宽并以 JPEG 返回；**任何失败都返回原字节**。

    调用方只在「确实要缩」时才调它（宽度合法且原图更大由这里自己判）。
    """
    w = clamp_width(width)
    if not w or not data:
        return data
    try:
        from PIL import Image
    except Exception:                                   # noqa: BLE001 —— 没装 Pillow 就退回原图
        return data
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.width <= w:
                return data                             # 本来就够小：不放大、不重编码
            height = max(1, round(im.height * (w / im.width)))
            thumb = im.convert("RGB") if im.mode not in ("RGB", "L") else im
            thumb = thumb.resize((w, height), Image.LANCZOS)
            buf = io.BytesIO()
            thumb.save(buf, "JPEG", quality=QUALITY, optimize=True)
            return buf.getvalue()
    except Exception:                                   # noqa: BLE001 —— 坏图 / 不认识的格式
        return data
