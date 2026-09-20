# 长期记忆（novel_dl_convert / NovelForge）

> 真值源 = `.codebuddy/memory/`。本文件只写不变式、约定、踩坑；某一期做了什么写当天 `YYYY-MM-DD.md`，不写进本文件（用户 2026-09-19 要求）。待办见文末。

## 项目 / 硬约定
- TXT→EPUB 工具，NAS/容器部署；`input`/`output` 物理分离；FastAPI + CLI；可插拔书源。镜像 `ghcr.io/735876214/novel_dl_convert:latest`。
- 删功能要删干净（路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口404」防回归断言）。
- 写计划只写四块：需求来源/功能范围/防回归要点/任务清单（不要架构/目录/关键代码结构）。
- 提交即推送：中文 commit，按能力拆多 commit；收尾工作区不留未提交改动。
- 视觉严格照搬 BookOrbit；零外部请求；局部更新不重建 DOM。
- ⚠️ 可能同时有另一 AI 会话：改前先 `git status`；别人改动不回退/不顺手提交；临时文件放 `/tmp`；记忆只追加。
- 新增书库由用户手动操作（不自动建库）；每库来源 = 挂载的 `LIBRARY_SOURCE_DIR/<source_subdir>`；库 `type` 只决定功能显隐矩阵。

## 元数据与出版（口径终局）
- 元数据只落服务端 DB（`meta_override`/`meta_online`/`meta_cover`）：手动编辑/revert/抓取apply/重排册号/改名/合并全部不写回文件。
- **源文件只读、副本禁止原地写**（共享 inode，须「临时文件+Path.replace」）是贯穿全局的不可动摇约束：①刮削出版三不可动摇（源只读/副本禁原地写/副本被删只标记待确认+记日志绝不自删源）；②硬链接副本内嵌过元数据会换成独立 inode，界面如实标注而非宣称「省空间」。成品目录不得与库根/扫描源重叠（建库即拦）。
- **源文件名没有任何可写入口**（第 28 期终局）：改名只剩「**按命名规则重出版副本**」一条落盘路径；实体改名/合并退化为纯元数据写入。
  - 命名规则**唯一实现** = `fileops.fill_pattern`（9 占位符、先长后短），`publish.relpath_for` 调它；`PATTERN_FIELDS` 唯一真值源，前端 `RENAME_TOKENS` 必须逐字一致（有契约测试）。**别再让第二处展开规则出现**。
  - `{index}` = **系列卷号**（两位补零），**不是**文件列表流水号；`{ext}` 展开已带扩展名，模式以 `{ext}` 收尾才摘尾扩展名（否则曾落成 `书名.m4b.m4b`）。
  - 「预览 == 落盘」硬不变量：共用 `publish.relpath_for` 与 `publish.rel_verdict`（`REL_REUSE/REBUILD/DECLINE`）；UI 拒「有未保存草稿时重出版」。
  - `apply_*` 目标一律由服务端算，客户端 `book_ids` 只当收窄条件。
  - 仍改 basename 的只剩 `apply_conflict_rename`/`apply_komga_layout`，二者成对调 `db.remap_book_id`。
- 在线抓取与手动编辑不按格式分流：结果只写 DB、与文件类型无关 → EPUB/PDF/漫画/有声书一视同仁（有声书是目录型条目）。非 EPUB 无 OPF 兜底原值层，「恢复」=撤销覆盖回落在线值。
- `core/publish.py` 是唯一仍写文件模块（硬链接副本+原子替换）；`fileops.patch_epub_meta`/`rewrite_epub` 已退出生产路径。
- **目录型条目（有声书一章一文件）同样出版**（第 29 期）：副本是真目录、内部逐文件硬链接（`publish.link_tree_or_copy`）；条目形态判据 = **名字带不带 `library.BOOK_EXTS` 扩展名**（不看 `format`/不 stat 磁盘）；副本名**不带扩展名**；源指纹是整树指纹（`source_sig._tree_files`，链接与指纹共用唯一清单）。目录名带扩展名时跳过出版。
- 无值哨兵 `db.META_CLEAR = "-"`（`_CLEARABLE` 全字段、有测试钉住）：空串=撤销覆盖；接口层 `null`=显式清空（写哨兵）。翻译三处一致：`db.get_effective_meta`/`metastore.effective`/`metastore.state`。

## Git / 环境 / 构建
- `.gitignore`：`.codebuddy/*` + `!.codebuddy/memory/`；忽略 `data/`、`*.db`、`novelforge/static/v2/`。
- 认证走 GCM；已清除 token 内嵌/insteadof 明文重写，勿再引入。推送失败先查认证/网络，别改 git config。
- Python 3.10+（本机 `python3`）；Node v20/22。Docker daemon 可用，本机对外网络有限（推送/拉取常需代理优先策略）。
- 行尾必须 LF（`.gitattributes` 锁）；CRLF 让容器 `sh /app/start.sh` 报 `set: Illegal option -` 反复重启。

## 自动化测试（硬前提）
- 完全离线：`.venv/bin/python -m pytest`；dev 依赖在 `requirements-dev.txt`。基线：POSIX 270 passed；**win32 全量 310 例 / 309 passed / 1 failed**（唯一失败=已知 flaky 有声书）。计数按环境取，别混引。
- ⚠️ win32 无项目 venv；自建后跑全量前先 `mkdir novelforge/static`（缺它 import `server` 即 `ensure_dirs()` 失败）；win32 另有 1–2 例「扫描→自动入队」失败，PowerShell 下 pytest 汇总行抓不到。**核对回归请在用户原环境跑。**
- 曾全量后半程 segfault：旁路线程未在 teardown 前收尾 → 现由 `tests/conftest.py` 的 `_quiesce_background()`（`watcher.wait_pending`+`scrape.stop`）在 `isolated` 夹具 `db.close()` **之前**收尾。
- 硬前提：①环境变量须在 import 业务模块前设（`config` 导入固化目录、`server` 导入即 `ensure_dirs()`）；②`db._conn`/`_db_path` 模块级缓存 → 隔离靠 `db.close()`。
- 碰库/DB 用例必须 `isolated`；接口用 `client`+`auth_headers`。假 EPUB（`b"EPUB"`）够扫描类；元数据写回/系列解析要真 EPUB（`epub_builder.build_epub`）。不测会外呼接口。`GET /` 会 503。
- 库 id 由名称派生（中文 slug 空→`lib-<sha1[:8]>`）；测试库根须在 `LIBRARY_SOURCE_DIR` 下。断言终态留余地（单线程 worker 可能比测试快）。

## 后端硬约束
- core 内引用配置一律 `from .. import config`；`import config` 被同名命名空间包劫持（py_compile 抓不到，启动才炸）。
- 写磁盘只用 rename/move，从不 unlink；删除即移入回收目录（`CACHE_DIR/recycle`）。禁 `config.OUTPUT_DIR / b["name"]` → 一律 `library.root_of(b) / b["name"]`。
- 库根只允许落在 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR` 内（`safe_path` 边界）。`book_id` 由 basename 派生、库维度化（`库$哈希`）。
- 新增库表列必须同进 `db._LIBRARY_COLS`，否则 `update_library` 静默写不进。
- 统计接口（`core/stats.py`）：`overview.integrity` **原有 5 个计数键一个都不能少**（第 29 期百分比是增补）；`largest`（体积榜）独立新键、与作者/系列榜共用 `top`，但**不要塞进 `_top`**（排序口径 `(-count, name)`）；0 字节书如实上榜。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值 = 每库覆写 ?? 全局`，落 `libraries.settings`（稀疏 JSON，键=全局点分路径）。
- `core/lib_settings.py`：`effective`/`config_for`/`apply_to`/`set_overrides`/`clear_overrides`/`schema()`；与 `features.allows_setting` 联动，`features.SETTING_CAPS` 唯一真值源。接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（`?keys=` 按项恢复）。
- 覆盖项：`output.format`/`output.layout`、`watcher.recursive`/`watcher.copy_non_txt`、`metadata_fetch.*`、`naming.pattern`/`naming.scope`、`scrape.enabled`、`opds.expose`、`komga.expose`。
- 对外可见性两层：**能力矩阵**（库类型有没有这能力）**且**「每库覆写??全局」开关，判定只留一处（OPDS `_opds_visible_libraries`/Komga `_ko_visible_libraries`）。「不可见」=「不存在」→ 列表没有且直连 404（用 `_ko_book`/`_ko_find_series`，别用 `library.by_id`/`komga_api.find_series`）。
- 能力矩阵 `features.FEATURES_BY_TYPE` 决定库类型能力，前端只声明菜单需哪个能力。

## 前端栈 / 规范
- `frontend/` = Vue3 SFC + TS + Vite8 + Tailwind v4 + Pinia4 + vue-router5（hash）。产物落 `novelforge/static/v2/`，FastAPI 挂 `/static`，`/` 服务其 index.html（缺失 503）。勿往 `novelforge/static/` 加手写页。
- `bridge.css` 前提（`@theme inline`）；`main.css` 须 `@custom-variant dark (&:is(.dark *));`。
- 仪表盘演示数据必须确定性常量，禁 `Math.random()`。`settingsNav`/router「标 ready 未注册组件」会 console.error → 注册表与组件同批改。`p()` 首参=路由 path，全局唯一（同 path 两条被静默覆盖+侧栏重复 key）。
- Vue 模板不渲染 markdown → 静态文本用 `<strong>`，JS 字符串别加星号。
- 工具页 `ToolsLayout.vue`=`/tools` 外壳（标签栏+嵌套 RouterView+KeepAlive :max=8，无卡片外框）；路由子页用 `onActivated`（别挂 `onMounted`），不在 `onActivated` 里重置用户输入。改磁盘工具一律「先预览再应用」，删除即移回收站。⚠️ 例外：页面内部 `v-if` 子组件（比 KeepAlive 深两层，如 `ScrapePanel`）首挂 `onActivated` 不触发 → `onMounted` 首载、`onActivated` 只刷新（data 非空去重）。
- 表格面板窄屏可用：宽屏 `<table class="hidden md:block">`，窄屏另写 `<ul class="md:hidden">` 卡片流。纯装饰增强取不到就不设变量 → CSS 整条失效 → 天然回退。

## 运行 / UI 验证
- 本地测试实例：`*_DIR`→`/tmp/nf-test/…`，显式设 `LIBRARY_SOURCE_DIR=/tmp/nf-test/libraries`，`AUTO_WATCH=false`，auth admin/test1234，`python3 -m uvicorn novelforge.server:app --port 8791`，token 落 `/tmp/nf-test/token.txt`。⚠️ `/tmp/nf-test` 可能被清理 → e2e 脚本自带数据准备。
- Docker：`docker-compose.yml` 端口 **8992**；`docker-compose.test.yml` 本地 build 挂 `./novelforge` 端口 **8993**（容器别动）。断网无法 `--build`。8992/8993 数据隔离。
- 构建：`cd frontend && npm run type-check && npm run build && npm run deploy`，并核对 `/static/v2/assets/index-*.js` 实际内容（HMR 源码≠服务端产物，StaticFiles 有浏览器缓存）。
- UI 验证：playwright 直连实例，`nf_token` 用 `add_init_script` 注入；迁移弹窗先 `force=True` 点「暂不迁移」。playwright-cli 默认要 Chrome 报错 → 加 `--browser=chromium`；先 `goto` 首页 → `localstorage-set nf_token <token>` → **`reload`**（只改 hash 不重载、令牌不生效）；快照落 `.playwright-cli/page-*.yml`。

## 后端踩坑
- `threading.Lock` 自锁死锁 → 共用锁且有嵌套调用一律 `RLock`。
- 事件循环线程长持同步锁 → Web 假死：`mark_processed`/`mark_recent` 走 `asyncio.to_thread`；watcher 独立 `_scan_lock`。
- `ebooklib.write_epub` 父目录不存在只 warn 不抛 → 造真 EPUB 前先 `mkdir`。
- 批量端点必须注册在 `/api/books/{bid}` 之前；同前缀字面量路径也要在 `{param}` 之前（如 `/api/scrape/run` vs `/api/scrape/{bid}/resolve`）。
- 目录型条目（有声书）不能用 `is_file()` 判存在（它是目录→误判不存在）；判存在用 `path.exists()`，格式闸门不该拦「只写 DB」链路。
- 字符串模板替换先长后短：`{series_index}` 排 `{series}`/`{index}` 之前。

## 待办（跨会话）
- 外部服务同步（Hardcover/Readwise/StoryGraph 推送）：**用户 2026-09-19 拍板本轮明确不做**；相关设置页维持「未支持」。
- 上游 `client/` 与 `server/src/modules/*` 取证：**第 30 期尝试 sparse-checkout，本环境无终端/网络故失败**，降级对 `%TEMP%\bookorbit-ref` 的 `packages/types` 做符号级补扫。结论已落 `docs/bookorbit-capability-gap.md`（第30期改判）：缺失资源 `sweep`=`CoverSweep`（封面修复扫描，非本项目缺失资源语义）、EDITIONS「版本编号」=外部 Hardcover/Storygraph `edition`（非自有版本号）、通知 `Clear` 在 `notification.ts` 未取证（模型仅 `read`/`count`）、成就 `dedication/devices` 分组标题确证、Requests 表格列确证（`createdAt/title/mediaKind/requester/status`）。文档结论须标注来源文件，与历史实测冲突以源码为准，源码无法确认处标「未验证」。
- BookOrbit 参考仓库 = `735876214/bookorbit` @ `main` @ `c292d6cc`，只读 blobless 稀疏镜像在 `%TEMP%\bookorbit-ref`（`packages/types` + `packages/plugin-api`）。**取证要扫符号，别按文件名猜**（第 28 期 bulk-rename 漏检教训）。
- 批注 Hub 四分组 UI 第 27 期已落地（月/书/颜色/来源，纯前端分组）；**无数据源故不做**：`origin` 的 `koreader`/`kobo`、`needsReview`、`devices`、跨端降色（kosync 纯进度、无批注端点）。
- **批注域软删除是既定语义**（第 27 期）：`DELETE`=移入垃圾桶（写 `deleted_at`），`purge` 才真删且只对垃圾桶内开放。新增 `annotations` 读点**必须带 `WHERE deleted_at = 0`**；探测级联逻辑谓词同样过滤，否则静默搁浅活跃批注（`remap_book_id` 踩过，`REMAP_PROBE_FILTER`）。
- **文档过期是常态，改文档前先核验代码**：`docs/bookorbit-capability-gap.md` 曾把「本项目无」写在早已实现的能力上，§0.3 基线自身先过期（68→260 路由、6→28 表）。复核该文档先重取基线再逐条核验，**不做整表翻转**（StatsView 双分区、Integrity 百分比、「孤儿封面目录」为刻意不同设计，是「仍缺/刻意」非「已做」）。
