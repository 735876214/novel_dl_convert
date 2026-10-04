"""第 94 期：导入入口的**统一路由**（`sources/intake.py`）与「静默失败」回归钉。

## 本文件存在的理由（用户原始 bug）

「书源管理 → 导入书源」卡走的是 `POST /api/sources` / `/api/sources/upload`。第 94 期
之前这两个接口**只认本项目 native schema**，把 Legado 原文逐条判成

    ['缺少 name（唯一标识）', '缺少 domains（域名白名单数组）', 'search.url 必填']

然后**回 HTTP 200** + ``{"added": [], "errors": [...]}``；前端又只读 `added`
（且它是**名字数组**，被拒时 `[]` 渲染成空串）⇒ 用户看到「已添加  个书源」，
结论就是「项目中没有反应」。同一个坑还埋着第二颗雷：本项目**自己导出**的文件
（`{"nf_export":1,"entries":[...]}`）从这张卡也导不进去 —— 而「导出→导入幂等」
是第 86 期已被钉住的承诺。

所以本文件盯三件事：
1. **静默 200 绝不许再出现**（下面 `test_不再返回静默200…` 是回归钉）；
2. 两个接口与 `/api/sources/import` 走**同一条**解析路（同一份输入、同一个结论）；
3. `mode=save` / `mode=import` 两种口径分别对应「手写表单保存」与「导入卡」，
   不许互相串味（串了就是「点保存什么都没发生」或「导一次盖掉一条」）。

⚠️ 全部离线：只用仓库自带夹具，不出网。
"""
import json
import pathlib

import pytest

from novelforge import config
from novelforge.core import db
from novelforge.sources import base, intake, ledger, store

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "legado_sample.json"
SOURCES_DIR = lambda: pathlib.Path(config.SOURCES_DIR)          # noqa: E731 —— 目录随夹具变


@pytest.fixture(autouse=True)
def _sandbox(isolated):                                     # noqa: ARG001
    """与 `test_source_import_api.py` 同款沙箱：规则目录 / 台账 / 注册表都清干净。"""
    d = SOURCES_DIR()
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob("*.json"):
        p.unlink()
    for row in db.source_ledger_all():
        db.source_ledger_delete(row["name"])
    db.source_imports_clear()
    before = set(base.REGISTRY)
    yield
    for name in set(base.REGISTRY) - before:
        base.REGISTRY.pop(name, None)


def _html_entry() -> dict:
    return next(e for e in json.loads(FIXTURE.read_text(encoding="utf-8"))
                if e.get("bookSourceName") == "示例HTML源")


def _hand_rule(name: str, domain: str = "other.com") -> dict:
    return {
        "name": name, "display_name": "手写的", "domains": [domain], "public": False,
        "search": {"url": f"https://{domain}/s?q={{title}}", "mode": "css", "container": ".i",
                   "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": "toc", "toc": {"mode": "css", "container": ".l a"},
                 "content": {"mode": "css", "container": "#c", "text": True}},
    }


def _names(client, h) -> set:
    return {s["name"] for s in client.get("/api/sources", headers=h).json()["sources"]}


# ---------------- ① 静默失败回归钉 ----------------

def test_不再返回静默200_Legado原文必须真落盘(client, auth_headers):
    """第 94 期之前：200 + ``added: []`` + 三条「缺少 name」错误，盘上一个文件都没有。"""
    r = client.post("/api/sources", headers=auth_headers,
                    content=json.dumps(_html_entry(), ensure_ascii=False).encode("utf-8"))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["format"] == "legado-3", "要如实报出识别成什么格式"
    assert data["counts"]["new"] == 1 and data["errors"] == []
    assert data["added"] == ["lg-example-novel.com"]
    assert (SOURCES_DIR() / "lg-example-novel.com.json").is_file(), \
        "回 200 就必须真落盘 —— 这正是当年缺的那一步"
    assert "lg-example-novel.com" in _names(client, auth_headers)


def test_同一份输入三条路结论必须一致(client, auth_headers):
    """`/api/sources`、`/upload`、`/import` 对**同一份**输入必须给出同一个结论。

    这是「两条路两套口径」那条老毛病的正面表述：任何一处漏了 `intake`，这条就会红。
    """
    entry = _html_entry()
    blob = json.dumps(entry).encode("utf-8")
    a = client.post("/api/sources", headers=auth_headers, content=blob).json()
    assert a["counts"]["new"] == 1 and a["errors"] == []
    name = a["added"][0]

    # 已经落盘了 ⇒ 另外两条路必须**一致地**判「重复」，而不是「认不出 / 冲突」
    b = client.post("/api/sources/upload", headers=auth_headers,
                    files={"file": ("x.json", blob, "application/json")}).json()
    c = client.post("/api/sources/import", headers=auth_headers,
                    json={"payload": json.dumps(entry), "origin": "t", "dry_run": True}).json()
    assert b["counts"]["duplicate"] == 1 and b["counts"]["update"] == 0
    assert [i["verdict"] for i in c["rows"]] == ["duplicate"]
    assert c["rows"][0]["name"] == name


def test_认不出格式要400加人话原因_绝不静默校验(client, auth_headers):
    for bad in ("", "这不是书源", "<xml><source/></xml>", "{}"):
        r = client.post("/api/sources", headers=auth_headers, content=bad.encode("utf-8"))
        assert r.status_code == 400, f"输入 {bad!r} 竟然回了 {r.status_code}"
        assert "无法识别格式" in r.json()["detail"], r.text
        assert "Legado" in r.json()["detail"], "原因要能直接照做，不是「解析失败」"


def test_上传文件走同一条路(client, auth_headers):
    raw = FIXTURE.read_bytes()
    r = client.post("/api/sources/upload", headers=auth_headers,
                    files={"file": ("legado_sample.json", raw, "application/json")})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["format"] == "legado-3"
    assert data["counts"]["new"] >= 1, "整份夹具里至少有一条是可执行的"
    assert data["origin"] == "legado_sample.json"
    assert "lg-example-novel.com" in _names(client, auth_headers)
    # 夹具里也有跑不了的条目 ⇒ 必须逐条给出人话原因，而不是只回一个计数
    if data["counts"]["unsupported"]:
        assert data["errors"] and data["errors"][0]["error"]


def test_本项目导出的文件能从快路导回去(client, auth_headers):
    """第 94 期之前这份文件从「导入书源」卡**导不回去**（自家导出认不出自家格式）。"""
    client.post("/api/sources", headers=auth_headers,
                content=json.dumps(_html_entry()).encode("utf-8"))
    payload = client.get("/api/sources/export", headers=auth_headers).json()

    r = client.post("/api/sources/upload", headers=auth_headers,
                    files={"file": ("export.json",
                                    json.dumps(payload).encode("utf-8"), "application/json")})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["format"] == "nf-export"
    # 导出→导入幂等：判「重复」而不是「更新」（第 86 期已有的承诺，快路也必须守住）
    assert data["counts"]["duplicate"] == 1 and data["counts"]["update"] == 0


# ---------------- ② 两种动作口径 ----------------

def test_导入卡撞名默认跳过_手写源一个字都不许动(client, auth_headers):
    """`mode=import`：保守口径 —— 撞名冲突跳过，**绝不覆盖用户手写的东西**。"""
    store.add_rule(_hand_rule("mine", "www.example-novel.com"))     # 同站点、不同名 → 冲突
    r = client.post("/api/sources", headers=auth_headers, params={"mode": "import"},
                    content=json.dumps(_html_entry()).encode("utf-8"))
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["conflict"] == 1 and r.json()["counts"]["skipped"] == 1
    assert "mine" in _names(client, auth_headers)
    assert "lg-example-novel.com" not in _names(client, auth_headers), "跳过就该一条都没多"


def test_手写表单保存撞名按覆盖_且覆盖前备份旧规则(client, auth_headers):
    """`mode=save`（= 第 94 期之前的老行为）：表单是显式 upsert。

    ⚠️ 这条用例防的是**我自己差点写出的回归**：若 `saveForm` 也走导入卡的保守口径，
    「编辑一个与既有源同名的书源」会变成「点了保存却什么都没发生、还提示已保存」。
    """
    name = "lg-example-novel.com"
    store.add_rule(_hand_rule(name, "other.com"))            # 同名、不同站点 ⇒ 撞名冲突
    r = client.post("/api/sources", headers=auth_headers, params={"mode": "save"},
                    content=json.dumps(_html_entry()).encode("utf-8"))
    assert r.status_code == 200, r.text
    assert r.json()["counts"]["conflict"] == 1 and r.json()["counts"]["skipped"] == 0
    saved = json.loads((SOURCES_DIR() / f"{name}.json").read_text(encoding="utf-8"))
    assert saved["display_name"] == "示例HTML源", "保存必须真的覆盖"
    assert saved["domains"] == ["www.example-novel.com"], "覆盖后站点也跟着新规则走"
    hist = client.get(f"/api/sources/{name}/history", headers=auth_headers).json()["items"]
    assert len(hist) == 1, "覆盖前必须把旧规则原文备份进历史（可回滚）"


def test_不可执行的行要带人话原因(client, auth_headers):
    """判 `unsupported` 的行**不许只回一个空结果**：要给「为什么 / 该怎么办」。"""
    entry = next(e["raw"] for e in intake.rows_from_payload(
        json.loads(FIXTURE.read_text(encoding="utf-8")))["rows"] if e["verdict"] == "unsupported")
    r = client.post("/api/sources", headers=auth_headers, content=json.dumps(entry).encode("utf-8"))
    assert r.status_code == 200, r.text
    errs = r.json()["errors"]
    assert errs and errs[0]["error"], "不可执行却不给原因 = 让用户对着列表猜"
    assert (SOURCES_DIR() / f"{errs[0]['name']}.json").exists() is False, "不可执行的不落规则"
    assert db.source_ledger_get(errs[0]["name"]) is not None, "但要进台账，能看见、能删"


def test_残缺的本项目规则要如实报错且不写入(client, auth_headers):
    """规则本体缺必填项时：**回 200 也要把路堵死**（老代码在这里 200 + 空 added 静默丢件）。"""
    r = client.post("/api/sources", headers=auth_headers,
                    content=json.dumps({"name": "半成品", "domains": ["a.com"]}).encode("utf-8"))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["added"] == [] and data["errors"], "没写进去就必须报出来"
    assert "search.url" in data["errors"][0]["error"], "原因要取自 validate_rule 的原话"
    assert not (SOURCES_DIR() / "半成品.json").exists()


# ---------------- ③ `intake` 纯函数 ----------------

def test_detect_认得出四种输入():
    entry = json.dumps([_html_entry()])
    assert intake.detect(entry) == intake.FORMAT_LEGADO
    assert intake.detect(json.dumps({"nf_export": 1, "entries": []})) == intake.FORMAT_EXPORT
    assert intake.detect(json.dumps({"version": 2, "entries": []})) == intake.FORMAT_EXPORT
    native = json.dumps({"name": "x", "domains": ["a.com"]})
    assert intake.detect(native) == intake.FORMAT_NATIVE
    assert intake.detect("") == "" and intake.detect("not json") == ""


def test_导出信封必须在legado之前判():
    """信封既没有 `bookSourceName` 也没有 `name`+`domains` —— 顺序颠倒了会判成「认不出」。"""
    payload = {"nf_export": 1, "entries": [{"bookSourceName": "X", "bookSourceUrl": "https://a.com"}]}
    assert intake.detect(payload) == intake.FORMAT_EXPORT
    assert intake.unpack_entries(payload) == payload["entries"]


def test_ledger_entries_of_委托给intake_只此一份判据():
    """`entries_of` 与 `intake` 认的格式必须**逐字一致**（否则老毛病会原样长回来）。"""
    for payload in (json.dumps([_html_entry()]),
                    json.dumps({"nf_export": 1, "entries": [_html_entry()]})):
        assert ledger.entries_of(payload) == intake.unpack_entries(payload)


def test_坏输入抛ValueError而不是静默回空():
    for bad in ("", "不是书源", "[]"):
        with pytest.raises(ValueError):
            intake.sniff_and_adapt(bad)


def test_判unsupported的行理由不许留空():
    """界面上出现一个「不能用但不说为什么」的条目 = 与本项目的纪律直接冲突。"""
    rows = intake.rows_from_payload(json.loads(FIXTURE.read_text(encoding="utf-8")))["rows"]
    bad = [r for r in rows if r["verdict"] == "unsupported"]
    assert bad, "夹具里必须有不可执行的条目，否则这条用例是假绿"
    for r in bad:
        assert r["unsupported_fields"], f"{r['name']} 判了不可执行却没给理由"
        assert r["unsupported_fields"][0]["why"], "理由不能是空串"
