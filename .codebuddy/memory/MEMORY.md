# 长期记忆（novel_dl_convert / NovelForge）

> 真值源 = `.codebuddy/memory/`。**本文件只写不变式、约定与踩坑**；某一期做了什么、完成了什么，
> 写当天日记 `YYYY-MM-DD.md`（git 历史亦存），**不要写进本文件**（用户 2026-09-19 明确要求）。
> 待办另见文末「待办（跨会话）」小节。

## 项目 / 硬约定
- TXT→EPUB 工具，NAS/容器部署；`input`/`output` 物理分离；FastAPI + CLI；可插拔书源。镜像 `ghcr.io/735876214/novel_dl_convert:latest`。
- 删功能要删干净（路由 + 模块 + db CRUD + 能力键 + 前端页面/路由/api + 文档 + 记忆 + 「接口 404」防回归断言）。
- 写计划只写四块：需求来源 / 功能范围 / 防回归要点 / 任务清单（用户 2026-09-18 明确要求，不要架构设计 / 目录结构 / 关键代码结构）。
- 提交即推送：中文 commit，按能力拆多个 commit；收尾时工作区不留未提交改动。
- 视觉严格照搬 BookOrbit；零外部请求；局部更新不重建 DOM。
- ⚠️ 可能同时有另一 AI 会话：改文件前先 `git status`；别人改动不回退、也不要顺手提交（必要时用「恢复 HEAD 版本 → 只加自己那一处 → 提交 → 还原」分离）；临时文件放 `/tmp`；写记忆只追加。
- 新增书库由用户**手动**操作（**不自动建库**）；每库内容来源 = 挂载的 `LIBRARY_SOURCE_DIR/<source_subdir>`；库 `type` 只决定功能显隐矩阵，**不干预**「来源子目录优先」的归库顺序。

## 元数据与出版（口径终局）
- 元数据**只能落服务端 DB**（`meta_override` / `meta_online` / `meta_cover`）：手动编辑、revert、抓取 apply、重排册号、实体改名与合并**全部不写回文件**。
- **在线抓取不按格式分流**：结果只写 DB、与文件类型无关 → EPUB / PDF / 漫画 / 有声书一视同仁（有声书是**目录型条目**）。⚠️ 但**手动编辑元数据仍限 EPUB**：非 EPUB 没有 OPF 兜底原值层，「恢复原值」无从取（`server.py` 的 `editable` / 400 是刻意保留的）。
- **`core/publish.py` 是唯一还会写文件的模块**（写的是硬链接**副本**，且走原子替换）；`fileops.patch_epub_meta` / `rewrite_epub` 已退出生产路径（前者仅测试造夹具、后者仅 publish 写副本），别再新增调用方。
- 刮削出版**三条不可动摇**：① 源文件只读；② 副本禁止原地写（与源共享 inode，必须「临时文件 + `Path.replace`」）；③ 副本被删**只标记待确认 + 记日志**，绝不自动删源、绝不自动重建。成品目录**不得与库根 / 扫描源目录重叠**（否则副本被扫回来成重复书），后端建库即拦。
- 显式**无值哨兵** `db.META_CLEAR = "-"`（仅对 `_CLEARABLE = ("series_index",)` 生效）：覆盖值是列、存不了空串（空串 = 撤销覆盖），「清空序号」只能靠哨兵。翻译点三处必须一致：`db.get_effective_meta`（要**带着空值**并进 merged，否则 library 保留文件旧值）、`metastore.effective`、`metastore.state`。

## Git / 环境 / 构建
- `.gitignore`：`.codebuddy/*` + `!.codebuddy/memory/`（否定规则配 `/*`）；忽略 `data/`、`*.db`、`novelforge/static/v2/`。
- 认证走 GCM；URL 内嵌 token / `insteadof` 明文重写已清除，勿再引入。推送失败先查认证/网络，别改 git config。
- Python 需 3.10+（`.venv`，用 `.venv/bin/python` 或 `/Users/stromboid/.local/bin/python3.12`）；Node v20/22 皆可。Docker daemon 可用，本机对外网络有限。
- 行尾必须 LF（`.gitattributes` 锁）；CRLF 让容器 `sh /app/start.sh` 报 `set: Illegal option -` 反复重启。

## 自动化测试（硬前提）
- `.venv/bin/python -m pytest`（完全离线）；dev 依赖在 `requirements-dev.txt`。
- ⚠️ 全量跑完在解释器退出时会打一段 lxml faulthandler dump（既有环境现象），**以「N passed」为准**；exit code 仍为 0。
- 两条硬前提：① 环境变量必须在 import 业务模块前设置（`config` 导入即固化目录、`server.py` 导入即 `ensure_dirs()`）；② `db` 的 `_conn`/`_db_path` 是模块级缓存 → 隔离靠 `db.close()`。
- 碰书库/DB 用例必须声明 `isolated`；接口用 `client` + `auth_headers`。假 EPUB（`b"EPUB"`）够扫描类；元数据写回 / 系列解析必须真 EPUB（`epub_builder.build_epub`）。**不测会外呼的接口**（要测就把检索函数换成返回固定候选）；`GET /` 会 503。
- 库 id 由名称派生（中文 slug 空 → `lib-<sha1[:8]>`）；测试库根必须在 `LIBRARY_SOURCE_DIR` 下。
- 后台线程要能被测试收尾：`scrape` daemon worker 会跨用例存活并拿旧 DB 连接查新库（「单独跑必过、全量跑随机挂」）→ `scrape.stop(timeout=)` 支持 join，`tests/conftest.py` 用 **autouse 夹具**每例收尾停 worker（同「测试不养 watcher 线程」纪律）。

## 后端硬约束
- core 内引用配置一律 `from .. import config`；`import config` 被同名命名空间包劫持（py_compile 抓不到，启动才炸）。
- 写磁盘只用 rename/move，**从不 unlink**；删除即移入回收目录（`CACHE_DIR/recycle`）。**禁 `config.OUTPUT_DIR / b["name"]`** → 一律 `library.root_of(b) / b["name"]`。
- 库根只允许落在 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR` 内（`safe_path` 的边界）。`book_id` 由 basename 派生、**库维度化**（`库$哈希`）。
- 新增库表列**必须**同进 `db._LIBRARY_COLS`，否则 `update_library` 静默写不进。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时叠加 `生效值 = 每库覆写 ?? 全局值`，落点 `libraries.settings`（稀疏 JSON，键 = 全局点分路径）。
- `core/lib_settings.py`：`effective()` / `config_for()` / `apply_to()` / `set_overrides` / `clear_overrides` / `schema()`；与 `features.allows_setting` 联动，**`features.SETTING_CAPS` 是唯一真值源**。接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（`?keys=` 按项恢复）。
- 覆盖项：`output.format` / `output.layout`、`watcher.recursive` / `watcher.copy_non_txt`、`metadata_fetch.*`、`naming.pattern` / `naming.scope`、`scrape.enabled`。（库实体属性 `watch` / `scan_interval` / `scan_cron` / `publish_path` 是**列**，不是覆盖项。）
- 能力矩阵 `features.FEATURES_BY_TYPE` 决定「哪些库类型有哪些能力」，前端只声明「哪一行菜单需要哪个能力」——加库类型只改后端，加菜单只改前端。

## 前端栈 / 规范（要点）
- `frontend/` = Vue 3 SFC + TS + Vite 8 + Tailwind v4 + Pinia 4 + vue-router 5（hash 模式）；产物落 `novelforge/static/v2/`，FastAPI 挂 `/static`，`/` 服务其 `index.html`（缺失 503）。勿往 `novelforge/static/` 加手写页。
- `bridge.css` 是前提（`@theme inline`）；`main.css` 必须 `@custom-variant dark (&:is(.dark *));`。
- 仪表盘演示数据必须确定性常量，禁 `Math.random()`。`settingsNav` / router「标 ready 未注册组件」会 `console.error` → 注册表与组件必须同批改。**`p()` 的首参就是路由 path，全局必须唯一**（同 path 两条会被 vue-router 静默覆盖 + 侧栏重复 key）。
- Vue 模板不渲染 markdown → 静态文本用 `<strong>`，JS 字符串别加星号。
- 工具页 `ToolsLayout.vue` = `/tools` 外壳（标签栏 + 嵌套 RouterView + KeepAlive :max=8，**无卡片外框**）；**路由子页**用 `onActivated`（别挂 `onMounted`），不在 `onActivated` 里重置用户输入。改磁盘的工具一律「先预览、再应用」，删除即移入回收站。
- ⚠️ 例外：**页面内部的 `v-if` 子组件**（比 KeepAlive 深两层，如 `ScrapePanel`）首次挂载时 `onActivated` **不触发** → 必须用 `onMounted` 首载，`onActivated` 只做「重新激活时刷新」（用 `data` 非空之类的条件天然去重）。
- 表格类面板要窄屏可用：宽屏 `<table class="hidden md:block">`，窄屏另写一份 `<ul class="md:hidden">` 卡片流（信息不裁剪、只换排布）。
- 纯装饰类增强（如详情页封面取色）**取不到就不设变量** → CSS 整条声明失效 → 天然回退，不留黑块/透明块。

## 运行 / UI 验证
- 本地测试实例（已授权直接 py_compile + 重启）：`*_DIR` → `/tmp/nf-test/…`，**`LIBRARY_SOURCE_DIR=/tmp/nf-test/libraries` 也要显式设**（否则走默认 `/app/libraries` 不存在），`AUTO_WATCH=false`，auth `admin`/test1234，`.venv/bin/python -m uvicorn novelforge.server:app --port 8791`。token 落 `/tmp/nf-test/token.txt`（`POST /api/auth/login`）。⚠️ `/tmp/nf-test` 可能被清理 → e2e 脚本要**自带数据准备**（建目录、写占位书、建库、再 scan）。
- Docker：`docker-compose.yml` 真实版拉镜像端口 **8992**；`docker-compose.test.yml` 本地 build 挂 `./novelforge` 端口 **8993**（容器，别动）。**断网无法 `--build`**。8992/8993 数据隔离。
- UI 验证（playwright）：项目 `.venv`，`executable_path` 传内核；直连实例 `nf_token` 用 `add_init_script` 注入；迁移弹窗先 `force=True` 点「暂不迁移」。构建：`cd frontend && npm run type-check && npm run build && npm run deploy`。
- playwright-cli（全局未安装，直接 `node /Users/stromboid/.codebuddy/plugins/marketplaces/codebuddy-plugins-official/plugins/playwright-cli/playwright-cli.js ...`）：默认要 Chrome 会报错 → **加 `--browser=chromium`**（内核已在 `~/Library/Caches/ms-playwright`）；先 `goto` 首页 → `localstorage-set nf_token <token>` → **`reload`**（只改 hash 不会重载，令牌不生效）；快照落项目根 `.playwright-cli/page-*.yml`（`--filename=` 会被忽略）；`npm ci` 可离线秒装。

## 后端踩坑（真实教训）
- `threading.Lock` 自锁死锁 → 共用锁且有嵌套调用一律 `RLock`。
- 事件循环线程长持同步锁 → Web 假死：`mark_processed` / `mark_recent` 走 `asyncio.to_thread`；watcher 独立 `_scan_lock`。
- `ebooklib.write_epub` 父目录不存在只 warn 不抛 → 造真 EPUB 前必须先 `mkdir`。
- HMR 源码 ≠ 服务端产物 → 验证前必须 `npm run build && npm run deploy`。
- 批量端点必须注册在 `/api/books/{bid}` 之前；**同前缀下字面量路径也要在 `{param}` 之前**（如 `/api/scrape/run` vs `/api/scrape/{bid}/resolve`）。
- **硬链接副本禁止原地写**：副本与源共享 inode，`open(dst,'wb')` 会连源文件一起改坏；必须走「临时文件 + `Path.replace`」（只换目录项）。推论：内嵌过元数据的副本必然换成独立 inode、不再共享数据块，界面要如实标注而不是继续宣称「硬链接省空间」。
- FastAPI 的 `StaticFiles` 静态资源会被浏览器缓存：改了前端务必 build + deploy，再校对页面引用的 JS hash 是否更新，否则会对着旧 JS 排查。
- **改名后 `book_id` 会变**（basename 派生）：元数据覆盖要落**新 id**；算所属库**不能**用 `fileops._lib_of(名字)`（它查扫描缓存，改名刚做完缓存未更新 → 退化成旧纯哈希 id → 覆盖写进没人读的 id →「改了没生效」且不报错）。用 `fileops._owning_library_id(path)`（按真实路径包含关系、取最深）。测试要用「扫描结果的 id」比对才抓得住这类静默错误。
- **字符串模板替换必须先长后短**：`{series_index}` 要排在 `{series}` / `{index}` 之前 —— `str.replace` 只看字面量，顺序错了会被短 token 抢先吃掉一半。
- **目录型条目（有声书）不能用 `is_file()` 判存在**：它是**目录**，`path.is_file()` 为假 → 会被误判「文件不存在」（元数据抓取的 `apply()` 就踩过）。判存在用 `path.exists()`，格式相关的闸门不该拦「只写 DB」的链路。

## 待办（跨会话）
- **T5 文档同步**（并行会话遗留的收尾）。
- `series_meta` / `apply_rename` 的**结构性重排**是否也去掉文件写 —— **改前需用户确认**（与「元数据只存服务端」口径对齐的最后两处）。
- 非 EPUB 的元数据**手动编辑**仍限 EPUB（缺 OPF 兜底原值层，「恢复原值」无从取）；要放开需先设计「清除覆盖 = 恢复无值」的语义。
- 剩余 5 个 placeholder 设置页（`appearance/icons`、`appearance/layout`、`appearance/behavior`、`libraries`、`koreader-upstream`）**处置未定**（删 / 留作上游对照）。
