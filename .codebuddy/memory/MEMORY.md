# 长期记忆（novel_dl_convert / NovelForge）

> 真值源 = `.codebuddy/memory/`；逐期细节看同名日记 `YYYY-MM-DD.md`（git 历史亦存）。

## 项目 / 硬约定
- TXT→EPUB 工具，NAS/容器部署；`input`/`output` 物理分离；FastAPI + CLI；可插拔书源。镜像 `ghcr.io/735876214/novel_dl_convert:latest`。
- 删功能要删干净（路由+模块+db CRUD+能力键+前端页面/路由/api+文档+记忆+404 防回归断言）。
- 写计划只写四块：需求来源/功能范围/防回归要点/任务清单（用户 2026-09-18 明确要求，不要架构/目录/代码结构）。
- 提交即推送：中文 commit，按能力拆多 commit。
- 视觉严格照搬 BookOrbit；零外部请求；局部更新不重建 DOM。
- ⚠️ 可能同时有另一 AI 会话：改文件前先 `git status`；别人改动不回退；临时文件放 `/tmp`；写记忆追加。

## Git / 环境 / 构建
- `.gitignore`：`.codebuddy/*` + `!.codebuddy/memory/`（否定规则配 `/*`）；忽略 `data/`、`*.db`、`novelforge/static/v2/`。
- 认证走 GCM；URL 内嵌 token / `insteadof` 明文重写已清除，勿再引入。推送失败先查认证/网络，别改 git config。
- Python 需 3.10+（`.venv`，用 `.venv/bin/python` 或 `/Users/stromboid/.local/bin/python3.12`）；Node v20/22 皆可。Docker daemon 可用，本机对外网络有限。
- 行尾必须 LF（`.gitattributes` 锁）；CRLF 让容器 `sh /app/start.sh` 报 `set: Illegal option -` 反复重启。

## 自动化测试（硬前提）
- `.venv/bin/python -m pytest`（完全离线）；dev 依赖在 `requirements-dev.txt`。约 242 passed。
- ⚠️ 全量跑完在解释器退出时会打一段 lxml faulthandler dump（既有环境现象，排除新用例同样出现），**以「N passed」为准**；仍会打印 exitCode 0。
- 两条硬前提：① 环境变量必须在 import 业务模块前设置（`config` 导入即固化目录、`server.py` 导入即 `ensure_dirs()`）；② `db` 的 `_conn`/`_db_path` 模块级缓存→隔离靠 `db.close()`。
- 碰书库/DB 用例必须 `isolated`；接口用 `client`+`auth_headers`。假 EPUB（`b"EPUB"`）够扫描类；元数据写回/系列解析必须真 EPUB（`epub_builder.build_epub`）。不测会外呼的接口；`GET /` 会 503。
- 库 id 由名称派生（中文 slug 空→`lib-<sha1[:8]>`）；测试库根必须在 `LIBRARY_SOURCE_DIR` 下。

## 后端硬约束
- core 内引用配置一律 `from .. import config`；`import config` 被同名命名空间包劫持（py_compile 抓不到，启动才炸）。
- 写磁盘只用 rename/move，**从不 unlink**；删除即移入回收目录（`CACHE_DIR/recycle`）。**禁 `config.OUTPUT_DIR / b["name"]`** → 一律 `library.root_of(b) / b["name"]`。
- 库根只允许落在 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR` 内（`safe_path` 边界）。`book_id` 由 basename 派生、库维度化（`库$哈希`）。
- 新增库表列**必须**同进 `db._LIBRARY_COLS`，否则 `update_library` 静默写不进。

## 配置分层（第 13 期，已实现）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时叠加 `生效值 = 每库覆写 ?? 全局值`，落点 `libraries.settings`（稀疏 JSON，键=点分路径）。
- `core/lib_settings.py`：`effective()`/`config_for()`/`apply_to()`/`set_overrides`/`clear_overrides`/`schema()`；与 `features.allows_setting` 联动，`features.SETTING_CAPS` 唯一真值源。接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（`?keys=` 按项恢复）。
- 覆盖项：`output.format/layout`、`watcher.recursive/copy_non_txt`、`metadata_fetch.*`、`naming.pattern/scope`、`scrape.enabled`。（库实体属性 `watch`/`scan_interval`/`scan_cron`/`publish_path` 是列，非覆盖项。）

## 前端栈 / 规范（要点）
- `frontend/` = Vue 3 SFC + TS + Vite 8 + Tailwind v4 + Pinia 4 + vue-router 5（hash 模式）；产物落 `novelforge/static/v2/`，FastAPI 挂 `/static`，`/` 服务其 `index.html`（缺失 503）。勿往 `novelforge/static/` 加手写页。
- `bridge.css` 是前提（`@theme inline`）；`main.css` 必须 `@custom-variant dark (&:is(.dark *));`。
- 仪表盘演示数据必须确定性常量，禁 `Math.random()`。`settingsNav`/router「标 ready 未注册组件」会 `console.error` → 注册表与组件同批改。
- Vue 模板不渲染 markdown → 静态文本用 `<strong>`，JS 字符串别加星号。
- 工具页 `ToolsLayout.vue` = `/tools` 外壳（标签栏+嵌套 RouterView+KeepAlive :max=8，**无卡片外框**）；**路由子页**用 `onActivated`（别挂 `onMounted`），不在 onActivated 重置用户输入。改磁盘工具一律先预览再应用。
- ⚠️ 例外：**页面内部的 `v-if` 子组件**（比 KeepAlive 深两层，如 `ScrapePanel`）首次挂载时 `onActivated` **不触发** → 必须用 `onMounted` 首载，`onActivated` 只做「重新激活时刷新」（用 `data` 非空之类的条件天然去重）。
- 表格类面板要窄屏可用：宽屏 `<table class="hidden md:block">`，窄屏另写一份 `<ul class="md:hidden">` 卡片流（信息不裁剪、只换排布）。

## 运行 / UI 验证
- 本地测试实例（已授权直接 py_compile + 重启）：`*_DIR`→`/tmp/nf-test/…`，**`LIBRARY_SOURCE_DIR=/tmp/nf-test/libraries` 也要显式设**（否则走默认 `/app/libraries` 不存在），`AUTO_WATCH=false`，auth `admin`/test1234，`.venv/bin/python -m uvicorn novelforge.server:app --port 8791`。token 落 `/tmp/nf-test/token.txt`（`POST /api/auth/login`）。
- Docker：`docker-compose.yml` 真实版拉镜像端口 **8992**；`docker-compose.test.yml` 本地 build 挂 `./novelforge` 端口 **8993**（容器，别动）。**断网无法 `--build`**。8992/8993 数据隔离。
- UI 验证（playwright）：项目 `.venv`，`executable_path` 传内核；直连实例 `nf_token` 用 `add_init_script` 注入；迁移弹窗先 `force=True` 点「暂不迁移」。构建：`cd frontend && npm run type-check && npm run build && npm run deploy`。
- 本轮改用 **playwright-cli**（全局未安装，直接 `node /Users/stromboid/.codebuddy/plugins/marketplaces/codebuddy-plugins-official/plugins/playwright-cli/playwright-cli.js ...`）：默认要 Chrome 会报错 → **加 `--browser=chromium`**（内核已在 `~/Library/Caches/ms-playwright`）；先 `goto` 首页 → `localstorage-set nf_token <token>` → **`reload`**（只改 hash 不会重载，令牌不生效）；快照落项目根 `.playwright-cli/page-*.yml`（`--filename=` 会被忽略）；`npm ci` 可离线秒装（前端 `node_modules` 默认不在）。

## 后端踩坑（真实教训）
- `threading.Lock` 自锁死锁→共用锁且有嵌套一律 `RLock`。
- 事件循环线程长持同步锁→Web 假死：`mark_processed/mark_recent` 走 `asyncio.to_thread`；watcher 独立 `_scan_lock`。
- `ebooklib.write_epub` 父目录不存在只 warn 不抛→造真 EPUB 前必须先 `mkdir`。
- HMR 源码≠服务端产物→验证前必须 `npm run build && npm run deploy`。
- 批量端点必须注册在 `/api/books/{bid}` 之前；**同前缀下字面量路径也要在 `{param}` 之前**（如 `/api/scrape/run` vs `/api/scrape/{bid}/resolve`）。
- **硬链接副本禁止原地写**：副本与源共享 inode，`open(dst,'wb')` 会连源文件一起改坏；必须走「临时文件 + `Path.replace`」（只换目录项）。推论：内嵌过元数据的副本必然换成独立 inode、不再共享数据块，界面要如实标注而不是继续宣称「硬链接省空间」。
- FastAPI 的 `StaticFiles` 静态资源会被浏览器缓存：改了前端务必 `npm run build && npm run deploy` 再校对 `document.querySelectorAll('script')[].src` 是否为新 hash，否则会对着旧 JS 排查。

## 第 17 期（部分完成）
- 多书库收尾。T1 `book_id` 库维度化+迁移（**已完成**）；T2 逐库扫描调度（watcher 多目标 + 库表 `watch`/`scan_interval`/`scan_cron` 列，**已完成**）；T3「每库元数据写回 EPUB」**被第 18 期的口径取代**：元数据只存服务端 DB（`meta_override`/`meta_online`/`meta_cover`），**绝不改写 EPUB 文件**（2026-09-19 变更）。
- **T4 已完成**（第 19 期）：书库管理页工具条 + 四栏卡片，新建/编辑走三页签 —— 见下文第 19 期。
- **未完成**：T5 文档同步。
- 约束：新增书库由用户手动操作（参考上游三页签），**不自动建库**；每库内容来源 = 挂载文件夹 `LIBRARY_SOURCE_DIR/<source_subdir>`；格式按 `type` 只决定功能显隐矩阵，不干预来源子目录优先归库。

## 第 18 期：刮削出版（已完成 2026-09-19）
- 一句话：**扫描入库 → 刮元数据 → 在每库独立的「成品目录」硬链接出一份副本并把元数据写进副本**，源文件逐字节不变，外部阅读器（Komga 等）挂载成品目录即可读；「转换日志」页新增「刮削」子标签看进展/结果/失败人工整理。目的三条：不改原书信息 / 外部阅读器可见 / 失败可及时更正。
- 数据层：`libraries.publish_path`（每库成品目录，建/改库时选，空=不出版）；表 **`scrape_items`**（逐书台账，兼持久队列与「待确认」待办）；状态机 `pending/running/ok/failed/skipped/removed/kept/orphan/source_removed`，**只许降级**（回 ok 必须用户显式动作）。
- 模块分工：`core/publish.py` 只管**文件**（硬链接→失败回退 copy2、算命名/系列路径、原子写副本、回收旧副本）；`core/scrape.py` 只管**状态与调度**（单线程 daemon worker、队列入队、verify、resolve 五个显式动作）。
- 配置：`scrape.{enabled,max_attempts,verify_interval}`；每库覆写 `scrape.enabled`（能力 `komga`，有声书库不暴露）。日志动作 `ACTION_SCRAPE="刮削"`。
- 接口：`GET /api/scrape/state`、`POST /api/scrape/run|verify`、`POST /api/scrape/{bid}/resolve`；`/api/libraries/{lid}/scan` 扫描后按开关自动入队；watcher 入库三处调 `enqueue_scrape_async`（与 `auto_fetch_async` 分开：抓取看 `metadata_fetch`，出版看 `scrape.enabled`）。
- **不可动摇的三条**：① 源文件只读；② 副本禁止原地写（共享 inode，必须原子替换）；③ 副本被删**只标记待确认 + 记日志**，绝不自动删源、绝不自动重建（删原文件走回收站，需勾选二次确认）。成品目录**不得与库根/扫描源目录重叠**（否则副本被扫回来成重复书），后端建库即拦。
- 未续：`series_meta`/`apply_rename` 的结构性重排是否也去掉文件写（改前需用户确认）。

## 第 19 期：写文件彻底收敛 + T4 建库三页签（已完成 2026-09-19）
- **口径终局**：「元数据只存服务端」现在覆盖**全部**写回路径 —— 手动编辑 / revert / 抓取 apply / **重排册号** / **实体改名与合并**都只写 `meta_override`。**`core/publish.py` 是唯一还会写文件的地方**（写的是硬链接**副本**，且走原子替换）。`fileops.patch_epub_meta` / `rewrite_epub` 已退出生产路径（前者仅测试造夹具、后者仅 publish 写副本），别再新增调用方。
- **显式无值哨兵** `db.META_CLEAR = "-"`（仅对 `_CLEARABLE = ("series_index",)` 生效）：覆盖值是列、存不了空串（空串=撤销覆盖），「清空序号」只能靠哨兵。翻译点三处：`db.get_effective_meta`（要**带着空值**并进 merged，否则 library 保留文件旧值）、`metastore.effective`、`metastore.state`。
- **改名的 book_id 陷阱**：改名后 id 变（basename 派生），覆盖要落**新 id**；算库 id **不能**用 `fileops._lib_of(名字)`（它查扫描缓存，改名刚做完缓存还没更新 → 退化成旧纯哈希 id → 覆盖写进没人读的 id →「改了没生效」且不报错）。已加 `fileops._owning_library_id(path)`：按真实路径包含关系（取最深）算。测试用「扫描结果的 id」比对才抓得住这类静默错误。
- **后台线程与测试隔离**：接口用例会把 scrape daemon worker 真叫起来，跨用例存活会拿旧 DB 连接查新库 → 「单独跑必过、全量跑随机挂」。`scrape.stop(timeout=)` 支持 join，`tests/conftest.py` 用 **autouse 夹具**每例收尾停 worker（同「测试不养 watcher 线程」纪律）。
- **T4 建库流程（对齐上游）**：书库管理页 = 顶部工具条（全部扫描 / 过滤 / 排序：默认·名称·书籍数·上次扫描）+ 每库**四栏卡片**（书库 · 内容 · 自动化 · 上次扫描）；新建/编辑 = **三页签**（内容 / 自动化 / 上次扫描）。「刮削出版」开关在自动化页签，保存时「与全局一致 → 恢复继承；不一致 → 写覆盖」，避免切断继承。
- 仍未做：第 17 期 T5 文档同步。
