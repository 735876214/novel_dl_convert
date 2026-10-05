# AGENTS.md 合规核查（第 95 期）

> 目的：按 `AGENTS.md`（第 1 节硬约束 + 第 7 节工程原则）**逐条核查项目现状**，产出可执行的发现清单。
> 方法：四个只读子代理并行分轴核查（A 单一真值源 / B 数据安全不变量 / C 旧路径与死代码 / D 重复造轮子与视觉层），
> 所有结论均以 `file:line` 为证，父代理对关键条目**二次独立复核**。
> 时效：本文件是 **2026-10 第 95 期的快照**，行号会随代码演进漂移；请以符号名 grep 复核。

## 0. 基线（实测，非引用）

| 项 | 实测值 | 命令 |
|---|---|---|
| 后端全量 | **2104 passed / 25 skipped / 0 failed**（310.16s） | `.venv\Scripts\python.exe -m pytest --junitxml=$env:TEMP\nf.xml` |
| 前端单测 | **65 spec / 673 passed** | `cd frontend && npm run test:unit` |
| 前端类型 | **0 error** | `cd frontend && npm run type-check` |
| 版本 | `VERSION` = `0.94.0` | — |

与外传基线 `AGENTS.md:84`「2129 例」一致（2104 + 25 = 2129 收集数）⇒ **该数字准确，未过期**。
（⚠️ 本节是**审计当时**的快照。整改后基线变为 **2147 例（2122 passed / 25 skipped）**，
`AGENTS.md:84` 已同批更新 —— 见 §6「实测」。）

## 1. 环境陷阱：代理变量会让 pytest 大面积假失败（新发现）

**现象**：本机首次跑全量得 `45 failed, 2059 passed`，失败集中在 `test_network_limits`(7) / `test_sources_search`(7) /
`test_online_read`(22) / `test_online_bind`(4) / `test_source_url_import`(4) / `test_sources_gate`(1)。

**根因**：`httpx` 0.28.1 解析 `NO_PROXY` 里的方括号 IPv6 `[::1]` 时会生成畸变代理 mount：

```
httpx._utils.get_environment_proxies()
=> {'http://': 'http://127.0.0.1:7897', 'https://': '...', 'all://localhost': None,
    'all://127.0.0.1': None, 'all://[::1]': None, 'all://*[::1]': None}   # ← 末项畸变
httpx.InvalidURL: Invalid port: ':1]'    # 堆栈 tests/test_network_limits.py:155
```

**处置**：清空 `HTTP_PROXY` / `HTTPS_PROXY` / `http_proxy` / `https_proxy` / `NO_PROXY` / `no_proxy` 后重跑 ⇒
`2104 passed, 0 failed`。**属本机环境，非产品回归**。建议写入 `AGENTS.md` §4 陷阱（见 §5 建议）。

## 2. 违反第 7.1 节「不为向后兼容留路」的旧路径

| 严重度 | 位置 | 事实 |
|---|---|---|
| high | `novelforge/server.py:8177-8187` | `/api/metadata/sources` 自陈「兼容端点；第 57 期起设置页改用 /providers」，仓内唯一消费者是 `frontend/src/views/settings/pages/MetadataPage.vue:266` 的 catch 兜底 |
| high | `novelforge/server.py:8058-8059`、`:8186` | `has_googlebooks_key` 双写字段（注释「兼容旧字段名」）；前端仅 `frontend/src/lib/api.ts:4002` 类型标注，无 `.vue` 消费；`tests/test_metadata_providers.py:238` 钉着它 |
| high | `novelforge/server.py:9215`（`/convert`）与 `novelforge/server.py:9260`（`/convert-path`） | 近乎逐字重复的两份实现（opts→`target_root`→400→`pipeline.dispatch`→`log_convert_fail`→`_log_dispatch`→`remember_origin`→`FileResponse`），段标题 `novelforge/server.py:9196` 即「兼容旧接口」。**注意：两条路由前端都在用**（`frontend/src/lib/api.ts:3259 convertDrop` → `/convert`、`:3277 convertPathDrop` → `/convert-path`），故正确处置是**收敛为单一 helper，两条路由都保留**，而不是删路由 |
| high | `novelforge/server.py:8276-8277`、`:8291-8292` | `/api/metadata/probe` 同时认 `keys`（早期）与 `configs`（新）两种入参；被 `tests/test_metadata_providers.py:156-174` 钉住 |
| med | `novelforge/config.py:103-105`、`:109`；`novelforge/server.py:6723-6729`、`:6809` | `output.format` 兼容保留键；`config.py:105` 称「前端下拉还从它取值」**已失真**（`frontend/src/views/settings/pages/ConversionPage.vue:19-20` 明写该块已删） |
| med | `novelforge/server.py:5182-5185` + `frontend/src/lib/api.ts:4728` → `frontend/src/stores/library.ts:128/541-556/795/804` | `/api/library-facets` 全链路无调用者（`loadLibraryFacets` 仅定义与导出） |
| med | `novelforge/sources/manager.py:421-423` | `update()` 兼容壳只回 `Path`；真实调用方仅 `novelforge/cli.py:165` 与 `tests/test_update_report.py:148` |
| low | `novelforge/server.py:3032-3033` | `written: []` 保留字段（前端仅类型） |
| low | `novelforge/sources/manager.py:58/203/207` | `_source` 历史键自写自读 |
| low | `novelforge/sources/manager.py:87`、`:108-115` | `gate_reason(source=…)` 形参不参与判定，10+ 调用点仍传 |
| low | `novelforge/core/metasources.py:410-411` | `key_field_of` **非违规，仅文案误标**：docstring 自陈「保留这个入口是为了兼容既有调用」，但它实际是 `config_fields_of` 的**派生访问器**、且有 3 处真实生产调用（`novelforge/server.py:8290`、`metasources.py:450`、`tests/test_metadata_providers.py:50/52/201`）⇒ 只需改注释 |
| low | `novelforge/config.py:52-53` | `LIBRARY_SOURCE_DIR` 兼容别名：**Python 常量**在生产代码里零引用，消费方全在 `tests/`（~20 个文件）。⚠️ **但它镜像的那个环境变量不是死路径** —— `novelforge/config.py:45-48` 的「未配置任何编号变量时回退单根 `LIBRARY_SOURCE_DIR`」是一条**真实部署模式**（单根部署，`docker-compose.yml` / 文档都在用），**必须保留** |
| low | `novelforge/server.py` 的 `/content` 端点（按符号名 grep，行号已被本期整改改写） | `/content` 端点仓内零消费者（**仓外消费者无法从仓内证明**） |
| med | `novelforge/server.py:182-183` | `return "0.80.0"` —— 全仓唯一残留的**第二份版本字面量**（VERSION 读不到时的回退）。`novelforge/__init__.py:13-16` 自陈第 79 期已删 `__version__`；`tests/test_version_contract.py:16` 只验 `/health == server.APP_VERSION`，**VERSION 存在时暴露不出这个回退值** |
| med | `frontend/src/lib/sourceImport.ts:50-56` | `FORMAT_LABELS` 是后端 `display_name`（`novelforge/sources/formats/legado3.py:14` / `legado2.py:20` / `jsonl.py:13` / `native.py:16` / `nf_export.py:39`）的**第二份拷贝**，且 5 键里 3 个文案已发散；后端本该唯一的入口 `novelforge/sources/formats/base.py:137 format_label()` **全仓零调用方**（仅 `novelforge/sources/formats/__init__.py:19`、`:24` 再导出）⇒ 服务端从不下发中文名，界面只能自抄 |
| med | `frontend/src/data/settingsFields.ts:248` | `libraries: ['libraries'],` 是**死条目**：全仓 `saveSection('libraries')` 零命中，`novelforge/server.py:6726 EDITABLE` 里**没有** `libraries`（`:6791-6795` 注释说明第 77 期已删整条），`GET /api/config` 恒回 `:7014 "libraries": {}` |
| med | `novelforge/config.py:228-229` + `novelforge/server.py:6754`/`:6986` | `notifications.merge_enabled` / `merge_window` **后端三处已接通**（默认值 / 白名单 / 回显 / 唯一读点 `novelforge/core/activity_log.py:219-224`），但 `frontend/src` 全量 grep **零命中** —— 界面没有出口（`NotificationsPage.vue:31` 那套是纯 localStorage 客户端过滤，与这两个键无关） |
| med | `novelforge/core/komga.py:40-41` ↔ `novelforge/core/fileops.py:46-48` | 「不安全文件名字符」判据**两份逐字相同**的正则（`_BAD_CHARS` / `_BAD_TAIL`），`novelforge/core/komga.py:51` 自陈「同规则但**故意不共用**」（理由：fileops 依赖 library，layout 要能被 pipeline 直接调用）；代价是 `novelforge/core/publish.py:125-126` 注释把 fileops 那份称作收尾权威，而目录型条目实际走 `komga.clean_segment`（`komga.py:118-119`）⇒ 改一处不同步另一处 |

## 3. 违反第 7.2 节「最简实现 / 禁投机抽象」的死配置与死代码

- `novelforge/core/db.py:4963-4964` `LIBRARY_MODES = ("inplace",)` —— 全仓仅定义处 1 命中（对照 `novelforge/core/db.py:4962 LIBRARY_TYPES` 有 4 命中）。
- `novelforge/core/comics.py:80` `append_pages` 真·原地追加（`zipfile.ZipFile(cbz, "a")`），`novelforge/` 内**无生产调用者**。
  ⚠️ **父代理复核后改判**：它**不是**「数据安全违规的死代码」—— 目标对象是本项目**自己的成品 CBZ**
  （`novelforge/sources/manager.py:535` 用 `comics.write_cbz` 产出），不是用户源文件；且 `tests/test_append_media.py`
  有 **6 个用例**直接钉它（漫画 3 + 有声书 3）。它的真实性质是「第 86 期第 6 步『音频/漫画追加写回』的既定能力，
  **从未接线**」—— 同族的 EPUB 分支 `novelforge/core/epub_update.py:174 append_chapters` **已接线**
  （`novelforge/sources/manager.py:404`）。**本期保留未删**（删它 = 删能力 + 删 6 个用例，属取舍而非清理）。
- `novelforge/cli.py:194` —— ⚠️ **父代理复核后撤销这条**：`scan` 走 `novelforge/cli.py:224-226 args.once = True; cmd_watch(args)`，
  而 `cmd_watch` 在 `once=True` 时只跑 `scan_once()` 就返回 ⇒ `--interval` 对 `scan` **确实无效**，
  那句 help「（保留参数，单次扫描无需间隔）」是**准确的**。原判据把 `:91-92`（`watch` 的用法）当成了 `scan` 也在消费它。
- `frontend/src/stores/dashboard.ts:23` 注释「本项目纯静态无后端，两者都存 localStorage」—— 事实错误（本项目有后端）。
- `novelforge/core/pipeline.py:471`（docstring）/`:475-482` —— `chapter_regex` 分支：`regex = (opts.get("chapter_regex") or "").strip()` / `if regex:` / `_re.compile(regex, _re.M).finditer(text)`。该键**全仓只有这两处**（无任何生产者）⇒ 分支恒不执行，且它**绕过了 `core/saferegex`**（执行期正则的唯一入口）。注意 `convert_chapters` 本身在生产链上（`novelforge/sources/manager.py:282`），死的是这个键。
- `novelforge/core/comics.py:80` 另注：`novelforge/core/comics.py:38-54 write_cbz` 是合规的 `.part` + `replace` 实现 ⇒ 同一个文件里两份写实现。

## 4. 违反第 7.5/7.6 节「优先成熟库 / 先查已有依赖」

| 严重度 | 位置 | 事实 |
|---|---|---|
| high | `novelforge/core/library.py:202`/`:414`/`:278`/`:288`/`:350`/`:520`/`:656`/`:918`、`:559 _NavParser` | 手写正则解析 EPUB/OPF/NCX XML；同仓 `novelforge/sources/rules.py:457` 已在用 BeautifulSoup、`novelforge/core/epub_cfi.py:31` 已 import `xml.etree.ElementTree` |
| high | `novelforge/core/metasources.py:1067`(Amazon) / `:1088`(Goodreads) / `:1184`(Libro.fm) / `:1206`(Lubimyczytac) | 14 家提供商里 5 家用正则抓 HTML；同文件 `:482 _strip_html` docstring 自陈「不必引第三方解析器」（但 bs4 已是依赖） |
| med | `novelforge/core/fileops.py:385`/`:394`/`:413`/`:566-571` | 手写正则改写 OPF XML |
| low | `novelforge/sources/generic.py:80-82` | 模板里手搓剥标签，与 `novelforge/sources/rules.py:470 html_to_text`（自称唯一实现）语义重复 |

**需修正的子代理结论**：`novelforge/sources/generic.py:62` 调用 `network.run_js`（无沙箱 Node 通道）而非 `novelforge/core/network.py:537 run_source_js`（契约入口）——
但该类在 `novelforge/sources/generic.py:14-17` 明写**刻意不注册**，且 `:90` `fetch_book()` 抛 `NotImplementedError`、`:88` 那行调用是注释 ⇒
**属教学模板的死路径**，应降级为「示范了错写法」，非线上违规。

## 4.5 文档 / 注释 / 计数过期（不违反行为，但会误导后续会话）

| 位置 | 现状 | 事实 |
|---|---|---|
| `AGENTS.md:25` | 写「引擎能执行什么」`rules._MODES` | 实际符号是 `novelforge/sources/rules.py:1279 MODES = ("css", "regex", "json", "xpath")`（无下划线）；`novelforge/sources/selspec.py:93 _MODES` 是**另一样东西**（阅读选择器语法名）⇒ **已修**（改 `rules.MODES`） |
| `AGENTS.md:77` | 「docs/ 既有对照文档 + **本次新增的 5 份**」 | 第 44 期措辞已过期；`docs/` 实为 21 份 md（顶层 11 + `docs/bookorbit/` 6 + `docs/review/` 2 md）⇒ **已修** |
| `AGENTS.md` 文档地图 | 缺 `docs/format-capability-matrix.md`、`docs/roadmap-verification.md`；`docs/bookorbit-*.md` 路径写法已随 `git mv` 过期 | ⇒ **已补两行 + 修为 `docs/bookorbit/bookorbit-*.md`** |
| `AGENTS.md` §2 remap 行 | 只列四处 | 代码实有**六份**清单（另有 `novelforge/core/db.py:2816 REMAP_DERIVED_TABLES`、`:2833 REMAP_MERGE_TABLES`）；契约 `tests/test_remap_tables.py:56-57` 只并前三份，但 `:16 _tables_with_book_id()` 直接问库 ⇒ **表口径不全，非代码缺陷** ⇒ **已补注** |
| `frontend/src/router/index.ts:136` | 注释「设置页的 **48** 个子路由」 | 实测 **37** 页（`frontend/src/data/settingsNav.ts:445 SETTINGS_PAGES`；契约 `tests/test_settings_nav_contract.py:118 assert len(pages) == 37`） |
| `frontend/src/data/settingsNav.ts:281` | note「支持 **9** 个占位符」 | `novelforge/core/fileops.py:54-55 PATTERN_FIELDS` 已是 **10** 个（含 `{narrators}`，第 53 期） |
| `novelforge/core/fileops.py:52` 与 `:231` | 「第 20 期定下 **9** 个」/ docstring「``PATTERN_FIELDS`` 的 **9** 个占位符」 | 同上是 10 个 —— **真值源文件自己的计数过期** |
| `novelforge/server.py:183` | 回退字面量 `"0.80.0"` 与 `:182` 日志同值 | 见 §2 med 行 |

**无守卫但代码合规**：路由注册顺序 —— 遍历 `novelforge/server.py` 全部 349 处 `@app.<method>()`，未发现被参数化路由遮蔽的字面量路由（**NO SHADOWED LITERAL ROUTES**）；但 `grep "app.routes|router.routes" tests/` 零命中，只有散点用例 `tests/test_book_delete.py:330`（docstring「参数化路由吞字面量路径在本仓踩过两次」）与 `tests/test_scrape_publish.py:364-365`。
同理 `novelforge/core/db.py:5052 _LIBRARY_COLS`（15 列，docstring 自陈「新增列必须同时加进来，否则静默写不进」）只有 `tests/test_api_smoke.py:643` 覆盖其中 3 列。

## 5. 建议（原始清单 · **处置结果见 §6**）

**本次已实施（文档校准，不改产品行为）**：§4.5 标「已修 / 已补」的三条 —— `AGENTS.md:25` 的 `rules._MODES` → `rules.MODES`；`AGENTS.md:77` 的「本次新增的 5 份」改为指向文档地图；文档地图补 `docs/format-capability-matrix.md` + `docs/roadmap-verification.md`、修 `docs/bookorbit/bookorbit-*.md` 路径、补 `docs/review/` 行；§2 remap 行补 `REMAP_DERIVED_TABLES` / `REMAP_MERGE_TABLES`；§4 陷阱新增「跑 pytest 前清空全部 proxy 变量」。

**待确认后实施**（按「同类一锅端」分批，删的同时改调用点与用例 —— §7.1「发现第二份实现 = 缺陷」）：

1. **加契约测试守纪律**：`docs/DESIGN.md:4` 写死「组件里禁止硬编码颜色/圆角/阴影」，但实测
   `frontend/src/views/ReadingActivityView.vue:15/49/183/195`（用了 `docs/DESIGN.md:6-7` 明确作废的 `#2563eb`）、
   `frontend/src/components/settings/SettingsSearchPanel.vue:129`（`bg-[#0f172a]/25`，应走 `bg-scrim`）、
   `frontend/src/components/charts/library/LibraryIntegrityGaugeChart.vue:51-55` 与 `:87-91`（应走 `--score-*`）等均无一测试拦截
   ⇒ 建议仿 `tests/test_frontend_unit_contract.py` 加一条扫描 `.vue` 字面色值的契约用例（现无任何测试钉住这些值，改动不会撞用例）。
2. **旧路径清理（§2）**：元数据兼容通道、`/convert` 双实现收敛、`output.format`、`/api/library-facets`、`manager.update()`、`written`、`_source`、`LIBRARY_SOURCE_DIR` 等。
3. **死代码 / 死配置（§3 + §4.5）**：`LIBRARY_MODES`、`comics.append_pages`、`pipeline.chapter_regex` 分支、`settingsFields.ts` 的 `libraries` 死条目、`sourceImport.ts` 的 `FORMAT_LABELS`（改为从后端取 `format_label`）、`server.py:183` 版本回退字面量。
4. **半截接线**：`notifications.merge_enabled` / `merge_window` —— 择一：删后端两键，或补前端控件。
5. **重复造轮子（§4）**：`novelforge/core/library.py` 的 EPUB/OPF/NCX 正则 → BeautifulSoup / ElementTree；`novelforge/core/metasources.py` 五家 HTML 抓取 → bs4；`novelforge/core/fileops.py` OPF 改写 → ElementTree。
6. **判据合并**：`novelforge/core/komga.py:40-41` 与 `novelforge/core/fileops.py:46-48` 的 `_BAD_CHARS` / `_BAD_TAIL` 二选一（`komga.py:51` 的「故意不共用」理由需重新评估）。
7. **文档计数修正**：`frontend/src/router/index.ts:136`（48→37）、`frontend/src/data/settingsNav.ts:281`（9→10）、`novelforge/core/fileops.py:52`/`:231`（9→10）、`frontend/src/stores/dashboard.ts:23` 假注释。
8. **数据安全两处待定口径**（非删除，需决策）：
   - `novelforge/core/zipkind.py:227-230` 是唯一能真 `unlink` 用户书文件的路径（经 `novelforge/server.py:3418` 可被 API 打到；前端 `frontend/src/components/tools/LibraryCopiesPanel.vue:54` 传默认 false）——与第 1 节「从不 unlink」冲突。
   - `novelforge/core/landing.py:375-382` 首次落地原地 `replace` 书本体；就地库下 `dest` 即用户原文件（`novelforge/core/watcher.py:517`）；增量路径由 `novelforge/core/landing.py:174-193 updatable()` 守住，但**自动落地那一支**（`novelforge/server.py:1468-1499`）无二次确认。

## 6. 整改落地（第 95 期实施结果）

> 用户在 §5 上**全选**了批次 1–6（即授权动手改产品代码）。本节记录**实际做了什么**、
> **哪些复核后撤销/改判**、以及**哪些没做及原因** —— 报告与代码不一致时以本节为准。
> ⚠️ `VERSION` **未改**（仍 `0.94.0`，用户 2026-10-05 选择「先不发版」）⇒ 无 CHANGELOG 段、无 tag/Release。

### 已实施

| 批次 | 落地内容 |
|---|---|
| 7 文档计数 | `frontend/src/router/index.ts:136` 删掉写死的「48 个子路由」；`frontend/src/data/settingsNav.ts:281`、`frontend/src/views/settings/pages/FileNamingPage.vue:193`（**审计漏的第 4 处**）「9 个占位符」→ 按后端 `PATTERN_FIELDS` 的 10 项重述；`novelforge/core/fileops.py:52`/`:231` 的「9 个」→ 10 个；`frontend/src/stores/dashboard.ts:18-25` 那颗假注释「本项目纯静态无后端」改写为真实理由（本地视图偏好、不进同步载荷） |
| 3 死代码 | 删 `novelforge/core/db.py` 的 `LIBRARY_MODES`；删 `novelforge/core/pipeline.py` 的 `chapter_regex` 死分支（它**绕过 `core/saferegex`**，且无生产者；书源正则切章由 `novelforge/sources/rules.py:1176 _split_regex` 承接）；删 `frontend/src/data/settingsFields.ts` 的 `libraries: ['libraries']` 死条目（`saveSection('libraries')` 零命中、后端 `EDITABLE` 无该段） |
| 4 半截接线 | 删 `notifications.merge_enabled` / `merge_window` 三处（`config.DEFAULTS` / `EDITABLE` / `GET /api/config` 回显）+ 唯一读点 `activity_log.merge_cfg()` 常量化（新增 `MERGE_WINDOW = 10.0`，删掉配置读取、5 秒缓存与零调用方的 `invalidate_merge_cache()`）—— 界面从来没有过出口，是**假配置** |
| 2 旧路径 | ① `output.format` 兼容链整条删（`config.DEFAULTS` 的键、`EDITABLE` 收成 `{"layout"}`、**`FORMAT_CHOICES` 常量**与 `/api/config` 的值域校验）；② `frontend/src/lib/sourceImport.ts` 的 `FORMAT_LABELS` 第二份表**删除**，三条导入路改为**后端下发** `format_label`（唯一产出点 `novelforge/sources/formats/base.py:137 format_label`，此前零调用方）；③ `/api/metadata/sources` 兼容端点 + `has_googlebooks_key` 双写键删除，前端那道「回落旧接口」的 catch 兜底收敛为如实报错；④ `/api/metadata/probe` 的 `keys`（早期入参）删除，只留 `configs`；⑤ `/api/library-facets` 全链路删（路由 + `novelforge/core/library.py` 的 `library_groups()` + 前端 api/store/类型 + `loadDedup.spec.ts` 的 mock）；⑥ `DownloadManager.update()` 只回 `Path` 的兼容壳删除（CLI 改调 `update_report` 并打印真实报告）；⑦ `/api/books/{bid}/metadata` 的 `written: []` 恒空字段删除；⑧ `key_field_of` 的「为兼容而保留」误标注释改为「派生读取器」；⑨ `novelforge/server.py` 版本兜底字面量 `"0.80.0"` → 哨兵 `_VERSION_UNKNOWN = "0.0.0-unknown"`（error 级日志；`parse_version` 视作 `(0,0,0)` ⇒ 更新提示照常）+ `Dockerfile` 的 `ARG APP_VERSION` 去掉写死的 `0.78.0` 默认值 |
| 6 判据合并 | 新增叶子模块 `novelforge/core/filename.py`（只 import `re`）：`UNSAFE_CHARS` / `TRAILING_JUNK` / `strip_unsafe()` 成为「跨平台文件名安全」的**唯一判据**；`komga.clean_segment` 与 `fileops.sanitize_stem` 改为共用它（各自保留**既有行为差异**：前者折叠内部空白、后者不折叠）。选叶子模块而非让 komga 反向 import fileops，是为了不改「pipeline 能直接 import komga」这条分层约束 |
| 1 视觉 | `frontend/src/views/ReadingActivityView.vue` 的热力图五档改由 `chartShades(useChartTheme().palette, 5)` 派生（不再写死那列**已作废**的 `#2563eb` 系）；`frontend/src/components/settings/SettingsSearchPanel.vue` 的 `bg-[#0f172a]/25` → `bg-scrim`、`rounded-[14px]` → `rounded-[var(--shell-radius)]`；`frontend/src/components/charts/library/LibraryIntegrityGaugeChart.vue` 的评分坡改用 `--score-*` 四个 token（原来的第五档蓝是自创的，且 `docs/DESIGN.md` §4 的色板只有四个锚点）—— 为此在**唯一图表入口** `frontend/src/lib/charts.ts` 新增导出 `cssVarHex(varName)`，避免组件里再抄一份「读 CSS 变量 + oklch 解析」 |

### 本轮新增的守卫（防这类缺陷悄悄回来）

- `tests/test_visual_tokens_contract.py`（**6 例**，新文件）：扫 `.vue` 的①任意值颜色工具类 `bg-[#…]`、②`docs/DESIGN.md` §1 明令作废的原型配色；外加三条正向钉（评分坡取 `--score-*` 且无裸十六进制、热力图走 `chartShades()`、浮层遮罩用 `bg-scrim`）。带 `design-token-ok` 单行豁免机制。**已实测「故意造回一处违规 ⇒ 用例变红」**。
- `tests/test_version_contract.py` +3 例：版本真值源就是仓库根 `VERSION`；**没有第二份版本字面量**（兜底不许是像样的版本号）；哨兵不破坏更新检查。
- `tests/test_sources_intake.py` +2 例：三条导入路的 `format_label` 与格式轴逐字一致；落盘那条分支也带它。
- `tests/test_api_smoke.py` +1 例、`tests/test_metadata_providers.py` +1 例：两个被删端点必须 **404**（AGENTS.md §1「删功能要删干净」）。
- `tests/test_epub_xml_parse.py`（**5 例**，新文件）：EPUB 元数据解析的**容错契约**（与实现无关）——
  截断的 OPF 不许丢 `<metadata>`、未定义实体不许带走坏点之前已解析好的字段、
  **未声明命名空间前缀也要读得到**、垃圾内容不抛异常。它是一次**被回退的重构**留下的护栏（见「回退记录」）。

### 复核后**撤销或改判**的审计结论（3 条）

1. `comics.append_pages` —— 改判为「未接线的既定能力」，**保留未删**（见 §3 那条的订正）。
2. `cli.py:194` 的 help 文案 —— **撤销**，它是准确的（见 §3 那条的订正）。
3. `LIBRARY_SOURCE_DIR` —— 澄清：**Python 常量**确实只被测试用，但它镜像的**环境变量回退**是真实部署模式，**不能删**（见 §2 表内订正）。

### 未做及原因

- **`novelforge/core/metasources.py` 五家 HTML 抓取 → bs4**（§4 high）：**第 99 期已部分落地**。
  按本条自己写的做法（「带真实站点核验 + 抓取样本落夹具」）做了逐家真机探活，**核出三处线上真 bug**
  并修掉：Audible 的 `response_groups` 带非法组名 `publisher` ⇒ 接口 400、**整家永远 0 结果**
  （`publisher_name`/`publisher_summary` 是**字段**，随 `product_desc` 照旧返回）；
  Lubimyczytac 多作者书**只拿到第一位作者**（卡内多作者是多个 `<a>`，旧实现三次独立 `findall`
  再按下标配对，长度仍等卡片数 ⇒ 是**截断**不是错位）；Amazon 的 JS 校验页
  （`200` + `<meta refresh …&bm-verify=…>`、约 2.3 KB、**不含任何验证码关键词**）被旧判据放行 ⇒
  **静默 0 条**。Lubimyczytac 已改逐卡 `bs4` 选择器（`_soup` 缺库时如实回落空列表），
  新增 `tests/test_metasources_scrape.py`（12 例）+ 真机夹具 `tests/fixtures/metasources/`。
  **本条并未全部收口**：Goodreads / Kobo（本机 `ConnectTimeout`）与 Libro.fm（HTTP 202 空体）
  **取不到可解析样本** ⇒ 仍按本条原话挂起（无样本不改选择器语义）。
- **`novelforge/core/fileops.py` 的 OPF 改写正则 → ElementTree**（§4 med）：仍保留。改写的是
  **出版副本的 XML**，字节级等价不可证，而「出版产物不得变化」是硬约束；已把理由写在原地。
- **`novelforge/core/library.py` 的 EPUB/OPF/NCX 解析 → ElementTree**（§4 high）：**第 100 期实测后关闭该立项**（用户口径：「只有比当前效果好的情况下才考虑更新，否则删除此待办」）。
  第 95 期做过一版、验证后回退（见 §6「回退记录」）。第 100 期不重复试写，而是先**取真实语料判决**：
  本机没有书库（`LIBRARY_SOURCE_ROOTS` 指向容器路径 `/app/libraries`）⇒ 从 **Standard Ebooks** 取
  **37 本真实第三方 EPUB**（30 本含 OPF），逐字段对比「现有正则」与「`xml.etree.ElementTree` 真解析器」：
  `title` / `creator` / `publisher` / `language` **0/30 不一致**，真解析器**零失败**，
  结构特征（含 CDATA / DOCTYPE / 非标准实体 / 单引号属性 / 疑未声明前缀）**全为 0**；
  **唯一差异是 `description` 30/30**，且 `html.unescape(旧结果) == 真解析器结果` **逐字成立**
  ⇒ 差异唯一就是「正则不解 HTML 实体」，与「解析器成熟度」无关。
  ⚠️ **判决口径**：合成语料上真解析器赢的三处（前缀别名 / CDATA / DOCTYPE 内部实体）**真实书里一个都没出现**，
  而它输的三处（未声明前缀 `unbound prefix` / 未定义实体 `undefined entity` / 纯垃圾 `syntax error` 整份作废）
  恰是第三方 OPF 会遇到的那类 ⇒ **有能力交换、无净收益**，本条按原口径**关闭**。
  那三处容错回归的**可执行形式** `tests/test_epub_xml_parse.py`（5 例）**保留**，作为「将来真要换解析器」的验收条件。
  唯一真差异已单独修掉：`novelforge/core/library.py:209` 新增 `_dc_description(opf)`（解一次实体、**保留标签**），
  `probe_epub` 在 `:1420` 改调它，守卫 `tests/test_epub_description.py`（7 例）。详见
  `docs/roadmap-gaps-remaining.md` 第 100 期段。
- **[low] 四项刻意留档**（都不影响正确性，改动面却不小）：
  `sources/manager.py:87 gate_reason(source=…)` 的 `source` 形参不参与判定（改签名要动 ~13 个调用点）；
  `sources/manager.py:207` 的 `_source` 写入冗余（但 `source_of` 读它是**外部回传 item 的输入契约**，`cli.py --item` 在用）；
  `config.py:53` 的 `LIBRARY_SOURCE_DIR` Python 别名（~20 个测试在用）；
  `server.py:/content` 端点（仓内零消费者，**仓外消费者无法从仓内证明**）。已记进 `docs/TODO.md` §1。
  ⚠️ **第 97 期已全部清掉**（用户拍板做「候选 C」，见 `docs/roadmap-gaps-remaining.md` 第 97 期段）：① `gate_reason` 的 `source` 形参**删除**（17 处调用点 / 11 处传参同批改，两个测试桩同步）；② `manager._mark` **不再写** `_source`（读侧 `source_of` 保留 —— 那是外部回传 item 的输入契约）；③ `config.LIBRARY_SOURCE_DIR` 别名**删除**（`LIBRARY_SOURCE_DIRS1..N` 的**环境变量回退照旧**；18 个测试文件改读 `LIBRARY_SOURCE_ROOTS[0]["path"]`）；④ `GET /content` 经用户确认**无外部脚本在用** ⇒ **直接删除**并补 404 用例。
- **§5 批次 8（数据安全两处口径）**：用户**未勾选** ⇒ 本轮不动。两条仍待用户决策
  （`zipkind.unpack` 的 `remove_source` 真 `unlink`；`landing` 自动落地支无二次确认）。
  ⚠️ **第 96 期已落地**（见 `docs/roadmap-gaps-remaining.md` 第 96 期段）：第一条改成 `publish.recycle`（移入回收站 + 台账，可还原）；第二条经复核**改判** —— 「无二次确认」**不是缺口**（用户 2026-10-03 的口径明确要求自动覆盖，见 `novelforge/core/landing.py:3-6`），真缺口是「覆盖不可撤销」，已补成「覆盖前先回收；回收失败即中止、盘上零改动」。

### 回退记录：EPUB 解析改 ElementTree（本期唯一一次「做完又退回」）

动机是 §7.5「优先成熟库」。改完、聚焦用例全绿之后，**验证阶段实测到三处真实回归**，
且全部落在「野生 EPUB 的容错」——恰恰是最不该出问题的空间：

| # | 回归 | 实证 |
|---|---|---|
| 1 | **截断的 OPF 丢整块元数据**：按「取最后一条 `end` 当文档元素」，`<package>…<manifest><item/></manifest>` 截断时最后一条 `end` 是内层 `item` ⇒ `<metadata>` 整棵看不见、书名作者全空（**且不报错**，`unparsable` 仍 False） | 探针脚本打印事件序列 + 修复后 `c` 的文本才读得到；文档元素应是**第一条 `start`** |
| 2 | **未定义实体（`&nbsp;`）让整份文档作废**：`read_events()` 是生成器，`ParseError` 在**迭代中途**抛，`list(...)` 一抛就把已吐出的事件一起丢掉 ⇒ 连坏点**之前**的书名也没了 | 探针脚本（`ParseError` 的 traceback 落在 `list(p.read_events())` 里） |
| 3 | **未声明命名空间前缀（`dc:` 未声明 `xmlns:dc`）丢全部元数据**：旧正则比字面标签名读得到，真解析器当硬错误 `unbound prefix` | `tests/test_isbn_shape.py` 打了个正着（**现有用例唯一抓到的一条**） |

⇒ **回退理由**：1 / 2 可以修（已在回退前的版本里修好并加测），但 3 必须另外解决 ——
要么字符串手术式地给根标签注入常用命名空间声明，要么换 `lxml` 的 `recover=True`；
而 `lxml` 在 `requirements.txt` 里**明确是可选依赖**（缺了要如实降级），
把它变成硬依赖、或在同一处留两条解析路径，**都违反推动这次重构的那两条原则**。
换来的只是一个「内部实现更现代」的**纯重构（用户可见行为零变化）**，却要动书库扫描的热路径 ——
正是 §7.3「绝不拿能用的功能去换没做完的复杂度」要挡的事。

⚠️ **没有白做**：那三处回归被写成了**与实现无关的容错契约**
（`tests/test_epub_xml_parse.py`，**5 例**，对回退后的正则实现**全绿** ——
所以才敢留着：它们既是当前实现的护栏，也是下次重试时的先撞墙）。
另有一条**主动放弃**的断言也值得记：原先我断言「坏实体**之后**的字段读不到」，
回退后实测旧正则**照读不误**（它对实体一无所知）⇒ 那是**实现定义**而非契约，
已改为只断言「坏点**之前**的不许丢」。**把某个实现的局限写成契约，是加测时最容易犯的错。**

### 实测（本轮收尾）

| 项 | 值 |
|---|---|
| 后端全量 | **2122 passed / 25 skipped / 0 failed**（285.14 s，`--junitxml` 解析；第 94 期基线 2104 passed ⇒ **+18**，与新增守卫例数逐一对上） |
| 前端单测 | **65 spec / 673 passed**（未变，视觉改动不撞既有断言） |
| 前端类型 | **0 error** |
| `VERSION` | 仍 `0.94.0`（**未发版**） |

