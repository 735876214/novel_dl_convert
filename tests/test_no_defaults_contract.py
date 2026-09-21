"""「不设默认」契约：书库 / 智能书架 / 收藏夹三组一律**空着出厂**。

第 37 期的口径（用户拍板）：全新部署时这三组都是空的，建什么、叫什么，全部由用户
手动新增。这条改动的**关键风险是回潮** —— 默认项这种东西最容易在后续某一期里
「顺手加一条方便用户」，而它一旦回来，用户就又得先删掉不想要的东西才能开始用。

所以这里用**纯文本 + 常量断言**把「没有默认」钉死（不碰 DB、不需要夹具，
与 `test_settings_nav_contract.py` 同一套做法：仓内前端没有 vitest，配置契约就用
pytest 校验）：

1. `data/collections.ts` 的三个骨架数组都是空的，且那 5 条内置智能书架的名字不再出现；
2. 后端「默认库」这个概念**整个**不存在了（常量 / 合成函数 / 启动播种都不许回来）；
3. `smart_scopes` / `collections` 两张表只在各自的 `create_*` 里插入（没有种子数据）；
4. 规则字段白名单在后端 `SCOPE_OPS` 与前端 `FIELD_OPS` 里**逐字一致**
   （两边各留一份是本仓既有的设计，但写歪了只会在运行期表现为「选了字段筛不出书」）；
5. 书库的三个写接口都走 `_libraries_changed()` 钩子 —— 没有可接收的库时投递会被拒收，
   而拒收计入失败次数、到上限就永久跳过；「建完库文件自己动起来」全靠这个钩子。

第 4 条不是「不设默认」的一部分，而是为「那 5 条内置书架删掉后能用手搓规则重建」
兜底 —— 补上的 `批注数` / `入库天数` 两个字段必须两边同时认识。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COLLECTIONS_TS = ROOT / "frontend" / "src" / "data" / "collections.ts"
NAV_TS = ROOT / "frontend" / "src" / "data" / "nav.ts"
SMART_SCOPE_TS = ROOT / "frontend" / "src" / "lib" / "smartScope.ts"
LIBRARY_PY = ROOT / "novelforge" / "core" / "library.py"
SERVER_PY = ROOT / "novelforge" / "server.py"
DB_PY = ROOT / "novelforge" / "core" / "db.py"

#: 第 37 期前硬编码在侧栏「智能书架」组里的 5 条内置书架
BUILTIN_SHELF_LABELS = ["最近添加", "未读", "在读", "已完成", "有批注"]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ① 侧栏三组：骨架是空的，没有预置条目
# ---------------------------------------------------------------------------

def test_侧栏三组骨架都是空数组():
    src = _read(COLLECTIONS_TS)
    for name in ("LIBRARIES", "SMART_SHELVES", "COLLECTIONS"):
        m = re.search(rf"export const {name}\s*:\s*NavEntry\[\]\s*=\s*\[(.*?)\]", src, re.S)
        assert m, f"{name} 的声明形状变了，请同步本测试"
        body = re.sub(r"//[^\n]*", "", m.group(1)).strip()
        assert body == "", f"{name} 必须为空骨架（第 37 期：不设默认），实际：{body!r}"


def test_内置智能书架的名字不再出现在侧栏数据里():
    for f in (COLLECTIONS_TS, NAV_TS):
        src = _read(f)
        for label in BUILTIN_SHELF_LABELS:
            assert f"'{label}'" not in src and f'"{label}"' not in src, \
                f"{f.name} 里又出现了内置书架「{label}」—— 默认项不许回潮"


def test_智能书架组只吃后端规则书架():
    """组的 items 必须是空骨架（条目由侧栏用 `smart_scopes` 覆盖），不能写死条目。"""
    assert "items: SMART_SHELVES" in _read(NAV_TS)


# ---------------------------------------------------------------------------
# ② 后端「默认库」概念整个下线
# ---------------------------------------------------------------------------

def test_后端不再有默认库这个概念():
    src = _read(LIBRARY_PY)
    for needle in ("DEFAULT_LIBRARY_ID", "def default_library", "def ensure_default_library"):
        assert needle not in src, f"library.py 里「默认库」概念回潮了：{needle}"


def test_启动不再播种任何书库():
    """lifespan 里不许再出现「建一条库」的调用 —— 播种是这条需求的核心禁止项。"""
    src = _read(SERVER_PY)
    m = re.search(r"async def lifespan\(app: FastAPI\):(.*?)\n@", src, re.S)
    assert m, "lifespan 的形状变了，请同步本测试"
    body = m.group(1)
    assert "create_library" not in body and "ensure_default" not in body
    assert "db.init()" in body, "前置：lifespan 仍应初始化持久层"


def test_内核也不合成假库():
    src = _read(LIBRARY_PY)
    # `libraries()` 必须老老实实返回真实行；`_scan_once` 没有库就不扫
    assert "rows or [default_library()]" not in src
    assert "lib = lib or default_library()" not in src


# ---------------------------------------------------------------------------
# ③ 两张表都没有种子数据（只有显式 create_* 能插入）
# ---------------------------------------------------------------------------

def test_智能书架与收藏夹都没有种子数据():
    src = _read(DB_PY)
    for table in ("smart_scopes", "collections"):
        hits = [i for i, line in enumerate(src.splitlines(), 1)
                if f"INSERT INTO {table}" in line]
        # 各只允许一处：`create_scope` / `create_collection` 内部
        assert len(hits) == 1, f"{table} 的 INSERT 应只有 create_* 里那一处，实际行号 {hits}"


# ---------------------------------------------------------------------------
# ④ 规则字段白名单：后端与前端逐字一致
# ---------------------------------------------------------------------------

def _parse_field_ops_ts() -> dict:
    src = _read(SMART_SCOPE_TS)
    m = re.search(r"export const FIELD_OPS[^{]*\{(.*?)\n\}", src, re.S)
    assert m, "FIELD_OPS 的形状变了，请同步本测试"
    out: dict = {}
    for line in m.group(1).splitlines():
        line = line.split("//")[0].strip()
        if not line:
            continue
        k, _, v = line.partition(":")
        ops = re.findall(r"'([a-z_]+)'", v)
        assert k.strip() and ops, f"解析不出这条字段规则：{line!r}"
        out[k.strip()] = set(ops)
    return out


def test_规则字段白名单前后端逐字一致():
    """`server.SCOPE_OPS` 与 `lib/smartScope.ts` 的 `FIELD_OPS` 必须同集合。

    本仓刻意两边各留一份（前端求值、后端校验，见 server.py 的注释），代价就是**必须
    有测试钉住**：少一个字段的表现是「管理页能选、选完筛不出书」，极难排查。
    """
    from novelforge import server
    backend = {k: set(v) for k, v in server.SCOPE_OPS.items()}
    assert backend == _parse_field_ops_ts()
    assert set(server.SCOPE_FIELDS) == set(backend), "SCOPE_FIELDS 与 SCOPE_OPS 的键集合必须一致"


def test_内置书架删掉后_fields_仍能重建它们():
    """那 5 条内置书架下线后，规则引擎必须凑得出等价条件 —— 否则是能力净损失。

    · 未读 / 在读 / 已完成 → `status`
    · 有批注             → `annotations`（第 37 期补）
    · 最近添加           → `added`（第 37 期补，单位=入库天数）
    """
    from novelforge import server
    assert {"status", "annotations", "added"} <= set(server.SCOPE_FIELDS)
    assert {"at_least", "at_most"} <= set(server.SCOPE_OPS["annotations"])
    assert {"at_least", "at_most"} <= set(server.SCOPE_OPS["added"])


# ---------------------------------------------------------------------------
# ⑤ 书库增删改必须走统一钩子（否则「建完库文件才被收走」会失灵）
# ---------------------------------------------------------------------------

def test_书库增删改都走_libraries_changed_钩子():
    """三个书库写接口都不许再裸调 `library.invalidate()`。

    第 37 期没有可接收的库时会**拒收**投递，而拒收也走失败计数，到 `max_retries`
    就永久跳过。用户照着提示建完库／补完规则，原先的文件必须自己动起来 ——
    这件事只有 `_libraries_changed()`（= invalidate + `forget_failures()`）会做。
    漏掉任何一个写接口的表现是「明明建好了库，input 里的文件却再也不进来」，
    而且**不报任何错**。行为侧由 `test_watcher_perlibrary` 的建库用例覆盖，
    这里只钉「新增写接口时别忘记接上」。
    """
    src = _read(SERVER_PY)
    for fn in ("api_create_library", "api_update_library", "api_delete_library"):
        m = re.search(rf"\ndef {fn}\(.*?(?=\n@app\.|\ndef )", src, re.S)
        assert m, f"{fn} 的形状变了，请同步本测试"
        body = m.group(0)
        assert "_libraries_changed()" in body, f"{fn} 没接上 _libraries_changed 钩子"
        assert "library.invalidate()" not in body, f"{fn} 应改用 _libraries_changed()"
    assert "def _libraries_changed()" in src and "forget_failures()" in src
