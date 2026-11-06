"""书库「内容探测」与「配置与内容不符时的校正」（第 265 期从 `server.py` 挪下来）。

这两件事都是**领域判断**（看目录里真装了什么 → 决定这个库该是什么类型、收哪些格式），
不是 HTTP 编排。此前它们长在 `server.py` 里，与 433 条路由挤在同一个 1.2 万行文件里。

⚠️ 校验与归一（`allowed_exts` 的形状、非法扩展名 → 400）**仍留在 server**：
那是**请求形状**的事，`core` 不认识 HTTP。本模块只回答「目录里有什么、该校正成什么」。
"""
from __future__ import annotations

import json
import logging
import pathlib

from . import audio, library

#: 「任意媒体」的全集 —— **派生**自 `library.BOOK_EXTS`（第 265 期挪过来时保持派生，
#: 不另抄一份字面量：白名单一改，这里自动跟上）。
ANY_MEDIA_EXTS = library.BOOK_EXTS

def scan_media(dirs, cap: int = 3000) -> tuple:
    """扫来源目录，得出**目录里真实装了什么**：``(扩展名集合, 需要合并的类型集合)``。

    ⚠️ 只下探**两层**（顶层文件 + 一层子目录里的单元文件）：漫画库的常见形态就是
    「顶层一堆 `.cbz`」或「一层目录、目录里一话一文件」，再深的树书架本来也不会合并成一本 ——
    为它把整个库走一遍不值得（建库/改库是交互路径）。`cap` 是硬上限，超了就停。
    """
    found: set = set()
    kinds: set = set()
    n = 0
    for raw in dirs or []:
        root = pathlib.Path(str(raw))
        try:
            children = sorted(root.iterdir())
        except Exception:                                    # noqa: BLE001 —— 目录不在 / 没权限都跳过
            continue
        for p in children:
            n += 1
            if n > cap:
                return found, kinds
            try:
                if p.is_file():
                    if p.suffix.lower() in ANY_MEDIA_EXTS:
                        found.add(p.suffix.lower())
                    continue
                if not p.is_dir():
                    continue
                files = [q for q in p.iterdir()
                         if q.is_file() and q.suffix.lower() in ANY_MEDIA_EXTS]
                ext_here = {q.suffix.lower() for q in files}
            except Exception:                                # noqa: BLE001
                continue
            # ⚠️ 判据是**文件数**≥2，不是**扩展名种类**≥2：目录型漫画/有声书最常见的样子是
            # 「一层目录里全是 .cbz（或 .mp3）」—— 按扩展名种类判永远为 1，于是这棵树被漏掉，
            # 类型就校正不过来，仍然看不见（本轮实测踩过）。
            if len(files) >= 2:             # 一层里 ≥2 个媒体文件 ⇒ 这是一棵「单元树」
                found |= ext_here
                if ext_here <= set(audio.AUDIO_EXTS):
                    kinds.add("audiobook")
                else:
                    kinds.add("comic")
    return found, kinds

def fix_empty_library(ltype: str, allowed_exts, dirs) -> tuple:
    """按**文件夹里真实装的东西**校正 `type` / 白名单；**只在会变成空库时动手**。

    背景（第 86 期，用户报的缺陷）：库的配置来自请求，**不随文件夹复原** —— 删库再用同名
    重建时，向导默认 `type='ebook'`，而 `.cbz/.cbr` 不在 ebook 白名单里；目录型漫画还要求
    `type∈{comic,audiobook}` 才会被合并成一本书。于是「同一个文件夹」重建后**一本书都读不到**，
    而本地原件明明还在（这类静默失败最难查：看起来像「库坏了」）。

    三条规则（顺序即优先级）：

    1. 目录里有本库**收得下**的文件 ⇒ **一个字都不改**（正常配置不许被悄悄动）；
    2. 一个都收不下、但目录里确实有媒体 ⇒ 按实际内容补白名单；出现「单元树」时
       同时把类型校正到 `comic` / `audiobook`（否则那棵树不会被合并成一本，仍然看不见）；
    3. 目录本来就是空的 ⇒ 原样返回（不猜）。
    """
    if not dirs:
        return ltype, allowed_exts
    if isinstance(dirs, str):
        try:
            dirs = json.loads(dirs)
        except Exception:                                    # noqa: BLE001
            return ltype, allowed_exts
    if not isinstance(dirs, (list, tuple)):
        return ltype, allowed_exts
    found, kinds = scan_media(dirs)
    if not found:
        return ltype, allowed_exts
    eff = library.exts_for_library({"type": ltype, "allowed_exts": allowed_exts})
    if found & {str(e).lower() for e in eff}:
        return ltype, allowed_exts                           # 规则 1：收得下，不碰
    new_exts = list(dict.fromkeys([*(eff or ()), *sorted(found)]))
    new_type = ltype
    if kinds:
        new_type = sorted(kinds)[0]                          # comic 优先于 audiobook（字典序）
    logging.getLogger("novelforge").warning(
        "书库配置与目录内容不符（目录里有 %s，但 type=%s 的白名单收不下）——"
        "已按目录内容校正为 type=%s：这类「重建后一本书都读不到」的库，配置多半是重建时丢的",
        "、".join(sorted(found)), ltype, new_type)
    return new_type, new_exts
