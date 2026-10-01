"""第 86 期第 6 步：EPUB 增量写回的**底层原语**（零网络，用真 EPUB 夹具）。

「既有条目一字不动」是整期最硬的约束（进度/批注全按条目 index 记录），
所以这里全部用**字节级断言**验，而不是「能打开就算过」。
"""
import pathlib
import shutil
import zipfile

from novelforge.core import epub_builder, epub_update


def _make_epub(tmp_path: pathlib.Path, chapters: int = 3) -> pathlib.Path:
    p = tmp_path / "书.epub"
    epub_builder.build_epub(
        {"title": "增量测试书", "author": "某人", "language": "zh"},
        [{"title": f"第 {i} 章", "body_html": f"<p>正文 {i}</p>"} for i in range(1, chapters + 1)],
        str(p))
    return p


def test_追加新章后既有条目一字不动(tmp_path):
    src = _make_epub(tmp_path)
    dst = tmp_path / "书.updated.epub"
    old = zipfile.ZipFile(src).namelist()

    # ⚠️ 中文必须 `.encode()`：Python 的 bytes 字面量只允许 ASCII（写成 `b"新章"` 是语法错误）
    epub_update.copy_with_extra(src, dst,
                                extra=[("EPUB/text/c0004.xhtml", "<p>新章</p>".encode())])

    assert epub_update.verify_unchanged(src, dst,
                                        added={"EPUB/text/c0004.xhtml"}) == [], \
        "既有条目的顺序 / 内容字节 / 元数据都必须与本文件一致"
    with zipfile.ZipFile(dst) as z:                 # ⚠️ read 必须留在 with 内（出了块归档就关了）
        names = z.namelist()
        tail = z.read(names[-1])
    assert names[:len(old)] == old, "既有条目**顺序**不变（新章追加在末尾）"
    assert names[-1] == "EPUB/text/c0004.xhtml" and tail == "<p>新章</p>".encode()


def test_mimetype仍居首位且不压缩(tmp_path):
    src = _make_epub(tmp_path)
    dst = tmp_path / "out.epub"
    epub_update.copy_with_extra(src, dst, extra=[("EPUB/text/x.xhtml", b"x")])
    with zipfile.ZipFile(dst) as z:
        assert z.namelist()[0] == "mimetype", "EPUB 规范：mimetype 必须是第一条"
        assert z.getinfo("mimetype").compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/epub+zip"


def test_可以就地替换某个条目(tmp_path):
    """重写 OPF / nav 走这条路 —— 其余条目仍必须一字不动。"""
    src = _make_epub(tmp_path)
    dst = tmp_path / "out.epub"
    opf = next(n for n in zipfile.ZipFile(src).namelist() if n.endswith(".opf"))
    epub_update.copy_with_extra(src, dst, replace={opf: "<package>改过的</package>".encode()})
    with zipfile.ZipFile(dst) as z:
        assert z.read(opf) == "<package>改过的</package>".encode()
    assert epub_update.verify_unchanged(src, dst, replaced={opf}) == []
    # 少声明一个 replaced ⇒ 校验必须**报出来**（判据本身要能抓到差异）
    assert epub_update.verify_unchanged(src, dst), "改了条目却在 replaced 里不声明，必须被发现"


def test_原子写不留part且不动源文件(tmp_path):
    src = _make_epub(tmp_path)
    before = src.read_bytes()
    dst = tmp_path / "out.epub"
    epub_update.copy_with_extra(src, dst, extra=[("EPUB/text/y.xhtml", b"y")])
    assert not list(tmp_path.glob("*.part")), "原子写不该留下临时文件"
    assert src.read_bytes() == before, "源文件必须一字不动（源不可变）"


def test_往不存在的目录写也能成功(tmp_path):
    src = _make_epub(tmp_path)
    dst = tmp_path / "深" / "一层" / "out.epub"
    epub_update.copy_with_extra(src, dst)
    assert dst.is_file()
    assert epub_update.verify_unchanged(src, dst) == []


def test_校验能抓出内容漂移(tmp_path):
    """把「既有条目被改动」造出来，校验必须报错（否则这条判据就是摆设）。"""
    src = _make_epub(tmp_path)
    dst = tmp_path / "bad.epub"
    shutil.copyfile(src, dst)
    with zipfile.ZipFile(src) as a:
        names = a.namelist()
        data = {n: a.read(n) for n in names}
    with zipfile.ZipFile(dst, "w") as z:
        for n in names:
            z.writestr(n, "被改过了".encode() if n.endswith(".xhtml") else data[n])
    assert epub_update.verify_unchanged(src, dst), "内容变了却校验通过 —— 这条判据形同虚设"
