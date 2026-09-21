# 上游功能缺口跟踪基线（第 6 期起）

> 来源：`docs/bookorbit-capability-gap.md`（采集自线上实例 BookOrbit v2.10.0，2026-09-16）
> 基线日期：2026-09-18
> 已完成参考：第 0–5 期路线图（见 `docs/roadmap-verification.md`，第 0–4 期 27/27 验证，第 5 期 2026-09-17 完成）；**第 6–32 期已完成**（第 33 期进行中）—— 第 6–9 期见下方分期标题（A1–A9 前端快赢 / B1–B4 轻后端 / D1–D5 作者级元数据与抓取深化 / D6–D7 CBR 阅读与有声书播放器），第 10 期起见「三、分期实施计划」下的**逐期实施记录**
> **第 33 期提示**：本文件的缺口清单已实质清空（档位为「可直接落地」的行**已全部收口**）。新增的缺口来源
> 请改看 `docs/bookorbit-module-inventory.md`（按上游代码模块逐条对照，已实测出 16 个此前从未被判定过的模块）——
> **只 grep 本文件会系统性漏项**，实测名称为准的 grep 假阴性率过半。
> 用途：跟踪"上游有、本项目仍缺失"的功能，并给出分期实施计划。本文件为**活文档**，每完成一项勾掉一项。

## 核验约定

- **✅ 实检缺失**：本文件编写时实跑 `grep`/`read` 确认源码无对应实现。
- **推断缺失**：依据 gap 文档"可直接落地 / 需新增后端能力"标注 + 路线图完成度推断，未逐行核实。
- 勾选框 `[ ]` 表示待实施，`[x]` 表示已完成并经验证。

---

## 一、待实施：上游有、本项目缺失

### A 类 · 纯前端（零后端，小时级，最高快赢比）

- [x] **A1 Appearance 浮层** — 顶栏主题快捷浮层（复用 localStorage 偏好）✅ 实检缺失
- [x] **A2 作者页排序/筛选** — 排序（书量/姓名）+「2+ 本」筛选（纯前端）✅ 实检缺失；「Added this week」需后端 author 级 `added` 字段，留待轻后端批次
- [x] **A3 作者详情页 Actions / Last Added** — 排序（书名/系列/最近添加）+「打开最近添加」真实操作
- [x] **A4 系列详情 FIRST IN SERIES** — 系列首册标记 ✅ 实检缺失（仅 #序号已做）
- [x] **A5 系列详情 排序方向 / SYNOPSIS** — 顺序/倒序切换 + 首册标记；SYNOPSIS 仅诚实「未提供」说明（上游来自外部元数据，未接入）✅ 实检缺失
- [x] **A6 What's New 页** — 静态 JSON 驱动，v2.10.0 风格 ✅ 实检缺失（无路由）→ 已建 `/whats-new` + `data/whatsNew.ts`
- [x] **A7 Documentation / Help 页** — 文档入口 ✅ 实检缺失 → 已建 `/docs` 链接应用内真实路由
- [x] **A8 Book Dock 整页拖拽投递** — 整页拖拽遮罩，松手投递到 INPUT_DIR（复用 /convert）✅ 实检缺失已补
- [x] **A9 Show library controls（书架级库控制条）** — 书架级控制条（视图/排序/方向/折叠/筛选/书卡信息/导出）已在 ShelfView 工具栏实装，无需新增

### B 类 · 轻后端（新表/接口，天级）

- [x] **B1 上传多格式** — `/convert` 放开 `.txt` 限制，EBOOK_EXT（EPUB/PDF/CBZ/FB2/MOBI/AZW3）直接入库（复用 `pipeline.dispatch`）；Book Dock 整页拖拽随之支持多格式 ✅ 已端到端验证（pdf/epub 入库、txt 转换、docx 拒绝 400）
- [x] **B2 Metadata Score Distribution (P50/P90)** — `core/metascore.py`：12 字段 × 5 组权重模型（加总 100；非 EPUB 归一化分母）+ P50/P90 + 4 档直方图（<50 / 50-69 / 70-89 / 90+）；`GET /api/metadata-score`；`stats.overview` 内嵌 `metadata_score`；前端 `MetadataScoreCard.vue` 接入「书库 → 元数据 → Confidence Score」。**只列本项目元数据管线真正能填的字段**（上游 24 字段含 Provider 专有字段，不凑数）；Series 计入 Enrichment（与上游"不计分"不同，已在页面标注）✅ 已实调验证
- [x] **B3 Book Dock 5 态状态机** — `book_dock_items` 表（id = 投递文件名）+ `core/bookdock.py` 状态机（pending/ready/needs_review/error，外加 `ignored` 隐藏终态）+ watcher `on_scan` 回调 + `/api/book-dock` 列表与 rescan/ignore/delete 三项操作；前端 5 标签（全部/待复核/待处理/就绪/出错）+ 逐条操作。**删除即移入回收目录**（不 unlink）✅ 端到端验证（docx→待复核、epub/txt→就绪、忽略隐藏、移出进回收）
- [x] **B4 用户菜单浮层** — 顶栏 `UserMenu` 浮层（复用 NotificationBell 模式）：用户名 + 个人资料入口 + 退出登录（清 `nf_token` 并弹回登录门禁）；Account 页与改密码此前已有（ProfilePage）✅ 已构建部署

### C 类 · 重（架构/外部依赖，周级，按需）

- [x] ~~**C1 Requests 完整功能**~~ — **已决策不做（2026-09-18，用户决策）**。理由：本项目的「从外部获取书」由**数据驱动书源规则**覆盖（`sources/rules.py` + `sources/store.py`），插件式索引器 / 下载客户端与之形态重叠、维护成本高。**页面与接口骨架已从代码中删除**：后端 `REQUEST_SECTIONS` + `GET /api/requests/config`；前端 `RequestsPage.vue` / 路由 / 设置注册项 / API 方法（`admin/requests` 页数 48 → 47）。⚠️ 旧理由「`Add to library` 依赖多库 → 不落地」在**第 10 期多库完成后已失效**，不再引用。
  ⚠️ **第 27 期复核（2026-09-19）**：此处「48 → 47」只是**当次删除动作**的增量记录，不是当前页数。当前设置页为 **48 页**（41 上游 + 7 本项目补充），见 `tests/test_settings_nav_contract.py:96` 的双向断言；`admin/requests` 仍在 `EXPECTED_PLACEHOLDERS`（`:38` 起、该项在 `:53`）里，即该页骨架被删除后**又以只读占位页形式存在**
- [x] **C2 系列详情 Group by media** — 第 10 期完成：`GET /api/series/{name}` 增 `groups`（复用 `migrate.target_type_of` 按媒体归类，含 media/label/count/books）；`SeriesDetailView` 按组分段渲染，**仅多于一组时**才加组标题（单媒体系列不加噪音），组内仍按系列序号排序并保留首册标记与倒序切换
- [x] **C3 SYNOPSIS 外部源** — **第 12 期完成**：新增 `core/series_meta.py` + `series_meta` 表（在线值与本地覆盖**分列**，与 `authors` 表同构）；`metasources.search_series` 用**系列名检索 + 成员书一致性打分**挑候选（⚠️ 外部源**没有「系列」实体**，OpenLibrary 的 `search.json` 既不返回系列字段也无系列详情接口 —— 可靠性天然低于作者侧；一致性分低于 `MIN_MATCH=0.6` 就**如实回「未找到」**，不编造简介，并把来源与置信度一并交给界面展示）；字段分层取 **本地覆盖 > 本地聚合 > 在线补空**（总册数 / 首发年 / 出版社 / 题材**优先**用成员书 OPF 聚合出的**事实**，在线值仅补空）；生效点是三处注入：`GET /api/series/{name}`、`komga_api.series_dto`（`metadata.summary` 原先恒为空串）、OPDS 系列入口（列表 `<summary>` / 系列内 `<subtitle>`）。
  ⚠️ **系列级字段只存本项目 DB、绝不写回 EPUB**（用户 2026-09-18 拍板）：OPF 里没有「系列简介」这个字段，唯一近似 `dc:description` 属于**单册**，写进去就是用系列简介覆盖掉某一册自己的简介；「系列首发年」写进各册 `dc:date` 还会让某本 2019 年出版的第 7 册变成 2015 年。**已知代价（已确认接受）**：把书库目录直接用 SMB 挂给别的软件（如 Calibre）时看不到系列简介与系列出版社；**连服务读**（Komga 客户端 / OPDS / 应用界面）则全部可见 —— 且写回方案**同样送不出「系列简介」**，故不为此动用户文件。
  另附「重排册号」：按当前序号升序重写 `calibre:series_index`（缺序号的排最后，不假装它是第一册），**只改 OPF、不动文件名** → `book_id` 不变 → 阅读进度 / 批注 / 评分 / 收藏不断链；返回带每条 `old_index`，可完整回滚（含「原本没有序号」→ 清除）。

### D 类 · 2026-09-18 复核后从「不做」移入排期

> 复核结论：原「已决策不做」清单里有 6 项判定已过期或过粗（详见第二节「已修正的过期记载」）。
> 其中「在线元数据抓取 / Pages」实际已实现，「作者传记/头像、有声书、多书库、CBR」现正式排期。

- [x] **D1 作者传记** — 第 8 期完成：`core/authors.py` 走 OpenLibrary 作者检索取传记；`authors` 表把**在线值 / 本地覆盖分列**，展示取「本地覆盖 > 在线」，用户改过的不被再次抓取冲掉
- [x] **D2 作者头像** — 第 8 期完成：头像下载到 `CACHE_DIR/authors/`（**零外链**），并加入 `_MEDIA_TOKEN_PATHS`（`<img src>` 只能靠 `?token=`）；无图 404 → 前端回退渐变占位；归一化名相似度 <0.5 视为不同人（宁可放弃也不给错配）
- [x] **D3 `metadata/authors` 页做实** — 第 8 期完成：作者区块改为真实开关（启用 / 抓传记 / 抓头像 / 立即抓取全部作者），不再虚高为 `ready`
- [x] **D4 抓取深化** — **已全部完成**。① **ISBN 精确匹配**（第 8 期）：`metasources.search_by_isbn`，命中即 `score=1.0`、`exact_isbn=True`，`metafetch.plan` 与 `online_candidate` 优先采用；② **系列级元数据**（第 12 期，原标注「仍缺、顺延」的那一项）：见上方 C3，`core/series_meta.py` + `series_meta` 表 + 系列页可编辑 / 可恢复在线 / 可抓取全部系列
- [x] **D5 A2 收尾** — 第 8 期完成：`GET /api/authors` 增 `added_ts`（名下最早一本书的 mtime），作者页「本周新增」筛选 +「新」徽标落地
- [x] **D6 CBR 阅读** — 第 9 期完成：`core/comics.py` 抽象 zip/rar 双后端（魔数嗅探 + `rarfile`，后端 `bsdtar` 由 `libarchive-tools` 提供）；`.cbr` 进 `BOOK_EXTS`；封面 / 漫画路由 / Komga 页面流 / OPDS MIME 全部放开
- [x] **D7 有声书播放器** — 第 9 期完成：新增 `core/audio.py`，把「一本书 = 一个文件」扩展为「**音频目录（一章一文件）或单个音频文件 = 一本书**」；`/api/books/{bid}/audio(/{index})` 轨清单 + Range 流式；完整播放器（倍速 / 快退快进间隔 / 睡眠定时 / 轨道列表 / 按秒进度同步）；`reader/audio` 设置页做实并纳入偏好同步（`PREFS_BLOCKS` 加 `audio`）
- [x] **D8 多书库** — 第 10 期完成。`libraries` 表 + `library_migrations` 台账 + `app_state` KV；`library.py` 改为**库注册表驱动的多根扫描**（缓存与指纹按库）；路径解析全仓库感知（`library.root_of(book)`、`fileops.output_dir(library_id)`、`safe_path` 按**所属库根**约束；Komga `libraryId` 按真实库返回、按库过滤生效）；`core/migrate.py` 按格式迁移（同名冲突拒绝并给建议名、批次幂等、一键回滚）；`core/library_rules.py` 入库归库（来源子目录名 > 格式 > 关键词）；`core/features.py` 能力矩阵驱动侧栏 / 工具标签 / 设置分组 / 仪表盘部件显隐。**一个刻意的保留**：`book_id` 仍由 basename 派生、不做数据迁移，跨库同名由迁移与入库时的冲突检测拦住

---

## 二、已决策不做（明确排除，不计入实施）

依据 `gap` 文档 §13 + 第 4 期决定，并于 2026-09-18 复核：

- 国际化（25 语言）— 中文硬编码，i18n 成本远超收益
- 全部多用户能力（多账号/角色/OIDC/账号审计/跨用户统计等）— 单用户轻登录
- Kobo 同步 / 邮件投递 — 2026-09-17 用户决定不做
- 在线元数据抓取的「源插件市场 / 更多第三方源」— 维持内置 2 源（OpenLibrary / Google Books），不引入插件体系

### 已修正的过期记载（2026-09-18 复核，以代码实况为准）

- **在线元数据抓取 / Metadata Freshness → 不再是「不做」**：第 5 期已实现（`core/metasources.py` + `core/metafetch.py`、入库自动抓取 `watcher.auto_fetch_async`、字段策略默认 `fill_only`、封面写入、7 个设置页）。仍缺的子项已移入 D4。
- **Pages（页数）字段 → 已实现**：EPUB 为**估算值**（`library._pages_in`，`BYTES_PER_PAGE=2048`，`pages_source='estimate'`），CBZ 为**真实值**（`comics.probe`，`pages_source='archive'`）；非 EPUB 恒 0、前端不显示。第 7 期 B2 已把它计入 Publishing 组（4 分）。
- **作者传记 / 作者头像 → 移入 D1/D2**（此前记「依赖外部作者元数据服务」，实为可复用已有抓取管线，成本中等）。
- **有声书播放器 → 移入 D7**（`BOOK_EXTS` 不含音频，`reader/audio` 页为 placeholder）。
- **多书库 → 移入 D8**（`collections.ts` 的 `LIBRARIES = []` 为空，侧栏「库」组无数据；`libraries` 设置页为 placeholder）。
- **CBR 阅读 → 移入 D6**（`comics.py` 明确只支持 CBZ，`.cbr` 不在 `BOOK_EXTS`，`library.py:35`）。

---

## 三、分期实施计划

### 第 6 期 · 前端快赢批次（A 类，零后端）✅ 已完成（A1–A9）
> 实际顺序：A1 → A6/A7 → A2/A3 → A4/A5 → A8/A9；另含「设置左列替换为设置导航」（`SettingsSidebar`）与 Book Dock 整页拖拽投递。

### 第 7 期 · 轻后端增强批次（B 类，天级）
1. [x] B1 上传多格式 — `/convert` 按扩展名分派（复用 `pipeline.dispatch`）
2. [x] B2 Metadata Score — `core/metascore.py` 权重模型 + `stats` 分位聚合
3. [x] B3 Book Dock 状态机 — `book_dock_items` 表 + `core/bookdock.py` 状态流转 + 前端 5 标签
4. [x] B4 用户菜单浮层 — 顶栏 `UserMenu` + Sign out（Account 页与改密码此前已有）

### 第 8 期 · 作者级元数据 + 抓取深化（B 类，天级，可立即开工）
> 主题：把「元数据只覆盖书」扩展到「也覆盖作者」，并补齐抓取缺口。全部复用既有 `metasources`/`metafetch` 管线，无需新架构。

1. **D1 作者传记** — 新增作者级检索（OpenLibrary `/authors` 或 Google Books 作者聚合）→ 新建 `core/authors.py` + `authors` 表（作者名 / 传记 / 照片路径 / 抓取时间）
2. **D2 作者头像** — 照片下载到 `CACHE_DIR` 本地缓存（**零外链**，与字体/封面同一约定），经 `/api/authors/{name}/photo` 分发；`AuthorsView.vue` / `AuthorDetailView.vue` 展示
3. **D3 `metadata/authors` 页做实** — 从「通用抓取开关」升级为作者级策略（开关 / 抓取内容 / 来源），status 由虚高 `ready` 转为真 ready
4. **D4 抓取深化** — 按 **ISBN 精确匹配**（当前只用书名+作者相似度）、**系列级元数据**（当前只写单本）
5. **D5 A2 收尾** — 作者页「Added this week」需后端 author 级 `added` 字段，随 `authors` 表一并落地

### 第 9 期 · 媒体形态扩展（CBR + 有声书）✅ 已完成
> 主题：把书目从「EPUB / PDF / CBZ」扩展到「漫画（+ CBR）」与「有声书（多轨 / 单文件）」。
> 用户已确认全部取最大档：引入系统依赖完整支持 CBR；有声书按「文件夹多轨 = 一本书」；播放器做到完整。

1. [x] **D6 CBR 阅读** — `requirements.txt` 加 `rarfile`；`Dockerfile` runtime 加 `libarchive-tools`（提供 bsdtar）；
   `comics.py` 用**魔数嗅探**选后端（`PK` → zipfile / `Rar!` → rarfile），`probe/pages/page_bytes/cover_entry` **签名不变**
   （上层零分支）；`BOOK_EXTS` 收 `.cbr`；`server` 封面与两个 comic 路由放开 CBZ/CBR（缺解压器返回 503）；
   `komga_api` 页面流、`opds._MIME`、`koreader.from_nf` 一并同步。
2. [x] **D7 有声书播放器** — 新增 `core/audio.py`（`AUDIO_EXTS` / `is_audio` / `is_audio_dir` / `tracks` / `cover_in_dir`）；
   `library` 引入**书目条目**概念（文件 **或** 音频目录），`_dir_signature` 与枚举**同源**（目录内部文件数与最新 mtime 计入指纹，
   避免「加了音频但列表不刷新」）；`book_detail` 下发轨道清单；
   `pipeline` / `watcher` 支持音频文件与**音频目录整树入库**；
   `GET /api/books/{bid}/audio(/{index})` + `_MEDIA_TOKEN_PATHS` 放开 `?token=`（`FileResponse` 自带 Range，拖拽跳转必需）；
   前端新增 `AudioPlayerView.vue` + `AudioPlayer.vue` + `lib/audioPrefs.ts`，路由 `/listen/:id`；`BookDetailView` 按格式分流；
   `reader/audio` 设置页做实（默认倍速 / 音量 / 快退快进间隔 / 睡眠定时），偏好同步三处加 `audio` 块。

### 第 10 期 · 架构级 / 重投入（需单独立项，周级+）

1. **D8 多书库（含库类型与功能按需加载）** — 动摇单一 `OUTPUT_DIR` 假设。**已确认口径**：
   - **compose 增加「书库来源根目录」挂载**（形如 `LIBRARY_SOURCE_DIR`，容器内如 `/app/libraries`），与既有 `INPUT_DIR` / `OUTPUT_DIR` / `CONFIG_DIR` / `CACHE_DIR` 同风格；
   - **新建书库两种模式并存**：①**就地引用**来源根目录下某个子文件夹（直接扫描、不搬文件，类 Komga 多 root）；②**作为导入源**（库另有独立存储目录，扫描后复制 / 移入）；
   - **库类型**：电子书 / 漫画 / 有声书 / 混合通用 —— 类型决定**功能显隐矩阵**（侧栏导航项、工具页标签、阅读器入口、设置页分组、仪表盘部件）；
   - **自动归类**（三条都启用）**+ 手动兜底**：按格式 / 媒体类型（`cbz`·`cbr` → 漫画；音频文件或目录 → 有声书；`epub`·`mobi`·`azw3`·`pdf`·`txt` → 电子书）、按元数据关键词（tags / 系列 / 作者）、按来源子文件夹名；界面上仍可逐本 / 批量手动指定；
   - **影响面**：`library.py`（多 root + 库维度扫描）、`stats.py`、工具页全域（实体管理 / 重命名 / 查重 / 缺失资源）、侧栏「库」组接真实数据（当前 `collections.ts` 的 `LIBRARIES = []`）、摄入链路（`pipeline` / `watcher` / `bookdock` 按规则路由）、`db.py`（新增 `libraries` 表与归属关系；⚠️ `book_id` 由 basename 派生，**跨库同名会冲突**，需带库维度或加前缀）；
   - **与第 9 期的关系**：第 9 期落地的漫画与有声书是「按类型分类与显隐」的前置，顺序不可颠倒。
2. ~~**C1 Requests 完整功能**~~ — **已于 2026-09-18 决策不做**（详见第一节 C 类说明）：本项目的「从外部获取书」走数据驱动书源规则，插件式索引器 / 下载客户端不做；已交付的只读骨架页与接口**已从代码中删除**
3. **C2 系列 Group by media** — 需后端按媒体类型分组（第 9 期已让 `format` 具备 `AUDIO` / `CBR` 两种媒体类型，此项可顺势落地）
4. **C3 SYNOPSIS 外部源** — 依赖外部系列元数据，先做可行性评估，可能并入 D1 的作者 / 系列级抓取

#### 第 10 期实施记录（D8 + C2）与**用户确认的四项结构决策**

四项决策已由用户逐条拍板，实现按此落地（偏离前需重新确认）：

1. **`/api/libraries` 升级为「库实体」**，格式分面改址 `/api/library-facets`；侧栏「库」组只列真实书库，
   格式分面**不再占侧栏**（书库页本就有格式筛选，那批 `fmt:` 条目是冗余入口）。侧栏「库」组里
   `data/collections.ts` 的 `LIBRARIES = []` 仍是**死数据**（被 `AppSidebar.groups` 覆盖）。
2. **库根不设默认，逐库选**：新建库时在向导里二选一 —— **就地引用**（`LIBRARY_SOURCE_DIR/<子目录>`
   即库根，不搬文件）/ **独立存储**（库自有存储目录，来源目录的文件导入进来）。
   库里**只存相对的来源子目录名**（`source_subdir`），不存来源绝对路径 —— 挂载点换了绝对路径会失效。
3. **迁移首次需一次确认**：启动时只生成逐条预览并落 manifest，**阻塞**等用户点一次「执行迁移」；
   选过「暂不迁移」即记入 `app_state`（不再打扰），设置里可勾「以后自动执行」。
4. **保留「全部书库」为默认**（不裁剪）：只有选中某个库时，侧栏导航 / 工具标签 / 设置分组 /
   仪表盘部件才按该库类型裁剪；统计与搜索默认跨库。

新落地的关键文件：`core/migrate.py`、`core/library_rules.py`、`core/features.py`；
新接口分组：`/api/libraries`（实体 CRUD + 扫描 + 来源目录列举）、`/api/library-facets`、
`/api/features`、`/api/library-migrations/*`（preview / plan / apply / rollback / batches / dismiss / reset-gate）。
**安全边界**：库根只允许落在「书库来源目录 / 导出目录 / 数据目录」之内（否则改名 / 回收会作用到系统目录）。

#### 第 11 期实施记录（工程护栏：自动化测试 + 删除 C1）

**主题**：给项目装上「工程护栏」—— 十期迭代后回归面已很大，而此前**零自动化测试**，每期只能人工冒烟。

- **新增 `tests/`（107 个用例，完全离线，约 2 秒跑完）**，分两层：
  - **核心纯逻辑**：`test_migrate.py`（按格式迁移 / 批次幂等 / 同名冲突拒绝并给建议名 / 一键回滚 / 逐条独立）、
    `test_library_rules.py`（归库优先级：来源子目录名 > 格式 > 关键词 > 回退默认库）、
    `test_features.py`（库类型能力矩阵边界）、`test_metastore.py`（override > online > opf 与 `orig` 语义）、
    `test_fileops_guard.py`（越界 / 绝对路径 / 层级 / 非法字符 / **跨库穿越**等安全负例）；
  - **接口冒烟**：`test_api_smoke.py`（鉴权 401、库根白名单 400、默认库不可删、非空库需 force、
    迁移 preview→plan→apply→rollback 全链路、元数据编辑产生覆盖并可恢复、非 EPUB 编辑被拒、能力清单、系列按媒体分组）。
- **两处关键工程决策**：① **环境变量必须在 import 业务模块之前设置**（`config` 导入即固化各目录、
  `server.py` 导入即执行 `ensure_dirs()`）→ `tests/conftest.py` 顶部先建会话级临时根再 import；
  ② `db` 的 `_conn` / `_db_path` 是模块级缓存 → **本期唯一一处业务代码改动**是新增 `db.close()`
  （关闭并清空缓存，供测试与切换数据目录使用，**不改任何运行时行为**）。
- **dev 依赖隔离**：新增 `requirements-dev.txt`（`-r requirements.txt` + `pytest>=8.0`）与 `pytest.ini`；
  **不写进 `requirements.txt`**，生产镜像不受影响。按用户选择**未加** CI workflow / 自检脚本。
- **删除 C1（求书）**：后端 `REQUEST_SECTIONS` + `GET /api/requests/config`；前端 `RequestsPage.vue` +
  router 注册 + settingsNav 条目 + `api.ts` 类型与方法 + `NetworkPage` 死链文案。并在测试里加了
  「`/api/requests/config` 返回 404」的断言，防止半删状态回归。上游采集记录（`NotificationsPage` 的
  `Book requests` 事件列举、`docs/review/*`、`bookorbit-settings-inventory.md`）**作为对照记录保留**。
- **文档与实况对齐**：C1 归档为「已决策不做」（并指出旧理由「依赖多库」在多库落地后**已失效**）；
  补勾第 8 期遗留未勾的 D1–D5（其中 **D4 的「系列级元数据」明确标注仍缺、未随本期关闭** ——
  ⏩ 该项**已于第 12 期完成**，见 C3 与 D4 条目；此处保留当时快照不改写）；
  `capability-gap.md` 修正 6 处过期记载（Requests 三处、多库两处、有声书 / Pages 各一处）；
  README 48 → 47 并新增「自动化测试」小节；`router/index.ts` 与 `settingsNav.ts` 里早已漂移的页面计数统一为 **47**。

#### 第 14 期实施记录（OPDS 按库暴露）

**主题**：第 10 期多书库落地后，书库已是**数据实体**，但对外目录仍停在「全库一个 feed」——
客户端订阅 `/opds` 看到的是所有库混在一起。本期把库维度补进 OPDS。

- **库只能落在路径上**：OPDS 客户端只会发 URL（多数连自定义头都不支持），且订阅的是固定地址
  → 新增 `/opds/lib/{lid}/…` 一整套（all / recent / authors / series / tags / author/{name} /
  series/{name} / tag/{name} / search / book / cover / download），**不给既有路由加 `?library=`**。
- **默认零变化**：`opds.py` 的新参数一律 keyword-only 且默认值等于原行为（`prefix="/opds"`），
  `/opds`、`/opds/all` 一行没动；只有**可见库 > 1** 时根导航才插入「按书库」入口
  （沿用 C2「仅多于一组才加组标题」的取法）—— 单库部署的输出与加它之前一致。
- **可见性两层，真值源只有一处**：`features` 新增能力键 `opds`（入 `_COMMON`），
  `SETTING_CAPS` 登记 `opds.expose`；`lib_settings.ITEMS` 新增覆盖项「对 OPDS 暴露」（bool），
  全局 `config.DEFAULTS["opds"]["expose"] = True`（= 全部暴露 = 与加开关前一致）。
  **不可见与不存在一律 404**，不给客户端「这里有个库只是不给你看」的暗示。
- **单库取书走库内查找**（`_opds_book_in`），不用 `library.by_id()` —— 后者遇跨库同名抛
  `BookIdConflict`；于是「这本书在不在该库」只有一处判定。
- **测试**：新增 `tests/test_opds_library.py`（10 例：关闭态 404、Basic 401、库导航、单库整套、
  单库搜索只在本库、关掉暴露后 404 且不进导航、越库取书 404、全局输出无库前缀回归）。
  能力集因此 +1 `opds`，同步改 `test_features.COMMON` 与「能力清单 17 → 18」两处断言；全量 **181 passed**。
- **顺带收尾（四处小尾巴）**：`settingsNav` 的 Watcher note 过期（`watcher.auto_fetch_async` 早已实现，
  且 `auto_fetch` 按阈值自动定稿）；`MEMORY.md` 里「仪表盘 12 登记 / 3 实现」过期（实际 12 个全实现）；
  两条同 id 的 `koreader` 设置页（上游对照那条改 path `koreader-upstream`，消掉 vue-router 的静默覆盖
  与侧栏重复 key 告警）；仪表盘「作者」计数 `/placeholder/_authors` 死链改 `/authors`。

#### 第 15 期实施记录（Komga 兼容服务端补齐）

**主题来源**：用户要的是「**本机作为服务端，为其他设备提供 Komga 订阅源**」—— 不是 OPDS，
而是第 5 期就有的 `/api/v1/*` 兼容服务端（第三方 Komga 客户端把地址填成 NovelForge 即可）。
多书库落地后它有一处没闭环：客户端在库视图里选了某个库，看到的仍是全部书库混在一起。

- **库维度接进 Komga 出口**：`komga_api.grouped(library_id=None)` 与 `find_series(name, library_id=None)`
  加可选库形参（默认 `None` = 全库 → 三个单系列端点行为零变化）；server 侧新增
  `_ko_visible_libraries` / `_ko_books` / `_ko_grouped` / `_ko_library_id_of` 四个辅助，
  **可见性判定只有这一处**。`POST /series/list` 此前**整个丢掉 payload**，现在 `libraryId` 生效；
  老客户端的 `GET /series`、`GET /books` 也新增 `library_id` 查询参数（不传 = 全部可见库 = 与之前一致）。
- **有声书不进 Komga**：不新增配置项，复用既有能力矩阵 —— `features` 的 `komga` 能力只属于
  ebook / comic / mixed，`audiobook` 天然没有 → 从**书库**这一层挡掉（`/libraries` 不列，
  书籍与系列列表也不含它的书）。此前 AUDIO 会因回退 DIVINA 变成打不开的坏条目。
- **CBR**：`MEDIA_TYPES` 补 `application/vnd.comicbook-rar`、`_PROFILES` 补 `DIVINA`
  （页面流早支持 CBZ/CBR，缺的只是元数据）。
- **系列级已读**（全新能力，仓库内无既有口径）：官方规格已查证 ——
  `POST /api/v1/series/{id}/read-progress` = 标已读、`DELETE` = 标未读，均 **204、无 body**。
  实现 `komga_api.mark_series_read()`：**保留原 locator、只把 percent 顶到 100**
  （与书级 `completed: true` 同语义 —— 标已读不该把读者送回第一页）。
  顺带给书级补了官方新口径 `PATCH`（老客户端仍走 `PUT`，两者都保留）。
- **测试**：新增 `tests/test_komga_library.py`（7 例：系列按库过滤、书籍按库过滤、有声书库不出现、
  CBR 媒体类型、系列级已读保留位置 / 未读归零、不存在的系列 404、PATCH 与 PUT 等价）。全量 **188 passed**。
- **已知取舍（已写进注释与文档）**：系列 id 由**名字**派生，客户端已用它存进度与收藏 →
  按库过滤后同名系列只出现在第一本所在库，**不为此改 id 派生方式**。

#### 第 16 期实施记录（Komga 客户端兼容收尾 + 删除 OPDS 订阅）

**主题**：本项目**就是** Komga 服务端，本期只做「被客户端访问」的最后一公里；同时删掉唯一一条
「从其他项目取数据」的能力。用户明确：**接入侧（从别的 Komga 拉书目 / 下载入库 / 双向同步）永久不做**，
设置页「未支持接入侧」那句**保留不划掉**。

- **Collections = 应用内收藏夹（可写）**：Komga 的 Collection 装**系列**，本项目收藏夹装 **book_id**
  → 映射时按书归到各自系列。端点按官方规格实现：`GET/POST /api/v1/collections`、
  `GET/PATCH/DELETE /api/v1/collections/{id}`、`GET/PUT /api/v1/collections/{id}/series`、
  `DELETE /api/v1/collections/{id}/series/{seriesId}`、`GET /api/v1/collections/{id}/thumbnail`。
  写操作真的落到 `collections` 表（应用内收藏夹页立刻能看到）；**自定义封面一律 403**
  （夹封面取成员书的封面，不假装支持上传）。`db` 新增 `update_collection` / `clear_collection`
  （此前**没有重命名入口**）。
- **越库的书不进 Komga**：收藏夹是全局的（能装有声书库的书），成员工书一律过 `_ko_books()` 的可见性过滤
  → 从 Komga 侧看它们不存在。
- **没有的概念诚实为空**：Readlist 返回空分页；`POST /readlists` 与 `/readlists/import` 给 403。
  `POST /api/v1/series/{id}/analyze` 是 **204 空实现**（书目实时扫描，没有「重新分析」这一步，但不假装做了）。
- **其余补齐**：`GET /api/v1/referential`（引用表，字段齐全且给真实值）、`GET /api/v1/libraries/{id}`（单库详情）、
  `GET /api/v1/books/{id}/previous|next`（系列内相邻）。
- **OPDS 搜索描述文档（OSDD）**：新增 `/opds/search/description`（与单库版），根 feed 的 `rel="search"`
  指向它并改用 `application/opensearchdescription+xml` —— 此前那里放的是 acquisition feed 的类型，客户端多半识别不出搜索。
- **删除「OPDS 订阅」（接入外部源）**：后端 6 条路由与注释段（107 行）、`core/opds_client.py`（240 行）、
  `db` 的 5 个 CRUD 函数（建表语句保留，老库可能已有）、`features` 的 `opds_sources` 能力键（三处集合 + 标签）；
  前端 `OpdsSourcesView.vue`、ToolsLayout 标签（10 → 9）、router 注册、`lib/api.ts` 类型与方法块；README 四处；
  `whatsNew.ts` 与 `DocumentationView.vue` 的「订阅源」文案改「目录」（避免与对外服务混淆）。
  测试加「`/api/opds/sources` 返回 404」的防回归断言。
- **测试**：新增 `tests/test_komga_client.py`（12 例：收藏夹映射 / 整体替换与移出 / 越库过滤 / 重命名与重名 409 /
  自定义封面 403 / Readlist 空与 403 / 引用表 / 单库详情 / 上一本下一本 / analyze / OSDD / 删除后 404）。
  能力集删掉 `opds_sources` → `test_features` 两处与「能力清单 18 → 17」同步。全量 **200 passed**。

#### 第 17–19 期实施记录（多书库收尾 / 刮削出版 / 写文件收敛 —— 由并行会话完成）

> 这三期的改动与本会话的 14–16 / 20–22 期**逐行交织**在同一批文件里（`db.py` / `server.py` /
> `watcher.py` / `api.ts` / `LibrariesView.vue`），当时的 commit 按「层」而不是按「期」拆，
> 各期口径写在 commit 正文里。这里按**口径**归档 —— 补记于第 22 期收尾的 T5 文档同步。

- **第 17 期 T2 · 逐库扫描调度**：`libraries` 表新增 `watch` / `scan_interval` / `scan_cron`
  （库**实体列**，不是 `settings` 覆盖项，故不进 `SETTING_CAPS`）；watcher 从「单一 INPUT_DIR 目标」
  改为**多目标调度器**（每库的来源子目录 = 一个目标，各带监听 / 间隔 / cron，坏 cron 退化为 interval）；
  `scan_once()` 仍只扫全局输入目录（`/api/scan` 向后兼容），另加 `scan_library_now(lid)`。
- **第 17 期 T3 · 元数据只存服务端**：所有「写回元数据」的落点（手动编辑 / 恢复 / 入库抓取 / 手动
  apply）改为**只写 SQLite**、绝不改写 EPUB；新增 `meta_cover` 表缓存服务端封面；
  `library._scan_once` **一次批量**合并 `override > online > opf`（靠 5s 扫描缓存摊销）——
  于是书架 / 卡片 / 搜索 / OPDS / Komga 与详情页口径一致。README 的元数据 / 抓取 / 单书详情三处
  措辞与 `metafetch` / `metastore` 的模块 docstring 同步更新。
- **第 18 期 · 刮削出版**（本项目**独有扩展**，按既有口径不在此展开 —— 见 README 的
  「刮削出版：给外部阅读器的第二份真相」小节）：扫描 → 抓元数据 → 在**该库的成品目录**用硬链接
  出版一份给外部阅读器读的副本，并在「转换日志 → 刮削」子标签里给出台账与人工处置。
  两条命门：**硬链接副本禁止原地写**（共享 inode，必须原子替换）、**只写与 OPF 原值不同的字段**
  （无元数据可写的副本保持纯硬链接、零额外占盘）。
- **第 19 期 · 写文件的最后两处收敛**：`series_meta.renumber_apply`（重排册号）与
  `fileops.apply_rename`（批量改名）改为写 `meta_override`、不再改写 EPUB；为此引入**显式无值哨兵**
  `db.META_CLEAR`（覆盖值是列、存不了空串，而「清空序号」是有意义的语义）。至此
  **`publish.py` 是唯一还会写文件的地方**（写副本，且走「临时文件 + 原子替换」）。
- **T5 文档同步（本文件）**：上面三段即补记。README 侧对应内容在当时的 18 / 19 期已同步
  （建库三页签与每库自动化、元数据只存服务端），此处不重复。

#### 第 20 期实施记录（Komga 反向查询封口 + 删 9 个「永久不做」页 + 差异清理）

**主题**：把 Komga 客户端面彻底封口，并清理三类已经明确「不再做」与三项「对标差异」。

- **Komga 反向查询封口**（官方规格已查证）：
  `GET /api/v1/series/{seriesId}/collections`（*List series' collections*）—— 走第 16 期映射的
  **真实收藏夹**，逐夹判「成员书里是否有属于该系列的书」；系列不存在 → 404。
  `GET /api/v1/books/{bookId}/readlists`（*List book's readlists*）—— 本项目没有阅读清单概念，
  **诚实返回空分页**；书不存在 → 404。两个都沿用既有分页壳。
- **删除 9 个「已决策不做」的 placeholder 设置页**（用户 2026-09-19 拍板）：
  `kobo`、`email`、`appearance/language`、`account/privacy`、`account/restrictions`、
  `admin/users`、`admin/account-activity`、`admin/magic-links`、`admin/oidc`。
  设置页 **47 → 38**；这 9 条经实测**只出现在 `settingsNav.ts`**（无组件 / 路由注册 / `PAGE_FEATURE` /
  能力键引用），所以删除只动一处 + 计数文案；`docs/bookorbit-*` 的上游采集记录**保留**作对照。
  统一记为「已决策不做（永久排除）」。
  ⚠️ **第 27 期复核（2026-09-19）**：这里的「47 → 38」是**当次删除的增量**，**不是当前页数** ——
  本轮复核时设置页为 **48 页**（41 上游 + 7 本项目补充），其中 **15 页为只读占位页**
  （`admin/requests` 等已决策不做的页后来重新以占位页承载）。真值源是
  `frontend/src/data/settingsNav.ts` + `tests/test_settings_nav_contract.py`（`:42-54` 的
  `EXPECTED_PLACEHOLDERS` 双向断言、`:96` 的总数断言），**改动页数时以该测试为准**。
  本文不改写上面的历史快照，只追加本节说明。
- **三项对标差异**：
  ① **命名 token 5 → 9**（`{series_index} {year} {publisher} {language}`）：只加 `library.books()`
  里**真实存在**的字段，取不到给空串；⚠️ 替换必须**先长后短**（`{series_index}` 在 `{series}` /
  `{index}` 之前），否则会被短 token 抢先吃掉一半 —— 已加回归断言。
  ② **漫画书脊**：`coverPrefs` 新增 `spineComics`（默认 true = 与之前观感完全一致），
  `BookCover` 只在漫画（CBZ / CBR）且关掉时不给 `data-cover-spine`。
  ③ **详情页封面取色**：新增 `lib/coverTint.ts`（canvas 采样 → 两个色相），
  接上照搬来却一直没接线的 `.book-detail-cover-tint`；**取不到就不设变量** → CSS 那条 `hsl()`
  整条失效 → 不染色，天然回退。
- **测试**：新增 `tests/test_naming_tokens.py`（5 例：真实值 / 先长后短不被抢先 / 缺字段空串 /
  `fields` 与后端一致 / 扩展后仍拒路径分隔符）+ `tests/test_komga_client.py` 追加 2 例
  （系列反向查收藏夹含「不在夹里 = 空分页」与 404；书籍查清单恒空 + 404）。全量 **255 passed**。

#### 第 21 期实施记录（元数据抓取扩到非 EPUB）

**主题**：把在线元数据抓取从「只支持 EPUB」扩到 PDF / 漫画 / 有声书。规划阶段实测发现整条链路
**早已就位**，本期实际只需拆掉两处过期判定 + 放开能力矩阵：

- **写入侧已就位**：`metafetch.apply()` 早已只写服务端 DB（`db.set_online` / `db.set_cover`），不碰 OPF。
- **展示侧已就位**：`library.books()` 已批量合并 DB 侧元数据与封面（`db.get_effective_meta` + `db.cover_ids`）
  → 书架 / 详情 / 搜索 / Komga / OPDS **自动可见**。所以「书架要不要展示、要不要付性能代价」这个选项前提
  **根本不存在**（详见本期计划记录）。
- **封面侧已就位**：封面路由优先下发 DB 缓存封面，无则回退文件内嵌图。
- **两处过期判定（本期拆掉的）**：
  ① `metafetch.plan()` 的 `format != "EPUB"` 跳过分支（理由写的是「没有可写的 OPF」，前提已失效）；
  ② `metafetch.apply()` 的 `.epub` 后缀闸门 —— 以及它上面用 `path.is_file()` 判存在，
  **有声书是目录型条目**，会被直接判「文件不存在」。改为只保留 `safe_path` 的**安全边界**
  （确实在该书所属库根下）+ `path.exists()`；结果本来只写 DB，与文件类型无关。
- **能力矩阵**：`features.FEATURES_BY_TYPE` 给 `comic` 与 `audiobook` 授予 `metadata`
  （`authors` 仍只给 ebook / mixed，它与作者检索绑定）。`ALL_FEATURES` 是并集、`metadata` 本就在其中 →
  **能力总数不变（17）**，前端 6 个元数据设置页在漫画 / 有声书库也出现，`metadata_fetch.*` 覆盖项同样可用。
- **边界未动**：**手动编辑元数据仍限 EPUB**（`server.py` 的 `editable` 与 400，非 EPUB 缺 OPF 兜底原值层，
  「恢复原值」无从取）—— 本期只动「在线抓取」这条路径。
- **前端文案**：`MetadataEditor` 改准原因（缺的是 OPF 兜底层，不是「不能写文件」）、`settingsNav` 的
  `PAGE_FEATURE` 注释、`api.ts` 两处注释、`MetadataPage` 的「有缺口」不再只算 EPUB + 两处「写入 EPUB」措辞。
- **测试**：新增 `tests/test_metafetch_formats.py`（5 例：漫画 / 有声书目录不再被跳过、apply 两类都能落库
  且书架可见、越界名仍被 `safe_path` 拦、全局关闭时不下发候选）；同步 4 处既有断言
  （`test_features` 2 处、`test_api_smoke` 1 处、`test_metadata_server_side` 1 处、
  `test_library_settings` 2 处 —— 后两处此前断言「漫画库不暴露 / 拒绝元数据覆盖」）。
  **全程 mock 检索、绝不外呼**。全量 **260 passed**。

#### 第 22 期实施记录（收口：非 EPUB 元数据编辑 + Komga 逐库暴露开关 + 注释与文档清理）

**主题**：三块**全部离线可验收**的收口 —— 补齐第 21 期刻意留下的「手动编辑仍限 EPUB」边界、
补齐第 15 期「Komga 可见性只按库类型判定」的不足，并清掉三处存量瑕疵。

- **非 EPUB 元数据编辑**：`GET/POST …/metadata` 与 `…/metadata/revert` 的「仅 EPUB」闸门全部解除
  （原先的理由是「字段的兜底原值来自 OPF」；第 17/19 期把改动改成**只落服务端 DB** 之后这条前提
  已不成立）。非 EPUB 没有 OPF 那一层 → 「恢复」= 撤销覆盖后回落在线的抓取值、没有在线值即为空。
- **「清空」成为真实语义**：`db._CLEARABLE` 由 `("series_index",)` 扩到**全部可编辑字段**
  （与 `fileops.METADATA_FIELDS` / `db._META_FIELDS` 三者同集合，有测试钉住）。接口层
  **`null` = 显式清空**（写哨兵，盖住在线的抓取值 → 之后的抓取也不会把它填回来），
  **空串仍然 = 撤销覆盖**（EPUB 老行为不变）；`_meta_out` 对 `tags` 给空列表、其余给空串，
  三处翻译点（`db.get_effective_meta` / `metastore.effective` / `metastore.state`）同步。
  前端 `MetadataEditor` 每个字段多一个「清空」动作，与「恢复在线」并列且写明区别。
- **Komga 逐库暴露开关**（`komga.expose`，与第 14 期的 `opds.expose` 同构）：
  `features.SETTING_CAPS` + `lib_settings.ITEMS` + `config.DEFAULTS` + `EDITABLE` 与 `/api/config`
  读侧；`_ko_visible_libraries()` 改为「库类型具备能力」**且**「每库覆写 ?? 全局」
  （默认 True = 全部暴露 = 与加开关之前一致）。**不可见与不存在同待遇**：新增
  `_ko_book()` / `_ko_find_series()`，单本 / 单系列 / 进度写入在不可见的库里一律 404
  （否则开关只是把书从列表里藏起来）。有声书库仍由能力矩阵排除，开关是叠加的第二层。
- **清理三项**：① `CoverPage` 两处过期文案（「元数据抓取只覆盖 EPUB」已随第 21 期过期、
  「本项目无漫画支持」与事实不符）；② **注释期号撞车** —— 本会话第 20 期的工作（命名 token /
  Komga 反向查询封口 / 漫画书脊 / 详情页取色 / 删 9 个对照页）此前被标成「第 17 期」，
  与并行会话的 `第 17 期 T2/T3` 撞号，已统一改为第 20 期；③ **T5 文档同步**（上方的第 17–19 期
  补记 + 修掉已过期的「编号说明」）。
- **测试**：新增 5 例（非 EPUB 编辑 + 显式清空盖住在线值 / 清空题材在批量热路径返回空列表 /
  哨兵字段清单与可编辑字段同集合 / EPUB 空串仍是撤销覆盖 / Komga 逐库关闭后列表与直连一并不可见），
  并把「非 EPUB 一律 400」的旧断言改为「非 EPUB 也能编辑」。全量 **265 passed**（连跑三轮稳定）。
- **顺带修掉两个让全量 pytest 失去可验证性的测试基础设施问题**：
  ① `watcher.auto_fetch_async` / `enqueue_scrape_async` 派生的**旁路线程**此前无人登记，
  用例收尾关库之后它们才去查库 → 全量跑到后半程**解释器 segfault**（连汇总行都打不出来）；
  现在线程登记进 `watcher._BG_THREADS` 并提供 `wait_pending()`，`isolated` 夹具在 `db.close()`
  **之前**等它们收干净（与既有「测试不养后台轮询」同一条纪律）。
  ② `test_scrape_publish` 的「扫描后自动入队」断言要求状态仍是 `pending/running`，而单线程 worker
  可能已经刮完 → 改为允许 `ok`（「入队」这件事本身由 `scrape_queued == 1` 钉住）。
- ~~**本次发现、但未改（留给以后）**：`watcher.auto_fetch_async` 仍按 `.epub` 后缀提前 return，
  因此**入库自动抓取**对漫画 / 有声书仍不触发。~~
  **第 28 期改判：已实现，非缺口**（连带项核验时发现原文已过期）。`core/watcher.py:88-92` 的
  允许清单早已放宽为 `.epub/.mobi/.azw3/.pdf/.fb2/*comics.COMIC_EXTS`，并有 `kind="audiobook"`
  分支（`core/watcher.py:430,436`，目录型条目名字无后缀、按 `kind` 显式放行）；
  `tests/test_watcher_auto_fetch.py` 已钉住漫画与有声书两例。双重门控（`metadata_fetch.enabled`
  且 `auto_on_import`）不变，默认仍是不联网。「入库即外呼」的取舍**已经定过**，只是没写进本文件。

#### 第 23 期实施记录（对标差异清理，纯前端 + 文档）

**主题**：上游对照页与已实现能力之间最后几处「说了但没落」的差异清理，**零后端改动**。

- **维护页**：ACHIEVEMENTS 重算接后端既有 `POST /api/achievements/backfill`；IMPORT / RECOMMENDATIONS /
  UPDATES 在容器口径下明确未支持（`SettingsUnsupportedCard`）。`api.ts` 的 `AchievementsOverview`
  补 `backfilled?`。
- **阅读器排版口径更正**：`ReaderEbookPage.vue` **实际已实现 13 项**（阅读模式 / 13 档主题 / 字体 /
  字号 / 行高 / 内容宽度 / 段落间距 / 首行缩进 / 字距 / 词距 / 分栏 / 两端对齐 / 断词），而
  `settingsNav` 的 `reader/ebook` note 仍写「仅字体 / 主题 / 字号 / 行高 / 内容宽度」——已按实况改为
  13 项 + 4 未支持。这类「代码已做、口径没跟上」正是本文件后面反复出现的漂移模式。
- **5 个 placeholder 页**（`appearance/icons`、`appearance/layout`、`appearance/behavior`、
  `koreader-upstream`、`libraries`）全部补 note「留作上游对照」，**未删任何导航项**（无重复入口）。
- **文档同步**：`roadmap-verification.md` 未支持表补阅读器排版 / 维护页 / 外观占位；
  `settings-inventory.md:763` 修正「均缺」断言；`capability-gap.md` 两条 Achievements 标「第 22 期已实现」。

#### 第 24 期实施记录（入库自动抓取放开到漫画 / 有声书）

**主题**：兑现第 22 期留的待办 —— `watcher.auto_fetch_async` 的「无 OPF 可写」早退理由自第 22 期起
已失效，但它仍按 `.epub` 后缀提前 return。

- `auto_fetch_async(name, cfg, kind=None)`：guard 改 **allow-list**（epub/mobi/awz3/pdf/fb2/cbz/cbr，
  复用 `comics.COMIC_EXTS`），并加 `kind="audiobook"` 显式放行（目录型条目名字无后缀）。
- **有声书目录分支**（`watcher.py` 的 `p.is_dir()`）此前**根本没调**这两个异步入口，补上
  `auto_fetch_async(rel, cfg, kind="audiobook")` 与 `enqueue_scrape_async(rel, lib, cfg)`。
- **双重门控不变**：`metadata_fetch.enabled` 且 `auto_on_import`，默认仍是不联网。
- 测试：新增 `tests/test_watcher_auto_fetch.py` 5 例（allow-list + kind 单元、门控、漫画库扫描触发、
  有声书库扫描触发、关闭不触发），全部 mock 外呼、断言名字抵达 `metafetch.auto_fetch`。
- 验收：全量 **270 passed / exit 0**（基线 265 + 5）。`MEMORY.md` 对应待办移除。

#### 第 25 期实施记录（Profile 补全：头像 / 显示名 / 时区 / 引导重放）

**主题**：YOU→Profile 是设置区最后一块**真缺口**（其余「阅读器五页」「Metadata 7 子页」复核后
发现早已 ready，是 inventory 文档滞后造成的假缺口 —— 后续规划改以 `settingsNav.ts` 为准）。

- **后端**：`users` 表加 `display_name` / `timezone` / `avatar_path`（**PRAGMA 守卫 ALTER** 迁移，
  不碰 `CREATE TABLE`）；`get_user_profile` / `update_user_profile` / `set_user_avatar` /
  `clear_user_avatar`；`hour_histogram()` 按账号时区（ZoneInfo，失败回落服务器本地时）归一 →
  接通 Early Bird / All-nighter 等时间类成就。
- **接口**：`GET/PUT /api/account/profile`、`POST/DELETE/GET /api/account/avatar`（复用 `_read_capped`，
  5MB、JPG/PNG/WEBP 白名单，落 `CACHE_DIR/user/avatar.<ext>`，**零外链**分发）；头像分发加入
  `_MEDIA_TOKEN_PATHS` 允许 `<img src>` 带 `?token=`。
- **前端**：`stores/auth.ts` 扩 `displayName` / `timezone` / `avatarUrl` + `display` getter；
  `ProfilePage.vue` 账号卡加头像上传 / 移除、显示名、时区（IANA 全量下拉）+「新手引导」卡；
  新建 `components/settings/GuidedTourModal.vue`（3 步浮层）；`UserMenu.vue` 顶栏优先显示头像 + 显示名。
- **验证**：头像 HTTP e2e 7 项全过（上传 / 带 token 分发 / profile 回显 / 移除 / 移除后 404 /
  非图片 400 / 空文件 400）；按能力拆 3 commit 推送。

#### 第 26 期实施记录（设置区对齐收尾：41 页逐页有落点 + 搜索 + 脏状态）

**主题**：在既有 `/settings` 嵌套路由骨架上补齐与对齐，**后端零改动、不新增前端依赖**。

- `settingsNav.ts` **38 → 48 页**：新增 10 个 `placeholder` 页（`appearance/language`、
  `account/privacy`、`account/restrictions`、`kobo`、`email`、`admin/users`、`admin/account-activity`、
  `admin/magic-links`、`admin/oidc`、`admin/requests`），每页带 `upstream`（标题 / 说明 / 页内分组 /
  条目）+ 中文 `note`；`SettingsPageDef` 增 `own?: boolean`，`komga` 与 `koreader-upstream` 标
  `own: true`（界面显示「本项目补充」徽标）。**7 页本项目补充 + 41 页上游落点 = 48**。
- **设置搜索**：新增 `composables/useSettingsSearch.ts` + `components/settings/SettingsSearchPanel.vue`
  （索引从 `SETTINGS_GROUPS` 派生：页面级 rank0 + `upstream.items` rank1；多词 AND、↑↓/↵/Esc、
  限高滚动 + `scrollIntoView`）。`App.vue` 的 ⌘K 在 `/settings` 下**让位**给设置面板。
- **脏状态双通道**：`useSettingsConfig` 按 `SECTION_KEYS` 分组比基线出 `dirtySections` / `hasDirty` /
  `discardDirty`（既有返回值不变，12 个使用方无感）；新增 `composables/useSettingsDirty.ts` 注册表，
  供自带局部 `dirty` 的页上报。`SettingsLayout.vue` 合并两源渲染「有未保存的改动 + 放弃更改」。
- 测试：`tests/test_settings_nav_contract.py` **9 项**，纯文本解析 `settingsNav.ts` / `router/index.ts`
  （48 页、path/name 唯一、上游 41 标题齐全、`ready` 与组件映射一致、own 集合、别名存在）——
  **不依赖 DB / 夹具，win32 稳定通过**。
- 踩坑：`note` 字符串里的 `**` 会被原样渲染（Vue 模板不解析 markdown，静态文本要用 `<strong>`）；
  本机构建需先把 `CODEBUDDY_NODE_BIN` 与 PATH 指向 `C:\Users\qingr\nodejs\` 的真实 Node。

#### 第 27 期实施记录（批注域补齐 + 文档漂移清理）

**主题**：复核后确认批注域是当时唯一成体系的真实功能缺口（现状只有一张平铺列表 + **硬删除**）。

- **数据模型**：`annotations` 补 `origin TEXT NOT NULL DEFAULT 'web'` 与
  `deleted_at REAL NOT NULL DEFAULT 0`（同一段 PRAGMA 守卫 ALTER 迁移块）；存量行语义完全不变。
- **软删除**：`delete_annotation` 由硬 `DELETE` 改**写 `deleted_at`**；新增 `restore_annotation`、
  `purge_annotation`（真删，**要求 `deleted_at != 0`**，活跃条目拒绝）、`trashed_annotations`。
  三处读点加 `WHERE deleted_at = 0`：`list_annotations` / `all_annotations` / `annotation_counts`。
- **统计**：`_week_index(ts)`（`monday.toordinal() // 7` —— ⚠️ **不能用 `year*53+week`**，跨年算错）
  与 `annotation_overview()` → `{active, trashed, weeks, longest_quiet_weeks}`。
- **级联真 bug 修复**：`remap_book_id` 的探测 `SELECT 1 FROM <t> WHERE book_id=?` 在软删除下会把
  「新 id 只有垃圾桶批注」误判成「已有数据」→ 跳过搬迁 → **旧 id 的活跃批注被静默搁浅**。修法：
  `REMAP_PROBE_FILTER = {"annotations": " AND deleted_at=0"}`，**只改探测、`UPDATE` 仍搬全部行**；
  `book_id_refs` **故意不加过滤**（孤儿判据与垃圾桶状态无关）。
- **接口**：`GET /api/annotations` 扩 `include_trashed`（**无参行为与改动前完全一致**）；新增
  `GET /api/annotations/overview`、`POST .../{aid}/restore`、`DELETE .../{aid}/purge`。
- **前端**：新建 `data/annotationColors.ts`（应用侧 10 色单一权威表）**归并 4 处各自为政的颜色表**；
  `AnnotationsView.vue` 重写为「活跃 / 垃圾桶」双视图 + 月 / 书 / 颜色 / 来源四档**前端**分组 +
  顶部统计条；`api.request()` 加 `expectStatus`（只压制 `console.error`，不动 401 分支）。
- **测试**：`tests/test_annotations.py` **12 项**。含三条钉子：软删除语义与 purge 拒绝活跃条目；
  **3 个下游逐个断言**批注数不变（`/api/stats` 的 `reading.annotations`、`GET /api/books[]`、
  导出 CSV 的「批注数」列 —— 只测 stats 会漏掉后两个）；rename 后旧 id 的**活跃**批注确实被搬走。
- **文档漂移清理**：`capability-gap.md` 逐条按代码核验后改判（§0.3 基线 **68 → 260 路由、
  6 → 28 张表**；§6/§7/§8/§10/§13 多项过期），**不做整表翻转**；并显式记下**三条必须保持原判**的项
  （两大标签分区 / Integrity 百分比 / 「孤儿封面目录」是刻意不同设计）—— 第 29 期正是从这三条开工的。

#### 第 28 期实施记录（重命名并入刮削：副本命名唯一化）

**主题**：用户拍板「批量重命名与刮削合并」。复核后确认这**不是新增能力，是消灭重复** ——
`publish.relpath_for` 早已按该库生效规则派生副本名，`scrape.resolve(bid,"rebuild")` 早已能按当前
规则重生成副本并把旧副本移入回收。真正的缺陷是**「同一份保存的规则有两套解释」**。

- **命名展开唯一化**（`9a0f126`）：`fileops.fill_pattern(pattern, book, ext, seq)` 收全部 9 个占位符、
  **先长后短**替换（`{series_index}` 必须排 `{series}` / `{index}` 之前）；`publish.fill_pattern` /
  `_index_text` **删除**，`relpath_for` 改调。此前 publish 只认 5 个占位符 ⇒ 预览（走 fileops）与
  落盘（走 publish）不一致，`{series_index}` 会被**字面写进文件名**。
- **接口**：新增 `POST /api/naming/preview`、`POST /api/naming/apply`；**删** `/api/rename/preview`、
  `/api/rename/apply` 与 `fileops.plan_pattern_rename`；删 `views/tools/BulkRenameView.vue`、路由
  `/tools/rename`、`ToolsLayout` 导航项（**工具页签 9 → 8**）。
- **冲突不静默**：把 `publish._free_rel` 的占用判断抽成只读可复用的 `publish.rel_verdict`
  （`REL_REUSE` / `REL_REBUILD` / `REL_DECLINE`），**预览与落盘共用同一判据**；预览标 `conflict`
  （`occupied` / `dup`）并**从批量里排除**，不让 `(2)` 兜底悄悄改掉预览结论。
- **实体改名纯元数据化**（`2b4fe03`、`1cff287`）：`apply_rename` / `_meta_override_for` /
  `_owning_library_id` **整函数删除**，新增只写 `db.set_override` 的 `apply_entity_rename`；
  `/api/entities/rename/apply` 契约改为 `{type, from, to, library_id?}`，**改哪些书由服务端按 `from`
  自算**（客户端指定的 items 一律无效）。顺带消灭「老 `apply_rename` 改 basename 却不调
  `db.remap_book_id` ⇒ 进度 / 批注搁浅在旧 id」这一已报缺陷 —— **不是打补丁，是把整条路径删掉**。
  仍改 basename 的只剩 `apply_conflict_rename` / `apply_komga_layout`，二者都成对调用 `remap_book_id`。
- **前端**：`ScrapePanel.vue` 新增「命名规则」区块（选定某库可改该库覆写；「全部书库」时只读并指向
  设置页 —— **全局规则只有一处能写**）；有未保存草稿时禁用重出版按钮（否则「预览按草稿、落盘按
  保存值」正是要消灭的不一致）。
- **测试**：`tests/test_naming_publish.py` 新增 14 例 + `test_rename_server_side.py` 重写，**30 passed**。
  钉住预览 == 落盘（逐字）、源文件指纹分毫不动、`book_id` 不变、**不外呼**（打开在线抓取并
  monkeypatch `metafetch.auto_fetch` 使其抛异常，整批仍成功）、旧接口 **404**（method + path 一起断言）。
- **e2e**（真 uvicorn + 真文件）：建库 → 扫描 → 出版 → 改规则 → 预览 → 重出版全程；源文件
  `(inode, 大小, mtime_ns, sha256)` 完全未变；旧副本两次进回收；`/api/rename/*` 实测 404。

#### 第 29 期实施记录（缺口清单核验到底 + 统计域收口 + 有声书出版）

**主题**：用户选定「核验到底 + 落地一批」。核验结果与「落地域」勾选**冲突并如实纠正** ——
勾选的「书籍详情补全」「书架与列表剩余项」经代码实测**早已全部实现**，其「缺」只存在于文档里；
根因正是本期要治的事：`capability-gap.md` 的 §1/§2/§3/§4/§11 **从来没有复核头**，内容停在
第 4 期时代，而第 27 / 28 期已两次证明**人工校正不持有**。故本期 = 把核验做完并写回文档（止血），
再加上统计域真缺口落地与有声书出版。

- **文档核验到底**（`d1a7ed5`、`fdc5353`）：§1–§12 全表逐条按代码核验改判，**补上 §1/§2/§3/§4/§11
  缺失的复核头**；本轮确认 **23 行过期**（PDF 阅读器、漫画阅读器、书架折叠 / 排序 / 导出、系列序号
  字段、编辑元数据、查重阈值、缺失资源 orphans、全局搜索…），自评「缺口」里真正站得住的只剩 5 条。
  **每行改判都附 `文件:行` 锚点**（抽查 30+ 处全部命中），§0.3 基线重取实测值并补 `activity_log`。
  另给三份停在旧期的文档加 ⏳ 时效标注（`roadmap-verification.md` 止于第 4 期、
  `settings-inventory.md` / `feature-flows.md` 止于 2026-09-19 上游快照）。
- **统计域三项**（`88e1e9f`、`295f120`、`3ad6725`）：`integrity` 在原有 5 个计数键**之外**增补百分比
  口径（按上游 `LibraryIntegrityGauge`）；`overview` 新增 `largest: [{id, title, size_bytes, format}]`
  体积榜（按上游 `LargestBookItem`，长度受既有 `top` 控制且**不塞进 `_top`**，0 字节书如实上榜）；
  前端 `StatsView.vue` 由一串平铺 `<h3>` 改为 **Library Stats / My Reading 两分区**、书库体检改
  百分比展示、新增 Top 50 体积榜。
- **有声书出版（目录型条目）**：出版链路原先用 `if not src.is_file()` 一票否决 ⇒ 一章一文件的
  有声书永远不出版。本次把条目形态判据从「读磁盘的 `is_dir`」换成「**条目名带不带书库认识的
  扩展名**」，与入库侧（`komga.relpath_for_dir`）同判据、同落点。副本：`link_tree_or_copy` 逐文件
  硬链接（回退逐文件 `copy2`），是**真目录**而非符号链接；指纹：`source_sig` 对目录产出**整树指纹**
  （相对路径 + 大小 + mtime —— 目录自身 mtime 看不出内部改动，而章序就是文件名顺序，改名同样算
  源变更）；副本名**不带扩展名**；名字与磁盘形态不一致时**跳过出版**而不产出错名。
- **顺带修一处既有缺陷**（`fafe999`）：`fileops.fill_pattern` 展开 `{ext}` 已带扩展名，
  `komga.relpath_for` 又拼一次 ⇒ 模式写 `{title}.{ext}` 落成 `书名.m4b.m4b`（设置页把 `{ext}` 列为
  可选占位符，用户照着填就撞上）。只在模式**以 `{ext}` 收尾**时摘掉尾部扩展名（零误判），
  `{ext}` 出现在别处一律不动。第 29 期端到端验证时发现，**非本轮引入**。
- **测试**：新增 `tests/test_audiobook_publish.py` **14 例**（源目录只读 / 逐文件同 inode / 整树指纹
  逮住「改一轨内容」与「互换章序」/ 指纹与链接共用同一份文件清单 / 目录条目不落扩展名 /
  scope 非 all 时不动 / 名字与磁盘形态不一致时跳过 / 旧副本进回收不留双份 / 落点被占时退让不覆盖 /
  重出版不外呼 / 副本目录走回收而非 unlink / 入库与出版同落点）；`test_naming_publish.py` 加
  `{ext}` 回归。全量回归与基线一致，只余既有 win32 flaky 两例。
- **e2e**（真 uvicorn，端口 8799）：建 audiobook 库 → 扫描 → 出版成**真目录** → 逐文件同 inode →
  改命名规则使预览 == 落盘 → 旧副本目录进回收 → 改名后逐文件仍同 inode 且源指纹分毫未动 →
  落点被别人的目录占着时预览标 `occupied`、apply 只跳过那一本、别人的目录原样不动。
  ⚠️ 踩坑：默认命名规则是 `{author} - {title}`（**不是空**），脚本第一版按「原样出版」写，
  于是「改名」根本没改到目录条目、断言假失败。

---

#### 第 30 期实施记录（残留清账 + 统计按库筛选 + 外壳小项 + 版本同源 + 上游取证）

**主题**：用户拍板「梳理下一期」，范围经多选确认为**残留缺口清账 + 统计按库筛选 + 上游取证与基线校准**；
成就体系对齐上游本轮**明确不做**。版本标识口径：**后端为权威**（前端不再手写版本号）。

- **统计按库筛选**：`GET /api/stats`（`server.py:3232-3236`）增 `library_id: str = Query("")`；
  `core/stats.py` 的 `overview(days, top, library_id="")` 据此取书（沿用既有 `library.by_library` 缓存，
  `invalidate(library_id)` 不新增扫描）；**空串 = 全库**，不传参输出与改动前逐字节一致 → 既有测试
  与 8 个仪表盘部件零影响。`stores/stats.ts` 带上当前库并在切库后失效重载；`views/StatsView.vue`
  加「统计范围」选择器（默认跟随当前库）。
- **本地转换放开多格式**（含两条既有 bug）：`LocalConvertView.vue` 的 `accept` 与文案跟随后端允许集
  （`.txt` ∪ `pipeline.EBOOK_EXT` ∪ `audio.AUDIO_EXTS`），拖拽/选择做扩展名**前端预校验**；下载名
  改为读响应头 `Content-Disposition`（`api.ts` 的 `requestBlob` 现在返回 `{blob, filename}`，兼容
  `filename*=UTF-8''` 与裸 `filename=`），根除「x.epub.epub」；`/convert-path` 与 `/convert` 同口径
  改为返回 `FileResponse`（后端给真实文件名），不新增第二套展开名逻辑。
- **书籍详情补全**：`BookDetailView.vue` 版本信息区新增归属库（`library_id` → `libraryEntities` 名）、
  入库日期（与导出 CSV 同源，皆文件 mtime）、页数（非 EPUB 恒 0 不展示，带来源标注 `estimate`/`archive`）；
  删掉写死的「字数：未知」假值行（项目「不做假交互」约定）。
- **阅读记录按书指标**：`core/db.py` 的 `session_by_book()` 在同一句 SQL 补 `avg_seconds`
  （`AVG(seconds)`，不增查询）；前端「按书」卡加**平均单次时长**与**阅读速度（页/小时）**——
  速度需可靠页数（来源为 `estimate`/`archive` 且 `pages>0`）才算并标注，否则不显示，不造假。
- **外壳小项**：① 侧栏新增「帮助」分组（说明书 / 更新日志 / 关于，复用既有三路由，不新建页面）
  （`data/nav.ts` + `components/AppSidebar.vue`）；② 删净 `shelfTag` 死入口（state + 过滤分支 +
  三处清空 + 导出 + 所有调用点，题材筛选已由书架筛选面板承担）；③ 书架页加库级控制最小集
  （切库 / 立即扫描 / 书库管理），重命名删除仍只在 `/tools/libraries`，避免第二处写入口。
- **版本标识同源（后端为权威）**：收敛单一常量 `APP_VERSION = "0.6.0"`（`server.py:113`），
  `FastAPI(version=APP_VERSION)` 与 `GET /health` 的 `version` 同读它；前端 `HealthInfo` 加 `version`，
  About 页与更新日志页渲染后端下发版本，`data/whatsNew.ts` 的 `version` 字段删除（不再手写版本号）；
  新增契约测试钉住「展示版本 == 后端常量」。
- **上游取证与文档校准**：对上游镜像做符号级取证（本环境无终端/网络，`client/` 与 `server/src/modules`
  未能 fetch，降级为对 `packages/types` 补扫）。结论：缺失资源 `sweep` = `CoverSweep`（封面修复维护扫描，
  详见 `packages/types/src/maintenance.ts`），本项目缺失资源概念不同（指向已消失书籍的 DB 行），且
  客户端 UI 未取证 → **sweep 不做**；EDITIONS「版本编号」实为外部 Hardcover/Storygraph 的 `edition`
  （`hardcoverEditionId`），**非自有顺序版本号**，本项目无该集成 → 不引入；通知 `Clear` 语义在
  `notification.ts` 未取证（模型仅 `read`/`count`），且清空日志入口已在 Watcher/Logs 页存在 → **不做**；
  成就 `dedication`/`devices` 分组标题确证（`packages/types/src/achievement.ts:1,9-10`），本项目成就未逐项对齐；
  求书表格核心列确证为 `createdAt/title/mediaKind/requester/status`（`packages/types/src/book-request.ts:534`），两页
  Mine/All 范围由 `mine`/`allTotal` 区分，本项目无 Requests 功能。
  `docs/bookorbit-capability-gap.md` 逐行改判（§1/§2/§3/§6/§7/§8/§11 等多行附 `文件:行`），并标注
  上述「未取证 → 不做」项；三份停旧期文档（roadmap-verification / settings-inventory / feature-flows）
  已在第 29 期加 ⏳ 时效标注，本期不整表翻转，以 capability-gap.md 为权威。

#### 第 30 期验证

- 后端 py_compile 已过；前端 `vue-tsc` 待用户在原环境跑（本会话命令授权超时，未能在本环境编译）。
  **〔第 31 期补记〕** 命令通道恢复后已跑完：`npm run type-check` / `build` / `deploy` 全部通过，
  产物同步 `novelforge/static/v2`。
- 新增契约测试：`tests/test_version_contract.py`（`GET /health` 的 `version` 非空且 == `server.APP_VERSION`）、
  `tests/test_stats_scope.py`（`/api/stats` 不传=全库 / 传库=只算该库 / 不存在的库=全库空集合）。
- 待运行：全量 pytest、构建部署、playwright 逐路由冒烟（统计库选择器 / 本地转换非 txt 文件名 /
  详情页新字段不出现 0/假值 / 阅读记录按书卡）。
  **〔第 31 期补记〕** 以上已全部执行，结论并入下方「第 31 期验证」。

---

#### 第 31 期实施记录（上游取证补记 + 阅读活动页 + 成就对齐 + 三份停旧期文档刷新）

**主题**：用户多选确认为全部四项 —— 上游取证补全 / 笔记子系统（时间轴 + 热力图）/ 成就体系对齐上游 /
文档过期清理。

- **阅读活动（本期唯一新增 UI）**：后端新增 `core/activity.py` —— `heatmap()` 按 `started_at` 的**本地日**
  聚合 `seconds/60` 成 `{date, minutes, sessions}`、`timeline()` 合并 session / annotation / achievement
  按 ts 倒序、`reading_activity()` 一次返回；`core/db.py` 增 `reading_day_minutes` / `session_feed` /
  `annotation_feed`（读批注**必须** `deleted_at=0`；空集合直接返回 `[]`，避免 `IN ()` 语法错）/
  `list_achievements` / `unlocked_map` / `upsert_achievement` / `clear_unlocked`。
  接口 `GET /api/reading-activity`（`server.py:3248`）：`library_id` **空串 = 全部书库**（与 `/api/stats`
  同惯例），**未知库返回空集合不 404**；`year` 过滤热力图年份、`limit` 限时间轴条数；按库过滤复用
  `library.books(lid)` 取 id 集合（同 `core/stats.py` 范式，**不新增扫描**）。
  前端 `stores/activity.ts`（跟随 `library.currentLibraryId` 失效重载）+ `views/ReadingActivityView.vue`
  （GitHub 式**纯 CSS Grid** 53×7 热力图、5 档色阶、hover 放大 + `title` 提示、时间轴按日分组 + 类型图标 +
  `HH:MM`、范围选择「今年 / 去年 / 全部」、空态如实显示「还没有阅读记录」）；接线在 `router/index.ts:180`、
  `data/nav.ts:45`、`AppSidebar.vue:34/58`、`lib/api.ts`。**零假数据、零外链、无 `Math.random()`**（确定性）。
- **成就对齐上游**：`core/achievements.py` 由 3 组（LIBRARY / READING / ANNOTATION）改为上游的 4 组
  （library / reading / exploration，批注归入 exploration）+ 新增 `dedication` 档（`streak_100` /
  `hours_500` / `active_days_100` / `finished_50`），共 21 条；`devices` **不引入**（本项目无 `source` 列）。
  `_metrics()` **未新增指标**（dedication 复用既有 streak / hours / days / finished）⇒ 判定逻辑零改动，
  「只解锁不回退、进度实时算」机制不变。前端 `AchievementsView.vue` 的 `GROUP_LABELS` 补 `dedication/坚持`。
- **上游取证（降级，如实标注）**：本环境当时**仍无终端 / 网络**，`client/` 与 `server/src/modules`
  第二次 fetch 失败（同第 30 期），取证范围限镜像 `%TEMP%\bookorbit-ref` 的 `packages/types` + 各根文档，
  结论附 `文件:行` 写回 `capability-gap.md` §1/§6/§7 的「第 31 期取证补记」，**未取证部分一律标「未取证」
  不臆测**：`achievement.ts` 5 分类（reading / library / exploration / dedication / devices）+ 4 档稀有度；
  `reading-session.ts` 热力图真值源是 `dailySummary{day,totalMinutes}[]`，`READING_SESSION_SOURCES`
  分桶 web / koreader / manual / kobo（本项目无 `source` 列 ⇒ 不做分设备热力图，**刻意分流**）；
  ⚠️ `account-activity.ts` 是**管理端账号活跃度**（admin 用户列表），与阅读时间轴**不相干**（易混点，
  勿拿它当依据）；`notification.ts` 有 30 种 `NotificationType` / 11 个 `NotificationCategory`，
  但**本项目无通知产生端** ⇒ 「清空通知」仍不做（第 30 期判定的取证补强，**非翻转**）；
  `maintenance.ts` 的 `sweep` = `CoverSweep` 封面修复维护扫描，与「孤儿记录」概念不同 ⇒ 仍不做；
  `hardcover.ts` 的 EDITIONS 属外部 Hardcover `edition` ⇒ 第 30 期结论获证。
- **文档刷新（不整表翻转）**：三份停旧期文档去 ⏳ 改「**时效说明（第 31 期复核，2026-09-20）**」头，
  一律指向 `capability-gap.md` 为权威 —— `roadmap-verification.md:3-7`（明写正文是 2026-09-17 的 0–4 期快照，
  保留价值在「当时怎么证的」）、`bookorbit-settings-inventory.md:12-15`、`bookorbit-feature-flows.md:10-13`；
  `capability-gap.md` §6 新增「阅读活动（时间轴 + 热力图）」行、§7 通知 Clear 取证补强、
  §1 全局搜索 / 收藏等锚点更新。
- **修一条第 30 期遗留真 bug**：`tests/test_version_contract.py` 打的是 `/api/health`，而路由是 `/health`
  （`server.py:248`；白名单 `server.py:160` 只有 `/health` + `/api/auth/login` + `/api/logout`；
  前端 `lib/api.ts:1793` 也走 `/health`）⇒ 401。全仓 `/api/health` **仅此一处**，改为 `/health` 后通过。
  根因：第 30 期本机跑不了测试，错误路径一直没暴露。
- **顺带修 TypeScript 报错**：`BookDetailView.vue` 重复 `fmtDate` 触发 TS2393（第 30 期 `bf6a8ab` 引入，
  非本期）；新版改名 `fmtDateSlash`。

#### 第 31 期验证

- **全量 pytest：346 例 / 1 failed**。唯一失败 = `test_watcher_auto_fetch::test_audiobook_library_scan_triggers_auto_fetch`
  （既有 win32 不通，单跑也挂）→ **与基线一致，非本期回归**。另 `test_scrape_publish::test_接口_扫描后按开关自动入队`
  本次全量挂、单跑该文件过 → 判定为**顺序依赖 flaky**（即早先记忆中「1–2 例扫描→自动入队失败」的真相）。
- 本期新增测试 7 例全绿：`test_reading_activity.py` 3 + `test_achievements_align.py` 4。
- 前端 `type-check` / `build` / `deploy` 成功，产物已同步 `novelforge/static/v2`（含「阅读活动 /
  reading-activity / 阅读热力图 / 时间轴」字符串）。
- **e2e 冒烟（真进程，非 TestClient）**：另起实例 `--port 8795` + 独立临时目录（8791 被旧代码实例占着，
  不打扰它）。`GET /api/reading-activity` 空态结构完整（`heatmap{library_id, year, days, total_minutes,
  active_days}` + `timeline{library_id, events, total}`）；`?year=2025&limit=3` 生效；`?library_id=nope`
  返回空集合**不 404**。playwright 注入 `nf_token` 后打开 `#/reading-activity`：侧栏入口在、热力图 53×7
  全网格（`title` 提示 `YYYY-MM-DD · 0 分钟 / 0 次`）、色阶图例、时间轴空态；**控制台 0 错误**。
  冒烟后停实例、关浏览器、工作区干净。
- **定位失败的关键手法**（已进 MEMORY）：PowerShell 抓不到 pytest 汇总行（落盘也只有进度条）⇒
  改用 `--junitxml` 落盘 + Python 解析 `//testcase[failure]`。此前记忆写的是「核对回归请在用户原环境跑」，
  等于放弃，现已改正。

---

#### 第 32 期实施记录（统计图表补齐 10 张 + 外观两页做实 + 真缺失小项收口）

**主题**：用户拍板三域 —— **统计页图表补齐 + 外观三页做实 + 已知真缺失小项收口**；上游核对深度取
「聚焦高价值缺口」；图表渲染**引入 ECharts**；统计图表**分两批、本期做前 10 张**。
⚠️ 用户勾的是「外观三页」，本轮**主动收窄为两页**（Icons 未做，理由见下），**不假装做了第三页**。

**上游形态取证（本轮突破，任务 1）**：第 30 / 31 期连续两次 fetch 失败的上游 `client/` 与
`server/src/modules`，本轮找到可行路径 —— 镜像 `%TEMP%\bookorbit-ref` 的 **tree 对象本地已有**
（零网络即可 `git ls-tree` 列出上游全部文件清单，此前只看了 `packages/types`，所以旧「缺口清单」
系统性漏掉了模块级能力），读内容则**走代理按需拉单个 blob**
（`git -C $REF -c http.proxy=http://127.0.0.1:7897 cat-file -p HEAD:<path>`）。
据此取到上游统计页完整图表元数据 `client/src/features/statistics/statistics-chart-meta.ts`：
**33 张图**（Library 19 / User 14），本项目原有 11 张 ⇒ 缺约 20 张。
照搬的骨架（全部实拉实读，未取到的不臆测）：`client/src/lib/echarts.ts` —— **单点 `use([...])` 注册**
（SVGRenderer + 12 图型 + 14 组件；注释 `:34-36` 写明选 SVG 而非 Canvas 是为消除 canvas 命中测试
坐标错位导致的 hover 闪烁；调色板 `HUE_OFFSETS` + `oklchToHex()` 手写 OKLCH→sRGB，因主题色是 oklch
变量而 ECharts 不认；`initChartThemes()` 幂等预注册「2 模式 × N 强调色」主题）、`ChartCard.vue`
（图标底色 `oklch(from var(--primary) l c calc(h + N))` + `#controls` 插槽）、`ChartEmptyState.vue`
（图标 `size-9 opacity-20` + 标题 + 描述，居中）、`StatisticsGrid.vue`（`tileClass(size)` 映射栅格跨度 +
`grid-flow-row-dense`）、`useStatisticsConfig.ts`（`config:{id,visible,order}[]` +
`normalizeCharts` 过滤未知 id 并给新图补默认项 + 600ms 防抖持久化）。
**上游的低数据量诚实提示阈值逐图照搬**（`reading-clock`/`peak` `MIN_EVENTS=20`、`favorite-days` `=14`、
`progress-funnel` `MIN_STARTED=10`、`completion-timeline` `MIN_COMPLETIONS=3`），不足阈值走空态文案
「数据不足」，**不画噪声图**。

**三处硬差异（照搬形态、不照搬数据契约）**

1. 本项目**无 `reading_sessions.source` 列、无按格式分桶** ⇒ 上游 `reading-clock` / `peak-reading-hours` /
   `favorite-reading-days` 三图的 `BreakdownSelect`（format / source 维度）**没有数据源** ⇒ **不做该控件**
   （防回归要点「不做假交互」），三图降级为单序列。
2. 本项目是**单接口 `GET /api/stats`**（上游每图一个 composable 一个 API）⇒ 所有图共用一份 `overview`，
   新序列一律**增补新键**，不照搬 per-chart 取数层。
3. 本项目无 `vue-i18n` / shadcn（Sheet / Popover / Dropdown）/ `@lucide/vue` / `@vueuse/core` /
   `vue-draggable-plus` ⇒ 用既有 `Icon.vue` / `Card.vue` / 原生 `<select>`；Configure 的重排**改用
   「上移 / 下移」按钮**（不引入拖拽库），功能等价、**零新依赖**（除 `echarts` + `vue-echarts`）。

**一处口径修正**：原计划写「Page Count Distribution → 加 `pages_hist` 分档直方图」，上游实为
**boxplot 按格式的五数概括**。改按上游形态，新键名 **`pages_by_format`**
（`{format, count, min, q1, median, q3, max}[]`），只含有页数的书（本项目非 EPUB 页数恒 0，自然排除），
tooltip 标注样本数。

**交付明细**

- **后端 · 统计序列**（`43fb435`）：`core/stats.py` 增补 8 条序列、`core/db.py` 配套聚合 ——
  `by_language` / `by_format_size` / `pages_by_format` / `added_monthly` / `publication_yearly` /
  `progress_funnel` / `completion_monthly` / `weekdays`（周几读多久，与 `hours` 同族）。
  **全部跟随 `library_id`**（复用 `core/stats.py:166-169` 的 `ids` 集合，**不新增扫描路径**）；
  **全部是新键**，既有键**一个未删**。新增 `tests/test_stats_charts.py`（295 行）。
- **前端 · 图表基建**（`604ddd9` + `b12bcf9`）：装 `echarts` + `vue-echarts`；`lib/charts.ts` 是**全站唯一**
  的图型注册 / 主题适配入口（按需注册 + 动态 import，跟随 `stores/theme.ts` 深色 / 浅色）；
  `components/charts/` 下 `ChartCard.vue` / `ChartEmptyState.vue` / `ChartFrame.vue`（动态 import +
  空态 / 加载态）+ `ChartGrid.vue`（`tileClass(size)` 映射栅格跨度）；`lib/statistics-charts.ts` 存图表元数据
  （id / label / size / category 与默认顺序，对齐上游常量）、`lib/format.ts` 补格式化工具。
- **前端 · 10 张图**（`7043dd1` 书库侧 5 张 + `f61ab7d` 阅读侧 5 张）：Books Added Over Time（柱 +
  `borderRadius:[3,3,0,0]`）/ Language Distribution（环形饼）/ Storage by Format（环形饼 + `formatBytes`）/
  **Page Count Distribution（boxplot）** / Publication Year Timeline（折线 + 面积 + `dataZoom` +
  markArea「Golden Era」+ markPoint「Peak」+ 5 年均线 + 底部统计卡）/ Reading Clock（极坐标堆叠柱）/
  Peak Reading Hours（直角堆叠柱，y 轴 `{value}m`）/ Progress Funnel（五阶段三模式 percent / counts / dropoff）/
  Completion Timeline（按月折线 + 面积）/ Favorite Reading Days（按星期堆叠柱，y 轴为**平均每日分钟**）。
  每张都有空态与低数据量提示。
- **前端 · 接入 + Configure**（`e4c4540`）：`components/charts/ChartConfigPanel.vue`（显隐开关 + 上移 / 下移 +
  恢复默认）+ `stores/statsChartPrefs.ts`（localStorage `nf-stats-chart-prefs`，600ms 防抖持久化 +
  读取时校验 + 未知 id 过滤）。
- **外观 · Layout 页做实**（`882beef`）：新 `stores/displayPrefs.ts` 承载展示类偏好（`coverSize` /
  `gridGap` / `cardInfoMode` / `authorCoverSize` / `authorCoverShape` / `zebraStriping`），**并入既有
  `appearance` 偏好块**（`lib/prefsPayload.ts`，**不新增第七块**，避免牵动服务端 `PREFS_BLOCKS`）；
  `stores/prefSync.ts` 接线；`ShelfView.vue` 的硬编码 Tailwind 栅格类改为 **CSS 变量驱动**
  （保留响应式断点行为）、`AuthorsView.vue` 消费作者封面尺寸 / 形状、`components/ui/BookCover.vue` 支持形状。
- **外观 · Behavior 页做实**（`36e0c8e`）：缩略图点击行为（上游 Read first / Open details —— 本项目原为
  固定进详情，`ShelfView.vue` 的 `onGridClick` / `onEntryClick` / `onTableRowClick` 加分支）、
  筛选预览默认展开、系列默认折叠，**上游三项全做实**，故该页页尾**没有**「未支持」对照卡。
- **测试同步**（`c59a649`）：外观两页由 `placeholder` 改 `ready` 后，`tests/test_settings_nav_contract.py`
  的占位页清单同步。
- **真缺失小项收口**：
  - **作者 `sort name`**（`4bfe94b` 后端 + `0b8a92d` 前端）：`authors` 表加列（照抄同表「在线值 / 本地覆盖」
    分列模式）+ `GET /api/authors` 下发 + `AuthorDetailView.vue` 可编辑 / 恢复在线（照抄 bio 那套）+
    `AuthorsView.vue` 排序项；新增 `tests/test_author_sort_name.py`（177 行）。
  - **作者「无头像」快捷筛选**（`c3367d2`）：`AuthorsView.vue` 加过滤项，`has_photo` 字段现成。
  - **审计日志按操作者筛选**（`5b47013` 后端 + `f6f4218` 前端）：`activity_log.recent()` 加 actor 过滤 +
    `/api/logs` **可选**参数（不传参输出与改动前一致）+ `AuditLogPage.vue` 控件（该页原有注释如实标注
    「日志接口尚未支持按 actor 过滤」，本期把它变成真的，注释一并更新）；新增 `tests/test_logs_actor.py`（160 行）。
  - **侧栏假按钮 + 收藏夹失败提示**（`df59689`）：侧栏「库」组的 add / more 原落到 `ui.demo()`
    （弹「演示动作：…」，与 `capability-gap.md` 的「全仓不再有看得见但点不动的控件」自我声明冲突），
    改为真实路由（add → `/#/tools/libraries?new=1` 并自动开新建向导，more → `/#/tools/libraries`）；
    新建收藏夹**失败**时提示被套上演示前缀的真 bug 改走 `ui.toast`，并在 `lib/api.ts` 新增
    `apiErrorMessage()` 剥掉后端 `{"detail":"…"}` 的花括号（**只剥壳**，不改 `request()` 的抛错约定，
    全站既有调用点不受影响）。
  - **`generic` 书源取消注册**（`26795f9`）：该模板类两个抽象方法都 `raise NotImplementedError`，
    却 `@register` 进了 `REGISTRY` ⇒ **每次 `/api/search` 都命中它、抛异常、被吞成一条
    「书源 generic 搜索失败」假失败日志**，还白建一次 `BrowserClient`。去掉 `@register`
    （`sources/__init__.py` 刻意不导入它）并在 docstring 与 README 写明「模板类不注册、JSON 规则源
    （`CONFIG_DIR/sources/*.json`）是首选路径」；新增 `tests/test_sources_registry.py`（5 例，含零网络桩
    与「接口 404」式防回归断言）。
  - **陈旧文案与注释订正**（`f44c634`）：`BookDockPage.vue` 的「未支持」卡把**已实现**的「投递后自动抓
    元数据」列成未支持（实测 `metadata_fetch.auto_on_import` 自第 5 期就在 `core/watcher.py:84` 与
    `metadata_fetch.enabled` 双重门控，多个入库点调 `auto_fetch_async`）⇒ 本轮**实拉上游**
    `client/src/features/settings/BookDockSettings.vue`（295 行）逐行核对后重写：上游 AUTO-FINALIZE 组 =
    开关 + 0–100 分阈值 + 目标库 + 合并模式 + 目标文件夹（`:207-287`），本项目缺的是「目标库 / 文件夹 /
    合并模式」这组配置，而本项目的 0–1 置信度阈值只是**候选筛选**阈值，两者不是一回事；
    `BookDetailView.vue:23` 原写「引入 SQLite 后（Batch 2）接入」（已改写为「阅读进度 `:260` `api.getProgress`」）；`data/nav.ts` 的「`_` 开头的 id」说法
    与**整个 `VIEW_META` 死表**（7 个 key 一个都到不了）+ `PlaceholderView.vue` / `router/index.ts`
    相应改写为「未知路由兜底」。

**明确不做（附理由，不做假动作）**

- **外观 Icons 页**：上游是「图标风格 + 自定义图标上传 + 排序」。本项目图标是内联 SVG 常量集
  （`lib/icons.ts`），做「风格」需多套图标集、「上传」需存储 + 覆盖机制，成本远超收益 ⇒ **保持
  placeholder 并如实标注**。
- 上游统计图的 `metadata-freshness-gauge`（第 30 期已判「价值低」）、`reading-source-distribution`
  （本项目无 `source` 列）、`goal-trajectory`（本项目无阅读目标设置）—— 三张不只不做，且**不补死 UI**。
- 上游 `client/` 全量取证、69 个后端模块逐模块对照：用户未选，本期只按需拉本期要照搬的文件。
  - **第 33 期已补**：模块数**实测订正为 67**（`ls-tree -d` 计数，非 69），其中 1 个是架构边界测试非能力
    ⇒ 能力模块 66 个；清单见 `docs/bookorbit-module-inventory.md`（含 16 个此前从未被判定过的模块）。
    `client/` 的 33 个 feature 也一并列了对照表。**本期只产出清单，不实现清单项。**
- `win32` 那例长期失败与顺序依赖 flaky 两例：**列为观察项不列为交付**（根因未定位，属既有 win32 不通）。
  - **第 33 期订正**：其中 `test_audiobook_library_scan_triggers_auto_fetch` **已定位并修复** ——
    它**不是 flaky 而是产品 bug**（win32 上目录 `st_size` 恒为 0，音频目录被 `handle_file` 的空文件
    检查拦掉 ⇒ 有声书永不入库）。另两例（顺序依赖那例 + `test_series_meta.py` 候选）本轮**未复现**，
    机制已分析、**按拍板不改测试逻辑**。详见下方 `#### 第 33 期验证` 的 B 段。

**备查（本轮未改）**：侧栏「库」组底部的 more 行仍写「查看全部书库（3）」—— 括号里是书库数、点下去是
「看全部书库的书」，读法含糊但**不属假动作**；要改得动 more 行的 label + count 契约，超出「订正文案」的
范围，留待后续。

#### 第 32 期验证

- **后端全量 pytest：388 例 / 1 failed**，唯一失败仍是既有的 win32 不通那例
  （`test_watcher_auto_fetch::test_audiobook_library_scan_triggers_auto_fetch`）→ **非本期回归**。
  本期新增 4 个测试文件全绿：`test_stats_charts.py` / `test_author_sort_name.py` / `test_logs_actor.py` /
  `test_sources_registry.py`。
- **统计接口向后兼容实测**：`/api/stats` 的**既有 16 个键一个不少** + 8 条新序列齐全且带真实数据；
  按库收窄生效（`default` 空库的阅读侧序列全 0、**形状固定**，`days` 是分母）；未知库 **200 + 空集合不 404**
  （与第 31 期 `/api/reading-activity` 同惯例）。
- **前端 e2e（8795 实例 + playwright）**：统计页两分区各 5 张图**全部渲染**（`inst:5`，每张都
  `withSvgPath:5`，标题逐一核对），Configure 隐藏一张 → 图数 5→4、**刷新后仍隐藏**（`checkboxStillOff:true`）、
  重排刷新后保留、「恢复默认」生效；外观 layout / behavior 两页存活（5 / 3 个控件）；
  **`ext: []` 零外部请求、`errs: []` 无控制台错误**。
- **小项 e2e**：侧栏「新建」→ `/#/tools/libraries?new=1` 且新建书库弹窗自动打开、「更多」→
  `/#/tools/libraries` 且弹窗不开；收藏夹同名连建两次 → 第一次进列表、第二次 toast 为「同名收藏夹已存在」
  （**无「演示动作」前缀、无花括号**）；`generic` 取消注册的因果链用**离线探针坐实**（现注册
  `['gutenberg']` → 无假失败日志；手工 `register(GenericHtmlSource)` 回去 → 复现「书源 generic 搜索失败：
  请实现 search()…」）；Book Dock 页分组标签只剩 AUTO-FINALIZE、旧文案（「尚未接线」「见第 7 期 B2」）绝迹；
  `/#/placeholder/_authors` 与任意未知路径照常渲染兜底页。
- **两处记号偏差的更正（记录在案，避免后续误读为缺陷）**：① 复核时按计划里的旧名 `weekday_minutes`
  去对响应，发现实现的真名是 **`weekdays`** —— 系「拿计划里的旧名当清单」的记号问题，**不是缺陷**，
  改用真名复核后 8 条新序列全部在位且带真实数据；② `LayoutPage` 的「上游还有、本项目未支持」卡经逐项
  核对是**准确的**（列 4 项真未做 + 理由），与 BookDock 那张（已实现却写着未支持）**不同，不需改**。

#### 第 33 期验证

**A. 上游模块级系统取证**：见 `docs/bookorbit-module-inventory.md`（67 个目录逐条判定 + 33 个 feature
对照 + 一条方法学警告「按模块名 grep 得出的覆盖结论是错的」）。**本期只产出清单，不实现清单项。**

**B. win32「flaky」的真相**：一例是产品 bug，另两例本轮未复现

| 用例 | 第 33 期结论 |
| --- | --- |
| `test_watcher_auto_fetch::test_audiobook_library_scan_triggers_auto_fetch` | **已定位并修复** —— 不是 flaky，是**产品 bug**（见 ①） |
| `test_scrape_publish::test_接口_扫描后按开关自动入队` | **未复现** —— 机制已分析（见 ②），**不改测试逻辑** |
| `test_series_meta.py`（第 33 期新观察到的候选） | **未复现** —— 同上 |

**① 第一例 = 产品 bug（已修，commit `16b0fb1`）**：`FolderWatcher.handle_file` 开头用
`p.stat().st_size == 0` 判「空文件」，而 **Windows 上目录的 `st_size` 恒为 0**（NTFS 的目录大小字段）
⇒ 音频目录（有声书）在到达 `p.is_dir()` 分支**之前**就被判「空文件」跳过 ⇒ **win32 上有声书永远
不入库**。Linux 上目录 st_size 非 0，所以 CI / 开发机一直没暴露，只在 win32 稳定复现。

> **定位难点值得记**：该用例的报错只有「auto_fetch 未被调用」（`calls == []`），**完全不指向根因**。
> 逐层打印后才看到 `_scan_locked` 返回 `{'scanned': 1, 'skipped': 1}` —— 即「条目进了流程但被跳过」，
> 再比对 `p.stat().st_size`（0）与 `_sig()`（对目录递归汇总，本来就是对的）才锁定。
> 另外「**长期稳定失败**」本身就是线索：**真 flaky 不会次次都挂**。
> 新增 `test_audio_dir_not_mistaken_for_empty_file` 直指 `handle_file` 的返回值；已实测
> 「临时改回旧逻辑 ⇒ 恰好这两例失败」，确认断言真能捕获该 bug。

**② 第二例 = 未复现，机制如下（不改测试逻辑，如实记录）**：该用例 `assert st["total"] == 1`
（`test_scrape_publish.py:442`）断言的是**全局**队列，而

- `total` = `sum(db.scrape_counts().values())`（`server.py:3024`）= **`scrape_items` 表全表行数**；
- `_quiesce_background` 收尾走 `scrape.stop(timeout=2.0)`（`conftest.py:98`）—— **超时后线程仍在**；
- `isolated` 会 `db.close()` + `db.init()` 换一套空库，但**残留线程下次取连接拿到的是新库**。

⇒ 残留 worker 要么经 `db.scrape_delete`（`scrape.py:278`「书库已不在」/ `:380`「源与副本都不在」）
**删行**（total 变 0），要么 upsert **插行**（total 变 2）。两种都让断言落空，**且时序决定是否发生**
—— 这正是「单跑必过、全量偶挂」的形状。

**为何本轮复现不了**：本机离线，worker 首次外呼**快速失败** ⇒ 秒退 ⇒ `stop(timeout=2.0)` 总能收干净。
历史上偶发时应是 worker 卡在超时里、2s 收不掉。**按用户拍板「定位不到就不硬改」**：既不改测试逻辑，
也不动 `total` 的口径（那会改变页面上「概览计数」的语义）。

**③ 第三例候选（`test_series_meta.py`）**：2026-09-20 那轮曾连跑三次、每次随机挂 1–2 例（受害者每次
不同，报错都落在 `fileops.patch_epub_meta` → `_rewrite_zip_opf`），怀疑同样是「残余 worker 持句柄」。
**第 33 期 4 轮全量一次未复现**，故只保留观察项，不做任何改动。

**④ 全量基线**：**404 例 / 0 failed**（第 32 期基线 388 例 / 1 failed；例数增加系本期新增的统计接口
测试）。第 33 期共跑 4 轮全量，**全部 0 failed**。

**⑤ 端到端对照实验**：接口级测试**覆盖不到**这条路径 —— 测试里 `AUTO_WATCH=false`（`conftest.py:57`）
⇒ watcher 不跑 ⇒ `/api/libraries/{lid}/scan` 里 `WATCHER.is_running()`（`server.py:2846`）为假
⇒ 走不到音频目录的摄入分支。故另起独立实例（**8796 端口** + 独立临时根 + `AUTO_WATCH=true`）做对照，
**唯一的变量就是那一行**：

| 运行 | `handle_file` 的空文件检查 | 本库书目 | 存储根下的副本 | 结论 |
| --- | --- | --- | --- | --- |
| 对照（临时回退那一行） | `if size == 0:` | `[]` | `[]` | **FAIL** |
| 修复版 | `if not is_dir and size == 0:` | `['e2e测试有声书']` | `01.mp3` / `02.mp3` | **PASS** |

⇒ 「修复真的改变了端到端行为」有了直接证据（不再只有单测层的回退验证）。布置过程中实测到两条
**产品契约**，一并记下：① 库根**必须**位于「书库来源目录 / 导出目录 / 数据目录」之一，否则建库直接
400；② 库存储根放在 `OUTPUT_DIR` 之下时，`default` 默认书库（root 即 `OUTPUT_DIR`、inplace、watch=1）
会把这副本**再收一次** ⇒ 书目出现两条（`audio-store/e2e测试有声书` 那条属 `default`）—— 属预期行为，
判定时按 `library_id` 过滤即可。

---

#### 第 34 期实施记录（上游模块清单「值得做 4 项」+ 遗留小尾巴 + 稳定性根因）

**主题**：用户拍板范围 = **模块清单 §4.1「值得做」4 项全做**（书签 / 重置阅读状态 / 跨实体浏览 /
侧栏计数）+ **遗留小尾巴清理**（侧栏 more 行契约、外观 Icons 页结项、统计剩余三张归档）；
书签取**对齐上游档**（软删垃圾桶 + 墓碑复活 + 并发合并）；catalog 落**新建独立页**；
第 33 期两例「未复现」的偶发失败本轮**投入定位根因**。

- **本地书签**（`5b8ada9` 后端 + `64bfbd1` 前端）：`bookmarks` 表带 `UNIQUE(book_id, anchor)`，
  软删除语义与批注同构（删除 = 移入垃圾桶、真删只对垃圾桶开放）。三条只属于书签的口径：
  **位置去重**（同位置恒为一行）、**tombstone 复活**（删过再加是复活那一行、保住 `created_at`）、
  **并发合并**（乐观并发：客户端回传它看到的那一版 `updated_at`，库里更新则 `applied=false`、
  **不改库**并把现值回给客户端；比较只用服务端时钟）。前端 = 阅读器工具条开关（实心/描边）
  + 笔记面板新增「书签」档（活跃 / 垃圾桶），**不新增全局导航项**；能力键 `bookmarks` 仅 ebook / mixed。
  ⚠️ **唯一索引带出一条真边界**：`remap_book_id` 对 bookmarks 必须**逐行搬**
  （`_remap_bookmarks`：同位置撞墓碑时先弃墓碑）—— 整体 `UPDATE` 会撞唯一约束、异常被 `except`
  吞成「搬了 0 行」⇒ 书签静默丢失。这条是写测试时撞出来的，不是猜的。
- **重置阅读状态**（`fba5094`）：`db.reset_reading_state` 只删「读出来的痕迹」三处
  （`reading_sessions` / `progress` / `reading_status`）；**批注 / 书签 / 评分 / 收藏 / 元数据覆盖
  与已解锁成就一律不动**，磁盘文件分毫不动（有指纹断言）。入口在详情页「我的记录 → 从头开始」
  （`window.confirm` 二次确认，与全站既有写法一致），并写一条新增动作「重置」的审计日志
  （与「清理」区分：那个指移入回收目录）。
- **实体总览新页**（`3f78897`）：`/browse`，侧栏「浏览」组首项（label = 实体总览，**避开组标题「浏览」
  与 `/explore`「探索发现」**——后者是外部书源检索，本页零外网）。**六个**维度：作者 / 系列 / 题材 /
  出版社 / 语言 / 收藏。两处与原计划的偏差**如实记录**：① 上游把「题材(genre)」与「标签(tag)」分两个字段，
  本项目只有 `tags`（OPF `dc:subject`）⇒ **只做一个维度**（拆两遍就是同一份数据换名重复，属假交互）；
  ② 数据全部来自 `library.scopedBooks`（= `/api/books` 按当前书库过滤），**不新增聚合接口** ——
  另起一套只会造出第二份真值源。为让「收藏」维度与其它维度同样能按库收窄，`/api/books` 增
  `collection_ids`（**一次批量查询** `db.collection_map()`，不逐本查）。
- **侧栏浏览计数**（`7e3db72`）：`core/browse_counts.py` + `GET /api/browse-counts`，
  三条口径 —— **与目标页同源**（作者 / 系列由 `library.books()` 聚合、批注走 `db.annotation_counts()`
  只算活跃）、**按库可选收窄**、**60 秒节流**（响应里如实给 `cached`）。
  **刻意不塞进 `/api/stats`**（那个接口既有键有测试钉住、且不能缓存）。
  侧栏 `countSource` 扩为 `'running' | 'browse'`；读失败时**不显示胶囊**（显示 0 会与「真的没有」混淆）。
  **侧栏刻意不传 `library_id`**：作者 / 系列 / 批注三页目前都是跨库的，计数跨库才对得上。
- **遗留小尾巴**（`0813775`）：① 侧栏「库」组 more 行口径统一 —— 原来是 `items.length`
  （= 书库数 + 1，因为「全部书库」也算一项）而点下去进的是书架；现改为 `label + to + countSource`
  三件一起声明 ⇒ **书库实体个数 + 进书库管理页**（与上游同款），并加契约测试防退回去；
  ② 外观「图标」页**结项**（写清上游形态 = 图标风格 / 自定义上传 / 排序，本项目图标是内联 SVG
  常量表且必须零外部请求 ⇒ 成本远超收益；保持只读说明、不加控件）；
  ③ 统计页剩余三张（`metadata-freshness-gauge` / `reading-source-distribution` / `goal-trajectory`）
  在 `capability-gap.md` **正式归档**：只写文档，**不加组件、不加图表 id**（栅格没有兜底分支，
  登记了 id 忘加组件会静默空白），并订正该行过期的「21/33」为 **30/33**。
  ④ **顺带揪出 3 处既有显示缺陷**：设置页 `note` 由 `SettingsPlaceholder.vue` 用 `{{ }}` **插值**渲染，
  写 `**重点**` 或反引号会**原样显示给用户**（命名规则 / Hardcover / Readwise 三处）——一并改为纯文本，
  并加契约测试（新增的 `test_说明文案是纯文本不带标记符号` 当场揪出这 3 处）。
- **稳定性：两处根因都定位并修掉**（本期最重的一块，详见下方「第 34 期验证」）：
  - `db84bb5` **刮削 worker 停机后仍会落库**（`scrape._epoch` 世代号）；
  - `a26147c` **随机 UUID 被当成 ISBN**（`metadata.isbn_digits` 收敛为唯一真值源）。

#### 第 34 期验证

**A. 全量回归（本机 POSIX，`.venv/bin/python -m pytest`）**

| 时点 | 用例数 | 结果 |
| --- | --- | --- |
| 干净 HEAD worktree（对照基线） | 405 | **3 轮里挂 1 轮**（`test_watcher_perlibrary`） |
| 本期改动 + 两处修复**之前** | 450 | 8 轮里挂 2 轮（`test_stats_integrity` 分位数），另有一轮 setup 期 `sqlite3.InterfaceError` |
| 本期**修复之后** | **475** | **连跑 4 轮全绿（0 failed / 0 errors）** |

⚠️ **口径**：这是**本机 POSIX** 的实测数，与记忆里 win32 的 404 例**不是同一套环境**，别混引。
第 33 期那条 win32 专属用例（音频目录 `st_size`）在本机无法复跑。

**B. 稳定性根因 ①：刮削 worker 停机后仍会落库（越库污染）**

机制（**可构造的必然，不是「偶发」**）：`stop(timeout)` 只等一段时间就走，而单条处理是
**不可中断的整段调用**（外呼 / 重试 / 写副本）⇒ worker 带着 `_stop` 检查不到的进度把那条跑完，
然后**照常落库**；而测试的库是**用例级隔离**的（换 `DATA_DIR` + `db.close()` → 下一套空库），
残留线程的写就落到**下一个用例的库**上：删行让全局 `total` 变 0、插行变 2。

修法 = **worker 世代号** `scrape._epoch`：`stop()` / `start()` 推进世代，`process()` / `_failed()` /
`_lost()` / `verify()` 的**每个落库点**都校验世代，作废即停手且不落库（返回 `aborted`）。
代价只是「那条留到下次重来」—— 本来就是既有恢复路径（`start()` 会 `reset_running`）。
守卫对同步调用与接口触发**完全透明**（`gen=None`）。

| 运行 | 守卫 | 换库后残留线程写了什么 | 结论 |
| --- | --- | --- | --- |
| 对照（临时把 `_stale` 改成恒 `False`） | 关 | `{'running': 1}` —— 新库被写了行 | **FAIL**（恰好两个断言守卫的用例红，第三个照旧绿） |
| 修复版 | 开 | 无 | **PASS** |

**C. 稳定性根因 ②：随机 UUID 被当成 ISBN**

机制：`library._isbn_of` 与 `fileops._set_isbn` 各写了一遍 `[\dxX-]{10,17}` 的**子串**判据，
而 EPUB 里最常见的 `dc:identifier` 就是一枚**随机 UUID**
（`ec365410-6538-43b9-93e2-9f8cdd3c0c72` —— 中间一段数字加连字符正好落进那个形状）
⇒ 实测**约 1/3 命中**。后果不只是测试偶发：界面冒出**假 ISBN**、元数据完整度白送 10 分
（`薄.epub` 32 → 42 ⇒ `test_stats_integrity::test_分位数增补p25与p75且既有两键不动` 断言落空），
而 `_set_isbn` 更狠 —— 它会**把书自己的标识符覆盖掉**。

定位手法（沿用第 33 期纪律）：报错只给一组对不上的分位数 ⇒ **逐层打印中间返回值**
（每本书的 `audit(b)["score"]` 与 `present`）⇒ 锁定是 ISBN 那一档 ⇒ 再打印
`_tag_all(opf,'dc:identifier')` 与 `_isbn_of(opf)`，当场看到漂移来自随机 UUID。

修法：形状判定收敛到**唯一真值源** `metadata.isbn_digits`（10 位末位可 X / 13 位纯数字，
允许分隔符与 `urn:isbn:` 前缀；UUID 一律不认），`library` 与 `fileops` 都改调它，
并加契约测试「全仓只剩一处判据」（**剥注释后**再扫 —— 说明文字里必须引用那条旧判据）。

| 探针 | 修复前 | 修复后 |
| --- | --- | --- |
| 同一批书构造 N 轮 | 6 轮里 **2 轮**漂移（`薄.epub` 42.0） | **8 轮恒为 32.0** |
| `tests/test_stats_integrity.py` | 5 轮里挂 2 轮 | **8 轮全绿** |

**D. 端到端（真进程，非 TestClient）**：书签 8801 端口 + 独立临时根，25 项断言全过
（位置去重 / 墓碑复活 / 软删语义 / purge 门槛 / 并发两侧 / 终态账目）。

**E. 文档**：`capability-gap.md`（§0.3 基线重取：路由 262 → **270**、表 27 → **28**；
§1 与 §4 各新增两行；统计行订正为 30/33 并写明归档含义）、
`bookorbit-module-inventory.md`（§4.1 四项标记已落地 + 头部加第 34 期更新）、
本文件（本节）。**所有新增锚点均已实测复核**（行号见各行）。

---

#### 第 36 期实施记录（跨库移动 + 搬迁断链修复 + 阅读器排版收尾 + 固定版式识别）

**主题**：**双轨并行**（两者无依赖，交替提交）。主轨 = **跨库移动** —— 上游 BookOrbit 的
「把某一本挑去别的库」在本项目**完全不存在**：自动归库由**格式**决定目标库，用户无从干预。
四条口径由用户拍板：① 目标库限**类型相容**；② 撞名**拒绝覆盖 + 一键改名移入**；
③ **副本随书搬**（正本走了副本留下 = 移动只做了一半）；④ 小轨锁定为「阅读器排版剩余四项」。
T1→T4 串行（T1 / T1.5 都是**先修既有真 bug**，不修的话新功能会踩在断链上）。
小轨 = 阅读器补**字重样式 / 文本区左右内边距** + **固定版式识别**。

- **T1 搬迁断链修复**（`a1b6d7a`）：`book_id` 是 `库$sha1(basename)` ⇒ **换库**（库前缀变）与
  **改名 / 加卷号**（basename 变）都会换 id。此前 `db.REMAP_TABLES` 漏了四张同样按 `book_id`
  存的表，于是每次移动 / 改名都**静默断链** —— 读点全按新 id 查，查不到**不抛异常、不回滚**，
  只是无声回落成抓取值或文件原值（用户看到的是「我改的元数据自己变回去了」）。
  `meta_override` / `meta_online` 进 `REMAP_MERGE_TABLES`（逐行搬、同 field 冲突保留目标行 ——
  整体 `UPDATE` 撞主键会被外层 `except` 吞成「搬 0 行」= 用户的编辑消失，第 34 期同一个坑）；
  `meta_cover` 进 `REMAP_TABLES` 走既有探测跳过；`scrape_items` 另写显式搬迁函数
  （它还带 `library_id` / `source_rel` / `link_rel` 三个库相关列），`old == new` 时是「只改列」。
  `ORPHAN_TABLES` 补三张（含 BLOB 的 `meta_cover` 是大头）；**刻意不加 `scrape_items`** ——
  台账行被删等于把「磁盘上可能还留着一个副本」静默遗忘，它的生死归刮削流程自己管。
  两条改名路径（`apply_conflict_rename` / `apply_komga_layout`）一并接上台账改写。
- **T2 前置 · 回滚不搬回关联数据**（`a71380f`）：`execute` 搬库时把关联数据 remap 到新 id，
  `rollback` 却只把文件移回原位、**不做反向 remap** ⇒ 回滚一次，进度 / 批注 / 用户改过的元数据
  就永久留在那个已经没有文件指向的 id 上。按 id 的**定义式**重算两侧 id 再反向搬，
  **不猜、不存快照**（即使 manifest 行是上一版写下的、或文件被手工挪过，算出来的也是当下真值）。
- **T2 核心 · 跨库移动**（`70c7f47`）：与自动归库**共用** manifest / 逐条独立 / remap / 回滚
  这台机器（差别只有「谁选源集合 / 谁定目标库 / 副本怎么处理」三处，故**不另开模块** ——
  另开就得把这几条纪律再抄一遍）。四条新口径：
  ① **类型相容闸门**判据只有 `library._exts_for_type`（库扫描白名单的**唯一真值源**）——
  不相容不是「半可见」，白名单决定扫描认不认，搬过去这本书**直接从该库书目里消失**、行当场
  变孤儿，所以**后端也拦一次**，不只靠前端置灰；目录型有声书按 `allow_audio_dir` 同判；
  ② **副本随书搬**，五种情形逐条区分（无副本 / 目标库没配成品目录（如实记 `skipped` + 副本在哪）/
  两库共用同一成品目录 / 落点已是同源硬链接（回收旧链接）/ 真搬移（落点被外来文件占着则**退让
  改名，绝不覆盖**））；落点与出版共用 `publish.relpath_for` + `rel_verdict` + `free_rel` ——
  **预览==落盘靠「共用」保证**，不是两边各写一遍；
  ③ **移动后必须 `watcher.mark_processed(dst)`** —— 去重键是「相对 `input_dir` 的路径 +
  (size, mtime)」，移进来的文件在它眼里是**全新投递**，不登记会被再入库一次；watcher 按参数注入
  （同 bookdock），不设模块级全局；④ **台账随书改挂**并按**磁盘实况**重量 `link_mode` /
  `link_shared`（跨卷移动必然换 inode，照抄旧值就是照着旧关系撒谎）。回滚是同一件事的镜像。
  冲突仍是**拒绝覆盖 + 一键改名移入**；manifest 的 `direction` 如实写 `bookmove`，而自动归库的
  字面量 `"move"` **不动**（`migration_last_batch("move")` 是既有回滚入口，存量批次还躺在 pending 里）。
- **T3 接口**（`d968994`）：五个入口**全走 POST**（选择集可能几十本、`book_id` 带 `$` 与哈希，
  塞进 query string 迟早撞长度上限；这组接口也没有缓存需求）。`/targets` 与 `/preflight` 的理由
  直接取后端 `compat_reason` ⇒ **前端置灰说的原因与后端真拒绝的原因逐字相同**；`/preflight`
  **一律 200**（它的职责是把理由列出来给人看，不是报错）；**`/plan` 才是相容闸门的落点** ——
  混进一本进不去这个库的书就**整批 400、不落行**，不「悄悄搬能搬的那几本」；`/apply` 立刻返回
  `task_id`、后台跑，进度是 `done/total` 真值，**刻意不写 `result`**（任务行有 result 就会渲染成
  「下载」按钮，而移动没有产物可下）；`/rollback` + `/batches` 只列 `bookmove` 批次，不混自动归库的
  （免得「撤销」按错批次）。core 侧补 `blocked_kind` 区分「整批 400」与「逐本跳过」两类拦截原因。
- **T4 前端**（`d16bc99`）：书架批量条新增「移动到书库」→ **三段式弹窗**（挑库 → 预检 → 确认），
  **不塞进批量条一键跑完**（这几步会真动磁盘）。目标库选择器把不相容的库**照列并写明原因**
  （抹掉的话用户会以为库没建好）；预检清单逐本说清「能搬 / 撞名 / 搬不了」，撞名逐条给动作、
  **默认不表态 = 这次不搬这一本**（不替用户决定）；确认文案只报后端数出来的
  `will_move_files` / `will_move_copies`，**不写「预计」「约」**；顶栏一条「上次移动：甲库 → 乙库 ·
  N 本」+「撤销本次移动」（移动会改磁盘位置，撤销入口不藏在别的页）；任务中心补
  `bookmove` 运行中百分比（下载仍只在终态显示 —— 它不报细分进度，给数字就是编造）。
- **小轨 · 固定版式识别**（`271de3b` 后端 + `3df68e3` 前端）：`core/library._fixed_layout_of`
  认三种真实写法的**显式声明**（EPUB3 标签体 / EPUB3 `content=` 属性 / 早期 Apple
  `<meta name="fixed-layout" content="true"/>`），**绝不靠特征猜**（「书里有整页 SVG」不是判据 ——
  猜错的代价是把一本正常书的排版设置夺走，比不做判定更糟，有 `test_有整页SVG但没声明仍算可重排`
  钉住）。判定随**书目与详情**下发（字段恒在，前端不用写 `undefined` 兜底），非 EPUB 恒 `false`。
  前端据实**停用重排偏好、不强加页宽**，控件仍列出但 `disabled` 并写明原因。
- **小轨 · 阅读器排版两项**（`3df68e3`）：新增**字重样式**（常规 / 加粗 / 斜体 / 粗斜体）与
  **文本区左右内边距** `gutter`（与 `width` 是**两个独立的量**：`width` 是文本块自身宽度上限，
  `gutter` 是文本块与阅读区边缘的留白）。默认 `1.5rem` **正好等于原先写死的 `px-6`** ⇒
  默认观感零变化。服务端偏好载荷校验是**块级**的（只查未知块名与体积上限）⇒ 新增阅读器偏好键
  **不需要后端改动**，这一点是核实过的、不是假设。

**与计划的「有意偏离」**（如实记录，都不是省略，是落点不同）：

1. **`preview` / `plan` 未被加参数，改为一对平行入口**：计划写「`preview` / `plan` / `execute`
   增显式选择集 + 显式目标库入参」；实施为 `migrate.move_preview`（`migrate.py:571`）/
   `move_plan`（`:594`），与既有 `preview`（`:172`）/ `plan`（`:258`）并列，**共用**
   `execute`（`:947`）/ `rollback`（`:1041`）。理由：自动归库那条路径的入参**冻结着既有回滚入口**
   （`migration_last_batch("move")`），两套语义塞进同一个函数就得在每个分支里判断「这次是哪种调用」；
   平行入口 + 共用执行层既满足防回归 #3（既有行为逐字不变），也不产生第二套规则展开。
   代价：`execute` 多一个 `direction` 判别，接口层据此拒收别的方向的批次。
2. **小轨「固定版式页宽」的处置 = 做了识别、不做那三档页宽**：计划的判据是「判定结果决定做实
   还是如实标注」，实测后**两条各取一半** —— `rendition:layout` 判定**做实**，页宽三档
   **如实标注为未提供**。理由：固定版式在本项目阅读器里是「整页走重排管线」这条路径，真按上游
   语义做三档页宽等于**另起一个固定版式渲染器**，不是本小轨的量级；而识别本身是硬前置，且立刻
   消除一个真 bug（整页排版被缩进 / 段距揉烂）。设置页对照卡里标为「已识别、仅不提供档位」，
   **不写成已实现**。
3. **小轨「新书套用默认值」= 记文档、不建开关**：上游那一项问的是「新书要不要套用当前排版偏好」，
   而本项目阅读器偏好是 `localStorage['reader-prefs']` **全局单一数据源**（阅读界面与设置页读写
   同一份）⇒ 对「新书」本就不存在「没套用」的问题，**没有开关可做**。只做口径改判并写进文档。

**诚实记录**：计划点名的两个 skill（前端开发规范 / agent-browser）**在本会话内不可用**
（`Skill` 工具查无此名），因此前端规范改为逐条对齐既有同类实现的写法（`ShelfView.vue` 批量动作条、
`MigrationGateDialog.vue` 三段式弹窗），`npm run type-check` 一次通过。**浏览器冒烟原打算用
HTTP 端到端替代**（T4 提交里就是这么如实写的「本期没有真实浏览器点击留证」），**但收尾时补上了**：
本机 `playwright-cli` 与 chromium 都在，`pip/npm` 之外不需要任何新装 —— 于是按第 35 期的同一套做法
（`playwright-cli` + `--browser=chromium`，实例 `127.0.0.1:8796`）逐项点了一遍，结论见下方 F。
**「skill 不可用」不等于「工具不可用」**：那条「没有留证」的自我声明本身是错的，这里就地更正。

**延后 / 留待下期的既有差异（不是漏改）**：自动归库那条路径**不管副本、也不改挂台账**，
本期按防回归 #3 逐字保持不动 ⇒ 两条路径在副本语义上**存在已知差异**，留着是有意为之。

**A. 单测**：全量 **595 例 / 0 failed**（基线 548 ⇒ 本期 +47：T1 契约测试 + T2 跨库移动 11 例 +
T3 接口 8 例 + 小轨固定版式 12 例等）。新增用例**全部做过变异验证** —— 副本不搬 / 不登记 watcher /
相容闸门失效 / 回滚不搬回数据 / 任务行写上 result / 进度写死 / 批次列表不过滤 `direction` /
固定版式改为「靠 `<svg` 猜」，每一处变异都有对应用例转红。T1 的契约测试本身就是
「凡含 `book_id` 列的表必须进搬迁清单」（改前 10 例全红 → 改后全绿）。

**B. 端到端（真实实例，非 TestClient）**：跨库移动 44 项断言全过（预检 → 计划 → 相容闸门 400 →
执行 → 磁盘 / 台账 / 进度 / 元数据读回 → `scrape/verify` 无误报 → 批次 → 回滚 → 再对账）；
固定版式 9 项（写三种 EPUB 进真库、按真实 HTTP 读书目与详情、并核已部署产物带着新界面文案）。

**C. 浏览器冒烟（收尾补齐，`playwright-cli` + chromium，实例 8796 / `/tmp/nf-test36`）**：

| 点的是什么 | 实测结论 |
| --- | --- |
| 固定版式的书 → 阅读设置 | `article` 带 `nf-fixed`；「这本是**固定版式**…只有主题、阅读模式与左右内边距会生效」原文渲染；**9 个滑杆里 8 个 `disabled=true`，唯一可用的是「文本区左右内边距」**（`0–6` / 步长 `0.5` / 值 `1.5`） |
| 可重排的书 → 阅读设置 | **无** `nf-fixed`、**无**固定版式提示；9 个滑杆**全部可用**；字重样式四档（常规 / 加粗 / 斜体 / 粗斜体）在列 |
| 点「粗斜体」 | `article` 即时变成 `font-weight:700` + `font-style:italic`，`localStorage['reader-prefs']` 落 `fontStyle:"boldItalic"` |
| 「文本区左右内边距」按 →（键盘，3 次） | `article` 的 `padding-left` 由 `1.5rem` → **`3rem`**，偏好落盘 `gutter:3`；设置页同步显示 `3.0rem`（**全局单一数据源当场验到**） |
| 设置 → 阅读器 → eBook | 字重样式行、内边距滑杆、脚注「…共 15 项；其余为未支持」；未支持卡两项**是纯文本**（`「」` 正常显示，没有漏出 `**` / 反引号） |
| 书架 → 多选 → 移动到书库 | 三段式弹窗：目标库列表**把不相容的「有声书库」照列并写明理由**（「只收 M4B / MP3 / … 这本是 EPUB」）；「甲库 · 书已经在其中」也照列；两者都是**不可点的 `generic`**、相容的两个才是 `button` ⇒ 前端禁选与后端理由**同一句话** |
| 选乙库 → 预检 | 「可移动 1 本」「整页书.epub · 没有副本」「将移动 1 本 → 「乙库」」（都是后端数出来的真数字） |
| 开始移动 | 磁盘实况：`lib/a/整页书.epub` → `lib/b/整页书.epub`，书目 `library_id` 跟着改，**`fixed_layout` 搬迁后仍为 true**；书架出现「上次移动：甲库 → 乙库 · 1 本」 |
| 撤销本次移动 | toast「已撤销：1 本搬回原库」，文件**真的回到 `lib/a`**、乙库清空 |

**从浏览器里捞出来的三件事（HTTP 端到端与产物字符串都测不到）**：

1. **真 bug，已修**（`4e17023`）：「离开阅读器」时会发 `POST /api/books/undefined/session` → **404**。
   根因是 `flushSession` 用 `bookId`（= `String(route.params.id)`）而路由参数在离开时**先变空**，
   `String(undefined)` 就是字面量 `"undefined"`；`book.value` 还在，所以原有的 `!book.value` 守卫
   拦不住。后果不是多一条噪声请求 —— 这段阅读时长被 `catch` 塞回一个**再没人上报的变量**，
   于是**每次离开都丢掉最后一段时长**。改为取 `book.value?.id`。改前 / 改后**都在浏览器里跑过**：
   旧产物发出 `…/undefined/session → 404`，新产物同一动作发 `…/lib-b09f4886$b6de2f5c9476/session → 200`
   （服务端访问日志里两条并存，是同一次操作的前后对照）。**前端无单测框架**（没有 vitest），
   所以这条的证据就是浏览器 + 服务端日志，如实说明。
2. **环境坑，非产品缺陷**：首轮 `/api/fonts` **500**，`OSError: [Errno 30] Read-only file system: '/app'`
   —— 测试实例当时只设了 `DATA_DIR` / `OUTPUT_DIR` / `LIBRARY_SOURCE_DIR`，漏了 `CONFIG_DIR`，
   于是 `FONTS_DIR`（= `CONFIG_DIR/fonts`）落到容器默认的 `/app`。补上 `CONFIG_DIR` 即好。
   ⚠️ 记一笔给下次搭实例的人：**建实例要连 `CONFIG_DIR` 一起给**。
3. **观察，未定性**：SPA 内直接改 hash 从一个书的阅读页跳到另一本（`#/read/A` → `#/read/B`），
   正文与 `nf-fixed` 会正确更新，但**阅读页头部的书名会停在上一本**；整页刷新后正常。
   应用自身的导航路径（书架 → 详情 → 阅读）不走这条，故未定性为缺陷，只记下待复现。

**D. 文档**：`bookorbit-capability-gap.md`（§0.3 基线重取：路由 270 → **284**、表 28 → **31**；
锚点 6 处行号更正）、`bookorbit-module-inventory.md`（§4.2 `book-move` 行改判为**已落地**并补
落地锚点与三条有意差异；§4 汇总行重算）、`bookorbit-settings-inventory.md`（三处 + 两项改判）、
`roadmap-verification.md:100`（阅读器排版行）、本文件（本节）。
**E. 附带修复**：`4e17023`（阅读时长上报用了 `undefined` 的 book_id，见 C-1），
**是浏览器冒烟才捞出来的**，不在原计划内。
**锚点核验**：`tests/check_doc_anchors.py` ⇒ 硬错 **0** / 疑似漂移 **0**（收尾时修掉 7 处），
且这 7 处**全部落在本期自己动过的两个文件**（`core/db.py` / `server.py`）上 ——
印证 §四那条纪律「改动落在锚点密集的文件上时，顺手把该文件相关锚点重核一遍」。
另：本期属「只改代码不新增能力键 / 设置页」的相位，`tests/test_settings_nav_contract.py` 的
48 与 `tests/test_features.py` 的 18 两处契约断言**未动**。

---

## 四、验证纪律（沿用 history）

全量类型检查 → 构建 → 部署 `novelforge/static/v2` → 重启测试实例 → 端到端脚本验证「保存 → 读回 → 实际生效」→ 浏览器逐路由冒烟。

**文档锚点核验（第 35 期起，与上面同列为收尾必做）**：`.venv/bin/python tests/check_doc_anchors.py`
（工具本身与它的五类误报、两类漏报见 `docs/bookorbit-capability-gap.md` §0.5）。

- **判据是两条，不是一条**：「工具报 0 条硬错 + 0 条漂移」**且**人工过完 `--todo` 清单。
  「行号合法、内容已换」这一类**工具天生测不出**（第 35 期 `DOCK_TABS` 差了 568 行就是工具漏报、
  人工捞出来的）。所以「工具不报错」永远不等于「核完了」。
- **只记当前真实行号，不记偏移量**（第 33 期 §0.4 的血教训：`:278` 写「偏移 1 行」，实测 44–54 行）。
- **改动落在锚点密集的文件上时，顺手把该文件相关锚点重核一遍**：第 34 期只改了 6 个文件，
  第 35 期就从中捞出 37 处漂移 —— 其中 `core/stats.py` 是**上一轮刚「逐个重取」过**、这一轮又整体后移
  275–305 行的（新键插在中间）。**「上期刚核过」不构成免检理由。**
