"""第 123 期：格式识别审查的七条修复（契约）。

每条用例都对应一个**用户看得见的现象**，不是实现细节的复述：

1. 容器里的「文档表」必须与直读格式同进同出 —— `.azw` 曾漏掉，于是 `.zip` 里是一份
   `.azw` 时被判成 `unknown`（同一个 MOBI 家族，只差一个后缀），连展开都抽不出来；
2. **图片 + 旁注文档按漫画读** —— 漫画包带一个 `说明.txt` / `ComicInfo.xml` 是常态，
   此前一律判 `mixed` 不可读，结果是「同样的字节存成 `.cbz` 能读、存成 `.zip` 读不了」，
   而展开也救不回（`_unpack_entries` 只抽文档、不抽图片）。⚠️ 旁注判据看**名字与类型**
   （`.xml/.nfo` 这类结构化元数据一律算，`.txt/.md` 只有名字像说明才算）——
   「一张封面 + `正文.txt`」必须仍判 `mixed`，否则正文会被静默吞掉（第 124 期复审）；
3. 图片 + **一本真文档**仍然判不准（不猜）—— 放宽不等于瞎猜；
4. 错标后缀的 `.cbz` 不许假装能读：0 页就得进「待修复」，而不是让阅读器报「没有图片」；
5. 序号单元里的一话是容器时，渲染器按**内容**选（`.zip` 里是 PDF 就不能塞给漫画阅读器）；
6. Komga / OPDS 的媒体类型表覆盖全部书目格式，且只给**真有阅读器**的格式一个 profile；
7. 「入库自动补全」与「事实校正」的格式集合都收敛到单一真值源（`.txt` 是主力格式）；
8. 混合库兜底：只建了一个综合库的部署按格式收得进来，但关键词命中时仍让给关键词库。
"""
import pathlib
import zipfile

from novelforge.core import (comics, komga_api, library, library_rules, mobicache,
                             opds, pipeline, units, zipkind)

#: 最小 PNG 头 —— `comics._keep` 只看后缀，内容不参与判定
_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32

#: 全部可能的书目 format（`library._probe_entry` 与 `units` 会产出的那些）
_ALL_FORMATS = ["EPUB", "PDF", "TXT", "MOBI", "AZW3", "AZW", "FB2",
                "CBZ", "CBR", "ZIP", "RAR", "7Z", "AUDIO", "UNITS"]


def _zip(target, files: dict, compression=zipfile.ZIP_STORED):
    target = pathlib.Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression) as z:
        for name, data in files.items():
            z.writestr(name, data)
    return target


# ---------------------------------------------------------------------------
# 1. 容器里的文档表 ⇄ 直读格式（`.azw`）
# ---------------------------------------------------------------------------

def test_容器文档表覆盖直读格式():
    """`_DOC_FORMATS` 与 `mobicache.EXTS` 同进同出 —— 两处都是 MOBI 家族的后缀表。"""
    exts = set(zipkind._DOC_FORMATS)                        # noqa: SLF001 —— 本用例就是钉这张表
    assert set(mobicache.EXTS) <= exts, "MOBI 家族的后缀在容器里必须认得出来"
    assert {".txt", ".pdf", ".epub"} <= exts
    # 表里的每一档都得是「本身就能入库」的格式：否则展开出来也收不进去
    assert exts <= set(pipeline.EBOOK_EXT)


def test_容器里的一份azw按azw展开(tmp_path):
    p = _zip(tmp_path / "单azw.zip", {"书.azw": b"BOOK"})
    v = zipkind.analyze(p)
    assert v["kind"] == "azw" and v["format"] == "AZW" and v["needs_unwrap"] is True
    assert ".azw" in zipkind._UNPACK_EXTS                    # noqa: SLF001 —— 由文档表派生


# ---------------------------------------------------------------------------
# 2./3. 图片 + 旁注文档 = 漫画；图片 + 真文档 = 判不准
# ---------------------------------------------------------------------------

def test_图片加旁注文档按漫画读(tmp_path):
    p = _zip(tmp_path / "带说明.zip", {"01.png": _PNG, "02.png": _PNG, "说明.txt": "扫描自某站"})
    v = zipkind.analyze(p)
    assert v["kind"] == "comic" and v["readable"] is True and v["format"] == "CBZ"
    assert v["evidence"]["ignored_docs"] == ["说明.txt"]
    assert "旁注" in v["reason"]
    # 与同名内容的 .cbz 完全一致（这是「同样的字节存成 .cbz 能读」对照的那一半）
    assert comics.probe(p).get("pages") == 2


def test_图片加正文文本仍然判不准(tmp_path):
    """`.txt` 是本项目的主力书籍格式：「一张封面 + 正文.txt」不能当 1 页漫画读掉。

    第 123 期曾把 `.txt` 一律当旁注 ⇒ 这本书登记成 1 页漫画（`pages=1`、不进「待修复」），
    而 `unpack_plan` 又因 `kind=="comic"` 拒绝展开 ⇒ 正文既读不到也取不出来（第 124 期
    复审的 P2）。现在旁注判据看**文件名**：`正文.txt` 不像说明 ⇒ 仍判 `mixed`。
    """
    p = _zip(tmp_path / "封面加正文.zip", {"cover.png": _PNG, "正文.txt": "这是一本小说"})
    v = zipkind.analyze(p)
    assert v["kind"] == "mixed" and v["readable"] is False
    assert "正文.txt" in v["reason"]
    # 真展开路径也确认它没被当成漫画挡住
    assert zipkind.unpack_plan(p)["ok"] is True


def test_旁注判据看名字也看类型(tmp_path):
    """结构化元数据（`ComicInfo.xml` / `.nfo`）永远是旁注；文本类看名字是否像说明。"""
    assert zipkind._is_note("ComicInfo.xml")                 # noqa: SLF001 —— 本用例钉的就是判据
    assert zipkind._is_note("ComicInfo.xml") and zipkind._is_note("sub/说明.txt")
    assert zipkind._is_note("README.md") and zipkind._is_note("License.txt")
    assert zipkind._is_note("版权声明.txt")
    assert not zipkind._is_note("正文.txt") and not zipkind._is_note("第01章.txt")
    # 名字像说明的文本 + 图 ⇒ 漫画（现状仍然读得动）
    ok = _zip(tmp_path / "带readme.zip", {"01.png": _PNG, "readme.txt": "来自某站"})
    assert zipkind.analyze(ok)["kind"] == "comic"


def test_图片加真文档仍然判不准(tmp_path):
    p = _zip(tmp_path / "图文混装.zip",
             {"01.png": _PNG, "别传我.epub": b"PK", "说明.txt": "旁注"})
    v = zipkind.analyze(p)
    assert v["kind"] == "mixed" and v["readable"] is False
    assert "别传我.epub" in v["reason"], "reason 要点名是哪一份文档让它判不准"


# ---------------------------------------------------------------------------
# 4. 错标后缀不假装能读
# ---------------------------------------------------------------------------

def test_错标后缀的cbz标记为无法解析(tmp_path):
    bad = _zip(tmp_path / "错标漫画.cbz", {"正文.txt": "这是一本小说"})
    info = library._probe_entry(bad)                          # noqa: SLF001 —— 条目探测的唯一入口
    assert info["pages"] == 0 and info["unparsable"] is True

    good = _zip(tmp_path / "正确漫画.cbz", {"01.png": _PNG, "02.png": _PNG})
    info2 = library._probe_entry(good)                        # noqa: SLF001
    assert info2["pages"] == 2 and not info2.get("unparsable")


# ---------------------------------------------------------------------------
# 5. 序号单元里的话：渲染器按内容选
# ---------------------------------------------------------------------------

def test_序号单元里的话按内容选渲染器(tmp_path):
    assert units.kind_of(_zip(tmp_path / "第1话.zip", {"01.png": _PNG})) == "comic"
    assert units.kind_of(_zip(tmp_path / "第2话.zip", {"正文.txt": "x"})) == ""
    assert units.kind_of(_zip(tmp_path / "第3话.zip", {"书.epub": b"PK"})) == ""
    # 真后缀（无需文件存在 —— 判据只看后缀）
    assert units.kind_of(tmp_path / "第4话.cbz") == "comic"
    assert units.kind_of(tmp_path / "第5话.pdf") == "pdf"
    assert units.kind_of(tmp_path / "第6话.mp3") == "audio"


# ---------------------------------------------------------------------------
# 6. 兼容层的媒体类型 / profile
# ---------------------------------------------------------------------------

def test_komga媒体类型表覆盖所有书目格式():
    missing = [f for f in _ALL_FORMATS if f not in komga_api.MEDIA_TYPES]
    assert missing == [], f"这些格式没有媒体类型，客户端只能当未知二进制：{missing}"
    assert set(komga_api._PROFILES) == {"EPUB", "PDF", "CBZ", "CBR"}, \
        "profile 只给客户端真有阅读器的格式（其余一律 UNSUPPORTED）"


def test_komga给不出阅读器的格式如实标UNSUPPORTED(isolated):     # noqa: ARG001 —— 要 DB
    for fmt, want in (("EPUB", "READY"), ("PDF", "READY"), ("CBZ", "READY"), ("CBR", "READY"),
                      ("TXT", "UNSUPPORTED"), ("MOBI", "UNSUPPORTED"), ("AZW3", "UNSUPPORTED"),
                      ("FB2", "UNSUPPORTED"), ("AUDIO", "UNSUPPORTED"), ("UNITS", "UNSUPPORTED")):
        dto = komga_api.book_dto({"id": f"default$probe{fmt}", "name": f"书.{fmt.lower()}",
                                  "format": fmt, "library_id": "default"})
        assert dto["media"]["status"] == want, fmt
        assert (dto["media"]["mediaProfile"] is None) == (want == "UNSUPPORTED"), fmt


def test_opds媒体类型覆盖所有可下载格式():
    missing = [f for f in _ALL_FORMATS
               if f != "UNITS" and opds.mime_of(f) == "application/octet-stream"]
    assert missing == [], f"这些格式在 OPDS 里下不了（type 客户端不认识）：{missing}"


# ---------------------------------------------------------------------------
# 7. 格式集合的单一真值源
# ---------------------------------------------------------------------------

def test_事实校正的媒体后缀来自单一真值源():
    from novelforge import server
    assert set(server._ANY_MEDIA_EXTS) == set(library.BOOK_EXTS)   # noqa: SLF001
    assert ".azw" in server._ANY_MEDIA_EXTS                        # noqa: SLF001


def test_入库自动补全覆盖主力格式():
    """判据是 `library.type_for_ext`（第 122 期收敛的唯一真值源），不是又一份手抄表。"""
    assert library.type_for_ext(".txt") == "ebook"
    assert library.type_for_ext(".cbz") == "comic"
    assert library.type_for_ext(".azw") == "ebook"
    assert library.type_for_ext(".jpg") == ""


# ---------------------------------------------------------------------------
# 8. 混合库兜底（但不抢关键词）
# ---------------------------------------------------------------------------

def test_只有综合库时按格式也收得进来(isolated):                   # noqa: ARG001
    """`isolated` 只建了一条 mixed 库 —— 按格式判定必须能落到它身上。

    第 123 期之前 `decide` 把 `_by_format` 的 mixed 回落就地丢弃，于是这种部署
    按格式**一本都收不进来**（只剩「库名 / 关键词」两条路）。
    """
    hit = library_rules.decide(name="三体.epub")
    assert hit is not None and hit["id"] == "default"


def test_关键词命中时仍让给关键词库(isolated, tmp_path, make_library):  # noqa: ARG001
    """兜底不许抢在关键词前面 —— 否则「关键字路由」永远不生效（第 40 期两条用例钉着它）。"""
    make_library("scifi", "科幻专区", "mixed", tmp_path / "libraries" / "scifi", rules="科幻")
    hit = library_rules.decide(name="未知文件.txt", meta={"tags": ["科幻"]})
    assert hit is not None and hit["id"] == "scifi"
