# 长期记忆·参考手册（novel_dl_convert / NovelForge）

> `MEMORY.md` 只放**每次都要遵守的铁律**（体积受限、每次会话自动注入）；本文件放**按需查阅**的运行手册与跨会话待办。
> 需要「怎么在本机跑实例 / 怎么冒烟 / 上游对照到哪一步 / 还有什么待办」时读这里。
> 由 09-21 的压缩整理从 `MEMORY.md` 拆分而来，内容等价、未删减。

## 运行 / UI 验证
- 本地实例：`*_DIR→/tmp/<自建>/…`、`LIBRARY_SOURCE_DIR=…/libraries`、`AUTO_WATCH=false`、`.venv/bin/python -m uvicorn novelforge.server:app --port <新端口>`（**别 kill 别人的实例**：8791 常被旧代码实例占、8993 是用户 Docker 容器）。
- 登录字段是 `{"user","pin"}`（**不是** username/password）；全新 `DATA_DIR` 首启由 `db.init()` 按 `AUTH_USER`/`AUTH_PIN` 建默认账号（缺省 `admin/changeme`）。
- 建库接口要 **`root_path` 绝对路径**（`{name,type,mode,root_path}`），只给 `source_subdir` 会 400。
- Docker：`docker-compose.yml` 端口 **8992**；`docker-compose.test.yml` 挂 `./novelforge` 端口 **8993**；断网无法 `--build`。
- 构建：`cd frontend && npm run type-check && npm run build && npm run deploy`，核对 `/static/v2/assets/index-*.js` **实际内容**（HMR 源码≠服务端产物）。
- 浏览器冒烟：`playwright-cli install-browser chromium`；注入 `nf_token`（`localstorage-set` + **`reload`**）；⚠️ `snapshot` 直接打到 stdout（`--filename` 可能不落盘）⇒ 重定向到 `/tmp` 自己读，别落仓库根；⚠️ 换了产物要**带 `?nc=N` goto**（普通 `reload` 用旧 bundle，会误判成「改动没生效」）。
- e2e 自查顺序：接口账目（curl）→ 界面文本（`eval innerText`）→ `console`（0 errors）→ `network`（无非本地请求）。

## 上游取证与待办（跨会话）
- **`docs/bookorbit-module-inventory.md` 是第三条轴**（按上游**代码模块**对照，67 目录/33 feature）：只按页面对照会系统性漏掉「整块模块从未进视野」的能力。⚠️ **按模块名 grep 文档得出的覆盖结论是错的**（假阴性过半）——判定只能按语义找 + 落到 `文件:行`。34 期落地 §4.1「值得做」4 项；35 期**改判** §4.2 里 3 项为做并落地（字段级锁 / 自定义字段 / 推荐打分）⇒ §4.2 真·不做 5 项。
- 外部同步（Hardcover/Readwise/StoryGraph）**09-19 拍板不做**；Requests（求书）**已决策不做**（走数据驱动书源规则）。
- 参考仓库 `735876214/bookorbit` @ `main` @ `c292d6cc`，镜像 `%TEMP%\bookorbit-ref`；**取证扫符号别按文件名猜**；读上游 blob 走代理 `cat-file -p HEAD:<path>`，勿改持久 git 配置。
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
- ⚠️ `npm install` 会删掉 `frontend/package-lock.json` 里一批 optional 的 `"dev": true`（纯噪声）⇒ 提交前 `git checkout -- frontend/package-lock.json`。
- Windows：IDE safe-delete shim 拦 PowerShell `Remove-Item`（静默不删）⇒ 清临时产物用删除工具；`Out-File` 不带 `-Encoding` 同样被拦。

### 命名与出版细节
- `fileops.fill_pattern` 9 个占位符、**先长后短**；`{index}`=系列卷号（两位补零，非流水号）；`{ext}` 已带扩展名 ⇒ **只有模式以 `{ext}` 收尾时才摘尾扩展名**。
- 「预览==落盘」共用 `publish.relpath_for`+`rel_verdict`（REL_REUSE/REBUILD/DECLINE）；仍会改 basename 的只剩 `apply_conflict_rename`/`apply_komga_layout`（成对调 `db.remap_book_id`）。
- 目录型条目的源指纹=`source_sig._tree_files`。

### 后端细节（统计 / 配置覆盖 / 页面入口）
- `core/stats.py`：`overview.integrity` 原有 5 个计数键一个不能少；`largest` 独立新键、与作者/系列榜共用 `top` 但**不要塞进 `_top`**；既有 **16 键有测试钉住**。
- 可覆盖项（每库）：`output.format`/`output.layout`、`watcher.recursive`/`watcher.copy_non_txt`、`metadata_fetch.*`、`naming.pattern`/`naming.scope`、`scrape.enabled`、`opds.expose`/`komga.expose`；`core/lib_settings.py` 的 `effective`/`config_for`/`apply_to`/`set_overrides`/`clear_overrides`/`schema()`。
- 可见性判定的唯一落点是 `_opds_visible_libraries`/`_ko_visible_libraries`（「不可见」=「不存在」→ 直连 404）。
- ⚠️ **判断「某能力有没有页面入口」要两头查**：先查 `server.py` 的 `EDITABLE` 白名单，再查前端 `settingsFields.ts` 的字段定义（只看配置文件会误判，`upload.max_bytes` 是一例）。

### 前端细节
- `bridge.css` 须 `@theme inline`；`main.css` 须 `@custom-variant dark (&:is(.dark *));`。
- ⚠️ **设置页 `note` 是纯文本插值**（`SettingsPlaceholder.vue` 的 `{{ page.note }}`）⇒ 写 `**`、反引号、`<strong>` 都会**原样显示给用户**；有契约测试钉住。
- 工具页 `ToolsLayout.vue` 子页用 `onActivated`（非 `onMounted`）；改磁盘工具「先预览再应用」、删除移回收站。例外：页面内 `v-if` 子组件（如 `ScrapePanel`）需 `onMounted` 首载、`onActivated` 只刷新。
- 窄屏双写法：宽屏 `<table class="hidden md:block">` + 窄屏 `<ul class="md:hidden">`；纯装饰增强取不到就不设变量 ⇒ CSS 整条失效 ⇒ 天然回退。
- **图表栈**：`echarts`+`vue-echarts`；`frontend/src/lib/charts.ts` 是**全站唯一**的注册/主题适配入口（组件里别各自 `use()`），按需注册 + 页面级动态 import；SVGRenderer + `oklchToHex()`（ECharts 不认 oklch）+ 幂等主题注册。
- **外观偏好归属边界**：`stores/displayPrefs.ts`（Layout 页六项）**并入 `appearance` 块**随整套偏好走服务端（不新增第七块；应用远端值**逐键挑**）；`stores/shelfPrefs.ts`（Behavior 三项 + 卡片信息）走 localStorage、**不进服务端同步**；写入经 `notifyPrefsChanged`、应用远端值走 `suppressing`。
- **侧栏导航契约**（`data/nav.ts` + `AppSidebar.vue`，有 `tests/test_nav_contract.py`）：① 动态计数项**不许写死数字**（`countSource: 'running' | 'browse'`，写死即假数据）；② 菜单 id 全局唯一；③ 组底部 `more` 行必须 **`label` + `to` + `countSource` 三件一起声明**，别再用 `items.length` 当计数。
- **命名避让**：`/explore`=「探索发现」=**外部书源检索**（`POST /api/search`）；`/browse`=「实体总览」=**本地书目按元数据维度浏览**（零外网）。两者不能合并、不能互相借名；侧栏「浏览」是**分组标题**，新页 label 别叫「浏览」。
- **实体总览只有六个维度**（作者/系列/题材/出版社/语言/收藏）：本项目**只有 `tags`（OPF `dc:subject`）一个题材类字段** ⇒ 上游 genre/tag 两维在此会变成同一份数据列两遍 ⇒ 只做一个；演播者无实体（不做）。数据一律来自 `library.scopedBooks`（+`/api/books` 的 `collection_ids`），**不为它新增聚合接口**。

### 文档锚点核验（工具口径）
- 工具=`tests/check_doc_anchors.py`（**非 `test_` 前缀 ⇒ pytest 不收集**）：`--drift`/`--suggest`/`--todo`/`--file`；方法与四条局限见 `docs/bookorbit-capability-gap.md` §0.4（核法与局限）+ §0.5（工具固化）。
- 自动核对的 ±6 窗口会吞掉偏 4 行的漂移、±2 假阳性约 80% ⇒ **脚本只能生成待核清单、不能判定**；区间引用只能按「它声称是什么」反向 grep。
- 追加一类误报：**「文档写 `x.py:1`，真值 `:2`」这种更正句式**前半截是记录旧错，不该按漂移判。
- ⚠️ **同期内「先写锚点、后改代码」也会让锚点作废**（第 34 期四笔代码落在最后、文档先行）⇒ 收尾必须按「当前真实行号」重测，**不记偏移量**。
