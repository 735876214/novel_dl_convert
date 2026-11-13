r"""持续审计第 2 轮（第 279 期）：**上传件的名字必须是纯文件名**。

这一轮扫了三个角度，两个零发现（**别重查**）：

- **数据库层：热查询的索引匹配** —— 用 `EXPLAIN QUERY PLAN` 逐个过：进度（按书 / 书+文件）、
  批注、书签、阅读会话（按书 / 时间窗）、`book_index`（按库 / 按 id / 脏库探测）、
  `collection_items`（按夹 / 按书）、`reading_status`、`meta_override` —— **全部 `SEARCH … USING INDEX`**。
  唯一一处 `SCAN` 是 `koreader_docs WHERE doc_md5=? OR alt_md5=?`（两列都没索引），
  实测 5000 行时 **0.22 ms/次**、KOReader 同步是低频动作 ⇒ **不构成缺陷**，不为此加索引。
- **前端状态一致性（乐观更新有没有回滚）** —— 全站口径是「**一律以服务端回答为准**，
  不在本地数组里 splice 出乐观结果」（`ShelfView.vue` 的注释），只有一处**刻意**的乐观切换
  （`KoreaderPage.vue` 的开关），且它**失败会回滚**（`if (!(await save())) st.value.enabled = !want`）。

一条发现：**`/convert` 的上传件带目录 ⇒ 500 + 误导文案**。

```
'../../逃出去.cbz'   -> 400「非法路径（不允许绝对路径或 ..）」        ✓（第 119 期的包含性校验）
'/etc/逃出去.cbz'    -> 400                                          ✓
'a/b/c.cbz'          -> 500「上传件写盘失败（可能磁盘已满或没有写权限）」  ✗
```

根因：`fileops.input_path` **按设计**允许子目录 —— 那是给 `/convert-path` 用的
（要读下载器在收书目录里建的分目录），而**上传**这条路不会替客户端建目录 ⇒
`a/b/c.cbz` 一路走到「写临时件」那一步才炸，回一句**误导**的话（真实原因是
「那个子目录不存在」）。而 `/convert` 是**未鉴权**的历史入口，谁都能用。

**修法**（判据按入口性质分，不是一刀切）：`/convert` 先拒「名字里带 `/` 或 `\`」，
返回与 `..` 同一档的 **400 + 人话**；`/convert-path` **保持允许**收书目录内的子路径
（用例双向钉住）。
"""
import io
import zipfile

import pytest

from novelforge import config


def _cbz_bytes(pages: int = 2) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for i in range(pages):
            b = io.BytesIO()
            Image.new("RGB", (20, 30), (i * 20, 0, 0)).save(b, "PNG")
            z.writestr(f"{i + 1:03d}.png", b.getvalue())
    return buf.getvalue()


def _post(client, name: str):
    return client.post("/convert", files={
        "file": (name, _cbz_bytes(), "application/vnd.comicbook+zip")})


@pytest.mark.parametrize("name", [
    "a/b/c.cbz", r"a\b\c.cbz", "../../逃出去.cbz", r"..\..\逃出去.cbz", "/etc/逃出去.cbz",
])
def test_上传件名字不许带目录(client, isolated, name):   # noqa: ARG001
    r = _post(client, name)
    assert r.status_code == 400, f"{name!r} -> {r.status_code} {r.text[:80]}"
    assert "目录" in r.text or "非法路径" in r.text, r.text


def test_正常名字照旧能收(client, auth_headers, make_library, tmp_path):   # noqa: ARG001
    """闸门不许把正常路径挡掉。"""
    root = tmp_path / "L"
    root.mkdir(parents=True, exist_ok=True)
    make_library("L", "库", "comic", root)
    r = _post(client, "正常 书名.cbz")
    assert r.status_code == 200, r.text
    assert r.headers.get("content-disposition")


def test_收书目录内的子路径仍能走_convert_path(client, auth_headers, make_library, tmp_path):  # noqa: ARG001
    """**反向**：`/convert-path` 是「读收书目录里已有的文件」，下载器建的子目录必须照旧可用。

    闸门只加在**上传**那条路上 —— 加宽到这条就等于把「下载插件的分目录」废掉。
    """
    root = tmp_path / "L2"
    root.mkdir(parents=True, exist_ok=True)
    make_library("L2", "库", "comic", root)
    sub = config.INPUT_DIR / "下载器分目录"
    sub.mkdir(parents=True, exist_ok=True)
    target = sub / "书.cbz"
    target.write_bytes(_cbz_bytes())
    r = client.post("/convert-path", data={"path": "下载器分目录/书.cbz"})
    assert r.status_code == 200, r.text


def test_convert_path_仍挡穿越(client):
    """反向的边界：子路径可以，**出收书目录**不行。"""
    r = client.post("/convert-path", data={"path": "../../etc/passwd"})
    assert r.status_code == 400, r.text
    assert "非法路径" in r.text or ".." in r.text
