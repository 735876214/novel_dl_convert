"""部署面：构建上下文 / 运行层 / 预压缩的**静态判据**（第 179 期体积优化）。

这些都不是运行时行为，但每一条漏了都只会表现为「镜像白大了 / 优化没生效」，没有任何
用例会顺带覆盖到 —— 所以和 `test_hardening_144_deploy.py` 一样，直接读文件钉住。

钉四条：

1. 运行层**不再** COPY `requirements.txt`（没有代码读它；builder 用的是 /tmp 那份）；
2. builder 删掉上游包自带的 `tests/` 目录（只匹配目录名恰好是 tests 的那一层）；
3. `.dockerignore` 覆盖那些「从不进镜像、却会被打包进构建上下文」的大目录；
4. 预压缩脚本与其清单和后端的选用判据**对得上**（`npm run build` 会调它，Docker 也走它）。
"""
import pathlib
import re

from novelforge import server

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_运行层不再拷贝_requirements():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    runtime = text.split("AS runtime", 1)[-1]
    assert "COPY start.sh config.yaml /app/" in runtime
    assert not re.search(r"^COPY .*requirements\.txt .* /app/", runtime, re.M), (
        "运行层不该再拷 requirements.txt —— 没有代码读 /app/requirements.txt"
    )
    # builder 仍然要读它（这是依赖安装的唯一输入）
    assert "COPY requirements.txt /tmp/requirements.txt" in text


def test_builder_删掉上游包自带的_tests_目录():
    text = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "-type d -name tests -prune -exec rm -rf {} +" in text
    # 只许精确匹配 tests —— 写宽成 `*test*` 会连 numpy/testing（运行时要用的模块）一起删
    assert "-name '*test*'" not in text


def test_dockerignore_覆盖大目录():
    lines = {
        ln.strip() for ln in (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    }
    for needed in ("docs/", "tests/", "clients/", "pgdata/", "scripts/", ".codebuddy/"):
        assert needed in lines, f".dockerignore 少了 {needed}（每 build 都会白送进上下文）"
    # 反向：预压缩脚本在 frontend/scripts 下，绝不能把前端工程排除掉
    assert "frontend/" not in lines


def test_预压缩清单与后端判据一致():
    """构建期生成哪些后缀的 `.gz`/`.br`，必须与后端 `_COMPRESSIBLE_EXTS` 对得上 ——
    两边各写一份清单就是第二份真值源（漏一个后缀 = 那个资源永远选不到预压缩件）。"""
    js = (ROOT / "frontend" / "scripts" / "precompress.mjs").read_text(encoding="utf-8")
    for ext in sorted(server._COMPRESSIBLE_EXTS):
        assert f"'{ext}'" in js, f"precompress.mjs 少了 {ext}（后端会去找它的旁路件）"


def test_构建脚本会生成旁路件():
    """Docker 的 frontend 阶段跑的是 `npm run build` —— 预压缩必须挂在这个脚本上，
    只挂 `deploy` 的话镜像里不会有 `.gz`（服务端只能回落现压，优化静默失效）。"""
    pkg = (ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    assert '"build": "vite build && node scripts/precompress.mjs dist"' in pkg
