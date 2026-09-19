# BookOrbit 全站能力缺口与添加方案

> 来源（历史实测）：`https://orbit.735876214.xyz:16666/`（线上实例，站点版本 **v2.10.0**）；采集日期 2026-09-16 ｜ 账号角色：Superuser（单账号本地部署）
> **源码对照（本轮新增）**：上游参考仓库 `https://github.com/735876214/bookorbit`，分支 `main` @ commit `c292d6cc`（v2.10.0）。只读镜像，不在本项目中复制上游代码，仅引用文件路径与结论。
> 用途：本文件是 novel_dl_convert **补齐线上能力**的排期依据，与 `docs/bookorbit-settings-inventory.md`（设置页 41 页清单）、`docs/bookorbit-library-contract.md`（类型契约）、`docs/bookorbit-feature-flows.md`（功能与流程）并列。
> 采集方式：浏览器自动化（Playwright CLI）**真实登录后逐页渲染采集**非设置页十个能力域；全程只读——仅导航、展开、点击进入子页、读取 DOM、截图；**未点击任何保存 / 删除 / 提交 / 启用 / 重置类控件**。
> 证据：逐页采集记录见 `docs/review/bookorbit-app-capture.md`；截图见 `docs/review/bookorbit-app-shots/`
> **脱敏**：全文不含账号、密码、邮箱、令牌、密钥真实值；此类字段一律只记「已设置 / 未设置」；含账号显示名的仪表盘截图主动未归档。
> **准确性约定**：①未取得可信值的项标注「未能采集」并说明原因；②本轮新增结论一律标注来源文件（`源码（<路径>）`），与历史实测（`历史实测（2026-09-16）`）分列，不混写；③凡源码无法确认的一律标注「**未验证（源码无法确认）**」，不做推测补全；④**「实例页面为空」不等于「上游无此能力」**——能力判断以源码为准，页面为空只在对应条目里说明 UI 侧未渲染。
> **本轮范围**：纯文档复核（零代码改动、零实例访问）；Hardcover / Readwise / StoryGraph 同步按用户拍板**本轮明确不做**（见 §13、§14）。

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

- 后端 `novelforge/server.py` 共 **260 个路由**（`grep -cE "^@app\.(get|post|put|delete|patch)\("`）；前端路由见 `frontend/src/router/index.ts`
- **唯一物理目录** `OUTPUT_DIR`（`novelforge/config.py:20`）；`novelforge/core/library.py:1-3` 明写「后端没有『图书库』实体」
- 单用户轻登录（`novelforge/core/auth.py:1-5` 明写不做多租户/角色；`users` 表无角色字段）
- SQLite 表 **28 张**（`novelforge/core/db.py`）：`users` / `progress` / `annotations` / `collections` / `collection_items` / `reading_sessions` / `reading_status` / `ratings` / `achievements` / `user_achievements` / `authors` / `series_meta` / `tasks` / `libraries` / `library_migrations` / `scrape_items` / `smart_scopes` / `opds_sources` / `pref_devices` / `pref_profiles` / `book_dock_items` / `notifications_read` / `koreader_docs` / `app_state` / `meta_cover` / `meta_online` / `meta_override`
- **元数据解析**来源是 EPUB 自身 + 文件名（`novelforge/core/metadata.py:11-33`）；**在线元数据抓取体系已于第 5 期落地**（`core/metasources.py` OpenLibrary / Google Books，均无需 API Key；`core/metafetch.py` plan→预览→apply，结果只落 `meta_online` / `meta_cover`、不改写文件）。
  ⚠️ 本节原写「**没有任何在线元数据抓取**」，与 §14 第 5 期「元数据自动抓取与治理 ✅」自相矛盾，以代码为准更正。

---

## 1. 域：应用外壳

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 侧栏主导航 | Dashboard / Book Dock / Requests / Tools | 部分：仪表盘/探索发现/任务中心/工具/数据统计/通知中心（`data/nav.ts:32-45`）；**无 Book Dock、无 Requests** | Book Dock **可直接落地**／Requests **已决策不做**（§9） | Book Dock 可复用 `INPUT_DIR` + watcher |
| BROWSE 组（Authors / Series / Annotations） | 三个入口 | **已有**（`router/index.ts:96-100`） | 可直接落地 | — |
| LIBRARIES 组（`/library/:id`、`/libraries`、New Library） | 多书库实体 + 分组菜单 | **第 10 期已实现多库实体**：侧栏「库」组列**真实书库**（`GET /api/libraries` 返回库实体，含类型 / 归属模式 / 书数），点击**切库 + 进书架**；原先的「格式 / 待修复 / 无封面」分面已改址 `GET /api/library-facets` 且不再占侧栏 | ~~需架构变更 → 不落地~~ **已落地** | 仍无 `/library/:id` 独立路由（用「当前库」状态替代），但 `OUTPUT_DIR` 假设已被推翻 |
| SMART SCOPES | `/smart-scopes` + New Smart Scope | 部分：固定 5 个智能书架（`data/collections.ts:22-28`），无独立路由、**无自定义** | 固定档 **可直接落地**／自定义 **需新增后端能力** | 自定义需 `smart_scopes` 表 + CRUD |
| COLLECTIONS | `/collections` + New Collection | **已有**（`router/index.ts:101-102`；后端 `server.py:516-568`） | 可直接落地 | — |
| 全局搜索（⌘K） | 跨库检索 | 部分：**UI 齐全但未接后端**——回车只弹提示（`components/AppHeader.vue:17-26`） | **可直接落地** | `/api/books` 已有，加一个查询接口即可 |
| Notifications 浮层（Mark all read / Clear） | 顶栏浮层 + 流水 + 已读 | 部分：仅整页 `/notify`（日志视图），**无浮层、无已读态**（`views/NotificationsView.vue`） | 浮层 **可直接落地**／已读 **需新增后端能力** | 已读需新表 `notifications_read` |
| Statistics | `/statistics` | **已有**（`/stats`，`router/index.ts:103`） | 可直接落地 | — |
| Achievements | `/achievements` | **已有（第 22 期实现）** | **已落地** | 新表 `achievements` + `user_achievements` + 派生规则（单用户内可行，不涉多用户）；维护页已接入 Backfill 按钮 |
| Upload books | 上传（支持多格式） | 部分：拖拽上传**限 .txt**（`tools/LocalConvertView.vue:165`；后端硬校验 `server.py:1072-1073`） | **可直接落地** | 放开多格式需在 `core/pipeline.py` 加分派 |
| Help（Documentation / What's New / About） | 三项 | 部分：About 已有；**Documentation / What's New 无** | **可直接落地** | What's New 静态 JSON 即可 |
| Appearance 浮层 | 顶栏浮层 | 部分：主题循环按钮 + 设置页主题页，**无浮层** | **可直接落地** | 偏好已存 localStorage |
| Language 浮层（25 语言） | 全站 i18n | **无**（界面中文硬编码） | **不建议做** | 见 §11 |
| 用户菜单（Account / Change Password / Sign out） | 浮层 | 部分：改密码已有；**无 Account 页、无 Sign out、无浮层**（顶栏头像为静态 div） | **可直接落地** | token 在 `localStorage.nf_token` |
| 版本标识 / What's New | `/whats-new`（v2.10.0） | **无**（后端 `FastAPI(version="0.5.0")`，前端未展示） | **可直接落地** | — |

## 2. 域：书架与智能书架

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 书架搜索 | 搜索框 | **无**（`ShelfView.vue` 无搜索） | **可直接落地** | 前端过滤即可 |
| 排序 | Title ↑ 等多键 | **无**（`stores/library.ts:94-99` `shelfBooks` 无排序） | **可直接落地** | — |
| Collapse series | 折叠同系列 | **无** | **可直接落地** | `books` 已带 `series` 字段 |
| Export metadata | 导出书目元数据 | **无**（`tools/OutputView.vue` 只下载文件本体） | **需新增后端能力**（很轻） | 由 `library.books()` 生成 CSV/JSON |
| Filters 面板 | 统一筛选面板 | 部分：标签 chips + 库分面 + 智能书架，**无统一面板** | **可直接落地** | — |
| Show library controls | 库级控制 | **无** | **可直接落地** | — |
| SELECT（多选模式） | 多选 + 批量动作 | **无**（全仓书架无多选；`checkbox` 仅出现在转换/改名/查重页） | UI **可直接落地**／批量写 **需新增后端能力** | 批量写需批量接口 |
| **Grid / List / Table 三视图** | 三视图切换 | **仅 Grid**（`ShelfView.vue:74-77`） | **可直接落地** | 纯前端 |
| Display 面板（书架级） | 书卡信息/密度 | 部分：仅仪表盘有部件面板 | **可直接落地** | 复用 localStorage 模式 |
| 书卡信息（格式徽章/系列 #序号/出版日期·语言/题材） | 5 类信息 | 部分：只显示 title/author/进度；数据侧 `format/year/language/tags/series` 后端**已有**（`core/library.py:552-562`），**系列序号字段不存在** | 展示 **可直接落地**／系列序号 **需新增后端能力**（很轻） | 序号需解析 OPF `calibre:series_index`（现仅解析系列名，`core/library.py:63-75`） |
| `/libraries` 列表页、`/library/:id` | 多书库 | **第 10 期已落地**：`GET /api/libraries` 返回**库实体**、侧栏「库」组点击即**切库 + 进书架**（无 `/library/:id` 独立路由，用「当前库」状态替代） | ~~需架构变更 → 不落地~~ **已落地** | 同 §1 |

## 3. 域：书籍详情

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 五标签（Details / Edit Metadata / Files / Reading Log / Highlights） | 5 个标签 | 部分：四标签（概览/目录/文件/批注，`BookDetailView.vue:30-35`） | — | 见下逐条 |
| Edit Metadata | 单书元数据编辑 | **无**（仅实体改名/合并会写 OPF，`core/fileops.py:193-254`） | **需新增后端能力** | 复用 `_patch_opf`，加 `POST /api/books/{bid}/metadata` |
| 阅读状态 + Date Started / Finished | 显式状态字段 | 部分：状态由进度**推导**（`core/stats.py:46-51`，阈值 99.5%），**无起止日期** | **需新增后端能力** | `progress` 表加 `status/started_at/finished_at` |
| YOUR REVIEW（书评 + 评分） | 可写书评 | **无** | **需新增后端能力** | 新表 `reviews(book_id, rating, body, ...)` |
| DETAILS 字段 | Publisher / Published / Language / Pages / ISBN / File Size / Library / Added | 部分：`BookDetailView.vue:309-316` 有系列/出版年/出版社/语言/ISBN；**Pages 无来源**（EPUB 无页数概念）；**Library 需多库** | 大部分 **可直接落地**／Pages **不建议做**／Library **需架构变更** | — |
| EDITIONS（按格式列文件与大小） | 版本编号 + 格式 + 大小 | 部分：按同 stem 聚合（`core/library.py:604-617`），**无版本编号** | **可直接落地** | — |
| Files on disk | 磁盘文件 | 部分：同 stem 文件列表，不展示绝对路径 | **可直接落地** | — |
| Similar Books | 相似书推荐 | **无** | **需新增后端能力** | 新模块 `core/recommend.py`（作者/系列/题材/标题相似度） |
| Reading Log（Total time / Sessions / Average / Active days / Pace / Last read） | 按书聚合 | 部分：**全局**口径已有（`core/stats.py:70-73,108-118`），**按书无**；表与写入路径已在（`core/db.py:85-93`、`server.py:573-585`） | **需新增后端能力**（数据已有，仅缺接口） | 加 `GET /api/books/{bid}/reading-log` |
| Add a session by hand | 手工补录 | **无** | **需新增后端能力**（很轻） | 复用 `db.add_session`（`core/db.py:285-296`） |

## 4. 域：阅读器

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| ePub 阅读器 | 完整 | **已有**（`/read/:id`、`views/ReaderView.vue`、`server.py:374-385`） | 可直接落地 | 注：**线上该页未采集到独立路由**，入口在详情页内 |
| PDF 阅读器 | 完整 | **无**：后端硬拒绝（`server.py:380-381` `仅 EPUB 支持在线阅读`）；详情页 `canRead` 仅 EPUB | **需新增后端能力** | 需文件流接口（`asset` 只支持 zip 内路径）+ 前端 pdf.js |
| 漫画阅读器（CBZ/CBR） | 完整 | **无** | **需新增后端能力** | 需解包 + 图片序列接口 |
| 有声书播放器 | 完整 | **无**（`BOOK_EXTS` 不含音频，`core/library.py:31`） | **不建议做** | 见 §11 |
| 阅读偏好（主题/字体/字号/行高/宽度） | 完整 | **已有**（`lib/readerPrefs.ts`、`ReaderView.vue:53-70`） | 可直接落地 | — |
| 深色主题 13 档 / 翻页模式 / 段落间距 / 断词 / 字距等 | 完整（设置页已采） | **无**（仅 3 档阅读主题） | **可直接落地** | 纯前端 |

## 5. 域：工具

> **第 28 期复核（2026-09-20）**：Bulk Rename 那一行按代码改判 —— 原「有页面 `/tools/rename`」的
> 现状已不成立（页面与 `/api/rename/*` 一并删除），改名并入刮削面板；其余各行为第 27 期复核结论。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| Entity Manager | 实体管理 | **已有**（`/tools/entities`、`server.py:947-997`） | 可直接落地 | — |
| Bulk Rename | **需先选书库** | **口径不同的自有实现**：第 28 期删掉 `/tools/rename` 页与 `/api/rename/*`，并入刮削面板的「命名规则」区块（规则 + 预览 + 一键重出版，`core/scrape.py` 的 `plan_naming` / `republish`）；**scope 仍是扩展名而非书库**（`naming.scope`），且只改**副本名**、源文件名无任何入口可改 | 现状 **可直接落地**／按书库 **需架构变更** | 「选书库」依赖多库实体；「只改副本名」是**刻意**与上游分流（上游改的是 `book.files[].filename`，与本项目「源文件只读」硬约束冲突，见 §1 的 `fileRenameEnabled`） |
| Duplicate Books | Library scope 多选 + **Similar-title threshold 85%** + Run scan | 部分：有页面与接口（`/api/duplicates`）；**无 scope、无可调阈值**；匹配为「归一化书名+作者」**精确**分组（`core/library.py:642-666`） | 精确匹配 **可直接落地**／阈值 **需新增后端能力**／library scope **需架构变更** | 阈值需引入相似度算法 |
| Missing Resources | Cover check + Run check + Missing books / Broken covers / **Orphaned cover folders** | 部分：有页面与接口，三类 issue = `zero-bytes`/`unparsable`/`no-cover`；**无 orphaned 目录、无 clean 动作、无 sweep** | **需新增后端能力** | 可复用 `fileops.recycle_items`（`core/fileops.py:309-339`） |
| 工具页签数 | 4 个 | **本项目 8 个**（书库管理 / 实体管理 / 重复书籍 / 缺失资源对齐上游；书源管理 / 导出目录 / 本地转换 / 转换日志为自有。第 28 期删掉「批量重命名」页签后为 8 个） | 可直接落地 | 已超出线上 |

## 6. 域：统计与成就

> **第 27 期复核（2026-09-19）**：本域原判定「无」的多数项在第 1–26 期已落地，下表按代码改判；每行结论可指到代码行。**两条原判原样保留**（两大标签 / Integrity 四项百分比）；**Metadata Freshness 保留档位但更正了判据**（原判据与代码矛盾，见该行）。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 两大标签（Library Stats / My Reading） | 分区 | 部分：单页 `/stats` 无分区（`views/StatsView.vue` 为平铺区块，20+ 个 `<h3>`，无 tab 结构） | **可直接落地** | 前端分区 —— **原判仍成立** |
| 筛选（All Libraries）+ Configure + 时间粒度（Monthly/Yearly/Last 5 Years） | 参数化聚合 | 时间粒度**已有**：`overview(days=28, top=8)` 参数化并收敛 7–365（`core/stats.py:24,27`），统计页传值（`views/StatsView.vue:26` → `lib/api.ts:2704`）；响应含权威 `window` 字段。「All Libraries」在本项目**无对应概念**（单库部署，`config.py:20` 唯一 `OUTPUT_DIR`） | 时间粒度**已落地**／多库筛选**不适用** | — |
| Books / Authors / Series / Storage / Languages | — | **已有**（`core/stats.py:152-166`） | 可直接落地 | — |
| Publishers / Genres | — | **已有**（`core/stats.py:64-70` 聚合，`:168-169` 返回）；统计页已渲染「Top 出版社」「Top 题材」（`StatsView.vue:327,349`） | **已落地** | — |
| Published 年份范围 / This Year | — | **已有**：`year` 按**十年**聚合（`core/stats.py:71-74` → `years.decades`，`:172-177`），统计页已渲染（`StatsView.vue:371`）。「This Year」按日历年的入库数已有 `added_month`（`core/stats.py:151-157`） | **已落地** | — |
| My Reading（Started / In Progress / Completed / **Avg Progress**） | — | **已有**：前三项（`core/stats.py:88-110`）+ **`avg_progress`**（`:178`） | **已落地** | — |
| **Library Integrity**（Integrity / Present / Primary / Metadata） | 四项百分比 | **无百分比口径**：`integrity` 只有**原始计数** —— `missing_author`/`missing_language`/`no_cover`/`zero_size`/`unparsable`（`core/stats.py:46-52` 初始化、`:59-83` 累加、`:179` 返回），前端按「0 字节」等计数渲染（`StatsView.vue:394`） | **需新增后端能力**（很轻） | **原判仍成立**（计数有、百分比无） |
| Format Distribution | — | **已有**（`core/stats.py:54-55,161`） | 可直接落地 | — |
| **Metadata Score Distribution**（P50/P90） | 24 字段权重评分 | **已有**：`core/metascore.py` 评分模型 + `metascore.summary(bs)`（Average / P50 / P90 + 分档直方图，`core/stats.py:14` import、`:181` 返回） | **已落地** | — |
| Metadata Freshness（Fresh ≤30d / Never fetched） | — | **指标无**。⚠️ 原判据「依赖在线元数据抓取，与定位冲突」**已失效** —— 抓取体系第 5 期就落地了（`core/metafetch.py`，`meta_online.fetched_at` 已在库里，见 `core/db.py:241-250`），这个指标**技术上可直接算** | **不建议做**（档位依价值而非依赖） | 与本项目已有 `metadata_score`（完整度）口径重叠、增量信息少；**不是做不了，是不值得做** |
| Top 50 Largest Books | — | **半落地**：`top` **已参数化**并收敛 1–50（`core/stats.py:17` 默认 8、`:31`），但 ⚠️ **前端从不传** `top`（`lib/api.ts:2704` 只发 `days`），且仓库**无任何按体积的榜单** —— `StatsView.vue` 体积只用于「占用」汇总卡（`:155`） | **可直接落地**（缺榜单与 UI） | 后端参数已具备，缺的是榜单本身与传参 |
| Achievements | 成就体系 | **已有（第 22 期实现）** | **已落地**（单用户口径） | 与多用户无关的成就可做；跨用户口径不做 |
| └ 上游成就模型（源码：`packages/types/src/achievement.ts`） | **5 分类**：`reading / library / exploration / dedication / devices`；**4 档稀有度**：`common / rare / epic / legendary`；字段 `groupKey / tier / threshold / hidden / sortOrder / earned / awardedAt / currentProgress / context` | 本项目成就为自有规则集，**未逐项对齐上游分类与稀有度** | 逐项对齐 **可直接落地**（纯数据/规则）；`devices` 分类 **不建议做**（依赖 KOReader/Kobo 设备实体） | 上游进度由**服务端算好**（`currentProgress` + `threshold`），且支持**全量回填**（对应设置页「运行回填」）——本项目的成就也应是**派生数据**而非一次性打卡 |
| 仪表盘部件 | 12 件 | **已有 12 件**（`components/dashboard/widgets/registry.ts:32-45`） | 可直接落地 | 已对齐 |

## 7. 域：通知与更新

> **第 27 期复核（2026-09-19）**：本域两行**此前全判为「无」，已全部过期** —— 浮层与已读均已落地。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| Notifications 浮层 | 浮层 + 已读 + Mark all read | **已有**：头部铃铛挂浮层（`AppHeader.vue:89` → `components/NotificationBell.vue`），「全部已读」在 `NotificationBell.vue:135-137`；已读走后端 `POST /api/notifications/read`（`server.py:3853`）+ `notifications_read` 表（`core/db.py:135`，`mark_notifications_read` `:980` / `clear_notifications_read` `:1005`）。整页日志视图保留，按类别偏好做客户端过滤（`lib/notifyPrefs.ts`） | **已落地** | — |
| What's New | `/whats-new` | **已有**：`views/WhatsNewView.vue` + 路由 `/whats-new`（`router/index.ts:174`） | **已落地** | — |

## 8. 域：任务中心

> **第 27 期复核（2026-09-19）**：「任务真实性」原有的两项指控（6 条演示种子 + 900ms 假进度 ticker）**均已在第 25 期前后清除**，原判过期。

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| 任务中心 | `/tasks` **返回 404**（线上无此页） | **本项目有**（`/tasks`、`TaskCenterView.vue`、`TaskDrawer.vue`）——**超出线上** | 可直接落地 | 但见右栏风险 |
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

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| `/book-dock` 页面 | 独立页 | **已有独立页**：`views/BookDockPage.vue` + 路由 `/book-dock`（`router/index.ts:87`）；接口 `GET /api/book-dock`（`server.py:3759`） | **已落地** | — |
| Pause / Rescan / Upload | 三个按钮 | **已有**：`POST /api/book-dock/{item_id}/rescan`（`server.py:3765`）+ `.../ignore`（`server.py:3774`）；watcher 侧 `POST /api/watcher/stop`、`POST /api/scan`、`POST /convert` 仍在 | **已落地** | — |
| 状态标签（All / Needs review / Pending / Ready / Error） | 5 态状态机 | **已有状态机**：`book_dock_items` 表（`core/db.py:215`，含 `status` 字段 + `idx_dock_status` 索引） | **已落地** | — |
| 空态 + **整页拖拽投递** | 全页 drop | 部分：仅 `LocalConvertView.vue:158-173` 一个小拖拽区（限 .txt） | **可直接落地** | **原判仍成立** —— 整页拖拽未做 |

## 11. 域：作者与系列

| 能力项 | 线上形态 | 本项目现状 | 档位 | 理由 |
| --- | --- | --- | --- | --- |
| `/authors` 索引 / 排序 / 筛选（2+ books / Added this week） | 完整 | 部分：仅纯 Grid（`AuthorsView.vue:37-61`） | **可直接落地** | 2+books / added-this-week 前端可算 |
| `/authors` No portrait / No sort name | 依赖作者头像与排序名 | **无**（`core/library.py:474-475` 只取 `dc:creator`） | **不建议做** | 依赖外部作者元数据服务 |
| `/authors/:id` 传记 + Actions | 完整 | 部分：有 Back + 书数 + 书单；**无传记、无 Actions** | Last Added **可直接落地**／传记 **不建议做** | 传记需外部数据源 |
| `/series/:id` 排序 + 方向 / Group by media / FIRST IN SERIES / 每书 #序号 / SYNOPSIS | 完整 | **已完整**（第 12 期）：排序 + 方向 / FIRST IN SERIES / 每书 `#序号`（第 6 期）、Group by media（第 10 期 C2）、SYNOPSIS 与系列级字段（第 12 期 C3：`SeriesMetaPanel` 展示 + 就地编辑 + 「恢复在线」+ 抓取，`SeriesRenumberDialog` 重排册号） | — | SYNOPSIS 的取值与作者侧**不同档**：外部源没有「系列」实体，只能靠「系列名检索 + 成员书一致性打分」，低置信度时如实显示「未找到」；**且只存服务端 DB、不写回 EPUB**（OPF 无该字段） |
| `/series` 总览 | — | **已有**（`core/library.py:386-396`） | 可直接落地 | — |

## 12. 域：批注

> **重要更正（2026-09-19）**：历史实测把本域记为「线上为空态」——那只是**该实例当时没有批注数据**，**不等于上游没有能力**。源码（`packages/types/src/annotation.ts`）显示模型明显更深，故原档位理由「超出线上」**作废**，改为按能力项逐条判定。
>
> **第 27 期交付（2026-09-19）**：分组 / 软删除垃圾桶 / 周节拍统计 **三项已落地**；**多端来源、`needsReview`、`devices` 与跨端降色仍未做**，理由见下（无数据源，不建死列与死 UI）。

| 能力项 | 线上形态（历史实测） | 本项目现状 | 档位 | 判据（源码） |
| --- | --- | --- | --- | --- |
| 批注来源 | 空态三张引导卡：Read here / Sync a Kobo / Sync KOReader | 仅 Web 内创建（`server.py:494-504`）；**已建 `origin` 列**并回填 `'web'`（`core/db.py` 迁移块），但**只有 web 一个写入方** | 多端来源 **需新增后端能力** —— **本轮不做** | `origin = "web" / "koreader" / "kobo"` ——三卡即三来源枚举，无第四种。⚠️ kosync 已核实是**纯进度**（只有 `/koreader/syncs/progress` 的 PUT/GET，无批注端点），也没有 KOReader/Kobo 批注导入 → **无数据源**，故只建列不建导入链路，界面如实标注 |
| 配色 | 页面未渲染 | **已有应用侧 10 色**：单一权威表 `frontend/src/data/annotationColors.ts`（原 4 处各自为政的颜色表已全部归并） | 应用侧 **已落地**／**跨端降色不做** | 应用 10 色 / KOReader 9 色 / Kobo 4 色，每色带 `koreaderFallback` + `koboFallback`。⚠️ 没有非 web 来源就没有降色对象，`downmapTo` 写了也无调用方 → 不做 |
| 分组维度 | 页面未渲染 | **已落地**：月 / 书 / 颜色 / 来源四档，默认按书（`views/AnnotationsView.vue`）。**纯前端**分组（列表本就在手，重排即可），未加服务端 `group=` 参数 | **已落地** | `ANNOTATION_HUB_GROUP_MODES = ["month", "book", "color", "source"]` |
| 待复核 / 垃圾桶 | 页面未渲染 | **垃圾桶已落地**：`DELETE` 改**软删除**（写 `deleted_at`），新增 `restore` / `purge`，总览页有垃圾桶视图与恢复/彻底删除（`core/db.py`、`server.py`）。**待复核（needsReview）不做** —— 它服务于「设备回传批注需人工对账」，没有设备回传就没有可对账对象 | 垃圾桶 **已落地**／待复核 **不做** | `AnnotationHubOverview.needsReview` / `.trashed` ——删除是**软删除**；设备回传批注需**人工对账** |
| 统计口径 | 页面未渲染 | **已落地（部分）**：`GET /api/annotations/overview` 返回 `active` / `trashed` / `weeks` / `longest_quiet_weeks`（周节拍按 ISO 周归桶，`core/db.py`），总览页顶部统计条消费。**`devices` 不做**（恒 1，无意义） | **已落地** | `weeks` / `longestQuietWeeks` / `devices` ——以周为节拍，并跟踪「连续无批注周数」 |
| 跨书搜索 / 跳转章节 / 导出 Markdown | 无 | **已有**（`views/AnnotationsView.vue`、`server.py:494-504`）；导出**只导活跃批注**、不含垃圾桶 | **已落地** | 本项目自有能力；上游是否存在对应能力：未验证（源码无法确认，本轮未取 `server/src/modules/annotation` 与 `client/`） |

---

## 13. 明确不建议做（含依据）

| 项 | 依据 |
| --- | --- |
| **界面国际化（Language，25 语言）** | 界面中文硬编码（如 `data/nav.ts:36-43`），需全量抽文案 + i18n 基建；对单人内网工具收益远低于维护成本 |
| ~~**Metadata Freshness / 在线元数据抓取体系**~~ ⚠️ **该条已过期** | **第 5 期已实现抓取体系**：`core/metasources.py`（OpenLibrary / Google Books，均无需 Key）+ `core/metafetch.py`（plan→预览→apply，结果只落 `meta_online`/`meta_cover`、不改写文件）。原判据「本项目只有 EPUB 自身 + 文件名」与 §14 自相矛盾，已作废。**仅「Freshness 指标」本身不做**，理由见 §6 该行（价值低，非依赖冲突） |
| ~~**作者传记 / 作者头像（No portrait）**~~ ⚠️ **该条已过期** | **第 8 期 D1/D2 已实现**：`authors` 表分列「在线抓取值」与「用户本地覆盖」（`bio` / `bio_local`、`photo` / `photo_local_path`，`core/db.py:259-265`），接口 `POST /api/authors/{name}/bio`（`server.py:1931`）+ 作者详情返回 `bio`/`bio_overridden`（`server.py:1902-1903`），前端 `views/AuthorDetailView.vue` 可编辑并显示「已覆盖」标记。原判据「依赖外部作者元数据服务」不再成立 —— 走的是既有抓取链路 + 本地覆盖，不引入新依赖 |
| ~~**有声书阅读器**~~ ⚠️ **该条已过期** | 第 9 期已实现（`core/audio.py` + `/api/books/{bid}/audio` + 播放器 + `reader/audio` 设置页）；原判据「`BOOK_EXTS` 不含音频」不再成立 |
| **Requests 的 Sources / Download clients / Automation 具体功能**（索引器 + 下载客户端） | 与既有「数据驱动书源」体系（`sources/rules.py`、`sources/store.py`）功能重叠。**2026-09-18 起为「已决策不做」**：骨架页与只读接口也已从代码中删除（不再是「按 §9 保留」） |
| ~~**Pages（页数）字段**~~ ⚠️ **该条已过期** | 已实现：EPUB 为估算值（`library._pages_in`）、CBZ 为归档真实页数；第 7 期已计入元数据完整度评分 |
| ~~**多书库（`/libraries`、`/library/:id`、按书库筛选 / 批量重命名 / 查重）**~~ ⚠️ **该条已过期** | **第 10 期已实现**（`libraries` 表 + 库感知路径解析 + 按格式迁移 + 能力显隐矩阵）；原判据「唯一 `OUTPUT_DIR`、无书库实体」不再成立 |
| **Hardcover / Readwise / StoryGraph 同步** | **2026-09-19 用户拍板：本轮明确不做**。源码显示这三项的上游形态并不轻：Hardcover 是**双向**（含导入书单/进度：`HardcoverImportPreviewOutcome` 五态、版本关联 `HardcoverEdition`、匹配方式 `hardcover_id / isbn / title_author`）；StoryGraph **没有公开 API**，凭据只能复用浏览器 `sessionCookie` + `rememberToken`；Readwise 虽最小（`ReadwiseSettings` + `disabledReason`）但与项目定位无关。三项均需**凭据加密存储 + 书籍匹配（ISBN/标题+作者）+ 同步任务调度**，维护成本远超收益 |
| **KOReader / Kobo 设备侧集成** | Kobo 同步已于 2026-09-17 决定不做；KOReader 侧源码显示并非「一处同步」而是**四套并列通道**（进度单一权威源 `canonicalSource`、`heldByReset` 设备分歧、插件目录 9 段 + 批量清单下载、能力协商 `KoreaderPluginCapability`），且插件有独立供应链（`manifestUrl` + `ed25519PublicKey` 签名校验）。复刻设备侧协议成本与收益不匹配，本轮不进入路线图 |
| **上游 Requests 的插件式索引器 / 下载客户端** | 见上一条 Requests 行；另据源码（`packages/types/src/indexer.ts`）其插件体系含签名更新通道与 SSRF 防护（`INDEXER_URL_UNSAFE` / `INDEXER_URL_PRIVATE`）、凭据加密（`BOOK_REQUEST_ENCRYPTION_KEY`），是**完整的插件市场形态**，与本项目「数据驱动书源规则」定位不同 |
| **全部多用户能力** | 单用户轻登录（`core/auth.py:1-5`）；`users` 表无角色字段 |

---

## 14. 分阶段路线图

> 每项格式：**能力 → 后端要补什么 → 前端要做什么**

### 第 0 期（本批立即开工）

- **审计日志**：`core/activity_log.py` 写入函数加 `actor` → `server.py` 各写入点透传 `request.state.user`（后台任务写「系统」）→ 前端真审计表（操作者/类别/动作/详情/时间 + 筛选）
- **收书目录**：复用 `INPUT_DIR` + watcher 现有接口 → 前端呈现投递目录、监听联动、自动处理开关；元数据自动抓取与置信度定稿标注未支持（依赖第 2 期）

### 第 1 期：自动化与运维

- **通知已读态**：新表 `notifications_read` + `POST /api/notifications/read` → 通知中心加已读标记与「全部已读」；顶栏加浮层入口
- **任务持久化**：用 `tasks` 表替掉进程内 `TASKS` dict（`server.py:95`）→ 任务中心改真表；**同时移除 `data/tasks.ts` 的 6 条演示种子与 ticker 假推进**
- **维护与清理**：新增 orphaned 封面目录扫描 + 清理接口（复用 `fileops.recycle_items`）→ `Maintenance` 页真实现
- **上传大小上限**：新增全局上传上限配置（当前**完全无限制**）→ 落到维护页
- ~~**Requests 页面与接口**（§9）~~：**已于 2026-09-18 撤销**（第 1 期曾交付只读骨架页 + `GET /api/requests/config`，现两者均已从代码删除）
- **成就体系**（单用户口径）：新表 `achievements` + `user_achievements` + `core/achievements.py` → `/achievements` 页

### 第 2 期：书库与元数据

- **真实封面**：后端无需新接口（`/api/books/{bid}/asset` 已能代理 zip 内资源）→ 前端先接真实封面，再做封面显示模式 / 书脊 / 阴影 / 卡片叠加层
- **书架三视图 + 搜索 + 排序 + Collapse series + 多选 + Filters**：后端无需改（多选批量写需批量接口）→ 前端 `ShelfView.vue` 重做
- **书卡信息补全 + 系列序号**：后端扩 `_series_of` 解析 OPF `calibre:series_index` → 书卡与系列页展示 `#序号`
- **单书 Edit Metadata**：复用 `fileops._patch_opf`，加 `POST /api/books/{bid}/metadata` → 详情页新增「编辑元数据」标签
- **阅读状态 + 起止日期 + 书评 + 相似书 + Reading Log（按书）+ 手工补录**：`progress` 扩字段 / 新表 `reviews` / 新模块 `core/recommend.py` / 加 `GET /api/books/{bid}/reading-log` → 详情页五标签逐步补齐
- **统计增强**：时间粒度参数化、Publishers/Genres/年份范围/Avg Progress/Top50、Library Integrity（很轻）→ `StatsView.vue` 分区改版
- **导出元数据**：`library.export_rows()` + `/api/books/export` → 书架导出按钮
- **自定义智能书架**：`smart_scopes` 表 + CRUD → `/smart-scopes` 页
- **查重阈值与模糊匹配**：改 `duplicate_groups()` 引入相似度 → 查重页加阈值滑块

### 第 3 期：阅读器体验

- **eBook 排版增强**（纯前端）：翻页/滚动模式、13 档深色主题、段落间距、两端对齐、断词、字距/词距/首行缩进、分栏
- **PDF 阅读器**：后端加文件流接口 → 前端 pdf.js 阅读器 + 对应设置
- **漫画阅读器**：后端加 CBZ/CBR 解包与图片序列接口 → 前端漫画阅读器 + 对应设置
- **字体管理**：后端新增字体上传/列表/分发接口（当前**后端零字体能力**）→ 阅读器字体页 + 服务端字体页
- **偏好同步**（单用户「账号级」= 存服务端多端一致）：偏好表 + 接口 → 外观与阅读偏好支持「本机 / 账号」

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

1. **不做假交互**：任何页面上的控件都必须真实生效；缺后端就先把后端做出来（§0.2）。⚠️ 原例证「骨架页（Requests）的配置项可见但标注功能待实现」**已失效** —— 该页随 C1 于 2026-09-18 删除，现全仓不再有「看得见但点不动」的控件。
2. **新增可配置项必须同时改两处**：`server.py` 的 `EDITABLE`（控制**可写**）与 `GET /api/config` 里的**硬编码键列表**（控制**可读**）是分开的——上一轮新增 `naming` 时踩过「能写进 settings.json 但读不回来」的坑，已在该处留注释。
3. **清除既有演示数据**：`frontend/src/data/tasks.ts:21-28` 的 6 条种子任务与 `stores/tasks.ts` 的假推进 ticker 属**伪造进度**，在第 1 期任务持久化时一并移除，不得保留。
4. **脱敏**：文档与截图不含账号 / 邮箱 / 令牌 / 密钥真实值；含账号显示名的截图不归档（本批已排除仪表盘截图）。
5. **验证纪律**：全量类型检查（**按输出文本判定**，`vue-tsc --build` 报错也返回退出码 0）→ 构建 → 部署 `novelforge/static/v2` → 重启测试实例 → 端到端脚本验证「保存 → 读回 → 实际生效」→ 浏览器逐路由冒烟；改后端写入路径时额外验证**历史条目兼容**。
6. **采集复现**：截图必须是**整页**——本应用用内层滚动容器，`fullPage` 对它是无效的。可靠做法是**把视口高度撑到内容高度**（实测：11 页从 720 补到 1006），而不是解除容器 overflow。
7. **档位可变**：若未来引入多物理目录或多账号，标为「需架构变更」的项可重新评估。
