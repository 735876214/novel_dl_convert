"""``GET /api/books`` 的**分页契约**（第 88 期 C 批）。

`/api/books` 新增可选查询参数 ``limit`` / ``offset``（只加不改）。这里钉住四件事，
它们的失效方式全是**静默**的（不报错、不崩，只是数据悄悄不对）：

1. **不传 ``limit`` ⇒ 与改造前逐字节一致**（``items`` 全量、顺序不变）。这是硬要求 ——
   仓库里还有别的调用方（侧栏 / 其它视图 / 可能的第三方），默认分页会让它们**少拿数据**。
   必须有一条用例证明「不加参数时没变」。
2. ``limit`` / ``offset`` 切片正确，且 ``total`` **始终是未切片前的总数**（前端要用它
   算「已显示 N / 共 M 本」）。
3. ``has_more`` 边界（正好读完 / 还有 / 越界）—— 写错只会让「加载更多」永远亮着却拉不到，
   或没拉完就停。
4. **翻页不重不漏**：同一排序下逐页拼起来必须逐项等于全量那一页。这条能抓住「排序不稳定」
   （一旦排序键有并列且不稳定，两页之间就会重复 / 漏项）。

⚠️ 零外网：只打 ``/api/books``，不触发任何抓取（测试配置里 metadata_fetch 默认关）。
"""
import pathlib

from novelforge.core import library


def _books(client, headers, **params) -> dict:
    r = client.get("/api/books", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json()


def _seed(root: pathlib.Path, n: int, make_book) -> None:
    """往库里放 n 本占位书（名字零填充 ⇒ 文件序确定 ⇒ 分页顺序可预期）。"""
    for i in range(n):
        make_book(root, f"书{i:03d}.epub")
    # 与既有用例同一手法：写完文件必须标脏，下一次读才会（冷索引时同步）重扫看到它们。
    library.invalidate()


def test_不传limit时与改造前一致_全量_顺序不变(client, auth_headers, default_root, make_book):
    """硬要求：不传 `limit` ⇒ 行为与改造前完全一致（返回全部、顺序不变）。"""
    _seed(default_root, 5, make_book)

    body = _books(client, auth_headers)                 # 不加任何参数
    assert body["total"] == 5
    assert len(body["items"]) == 5
    # 追加字段：不传 limit ⇒ limit 回显 null、offset=0、has_more=false
    assert body["limit"] is None
    assert body["offset"] == 0
    assert body["has_more"] is False
    # 第 88 期 A 批的 scanning 字段仍在（分页只加不改）
    assert isinstance(body["scanning"], list)

    # 与「显式给一个超大 limit」逐项一致 —— 证明不加参数就是「全部、同一顺序」
    big = _books(client, auth_headers, limit=999)
    assert [b["id"] for b in big["items"]] == [b["id"] for b in body["items"]]
    assert big["total"] == 5 and big["has_more"] is False


def test_limit_offset切片正确_且total是未切片总数(client, auth_headers, default_root, make_book):
    _seed(default_root, 5, make_book)
    full = [b["id"] for b in _books(client, auth_headers)["items"]]

    p1 = _books(client, auth_headers, limit=2, offset=0)
    assert [b["id"] for b in p1["items"]] == full[:2]
    assert p1["total"] == 5 and p1["limit"] == 2 and p1["offset"] == 0
    assert p1["has_more"] is True                       # 还有 3 本没给

    p2 = _books(client, auth_headers, limit=2, offset=2)
    assert [b["id"] for b in p2["items"]] == full[2:4]
    assert p2["total"] == 5 and p2["has_more"] is True  # 还有 1 本

    p3 = _books(client, auth_headers, limit=2, offset=4)
    assert [b["id"] for b in p3["items"]] == full[4:5]
    assert p3["total"] == 5 and p3["has_more"] is False  # 到尾了


def test_has_more边界_正好读完为假(client, auth_headers, default_root, make_book):
    _seed(default_root, 5, make_book)
    body = _books(client, auth_headers, limit=5, offset=0)   # 正好一页读完
    assert len(body["items"]) == 5
    assert body["has_more"] is False


def test_offset越界不报错_空items但total真实(client, auth_headers, default_root, make_book):
    """翻页到尾巴再拉一页是正常操作，不该 400/500。"""
    _seed(default_root, 5, make_book)
    body = _books(client, auth_headers, limit=2, offset=99)
    assert body["items"] == []
    assert body["total"] == 5            # ⚠️ 仍是真实总数（不是 0、也不是 99）
    assert body["offset"] == 99
    assert body["has_more"] is False


def test_只给offset也给全量(client, auth_headers, default_root, make_book):
    """只给 offset、不给 limit ⇒ 等价于「不限」：返回 offset 起的全部。"""
    _seed(default_root, 5, make_book)
    full = [b["id"] for b in _books(client, auth_headers)["items"]]
    body = _books(client, auth_headers, offset=2)
    assert [b["id"] for b in body["items"]] == full[2:]
    assert body["limit"] is None
    assert body["has_more"] is False


def test_limit为0表示不限(client, auth_headers, default_root, make_book):
    """``limit<=0`` 语义自定（本期定：0 = 不限，负数非法）—— 见 handler 文档串。"""
    _seed(default_root, 5, make_book)
    body = _books(client, auth_headers, limit=0)
    assert len(body["items"]) == 5
    assert body["limit"] is None         # 生效值回显 = 不限
    assert body["has_more"] is False


def test_非法参数一律400且detail是中文(client, auth_headers, default_root, make_book):
    _seed(default_root, 3, make_book)
    for params in ({"limit": "abc"}, {"offset": "x"}, {"limit": "-1"}, {"offset": "-1"}):
        r = client.get("/api/books", headers=auth_headers, params=params)
        assert r.status_code == 400, f"{params} 应当 400，实际 {r.status_code}：{r.text}"
        detail = r.json()["detail"]
        assert isinstance(detail, str) and detail, f"{params} 的 detail 应为非空字符串"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in detail), \
            f"{params} 的 detail 应为中文：{detail!r}"


def test_翻页不重不漏(client, auth_headers, default_root, make_book):
    """逐页拼起来必须逐项等于全量那一页 —— 这条能抓住排序不稳定（并列键 + 非稳定序）。

    若 `library.books()` 的顺序在两页之间发生抖动，这里就会出现重复 / 漏项。
    """
    _seed(default_root, 5, make_book)
    full = [b["id"] for b in _books(client, auth_headers)["items"]]

    page_size = 2
    got: list[str] = []
    offset = 0
    while True:
        body = _books(client, auth_headers, limit=page_size, offset=offset)
        got.extend(b["id"] for b in body["items"])
        if not body["has_more"]:
            break
        offset += page_size
        assert offset <= body["total"] + page_size, "翻页没有终止（has_more 一直为真？）"

    assert got == full, f"逐页拼接与全量不一致：\n  逐页={got}\n  全量={full}"
    assert len(set(got)) == len(got), "翻页出现了重复项"
