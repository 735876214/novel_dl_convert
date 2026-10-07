"""来源的**领域轴**：一家源供给的是「哪一种东西」。

为什么要这张轴（第 102 期）：14 家旧源全是**书目**（书 / 版本 / ISBN / 出版社），
而新接入的漫画与动画目录不同 ——

- **漫画**（Comic Vine / Metron / GCD / MangaDex）：实体是「卷 / 期」，
  有出版社与年份，但**多数没有 ISBN**、没有页码；
- **动画 / 轻小说目录**（Bangumi / AniList / MyAnimeList / Kitsu）：实体是**作品**，
  它的「作者」往往是**原作者**而不是这本书的作者，且**根本没有 ISBN / 出版社 / 页码**。

⚠️ 这张轴**只描述事实**（这家是什么、哪些字段对它有意义），**不参与计分**。
`metascore` 目前对全部书按同一张表打分（`core/metascore.py:70`），
按 kind 重算权重会**改变现有书库的评分**，属另一件事（见 `docs/TODO.md`）。

`FIELDS_OF_KIND` 的用途是**如实标注**：界面可以说清「这家不提供 ISBN」，
而不是让用户以为「抓不到是坏了」。
"""
from __future__ import annotations

#: 四个领域档。**新增一家源必须显式选一档**（契约测试钉住），不能默默漏过。
KIND_EBOOK = "ebook"
KIND_COMIC = "comic"
KIND_ANIME = "anime"
KIND_AUDIOBOOK = "audiobook"

#: 全部 kind（顺序 = 界面上分组的呈现顺序）
KINDS = (KIND_EBOOK, KIND_COMIC, KIND_ANIME, KIND_AUDIOBOOK)

#: kind → 中文名（界面直接用这一份，别在两端各写一套说法）
KIND_LABELS = {
    KIND_EBOOK: "电子书",
    KIND_COMIC: "漫画",
    KIND_ANIME: "动画 / 轻小说",
    KIND_AUDIOBOOK: "有声书",
}

#: kind → **该领域真正有意义的字段**（`fileops.METADATA_FIELDS` 的子集）。
#:
#: ⚠️ 这是**描述性**的：不在表里的字段不是「禁止写入」，而是「这家源本来就不提供」。
#: 用它来做两件事：① 界面上如实说明；② 判断「这条候选值不值得为它去补详情」。
#:
#: `title` / `author` / `description` / `cover` / `tags` 四类**每个领域都有**：
#: 封面在 `_entry` 里叫 `cover_url`（不是 METADATA_FIELDS 的成员，单独写在下方的注释里）。
FIELDS_OF_KIND = {
    # 书目：全套字段都有意义
    KIND_EBOOK: frozenset({
        "title", "author", "subtitle", "series", "series_index", "date", "publisher",
        "language", "description", "tags", "isbn",
    }),
    # 漫画：有卷 / 期与出版社、年份，但**基本没有 ISBN**（单行本偶有）。
    # 这里的「作者」语义是编剧 / 画师（Comic Vine 的 person credits）。
    KIND_COMIC: frozenset({
        "title", "author", "series", "series_index", "date", "publisher",
        "description", "tags", "isbn",
    }),
    # 动画 / 轻小说目录：实体是**作品**而不是某个版本（没出版社、没 ISBN、没页码）。
    # `series` / `series_index` 对它们**最有意义**（作品 → 系列 → 第几季 / 第几册）。
    KIND_ANIME: frozenset({
        "title", "author", "series", "series_index", "date", "description", "tags",
    }),
    # 有声书：演出者是独立字段（`narrators` 已在 fileops.METADATA_FIELDS 里）；
    # 副标题同理（第 113 期：Audible 从顶层 `subtitle` 供给它）。
    KIND_AUDIOBOOK: frozenset({
        "title", "author", "subtitle", "narrators", "series", "series_index", "date",
        "publisher", "language", "description", "tags", "isbn",
    }),
}

#: 每个 kind 都提供封面（`_entry` 的 `cover_url`，不属 METADATA_FIELDS）。
#: 写成一个常量是为了让界面与详情补全逻辑**不必再列一遍**。
KIND_HAS_COVER = frozenset(KINDS)


def fields_of(kind: str) -> frozenset:
    """该领域有意义的字段集合；未知 kind ⇒ 空集（调用方按「不知道」处理，不猜）。"""
    return FIELDS_OF_KIND.get(kind, frozenset())


def provides(kind: str, field: str) -> bool:
    """该领域**是否提供**某字段（`cover` 单独判）。"""
    if field == "cover":
        return kind in KIND_HAS_COVER
    return field in fields_of(kind)
