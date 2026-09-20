# 长期记忆（novel_dl_convert / NovelForge）

> 真值源=`.codebuddy/memory/`；本文件只记不变式/约定/踩坑。某期做了什么写当天 `YYYY-MM-DD.md`，不进本文件（2026-09-19 约定）。

## 项目与硬约定
- TXT→EPUB 工具，NAS/容器部署；input/output 物理分离；FastAPI+CLI；可插拔书源。镜像 `ghcr.io/735876214/novel_dl_convert:latest`。
- 删功能要删干净（路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口404」防回归断言）。
- 写计划只写四块：需求来源/功能范围/防回归要点/任务清单（不要架构/目录/代码结构）。
- 提交即推送：中文 commit、按能力拆多 commit；收尾工作区不留未提交改动。
- 视觉严格照搬 BookOrbit；零外部请求；局部更新不重建 DOM。
- 可能同时有另一 AI 会话：改前 `git status`；别人改动不回退/不顺手提交；临时文件放 `/tmp`；记忆只追加。
- 新增书库用户手动操作（不自动建库）；每库来源=挂载 `LIBRARY_SOURCE_DIR/<source_subdir>`；库 `type` 只决定功能显隐矩阵。

## 元数据与出版（终局口径）
- 元数据只落服务端 DB（meta_override/online/cover），一切编辑/revert/抓取/重排册号/改名/合并均不写回文件。
- **源不可变**（贯穿全局不可动摇）：源只读、副本禁原地写（共享 inode，须「临时文件+Path.replace」）；刮削出版三不可动摇（源只读/副本禁原地写/副本被删只标记待确认+记日志绝不自删源）；硬链接副本内嵌过元数据会换独立 inode，界面如实标注而非宣称省空间；成品目录不得与库根/扫描源重叠（建库即拦）。
- **源文件名无写入口**（第28期终局）：改名只剩「按命名规则重出版副本」一条落盘路径；实体改名/合并退化为纯元数据写入。
  - 命名规则**唯一实现**=`fileops.fill_pattern`（9 占位符、先长后短），`publish.relpath_for` 调它；`PATTERN_FIELDS` 唯一真值源，前端 `RENAME_TOKENS` 须逐字一致（有契约测试）。**别再让第二处展开规则出现**。
  - `{index}`=系列卷号（两位补零，非流水号）；`{ext}` 展开已带扩展名，模式以 `{ext}` 收尾才摘尾扩展名（否则 `书名.m4b.m4b`）。
  - 「预览==落盘」硬不变量：共用 `publish.relpath_for`+`publish.rel_verdict`（REL_REUSE/REBUILD/DECLINE）；UI 拒「有未保存草稿时重出版」。
  - `apply_*` 目标一律服务端算，客户端 `book_ids` 只当收窄条件；仍改 basename 的只剩 `apply_conflict_rename`/`apply_komga_layout`（成对调 `db.remap_book_id`）。
- 在线抓取与手动编辑不按格式分流→结果只写 DB，EPUB/PDF/漫画/有声书一视同仁（有声书是目录型条目）；非 EPUB 无 OPF 兜底，「恢复」=撤销覆盖回落在线值。
- `core/publish.py` 是唯一仍写文件模块（硬链接副本+原子替换）；`fileops.patch_epub_meta`/`rewrite_epub` 已退出生产路径。
- **目录型条目（有声书一章一文件）同样出版**（第29期）：副本真目录、内部逐文件硬链接（`publish.link_tree_or_copy`）；形态判据=名字带不带 `library.BOOK_EXTS` 扩展名（不看 format/不 stat 磁盘）；副本名不带扩展名；源指纹=整树指纹（`source_sig._tree_files`）；目录名带扩展名时跳过出版。
- 无值哨兵 `db.META_CLEAR="-"`（`_CLEARABLE` 全字段、有测试钉住）：空串=撤销覆盖；接口层 `null`=显式清空（写哨兵）。翻译三处一致：`db.get_effective_meta`/`metastore.effective`/`metastore.state`。

## Git / 环境 / 构建
- `.gitignore`：`.codebuddy/*`+`!.codebuddy/memory/`；忽略 `data/`、`*.db`、`novelforge/static/v2/`。
- 认证走 GCM；已清 token 内嵌/insteadof 明文重写，勿再引入；推送失败先查认证/网络，别改 git config。
- Python 3.10+（本机 `python3`）；Node v20/22；Docker daemon 可用，本机对外网络有限（推送/拉取常需代理优先策略）。
- 行尾必须 LF（`.gitattributes` 锁）；CRLF 让容器 `sh /app/start.sh` 报 `set: Illegal option -` 反复重启。

## 自动化测试（硬前提）
- 完全离线：`.venv/bin/python -m pytest`；dev 依赖在 `requirements-dev.txt`。基线：POSIX 270 passed；**win32 全量 310 例 / 309 passed / 1 failed**（唯一失败=已知 flaky 有声书）。计数按环境取，别混引。
- win32 无项目 venv；自建后跑全量前先 `mkdir novelforge/static`（缺它 import `server` 即 `ensure_dirs()` 失败）；另有 1–2 例「扫描→自动入队」失败，PowerShell 下 pytest 汇总行抓不到→**核对回归请在用户原环境跑**。
- 曾全量后半程 segfault→现由 `tests/conftest.py` 的 `_quiesce_background()`（`watcher.wait_pending`+`scrape.stop`）在 `isolated` 夹具 `db.close()` **之前**收尾。
- 硬前提：①环境变量须在 import 业务模块前设（`config` 导入固化目录、`server` 导入即 `ensure_dirs()`）；②`db._conn`/`_db_path` 模块级缓存→隔离靠 `db.close()`。
- 碰库/DB 用例必须 `isolated`；接口用 `client`+`auth_headers`。假 EPUB（`b"EPUB"`）够扫描类；元数据写回/系列解析要真 EPUB（`epub_builder.build_epub`）。不测会外呼接口。`GET /` 会 503。库 id 由名称派生（中文 slug 空→`lib-<sha1[:8]>`）；测试库根须在 `LIBRARY_SOURCE_DIR` 下；断言终态留余地。

## 后端约束与踩坑
- core 内引用配置一律 `from .. import config`；`import config` 被同名命名空间包劫持（py_compile 抓不到，启动才炸）。
- 写磁盘只用 rename/move，删除移 `CACHE_DIR/recycle`；路径用 `library.root_of(b)/b["name"]`，禁 `config.OUTPUT_DIR/b["name"]`。
- 库根限 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR`（`safe_path`）；`book_id`=basename 派生+库维度化（`库$哈希`）。
- 新增库表列须同进 `db._LIBRARY_COLS`，否则 `update_library` 静默写不进。
- 统计接口（`core/stats.py`）：`overview.integrity` **原有 5 个计数键一个都不能少**（第29期百分比是增补）；`largest`（体积榜）独立新键、与作者/系列榜共用 `top`，但**不要塞进 `_top`**（排序 `(-count, name)`）；0 字节书如实上榜。
- 共用锁嵌套用 `RLock`；`mark_processed`/`mark_recent` 走 `asyncio.to_thread`，watcher 独立 `_scan_lock`。
- `write_epub` 前先 `mkdir`（父目录不存在只 warn 不抛）；批量端点注册在 `/api/books/{bid}` 之前、字面量路径在 `{param}` 之前；目录型条目用 `path.exists()` 不用 `is_file()`；模板替换先长后短（`{series_index}` 排 `{series}`/`{index}` 前）。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值=每库覆写 ?? 全局`，落 `libraries.settings`（稀疏 JSON，键=全局点分路径）。
- `core/lib_settings.py`（`effective`/`config_for`/`apply_to`/`set_overrides`/`clear_overrides`/`schema()`）与 `features.SETTING_CAPS` 唯一真值源；接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（`?keys=` 按项恢复）。
- 覆盖项：`output.format`/`output.layout`、`watcher.recursive`/`watcher.copy_non_txt`、`metadata_fetch.*`、`naming.pattern`/`naming.scope`、`scrape.enabled`、`opds.expose`、`komga.expose`。
- 可见性=能力矩阵（库类型有没有）∩每库开关，判定只留一处（OPDS `_opds_visible_libraries`/Komga `_ko_visible_libraries`）。「不可见」=「不存在」→直连 404（用 `_ko_book`/`_ko_find_series`）。`features.FEATURES_BY_TYPE` 决定库类型能力。

## 前端栈与规范
- `frontend/`=Vue3 SFC+TS+Vite8+Tailwind v4+Pinia4+vue-router5(hash)。产物 `novelforge/static/v2/`，`/` 服务其 index.html（缺失 503）。勿往 `novelforge/static/` 加手写页。
- `bridge.css` 须 `@theme inline`；`main.css` 须 `@custom-variant dark (&:is(.dark *));`。
- 演示数据确定性常量禁 `Math.random()`；`p()` 路由 path 全局唯一（同 path 两条被静默覆盖+侧栏重复 key）；`settingsNav`/router 注册表与组件同批改。
- 工具页 `ToolsLayout.vue` 子页用 `onActivated`（非 `onMounted`）；改磁盘工具「先预览再应用」、删除移回收站。例外：页面内 `v-if` 子组件（如 `ScrapePanel`）需 `onMounted` 首载、`onActivated` 只刷新。
- 表格窄屏：宽屏 `<table class="hidden md:block">`+窄屏 `<ul class="md:hidden">`；纯装饰增强取不到就不设变量→CSS 整条失效→天然回退。

## 运行 / UI 验证
- 本地实例：`*_DIR→/tmp/nf-test/…`，`LIBRARY_SOURCE_DIR=/tmp/nf-test/libraries`，`AUTO_WATCH=false`，auth admin/test1234，`uvicorn novelforge.server:app --port 8791`，token 落 `/tmp/nf-test/token.txt`（⚠️目录可能被清→e2e 自带数据）。
- Docker：`docker-compose.yml` 端口 **8992**；`docker-compose.test.yml` 挂 `./novelforge` 端口 **8993**；断网无法 `--build`；数据隔离。
- 构建：`cd frontend && npm run type-check && npm run build && npm run deploy`，核对 `/static/v2/assets/index-*.js` 实际内容（HMR 源码≠服务端产物）。
- UI 验证：playwright 注入 `nf_token`（`add_init_script`+`localstorage-set`+**`reload`**）；迁移弹窗 `force=True` 点暂不迁移；CLI 加 `--browser=chromium`；快照落 `.playwright-cli/page-*.yml`。

## 上游取证与待办（跨会话）
- 外部同步（Hardcover/Readwise/StoryGraph）：**2026-09-19 拍板不做**；设置页维持未支持。
- 上游取证第30期 sparse-checkout 失败，降级扫 `%TEMP%\bookorbit-ref` 的 `packages/types`；结论落 `docs/bookorbit-capability-gap.md`：sweep=`CoverSweep`（非本项目缺失资源语义）、EDITIONS=外部 `edition`（非自有版本号）、通知 `Clear` 未取证、成就 `dedication/devices` 分组确证、Requests 列确证（`createdAt/title/mediaKind/requester/status`）。文档须标来源，冲突以源码为准。
- 参考仓库 `735876214/bookorbit` @ `main` @ `c292d6cc`，镜像 `%TEMP%\bookorbit-ref`（`packages/types`+`packages/plugin-api`）；**取证扫符号别按文件名猜**（第28期 bulk-rename 漏检教训）。
- 批注 Hub 四分组 UI 第27期落地（月/书/颜色/来源，纯前端）；**无数据源故不做**：`koreader`/`kobo`/`needsReview`/`devices`/跨端降色（kosync 纯进度、无批注端点）。
- **批注软删除既定语义**（第27期）：`DELETE`=移垃圾桶（`deleted_at`），`purge` 才真删且只对垃圾桶内开放；读点必须 `WHERE deleted_at=0`（曾 `remap_book_id` 踩过，`REMAP_PROBE_FILTER`）。
- **文档过期是常态，改前先核验代码**：`docs/bookorbit-capability-gap.md` 曾把「本项目无」写在已实现能力上，§0.3 基线自身先过期（68→260 路由、6→28 表）；复核先重取基线再逐条核验，**不做整表翻转**（StatsView 双分区、Integrity 百分比、「孤儿封面目录」为刻意不同设计）。
- 第31期取证仍无终端/网络，`client/` 与 `server/src/modules` **仍未 fetch**（同第30期），真值源限 `%TEMP%\bookorbit-ref` 的 `packages/types`。⚠️ **`account-activity.ts` = 管理端账号活跃度（admin 用户列表），不是阅读时间轴**，别拿它当热力图依据；阅读会话模型看 `reading-session.ts` 的 `dailySummary{day,totalMinutes}[]`（含 `READING_SESSION_SOURCES` 分桶）。

## 阅读活动与成就（第31期）
- 阅读活动页：后端 `core/activity.py` + `GET /api/reading-activity`（`library_id` 空串=全库、未知库=空集合不 404，与 `/api/stats` 同惯例；`year`/`limit` 可选）；聚合 `reading_sessions`（按 `started_at` **本地日**）+ `annotations`（必须 `WHERE deleted_at=0`）+ `user_achievements`；前端 `/reading-activity`（`stores/activity.ts` + `ReadingActivityView.vue`，纯 CSS Grid 热力图、零外链）。热力图数据模型对齐上游 `dailySummary`；**无 `source` 列 ⇒ 无分设备热力图**，属刻意分流。
- 成就分组对齐上游 5 分类中的 **4 个**（`library`/`reading`/`exploration`/`dedication`）；**`devices` 刻意不做**（上游靠 `reading_sessions.source` 分桶，本项目无该列）。`rarity/tier/hidden/iconName` 为上游展示层概念，本项目有意简化为无。**成就 key 不可改名**（前端/统计引用），只扩 `ACHIEVEMENTS` 目录 + `_metrics()`。
- 第31期新增测试 `tests/test_reading_activity.py`(3) 与 `tests/test_achievements_align.py`(4)，全量基线计数随之上浮（本机未复跑全量，别沿用旧的 310 例）。
