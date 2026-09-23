"""前端单测护栏自身的契约（第 39 期）。

第 39 期给前端立了第一套单测（vitest + @vue/test-utils）。但**护栏本身也会被拆掉** ——
删掉 npm script、把配置块挪走、或者把 `ChartGrid` 那条编译期类型标注放宽，
都能让护栏悄悄失效，而 `pytest` 与 `npm run test:unit` 两边都不会报错。

所以这里钉的不是「某个功能对不对」，而是「**护栏还在不在**」。

## 为什么是纯文本断言，而不是从 pytest 里调 `npx vitest`

本仓库的硬前提是**全量测试离线**。从 pytest 里拉子进程跑 node 会破坏它；
退一步写成「有 node 才跑、没有就 skip」则更糟 —— 那是一个**永远绿**的假交互，
比没有测试更误导人。故两边各管各的：前端 spec 由 `npm run test:unit` 跑，这里只静态核对。

## 为什么不重复断言 `ChartGrid` 的「id 都有组件」

那条不变式是**编译期**的：`StatisticsChartId = keyof typeof STATISTICS_CHART_META`
（`lib/statistics-charts.ts`），于是 `Record<StatisticsChartId, Component>` 里少一个 id
**直接编译失败**。再写运行期断言只是把 `npm run type-check` 重做一遍，且更弱。
真正的回归风险是**有人把这条标注放宽**（比如改成 `Record<string, Component>`）——
那会让编译期保护失效却依然能构建通过。所以这里钉的是**标注本身**。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
PKG_JSON = FRONTEND / "package.json"
VITE_CONFIG = FRONTEND / "vite.config.ts"
CHART_GRID = FRONTEND / "src" / "components" / "charts" / "ChartGrid.vue"
STATISTICS_CHARTS = FRONTEND / "src" / "lib" / "statistics-charts.ts"

#: 第 39 期的三个 devDependency。少任何一个，`npm run test:unit` 都跑不起来。
REQUIRED_DEV_DEPS = ("vitest", "@vue/test-utils", "happy-dom")

#: 本期立的前端 spec。每个都必须真的存在**且含至少一个用例** ——
#: 空文件同样会让 `vitest run` 报绿。
EXPECTED_SPECS = (
    "src/views/ReaderView.spec.ts",
    "src/stores/library.spec.ts",
    # 第 40 期：阅读阈值是「全前端唯一的判定入口」，它的行为由这条 spec 兜住
    "src/lib/readingThresholds.spec.ts",
    # 第 40 期：新建向导。「立即创建」必须**真的建库**（不是只关浮层），这条 spec 兜住
    "src/components/tools/LibraryWizard.spec.ts",
    # 第 40 期：路径判据（向导与编辑弹窗共用一份）。原来两处各写一遍 `startsWith('/')`，
    # Windows 上把 `C:\…` 判成非绝对 ⇒ 向导卡在第 2 步。
    "src/lib/paths.spec.ts",
    # 第 43 期：书架首字母分桶（跳转条的唯一判据源）。分错桶不会报错、只是跳错位置，
    # 故用 spec 把「拉丁按首字 / 非拉丁归 # / 桶序升序」钉死。
    "src/lib/shelfBuckets.spec.ts",
)


def _pkg() -> dict:
    return json.loads(PKG_JSON.read_text(encoding="utf-8"))


def test_前端单测脚本存在且口径正确():
    """脚本名是 `test:unit`，**不是** `test`。

    本仓库说的「测试」历来专指 pytest 那 632 例；把前端单测也叫 `test`
    会让「跑一下测试」这句话失去唯一含义，基线数字也会被混着算。
    """
    scripts = _pkg().get("scripts", {})
    assert "test:unit" in scripts, (
        "package.json 缺 `test:unit` 脚本 —— 前端护栏没有入口了。"
        f"现有脚本：{sorted(scripts)}"
    )
    assert scripts["test:unit"] == "vitest run", (
        f"`test:unit` 必须是 `vitest run`（跑完即退，不进 watch），实际是 {scripts['test:unit']!r}"
    )


def test_三个前端测试依赖都在_devDependencies():
    dev = _pkg().get("devDependencies", {})
    missing = [d for d in REQUIRED_DEV_DEPS if d not in dev]
    assert not missing, f"package.json 的 devDependencies 缺：{missing}"


def test_vite_config_承载_vitest_配置():
    """vitest 配置写在 `vite.config.ts` 里，**不另起 `vitest.config.ts`**。

    理由：`vite.config.ts` 的 `resolve.alias['@']` 是本仓库**唯一**的 `@` 定义，
    另起一个配置文件就得把它复制一份 —— 那正是本仓库一直在避免的「两处各写一遍」。
    """
    cfg = VITE_CONFIG.read_text(encoding="utf-8")
    assert 'reference types="vitest/config"' in cfg, (
        "vite.config.ts 顶部缺 `/// <reference types=\"vitest/config\" />` —— "
        "没有它 `defineConfig` 不认 `test` 字段"
    )
    assert re.search(r"\btest:\s*\{", cfg), "vite.config.ts 里找不到 `test:` 配置块"
    assert "environment: 'happy-dom'" in cfg or 'environment: "happy-dom"' in cfg, (
        "test 块里没有 environment: 'happy-dom'"
    )
    assert "include:" in cfg, "test 块里没有 include（会把非 spec 文件也当用例收）"
    assert not (FRONTEND / "vitest.config.ts").exists(), (
        "出现了 vitest.config.ts —— 会把 `@` 别名复制成第二份真值源"
    )


def test_前端_spec_文件存在且不是空壳():
    for rel in EXPECTED_SPECS:
        p = FRONTEND / rel
        assert p.exists(), f"前端 spec 缺失：{rel}"
        body = p.read_text(encoding="utf-8")
        assert re.search(r"\b(it|test)\(", body), (
            f"{rel} 里没有任何 `it(` / `test(` —— 空壳 spec 同样会让 vitest 报绿"
        )


def test_chartgrid_的编译期穷尽性标注还在():
    """`Record<StatisticsChartId, Component>` 是「忘登记组件」的唯一防线。

    放宽成 `Record<string, Component>` 后，少登记一个 id 不再编译失败，
    而 tile 的 `<div>` 照占栅格、里面什么都没有 —— 第 33 期修掉的那个静默空白会回来。
    """
    grid = CHART_GRID.read_text(encoding="utf-8")
    assert re.search(r"Record<\s*StatisticsChartId\s*,\s*Component\s*>", grid), (
        "ChartGrid.vue 的 `Record<StatisticsChartId, Component>` 标注被改了 —— "
        "编译期穷尽性保护失效"
    )
    charts = STATISTICS_CHARTS.read_text(encoding="utf-8")
    assert re.search(r"type\s+StatisticsChartId\s*=\s*keyof\s+typeof\s+STATISTICS_CHART_META", charts), (
        "`StatisticsChartId` 不再由目录的键推导 —— ChartGrid 那条 Record 就兜不住了"
    )
