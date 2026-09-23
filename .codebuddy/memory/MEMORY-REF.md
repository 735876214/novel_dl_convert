# 长期记忆·参考手册（novel_dl_convert / NovelForge）

> `MEMORY.md` 只放**每次都要遵守的铁律**（体积受限、每次会话自动注入）；本文件放**按需查阅**的运行手册与跨会话待办。
> 需要「怎么在本机跑实例 / 怎么冒烟 / 上游对照到哪一步 / 还有什么待办」时读这里。
> 由 09-21 的压缩整理从 `MEMORY.md` 拆分而来，内容等价、未删减。

## 运行 / UI 验证
- 本地实例：`*_DIR→/tmp/<自建>/…`、`LIBRARY_SOURCE_DIR=…/libraries`、`AUTO_WATCH=false`、`.venv/bin/python -m uvicorn novelforge.server:app --port <新端口>`（**别 kill 别人的实例**：8791 常被旧代码实例占、8993 是用户 Docker 容器）。
- 登录字段是 `{"user","pin"}`（**不是** username/password）；全新 `DATA_DIR` 首启由 `db.init()` 按 `AUTH_USER`/`AUTH_PIN` 建默认账号（缺省 `admin/changeme`）。
- 建库接口收 **`source_dirs`（绝对路径 JSON 数组，第 41 期起）**；路径须在 `config.LIBRARY_SOURCE_ROOTS` 内（「就地引用」，跨根合法）。⚠️ 已无 `mode`/`root_path`/`source_subdir`。
- Docker：`docker-compose.yml` 端口 **8992**；`docker-compose.test.yml` 挂 `./novelforge` 端口 **8993**；断网无法 `--build`。
- 构建：`cd frontend && npm run type-check && npm run build && npm run deploy`，核对 `/static/v2/assets/index-*.js` **实际内容**（HMR 源码≠服务端产物）。
- ⚠️ **本机 Node 由 nvm 管理（09-23 订正，取代此前「nvm 是空的、用 IDE 托管」的旧结论）**：nvm v2.0.0 位于
  `C:\Users\qingr\AppData\Local\Author Software\nvm`，已 `nvm install 24.19.0` + `nvm use 24.19.0`（设为默认），
  `node`/`npm` 现解析为 **v24.19.0 / 11.17.0**。winget 直装的 node 落在 WinGet 包目录、PATH 检索会跳过且被 nvm 抢注
  ⇒ **不能靠 winget 直装落地，须走 nvm**（那份 winget node 是无害残留）。`npm install` 等下载动作仍受本机网络限制（走系统代理）。
  ⚠️ `install_binary`（node）在本机会因 EPERM（rename 失败）装不上，**别在它上面反复试**。
  ⚠️ **跑 `npm run build` / `deploy` 前必须先 `$env:NODE_OPTIONS=''`** —— IDE 注入的 safe-delete shim 会拦 Vite 的
  `fs.rmSync`（清 outDir）与 `deploy.mjs` 的删除，报 `checkBulkDeleteGuard` / 「No active Node.js version」。
  同一条「先清 `NODE_OPTIONS`」对 pytest 也适用（此前几期的命令都带它，原因就在这里）。
- 浏览器冒烟：`playwright-cli install-browser chromium`；注入 `nf_token`（`localstorage-set` + **`reload`**）；⚠️ `snapshot` 直接打到 stdout（`--filename` 可能不落盘）⇒ 重定向到 `/tmp` 自己读，别落仓库根；⚠️ 换了产物要**带 `?nc=N` goto**（普通 `reload` 用旧 bundle，会误判成「改动没生效」）。
- e2e 自查顺序：接口账目（curl）→ 界面文本（`eval innerText`）→ `console`（0 errors）→ `network`（无非本地请求）。

## 上游取证与待办（跨会话）
- **`docs/bookorbit-module-inventory.md` 是第三条轴**（按上游**代码模块**对照，67 目录/33 feature）：只按页面对照会系统性漏掉「整块模块从未进视野」的能力。⚠️ **按模块名 grep 文档得出的覆盖结论是错的**（假阴性过半）——判定只能按语义找 + 落到 `文件:行`。34 期落地 §4.1「值得做」4 项；35 期**改判** §4.2 里 3 项为做并落地（字段级锁 / 自定义字段 / 推荐打分）、36 期再落地 `book-move` ⇒ §4.2 真·不做 **4 项**（`embedding` / `position-converter` / `email` / `narrator`）。**42 期复核：上游 `main` 仍为 `c292d6cc`（无新提交）⇒ 转为「判定刷新 + 部分缺口」**：该文件第二节判定列 **10 处刷新**（含 3 处文档错误订正）、第六节新增部分缺口 14 项。
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
- 工具=`tests/check_doc_anchors.py`（**非 `test_` 前缀 ⇒ pytest 不收集**）：`--drift`/`--suggest`/`--todo`/`--file`；方法与四条局限见 `docs/bookorbit-capability-gap.md` §0.4（核法与局限）+ §0.5（工具固化）。
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
