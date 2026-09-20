# 长期记忆（novel_dl_convert / NovelForge）

> 真值源 = `.codebuddy/memory/`。本文件只写不变式、约定、踩坑；某一期做了什么写当天 `YYYY-MM-DD.md`，不写进本文件（用户 2026-09-19 要求）。待办见文末。

## 项目 / 硬约定
- TXT→EPUB 工具，NAS/容器部署；`input`/`output` 物理分离；FastAPI + CLI；可插拔书源。镜像 `ghcr.io/735876214/novel_dl_convert:latest`。
- 删功能要删干净（路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口404」防回归断言）。
- 写计划只写四块：需求来源/功能范围/防回归要点/任务清单（不要架构/目录/关键代码结构）。
- 提交即推送：中文 commit，按能力拆多 commit；收尾工作区不留未提交改动。
- 视觉严格照搬 BookOrbit；零外部请求；局部更新不重建 DOM。
- ⚠️ 可能同时有另一 AI 会话：改前先 `git status`；别人改动不回退/不顺手提交；临时文件放 `/tmp`；记忆只追加。
- 新增书库由用户手动操作（不自动建库）；每库来源 = 挂载的 `LIBRARY_SOURCE_DIR/<source_subdir>`；库 `type` 只决定功能显隐矩阵，不干预「来源子目录优先」归库顺序。

## 元数据与出版（口径终局）
- 元数据只落服务端 DB（`meta_override`/`meta_online`/`meta_cover`）：手动编辑/revert/抓取apply/重排册号/改名/合并全部不写回文件。
- **源文件名没有任何可写入口**（第 28 期终局）：改名只剩「**按命名规则重出版副本**」一条落盘路径；实体改名/合并退化为一次纯元数据写入。
  - 命名规则**唯一实现** = `fileops.fill_pattern`（9 个占位符、先长后短），`publish.relpath_for` 调它；`PATTERN_FIELDS` 是唯一真值源，前端 `RENAME_TOKENS` 必须逐字一致（有契约测试）。**别再让第二处展开规则的地方出现**。
  - `{index}` = **系列卷号**（`series_index` → `seq` → `"01"`，两位补零），**不是**文件列表流水号（流水号会让文件名每刮一次就变）。
  - 「预览 == 落盘」是硬不变量：预览与落盘共用 `publish.relpath_for` **且**共用落点判据 `publish.rel_verdict`（`REL_REUSE`/`REL_REBUILD`/`REL_DECLINE`）。UI 层另外拒绝「有未保存草稿时重出版」（预览按草稿、落盘按保存值就是不一致）。
  - `apply_*` 的**目标一律由服务端自己算**：客户端给的 `book_ids` 只当**收窄**条件，预览条目不作为落盘依据 —— 预览过期也改不错。
  - 仍改 basename 的只剩 `fileops.apply_conflict_rename`（库内同名冲突）与 `apply_komga_layout`（库布局整理）——二者都成对调 `db.remap_book_id`。
- 在线抓取与手动编辑不按格式分流：结果只写 DB、与文件类型无关 → EPUB/PDF/漫画/有声书一视同仁（有声书是目录型条目）。非 EPUB 无 OPF 兜底原值层，故「恢复」=撤销覆盖后回落在线抓取值、无在线值即空。
- `core/publish.py` 是唯一仍写文件的模块（写硬链接副本、走原子替换）；`fileops.patch_epub_meta`/`rewrite_epub` 已退出生产路径，勿新增调用方。
- 刮削出版三不可动摇：①源文件只读；②副本禁止原地写（共享 inode，须「临时文件+Path.replace」）；③副本被删只标记待确认+记日志，绝不自删源/自重建。成品目录不得与库根/扫描源重叠（否则副本被扫回成重复书），建库即拦。
- **目录型条目（有声书一章一文件）同样出版**（第 29 期）：副本是**真目录**，内部逐文件硬链接（`publish.link_tree_or_copy`；`os.link`/`copy2` 都不能对目录用），故写副本不改源。条目形态判据 = **名字带不带 `library.BOOK_EXTS` 的扩展名**（不看 `format`：单文件与目录型音频同为 `AUDIO`；也不 stat 磁盘），与入库侧 `komga.relpath_for_dir` 同判据、同落点；副本名**不带扩展名**。源指纹是**整树指纹**（`source_sig` 对目录走 `_tree_files`：相对路径+大小+mtime）—— 目录自身 mtime 看不出内部改动，而章序就是文件名顺序，所以「改一轨内容」「互换章序」都必须算源变更；`_tree_files` 是**指纹与链接共用的唯一清单**，两处各写一套必然分叉。名字与磁盘形态不一致（目录名带扩展名）时**跳过出版**，不产错名。
- `{ext}` 展开后**已经带上了扩展名**，落点拼接（`komga.relpath_for`）会再拼一次 ⇒ 模式写 `{title}.{ext}` 曾落成 `书名.m4b.m4b`（第 29 期修）。只在模式**以 `{ext}` 收尾**时摘掉尾部扩展名；`{ext}` 出现在别处（如 `{ext} - {title}`）是用户显式要扩展名进名字，一律不动。
- 无值哨兵 `db.META_CLEAR = "-"`（`_CLEARABLE`=全部可编辑字段，有测试钉住）：空串=撤销覆盖，「清空」只能靠哨兵。接口层 `null`=显式清空（写哨兵盖住在线值）。翻译三处一致：`db.get_effective_meta`（带无值进 merged）、`metastore.effective`、`metastore.state`（tags 无值给[]，其余给""）。

## Git / 环境 / 构建
- `.gitignore`：`.codebuddy/*` + `!.codebuddy/memory/`（否定配 `/*`）；忽略 `data/`、`*.db`、`novelforge/static/v2/`。
- 认证走 GCM；已清除 token 内嵌/insteadof 明文重写，勿再引入。推送失败先查认证/网络，别改 git config。
- Python 3.10+（本机用 `python3`）；Node v20/22。Docker daemon 可用，本机对外网络有限。
- 行尾必须 LF（`.gitattributes` 锁）；CRLF 让容器 `sh /app/start.sh` 报 `set: Illegal option -` 反复重启。

## 自动化测试（硬前提）
- 完全离线：`.venv/bin/python -m pytest`；dev 依赖在 `requirements-dev.txt`。基线：POSIX **270 passed**（第 24 期 +5）；**第 28 期 win32 全量 310 例 / 309 passed / 1 failed**（唯一失败 = 已知 flaky 有声书，无回归）。计数按环境取，别混引。
- ⚠️ win32 侧无项目 venv（`.venv/` 未建）；自建后跑全量前先 `mkdir novelforge/static`（不入库，缺它 import `server` 即 `ensure_dirs()` 失败）；win32 另有 1–2 例「扫描→自动入队」失败（`test_watcher_auto_fetch`、`test_scrape_publish`），pytest 汇总行 PowerShell 下抓不到。**核对回归请在用户原环境跑。**
- 曾全量后半程 segfault 根因：`watcher.auto_fetch_async`/`enqueue_scrape_async` 派生旁路线程未登记，teardown 关库后它们才查库。现由 `tests/conftest.py` 的 `_quiesce_background()`（`watcher.wait_pending`+`scrape.stop`）在 `isolated` 夹具 `db.close()` **之前**收尾，autouse 只兜底。
- 硬前提：①环境变量必须在 import 业务模块前设（`config` 导入即固化目录、`server` 导入即 `ensure_dirs()`）；②`db._conn`/`_db_path` 模块级缓存 → 隔离靠 `db.close()`。
- 碰库/DB 用例必须 `isolated`；接口用 `client`+`auth_headers`。假 EPUB（`b"EPUB"`）够扫描类；元数据写回/系列解析要真 EPUB（`epub_builder.build_epub`）。不测会外呼的接口（要测就换检索函数返回固定候选）；`GET /` 会 503。
- 库 id 由名称派生（中文 slug 空→`lib-<sha1[:8]>`）；测试库根须在 `LIBRARY_SOURCE_DIR` 下。
- 断言终态留余地：单线程 worker 可能比测试快 → 断言「还在 pending/running」会随机挂，应允许 ok。

## 后端硬约束
- core 内引用配置一律 `from .. import config`；`import config` 被同名命名空间包劫持（py_compile 抓不到，启动才炸）。
- 写磁盘只用 rename/move，从不 unlink；删除即移入回收目录（`CACHE_DIR/recycle`）。禁 `config.OUTPUT_DIR / b["name"]` → 一律 `library.root_of(b) / b["name"]`。
- 库根只允许落在 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR` 内（`safe_path` 边界）。`book_id` 由 basename 派生、库维度化（`库$哈希`）。
- 新增库表列必须同进 `db._LIBRARY_COLS`，否则 `update_library` 静默写不进。
- 统计接口（`core/stats.py`）：`overview.integrity` 的**原有 5 个计数键一个都不能少**（前端旧渲染路径与既有测试都依赖它），第 29 期加的百分比是**增补**不是替换；`largest`（体积榜）是独立新键，与作者/系列榜共用 `top` 参数，但**不要塞进 `_top`**（后者的排序口径是 `(-count, name)`）；0 字节书如实上榜 —— 它是真实信号，不是要排除的脏数据。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值 = 每库覆写 ?? 全局值`，落 `libraries.settings`（稀疏 JSON，键=全局点分路径）。
- `core/lib_settings.py`：`effective`/`config_for`/`apply_to`/`set_overrides`/`clear_overrides`/`schema()`；与 `features.allows_setting` 联动，`features.SETTING_CAPS` 是唯一真值源。接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（`?keys=` 按项恢复）。
- 覆盖项：`output.format`/`output.layout`、`watcher.recursive`/`watcher.copy_non_txt`、`metadata_fetch.*`、`naming.pattern`/`naming.scope`、`scrape.enabled`、`opds.expose`、`komga.expose`。（库实体属性 `watch`/`scan_interval`/`scan_cron`/`publish_path` 是列，非覆盖项。）
- 对外可见性两层：**能力矩阵**（库类型有没有这能力）**且**「每库覆写??全局」开关，判定只留一处（OPDS `_opds_visible_libraries`/Komga `_ko_visible_libraries`）。口径：「不可见」=「不存在」对客户端同待遇 → 列表没有且直连 404（Komga 用 `_ko_book`/`_ko_find_series`，别用 `library.by_id`/`komga_api.find_series`）。
- 能力矩阵 `features.FEATURES_BY_TYPE` 决定库类型能力，前端只声明菜单需哪个能力——加库类型只改后端，加菜单只改前端。

## 前端栈 / 规范
- `frontend/` = Vue3 SFC + TS + Vite8 + Tailwind v4 + Pinia4 + vue-router5（hash）。产物落 `novelforge/static/v2/`，FastAPI 挂 `/static`，`/` 服务其 index.html（缺失 503）。勿往 `novelforge/static/` 加手写页。
- `bridge.css` 前提（`@theme inline`）；`main.css` 须 `@custom-variant dark (&:is(.dark *));`。
- 仪表盘演示数据必须确定性常量，禁 `Math.random()`。`settingsNav`/router「标 ready 未注册组件」会 console.error → 注册表与组件同批改。`p()` 首参=路由 path，全局唯一（同 path 两条被 vue-router 静默覆盖+侧栏重复 key）。
- Vue 模板不渲染 markdown → 静态文本用 `<strong>`，JS 字符串别加星号。
- 工具页 `ToolsLayout.vue`=`/tools` 外壳（标签栏+嵌套 RouterView+KeepAlive :max=8，无卡片外框）；路由子页用 `onActivated`（别挂 `onMounted`），不在 `onActivated` 里重置用户输入。改磁盘工具一律「先预览再应用」，删除即移回收站。
- ⚠️ 例外：页面内部 `v-if` 子组件（比 KeepAlive 深两层，如 `ScrapePanel`）首挂 `onActivated` 不触发 → 用 `onMounted` 首载，`onActivated` 只做重新激活刷新（用 data 非空条件天然去重）。
- 表格面板窄屏可用：宽屏 `<table class="hidden md:block">`，窄屏另写 `<ul class="md:hidden">` 卡片流。
- 纯装饰增强（如详情页封面取色）取不到就不设变量 → CSS 整条失效 → 天然回退。

## 运行 / UI 验证
- 本地测试实例：`*_DIR` → `/tmp/nf-test/…`，`LIBRARY_SOURCE_DIR=/tmp/nf-test/libraries` 要显式设，`AUTO_WATCH=false`，auth admin/test1234，`python3 -m uvicorn novelforge.server:app --port 8791`，token 落 `/tmp/nf-test/token.txt`。⚠️ `/tmp/nf-test` 可能被清理 → e2e 脚本自带数据准备。
- Docker：`docker-compose.yml` 真实版端口 **8992**；`docker-compose.test.yml` 本地 build 挂 `./novelforge` 端口 **8993**（容器，别动）。断网无法 `--build`。8992/8993 数据隔离。
- UI 验证：playwright 直连实例，`nf_token` 用 `add_init_script` 注入；迁移弹窗先 `force=True` 点「暂不迁移」。构建：`cd frontend && npm run type-check && npm run build && npm run deploy`。
- playwright-cli：默认要 Chrome 报错 → 加 `--browser=chromium`；先 `goto` 首页 → `localstorage-set nf_token <token>` → **`reload`**（只改 hash 不重载，令牌不生效）；快照落 `.playwright-cli/page-*.yml`。

## 后端踩坑
- `threading.Lock` 自锁死锁 → 共用锁且有嵌套调用一律 `RLock`。
- 事件循环线程长持同步锁 → Web 假死：`mark_processed`/`mark_recent` 走 `asyncio.to_thread`；watcher 独立 `_scan_lock`。
- `ebooklib.write_epub` 父目录不存在只 warn 不抛 → 造真 EPUB 前先 `mkdir`。
- HMR 源码 ≠ 服务端产物 → 验证前必须 `npm run build && npm run deploy`。
- 批量端点必须注册在 `/api/books/{bid}` 之前；同前缀字面量路径也要在 `{param}` 之前（如 `/api/scrape/run` vs `/api/scrape/{bid}/resolve`）。
- 硬链接副本禁止原地写：副本与源共享 inode，`open(dst,'wb')` 连源一起改坏 → 须「临时文件+Path.replace」。推论：内嵌过元数据的副本换成独立 inode，界面要如实标注而非宣称「硬链接省空间」。
- FastAPI `StaticFiles` 被浏览器缓存：改前端务必 build+deploy 再校对 JS hash。
- ⚠️ **第 28 期收窄**：实体改名/合并**不再改 basename** ⇒ `book_id` 不变、无 id 搬迁问题。下面这条老踩坑**只对仍改 basename 的两处**（`apply_conflict_rename` / `apply_komga_layout`）生效：改 basename 后 `book_id` 会变（basename 派生），元数据覆盖要落新 id；算所属库不能靠 `fileops._lib_of`（查扫描缓存，改名后缓存未更新 → 覆盖写进没人读的 id，「改了没生效」还不报错）；`_owning_library_id` 已随 `apply_rename` 删除，这两处走 `db.remap_book_id` 搬迁。测试用「扫描结果的 id」比对。
- 字符串模板替换先长后短：`{series_index}` 排 `{series}`/`{index}` 之前（唯一实现 `fileops.fill_pattern`，见「元数据与出版」）。
- 目录型条目（有声书）不能用 `is_file()` 判存在：它是目录，`path.is_file()` 为假→误判不存在（元数据 `apply()` 踩过）。判存在用 `path.exists()`，格式闸门不该拦「只写 DB」的链路。

## 待办（跨会话）
- 外部服务同步（Hardcover/Readwise/StoryGraph 推送）：**用户 2026-09-19 拍板本轮明确不做**，不再排期，也不留半成品入口；相关设置页维持如实标注「未支持」。
- BookOrbit 参考仓库已升格为**真值源**：`735876214/bookorbit` @ `main` @ `c292d6cc`，只读 blobless 稀疏镜像在 `%TEMP%\bookorbit-ref`（`packages/types` + `packages/plugin-api`，76 个 `.ts`）；文档结论须标注来源文件，与历史实测冲突时以源码为准，源码无法确认处标「未验证（源码无法确认）」。
- 上游 `client/` 与 `server/src/modules/*` **尚未取证**（按需 sparse-checkout 追加）；已知界面层空白：成就 `dedication/devices` 分组标题、Requests 两页表格列。bulk-rename 类型在 `packages/types/src/file-write.ts:229-274`（第 28 期核实）—— **取证要扫符号，别按文件名猜**。
- 批注 Hub 四分组 UI 第 27 期已落地（月/书/颜色/来源，纯前端分组）；**无数据源故不做**：`origin` 的 `koreader`/`kobo`、`needsReview`、`devices`、跨端降色（kosync 已核实是纯进度、无批注端点）。
- **批注域的软删除是既定语义**（第 27 期）：`DELETE` = 移入垃圾桶（写 `deleted_at`），`purge` 才是真删且**只对垃圾桶内条目开放**。加任何新的 `annotations` 读点时**必须带 `WHERE deleted_at = 0`**；新增「按 book_id 探测是否已有数据」的级联逻辑时，探测谓词**必须同样过滤**，否则会静默搁浅活跃批注（`remap_book_id` 踩过，见 `REMAP_PROBE_FILTER`）。
- **文档过期是常态，改文档前先核验代码**：`docs/bookorbit-capability-gap.md` 曾把「本项目无」写在一堆早已实现的能力上，**它的 §0.3「判定依据」基线自己就先过期了**（68→260 路由、6→28 表）。**基线错误会让下游每条判定都失去依据** —— 复核该文档时先重取基线，再逐条核验，**不做整表翻转**（有反例：StatsView 双分区、Integrity 百分比、「孤儿封面目录」是刻意不同设计，均为「仍缺/刻意」而非「已做」）。
