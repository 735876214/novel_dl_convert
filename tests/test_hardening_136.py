"""第 136 期回归：按书取路径 / 原子写 / 目录缓存 / OPDS 分页 的判据不许退回旧写法。

这一轮修的都是「单点写法错了、但单测照绿」的缺陷 —— 正确性来自**判据唯一**：
同一件事全仓只有一处实现。所以这里用静态断言钉住「旧写法不得重新出现」，
比造一个能跑绿的数据流更贴近真实回归面（旧写法在磁盘/容器环境里才暴露）。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / "novelforge"


def _src(rel: str) -> str:
    return (CORE / rel).read_text(encoding="utf-8")


def test_按书取路径不许再自己拼根目录和书名():
    """`library.root_of(b) / b["name"]` 在多文件夹库里会指到另一个根上的同名文件。

    判据只许一处：`library.abs_path(book)`。这条断言覆盖 core/ 与 sources/ 全量。
    """
    bad = []
    for p in list(CORE.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.endswith("core/library.py"):
            continue                      # 判据本身的实现处
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"root_of\([^)]*\)\s*/\s*", text):
            line = text[: m.start()].count("\n") + 1
            if text.splitlines()[line - 1].lstrip().startswith("#"):
                continue                  # 注释里点出旧写法是在说明**为什么**不能这么写
            bad.append(f"{rel}:{line}")
    assert bad == [], f"这些地方还在自己拼「代表根 + 书名」：{bad}"


def test_追更_sidecar_与音轨都是原子写():
    """直写最终名会「先截断后失败」——半截 JSON 让追更永久报错，旧轨被毁且无留档。"""
    text = _src("sources/manager.py")
    assert '.part")' in text, "sidecar / 音轨的原子写写法不见了"
    assert 'sidecar.write_text(json.dumps' not in text, "sidecar 退回直写"
    assert "(dest / f\"第{i}话{ext}\").write_bytes" not in text, "音轨退回直写"


def test_作者头像与活配置都是原子写():
    assert "photo_tmp.write_bytes(bytes(buf))" in _src("core/authors.py")
    server = (ROOT / "novelforge" / "server.py").read_text(encoding="utf-8")
    assert 'cfg_tmp.replace(config.CONFIG_FILE)' in server
    assert "shutil.copy2(src, config.CONFIG_FILE)" not in server


def test_来源文件夹被清空的库不能只标_fresh():
    """旧写法只 `_mark_fresh` 就返回 ⇒ 索引里的旧行一条不删，书架永远挂着幽灵书。"""
    text = _src("core/catalog.py")
    old = """    if not _lib.roots_of(lib):
        _mark_fresh(lid)"""
    assert old not in text, "roots 为空的分支退回「只标 fresh 就返回」"
    assert "refresh_library(lib)                 # roots 空" in text


def test_丢列表缓存要先删再忘():
    """`cache.drop` 吞异常：先忘后删的话，drop 失败就再也删不到这个键。"""
    text = _src("core/catalog.py")
    block = text[text.index('if out.get("added") or out.get("removed"):') :][:600]
    assert block.index("cache.drop(") < block.index("_cached_libs.discard("), (
        "顺序反了：必须 drop 成功之后才从 _cached_libs 里忘掉"
    )


def test_刮削启动门槛要看残留的_running_行():
    """进程在刮削中途被杀 ⇒ 行停在 running，而启动门槛只查 pending ⇒ 队列永久停摆。"""
    server = (ROOT / "novelforge" / "server.py").read_text(encoding="utf-8")
    assert 'db.scrape_list(status="running", limit=1)' in server


def test_清空日志要连尾随窗口一起丢():
    """只清 _memory 的话，10s 合并窗口走完会把刚删掉的条目写回 activity.jsonl。"""
    text = _src("core/activity_log.py")
    idx = text.index("def clear(")
    body = text[idx : idx + 900]
    assert "_pending.clear()" in body, "clear() 不清 _pending ⇒ 清空后条目会复活"

