# AGENTS.md — AI 进入本项目首先要读的东西

> 本文件是**入口索引 + 硬约束**。更细的说明按下面「文档地图」去找，别把细节抄进来。
> 项目名：**NovelForge**（仓库名 `novel_dl_convert`）。定位：**TXT/电子书 → 书库 + 在线阅读器**，
> 面向 **NAS / 容器**自托管，单用户。后端 FastAPI，前端 Vue 3 SPA。

---

## 0. 开工前三件事（顺序别调）

1. **`git log --oneline -12` + `git status --short`**
   - 本项目**可能有别的 AI 会话在并行推进**；**期号会被别人用掉** —— 别沿用旧计划里的期号。
   - 别人未提交/已提交的改动**不回退、不顺手提交**；工作区里不是你的改动（例：`.vscode/settings.json`）不要一起 commit。
2. **读 `docs/TODO.md`** 看当前任务与优先级；读本轮相关的 `docs/roadmap-gaps-remaining.md` 段落（最新期在文件**末尾**）。
3. **读 `.codebuddy/memory/MEMORY.md`（铁律）+ `MEMORY-REF.md`（域细节/运行手册）**。跨会话的历史事实在 `memory/YYYY-MM-DD.md`。

## 1. 改动纪律（硬约束，违反会被判为回归）

- **加/删功能都要彻底**：路由 + 模块 + db CRUD + 能力键 + 前端页/路由/api + 文档 + 记忆 + 「接口 404」断言，一处不落。
- **单一真值源**：同一判据**只许有一处实现**。典型：命名规则 `fileops.fill_pattern`、路径判据 `frontend/src/lib/paths.ts`、
  阅读状态阈值 `lib_settings.reading_thresholds` ↔ `lib/readingThresholds.ts`、续接 `lib/seriesNext.ts`、
  ISBN 形状 `metadata.isbn_digits`、位置换算 `core/epub_cfi.py`、图表入口 `lib/charts.ts`。
  发现第二份拷贝 = 缺陷，先收敛再改行为。
  ⚠️ **第 94 期新增六处**：书源导入路由 `sources/intake.py`、格式轴 `sources/formats/*`（与执行轴 `base.REGISTRY` **正交**）、
  「引擎能执行什么」`rules.MODES` + `rules.audit_native_rule`（**诚实闸** —— adapter 不许自评可用）、
  编码探测 `pipeline.decode_bytes`、执行期正则 `core/saferegex`、阅读选择器解析与转换 `sources/legado.*`（formats 只包装）。
- **数据只落服务端 DB，绝不写回书文件**（`core/publish.py` 是唯一仍写文件的模块；它写的也是**副本**，源文件绝对只读）。
- **源不可变**：副本禁原地写（临时文件 + `Path.replace`）；删除一律**移入回收站**（`CONFIG_DIR/cache/recycle`），**从不 `unlink`**。
  ⚠️ **删除的边界（第 81 期口径）**：只有**用户显式动作**才会移动磁盘上的文件 ——
  「删书」回收**三份**（① 收书目录里的本地原件 / ② 书库根里的成品 / ③ 出版副本）；
  「移除书库」**默认只删登记、零文件触碰**，仅显式 `purge_files=1` 才在**后台任务**里回收 ②③、**保留 ①**
  （想搬回用「设置 → 维护 → 回收站还原」）。后台流程（刮削 / 发布 / 扫描）依旧**绝不自动删源**。
- **软删除**：`DELETE` = 置 `deleted_at`，`purge` 才真删；**一切读点须带 `WHERE deleted_at=0`**。
- **视觉层照搬 BookOrbit，不允许自创**（见 `docs/DESIGN.md`）；**不做假交互**（没有后端就如实标注「未支持」）。
- **外部依赖 / 出网：默认自托管、默认不引**（字体自托管、图标内联 SVG、前端不拉第三方 CDN）—— 这是**默认取向**，
  **不是硬约束**（第 80 期口径修订，见 `docs/roadmap-gaps-remaining.md`）。允许**显式、可关、失败能降级**地引入：
  ① 新增依赖必须在 `requirements*.txt` / `frontend/package.json` 显式声明并说明理由；② 出网一律由后端发起、有开关或退路，
  失败不得阻塞主流程；③ 仅为「省事」把界面资源丢给外部 CDN 仍然不做（自托管是默认选择，不是禁令）。
- **不做假数据**：演示数据禁用 `Math.random()`；计数/进度必须来自真实接口。
- **compose 文件只保留两份**：仅 `docker-compose.yml`（生产部署）与 `docker-compose.test.yml`（测试），**严禁新增任何新格式 / 叠加件**（offline、update 等一律内联进主文件注释或文档说明，不另建文件）。
- 写计划只写四块：**需求来源 / 功能范围 / 防回归要点 / 任务清单**。
- ⚠️ 除上述硬约束外，**工程取向**见第 7 节（不为向后兼容留路 / 最简实现 / 分层生长 / 模块化 / 优先成熟库 / 先查已有依赖 / 长期决策 / 先研究成熟产品）；
  两者冲突时**以本节的硬约束为准**。

## 2. 三处同步点（最容易漏、且漏了不报错）

| 场景 | 必须同批改的位置 |
|---|---|
| 新增「可保存的配置分区」 | ① `server.EDITABLE` ② `GET /api/config` 的硬编码键列表 ③ 前端 `data/settingsFields.ts` 的 `SECTION_KEYS` |
| 新增偏好块 | ① `server.PREFS_BLOCKS` ② 前端 `lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS`（契约 `tests/test_prefs_shelf_block.py`） |
| 新增 / 删设置页 | ① `data/settingsNav.ts`（**删条目即删路由与侧栏项**）② 路由组件映射 `SETTINGS_PAGE_COMPONENTS` ③ 侧栏/搜索由注册表派生（自动） |
| 新增库表列 | 必须同进 `db._LIBRARY_COLS`，否则 `update_library` **静默写不进**（界面仍显示「已保存」） |
| 新增含 `book_id` 的表 | 必过 remap 清单：`ORPHAN_TABLES` / `REMAP_TABLES` / `REMAP_PROBE_FILTER` / `REMAP_EXPLICIT_TABLES`（契约 `tests/test_remap_tables.py`；另有 `REMAP_DERIVED_TABLES` / `REMAP_MERGE_TABLES` 由该用例的 `_tables_with_book_id()` 直接问库兜底） |
| 新增书源 / 提供商 | `core/metasources.SOURCES` 与 `_FETCHERS` **逐字一致**（契约 `IMPLEMENTED == _FETCHERS.keys()`） |
| 新增发布/接口 | 批量端点注册在 `/api/books/{bid}` **之前**；字面量路径在 `{param}` 之前 |

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
    metasources.py · metafetch.py   14 家元数据提供商 + 抓取编排（出网只经 `_get_json`/`_get_text`）
  static/v2/                前端**构建产物**（勿手写；由 frontend/ 构建 + deploy 同步）
frontend/                   前端工程（Vue 3 SFC + TS + Vite + Tailwind v4 + Pinia）
  src/assets/theme/*.css    视觉 token（照搬 BookOrbit，见 docs/DESIGN.md）
  src/views/ · components/ · stores/ · lib/ · data/ · composables/
  scripts/deploy.mjs        dist → novelforge/static/v2
tests/                      pytest 全量（离线）；conftest.py 有仓库根防删除守卫
docs/                       文档（见下「文档地图」）；bookorbit/ 上游对照、review/ 历史评审快照
```

## 4. 常用命令

```bash
# 后端测试（离线、全量；Windows 用 .venv\Scripts\python.exe）
.venv/bin/python -m pytest                 # 当前基线 2152 例（2127 passed / 25 skipped；只增不减）
                                           # ⚠️ 跑前先清空全部 proxy 变量，见第 5 节最后一条
.venv/bin/python -m pytest tests/test_catalog.py -k 某关键字

# 前端四连（缺一不可；Windows 先 $env:NODE_OPTIONS=''）
cd frontend
npm run type-check && npm run test:unit && npm run build && npm run deploy

# 跑本地实例（隔离目录，别占用别人的端口；8993 常被测试 compose 占）
INPUT_DIR=$TMP/nf/input OUTPUT_DIR=$TMP/nf/output CONFIG_DIR=$TMP/nf/config \
DATA_DIR=$TMP/nf/data CACHE_DIR=$TMP/nf/cache LIBRARY_SOURCE_DIR=$TMP/nf/libraries \
AUTO_WATCH=false .venv/bin/python -m uvicorn novelforge.server:app --port 8412
# 健康检查 GET /health（唯一给版本号的端点）；登录字段是 {"user","pin"}，默认 admin/changeme
```

- ⚠️ **`build` 只落 `frontend/dist`，`deploy` 才同步到 `novelforge/static/v2`**；漏 deploy ⇒ 服务端仍发旧 bundle（改动看似「没生效」）。
- ⚠️ `vitest` **不校验模块导出完整性** —— 只有 `build` 才报断链（历史上曾把两个文件误提交成 0 B）。
- ⚠️ Windows 的 IDE safe-delete shim 会拦 Vite 清目录与 `Remove-Item`；跑 `build`/`deploy`/`pytest` 前 `$env:NODE_OPTIONS=''`。
- ⚠️ 改了后端**必须重启进程**才生效（用户曾把「改了后端没重启」误当成产品 bug）。

## 5. 已知陷阱速查

- `core/` 里一律 `from .. import config`（裸 `import config` 会被同名命名空间包劫持，**启动时才炸**）。
- `db` 只走 `db._connect()`（持 `RLock` 的代理连接）；**别抓裸连接、别绕开锁**（否则 `InterfaceError`/段错误）。
- win32 目录 `st_size` 恒 0 ⇒「空文件」判据要 `not is_dir() and st_size == 0`。
- **能力键判隐显轴**：`library.hasFeature(k)` 判的是「侧栏当前选中的库」，读者侧要判「**这本书**属于哪个库」。
- 设置页 `note` 是**纯文本插值** ⇒ `**`/反引号/`<strong>` 会原样显示；且只有占位页会渲染 note。
- 前端设置页路由是 `#/settings/<page.path>`（**不带分组段**）。
- 计时类测量用 `curl`，**别用 PowerShell `Invoke-RestMethod`**（解析大 JSON 会严重虚高耗时）。
- `pytest.ini` 已含 `addopts=-q`，**别再加 `-q`**；计数用 `--junitxml` 解析（Windows 下会话末清理报错不影响结果，看 junit 才算数）。
- ⚠️ **重建 / 包装 HTTP 响应时必须摘掉 `Content-Encoding` / `Content-Length`**（第 94 期，`network._drop_entity_headers`）——
  留着前者会让 httpx 把**已解压**的字节再解一次（开 gzip 的真实站点**全挂**），而**桩站返回的正文从不压缩 ⇒ 单测 100% 绿**。
  凡这类改动，收尾必须拿**真实地址**核一次。
- ⚠️ `quickjs` 只有 **cp38–cp312** 预编译包 ⇒ `requirements.txt` 的 `python_version < "3.13"` 标记不能少（否则 3.13+ 装整条失败）。
- ⚠️ **不认识的 python 进程一律不 kill**（本机常有并行会话的实例）；`pytest` 里调 `ledger.plan` 的用例必须带 `isolated` fixture。
- ⚠️ **跑 pytest 前清空全部 proxy 变量**（`HTTP_PROXY` / `HTTPS_PROXY` / `http_proxy` / `https_proxy` / `NO_PROXY` / `no_proxy`）——
  `httpx` 0.28.1 解析 `NO_PROXY` 里的方括号 IPv6（`[::1]`）会生成畸变 mount `all://*[::1]`，于是**任何真实 `BrowserClient` 用例**炸
  `httpx.InvalidURL: Invalid port: ':1]'`（本机曾据此误判出 45 个「回归」）。**只去掉方括号不够，必须整组清空**。

## 6. 提交与交付

- 中文 commit、**按能力拆多笔**；**提交即推送**（`git push origin main`）；收尾不留未提交改动（临时文件放 `$TMP`，别落仓库根）。
- 🚀 **改了 `VERSION` 就必须同批在 `CHANGELOG.md` 补一段**：推送到 `main` 后 `.github/workflows/release.yml` 会读 `VERSION`，
  若 `v<版本>` tag 还不存在就**自动打 tag 并创建 Release**（notes 取 CHANGELOG 对应段）⇒ 漏了那段，发布会在 CI 里失败。
  版本号唯一真值源是仓库根 `VERSION`（`/health` 下发）；**别再写第二份版本字面量**（`novelforge.__version__` 已删）。
- 每期收尾要更新：`docs/roadmap-gaps-remaining.md`（本期实施记录）+ `.codebuddy/memory/`（当日日志；长期事实进 `MEMORY.md`/`MEMORY-REF.md`）。
- 行尾：`*.sh` / `Dockerfile` / `.dockerignore` 必须 **LF**（否则容器 `sh /app/start.sh` 报 `set: Illegal option -`）。

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
   视觉层逐字照搬 BookOrbit、书源对齐 legado / Mihon、命名/续接对齐既有上游。

---

## 文档地图

| 文件 | 管什么 |
|---|---|
| `AGENTS.md`（本文件） | AI 入口：硬约束、三处同步点、常用命令、陷阱 |
| `docs/TODO.md` | 当前任务、优先级、进度与下一期候选 |
| `docs/DESIGN.md` | 视觉规则（token / 圆角 / 阴影 / 字体 / 暗色 / 动效） |
| `docs/project-overview.md` | 项目整体说明（能力全景） |
| `docs/architecture.md` | 架构与数据流（分层 / DB / 索引 / 缓存 / 出版 / 多端） |
| `docs/user-guide.md` | 面向使用者的功能说明（怎么用） |
| `docs/development.md` | 开发方式、命令、回归清单 |
| `docs/component-api.md` | 前端组件与状态/工具模块 API |
| `docs/format-capability-matrix.md` | 书源格式轴 × 执行轴的能力矩阵（第 94 期） |
| `docs/roadmap-verification.md` | 路线图完成度核查快照（第 94 期，**不采信文档状态标记**、只认实证） |
| `docs/bookorbit/bookorbit-*.md` | 既有上游对照基线（capability-gap / module-inventory / settings-inventory / feature-flows / library-contract / dashboard-styles） |
| `docs/review/` | 历史评审快照（backend / frontend code_review_report、上游截图记录） |
| `docs/roadmap-gaps-remaining.md` | 逐期实施记录（**活文档**，最新期在末尾） |
| `README.md` | 面向部署者/使用者的完整说明（NAS 部署、配置表、CLI） |
