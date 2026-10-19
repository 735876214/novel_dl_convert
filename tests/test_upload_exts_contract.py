"""上传 / 投递白名单契约（第 122 期）。

**事故**：用户报「zip 格式的书导入后不能识别」。查下来后端一直收得下 zip
（`novelforge/core/pipeline.py::EBOOK_EXT` 从第 87 期起就有 `.zip`，第 110 期加了 `.azw`，
第 111 期加了 `.rar` / `.7z`），是**前端**「工具 → 本地转换」页自己维护的白名单漏了这四个，
拖一本 zip 漫画进去直接弹「已跳过 1 个不支持的格式」，一个文件都不投递。

那段注释当时写的是「与后端 `POST /convert` 的允许集一致 = `core/pipeline.EBOOK_EXT`」——
**注释是真的，代码是假的**：它已经悄悄漂移了三代，而前端没有任何东西会因此变红
（页面单测只验「不支持的格式被跳过」，`.xyz` 是它自己举的例）。

所以这里用纯文本断言把两个集合钉在一起（与 `tests/test_first_run_contract.py` 同一套做法：
仓内配置契约用 pytest 解析前端源码）。修法只有一条路 —— 改后端白名单就必须同批改这里。
"""

from __future__ import annotations

import re
from pathlib import Path

from novelforge.core import pipeline

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "frontend" / "src"
VIEW = SRC / "views" / "tools" / "LocalConvertView.vue"

#: 后端允许集里**容易再被漏掉**的那几个：通用容器 + MOBI 家族的老后缀。
#: 单列出来是为了让失败信息一眼看出「又是谁被漏了」，而不是只报「集合不等」。
SUSPECTS = (".zip", ".rar", ".7z", ".azw", ".cbz", ".cbr")


def _view_source() -> str:
    assert VIEW.is_file(), f"找不到前端视图：{VIEW}"
    return VIEW.read_text(encoding="utf-8")


def _frontend_allowed() -> list[str]:
    """从 `const ALLOWED_EXT = [...]` 里取出扩展名列表（保持声明顺序）。"""
    src = _view_source()
    m = re.search(r"const ALLOWED_EXT\s*=\s*\[(.*?)\]", src, re.S)
    assert m, "LocalConvertView.vue 里找不到 `const ALLOWED_EXT = [...]`（被改名了？）"
    return re.findall(r"'(\.[a-z0-9]+)'", m.group(1))


def test_前端白名单与后端允许集逐项一致():
    front = _frontend_allowed()
    back = set(pipeline.EBOOK_EXT)
    missing = sorted(back - set(front))
    extra = sorted(set(front) - back)
    assert not missing, (
        f"前端白名单漏了后端收得下的格式 {missing} —— 拖这类文件会被前端以"
        f"「不支持的格式」直接跳过（第 122 期的 zip 事故就是这么来的）"
    )
    assert not extra, (
        f"前端白名单比后端多出 {extra} —— 前端放行、后端 400 拒收，用户会拿到"
        f"「点了没反应 / 投递失败」"
    )


def test_容器与mobi老后缀都在白名单里():
    front = set(_frontend_allowed())
    for ext in SUSPECTS:
        assert ext in front, f"{ext} 不在前端白名单里（它属于后端 EBOOK_EXT）"


def test_白名单没有重复项():
    front = _frontend_allowed()
    assert len(front) == len(set(front)), f"ALLOWED_EXT 里有重复项：{front}"


def test_accept_由同一份白名单派生():
    """`<input accept>` 不许再抄一份 —— 抄一份就多一处会漂移的真值源。"""
    src = _view_source()
    assert "const ACCEPT = ALLOWED_EXT.join(',')" in src, (
        "ACCEPT 不再由 ALLOWED_EXT 派生（或写法变了）：确认 `accept=` 属性仍跟着白名单走"
    )
    assert not re.search(r"const ACCEPT\s*=\s*\[", src), "ACCEPT 被写成了第二份字面量清单"


def test_前端只有这一处书籍后缀白名单():
    """单一真值源：别的 .vue / .ts 里不许再出现一份「书籍后缀清单」。

    判据取「同时出现 `'.cbz'` 和 `'.epub'`」—— 只提到某一种格式（文档说明、示例文件名）
    的文件不算。`.spec.ts` 是测试自己的夹具，不参与判据。
    """
    hits = []
    for p in sorted(SRC.rglob("*")):
        if p.suffix not in {".vue", ".ts"} or p.name.endswith(".spec.ts"):
            continue
        if p == VIEW:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if "'.cbz'" in text and "'.epub'" in text:
            hits.append(str(p.relative_to(ROOT)))
    assert not hits, (
        f"这些文件里出现了第二份书籍后缀白名单：{hits} —— 白名单只许有一处"
        f"（`LocalConvertView.vue` 的 ALLOWED_EXT），否则迟早再漂移一次"
    )
