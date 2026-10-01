"""第 86 期：Cookie（`sources/creds.py`）与凭据路由的契约。

盯住三件事：

1. **格式必须是客户端读得懂的那种**（`LWPCookieJar`）：写错格式等于没写，而且不报错；
2. **必须补域名**：从浏览器复制的串没有 `Domain=`，而 `http.cookiejar` 按域匹配 ——
   不补就是「保存成功了但一直是匿名」这种最难查的静默失败；
3. **任何响应都不许回凭据值**，只回「有没有设置」。
"""
import http.cookiejar as cj
import json
import pathlib

import pytest

from novelforge import config
from novelforge.core import db
from novelforge.sources import base, creds, store, toc_sources


@pytest.fixture(autouse=True)
def _sandbox(isolated):                                     # noqa: ARG001
    """清干净跨用例共享的目录 / REGISTRY / 台账（见 `test_source_ledger.py`）。"""
    d = pathlib.Path(config.SOURCES_DIR)
    d.mkdir(parents=True, exist_ok=True)
    for p in d.glob("*.json"):
        p.unlink()
    for row in db.source_ledger_all():
        db.source_ledger_delete(row["name"])
    for f in pathlib.Path(creds.cookie_dir()).glob("*.cookies.txt"):
        f.unlink()
    before = set(base.REGISTRY)
    yield
    for name in set(base.REGISTRY) - before:
        base.REGISTRY.pop(name, None)


def _rule(name: str, domain: str, vars_: list = None) -> dict:
    tpl = "https://%s/s?q={title}" % domain
    return {
        "name": name, "display_name": name, "domains": [domain], "public": False,
        "search": {"url": tpl, "mode": "css", "container": ".i",
                   "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": "single", "content": {"mode": "css", "container": "#c"}},
        **({"headers": {"X-Token": "{var:密钥}"}} if vars_ else {}),
    }


# ---------------- creds 纯函数 ----------------

def test_解析粘贴串():
    assert [(i["name"], i["value"]) for i in creds.parse_cookie_text("a=1; b=2\nc=3")] == \
        [("a", "1"), ("b", "2"), ("c", "3")]
    # 带属性的整串：属性并到前一条 cookie 上；裸标志（Secure）也要认
    one = creds.parse_cookie_text("s=abc; Domain=.example.com; Path=/x; Secure")
    assert len(one) == 1 and one[0]["domain"] == ".example.com"
    assert one[0]["path"] == "/x" and one[0]["secure"] is True
    # 值里出现 `=` 不许被截断，也不许把值误判成属性
    assert creds.parse_cookie_text("token=a=b; note=domain=x")[1]["value"] == "domain=x"
    assert creds.parse_cookie_text("") == [] and creds.parse_cookie_text("; ;") == []


def test_保存补域名且格式客户端读得懂(isolated):                            # noqa: ARG001
    st = creds.save("my-source", "sid=SECRET; token=T2", ["www.example-novel.com"])
    assert st["has"] is True and st["count"] == 2
    assert st["domains"] == ["example-novel.com"], "www 要去掉：父域覆盖子域，反之不行"
    text = json.dumps(st, ensure_ascii=False)
    assert "SECRET" not in text and "value" not in text, "状态里绝不含凭据值"

    # 落盘格式必须是 BrowserClient 能读的那种
    raw = creds.cookie_file("my-source").read_text(encoding="utf-8")
    assert raw.startswith("#LWP-Cookies-") and "SECRET" in raw
    jar = cj.LWPCookieJar(str(creds.cookie_file("my-source")))
    jar.load(ignore_discard=True, ignore_expires=True)
    assert [c.name for c in jar] == ["sid", "token"]
    assert {c.domain for c in jar} == {"example-novel.com"}


def test_拿不到域名就如实报错(isolated):                                    # noqa: ARG001
    with pytest.raises(ValueError, match="domains"):
        creds.save("x", "a=1", [])
    with pytest.raises(ValueError, match="没解析出"):
        creds.save("x", "", ["x.com"])
    # 串里自带 Domain 时，即使来源没声明域也能存
    assert creds.save("y", "a=1; Domain=.foo.com", [])["domains"] == ["foo.com"]


def test_清除(isolated):                                        # noqa: ARG001
    assert creds.clear("nope") is False, "本来就没有要如实回 False，不假装清掉了"
    creds.save("z", "a=1", ["z.com"])
    assert creds.clear("z") is True and creds.status("z")["has"] is False


def test_cookie文件名契约钉住第85期那个坑():
    """取目录实际读的是**规则名**的文件，不是注册表 id —— 第 85 期就是在这儿静默失效的。"""
    with_rule = [s for s in toc_sources.SOURCES if s.get("rule")]
    assert with_rule, "注册表里至少要有带规则的来源"
    for s in with_rule:
        assert toc_sources.cookie_name(s["id"]) == f"{s['rule']['name']}.cookies.txt"
    assert any(s["rule"]["name"] != s["id"] for s in with_rule), \
        "id 与规则名不同，正是这个契约存在的意义（番茄：id=fanqie / 规则名=fanqie-toc）"
    assert toc_sources.cookie_name("没有这个来源") == "", "未知 id 不编文件名"


# ---------------- 路由 ----------------

def test_接口_保存查询清除都不回值(client, auth_headers):
    name = "cookie-test"
    store.add_rule(_rule(name, "www.cookie-demo.com"))
    r = client.post(f"/api/sources/{name}/cookie", headers=auth_headers,
                    json={"text": "sid=SECRET-VALUE"})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 1
    assert r.json()["declared_domains"] == ["www.cookie-demo.com"]
    # ⚠️ cookie **实际绑定**到归一化后的域（去掉 `www.`）—— 报出来的是真正会生效的那个
    assert r.json()["domains"] == ["cookie-demo.com"]
    assert "SECRET-VALUE" not in r.text, "任何响应都不许回凭据值"

    got = client.get(f"/api/sources/{name}/cookie", headers=auth_headers).json()
    assert got["has"] is True and got["names"] == ["sid"]
    assert "SECRET-VALUE" not in json.dumps(got, ensure_ascii=False)

    d = client.delete(f"/api/sources/{name}/cookie", headers=auth_headers).json()
    assert d["cleared"] is True
    assert client.get(f"/api/sources/{name}/cookie", headers=auth_headers).json()["has"] is False


def test_接口_解析不出就400说清原因(client, auth_headers):
    store.add_rule(_rule("cookie-empty", "cookie-empty.com"))
    r = client.post("/api/sources/cookie-empty/cookie", headers=auth_headers,
                    json={"text": "这不是 cookie"})
    assert r.status_code == 400 and "没解析出" in r.json()["detail"]


def test_接口_变量只回是否设置(client, auth_headers):
    name = "vars-test"
    store.add_rule(_rule(name, "vars-demo.com", vars_=["密钥"]))
    r = client.post(f"/api/sources/{name}/vars", headers=auth_headers, json={"密钥": "S3CRET"})
    assert r.status_code == 200 and r.json()["keys"] == {"密钥": True}
    assert "S3CRET" not in r.text, "变量值等同凭据：只回「已设置」"
    assert r.json()["referenced"] == ["密钥"], "规则里引用到的键要提示出来"

    got = client.get(f"/api/sources/{name}/vars", headers=auth_headers).json()
    assert got["keys"] == {"密钥": True} and "S3CRET" not in json.dumps(got, ensure_ascii=False)

    # 空值 = 清除该键
    client.post(f"/api/sources/{name}/vars", headers=auth_headers, json={"密钥": ""})
    assert client.get(f"/api/sources/{name}/vars", headers=auth_headers).json()["keys"] == {}


def test_接口_登录声明_手写源如实说明(client, auth_headers):
    name = "login-test"
    store.add_rule(_rule(name, "login-demo.com"))
    spec = client.get(f"/api/sources/{name}/login-spec", headers=auth_headers).json()
    assert spec["has_declaration"] is False and spec["needs_cookie"] is True
    assert "手写源" in spec["note"], "没有声明就如实说，不编一份出来"
    assert spec["cookie"]["has"] is False


def test_接口_登录声明_导入源来自原始原文(client, auth_headers):
    from novelforge.sources import ledger
    ent = next(e for e in json.loads(
        (pathlib.Path(__file__).parent / "fixtures" / "legado_sample.json").read_text(encoding="utf-8"))
        if e.get("bookSourceName") == "示例HTML源")
    ledger.apply(ledger.plan([ent], origin="t.json"), origin="t.json")
    name = "lg-example-novel.com"
    spec = client.get(f"/api/sources/{name}/login-spec", headers=auth_headers).json()
    assert spec["has_declaration"] is True, "导入源必须用台账里的原始声明"
    assert isinstance(spec["vars"], list) and "unsupported" in spec
    assert spec["cookie"]["has"] is False


def test_凭据接口都要鉴权(client):
    for path in ("/api/sources/x/cookie", "/api/sources/x/vars", "/api/sources/x/login-spec"):
        assert client.get(path).status_code in (401, 403)
