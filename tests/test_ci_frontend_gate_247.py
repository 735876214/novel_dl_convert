"""**CI 必须跑前端的质量门**（第 247 期）。

## 缺陷

CI 此前**完全不校验前端**：

- `tests.yml` 只有 pytest 一个 job；
- `docker-image.yml` 的镜像构建只跑 `npm run build`（= `vite build`），
  而 **vite 不做类型检查**（esbuild/rolldown 只转译）⇒ **TS 类型错误不会被
  镜像构建抓到**；
- ⇒ `vue-tsc` 的类型错误与 `vitest` 的单测失败，**CI 全绿**。

而本仓记忆里明写「`vue-tsc` 与 `vitest` 各有对方没有的判据力」——
缺了这两个门，等于**没有守门人**。

## 这里钉的是「那两个命令必须在 CI 里跑」

按**字符串包含**判（不是解析完整 YAML 结构）：改了措辞不会红，
但**删掉 `npm run type-check` 或 `npm run test:unit` 就会红**。
"""
from __future__ import annotations

import pathlib

WORKFLOW = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows" / "tests.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_工作流文件在():
    assert WORKFLOW.is_file(), f"CI 工作流不在：{WORKFLOW}"


def test_CI_跑类型检查():
    """`vue-tsc` 抓的是**只有它能抓**的那一类（props / 导入的类型不匹配）。"""
    assert "npm run type-check" in _text(), (
        "CI 里没有类型检查门 ⇒ TS 类型错误不会被抓到"
        "（注意：vite build **不做**类型检查，只转译）"
    )


def test_CI_跑前端单测():
    """`vitest` 抓的是**只有它能抓**的那一类（真 mount 才暴露的问题）。"""
    assert "npm run test:unit" in _text(), (
        "CI 里没有前端单测门 ⇒ vitest 失败不会被抓到"
    )


def test_前端门与后端门是两个独立的_job():
    """前端 job 独立 ⇒ 与 pytest 并行，不拖慢后端那条。

    ⚠️ 若把两个塞进同一个 job，前端一慢就把后端的结论一起拖迟。
    """
    text = _text()
    assert text.count("runs-on: ubuntu-latest") >= 2, (
        "CI 只有一条流水线 ⇒ 前端门会与后端门串行"
    )
