# 长期记忆（novel_dl_convert / NovelForge）

> 真值源=`.codebuddy/memory/`；本文件只记不变式/约定/踩坑。某期做了什么写当天 `YYYY-MM-DD.md`，不进本文件（2026-09-19 约定）。
> 2026-09-21 结构整理：合并重复条目、删掉已被代码/文档吸收的历史细节（第 30 期前的过程性内容），保留全部仍然成立的不变式。

## 项目与硬约定
- TXT→EPUB 工具，NAS/容器部署；input/output 物理分离；FastAPI+CLI；可插拔书源。镜像 `ghcr.io/735876214/novel_dl_convert:latest`。
- 删功能要删干净（路由+模块+db CRUD+能力键+前端页/路由/api+文档+记忆+「接口404」防回归断言）。
- 写计划只写四块：需求来源/功能范围/防回归要点/任务清单（不要架构/目录/代码结构）。
- 提交即推送：中文 commit、**按能力拆多 commit**；收尾工作区不留未提交改动。临时文件放 `/tmp`（别落仓库根）。
- 视觉严格照搬 BookOrbit；**零外部请求**；局部更新不重建 DOM；不做假交互（宁可空态也别放假数字）。
- 可能同时有另一 AI 会话：改前 `git status`；别人改动不回退/不顺手提交；记忆只追加。
- 新增书库用户手动操作（不自动建库）；每库来源=挂载 `LIBRARY_SOURCE_DIR/<source_subdir>`；库 `type` 只决定功能显隐矩阵。

## 元数据与出版（终局口径）
- 元数据只落服务端 DB（meta_override/online/cover），一切编辑/revert/抓取/重排册号/改名/合并均不写回文件。
- **源不可变**（不可动摇）：源只读、副本禁原地写（共享 inode，须「临时文件+`Path.replace`」）；刮削出版三原则（源只读/副本禁原地写/副本被删只标记待确认+记日志、绝不自删源）；硬链接副本内嵌过元数据会换独立 inode，界面**如实标注**而非宣称省空间；成品目录不得与库根/扫描源重叠（建库即拦）。
- **源文件名无写入口**（第 28 期终局）：改名只剩「按命名规则重出版副本」一条落盘路径；实体改名/合并退化为纯元数据写入。
- 命名规则**唯一实现**=`fileops.fill_pattern`（9 占位符、**先长后短**），`publish.relpath_for` 调它；`PATTERN_FIELDS` 是唯一真值源，前端 `RENAME_TOKENS` 须逐字一致（有契约测试）。**别再让第二处展开规则出现**。
  - `{index}`=系列卷号（两位补零，非流水号）；`{ext}` 展开已带扩展名 ⇒ 只有模式**以 `{ext}` 收尾**时才摘尾扩展名（否则 `书名.m4b.m4b`）。
  - 「预览==落盘」硬不变量：共用 `publish.relpath_for`+`publish.rel_verdict`（REL_REUSE/REBUILD/DECLINE）；UI 拒「有未保存草稿时重出版」。
  - `apply_*` 目标一律**服务端自己算**，客户端 `book_ids` 只当收窄条件；仍改 basename 的只剩 `apply_conflict_rename`/`apply_komga_layout`（成对调 `db.remap_book_id`）。
- 在线抓取与手动编辑**不按格式分流**→结果只写 DB，EPUB/PDF/漫画/有声书一视同仁（有声书是目录型条目）；非 EPUB 无 OPF 兜底，「恢复」=撤销覆盖回落在线值。
- `core/publish.py` 是唯一仍写文件的模块（硬链接副本+原子替换）；`fileops.patch_epub_meta` 只服务测试与旧路径。
- **目录型条目（有声书一章一文件）同样出版**（第 29 期）：副本真目录、内部逐文件硬链接（`publish.link_tree_or_copy`）；形态判据=**名字带不带 `library.BOOK_EXTS` 扩展名**（不看 format、不 stat 磁盘）；副本名不带扩展名；源指纹=整树指纹（`source_sig._tree_files`）。
- 无值哨兵 `db.META_CLEAR="-"`（`_CLEARABLE` 全字段、有测试钉住）：空串=撤销覆盖；接口层 `null`=显式清空（写哨兵）。翻译三处一致：`db.get_effective_meta`/`metastore.effective`/`metastore.state`。

## Git / 环境 / 构建
- `.gitignore`：`.codebuddy/*`+`!.codebuddy/memory/`；忽略 `data/`、`*.db`、`novelforge/static/v2/`、`dist/`、`.playwright-cli/`。
- 认证走 GCM；已清 token 内嵌/insteadof 明文重写，勿再引入；推送失败先查认证/网络，别改 git config。
- Python 3.10+（**PEP 604 语法，系统 python3.9 不可用**）；Node v20/22（本机 nvm 有 v24，实测可用）；Docker daemon 可用；本机对外网络有限（推送/拉取偶需代理 `-c http.proxy=…`）。
- 行尾必须 LF（`.gitattributes` 锁）；CRLF 让容器 `sh /app/start.sh` 报 `set: Illegal option -` 反复重启。
- **macOS 工作区首次跑测试要自建环境**（工作区不含 venv）：`/Users/stromboid/.local/bin/python3.12 -m venv .venv` + `.venv/bin/pip install -r requirements-dev.txt`；再 `mkdir -p novelforge/static`（`StaticFiles(directory=…)` 目录不存在会在 **import 期**直接抛）。**别建 `static/v2/index.html`**，否则 `GET /` 不再是 503。
- ⚠️ `npm install` 会把 `frontend/package-lock.json` 里一批 optional 包的 `"dev": true` 删掉（纯 npm 版本噪声）⇒ **提交前 `git checkout -- frontend/package-lock.json`**。
- Windows 上 IDE 的 safe-delete shim 也拦 PowerShell `Remove-Item`（`SAFE_DELETE_BULK_GUARD_ERROR`，静默不删）⇒ 清临时产物用删除工具；`Out-File` 不带 `-Encoding` 同样被拦。

## 自动化测试（硬前提）
- 完全离线：`.venv/bin/python -m pytest`；dev 依赖在 `requirements-dev.txt`。**基线按环境取，别混引**：
  - **POSIX（macOS）475 例 / 0 failed**（第 34 期实测，连跑 6 轮全绿）；
  - win32 **404 例 / 0 failed**（第 33 期 4 轮全绿）；第 31/32 期的 346/388 例是旧数。
- ⚠️ **`pytest -q` 的汇总行抓不到**（PowerShell 与 zsh 同样，重定向后只剩 warnings summary）⇒ 一律用
  `--junitxml=/tmp/nf.xml` + Python 解析 `//testcase[failure|error]`（别用 `Select-Object -Last N`，也别拿 `[xml]` 解析）。
- **跑全量前确认 `novelforge/static` 存在**（缺它 import `server` 即 `ensure_dirs()` 失败）。
- **「长期稳定失败」不是 flaky，是产品 bug 的症状**（第 33 期）：真 flaky 不会次次都挂。报错不指向根因时（如只有 `calls == []`）要**逐层打印中间返回值**定位；修完**临时回退那一处**确认「恰好相关用例失败」。e2e 层同理做对照（改前 FAIL / 改后 PASS，唯一变量是那一处）。
  - 第 34 期两条实例：① 残留刮削 worker 越库写（修法见下）；② `_isbn_of` 把随机 UUID 当 ISBN（≈1/3 命中，修法见下）。定位手法都是「打印中间值 → 锁定漂移项」。
- 硬前提：①环境变量须在 import 业务模块前设（`config` 导入固化目录、`server` 导入即 `ensure_dirs()`）；②`db._conn`/`_db_path` 模块级缓存→隔离靠 `db.close()`。
- 碰库/DB 用例必须 `isolated`；接口用 `client`+`auth_headers`。假 EPUB（`b"EPUB"`）够扫描类；元数据写回/系列解析要真 EPUB（`epub_builder.build_epub`）。不测会外呼的接口。库 id 由名称派生（中文 slug 空→`lib-<sha1[:8]>`）；测试库根须在 `LIBRARY_SOURCE_DIR` 下；断言终态留余地。
  - ⚠️ **`isolated` 的「换库」= 改 `DATA_DIR` + `db.close()`**；只调 `db.close()+init()` 会重开**同一个文件**（写复现脚本时踩过，断言会失去意义）。
- 曾全量后半程 segfault→现由 `tests/conftest.py` 的 `_quiesce_background()`（`watcher.wait_pending`+`scrape.stop`）在 `isolated` 夹具 `db.close()` **之前**收尾。

## 后端约束与踩坑
- core 内引用配置一律 `from .. import config`；`import config` 被同名命名空间包劫持（py_compile 抓不到，启动才炸）。
- **`scrape._epoch` 世代号（第 34 期，停机收尾的保证）**：`stop(timeout)` 等不到 worker 真退出（单条处理不可中断：外呼/重试/写副本），故它**必定推进世代**；`process`/`_failed`/`_lost`/`verify` 的**每个落库点**都校验世代，作废即停手不落库（返回 `aborted`，条目留待下轮 `reset_running` 重来）。`gen=None` = 同步/接口调用，守卫完全透明。**新增 worker 落库点时必须一并加守卫**，否则又会「残留线程写到换过的那套库」。
- **ISBN 形状唯一真值源 = `metadata.isbn_digits`**（第 34 期）：10 位末位可 X / 13 位纯数字，允许分隔符与 `urn:isbn:`；**UUID 一律不认**。`library._isbn_of` 与 `fileops._set_isbn` 都调它 —— 原先两处各写了一遍 `[\dxX-]{10,17}` 子串判据，会把 EPUB 的随机 UUID 当 ISBN（界面冒假 ISBN + 完整度白送 10 分 + **覆盖掉书自己的标识符**）。有契约测试钉「全仓只剩一处判据」。
- 写磁盘只用 rename/move，删除移 `CACHE_DIR/recycle`；路径用 `library.root_of(b)/b["name"]`，禁 `config.OUTPUT_DIR/b["name"]`。
- 库根限 `LIBRARY_SOURCE_DIR`/`OUTPUT_DIR`/`DATA_DIR`（`safe_path`，建库时**强校验**，三者之外一律 400）；`book_id`=basename 派生+库维度化（`库$哈希`）。⚠️ 库存储根放在 `OUTPUT_DIR` 之下时，`default` 默认书库（root 即 `OUTPUT_DIR`、inplace、watch=1）会把这副本**再收一次** ⇒ 同一本书登记两条 —— 属预期行为，断言按 `library_id` 过滤。
- 新增库表列须同进 `db._LIBRARY_COLS`，否则 `update_library` 静默写不进。
- **给既有表加唯一约束要回头看 `db.remap_book_id`**（第 34 期书签踩到）：整体 `UPDATE` 撞唯一约束会抛异常并被外层 `except` 吞成「搬了 0 行」⇒ 关联数据静默丢失。做法是**逐行搬 + 冲突时弃墓碑**（`_remap_bookmarks`）；同时该表要进 `ORPHAN_TABLES`/`REMAP_TABLES`，有软删的还要进 `REMAP_PROBE_FILTER`（加 ` AND deleted_at=0`）。
- 统计接口（`core/stats.py`）：`overview.integrity` **原有 5 个计数键一个都不能少**；`largest`（体积榜）独立新键、与作者/系列榜共用 `top`，但**不要塞进 `_top`**；0 字节书如实上榜。**新序列只增键不删键**（既有 16 键有测试钉住），**必须跟随 `library_id`**（书库侧从 `bs` 算、阅读侧靠 `core/stats.py:97` 的 `ids` 集合过滤，`lid` 空时 `ids=None`=全库），**不新增扫描路径**。真名照代码：`weekdays`（不是 `weekday_minutes`）、`pages_by_format`（boxplot 五数概括）。
- ⚠️ **win32 上目录的 `st_size` 恒为 0**（NTFS）：任何「空文件」判据都必须**排除目录**（`if not p.is_dir() and p.stat().st_size == 0`）；第 33 期实测后果=win32 上有声书永不入库（Linux 目录 st_size 非 0 ⇒ 永不暴露）。要目录体积用 `watcher._sig()`。
- `write_epub` 前先 `mkdir`；批量端点注册在 `/api/books/{bid}` 之前、字面量路径在 `{param}` 之前；目录型条目用 `path.exists()` 不用 `is_file()`；模板替换先长后短。
- **版本唯一真值源=`server.APP_VERSION`，只由 `GET /health` 下发**：路由是 `@app.get("/health")`，**没有 `/api/health`**（白名单只含 `/health`+`/api/auth/login`+`/api/logout`，打 `/api/health` 会被拦成 401）。前端 `lib/api.ts` 的 `health()` 也走 `/health`。三处必须同口径。
- 共用锁嵌套用 `RLock`；`mark_processed`/`mark_recent` 走 `asyncio.to_thread`，watcher 独立 `_scan_lock`。
- **写进文档/注释的「文件:行号」收尾必须实测复核**（第 32 期核 71 处修 10；第 33 期核 312 处修 28）：方法是**并排打印「文档上下文 + 源码实际行」**再判定。两条硬教训：① **别记偏移量，只记当前真实行号**；② 自动核对的窗口 ±6 会吞掉偏 4 行的漂移、±2 假阳性约 80% ⇒ **脚本只能生成待核清单，不能判定**；区间引用只能按「它声称是什么」反向 grep。方法与四条局限见 `docs/bookorbit-capability-gap.md` §0.4。

## 配置分层（四层 + 每库覆盖）
- `DEFAULTS → config.yaml → settings.json → 环境变量`；库已知时 `生效值=每库覆写 ?? 全局`，落 `libraries.settings`（稀疏 JSON，键=全局点分路径）。
- `core/lib_settings.py`（`effective`/`config_for`/`apply_to`/`set_overrides`/`clear_overrides`/`schema()`）与 `features.SETTING_CAPS` 唯一真值源；接口 `GET/PUT/DELETE /api/libraries/{lid}/settings`（`?keys=` 按项恢复）。
- 覆盖项：`output.format`/`output.layout`、`watcher.recursive`/`watcher.copy_non_txt`、`metadata_fetch.*`、`naming.pattern`/`naming.scope`、`scrape.enabled`、`opds.expose`/`komga.expose`。
- 可见性=能力矩阵（库类型有没有）∩每库开关，判定只留一处（`_opds_visible_libraries`/`_ko_visible_libraries`）。「不可见」=「不存在」→直连 404。
- ⚠️ **能力键的判隐显轴要挑对**（第 34 期实测）：`library.hasFeature(k)` 判的是「侧栏**当前选着**哪个库」，只适合**全局导航项/设置页**这类入口；读者侧（如阅读器工具条）要判的是「**这本书**属于哪个库」。书签按钮曾因此被误藏（选着漫画库、读电子书）。`features` 里 `bookmarks` 键**只作能力矩阵的一行**，别拿它藏按钮。

## 前端栈与规范
- `frontend/`=Vue3 SFC+TS+Vite8+Tailwind v4+Pinia4+vue-router5(hash)。产物 `novelforge/static/v2/`，`/` 服务其 index.html（缺失 503）。勿往 `novelforge/static/` 加手写页。
- `bridge.css` 须 `@theme inline`；`main.css` 须 `@custom-variant dark (&:is(.dark *));`。
- 演示数据确定性常量禁 `Math.random()`；路由 path 全局唯一（同 path 两条被静默覆盖+侧栏重复 key）；`settingsNav`/router 注册表/侧栏三处与组件同批改。
- ⚠️ **设置页 `note` 是纯文本插值**（`SettingsPlaceholder.vue` 用 `{{ page.note }}`）⇒ 写 `**`、反引号、`<strong>` 都会**原样显示给用户**；有契约测试钉住（第 34 期当场揪出 3 处既有违规）。
- 工具页 `ToolsLayout.vue` 子页用 `onActivated`（非 `onMounted`）；改磁盘工具「先预览再应用」、删除移回收站。例外：页面内 `v-if` 子组件（如 `ScrapePanel`）需 `onMounted` 首载、`onActivated` 只刷新。
- 表格窄屏：宽屏 `<table class="hidden md:block">`+窄屏 `<ul class="md:hidden">`；纯装饰增强取不到就不设变量→CSS 整条失效→天然回退。
- **图表栈**：`echarts` + `vue-echarts`；`frontend/src/lib/charts.ts` 是**全站唯一**的注册/主题适配入口（组件里别各自 `use()`），按需注册 + 页面级动态 import；SVGRenderer + `oklchToHex()`（ECharts 不认 oklch）+ 幂等主题注册。**零外部请求**：不得 CDN、不得运行时拉地图/主题/字体。
- **外观偏好归属边界**：`stores/displayPrefs.ts`（Layout 页六项）**并入 `appearance` 块**随整套偏好走服务端（不新增第七块；应用远端值时**逐键挑**）；`stores/shelfPrefs.ts`（Behavior 三项 + 卡片信息）走 localStorage、**不进服务端同步**。写入经 `notifyPrefsChanged`、应用远端值走 `suppressing`。
- **侧栏导航契约**（`data/nav.ts` + `AppSidebar.vue`，有 `tests/test_nav_contract.py`）：① 动态计数项**不许写死数字**（`countSource: 'running' | 'browse'`，写死即假数据）；② 菜单 id 全局唯一；③ 组底部 `more` 行必须 **`label` + `to` + `countSource` 三件一起声明**（第 34 期统一：书库实体数 + 进书库管理页），别再用 `items.length` 当计数。
- **命名避让**：`/explore` =「探索发现」= **外部书源检索**（`POST /api/search`）；`/browse` =「实体总览」= **本地书目按元数据维度浏览**（零外网）。两者不能合并、不能互相借名；侧栏「浏览」是**分组标题**，新页 label 别叫「浏览」。
- **实体总览只有六个维度**（作者/系列/题材/出版社/语言/收藏）：本项目**只有 `tags`（OPF `dc:subject`）一个题材类字段**，上游的 genre/tag 两维在此会变成同一份数据列两遍 ⇒ 只做一个；演播者无实体（不做）。数据一律来自 `library.scopedBooks`（+`/api/books` 的 `collection_ids`），**不为它新增聚合接口**。

## 运行 / UI 验证
- 本地实例：`*_DIR→/tmp/<自建>/…`，`LIBRARY_SOURCE_DIR=…/libraries`，`AUTO_WATCH=false`，`uvicorn novelforge.server:app --port <新端口>`（**别 kill 别人的实例**：8791 常被旧代码实例占、8993 是用户 Docker 容器）。
- 登录接口字段是 `{"user","pin"}`（**不是** username/password）。全新 `DATA_DIR` 首次启动由 `db.init()` 按 `AUTH_USER`/`AUTH_PIN` 建默认账号（缺省 `admin/changeme`）。
- 建库接口要 **`root_path` 绝对路径**（`{name,type,mode,root_path}`，响应里是 `{"library": {...}}`），只给 `source_subdir` 会 400「库根必须是绝对路径」。
- Docker：`docker-compose.yml` 端口 **8992**；`docker-compose.test.yml` 挂 `./novelforge` 端口 **8993**；断网无法 `--build`。
- 构建：`cd frontend && npm run type-check && npm run build && npm run deploy`，核对 `/static/v2/assets/index-*.js` **实际内容**（HMR 源码≠服务端产物）。
- 浏览器冒烟：`npm i -g @playwright/cli` + `playwright-cli install-browser chromium`；注入 `nf_token`（`localstorage-set` + **`reload`**）；⚠️ **`snapshot` 现在直接打到 stdout**（`--filename` 可能不落盘），要重定向到 `/tmp` 自己读，别再落仓库根；⚠️ 换了产物要**带 `?nc=N` 缓存破坏参数 goto**（普通 `reload` 会用旧 bundle，会误判成「改动没生效」）。
- e2e 自查顺序：接口账目（curl）→ 界面文本（`eval innerText`）→ `console`（应为 0 errors）→ `network`（不应有非本地请求）。

## 上游取证与待办（跨会话）
- **`docs/bookorbit-module-inventory.md` 是第三条轴**（按上游**代码模块**对照，67 目录/33 feature，第 33 期产出）：只按页面对照会系统性漏掉「整块模块从未进视野」的能力。⚠️ **按模块名 grep 文档得出的覆盖结论是错的**（假阴性过半）——判定只能按语义找 + 落到 `文件:行`。第 34 期已把 §4.1「值得做」4 项全部落地（书签/重置阅读状态/跨实体浏览/侧栏计数），§4.2「有价值但不做」8 项**未改判**。
- 外部同步（Hardcover/Readwise/StoryGraph）**2026-09-19 拍板不做**；设置页维持未支持。Requests（求书）**已决策不做**（走数据驱动书源规则）。
- 参考仓库 `735876214/bookorbit` @ `main` @ `c292d6cc`，镜像 `%TEMP%\bookorbit-ref`；**取证扫符号别按文件名猜**；上游源码可取证（tree 对象本地已在，读 blob 走代理 `cat-file -p HEAD:<path>`，勿改持久 git 配置）。
- 统计页图表：上游 33 张，本项目 **30/33**；**其余 3 张已归档（不做且不补死 UI）**：`reading-source-distribution`（无 `source` 列）、`goal-trajectory`（无阅读目标）、`metadata-freshness-gauge`（价值低）。上游 3 图的 `BreakdownSelect`（format/source）**不造控件**。
- 批注/书签的**软删除既定语义**：`DELETE`=移垃圾桶（`deleted_at`），`purge` 才真删且只对垃圾桶内开放；一切读点必须 `WHERE deleted_at=0`（`annotation_counts`/`trashed_*`/`remap` 探测）。
- **批注 Hub 四分组**（月/书/颜色/来源，纯前端）+ **本地书签**已落地；**无数据源故不做**：`koreader`/`kobo` 批注导入、`needsReview`、`devices`、跨端降色（kosync 纯进度、无批注端点）。
- **文档过期是常态，改前先核验代码**：`docs/bookorbit-capability-gap.md` 的 §0.3 基线要**重取**（第 34 期：路由 262→270、表 27→28；表数要数**缩进 12 空格的**建表语句，直接 grep 会把迁移注释里的字样多算 2）；复核**不做整表翻转**（StatsView 双分区、Integrity 百分比、「孤儿封面目录」是刻意不同设计）。
- **判断「某能力有没有页面入口」要两头查**：只看配置文件会误判（`upload.max_bytes` 一例）⇒ **先查 `server.py` 的 `EDITABLE` 白名单，再查前端 `settingsFields.ts` 的字段定义**。
- ⚠️ `docs/roadmap-verification.md` 的「27/27 通过」里有 1 项不实（第 0 期「审计日志」把**计划**写成**实证**）⇒ **该文件正文结论不采信**（「核查方法」章节仍有价值）。
- ⚠️ **`account-activity.ts` = 管理端账号活跃度，不是阅读时间轴**，别当热力图依据；阅读会话模型看 `reading-session.ts` 的 `dailySummary{day,totalMinutes}[]`（含 `READING_SESSION_SOURCES` 分桶）。
- **阅读活动与成就**：`core/activity.py` + `GET /api/reading-activity`（`library_id` 空串=全库、未知库=空集合不 404）；热力图对齐上游 `dailySummary`；**无 `source` 列 ⇒ 无分设备热力图**（刻意分流）。成就对齐上游 5 分类中的 4 个（无 `devices`），**成就 key 不可改名**，只扩 `ACHIEVEMENTS` + `_metrics()`。
