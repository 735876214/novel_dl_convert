"""第 86 期：JS 解密通道的**部署前提**（`NODE_BIN` / Node 是否真的存在）。

用户当场提出的一条现实约束：**NAS 里未必有 Node**。Docker 镜像自带
（多阶段构建 + `NODE_BIN=/usr/local/bin/node`），但手工 / NAS 部署不一定 —— 而 `NODE_BIN`
默认就是 `"node"`。所以这里钉两件事：

1. 缺 Node 时抛的是**人话**（说清「什么跑不了、怎么补」），不是英文系统错误；
2. **有 Node 时真的把脚本跑起来**（不是只跑桩）—— 真机结论才算验证。
"""
import pathlib

import pytest

from novelforge.core import network


def test_缺node报的是人话而不是系统错误(monkeypatch):
    monkeypatch.setattr(network, "NODE_BIN", str(pathlib.Path("C:/没有这个目录/node-不存在")))
    st = network.node_state(refresh=True)
    assert st["available"] is False
    assert st["bin"].endswith("node-不存在")
    # 必须能照做：说清哪台机器的问题、什么会跑不了、怎么补
    assert "Node" in st["reason"] and "NODE_BIN" in st["reason"]
    assert "书源" in st["reason"]

    with pytest.raises(RuntimeError) as e:
        network.run_js_sync("console.log(1)")
    assert not isinstance(e.value, FileNotFoundError)
    assert "NODE_BIN" in str(e.value), "报错要带上「去设置 NODE_BIN」这条出路"


def test_node不可用时能力接口如实回(client, auth_headers, monkeypatch):
    monkeypatch.setattr(network, "NODE_BIN", str(pathlib.Path("C:/没有这个目录/node-不存在")))
    r = client.get("/api/sources/capabilities?refresh=true", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["decrypt"] is False and body["node"]["available"] is False
    assert body["hint"] and "NODE_BIN" in body["hint"], "界面要能直接把这句话显示出来"


def test_有node时脚本真的跑起来():
    st = network.node_state(refresh=True)
    if not st["available"]:
        pytest.skip(f"本机没有 Node（{st['reason']}）：跳过真机执行；部署前提见 /api/sources/capabilities")
    assert st["version"], "有 Node 就该能读到版本号"
    # 真的起一次子进程：__args 传入、JSON 输出解析回来
    assert network.run_js_sync("console.log(JSON.stringify([__args[0] + __args[1], '好']));",
                              1, 2) == [3, "好"]
    assert network.run_js_sync("console.log('纯文本');") == "纯文本"

    r = network.node_state(refresh=True)
    assert r["available"] is True and r["reason"] == ""


def test_run_js异步包装可用():
    import asyncio

    st = network.node_state()
    if not st["available"]:
        pytest.skip("本机没有 Node")
    assert asyncio.run(network.run_js("console.log(String(__args[0]).toUpperCase());", "abc")) == "ABC"
