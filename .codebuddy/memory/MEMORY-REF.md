# 长期记忆·参考手册（novel_dl_convert / NovelForge）

> `MEMORY.md` 只放**每次都要遵守的铁律**（体积受限、每次会话自动注入）；本文件放**按需查阅**的运行手册与跨会话待办。
> 需要「怎么在本机跑实例 / 怎么冒烟 / 上游对照到哪一步 / 还有什么待办」时读这里。
> 由 09-21 的压缩整理从 `MEMORY.md` 拆分而来，内容等价、未删减。

## 运行 / UI 验证
- 本地实例：`*_DIR→/tmp/<自建>/…`、`LIBRARY_SOURCE_DIR=…/libraries`、`AUTO_WATCH=false`、`.venv/bin/python -m uvicorn novelforge.server:app --port <新端口>`（**别 kill 别人的实例**：8791 常被旧代码实例占、8993 是用户 Docker 容器）。
- 登录字段是 `{"user","pin"}`（**不是** username/password）；全新 `DATA_DIR` 首启由 `db.init()` 按 `AUTH_USER`/`AUTH_PIN` 建默认账号（缺省 `admin/changeme`）。
- 建库接口收 **`source_dirs`（绝对路径 JSON 数组，第 41 期起）**；路径须在 `config.LIBRARY_SOURCE_ROOTS` 内（「就地引用」，跨根合法）。⚠️ 已无 `mode`/`root_path`/`source_subdir`。
- Docker：`docker-compose.yml` 是**自足的 NAS 单文件**（镜像 / 端口 **8992** / 挂载 `./input ./output ./config ./cookies ./cache ./data ./libraries` / `AUTH_*` / `AUTO_WATCH` / `WATCH_INTERVAL` 全部写字面量，**不读 `.env`**；`.env.example` 已删，`.env`/`.env.*` 仅留在 `.dockerignore` 里做卫生）。可选开关一律是**注释行**：`user: "1026:100"`、`EBOOK_CONVERT_BIN=`、`HTTP_PROXY/HTTPS_PROXY/NO_PROXY=`、`LIBRARY_SOURCE_DIRS1_NAME`/`DIRS2*`；`pull_policy: missing`（非 always）是刻意的。compose 文件仅保留 `docker-compose.yml` 与 `docker-compose.test.yml`，**不另设叠加件**（offline / update 等已移除，相关用法内联进主文件注释或文档）。⚠️ 原 `docker-compose.override.yml` 名仍被 Compose **自动合并**（静默改 8993 + 禁拉取），切勿恢复该文件名。`docker-compose.test.yml`（本地 build + 挂 `./novelforge` + 8993 + `./data-test`）同样自足；断网无法 `--build`。
- 构建：`cd frontend && npm run type-check && npm run build && npm run deploy`，核对 `/static/v2/assets/index-*.js` **实际内容**（HMR 源码≠服务端产物）。
- ⚠️ **本机 Node 由 nvm 管理（09-23 订正，取代此前「nvm 是空的、用 IDE 托管」的旧结论）**：nvm v2.0.0 位于
  `C:\Users\qingr\AppData\Local\Author Software\nvm`，已 `nvm install 24.19.0` + `nvm use 24.19.0`（设为默认），
  `node`/`npm` 现解析为 **v24.19.0 / 11.17.0**。winget 直装的 node 落在 WinGet 包目录、PATH 检索会跳过且被 nvm 抢注
  ⇒ **不能靠 winget 直装落地，须走 nvm**（那份 winget node 是无害残留）。`npm install` 等下载动作仍受本机网络限制（走系统代理）。
  ⚠️ `install_binary`（node）在本机会因 EPERM（rename 失败）装不上，**别在它上面反复试**。
  ⚠️ **跑 `npm run build` / `deploy` 前必须先 `$env:NODE_OPTIONS=''`** —— IDE 注入的 safe-delete shim 会拦 Vite 的
  `fs.rmSync`（清 outDir）与 `deploy.mjs` 的删除，报 `checkBulkDeleteGuard` / 「No active Node.js version」。
  同一条「先清 `NODE_OPTIONS`」对 pytest 也适用（此前几期的命令都带它，原因就在这里）。
- 浏览器冒烟：本机（win32）**无 chromium 也能跑** —— `playwright-cli open --browser=msedge`（走系统 Edge 通道，免下载；直接 `open` 会失败）；也可 `playwright-cli install-browser chromium`；注入 `nf_token`（`localstorage-set` + **必须再 `reload`**，否则首屏未授权请求 401、且应用会把刚注入的 token 清掉）；⚠️ `snapshot` 直接打到 stdout（`--filename` 可能不落盘）⇒ 重定向到 `/tmp` 自己读，别落仓库根；⚠️ 换了产物要**带 `?nc=N` goto**（普通 `reload` 用旧 bundle，会误判成「改动没生效」）。
- **`ui-smoke`（机器级三档冒烟，仓库内 `.codebuddy/tools/ui-smoke.ps1`）**：`open →（可选）登录 → 每档 set viewport → 量布局 → 截图`；`-CleanOnly` 清残留。
  ⚠️ **三个会让它静默挂死的坑（2026-10-03 已全部修进脚本）**：① `~/.agent-browser/default.pid|default.port` 残留指向**已死进程** ⇒ CLI 永久等待、不启新守护进程（`open` 零输出挂死）；② **PowerShell 管道 + 冷启动死锁**：首个 `open` spawn 的守护进程会**继承 PS 管道句柄** ⇒ `& agent-browser ... 2>&1 | ...` 永远等不到流结束（cmd/`.bat` 不受影响、守护进程**已热**时也正常）⇒ 首个 open 走临时 `.bat`，且**别用 `Start-Process -Wait`**（它等整棵进程树，守护进程不死就永不返回，要轮询日志的 `EXIT=`）；③ `eval` 传的 JS **只能用单引号**（双引号会被工具层吃掉 ⇒ `SyntaxError: Unexpected token '?'`），并放进 **here-string**。
  `-Widths` 用**空格**分隔（逗号会被 `.cmd` 转发吃掉）；默认 `-Profile ~/.agent-browser-profile/novelforge`（**存着登录态，别删那个目录**）。
  ⚠️ 360 档判据要**看 `off` 不能只看 `ovf`** —— 溢出常被内部 `overflow-x:auto` 容器吸收，`ovf` 仍是 false。
- e2e 自查顺序：接口账目（curl）→ 界面文本（`eval innerText`）→ `console`（0 errors）→ `network`（无非本地请求）。
- ⚠️ **本机（win32）跑测试的环境（第 81 期实测）**：仓库里**没有 `.venv`**；可用解释器是 `install_binary` 装的
  `C:\Users\qingr\.workbuddy\binaries\python\versions\3.14.3\python.exe`（先 `pip install -r requirements-dev.txt`），
  且**必须**先建出 `novelforge\static\` 目录（`server.py` 在 import 期 `StaticFiles(directory=…)` 会因目录不存在直接抛）；
  `static/v2` 已被 gitignore、**别往里塞手写页**。跑 `pytest` / `npm run build` / `deploy` 前一律 `$env:NODE_OPTIONS=''`。
- ⚠️ **回收目录是会话级共享的**（`fileops.recycle_dir()` 基于 `config.CACHE_DIR`，而 `isolated` 夹具**不切**它）：
  写「默认删库没掉文件 / 某次回收没发生」这类断言**只能做名字差集**（前后各拍一次快照），
  断言「目录里本来没有同名文件」会依赖用例执行顺序 —— 第 81 期先在 `test_api_smoke`、后在 `test_library_purge` 上各踩一次。

## 上游取证与待办（跨会话）
- **`docs/bookorbit/bookorbit-module-inventory.md` 是第三条轴**（按上游**代码模块**对照，67 目录/33 feature）：只按页面对照会系统性漏掉「整块模块从未进视野」的能力。⚠️ **按模块名 grep 文档得出的覆盖结论是错的**（假阴性过半）——判定只能按语义找 + 落到 `文件:行`。34 期落地 §4.1「值得做」4 项；35 期**改判** §4.2 里 3 项为做并落地（字段级锁 / 自定义字段 / 推荐打分）、36 期再落地 `book-move` ⇒ §4.2 真·不做 **4 项**（`embedding` / `position-converter` / `email` / `narrator`）。**42 期复核：上游 `main` 仍为 `c292d6cc`（无新提交）⇒ 转为「判定刷新 + 部分缺口」**：该文件第二节判定列 **10 处刷新**（含 3 处文档错误订正）、第六节新增部分缺口 14 项。
- 外部同步（Hardcover/Readwise/StoryGraph）**09-19 拍板不做**；Requests（求书）**已决策不做**（走数据驱动书源规则）。
- 参考仓库 `735876214/bookorbit` @ `main` @ `c292d6cc`（**42 期复核仍为此 commit —— 上游自 v2.10.0 起未推进**），镜像 `%TEMP%\bookorbit-ref`（`blob:none` 部分克隆、工作树未检出 ⇒ 用 `ls-tree`/`cat-file`）；**取证扫符号别按文件名猜**；读上游 blob 走代理 `cat-file -p HEAD:<path>`，勿改持久 git 配置。
- 统计页图表：上游 33 张，本项目 **30/33**；其余 3 张**已归档**（不做且不补死 UI）：`reading-source-distribution`（无 `source` 列）、`goal-trajectory`（无阅读目标）、`metadata-freshness-gauge`。上游的 `BreakdownSelect`（format/source）**不造控件**。
- 软删除的硬规则已写在 `MEMORY.md`（此处不再重复）；35 期 `custom_field_defs` 沿用同一语义。最容易漏的三个读点：`annotation_counts`、`trashed_*`、`remap` 探测。
- **批注 Hub 四分组**（月/书/颜色/来源，纯前端）+ **本地书签**已落地；**无数据源故不做**：`koreader`/`kobo` 批注导入、`needsReview`、`devices`、跨端降色（kosync 纯进度、无批注端点）。
- **文档过期是常态，改前先核验代码**：capability-gap 的 §0.3 基线要**重取**（表数要数**缩进 12 空格的**建表语句，直接 grep 会把迁移注释里的字样多算 2）；复核**不做整表翻转**（StatsView 双分区、Integrity 百分比、「孤儿封面目录」是刻意不同设计）。
- ⚠️ `docs/roadmap-verification.md` 的「27/27 通过」里有 1 项不实（把**计划**写成**实证**）⇒ **正文结论不采信**（「核查方法」章节仍可用）。
- ⚠️ **`account-activity.ts` = 管理端账号活跃度，不是阅读时间轴**，别当热力图依据；阅读会话模型看 `reading-session.ts` 的 `dailySummary{day,totalMinutes}[]`（含 `READING_SESSION_SOURCES` 分桶）。
- **阅读活动与成就**：`core/activity.py` + `GET /api/reading-activity`（`library_id` 空串=全库、未知库=空集合不 404）；热力图对齐上游 `dailySummary`；**无 `source` 列 ⇒ 无分设备热力图**（刻意分流）。成就对齐上游 5 分类中的 4 个（无 `devices`），**成就 key 不可改名**，只扩 `ACHIEVEMENTS` + `_metrics()`。

## 域细节（由 09-21 压缩从 `MEMORY.md` 外移；动到这些领域前先读本节）

### 环境与构建
- `.gitignore`：`.codebuddy/*` + `!.codebuddy/memory/`；忽略 `data/`、`*.db`、`novelforge/static/v2/`、`dist/`、`.playwright-cli/`。
- macOS 首次跑测试：`/Users/stromboid/.local/bin/python3.12 -m venv .venv` → `.venv/bin/pip install -r requirements-dev.txt` → **再** `mkdir -p novelforge/static`（缺目录在 **import 期**就抛）。**别建 `static/v2/index.html`**，否则 `GET /` 不再是 503。
- ⚠️ `npm install` 会删掉 `frontend/package-lock.json` 里一批 optional 的 `"dev": true`（纯噪声）。**规则（第 39 期修订，取代此前「提交前一律 `git checkout --`」）**：不再无脑还原 —— 那会把**本期真要加的新依赖一起丢掉**（第 39 期加 vitest 三件套时就会）。改为：提交前**逐段 `git diff frontend/package-lock.json`**，只放行「本期新增依赖引入的改动」，其余 `"dev": true` 增减照旧还原。
- Windows：IDE safe-delete shim 拦 PowerShell `Remove-Item`（静默不删）⇒ 清临时产物用删除工具；`Out-File` 不带 `-Encoding` 同样被拦。
- **发布自动化（第 79 期）**：`.github/workflows/release.yml` 一个 workflow 两个触发 —— 推 `main` 时读仓库根 `VERSION`，
  `v<版本>` tag 不存在就**自动打 tag + 建 Release**（已存在则跳过）；人工推 `v*` tag 也走它（`gh release view` 命中则跳过）。
  notes 的唯一实现 = `python3 -X utf8 -m novelforge.core.changelog <版本>`（与应用内「新功能」页同源；缺段以 1 退出）。
  ⚠️ 打 tag 与建 Release **必须同 job**：`GITHUB_TOKEN` 推的 tag 不会再触发其它 workflow。
  ⇒ **改 `VERSION` 必须同批补 `CHANGELOG.md` 段**，否则发布在 CI 里失败（不会发空 notes 的 Release）。
  镜像另有一条链：`docker-image.yml` 在推 `main` 时构建并推 `ghcr.io/…:latest`（与 tag 无关）。

### 命名与出版细节
- `fileops.fill_pattern` 9 个占位符、**先长后短**；`{index}`=系列卷号（两位补零，非流水号）；`{ext}` 已带扩展名 ⇒ **只有模式以 `{ext}` 收尾时才摘尾扩展名**。
- 「预览==落盘」共用 `publish.relpath_for`+`rel_verdict`（REL_REUSE/REBUILD/DECLINE）；仍会改 basename 的只剩 `apply_conflict_rename`/`apply_komga_layout`（成对调 `db.remap_book_id`）。
- 目录型条目的源指纹=`source_sig._tree_files`。

### 后端细节（统计 / 配置覆盖 / 页面入口）
- `core/stats.py`：`overview.integrity` 原有 5 个计数键一个不能少；`largest` 独立新键、与作者/系列榜共用 `top` 但**不要塞进 `_top`**；既有 **16 键有测试钉住**。
- 可覆盖项（每库）：`output.format`/`output.layout`、`watcher.recursive`/`watcher.copy_non_txt`、`metadata_fetch.*`、`naming.pattern`/`naming.scope`、`scrape.enabled`、`opds.expose`/`komga.expose`；`core/lib_settings.py` 的 `effective`/`config_for`/`apply_to`/`set_overrides`/`clear_overrides`/`schema()`。
- 可见性判定的唯一落点是 `_opds_visible_libraries`/`_ko_visible_libraries`（「不可见」=「不存在」→ 直连 404）。
- ⚠️ **判断「某能力有没有页面入口」要两头查**：先查 `server.py` 的 `EDITABLE` 白名单，再查前端 `settingsFields.ts` 的字段定义（只看配置文件会误判，`upload.max_bytes` 是一例）。
- **`sqlite3.InterfaceError: bad parameter or other API misuse` 的定位法**（第 39 期查了半天，记下来省下次）：它就是 SQLite C 库 `sqlite3_errmsg` 里 **`SQLITE_MISUSE` 的文本** —— **不在** `_sqlite3.pyd` 里（去二进制里 `strings` 会扑空，实测偏移 -1）。它**与常见的 sqlite3 误用无关**：cursor 关后用 / 连接关后用 / 参数错 / `row_factory` 非 callable 产出的都是 `ProgrammingError`/`TypeError`，**没有一种能造出 `InterfaceError`**。本仓实测的唯一成因是「**同一连接上的无锁并发访问**」（`commit()` 重置语句那条假设已被实验证伪：三种操作各自对撞读线程，全 0 异常）。想抓抛出点用 `traceback.format_exc()`（Python 3.11+ 带 `^^^^` 精细定位，链式调用也能指出是哪一段）—— `format_stack()` 拿不到，异常已抛出栈。

### 前端细节
- **前端单测（第 39 期起）**：`cd frontend && npm run test:unit`（= `vitest run`）。脚本名**刻意不叫 `test`** —— 本仓库「测试」历来专指 pytest 那套。配置**不另起 `vitest.config.ts`**（`vite.config.ts` 的 `@` alias 是唯一真值源），就加在既有 `defineConfig` 的 `test` 块里；**不开 `globals`**（spec 在 `src/**` 下会被 `vue-tsc --build` 一并检查，显式 `import { describe, it, expect } from 'vitest'` 即可）。
  - ⚠️ **前端用例数独立计数**，**不得并入 pytest 基线**（两套跑法、两套前提）。
  - ⚠️ 要伪造时钟用 `vi.useFakeTimers({ toFake: ['Date'] })` —— **只伪造 `Date`**。全套假时钟会让 `flushPromises()` 自己挂住（它内部就靠一个 `setTimeout` 落地）。
  - ⚠️ happy-dom 没实现 `scrollIntoView`，挂载阅读器类组件前先 `Element.prototype.scrollIntoView = vi.fn()`，否则滚到章节时抛。
  - 挂载 harness 的坑：`vi.mock('@/lib/api')` 要**一次给齐所有**被调接口 —— 少一个就在 `onMounted` 里抛，异常被当成「加载失败」渲染成空态，用例最后以「找不到按钮」报错，**离真正原因很远**。
- `bridge.css` 须 `@theme inline`；`main.css` 须 `@custom-variant dark (&:is(.dark *));`。
- ⚠️ **设置页 `note` 是纯文本插值**（`SettingsPlaceholder.vue` 的 `{{ page.note }}`）⇒ 写 `**`、反引号、`<strong>` 都会**原样显示给用户**；有契约测试钉住。
- 工具页 `ToolsLayout.vue` 子页用 `onActivated`（非 `onMounted`）；改磁盘工具「先预览再应用」、删除移回收站。例外：页面内 `v-if` 子组件（如 `ScrapePanel`）需 `onMounted` 首载、`onActivated` 只刷新。
- 窄屏双写法：宽屏 `<table class="hidden md:block">` + 窄屏 `<ul class="md:hidden">`；纯装饰增强取不到就不设变量 ⇒ CSS 整条失效 ⇒ 天然回退。
- **图表栈**：`echarts`+`vue-echarts`；`frontend/src/lib/charts.ts` 是**全站唯一**的注册/主题适配入口（组件里别各自 `use()`），按需注册 + 页面级动态 import；SVGRenderer + `oklchToHex()`（ECharts 不认 oklch）+ 幂等主题注册。
- **外观偏好归属边界**：`stores/displayPrefs.ts`（Layout 页六项）**并入 `appearance` 块**随整套偏好走服务端；`stores/shelfPrefs.ts` **第 43 期起 `collapseSeries` 进第 7 块 `shelf`**（其余视图/排序/缩略图点击/筛选默认展开 + 卡片信息仍走 localStorage、不进同步）；写入经 `notifyPrefsChanged`、应用远端值走 `suppressing` 逐键挑。
- **侧栏导航契约**（`data/nav.ts` + `AppSidebar.vue`，有 `tests/test_nav_contract.py`）：① 动态计数项**不许写死数字**（`countSource: 'running' | 'browse'`，写死即假数据）；② 菜单 id 全局唯一；③ 组底部 `more` 行必须 **`label` + `to` + `countSource` 三件一起声明**，别再用 `items.length` 当计数。
- **命名避让**：`/explore`=「探索发现」=**外部书源检索**（`POST /api/search`）；`/browse`=「实体总览」=**本地书目按元数据维度浏览**（零外网）。两者不能合并、不能互相借名；侧栏「浏览」是**分组标题**，新页 label 别叫「浏览」。
- **实体总览只有六个维度**（作者/系列/题材/出版社/语言/收藏）：本项目**只有 `tags`（OPF `dc:subject`）一个题材类字段** ⇒ 上游 genre/tag 两维在此会变成同一份数据列两遍 ⇒ 只做一个；演播者无实体（不做）。数据一律来自 `library.scopedBooks`（+`/api/books` 的 `collection_ids`），**不为它新增聚合接口**。

### 文档锚点核验（工具口径）
- 工具=`tests/check_doc_anchors.py`（**非 `test_` 前缀 ⇒ pytest 不收集**）：`--drift`/`--suggest`/`--todo`/`--file`；方法与四条局限见 `docs/bookorbit/bookorbit-capability-gap.md` §0.4（核法与局限）+ §0.5（工具固化）。
- 自动核对的 ±6 窗口会吞掉偏 4 行的漂移、±2 假阳性约 80% ⇒ **脚本只能生成待核清单、不能判定**；区间引用只能按「它声称是什么」反向 grep。
- 追加一类误报：**「文档写 `x.py:1`，真值 `:2`」这种更正句式**前半截是记录旧错，不该按漂移判。
- ⚠️ **同期内「先写锚点、后改代码」也会让锚点作废**（第 34 期四笔代码落在最后、文档先行）⇒ 收尾必须按「当前真实行号」重测，**不记偏移量**。
- 各期核验规模（判「这算多还是少」的参照）：32 期核 71 修 10、33 期核 312 修 28、35 期核 706 修 37、36 期核 719 修 7、39 期核 11 疑似漂移全修（12 处）、**40 期核 768 处 / 疑似漂移 17 全修（29 处，含同批行人工捞出的 15 处）**。39 期那批由 `core/db.py` 净增 102 行引起、40 期由同一文件的 6 个 hunk（+38/−7）引起，再次印证「动了锚点密集文件就顺手重核那一份」。
  ⚠️ **核验规模那个数是「修前」口径，修完会变**（40 期 768 → 767，因为 1 处写错的锚点被改成了「第 N 行」的非锚点表述）；**符号命中数会随当期实施记录一起长**（40 期复校完成时 47 → 追完记录后 56）。引用这两个数时要说清是哪一刻的。
  ⚠️ **40 期摸到的漏报面：工具只核对「`` `路径:行号` `` **后面**跟着反引号符号名」的锚点** ——符号写在锚点**之前**的（「… `books.by_format`（`core/stats.py:635`）」）**根本不进核对**，那一批 15 处漂移工具**一条都没报**，全靠人工在同一批行上捞。⇒ 判据「0 硬错 + 0 漂移」**只能是下限**。
  ⚠️ **「不记偏移量」的实证（40 期）**：同一期 `core/db.py` 的 hunk 合计 +38/−7，但各锚点位移互不相同 —— 22 / 22 / 22 / 23 / **31** 行都有（只有落在该锚点**之前**的 hunk 才影响它）。
  ⚠️ **被动产生的漂移**：写「第 40 期实施记录」时引用了旧锚点做例子，工具**立刻**把它算成一条新漂移 ⇒ 记录里引旧行号不要写成 `` `path:行号` `` 的形式，写「第 N 行」。历史实施记录里的旧行号（roadmap `:859` / `:879` / `:1416`）**一律不动** —— 改它等于篡改历史。

---

## 出版 / 元数据细节（09-23 压缩自 `MEMORY.md`；动这些领域前先读）

- 硬链接副本内嵌元数据会变独立 inode ⇒ **不得宣称省空间**。
- **目录型条目**（有声书一章一文件）同样出版：副本是**真目录 + 内部逐文件硬链接**；形态判据 = **名字带不带 `library.BOOK_EXTS` 扩展名**（不看 `format`、不 stat 磁盘）；**副本名不带扩展名**。
- 无值哨兵 `db.META_CLEAR="-"`（`_CLEARABLE` 全字段、有测试）的三处翻译须一致：`db.get_effective_meta` / `metastore.effective` / `metastore.state`。
- **抓取三道正交闸**：①字段策略 `metadata_fetch.fields[key] ∈ {overwrite(默认)/fill_only/skip}`（全局 + 每库）②`meta_locks` 显式字段锁（**只挡抓取、不挡手工编辑**；解锁后抓取重新接管）③「改过就不动」（`field in overrides` 隐式）；**自定义字段默认值同受此三闸**。
- 相似书五路权重：`0.5·词袋余弦 + 0.1·同作者 + 0.25·题材 Jaccard + 0.1·同系列 + 0.05·评分接近度`；**任一方未评分时那一路不进分母**（不当 0 分）；词袋**简介不进**；`limit`≤25、详情页默认 6 可展开；0 分不返回；`SimilarBook.score`=0–1（前端不显示）；另有「实质重合」门（至少同作者 / 同题材 / 同系列之一才进候选）。
- 作者排序名派生 `authors.derive_sort_name`：拉丁两名 →「姓, 名」、多名带小词表（`Le Guin`）、**CJK 原样返回 ⇒ 跳过**（填了等于没填）。
- 阅读尝试（轮次）：一轮 =「开始读 → 读完」，读完再开始 = 新一轮（`round` 递增）；⚠️ 自动维护挂 `db.set_status`（进 reading 开轮 / finished 收尾；**搁置·弃读不动轮次**）；`reset_reading_state` **四清**（删 `reading_sessions` + `progress` + `reading_status` + `reading_attempts`，**不动批注/书签/评分/文件**）。
- **remap 四处清单**：`ORPHAN_TABLES` / `REMAP_TABLES` / 有软删进 `REMAP_PROBE_FILTER` / 含库相关列进 `REMAP_EXPLICIT_TABLES`（唯一成员 `scrape_items`）。整体 `UPDATE` 撞唯一约束会被外层 `except` 吞成「搬 0 行」⇒ 必须**逐行搬 + 冲突取舍**。
- `migrate.execute`/`rollback` 不按 `direction` 分支：自动归库(`move`)与用户移动(`bookmove`)共用 `_after_bookmove`/`_after_bookmove_back`，回程对称；`DIR_AUTO="move"` 字面量**不能改**；`server.py` 拒用 bookmove 执行自动归库批次那两处**保留**；反查所属库用 `_lib_id_of_path`（取**最长**匹配）。
- ⚠️ **`db` 访问只走 `db._connect()`**：返回持 `_lock` 的代理 `db._Conn`（非裸 `sqlite3.Connection`）；`_lock` 是 **RLock**（非重入会自锁死）；「锁内写 + 裸读」实测全 `InterfaceError`、裸读 + `close()` 全段错误；`db._Result` 接口面收窄（execute/executemany/executescript/commit/rollback + 标量/fetchone/fetchall/迭代），新增游标属性要补。契约 `tests/test_db_concurrency_contract.py`。`db.close()` 生产无人调，但「锁内写 + 裸读」生产可达；旧代理线程拿 `ProgrammingError` 是**真错误、别吞**。
- ⚠️ **win32 目录 `st_size` 恒 0**：「空文件」判据须 `if not p.is_dir() and p.stat().st_size==0`；目录体积用 `watcher._sig()`。

---

## 逐期铁律原文（第 53–61 期；2026-09-28 由 `MEMORY.md` 下沉，内容未删减）

> `MEMORY.md` 只留「每次都要遵守」的跨期铁律与一页索引；本节的逐期细节按需查阅（当期实施记录另见 `docs/roadmap-gaps-remaining.md`）。
>
> ⚠️ **口径修订（第 80 期，2026-09-29）**：下文多处把「零依赖 / 零外部请求」当作**取舍理由**（第 53 期音频标签「零依赖」、第 54 期 embedding「绝不引远程 API」等）。这些**理由仍然成立**（省事 / 隐私 / 内网可用），但**已不再是硬约束** —— 允许**显式、可关、失败降级**地引入外部依赖与出网，新增依赖须在 `requirements*.txt` / `frontend/package.json` 显式声明并说明理由（见 `AGENTS.md` 第 1 节）。下面的原文保留不改，视为历史记录。

### 演播者实体（第 53 期，2026-09-24）
- `books.narrators`（列表列，与 `tags` 同构）+ `narrators` 实体表（`sort_name`/`sort_name_local` 两列分列，镜像 `authors`；**派生/回填只写 `sort_name`**）；扫描期 `core/audio_meta.py` **零依赖**解析音频标签落盘（m4b/mp3/m4a/opus/ogg/flac），解析失败降级空、绝不挡入库；接口 `/api/narrators*` 形态对齐 authors；命名 token `{narrators}` 与 `RENAME_TOKENS` 契约钉死；**刻意差异**：不新增浏览维度、无头像。

### 语义向量与精确位置（第 54 期，2026-09-26）
- **`core/embed.py`**：相似书余弦一路优先语义向量 —— 默认 **LSA**（TF-IDF+SVD，纯 numpy **离线零下载**；词表按 df 封顶并**显式定序**，否则两次重算余弦漂移 ⇒ 推荐列表跳）；可选本地 transformer（`CACHE_DIR/embedding-model` + 自备依赖）；**绝不引远程 embedding API**。`book_embeddings` 表（float32 BLOB + `model_tag`）进 REMAP/ORPHAN；读端 `load_vectors` **只认当前 tag**（旧 tag 不混排）；重算=全量批式（`POST /api/embeddings/recompute` + `/similar` 缺向量·扫描完成两条自愈钩子，单飞闸 `threading.Event`+600s 节流，线程收尾走 `server.wait_embed_refresh` 进 conftest）。
- **`recommend.similar_books(…, vectors=)`**：两书都有向量走语义余弦、缺向量**逐对回落**词袋；「实质重合」门不动 —— 向量管排得好不好、门管该不该出现；出参结构不变。
- **`core/epub_cfi.py` = 位置换算唯一真值源**：CFI 生成/解析 + CFI→XPointer 兼容层；`xml.etree` 解析（坏书一律安全回落空 CFI）；⚠️ **字符偏移 = 渲染正文 textContent 坐标系**（后端 ET text/tail 模拟 DOM childNodes 数步序，前端 `contentRef.textContent.length`，两侧同尺度才能往返）；`progress.cfi` **只由 NF 阅读器写入，其它来源写进度一律清空 cfi**（防「章已变、CFI 挂旧章」）；进度端点 `offset` 进 / `cfi`+`offset` 出（前端不在 JS 里解析 CFI）；恢复换算不了必须回落「章+全书百分比」。
- **KOReader 刻意保守**：`from_nf` 下发仍为**章首 XPointer**（kosync 只认 XPointer，真 CFI 会破坏解析，章内精度由 percentage 兜底）；`to_nf` 仅兼容识别 `epubcfi` 取章序号（crengine 字符坐标不同尺度，不换算不落库）；kobo span / kepub DOM 仍不做；Kobo 同步仍不做（2026-09-17 决策）。
- 依赖：`requirements.txt` 新增 `numpy>=1.26`。文档：module-inventory §2/§4.2/§9 两行改判（embedding 已覆盖；position-converter 已覆盖·子集）+ 第 54 期记录；roadmap 同步。

### 第 55 期铁律（就地建库 / TXT 阅读 / 分章真值源）
- **「新增书库」= 就地弹窗**：全局单实例 `frontend/src/stores/libraryWizard.ts` + App.vue 挂**一份** `<LibraryWizard>`；各入口调 `wizard.show()`（`created()` 负责刷新全局书库实体 + 宿主回调）。⚠️ **禁再在别处挂 LibraryWizard 或另建第二份数据拉取**（z-50 浮层叠两层关不掉；`?new=1` 经 store 仍可用）。「管理」语义入口（书架顶栏 / 侧栏「更多」）仍跳 `/settings/libraries`。
- **分章唯一真值源 = `core/detect.py`**（出版管线 / 书源 / TXT 阅读共用；契约 `tests/test_detect_chapters.py`）。⚠️ 两条现状口径别当 bug 顺手改（会同时改出版成品目录）：① 首个边界前的内容（书名/作者）**被丢弃**；② 正则是**非锚定**的 —— 正文里出现「第 N 章」字样也会被当边界。
- **TXT 阅读 = 派生 EPUB 优先、原生分章兜底**（`core/txtcache.py`）：派生件落 `CACHE_DIR/txt-epub/<book_id>/`（**派生缓存**：不进书库、不落成品目录）；形态由**源文件指纹**锁定（源没变不换路线，防章节号漂移让批注跳错章）；失败写 state.json 标记。⚠️ 派生 EPUB 必须 `epub_builder.build_epub(..., nav=False)`（spine 不含 nav 页 ⇒ 章节 index 0 基，与原生兜底索引空间对齐）；`build_epub` 的 `nav` 参数默认 `True`，改动它前先看全部既有调用方。
- 新增端点/接口形状不变原则：TXT 阅读**前端零改动**（后端把两条路线归一成 `chapters` + `/chapter/{index}` 同一形状）；`BookDetailView.canRead` 放行 TXT（需有章节）。
- 设置页三处同步点、契约测试的「源码字符串断言」：改行为时**同步改断言**并在测试里写清新口径（第 55 期改了 `manageLibs`→`createLib`、`cta.to` 可选两处）。

### 第 56 期铁律（多设备进度提示 / 偏好同步感知）
- **进度同步 = 轮询 + 提示，绝不上 SSE、绝不静默挪阅读位置**：`ReaderView` 用服务端 `updated_at` 当基准（载入读到的 + PUT 回带的 `ownWriteAt`），8s 轮询且「时间戳更新 >1s **且位置确实不同**」才渲染提示条；**只有用户点「跳过去」才 `loadChapter`**（随即写回本机位置避免重复提示）。`hidden` 不轮询；卸载停轮询；提示条不碰 `html`/`contentRef`（不重排正文）。
- **`updated_at` 是公开契约**：`GET/PUT /api/books/{bid}/progress` 都带；⚠️ **没有进度行时不得给**（造 0 当基准会让首次进阅读器就弹提示）。任何写进度的来源（KOReader/Komga/完成标记）都经 `db.set_progress` ⇒ 自动刷新时间戳（语义：也算「别处读过」）。
- **偏好同步感知**：设备行 `last_seen` 就是变更信号（勿另建表/列）；判定**必须走纯函数** `prefsSyncDecision`（noop / apply-remote / conflict，1s 容差）；`conflict`（本机有未推送改动）**只提示不覆盖**（顶栏胶囊 → 设置页显式选）。`boot()` 的启动裁决语义不变（启动那刻 pending⇒本机为准并推）。
- 前端 spec 假时钟约定：伪造计时器时**保留真 `setTimeout`**（只 fake `setInterval`/`clearInterval`/`Date`），否则 `flushPromises()` 自挂。

### 前端约定（第 57 期补充，通用）
- **设置页真实路由 = `#/settings/<page.path>`**（如 `#/settings/metadata/providers`），**不带分组段** —— 分组只是侧栏视觉分组。曾误写 `#/settings/library/metadata/providers` → 「未知路由」。
- **目录/列表类数据拉取失败必须显式**：不许 `catch { /* 静默 */ }` 让块变空（用户看到「已启用：2/0 + 没有匹配的提供商」会一头雾水）。做法：① 尽量**回落旧接口**保住可用性；② 把原因写在界面上 + 「重试」按钮；③ 计数类显示要做兜底，别出现 `N/0`；④ 空态区分「加载中 / 无匹配 / 空」。
- **前端改动后必须 `type-check` + `test:unit` + `build` + `deploy`**（部署产物落 `novelforge/static/v2`，不入库）；**后端改动必须重启进程才生效**（用户遇到的「空列表」根因就是后端没重启）→ 交付说明里要写清重启/重建镜像这一步。
- 浏览器冒烟用 `playwright-cli open --browser=msedge <url>`（本机没装 Chrome，Chromium 会报 distribution not found）；用 `CONFIG_DIR/INPUT_DIR/OUTPUT_DIR` 指向 `.codebuddy/tmp-*` 隔离，`admin/changeme` 登录；`route "**/api/xxx" --status=404` 可复现旧后端场景。
- ⚠️ **注入 token 不稳，直接走登录表单更可靠**（第 66 期实测：`localstorage-set nf_token` + 重载仍停在登录门禁；用表单填 `admin/changeme` 点「进入」即通）。

### 第 60 期铁律（按语种重排来源顺序）
- 规则：`专精本语种(0) → 多语种通吃(1) → 专精别的语种(2)`，**档内保持用户设的顺序**（`sorted` 稳定）；**只排序、不筛源**（任何启用的家都仍会被查到）；**未知语种不重排**。亲和表 `metasources.LANG_AFFINITY` + `LANG_BROAD`，契约 `∪ == SOURCES`（新增一家源必须显式表态）。
- ⚠️ **占位语种陷阱**：`_lang_of("未知")` 返回非空串（它服务于「写进书目时归一」），重排前必须再拦一道 `LANG_UNKNOWN`，否则会拿占位符当真实语种、把所有源判成「专精别的语种」→ 凭一个占位值瞎重排。
- 调用点三处必须同口径：`metafetch.plan`（**逐本**算）、`metafetch.online_candidate`（单本）、`series_meta`（系列无自身语种 → 成员书投票，平票取先出现者以保证可复现）。`plan` 每本回传 `sources_order`，界面据此解释「为什么先问它」。
- 配置键新增要动三处：`config.DEFAULTS`、`server.EDITABLE`（`GET /api/config` 的 metadata_fetch 走掩码函数整体回传，不用手列），前端 `data/settingsFields.ts` 的 `SECTION_KEYS`（metadata 段已有 → 无需改）。
- **前端自动化踩坑（差点误报产品 bug）**：用 DOM 遍历点某个设置行里的按钮时，向上找「含 button 的容器」会拿到祖先容器、点到**邻近按钮**，现象是「标签翻了但值没落库」——看着像产品 bug。正确定位：`filter(元素包含该行标题 && 元素内恰好 1 个 button)` 取**最深**那个。另外 SPA 同路由 `page.goto` 不会重挂组件，草稿会串场，验证开关前要带 `?fresh=timestamp` 强制重挂。

### 第 61 期铁律（阅读器体验八项）
- **翻页模式几何（修过一次又错一次的坑）**：正文 `width` 是 **border-box**（含内边距）⇒ 要设**整屏宽**，内容盒才等于「可用宽」；栏宽 = 可用宽/栏数；**位移步长 = 栏宽 + 栏距**（不是容器宽 + 栏距）。把 width 设成「可用宽」会让内容盒再窄两个内边距，右缘照旧露下一栏。
- **目录跳转按 `flat` 位置、不回查后端 index**；**请求序号守卫**必须有（连点目录时慢响应后到会覆盖后跳的那一章 = 「跳错位置」真因）。无章节序号的目录项**不要渲染**成死项；切章要有加载反馈（否则用户认为「点了没反应」）。
- **进度实时 = 就地回写 store**（`library.patchProgress`），四个阅读器都要调；不重拉整库。切后台/关页面要补发去抖里未发出的那一次（visibilitychange 复用会话的、另加 pagehide）。
- **自动续章的「无缝」全靠预取**：`chapterCache` 先把下一章取好 ⇒ 切换时不发请求、不闪加载。**先确保缓存再切换**，反过来写就退化成「自动点下一章按钮」，空档一个不少。翻页模式的末页判定是另一条路径（本期未改）。
- **通知合并（尾随去抖）必然要延迟落盘**：窗口内不写文件 ⇒ 必须 `atexit` 兜底 flush；且**测试默认关闭合并**（`tests/conftest.py` autouse），否则会破坏大批既有用例「写一条即落一条」的前提。合并键 = 动作 + 结果 + 主体。
- **漫画库里的 PDF 按漫画形态读**：pdf.js 逐页渲染成 blob 图，交回同一套 `<img>` 漫画布局（单/双页、右到左、无间隙连续自动适用），**不要新写一份 PDF 布局**；`comicPrefs.pdfMode` 决定默认阅读器，两个阅读器互留切换入口并共用页进度。
- **性能优化先量化**：本项目 3 本书的小库下全链路仅 59/66/119ms、接口 3–10ms —— 没有指标前不许「凭感觉优化」。
- **验证技巧**：滚轮验证要把鼠标移到**视口中心**（用元素 boundingBox 会指到视口外 ⇒ 滚轮根本没落在阅读区）；后端改完必须**重启 uvicorn** 才生效；多实例共用同一 CONFIG_DIR 会共享日志目录 ⇒ 验证合并/日志类行为要换全新 CONFIG_DIR。

### 第 59 期铁律（14 家真联网体检）
- **体检 = 只读 + 分类 + 首条结果**：`metasources.health_check()`（并发 4、单家超时 12s）；`POST /api/metadata/health` 跑一次、`GET` 回上次（**进程内缓存**，重启即空，如实回「尚未体检过」）。**分类是给用户的动作指南**：限流=等一会/填 Key、拒绝=填 Key、反爬拦截=降频率/带 Cookie、重定向=被拦到验证页、`empty`=站点可能改版、`http`=接口报错。不要退化成「可用/不可用」。
- **样本按家给**（`HEALTH_SAMPLES`）：地区性目录用当地书名（Aladin `채식주의자` / Lubimyczytac `Wiedźmin` / RanobeDB `狼と香辛料`），否则**好家会被误报成无结果**。
- **必须回「命中的第一条」**：只报状态会漏掉「可用但答非所问」——Amazon 第一版抓到 `Aug 25, 2020` 却显示可用。**错字段比缺字段更糟**。
- 真实站点事实（本机实测，别再当 bug 修）：Google Books 匿名 **429**、Kobo **403**、Goodreads **302**（反爬验证页）、Audible **400**、AudNexus SSL 中断、Libro.fm **HTTP 202 + 挑战页**（`_get_text` 已判 202 与验证码页 → `blocked`）、Open Library 偶发 SSL 握手超时。Amazon 书名在**结果项 `<h2>`** 里；Lubimyczytac 用 `book-card__title/__author`（`authorAllBooks__*` 早已废弃）。
- `_strip_html` 的实体还原用标准库 `html.unescape`：手写对照表会漏（Amazon 书名有 `&#x27;`）。
- 写「只读」类断言要**前后对比**（`before == after`），别断言绝对值为空/为假 —— 同进程里别的用例可能已改过同一份隔离配置，那样写会变成依赖执行顺序的假失败。

### 第 58 期铁律（跨源字段级合并）
- **合并有门槛**：只有 `score >= max(0.7, 0.9×最佳分)` 的候选才参与（`metafetch.MERGE_MIN_SCORE/MERGE_RELATIVE`）—— 拼错书的字段不可逆。不够格**逐字回到旧行为**（只用最佳候选）；`metadata_fetch.merge_sources` 可整体关掉。
- **`FIELD_TRUST` 的键必须是字段名，不是书对象键**：年份是 `date`（书目里才叫 `year`）。写成 `year` **不报错、只静默失效**（信任表形同虚设）—— 有契约钉住这条。
- ⚠️ 查询题：**`_VALUE_KEYS`/`_CURRENT` 的键是字段名**，`changes` 里也是字段名（`date`）；`_candidate_values`/`merge_values` 遍历的是字段名，候选里的值键才是 `year`。
- 合并**只改选值，不改写不写**：字段策略 / `meta_locks` / `meta_overrides` 三闸照旧；`plan` 与 `online_candidate` **必须同一套规则**（否则同一数据两种答案）；逐字段回传 `source/score`，整条回 `merged_from`（空 = 未合并）。
- **候选入口一律剥 HTML**（`metasources._strip_html`）：实测 iTunes 的简介带 `<b>` 标签，不剥就落库成字面标签。**真实联网能抓到单测抓不到的问题**（假响应是自己写的）。

### 第 57 期铁律（元数据提供商 / 插件市场 / 书源）
- **14 家提供商全部接入**（B 段）：`core/metasources.SOURCES` 与 `_FETCHERS` **必须逐字一致**（契约 `IMPLEMENTED == _FETCHERS.keys()`，`tests/test_metadata_providers.py`）—— 加一家 = 注册表条目 + fetcher + `IMPLEMENTED` 三处同改。三档如实标注：免密钥即用（open-library / googlebooks / itunes / audnexus / ranobedb）、**需密钥**（hardcover / comicvine / aladin，`needs_config=True` + `key_field`）、**页面抓取型**（amazon / goodreads / kobo / audible / librofm / lubimyczytac，`fragile=True` → 前端「易失效」徽标；站点改版可能失效，**真实可用性无法离线验证**）。
- **出网收口**：14 家只经 `metasources._get_json` / `_get_text` 出网 —— 契约测试 monkeypatch 这两个函数即可离线测全部解析（`tests/test_metasources_parsers.py` 33 项）。失败码统一翻中文（429/401/403 有专门文案）；**单源异常绝不冒泡**（解析器一律 `isinstance` 过滤 + 空响应回落 `[]`）。
- **密钥三处同步**：`config.DEFAULTS["metadata_fetch"]` + `server.EDITABLE["metadata_fetch"]` + 注册表 `key_field`；回显一律经 `_mask_metadata_fetch`（**按注册表循环掩码** + `has_<键名>`）。`metasources.options_for(mf, sources)` 是唯一的密钥拼装口（metafetch 的 plan/online_candidate 与 series_meta 共用）。缺密钥的家：抓取回明确中文错误、`/api/metadata/probe` **不发外呼**。
- **启用状态真值源仍是 `metadata_fetch.sources`**（默认只开 2 家：openlibrary + googlebooks；`GET /api/metadata/providers` 只聚合不新开状态）。
- **凭据/参数挂在对应提供商那一行**（第 57 期 D/E 段，用户要求对齐上游）：每行「配置 ▾」展开后在该行下方给控件 + 测试/保存/重置，**不再有底部集中密钥区**。**注册表 `config_fields` 是唯一真值源**：`{key, opt, label, type: secret|select, options?, placeholder?, hint?}`；`provider_catalog()` 把头一项派生成 `key_field`/`key_label`/`key_placeholder`（前端旧字段名可用），`key_field_of()` 同样派生 —— **不要**再单独写这三个字面量。掩码遍历 `metasources.secret_fields()`（Cookie 也是凭据）。
  - ⚠️ **行内「测试」必须只读**：把输入框当前（可能未保存）的值经 `POST /api/metadata/probe` 的 `configs`（整行草稿，早期 `keys` 兼容）传进去，**不落盘** —— 否则只能测到上次保存的旧值，或被迫先保存一次。
  - ⚠️ **行内改动必须同时写进页面级配置草稿**（`setDraft` 里 `setVal`）：否则点页面自己的「保存」不落库，用户会以为存了。静默态 secret 仍是掩码值，后端把掩码当「不修改」语义，安全。
  - 每个配置项必须**真的被 fetcher 用上**（Amazon Cookie 头 / iTunes 尺寸段 / Kobo URL 两段 / Audible 分站域名），否则就是假交互。
- **声明式插件市场已取消**（用户拍板，2026-09-26）：不要再提「可经插件市场安装」，也不要有任何市场/插件包代码。zlibrary 专用下载同样不做（盗版分发平台）。
- 书源侧：**表单化添加**（`SourcesView` 三段式）+ `POST /api/sources/test`（校验 + **不落盘**试搜，写盘唯一入口仍是 `store.add_rule`）；前端必填校验与 `rules.validate_rule` 同口径（另加写盘文件名字符集）。
- **系列级元数据**（第 57 期 C 段）：`series_meta.FIELDS` = description / publisher / first_year / tags **四个字段都可本地覆盖**；⚠️ **`set_local` 的空串语义 = 清除该字段覆盖**，所以「恢复在线」必须**只提交那一个字段**（顺手带上别的字段会清掉用户的其它覆盖）—— `SeriesMetaPanel.spec.ts` 盯死这条；未覆盖时来源是「成员书聚合」（`_aggregate` 零猜测）或在线，界面要标出来源；「册数」两个概念不可合并（owned_count 实际拥有 / declared_count 外部声明）。改前端面板后**必跑** `npm run test:unit`：面板展示改了不会被测试发现，payload 改了才会。

---

## 逐期铁律原文（第 66–71 期；2026-09-28 由 `MEMORY.md` 下沉，内容未删减）

### 第 66 期铁律（阅读器「自动续接」收尾）
- 漫画 / PDF / 有声书三处跨册续接**收敛到唯一真值源 `frontend/src/lib/seriesNext.ts`**（`SERIES_NEXT_MSG` 文案 + 纯函数 `resolveNextVolume` + `useSeriesNext`，含 `enabled` 门 / 单飞闸 / 同类提示 2s 节流）—— ⚠️ 三处组件**不得再各写文案或各拼 `seriesDetail+sortBySeriesIndex+findIndex`**。
- 三处默认值**统一为「开」**（只改 `*_PREFS_DEFAULT`，**不迁移存量**，读时 `{...DEFAULT,...stored}` 天然尊重用户已关的开关）；文案统一用「册」；触底闩 `autoNextArmed` 留在组件（滚动渲染态）。

### 第 67 期铁律（提速收尾）
- ① **响应 gzip**（`server.py` 挂 `GZipMiddleware`；`/api/books` 1.36 MB→491 KB、主包 JS 1.02 MB→301 KB；安全性靠 **206 永不压缩** + `audio/image/video/font/zip` 默认排除；代价是该端点 **+45–60 ms CPU**，LAN 打平 / WAN 受益）。
- ② **并发请求必须单飞**：`if (loaded) return` 守卫**不足以**去重 —— 它在发请求前先 `await` 别的（阈值等）就是让步点，同批调用会全部通过 ⇒ 实测一次页面加载 `/api/books` 打了 **7 次**；各 store 的 loader 必须持**在飞 Promise**（`collections` 的 force 要「等前一次落地再拉」，否则吞掉刚建的收藏夹）。
- ③ **测量纪律**：计时用 `curl`，**别用 PowerShell `Invoke-RestMethod`**（解析 1.3 MB JSON 会把 65 ms 测成 613 ms）。

### 第 68 期铁律（列表载荷与迁移预览）
- ① `server._card()` 是**所有书目列表的统一出口**，**不发简介正文**（曾占 `/api/books` 体积 68%），只发 `has_description` —— 原始 1.36 MB→417 KB、**gzip 后 491 KB→37 KB**；消费方改「筛选看布尔 / 预览从详情取」。
- ② `core/migrate.preview()` 原先**每本书**都调一次 `libraries_of_type()`（读库表）⇒ 改为循环外算「类型→同类库」映射，**300 ms→37 ms**。
- ③ `App.vue` 的 `showLogin` 初值 `false` 会让门控组件**先挂载一次**（未登录白拉一次预览）⇒ 门控要用 `authChecked`，**`auth.ready` 不行**（它在 `init()` 内先变真，中间仍有一个 tick 会挂载）。

### 第 69 期铁律（滚动模式跨章连续流）
- ⚠️ 补偿三条（全是真机量出来的、不是推理）：① 锚取**正文 article** 而非外层 `<section>`（`first:` 变体的 `pt-6` 不在 border-box 里，实测漏 **24px**）；② 补偿写**绝对值** `beforeTop + 补偿量`，**不能 `+=`**（浏览器自带 scroll anchoring 常已替我们调好 `scrollTop`，相对累加会把同一段位移补两次）；③ 锚必须是**已存在**的块（新插入的块此刻还没有 DOM ⇒ `chunkArt` 返回 null ⇒ 等于没有锚 ⇒ 正文被整体按下、看起来「跳了一屏」）。
- ⚠️ **同一位置被并发并入 ⇒ `:key` 重复 ⇒ Vue patch 失去定义、渲染错序**（实测出「上一章排在中间」）。规律：两条异步路径可能同时想要同一份数据时，**合并前重读当前集合 + 落地前按 id 去重 + 写入串行**，三样都要有。
- ⚠️ 冒烟时 `playwright-cli goto` **只改 hash 不重载产物**：验证新构建必须带 cache-busting 查询（如 `?v=69b#/read/...`）；且 SPA 内 `goto` **不一定重新挂载组件** ⇒ 验页面级状态要 `reload`（第 71 期验闸门时踩到：goto 后仍显示旧状态）。

### 第 70 期铁律（全站开关统一 / 收书投递）
- **全站开关只有一个实现**：`frontend/src/components/ui/Switch.vue`（`button[role=switch]` + `aria-checked`）。改外观 / 尺寸 / 过渡 / 禁用**只改这一个文件**；配色必须走主题变量，焦点环**不要自写**（全局 `:focus-visible` + `prefers-reduced-motion` 已接管）。⚠️ 滑块用 `bg-card` 而非硬编码白色（深色主题下 `--primary` 是**浅色**，写死白滑块会糊在浅色轨道上）。
- ⚠️ **`v-model` 与同一事件上的副作用监听器，执行顺序不由我们决定**：写 `v-model="x" @update:model-value="persist()"` 可能先 persist 后赋值 ⇒ **存的是旧值**。凡「改值后要落盘 / 上报」的组件统一写成一条内联语句：`:model-value="x" @update:model-value="x = $event; persist()"`。
- ⚠️ **`<label>` 包住自定义按钮时，点标签文字仍会切换**（Edge 实测）：`input[type=checkbox]` 换成 `button[role=switch]` **不会**丢这个既有行为，可放心保留 `<label>` 外壳。
- **收书目录投递只有一条链路**：`api.convertDrop(file)` → `POST /convert`（写进 `INPUT_DIR` 走既有管线）；拖拽与工具栏「上传」按钮共用 `deliverToDock(files)`；隐藏的 `input[type=file]` 处理完**必须清空 `input.value`**，否则连选同一个文件第二次不再触发 `change`。项目**没有 i18n**，文案写中文字面量。

### 第 71 期铁律（探索发现：闸门 / 逐源状态 / 合并 / 真分页）
- **闸门判定只有一处** `DownloadManager.gate_reason(source=None)`（空串 = 放行）；`/api/search`、`/api/download`、`/api/preview` **请求入口**先问它、非空即 400 + 原因原文；`store.sources_status()` 的 `usable`/`blocked_reason` 由它产出（界面文案与接口拒绝原因**同源**）；**`/api/sources/test` 刻意不拦**（管理面自检，否则用户无法验证自己写的规则）；前端进页面先读状态、关着就**提前置灰**并给出出口（不允许「点了才报错」）。
- **命中来源名只有一种读法** `sources.source_of(item)`（`source` / `_source` 都认、新键优先）；`manager._mark()` 一处写全 `source` / `source_name` / `_source`。⚠️ 此前只写 `_source` ⇒ 来源徽章空白 + 预览必 502「未知书源: undefined」。
- **搜索必须真并发**：`asyncio.gather` + 每源 `asyncio.wait_for(SEARCH_TIMEOUT=20)`（模块常量，不进配置面板）；逐源状态 `sources=[{name,display_name,ok,count,error,skipped,reason,has_more}]` 如实回，失败原因用原文，不编造分类。
- **分页契约** `SourceAdapter.search_page(client,title,page=1)`：**`page>1` 且源不支持分页必须回空**（否则「加载更多」会把第一页原样再显示一遍）；`RuleBasedSource` 仅在 `search.url` 含 `{page}` 时替换（不含 ⇒ `has_more=False`，「不知道就说不知道」）；前端「加载更多」是**追加**，且「本页无新条目」时收起按钮。
- **合并刻意保守**（`frontend/src/lib/searchResults.ts` 纯函数）：书名与作者**都**归一化成功且分别相同才合并 —— 作者未知不并、卷次 / 副标题差异不猜；排序「书名完全相同 > 前缀 / 包含 > 其它，同档有作者信息优先，其余稳定保持后端序」。
- **行内任务状态**复用既有 tasks store（**不新增轮询**）；**不做「一键重试」**（`tasks` 表没有可重放的源数据列，做出来只会是假按钮）。
- ⚠️ **httpx 0.28 没有 `CookieJar`**（只有 `Cookies` / `CookieConflict`）⇒ `core/network.py` 必须用标准库 `http.cookiejar.CookieJar`；写成 `httpx.CookieJar()` 会让**每个书源一构造客户端就 AttributeError**（搜索恒 0 条 / 下载恒失败），而**单测全用桩 client 照不到**（第 71 期真机冒烟才现形）。
- ⚠️ **规则源搜索命中地址必须补绝对**：`_absolutize` 按搜索页 url 做 urljoin（与章节目录 `_extract_links` 同口径）；不补则真实站点几乎都用相对链接 ⇒ 预览 / 取书以「Request URL is missing an 'http://'…」失败。
- ⚠️ 冒烟坑：隔离 `CONFIG_DIR` 残留上一轮 `settings.json`（`download.enabled=true`）会让闸门**不触发** ⇒ 验「闸门关闭态」前先确认目录干净。

### 第 72 期铁律（TXT 乱码：编码样本截断 / 长章书分章退化）

**症状 → 根因链**（本机一本 1.1 MB 中文 UTF-8 TXT：阅读全文乱码、详情 3723 章、每章只有乱码 `<h2>`）：
导入链路**无责**（`pipeline.dispatch` 只 `shutil.copy2`，源与库副本 md5 逐字节相同、文件本身是合法 UTF-8）。
真因是**三处判据**，且**只修编码不够**（修好编码后仍是 3723 个空正文章 —— 实测）。

- ⚠️ **按字节切出来的样本，不能当作「这不是 UTF-8」的证据**（缺陷 A，`pipeline._detect_encoding`）。`_sample_bytes` 按**字节**截 256 KiB，切点有 2/3 概率落在 3 字节汉字中间；老实现拿整段样本 `decode("utf-8-sig")` 自证（**严格**解码，尾部不完整即抛）⇒ 判 gb18030 ⇒ 解出满屏乱码且**全程不报错**（调用方还叠加 `errors="ignore"`）。判「前缀」的唯一写法：`codecs.getincrementaldecoder("utf-8")().decode(data, final=False)`（**每次新建实例**，解码器有状态）—— 只容忍**尾部**不足一个字符的序列，**中间**任何坏字节照旧抛（实测真 GBK / Big5 样本仍判 False，容错没放宽成「差不多就行」）。样本 >256 KiB 的中文 TXT 因此成片中招，而现有夹具都远小于 256 KiB。
- ⚠️ **两段样本拼接，接缝处必须自己保证是字符边界**（缺陷 A2，同族第三处）。「开头纯 ASCII」时补采中段，起点 `size // 2` **按字节算**、多半落在字符中间 ⇒ 直接拼 `data + more` 会在**中间**造出一个假非法字节（续字节不能当字符开头）—— 前缀判定只容忍尾部，**救不了它**，真 UTF-8 书照样被判成 big5。修法 `_read_from_char_boundary`：① 窗口内先找换行（`0x0A` 在 UTF-8 / GBK / Big5 里都**不可能**做后继字节，换行后必是字符边界）；② 没有换行就跳过开头的续字节（`0x80–0xBF`）。头部那段全 ASCII ⇒ 尾部必然是边界，所以只需对齐中段起点。
- ⚠️ **长章不是「命中太少」**（缺陷 B，`detect.detect_chapters`）：老置信闸门 `len(bounds) * 2000 >= len(text)` 会把一本 25 章、平均 1.5 万字/章的书判成「正则无效」（25×2000 = 50,000 < 373,187）⇒ 退化缩进切分。新判据 `detect.regex_confident(bounds, text)` = **密度 `len(bounds)*2000 >= len(text)` 或条数 `len(bounds) >= 3`**（行首锚定后 3 条以上行首章标记基本不可能是巧合）。它是**公开名**：消费者有两个 —— `detect_chapters`（用不用缩进降级）与 `ai_detect.HybridChapterDetector`（要不要花钱调 LLM），**同一判据不许有第二份拷贝**。
- **降级产物一章正文都没有 ⇒ 回退正则边界**（保险）：全顶格文本在缩进降级下「每一行都成章首」⇒ N 个空正文假章，阅读器里表现为「满屏标题、点进去没有正文」。几个真边界好过 N 个空章。
- **缩进降级认全角空格** `_split_by_indent`：`ln[:1] in (" ", "\t", "　")` —— 必须与 `_LEAD`（`[ \t　]*`）的字符集一致。中文文本用全角空格缩进是常态，只认半角会把**每一段**当成新章首（本机那本 3697 行用 `　　` 缩进）。
- **`mode: regex` 的语义就是 `detect_chapters`**：直接委派，别在 `ai_detect` 里重写置信判据与降级逻辑（老写法少写「降级全空回退正则」那道保险 ⇒ 同一文本走管线与走检测器得到**不同目录**）。**行为变更**（写进 roadmap）：hybrid 模式下长章书不再触发 LLM（此前一本**已切对**的书每次都要花一次钱）。
- ⚠️ **派生缓存：凡影响正文产出的口径都要进指纹**。第 62 期只放进了分章规则版本；本期新增 `pipeline.ENCODING_RULE_VERSION`，由 `txtcache.ENC_RULE_VERSION` 写进 `state.json`（`enc_rule`）与 `_SPLIT_CACHE` 键，`server.py` 原生路线的 Redis 章节缓存 `extra` 也带上（`v{RULE_VERSION}:e{ENC_RULE_VERSION}`）。漏掉的后果就是「判据改了、源文件一个字节没动」时**缓存永远命中、改了看不见效果**。
- **老 `state.json` 缺 `enc_rule` 字段本身就是失效信号**（`state.get("enc_rule") != ENC_RULE_VERSION` ⇒ 不命中 ⇒ 重建）：这是「已缓存成 ok 的乱码派生件」与「失败状态永久粘住」唯一的自愈通道 —— 少了它，改完代码用户看到的还是老样子，且**不报错、不重建**。
- **「正文读不出」必须留痕**（第 72 期可观测）：`txtcache.derived_epub` 失败分支写一条 `ACTION_CONVERT` + `STATUS_FAIL` 活动日志（主体 = **源文件名**，不同书不合并；`_log_rule_rebuild` 那种固定标签才合并成一条）。此前整条路**静默**：`state.json` 记个 `failed`，阅读器照渲染空章，用户在界面上拿不到任何提示。**同一（源指纹, 判据版本）只写一次**（第二次请求走 state 命中失败分支直接 `return None`），不会刷屏。
- **不引 chardet / charset-normalizer**（项目铁律），也**不把 utf-8 放进打分循环**（那是第二条判据改动：本期容错只放宽「样本尾部被切断」，中间有坏字节仍判非 UTF-8）。**不做 UTF-16 / UTF-32 探测**（另一个独立缺口，无实例）。

### 第 73 期铁律（序号单元合并 / 口径自愈 / 进度独占）

**需求**：漫画库 / 有声书库里一本书的实际形态是 `《转生魔女宣告毁灭（1-43话）》/第1卷/第1话.pdf`
（序号写法还混着 `第1话` / `第二话` / `第03话` / `4 第4话`），而扫描层是「一个文件 = 一本书」
⇒ 书架上 43 本散书、读不成连续话；`_iter_book_entries` 那句「只下探一层」还让更深的文件**根本扫不到**。
用户拍板：合并判据 = 序号单元判据 / 只管**漫画库 + 有声书库** / 合并 + 连续阅读 / 窄规则剥书名备注。

**判据本体 `novelforge/core/units.py`（唯一真值源）**
- `is_unit_dir(d)` = 递归媒体文件中 **≥2 个能解析出序号、且序号不全相同**。两道闸各管一件事：「≥2」排除
  只有一话的目录；「不全相同」排除**把容器当书**（`作者/《甲》/第1话.cbz` + `作者/《乙》/第1话.cbz`
  两个都解析得出序号，实为两本书各自的第一话）。取向写死：**宁可少合并（退回今天行为）不可错合并**
  —— 错合并之后用户只能靠改名目录自救。
- `parse_unit` 三形态：① 尾部 `第N<单位词>`（`第12话` / `第十二话` / `第03卷`，标记后**可带标题**）；
  ② `4 第4话`（**前缀数字必须等于**单元号，`4x 第4话` 不算）；③ 裸数字 `01` / `007`（**≤ `_MAX_UNIT`=999**，
  否则 `2024.pdf` 会被当话）。单位词 `话話卷回册集部篇幕章`。**刻意不收**：`《甲》(第1卷).cbz`（标记不在
  开头）、`作品名 第1话.pdf`、`第1-43话.pdf`（那是范围）、`vol.1.cbz`。
- 排序 `(num, natural_key(rel_path))`，**解析不出序号的排最后**（`序章` / `番外` 不猜位置）；
  `name` 是**相对树根**的 posix 路径（要直接下发前端，不含绝对路径）。
- 上限 `_MAX_DEPTH=4` / `_MAX_FILES=5000`，**超限一律不合并**（保守退回）；符号链接环路靠深度兜住。
- **两套 exts 口径是有意的**：枚举侧传**库生效白名单**，探测侧 `_probe_entry`（只能依赖文件自身）
  用固定 `UNIT_EXTS` —— 同一实现、两个配置，理由写进注释。
- ⚠️ **库级 `exclude` 图案刻意不在树内应用**：树通过判据后整棵就是一个条目、图案作用的对象已消失；
  更硬的理由是**增量闸门拿不到图案**（`_cheap_facts` 只有路径）⇒ 应用了会出现「卡片说 4 话、阅读器里 5 话」。
- ⚠️ **`shape_of` 顺序 = 先平铺音频、后序号单元**：编号轨有声书 `01.mp3…12.mp3` 同时满足两条判据，
  取**音频形态**才能让「N 轨 + 播放器」这套既有行为逐字不变。`merges_for(ltype)` 只认 `comic` / `audiobook`；
  `collected_by` 由**枚举**与**搬家闸门**共享（第三份拷贝已收敛，别再写第四份）。
- ⚠️ **与 `komga.infer` 是两套判据，刻意不合并**（那套解析「系列名 + 册号」、要 ≥2 字系列名；
  实测对 `第1话` / `4 第4话` / `01` 一律返回空）。

**扫描层（`library.py` / `catalog.py` / `migrate.py`）**
- `_iter_book_entries(d, exts, exclude, ltype)` 新分支排在「顶层文件 → 隐藏目录 → 音频目录」之后、
  **下探一层之前**，命中即 `continue`（书边界 = **最外层**；不 `continue` 会把子树文件当兄弟条目重登记）。
- `_probe_entry` 命中单元树 ⇒ `tracks = 话数`（**复用既有 `tracks` 列** ⇒ 零新列零迁移）、
  `format = "AUDIO"`（全部是音频话）否则 `"UNITS"`、`pages = 0`；**签名不变** —— 「只能依赖文件自身」
  这条硬约束**没有被绕开**：判据只需要目录自身 + 文件名，`_probe_entry` 照旧只拿得到路径。
- ⚠️ `_cheap_facts` 目录分支改 `units.dir_fingerprint`（**递归**）—— **本期唯一的性能代价**
  （目录条目从一次 scandir 变一次递归遍历，带 `_MAX_FILES` 上限）。指纹必须看得见树里**每一个**文件
  （含封面）：只算媒体文件的话「加一张封面」在增量闸门上完全看不见。
- ⚠️ **`SCAN_RULE_VERSION`（`library.py`）**：凡改变**条目边界或卡片字段口径**的改动都要 +1。
  `catalog` 把它**按库**记在 `app_state`（`book_index_rule:{lid}`），不一致 ⇒ 该库下一轮刷新**当作 `force`**，
  成功后写回（只发生一次，之后回增量）。⚠️ **按库分键是必须的**：全局键会让第一个刷新完的库写上新版本、
  **后面的库再也不重探** ⇒ 只有一本书被修好，比不修更难查。这是**存量索引唯一的自愈通道**
  （磁盘没变 ⇒ `(size, mtime)` 闸门永不重探旧行；第 72 期在派生件那边踩过同一个坑）。
- 排序键同源：`catalog` 里「精确复刻 `_iter_book_entries` 遍历顺序」的那份必须同批改（否则书架顺序抖动）；
  `migrate` 的第三份「是不是音频目录」字面量收敛到 `collected_by`。

**书名 `metadata.strip_count_note`**：剥**尾部**括号的范围 / 话数备注（`^第?全?\d*(?:[-–~]\d+)[话話卷回集部篇幕章]?$`
与 `^全?\d+[话話卷回册集部篇幕章]$`）⇒ `（1-43话）` / `（全43话）` / `（第1-43话）` / `（1-43）` 剥；
**反例不剥**：`（0079）`（无范围无单位词）/ `（修订版）` / `（上册）`。`from_filename` 的**两个分支都过它**
（对所有书生效，存量靠口径版本自愈重探）；用户改过的书名在**覆盖层**里、优先 ⇒ 不覆盖用户编辑。

**服务端**：四个 `/units` 端点（话清单 / 单话字节流 / 话的页数 / 话的第 n 页）；`_MEDIA_TOKEN_PATHS` 增
`books/[^/]+/units/\d+$` 与 `books/[^/]+/units/\d+/page/\d+$`（`<audio src>` / `<img src>` 是**浏览器原生请求**、
带不了 Authorization）—— ⚠️ **列表端点仍要鉴权**。`api_audio_tracks` / `api_audio_track` 改为**委派**
`units.tracks_of` / `track_at`（**音频轨与话是同一份清单的两个名字** ⇒ 嵌套有声书一并修好、AudioPlayer 协议不变）；
详情封面走 `units.cover_in_tree`。

**前端**
- **进度换算唯一真值源 `lib/unitsProgress.ts`**（`toPercent` / `fromPercent`，口径与改造前 `AudioPlayer` 逐字相同）
  —— 顺手把 `AudioPlayer` 里那份 `Math.floor(percent / 100 * total)` 的**第二份反推公式**收敛掉。
- ⚠️ **二进制浮点下乘除不严格互逆**：`toPercent(i, 0, total)` 写出的 `i / total * 100` 反解回来可能是
  `15.999999999999998` ⇒ `floor` 落到**上一话的末尾**（43 话的书里第 16 话开头回到第 15 话最后一页，
  界面显示第 16 话，**全程不报错**）。`fromPercent` 加 **`BOUNDARY_EPS = 1e-9`**；往返用例断言
  「话号**精确** + 话内比例只要浮点容差」。
- ⚠️ **进度由上层独占**：整本书只有 `progress` 那一行 `percent`，`UnitsReader` 是**唯一**写它的地方；
  三个子阅读器在 `unit?: UnitRef` 模式下**进度不读不写**，只 `emit('unitPos')` / `emit('unitEnd')`。
  四条协议：① 上报带 `index` ⇒ **丢弃过期上报**（换话时旧组件卸载还会再报一次，不核对会把
  「第 3 话读到一半」写成「第 4 话读到一半」）；② 换话两笔写入**串行**；③ 卸载时**补写**；④ 写库**不取整**。
- `UnitsReader.vue` 主区按当前话 `kind` 挂 `PdfReader` / `ComicReader` / `AudioPlayer`，`:key` = 话号 ⇒ 换话**重建**；
  自动续话**只在「读完自动进下一话」时 `autoplay`**，用户点「下一话」不自动播。
- ⚠️ **`await router.isReady()` 不能写在 `mount` 之前**：首次导航由 `app.use(router)`（即 mount）发起，
  先 await 它就是**死等** —— 表现是**每个用例都 5 s 超时**（一次 9 例一起超时）。
- ⚠️ **`vue-tsc` 对桩的联合类型按名字取 prop 会收成 `never`** ⇒ 用例改成 `.props()` 整取再断言；
  桩用 `h()` 而**不是** `template:`（运行期模板编译要完整版 Vue，vitest 走 bundler 版）。

**未做（用户需知情）**：⚠️ `watcher` / 收书目录入库路径**不认**单元树（往 `INPUT_DIR` 丢一棵树仍拆成 N 本散书，
与「放进库根」行为不一致）；⚠️ 43 本旧散书的进度 / 评分 / 收藏**不自动并**到新书（旧行不删不搬，将来可补一次映射）；
不做 PDF 首页当封面 / 扫描期统计 PDF 页数 / 跨类型自动续话 / 合集切漫画视图 / 散图目录合并 / 电子书库与混合库合并 / remap。
⚠️ 容器验收时 `publish_path` 有「不得与库根重叠」守卫 ⇒ 发布回归是**容器内直调 publish 原语**（不是走 API 发布的），
如实标注；源码树指纹与逐文件 size/mtime 实测**完全未变**。

### 第 79 期铁律（序号单元第四形态「前缀 + 尾部编号」/ 存量自愈 / 冒烟纪律）

**判据（`novelforge/core/units.py` 是唯一真值源）**
- **第四种形态**：`<标题><尾部编号>`（`超人前传0904.pdf` → 904、去前导零），独立上界 `_MAX_TAIL_UNIT = 9999`。
  ⚠️ **`_MAX_UNIT = 999` 一个字都不许动** —— 抬高它会让 `2024.pdf`（年份）变成「第 2024 话」，是明确回归。
- **解析点只此一处**：内部 `_split_unit(stem) -> (前缀, 序号) | None`，`parse_unit` 委托取序号（公开契约不变）；
  `is_unit_dir` 的同前缀闸取前缀。既有三形态（`第12话` / `4 第4话` / 纯数字）一律回**空串前缀** ——
  给它们硬编一个前缀，同一棵树里的 `4 第4话` 与 `第4话` 就会被判成两种前缀、**反而不再合并**。
- **新形态必须后置**（`第1话 番外` / `第01话 某标题` 这些带尾巴的写法必须仍由标记形态先命中）。
- ⚠️ **编号必须紧贴标题文字**（前缀末字符 ∈ `[^\W\d_]` 即字母/汉字）：这条比「任意非空前缀」严，且**实测倒逼**——
  否则 `vol.1`（`pre="vol."` + `num="1"`）会被认成「第 1 话」，而它是现有契约表里明确写着 `None` 的一条。
  代价：`作品名-1408` / `作品名_1408` / `作品名 1408` 不收（宁可少合并）。
- ⚠️ **`_BARE_NUM_RE` 分支在超界时不 return**（既有语义边界，保留）：新正则必须自带「前缀含非数字字符」的约束，
  否则 `1408` 会被拆成 `pre="1" + num="408"` ⇒ 第 408 话。
- **「同前缀」闸**：`is_unit_dir` = `前缀集合恰 1 种` **且** `≥2 个不同序号`（原先只有后半条）。
- ⚠️ **`_entries()` 是四元组** `(Path, rel, 前缀, 序号)`：改元数时全部解包点同批改，最易漏的是
  `_sorted_entries` 的排序键**按位置索引**（`t[2]` → `t[3]`）—— 错位成前缀会拿 str 与 `_INF`(float) 比元组、
  抛 TypeError（响亮失败，不是静默错序）。

**「只在一级子文件夹内合并」= 零新代码**：`is_unit_dir` 只对**目录**调用，而 `_iter_book_entries` 的目录分支
只扫库根这一层；库根的文件是「文件条目」、永不走该判据 ⇒ 「平铺库根不合并」天然成立，**不要**加「库根例外」分支。

**存量自愈**：`library.SCAN_RULE_VERSION` 1 → 2（条目边界口径变了 ⇒ 旧索引行必须重探）。
`catalog._rule_stale` 按**库**比对，不一致即把该库下一轮刷新当作 `force`，跑完写回（**只自愈一次**）。
⚠️ 实测：**单纯 `GET /api/books` 不会触发自愈** —— 该路径只在库「未就绪 / 脏」时刷新，而「口径过期」两者都不是；
真实触发点是监听线程的定时全量兜底（`catalog.refresh_all`，默认 60s，`libraries.index_interval`）、重启预热、
以及任何让库变脏的写操作。`POST /api/libraries/{lid}/scan` **恒 force**，不能用来验增量/自愈路径。

**冒烟纪律（本期新增）**
- ⚠️ `playwright-cli snapshot --filename=x.yaml` 把文件写到 **cwd**（不是 `.playwright-cli/`）⇒ 误落仓库根，
  临时产物要么不带 `--filename`（落 `.playwright-cli/`，已 gitignore）要么显式写到临时目录。
- ⚠️ **`git commit -F` 用当期新建的信息文件**：误用上一期残留的 `$env:TEMP\nf_msg1.txt` 会提交成上一期的信息
  （本地未推送时 `git reset --soft HEAD~1` + 重做即可，别 amend 后继续堆）。
- 端点形状：`GET /api/books` → `{items,total}`；`POST /api/libraries` → `{ok,library}`（id 在 `library.id`）。
- 假 PDF（`b"%PDF-1.4 fake"`）够扫描/合并类验收，但阅读器会报 `Invalid PDF structure.`（夹具所致，不是产品问题）。

---

### 第 81 期铁律（「移除书库」语义 / 回收台账与还原 / 长文件名）

**需求**：线上实例报「移除漫画书库失败」。现场：请求数小时不返回、库仍在册但 `book_count` 持续下降
（2206→1947→1834→1647→1531）、回收目录以 **≈79 MB/s（跨卷速率）** 增长、活动日志 165 条全 success
却无一条「移除书库登记」。用户 `docker compose stop` 止血并保留现场。

- **「移除书库」= 只删登记**（第 75 期「回收 ②③ 保留 ①」的**默认行为作废**）：`DELETE /api/libraries/{lid}`
  默认同步、立即返回、**零文件触碰**（返回 `{purge_files:false, targets:0, task_id:null}`）；
  要连文件一起清必须**显式** `purge_files=1`（`force` 参数已整个删除）。**不再有**「库里还有书」的 400 拦截。
- ⚠️ **待回收清单必须在删登记之前物化**（`server._purge_paths`）：③ 的路径取自刮削台账 `link_rel`，
  而 `db.scrape_delete_by_library` 会把台账行删掉 —— 晚一步就再也算不出副本在哪。
- ⚠️ **「删书」口径一字未动**（仍是 ① 收书目录里的本地原件 + ② 书库根里的成品 + ③ 出版副本一起回收）。
  两条路径口径不一致是**刻意的**：「删书」是用户指着某一本说「连文件一起删」；「移除书库」只该表达「别再管这个库」。
- **长文件操作一律后台任务**（类型 `librarypurge` 清理 / `recycle` 还原）：接口立即返回 `task_id`，
  逐项回调真进度；**刻意不写 `result`**（有它前端会渲染成「下载」按钮，而这两件事没有产物可下）。
  全局在跑标记 `_ops_pending` / `_ops_idle` + `server.wait_background_ops()`，由
  `tests/conftest.py::_quiesce_background` 在夹具 `db.close()` **之前**收尾（与 scrape / watcher / embed 同纪律）。
- **回收落点名唯一实现 `fileops.recycled_name`**：`{stamp}_{n_}{name}`，UTF-8 字节长 ≤ `RECYCLE_NAME_MAX`(255)；
  超长按**字节边界**截断（`trunc_bytes`）+ 追加 `~<8 位短哈希>`（保唯一可辨）、尽量保住扩展名。
  三个调用方必须走它：`publish.recycle` / `fileops.recycle_items` / `bookdock.remove`（原先各写了一份 `f"{stamp}_{name}"`）。
  线上该漫画库 ≥240 字节的名字有 **7 个**（最长 277）⇒ `ENAMETOOLONG` 被记成 failed。
- **回收台账 `recycle_items`**（`id / orig_path / recycled_name / why / size / created_at`）：
  ⚠️ **刻意不含 `book_id`** —— 它记的是「磁盘上某个被移走的路径」而非「某本书的数据」，
  改名 / 换库都不会让它失效 ⇒ **不进** `ORPHAN_TABLES` / `REMAP_TABLES` / `REMAP_PROBE_FILTER` / `REMAP_EXPLICIT_TABLES`。
  写入走**永不外抛**的 `db.recycle_note`（文件已移走，不能因为记不上账把回收算失败）；
  `size` 必须在 `shutil.move` **之前**取，目录型条目用 `fileops.size_of` 递归和（win32 目录 `st_size` 恒 0）。
- **回收站还原**（`core/recycle.py` + `GET /api/recycle` + `POST /api/recycle/restore`）：
  `ids`（台账行，按各自 `orig_path`）/ `names` + `target_dir`（无台账孤儿，剥 `YYYYMMDD-HHMMSS_[n_]` 前缀）/
  `all`（全部台账条目）三种入参可组合。**幂等可续跑**：成功后删台账行。
  目标已存在 ⇒ `recycle.free_path` 退让改名（`名字 (2).ext`）**绝不覆盖**，回执如实标 `renamed`。
  `names` 必须是纯文件名（`_safe_name` 挡 `/`、`\`、`..`）；解析不出的条目进 `errors`，不静默丢。
- **清空回收站同批清台账**（`db.recycle_clear`）：文件都真删了，台账再宣称「可以还原」就是骗人。

---

### 第 82 期铁律（首页对齐上游：两步走 / 壳上移 / 行内拖拽 / 真实数据态）

**需求**：「从上游获取首页的样式」。**两步走**：先出对照基线（`docs/bookorbit/bookorbit-dashboard-styles.md`，
上游 `bookorbit @ c292d6cc`），用户确认后逐项改造。**业务语义与数据来源一律不动**（`reading-rhythm` 仍是「入库节奏」、
discover 行仍按 id 稳定排序）。**口径以对照文档 §7「实施结果」为准**（它覆盖 §2–§4 的旧判定）。

- ⚠️ **命名陷阱**：两侧都有 `DashboardScroller.vue` 但**职责不同** —— 上游是「一个书架行」，本项目是「页面级栅格容器」
  （14 行 + `<slot>`）；本项目的书架行叫 `DashboardShelfRow.vue`。按文件名对会比较出完全错误的结论。
- **尺寸与键**：`WidgetSize` 收敛为上游两档 `'1x1' | '1x1.5'`（宽卡 5 件分配照抄上游 `widgetLayout`）；
  ⚠️ `WidgetId` 是 localStorage 持久化键**一字不改**，且持久化结构 `{id, enabled}` **不含 size** ⇒ 改档位**零迁移**。
- **壳上移**：卡片外壳（`h-55 rounded-2xl border-primary/40 bg-card/30 shadow-sm backdrop-blur-[1px]`）**唯一真值源在
  `DashboardWidgetRow.vue`**；12 件部件根节点统一 `flex h-full flex-col[/…] p-3`、只声明 `size` prop 不分支渲染。
  改圆角/描边/宽度只动行组件，**别在部件里加壳**（双层壳是本次消灭的形态差）。
- **行内拖拽**：显式依赖 `vue-draggable-plus@^0.6.1`（≈13–15 KB gzip，**触屏可拖** —— 原生 HTML5 DnD 在
  iOS/Android 不触发 `dragstart`，这是浏览器限制不是实现问题；理由记录在 package.json 声明处 /
  `architecture.md` 不变量 #6 / 组件头注释）。⚠️ 它直接操作 DOM ⇒ 必须保留 `localWidgets` 本地副本防松手闪回；
  ⚠️⚠️ **行内渲染的是可见子集**（启用 ∩ 已实现 ∩ 能力裁剪），而 `moveWidget` 用全量索引 ⇒ 必须经
  `stores/dashboard.ts::applyVisibleOrder` 做「可见子集 → 全量索引」映射，否则排错位。设置面板内仍用原生 `useDndSort`，两处互不影响。
- **数据态**（`composables/useWidgetState.ts`，唯一真值源）：`{loading?, error?, empty?} → loading > error > empty > ready`。
  ⚠️ **只读各 store 既有字段**（`stats.loaded/error`、`library.loaded/hasNoLibraries`、批注部件本地 `failed`），
  **不做假数据、不加假延迟**。⚠️ 空值收窄：分支条件要直接引用可空 computed（`v-else-if="!book"`），
  用 `state === 'empty'` 判会丢 TS 收窄（`today`/`book`/`gem` 全报 possibly null）。
- **刻意不引**：`@vueuse/core`（窄屏判定用 `matchMedia` 自实现，`lib/shelfRows.ts::useNarrowScreen`，不可用环境按宽屏降级）、
  `lucide-vue-next`（图标走 `lib/icons.ts` 唯一注册表，grip 用 `fill="currentColor"` 实心圆点）、`tailwindcss-animate`
  （动效在 `assets/main.css`）；**不按通用 Vue 模板降级栈**（项目是 Vite 8 / TS 6 / Tailwind v4 `@theme inline`）。
- **收尾**：新增纯函数必须立 spec 并登记 `test_frontend_unit_contract.py::EXPECTED_SPECS`（缺失即报错）；
  ⚠️ 响应性用例的源必须是 `ref`/store 字段（普通 `let` 变量不是响应源，computed 不会重算 —— 本期实测踩过）；
  图标契约（模板字面量名 ⊆ `ICONS` 键 + path 非空）会自动覆盖新增键。

---

### 第 83 期铁律（仪表盘余留：库范围 / 第 13 件部件 / 快速预览 / 封面上场）

**范围**：用户从对照文档 §7.2 现状与 §7.4 未做项里各挑两项（库范围筛选 + 封面动画与细节收尾），
`reading-rhythm` 语义**另开第 13 件部件**（保留「入库节奏」），书架行**点封面改开快速预览浮层**。
**不做**：整页三态分支（本项目没有单一「页面加载」信号，硬造即假）、上游首页截图肉眼比对。

- **库范围语义**（`lib/shelfScope.ts`，唯一判据）：`library_ids` **空 / 缺省 = 全部书库**
  （与 `CustomFieldDef.library_ids` 同口径）；**指向已删库的 id 一律忽略**；忽略后**有效项一个不剩 ⇒ 退化回全部**
  （宁可多显示，也不静默清空）；缺 `library_id` 的旧书目按「不在所选库」处理。过滤层必须叠在 `allBooks` **之后**
  （四种行类型才统一生效）；`scope`（智能书架键）与它是**两个维度**，别合并。
- **面板交互**：当前是「全部书库」时勾第一个库 ⇒ 变成只有这个库；**取消最后一个勾选直接拒绝 + 提示**
  （否则会静默回到「全部书库」，与用户意图相反）。数据侧不做「至少一个」的兜底 —— 那是交互约束不是数据约束。
- **第 13 件部件**：**前 12 个 `WidgetId` 与上游逐一对应是契约**（id 是 localStorage 键，改名会让存量偏好静默丢失），
  新增一律**追加末尾**且**不进 `DEFAULT_WIDGET_IDS`**（存量用户升级不该凭空多卡片）；`mergeWidgets` 会自动追加新 id ⇒ **零迁移**。
  契约由 `tests/test_dashboard_widget_contract.py` 钉住（含「registry 无漏登记」「部件不许再加壳」）。
- **快速预览**：基座是自有 `BookPreviewDialog.vue`（第 64 期），加 `actions`（默认 `false` ⇒ 既有调用方零影响）。
  ⚠️ **必须 `<Teleport to="body">`** —— 书架行外壳有 `backdrop-blur`，会让 `position: fixed` 的后代以外壳为包含块，
  浮层会被裁进卡片里。边界不破：仍**不给**批注 / 阅读日志 / 文件路径 / 编辑入口。
- **删书唯一真值源** `lib/bookDelete.ts`（`siblingNamesOf` / `deleteConfirmLines` / `deletedToast` / `confirmAndDeleteBook`）：
  书卡 ⋮ 菜单与预览浮层共用；「部分失败要点名」这条别在任一处另写。
- **封面错峰**：照上游**带内** `index * 35ms`（每带重置 ⇒ 实际最大 ≈ 每带封面数 × 35ms），另加 700ms 上限兜底。
  ⚠️ **scoped keyframes 不受 `main.css` 全局 `prefers-reduced-motion` 降级的保护**（那条只压 duration）⇒
  组件内自己写 `@media (prefers-reduced-motion: reduce) { animation: none !important }`；挂在内联样式上的动画需 `!important` 才压得住。
- **上游路径**：快速预览**不在** dashboard 特性下，是 `client/src/features/book/components/BookQuickView.vue`
  （配 `BookCoverCard` / `AddToCollectionSheet` / `DeleteBookDialog` + `useDeleteBook`）；
  且上游是**封面卡动作菜单 → `quick-view`**（动作集合 `quick-view` / `edit-metadata` / `add-to-collection` / `move-to-library` / `delete`），
  **不是点封面**。本项目按用户口径改成「点封面即开预览」。
- **顺手修的真缺陷**：三件部件打开目标写死 `/read/`（有声书进打不开的阅读器）⇒ 统一走 `lib/bookActions`→`openTargetOf`。

---

## 逐期铁律原文（第 84–89 期；2026-10-03 由 `MEMORY.md` 下沉 + 新增）

> 第 84 / 85 期原为 `MEMORY.md` 内联长段（导致注入截断），2026-10-03 下沉到此；第 86–89 期为同期新增。
> ⚠️ **期号 84 已被并行会话占用，别再回用**。

### 第 84 期铁律（自动更新加固）

- ① 第 80 期「先记已尝试、再执行」使 pull 失败也被当「已试过」⇒ **失败一次即永久卡死**；
  改建 `auto_failures` / `auto_retry_at` / `last_auto_result` / `auto_message` **退避状态机**
  （**1h→6h→24h 封顶**）；新 stage **`defer`** **不复用**语义为「永久放弃」的 `already_tried`；
  未挂 socket 记 `unavailable`、**不记失败**。
- ② 抽出 `_tick()` 让**启动首轮与定时轮共用同一份逻辑**（启动即检，不等一个间隔）。
- ③ 新增 `core/backup.py` 更新前快照（PG `pg_dump -Fc` / SQLite `copy2`，落 `BACKUP_DIR` 保留 5 份，
  **失败即 `backup_failed` 中止、不进入 pull**）。
- ④ 维护页 UPDATES 从「未实现」改为「已实现 + 跳转 `ext/update`」——
  ⚠️ `IMPLEMENTED` 必须与 `settingsNav` 的 `upstream.items` **逐字一致**
  （裸 `Check for updates` 匹配不上带中文括注的那条，是新 spec 抓出的真缺陷）。
- 交付：退避重试 / 启动即检 / 更新前自动备份 / 引导式开启（V0.84.0，并行会话）。

### 第 85 期铁律（目录体系：本地「卷 / 段」+ 官方书城目录覆盖）

- **批次 A**：`core/reading_list.py` 是「卷 / 段 → 章」的**唯一真值源**（EPUB 路径与 TXT 路径都调它）；
  `detect.is_volume_title` / `is_unnumbered_title` 提升为公开判据；`library._reading_list` 标题三级回退
  （目录 → 文档自带标题 → 文件名）；前端 `lib/chapterGroups.ts` 卷折叠 / 缩进 / 段名。
- **批次 B**：`store_toc`（含负结果）+ `toc_map`（未映射的本地章节不入表）两表；
  `sources/toc_sources.py` **只取目录、绝不取正文**；`GET /api/toc/sources` / `POST /api/toc/fetch`（失败也落库）
  / `DELETE /api/toc/{bid}`；配置 `download.toc_enabled`（**默认关闭**）+ 闸门加**用途维度**。
- ⚠️ 番茄 / 起点两条内置规则**未在本机验证**（`verified=false`，界面标「未验证」）⇒ 需在联网环境用
  「试取目录」核对后把注册表里的 `verified` / `status` 回填。微信读书 / 掌阅 / 晋江只登记。
  **第 91 期已真机核过（结论见下文第 91 期铁律）**：番茄 `/page/<书号>` 可用而 `/search?query=` 404、
  起点两条路径都返回反爬挑战 ⇒ **两条仍留 `verified=false`**，`status` 不动（一个布尔说不清「哪一半可用」）。
- ⚠️ 踩坑：私有 helper 重名覆盖（`_tag_text`）让 82 条无关测试连锁失败 ⇒ **必须跑全量**；
  happy-dom 的 `isVisible()` 测不出 `v-show`（改断言 `style.display`）。

### 第 86 期铁律（书源体系对齐 legado/Mihon + 书籍追更）

- 16 条书源接口（导入差异预览 / 台账 / 登录凭据 / 单源与全部验证 / 批量）全部有界面入口（工具页「书源工具」）。
- **章节级追加**已落地：`core/epub_update.append_chapters` + manifest/spine/nav/ncx 插入 + `verify_unchanged`；
  `manager.update_lock` **按路径加锁**（不加锁会「后写覆盖前写 = 丢章且两边都报成功」）。
- ⚠️ nav 定位加固：必须先在 `epub:type="toc"` 的 `<nav>` 里取**最后一个** `</ol>`，否则新章被插进「地标」列表
  （阅读器目录里看不到，而「nav 含该链接」的断言照样过）。
- `core/autoupdate.py`（骨架照抄 `updater.py`）：**默认开启**、每 12h、串行 + 限量 + 逐本节流、**首轮延迟一个间隔**、
  **只调 `update_report`**；手动轮**必须**与定时轮共用 `autoupdate.tick`。
- ⚠️ 测试不能真让 `stop.wait(interval)` 等（最小 1h）⇒ monkeypatch `stop.wait` 让前 N 次 False。
- ⚠️ `auto_update` 配置三处登记（第 86 期补）—— 没它「关掉追更」在界面上不可达（假开关）。

### 第 87 期铁律（`.zip` 内容分派 / 重名重构 / 格式能力矩阵）

- `core/zipkind.py`：`analyze(path)` 分档 `comic`/`epub`/`pdf`/`nested`/`multi`/`mixed`/`empty`/`broken`，
  每档给 `reason` + `evidence`；`.zip` 的 `format` **归一成真实形态 `CBZ`** ⇒ 上层零分支；
  判不出留 `ZIP` + `unparsable=True`（进「待修复」分面，不假装能读）。
- **展开（unwrap）成真正的书**：只在容器所在目录落文件 · 原子写 · **绝不覆盖已有文件**（不改名，改名换 `book_id`）·
  **默认不删源** · zip-slip 防护。
- 修 3 处静默失败：① 服务端抓取封面只对 EPUB 生效（读取提到格式分支**之前**）② OPDS 不给目录型条目
  广告必然 404 的下载链 ③ 前端「无封面」分面改成「没有封面」即命中。
- 重名判据收敛：`conflict_key` / `volume_of` / `is_copy_name` / `conflict_kind`（**纯函数**）；
  ⚠️ 与 `norm_key` 分工**不能合并**；结论分级 `duplicate_scan`（默认不勾，改名是错的）/`cross_library`/`same_name_different_dirs`；
  ⚠️ **不改 `book_id` 生成规则**（改了 = 全库迁移）。
- `docs/format-capability-matrix.md` + `tests/test_format_matrix.py`：**任何「只给部分库」的能力键都必须在
  `EXCLUSIVE` 表里登记理由**，否则测试红（写理由的过程本身会暴露漏配）。
- 窄屏：`ToolsLayout.vue` 内容区 `overflow-x-auto` + 内层 `min-w-[32rem]`（**宁可横向滚，也不压成一字一行**）。
  诊断脚本 `.codebuddy/tools/diag-narrow.js`（高窄盒子探测器，**必须用文件传入**，命令文本里的双引号会被工具层吃掉）。

### 第 88 期铁律（书库加载慢：请求路径 + 前端感知 + 分页）

- **契约变更（有意）**：`library.invalidate()` 之后**下一次读**由「**同步**增量刷」改为
  「**派后台刷新 + 最多等 `catalog.SETTLE_WAIT=0.25s`**，到点如实返回现有索引」；
  可见性改由前端轮询补（`/api/books` 的 `scanning` + `GET /api/libraries/scan-state`）。
  想「一刻不等」把 `SETTLE_WAIT` 置 0，**但必须同时**把「写后立刻读」那批用例改成轮询语义。
- ⚠️ **显式扫描路径一律保持同步**（`refresh_library(force=True)` / `POST /api/libraries/{lid}/scan` / watcher）
  —— 硬约束，不许动。
- 启动后台预热 `prewarm_async`（只针对索引非空的库）；`/convert`、`/convert-path` 入库后补 `invalidate(lid)`；
  `refresh_library` 计时日志（>300ms 才记一行）。
- ⚠️ **`library.invalidate()` 有 20+ 调用点，不要在它里面点火**（试过接线 `invalidate_and_refresh`，会让后台刷新与调用方
  紧接着的读断言赛跑 ⇒ flaky；已删除并留注释说明）；点火点收敛为三处：读路径 / 启动预热 / 监听线程。
- 前端：新 `components/ui/Skeleton.vue`；空态判据改为「**非 loading 且真无数据**」（此前数据在路上却显示「这个书架还是空的」）；
  错误态与重试；「正在建立索引…」进度条；阈值并行；次要请求懒化；`request()` 超时与分类错误（GET 仅网络错重试一次）。
- 分页/无限滚动：`/api/books` 可选 `limit`/`offset`（**不传=全量逐项兼容**；按**字符串**收再自己解析，声明 `int` 会被 422 拒；
  负数/非数字 400；`total` 恒为切片前总数；切片在排序之后；`limit=0`=不限；`offset` 越界 ⇒ `items=[]`+真实 total+`has_more=false`）。
  前端页大小 **120**；⚠️ **分页状态必须与全量 `books` 彻底分离**（`shelfLoadedBooks` / `loadShelfFirstPage` / `loadMoreShelfBooks` /
  `autoLoadMoreShelf` / `resetShelfQuery`，**只有 `ShelfView` 读**）—— 直接建在共享 `books` 上会让侧栏计数、仪表盘部件、
  浏览页、智能书架计数**全部只见前缀**（600 本显示成 120），而**没有任何既有 spec 覆盖**。
  另：`patchProgress` 必须双数组回写；数据变更后统一 `refreshBooks()`。
- ⚠️ 事故教训：**子代理「被取消」≠「已停止」**（超时被取消后进程可能继续跑并与新代理并发改同一工作区）⇒
  取消后先 `git status` + 看 mtime 确认工作区静止；**同一工作区同时只派一个会写代码的子代理**。

### 第 89 期铁律（TXT 上传假报错 + 正文不乱码）

- **上传假报错的根因**：`BookDock` 的上传走 `api.convertDrop` → 用的是 `request()`（JSON），而 `POST /convert` 返回
  `FileResponse` 文件流 ⇒ `res.json()` 把文件字节按 UTF-8 解出 `�`、V8 抛 `Unexpected token '�'`；**书其实已入库**
  （等一会自己出现）。修法：`api.ts` 新增 **`requestAck()`**（同一套鉴权/超时/401/错误剥壳，但**不解析响应体**并
  `res.body?.cancel()`），`convertDrop` 改用它。⚠️ 全仓「返回文件流/非 JSON 的接口」调用点里**只有这一处坏点**
  （其余走 blob 或 `<a href>`）。
- **解码不再静默丢字节**：`ENCODING_RULE_VERSION` **1 → 2**（`pipeline.py`，`txtcache.ENC_RULE_VERSION` 跟随 ⇒ 存量派生件自动重建）；
  新增 `_choose_encoding()`（**确定性证据优先**：UTF-32/UTF-8/UTF-16 BOM → 无 BOM 像 UTF-16 → UTF-8 前缀自证 → gb18030/big5hkscs/big5 打分）
  + `decode_file()`（候选**逐个严格试解**，坏字节以 U+FFFD 顶替并**计数/记偏移**，返回 `{encoding, undecodable, positions}`）；
  `txtcache.decode_info()` + 派生件 `state.json` 增 `encoding`/`undecodable`；章节接口**新增** `text_encoding`（只加不改）；
  阅读器在 `undecodable > 0` 时显示低调提示。全仓 `errors="ignore"` 只剩注释、**无一处可执行代码**。
- ⚠️ **无 BOM 的纯中文 UTF-16 仍不可判**（两字节都不为 0，与随机字节无从区分）—— 已如实写明。
- 测试：`tests/test_txt_encoding_bytes.py` 11 例（修前 BOM/UTF-16 那几条是红的）+ `frontend/src/lib/convertUpload.spec.ts` 5 例（登记 `EXPECTED_SPECS`）。

### 第 90 期铁律（窄屏外壳侧栏：抽屉 / 图标条 / 拖宽 / ⌘B）

- **形态照「视口宽」分三种**（判据只有 `lib/viewport.ts` 的 `NARROW_QUERY = '(max-width: 639.98px)'`，
  **不用**上游的 768 —— 本仓 640–767 要保持两栏）：**≤640px** 抽屉（`ui/sheet`，宽 `18rem`，`Teleport` 到 body、
  遮罩 `bg-scrim`、Esc / 点遮罩可关、点导航项自动收）；**展开**（默认 **240px**，可拖 **224–480**）；**折叠**（图标条 `3rem`）。
- **折叠态 / 宽度 / 窄屏判定的唯一真值源 = `ui/sidebar/SidebarProvider.vue`**（`useSidebar()` provide/inject）。
  `stores/ui.ts` 的 `sidebarCollapsed` / `toggleSidebar` **已删**（契约 `test_frontend_unit_contract.py` 里两条新断言钉住：
  ui store 不许再长出这两个名字；`lib/prefsPayload.ts` 的 `PAYLOAD_BLOCKS` 不许出现侧栏块）。
  ⚠️ 这两条契约**先剥 JS 注释再断言**（`_strip_js_comments`，字符串感知）—— 那两个文件的抬头正在逐字解释
  「为什么不放进同步块 / 删掉了什么」，不剥会被自己的说明绊倒。
- ⚠️ **侧栏偏好只落本机**（`lib/sidebarPrefs.ts`，键 `nf_sidebar_collapsed` / `nf_sidebar_width`）：
  宽度是**屏幕**属性不是人的偏好（27 寸拖到 420px、平板就该是抽屉）⇒ **刻意不进** `server.PREFS_BLOCKS`。
  `nf_` 前缀防同域部署时与上游 BookOrbit 撞键。
- ⚠️ **默认宽度 240 不是上游的 256**：跟上游改会让**每一个宽屏用户**的开箱布局动一下 —— 那是回归不是对齐。
  上游的 `SIDEBAR_WIDTH = '16rem'` **故意不搬**（本仓 `widthPx` 是从 localStorage 同步读出的，那根 CSS 变量永不缺席）。
- ⚠️ **折叠态宽度的类必须挂在 group 元素上**（`data-[collapsible=icon]:w-(--sidebar-width-icon)` 是**自身**选择器）；
  挂到内层卡片上不报错，只是「中间一小撮图标、两边一大片空白」。
- **Rail 的 3px 阈值只决定「松手算点击还是拖拽」**，**不拦宽度**（位移多少宽度就跟多少；拦了手感会「先不动、过了 3px 突然跳」）。
  折叠态**不认**拖拽（松手退化成点击 ⇒ 先展开）。
- **⌘/Ctrl+B 与 ⌘K 各管各的键**：写成「有 meta/ctrl 就开合」会让 ⌘K **同时**弹搜索并收侧栏。
- ⚠️ **取侧栏菜单行认 `data-sidebar="menu-button"`，别认 `data-slot`**：带 tooltip 时行被塞进 `TooltipTrigger as-child`，
  触发器的 `data-slot="tooltip-trigger"` 会**顶掉**行上的同名属性（上游同样如此）。
- ⚠️ **写抽屉/浮层的 spec 要等 reka 的两处异步**：点击外部的 `pointerdown` 监听器要等 `watchEffect`（微任务）
  **再排一个 `setTimeout(0)`** 才挂到 document；卸载还要多等一拍（`usePresence` 里有一次 `await nextTick()`）
  ⇒ `sheet.spec.ts` 用三轮 `settle()`（宏任务 + 双 `nextTick`）。等少了会把「关得掉」误判成「关不掉」。
- ⚠️ **reka 不写 `aria-modal`**：模态语义靠 `useHideOthers` 给 body 其余子树打 `aria-hidden` ⇒ 断言认这个。
- ⚠️ **happy-dom 的 `matchMedia` 不跟着窗口尺寸触发 `change`** ⇒ 「跟随变化」这条最该测的行为反而测不到，
  两份 spec 各自装了可控桩（`available:false` 用**赋值 `undefined`** 模拟不支持，`delete` 删不掉原型方法）。
- **`ui-smoke` 用法坑（本期实测）**：`-Routes '#/a','#/b'` 经 `.cmd` 转发后逗号被吃成**一个**元素 ⇒ 变出一条
  `#/a,#/b` 的假路由（度量到的是 404 页）；**一次只传一条路由**。git-bash 下还要防 MSYS 把 `#/…` 改写成
  Windows 路径（`MSYS2_ARG_CONV_EXCL='*'`）。`-Widths` 同样只能用空格分隔。
- **验收只看 `off`**（`ovf=false` 是假象：溢出被内部横滚容器吸收）。本期实测（实例 8993）：
  `#/shelf` 360 档 **27 → 3**、`#/tools/sources` 360 档 **38 → 16**；768 / 1280 `off=0`。
  **残留两处都不是本期回归**：① 顶栏右侧图标行固定 **375px**（10 个 33px 圆钮）> 360 档顶栏内容盒 **334px**
  ⇒ 最右三个（外观/设置/头像）被 `overflow-x: clip` 裁掉 —— 顶栏第一个按钮换成 `SidebarTrigger` 时**尺寸逐字未变**（32×32，
  已 `git show HEAD:…/AppHeader.vue` 核对）；② 工具页自己的 `min-w-[32rem]`（第 86 期「可用但不优雅」口径）。
  两者都要先定交互口径（上游顶栏同样 11 项，**没有**可照搬的窄屏范式），已记进 `docs/TODO.md` 第 3 节。


### 第 91 期铁律（TODO 台账 / 401 探测归零 / 来源权重 / 窄屏「更多」/ 浮层键盘）

- **`docs/TODO.md` 只放「还没做的」**：完成的**只留一行索引**（期号 | 一句话 | 版本/指针），细节一律进
  `docs/roadmap-gaps-remaining.md`；每条待办必须**带证据**。历史详情**删除不迁移**（roadmap + CHANGELOG + memory 已是完整真值源，
  在 TODO 里再抄一遍只会让「当前还剩什么要做」淹没在历史里）。唯一例外是**仍然生效的语义**
  （「移除书库」零文件触碰 /「删书」回收三份 → 指针指 `AGENTS.md` 第 1 节）与**用户侧遗留动作**（待用户线上点一次还原）。
- ⚠️ **未登录探测归零的真正机制（第 91 期逐行核对，与旧 TODO 描述有出入）**：`stores/auth.ts` 的 `token`
  在 store 构造时**同步**读 localStorage ⇒ `auth.authenticated` 在 `App.vue` setup 期就已知 ⇒ `showLogin` 的**初值**
  可以直接写 `ref(!auth.authenticated)`（已登录用户冷启动**不多等**一次 `api.me()`）。
  但**只改初值只能 12 → 2** —— `App.vue` 里 `tasks.refresh()` 与 `library.loadLibraries()` 是 **App.vue 级、
  不受 `v-if/v-else` 控制**的，无条件发请求 ⇒ 必须抽 `bootstrapShell()` 并**只在「未弹门禁」时调用**。
- ⚠️ **`LoginGate` 的 `@authed` 回调必须同批复跑 `bootstrapShell()`**：漏了**不报错**，只是登录后任务轮询与书库
  **永不启动**（界面看着正常、只是永远是空的）—— 静态契约钉住（`tests/test_unauth_probe_contract.py`）。
- **诚实边界（刻意不修）**：localStorage 里**有 token 但已失效**时，外壳仍会先挂载并发一轮探测，随后 401 把门禁弹出来。
  修它就得让**已登录用户冷启动也等一次 `api.me()`** —— 本期口径只承诺「**从未登录过 / 清过 localStorage 的访客 = 0 个 401**」。
- ⚠️ **测量 401 别用 `performance.getEntriesByType('resource')`** —— 该 API **拿不到 HTTP 状态码**。
  数 **uvicorn 访问日志里的 `401` 行**。另：改了前端**不跑 `deploy` 就是测旧 bundle**（本期第一次测出 13 全是假象）。
- **来源排序的唯一真值源仍是 `metasources.reorder_for_language()`**：加可选 `weights` 后排序键 `(-weight, language_tier(...))`；
  **归一只有 `metasources.weight_of()` 一处**（缺省 / 非法 / 负数 / 未知 id 一律 → `0` = 不干预）。
  ⚠️ **权重全为 0 必须与改动前逐字一致** —— 靠 `sorted` 的**稳定性**保档内用户顺序，写成用例，别改成会打乱档内顺序的写法。
  配置键 `metadata_fetch.source_weights` 走**三处同步点**（`config.DEFAULTS` ↔ `server.EDITABLE["metadata_fetch"]` ↔
  `_mask_metadata_fetch`）；漏 `DEFAULTS` 会让「恢复默认」丢键。
- ⚠️ **窄屏（≤640px）顶栏的 7 个入口是「唯一入口」**（第 65 期已从侧栏撤掉）：数据统计 / 任务 / 工具 / 阅读记录 /
  阅读活动 / 成就 / 设置 —— 收进「更多」**不是隐藏**，`v-if` 写错就变成「窄屏没法进设置 / 任务」。
  判据必须用 `useNarrowScreen()`（`lib/viewport.ts`，**不另写断点**），用 `v-if/v-else` 而**不是纯 CSS 隐藏**
  （面板 `Teleport` 到 body，CSS 藏不住，且会变成 JS/CSS 两份断点）。
- ⚠️ **浮层菜单（`ui/DropdownMenu.vue`）的键盘契约**（第 91 期补的真缺陷：面板为躲裁切 `Teleport` 到 `<body>` 末尾，
  代价是 **Tab 序排在整个页面之后**，`Esc` 也**无人监听**）：打开即入焦第一项、`↑`/`↓` 循环移动、
  **`Esc` 关闭并把焦点还给触发器**、**`Tab` 也关闭**（`preventDefault` —— 否则焦点会走到浏览器 chrome）。
  契约写在**共享组件**里 ⇒ 书卡的 ⋮ 菜单一并受益。⚠️ spec 必须 `attachTo: document.body`（游离 DOM 上
  `document.activeElement` 恒为空）；`press()` 要 await 一拍否则面板还挂在 DOM 上会**假红**。
- ⚠️ **浮层里的 `Tab` 语义是「关闭 + 焦点还给触发器」**，不是「留在菜单项上」：先按后者写，实测焦点跑到触发器，
  复核确认**实现是对的** ⇒ **改断言，不改实现**。
- **同一服务端动作不该有两种客户端语义**：`LocalConvertView` 原先走 `convertFile` / `convertPath`（blob 变体，
  转完把成品**推回浏览器**），而收书目录页走 `convertDrop`（`requestAck`）⇒ 统一到 ack 链路
  （投递 → toast → 刷新），blob 变体**全删**。删公开 api 方法前**再 grep 一次全仓**（含 `*.spec.ts` 的 mock）。
- **`note` / 提示文案是纯文本插值**（`{{ … }}`）：`**` 与反引号会**原样**显示给用户 ⇒ 补契约
  「`note` 里不许有 markdown」（本期真在 `weread` 的 note 上踩了一次）。
- **番茄 / 起点目录规则的真机结论（第 91 期，经本机代理）**：番茄 `/page/<书号>` **可用**（匿名 SSR，
  内置正则逐字命中，实测一本 **550 章**全解析）但 `/search?query=` **404** ⇒ **一半通过一半不通过**；
  起点 `/so/…` 与 `/book/…/` 都是 **202 + 209 B `probe.js`**（反爬 JS 挑战）⇒ **两条都用不了**。
  一个布尔 `verified` 说不清「哪一半可用」⇒ **两条都保守留 `False`**，把实测结论写进 `note`（**不改 `status` 与 `verified`**，
  三条既有 toc 契约**零改动**）。
- ⚠️ **冒烟要看两层判据**：先排除 `overflow-x: auto|scroll|hidden|clip` 祖先内的元素，再做更严的
  「**超出视口 AND 被不可滚动的 `overflow:hidden|clip` 祖先裁掉**」复核 —— 第 90 期那个顶栏缺陷正是被
  `overflow-x: clip` 吃掉的，宽松判据会把它归成「可达」而漏掉。本期 4 页 × 360/768/1280 = 12 组全 0。
- **`online-fallback` 是独立一期**（第 91 期只写口径不动代码）：触发 = 本地读不了（未下载 / 格式不支持 / 文件缺失损坏）；
  共享按源登录态**必须**走 `DownloadManager.gate_reason()` 这唯一闸门；⚠️ 需用户先拍板的**合规边界**：
  渲染第三方页面必须**如实标注「这是源站在线页面」**、不得像在托管正文，只接公版 / 授权源。
- **跨语言检索词保持「未支持」**（口径写死在设置页）：① 翻译质量不可控、会推高「同名不同书」误配率；
  ② 各源语言内检索语义不同；③ 已有「按语种重排 + 手动指定来源」两条退路。已进 TODO 的「**明确不做**」区。
- **踩坑**：`window[m]('keydown', fn)` 过不了 `tsc`（字符串联合推不出 `KeyboardEvent` 重载）⇒ 拆成显式 `if/else` 两个调用；
  `POST /api/libraries` 内联 `-d` 带中文必炸 ⇒ 写文件 + `--data-binary @f` + `charset=utf-8`；
  `/api/books` 的键是 **`items`** 不是 `books`；**`/tools/convert` 是 404 路由**（真路由 `/tools/local`）；
  `json.load(sys.stdin)` 会按 **cp936** 解码 ⇒ 先 `sys.stdin.reconfigure(encoding='utf-8')`（否则乱码 + `\udcXX` 孤立代理，
  写文件时 `UnicodeEncodeError`）；`nohup … &` 后台跑 pytest 中途死掉**却报 exit 0** ⇒ 长跑改前台 + 足够超时。

### 第 92 期铁律（工具页窄屏重排 / `off` 的正确读法 / 栅格里的 `min-w-0`）

- ⚠️ **`ui-smoke` 的 `off` 是「原始越界数」**（`.codebuddy/tools/ui-smoke.ps1:166-175`）：
  统计的是**有尺寸的交互元素**（`button,a,input,select,textarea`）里
  `rect.right > innerWidth+1 || rect.left < -1` 的个数 —— **不做任何祖先 `overflow` 过滤**。
  ⇒ 「元素在 `overflow-x-auto` 里、用户能横滑到」**照样计入**。**「反正能滑到」不算达标。**
  ⇒ 反过来也要记住：`clippedUnreachable` 那个**更严的复核判据在脚本里并不存在**，
  它只是 roadmap 里描述过的口径（要排除 `overflow-x|auto|scroll|hidden|clip` 祖先再判）。
  **验收一律看 `off` 原始值**，别自己发明一套宽松口径。
- ⚠️ **`ovf=false` 不是「没问题」的证据**：横滚容器把溢出**吸收**了，页面永远不出现横向滚动条。
  这类缺陷**不报错、不加日志、测试全绿**，只有真按目标宽度量一次才看得见。
  所以「窄屏有没有溢出」这件事**只能实测**，不能靠读代码拍胸脯。
- ⚠️ **工具页外壳（`views/tools/ToolsLayout.vue`）一律不许出现横向滚动**：
  第 86 期留下的两处 —— 内容区 `min-w-[32rem]`（512px 下限）+ 标签条 `overflow-x-auto` ——
  在 360 档分别造成「184px 常驻视口外」与「尾部标签滚出去」，合计 `off=13`。
  加 `min-w-[32rem]` 时的立论（窄屏侧栏仍常驻 240、内容盒只剩 82px、中文被压成一字一行）
  **第 90 期起已不成立**（窄屏侧栏改成抽屉）⇒ 它只剩「内容比视口宽」这一个效果。
  **契约 `tests/test_tools_layout_contract.py` 把这两条钉住**（断言前**必须先剥 `<!--.*?-->`** ——
  模板注释里**逐字**写着这两个类名，不剥会被自己的说明绊倒）。
- ⚠️ **工具页标签条的窄屏形态：`flex-wrap` + 原生 `<select>`，不做固定断点。**
  标签条 8 项约 **672px**，而**侧栏宽度用户可拖 224–480** ⇒ 「到某档就换控件」**算不准还剩多少位置**
  （`md`/`lg` 都会在某个侧栏宽度下失效）。`flex-wrap` 没有魔数、任何宽度都不溢出，
  且在装得下时**完全惰性**（≥1024 逐字与单行一致）。
  ⚠️ 但 `flex-wrap` 只保证「不溢出」**不保证「好看」**：360 档 8 项会折成 **3 行 / 132px**，
  所以才补了窄屏（`sm:hidden`，与 `lib/viewport.ts` 的 `NARROW_QUERY` **同档**）的原生下拉。
  **换控件 ≠ 隐藏**：下拉与标签条必须渲染**同一份** `visibleSections`（契约钉「恰好 2 处」），
  否则「换个宽度就少几个入口」且不报错（第 91 期顶栏「更多」那条的同一形状）。
- ⚠️ **`<input>` / `<textarea>` 进栅格或 flex 轨道时必须带 `min-w-0`**：
  `w-full` **单独不够** —— `<input>` 的固有 min-content 宽度约 **150–180px**（HTML 的 `size=20` 默认值），
  而 grid item / flex item 的 `min-width: auto` 取的就是这个固有宽 ⇒ `grid-cols-2` 的两轨合计
  会**撑破容器**（`SourcesView` 的四个选择器就是这一处）。宽屏有富余时 `min-w-0` 是 no-op。
- **窄屏结论只能用「有真实数据的实例」量**：本期用的是用户提供的 8412（4 本书目）。
  改前先量（`docs/TODO.md` 记 `off=16`、本期实测 **13**，数据 / bundle 不同）——
  **别拿文档里的历史数字当验收基线**。
- **踩坑（写断言时最容易白写的一条）**：Python 正则里
  `re.escape(attr) + r"\b"` 对 `role="tablist"` 这类**以引号结尾**的属性**永远不匹配** ——
  `\b` 要求**词字符**边界，而 `"` 与后面的空白都不是词字符。去掉 `\b` 即可。
- ⚠️ **Tailwind v4 扫的是「原文」，不是「DOM」**：源码里任何位置出现类名字面量都会进 CSS，**包括注释与字符串** —— 第 92 期在 `ToolsLayout.vue` 的模板注释里写了「这里曾经是 `min-w-[32rem]`」，构建产物 `assets/index-*.css` 里就真的多了一条 `.min-w-\[32rem\]{min-width:32rem}`（死规则，约 40 B，无 DOM 消费方）。⇒ ① 在 Tailwind 项目里**别在注释里写类名字面量**（想说明就改述，如「32rem 的最小宽度类」）；② 反过来 `grep` 构建产物**不能**证明「某类还在用」。
- ⚠️ **配套的自检盲区**：契约测试用 `_strip_html_comments()` 剥注释后才断言「不许再出现」，所以**测试全绿 ≠ 注释干净** —— 这两件事要分开看。

### 第 93 期铁律（在线阅读 / 章节缓存 / 跨客户端进度 / 自动落地）

- ⚠️ **正文净化的唯一实现 = `sources/rules.html_to_text`**（第 93 期从**三份**收敛成一份：
  `online` 一份、`rules._extract_css` 一份、追更一份）。`sources/online.html_to_text` 现在只是**再导出**；
  要改净化行为就改那一处。
  **踩坑（真机走查逼出来的）**：`BeautifulSoup.get_text("\n", strip=True)` 会把**内联**标签也切成独立行
  —— 分隔符对**每个子节点**都插一次，于是 `<b>加粗</b>` 这样行内的东西被拆成三行；而 `strip=True`
  又会把补上的分段标记一并吃掉（实测 `get_text("", strip=True)` 返回的是一行糊在一起的文本）。
  ⇒ 正确写法：`get_text("")` + **逐行** strip 去空 + 只给 `_BLOCK_TAGS` 白名单里的**块级**标签补分段。
  判据一句话：**内联标签只剥标记、不断段**。第一次修错方向（改 `online`）时症状**一字不变** ——
  真正的源头在上游 `_extract_css`，这是「找到第二份拷贝」的活样本。
- ⚠️ **对齐要「求位移」，不能按同序号硬比**：本地章节表是 **EPUB spine 下标**
  （`library._reading_list`），而本项目自己下载的书 spine 首条是 **nav 目录页**
  （`epub_builder.build_epub` 默认 `nav=True`）⇒ **本地 index 恒比源站章号大 1**；
  源站目录里多一条「序章 / 版权页」时位移又是另一个方向。按同下标硬比 ⇒ **一本都对不上**，
  且**没有任何报错**（只表现为「进度不涨 / 落地不动」）。
  ⇒ 唯一判据 = `reading_list.align_shift`：候选位移由「本地每章的归一标题在线上目录里的同名位置」给出，
  逐个用用户那条 5 章规则验，**恰好一个**通过才采纳（两个以上 ⇒ `None`，有歧义不猜）；
  锚点从**本地末章往前退 `ALIGN_ANCHORS = 20` 章**（源站只改尾部个别标题时退几章仍能对齐）。
  `align_online(titles, local, pos)` 是逐章入口、`align_map` 整本一次求位移 + 纯算术映射
  （逐章问一遍是 O(章数) 的活）；`landing.aligned_tail` 用同一套 `norm_title`。
- ⚠️ **两份阅读位置故意不合并**（`reading_list` 与 `online` 的 docstring 都写明了，别「简化」）：
  `online_bind.pos` = **在线位置**（任何客户端打开 `/online/:id` 都从同一处续读的**唯一**依据）；
  `progress.locator/percent` = **本地位置**。对齐成功（`reading_list.align_online`：线上 `pos` 前后各 2 章
  共 5 章窗口里 `norm_title` 命中 ≥3）时**同时**写；对不上（`local_index === null`，**不是异常**）
  只写前者并在页内如实提示 ⇒ 把它当错误抛会让整章打不开。**前端只读服务端给的 `local_index`，绝不重算。**
- ⚠️ **在线读的写盘点限死在 `CACHE_DIR/online/`**（静态契约钉住，越界即红）；缓存上限
  **总量 200 MB / 单本 500 章**，超了按最久没碰过的先删（真 LRU）；**第三方标记永不进 `v-html`**
  （端点只回我们转义的 `<p>`，用例断言响应里不含源站标签与事件属性）；清缓存只清缓存目录。
- ⚠️ **自动落地走 `core/landing.py`，一律写进「这本书自己的位置」**（同名 ⇒ 同一个 `book_id`）——
  **绝不新建第二条书目**，否则第 87 期的重名判定会在书架上多出一本、而用户的进度还留在旧的那本上。
  `SYNC_AFTER = 5` 判的是 `len(seen) > 5` **且** `auto_task` 为空 ⇒ **只触发一次**（失败也不重试轰炸），
  且**不静默**（任务中心 + 通知 + `activity_log`）。
  `updatable()` / `update_writes()` 把既有事实钉住：**追更只写「收书目录里的原件」与「本项目在书库根里的
  成品」两份** ⇒ **用户自己导入的书换不到**（如实拒绝 + **零写入**，指路「用源站整本覆盖本地」）。
  **首次落地按「这本书自己的后缀」挑产物** —— 只看「stage 里唯一的产物」会把 EPUB 字节写进 `.txt`
  （TXT 阅读器显示一片乱码；真机踩到过）。
- ⚠️ **「覆盖」默认不是整本重写**：默认路径 = 追更的「只追加 + 原子写 + EPUB 按章 append」（进度/批注
  不错位）；整本重写只在①首次落地②用户显式点「用源站整本覆盖本地」（`overwrite=true` + 二次确认）时发生。
  **用户自己的源文件永远不写。**
- ⚠️ **闸门补齐**：`gate_reason()` 是**唯一**闸门。定时追更此前**完全不过闸门**（`download.enabled`
  默认 False 却照样逐本外呼）—— 第 71/80 期口径里点名的「假开关」的**第 4 个调用方**；同批还修掉
  两个一直静默的漏子：`DownloadManager()` **缺必填 `cfg`** ⇒ 每轮构造必抛、被吞成「构造下载器失败」
  ⇒ **定时追更从来没真正跑过一本**；候选枚举按「书库根 + 去后缀」找留档 ⇒ **正常部署一本都找不到**。
  现在「这本书来自哪个源」只有 `autoupdate.sidecar_of(book)` 一处（按 `config.INPUT_DIR` 找）。
- ⚠️ **新增含 `book_id` 的表 `online_bind`** ⇒ remap 四处同批改；书被软删后绑定不参与在线读。
- ⚠️ **`Esc` 收面板（阅读器）**：`ReaderView.onKeydown` 里**一次只关一层**（设置 → 笔记 → 目录）、
  关掉后把焦点**还给触发它的那个按钮**（`Button` 是单根组件 ⇒ 模板 ref 拿到实例、按钮在 `$el`）、
  **没有面板时不吞这个键**（`defaultPrevented` 仍为 false，别吃掉别人的弹窗）。
  ⚠️ 这段必须放在 `if (!paged.value) return` **之前** —— 滚动模式下没有翻页键，但面板一样得能关。
  真机实测的焦点序：Tab 第 **38** 下到在线来源横幅里的「打开源站页面」（焦点环 `outline: solid 2px` 可见）。
- **真机走查的方法论（本期三个缺陷单测全绿时都存在）**：桩书站要能造出「标题错位」（`wrong.txt`）与
  「章节数变化」（`count.txt`）—— 否则「对不上」和「断网」这两条最要紧的路径根本走不到；
  三个缺陷的共同形态是**不报错、不提示，只是结果不对**（内联标签被切碎 / 追更报「追加了 12 章」而文件
  逐字节没变 / EPUB 字节写成 `.txt`）。
  ⚠️ **PowerShell 5.1 把无 BOM 的 `.ps1` 读成 ANSI** ⇒ 脚本里写中文会变乱码、选择器静默失配
  （`button[title=目录]` 变成 `鐩綍`）⇒ 界面脚本**只写 ASCII**，中文用 JS 的 `\uXXXX` 转义；
  取 `agent-browser eval` 的结果要**先滤掉 `[agent-browser]` 那类信息行**再取最后一行，否则会吞掉真结果。

### 第 94 期铁律（书源导入 / 格式轴 / 转换诚实闸 / 引擎能力 / 安全层）

#### 一、用户这个 bug 的**形状**（会再犯，记住形状比记住这次改了什么更重要）

「**点了没反应**」= 后端**回 200 装成功** + 前端**不读错误字段** + 提示文案自己编。
第 91 期（未登录 401）、第 93 期（追更报「新增 0 章」）、本期**同一个形状出现三次**。
判据：**任何「用户动作 → 结果」的路径，都必须在界面上给出与后端结论一致的一行字**；
接口**不许**用 200 表示「我拒绝了」。三条导入入口（`/api/sources`、`/api/sources/upload`、
`/api/sources/import`）已收敛到 `sources/intake.py` 一条解析路 —— **再加导入通道就加到那里，别在 `server.py` 里另起判据**。

#### 二、格式轴与执行轴**正交**（加格式不改执行层）

- **执行模型仍是 native schema**（`rules.py` 顶部 docstring 那一份），
  `sources/model.py::UnifiedBookSource` 只是它的**类型化契约**（`to_native()` 是恒等函数），**不是第三套模型**；
- `sources/formats/*` 是**格式轴**：只做 `sniff` / `parse` / `map` / `serialize`，
  **绝不产出第二套可执行结构**；`base.REGISTRY` 是**执行轴**。两条轴**不合并、不互为第二实现**。
- `legado2` 适配器**不写第二套 convert** —— 它只调 `legado.normalize_legacy()` 做**键名归一**，
  再交给 `legado3` 那**唯一**一份转换。`legado.detect_format` 是 JSON 类格式 sniff 的权威实现。
- ⚠️ `ledger.plan` 里的条目级分派**只在格式轴**（`formats.map_entry`）；
  历史上那句内联判据 `"name" in ent and "domains" in ent` 与 native 适配器的 sniff 是同一件事的两份实现，已删。

#### 三、转换诚实闸（本期的核心，别绕过）

- **「引擎能执行什么」唯一真值源 = `rules._MODES` + `rules.audit_native_rule`**。
  `legado.analyze` 的 `supported` **由它反推**。改判定能力就改那一处，**不许让 adapter 自称可用**。
- 每新增一项执行能力，就**从 `_UNSUPPORTED_CONSTRUCTS` 里摘掉一条**并补用例
  ⇒ 单调变诚实，不会先松后紧。
- 实测收益：22 条真实 3.x 样本上「假可用」从 **6/9** 降到 **0**。
  ⚠️ 副作用是**被判「可用」的源变少**（`yes` 9 → 2）——这是**修正**，CHANGELOG 与界面都要说清楚。

#### 四、`field_report` 与 `unsupported_fields` **分工不同，不许合并**

- `unsupported_fields` 是**判定依据**（决定 `verdict` / `supported`）；
- `field_report` 是**交代**（这条源里每一项都去哪儿了：`executable` / `ported` / `unsupported` + 原因 + 出路）。
- ⚠️ 把「发现页不支持」塞进判定依据，2.x 真实样本里带发现页的 **1321 条源会全部被判死** ——
  **把「如实说」做成「误杀」**。用例 `test_发现页只进报告_不进判定依据` 钉住这条边界。
- 表外的键**走兜底不静默丢**：不猜含义，但见了就说「本项目不使用这个字段」+ 给出去哪儿手写等价规则。
- ⚠️ **接口白名单会吃掉新键**：`server._IMPORT_ROW_KEYS` 漏了 `field_report` 时，
  接口上就是拿不到（界面上「字段明细」永远空）——**加行键必须同批加白名单**。
  native 行也要有 `field_report`（空列表），否则前端 `r.field_report.length` 会炸。

#### 五、⚠️ **重建响应体必须摘掉描述传输实体的头**（本期最贵的一个缺陷）

`network._send_capped` 给响应体加上限时需要**重建 `httpx.Response`**。重建时手里拿到的
**已经是解压后**的字节，若仍带着 `Content-Encoding: gzip`，httpx 会**再解一次** ⇒
`DecodingError: incorrect header check`，**所有开压缩的真实站点全部抓不到**。
⇒ 唯一实现 `_drop_entity_headers`（同时摘 `Content-Length`：`Response._prepare` 会按新 body 重算）。
**这个缺陷单测 100% 绿**（桩站返回的正文从不压缩），**只有真网跑一次才会现形**。
判据：**凡「重建 / 包装响应或流」的改动，收尾必须拿真实地址核一次**。

#### 六、收敛掉的单一真值源（九处，出现第二份 = 缺陷）

1. 选择器解析：`legado` 的 mini 解析器（`@text`/`@html`/`@attr(x)`/`||`/`&&`/索引 `!n`·`.n`）；
2. URL 选项字典：`parse_url_spec`；
3. `##` 替换：`_apply_regex_replace`（字段里的 `##` 与 `ruleContent.replaceRegex` 共用）；
4. 编码探测：`pipeline.decode_bytes`（`decode_file` 重构为「读字节 + 解码」两个入口，**一份实现**）；
5. 执行期正则：`core/saferegex`（书源执行路径不留裸 `re.compile`；规范类常量正则仍用 stdlib）；
6. JS 沙箱：`core/jssandbox`（规则默认走它；Node 通道只为既有契约保留并标「非沙箱、legacy」）；
7. SSRF 判据：`urlguard.ip_scope()`；
8. 能力判定：`rules._MODES` + `audit_native_rule`；
9. 导入路由决策：`intake.sniff_and_adapt` / `rows_from_payload`。

#### 七、安全层的**边界与残余风险**（写进文档，别当已经解决）

- **URL 导入是本项目唯一让用户提供地址的出网点** ⇒ 单独设闸：只放行 http/https、
  域名解析出的**每个** A/AAAA 都必须是全球可路由（内网 / 回环 / 链路本地一律拒）、
  **重定向逐跳复查**（关自动重定向手动跟随）、拒了给原文。默认**关闭**（`source_import.url_enabled`）。
- **残余 TOCTOU**：DNS rebinding 用「连已校验 IP + 保留 Host」缓解，理论窗口仍在 —— **如实记录，不声称已解决**。
- **`verify_tls` 默认不改**：书源抓取**保持 False**（改默认 = 静默改变既有行为，很多源站证书不规范）；
  **URL 导入那条路强制 True**（它没有历史包袱），但同样可显式关掉。
- **`url` 导入的 `dry_run` 默认为 true** —— 先给差异表再落盘，别在调用侧默认成 apply。
- **永久 unsupported（UI + 审计双处如实标注）**：Android 专有桥（`java.*` / `source.*`）、
  发现页（`exploreUrl` / `ruleFindUrl`，项目无此功能）、二维码导入、由客户端提供章节 URL。

#### 八、配置与测试的坑

- **三处同步点**（本期的 `source_import` 段与 `network` 新键）：`config.DEFAULTS` ↔ `server.EDITABLE`
  + `GET /api/config` 硬编码键列表 ↔ 前端 `settingsFields.ts` 的 `FIELDS` / `SECTION_KEYS`。
  漏一处 = **假配置**（界面上能存、代码里没人读）。
- ⚠️ **`POST /api/sources/import` 吃的是 `payload`（不是 `content`）**；带中文的请求体写文件 +
  `--data-binary @file`，否则 FastAPI 报 body 解析错。
- ⚠️ **auth 只能是 Bearer token**（`POST /api/auth/login` → `Authorization: Bearer …`）；
  cookie jar **不生效**（401）。
- ⚠️ 调 `ledger.plan` 的用例必须带 **`isolated` fixture**（它要读库判冲突，否则 `sqlite3.OperationalError`）。
- ⚠️ **测试夹具别用 `A | {nested}` 浅合并**（字典合并是**覆盖**）—— 会把整个 `ruleToc` 换掉，
  于是「主链可执行」那组拿到一个没有 `chapterList` 的条目。
- ⚠️ **quickjs 只有 cp38–cp312 的预编译包**：`requirements.txt` 里的 `python_version < "3.13"`
  标记不能少，否则 3.13+ 开发机 `pip install -r requirements.txt` **整条失败**。
- ⚠️ **不认识的 python 进程一律不 kill**（本机并行跑着别人的实例）—— 只 `TaskStop` 自己的 task id。

#### 九、刻意不做 / 等样本（**不猜、不写桩、不做空壳**）

- **四类格式**：`.js` / `.xbs` / XML / 纯文本规则 —— 两个候选 URL 一个 404、一个 Cloudflare 403
  挑战页（拿到的 5,646 字节是 HTML）。按用户口径「**没提供或提供格式错误的书源 ⇒ 不做**」，
  导入时给「无法识别格式：…」。**框架已就位，加 adapter 不改执行层。**
- **四个待样本参数**（1537 条真样本里统计到的）：以 `+` 开头的规则值 100 处、
  `:lt()`/`:gt()`/`:eq()` 9 处、编译不过的规则 17 处、2.x 的 JSON 搜索通道与 `{$…}` URL 模板。
- 二维码导入不做（本项目无客户端扫码通道）。

### 第 95 期铁律（`AGENTS.md` §7 工程原则 / 合规审计 / 旧路径清理 / 守卫）

#### 一、`AGENTS.md` 新增 §7「工程原则」—— 8 条 + **两条边界先写死**

8 条：① 不为向后兼容留路（旧实现删掉，不加兼容层 / 回退分支 / 迁移垫片）② 只做满足当前需求的最简实现
（禁投机性抽象）③ 分层生长（从端到端能跑的最小版本起步）④ 模块化 / 关注点分离 ⑤ 优先成熟库
⑥ 先查已有依赖再自己写 ⑦ 为长期做架构决策（不接受「先这样以后再换」）⑧ 先研究成熟产品怎么解。

⚠️ **两条边界**（防被误读成「可以删安全网」）：**数据安全语义不是兼容层**（软删除 / 回收站 / 源不可变 /
「移除书库只删登记」照旧）；**DB schema 迁移不是兼容层**（建表 / 加列 / `*_RULE_VERSION` 存量自愈照旧）。
§1 末尾有一行指针，且写明**冲突时以 §1 硬约束为准**。

#### 二、⚠️ 本机跑 pytest **必须先清空全部代理变量**（否则 45 个用例假失败）

`httpx` 0.28.1 的 `get_environment_proxies()` 解析 `NO_PROXY` 里的方括号 IPv6（`[::1]`）会生成
**畸变 mount** `all://*[::1]` ⇒ 任何真实 `BrowserClient` 用例炸
`httpx.InvalidURL: Invalid port: ':1]'`，实测一次性假失败 **45 个**（看着像大回归）。
**只去掉方括号不够，必须整组清空**：`HTTP_PROXY` / `HTTPS_PROXY` / `http_proxy` / `https_proxy` /
`NO_PROXY` / `no_proxy`。已写进 `AGENTS.md` §5。

#### 三、删功能要删干净 = **六处同批**（本轮删了两个端点，各补了一条 404 用例）

路由 + 模块/函数 + 前端 `api`/`store`/类型 + 文档 + 记忆 + **「接口 404」断言**
（体例见 `tests/test_api_smoke.py::test_格式分面接口已随零调用者移除`、
`tests/test_metadata_providers.py::test_旧元数据源接口已删除返回404`）。
⚠️ 半删状态（删了页面、接口还在 / 删了接口、前端还在调）**不会报错**，只会让人以为「这功能还在」。
本轮删掉的是：`/api/metadata/sources`（兼容端点）+ `has_googlebooks_key`（双写键）、
`/api/library-facets`（全链路零调用者）、`output.format`（含 `FORMAT_CHOICES`）、
`/api/metadata/probe` 的 `keys` 入参、`DownloadManager.update()`（只回 `Path` 的壳）、
`written: []`（恒空字段）、`notifications.merge_enabled/merge_window`（无界面出口的假配置）、
`LIBRARY_MODES`、`pipeline.chapter_regex` 死分支、`settingsFields.ts` 的 `libraries` 死条目。

#### 四、格式中文名**由后端下发**（前端不许再抄一份表）

唯一产出点 = `novelforge/sources/formats/base.py:format_label()`（此前零调用方）；
接口体新增 `format_label` 字段（`/api/sources`、`/api/sources/upload`、`/api/sources/import`、
`/api/sources/import-url` 四条路都带）。前端 `lib/sourceImport.ts` 的 `FORMAT_LABELS` 第二份表**已删**
（它 5 个键里已有 3 个与后端 `display_name` 悄悄发散）。⚠️ `sourceImport.spec.ts` 钉着文案，
改名字要同批改它。

#### 五、文件名安全判据**唯一实现 = `novelforge/core/filename.py`**（叶子模块）

`UNSAFE_CHARS` / `TRAILING_JUNK` / `strip_unsafe()`；`komga.clean_segment` 与
`fileops.sanitize_stem` 共用它。⚠️ 两者**「折不折叠内部空白」的差异是刻意的**（前者折叠、后者不折叠）——
别顺手「统一」。选**叶子模块**（只 import `re`）而不是让 `komga` 反向 import `fileops`，是为了不改
「`pipeline` 能直接 import `komga`」这条分层约束。

#### 六、版本号：兜底**不许是像样的版本号**

`server._read_version()` 读不到 `VERSION` 时曾回字面量 `"0.80.0"` —— 那会让「部署缺 VERSION」
**伪装成**「本应用就是那个版本」，而原契约只验「非空且 == APP_VERSION」⇒ 谁都不会发现。
现改为哨兵 `_VERSION_UNKNOWN = "0.0.0-unknown"`（error 级日志；`parse_version` 视作 `(0,0,0)` ⇒
更新提示照常）。`Dockerfile` 的 `ARG APP_VERSION` 也**去掉了写死的默认值**。
守卫：`tests/test_version_contract.py::test_没有第二份版本字面量`。

#### 七、视觉层：**组件里不许自创颜色**已有守卫

`tests/test_visual_tokens_contract.py`（扫 `.vue` 的任意值颜色工具类 `bg-[#…]` + `docs/DESIGN.md` §1
已作废的 `#2563eb`/`#6366f1`；带 `design-token-ok` 单行豁免）。配套的单一真值源：
- **「CSS 颜色变量 → 色串」= `charts.cssVarHex()`**（ECharts 不认 `var()`/`oklch()`，必须运行时解析；
  别在组件里再抄一份 `getComputedStyle` + 正则 —— 本轮就把一份这样的重写收敛掉了）；
- 热力图「一色多档」= `charts.chartShades()`；浮层遮罩 = `bg-scrim`；评分坡 = `--score-*` 四个 token
  （`docs/DESIGN.md` §4 的色板只有四个锚点，**原来第五档那个蓝是自创的**）。

#### 八、⚠️ **不要用 PowerShell `Get-Content -Raw` + `Set-Content` 改这些 UTF-8 文件**

为验证「守卫测试真的会红」，我用它临时改回一处 `bg-[#0f172a]/25` ⇒ **整文件中文被写坏**（17 行 mojibake）。
临时改动用 **python 脚本或 edit 工具**；已坏的用 `git checkout -- <file>` 还原后重做。

#### 九、子代理的产出**必须复核**（本轮两个都没交报告）

一个只改了 3 个 `.vue` 且**漏建**了要求的守卫测试；另一个**什么都没落地**；还有一个按要求「不许改
`charts.ts`」于是**绕道重写了一份** OKLCH 解析（违反 §7.1，父代理改为在 `charts.ts` 导出
`cssVarHex()` 一处实现）。⇒ 收尾一律以**工作区实际 diff + 全量回归**为准，**不信「子代理说做了」**；
审计结论也一样 —— 本轮 4 轴审计里有 **3 条被父代理复核推翻**（见 §十）。

#### 十、复核推翻了审计的 3 条结论（**审计报告也要复核**）

1. `comics.append_pages` **不是**「数据安全违规的死代码」：目标是本项目**自己的成品 CBZ**
   （`download_comic` 用 `write_cbz` 产出），且 `tests/test_append_media.py` 有 **6 个用例**钉它。
   真实性质是「第 86 期第 6 步的既定能力，**从未接线**」（同族 EPUB 分支 `append_chapters` 已接线）⇒ **保留未删**。
2. `cli.py` 的 `scan --interval` help「（保留参数…）」**没过期**：`scan` 设 `once=True`，`cmd_watch` 只跑
   `scan_once()` 就返回 ⇒ 该参数对 `scan` 确实无效。⇒ **撤销该条**。
3. `LIBRARY_SOURCE_DIR` **不能删**：Python 常量确实只被测试用，但它镜像的**环境变量回退**
   （`config.py` 的「未配置任何编号变量时回退单根」）是**真实部署模式**。

#### 十一、刻意未做（连同理由）

- **网页抓取改用 HTML 解析库**（`metasources.py` 五处抓真实线上页面）：硬规则是「能出网验证的就必须
  真的出网验证」，没有逐家真机核过就改选择器语义 = 拿「单测绿」换「线上未知」。**要做就单独一轮**。
- **EPUB 解析（`library.py` 的 OPF/NCX/nav）改 ElementTree：第 95 期做了、验证后回退了**。
  实测三处容错回归（截断 OPF 丢 `<metadata>` / 未定义实体让整份作废 / **未声明命名空间前缀丢全部元数据**），
  而 `lxml` 是**可选依赖** ⇒ 修它要么字符串手术、要么留两条解析路径，**都违反推动重构的原则**；
  换来的只是纯重构（用户可见行为零变化）却要动书库扫描热路径（§7.3）。
  ⚠️ 证据与结论写在 `docs/roadmap-gaps-remaining.md` 第 95 期段 + `docs/TODO.md` §1；
  ⚠️ **重试前先跑 `tests/test_epub_xml_parse.py`（5 例，与实现无关的容错契约）**。
  ⚠️ 加测教训：**别把某个实现的局限写成契约**（我原先断言「坏实体之后的字段读不到」，
  回退后实测旧正则照读不误 —— 那是实现定义，不是承诺）。
- **`fileops.py` 的 OPF 改写正则 → ElementTree**：改写的是**出版副本的 XML**，字节等价不可证。
- **[low] 四项**：`gate_reason(source=…)` 的不参与判定形参、`_source` 的冗余**写入**（读那一侧是
  外部回传 item 的**输入契约**，不能一起删）、`LIBRARY_SOURCE_DIR` 的 Python 别名、`/content` 端点
  （仓外消费者无法从仓内证明）。已记进 `docs/TODO.md` §1。
- **数据安全两处口径**（`zipkind.unpack` 的 `remove_source` 真 `unlink`；`landing` 自动落地支无二次确认）：
  用户未勾选该批次 ⇒ 仍待决策。⇒ **第 96 期已落地**（`remove_source` 改走回收站；「无二次确认」经复核
  **不是缺口**，真缺口是「覆盖不可撤销」）——见下一节。

---

### 第 96 期铁律（数据安全：覆盖 / 删源一律先 `publish.recycle`）

#### 一、**「删除」与「覆盖」是同一条纪律**（第 96 期立）

`AGENTS.md` §1 的「删除一律移入回收站、从不 `unlink`」**同样约束覆盖**：任何会摧毁用户既有文件的
写点，**写之前**先把被替换的那一份移入回收站（`core/publish.py:recycle` —— 落点名走
`fileops.recycled_name`、台账走 `db.recycle_note`、**永不外抛**），使「回收站还原」能把东西搬回来。
第 96 期补上的两条路径：`core/zipkind.py`（展开容器回收源容器，此前是全仓**唯一**一次真 `unlink`）、
`core/landing.py`（整本覆盖前先 park 被替换的 `dest` / `txt_dest`）。
`docs/architecture.md` 里那句「都走 `publish.recycle` —— 仍从不 `unlink`」到这一期才**覆盖全部写点**。

#### 二、覆盖前的回收必须**在写盘之前**，且失败要**中止**

`landing._first_landing` 的教训：原来的顺序是「先 `shutil.copy2` 盖留档 → 再 `replace` 盖书」，
所以**回收动作必须整体提前**，否则救回来的是刚写进去的新内容。为此：
`txt_dest` 只算一次；`dest` 与 `txt_dest` 用 `_same_path`（`normcase(resolve())`）**去重**
（单目录部署 / 就地库下两者**就是同一个文件**，回收两次会把刚写好的那份搬走）；
`_park()` 抛异常 ⇒ `_skip(...)` **中止整条落地**（此刻盘上零改动）—— 宁可如实拒绝，也不做不可撤销的覆盖。

#### 三、回收失败**不许静默**（两条路径都要如实回报）

- `zipkind.unpack` 返回值新增 `source_note`：回收失败时写明 `回收源容器失败（<异常>: <原文>），已保留原文件`，
  且 `source_removed=False`。旧代码在 `except OSError` 里只是**默默**把 `removed` 置 False。
- `landing` 侧失败即 `mode="skip"` + 原因原文进 `note`（任务中心看得见）。

#### 四、⚠️ 「无二次确认」**不等于**缺口 —— 先看用户口径再看审计措辞

审计把「`landing` 自动落地支无二次确认」记成数据安全缺口；但 `core/landing.py:3-6` 记录的
**用户 2026-10-03 原话**是「默认将本地书进行覆盖……需要书源自动搜索更新章节、自动下载、自动覆盖」
⇒ 自动覆盖是**用户拍板的产品行为**，不该加确认弹窗。**真缺口是「覆盖不可撤销」**，已用回收补上。
教训：读审计条目时要回到**原始口径**，别把「与我的直觉不符」当成缺陷。

#### 五、`.part` 是「半成品不进书架」的唯一机制

留档 txt 的复制改 `_copy_atomic()`（`shutil.copy2` 到 `.part` 再 `replace`）：`shutil.copy2` 直接写目标是
**原地写**，中途死掉会在**被监听**的收书目录里留半份 txt ⇒ 监听线程会把它当一本新书收进书架。
`*.part` 在 `config` 的 watcher 忽略清单（`watcher.ignore`）里，与 `sources/manager.py` 的留档写法同一手法。

#### 六、报告写实：显式覆盖**不是**「本地读不了」

`_first_landing` 此前无论哪条路都写「本地读不了（没有可读章节）」——`overwrite=True`（用户点
「用源站整本覆盖本地」）盖的往往是**本来读得了**的书。现按 `replacing_readable` 分支措辞，
并把「原文件 X 已移入回收站（可还原）」追加进 `detail`。

#### 七、守卫用例（钉行为，不钉实现）

`tests/test_zip_unpack.py`（16 例）：回收那份**逐字节一致**、台账 `orig_path` +
`recycle.plan_restore(...)["items"][0]["dst"] == str(p)`、回收失败时**原容器原样保留**、
接口层 `remove_source:true` 走回收。
`tests/test_online_landing.py`（24 例）：首次落地前 `ctx/坏书.epub` 逐字节进回收站、
txt 书**两个落点都留档**（`blobs == [b"", "旧的留档"]`）、显式覆盖同样留档且 `detail` 不再说「本地读不了」、
回收失败即 `skip` 且**盘上零改动**。
⚠️ 加这类用例必须确认「改动前它会红」——否则是恒真断言。

---

### 第 97 期铁律（四条 `[low]` 清理：死参数 / 冗余键 / 测试专用别名 / 零消费者端点）

#### 一、闸门 `gate_reason` 只剩两个开关，**没有来源维度**

`novelforge/sources/manager.py` 的 `gate_reason(feature: str = "download") -> str`：
`feature == "toc"` 看 `download.toc_enabled`，否则看 `download.enabled`。
第 93 期删掉「仅放行公版源」后 `source` 形参就不参与判定了，第 97 期**把形参删掉**
（11 处传参调用点 + 2 处测试桩同批改，`sources/toc_sources.py` 两处举例同步）。
「**闸门只有一个入口**」这条纪律不变 —— 界面显示的原因与接口拒绝的原因仍是同一份原文。

#### 二、`source_of` 是**读侧契约**：`_source` 的「不再写」与「仍然读」是两件事

`manager._mark` 现在只写 `source`（前端与下载路径读的）+ `source_name`。
`source_of(item)` 仍是 `str(item.get("source") or item.get("_source") or "")` ——
`_source` 是**外部回传 item**（`cli.py --item` / sidecar 里手写的）的输入契约。
**要删 `_source` 必须先换掉「外部回传」这条路**，否则旧 sidecar 失效；
`tests/test_sources_search.py` 有一条专门钉 `source_of({"_source": "b"}) == "b"`。

#### 三、`LIBRARY_SOURCE_DIR` 是同名的两个东西，**别一起删**

- **环境变量** `LIBRARY_SOURCE_DIR`（`novelforge/config.py` 的 `os.getenv(..., "/app/libraries")`）：
  `LIBRARY_SOURCE_DIRS1..N` 都没配时的**单根部署回退** ⇒ **必须保留**。
- **Python 别名** `config.LIBRARY_SOURCE_DIR`（= `LIBRARY_SOURCE_ROOTS[0]["path"]`）：生产代码零引用，
  只有测试在读 —— 第 97 期**删除**；测试改读 `LIBRARY_SOURCE_ROOTS[0]["path"]`（≈45 处 / 18 个文件），
  `tests/conftest.py` 的 `isolated` 夹具里那份别名 patch 一并删掉（`LIBRARY_SOURCE_ROOTS` 那份才是生效的）。

#### 四、删端点要连它的**独占 import** 与**注释里的举例**一起清

`GET /content`（旧式非 `/api` 路径：按 `supports_url(url)` 在 `REGISTRY` 里选一条已注册书源、
把 `src.render()` 的结果原样当 HTML 回吐，**每次都出网抓第三方页面**）在仓内零消费者，
经用户确认无外部脚本在用后**删除**，并补 **404 断言**（`tests/test_api_smoke.py`）。连带两处：
① `HTMLResponse` 在 `server.py` 里只被它用过 ⇒ import 同批删；
② `novelforge/core/network.py` 的 `verify_tls_enabled` docstring 原拿 `/content` 当「没有 cfg 的调用点」举例
⇒ 举例过期要改（**删调用点最容易漏的就是注释里的举例**）。

#### 五、`verify_tls_enabled(cfg=None)` 的缺省分支**保留** —— 它有别的读者

生产侧唯一调用点是 `DownloadManager`（总传 cfg），但缺省 / 空 dict 分支被
`tests/test_source_url_import.py:178-179` 钉着，且它是「只有全局配置」这类调用点的退路。
**要删得先决定那种调用点怎么办**，不在第 97 期。

#### 六、⚠️ **脚本报「全部命中」不等于文件真的改对**

第 97 期的替换脚本对 `tests/test_sources_search.py` 那条断言报告命中，但文件**实际没被改**
（`git diff` 里只剩事后用 edit 工具补的那一次），是聚焦用例 `KeyError: '_source'` 把它暴露出来的。
**教训：批处理替换之后必须 ① 跑聚焦用例 ② 核对 `git diff`，别只信计数与「已写 N 个文件」的输出。**
机制未完全证实，怀疑与脚本里「先改内存 `buf`、再用 `glob` 从磁盘读同一批文件」的写法有关。

---

### 第 98 期铁律（仪表盘页级三态 / 快速预览两个动作 / 上游对照）

#### 一、「页级加载」的判据**只许聚合真实请求状态**，不许超时启发式

`frontend/src/lib/dashboardPageState.ts` 是唯一实现，四档 `loading | error | empty | ready`，输入只有
`noLibraries` / `emptied` / `statsLoaded` / `statsError` / `booksLoading` / `booksError`：
`loading` = 统计**既没成功也没失败**且书目还在路上；`error` = 统计与书目**都**失败且统计从未到手；
`empty` 让位给既有的 0 库引导 / 全关空态；其余 `ready`。
⚠️ **不许**改成「进页面 N 毫秒没数据就当 loading」—— 那不是任何真实请求的状态，正是第 80 期
「消灭假开关」要挡的假信号（第 82 / 83 期拒绝做页级三态的原始理由就是这个）。

#### 二、**页级骨架自己得会解开**：谁在等，谁就得发请求

`frontend/src/views/DashboardView.vue` 的 `onMounted` 里必须自己 `void stats.load()`：
加载期部件行**不渲染**，而 13 件部件平时是各自 `onMounted` 去拉统计的 ⇒ 不自己发这一发就是
**永远转不完的骨架**。`stats.load()` 自身按「书库 + 已加载」去重，所以部件挂起来之后的重复调用不会多发请求。

#### 三、「有真数据就不许遮」是这类页级状态的硬边界

骨架与页级错误只在「首屏那几条请求都没 settle / 都失败」时出现；**任一条 settle（成功或失败）立刻退出**，
只对仍未就绪的那一条保留**区块级**提示（统计失败那张卡片照旧）。断言就钉这条：
`dashboardPageState.spec.ts` 的「统计一到手就不再遮」「没有任何请求在路上时**不**显示骨架」
「只有一条失败**不**升级成整页错误」。

#### 四、⚠️ 上游**有**页级信号 —— 别把「我们没有」记成「上游也没有」

`client/src/views/DashboardView.vue` 第 42-44 行：

```
42: if (librariesLoaded.value) return libraries.value.length === 0 ? 'empty' : 'ready'
43: if (librariesError.value) return 'error'
44: return 'loading'
```

上游拿的是 `useLibraries()` 的 `loaded` / `error` / `length === 0`。**我们刻意不照搬**：
`frontend/src/stores/library.ts` 的 `loadLibraries` 失败时保持 `librariesLoaded = false` 且**不加 error 标志**
（注释写明「不知道有几个库时不说『还没有书库』」）⇒ 拿它当页级信号会得到一个**永远解不开的骨架**。
我们的首屏内容（13 件部件 / 书架行）本来也不挂在书库列表上。
⚠️ 上游的三态**还有第二层**：`DashboardScroller.vue` 每行自带 loading / error / empty
（骨架带 `SKELETONS_PER_BAND = 8`、`w-[120px]`）—— 这一层我们早有（`useWidgetState` + 各行骨架）。

#### 五、快速预览的动作：**只带意图**，由父组件接既有实现

`frontend/src/components/book/BookPreviewDialog.vue` 的 `actions` 模式现在五个动作
（加入收藏 / 删除 / **编辑元数据** / **移动到书库…** / 详细信息），后两个**只 `emit`**：
- `edit-metadata` ⇒ 父组件 `router.push(metadataEditPath(id))` 深链到详情页元数据页签。
  ⚠️ **不挂第二个 `MetadataEditor` 实例**（它是自取数据的区块组件，同一屏两个入口更糟）；
  深链路径的唯一实现是 `frontend/src/lib/bookOpen.ts` 的 `metadataEditPath()`（原先内联字符串有两处）。
- `move-to-library` ⇒ 父组件开既有 `frontend/src/components/book/BookMoveDialog.vue`
  （`props: { open, bookIds }`；它自己会 toast，父组件**别重复提示**，只重拉书目与库计数）。
- 浮层里**没有就地编辑器**；批量删除的「撤销」仍留在书架页。

#### 六、⚠️ `agent-browser` 在本机**已不可用**；截图改用 Edge CDP 无头

`agent-browser`（0.38.1）会去连一个 **CEF 远程调试实例**（`http://127.0.0.1:8080/` 的 `<title>` 就是
`CEF remote debugging`），然后**挂住不返回** —— 三次尝试（含放进 PowerShell 后台 job）都没产出文件、
无残留进程。⚠️ §7.7 记的「本机已装 agent-browser、冒烟跑通」**已过时**。

**可用替代（第 98 期收尾实测有效、零新依赖）**：直接用本机 Edge 的无头 CDP 截图 ——
`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` 带
`--headless=new --remote-debugging-port=9333 --user-data-dir=<临时目录> --window-size=W,H`，
流程 `Page.enable` → `Emulation.setDeviceMetricsOverride` → `Page.navigate`（等 6 s）→
`Runtime.evaluate` 用**原生 setter + `input` 事件**填登录表单并点「登录」→ 再 `Page.navigate`（等 6 s）
→ `Page.captureScreenshot`（`captureBeyondViewport: true` 拿整页）。脚本 `%TEMP%\nf_shot.py`（**不入库**），
只用标准库（含手写 WebSocket 帧）。⚠️ 本机服务端口**不是** §7.7 的 8412，先查
`Get-CimInstance Win32_Process | ? CommandLine -like '*uvicorn novelforge*'` 拿真实 `--port`（本次是 8413）。

#### 七、看图对照的结论：**外壳逐字一致，差异只在既定范围三处**

两侧截图都看过之后的结论（写进 `docs/bookorbit/bookorbit-dashboard-styles.md` §7.8 ④）：
外壳 `h-55 rounded-2xl border border-primary/40 bg-card/30 shadow-sm backdrop-blur-[1px]`
与书架行外壳 **逐字一致**，结构同序；差异只有 ① 语言 ② **默认启用集合**（上游默认 6 张、且把
`library-overview` 设为 `enabled: false`；本项目默认 8 件、该卡排第一）③ 侧栏分区粒度。
⇒ **没有发现需要修的视觉偏差**。
⚠️ 看图时别把上游 `Reading DNA` 卡上的 `Rhythm` 横条当成我们的 `reading-rhythm`（那个 id 在本项目
已落定为「入库节奏」，第 83 期决策）。

