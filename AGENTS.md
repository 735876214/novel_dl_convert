# AGENTS.md — AI 进入本项目首先要读的东西

> 本文件是**入口索引 + 硬约束**。更细的说明按下面「文档地图」去找，别把细节抄进来。
> 项目名：**NovelForge**（仓库名 `novel_dl_convert`）。定位：**TXT/电子书 → 书库 + 在线阅读器**，
> 面向 **NAS / 容器**自托管，单用户。后端 FastAPI，前端 Vue 3 SPA。

**30 秒红线**（细则全在 §1，冲突时以 §1 为准）

- 不回退、不顺手提交别人的改动；本机 IDE 配置不入库（`.vscode/settings.json` 已从仓库移除并在 `.gitignore` 里钉住）。
- 加 / 删功能都要**彻底**：路由 + 模块 + db CRUD + 能力键 + 前端 + 文档 + 记忆 + 「接口 404」断言，一处不落。
- **单一真值源**：同一判据只许一处实现 —— 发现第二份 = 缺陷。
- 书文件**只读**；删除一律**移入回收站**（从不 `unlink`）；软删除的一切读点带 `WHERE deleted_at=0`。
- 不手写 `static/v2`；不新增 compose 文件；不写假数据；不为省事把界面资源丢给外部 CDN。
- 跑测试用 `scripts/test.sh`；收尾 `python tests/period_close.py check` **0 问题**才算完。

## 0. 开工前三件事（顺序别调）

1. **`git log --oneline -12` + `git status --short`**
   - 本项目**可能有别的 AI 会话在并行推进**；**期号会被别人用掉** —— 别沿用旧计划里的期号。
   - 别人未提交/已提交的改动**不回退、不顺手提交**；工作区里不是你的改动不要一起 commit。
2. **读 `docs/TODO.md`** 看当前任务与优先级；读本轮相关的 `docs/roadmap-gaps-remaining.md` 段落（最新期在**末尾**，按 `## 第 N 期` 搜）。
3. **读 `.codebuddy/memory/MEMORY.md`（铁律 + 一期一行索引）+ `MEMORY-REF.md`（按主题的域细节 / 运行手册）**；
   本机（Windows）专属陷阱见 `docs/development-windows.md` —— **换机器 / 容器请忽略它**。

## 1. 改动纪律（硬约束，违反会被判为回归）

- **加 / 删功能都要彻底**（同批改完、一处不落）：
  - **新增**：路由 → 模块 → db CRUD → 能力键 → 前端页/路由/api → 文档 → 记忆 → 「接口 404」断言。
  - **删除**：删路由 → 删模块 → 删 db CRUD → 删能力键 → 删前端页/路由/api → 删文档 → 改记忆索引 →
    删/改 404 断言 → `rg` 全文确认无残留引用（**不留兼容垫片 / 回退分支**，见 §7.1）。
- **单一真值源**：同一判据**只许有一处实现**。典型：命名规则 `fileops.fill_pattern`、路径判据 `frontend/src/lib/paths.ts`、
  阅读状态阈值 `lib_settings.reading_thresholds` ↔ `lib/readingThresholds.ts`、续接 `lib/seriesNext.ts`、
  ISBN 形状 `metadata.isbn_digits`、位置换算 `core/epub_cfi.py`、图表入口 `lib/charts.ts`；
  第 94 期又立六处：书源导入路由 `sources/intake.py`、格式轴 `sources/formats/*`（与执行轴 `base.REGISTRY` **正交**）、
  「引擎能执行什么」`rules.MODES` + `rules.audit_native_rule`（**诚实闸** —— adapter 不许自评可用）、
  编码探测 `pipeline.decode_bytes`、执行期正则 `core/saferegex`、阅读选择器解析与转换 `sources/legado.*`（formats 只包装）。
  发现第二份拷贝 = 缺陷，先收敛再改行为。
- **数据只落服务端 DB，绝不写回书文件**（`core/publish.py` 是唯一仍写文件的模块；它写的也是**副本**，源文件绝对只读）。
- **源不可变**：副本禁原地写（临时文件 + `Path.replace`）；删除一律**移入回收站**（`CONFIG_DIR/cache/recycle`），**从不 `unlink`**。
  ⚠️ **删除的边界（第 81 期口径）**：只有**用户显式动作**才会移动磁盘上的文件 ——
  「删书」回收**三份**（① 收书目录里的本地原件 / ② 书库根里的成品 / ③ 出版副本）；
  「移除书库」**默认只删登记、零文件触碰**，仅显式 `purge_files=1` 才在**后台任务**里回收 ②③、**保留 ①**
  （想搬回用「设置 → 维护 → 回收站还原」）。后台流程（刮削 / 发布 / 扫描）依旧**绝不自动删源**。
- **软删除**：`DELETE` = 置 `deleted_at`，`purge` 才真删；**一切读点须带 `WHERE deleted_at=0`**。
- **视觉层照搬 BookOrbit，不允许自创**（见 `docs/DESIGN.md`）；**不做假交互**（没有后端就如实标注「未支持」）。
- **外部依赖 / 出网：默认自托管、默认不引** —— 这是**默认取向**，**不是硬约束**（第 80 期口径修订）。
  允许**显式、可关、失败能降级**地引入：① 新增依赖必须在 `requirements*.txt` / `frontend/package.json` 显式声明并说明理由；
  ② 出网一律由后端发起、有开关或退路，失败不得阻塞主流程；③ 仅为「省事」把界面资源丢给外部 CDN 仍然不做。
- **不做假数据**：演示数据禁用 `Math.random()`；计数 / 进度必须来自真实接口。
- **compose 文件只保留两份**：仅 `docker-compose.yml`（生产部署）与 `docker-compose.test.yml`（测试），
  **严禁新增任何新格式 / 叠加件**（offline、update 等一律内联进主文件注释或文档说明，不另建文件）。
- 写计划只写四块：**需求来源 / 功能范围 / 防回归要点 / 任务清单**。
- ⚠️ 除上述硬约束外，**工程取向**见第 7 节；两者冲突时**以本节的硬约束为准**。

## 2. 同步点（最容易漏、且漏了不报错）

> 加 / 删这类东西时，**同批**改完下表各处 —— 表里的契约测试就是「漏了会红」的判据。

| 场景 | 必须同批改的位置 | 契约测试 |
|---|---|---|
| 配置分区（可保存） | ① `server.EDITABLE` ② `GET /api/config` 的硬编码键列表 ③ 前端 `data/settingsFields.ts` 的 `SECTION_KEYS`；**删分区走反向**（三处同批删） | `tests/test_update_config_contract.py` |
| 配置项 / 环境变量 | `config.DEFAULTS` → `server.EDITABLE`（若可编辑）→ `GET /api/config` 的键列表 → 前端 `settingsFields.ts`；用户可见的另加 `README.md` 配置表 / `docs/user-guide.md` | `tests/test_update_config_contract.py` |
| 偏好块 | ① `server.PREFS_BLOCKS` ② 前端 `lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS` | `tests/test_prefs_shelf_block.py` |
| 设置页（增 / 删） | ① `data/settingsNav.ts`（**删条目即删路由与侧栏项**）② 路由组件映射 `SETTINGS_PAGE_COMPONENTS`；侧栏 / 搜索由注册表派生（自动） | `tests/test_settings_nav_contract.py` |
| 库表列 | 必须同进 `db._LIBRARY_COLS`，否则 `update_library` **静默写不进**（界面仍显示「已保存」） | `tests/test_api_smoke.py`（只覆盖部分列，别只信它） |
| 含 `book_id` 的表 | remap 清单：`ORPHAN_TABLES` / `REMAP_TABLES` / `REMAP_PROBE_FILTER` / `REMAP_EXPLICIT_TABLES`（另有 `REMAP_DERIVED_TABLES` / `REMAP_MERGE_TABLES` 由用例问库兜底） | `tests/test_remap_tables.py` |
| 书源 / 提供商 | ① **声明** `core/sources/registry.py` 的 `DECLARED`（存的是**函数名字符串**，由 `_bind_declared()` 注入）② **实现** `core/metasources.py` 里的同名函数 ③ 配置键进 `DEFAULTS["metadata_fetch"]` 与 `server.EDITABLE` | `tests/test_metasource_registry_contract.py` + `tests/test_metadata_providers.py` |
| 发布 / 接口 | 批量端点注册在 `/api/books/{bid}` **之前**；字面量路径在 `{param}` 之前；**删除的接口必须有 404 断言** | —（靠 §1 的 404 断言） |

## 3. 目录地图（只列常去的）

```
novelforge/                 Python 包（后端全部逻辑）
  server.py                 FastAPI 应用：全部路由 + 中间件（含 gzip）；APP_VERSION 唯一真值源
  cli.py                    命令行入口（convert / search / download / update / watch / scan / logs）
  config.py                 目录与配置解析（四层：DEFAULTS → config.yaml → settings.json → 环境变量）
  core/                     领域模块（见 docs/architecture.md 的分层表）
    library.py              书库扫描 / 书目聚合（对外字段的**唯一产出点**）
    catalog.py              书目**索引落库**（请求路径不再扫盘；这是「书架秒开」的关键）
    db.py                   持久层（SQLite / PostgreSQL 双后端，经 sqlcompat.py）
    cache.py                Redis 读缓存（可选、可缺席、挂掉自动降级）
    publish.py · scrape.py  刮削出版（硬链接副本 / 原子写 / 状态机）
    metasources.py · metafetch.py   13 家元数据提供商 + 抓取编排（出网只经 `_get_json`/`_get_text`）
  static/v2/                前端**构建产物**（勿手写；由 frontend/ 构建 + deploy 同步）
frontend/                   前端工程（Vue 3 SFC + TS + Vite + Tailwind v4 + Pinia）
  src/assets/theme/*.css    视觉 token（照搬 BookOrbit，见 docs/DESIGN.md）
  src/views/ · components/ · stores/ · lib/ · data/ · composables/
  scripts/deploy.mjs        dist → novelforge/static/v2
scripts/                    一键验证脚本（入库；见 §4）
  test.sh · frontend-verify.sh · dev-instance.sh · _lib.sh（三者共用的探测 / 清变量）
tests/                      pytest 全量（离线）；conftest.py 有仓库根防删除守卫
docs/                       文档（见下「文档地图」）；bookorbit/ 上游对照、review/ 历史评审快照
```

## 4. 常用命令

```bash
# 后端全量测试（离线）—— 脚本已清 proxy、已带 junitxml，有 failed/errors 即退 1
bash scripts/test.sh                       # 当前基线 2559 例（2546 passed / 13 skipped；只增不减）
bash scripts/test.sh tests/test_catalog.py -k 某关键字

# 前端四连（type-check → unit → build → deploy，缺一不可）
bash scripts/frontend-verify.sh

# 起本地实例（隔离目录 + 新端口，别占用别人的）
bash scripts/dev-instance.sh 8412
# 健康检查 GET /health（唯一给版本号的端点）；登录字段是 {"user","pin"}，默认 admin/changeme
# ↑ 仅本地默认；部署必须改 AUTH_USER / AUTH_PIN
```

- 📌 **§4 的基线行由 `tests/period_close.py` 维护**（`new --numbers/--junit`），**勿手改**；它与 `docs/TODO.md` §0 必须一致（R3 对账）。
- ⚠️ **`build` 只落 `frontend/dist`，`deploy` 才同步到 `novelforge/static/v2`** —— 漏 deploy ⇒ 服务端仍发旧 bundle（改动看似「没生效」）；
  而 `type-check` / `unit` 都**不校验模块导出完整性**，只有 `build` 会报断链（历史上曾把两个文件误提交成 0 B）。
- ⚠️ 改了后端**必须重启进程**才生效；Windows 上直跑命令（不经脚本）时的环境差异见 `docs/development-windows.md`。

## 5. 已知陷阱速查

> 只列**跨环境通用**的判据：一行一条（症状 → 处理），展开见「去哪看」列。
> ⚠️ **本机（Windows）专属陷阱不在本表** —— 见 `docs/development-windows.md`（换机器 / 容器忽略它）。

| 症状 / 关键词 | 判据与处理 | 去哪看 |
|---|---|---|
| `core/` 里 `import config`：**启动时才炸** | 一律 `from .. import config`（裸 import 会被同名命名空间包劫持） | `docs/development.md` §3 |
| `db` 报 `InterfaceError` / 段错误 | 只走 `db._connect()`（持 `RLock` 的代理连接）；别抓裸连接、别绕开锁 | `docs/development.md` §3 |
| win32 目录 `st_size` 恒 0 | 「空文件」判据要 `not is_dir() and st_size == 0`；目录体积用 `watcher._sig()` | `MEMORY-REF.md`（搜索 `st_size`） |
| 能力键判隐显轴 | `library.hasFeature(k)` 判的是**侧栏当前选中的库**；读者侧要判「**这本书**属于哪个库」 | —（本行即判据） |
| 设置页 `note` 里的 `**` 原样显示 | `note` 是**纯文本插值**（`**` / 反引号 / `<strong>` 不渲染），且只有占位页渲染 note；前端设置页路由是 `#/settings/<page.path>`（**不带分组段**） | —（本行即判据） |
| 真站点全挂，但单测 100% 绿 | 重建 / 包装 HTTP 响应时**必须摘掉 `Content-Encoding` / `Content-Length`**（`network._drop_entity_headers`）—— 留着会让 httpx 把已解压的字节再解一次，而桩站正文从不压缩 ⇒ 单测抓不到。凡这类改动，收尾必须拿**真实地址**核一次 | roadmap 第 94 期段 |
| 3.13+ 装 `quickjs` 整条失败 | `requirements.txt` 的 `python_version < "3.13"` 标记不能少（它只有 cp38–cp312 预编译包） | `requirements.txt` 注释 |
| 源码目录被**静默忽略**（本机永远看不出来） | `.gitignore` 模式**不写前导斜杠**会匹配任意层级同名目录（`input/` 曾吞掉 `frontend/src/components/ui/input/` 达 15 期，只有 CI 从 clone 构建才报）⇒ 运行时目录一律锚定仓库根（`/input/` `/output/` `/cache/` …）；新增源码目录后跑 `git ls-files --others --ignored --exclude-standard -- frontend/src novelforge` 复验 | `.gitignore` 注释 + `tests/test_source_tracking_contract.py`（已钉） |
| 计数 / 汇总行读不到 | 计数一律用 `--junitxml` 解析（`scripts/test.sh` 已内置）；`pytest.ini` 已含 `addopts=-q`，**别再加 `-q`** | `docs/development.md` §4 |

## 6. 提交与交付

- 中文 commit、**按能力拆多笔**（惯例 `feat(115): …` / `fix(core): …` / `docs(116): …`）、**提交即推送**（`git push origin main`）；
  收尾不留未提交改动（临时文件放 `$TMP`，别落仓库根）。
- 🚀 **改了 `VERSION` 就必须同批在 `CHANGELOG.md` 补一段**：推送到 `main` 后 `.github/workflows/release.yml` 会读 `VERSION`，
  若 `v<版本>` tag 还不存在就**自动打 tag 并创建 Release**（notes 取 CHANGELOG 对应段）⇒ 漏了那段，发布会在 CI 里失败。
  版本号唯一真值源是仓库根 `VERSION`（`/health` 下发）；**别再写第二份版本字面量**。
- **每期收尾只写两处（第 106 期起）**：
  ① `docs/roadmap-gaps-remaining.md` 本期段 —— **唯一叙事**（根因 / 证据 / 修法 / 核验）；
  ② `.codebuddy/memory/MEMORY.md` 的「逐期铁律索引」加**一行**（期号 + 一句话铁律）。
  - **机械的几处用落位器**（`tests/period_close.py`，用法与 R1–R8 判据见 `docs/development.md` §9）：
    `python tests/period_close.py new --period N --title "期标题" --numbers "总 passed skipped" --seconds S`，
    再 `python tests/period_close.py check`（**只读**）对账，**0 问题**才算收尾完；缺锚点或期号已被占用就整体拒绝（绝不改一半）。
    工具**不写叙事也不做提炼** —— roadmap 正文与索引行那句话仍要手写。
  - **不再**新建 `memory/YYYY-MM-DD.md`（当日日志 2026-10-06 起取消）；**不再**按期号往 `MEMORY-REF.md` 追加（它**按主题**组织）。
  - 逐期铁律全文存档 = `.codebuddy/memory/MEMORY-PERIODS.md`（**第 1–105 期，只读，不追加**）。
    查老期号：`MEMORY-PERIODS.md` 按 `### 第 N 期` 搜；roadmap 按 `## 第 N 期` 搜（最新在末尾）；第 74 期及更早的期号↔主题对照见 `docs/TODO.md` §2。
- **收尾顺序**：
  1. `bash scripts/test.sh`（全量）+ `bash scripts/frontend-verify.sh`（四连）；
  2. `python tests/period_close.py new --period N --title "…" …` 落位；
  3. `python tests/period_close.py check` —— **0 问题**；
  4. 改过 `VERSION` ⇒ 补 `CHANGELOG.md` 段；
  5. `git status --short` 排除无关文件（`.vscode/settings.json` 已在 `.gitignore` 里，正常不该出现）；
  6. 按能力拆中文 commit → `git push origin main`；
  7. `git log --oneline` 核笔数、`git show --stat <hash>` 核内容（提交失败会**静默**留下暂存区，见 `docs/development-windows.md`）。
- **失败处理**：测试失败**不强推**；`period_close` 整体拒绝时**不要手改一半**；CI 红先查 `VERSION` / `CHANGELOG` 缺段；
  真机探活失败先按 DNS / 代理归因，**别去改选择器或超时**。
- 行尾：`*.sh` / `Dockerfile` / `.dockerignore` 必须 **LF**（`.gitattributes` 已钉；否则容器 `sh /app/start.sh` 报 `set: Illegal option -`）。

## 7. 工程原则（长期取向，第 95 期立）

> 与第 1 节的硬约束**冲突时以硬约束为准**。为防止本节被误读成「可以删安全网」，两条边界先写死：
> ① **数据安全语义不是兼容层** —— 软删除（`deleted_at`）/ 回收站（`fileops.recycle_dir()`）/ 源不可变 /
> 「移除书库只删登记」照旧，**永不以「不做向后兼容」为由删掉**；
> ② **DB schema 迁移不是兼容层** —— `core/db.py` 的建表 / 加列 / `*_RULE_VERSION` 存量自愈照旧
> （那是**存量数据**的正确性，不是代码里的旧路径）。
> 本节针对的是**代码里的旧路径**：废弃分支、兼容垫片、双实现、为猜想的未来预留的抽象。

1. **不为向后兼容留路（Do not preserve backward compatibility）**：旧实现**删掉**，不加兼容层 / 回退分支 / 迁移垫片。
   改行为就同批改调用点与用例；**发现第二份实现 = 缺陷**（与第 1 节「单一真值源」同向）。
2. **只做满足当前需求的最简实现**：**禁投机性抽象**、禁「以后可能要」的配置项与间接层。多一层间接 =
   多一处可能不同步的真值源。
3. **分层生长**：从**能端到端跑通的最小版本**起步，新能力加在**已经能用的产品**上；
   **绝不拿能用的功能去换没做完的复杂度**（宁可少一个能力，不留半截架构）。
4. **模块化、关注点分离**：新逻辑先看 `docs/architecture.md` 的分层表该落在哪一层，别塞进 `server.py` 顺手的位置。
5. **优先用成熟库**：能降低总复杂度或提高可靠性的就用；**没有明确理由不自己重写**常见功能。
6. **先查已有依赖再自己写**：动手前**先看文档与类型**，别假设某个库没有这个能力。本项目已装：
   `httpx` / `beautifulsoup4` / `lxml` / `quickjs` / `regex` / `Pillow` / `ebooklib` / `pypdfium2` /
   `rarfile` / `numpy` / `croniter` / `psycopg` / `redis`（清单与理由见 `requirements.txt` 逐条注释）。
7. **为长期做架构决策**：**不接受「先这样、以后再换」的临时方案** —— 临时方案 = 未来的第二份实现。
8. **先研究成熟产品怎么解**：照搬已被验证的模式与约定，**不从零发明**。本项目一直在这么做：
   视觉层逐字照搬 BookOrbit、书源对齐 legado / Mihon、命名 / 续接对齐既有上游。

---

## 文档地图

| 文件 | 管什么 |
|---|---|
| `AGENTS.md`（本文件） | AI 入口：硬约束、同步点、常用命令、陷阱 |
| `docs/TODO.md` | 当前任务、优先级、进度与下一期候选 |
| `docs/DESIGN.md` | 视觉规则（token / 圆角 / 阴影 / 字体 / 暗色 / 动效） |
| `docs/project-overview.md` | 项目整体说明（能力全景） |
| `docs/architecture.md` | 架构与数据流（分层 / DB / 索引 / 缓存 / 出版 / 多端） |
| `docs/user-guide.md` | 面向使用者的功能说明（怎么用） |
| `docs/development.md` | 开发方式、命令、回归清单、调试技巧、收尾工具 |
| `docs/development-windows.md` | **仅当前 Windows 开发机**的专属陷阱（Linux / 容器忽略） |
| `docs/component-api.md` | 前端组件与状态/工具模块 API |
| `docs/format-capability-matrix.md` | 书源格式轴 × 执行轴的能力矩阵（第 94 期） |
| `docs/roadmap-verification.md` | 路线图完成度核查快照（第 94 期，**不采信文档状态标记**、只认实证） |
| `docs/agents-audit-95.md` | 第 95 期 AGENTS 合规审计快照（历史文件，行号会漂移） |
| `docs/bookorbit/bookorbit-*.md` | 既有上游对照基线（capability-gap / module-inventory / settings-inventory / feature-flows / library-contract / dashboard-styles） |
| `docs/review/` | 历史评审快照（backend / frontend code_review_report、上游截图记录） |
| `docs/roadmap-gaps-remaining.md` | 逐期实施记录（**活文档**，最新期在末尾，按 `## 第 N 期` 搜） |
| `README.md` | 面向部署者/使用者的完整说明（NAS 部署、配置表、CLI） |
| `scripts/` | 一键验证脚本（`test.sh` / `frontend-verify.sh` / `dev-instance.sh`，见 §4） |

### 记忆与收尾（每轮都要碰的入口）

| 文件 | 管什么 |
|---|---|
| `.codebuddy/memory/MEMORY.md` | 硬约定 + 逐期铁律索引（**一期一行**，最新在末尾） |
| `.codebuddy/memory/MEMORY-REF.md` | 按主题的运行手册 / 域细节 / 跨会话待办（**不按期号追加**） |
| `.codebuddy/memory/MEMORY-PERIODS.md` | 第 1–105 期逐期铁律全文存档（**只读**，不追加） |
| `VERSION` | 版本号**唯一真值源**（`/health` 下发）；改它必须同批补 `CHANGELOG.md` |
| `CHANGELOG.md` | 版本段 —— release notes 的唯一来源 |
| `tests/period_close.py` | 收尾落位器 + 三处对账（`new` / `check`，R1–R8） |
| `tests/check_doc_anchors.py` | 文档锚点（`file:line`）漂移核验 |
