"""封面缩略图（第 152 期）：把封面压到指定宽度再下发。

**为什么需要**：书封面是**原始尺寸**的图（实测一本有声书的封面 186 KB）。书架一屏 120 张、
系列页 652 张，全尺寸下发意味着几十 MB 的流量 —— 而卡片上它们只占 150–180 CSS px
（2x 屏 ≈ 360 物理像素）。这是「打开书架慢」里最容易被漏掉的一段：接口本身只有几十 KB。

**只做一件事**：等比缩到给定宽度，编码成 **WebP**（第 208 期起；此前是 JPEG，实测同尺寸
小 26–40%）。所有判断都收在本模块：
- 宽度先夹到 ``MIN_WIDTH..MAX_WIDTH``（调用方传什么都安全）；
- 原图本来就比目标窄 ⇒ **不放大**；但字节很重的窄图（`REENCODE_OVER`）仍按原尺寸重压 ——
  真机书封 427×600 却有 392 KB，只按宽度判「够小」会让书架继续下几十 MB；
- 任何解码/编码失败 ⇒ **原样返回**（缩略图是优化，不是可用性前提 —— 拿不到图比拿不到图更糟）；
- 带了 alpha 的 PNG 铺白底再编码（透明像素转成黑色是最常见的「封面变黑」来源）。

⚠️ 这是「封面缩略」的**唯一实现**：`server._cover_cached` 是唯一调用方。别在端点里
再抄一份 ``Image.open``（本项目已有 ``komga_api`` 的「转 JPEG」那一段，它做的是**格式转换**
不是缩放，两者的判据不同，刻意不合并 —— 合并会让漫画页转码跟着受缩略图策略影响）。

**第 248 期**：解码前的**像素闸**与「透明像素铺白底」都挪到了 `core/imaging.py` ——
它们是**图片处理的通用判据**（上传验图、Komga 转码也要用），放在这里就变成了第二份实现。
本模块仍然只管「缩到多宽、编成什么格式」。
"""
from __future__ import annotations

import io

from . import imaging

#: 允许的宽度区间。低于 64 看不清、高于 1024 就比原始封面还费流量。
MIN_WIDTH = 64
MAX_WIDTH = 1024

#: 编码质量。82 在封面这种大面积渐变的图上肉眼无差，体积约为 92 的一半。
QUALITY = 82

#: 缩略图的编码与媒体类型（第 208 期：JPEG → WebP）。
#: 实测（真机 8 张书封，原图只有 427×600 却重 292 KB —— 抓来的 JPEG 质量给到 95+）：
#:   · **同尺寸重编码**：WebP(q82) 比 JPEG(q82) 小 26–40%（8 张 531,256 → 382,420 B）；
#:   · **相对原图**（也就是用户真正省下的）：2,325 KB → 373 KB，**−84%**。
#: 2026 年所有在用的浏览器都能直接 `<img>` 解 WebP ⇒ 不做 `Accept` 协商
#: （那要多一份缓存键与一条回退分支）。
#: ⚠️ 只在**真的重编码**时才能用这个类型 —— 没缩时返回的是原图字节，`resize_image`
#: 原样返回同一个对象，调用方靠它判断要不要换媒体类型。
THUMB_MEDIA = "image/webp"


def clamp_width(width: int) -> int:
    """把调用方给的宽度夹进合法区间；非数字 / 非正数 → 0（= 不缩）。"""
    try:
        w = int(width)
    except (TypeError, ValueError):
        return 0
    if w <= 0:
        return 0
    return max(MIN_WIDTH, min(MAX_WIDTH, w))


#: 原图字节超过这个值就**重编码**，即使宽度已经够小（第 208 期）。
#: 真机书封普遍只有 427×600 却有 **392 KB**（抓来的 JPEG 质量给到 95+），按「宽度够小」
#: 判会把它们原样下发 —— 书架一屏 120 张仍是 30+ MB。判据必须是**字节**，不是宽度。
REENCODE_OVER = 120 * 1024


def resize_image(data: bytes, width: int) -> bytes:
    """等比缩到 ``width`` 宽并以 **WebP** 返回；**任何失败都返回原字节（同一个对象）**。

    三种「原样返回」：宽度非法 / 解码失败 / **重编码反而不更小**。宽度不超目标但字节
    很重的图（见 `REENCODE_OVER`）仍会按原尺寸重编码 —— 编码完更大就退回原图。
    """
    w = clamp_width(width)
    if not w or not data:
        return data
    try:
        from PIL import Image, ImageOps
    except Exception:                                   # noqa: BLE001 —— 没装 Pillow 就退回原图
        return data
    try:
        # ⚠️ 走 `imaging.open_image`（像素闸）：封面是**外部内容**，而纯色大图压缩率极高
        # （实测 12000×12000 的 PNG 只有 450 KB，真解码要 411 MB）⇒ 必须有解码前的闸。
        # 超限时它抛 `TooManyPixels`，被下面兜住 ⇒ **仍然原样返回原图**（缩略图是优化，
        # 不是可用性前提 —— 见模块头第 12 行）。
        with imaging.open_image(data) as im:
            if im.width <= w and len(data) <= REENCODE_OVER:
                return data                             # 真的够小：不放大、不重编码
            # ⚠️ EXIF 方向（第 213 期审计）：浏览器显示 JPEG 时会按 `Orientation` 自动旋转，
            # 而**重编码会丢掉 EXIF** —— 不先转正，带方向标记的封面就会转 90°。
            # 这个缺陷在「宽图被缩」这条路上一直存在，本期把重编码范围扩大到「字节重的窄图」
            # 后影响面变大，所以在这里收口（判据只有这一处）。
            im = ImageOps.exif_transpose(im)
            target = min(w, im.width)                   # 窄图不放大，只重压
            height = max(1, round(im.height * (target / im.width)))
            thumb = imaging.flatten(im).resize((target, height), Image.LANCZOS)
            buf = io.BytesIO()
            # `method=6` 是最慢也最小的一档：缩略图只算一次、之后进缓存，值得这点 CPU
            thumb.save(buf, "WEBP", quality=QUALITY, method=6)
            out = buf.getvalue()
            # 不变量：缩略图**永远不比原图大**（纯色小图重编码可能略大）
            return out if len(out) < len(data) else data
    except Exception:                                   # noqa: BLE001 —— 坏图 / 不认识的格式
        return data
