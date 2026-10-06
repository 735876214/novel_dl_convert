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
3. **读 `.codebuddy/memory/MEMORY.md`（铁律 + 一期一行索引）+ `MEMORY-REF.md`（按主题的域细节/运行手册）**。
   第 53–105 期的逐期铁律全文在 `MEMORY-PERIODS.md`（存档）；**当日日志已取消**（2026-10-06 起不再新建 `memory/YYYY-MM-DD.md`），跨会话历史事实按需查既有日期文件。

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
| 新增书源 / 提供商 | ① **声明**：`novelforge/core/sources/registry.py` 的 `DECLARED`（`fetch_name` / `isbn_name` / `detail_name` / `id_field` / `kind` / `rate_limit` / `cache_ttl` …）② **实现**：`novelforge/core/metasources.py` 里的同名函数（声明存的是**函数名字符串**，由 `_bind_declared()` 注入；找不到直接 `raise ValueError`）③ 该源的配置键进 `DEFAULTS["metadata_fetch"]` 与 `server.EDITABLE`（契约 `tests/test_metasource_registry_contract.py` + `tests/test_metadata_providers.py`） |
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
.venv/bin/python -m pytest                 # 当前基线 2343 例（2318 passed / 25 skipped；只增不减）
                                           # ⚠️ 跑前先清空全部 proxy 变量；⚠️ 别再加 `-q`（两条都见第 5 节）
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
- ⚠️ **pwsh 的 `> $out 2>&1` 把输出写成 UTF-16LE**（第 102 期）：用 `encoding="utf-8"` 读会得到夹 `\x00` 的乱码、**搜不到任何关键词**（据此白读一轮「exit 0 但没有汇总行」）。读这类日志要 `encoding="utf-16"`。
- ⚠️ **不要在本仓跑 `pnpm run <script>`**（第 102 期实测）：pnpm 的 deps 检查会**自动 install** —— 把 `frontend/node_modules`
  整套移进 `.ignored` 再从 registry 重装（版本与 `package.json` 的 `^` 记录不同），最后卡在
  `[ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: vue-demi@0.14.10` 上 exit 1，**脚本压根没跑**。
  正确姿势：`cd frontend` 后**直接调 `frontend/node_modules/` 里的工具**（如 `node node_modules/vue-tsc/bin/vue-tsc.js --build`），或按第 4 节用 `npm run`。
- ⚠️ **`vue-tsc` 3.3.12 起比 3.3.11 严**（第 102 期记录、第 103 期复核为**实红**、**第 104 期已修**）：
  症状是 `frontend/src/components/book/MetadataEditor.vue:614` 的模板内联
  `FIELD_LABELS[c as keyof BookMetadataFields]` 报 `TS2339`（`--build --force` 恰 1 条、`EXIT=2`），
  而 **3.3.11 全量重建 exit 0** ⇒ 触发条件是「**重装前端依赖**」，与那行代码有没有改过无关。
  第 104 期的解法是**把代码写对**（五处重复的字段中文名收敛成一个 `labelOf(k: string)`，
  索引断言只留一处），而不是收紧 `package.json` 的版本范围 —— 范围挡不住下次重装，写对才挡得住。
  ⚠️ 所以「本地类型检查突然红一条、你没动过那个文件」先怀疑**工具链版本漂移**，别急着改业务代码。
- ⚠️ **`write` 工具落的临时文件在 `C:\Users\qingr\Temp\`，而 pwsh 的 `$env:TEMP` 是 `…\AppData\Local\Temp`**（第 103 期）：
  用 `git commit -F "$env:TEMP\nf_msg_xxx.txt"` 会报 `fatal: could not read log file '…': No such file or directory`（提交未发生，`git add` 的暂存还在）
  ⇒ **一律给完整显式路径**（`git commit -F "C:\Users\qingr\Temp\nf_msg_xxx.txt"`）。
  ⚠️ **这条的后果比看上去严重**：失败后**暂存区不会清空**，那一笔的内容会被**下一笔提交悄悄带走**
  （第 103 期给 RanobeDB 缺陷修复准备的那一笔就这么并进了系列那一笔 `e1927ea`）⇒
  **每笔提交后都要核 `git log --oneline` 的笔数**，收尾用 `git show --stat <hash>` 确认内容对得上。
- ⚠️ **读仓库里的中文 / JSON 文件一律用 `read` 工具**（第 103 期）：`Get-Content package.json -Raw | ConvertFrom-Json` 在本机
  因控制台 **GBK 解码**把中文读成乱码而报 `传入的对象无效`，`Get-Content docs\*.md` 则是满屏乱码 —— 都**不是文件坏了**，是 pwsh 读错了。
- ⚠️ **本机的 DNS 被上游污染**（第 104 期实测，与代码无关）：`openlibrary.org` / `www.goodreads.com` /
  `www.googleapis.com` 在本机解析到的是**别人的网段**（Facebook 的 `31.13.x` / `128.242.x`），
  而 `8.8.8.8` 给的是正确地址（`199.59.149.201` / `199.59.148.6`）；`hosts` 里**没有**自定义行、`1.1.1.1` 的 UDP/53 无应答。
  ⇒ 这三家的**真机探活 / 详情核验现在做不了**（第 102 期起挂起的三条都撞在这上面）。
  探针连不上时先按 DNS 归因（应用内体检会报 `dns_polluted` 并把两边地址写进原因），**别去改选择器或超时**。
- ⚠️ **`.gitignore` 的模式不写前导斜杠，会把源码一起忽略掉，而本机永远看不出来**（第 105 期）：
  `input/` / `output/` / `cache/` 这类**不带前导斜杠**的模式匹配**任意层级**的同名目录 ——
  本仓库就这么把 `frontend/src/components/ui/input/`（`Input.vue` + `index.ts`，被
  `ui/sidebar/SidebarInput.vue` import）静默忽略了**从第 90 期到第 105 期**。
  症状极隐蔽：**本机文件一直在 ⇒ 本地 `npm run build` / `vue-tsc` / 单测全绿**，
  只有 CI 从 clone 构建（`Build and Push Image` 的 `npm run build`）才报
  `[UNLOADABLE_DEPENDENCY] Could not load src/components/ui/input`，并让**整个镜像构建 + 推送连续失败 30+ 次**。
  ⇒ ① 运行时目录一律写成锚定仓库根的形式（`/input/` `/output/` `/cookies/` `/cache/` `/config/cookies/`
  `/config/cache/`，与 `/data/`、`/libraries/` 同口径）；② 新增源码目录后**别只信本机构建** ——
  跑 `git ls-files --others --ignored --exclude-standard -- frontend/src novelforge` 看有没有被吞掉的文件；
  ③ 这两条已由 `tests/test_source_tracking_contract.py` 钉住（源码树不许有被忽略的文件 + `@/` 别名导入必须落在已入库路径上）。

## 6. 提交与交付

- 中文 commit、**按能力拆多笔**；**提交即推送**（`git push origin main`）；收尾不留未提交改动（临时文件放 `$TMP`，别落仓库根）。
- 🚀 **改了 `VERSION` 就必须同批在 `CHANGELOG.md` 补一段**：推送到 `main` 后 `.github/workflows/release.yml` 会读 `VERSION`，
  若 `v<版本>` tag 还不存在就**自动打 tag 并创建 Release**（notes 取 CHANGELOG 对应段）⇒ 漏了那段，发布会在 CI 里失败。
  版本号唯一真值源是仓库根 `VERSION`（`/health` 下发）；**别再写第二份版本字面量**（`novelforge.__version__` 已删）。
- **每期收尾只写两处（第 106 期起，用户 m08584 要求精简）**：
  ① `docs/roadmap-gaps-remaining.md` 本期段 —— **唯一叙事**（根因 / 证据 / 修法 / 核验，别再往第二处抄一遍）；
  ② `.codebuddy/memory/MEMORY.md` 的「逐期铁律索引」加**一行**（期号 + 一句话铁律）。
  - ▸ **机械的几处用落位器**（第 107 期起，用户 m08782「再谈自动化」立项）：
    `python tests/period_close.py new --period N --title "期标题" --numbers "总 passed skipped" --seconds S`
    一次改完 —— roadmap 追加期段标题、TODO 头部占位、TODO §2 一行索引、TODO §0 的 HEAD 链与基线句、
    `AGENTS.md` §4 基线、`MEMORY.md` 索引行、并把旧口径手记的「连续 N 轮未升版」换成 VERSION 派生句；
    缺锚点或期号已被占用 ⇒ **整体拒绝、绝不改一半**（幂等，可反复跑）。
    跑完再 `python tests/period_close.py check`（**只读**）对账 R1–R8，0 问题才算收尾完：
    `R1` 新期号三处齐全 / `R2` 索引标签可解析不重复不越界 / `R3` §0 提到最新期号且两处基线一致 /
    `R4` 不许再建当日日志 / `R5` `MEMORY-PERIODS.md` 只读 /
    `R6` §2 是「**一行一期**」的表：期号不重复、表里不许夹裸行（表头前缀被吃掉的那种）、第 ≥107 期的一行 ≤300 字符 /
    `R7` 版本字面量 = 仓库根 `VERSION`（`--fix` 可修）/ `R8` 第 106 期口径还在。
    **工具不写叙事也不做提炼**：roadmap 正文、TODO 头部那一句话、索引行的一句话仍要手写
    （先跑 `new` 再写正文 —— 期段标题已存在时 `new` 会拒绝）。
  - **不再**新建 `memory/YYYY-MM-DD.md`（当日日志 2026-10-06 起取消；既有日期文件保留为历史）。
  - **不再**按期号往 `MEMORY-REF.md` 追加 —— 它**按主题**组织，只有出现**新的领域知识**（运行手册 / 域细节 / 跨会话待办）时才补对应小节。
  - 逐期铁律全文存档 = `.codebuddy/memory/MEMORY-PERIODS.md`（**只读，不追加**）；老期号细节按 `### 第 N 期` 搜。
  - `docs/TODO.md`（§0 进度 / §1 待办 / §2 交付索引）与 `AGENTS.md` 基线数字仍要同批更新。
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
