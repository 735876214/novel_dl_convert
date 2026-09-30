# TODO.md — 当前任务 / 优先级 / 开发进度

> 维护约定：**完成即移入「已完成」并写清 commit/期号**；每条待办要带**证据**（数字、文件、复现方式），
> 不写「优化一下性能」这种没有判据的条目。较长的逐期记录放 `docs/roadmap-gaps-remaining.md`。

**最后更新**：2026-10-01（**第 82 期已交付**：V0.82.0 —— 首页（仪表盘）逐项对齐上游 BookOrbit；第一步对照基线在 `docs/bookorbit/bookorbit-dashboard-styles.md`，实施记录见 `docs/roadmap-gaps-remaining.md` 第 82 期）

## 0. 当前状态

- ✅ **第 82 期已交付**（V0.82.0，首页对齐上游；本轮纯前端，无用户侧补救动作。第 81 期那条「回收站还原」若线上还没点，仍需做一次）。
- HEAD = 第 82 期（V0.82.0）；工作区干净（仅 `.vscode/settings.json` 是各人本机设置，**不属于仓库改动**）。
- 测试基线：后端 **1335 例（1323 passed / 12 skipped / 0 failed）**（`pytest`，离线）；前端 **456 例 / 41 个 spec**（`npm run test:unit`）。
- 版本：`VERSION` = **0.82.0**（单一真值源，`GET /health` 下发）；每个版本在 `CHANGELOG.md` 有一段。
- ⚠️ 前端自本期起有**显式运行时依赖** `vue-draggable-plus`（仪表盘部件行内拖拽；原生 HTML5 DnD 触屏不触发，
  理由记录在 `docs/architecture.md` 不变量第 6 条与组件头注释 —— 第 80 期「显式引入须声明理由」口径下的第一个）。
- ⚠️ **口径修订（第 80 期）**：「零外部请求 / 零依赖」已由**硬约束改为默认取向** —— 默认仍自托管、不拉 CDN，但允许**显式、可关、失败降级**地引入外部依赖与出网（见 `AGENTS.md` 第 1 节）。别再用「零依赖」当**不做**的理由。
- 上游缺口清单（`docs/roadmap-gaps-remaining.md` 第一节）已实质清空；新缺口来源改看 `docs/bookorbit/bookorbit-module-inventory.md`。
- ⚠️ 本文件的「已完成（近三期）」只登记到第 68 期 —— **第 69–79 期的记录在 `docs/roadmap-gaps-remaining.md`（活文档，最新期在末尾）**，别按这里判断「最近做了什么」。

## 1. 待办（按优先级）

### P0 · 第 81 期（✅ 已完成，V0.81.0，2026-09-30）：修「移除漫画书库失败」+ 回收站还原

> ✅ **已交付**（T0–T5 全部完成，结果见下方逐项；完整实施记录与取舍见 `docs/roadmap-gaps-remaining.md` 第 81 期）。
> ⚠️ 唯一留在用户侧的动作：**在线上点一次「全部按原路径还原」**（见第 0 节）。

**需求来源**

- 用户报告（原文一句）：`http://192.168.0.95:8992   移除漫画书库失败`。
- **线上现状**：漫画库 `lib-6a0b30d3` 的移除动作正在跑，**已把 ~2400 份 / 68 GB 本地漫画搬进回收目录**；
  用户已按建议 `docker compose stop novel_dl_convert` **停服止血**，保留现场（库登记与已搬文件都在）。
  ⚠️ **upgrade 后第一件事是用本期新增的还原功能把这批漫画搬回 `/app/libraries/漫画`（宿主机 `./libraries/漫画`）。**

**现象与证据**（只读探测线上实例得出，可直接采信）

1. 移除请求**长时间不返回**（实测数百秒仍无响应）⇒ 前端只能显示「失败」。
2. 漫画库 `lib-6a0b30d3` **仍在册**，但 `book_count` 持续下降：2206 → 1947 → 1834 → 1647 → 1531。
3. 活动日志 165 条**全 success，没有一条「移除书库登记」** ⇒ `api_delete_library` 末尾的 `activity_log.log` 从未执行到。
4. 回收目录 `CONFIG_DIR/cache/recycle` 实时增长：61 秒内 **+240 份 / +4.8 GB（≈79 MB/s）**，
   三次采样 `files/bytes` = `2192/63.0GB → 2327/65.2GB → 2432/67.8GB`。
   ⇒ 该速率是**跨卷速率**，证明 `shutil.move` 走了 **EXDEV 复制回退**（同盘 rename 是 O(1)、无字节吞吐）。
   部署侧 `docker-compose.yml` 的 `./cache` 与 `./libraries` 是两个相对路径，用户实际把 `libraries` 指到了另一卷。

**根因**

- **主因**：`novelforge/server.py::api_delete_library`（≈L4200-4259）把**跨文件系统的大搬迁**放在 **HTTP 请求内同步执行**，
  逐本 `_recycle_one(...)`（② 书库内成品 + ③ 出版副本）⇒ 请求数小时不返回，且**没有任何进度回调**、无法取消、用户完全不可见。
- **名实不符**：该库 `source_dirs=["/app/libraries/漫画"]`、`publish_path=""`、无 ① 记录 ⇒ 被回收的「②」**就是用户本地原件**，
  与第 75 期「移除书库保留本地的书」的字面口径矛盾。
- **次因**：`novelforge/core/publish.py::recycle`（≈L218-234）落点名 `f"{stamp}_{p.name}"`，
  `stamp = "%Y%m%d-%H%M%S"` = **16 字节**；而 Linux 单文件名上限 **255 字节（UTF-8）**。
  该漫画库 ≥240 字节的名字有 **7 个**（实测最长达 **277 字节**）⇒ `ENAMETOOLONG` 被记成 `failed`。
  重名退让分支 `f"{stamp}_{n}_{p.name}"` 同样会溢出（序号把长度顶回去）。

**功能范围（用户已逐项拍板，不可擅自缩减/改口径）**

- **A 治「请求挂死」**：把长操作从请求里摘出来，改成**后台任务 + 真实进度**（照抄既有 `db.task_*` + `/api/tasks` + TaskCenterView 的 `bookmove` 范式），接口立即返回 `task_id`，前端不再阻塞。
- **B 修超长文件名**：`publish.recycle` 目标 basename 保证 **UTF-8 字节长 ≤255**（含重名序号分支），按字节边界截断、不切坏多字节字符，超长时加短哈希后缀保唯一可辨。
- **C 加「回收站还原」**：新增入口，**按原路径把回收站文件搬回**（还原本次被误搬的 ~2400 份漫画）；历史无台账的文件走「剥时间戳前缀 + 指定目录」的孤儿还原。
- **语义变更（本次核心）**：**「移除书库」一律不动任何磁盘文件**，另给一个**显式的「连文件一起清理」开关**。
  ⇒ 第 75 期「移除书库回收 ②③」的默认行为**作废**（「删书」的第 75 期口径**不动**，仍是三份一起回收）。

**任务清单（实施顺序）**

- [x] T0 线上处置：**用户侧动作未做**（本机无法代做）——升级后确认库登记仍在，用新还原功能把这批漫画搬回 `./libraries/漫画`。
- [x] T1 后端拆分 `api_delete_library`：默认路径**同步、立即返回、零文件触碰**（只 `db.delete_library` + `db.scrape_delete_by_library` + `catalog.forget` + `_libraries_changed` + `activity_log`）；`purge_files=1` 走后台任务（`_run_library_purge` + `_purge_worker`，沿用 `_run_book_move` 写法，**刻意不写 `result`**）。`force` 参数整个去掉。
      ⚠️ 同步阶段先**物化待回收路径清单**（`_purge_paths`，在删登记与 `scrape_delete_by_library` 之前算好 ②③ 路径）—— ③ 依赖刮削台账 `link_rel`，台账行会随库删除。
- [x] T2 `publish.recycle` 长名加固 + 回收台账写入（`recycle_items` 表：`id/orig_path/recycled_name/why/size/created_at`，**刻意不含 `book_id`** ⇒ 从设计上规避 remap 四处同步点）。落点名收敛为唯一实现 `fileops.recycled_name`（三个调用方同批改）；写入走**永不外抛**的 `db.recycle_note`。
- [x] T3 新增 `novelforge/core/recycle.py`（`list_items` 台账 + 磁盘实况 + 孤儿、`strip_stamp` 剥时间戳前缀、`free_path` 退让命名、`plan_restore` / `restore_many`）+ `GET /api/recycle`、`POST /api/recycle/restore`（后台任务 + 进度 + **幂等可续跑**，目标已存在则**退让不覆盖**并如实报告）。
- [x] T4 前端：`LibrariesView.vue::remove()` 改为**页内确认浮层**（默认文案 + 「连文件一起清理」勾选 + 受理 toast）；`api.ts::deleteLibrary` 语义/返回类型改 + 新增 `recycleList` / `recycleRestore`；维护页新增「回收站还原」区块；`data/tasks.ts` 加 `librarypurge` / `recycle` 两类型；`TaskCenterView.vue` 让新类型运行中显示真进度。
- [x] T5 测试与收尾：新增 `tests/test_library_purge.py`（7 例）、`tests/test_recycle_restore.py`（10 例），**改写了既有「移除书库会回收 ②③」的旧断言**；后端全量 **1335 例 / 1323 passed / 12 skipped / 0 failed** + 前端四连全绿；`VERSION` 0.81.0 + CHANGELOG 段 + roadmap 记录 + 记忆。

**防回归要点**

- 默认删库路径**必须先证明「磁盘文件零触碰」**（用例断言文件仍在原处），这是本期最容易写漏的一条。
- 新增字面量端点 `/api/recycle`、`/api/recycle/restore` **注册在含 `{param}` 的同类路径之前**（路由遮蔽）。
- 后台线程进收尾清单，`tests/conftest.py::_quiesce_background()` 须在夹具 `db.close()` **前**回收。
- 「移除书库不动文件」与「删书回收三份」的**口径不一致**记进本文件「明确不做 / 待议」，不擅自改删书。
- 收尾：`VERSION`（0.80.0 → 0.81.0）**必须同批补 `CHANGELOG.md` 段**（否则 CI `release.yml` 发布失败）+ `docs/roadmap-gaps-remaining.md` 本期记录 + `.codebuddy/memory/`。

### P1 · 有明确指标、可直接动手

- [ ] **「元数据来源」页最后两条如实标注的「未支持」**（用户此前已确认，尚未排期）
  - ① 按书的语种**翻译检索词**（跨语言检索）—— 现状只按语种「重排来源顺序」；
  - ② **自定义来源权重** —— 现状固定三档（专精本语种 → 多语种通吃 → 专精别语种，档内保序）。
  - 出处：`MetadataPage.vue` 的 `SettingsUnsupportedCard` 文案（改这两条要同步改那里的 note）。

### P2 · 要先量化再决定（涉及首屏体感，别凭感觉改）

- [ ] **未登录访问会先渲染一次外壳，白发约 10 个注定 401 的探测请求**（每个约 337 B）
  - 证据：600 本库实测，冷访问（未登录）时 `collections` / `libraries` / `smart-scopes` / `features` /
    `browse-counts` / `notifications` / `prefs/*` / `config` 等各被调 **2 次**，多出的那次全是 401 探测。
  - 成因：`App.vue` 的外壳挂在 `v-else`（`showLogin` 初值 `false`）⇒ 鉴权还没裁决时外壳已渲染、它的 store 已开拉。
    第 68 期只给 `<MigrationGateDialog>` 加了 `authChecked` 门（它拉的是**真数据**、单次约 300 ms，代价大）；
    外壳这批是**廉价探测**（337 B、无正文），当时没动。
  - 权衡：把外壳也 gate 到 `authChecked` 会让**已登录用户的冷启动**多等一次 `api.me()`（首屏变慢）——
    先量「已登录冷启动的损失」与「未登录浪费」各多大，再决定值不值。

### P3 · 文档债 / 卫生

- [ ] **`docs/roadmap-gaps-remaining.md` 缺第 62–65 期的实施记录**
  - 那几期由并行会话完成（书目索引落库 / PG 后端 / Redis 缓存 / 文件维度读点 / 批注位置锚 / 书卡菜单 / 删书 / Book Dock 入口…），
    提交里有代码与新文档，但**没写进这份逐期台账**。补写时以 `git log` 与当时代码为准，别凭印象。
- [ ] 合并/整理 `docs/` 下与 `README.md` 重复的表述（README 已很完整，新增文档应**引用**而非抄写）。

### 明确「不做」（避免反复立项）

- Kobo 同步、邮件投递；国际化（25 语言）；多用户/角色/OIDC；在线元数据的「插件市场 / 第三方源市场」（**已取消**）；
  批注跨端同步与导入（无数据源）、按设备重建批注位置、Kobo 阅读状态投影、通知清理 job、通知 SSE 网关、孤儿封面清扫；
  非 EPUB 的元数据解析（刻意不解析）；实体**删除**策略（源文件名无写入口）；`file-write`（元数据写回文件，永久不做）。
- 判据与出处：`docs/roadmap-gaps-remaining.md` 第二节 + `docs/bookorbit/bookorbit-module-inventory.md` §4.2 / §6.2 / §9。

## 2. 已完成（近三期）

- **第 82 期（2026-10-01）· 首页（仪表盘）逐项对齐上游 BookOrbit**（V0.82.0，两步走：先对照基线后改造）
  - 第一步：上游 `bookorbit @ c292d6cc` 首页逐区块四档判定，落 `docs/bookorbit/bookorbit-dashboard-styles.md`（含「两侧同名 `DashboardScroller` 职责不同」的命名陷阱）。
  - 第二步：部件行改横向卡片带（定宽两档 + `h-55` 外壳上移 + 悬停滚动按钮 + 行内拖拽）；12 件部件去壳 + 补
    **真实** loading/error/empty 三分支（统一封装 `useWidgetState`）；问候语行（按时段 + 时区，入口从 FAB 移到本行）；
    书架行外壳表头 + 多行（1..3）分带 + 单列/两列布局 + 面板控件；首启卡片上游化（失效文案同步改写）；
    页面三级错峰入场动效。
  - 依赖：显式新增 `vue-draggable-plus@^0.6.1`（触屏可拖；≈13–15 KB gzip）；**不引** `@vueuse/core`（`matchMedia` 自实现）与
    `lucide-vue-next`（图标走 `lib/icons.ts` 唯一注册表，新增 6 键）。
  - 契约：`WidgetId` localStorage 键一字不改（尺寸档位改两档零迁移）；行内拖拽经 `applyVisibleOrder` 做「可见子集 → 全量索引」映射；
    三个新纯函数 spec 登记进 `EXPECTED_SPECS`。
  - 验证：前端 **456 例 / 41 spec** 全过 + 后端图标契约 10 passed + 四连（type-check / test:unit / build / deploy）全绿。
  - commit：见 `docs/roadmap-gaps-remaining.md` 第 82 期段。
- **第 81 期（2026-09-30）· 「移除书库」改为「只删登记」+ 长文件操作后台化 + 回收站还原**（V0.81.0）
  - 缺陷形态：移除漫画库（约 2400 份 / 68 GB）时请求数小时不返回、前端显示「失败」；
    库仍在册但 `book_count` 持续下降，回收目录以 ≈79 MB/s（跨卷速率）增长 ——
    根因是大搬迁同步跑在 HTTP 请求内，且该库就地引用用户目录 ⇒ 被回收的「②」就是用户的本地原件。
  - 修法：① 默认路径**只删登记、零文件触碰**（同步立即返回），连文件一起清改为显式 `purge_files=1` +
    **后台任务**（类型 `librarypurge`，逐份真进度）；② `publish.recycle` 落点名保证 UTF-8 ≤255 字节
    （唯一实现 `fileops.recycled_name`）；③ 新增 `recycle_items` 台账 + `core/recycle.py` +
    `GET /api/recycle` / `POST /api/recycle/restore`（类型 `recycle`，**幂等可续跑**、目标已存在则退让改名不覆盖）。
  - 契约：回收台账表**刻意不含 `book_id`**（不进 remap 四处清单）；`_quiesce_background` 收后台长操作线程；
    `test_no_defaults_contract` 的形状正则放宽到 `async def`。
  - 验证：后端 **1335 例 / 1323 passed / 12 skipped / 0 failed**；前端四连全绿（447 例）。
  - commit：见 `docs/roadmap-gaps-remaining.md` 第 81 期段。
- **第 80 期（2026-09-29）· `update` 段配置从「看着有」变成「每个键都真有读点」**（V0.80.0）
  - 缺陷形态：`update.image` / `update.auto_apply` 写是写得进、`GET /api/config` 也回显、设置页报「已保存」，
    但**后端没有任何读点**（`image` 唯一读法是环境变量，`auto_apply` 连读点都没有）⇒ 改完等于没改。
  - 修法：新增 `updater.configured_image()`（唯一镜像读法：显式入参 > `update.image` > `NOVELFORGE_UPDATE_IMAGE` > 内置默认）
    与 `updater.maybe_auto_apply()`（自动更新，**先记后做**，同版本只尝试一次）；新增 `server._apply_update_config()`
    与既有 `_apply_watcher_config()` 并排，在 5 处配置写接口与 lifespan 复用 ⇒ `check_enabled` / `interval_hours` 保存即生效。
  - 契约：`tests/test_update_config_contract.py` 钉死「`EDITABLE['update']` ⇄ 设置页 `UPDATE_FIELDS` ⇄ 代码读点」三者一致；
    `tests/test_updater.py` 完全离线覆盖版本比较 / 出网三条路径与 1h 缓存 / 持久化往返 / 未挂载降级 / 镜像优先级 / 自动更新四象限。
  - 口径：解除「零外部请求 / 零依赖」硬约束 → 「默认自托管、默认不引；允许显式、可关、失败降级地引入」（本期**未新增依赖**）。
  - commit：见 `docs/roadmap-gaps-remaining.md` 第 80 期段。
- **第 79 期（2026-09-29）· 漫画 / 有声书：一级子文件夹内「同前缀 + 尾部编号」合并为合集**（V0.79.0）
  - 用户实况 `超人前传0904.pdf` / `超人前传1408.pdf` 这类散文件 ⇒ 文件夹整体合成**一本合集**
    （书架 1 条、话数 = 文件数、话序按序号、逐话连读）；判据在 `novelforge/core/units.py`
    （新增第四形态 + `is_unit_dir` 的「同前缀」闸），`library.SCAN_RULE_VERSION` 1 → 2 让存量书架自愈。
  - ⚠️ 实现比原方案更严一处（实测倒逼）：原方案的正则会把 `vol.1`（现有契约里必须是 `None`）
    认成「第 1 话」⇒ 收紧为「编号必须**紧贴**标题文字」，`作品名-1408` / `作品名_1408` / `作品名 1408` 不收。
  - 验证：后端全量 **1279 例 / 1267 passed / 12 skipped / 0 failed**（基线 1257 passed，只增不减）；
    真机（隔离实例 + Edge）：同前缀 ⇒ `UNITS`/2 话、混前缀 ⇒ 各自一本、库根平铺 ⇒ 各自一本、
    阅读器显示「1 / 2」可切话；口径标记改成 `1` 后**重启**即自愈回 `2`（幂等）。前端零改动。
  - commit：`9e29155`（判据本体 + 自愈）、`74b12e2`（契约测试）、`ea40e85`（版本号 V0.79.0）、文档与记忆见同期末笔。
- **第 68 期（2026-09-28）· 两处载荷优化（都带前后对照）**
  - ① **`/api/books` 不再下发简介正文**，改发 `has_description` 布尔（`server._card`）：
    原始 **1,363,248 B → 417,189 B（−69%）**，**gzip 后 491 KB → 37 KB**（正文去掉后剩余字段重复度高、压缩率更高）。
    前端两处消费方同步改造：元数据缺口筛选改看布尔、快速预览改从**详情**取正文；新增契约 `tests/test_card_payload.py`（2 例）。
  - ② **`/api/library-migrations/preview` 单次 ~300 ms → 37 ms**：原先**每本书**都调一次 `libraries_of_type()`
    （= 读一遍库表 + 组装列表），改为循环外一次算好「类型 → 同类库 / id → 库」映射，目标库根按库缓存。
    并把它**每次打开被调 2 次 → 1 次**：成因是 `App.vue` 的 `showLogin` 初值 `false` ⇒ 先挂载 → 鉴权失败卸载 → 登录后再挂载；
    改用「鉴权已裁决」标记 `authChecked` 门控（`auth.ready` 不行 —— 它在 `init()` 内先变真，中间仍有一个 tick 会挂载）。
  - 验证：后端全量 **1182 / 0 failed / 0 error**（+ 新契约 2 例）；前端 `type-check` / `test:unit`（340）/ `build` / `deploy` 全绿；
    真机（600 本库）复测：preview 1 次、`/api/books` 1 次真实拉取（38 KB gzip）。
- **第 67 期（2026-09-28）· 提速验证与收尾**
  - 复现：自建 **600 本合成 EPUB** 大库 + 隔离实例；结论 —— 第 62 期的**书目索引确实生效**（冷扫描 600 ms、`/api/books` 65–73 ms）。
  - 修：① 响应 **gzip**（列表 1.36 MB → 491 KB；主包 1.02 MB → 301 KB）；② 前端**并发请求单飞闸**（一次页面加载
    `/api/books` **7 → 1**、stats 3 → 1、libraries 3 → 1、collections 2 → 1；整页首载 ≈4 MB → 1.04 MB）。
  - commit：`bb9e504`（gzip）、`2a84183`（文档记忆）、前端去重笔见同期日志。
- **第 66 期（2026-09-28）· 阅读器「自动续接」收尾**
  - 三处跨册续接收敛到唯一真值源 `frontend/src/lib/seriesNext.ts`；默认值统一为「开」（只改默认、不迁移存量）；
    文案统一「册」；补有声书「无系列」提示与单飞闸；同类提示 2 s 节流。commit `4031dda` / `c3f26a7`。
- **第 62 期 · 「书架 42 秒 → 毫秒级」**（并行会话）
  - 书目**索引落库**（`core/catalog.py`）、PostgreSQL 可选后端、Redis 读缓存、增量刷新每文件 3 次 stat → 1 次。

## 3. 下一期（第 83 期）候选

⚠️ 第 82 期**已交付**（见第 2 节）。下一期开工前先 `git log --oneline -12` + `git status --short` 定期号
（**期号会被并行会话用掉**）。

仪表盘相关的余留（对照文档 `docs/bookorbit/bookorbit-dashboard-styles.md` §5 待确认 + §7 未做项）：
每书架的「库范围」筛选、`BookQuickView` 三件套、封面入场动画 —— 均需先有用户需求再排期。

第 1 节 P1 起按优先级取（「元数据来源」页最后两条如实标注的「未支持」最接近可直接动手）；
若要做重投入项（例如再次跑大库基准、或做 PG/Redis 相关专项），**先量化再动手**
（本项目已在第 61 期明确：没有指标不许凭感觉优化）。
