"""**每个** CSV 导出端点都要防公式注入（第 132 期补 · 第 244 期补漏）。

## 漏的那一处

第 132 期给书目导出与批注导出都套了 `csvsafe.row`，但**审计日志导出**
（`GET /api/logs/export`）的 `writerow` **没套** ⇒ 它的字符串也是用户可控的：

- `file` / `output` —— **书名**（从外面拖进来的 EPUB 自带文件名）；
- `actor` —— 登录账号名。

一本叫 `=cmd|'/c calc'!A0` 的书 ⇒ 用户导出审计日志、在 Excel 里双击打开 ⇒
那段文字被当公式求值（第 132 期防的正是这个，此处漏了）。

## 这里钉住的是「**每个** writerow 都套了 csvsafe」

不止补这一处 —— 断言全仓**所有** `csv.writer` 的每一次 `writerow` 都经过
`csvsafe.row`（新加导出端点时立刻红）。
"""
from __future__ import annotations

import ast
import pathlib

SERVER = pathlib.Path(__file__).resolve().parents[1] / "novelforge" / "server.py"


def _csv_writerows() -> list:
    """所有**在 CSV 导出函数里**的 `writerow(...)` 调用。

    写法是 `buf = io.StringIO()` + `w = csv.writer(buf)`（**不是** `with csv.writer(...)`）
    ⇒ 判据按「**含 `csv.writer(...)` 赋值的函数**」来找，而不是按 `with` 块。
    """
    tree = ast.parse(SERVER.read_text(encoding="utf-8"))
    out: list = []
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        has_csv_writer = False
        for sub in ast.walk(fn):
            if not isinstance(sub, ast.Assign) or not isinstance(sub.value, ast.Call):
                continue
            f = sub.value.func
            if (isinstance(f, ast.Attribute) and f.attr == "writer"
                    and isinstance(f.value, ast.Name) and f.value.id == "csv"):
                has_csv_writer = True
        if not has_csv_writer:
            continue
        for sub in ast.walk(fn):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "writerow"):
                out.append((sub.lineno, sub))
    return out


def test_所有_csv_writerow_都套了_csvsafe():
    calls = _csv_writerows()
    assert calls, "没找到 csv.writer 的 writerow —— 解析器口径变了？"
    for lineno, call in calls:
        # `w.writerow(csvsafe.row([...]))` —— 数据行必须套 csvsafe.row
        assert len(call.args) == 1, f"server.py:{lineno} writerow 的参数不是单个"
        arg = call.args[0]
        assert isinstance(arg, ast.Call), f"server.py:{lineno} writerow 没有套 csvsafe.row"
        f = arg.func
        assert isinstance(f, ast.Attribute) and f.attr == "row", \
            f"server.py:{lineno} 调的不是 csvsafe.row"
        assert isinstance(f.value, ast.Name) and f.value.id == "csvsafe", \
            f"server.py:{lineno} 调的不是 csvsafe.row"


def test_审计日志导出会给危险前缀加单引号(client, auth_headers, isolated):
    """端到端：一本书名以 `=` 开头 ⇒ 导出的 CSV 单元格被加前缀（不再是公式）。"""
    from novelforge.core import activity_log

    activity_log.log(activity_log.ACTION_METADATA, "=cmd|'/c calc'!A0",
                     activity_log.STATUS_OK, source="test")
    r = client.get("/api/logs/export", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.text
    assert "'=cmd|'/c calc'!A0" in body, "审计日志导出没有防公式注入"
