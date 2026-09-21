# BookOrbit 全站能力缺口与添加方案

> 来源（历史实测）：`https://orbit.735876214.xyz:16666/`（线上实例，站点版本 **v2.10.0**）；采集日期 2026-09-16 ｜ 账号角色：Superuser（单账号本地部署）
> **源码对照（本轮新增）**：上游参考仓库 `https://github.com/735876214/bookorbit`，分支 `main` @ commit `c292d6cc`（v2.10.0）。只读镜像，不在本项目中复制上游代码，仅引用文件路径与结论。
> 用途：本文件是 novel_dl_convert **补齐线上能力**的排期依据，与 `docs/bookorbit-settings-inventory.md`（设置页 41 页清单）、`docs/bookorbit-library-contract.md`（类型契约）、`docs/bookorbit-feature-flows.md`（功能与流程）并列。
> 采集方式：浏览器自动化（Playwright CLI）**真实登录后逐页渲染采集**非设置页十个能力域；全程只读——仅导航、展开、点击进入子页、读取 DOM、截图；**未点击任何保存 / 删除 / 提交 / 启用 / 重置类控件**。
> 证据：逐页采集记录见 `docs/review/bookorbit-app-capture.md`；截图见 `docs/review/bookorbit-app-shots/`
> **脱敏**：全文不含账号、密码、邮箱、令牌、密钥真实值；此类字段一律只记「已设置 / 未设置」；含账号显示名的仪表盘截图主动未归档。
> **准确性约定**：①未取得可信值的项标注「未能采集」并说明原因；②本轮新增结论一律标注来源文件（`源码（<路径>）`），与历史实测（`历史实测（2026-09-16）`）分列，不混写；③凡源码无法确认的一律标注「**未验证（源码无法确认）**」，不做推测补全；④**「实例页面为空」不等于「上游无此能力」**——能力判断以源码为准，页面为空只在对应条目里说明 UI 侧未渲染。
> **本轮范围**：纯文档复核（零代码改动、零实例访问）；Hardcover / Readwise / StoryGraph 同步按用户拍板**本轮明确不做**（见 §13、§14）。
> ⚠️ **本文件只是三条轴里的一条（第 33 期加注）**：它按**页面 / 协议面**对照，因此**发现不了「整块模块从未进过视野」的缺口**。按上游代码模块逐条对照的结果另见 `docs/bookorbit-module-inventory.md`（67 个后端模块 + 33 个前端 feature；已实测出 16 个模块此前从未被判定过，含一个 94 文件的模块）。**找缺口时两份都要看，不要只 grep 本文件。**

---

## 0. 落地口径（本方案的前置约定）

### 0.1 档位定义

| 档位 | 含义 | 处理 |
| --- | --- | --- |
| **可直接落地** | 本项目已有后端支撑，或纯前端即可完成 | 排入路线图，直接做 |
| **需新增后端能力** | 需新写接口 / 表 / 模块，但架构不变 | **排入路线图，先补后端再实现能力** |
| **需架构变更** | 动摇现有单用户 / 单一成品目录假设 | **不落地**（见 0.2） |
| ~~**页面与接口保留、功能后置**~~ | 页面与接口先存在，具体能力后期实现 | **已废弃（2026-09-18）**：唯一用例是第 9 节的 Requests，而它已改为「已决策不做」，骨架页与只读接口均已删除 |
| **不建议做** | 与本项目定位无关，或维护成本远超收益 | 不实现，仅记录理由（见第 11 节） |

### 0.2 两条硬性落地原则

1. **与多用户有关的能力不落地。**「多用户」按**应用账号体系**界定：多账号与角色权限、邀请与自注册、免密登录链接、OIDC/SSO、账号活动审计、隐私与分享、内容限制、跨用户成就统计。
   **不计入**多用户（可做）：OPDS 客户端账号、KOReader/Kobo 设备凭据、外部服务 Token（Hardcover / Readwise / StoryGraph）、单用户语境下的「账号级偏好同步」。
2. **缺后端支撑的，先把后端做出来再把能力做完整**，不再以「缺后端」为由停在占位页。

### 0.3 本项目实况基线（判定依据）

> **第 27 期复核（2026-09-19）**：本节原记「68 个路由 / 6 张表」，已随第 1–26 期落地而失真 —— 失真的基线会让下游每条判定都失去依据，故按代码重取。
> **第 29 期重取（2026-09-20）**：本节**逐条重验，锚点全部仍然准确**（含 `config.py:20` / `library.py:1-3` /
> `auth.py:1-5` / `metadata.py:11-33` 四处引用）。唯一改动是**表数量**：原文写「**28 张**」，但同一句只枚举了
> **27 个**名字，实测 `CREATE TABLE` 也是 **27** —— **枚举是对的，计数写错了**。
> 另补一条**否定性说明**（下方），免得后来者按「审计日志」去找一张并不存在的表。

- 后端 `novelforge/server.py` 共 **262 个路由**（`grep -cE "^@app\.(get|post|put|delete|patch)\("`；第 29 期记 260 —— 第 31 期 +`GET /api/reading-activity`、第 32 期 +`POST /api/authors/{name}/sort-name`）；前端路由见 `frontend/src/router/index.ts`
- **唯一物理目录** `OUTPUT_DIR`（`novelforge/config.py:20`）；`novelforge/core/library.py:1-3` 明写「后端没有『图书库』实体」
- 单用户轻登录（`novelforge/core/auth.py:1-5` 明写不做多租户/角色；`users` 表无角色字段）
- SQLite 表 **27 张**（`novelforge/core/db.py` 的 `CREATE TABLE IF NOT EXISTS` 计数）：`users` / `progress` / `annotations` / `collections` / `collection_items` / `reading_sessions` / `reading_status` / `ratings` / `achievements` / `user_achievements` / `authors` / `series_meta` / `tasks` / `libraries` / `library_migrations` / `scrape_items` / `smart_scopes` / `opds_sources` / `pref_devices` / `pref_profiles` / `book_dock_items` / `notifications_read` / `koreader_docs` / `app_state` / `meta_cover` / `meta_online` / `meta_override`
- ⚠️ **审计/活动日志不是表，是文件**：`novelforge/core/activity_log.py:4-7` 明写落盘两份 —— `activity.log`（人类可读，可直接 tail）与 `activity.jsonl`（结构化，供接口与前端表格消费），目录由 `LOG_DIR` 控制。**上表里没有 `activity_log` 不是遗漏**；§14 第 0 期那条「审计日志」说的是给它加 `actor` 字段，不是新建表
- **元数据解析**来源是 EPUB 自身 + 文件名（`novelforge/core/metadata.py:11-33`）；**在线元数据抓取体系已于第 5 期落地**（`core/metasources.py` OpenLibrary / Google Books，均无需 API Key；`core/metafetch.py` plan→预览→apply，结果只落 `meta_online` / `meta_cover`、不改写文件）。
  ⚠️ 本节原写「**没有任何在线元数据抓取**」，与 §14 第 5 期「元数据自动抓取与治理 ✅」自相矛盾，以代码为准更正。

### 0.4 引用锚点的核法与局限（第 33 期，2026-09-21）

**背景**：第 32 期只核了「改判过的行」，没能发现 `:117` / `:138` 两处漂移。第 33 期因此对全文
**312 条**本项目 `文件:行号` 引用做了一次系统复核（上游 `packages/` / `client/` / `server/src/` 路径不计入）。
结果：**行号更正 25 处、路径补全 2 处、作废标注 1 处**（明细见下）。

**两个只读脚本**（都放在 `%TEMP%`，不随仓库提交）：

| 脚本 | 判什么 | 报什么 |
| --- | --- | --- |
| `nf33-anchor-check.py` | 结构性：文件能否解析 / 行号是否越界 / 目标行是否空行 / 是否纯注释 | MISSING / OOR / BLANK / COMMENT |
| `nf33-anchor-check2.py` | 语义：引用**前 80 字符内**若有 `/xxx` 字面量，看它在**被引行 ±N 行**内是否真出现 | 「疑似漂移」+ 该字面量在源码里的真实行号 |

**结构检查结果**：MISSING **0**、OOR **0**、BLANK **1**、COMMENT **5** —— 6 条全部**已知合法**
（BLANK 那条是本文件自己标注作废的历史锚点；5 条 COMMENT 是**有意**引用的代码注释）。

**语义检查结果与它的局限**（这段比结论重要，给下一次复核的人看）：

1. **窗口宽度是个两难，没有「对的」取值**。取 ±6 行时**漏报** `router/index.ts:161`
   （`/listen/:id` 真实在 `:165`，偏差 4 行被窗口吞掉）；收紧到 ±2 行，42 条里报出 34 条，
   **假阳性率约 80%** —— 引用旁 80 字符内的字面量常常属于**相邻的另一个**引用。
   ⇒ **这类脚本只能用来「生成待核清单」，不能用来判定。逐条并排打印后人工判，是唯一的用法。**
   本轮 28 处修改里有 5 处（`:66` / `:124`×2 / `:153` / `:165`）是**只有收紧窗口后才暴露**的。
2. **覆盖率天然很低**：42/312 = **13.5%**。不带字面量的引用（纯中文描述，如「阅读状态字段」）
   自动核不了，仍靠人工。
3. **区间引用（`a-b`）测不出漂移**：只要区间内**有任何一行**非空非注释就归 OK。
   `BookDetailView.vue:487-505` 声称是「文件」标签，实际是**章节 tab 的搜索框与卷列表**，两个脚本都放行。
   ⇒ 对区间引用只能**按「它声称是什么」反向 grep 定位**；本轮 3 处区间漂移（`:124` 两处、`:316`）
   都是这么找出来的。
4. **简写会误报 MISSING**：`hardcover.ts:139`（上游简写）与 `roadmap-verification.md:24`（`docs/` 简写）
   被当成本项目文件而找不到 —— 已补全为全路径。**引用一律写全路径，别写简写。**

**本轮更正明细**（⚠️ 下表「**原引用**」列是**已作废的历史值**，复核脚本会照旧把它们报成
MISSING / OOR / BLANK / COMMENT —— **这是预期噪声，不必再修**；只有「实测应为」列才是当前的引用）：

| 文档行 | 原引用 | 实测应为 | 目标 |
| --- | --- | --- | --- |
| :65 / :99 | `router/index.ts:196` | `:204` | `/tools/libraries` |
| :66 | `router/index.ts:158` | `:162` | `/smart-scopes` |
| :69 | `server.py:3826` / `:3854` | `:3880` / `:3908` | `GET /api/notifications` / `POST /api/notifications/read` |
| :71 | `router/index.ts:172` | `:179` | `/achievements` |
| :73 | `router/index.ts:174` / `:173` / `:91` | `:182` / `:181` / `:95` | `/docs` / `/whats-new` / `/settings/ext/about` |
| :104 | `server.py:2270-2283` | `:2297-2308` | `GET /api/libraries`（原指到 `_norm_rules` 的 docstring） |
| :104 | `router/index.ts:154-209` | `:157-216` | 路由全表区间 |
| :124 | `BookDetailView.vue:487-505` | `:528-545` | 详情页「文件」标签（原为章节 tab 的搜索框） |
| :124 | `BookDetailView.vue:404-415` | `:445-475` | 概览侧栏「成品文件」（原为制版说明） |
| :150 | `views/ReaderView.vue:28-31` | 补 `:805` | 原引是文件头注释；实际渲染在 `:805` 的 `v-html="html"` |
| :153 / :165 | `router/index.ts:161` | `:165` | `/listen/:id` |
| :232 | `router/index.ts:174` | `:181` | `/whats-new` |
| :278 | `server.py:3740` / `:3735` | `:3791` / `:3786` | `POST /api/watcher/stop` / `:start` |
| :278 | `server.py:3766` / `:3775` | `:3817` / `:3826` | book-dock rescan / ignore |
| :278 | `server.py:3747` / `:5207` / `:3784` | `:3798` / `:5261` / `:3835` | `POST /api/scan` / `POST /convert` / book-dock delete |
| :316 | `server.py:2058-2095` | `:2085-2108` | `/api/annotations` + `/api/annotations/overview` |
| :439 | `data/tasks.ts:21-28` | 标注作废 | 种子已删，该文件现只剩 14 行类型 |
| :124 | `hardcover.ts:139` | 补全上游全路径 | `packages/types/src/hardcover.ts:139` |
| :364 | `roadmap-verification.md:24` | 补全 `docs/` | `docs/roadmap-verification.md:24` |

⚠️ **一条要带走的教训**：`:278` 原先写的是「**锚点整体偏移 1 行**已更正」—— 实测偏移 **44–54 行**。
**「整体偏移 N 行」这种描述本身会过期**：只要上方插入过任何代码就立刻失真。
⇒ **别记偏移量，只记当前真实行号。**

---

## 1. 域：应用外壳

> **第 29 期复核（2026-09-20）**：本域此前**从来没有复核头**，14 行全部是**第 4 期旧文**。
> 本轮逐行按代码改判，结果：**已过期 6 行**（54 全局搜索 / 55 Notifications 浮层 / 59 Help /
> 60 Appearance 浮层 / 62 用户菜单 / 49 侧栏主导航部分）、**部分过期 2 行**（58 Upload books / 63 版本标识）、
> **结论仍成立但锚点失效 6 行**（50 / 51 / 53 / 56 / 57，锚点已逐个换新）。
> ⚠️ 本域暴露出一条**通用教训**：这 6 行「结论对、锚点错」的行最危险 —— 结论对得让人不去复核，
> 而 `文件:行` 早已指到别的代码上（例如原 `router/index.ts:96-100` 今天落在无关代码上）。
> 因此本轮**对仍成立的行也一律重取锚点**。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 侧栏主导航 | Dashboard / Book Dock / Requests / Tools | **部分过期 —— 功能层已补齐，位置与文档写的不一样**：主导航现为 **8 项**（仪表盘/探索发现/任务中心/工具/数据统计/**阅读记录**/**通知中心**/**成就**，`data/nav.ts:32-49`）。**Book Dock 已实现**（`core/bookdock.py` + `GET /api/book-dock` 与 rescan/ignore/delete，`server.py:3760-3787`），但它是**设置页**（`views/settings/pages/BookDockPage.vue:15-26`，路由 `admin/book-dock`），**不是侧栏项**（`components/AppSidebar.vue:21-34` 的路由表里没有它）。**Requests 确实没做**：全仓 `/api/requests` **零命中**，只剩设置注册表里一个 `placeholder` 占位（`data/settingsNav.ts:501`） | Book Dock **已落地**／Requests **已决策不做**（§9） | 原判「Book Dock 可直接落地，可复用 INPUT_DIR + watcher」**已实现** —— 目录监听与 Book Dock 本就是同一套（`BookDockPage.vue:15-26` 自陈「投递目录 = INPUT_DIR」） |
| BROWSE 组（Authors / Series / Annotations） | 三个入口 | **已有**（侧栏「浏览」组 = 作者/系列/批注，`data/nav.ts:51-59`；路由 `router/index.ts:166-170`） | **已落地** | 结论仍成立、锚点已换（原 `router/index.ts:96-100` 今天落在无关代码上）；**档位第 32 期更正** —— 能力早已在手，不该继续占排期位 |
| LIBRARIES 组（`/library/:id`、`/libraries`、New Library） | 多书库实体 + 分组菜单 | **第 10 期已实现多库实体**：侧栏「库」组列**真实书库**（`GET /api/libraries` 返回库实体，含类型 / 归属模式 / 书数，`server.py:2270-2283`）+「全部书库」置顶（`components/AppSidebar.vue:96-110`），点击**切库 + 进书架**（`AppSidebar.vue:165-170`）；原先的「格式 / 待修复 / 无封面」分面已改址 `GET /api/library-facets` 且不再占侧栏（`server.py:2299-2305`） | ~~需架构变更 → 不落地~~ **已落地** | 仍无 `/library/:id` 独立路由（用「当前库」状态替代；书库实体管理在 `/tools/libraries`，`router/index.ts:204`），但 `OUTPUT_DIR` 假设已被推翻。**结论仍成立，锚点已换** |
| SMART SCOPES | `/smart-scopes` + New Smart Scope | **自定义已落地**（第 10 期起）：独立路由 `/smart-scopes`（`router/index.ts:162`）+ 管理页 `views/SmartScopesView.vue:100-131`（增删改）、`:147-264`（表单 + 列表 + 实时预览命中数）；后端 CRUD `server.py:2939 / 2951 / 2963 / 2977`；侧栏把规则书架并入「智能书架」组、组头「+」直跳该页（`AppSidebar.vue:124-137`、`:186-190`）。固定 5 个仍在（`data/collections.ts:22-28`） | **已落地** | 原判「无独立路由、无自定义」两条均已过期 —— 这正是「结论过期」而非「锚点漂移」的典型 |
| COLLECTIONS | `/collections` + New Collection | **已有**（路由 `router/index.ts:171-172`；后端 CRUD 自 `server.py:2871` 起；侧栏用真实数据渲染且「+」走真实创建，`AppSidebar.vue:113-123`、`:191-201`） | **已落地** | 结论仍成立、锚点已换（原 `router/index.ts:101-102`、`server.py:516-568` 均已失效）；**档位第 32 期更正**。⚠️ 第 32 期另修了这条链路上的一处假动作：新建收藏夹**失败**时提示曾被套上「演示动作」前缀，现改走 `ui.toast` + `lib/api.ts` 的 `apiErrorMessage()`（剥掉后端 `{"detail":"…"}` 的花括号） |
| 全局搜索（⌘K） | 跨库检索 | **已落地**：回车**真跳转**并带查询串 —— `components/AppHeader.vue:23-36`（关键在 `:32` 的 `router.push({ path: '/shelf', query: { q } })`，代码注释自陈「原先这里只弹一个 demo 提示」）；书架页消费 `q`：`views/ShelfView.vue:143-145`（读取 + watch 同步）、`:188-196`（按 title/author/series/name 四字段过滤）、搜索框 `:412-418` | **已落地** | 原判「UI 齐全但未接后端」已过期。⚠️ 口径更正：实现是**在已加载书单上做前端过滤**，**没有**新增跨库检索接口 —— 原档位理由「加一个查询接口即可」也随之失效 |
| Notifications 浮层（Mark all read / Clear） | 顶栏浮层 + 流水 + 已读 | **已落地**：铃铛挂真实浮层（`components/AppHeader.vue:89` → `components/NotificationBell.vue:122-185`），「全部已读」在 `NotificationBell.vue:130-138`（→ `:50-61`），单条点击标记已读 `:63-71`，未读角标 `:114-119`；后端 `GET /api/notifications`（`server.py:3880`）+ `POST /api/notifications/read`（`server.py:3908`）+ `notifications_read` 表已建 | **已落地（Clear 除外）** | 原判「无浮层、无已读态」「需新增后端能力／需新表」**三条全部过期**。⚠️ **Clear 本轮（第 31 期）仍不做**：第 31 期补全取证 —— 上游 `packages/types/src/notification.ts` 定义 **30 种通知类型**（`NotificationType`）+ 11 个 `NotificationCategory` + `NotificationSeverity`（success/warning/error）+ `NotificationLevel`（off/problems/all），但**本项目无通知产生端**（`notifications_read` 表仅记录已读，全仓无 `notifications` 写入调用），「清空全部通知」无对象；且清空日志入口已存在于 `settings/pages/WatcherPage.vue:154`、`tools/LogsView.vue:151`，再做会重复。故浮层无 Clear，继续标「未落地」 |
| Statistics | `/statistics` | **已有**（`/stats`，`router/index.ts:176`；顶栏亦有入口 `components/AppHeader.vue:90-92`） | **已落地** | 结论仍成立、锚点已换（原 `router/index.ts:103` 已失效）；**档位第 32 期更正** —— 本页第 32 期补到 **21 张图 + 图表配置面板**（见 §6） |
| Achievements | `/achievements` | **已有（第 22 期实现）**：路由 `router/index.ts:179` + `views/AchievementsView.vue`；后端 `server.py:3555`（列表）、`:3565`（backfill）；维护页 Backfill 按钮 `settings/pages/MaintenancePage.vue:137-142`、`:315` | **已落地** | 新表 `achievements` + `user_achievements` + 派生规则（单用户内可行，不涉多用户）；维护页已接入 Backfill 按钮。结论与锚点均仍准确 |
| Upload books | 上传（支持多格式） | **已落地（第 30 期收口）**：前端 `tools/LocalConvertView.vue:165` 的 `accept` 现跟随后端允许集（`.txt` ∪ `pipeline.EBOOK_EXT`，见 `core/pipeline.py:8` / `core/audio.py` 的 `AUDIO_EXTS`），文案同步放开；拖拽/选择做了扩展名**前端预校验**并给可读提示；下载名改为读响应头 `Content-Disposition`（兼容 `filename*=UTF-8''` 与裸 `filename=`），不再自己拼 `.epub`，彻底修掉 `x.epub.epub`；`/convert-path` 与 `/convert` 同口径改为返回 `FileResponse`（后端给真实文件名） | 已落地 | 原判「后端硬校验」（`server.py:1072-1073`，已失效）**已过期**。⚠️ 上一轮记的「残留不一致（静态阅读所得）」—— 拖拽无校验、下载名拼 `.epub`、投非 txt 得 `x.epub.epub` —— **第 30 期已全部修复**（改动：`LocalConvertView.vue`、`lib/api.ts` 的 `requestBlob`、后端 `/convert-path` 改 `FileResponse`） |
| Help（Documentation / What's New / About） | 三项 | **已落地**：Documentation = `/docs`（`router/index.ts:182` + `views/DocumentationView.vue`）；What's New = `/whats-new`（`router/index.ts:181` + `views/WhatsNewView.vue` + 数据 `data/whatsNew.ts`）；About = `/settings/ext/about`（`router/index.ts:95` → `settings/pages/AboutPage.vue`）。**第 30 期补了顶层 Help 菜单**：侧栏新增「帮助」分组（说明书 / 更新日志 / 关于），复用上述三路由（`data/nav.ts` 的 `帮助` 分组 + `components/AppSidebar.vue` 的 `PATH_BY_ID`/`PATH_TO_ID` 加 `docs`/`whatsnew`/`about`），不新建页面 | 已落地 | 原判「Documentation / What's New 无」已过期。**上一轮记的「残留缺口：无顶层 Help 菜单」—— 第 30 期已补侧栏「帮助」分组** |
| Appearance 浮层 | 顶栏浮层 | **已落地**：`components/AppearanceMenu.vue:86-145`（主题 Segment / 点缀色 SwatchGrid / 圆角 Segment + 「恢复默认外观」），「完整设置」跳 `/settings/appearance/theme`（`AppearanceMenu.vue:59-62`），挂载点 `components/AppHeader.vue:105` | **已落地** | 原判「主题循环按钮 + 无浮层」已过期。**第 32 期补**：外观设置三页里的 **Layout / Behavior 两页已做实**（`settings/pages/LayoutPage.vue` / `BehaviorPage.vue`，偏好并入既有 `appearance` 块、新增 `stores/displayPrefs.ts`）；**Icons 页仍为 placeholder 并如实标注** —— 本项目图标是内联 SVG 常量集（`lib/icons.ts`），做「图标风格 / 自定义上传」成本远超收益，**主动不做**，不假装做了第三页 |
| Language 浮层（25 语言） | 全站 i18n | **无**（界面中文硬编码） | **不建议做** | 见 §11 |
| 用户菜单（Account / Change Password / Sign out） | 浮层 | **已落地**：头像已是按钮 + 浮层（**不再是静态 div**）—— `components/UserMenu.vue:68-114`，挂载 `components/AppHeader.vue:109`；Account 页 = `/settings/account/profile`（`UserMenu.vue:34-37` → `settings/pages/ProfilePage.vue`，含账号展示 + 修改密码 `:243-267` + 退出登录 + 成就开关 + 头像 + 显示名 + 时区）；Sign out = `UserMenu.vue:39-44`（清 token 并派发 `nf-unauthorized`）+ 按钮 `:108-112` | **已落地** | 原判四条断言（无 Account 页 / 无 Sign out / 无浮层 / 静态 div）**全部过期** |
| 版本标识 / What's New | `/whats-new`（v2.10.0） | **已落地（第 30 期，后端为权威）**：收敛为**单一版本常量** `APP_VERSION = "0.6.0"`（`server.py:100` 附近），`FastAPI(version=APP_VERSION)` 与 `GET /health` 返回的 `version` 同读它（`server.py:244-256`）；前端 `HealthInfo` 加 `version`（`lib/api.ts:15-22`），About 页「版本」行（`settings/pages/AboutPage.vue:30-46`）与更新日志页头（`views/WhatsNewView.vue`）统一渲染后端下发的版本，**前端不再手写版本号**（`data/whatsNew.ts` 的 `version` 字段已删除） | 已落地 | ⚠️ 上一轮指的「同源性问题」（前端 `v0.6` 手写常量 vs 后端 `0.5.0`）—— **第 30 期已解决**：后端为唯一真值源，前端只读 `/health` 的 `version`，并加契约测试钉住同源 |

## 2. 域：书架与智能书架

> **第 29 期复核（2026-09-20）**：本域此前**从来没有复核头**，11 行全是**第 4 期旧文**。
> 本轮逐行按代码改判，结果：**已过期 10 行**、**仍成立 1 行**（74 库级控制）。
> **第 33 期补记**：那最后一行也倒了 —— **库级控制已落地**（`ShelfView.vue:457-469`：切库 / 立即扫描 /
> 书库管理三项）。原判「无此能力」是**纯 grep 假阴性**：词表 `libraries\|scanLibrary\|…` 一个都没命中
> 实际用的 `libraryEntities` / `scanShelf` / `manageLibs`。**本域至此 11 行全部落地**，
> 教训已写进该行理由栏，并同步进 `docs/bookorbit-module-inventory.md` 的方法学警告。
> 这是全文**过期最彻底的一节** —— 原判「无」的九项（搜索/排序/折叠/导出/统一筛选/多选/三视图/
> Display/书卡信息）**全部已实现**。⚠️ 请注意档位列里那些「需新增后端能力」的判断：
> 批量写接口（`POST /api/books/batch`）与导出接口（`GET /api/books/export`）**都已存在**，
> 原判把它们当作「待补的后端」是错的。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 书架搜索 | 搜索框 | **已落地**：工具栏搜索框（`aria-label="书架搜索"`，`views/ShelfView.vue:407-418`）；过滤 computed `searched` 按 title/author/series/name 四字段（`:188-196`）；顶栏全局搜索经 `?q=` 接进来（`:143-145`） | **已落地** | 原判「无搜索」已过期 |
| 排序 | Title ↑ 等多键 | **已落地**：排序**上移到页面层**（不在 store）—— `sorted` computed 支持 title/author/series/progress/pages/stars/added + 升降序（`ShelfView.vue:210-245`），字段选择器 `:439-446`、升降序按钮 `:447-453`，选项定义 `stores/shelfPrefs.ts:15,43-51` | **已落地** | 原判「无排序」已过期，**锚点也错**：原引的 `stores/library.ts:94-99` 今天是 `SMART_KEYS` 常量表；`shelfBooks` 今天在 `library.ts:165-170`（确实不含排序，但结论不能据此下） |
| Collapse series | 折叠同系列 | **已落地**：工具栏 toggle `ShelfView.vue:454-461`；`rows` computed 按 `series` 合成一条并带展开态（`:250-274`），展开集合 `:147`，列表/表格的展开行 `:309-324`、`:327-345`；系列内按序号重排 `lib/bookInfo.ts:73-83` | **已落地** | 原判「无」已过期 |
| Export metadata | 导出书目元数据 | **已落地**：书架「导出 CSV」按钮 + `onExport`（`ShelfView.vue:44-51,483`）；客户端 `api.exportBooks`（`lib/api.ts:1872-1885`）；后端 `GET /api/books/export`（`server.py:978-1018`，**17 列**含系列/序号/格式/大小/出版年/出版社/语言/ISBN/题材/入库日期/进度/状态/评分/批注数），行生成 `library.export_rows`（`core/library.py:1197-1221`） | **已落地** | 原判「无」「需新增后端能力」均过期。注：`tools/OutputView.vue` 今天**仍只下载文件本体**（`:11,62,93`）—— 导出能力是**新增在书架页**，两者已分家 |
| Filters 面板 | 统一筛选面板 | **已落地**：统一筛选面板 Card（`ShelfView.vue:488-536`），筛选按钮带脏标记 ●（`:462-468`），维度 = 格式/语言/题材/封面/阅读状态（`:161-172`、`:489-535`），过滤 computed `:198-208`，清除 `:174-180,534` | **已落地** | 原判「无统一面板」已过期。⚠️ **上一轮记的死入口 `shelfTag` —— 第 30 期已删净**：`openShelf(title, tag)` 改为 `openShelf(title)`（所有调用点本就不传 tag，见 `AppSidebar.vue:178,307`、`dashboard/DashboardShelfRow.vue:54`、`library.ts:304`），`stores/library.ts` 里的 `shelfTag` state（`:79`）、过滤分支（`:168`）、清空（`:289`/`:298`）、导出（`:313`）一并移除，题材筛选由面板 select 承担（`ShelfView.vue:507-513`） |
| Show library controls | 库级控制 | **已落地（第 33 期改判；原判「无此能力」是 grep 假阴性）**：书架页工具栏下方**有库级控制条** —— `ShelfView.vue:457-469`，三项分别是**切库** `<select v-model="currentLib">`（选项来自 `library.libraryEntities`）、**立即扫描**（`@click="scanShelf"`）、**书库管理**（`@click="manageLibs"`）。代码注释写明这是「最小集」，**重命名与删除仍在 `/tools/libraries`**（`router/index.ts:204` → `views/tools/LibrariesView.vue`，后端 `PATCH/DELETE /api/libraries/{lid}`，`server.py:2390`、`:2459`），「避免第二处写入口」——是**有意为之的取舍，不是遗漏** | **已落地** | ⚠️ **原判的教训（第 33 期记）**：当时用 grep 词表 `libraries\|renameLibrary\|deleteLibrary\|scanLibrary\|新建\|重命名\|删除` 判「零命中 ⇒ 无此能力」，而实际代码用的是 **`libraryEntities` / `scanShelf` / `manageLibs`** —— 词表一个都没覆盖到，**grep 假阴性**。同一类错误在按模块名 grep 时**假阴性率过半**（实测 34/67 零命中、真正未判定的只有 16 个，见 `docs/bookorbit-module-inventory.md`）。**判能力有无只能按语义找 + 落到 `文件:行号`；grep 只能用来找起点，不能用来判定「不存在」。** |
| SELECT（多选模式） | 多选 + 批量动作 | **已落地（含后端）**：`selectMode`/`selected`/`toggleSelect`/`selectAllVisible`/`runBatch`（`ShelfView.vue:53-137`），「多选」按钮 `:435-437`，批量动作条（标记状态/评分/加入收藏夹）`:538-558`，三视图内勾选框 `:580-586`（网格）、`:671-677`（列表）、`:732-738`（表格）；**后端批量接口已在**：`POST /api/books/batch`（`server.py:1038-1088`，动作 set_status/set_rating/add_to_collection） | **已落地** | 原判「无多选」与「批量写需新增后端能力」**均过期** —— 批量接口不是待补项，是已存在的 |
| **Grid / List / Table 三视图** | 三视图切换 | **已落地**：grid `ShelfView.vue:568-635`、list `:637-706`、table `:708-783`；切换按钮 `v-for SHELF_VIEW_OPTIONS`（`:421-433`）；选项与类型 `stores/shelfPrefs.ts:14,37-41` | **已落地** | 原判「仅 Grid」已过期，**锚点也错**：原引的 `ShelfView.vue:74-77` 今天是 `visibleIds()` 内部的分支 |
| Display 面板（书架级） | 书卡信息/密度 | **已落地**：书架级显示偏好已持久化 —— `ShelfPrefs`（view/sort/dir/collapseSeries）`stores/shelfPrefs.ts:20-35`、书卡信息密度三档 compact/standard/detailed `:17-18,53-57`、筛选面板开关 `:84`，localStorage 键 `nf-shelf-prefs`（`:28,86-92`）；UI 在工具栏第二行「书卡信息」chips + 恢复默认（`ShelfView.vue:471-485`） | **已落地** | 原判「仅仪表盘有部件面板」已过期。⚠️ 形态差异：本项目是**工具栏常驻**而非浮层「面板」—— 能力等价，形态不同，如实记录 |
| 书卡信息（格式徽章/系列 #序号/出版日期·语言/题材） | 5 类信息 | **已落地（两处断言均已过期）**：格式徽章 `ShelfView.vue:594-600`；系列 `#序号` `:606-608`（列表 `:684-686`、表格 `:742-744`）；出版日期·语言·页数 `metaOf` `:614-615` → `lib/bookInfo.ts:44-46`；题材 `tagsLabel` `:618-622` → `bookInfo.ts:49-54`；评分 `:697-699,767-769`；进度 `:623-633`。集中定义见 `bookInfo.ts:3-10`（注释明写「对齐上游的 5 类」） | **已落地** | ⚠️ **原判「系列序号字段不存在」是错的** —— 解析器 `_series_index_of`（`calibre:series_index` + EPUB3 `group-position` 兜底）在 `core/library.py:71-90`，EPUB 探测处调用 `library.py:823`，下发书目字典 `library.py:1111`，前端契约 `lib/api.ts:526-527`。原引锚点 `core/library.py:63-75` 今天分别是 `norm_key`（63-69）与序号解析（71-90）—— **恰好指到了它声称不存在的那段代码上** |
| `/libraries` 列表页、`/library/:id` | 多书库 | **第 10 期已落地**：`GET /api/libraries` 返回**库实体**（`server.py:2297-2308`；原引 `:2270-2283` 是 `_norm_rules` 的 docstring，第 33 期全文复核改正）；侧栏「库」组 = 库实体、「全部书库」置顶、每项带书数胶囊（`AppSidebar.vue:96-110`），点击即**切库 + 进书架**（`:165-170`，store 侧 `library.ts:301-305`）；**无 `/library/:id` 独立路由** —— 路由全表 `router/index.ts:157-216` 无此路径，全仓 grep 零命中 | ~~需架构变更 → 不落地~~ **已落地** | 结论与今日实现一致（本轮复核确认）。同 §1 |

## 3. 域：书籍详情

> **第 29 期复核（2026-09-20）**：本域此前**从来没有复核头**，10 行全是**第 4 期旧文**。
> 本轮逐行按代码改判，结果：**已过期 8 行**、**部分过期 1 行**（89 DETAILS 字段）、**仍成立 1 行**（91 Files on disk）。
> **第 33 期补记**：Files on disk 那行的**结论仍成立，但档位改判为「已决策不做」**（理由见该行：单用户本地库
> 展示绝对路径无收益、反增信息泄露面），且**锚点已漂移** —— 原引 `:487-505` 今天是章节搜索框，
> 文件行实为 `:446-455` 与 `:528-545` 两处。**本域至此不再有「可直接落地」档位的行。**
> ⚠️ 本域是**「档位列集体判反」**的典型：原判的「需新增后端能力」五项（Edit Metadata / 阅读状态起止 /
> 书评 / 相似书 / 按书日志 / 手工补录）**后端全部已存在**，且都是**只写服务端、不碰源文件**的实现 ——
> 与本项目「源文件只读」的硬约束一致。**原判理由里说「复用 `_patch_opf` 写 OPF」的那个方向，恰恰是错的**。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 五标签（Details / Edit Metadata / Files / Reading Log / Highlights） | 5 个标签 | **已落地（且比上游多一档）**：今天 **6 个标签** —— 概览/目录/文件/批注/编辑元数据/我的记录（`TABS` 定义 `views/BookDetailView.vue:61-69`，渲染 `:336-353`）。与上游对应：Details=概览 `:356-436`、Edit Metadata=编辑元数据 `:536-538`、Files=文件 `:487-505`、Highlights=批注 `:508-533`、Reading Log ≈ 我的记录 `:541-543` | **已落地** | 原判「四标签」已过期，**锚点也错**（原引 `:30-35` 今天是文件头注释，且那段注释**自身也过期**：仍写「四标签」与「持久化字段将在引入 SQLite 后接入」，见下方「本轮发现」）。⚠️ 对应关系是**近似**：本项目的「我的记录」只有状态/起止日期/评分/书评，**会话级**日志在 `/log` 页 —— 不宜写成「已有 Reading Log 标签」 |
| Edit Metadata | 单书元数据编辑 | **已落地**：后端 `GET`/`POST /api/books/{bid}/metadata`（`server.py:1162-1186`、`:1188-1251`，三种取值语义：覆盖 / `null` 清空 / 空串撤销），另有 `/metadata/online`（`:1253`）与 `/metadata/revert`（`:1266`）；**只写服务端覆盖、不改写任何文件**（`:1190-1196,1226-1233` 明写「不再写文件：written 恒为空」）；前端 `components/book/MetadataEditor.vue`（357 行）挂在「编辑元数据」标签（`BookDetailView.vue:536-538`） | **已落地** | 原判「无」已过期。⚠️ 原判理由「复用 `_patch_opf` 加 POST 接口」**方向就是错的** —— 那会写回 OPF，与「元数据仅存服务端」的既定原则冲突。`core/fileops.py:193-254` 今天只服务实体改名与命名规则重出版 |
| 阅读状态 + Date Started / Finished | 显式状态字段 | **已落地**：表 `reading_status(book_id, status, started_at, finished_at, updated_at)`（`core/db.py:160-166`）；写入规则 `db.set_status`（`db.py:2369-2408`：进 reading/finished 自动记 `started_at`，进 finished 记 `finished_at`，**离开 finished 清零**）；接口 `GET`/`PUT /api/books/{bid}/status`（`server.py:1489-1503`，可显式传起止日期）；前端 `components/book/ReadingRecord.vue:26-32`（5 档状态）、`:84-126`（保存）、`:138-172`（「开始于/读完于」date input） | **已落地** | 原判「无起止日期」已过期。⚠️ 进度推导**今天只是兜底**：真实状态优先，无状态行才按 ≥99.5% 推导（`core/stats.py:146-165`）—— 原引锚点 `core/stats.py:46-51` 今天是 `integrity` 计数块 |
| YOUR REVIEW（书评 + 评分） | 可写书评 | **已落地**：后端 `GET`/`PUT /api/books/{bid}/review`（`server.py:1508-1528`，stars 与 review 一起保存，0/空串=清除）；落 `ratings` 表 review 列（`db.set_review` `db.py:1275-1286`、`db.get_review` `:1288-1300`）；前端「我的评分与书评」卡（5 星 + 清除 + textarea + 保存）`ReadingRecord.vue:175-221`；书架列表/表格也展示评分（`ShelfView.vue:697-699,767-769`） | **已落地** | 原判「无」「需新建 `reviews` 表」均过期 —— **没有新建表**，复用了既有的 `ratings` 表加列 |
| DETAILS 字段 | Publisher / Published / Language / Pages / ISBN / File Size / Library / Added | **已落地（第 30 期补全）**：版本信息区（`BookDetailView.vue:371-384` 一带，现为 `versionRows` computed）显示系列/书库（归属库，`book.library_id` → 库名，来自 `stores/library.ts` 的 `libraryEntities`）/入库（与导出 CSV「入库日期」同源：都是文件 `mtime`，`core/library.py:1219`）/出版年/出版社/语言/ISBN；**Pages 已展示并带来源标注**（非 EPUB 恒 0 → 不显示；`pages_source='estimate'` 标「EPUB 估算页数」、`'archive'` 标「归档真实页数」） | 已落地 | 原判「Pages 无来源 → 不建议做」**已过期**。**上一轮记的「`:379` 的『字数』写死 `'未知'`」—— 第 30 期按「不做假交互」约定删除了该行**（不引入新数据源） |
| EDITIONS（按格式列文件与大小） | 版本编号 + 格式 + 大小 | **已落地（格式/大小）；「版本编号」判定更正（第 30 期取证）**：「按格式列文件与大小」已落地（详情页「文件」标签 `BookDetailView.vue:528-545`、概览侧栏「成品文件」同源 `:445-475`；**原引 `:487-505` 今天是章节 tab 的搜索框与卷列表、原引 `:404-415` 是制版说明，均系第 33 期全文复核改正**）。上游取证显示所谓「版本编号」实为**外部书目版本**（Hardcover/StoryGraph 的 `edition`，如 `hardcoverEditionId`，见 `packages/types/src/book.ts:164`、`packages/types/src/hardcover.ts:139`），**非 BookOrbit 自有顺序版本号**；本项目无 Hardcover 集成，故**不引入「版本编号」概念**（也不造假数据）。「同 stem 文件枚举」后端在 `library.book_detail`（`core/library.py:1232-1263`） | 已落地（版本编号非本项目范围） | 原判锚点 `core/library.py:604-617` 今天是 `by_id`/`BookIdConflict` |
| Files on disk | 磁盘文件 | **仍成立（结论对，锚点已漂移，第 33 期修）**：文件行只给**库内相对路径**名 + 格式 + 大小 + mtime + 下载，**不展示绝对路径**。文件行**有两处**：概览区 `BookDetailView.vue:446-455`（格式徽章 + `fmtSize(f.size) · fmtDate(f.mtime)` + 下载）、文件 tab `:528-545`（同四字段的卡片式列表）。**原引 `:487-505` 今天是「章节搜索框 + 章节总数」，完全不相干**。后端返回 `f.relative_to(root).as_posix()`（`core/library.py:1250`）；协议层 `BookFile` 只有 `name/format/size/mtime` 四字段、**无 path**（`lib/api.ts:508-513`） | **已决策不做** | **第 33 期把档位从「可直接落地」改为「已决策不做」**，理由：本项目是单用户本地库，展示绝对路径在**远程访问 / 多端**下没有任何收益，反而多一个**信息泄露面**（服务器目录结构）。当前「只给库内相对路径 + 下载按钮」既够用又不泄露，是**正确的终态而非待办** |
| Similar Books | 相似书推荐 | **已落地**：后端 `GET /api/books/{bid}/similar`（`server.py:1530-1542`），实现 `core/recommend.py:18-24`（同作者/题材/系列，0 分不返回）；前端加载 `BookDetailView.vue:102-109`，渲染「相似书」块（标题 + reasons + 点击跳转）`:417-433` | **已落地** | 原判「无」「需新建 `core/recommend.py`」均过期 —— 该模块正是按原计划建的，只是文档没跟上 |
| Reading Log（Total time / Sessions / Average / Active days / Pace / Last read） | 按书聚合 | **已落地（第 30 期补 Average·Pace）**：接口三块 `GET /api/reading-log` → `items`/`by_book`/`recent`（`server.py:1544-1593`），按书聚合 `db.session_by_book`（现含 `seconds`/`sessions`/`last_ended`/`avg_seconds`，`core/db.py:886-899`，`avg_seconds` 由 `AVG(seconds)` 同一句 SQL 算出）；前端「按书」卡（`views/ReadingLogView.vue:208-226`）现显示 累计时长/次数/**平均单次时长**/最近日期，以及**阅读速度（页/小时）**—— 速度需页数，有可靠来源（`pages_source` 为 `estimate`/`archive` 且 `pages>0`）才算并标注，否则不显示（`paceText`）；**按书日志不在详情页**（避免与 `/log` 页重复入口） | 已落地 | 原判两个锚点均失效：`core/db.py:85-93` → 今天 session 表在 `db.py:112-118`；`server.py:573-585` → 今天写入是 `db.add_session`（`db.py:810-820`） |
| Add a session by hand | 手工补录 | **已落地**：后端 `POST /api/reading-log`（`server.py:1595-1649`，校验书存在 / 1–1440 分钟 / 日期 `YYYY-MM-DD` / 开始 `HH:MM` / **不补录未来**）；前端「补录」按钮 + 表单（书/日期/开始/时长）`ReadingLogView.vue:51-86,122-161` | **已落地** | 原判「无」已过期，锚点 `core/db.py:285-296` 亦失效（`db.add_session` 今天在 `db.py:810-820`） |

## 4. 域：阅读器

> **第 29 期复核（2026-09-20）**：本域此前**从来没有复核头**，6 行全是**第 4 期旧文**。
> 本轮逐行按代码改判，结果：**已过期 4 行**（101 PDF / 102 漫画 / 103 有声书 / 105 排版增强）、
> **仍成立 2 行**（100 ePub / 104 阅读偏好，锚点已换）。
> **第 33 期补记**：这两行**档位改判为「已落地」** —— 它们的「本项目现状」栏自己就写着已有证据
> （`/read/:id` + `ReaderView.vue`；`readerPrefs.ts` 全套 + 消费端绑定），**档位却一直停在「可直接落地」**，
> 是本文件典型的一类缺陷：**结论对、档位错**。同时修锚点：ePub 行的路由实为 `router/index.ts:164`
> （原引 `:160` 今天是 `/tasks`）。**本域至此不再有「可直接落地」档位的行。**
> ⚠️ 本域有**两处跨节自相矛盾**，裁定如下（均以代码为准）：
> **①有声书** —— §13「有声书阅读器」条早已标为**已过期**（第 9 期实现），而本节却仍写「无」；
> 代码证实 **§13 正确、本节作废**。**②PDF 阅读器** —— 本节称「后端硬拒绝」，但那条拒绝语
> 今天只约束 **EPUB 章节 HTML 流**这一条路径，PDF 走的是另一条接口，**本节作废**。
> ⚠️ 还有一处**易误判点**必须写明：`core/pdfrender.py` 是给 **Komga 客户端**逐页取图用的
> 服务端渲染（文件头 `:1-4` 自陈），**不是** Web 阅读器的实现 —— 拿它当「PDF 阅读器已存在」的证据是错的。
> 更根本的变化：阅读器今天已按格式分流为**四个独立子系统**（各有自己的偏好模块与设置页），
> 本表 6 行的结构**已不足以描述它** —— 新增部分见本节末尾补记。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| ePub 阅读器 | 完整 | **已落地（第 33 期改判）**：路由 `/read/:id`（**`router/index.ts:164`**，原引 `:160` 今天是 `/tasks`）+ `views/ReaderView.vue:28-31`（章节流机制的文件头注释；**实际渲染在 `:805` 的 `v-html="html"`**，第 33 期全文复核补齐）；后端 `GET /api/books/{bid}/chapter/{index}`（`server.py:1456-1467`，仅 `.epub` 放行）、`/api/books/{bid}/asset`（`server.py:1133-1140`，取 zip 内资源） | **已落地** | 注：**线上该页未采集到独立路由**，入口在详情页内。本条「本项目现状」栏自己就写着「已有」的证据，**档位却一直停在「可直接落地」，属本文件典型的「现状与档位自相矛盾」**（第 33 期一并收口）。锚点两处均已换过 |
| PDF 阅读器 | 完整 | **已落地**：前端 `components/reader/PdfReader.vue`（pdf.js 动态 `import('pdfjs-dist')` `:222-224`，取流 `url: /api/books/{bid}/file` `:231-233`，Bearer 走 pdf.js `httpHeaders`），接入 `ReaderView.vue:8`、`:42`、`:615`；后端 `GET /api/books/{bid}/file`（`server.py:1362-1377`，`FileResponse` 自带 Range/206）；详情页 `canRead` 已放行（`BookDetailView.vue:111-117`）；偏好 `lib/pdfPrefs.ts:11-53` + 设置页 `reader/pdf` | **已落地** | 原判「无」已过期。⚠️ **`仅 EPUB 支持在线阅读`（今天在 `server.py:1463`）只约束 `/api/books/{bid}/chapter/{index}` 这一条 EPUB 章节表单路径**，不能据此判 PDF 无阅读器 —— 这正是原判出错的机制。另注：PDF **刻意不开** `?token=` 口子（`server.py:1367-1368` 有明确理由） |
| 漫画阅读器（CBZ/CBR） | 完整 | **已落地**：前端 `components/reader/ComicReader.vue`（页列表 `api.comicPages` `:75`，页图 URL `api.comicPageUrl` `:46-48`），接入 `ReaderView.vue:9`、`:43`、`:616`；后端 `core/comics.py`（文件头 `:1-24`：zip/rar 魔数嗅探双后端、自然排序、`__MACOSX`/`.DS_Store` 过滤），路由 `server.py:1383-1394`（页清单）、`:1397-1411`（单页取图），**CBR 缺解压器时如实报 503**；偏好 `lib/comicPrefs.ts` + 设置页 `reader/comics` | **已落地** | 原判「无」已过期 |
| 有声书播放器 | 完整 | **已落地（第 9 期）**：`core/audio.py:16` `AUDIO_EXTS = (".m4b",".mp3",".m4a",".opus",".ogg",".flac",".aac",".wav")`；**`BOOK_EXTS` 今天在 `core/library.py:35` 且已含 `*audio.AUDIO_EXTS`**；路由 `GET /api/books/{bid}/audio`（`server.py:1423-1431`，轨清单）、单轨流（`:1434-1453`，带 Range，`?token=` 已登记于 `_MEDIA_TOKEN_PATHS` `server.py:139`）；前端独立路由 `/listen/:id`（`router/index.ts:165`）+ `views/AudioPlayerView.vue` + `components/reader/AudioPlayer.vue`，详情页入口 `BookDetailView.vue:120`（`canListen`）；偏好 `lib/audioPrefs.ts:10-40`（倍速/跳过/睡眠定时）+ 设置页 `reader/audio` | **已落地** | ⚠️ **本节此行为错误记载，已作废；以 §13 为准**（§13 早已标「已过期：第 9 期已实现」）。原判「`BOOK_EXTS` 不含音频，`core/library.py:31`」**锚点与事实双错**：常量在 `:35` 且已含音频 |
| 阅读偏好（主题/字体/字号/行高/宽度） | 完整 | **已落地（第 33 期改判）**：`lib/readerPrefs.ts:21-44`（`ReaderPrefs` 字段）、`:48-62`（默认值）、`:64-68`（`READER_FONTS`）、`:107-116`（滑杆范围 `READER_RANGES`）；消费端 `ReaderView.vue:64-67`（`prefs` 双向绑定 + 落盘）、`:89-107`（`contentStyle` 落到 `fontSize`/`lineHeight`/`maxWidth`/`fontFamily`） | **已落地** | 结论与锚点均经第 32 期复核、第 33 期复验仍成立。**档位原写「可直接落地」，与同行的证据自相矛盾**（原引 `ReaderView.vue:53-70` 恰覆盖该区块）—— 与上一行属同一批收口 |
| 深色主题 13 档 / 翻页模式 / 段落间距 / 断词 / 字距等 | 完整（设置页已采） | **已落地**：`lib/readerPrefs.ts:79-93` —— `READER_THEMES` **实为 13 档**（浅色 light/paper/sepia/gray 4 档 + 深色 charcoal/dark/black/midnight/navy/forest/wine/umber/slate 9 档）；翻页模式 `:19`（`ReaderMode = 'scroll' \| 'paged'`）+ `:70-73`，实现在 `ReaderView.vue:74-107`（定高分栏 + 横向翻页）；段落间距/两端对齐/断词/字距/词距/首行缩进/分栏定义在 `readerPrefs.ts:29-43`、渲染 `ReaderView.vue:97-103`、设置 UI `settings/pages/ReaderEbookPage.vue:47-52,77-82,93,148,152` | **已落地** | 原判「**无**（仅 3 档阅读主题）」**整句不成立** —— 13 档主题当时就已存在 |

> **补记（第 29 期）：阅读器今天已分流为四个子系统**，上表 6 行的结构不足以描述，故在此补记。
> 每个子系统各有独立的偏好模块与设置页：
>
> - **PDF**：`lib/pdfPrefs.ts:11-53`（scrollMode/spread/fit/zoom）→ `settings/pages/PdfPage.vue`
> - **漫画**：`lib/comicPrefs.ts:11-70` → `settings/pages/ComicsPage.vue`
> - **有声书**：`lib/audioPrefs.ts:10-40` → `settings/pages/ReaderAudioPage.vue`
> - **电子书**：`lib/readerPrefs.ts` → `settings/pages/ReaderEbookPage.vue` 与 `reader/fonts`
>
> 另：阅读入口**不止 `/read/:id`** —— 听书是独立路由 `/listen/:id`（`router/index.ts:165`）。

## 5. 域：工具

> **第 28 期复核（2026-09-20）**：Bulk Rename 那一行按代码改判 —— 原「有页面 `/tools/rename`」的
> 现状已不成立（页面与 `/api/rename/*` 一并删除），改名并入刮削面板；其余各行为第 27 期复核结论。
> **第 29 期复核（2026-09-20）**：本域**逐行重验，结果最不乐观** —— 5 行里 **3 行判定本身是错的**：
> **Duplicate Books**（称「无 scope、无可调阈值、精确分组」—— 三者**全部已实现**）、
> **Missing Resources**（称「无 clean 动作」—— 接口已在）、**Entity Manager**（能力对、锚点全错）。
> ⚠️ 尤其注意 Duplicate Books 的原锚点 `core/library.py:642-666`：它今天指向 `id_conflicts()`
> —— **那是 book_id 撞车清单，与重复书毫无关系**。这类「锚点指到隔壁功能上」的错误比结论过期更隐蔽，
> 因为锚点看起来「有据可查」。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| Entity Manager | 实体管理 | **已有**（能力成立）：前端 `/tools/entities`（`router/index.ts:205` → `views/tools/EntityManagerView.vue`）；后端 `GET /api/entities`（`server.py:3962`）、`POST /api/entities/rename/preview`（`:3969`）、`.../rename/apply`（`:3985`）、`POST /api/entities/merge`（`:4010`） | **已落地** | 结论仍成立、**锚点已换**（原引 `server.py:947-997` 今天是 `/api/books`（`:948`）与 `/api/books/export`（`:978`））；第 32 期再校一次 —— 本轮 `server.py` 整体后移 **54 行**。另注：第 28 期起改名**只写服务端元数据**（`server.py:3985-4007` docstring 明写「源文件名与文件内容都不动」） |
| Bulk Rename | **需先选书库** | **口径不同的自有实现**：第 28 期删掉 `/tools/rename` 页与 `/api/rename/*`，并入刮削面板的「命名规则」区块（`components/tools/ScrapePanel.vue:571` 注释、`:574` 标题「命名规则（副本名）」），规则 + 预览 + 一键重出版走 `/api/naming/preview`（`server.py:4027`）与 `/api/naming/apply`（`:4052`），实现 `core/scrape.py:443` `plan_naming` / `:509` `republish`（docstring 明写「**只动副本，源文件只读**」）。**「按书库」第 32 期已核实落地**：`plan_naming(library_id=..., scope=...)`（`core/scrape.py:443`）按库收窄候选（`:456` 取值、`:461` 传 `db.scrape_list`）；前端同一份配置**也按库**（`ScrapePanel.vue:63` 注释「生效值 = 每库覆写 ?? 全局」、`:296` 读 `librarySettings(libId)`） | 现状 **已落地**／按书库 **已落地** | 「只改副本名」是**刻意**与上游分流（上游改的是 `book.files[].filename`，与本项目「源文件只读」硬约束冲突）。⚠️ **第 32 期更正**：原写「scope 仍是扩展名而非书库」「按书库需架构变更」**已过期** —— 多书库第 10 期落地后 `plan_naming` 已按库收窄；`scope`（扩展名维度，`core/publish.py:120`）与「按库」是**两个正交维度**，不是替代关系 |
| Duplicate Books | Library scope 多选 + **Similar-title threshold 85%** + Run scan | **已落地（原判三条全错）**：`core/library.py:1288` `def duplicate_groups(threshold: int = 85, library_id=None)`；相似度用 `difflib.SequenceMatcher`（`:1304` import、`:1343` `ratio() >= thr`）+ **并查集单链法聚类**（`:1320-1350`），阈值钳制 50–100（`:1306-1309`）；接口 `GET /api/duplicates`（`server.py:5214-5215`，`threshold: int = Query(85, ge=50, le=100)` + `library_id: str = ""`）；前端阈值控件与库 scope 均在 `views/tools/DuplicateBooksView.vue:34`（`threshold = ref(85)`）、`:35`（预设 `[70, 85, 95]`）、`:177-191`、`:193`（`<LibraryScopeSwitch>`） | **已落地** | ⚠️ **原判「无 scope、无可调阈值、精确分组」三条全部过期**，档位列三段判定也随之作废。**锚点更是指错了功能**：原引 `core/library.py:642-666` 今天是 `id_conflicts()`（`:633` 定义）—— **book_id 撞车清单，与重复书无关**。附：阈值是 **70/85/95 三个预设按钮**，不是滑块。第 32 期再校：`server.py` 锚点后移 54 行（原 `:5160-5161`） |
| Missing Resources | Cover check + Run check + Missing books / Broken covers / **Orphaned cover folders** | **部分过期**：三类 issue 属实（`views/tools/MissingResourcesView.vue:30-46` `ISSUE_META`、`core/library.py:1382-1392` `missing_items`、`GET /api/missing` `server.py:5236-5239`）。**「无 clean 动作」已过期**：`GET /api/maintenance/orphans`（`server.py:3644`，只读扫描）+ `POST /api/maintenance/orphans/clear`（`:3650-3665`，清理），前端 `settings/pages/MaintenancePage.vue:156`「清理孤儿记录」。**「无 orphaned 目录」字面仍成立但概念已另立**：`server.py:3626` 起注释明写本项目对应物**不是**「孤儿封面目录」而是「DB 里指向已消失书籍的行」。**「无 sweep」仍成立**（全仓 grep `sweep` 零命中） | orphaned/clean **已落地**／sweep **已决策不做** | ⚠️ 原判「无 clean 动作」过期；**锚点也错**：`fileops.recycle_items` 在 `core/fileops.py:714`（原引 `309-339` 今天是 `_set_tags`/`patch_opf_meta` 一带的 OPF 改写代码）；且该函数**已被重复书籍清理实际复用**（`fileops.py:755` `resolve_duplicates` → `:758` 调用）。**sweep 档位第 32 期改判**：第 30/31 期取证坐实上游 `sweep` = `CoverSweep`（封面修复维护扫描，见 `packages/types/src/maintenance.ts`），与本项目「孤儿记录」是**两回事**；本项目封面链路走元数据抓取的封面写入，**不做**，故档位由「可直接落地（仍未做）」改为「已决策不做」 |
| 工具页签数 | 4 个 | **本项目 8 个**（`views/tools/ToolsLayout.vue:32-41` `SECTIONS` 恰 8 项：书库管理 / 实体管理 / 重复书籍 / 缺失资源 / 书源管理 / 导出目录 / 本地转换 / 转换日志；路由 `router/index.ts:203-213` 的 `/tools` 子路由 + 空路径重定向） | **已落地** | 已超出线上，**档位第 32 期更正**（能力在手不占排期位）。⚠️ 补一条：**实际可见数可能少于 8** —— `ToolsLayout.vue:48-50` 按库能力裁剪（书源管理需 `sources`、本地转换需 `convert`，真值源 `core/features.py`） |

## 6. 域：统计与成就

> **第 27 期复核（2026-09-19）**：本域原判定「无」的多数项在第 1–26 期已落地，下表按代码改判；每行结论可指到代码行。**Metadata Freshness 保留档位但更正了判据**（原判据与代码矛盾，见该行）。
> **第 29 期复核（2026-09-20）**：第 27 期「原样保留」的**两条原判（两大标签 / Integrity 四项百分比）
> 已于本期落地**，连同「Top 50 Largest Books」一并改判为**已落地** —— 本域**已无缺口**。
> 这三行的改判锚点全部指向本期新写的代码行（见下），不是「据说做了」。
> ⚠️ 本轮同时确认：**Metadata Freshness 仍是不做**，且理由仍是「价值低」而非「做不了」—— 那个判据更正依然有效。
>
> **第 31 期取证补记（2026-09-20）**：本环境仍无终端/网络，`client/` 与 `server/src/modules` **未能 fetch**（同第 30 期）；本轮取证范围限于 `%TEMP%\bookorbit-ref` 镜像内的 `packages/types` 与各根文档。已取证的真值源：`achievement.ts`（5 分类 + 4 稀有度）、`reading-session.ts`（`dailySummary{day,totalMinutes}` 热力图源 + `READING_SESSION_SOURCES` 分桶）、`account-activity.ts`（管理端账号活跃度，**非**阅读时间轴）、`maintenance.ts`（cover sweep / 缺失资源清理，服务端能力）、`hardcover.ts`（EDITIONS 属 Hardcover 外部集成）、`annotation.ts`（批注/高亮数据模型）、`notification.ts`（30 种通知类型，但本项目无产生端）。未取证部分（具体成就条目阈值、`client` 页面结构、`server/src/modules` 实现）一律标「未取证」，不凭空断言。
>
> **第 32 期复核（2026-09-20）**：本域是本期**改动最大的域** —— 统计页图表由 11 张补到 **21 张**
> （照搬上游 `client/src/features/statistics/statistics-chart-meta.ts` 的 33 张中**前 10 张**，
> 另加「图表配置」面板），`core/stats.py` 因此**整节重排**：文件由约 230 行涨到 **386 行**，
> **本表原先引用的每一个 `core/stats.py:行` 都已失效**，本轮按新行号**逐个重取**。
> 这是「锚点随代码膨胀而静默失效」的又一次实证：§1 复核头里那条通用教训（结论对、锚点错最危险）
> 对本域同样成立，**不要依据旧行号引用本模块**。
> **上游取证突破**：第 30 / 31 期两次 fetch 失败的上游 `client/`，本期找到可行路径（镜像 tree 本地已有，
> 走代理按需拉单个 blob），据此取到上游统计页的完整图表元数据与 `lib/echarts.ts` 基建形态 ——
> 结论已并入 §6 与 §15，**未取到的仍标「未取证」**。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 两大标签（Library Stats / My Reading） | 分区 | **已落地（第 29 期）**：`StatsView.vue:70-72` 定义两档 `TabKey = 'library' \| 'reading'`（默认「书库统计」），`:203` 用本项目既有的 `Segment` 原语渲染切换，`:238` 起按 `tab` 分支渲染两套区块；**第 32 期起两个分区各挂一组图表**（`ChartGrid` `:246`） | **已落地** | 本轮落地 —— 原判「单页无分区」已不成立 |
| 统计页图表（上游 **33 张**） | Library 19 / User 14，每张带 `label` / `size` / `category` （源码 `client/src/features/statistics/statistics-chart-meta.ts`） | **第 32 期补到 21 张**（原 11 张 + 本期 10 张）：书库侧 5 张 = Books Added Over Time / Language Distribution / Storage by Format / Page Count Distribution / Publication Year Timeline；阅读侧 5 张 = Reading Clock / Peak Reading Hours / Progress Funnel / Completion Timeline / Favorite Reading Days。**第 33 期补到 30 张**（13 张纯缺口 + 7 张手写卡片转正式 id）。基建照搬上游 `client/src/lib/echarts.ts`（**单点 `use([...])` 按需注册** + SVGRenderer + `oklchToHex()` 调色板 + 幂等主题注册），本项目落点 `frontend/src/lib/charts.ts`；图表元数据与默认顺序在 `frontend/src/lib/statistics-charts.ts` | **30/33（其余 3 张已归档：不做且不补死 UI）** | 上游真值源为本轮实拉取得。**三张刻意不做（第 34 期正式归档）**：`reading-source-distribution`「Where You Read」（本项目 `reading_sessions` 无 `source` 列）、`goal-trajectory`「Pace vs Goal」（无阅读目标设置）、`metadata-freshness-gauge`（第 30 期已判「价值低」）。**归档的含义**：只写文档，**不加组件、不加图表 id** —— 图表栅格没有兜底分支，登记了 id 却忘加组件会静默空白。⚠️ 上游 `reading-clock` / `peak-reading-hours` / `favorite-reading-days` 三图的 `BreakdownSelect`（format / source 维度）**本项目没有数据源**，**不做该控件** —— 三图降级为单序列，不造只动不响的控件 |
| 筛选（All Libraries）+ Configure + 时间粒度（Monthly/Yearly/Last 5 Years） | 参数化聚合 | **三项均已落地**。①时间粒度：`overview(days=28, top=8, library_id="")` 参数化并收敛 7–365（`core/stats.py:83-84`），响应含权威 `window`（`:374`）；②「All Libraries」**第 30 期落地**：`GET /api/stats` 增 `library_id`（`server.py:3232`），**空串 = 全库**（不传参时输出与改动前逐字节一致，8 个仪表盘部件零影响）；前端「统计范围」选择器默认跟随当前库（`views/StatsView.vue:189-191` + `stores/stats.ts`）；③**Configure 第 32 期落地**：`components/charts/ChartConfigPanel.vue`（显隐开关 + 上移 / 下移 + 恢复默认）+ `stores/statsChartPrefs.ts`（localStorage `nf-stats-chart-prefs`，600ms 防抖持久化、读取时校验、未知 id 过滤），入口 `StatsView.vue:233` | 时间粒度 / 多库筛选 / Configure **均已落地** | ⚠️ 上一轮记的过期理由「All Libraries 在本项目无对应概念（单库部署，config.py:20 唯一 OUTPUT_DIR）」**第 30 期已作废** —— 多书库第 10 期已落地，按库筛选只是顺延的补完。Configure 的**形态与上游不同**：上游是 shadcn Sheet + `vue-draggable-plus` 拖拽，本项目用既有 `Card` + **上移 / 下移按钮**（不引入拖拽库，功能等价、零新依赖） |
| Books / Authors / Series / Storage / Languages | — | **已有**（`core/stats.py:333-338` 的 books 块 + `:345-348` 的四个计数器榜） | **已落地** | 档位更正（第 32 期）：能力在手就不再占排期位。⚠️ 本行原引的 `:152-166` **已失效** —— 第 32 期 `stats.py` 整节重排 |
| Publishers / Genres | — | **已有**（`core/stats.py:347-348`，同一返回块）；统计页已渲染「Top 出版社」「Top 题材」（`StatsView.vue:350-352`、`:374-376`） | **已落地** | 档位更正（第 32 期） |
| Published 年份范围 / This Year | — | **已有**：`year` 按**十年**聚合（`core/stats.py:349-354` → `years.decades`），统计页已渲染（`StatsView.vue:399-403`）。「This Year」按日历年的入库数已有 `added_month`（`core/stats.py:301-312` 计算、`:378` 下发）；**第 32 期另补 `publication_yearly`**（逐年序列，供 Publication Year Timeline 图吃 —— **十年聚合键保留不动**） | **已落地** | 档位更正（第 32 期） |
| My Reading（Started / In Progress / Completed / **Avg Progress**） | — | **已有**：前三项在 `reading` 块（`core/stats.py:361-372`）+ **`avg_progress`**（`:355`） | **已落地** | 档位更正（第 32 期） |
| **Library Integrity**（Integrity / Present / Primary / Metadata） | 四项百分比 | **已落地（第 29 期）**：`core/stats.py:182-206` 在**原有 5 个计数键之侧**增补 `total_books` / `present(_percent)` / `primary(_percent)` / `metadata(_percent)` / `score`（对齐上游 `LibraryIntegrityGauge` 四值），返回 `:356`；前端 `StatsView.vue:146-161` 计算、`:429` 渲染大号 `score`% + 三条覆盖率，**原有计数行保留在分隔线下**（琥珀警告不变） | **已落地** | 本轮落地 —— 原判「计数有、百分比无」已不成立。⚠️ **口径差异已写进代码注释**（`core/stats.py:182-186`）：上游 Present = 文件在磁盘上，本项目书目**由扫描文件得来**、该值恒真，故改落在「文件有实体内容（非 0 字节）」；Primary 落在「主文件能被解析」 |
| Format Distribution | — | **已有**（`core/stats.py:336` 的 `books.by_format`）；**第 32 期另补 `by_format_size`**（按格式算体积，供 Storage by Format 图） | **已落地** | 档位更正（第 32 期） |
| **Metadata Score Distribution**（P50/P90） | 24 字段权重评分 | **已有**：`core/metascore.py` 评分模型 + `metascore.summary(scores=scores)`（Average / P50 / P90 + 分档直方图，`core/stats.py:50` import、`:358` 返回） | **已落地** | 档位更正（第 32 期） |
| Metadata Freshness（Fresh ≤30d / Never fetched） | — | **指标无**。⚠️ 原判据「依赖在线元数据抓取，与定位冲突」**已失效** —— 抓取体系第 5 期就落地了（`core/metafetch.py`，`meta_online.fetched_at` 已在库里，见 `core/db.py:241-250`），这个指标**技术上可直接算** | **不建议做**（档位依价值而非依赖） | 与本项目已有 `metadata_score`（完整度）口径重叠、增量信息少；**不是做不了，是不值得做** |
| Top 50 Largest Books | — | **已落地（第 29 期）**：`core/stats.py:207-230` 新增 `largest`（按体积降序，字段 `id/title/size_bytes/format`，对齐上游 `LargestBookItem`），返回 `:360`；前端 `StatsView.vue:164-166` 取数、`:491-494` 渲染体积榜、`lib/api.ts:2947-2952` 已传 `top=50` | **已落地** | 本轮落地 —— 原判「仓库无任何按体积的榜单」「前端从不传 top」均已不成立。⚠️ 榜单长度固定 50（`_LARGEST_N`，`core/stats.py:54`）、**刻意不跟随 `top`**：那个参数管作者 / 系列 / 出版社 / 题材四个计数器榜，混用会一加载就把四个榜一起撑到 50 行 |
| Achievements | 成就体系 | **已有（第 22 期实现）** | **已落地**（单用户口径） | 与多用户无关的成就可做；跨用户口径不做 |
| └ 阅读活动（时间轴 + 热力图） | `/reading-activity`：按日阅读分钟贡献热力图 + 时间轴活动流 | **第 31 期新增**：后端 `core/activity.py` 聚合 `reading_sessions`（按 `started_at` 日聚合 `SUM(seconds)/60` → 热力图，对齐上游 `reading-session.ts` 的 `dailySummary{day,totalMinutes}[]`）+ 合并 `annotations` / `user_achievements` / 阅读会话为时间轴；`GET /api/reading-activity`（`library_id` 复用 `library.by_library` 缓存，空串=全库）；前端 `ReadingActivityView.vue`（GitHub 式贡献日历 + 时间轴）。⚠️ 上游 `account-activity.ts` 是**管理端账号活跃度**（admin 用户列表），**非**阅读时间轴，二者不相干 | **已落地** | 上游热力图数据模型 `dailySummary{day,totalMinutes}` 已对齐；时间轴本项目自组（上游无单一 timeline 类型，由 sessions/annotations/achievements 合并）；`reading_sessions` 无 `source` 列，故无分设备热力图（上游有 `READING_SESSION_SOURCES` = web/koreader/manual/kobo 分桶），属刻意分流 |
| └ 上游成就模型（源码：`packages/types/src/achievement.ts`） | **5 分类**：`reading / library / exploration / dedication / devices`（标签见 `ACHIEVEMENT_CATEGORY_LABELS`：Reading/Library/Exploration/Dedication/Devices）；**4 档稀有度**：`common / rare / epic / legendary`；字段 `groupKey / tier / threshold / hidden / sortOrder / earned / awardedAt / currentProgress / iconName / context` | **第 31 期已对齐 5 分类**：原 3 组 `LIBRARY/READING/ANNOTATION` 重映射为 `library / reading / exploration`（批注归入 exploration）+ 新增 `dedication`（长周期坚持类，如更长连续天数 / 更高累计时长）；分组标题改用上游 `ACHIEVEMENT_CATEGORY_LABELS`。`devices` 仍**不引入**。`rarity / tier / hidden / iconName` 本项目**有意简化为无**（不改判定逻辑，UI 不展示稀有度档位） | 逐项对齐 **已落地（分类与条目）**；`devices` 分类 **仍不做**（上游依赖 `reading_sessions.source` 多设备分桶，本项目 `reading_sessions` 表无 `source` 列，无法喂数据，属刻意分流）；`rarity/tier/hidden` 为上游展示层概念，本项目不引入 | 上游进度由**服务端算好**（`currentProgress` + `threshold`），且支持**全量回填**（对应设置页「运行回填」）——本项目成就同为**派生数据**：进度实时算、只解锁不回退（`core/achievements.py`） |
| 仪表盘部件 | 12 件 | **已有 12 件**（`components/dashboard/widgets/registry.ts:47` 的 `WIDGETS`） | **已落地** | 档位更正（第 32 期）：已对齐，不再占排期位 |

## 7. 域：通知与更新

> **第 27 期复核（2026-09-19）**：本域两行**此前全判为「无」，已全部过期** —— 浮层与已读均已落地。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| Notifications 浮层 | 浮层 + 已读 + Mark all read | **已有**：头部铃铛挂浮层（`AppHeader.vue:89` → `components/NotificationBell.vue`），「全部已读」在 `NotificationBell.vue:137`；已读走后端 `POST /api/notifications/read`（`server.py:3908`）+ `notifications_read` 表（`core/db.py:135`）。整页日志视图保留，按类别偏好做客户端过滤（`lib/notifyPrefs.ts`） | **已落地** | 第 32 期再校锚点（`server.py` 后移 55 行）。**Clear 仍不做**：本项目**无通知产生端**，且清空日志入口已在 Watcher / Logs 页（见 §1 该行） |
| What's New | `/whats-new` | **已有**：`views/WhatsNewView.vue` + 路由 `/whats-new`（`router/index.ts:181`） | **已落地** | — |

## 8. 域：任务中心

> **第 27 期复核（2026-09-19）**：「任务真实性」原有的两项指控（6 条演示种子 + 900ms 假进度 ticker）**均已在第 25 期前后清除**，原判过期。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 任务中心 | `/tasks` **返回 404**（线上无此页） | **本项目有**（`/tasks` `router/index.ts:160`、`TaskCenterView.vue`、`TaskDrawer.vue`）——**超出线上** | **已落地**（超出线上） | 档位第 32 期更正；但见右栏风险 |
| 任务真实性 | — | **已改为全真**：演示种子与假 ticker 均已删除 —— `data/tasks.ts` 头注释明写移除始末，该文件现只剩类型；任务数据一律来自服务端任务表，`stores/tasks.ts` 轮询真实 `GET /api/tasks`；后端已持久化到 `tasks` 表（`core/db.py`，非进程内字典） | **已落地** | 原「假数据会让用户误判真实进度」的风险已消除 |

## 9. 域：求书（Requests）—— **已决策不做（2026-09-18）**

> **状态变更**：本条原定档位是「页面与接口保留、功能后置」（第 1 期建了只读骨架页 + `GET /api/requests/config`）。
> **2026-09-18 用户决策：C1 不做** —— 本项目的「从外部获取书」已由**数据驱动书源规则**覆盖，
> 插件式索引器 / 下载客户端与之形态重叠、维护成本高。
> **代码现状**：后端 `REQUEST_SECTIONS` 与 `GET /api/requests/config`、前端 `RequestsPage.vue`
> 及其路由 / 设置注册项 / API 方法 / 死链文案**均已删除**；`/api/requests/config` 现返回 **404**。
> ⚠️ 原「`Add to library（目标书库）` 依赖多库 → 不落地」的**旧理由已失效**（第 10 期多库已落地），
> 该项仍因**定位**而不做，请勿再引用旧理由。

| 能力项 | 线上形态 | 本项目现状 | 档位 |
| --- | --- | --- | --- |
| `/requests` 页面 + Beta 说明 | 「Ask for books the library does not have yet」+ 实验性提示 | **无**（能力最接近的是「探索发现」`ExploreView.vue`，但它是**即时搜索→下载**，不是「登记需求、等待匹配」） | **不做**（原骨架页已删） |
| 「No search sources are set up…」+ **Add a source** | 引导文案 + 按钮 | 形态不同：本项目书源是数据驱动 JSON 规则（`novelforge/sources/store.py`），默认仅内置 Gutenberg 公版源，`download.enabled` 默认 `false` | 见「网络与下载」页的真实引导 |
| 标签 `My requests` / `All requests` | 两个列表 | **无** | **不做** |
| 表单（Title / Author / Format / Fulfillment / Choose a release / Request language / More options） | 完整 | **无** | **不做** |
| 「Add to library（目标书库）」 | 选目标库 | **无**（多库已于第 10 期落地，但求书不做） | **不做** |
| 设置侧三段（Sources / Download clients / Automation） | 完整 | **无**（原占位页已删） | **不做** |

**替代路径**：本项目「从外部获取书」一律走「工具 → 书源管理」的数据驱动书源规则（检索 / 下载 / 入库）。
与上游的插件 / indexer 形态不同，但覆盖同一需求。

## 10. 域：收书目录

> **第 27 期复核（2026-09-19）**：本域**整域已落地**（第 25 期前后 B3 交付），原判「无独立页 / 无状态机 / 需新增后端能力」全部过期。
> **第 29 期复核（2026-09-20）**：⚠️ **上轮把「整页拖拽投递」改判为「未做」是错的** —— 本轮逐行复核发现
> 它**早已实现**，且覆盖范围是**整个窗口**而非小方块（见末行）。错误来源是**证据取错了地方**：
> 拿 `LocalConvertView.vue` 那个限 `.txt` 的小拖拽区去推断「整页拖拽未做」，而真正的实现在
> **另一个文件**里。这条教训值得记住 —— **「在那里没找到」不等于「不存在」**。
> 另修正三处路径/行号：页面在 `settings/pages/BookDockPage.vue`（**不是** `views/BookDockPage.vue`）、
> URL 是 `/settings/admin/book-dock`（**不是** `/book-dock`）、后端锚点整体偏移 1 行。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| `/book-dock` 页面 | 独立页 | **已有**（页面路径与 URL 均已更正）：`views/settings/pages/BookDockPage.vue`，注册 `router/index.ts:86`（`'admin/book-dock': BookDockPage`），由 `settingsChildren`（`:127-141`）从注册表生成、挂在 `:178-186` 的 `/settings` 下 ⇒ **URL 是 `/settings/admin/book-dock`**；导航登记 `data/settingsNav.ts:517`；接口 `GET /api/book-dock`（`server.py:3760`） | **已落地** | ⚠️ 两处更正：页面**不在** `views/BookDockPage.vue`；`router/index.ts:87` 今天是 `'admin/audit-log'`。另注：它**不是侧栏主导航项**（见 §1） |
| Pause / Rescan / Upload | 三个按钮 | **已有**：暂停/开始 `BookDockPage.vue:240-242` → `server.py:3791` `/api/watcher/stop`、`:3786` `/api/watcher/start`；重扫 `:348` → `server.py:3817`；忽略 `:349` → `server.py:3826`；页头「立即扫描」`:239` → `POST /api/scan`（`server.py:3798`）；Upload 走 `POST /convert`（`server.py:5261`） | **已落地** | 结论仍成立，**锚点已随第 33 期全文复核逐条重测更正**（原记「整体偏移 1 行」是低估：实测偏移 44–54 行）。⚠️ 原表**漏记第三个动作**：移出 `BookDockPage.vue:350` → `POST /api/book-dock/{item_id}/delete`（`server.py:3835`） |
| 状态标签（All / Needs review / Pending / Ready / Error） | 5 态状态机 | **已有状态机**：`book_dock_items` 表（`core/db.py:215`，含 `status` 字段 + `idx_dock_status` 索引 `:227`）；五态枚举 `DOCK_TABS = ("all","needs_review","pending","ready","error")`（`core/db.py:1546`），中文标签 `core/bookdock.py:34-35`，计数装配 `bookdock.py:140-149`，前端渲染 `BookDockPage.vue:312-323` | **已落地** | 结论与原有锚点均仍准确，本轮**补上原表未引的五态枚举锚点** |
| 空态 + **整页拖拽投递** | 全页 drop | **已落地（原判「未做」是错的）**：①脚本 —— `settings/pages/BookDockPage.vue:166-230`，用 **window 级**事件（`onMounted` 注册 `:211-215` 的 `dragenter`/`dragover`/`dragleave`/`drop`，`onBeforeUnmount` 移除 `:225-230`）；②视觉 —— 全屏遮罩 `:383-404`（`class="fixed inset-0 z-[60] …"`），drop 处理 `:394`，文案「松开投递到收书目录」`:398`；③**接受的扩展名不限于 .txt**：`POST /convert` 后端放行 `.txt ∪ pipeline.EBOOK_EXT`（`server.py:5212-5215`），`EBOOK_EXT` 含 epub/mobi/azw3/pdf/fb2/cbz/cbr **+ 音频扩展**（`core/pipeline.py:8`），空态文案亦如此声明（`BookDockPage.vue:361`「把 .txt / EPUB / PDF / CBZ 拖进本页任意位置」） | **已落地** | ⚠️ **本节上轮的改判作废**。`LocalConvertView.vue:158-171` 那个小拖拽区**确实仍限 .txt**，但**由它推不出**「整页拖拽未做」—— 两者是两个不同页面上的两个不同控件 |

## 11. 域：作者与系列

> **第 29 期复核（2026-09-20）**：本域此前**从来没有复核头**，5 行全是**第 4 期旧文**。
> 本轮逐行按代码改判，结果：**已过期 2 行**（196 索引/排序/筛选、198 传记+Actions）、
> **部分过期 1 行**（197 No portrait / No sort name）、**仍成立 2 行**（199 `/series/:id`、200 `/series` 总览，锚点已换）。
> ⚠️ 本域同样有**跨节自相矛盾**：§13「作者传记 / 作者头像（No portrait）」条早已标为**已过期**
> （第 8 期 D1/D2 实现），而本节第 198 行却仍写「无传记、无 Actions」——
> 代码证实 **§13 正确、本节作废**，且第 197 行的判据「依赖外部作者元数据服务」**随之一起作废**。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| `/authors` 索引 / 排序 / 筛选（2+ books / Added this week） | 完整 | **已落地**：后端 `authors_list` 聚合（`core/library.py:749-759`）+ `GET /api/authors`（`server.py:1874` 起，含 `count` / `series` / `covers` / `has_photo` / `added_ts` / **`sort_name`**）；前端 `views/AuthorsView.vue` 排序状态 `:18-20`、选项 `:31-34`（按书量 / 按姓名 / **按排序名**）、过滤+排序 `:40-47`、筛选 UI `:71-87`（含 **2+ 本 / 本周新增 / 无头像**）、「本周」口径 `:27-29` | **已落地** | 原判「仅纯 Grid」已过期。⚠️ 原引锚点 `AuthorsView.vue:37-61` 今天恰好落在筛选逻辑范围内 —— **锚点「蒙对」而结论错**，这是最容易被放过去的一类。**第 32 期新增**排序名与「无头像」两项（见下行） |
| `/authors` No portrait / No sort name | 依赖作者头像与排序名 | **已落地（第 32 期补完）**：**portrait** 第 8 期即有（`core/authors.py`，OpenLibrary 作者检索 + 传记/头像本地缓存，零外链，文件头 `:1-10`）；**「无头像」快捷筛选**第 32 期落地（`views/AuthorsView.vue` 的过滤项 + 按钮，复用既有 `has_photo` 字段）；**`sort name` 第 32 期落地**：`authors` 表加列（**在线值 / 本地覆盖分列**，同表既有模式）+ `GET /api/authors` 下发（`server.py:1895`）+ 详情页可编辑 / 恢复在线（`POST /api/authors/{name}/sort-name`，`server.py:1959`）+ 作者页排序项；测试 `tests/test_author_sort_name.py` | **已落地** | ⚠️ 原判「**不建议做**」的理由「依赖外部作者元数据服务」**早已作废**—— 抓取链路 `core/authors.py` 已在，走既有链路、不引入新依赖。原引 `core/library.py:474-475` 今天是 `_spine()`；`dc:creator` 在 `library.py:821` |
| `/authors/:id` 传记 + Actions | 完整 | **已落地**：后端 `GET` 详情返回 `bio` / `bio_overridden` / `has_photo` / `photo_overridden` / `photo_source` / **`sort_name` / `sort_name_overridden`**（`server.py:1904` 起），`POST /api/authors/{name}/bio`（`:1948`）、`POST .../sort-name`（`:1959`）、头像分发（`:1938`）、上传头像（`:1970`）、抓取单个（`:2068`）/ 全部（`:2077`），实现在 `core/authors.py`（本地覆盖 > 在线的 `effective()`）；前端 `views/AuthorDetailView.vue:183-275`（资料卡：头像 + 传记正文 `:220-225` + 「传记已本地修改」/「头像已本地修改」标记 `:206-218`），Actions：抓取在线资料 `:228-230`、编辑/保存/恢复在线传记 `:231-233,260-271`、上传头像 `:234`、恢复在线头像 `:235-243`、书单排序 `:277-286`；**「打开最近添加」也已在**（`:50-52`、`:159-161`、`:283-285`）。**第 32 期新增**排序名的编辑与「恢复在线」（同 bio 那套） | **已落地** | ⚠️ **本节此行为错误记载，已作废；以 §13 为准**（§13 早已标「已过期：第 8 期 D1/D2 已实现」）。原判「无传记、无 Actions」与其理由**一并作废**；锚点第 32 期整体后移 |
| `/series/:id` 排序 + 方向 / Group by media / FIRST IN SERIES / 每书 #序号 / SYNOPSIS | 完整 | **已完整**（第 12 期收口，**本轮逐项复核仍成立**）：排序+方向 `views/SeriesDetailView.vue:48-52`、`:63-66`、`:124-129`；Group by media `:74-82`（多组才显示组标题）、`:136-139`；FIRST IN SERIES `:57-61`（`firstId` 取最小 `series_index`）、`:165-171`（「首册」徽章）；每书 `#序号` `:152-158`（缺号提示 `:54-55`、`:114-116`）；SYNOPSIS 与系列级字段 `components/book/SeriesMetaPanel.vue`（展示 + 就地编辑 + 「恢复在线」`:77-85`、`:133`、`:144`、`:180-182`），挂载 `SeriesDetailView.vue:122`；重排册号 `components/book/SeriesRenumberDialog.vue`（挂载 `:193-198`）。后端 `server.py:1729`（详情）、`:1771`/`:1785`（meta 读写）、`:1808`/`:1817`（抓取）、`:1836`/`:1845`（重排预览/应用）+ `core/series_meta.py` | — | SYNOPSIS 的取值与作者侧**不同档**：外部源没有「系列」实体，只能靠「系列名检索 + 成员书一致性打分」，低置信度时如实显示「未找到」；**且只存服务端 DB、不写回 EPUB**（OPF 无该字段） |
| `/series` 总览 | — | **仍成立**：后端 `series_list` 聚合按册数降序（`core/library.py:731-741`）+ `GET /api/series`（`server.py:1714`）；前端路由 `/series`（`router/index.ts:166`）+ `views/SeriesView.vue:20-27`（取数）、`:40-71`（Grid 渲染），**已含简介摘要** `:63-69`（第 12 期 C3） | **已落地** | **结论仍成立、锚点已换** —— 原引 `core/library.py:386-396` 今天是 `_nav_entries` 内部（EPUB3 nav 解析，与系列无关）；档位第 32 期更正 |

## 12. 域：批注

> **重要更正（2026-09-19）**：历史实测把本域记为「线上为空态」——那只是**该实例当时没有批注数据**，**不等于上游没有能力**。源码（`packages/types/src/annotation.ts`）显示模型明显更深，故原档位理由「超出线上」**作废**，改为按能力项逐条判定。
>
> **第 27 期交付（2026-09-19）**：分组 / 软删除垃圾桶 / 周节拍统计 **三项已落地**；**多端来源、`needsReview`、`devices` 与跨端降色仍未做**，理由见下（无数据源，不建死列与死 UI）。
> **第 29 期复核（2026-09-20）**：本域**能力结论基本仍成立，但两处「理由/判据」是错的**，本轮更正：
> **①配色行**称「每色带 `koreaderFallback` + `koboFallback`」「`downmapTo` 写了也无调用方」——
> 全仓 grep 这三个标识符 **零命中**，它们**根本不存在**；**②分组维度行**引的
> `ANNOTATION_HUB_GROUP_MODES` **也不存在**，本项目真实常量是 `GROUP_MODES`（`views/AnnotationsView.vue:29-34`）。
> ⚠️ **根因**：「判据（源码）」这一列**长期混用上游类型名与本项目实现名**，两者长得像、又都带反引号，
> 复核时极易把上游名当成实现锚点。本轮起该列**一律用本项目实现名**，上游名如需保留须显式标注「（上游）」。
> 另：三行的后端锚点 `server.py:494-504` 今天指向的是 **OPDS 代码**，已全部换新。

| 能力项 | 线上形态（历史实测） | 本项目现状 | 档位 | 判据（源码） |
| --- | --- | --- | --- | --- |
| 批注来源 | 空态三张引导卡：Read here / Sync a Kobo / Sync KOReader | **结论仍成立**：仅 Web 内创建（`POST /api/books/{bid}/annotations` `server.py:1666-1683`，`:1666` `origin` 缺省 `'web'`）；**已建 `origin` 列**并回填 `'web'`（迁移块 `core/db.py:432-436`），写入函数 `db.add_annotation(..., origin="web")`（`db.py:569`），**只有 web 一个写入方**；前端如实标注只有一种来源（`views/AnnotationsView.vue:296-301`） | 多端来源 **需新增后端能力** —— **本轮不做** | `origin = "web" / "koreader" / "kobo"` —— 三卡即三来源枚举，无第四种。⚠️ kosync 已核实是**纯进度**（只有 `/koreader/syncs/progress` 的 PUT/GET，无批注端点），也没有 KOReader/Kobo 批注导入 → **无数据源**，故只建列不建导入链路，界面如实标注。**锚点已换**（原引 `server.py:494-504` 今天是 `_opds_base`/`_opds_xml`；第 32 期再校：`server.py` 整体 +54 行、`db.py` +99 行） |
| 配色 | 页面未渲染 | **已有应用侧 10 色**：单一权威表 `frontend/src/data/annotationColors.ts:27-38`（yellow/orange/red/pink/magenta/purple/blue/teal/green/gray，原 4 处各自为政的颜色表已全部归并，沿革见该文件 `:3-16`） | 应用侧 **已落地**／**跨端降色不做** | ⚠️ **本行原判据有两处不实，已删**：称「每色带 `koreaderFallback` + `koboFallback`」与「`downmapTo` 写了也无调用方」—— 全仓 grep 这三个标识符 **零命中，它们根本不存在**；`HighlightColor` 接口只有 `key`/`label`/`hex` 三字段（`annotationColors.ts:18-24`）。该文件反而**如实声明**其余 6 色色值「未经上游源码逐色取证（未验证）」（`:13-16`）—— 以该声明为准，不要补写不存在的降色字段 |
| 分组维度 | 页面未渲染 | **已落地**：月 / 书 / 颜色 / 来源四档，默认按书。**纯前端**分组（列表本就在手，重排即可），未加服务端 `group=` 参数 —— 该前缀下只有 `/api/annotations`（仅 `include_trashed`）与 `/api/annotations/overview`（`server.py:2085-2108`） | **已落地** | ⚠️ **原判据引的常量名不存在**，已改为本项目真名：`GROUP_MODES`（`views/AnnotationsView.vue:29-34`，取值 `month`/`book`/`color`/`source`），类型 `GroupMode` 在 `:27`，默认 `groupBy = ref<GroupMode>('book')` 在 `:28`；分桶与排序逻辑 `:85-124`，切换 UI `:282-296` |
| 待复核 / 垃圾桶 | 页面未渲染 | **仍成立**：`DELETE` 改**软删除**（写 `deleted_at`，`db.delete_annotation` `core/db.py:583-593`），新增 `restore`（`:596-608`）/ `purge`（`:613-623`，SQL 带 `deleted_at != 0` 条件、**活跃条目拒删**），垃圾桶查询 `:628-641`；路由软删 `server.py:1685`、restore `:1692`、purge `:1700`；前端活跃/垃圾桶切换 `AnnotationsView.vue:240-258`、恢复/彻底删除按钮 `:331-347`、移入垃圾桶 `:349-357`。**待复核（needsReview）不做** —— 没有设备回传就没有可对账对象 | 垃圾桶 **已落地**／待复核 **不做** | ⚠️ 判据列原引的 `AnnotationHubOverview.needsReview` 是**上游类型名**，本项目对应类型是 `AnnotationOverview`（`lib/api.ts:780-787`，**无该字段**）；后端 `server.py:2110-2120` 明写**刻意不返回** `needsReview`。删除是**软删除**；设备回传批注需**人工对账**。第 32 期再校锚点（原引 `db.py:569-580`/`:590`/`:607`/`:615-626`、`server.py:1675`/`:1682`/`:1690`） |
| 统计口径 | 页面未渲染 | **仍成立**：`GET /api/annotations/overview`（`server.py:2108`）→ `core/db.py:791-805` `annotation_overview()`，返回 `active` / `trashed` / `weeks` / `longest_quiet_weeks`；**按 ISO 周归桶**准确 —— `_week_index`（`db.py:780-788`）按 ISO 周周一 `monday.toordinal() // 7`，注释解释了为何不用 `year*53+week`；前端统计条消费 `AnnotationsView.vue:216-236`。**`devices` 不做**（恒 1，无意义） | **已落地** | 判据列的 `weeks`/`longestQuietWeeks`/`devices` 是**上游字段名**；本项目字段为 snake_case 的 `weeks`/`longest_quiet_weeks`，**且不含 `devices`**。第 32 期再校锚点（原引 `server.py:2081-2094`、`db.py:777-805`/`:800-805`/`:766-774`） |
| 跨书搜索 / 跳转章节 / 导出 Markdown | 无 | **仍成立**，三项全在 `views/AnnotationsView.vue`：跨书搜索（按 quote / note / book_title 过滤）`:60-75`；跳转章节 `:147-149`（`router.push('/read/<book_id>?chapter=<chapter>')`）；导出 Markdown `:178-209`，**只导活跃批注**由 `:180` `items.value.filter((a) => a.deleted_at === 0)` 落实 | **已落地** | 后端锚点已换：`GET /api/annotations`（`server.py:2085`）、overview（`:2108`）、单书批注 CRUD 含 restore/purge（`:1661-1706`）—— 原引 `server.py:494-504` 是 **OPDS 代码**。上游是否存在对应能力：**未验证（源码无法确认）**，本轮仍未取 `server/src/modules/annotation` 与 `client/` |

---

## 13. 明确不建议做（含依据）

| 项 | 依据 |
| --- | --- |
| **界面国际化（Language，25 语言）** | 界面中文硬编码（如 `data/nav.ts:32-49` 的导航分组标签），需全量抽文案 + i18n 基建；对单人内网工具收益远低于维护成本（锚点第 29 期更正：原引 `:36-43` 是旧行号，今天落在分组中段） |
| ~~**Metadata Freshness / 在线元数据抓取体系**~~ ⚠️ **该条已过期** | **第 5 期已实现抓取体系**：`core/metasources.py`（OpenLibrary / Google Books，均无需 Key）+ `core/metafetch.py`（plan→预览→apply，结果只落 `meta_online`/`meta_cover`、不改写文件）。原判据「本项目只有 EPUB 自身 + 文件名」与 §14 自相矛盾，已作废。**仅「Freshness 指标」本身不做**，理由见 §6 该行（价值低，非依赖冲突） |
| ~~**作者传记 / 作者头像（No portrait）**~~ ⚠️ **该条已过期** | **第 8 期 D1/D2 已实现**：`authors` 表分列「在线抓取值」与「用户本地覆盖」（`bio` / `bio_local`、`photo` / `photo_local_path`，`core/db.py:259-265`），接口 `POST /api/authors/{name}/bio`（`server.py:1948`）+ 作者详情返回 `bio`/`bio_overridden`（`server.py:1915-1916`），前端 `views/AuthorDetailView.vue` 可编辑并显示「已覆盖」标记。原判据「依赖外部作者元数据服务」不再成立 —— 走的是既有抓取链路 + 本地覆盖，不引入新依赖。**第 32 期补**：`sort_name` 同走这一套（`POST /api/authors/{name}/sort-name`，`server.py:1959`），锚点整体后移 |
| ~~**有声书阅读器**~~ ⚠️ **该条已过期** | 第 9 期已实现（`core/audio.py` + `/api/books/{bid}/audio` + 播放器 + `reader/audio` 设置页）；原判据「`BOOK_EXTS` 不含音频」不再成立 |
| **Requests 的 Sources / Download clients / Automation 具体功能**（索引器 + 下载客户端） | 与既有「数据驱动书源」体系（`sources/rules.py`、`sources/store.py`）功能重叠。**2026-09-18 起为「已决策不做」**：骨架页与只读接口也已从代码中删除（不再是「按 §9 保留」） |
| ~~**Pages（页数）字段**~~ ⚠️ **该条已过期** | 已实现：EPUB 为估算值（`library._pages_in`）、CBZ 为归档真实页数；第 7 期已计入元数据完整度评分 |
| ~~**多书库（`/libraries`、`/library/:id`、按书库筛选 / 批量重命名 / 查重）**~~ ⚠️ **该条已过期** | **第 10 期已实现**（`libraries` 表 + 库感知路径解析 + 按格式迁移 + 能力显隐矩阵）；原判据「唯一 `OUTPUT_DIR`、无书库实体」不再成立。**注（第 29 期）**：本条枚举里的「批量重命名」作为**独立工具页**已于**第 28 期删除** —— 按用户决定改名**并入刮削面板**（`core/scrape.py` 的 `plan_naming` / `republish`），前端 `BulkRenameView.vue` 与 `/api/rename/*` 已不存在；查重页 `DuplicateBooksView.vue` 保留 |
| **Hardcover / Readwise / StoryGraph 同步** | **2026-09-19 用户拍板：本轮明确不做**。源码显示这三项的上游形态并不轻：Hardcover 是**双向**（含导入书单/进度：`HardcoverImportPreviewOutcome` 五态、版本关联 `HardcoverEdition`、匹配方式 `hardcover_id / isbn / title_author`）；StoryGraph **没有公开 API**，凭据只能复用浏览器 `sessionCookie` + `rememberToken`；Readwise 虽最小（`ReadwiseSettings` + `disabledReason`）但与项目定位无关。三项均需**凭据加密存储 + 书籍匹配（ISBN/标题+作者）+ 同步任务调度**，维护成本远超收益 |
| **KOReader / Kobo 设备侧集成** | Kobo 同步已于 2026-09-17 决定不做；KOReader 侧源码显示并非「一处同步」而是**四套并列通道**（进度单一权威源 `canonicalSource`、`heldByReset` 设备分歧、插件目录 9 段 + 批量清单下载、能力协商 `KoreaderPluginCapability`），且插件有独立供应链（`manifestUrl` + `ed25519PublicKey` 签名校验）。复刻设备侧协议成本与收益不匹配，本轮不进入路线图 |
| **上游 Requests 的插件式索引器 / 下载客户端** | 见上一条 Requests 行；另据源码（`packages/types/src/indexer.ts`）其插件体系含签名更新通道与 SSRF 防护（`INDEXER_URL_UNSAFE` / `INDEXER_URL_PRIVATE`）、凭据加密（`BOOK_REQUEST_ENCRYPTION_KEY`），是**完整的插件市场形态**，与本项目「数据驱动书源规则」定位不同 |
| **全部多用户能力** | 单用户轻登录（`core/auth.py:1-5`）；`users` 表无角色字段 |

---

## 14. 分阶段路线图

> 每项格式：**能力 → 后端要补什么 → 前端要做什么**
>
> **⏳ 时效标注（第 29 期，2026-09-20）**：本节的期号**止于第 5 期**，是**历史排期记录**——
> 第 0–5 期**均已交付**（第 5 期于 2026-09-17 完成），本节此后未再随项目推进更新。
> **第 6 期起的实施记录不在本文件**，见 `docs/roadmap-gaps-remaining.md`（活文档，逐期追加实施记录）。
> 因此：本节里的「要补什么」**一律是过去时，不是待办**；判断某能力今天做没做，
> **看 §1–§12 的现状列（第 29 期已逐行核验到底），不要看本节**。
> ⚠️ 本节还残留几处**已被后来决策推翻**的写法，各条已就地标注（如第 1 期的 Requests、
> 第 2 期的 `reviews` 新表与「复用 `_patch_opf` 写 OPF」方向）—— 它们**当时**是对的，
> 后来的实现换了路子，不表示原计划有误，但**照着做会做错**。

### 第 0 期（本批立即开工）

- **审计日志** ✅ **已完成**：`core/activity_log.py` 写入函数加 `actor`（`ContextVar` + `set_actor`，`activity_log.py:62-75`；无请求上下文的后台任务写「系统」）→ `server.py` 各写入点透传 → 前端真审计表。**第 32 期补上最后一块**：`recent(actor=...)` 过滤（`activity_log.py:252`、`:280-282`）+ `actors()` 取值清单（`:286`）+ `GET /api/logs` 增**可选** `actor` 参数（`server.py:3855`，不传参输出与改动前一致）+ `AuditLogPage.vue` 操作者筛选控件（该页原注释如实写着「日志接口尚未支持按 actor 过滤」，本期把它变成真的）。测试 `tests/test_logs_actor.py`
- **收书目录**：复用 `INPUT_DIR` + watcher 现有接口 → 前端呈现投递目录、监听联动、自动处理开关；元数据自动抓取与置信度定稿标注未支持（依赖第 2 期）

### 第 1 期：自动化与运维

- **通知已读态**：新表 `notifications_read` + `POST /api/notifications/read` → 通知中心加已读标记与「全部已读」；顶栏加浮层入口
- **任务持久化**：用 `tasks` 表替掉进程内 `TASKS` dict（`server.py:95`）→ 任务中心改真表；**同时移除 `data/tasks.ts` 的 6 条演示种子与 ticker 假推进** ✅ **已完成**（见 §8 复核头：种子与假 ticker 均已清除）
- **维护与清理**：新增 orphaned 封面目录扫描 + 清理接口（复用 `fileops.recycle_items`）→ `Maintenance` 页真实现
- **上传大小上限** ✅ **已实现**：配置项 `upload.max_bytes`（默认 50 MB）与 `upload.max_source_rules_bytes`（默认 5 MB）在 `novelforge/config.py:106-114`；读取走 `_upload_limit()`（`server.py:312-325`，值非法或 ≤0 **回退内置默认而非放行** —— 避免「配置写坏 = 变回无限制」这种静默降级），用法 `_read_capped(file, _upload_limit(...))`（`server.py:328`、`:5271`），超限返回 **413**。**「页面可改」也已落实**（当时的计划正是如此）：两项在 `server.py:3281` 的 `EDITABLE` 白名单内、`/api/maintenance` 回传该块（`:3549-3552`）、前端定义在 `frontend/src/data/settingsFields.ts:72-86` 的 `UPLOAD_FIELDS`（注释「维护 → 上传上限」，对应上游 Maintenance 页的 UPLOADS 分组） ⇒ 与 `docs/roadmap-verification.md:24` 的「配置 + 接口回传 + 页面可改」一致。**〔第 32 期更正〕** 本条曾一度被写成「本项目**没有**把它做成维护页上的可编辑项」，系只看了 `settings.json` 而**未核 `EDITABLE` 白名单**所致，已回改 —— 教训：判断「有没有页面入口」要顺着「白名单 + 前端字段定义」两头查，不能只看配置文件
- ~~**Requests 页面与接口**（§9）~~：**已于 2026-09-18 撤销**（第 1 期曾交付只读骨架页 + `GET /api/requests/config`，现两者均已从代码删除）
- **成就体系**（单用户口径）：新表 `achievements` + `user_achievements` + `core/achievements.py` → `/achievements` 页

### 第 2 期：书库与元数据

- **真实封面**：后端无需新接口（`/api/books/{bid}/asset` 已能代理 zip 内资源）→ 前端先接真实封面，再做封面显示模式 / 书脊 / 阴影 / 卡片叠加层
- **书架三视图 + 搜索 + 排序 + Collapse series + 多选 + Filters**：后端无需改（多选批量写需批量接口）→ 前端 `ShelfView.vue` 重做 —— ✅ **已完成**；⚠️ 括注「多选批量写需批量接口」当时的判断偏保守：`POST /api/books/batch` **已建**（`server.py:1038-1088`）
- **书卡信息补全 + 系列序号**：后端扩 `_series_of` 解析 OPF `calibre:series_index` → 书卡与系列页展示 `#序号` —— ✅ **已完成**；⚠️ 实际落点是 `_series_index_of`（`core/library.py:71-90`，另加 EPUB3 `group-position` 兜底），函数名与当时的计划不同
- **单书 Edit Metadata**：复用 `fileops._patch_opf`，加 `POST /api/books/{bid}/metadata` → 详情页新增「编辑元数据」标签 —— ✅ **已完成，但方向改了**：⚠️ **没有**复用 `_patch_opf` 写 OPF，实现是**只写服务端覆盖、不碰任何文件**（`server.py:1190-1196,1226-1233`）。**按原计划做会做错** —— 它会写回 OPF，与「元数据仅存服务端」的既定原则冲突
- **阅读状态 + 起止日期 + 书评 + 相似书 + Reading Log（按书）+ 手工补录**：`progress` 扩字段 / 新表 `reviews` / 新模块 `core/recommend.py` / 加 `GET /api/books/{bid}/reading-log` → 详情页五标签逐步补齐 —— ✅ **已完成**；⚠️ 两处与计划不同：**没有新建 `reviews` 表**（复用既有 `ratings` 表加列，`db.set_review` `db.py:1275`）；**没有建 `GET /api/books/{bid}/reading-log`**（实现为 `GET /api/reading-log` 返回 `items`/`by_book`/`recent` 三块，`server.py:1544-1593`）。相似书模块 `core/recommend.py` **按计划建了**
- **统计增强**：时间粒度参数化、Publishers/Genres/年份范围/Avg Progress/Top50、Library Integrity（很轻）→ `StatsView.vue` 分区改版
- **导出元数据**：`library.export_rows()` + `/api/books/export` → 书架导出按钮 —— ✅ **已完成**，**按计划落地**（`core/library.py:1197-1221`、`server.py:978-1018`，17 列）
- **自定义智能书架**：`smart_scopes` 表 + CRUD → `/smart-scopes` 页 —— ✅ **已完成**，**按计划落地**（`server.py:2939/2951/2963/2977`）
- **查重阈值与模糊匹配**：改 `duplicate_groups()` 引入相似度 → 查重页加阈值滑块 —— ✅ **已完成**；⚠️ 交互与计划不同：**不是滑块**，是 **70/85/95 三个预设按钮**（`views/tools/DuplicateBooksView.vue:35`（`THRESHOLD_PRESETS = [70, 85, 95]`）、`:177-191`）

### 第 3 期：阅读器体验

> **第 29 期注**：本期五项**均已交付**（详见 §4 及其「补记」）。下方保留当时的计划措辞。

- **eBook 排版增强**（纯前端）：翻页/滚动模式、13 档深色主题、段落间距、两端对齐、断词、字距/词距/首行缩进、分栏 —— ✅ **已完成**（`lib/readerPrefs.ts:79-93` 13 档主题、`:29-43` 各项、`:70-73` 翻页模式）
- **PDF 阅读器**：后端加文件流接口 → 前端 pdf.js 阅读器 + 对应设置 —— ✅ **已完成**（`GET /api/books/{bid}/file` `server.py:1362-1377` + `components/reader/PdfReader.vue`）
- **漫画阅读器**：后端加 CBZ/CBR 解包与图片序列接口 → 前端漫画阅读器 + 对应设置 —— ✅ **已完成**（`core/comics.py` + `components/reader/ComicReader.vue`）
- **字体管理**：后端新增字体上传/列表/分发接口（当时**后端零字体能力**）→ 阅读器字体页 + 服务端字体页 —— ✅ **已完成**（`core/fonts.py` + `/api/fonts` 4 条路由）
- **偏好同步**（单用户「账号级」= 存服务端多端一致）：偏好表 + 接口 → 外观与阅读偏好支持「本机 / 账号」 —— ✅ **已完成**（`/api/prefs/profiles` + `/api/prefs/devices` 共 9 条路由，前端 `stores/prefSync.ts` + `lib/prefsBridge.ts` 防回环）

### 第 4 期：多端同步与设备

- **OPDS 订阅源**：只读 Atom/XML feed + 客户端账号 → `OPDS` 页 —— **已完成**（`core/opds.py`，`/opds` 独立前缀 + Basic 认证，开关 `opds.enabled` 默认关闭）
- **Komga 集成**：见下方说明（方向待确认）→ `Komga` 页
- ~~**外部服务集成**：Hardcover / Readwise / StoryGraph 凭据存储 + 同步任务 → 三页~~ ⚠️ **本轮明确不做（2026-09-19 用户拍板）**：与项目定位无关，且上游形态并不轻（Hardcover 双向含导入、StoryGraph 无公开 API 只能复用浏览器会话 Cookie、三项均需凭据加密 + 书籍匹配 + 同步调度）。原「三页」不建骨架、不留占位入口，据此 §13 已列依据。**相关设置页与文案维持现状，继续如实标注未支持。**
- **KOReader 设备侧集成**（原「KOReader 进度互通」）：**本轮不进入路线图（优先级最低）**——源码显示上游是四套并列通道 + 独立插件签名供应链（见 §13），复刻成本与收益不匹配
- ~~**Kobo 同步**~~：**不做**（2026-09-17 用户决定，KEPUB 派生 + 私有同步协议成本与收益不匹配）
- ~~**邮件投递**~~：**不做**（2026-09-17 用户决定）

#### Komga 集成的两个候选方向（技术上互不重叠）

Komga 是漫画/电子书服务器：扫描**库根目录**，目录结构约定为「一层系列目录 + 书文件」
（**不递归 Series 文件夹的子目录**），卷号从文件名解析（如 `系列 #1.cbz`）。

- **A. 输出侧兼容**（NovelForge → Komga）：新增输出布局选项，按系列建目录并输出 Komga 可解析的卷号命名。
  本项目当前输出是**平铺**的（`config.OUTPUT_DIR / name`），喂给 Komga 会散成一堆单本「系列」。
  成本小、见效直接。
- **B. 接入侧集成**（Komga → NovelForge）：配置 Komga 地址 + API Key，浏览其库/系列/书、下载入库、同步阅读进度。
  成本大（需 Komga REST 客户端 + 凭据存储 + 下载任务）。

### 第 5 期：元数据抓取与 Komga 兼容服务端（2026-09-17 完成）

两条线并行，均已落地并验证：

- **元数据自动抓取与治理** ✅：`core/metasources.py`（OpenLibrary / Google Books，均无需 Key）+
  `core/metafetch.py`（plan / apply / 入库自动抓）+ `fileops` 的封面写入（zip + OPF 三处声明）。
  落地「书库」组 7 个设置页：Providers / Books / Authors / Field Rules / Confidence Score /
  Genre Blocklist / Custom Fields，并提供「先预览、再应用」的手动抓取面板。
  - 实测：OpenLibrary 可用；Google Books 匿名请求常撞 429（已支持填 Key）
  - 默认 `fill_only` 策略（只补空字段）；封面复用 `library._COVER_MIN_BYTES` 阈值拦掉小图
- **Komga v1 兼容服务端** ✅（用户选定形态 A：本应用**冒充** Komga，客户端零改动）：
  `core/komga_api.py`（DTO / Spring Data 分页壳 / Basic + X-API-Key + 会话三种认证 / 进度双向映射）+
  `core/pdfrender.py`（PDF 逐页渲染 + 磁盘缓存）+ 21 条 `/api/v1/*` 路由。
  - 第三方 Komga 客户端（Mihon / Panels / 官方 App）把地址填成本应用即可浏览书库、读漫画与 PDF、
    下载 EPUB、双向同步阅读进度；已弃用的 `GET /series`、`GET /books` 也保留（老客户端在用）
  - **中间件必须放行 `/api/v1/`**：客户端路径写死、发 Basic 而非 Bearer
- 顺带修两处旧缺口：**全局搜索**原先只弹提示（现跳书架并预填，真实过滤）；
  **watcher 的复制路径**不走 `output.layout`（现跟上）

### 后期（未定期）

- ~~**Requests 具体功能**（§9）~~：**已决策不做（2026-09-18）**。插件式索引器 + 插件市场、Torznab/Newznab、下载客户端与凭据加密（上游需 `BOOK_REQUEST_ENCRYPTION_KEY`）、下载后自动化 —— 本项目改用**数据驱动书源规则**覆盖同一需求

---

## 15. 执行约定

1. **不做假交互**：任何页面上的控件都必须真实生效；缺后端就先把后端做出来（§0.2）。⚠️ 原例证「骨架页（Requests）的配置项可见但标注功能待实现」**已失效** —— 该页随 C1 于 2026-09-18 删除，现全仓不再有「看得见但点不动」的控件。**第 32 期的两条正例**：①侧栏「库」组的 add / more 两个按钮曾落到 `ui.demo()`（弹「演示动作：…」，与上句的自我声明直接冲突），已改接真实路由；②外观 Layout / Behavior 两页做实（每项都真的驱动书架 / 作者页，改完立即生效），而 **Icons 页做不到就如实标注「不做」** —— 用户勾的是「外观三页」，本轮**主动收窄为两页**并写明原因，不假装做了第三页。**反面警示**：`BookDockPage.vue` 的「未支持」卡曾把**已实现**的「投递后自动抓元数据」列为未支持（第 32 期订正）—— 文案过期与假交互同样伤信任
2. **新增可配置项必须同时改两处**：`server.py` 的 `EDITABLE`（控制**可写**）与 `GET /api/config` 里的**硬编码键列表**（控制**可读**）是分开的——上一轮新增 `naming` 时踩过「能写进 settings.json 但读不回来」的坑，已在该处留注释。
3. **清除既有演示数据**：`frontend/src/data/tasks.ts` 原有的 6 条种子任务（当时在 `:21-28`；**该区间已随种子一并删除，第 33 期复核时文件只剩 14 行、仅存类型**）与 `stores/tasks.ts` 的假推进 ticker 属**伪造进度**，在第 1 期任务持久化时一并移除，不得保留。✅ **已完成（2026-09-20 复核）**：种子与假 ticker **均已删除** —— 见 §8 复核头；`data/tasks.ts` 现只剩类型。本节原写作「待移除」，与 §8 冲突，以本条为准。
4. **脱敏**：文档与截图不含账号 / 邮箱 / 令牌 / 密钥真实值；含账号显示名的截图不归档（本批已排除仪表盘截图）。
5. **验证纪律**：全量类型检查（**按输出文本判定**，`vue-tsc --build` 报错也返回退出码 0）→ 构建 → 部署 `novelforge/static/v2` → 重启测试实例 → 端到端脚本验证「保存 → 读回 → 实际生效」→ 浏览器逐路由冒烟；改后端写入路径时额外验证**历史条目兼容**。
6. **采集复现**：截图必须是**整页**——本应用用内层滚动容器，`fullPage` 对它是无效的。可靠做法是**把视口高度撑到内容高度**（实测：11 页从 720 补到 1006），而不是解除容器 overflow。
7. **档位可变**：若未来引入多物理目录或多账号，标为「需架构变更」的项可重新评估。
8. **前端图表零外部请求**（第 32 期立）：统计页图表一律**本地打包** —— `echarts` + `vue-echarts` 走 npm 依赖、**按需注册**图型（只 `use()` 用到的）+ **动态 import**；**不得引用 CDN、不得运行时拉取地图 / 主题 / 字体**。主题跟随本站深色 / 浅色，`frontend/src/lib/charts.ts` 是**全站唯一**的注册与主题适配入口（**不要在组件里各自 `use()`**，那会重复注册且主题不同步）。验证方式：打开统计页，devtools 网络面板除本地资源外**零请求**；断网后图表照常渲染
