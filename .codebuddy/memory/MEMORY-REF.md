# 运行手册 / 跨会话待办（`MEMORY-REF.md`）

> `MEMORY.md` 只放**每次都要遵守的铁律**（体积受限、每次会话自动注入）；本文件放**按需查阅**的
> 运行手册与跨会话待办 —— 「怎么在本机跑实例 / 怎么冒烟 / 上游对照到哪一步 / 还有什么待办」。
>
> 第 220 期精简：原来 28 KB 里有 15 KB 是「**动到某领域前才读**」的域细节 ⇒ 拆到
> `.codebuddy/memory/MEMORY-DETAIL.md`（按需读）。这里只留**每次都可能要用**的部分：
> 运行 / UI 验证、上游取证与跨会话待办、鸿蒙端、逐期内容去哪了。

## 运行 / UI 验证
- 本地实例：`bash scripts/dev-instance.sh [端口]`（自动建隔离目录、默认 8412）；等价手写版 `*_DIR→/tmp/<自建>/…`、`LIBRARY_SOURCE_DIR=…/libraries`、`AUTO_WATCH=false`、`.venv/bin/python -m uvicorn novelforge.server:app --port <新端口>`（**别 kill 别人的实例** —— 本机端口占用见 `docs/development-windows.md`）。
- 登录字段是 `{"user","pin"}`（**不是** username/password）；全新 `DATA_DIR` 首启由 `db.init()` 按 `AUTH_USER`/`AUTH_PIN` 建默认账号（缺省 `admin/changeme` —— **仅本地默认，部署必须改**）。
- 建库接口收 **`source_dirs`（绝对路径 JSON 数组，第 41 期起）**；路径须在 `config.LIBRARY_SOURCE_ROOTS` 内（「就地引用」，跨根合法）。⚠️ 已无 `mode`/`root_path`/`source_subdir`。
- Docker：`docker-compose.yml` 是**自足的 NAS 单文件**（镜像 / 端口 **8992** / 挂载 `./input ./output ./config ./cookies ./cache ./data ./libraries` / `AUTH_*` / `AUTO_WATCH` / `WATCH_INTERVAL` 全部写字面量，**不读 `.env`**；`.env.example` 已删，`.env`/`.env.*` 仅留在 `.dockerignore` 里做卫生）。可选开关一律是**注释行**：`user: "1026:100"`、`EBOOK_CONVERT_BIN=`、`HTTP_PROXY/HTTPS_PROXY/NO_PROXY=`、`LIBRARY_SOURCE_DIRS1_NAME`/`DIRS2*`；`pull_policy: missing`（非 always）是刻意的。compose 文件仅保留 `docker-compose.yml` 与 `docker-compose.test.yml`，**不另设叠加件**（offline / update 等已移除，相关用法内联进主文件注释或文档）。⚠️ 原 `docker-compose.override.yml` 名仍被 Compose **自动合并**（静默改 8993 + 禁拉取），切勿恢复该文件名。`docker-compose.test.yml`（本地 build + 挂 `./novelforge` + 8993 + `./data-test`）同样自足；断网无法 `--build`。
- 构建：`bash scripts/frontend-verify.sh`（= `type-check && test:unit && build && deploy` 四连），核对 `/static/v2/assets/index-*.js` **实际内容**（HMR 源码≠服务端产物）。
- ⚠️ **本机（Windows）专属项不在这里重抄**：nvm 与 `NODE_OPTIONS`、`.venv` 解释器、msedge 冒烟与 `ui-smoke.ps1`、端口占用、编码 / proxy 坑
  —— 一律见 **`docs/development-windows.md`**（仅当前开发机，Linux / 容器忽略）。
- e2e 自查顺序：接口账目（curl）→ 界面文本（`eval innerText`）→ `console`（0 errors）→ `network`（无非本地请求）。
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

## 鸿蒙端（`clients/harmony`，ArkTS / ArkUI API 26）

- **构建与安装**：命令行只能 `assembleHap`（**未签名**）；安装与运行必须 DevEco ▶ Run —— 签名口令是 IDE 加密的，CLI 签名报 `00303242`。
- **阅读面 = 跨章连续流**：窗口恒 3 块（当前 ± 1），判据全在 `common/ReaderFlow.ets`
  （网页端 `frontend/src/lib/readerFlow.ts` 的原生镜像；改一端必须同批改另一端）。`ReaderPage` 只量几何、补窗、补位移。
- ⚠️ **ArkUI 没有浏览器的滚动锚定**：在视口上方插入/删除章块会把内容整体推走，必须把这段位移补回 `Scroller`。
  **`scrollTo` 默认带 1s 动画 ⇒ 补偿必须传 `animation: false`**，否则变成慢慢漂移。
- ⚠️ **`Area.position` 不是内容坐标**（真机实测每块都报 0）：拿它算「块顶距内容顶部多远」会让可见章永远判到最后一块 ——
  表现是**轻轻一滚就换到下一章、往上滚也一样**（每次滚都往后推进一格）。章块几何只能**按块序累加高度**得到
  （块同属一个 Column、紧挨着排，间距都在各自 padding 里）；`Area.height` 也可能带单位字符串，取值要 `Number.parseFloat`。
- **补偿的两种时机**：上方**插入**（前插上一章）高度要等布局才知道 ⇒ 记令牌，等那块 `onAreaChange`（尺寸变化必触发）
  补它自己的高度；上方**删除**（裁剪）高度当场已知 ⇒ 就地改偏移，与状态变更同一帧落地。追加/下方裁剪不用补。
- **可见章判据要能「拒绝移动」**：锚线必须落在某块区间内（`top <= line <= top+height`）才算换章，一个都落不进去
  （几何没量到 / 视口高度不可信）就**保持当前章**，绝不退回「最后一个 top <= line」那种写法 —— 那正是上面那个 bug。
- **进度契约（与网页端同一个 progress 行）**：⚠️ **两把尺子，不能混** ——
  `locator` = **spine index**（`/chapter/{index}` 的入参、批注/书签的锚）；
  `percent` = **摊平位置**口径 `(摊平下标 + 章内比例) / 摊平章数`（网页端 `overallPercent` 同式，
  恢复按 `floor(percent/100 * 摊平章数)` 折算）。
  两者在**没有空档**的书上相等；有封面页/版权页（spine 里有、目录不列）的书上**不相等** ——
  端上拿 spine index 当 percent 的分子 ⇒ 网页端续读跳到后面某一章（已修）。
  `POST /session` 的 `source` 用 `web`（后端枚举没有 harmony，不为一个字符串加枚举）。
  **口径由 `tests/test_client_progress_scale.py` 钉着两端源码**（读 `.ets` / `.vue` 的写法断言）。
- **阅读面路由参数 `index`**：`>= 0` = 用户显式点的某一回（阅读面**不**拿 locator 覆盖）；`< 0` = 「继续阅读」（读 locator）。
- **设计真值源只有 `design/harmonyos-v2.html`**（v1 旧稿 `harmonyos-client.html` 已删，别再引旧稿）。
- **会话结束只有一个入口**：`Nav.toLogin()` = 清凭证 + `reset('login')`，各页 401 只调它。
  ⚠️ 以前 401 只跳登录不清 token，而登录页见 `loggedIn()` 为真又自动跳回首页 ⇒ **首页与登录页无限互踢**，
  token 一过期就永远进不去登录表单。别再在各页各写一遍 `Session.logout()`（第二份「会话结束」判据）。
- **阅读状态三档 / 继续阅读**：判据在 `common/ReadingStatus.ets`（`statusBucket` / `isInProgress` / `statusLabel`，
  镜像网页端 `readingThresholds.ts`）。第 201 期扩到 8 档后，`percent > 0 || status !== null` 会把
  「想读 / 弃读」也当成在读 —— 继续阅读与网页端一致，**只看进度**（`started < percent < finished`）。
- **书目共享缓存**：`common/ShelfData.ets`（首页/书架共用、30s TTL、并发去重、`patchProgress` 就地改一条）。
  切 tab 不再重拉 2309 本、也不在主线程重复 `Cache.saveShelf`；读完后按 `/progress` 只改那一张卡。
- **非重排格式**：`library.book_detail` 对 PDF / CBZ / 有声返回 `chapters=[]`，`GET /chapter` 回 400。
  详情页按「**有没有章节**」禁用阅读入口（不要再抄一份格式白名单），阅读面把服务端 detail 原样显示
  （别把 400 说成「连不上 NAS」）。
- **离线入口**：详情/目录也要缓存（`Cache.saveDetail/loadDetail`），否则「书架能看、点进去就废」；
  阅读面断网时目录从这份兜底，「继续阅读」退回 `Session.lastRead()` 的章。
- **阅读计时**：退后台要暂停（`EntryAbility.onBackground` 置 `appActive=false`，`ReadingSync` 心跳跳过累加），
  否则锁屏放着也算阅读时长。
- **401 统一出口**：`Api.unauthorized`（`Index` 启动时注册成「清凭证 + 回登录」）。页面里**不再各写一遍**；
  两个坑：① **登录接口自身的 401（口令错）必须在 `Api.login` 里排除**，否则登录页会被就地重置；
  ② 用「发请求时的令牌快照」判断（`Api.token === usedToken`），否则重新登录后旧请求迟到的 401 会踢掉新会话。
- **渲染热路径不要现算大数组**：目录拍平 / 当前章（`DetailPage.flat/cur`）、书架筛选与三档计数
  （`ShelfPage.filtered/cnt*`）、首页「在读」列表（`HomePage.readingCache`）都在状态变化时算一次，
  渲染只读缓存 —— 否则 2099 章 / 2309 本会在每次 build（含每个搜索按键）里反复过滤排序。
- **固定版式也要挡**：`BookDetail.fixed_layout` 必须进「端上能不能读」的判据 —— 整页排好版的 EPUB
  被当普通段落重排会把版式揉烂；详情页对这类书不列目录、按钮如实禁用。
- **已踩过的卡顿**：书架一次渲染 2309 本（9 万节点）、详情一次渲染 2099 行目录都会 appfreeze ⇒ 两端都改成分页/按卷增量渲染
  （`ShelfPage` 每屏 60、`DetailPage` 每卷 6）。

---

## 逐期内容去哪了（第 106 期起）
- 第 53–105 期的「逐期铁律原文」已移到 `.codebuddy/memory/MEMORY-PERIODS.md`（存档、只读）。
- **本文件按主题组织：不再按期号追加。** 只有出现**新的领域知识**（新的运行手册 / 域细节 / 跨会话待办）时才在上方对应小节补一条。
- 每期实施记录的唯一出处 = `docs/roadmap-gaps-remaining.md`（最新期在末尾）；一期一行的铁律索引见 `MEMORY.md`。
- 当日日志（`.codebuddy/memory/YYYY-MM-DD.md`）**2026-10-06 起取消**（既有日期文件保留为历史）。
