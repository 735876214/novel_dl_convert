"""源码入库完整性契约（第 105 期）：**本地能构建**不等于**别人 clone 下来能构建**。

起因是一次 CI 红（`Build and Push Image` 连续 30+ 次失败，2026-10-03 起）：

- `.gitignore` 第 11 行写的是 `input/`（本意是仓库根的运行时挂载点），而**不带前导斜杠的
  模式会匹配任意层级的同名目录** ⇒ 第 90 期新增的 `frontend/src/components/ui/input/`
  （`Input.vue` + `index.ts`，被 `ui/sidebar/SidebarInput.vue` import）被**静默忽略、从未入库**；
- 本机文件一直在，所以**本机构建永远是绿的**；CI 从 clone 构建才报
  `[UNLOADABLE_DEPENDENCY] Could not load src/components/ui/input`（vite 的报错），
  而 Dockerfile 里的 `npm run build` 一失败，整个镜像构建（含推送）就全挂。

两条用例分别钉住**机制**与**后果**：
1. 源码树里不许出现被 `.gitignore` 忽略的文件（构建产物 / 依赖 / 缓存除外）；
2. 前端源码里的 `@/...` 别名导入，必须指向一个**已入库**的文件。
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC_DIRS = ("frontend/src", "novelforge")

#: 这些被忽略是**故意的**（构建产物 / 依赖 / 字节码），不算「源码没入库」。
_IGNORED_OK = ("frontend/dist/", "frontend/node_modules/", "novelforge/static/v2/")
_IGNORED_OK_SUFFIX = (".pyc", ".pyo")


def _git(*args: str) -> list:
    """跑一条 git 命令并返回非空输出行；本机没 git / 不是 clone 时整条用例跳过。"""
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("不是 git clone（或本机没有 git）⇒ 无从核对入库情况")
    out = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                         text=True, encoding="utf-8", errors="replace", check=True)
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def _is_intentional(path: str) -> bool:
    return (any(seg in path for seg in _IGNORED_OK)
            or "/__pycache__/" in path
            or path.endswith(_IGNORED_OK_SUFFIX))


def test_源码树里没有被静默忽略的文件():
    """`.gitignore` 的模式写歪了，就会把**源码**一起忽略掉，而本机完全看不出来。"""
    ignored = _git("ls-files", "--others", "--ignored", "--exclude-standard", "--", *SRC_DIRS)
    bad = [p for p in ignored if not _is_intentional(p)]

    assert not bad, (
        "这些源码文件被 .gitignore 忽略了，永远不会入库（本机能跑、别人 clone 就断链）：\n  "
        + "\n  ".join(bad)
        + "\n⇒ 检查 .gitignore 里的模式是否缺了**前导斜杠**（`input/` 会匹配任意层级，"
          "`/input/` 才只匹配仓库根）。"
    )


def test_前端别名导入都指向已入库的文件():
    """`@/x/y` 必须落在**已入库**的路径上 —— 只存在于本机的文件正是 CI 断链的由来。"""
    tracked = set(_git("ls-files", "frontend/src"))
    assert tracked, "frontend/src 一个文件都没入库？"

    refs: list = []
    for path in sorted((ROOT / "frontend" / "src").rglob("*")):
        if not path.is_file() or path.suffix not in (".ts", ".vue", ".js", ".mts"):
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for spec in re.findall(r"""["']@/([^"']+)["']""", text):
            refs.append((str(path.relative_to(ROOT)).replace("\\", "/"), spec))

    assert refs, "一个 @/ 别名导入都没扫到？扫描逻辑大概坏了"
    missing = sorted({f"{where} → @/{spec}" for where, spec in refs
                      if not _resolves(tracked, spec)})
    assert not missing, (
        "这些别名导入指向的文件不在版本库里（本机有、clone 没有 ⇒ CI 构建必挂）：\n  "
        + "\n  ".join(missing)
    )


def _resolves(tracked: set, spec: str) -> bool:
    """`@/` 映射到 `frontend/src/`（见 `frontend/vite.config.ts` 的 alias）。

    不写死扩展名清单：候选 = 原样、`原样.*`、`原样/index.*`，全部在**已入库**集合里找。
    """
    base = "frontend/src/" + spec
    for path in tracked:
        if path == base:
            return True
        if path.startswith(base + ".") or path.startswith(base + "/index."):
            return True
    return False
