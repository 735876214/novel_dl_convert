# 上游功能缺口跟踪基线（第 6 期起）

> 来源：`docs/bookorbit/bookorbit-capability-gap.md`（采集自线上实例 BookOrbit v2.10.0，2026-09-16）
> 基线日期：2026-09-18
> 已完成参考：第 0–5 期路线图（见 `docs/roadmap-verification.md`，第 0–4 期 27/27 验证，第 5 期 2026-09-17 完成）；**第 6–32 期已完成**（第 33 期进行中）—— 第 6–9 期见下方分期标题（A1–A9 前端快赢 / B1–B4 轻后端 / D1–D5 作者级元数据与抓取深化 / D6–D7 CBR 阅读与有声书播放器），第 10 期起见「三、分期实施计划」下的**逐期实施记录**
> **第 33 期提示**：本文件的缺口清单已实质清空（档位为「可直接落地」的行**已全部收口**）。新增的缺口来源
> 请改看 `docs/bookorbit/bookorbit-module-inventory.md`（按上游代码模块逐条对照，已实测出 16 个此前从未被判定过的模块）——
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
- **版本标识同源（后端为权威）**：收敛单一常量 `APP_VERSION = "0.6.0"`（`server.py:152`），
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
  `docs/bookorbit/bookorbit-capability-gap.md` 逐行改判（§1/§2/§3/§6/§7/§8/§11 等多行附 `文件:行`），并标注
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
  `data/nav.ts:45`、`AppSidebar.vue:36/61`、`lib/api.ts`。**零假数据、零外链、无 `Math.random()`**（确定性）。
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
    ⇒ 能力模块 66 个；清单见 `docs/bookorbit/bookorbit-module-inventory.md`（含 16 个此前从未被判定过的模块）。
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

**A. 上游模块级系统取证**：见 `docs/bookorbit/bookorbit-module-inventory.md`（67 个目录逐条判定 + 33 个 feature
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

- `total` = `sum(db.scrape_counts().values())`（`server.py:4572`）= **`scrape_items` 表全表行数**；
- `_quiesce_background` 收尾走 `scrape.stop(timeout=2.0)`（`conftest.py:281`）—— **超时后线程仍在**；
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
⇒ watcher 不跑 ⇒ `/api/libraries/{lid}/scan` 里 `WATCHER.is_running()`（`server.py:4392`）为假
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
   增显式选择集 + 显式目标库入参」；实施为 `migrate.move_preview`（`migrate.py:405`）/
   `move_plan`（`:428`），与既有 `preview`（`:172`）/ `plan`（`:258`）并列，**共用**
   `execute`（`:781`）/ `rollback`（`:861`）。理由：自动归库那条路径的入参**冻结着既有回滚入口**
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

#### 第 37 期实施记录（书库 / 智能书架 / 收藏夹一律**不设默认**）

**主题**：用户拍板的口径 —— **全新部署时这三组都是空的，建什么、叫什么全部手工新增**。
这不是「清一下种子数据」，而是拆掉一条贯穿全仓的隐含前提：此前 `libraries` 表为空时，
产品会**合成一个 `DEFAULT_LIBRARY_ID` 的假库**（root = `OUTPUT_DIR`）兜底，于是
「书库表为空」这个状态在代码里**根本不存在**，而它现在成了默认状态。

四条口径由用户逐项拍板（AskUserQuestion）：

| 争点 | 拍板 |
| --- | --- |
| 书库「默认」这个概念 | **彻底去掉** —— 不播种、不合成、去掉「默认」徽章与删除守卫；`default` 退化成一条**普通可删**的库 |
| 一个库都没有时投递 `input/` | **拒收**，提示先建库 |
| 有库但规则全不命中 | **也不收，如实报错**（库的 `rules` 就是路由表，路由表不命中就不猜） |
| 智能书架的 5 条内置 | **删掉，但补 `added` + `annotations` 两个规则字段**，保证能手搓重建 |

- **内核**（`core/library.py` / `core/library_rules.py`）：删掉 `DEFAULT_LIBRARY_ID` /
  `default_library()` / `ensure_default_library()` / 无人调用的 `resolve()`；`libraries()`
  改为**老老实实返回真实行**（空表 = 空列表），`get_library("")` 一律 `None`。归库判定的
  最后一档从「回退默认库」改成 **`None` = 拒收**，新增 `no_library_reason()` 把
  「一个库都没有」与「规则不命中」**分开说话**（不说清，用户不知道该去建库还是改规则）。
  `guard_conflict` 也跟着改：落点不属于任何已登记库时**放行给上游拒收**，而不是拿空 id 去查撞名。
- **摄入链路**（`server.py` / `core/watcher.py`）：上传 / `/convert` / `/convert-path` /
  下载任务都改成**先解析目标、拿不到就 400 拒收**（且都在**写文件之前**判断）；
  watcher 的 `handle_file` 拒收时**原文件留在原地**，如实记一次带原因的失败。
  ⚠️ 由此牵出一个必须配套的东西：拒收也走**失败计数**，到 `max_retries` 就永久跳过 ——
  于是「建库 → 文件自己进来」这条链条本来是断的。补 `FolderWatcher.forget_failures()`，
  由新的 `server._libraries_changed()`（= `library.invalidate()` + `forget_failures()`）在
  书库**增 / 删 / 改**三处统一调用。**必须是「删条目」而不是「把 failed 清零」** ——
  扫描侧把 `failed == 0` 当成「已成功处理过」，清零等于**再也不会被扫**，与意图正好相反
  （这一点是写测试时被一条真失败打出来的，见下方 A）。
- **孤儿清理的第二道判据**（`server._orphan_refs()`）：不能再拿「书目列表为空」当
  「所有记录都成了孤儿」。`book_id` 形如 `库$哈希`，**库已不存在的行不算孤儿** ——
  否则「移除全部书库 → 点清理孤儿」就是一次不可恢复的进度 / 批注大清洗。
  扫描口径与清理口径**同源**（`_orphans()` 与 `api_orphans_clear` 都调 `_orphan_refs()`），
  不做两份判据。没有 `$` 的旧 id（第 17 期库维度化之前）无法归属任何库，按老口径处理。
- **前端**：`data/collections.ts` 三个骨架数组清空（`LIBRARIES` / `SMART_SHELVES` /
  `COLLECTIONS`），侧栏改吃各自的空态文案（「尚无智能书架」/「尚无收藏」，两者本就存在）；
  `stores/library.ts` 删掉 `SMART_KEYS` / `smartKeyOf()` / `smartCounts` 这套**内置键盘**
  （仪表盘仍在用的 `smartBooks()` 保留）；`LibrariesView.vue` 去掉「默认」徽章与移除按钮上的
  `v-if`；`api.ts` 的 `LibraryEntity` 去掉 `is_default`。
- **规则字段补齐**（`server.SCOPE_FIELDS` / `SCOPE_OPS` ↔ `lib/smartScope.ts` 的
  `FIELD_OPS` / `FIELD_LABELS`）：新增 **`annotations`（批注数）** 与 **`added`（入库天数，
  值 = 距今天数，取 `mtime`）**，两者都是 `至少 / 至多`。没有它们，「有批注」「最近添加」
  这两条内置书架删掉后**造不回来** —— 那才是真的能力净损失。

**与计划的「有意偏离」**：无。四条口径都是用户拍板后**逐条照做**，没有中途改判。

**A. 单测**：全量 **619 例 / 0 failed**（第 36 期基线 595 ⇒ 本期 **+24**）。新增用例分布：
`test_no_defaults_contract.py`（10 例，纯文本 / 常量契约）、`test_smart_scopes.py`（9 例，
这组接口**此前一个测试都没有**）、本文件相关 5 例（孤儿放过 / 原因文案 / 空表 / 拒收 / 建库后自动收走）。
两处补做的**改前 FAIL / 改后 PASS**：
① 临时摘掉 `_orphan_refs()` 里的 `and str(i).split("$", 1)[0] in lib_ids` ⇒
`test_库被移除登记后它的书不算孤儿` 当场断言失败（`assert 1 == 0`），文件随后按字节还原；
② 临时让 `_libraries_changed()` 不调 `forget_failures()` ⇒ `test_建库后被拒收过的文件会自动重新收走`
失败（`scanned: 0`）。该用例刻意把 `max_retries` 设成 1：第一轮就触顶，
**再扫一轮本来就不会重试**，成败只取决于建库时有没有清计数 —— 否则漏掉钩子也会因
「还没到上限、本来就会重试」而误过。
顺带记一笔：**先写的 `forget_failures()` 是错的**（清零而非删条目），正是这条测试把它打出来的。

**B. 端到端（真实实例，非 TestClient，8796 + `/tmp/nf-test37`）**：全新根启动 ⇒
`libraries` / `smart-scopes` / `collections` **三处都是空列表**；投 `.epub` 进 `input/` 再 `/api/scan` ⇒
`failed` 里原文带着「没有可接收的书库：还没有书库：请先到「工具 → 书库管理」新建一个书库并指定它的来源目录」，
**文件留在原地、导出目录为空**；`/convert` ⇒ **400** 且是同一句话；随后建一条 `ebook` 库 ⇒
**原先被拒收的文件自己进了新库的根**（这正是 `forget_failures` 的端到端证据）；
`/api/libraries` 的 DTO 里**没有 `is_default`**，书目 id 带上了库前缀。

**C. 浏览器冒烟（`playwright-cli` + chromium，实例 8796 / `/tmp/nf-test37`）**：

| 点的是什么 | 实测结论 |
| --- | --- |
| 首次进入（已登录） | 侧栏「库」组 1 条真实库 + 「全部书库」；**「智能书架」组 = 「尚无智能书架」**、**「收藏夹」组 = 「尚无收藏」** |
| 工具 → 书库管理 | `1 / 1`、「电子书库」；按钮组 **设置 / 扫描 / 编辑 / 移除** 四件齐（第 37 期前默认库只有三件、且挂「默认」徽章）；「来源父目录」是真实路径 |
| 智能书架 → 新建 | 字段下拉里 **「批注数」「入库天数」在列**；选「批注数」后算子自动切成 **至少 / 至多**（字段-算子耦合生效）；值填 `1` ⇒ 预览 **命中 0 本**（这本书确实没有批注） |
| 保存「有批注」 | 列表出现「全部 · 批注数 至少 11 / 0 本」—— 值 `11` 是**冒烟工具的车祸**（见下方坑 1），不是产品行为；删掉后重来 |
| 手搓「最近添加」= 入库天数 **至多 30** | 预览 **命中 1 本**（今天入库）→ 保存 → 侧栏「智能书架」组**出现「最近添加」、计数 1** → 点进书架「**最近添加 · 共 1 本**」 |

**从浏览器里捞出来的一件工具坑（不是产品缺陷）**：`playwright-cli fill <ref> <text>` **不会触发 Vue 的
`v-model`** —— DOM 里 value 有了、组件状态仍是空，表现为「输入框明明填了，`保存` 一直 disabled、
实时预览毫无反应」。改用 `type` / `press`（走真实按键事件）立刻正常。第一轮那个 `11` 就是
`fill "1"` 与 `type "1"` 叠加的结果。⚠️ 记一笔给下次冒烟的人：**这个仓的前端一律用 `type`，别用 `fill`。**

**D. 文档**：`bookorbit-capability-gap.md`（SMART SCOPES 行改判「固定 5 个已下线」并补两个新字段的去处；
COLLECTIONS 行改成「本组从不预置」+ 实测锚点；另修 3 处漂移行号 `notifications/read` `4429→4486`、
`GET /api/logs` `4377→4433`、`EDITABLE` `3786→3819`、`/api/maintenance` `3890-3893→4103-4106`、
`_upload_limit` `323-334→326-335` 及用法 `339/5612→342/5859`）、
`roadmap-gaps-remaining.md`（`total` 口径 `3024→3050`、`WATCHER.is_running()` `2846→2872`；本节）。
**锚点核验**：`tests/check_doc_anchors.py` ⇒ 硬错 **0** / 疑似漂移 **0**（收尾修掉 5 处，
全部落在本期自己动过的 `server.py` 上）。本期同样**不动** `tests/test_settings_nav_contract.py` 的
48 与 `tests/test_features.py` 的 18 两处契约断言（未新增能力键 / 设置页）。

**E. 已知后果（有意为之，不是遗漏）**：按用户拍板的「rules 就是路由表」语义，
往全局 `input/` 投一个 `.txt` / `.epub` **不再必然被收** —— 只有当某条库的规则命中它
（例如存在一条格式相符的库）时才落地，否则拒收并在失败清单里说明原因。
这是「不猜一个库」的直接代价，配套的 `forget_failures()` 保证用户照着提示建完库之后，
**原先投过的文件会自己进来**，不必重投。

---

#### 第 38 期实施记录（首次使用引导 + 0 库边界收尾）

**主题**：第 37 期把「书库表为空」扶正成全新部署的**正常初始态**，可前端**一处都没说这件事**。
后果是首屏一整页的 0（0 本 / 0 B / 0 / 30 本）都在陈述「你还没有书」，而真相是
**这些数字背后连一个能放书的地方都还没有**；更糟的是十几个入口（探索发现下载 / 本地转换上传 /
Book Dock 投递 / 书架「立即扫描」/ 任务中心空态 …）都在把人往「下载 / 上传 / 投递」上引，
而这三个动作在「没有可接收的库」时**全都会被后端 400 拒收** —— 下载还会先报「已加入下载队列」、
再在后台悄悄失败。本期收的就是这个口子。

三条口径由用户逐项拍板（AskUserQuestion）：

| 争点 | 拍板 |
| --- | --- |
| 引导用什么载体 | **复用既有 `GuidedTourModal`**，不新建引导组件（它此前只能从「设置 → 个人资料」手动重放） |
| 首屏那些 0 要不要改 | **一个数字都不改** —— 它们是真值；改成「—」或藏起来本身就是伪造，改为**加一条横幅解释这些 0 从哪来** |
| 三个导入入口怎么处理 | **抢先拦截**（前端提前返回 + 给出口），而不是等后端 400 再解释 |

- **判据（这是全期的地基）**：`libraryEntities.length === 0` **判不了**这件事 ——
  `libraryEntities` 初值就是 `[]`，拉取失败还被 `catch` 吞掉，于是「还没拉到 / 拉失败」与
  「真的一个库都没有」长得一模一样。拿它当判据，每次进页面都会**闪一下**「还没有书库」，
  而后端明明是通的。`stores/library.ts` 因此新增 `librariesLoaded`（**只在成功取回后**置真，
  失败保持 false —— 不知道就是不知道，不猜成 0），零库判据统一收敛成
  `hasNoLibraries = librariesLoaded && libraryEntities.length === 0`。**判据只有一个**，
  十来个改口的宿主全部走它，谁都不许再直接拿 `length` 判空。
- **空态三态分开**（`ShelfView.vue`）：`0 库` ≠ `有库但没书` ≠ `有筛选没命中`。
  第 38 期之前只有后两态，且把「没书」一概说成「到「探索发现」把书下载进来」—— 0 库时那是句错话。
  0 库态另带一个 `新建书库` 出口（复用既有 `manageLibs()`），并**收起「立即扫描」**
  （扫不出任何东西）、**保留「书库管理」在最显眼处**（它就是本期引导指向的那个出口）。
- **引导挂在 shell 层**（`App.vue`）：只在 `hasNoLibraries` 成立时弹一次，用 `nf_tour_seen` 记
  「弹过就算看过」（打开即写标记，不按「是否点完」记 —— 里面那套步骤可以随时从个人资料页重放，
  反过来按「没看完就再弹」会变成每次刷新糊一个弹窗）。0 库时第一步换成「先建一个书库」并带一个
  `新建书库` CTA；**常驻指引不依赖它** —— 仪表盘提示条、书架空态、侧栏、书库管理页各自都会说。
- **改口的宿主（十处）**：仪表盘 `FirstRunNotice`（新增的虚线提示条，**刻意不注册进部件表** ——
  能被关掉的提示条等于没有）、`LongWaitWidget` / `CurrentlyReadingWidget` / `HighlightOfTheDayWidget`
  （三处空态加「正在载入…」，把「还没拉到」与「真的没有」也分开）、`StatsView.integrityCleanText`、
  `LibraryIntegrityGaugeChart`（原来是「书库还是空的」，读起来像「库已存在、只是没放书」）、
  `TaskCenterView`、`OutputView`、`ScrapePanel`、`ExploreView`、`LocalConvertView`、`BookDockPage`、
  `LibrariesView`、`AppSidebar`。
- **`AppSidebar` 里的一处死代码**：原打算照其它组一样改 `group.empty`，读代码发现**「库」组永远不为空**
  （恒有「全部书库」一项），那个分支对它**永远走不到** —— 改也是白改。改成显式补一行
  「还没有书库，先建一个」，否则全新部署的侧栏「库」组就只有一个筛选框和「查看全部书库（0）」。
- **三个入口的拦截**（`ExploreView.startDownload` / `LocalConvertView` 的 `convertFiles` 与
  `convertByPath` / `BookDockPage.onDrop`）：都在**发请求之前**判 `hasNoLibraries` 并 `return`，
  再弹一条带出口的 toast，而不是让用户先看到「已加入下载队列」再在任务中心读失败原因。

**与计划的「有意偏离」**：无。三条口径都是用户拍板后逐条照做。

**A. 单测**：全量 **632 例 / 0 failed**（第 37 期基线 619 ⇒ 本期 **+13**，全部来自新增的
`tests/test_first_run_contract.py`）。仓内前端没有 vitest，所以沿用 `test_no_defaults_contract.py`
那套**纯文本契约**（读源码断言），五组：判据唯一 / 三态文案 / 引导分支 / 三处拦截点在请求之前 /
出口指向同一处 `/tools/libraries`。
改动前跑出 **11 例真失败 + 2 例前向守卫**（后两条读的是本期新增的文件，改前不存在，属预期）。
写这组断言时自纠了三处**是我自己的正则错**、不是产品缺陷：`\n\)\n` 匹配不到 `\n})\n`；
`body.index("api.")` 抛 ValueError（真实代码是换行后的 `api\n    .download(`，改用
`re.search(r"\.download\(")` 取 `head`）；`WIDGET_META` 出现在 `FirstRunNotice` 自己的说明注释里
⇒ 加 `_code()` 先剥注释再断言「不许出现某标识符」（解释「为什么不许」的注释必然要提到它）。

**B. 端到端（真实实例 8796 + `/tmp/nf-test38`）**：先以**全新根**启动 ⇒ 仪表盘提示条、
书架「还没有书库」+「新建书库」且**无**「立即扫描」与工具栏、侧栏「还没有书库，先建一个」、
书库管理页引导段、引导弹窗「先建一个书库 · 1 / 3」；点引导 CTA ⇒ 落到
`#/tools/libraries?new=1` 且**新建弹窗已打开**。随后在该弹窗里建一条 `ebook` 库 ⇒
**四个翻转点同时成立**：提示条消失、书架变成「这个书架还是空的 / 换个入口看看，或到「探索发现」
把书下载进来」且工具栏（切库 + 立即扫描 + 书库管理）恢复、引导不再弹、三个入口的拦截不再触发
（探索发现副标题与本地转换 / Book Dock 的说明都回到正常口径）。

**C. 浏览器冒烟（`playwright-cli` + chromium，实例 8796 / `/tmp/nf-test38`）**：

| 点的是什么 | 实测结论 |
| --- | --- |
| 0 库首屏（仪表盘） | 提示条「还没有书库 / 下面的数字全是 0，是因为书还没有地方可放…」+`新建书库`；**下方所有 0 值照旧显示**（口径：不改真值） |
| 首屏自动弹引导 | 「先建一个书库 · 新手引导 1 / 3」，带「跳过」与「新建书库」 |
| 引导 CTA | 落 `#/tools/libraries?new=1`，**新建弹窗已打开**（`?new=1` 直达生效） |
| 侧栏「库」组 | 「全部书库 0」下有「还没有书库，先建一个」；组底仍是「查看全部书库（0）」 |
| 书架（0 库） | 「还没有书库」+ 说明 +「新建书库」；**无「立即扫描」、无工具栏** |
| 建库后重进 | 书架「这个书架还是空的」+ 工具栏恢复；仪表盘提示条消失；「正在阅读」=「还没有在读的书，打开一本开始阅读吧」；引导不再弹 |

**D. 文档**：本节 + 锚点核验两处漂移（`ShelfView.vue:457-469 → 545-560`、
`AppSidebar.vue:34/58 → 36/61`，均为**实测行号**）。
`tests/check_doc_anchors.py` ⇒ 硬错 **0** / 疑似漂移 **0**，`--todo` 清单逐条过完。
本期**不动** `tests/test_settings_nav_contract.py` 的 48 与 `tests/test_features.py` 的 18
两处契约断言 —— **未新增表 / 能力键 / 设置页 / 页面 / 路由**，全部改动都在既有文件里改口。

**E. 两个坑（都不是产品缺陷，但下次会再踩）**：

1. **`onMounted` 在「登录之前」就跑完了** —— 这是本期唯一一个**靠浏览器实测才发现的真 bug**。
   引导最初写成在 `App.vue` 的 `onMounted` 里采样一次 `hasNoLibraries`，结果**一次都没弹过**
   （`nf_tour_seen` 始终为空）。根因：`App` 早在**登录之前**就挂载好了（登录是覆盖层 `LoginGate`，
   **不是路由**），那一刻 `loadLibraries()` 拿到的是 **401**、`librariesLoaded` 仍是 false，
   于是「0 库」这个判断当时根本不成立；等用户登进来，`onMounted` 早已跑完，不会再跑第二次。
   改成盯 `hasNoLibraries` 的 `watch(..., { immediate: true })`：无论库是登录后才拉到的、
   还是用户把最后一个库删掉才变成 0 的，都会在**成立的那一刻**触发。
2. **`playwright-cli` 的几个用法**（第 37 期记过 `fill` 的坑，本期补三条）：
   ① `--browser=chromium` **只对 `open` 有效**，`snapshot` / `click` 带上它一律
   `Unknown option: --browser`；② `open` 每次起的是**新上下文**（localStorage 清空 ⇒ 要重新登录），
   **同一个会话里再 `open` 会失败**，此后所有命令都报 `browser 'default' is not open` ——
   改用 `goto <url>` 做页内跳转；③ 本机默认浏览器是 chrome、**没装**，不开 `--browser=chromium`
   直接 `Chromium distribution 'chrome' is not found`。
   另记一笔**工具的假象**：`click` 之后紧跟 `type` 时，第一次 `type` 可能落在**焦点尚未切换**的空档里，
   DOM 里没有值、稍后快照才发现 —— 表现为「字段看着没填上」。重 `click` 一次再 `type` 就好；
   本轮那条库的 `source_subdir` 因此成了 `ebooksebooks`（冒烟实例的数据问题，不是产品行为）。

**F. 全量回归里的一例偶发（与本期的前端改动无关，如实记一笔）**：第一轮全量 632 例中
`test_watcher_perlibrary::test_open_library_source_is_scanned_and_writes_last_scan` 失败在
`db.get_library` 的 `sqlite3.InterfaceError: bad parameter or other API misuse`（**文件已摄入成功**，
挂在读回 `last_scan_at` 那一刻），单跑该文件 8 例全绿、**第二轮全量 632 / 0 / 0**。
该用例在**干净 HEAD worktree** 上也偶发过（第 33 期 §C 有同样的记录），属既有顺序 / 线程时序问题；
本期改动全在前端 + 一个纯文本测试文件，不触碰 DB。

---

#### 第 39 期实施记录（前端回归护栏 + 未关闭观察项三例 + 归库↔移动语义统一）

**主题**：**还款期，不是新增能力期**。第 38 期收尾时三条缺口轴已实质耗尽 ——
`bookorbit-capability-gap.md` 四组全 `[x]`（全文仅剩 `:493` 一条属**决策未定**的 Komga 方向，
不是「工作未做」）、`bookorbit-module-inventory.md` §4.2 剩的 4 项都属「与本项目定位无关」、
本文件无「待落地」档位。缺口没有了不等于没活干，本期还三笔债：**前端零单测框架**
（历史上每一个前端 bug —— 第 34 期侧栏计数、第 36 期 SPA 标题、第 38 期 `librariesLoaded` ——
都只能靠浏览器冒烟抓，632 例 pytest 对 `frontend/src/**` 一行都覆盖不到）、
三个当轮如实记录却未修的观察项、以及一笔**代码自己写明「要改它得单独一期」**的语义债
（`migrate.py` 原文：「要改它得单独一期」—— 第 39 期正是这一期）。

三条口径由用户逐项拍板（AskUserQuestion）：

| 争点 | 拍板 |
| --- | --- |
| 落地域 | **前端回归护栏 ＋ 未关闭观察项三例 ＋ 归库↔移动语义统一**（备份与恢复**未选** —— `README.md:127` 已写明「备份它等于备份全部阅读数据」＋ compose 显式挂载 `./data`，该候选本身不成立） |
| 前端单测口径 | **vitest + @vue/test-utils**（非纯逻辑测试、非纯文本契约） |
| T5 的 db 层修复形态 | **单点代理：`_connect()` 按语句持锁**（一处改动覆盖全部 169 处调用点，不逐处手改） |

**前端护栏（T1/T2）**：`vitest 5.0.1 + @vue/test-utils 2.5.1 + happy-dom 20.14.5`。
**不另起 `vitest.config.ts`**（`vite.config.ts` 的 `resolve.alias['@']` 是唯一真值源，
另起一份就是复制它）；**不启用 `globals`**（spec 在 `src/**` 下会被 `vue-tsc --build` 一并检查，
开 `globals` 就得往 `types` 里加东西、污染构建期类型环境）；脚本名 **`test:unit`** 而非 `test`
（本仓「测试」传统上专指 pytest，改名会造成口径混淆）。
`ChartGrid` 的一致性**不写运行期用例** —— `StatisticsChartId = keyof typeof STATISTICS_CHART_META`
⇒ `Record<StatisticsChartId, Component>` 让「目录有 id、组件没登记」**直接编译失败**，
再写一条运行期断言只是重复 `type-check`；真正该钉的是**别有人把它放宽成 `Record<string, Component>`**。

**T5 的真结论（本期最有价值的一条，与计划假设不同，如实记）**：

计划里 H1 的写法是「写线程持锁 `commit()` 会重置该连接上的所有语句 ⇒ 另一线程中途 `fetchone()`
抛 `InterfaceError`」。**这条被直接实验证伪**：`executescript` / `rollback` / `commit` 三种操作
各自与一个整窗口持有游标的读线程对撞 2 秒 —— **全是 0 异常**。`commit()` 根本不会重置别人的语句；
而常见的 sqlite3 误用（cursor 关后用、连接关后用、参数错、`row_factory` 非 callable …）
产出的都是 `ProgrammingError` / `TypeError`，**没有一种能造出 `InterfaceError`**。
（该消息本身不在 `_sqlite3.pyd` 里 —— 它是 SQLite C 库 `sqlite3_errmsg` 的文本，
即 `SQLITE_MISUSE` 的默认描述。）

真机制是**同一连接上的无锁并发访问**，而且**不需要 `close()` 就能造出来**：

| 探针（放大版，非原样） | 修复前 | 修复后 |
| --- | --- | --- |
| 三线程裸读 `db.get_library` + 一线程锁内 `db.create_library`（4s） | **3/3 轮全 `InterfaceError`**，各 400–500 次 | **0**（3/3 轮） |
| 同上再加「读该库生效设置」= 用户可见症状 | **1973 / 2303 / 2509 次每 5s**，另加写失败 269/298/254 次 | **未发生** |
| 三线程裸读 + `db.close()`（4s） | **6/6 段错误**（exit 139） | **exit 0**（不崩） |

**它是生产可达的**：`db.create_library` / `update_library` 持锁写，而 `db.get_library` 裸读，
生产里 watcher 线程、scrape worker、`server.py:4784` 的 `asyncio.to_thread(migrate.execute)`
与请求线程都会同时进这个连接。**用户可见后果**不是「报个错」——
`library.get_library` 把这个异常吞成 `None` ⇒ `lib_settings.overrides()` 得空 dict ⇒
**每库覆写静默回落全局值**：用户关掉某库的「自动刮削」，读回来又是开的。

**它还解释了第 38 期 F 小节记的那条偶发**：`test_scrape_publish.py` 的
「扫描后按开关自动入队」断言 `auto_enabled is False` 却拿到 `True` ——
`:452` 刚设完 `scrape.enabled: False`，`:458` 读回时撞上并发写，覆写被吃，回落成全局的 `True`。
**逐字吻合，两件事本是同一个根因。**

修法（用户拍板的单点代理）：`_connect()` 返回 `db._Conn` —— **每条语句都在 `_lock` 内跑完、
并把结果取干净**（`db._Result` 是内存里的一段行，接口照 `sqlite3.Cursor` 的常用面做窄）；
`_lock` 改 `RLock`（`with _lock:` 块里还会再调 `c.execute`，非重入锁会自锁死）。
169 处调用点**一行不改**。代理绝不能把「还没取完的语句」留到锁外 —— 那正是竞态本身。
`db.close()` 也持锁 ⇒ 原先那条段错误路径一并封死。

**H2（坐实并已修）**：`tests/conftest.py::_quiesce_background` 此前**丢弃**
`watcher.wait_pending(5.0)` 的返回值（它返回「超时后仍未结束的数量」），并把一切包进
`except Exception: pass` —— 于是「收尾没干净」只表现为后面某个**无关**用例偶发变红。
已改成非 0 就 `pytest.fail` 把这件事说出来（失败信息里明说「泄漏点可能在更早的用例」）。
**改硬失败前先量过**：全量跑里该值**恒为 0**（`scrape.stop(2.0)` 也从未残留），故不误伤。

**观察项三例的最终状态**：

| 观察项 | 最终状态 |
| --- | --- |
| ① 侧边栏库计数首次加载显示为 0（第 34 期记录） | **未复现 ⇒ 按纪律只补覆盖、不硬改**。新增 `tests/test_library_count_contract.py` 6 例 —— `book_count` 此前**全仓零覆盖** |
| ② SPA hash 导航标题过期（第 36 期记录） | **已修**（`ReaderView.vue`：抽 `load()` 由 `onMounted` 与 `watch(bookId, …)` 共用；**不加 `:key`** —— 与本项目「局部更新不重建 DOM」的既有做法冲突） |
| ③ `InterfaceError` 间歇失败（第 33/38 期记录） | **根因查明并已修**（见上）。计划假设（H1）被证伪，真机制另有其人且**生产可达** |

**与计划的「有意偏离」**：一处 —— T5 的修复形态由「`db._lock` 改 `RLock` + 把读路径逐处纳入锁」
改为**单点代理**（用户拍板）。理由是逐处手改 169 个调用点靠人工找全，漏一处等于没修。
计划第 17 条的**前提**（H1）不成立，但**修法方向（读路径纳入锁）恰好正确** —— 实验已直接验证。

**A. 单测**：全量 **651 例 / 0 failed / 0 err**（本期基线 647 ⇒ **+4**，全部来自新增的
`tests/test_db_concurrency_contract.py`）。本期共 5 个 commit，基线轨迹
632（第 38 期）⇒ 647（T1/T2 前端自守契约 5 + T3 计数契约 6 + T6 归库统一契约 4）⇒ **651**。
前端用例**单独计数**、**不并入 pytest 基线**（两套跑法、两套前提）。
新护栏做了**变异验证**：把 `_connect()` 退回裸连接 ⇒ 4 例中 **3 例变红**
（第 4 例守的是「锁是重入锁」，本就该保持绿），撤销变异 ⇒ **4/4 全绿**；
H2 那条也验过：伪造 `wait_pending` 返回 1 ⇒ `Failed: 收尾没干净…`，撤销 ⇒ 全绿。
全量连跑 **4 轮**（3 轮验 db 改动 + 1 轮验 conftest 改动）**全部 651/0/0**。

**B. 集成冒烟（真实 uvicorn 实例 8802 + 独立临时根，**保留 watcher 后台线程**）**：
登录 → 建库 → 写覆写 → 读回 `auto_enabled=False` → **三线程猛读 + 一线程反复重写、压 6 秒**
⇒ **GET/PUT 出错 0 次、覆写被吃 0 次**，压完再读回仍是 `False`，服务端日志
`traceback|InterfaceError|ProgrammingError` **0 行**。
（顺带撞了两次产品自己的护栏，都属正常拒绝：「库根必须是绝对路径」——
Windows 下 `/tmp/…` 不算；「库根必须位于书库来源 / 导出 / 数据目录之内」。）

**C. 浏览器冒烟**：**本轮未跑**。本轮改动只有 db 层并发修复 + 文档 / 记忆 / 锚点；
T5 的症状（并发下每库覆写被吃）在浏览器里**单用户操作触发不到**（它需要多线程同时进连接），
故以「真实实例 + 并发压测」替代（见 B）。

**D. 文档**：本节 + 锚点全文复查。⚠️ `novelforge/core/db.py` 本期**净增 102 行**（`_Conn` /
`_Result` / docstring），它此前是锚点密集文件 ⇒ 指向它的锚点**整体后移**。
`tests/check_doc_anchors.py` 实测：修前 **硬错 0 / 疑似漂移 11**，逐条打开核实（不记偏移量、
只写实测行号）后修 12 处 ⇒ 修后 **硬错 0 / 疑似漂移 0**，符号命中由 37 升到 49。
修的清单（旧 → 新，全部实测）：`collection_map` 961→1063（两处）、`reset_reading_state`
3370→3472（两处）、`notifications_read` 表 156→258、`book_dock_items` 表 236→338、
`idx_dock_status` 248→350、`DOCK_TABS` 2160→2262、`set_review` 1889→1991、
`save_bookmark` 792→894、`meta_locks` 277→379 与其建表注释 272-276→374-378、
原引 `conftest.py:98`→`:109`（`_quiesce_background` 里的 `scrape.stop`；**真值**今天是 `:255`/`:281`）。
**历史记录里的旧行号一律不动** —— `capability-gap.md:86-99` 那张「原引用 / 实测应为」表
是第 33 期的核验记录，改它等于篡改历史。

**E. 三个坑（都不是产品缺陷，但下次会再踩）**：

1. **`-qq` 会吞掉汇总行**：`pytest.ini:6` 已有 `addopts = -q`，命令行**再加一个 `-q`**
   就是 `-qq`，`N passed in Xs` **整行消失**。此前把「抓不到汇总行」归因成「重定向后只剩 warnings」
   **是错的**，真因就是这个。判据只能靠 `--junitxml`：且 pytest 的根元素是 `<testsuites>`
   而非 `<testsuite>`，`r.get('tests')` 在根上返回 `None`，必须 `r.iter('testsuite')` 再求和。
2. **探针脚本别用 `grep` 猜结果**：`grep "FAILED"` 区分大小写，匹配不上小写的 `failed`；
   `tail -8` / `head -40` 也看不到汇总行（它排在 warnings 摘要**之前**）。
   要么落全量日志到文件再解析，要么走 junitxml。
3. **`InterfaceError` 的文本不在 `_sqlite3.pyd` 里** —— 第一反应去二进制里找那条消息会扑空
   （实测偏移 -1）。它是 SQLite C 库自己的 `sqlite3_errmsg` 文本。想定位就该抓**抛出点**：
   `traceback.format_stack()` 拿不到（异常已抛出栈），必须 `format_exc()` ——
   且 Python 3.11+ 会带 `^^^^` 精细定位，链式表达式（`_connect().execute(...).fetchone()`）
   也能指出是哪一段调用。

**F. 一条方法论的收获（值得单独记一笔）**：本轮**四次**基于「读码看起来对」的推测被实验或读码推翻 ——
① 「旧自动归库路的 `old_id` 算错（传了绝对路径）」：读 `library._book_id` 发现**只用 basename**，
两条路算出同一个 id；② 「`update_library` 整行覆盖导致覆写被旧快照盖掉」：读 `db.py` 发现
**只写传入的列**；③ 「`ltype` 回落成 `mixed` 会让 `allows_setting` 丢掉 `scrape.enabled`」：
读 `FEATURES_BY_TYPE` 发现 `mixed` **有** `komga` 能力；④ 计划里的 H1 机制（`commit()` 重置语句）。
**这四条一条都没写进文档**。结论：**「读起来像」不构成证据，动手前先造能证伪它的探针** ——
这也正是本仓「无复现不改」那条纪律值钱的地方。

全量类型检查 → 构建 → 部署 `novelforge/static/v2` → 重启测试实例 → 端到端脚本验证「保存 → 读回 → 实际生效」→ 浏览器逐路由冒烟。

**文档锚点核验（第 35 期起，与上面同列为收尾必做）**：`.venv/bin/python tests/check_doc_anchors.py`
（工具本身与它的五类误报、两类漏报见 `docs/bookorbit/bookorbit-capability-gap.md` §0.5）。

- **判据是两条，不是一条**：「工具报 0 条硬错 + 0 条漂移」**且**人工过完 `--todo` 清单。
  「行号合法、内容已换」这一类**工具天生测不出**（第 35 期 `DOCK_TABS` 差了 568 行就是工具漏报、
  人工捞出来的）。所以「工具不报错」永远不等于「核完了」。
- **只记当前真实行号，不记偏移量**（第 33 期 §0.4 的血教训：`:278` 写「偏移 1 行」，实测 44–54 行）。
- **改动落在锚点密集的文件上时，顺手把该文件相关锚点重核一遍**：第 34 期只改了 6 个文件，
  第 35 期就从中捞出 37 处漂移 —— 其中 `core/stats.py` 是**上一轮刚「逐个重取」过**、这一轮又整体后移
  275–305 行的（新键插在中间）。**「上期刚核过」不构成免检理由。**

#### 第 40 期实施记录（新建书库向导 5 步 + 允许格式 / 排除图案 / 图标 + 阅读阈值可配）

**主题**：不是补缺口，是**改造既有流程**。第 38–39 期把三条缺口轴走完、把债还清，本期回到
**产品形态本身** —— 用户拿上游 BookOrbit「Create a library」7 步向导的 9 张截图，要求照它的
**信息结构**重排本项目的「新增书库」。

**开工前实测得出的判断（本期省掉一半活的原因）**：上游 7 步里，第 2 步 Folders、
第 5 步 Reading 的「何时算读完」、第 6 步 Automation 在本项目**都已是现成后端** ——
`api_create_library`（`novelforge/server.py:4056`）本就收 `name / type / mode / root_path /
source_subdir / publish_path / rules / watch / scan_interval / scan_cron` 十项，而第 6 步的
「自动扫描计划」是**第 17 期 T2 的真实调度**（`watcher._should_scan`，`novelforge/core/watcher.py:668`），
不是占位。**真正新增的只有 3 个库表列 + 2 个配置项**，其余是把已有能力摆成向导的样子。

**用户拍板（AskUserQuestion，4 轮）**：

| 争点 | 拍板 |
| --- | --- |
| 落地范围 | 「1、第一步是库名称和图标…3、扫描模式不全做，原有的电子库、漫画库、有声库的文件格式，按照书库类型放在允许的格式中，给出默认选择格式和格式增选。4、源优先级和格式优先级不做。其余的功能全做」 |
| 将元数据写入文件 | **不做**（铁律：只落服务端 DB，绝不写回文件） |
| 扫描模式的开关 | 「这一步不做扫描模式的开关，也不体现」 |
| Step 7 File updates | 「这一步整体取消」 |
| 阅读阈值 | 「全局配置 + 每库可覆盖」 |
| 阈值同步范围 | 「**全量同步**」—— 后端 + 前端全部硬编码 `99.5` 改读配置 |
| 排除图案 | 「新增库级列，复用同一套 glob 语义」 |
| DATE ADDED | 「不做，向导里不出现这一项」 |
| 隐形文件防护 | 「加防护」—— 入库路由跳过「收了也看不见」的库 |

**向导骨架**（`frontend/src/components/tools/LibraryWizard.vue`，新建 748 行 + spec 368 行）：
`?new=1` 时渲染全屏 5 步向导替代「列表 + 弹窗」，**`?new=1` 之外一律走原路径** ——
编辑沿用既有弹窗（只补齐新字段），22+ 条既有编辑用例一条不动。
原步骤条 `STEPS`（`frontend/src/components/tools/LibraryWizard.vue:69`；**已失效** —— 该向导今天改回了「三页签」结构，见 `LibraryWizard.vue` 头注释）：
`基本信息`（必填）→ `内容来源`（必填）→ `扫描` → `阅读` → `自动化`，对应上游
Details / Folders / Scanning / Reading / Automation。

**两条由我提出、写进计划、用户未反对的实现决策**：

1. **Step 4 Metadata（源优先级 / 格式优先级）与 Step 7 File updates 从步骤条里整个去掉，不留空壳。**
   这是「不做假交互」的直接推论：留一个点进去是空白的步骤，比少一步更糟。
2. **向导状态只在前端内存里，最后一次 POST 建库** —— 不做「建一半的库」。
   底部「立即创建」= 用当前已填值 + 其余默认值**真建库**（对应上游 Any step 的 *Create now*），
   且**必填两步仍然要过**（它减的是「不用再往后点了」，不是「可以不填名字」）。
   有变异验证钉住「只关弹窗不建库 ⇒ 用例必须变红」。

**新增 3 列**（`icon` / `allowed_exts` / `exclude`，均 `TEXT NOT NULL DEFAULT ''`），
**七处同步点**：① CREATE TABLE ② 迁移块 ③ `create_library` 签名与 INSERT
（`novelforge/core/db.py:4375`）④ **`_LIBRARY_COLS`（`novelforge/core/db.py:4430`）**
⑤ `_library_dto`（`novelforge/server.py:3768`）⑥ POST（`server.py:4039`）⑦ PATCH（`server.py:4113`）。
第 ④ 处**最易漏且不报错**：`update_library`（`novelforge/core/db.py:4437`）是「过滤后为空就原样返回」，
漏了的表现是**界面显示「已保存」而值没变**。⚠️ sqlite 的 `ALTER TABLE ADD COLUMN` 只接受
**常量**默认值 ⇒「按库类型推导扩展名」**不能**写成列默认值，只能靠 `''` 哨兵 + 读时回落。

**「空串 = 没设过」是刻意与「空集合」不同的语义**：`allowed_exts` 为 `''` ⇒ 回落该库类型的
默认白名单（`library.exts_for_library`，`novelforge/core/library.py:1024`）；坏 JSON 一律当没设过
（不抛异常、更不留一个一本也扫不出来的**死库**）。向导里「一个都不勾」发的正是空数组 ⇒
界面语义是「继承默认」。`allowed_exts` 与 `exclude` 的空串/坏值/列表去重保序，
另有 `tests/test_library_scan_scope.py` 12 例钉住（本期新建）。

**允许格式 / 排除图案的扫描语义**（`library.py:1401-1440`），与 `watcher.ignore` **同族，
但有两处明写的差异** —— ① 用 `fnmatch.fnmatchcase`（`watcher._ignored` 用的 `fnmatch.fnmatch`
在 Windows 上**大小写不敏感**，而库级排除是用户显式写下的可见规则，不能随平台变）；
② 图案**含 `/`** 时匹**相对库根**的路径，否则只匹 basename（watcher 那套是纯 basename）。
`watcher.ignore` 本期**一行不改**：它的作用域是 `INPUT_DIR`，与库扫描是两条不同的轴。

**隐形文件防护**：`library_rules.decide`（`novelforge/core/library_rules.py:172`）的候选过滤里
跳过「收了也看不见」的库（判据 = `library.accepts_ext`，`novelforge/core/library.py:1035`）⇒
返回 `None` 走**既有拒收路径**。这是**既有问题**而非本期引入：`type=ebook` 的库把 `source_subdir`
指向漫画目录，今天就能造出「文件落了盘、书目里却没有」的隐形文件；`allowed_exts` 可配之后
撞上的概率大幅提高。⚠️ 实际行为是**改判到其它合格库（fall-through）**，**不是**「一起拒收」——
只有**所有**候选库都看不见它时才拒收。跨库移动的相容闸门（`novelforge/core/migrate.py`）同样
改判**目标库**的生效格式集，否则用户能把书移进一个看不见它的库。

**阅读阈值可配（本期最值钱的一步）**：新增 `percent` 类型（`novelforge/core/lib_settings.py:282`，
值域 **0–100** —— 既有的 `number` 是 0–1，不能复用）+ `reading_thresholds()`
（`novelforge/core/lib_settings.py:235`，**全仓唯一入口**）+ `GET /api/reading-thresholds?library_id=`
（`novelforge/server.py:2740`，空 = 全局，带库 = 生效值）。
默认值**刻意不改既有行为**：`finished_threshold = 99.5`（**不是**上游的 99）、
`started_threshold = 0.0`（等价改造前的 `pct > 0`）。**改默认值等于静默改变既有的「已读完」判定**，
会让用户的书一夜之间从「读完」变回「在读」。
「全量同步」的落点：后端 `stats.py` / `komga_api.py` / `server.py` / `achievements.py`；
前端新增 `frontend/src/lib/readingThresholds.ts`（唯一入口 `statusFromPercent`，`:101`），
把原先**同一段逻辑的三份拷贝**（`bookInfo.statusLabel` / `library.derivedStatus` / `smartScope`）
收敛到它，8 处全部改调。**不新造第二处推导** —— 半改就是「两个真相源」，
会出现「统计里算已读完、书架上还是在读」。

**图标**：选择器数据源 = `Object.keys(ICONS)`，后端只做形状校验（`_norm_icon`，
`novelforge/server.py:2664`）。契约测试把 `frontend/src/lib/icons.ts` 的键**逐个喂给后端**
（纯文本断言，不拉 node —— 全量测试离线的硬前提），两边一旦不合，用户能在向导里选出这个图标、
点「创建」却拿到 400，且看不出为什么。建库后图标出现在**书库列表卡片与侧栏库项两处**。

**设置页**：全局阈值控件落在「设置 → 个人资料 → 阅读进度口径」卡（`ProfilePage.vue`），
**放在成就卡旁边不是随手摆的** —— 成就的「已读完」判定读的就是这个阈值。

**计划外发现的两个既有缺陷（都已修，均与本期主线无关）**：

1. **Windows 上 `C:\…` 被判成非绝对路径 ⇒ 向导卡在第 2 步。** 原实现两处各写一遍
   `raw.startsWith('/')`，抄的是后端 `pathlib.Path.resolve()` 的 **POSIX 版**口径。
   已抽成 `frontend/src/lib/paths.ts`（`isAbsolutePath` `:31` / `pathsOverlap` `:58`），两处改调；
   `pathsOverlap` 顺带修掉「只认 `/`，分隔符混写下重叠检测**恒为假**」。
   **生产跑在 Linux 上，所以这个 bug 从没露头。**
2. **全局阅读阈值写不进去。** `reading` 当时不在 `server.EDITABLE`（`novelforge/server.py:5364`）里，
   `_sanitize_config` 整块丢掉 ⇒ patch 为空 ⇒ 400「没有可保存的配置项」；
   `GET /api/config` 里那把**硬编码键列表**也缺它；前端 `SECTION_KEYS` 同样缺。
   漏了的表现极隐蔽：界面上的开关正常切换（本地草稿改了），只有一条 toast 一闪而过。
   而 `settingsNav.ts` 的 note 当时写着「是设置项」—— **那是一句假陈述**，
   本期补上控件把它变成真的。⇒ 新增可保存配置分区是**三处**同步点（见记忆）。

**A. 单测**：全量 **691 例 / 0 failed / 0 err**。基线 651（第 39 期）⇒ **+40**：
`tests/test_reading_thresholds.py` 新建 22 例（13 个函数，1 个 `parametrize` × 10）
+ `tests/test_library_scan_scope.py` 新建 12 例 + `tests/test_api_smoke.py` +4（向导 payload 契约）
+ `tests/test_library_rules.py` +2（隐形文件防护）。
前端用例**单独计数、不并入 pytest 基线**：**52 例 / 5 个 spec 文件**（本期新建 3 个：
`LibraryWizard.spec.ts` / `paths.spec.ts` / `readingThresholds.spec.ts`）；
`npm run type-check`（`vue-tsc --build`）exit 0；`npm run build && npm run deploy` 之后
`git status` 里 **`novelforge/static/v2` 未出现**（已在 `.gitignore:28`）。

**变异验证（强制纪律，本期 6 组，全部先红后绿）**：

| 目标 | 变异 | 期望 | 实测 |
| --- | --- | --- | --- |
| `_LIBRARY_COLS` | 从白名单里删掉 `icon` | 红 | **红**（`test_编辑弹窗的payload也能改这三个新列`） |
| 隐形文件防护 | `library_rules._accepts` 直接 `return True` | 红 | **红**（`test_没有库收得了的格式一律拒收不隐形`） |
| 排除图案 | `fnmatchcase` → `fnmatch` | 红 | **红**（`test_图案大小写敏感`，Windows 上唯一会红的一条） |
| 阈值默认值 | `finished_threshold` `99.5` → `99` | 红 | **红**（`test_默认阈值与改造前的硬编码逐字节等价`，10 个档位全红） |
| 阈值分发 | 前端 `thresholdsFor()` 恒返兜底值（= 只有后端可配） | 红 | **红**（`readingThresholds.spec.ts` 3/12） |
| 假交互 | 「立即创建」不调 `api.createLibrary` | 红 | **红**（`LibraryWizard.spec.ts` 12/21） |

撤销全部变异后：后端四文件 **92 例全绿**、前端 **52 例全绿**。

**B. 浏览器冒烟（T5-29，真实 uvicorn 实例 8794 + 独立临时根，未碰 8791 / 8993）**：
走完 5 步建一个库，四项逐条核对 ——

① **图标在列表与侧栏都可见**（两处 `svg path` 相同 `M4 19.5A2.5 2.5 0 016.5 17H20`）；
② **只有勾选的格式入库**（`普通卷.cbz` 进，`该被拒.cbr` 不进）；
③ **排除图案生效**（`草稿.draft.cbz` 不进）；
④ **阈值改动后统计与书架口径一致**，含**反向翻转**：

| 全局「已读完」阈值 | 后端统计 `finished` | 书架筛选「已读完」 | 书架筛选「在读」 |
| --- | --- | --- | --- |
| 50 | 1 | 1 本 | 0 本 |
| 99.5 | 0 | 0 本 | 1 本 |

冒烟全程**数据完全隔离**（DB 在 `%TEMP%\nf40e2e\config\data\novelforge.db`，未污染用户真实数据）。

**C. 锚点核验**：`tests/check_doc_anchors.py` 实测 —— 修前 **硬错 0 / 疑似漂移 17**，
逐条打开核实（**只写实测行号、不记偏移量**）后改 **29 处**（分布在 13 行上：
工具点名 14 条 + 在**同一批行**上顺带实测捞出 15 条），修后 **硬错 0 / 疑似漂移 3**，
符号命中由 33 升到 47。剩下的 3 条（`roadmap-gaps-remaining.md:859` / `:879` / `:1416`）
**全部落在本文件的历史实施记录里**（第 33 / 33 / 39 期）—— 按既有纪律**不动**：
改历史记录里的旧行号等于篡改历史。

⚠️ 本期又摸到工具的一个**漏报面**（补进 §0.5 的局限清单）：它只对
`` `路径:行号` ``**后面跟着反引号符号名**的锚点做自动核对，**符号写在锚点之前**的
（如旧文档里 `core/stats.py` 的那条 —— 它把 `books.by_format` 写在**行号之前**，写成「第 635 行」而不是「`:635`」）不进核对 ⇒ 那 15 处漂移**工具一条都没报**。
判据「0 硬错 + 0 漂移」因此**只能是下限**，动了锚点密集文件仍必须人工过一遍该文件的锚点。

**D. 一条方法论实证（「不记偏移量」的由来）**：本期 `core/db.py` 的 6 个 hunk 合计
**+38 / −7**，但文件里不同锚点的位移**互不相同** —— `save_bookmark` 后移 **22** 行
（894→916）、`set_review` 后移 22 行（1991→2013）、`collection_map` 后移 22 行（1063→1085），
而 `reset_reading_state` 后移 **31** 行（3472→3503）、`DOCK_TABS` 后移 23 行（2262→2285）。
因为「落在该锚点**之前**的 hunk 才影响它」，`+38/−7` 分摊到各锚点上是不同的数。
**同一个文件、同一期改动，偏移量可以有五种值** —— 这就是「只写实测行号」那条纪律的实证。

**E. 三个坑（都不是产品缺陷，但下次会再踩）**：

1. **Git Bash 的 `/tmp` 与 Python 看到的 `/tmp` 不是同一个目录。** 前者是 MSYS 的
   `C:\Users\<用户>\AppData\Local\Temp`，后者（原生 Windows 版）解析成 `C:\tmp`。
   `pytest --junitxml=/tmp/x.xml` 落盘后 bash 里 `ls /tmp/x.xml` 找得到、
   Python 里 `open('/tmp/x.xml')` 报 `FileNotFoundError` —— 本轮被这个卡过一次。
   判据：先用 `cygpath -w /tmp/...` 看真实路径，或干脆给 Windows 原生绝对路径。
2. **`-q` 会加成 `-qq` 吞掉汇总行**（第 39 期已记，本轮又踩一次）：`pytest.ini:6` 已有
   `addopts = -q`。计数一律走 `--junitxml` + 解析 XML。
3. **中文用例名在 GBK 控制台下会显示成乱码**，`FAILED tests/...::test_????` 看不出是哪个用例。
   抓失败详情时给 `PYTHONIOENCODING=utf-8`，或统一落 UTF-8 文件再读。

**F. 与计划的偏离（如实记）**：

1. 计划把「允许格式 / 排除图案」的用例挂在 `tests/test_library_rules.py`；实施时发现
   `_excluded` 的语义（`fnmatchcase` / 含 `/` 走相对路径）**在计划里没有任何靶子能钉**，
   故新建 `tests/test_library_scan_scope.py` 专门承载 12 例（含 3 条大小写用例）。
   这也让变异验证第 3 组有了可红的靶子 —— 原计划那条变异**本来无处可验**。
2. 新增 `GET /api/reading-thresholds` 时发现 `GET /api/config` 的**硬编码键列表**
   才是漏点的第三处（计划只列了两处）—— 见「计划外发现」第 2 条。

**G. 未接项与既有分歧（本期未改，逐条留档）**：

1. **隐形文件防护的实际行为是 fall-through 改判**，不是选型时「一起拒收」的措辞（见上）。
2. `ShelfView` 的「阅读状态」筛选与 `BookCover` 角标**只按进度判**，而书卡文案
   （`bookInfo.statusLabel`）**状态优先** ⇒ 同一本书手动标「已读完」后，角标与筛选可能不一致。
   （**既有分歧**，本期只统一了阈值来源，没有统一这个优先级。）
   **第 41 期已收口**：见下方「第 41 期实施记录」（`statusBucket` 统一三处口径）。
3. 「浏览服务器文件夹」**没接** —— `GET /api/libraries/source-dirs` 前端从来无调用点，
   向导里保持文本输入；另有 `?new=1` 与首次引导 `GuidedTourModal` 会叠加（既有行为）。
   **第 41 期已收口**：向导步骤②两处「浏览」按钮已接入该端点（见下方「第 41 期实施记录」）。

---

#### 第 41 期实施记录（收口 phase 40 未接项：浏览服务器文件夹 + 阅读状态优先级统一）

**主题**：收口第 40 期新建书库向导留下的两处未接项（见第 40 期 §G 第 2、3 条），**不新增产品形态**。
① 向导「内容来源」步骤接入 `GET /api/libraries/source-dirs`，让用户从服务器目录清单里挑来源目录，替代纯手输；
② 统一阅读状态判定优先级 —— `ShelfView` 筛选与 `BookCover` 角标复用 `readingThresholds.statusBucket`
（真实状态优先），消除「手动标已读完但书架筛选 / 封面角标仍显示在读」的不一致。

**后端零改动**：`api_library_source_dirs`（`novelforge/server.py:4009`）与前端 `api.librarySourceDirs`
（`frontend/src/lib/api.ts:3234`）第 40 期已实现，本期只是把后者接到界面；`tests/test_api_smoke.py:150`
那条「`/api/libraries/source-dirs` 返回 200」的接口契约**本来就在**，本期不新增后端用例。

**1. 浏览服务器文件夹**（`frontend/src/components/tools/LibraryWizard.vue`）：
- 步骤②「库根目录」「来源子目录」两输入框各加一个「浏览」幽灵按钮（`wizard-browse-root` /
  `wizard-browse-sub`），点击 `await api.librarySourceDirs()` 取回 `LIBRARY_SOURCE_DIR` 下的真实子目录清单
  （`{root, exists, dirs:[{name, path, entries}]}`），在该行下方弹**局部**浮层（v-if，不重建整页 DOM），
  每条显示子目录名 + 条目数（`wizard-browse-item`）。状态 `browse`（`LibraryWizard.vue:159`）、
  `openBrowseRoot`（`LibraryWizard.vue:188`）、`addCurrentFolder`（`LibraryWizard.vue:219`）。
- 选中回填：`root` 目标用绝对 `path`；`sub` 目标用 `path` 剥离 `root` 前缀得到的相对子目录名
  （与 `props.sourceDir` 同口径，沿用第 40 期「来源子目录相对 `LIBRARY_SOURCE_DIR`」的语义）。
- 保留 `touched.root` / `touched.sub` 既有手改标记语义：用户从清单选了就不被 `resyncDefaults` 覆盖。
- 加载中显示「加载中…」、空清单显示「无可用子目录」、拉取失败走 `ui.toast` 不崩（弹层不打开）。

**2. 阅读状态优先级统一**（`frontend/src/lib/readingThresholds.ts`）：
- 新增 `statusBucket(b, libraryId)`（`readingThresholds.ts:133`）：**真实状态行优先**，把 5 状态压成筛选三档 ——
  `finished` → 已读完；`reading` / `paused` / `abandoned` → 在读（过滤器 UI 仅三档，已开始的都进在读桶）；
  无状态行时按进度阈值兜底（含 percent 够高 → 已读完）。与 `statusOf` / `statusLabelOf` 同文件同源，
  **不造第三份三态拷贝**（项目铁律：判据只此一处）。
- `ShelfView.vue` 删除本地只按进度的 `statusOf`（`ShelfView.vue:296`），改调 `statusBucket(b, library.currentLibraryId)`
  驱动 `fStatus` 筛选；书卡文案 `bookInfo.statusLabel` 本就走 `statusLabelOf`，由此三处口径统一。
- `BookCover.vue` 角标由 `percentLabel(book.percent)`（只看进度）改为 `statusLabelOf(book, libraryStore.currentLibraryId)`
  （`BookCover.vue:96`），`CoverBook` 类型补 `status` 字段；跨库组件取当前库阈值当上下文、无当前库退回全局
  （与原有 `percentLabel` 的 fallback 一致）。
- **范围外（不动）**：`stores/library.ts` 的 `derivedStatus` 分面计数（进度口径，第 40 期已明确不在此期范围）。

**A. 单测**：前端用例数 **56 / 5 个 spec**（第 40 期 52 ⇒ +4：`readingThresholds.spec.ts` +4 状态桶用例 +
`LibraryWizard.spec.ts` +4 浏览契约）；`npm run test:unit` 全过；`vue-tsc --build` exit 0。
后端零改动 ⇒ pytest 基线 **691 例**维持绿（本期未碰后端）。
变异验证（强制）：① `statusBucket` 把 `finished` 也判成 `reading`（退化回旧逻辑）⇒ `readingThresholds.spec.ts` 相关用例红；
② `ShelfView` 的 `statusOf` 改回 `statusFromPercent(b.percent)`（忽略 status）⇒ 手动 `finished` 不进「已读完」桶的断言红；
③ 向导「浏览」按钮不调 `openBrowse`（`@click` 删掉）⇒ 弹层不出现、回填用例红。撤销后全绿。

**B. 浏览器冒烟**（真实 uvicorn 实例 + 独立临时根）：
- 向导步骤②点「库根目录」旁的「浏览」⇒ 弹出 `LIBRARY_SOURCE_DIR` 下子目录清单（含条目数）；点选一个 ⇒
  库根输入框回填绝对路径；「来源子目录」旁的「浏览」点选 ⇒ 回填相对子目录名（如 `comics`）。
- 一本书在详情页手动标「已读完」（`status=finished`，`percent` 仍 20%）⇒ 书架「阅读状态」筛「已读完」命中它、
  封面左下角角标显示「已读完」，与书卡文案一致（改前角标显示「在读」、筛选漏掉）。

**C. 锚点 / 文档**：本期新增的 `path:line` 锚点（LibraryWizard `:220/:228/:245`、readingThresholds `:133`、
BookCover `:96`、ShelfView `:280`）均按实测行号写入；`tests/check_doc_anchors.py` 复核 **硬错 0 / 疑似漂移 0**
（本期只在 `LibraryWizard.vue` 内新增、未改既有带锚点行，故不引入漂移）。
第 40 期 §G 第 2、3 条已反向标注「**第 41 期已收口**」。

---

#### 第 41 期实施记录（续）：书库存放改造 —— 多来源根 `source_dirs`、移除 import 模式

**主题**：库数据模型从「单 `root_path` + `source_subdir` + `mode(inplace/import)`」改为
「多个文件夹绝对路径 `source_dirs`（JSON 数组），仅就地引用」。compose 用
`LIBRARY_SOURCE_DIRS1..N`（+ 可选 `<N>_NAME`）声明**不定数量**来源根，序号从 1 连续、
首个缺号即停；未配置任何编号变量时回退单根 `LIBRARY_SOURCE_DIR`（默认 `/app/libraries`），老部署兼容。

`config.LIBRARY_SOURCE_ROOTS`（`[{name, path}]`）**仅用于两件事**：① 向导浏览树的根
② 建库 / 改库时一次性的边界校验（`config.normalize_source_dirs` 拒非来源根内的路径，跨根合法）。
**后端不反查「所属根名 / 相对子目录」** —— 绝对路径即唯一真值，层级信息由前端下钻选择时持有。

- **配置层** `config.py`：循环扫 `LIBRARY_SOURCE_DIRS1..N` → `LIBRARY_SOURCE_ROOTS`；
  `ensure_dirs()` 遍历多根；保留 `LIBRARY_SOURCE_DIR` 兼容别名（指向首根）。
- **数据层** `core/db.py`：`libraries` 加 `source_dirs TEXT`（JSON 绝对路径数组），
  删 `mode` / `root_path` / `storage_path` / `source_subdir` 四列；迁移**先 backfill 再 DROP**
  （现存 inplace 库 `source_dirs = json([root_path])`）。`source_dirs` 已进 `_LIBRARY_COLS`。
- **接口层** `server.py`：`GET /api/libraries/source-dirs` 返回多根 + `?root=<idx>&path=<sub>` 下钻；
  create / update 收 `source_dirs` 多根校验；`_library_dto` 输出 `source_dirs`（取代 `root_path` / `source_subdir` / `mode`）。
- **核心** `library` / `library_rules` / `migrate` / `watcher` / `server`：扫描 / 落盘 / 路径解析 /
  `_lib_id_of_path`（最长匹配）一律遍历 `source_dirs` 的绝对路径，移除 import 分支；
  `library.roots_of(lib)` = 解析 `source_dirs` JSON 得 Path 列表。
- **前端** `LibraryWizard` 移除「归属模式」步骤；内容来源步骤改为**多来源根浏览 + 逐层下钻 + 跨根多选**，
  提交 `source_dirs`（绝对路径），前端持有根名 / 相对子目录用于 chips 展示；
  `api.ts` / `LibrariesView` / 设置页同步。

**两个会让测试静默失败的真实 bug（本轮定位并修复）**：
1. `core/watcher.py` 模块顶层漏 `from . import library` ⇒ `_derive_targets` / `handle_file` 里
   裸名 `library.roots_of(...)` 抛 `NameError`，被 `except Exception: pass` 吞掉，**逐库扫描目标整组消失**。
2. `server.py` 的 `_publish_path_allowed` 内层 `for rp in _roots_of(lib)` 覆盖了外层成品目录变量 `rp`
   ⇒ 之后 `rp == g` 恒真，**建库时成品目录校验一律误报「与库根重叠」400**。内层改名 `lr`。

**验证**：后端全量 **690 passed / 0 failed**；前端 `npm run test:unit` **58 passed**、
`vue-tsc --build` exit 0。旧 `root_path` / `source_subdir` / `mode` / `import` 契约的用例全部改写为 `source_dirs`。
`docker-compose.yml` 改 `LIBRARY_SOURCE_DIRS1=/app/libraries` 并示范 `2/3` + `_NAME` 扩展。

---

#### 第 42 期实施记录（上游无新增 → 判定刷新 + 部分缺口；纯取证/文档）

**主题**：用户拍板「重新取证上游找新缺口」。先代理优先复核上游 `735876214/bookorbit` 的
`refs/heads/main` —— **仍为 `c292d6cc`**（与第 33 期取证同一 commit，无新提交、无新 tag），
「上游出了新版本、有新模块」的前提**不成立**。转而做**同一版本上的两件此前未系统做过的事**：
① 刷新 `bookorbit-module-inventory.md` §2 的逐行「判定」列；② 补一类此前未单独成表的
「**部分缺口**」（上游模块有、本项目只做了子集）。**本期零运行时改动**（不实现清单里的任何项）。

**A. 上游取证结论**：`git ls-tree` 对比 `c292d6cc..FETCH_HEAD` **0 提交 / 0 文件**；
`ls-remote` 权威确认 `refs/heads/main == c292d6cc`。⇒ 「按新版本找新模块」这条路本期**不可用**，
如实记录（**不虚构新缺口**）。

**B. §2 判定刷新（10 处，均已就地改在清单第二节表内）**：`book-metadata-lock` / `bookmark` /
`browse-counts` / `catalog` / `custom-metadata` / `reading-state` / `recommendation` 七项由
「漏项候选」改为「**已覆盖**」（第 34–36 期其实已落地，**判定列未回填**）；另订正 3 处**文档错误**：
1. 第 32 行 `health`：原记「本项目有 `/api/health`」——**没有**该路由，真路由是 `GET /health`
   （`novelforge/server.py:262`；白名单只含 `/health` + `/api/auth/login` + `/api/logout`）。
   第 31 期早已订正代码侧（并修了打错路径的契约测试），此表漏改。
2. 第 33 行（上游模块 `kobo`）：原记「已实现可用子集」——**未实现**。依据：`README.md:113` 明写
   「未做：Kobo 同步」、`docs/bookorbit/bookorbit-capability-gap.md:435`、设置页占位 `frontend/src/data/settingsNav.ts:344-363`；全仓无 `kobo*.py`。
3. 第 40 行 `metadata`：原记「`core/metadata.py` 对等（6 类）」——**高估**，实际仅 EPUB 全解析
   （+ 漫画/音频结构），**FB2 完全不支持**、MOBI/AZW3/PDF 无内容解析。

**C. 新增第六节「已覆盖模块的部分缺口」**（14 项，三分类）：**值得做 6**（系列缺册 / 作者排序键回填 /
书架首字母跳转 / 阅读尝试即重读 / 批注导出增强 / 系列折叠偏好上云）、**有价值但不做 5**、
**与定位或既有决策不容 6**（批注跨端同步 / 按设备重建位置 / Kobo 状态投影 / 通知清理 job /
通知 SSE 网关 / 孤儿封面清扫）。逐项带本项目 `文件:行` 锚点，**排期与否由用户决定**。

**D. 基线重取**：`bookorbit-capability-gap.md` §0.3 路由 **284 → 285**（第 41 期 +`GET /api/libraries/source-dirs`）、
表仍 **31 张**、`APP_VERSION="0.6.0"`。联动文档（`settings-inventory` / `feature-flows` /
`library-contract`）按第 41 期库模型关键字（`root_path`/`source_subdir`/`inplace`）复核**零命中**，无需改；
路线图历史记录里的旧表述**属历史事实，不动**。

**E. 验证**：后端全量 pytest **690 例 / 0 failed**（与第 41 期基线一致，纯文档改动无回归）；
文档锚点核验 **硬错 0**，疑似漂移 **26 → 11** —— 修掉 **15 处活跃文档锚点**（`bookorbit-capability-gap.md` 10 处、
`bookorbit-module-inventory.md` 5 处），**剩余 11 条全部位于逐期历史实施记录内**
（`roadmap-gaps-remaining.md` 的 `:859` / `:879` / `:1077` / `:1416` / `:1526` / `:1563-1565` / `:1617` / `:1721` / `:1730`），
按「历史实施记录里的旧行号一律不动 —— 改它等于篡改历史」的约定**不修**。

---

#### 第 43 期实施记录（部分缺口清账：§6.2-A「值得做」6 项落地）

**主题**：用户拍板做第 42 期取证产出的**全部 6 项**「值得做」部分缺口
（`bookorbit-module-inventory.md` §6.2-A）。本期是**能力落地期**（非取证期），
后端 + 前端 + 契约测试 + 文档一并交付。逐项落地实现位置见该文件**第七节**，此处只记语义决策。

1. **系列缺册**：判定**只在后端一处**（`library.series_gaps`）—— 按 `series_index` 数字集合求 `[1..max]` 的补集。
   ⚠️ **无序号不并入缺册**（否则每本没序号的书都凭空造一个「缺 1」）、**非数字序号也不并入**（不硬猜第几册），
   两者各自单列计数。前端只展示，不再自己算。
2. **作者排序键回填**：⚠️ 关键取舍 —— 排序名有两列，**只写派生态列 `sort_name`、绝不动用户覆盖列
   `sort_name_local`**（写后者等于冒充用户改过、界面误显示「已覆盖」并挡住抓取）。派生规则保守：
   拉丁两段 →「姓, 名」；≥3 段带小词表处理 `Le Guin` 一类；**CJK 原样返回 ⇒ 跳过**（填了等于没填）。
3. **书架首字母跳转**：分桶判据唯一源 `frontend/src/lib/shelfBuckets.ts`；**不做拼音**（要新增依赖且多音字会算错）
   ⇒ CJK 老实归 `#`。桶序固定 A–Z 升序、`#` 垫底（不跟随当前排序，否则按入库时间排时跳转条毫无规律）；
   桶数 <3 不显示（两三个桶的「跳转」只是噪音）。
4. **阅读尝试 / 重读**：新表 `reading_attempts`（一轮 = 开始读 → 读完；读完再开始 = 新一轮 `round` 递增）。
   ⚠️ **自动维护**挂在 `db.set_status`（进 reading 开轮、进 finished 收尾；搁置/弃读**不动**轮次）；
   `reset_reading_state` 从「三清」扩为**四清**（+ `attempts`，既有契约测试同步更新）；
   表已进 `ORPHAN_TABLES` / `REMAP_TABLES`。历史补录 `backfill_attempts` 只补「一轮都没有」的书。
5. **批注导出增强**：改**走后端**（`GET /api/annotations/export`，三格式 + 按书/库收窄，**只导活跃**）；
   前端由「纯前端生成 Markdown」改为 blob 下载 —— `/api` 一律要求 Bearer 头，`<a download>` 带不了。
6. **系列折叠偏好上云**：新增第 7 个偏好块 `shelf`。⚠️ **刻意只搬 `collapseSeries` 一项** ——
   其余书架字段（视图 / 排序 / 缩略图点击 / 筛选默认展开）是「这台设备怎么看书架」，仍只存本机；
   `shelfPrefs.save()` 起调 `notifyPrefsChanged()`，`applyRemote` 逐键挑 + `suppressing` 抑制回推
   （沿第 32 期 `displayPrefs` 范式）。首次无远端记录时 `collect()` 带上本机值登记 ⇒ **本机旧值自动上云**。

**防回归要点**：① 含 `book_id` 的新表必须过 `ORPHAN_TABLES` / `REMAP_TABLES`（`tests/test_remap_tables.py` 钉住）；
② 偏好块清单**两端一致**（`server.PREFS_BLOCKS` ↔ 前端 `PAYLOAD_BLOCKS`，`tests/test_prefs_shelf_block.py` 钉住）；
③ 缺册 / 分桶 / 派生排序键**各只有一处实现**，前端不再自己算；④ 不做假交互（无轮次就显空态、桶数不足不显示跳转条）。

**验证**：后端全量 **720 例 / 0 failed**（第 42 期基线 690 + 本期 30）；前端 `npm run test:unit` **62 例**（58 + 4）；
`vue-tsc --build` exit 0；浏览器冒烟（书架跳转条 / 系列缺册 / 阅读尝试 / 批注导出）见本期提交信息。

---

## 第 53 期 · 演播者实体补全（2026-09-24）

**需求来源**：用户从四个候选中拍板「演播者实体补全」—— 上游 13 个命名 token 中本项目 `fileops.PATTERN_FIELDS` 仅 9 个，`{narrators}` 是已记录的缺失 token；后端 `novelforge/**.py` 零 `narrator` 字样；`audio.py` 只做轨道统计、从不解析标签，演播者从未被提取，重命名规则无法用上。

**功能范围**：
1. **音频标签解析（前置，零依赖）**：新增 `core/audio_meta.py`，纯标准库解析 m4b/mp3/m4a/opus/ogg/flac 的演播者（MP4 `©nrt` / Vorbis `NARRATOR` / ID3v2 `TXXX`·演播·旁白），解析失败降级为空；扫描期经 `audio.first_audio_file` 落 `books.narrators`（列表列，与 `tags` 同构）。
2. **演播者实体 + 排序名**：新增 `core/narrators.py`（镜像 `authors.py`：derive_sort_name / backfill_sort_names / sort_name_of / effective / set_sort_name / narrator_books）+ db `narrators` 表（`name` PK + `sort_name` / `sort_name_local` 两列分列；无头像 `hasPhoto=—`、软删同作者现状即不做）；`library.narrators_list()` / `narrator_books()` 聚合（无关联表，扫 `books()`）。
3. **命名 token `{narrators}`**：`fileops.PATTERN_FIELDS` 与前端 `RENAME_TOKENS` 同步加 `{narrators}`，`fill_pattern` 多值 `", "` 连接；`FileNamingPage` 缺口说明由「缺 5」改「缺 4」。
4. **按书替换**：`fileops.METADATA_FIELDS` 加 `narrators`，`/api/books/{bid}/metadata` 经 override 层接受（与 `tags` 同构：非空=覆盖、空串=撤销、null=清空）；详情页 `MetadataEditor` 编辑元数据表单加「演播者」字段。
5. **展示**：`BookDetailView` 信息栅格 + `AudioPlayerView` 作者下方展示演播者（零外部请求）。
6. **接口**：`/api/narrators`、`/api/narrators/{name}`、`/api/narrators/{name}/sort-name`、`/api/narrators/sort-name/backfill`（形态对齐 authors 端点）。

**防回归要点**：① 命名 token 两处必须一致（`PATTERN_FIELDS` ↔ `RENAME_TOKENS`），`tests/test_naming_tokens.py` 钉死（本期顺带把断言 9→10 + 增 `{narrators}` 展开测试）；② 排序名两列分列，派生/回填**只写 `sort_name`、绝不动 `sort_name_local`**（写后者=冒充用户改过、误显「已覆盖」并挡抓取），与 `authors` 铁律逐字对齐；③ 元数据只落 DB、绝不写回文件，override>online>opf 三层 + 三道正交闸同样适用；④ 列表型字段（tags/narrators）清空哨兵回退空列表、批量合并按列表解析，须同进 `_CLEARABLE` / `_META_FIELDS` / `_meta_out` / `metastore._opf_value`；⑤ 刻意差异：不新增独立浏览维度（BrowseView 第 34 期已定不做）、无头像。

**验证**：后端全量 **794 例 / 0 failed / 0 error**（第 42 期基线 690 + 第 52 期 30 + 本期 26 + 其它）；新增 `tests/test_audio_narrators.py`（解析器 + 扫描落盘）、`tests/test_narrator_entity.py`（实体/排序名/软删/接口）；`vue-tsc --build` exit 0、`npm run build` + `npm run deploy` 已同步 `novelforge/static/v2`；文档（module-inventory / settings-inventory）narrator 由「漏项候选/不做」改判「已覆盖」，计数 已覆盖 46→47、不做 16→15。

## 第 54 期（2026-09-26）：重开两项判「不做」的能力 —— 语义向量 + 精确阅读位置

用户拍板把 module-inventory §4.2 仅剩的两项「有价值但不做」重开：**`embedding` 语义向量**
与 **`position-converter` 阅读位置换算**。至此「有价值但不做」清单实质清零
（`email` / `migration` / `file-write` / `seed` / kobo span / kepub DOM 等仍按原判不做，
理由未变）。详细落地锚点见 `docs/bookorbit/bookorbit-module-inventory.md` 第 54 期一节，此处只记
决策与防回归要点。

1. **语义向量（`core/embed.py`）**：默认 LSA（TF-IDF + SVD，纯 numpy、离线零下载），
   可选本地 transformer（`CACHE_DIR/embedding-model` + 自备依赖），**绝不引远程 API**；
   新表 `book_embeddings`（float32 BLOB + `model_tag`）进 `REMAP_TABLES` / `ORPHAN_TABLES`；
   `POST /api/embeddings/recompute` + 两条自愈钩子（`/similar` 缺向量、扫描完成后；
   单飞闸 + 600s 节流，收尾进 conftest `_quiesce_background`）。
2. **推荐整合**：`similar_books(…, vectors=)` 两书都有向量走语义余弦、缺向量**逐对回落**
   词袋；「实质重合」门不动 —— 向量只管排得好不好，门管该不该出现。接口出参不变。
3. **精确位置（`core/epub_cfi.py`，唯一真值源）**：CFI 生成/解析 + CFI→XPointer 兼容层；
   标准库 `xml.etree` 解析（坏书一律安全回落）；**字符偏移 = textContent 坐标系**
   （后端 ET text/tail 模拟 DOM childNodes，前端 `textContent.length`，同尺度才能往返）；
   `progress` 加 `cfi` 列，**非 NF 来源的进度写入一律清空 cfi**（防「章已变、CFI 挂旧章」）；
   进度端点 `offset` 进 / `cfi`+`offset` 出，前端不在 JS 里解析 CFI。
4. **KOReader 刻意保守**：`from_nf` 下发仍为章首 XPointer（kosync 只认 XPointer，
   真 CFI 反而破坏解析）；`to_nf` 仅兼容识别 `epubcfi` 取章序号；kobo span / kepub DOM
   仍不做。
5. **防回归要点**：① `book_embeddings` 漏登记搬迁/孤儿清单会被 `test_remap_tables.py`
   直接红（契约按 sqlite_master 实测断言）；② 语义向量必须确定性（词表显式定序，
   否则两次重算余弦漂移 → 推荐列表跳）；③ 恢复链路换算不了精确偏移必须回落
   「章 + 全书百分比」（与改造前行为逐字一致），保存进度绝不因 CFI 失败；④
   `test_reading_state.py` 进度归零断言随响应加法演进更新（恒带 `cfi`）。
6. **验证**：后端全量 **820 例 / 0 failed**（基线 794 + 本期 26：test_embeddings 14 +
   test_epub_cfi 12）；前端 `type-check` / `build` / `deploy` 全绿并同步
   `novelforge/static/v2`；`requirements.txt` 新增 `numpy>=1.26`。

## 第 55 期（2026-09-26）：新增书库就地弹窗 + TXT 阅读（三期路线图第一期）

用户提了五项需求并拍板分期：**55 期 = ②就地弹窗 + ⑤TXT 阅读**（56 期 = 偏好同步 +
进度轮询提示；57 期 = 元数据提供商页 + 插件市场 + 手动书源）。①③④ 的口径与边界见
对话记录，本文件只记本期落地。

### ② 新增书库就地弹窗（不跳设置页）

- 方案：`LibraryWizard` 本就自带 z-50 遮罩外壳，缺的只是各宿主页没有 `types` /
  `sourceRoots` / `libs` 三份数据（此前只有书库管理页的 `reload()` 拉过）。收拢为
  **全局单实例**：新 store `frontend/src/stores/libraryWizard.ts`（`show()` 现拉
  `/api/libraries` 再开浮层；`created()` 关浮层 + 刷新全局书库实体 + 宿主一次性回调），
  App.vue 挂**一份**（多处各自挂会叠两层 z-50 关不掉 —— LibrariesView 第 40 期注释的
  互斥约定由此天然满足）。
- 改造入口（8 处里 7 处）：书架空态（新 `createLib`；顶栏 `manageLibs` 保留为「管理」语义）、
  首屏提示条、引导第一步 CTA（`cta.to` 变可选，缺省 = 就地弹窗）、侧栏「库·新增」、
  本地转换 0 库文案、收书目录 0 库文案、探索发现与两处拦截 toast 文案（去掉「去设置页」指向）。
  `?new=1` 老入口经 store 继续可用；LibrariesView 不再自带一份向导。
- 契约测试同步：《tests/test_first_run_contract.py》`test_建库出口就地弹窗不跳设置页`
  （改断言「四个文件都 import useLibraryWizardStore」+ NOTICE/TOUR 不得残留
  `/settings/libraries`）、书架用例补 `createLib` 断言。新增
  `frontend/src/stores/libraryWizard.spec.ts`（4 例）。

### ⑤ TXT 阅读（转 EPUB 为主 / 原生分章兜底）

- **分章真值源**：`core/detect.py`（regex 非锚定 + 缩进降级 + AI 可选）本就是唯一实现，
  本期**新增契约测试** `tests/test_detect_chapters.py`（7 例）钉住出参形状、首个边界前
  内容被丢弃（docstring 原先写反，已按实际行为订正）、置信判据、缩进降级、merge 与
  cfg 无 key 等同正则；并显式钉住「**正文里出现「第 N 章」也会被当边界**」这条现状口径
  （它同时决定出版成品目录，要改必须独立评估）。
- **派生 EPUB 缓存**：新增 `core/txtcache.py` —— TXT 优先转一本最小 EPUB 落
  `CACHE_DIR/txt-epub/<book_id>/`（**派生缓存**：不进书库、不落成品目录、可重建），
  阅读器于是走**完整 EPUB 链路**（目录 / 批注 / 进度 / 资源全免费复用）；转不动
  （空文本 / 编码全坏 / >20 MB / 构建失败）则记**失败标记**并回落**原生分章**
  （`native_chapters` / `native_chapter_html`，与 `library._reading_list` 同形状）。
  形态由缓存里的**源文件指纹**锁定（源没变不换路线，避免章节号漂移让批注跳错章）；
  缓存重建走「临时文件 + `Path.replace`」原子落盘。
- **`epub_builder.build_epub(..., nav=False)`**（新增向后兼容开关，默认 `True` 逐字不变）：
  派生 EPUB 不把 nav 页放进 spine ⇒ 章节 index 0 基，**与原生兜底索引空间对齐**；
  NCX/目录照常写入（标题不丢）。
- **接口/前端**：`library.book_detail` 为 TXT 下发章节树（派生优先）；`GET /api/books/{bid}/chapter/{index}`
  打通 TXT（派生优先、原生兜底，其它格式仍 400）；`BookDetailView.canRead` 放行 TXT。
  **前端阅读器零改动**（后端归一成同一形状）。
- 契约测试：`tests/test_txt_reading.py`（6 例：详情+可读、超大回落且无半成品残留、
  形态锁定、源变更重建、非 EPUB/TXT 仍 400、缓存不落库根）。

### 验证
- 后端全量 **833 例 / 0 failed**（基线 820 + 本期 13：test_detect_chapters 7 + test_txt_reading 6）；
  前端 `test:unit` **66**（62 + libraryWizard 4）、`type-check` / `build` / `deploy` 全绿
  （已同步 `novelforge/static/v2`）。

## 第 56 期（2026-09-26）：多设备进度提示 + 偏好同步感知（三期路线图第二期）

用户拍板：③ 走**轮询 + 提示**，**不上 SSE**（全仓既有禁令维持：通知网关 / book-move 逐本
进度都因此走轮询）、**绝不静默挪动阅读位置**。

### A. 多设备进度提示（阅读器内）

- **后端加法**：`PUT /api/books/{bid}/progress` 回带本次写入的 `updated_at`（`db.set_progress`
  改为返回时间戳）；`GET` 也带回 `updated_at`（第 54 期以前它只在 db 层存在、API 层丢掉了）。
  **没有进度行时不给 `updated_at`** —— 不能造一个 0 当基准（否则首次进阅读器就弹提示）。
- **前端**：`ReaderView` 记 `ownWriteAt`（载入时读到的 + 每次 PUT 回带的），每 **8s** 轮询
  `getProgress`；只有「时间戳更新（>1s 容差）**且位置确实不同**」才渲染提示条
  「其他设备更新了进度：第二章 · 50.0% → 跳过去 / 忽略」。**只在用户点「跳过去」时**
  才 `loadChapter` 并立刻把本机位置写回（避免下一轮重复提示）；点「忽略」保持不动。
  `document.visibilityState !== 'visible'` 不轮询（与阅读时长 accrual 同一条纪律）；
  `onBeforeUnmount` 停轮询。提示条插在进度条与正文容器之间，**不触碰 `html`/`contentRef`** ⇒ 不重排正文。
- 契约：`tests/test_progress_updated_at.py`（4 例：写入回带且递增 / GET 同值 / 无行不给基准 /
  其它来源（KOReader·Komga·完成标记）写进度同样刷新时间戳且仍清 cfi）；
  `frontend/src/views/ReaderView.remoteProgress.spec.ts`（4 例：只提示不自动跳 / 跳过去才跳且写回 /
  忽略保持不动 / 时间戳未更新不打扰）。⚠️ 该 spec 只伪造 `setInterval`+`Date`（保留真
  `setTimeout`），否则 `flushPromises()` 会挂住 —— 与既有 `ReaderView.spec.ts` 的假时钟约定一致。

### B. 偏好同步感知（跨设备「感觉得到」）

- **变更信号**：不新增表/列 —— 设备行本来就有 `last_seen`（每次上报刷新），用它当「远端是否更新」。
- **判定抽成纯函数** `prefsSyncDecision({remoteSeen, localSeen, hasPending})`
  ⇒ `noop`（≤1s 容差，本机回环不误判）/ `apply-remote`（本机无未推送改动：沿用既有
  「服务端为准」静默应用 + 顶栏「已同步其他设备偏好」胶囊 8 秒自隐）/ `conflict`
  （本机有未推送改动：**只置提示、绝不覆盖**，顶栏「偏好有更新」胶囊点进设置页显式选）。
- **时机**：`init()` 起 15s 轮询（app 级单例；`booted` 且页面可见才真发请求）；`boot`/`push`/
  `applyProfile` 后更新「已认账」时间戳 `acceptedSeen`。⚠️ `boot()` 的启动裁决语义**不变**
  （启动那一刻本机 pending ⇒ 本机为准并推；否则服务端为准）—— 本期加的只是一层「运行中感知」。
- 契约：`frontend/src/stores/prefSync.spec.ts`（5 例，纯函数：远端旧/同 ⇒ noop、1s 容差、
  无 pending ⇒ apply、有 pending ⇒ conflict、无基准 ⇒ noop）。

### 验证
- 后端全量 **837 例 / 0 failed**（基线 833 + 本期 4）；前端 `test:unit` **75**
  （66 + prefSync 5 + ReaderView.remoteProgress 4）、`type-check` / `build` / `deploy` 全绿。

## 第 57 期（2026-09-26）：元数据提供商目录与「提供商」页（三期路线图第三期 · A 段）

范围（用户拍板）：① 元数据源插件市场 / 更多第三方源 / 系列级元数据；④ 手动个性化书源
（**zlibrary 专用下载不做**——盗版分发平台，已向用户说明，以「通用书源 + 投递」替代）。
出网口径修订：**默认零外部请求；仅插件市场与已启用的元数据源按用户显式配置出网**，
其余（前端 CDN / 字体 / 更新检查）仍严格零外部。

**A 段（本期已落地）：提供商目录 + 设置页「提供商」按上游截图 1:1 重做**

1. `core/metasources.SOURCES` 从 2 条扩成**上游那 14 家的目录**（四组：一般书籍目录 7 /
   有声读物 3 / 漫画和小说 2 / 极权目录 2），每条带 `group / home / note / implemented /
   needs_config / key_field / config_hint`。⚠️ **`implemented` 是诚实标记**：本项目真正能抓的
   只有 `openlibrary` / `googlebooks`，其余 12 家只列出、**不给开关**（能点但没用 = 假交互），
   前端如实渲染成「未实现 · 可经插件市场安装」。契约 `IMPLEMENTED == _FETCHERS.keys()` 钉住
   两侧一致（`tests/test_metadata_providers.py`）。
2. 新端点 `GET /api/metadata/providers`：目录 + 分组 + `已启用 N/总数` + `needs_setup`
   （「需要设置」过滤器的唯一数据源）。`enabled` 的真值源仍是 `metadata_fetch.sources`
   （启用 = 在列表里、顺序即优先级），不新开一份状态。
3. `/api/metadata/probe` **对未实现的家不发外呼**（如实回报「未实现」）——否则用户会以为
   自己网络坏了；`metafetch.plan` / `online_candidate` 也只在**已实现**的源里选（配置里
   混入未实现 id 不会白跑往返，也不会炸）。
4. 设置页 `MetadataPage.vue` 的 providers 区块按上游那页重做：分组标题 + 每行
   「图标首字 / 名称 / 启用与顺序徽标 / 需要设置 / 未实现 / 备注」+ 上移下移 + 官网 +
   **开关**（未实现的家渲染成 `—` 而不是开关）+ 顶部「已启用：N/14」+ 过滤器
   （全部 / 已启用 / 需要设置）+ 搜索框 + 连通性检测。
5. 契约测试 `tests/test_metadata_providers.py`（8 项）：注册表 14 家 / 四组、实现清单一致、
   默认顺序只含已实现、分组排序、未实现源检索不抛、端点形状与计数、探测跳过未实现
   （spy 断言**零外呼**）、配置混入未实现源时 plan 不炸。

**B 段（本期已落地）：14 家提供商全部接入 + 书源表单化；插件市场取消**

用户拍板（逐字）：「全部 14 家都写（免 Key 的直接可用；需 Key 的做成「填 Key 即可用」；
抓取型的也写但标注「易失效」）」「同页但保留「提供商」分区标题（页面仍叫「元数据来源」）」
「**市场的任务取消**」「做：表单化 + 逐源连通性自检」。

1. **14 家全部真能抓**（原判「只维持内置 2 源」作废）：
   - 出网收口：新增 `metasources._get_json` / `_get_text` —— 14 家**只经这两个函数**访问公网，
     于是解析逻辑可完全离线回归（契约测试只 monkeypatch 这两个口），错误码文案也只有一处
     （429 / 401 / 403 有专门中文说明）。
   - 免密钥即用 5 家：Open Library、Google Books、**iTunes**（Search API）、**AudNexus**、
     **RanobeDB**（`/api/v0`，两段式：`/books` 拿 id → `/book/{id}` 补作者/出版社/简介；
     官方未公布封面 CDN 前缀 ⇒ **封面留空而不是拼猜测 URL**）。
   - 填密钥即用 3 家：**Hardcover**（`api.hardcover.app/v1/graphql` Bearer Token）、
     **Comic Vine**（`api_key`）、**Aladin**（TTBKey，`output=js` 的响应带前后缀 ⇒ `_first_json`
     用 `raw_decode` 抠第一个 JSON 值）。
   - **页面抓取型 6 家**：Amazon、Goodreads、Kobo、Audible、Libro.fm、Lubimyczytac
     （Kobo 走 `__NEXT_DATA__` 递归扫描；其余正则提取）。⚠️ **如实标注 `fragile=True`**
     （页面「易失效」徽标）——真实可用性**无法离线验证**（反爬 / 改版），代码只保证
     「结构未变时解析正确 + 失败一律回落空列表」。
   - 注册表 `SOURCES` 14 家全 `implemented=True`，新增 `fragile` 与 `key_field`；
     `IMPLEMENTED == _FETCHERS.keys()` 契约继续钉住（防漏接）；`DEFAULT_ORDER` 仍只开
     2 家（14 家都能用 ≠ 默认全开：每家多一轮外呼且易被限流）。
2. **密钥通用化（三处同步）**：`config.DEFAULTS["metadata_fetch"]` 新增
   `hardcover_api_token` / `comicvine_api_key` / `aladin_ttbkey`；`server.EDITABLE` 同步；
   `_mask_metadata_fetch` 改为**按注册表 `key_field` 循环掩码** + 回显 `has_<键名>`；
   `metasources.options_for(mf, sources)` 成为唯一拼装口（`metafetch.plan` / `online_candidate` /
   `series_meta.fetch_one` 共用，原先各自写死 googlebooks 的写法一并删除）。
   `/api/metadata/probe` 对**缺密钥的家不发外呼**（如实回报「需要设置」）。
3. **设置页「元数据来源」收尾**：行内新增「易失效」徽标；底部密钥区**按注册表渲染**
   （哪家有 `key_field` 就出现哪个输入框 + 已设置/未设置）；未接入分支保留为防御；
   「未支持」卡订正为真实剩余缺口（跨源字段级合并、按语种自动重排源序）。
4. **插件市场取消**：57-A 引入的「可经插件市场安装」措辞与断言全部清除（页面、测试、文档、
   记忆），并在 MEMORY 记明**取消**（不再排期）。出网口径因此收敛为
   **「默认零外部请求；仅已启用的元数据源按用户显式配置出网」**。
5. **书源表单化 + 逐源自检**：`SourcesView` 新增「手动添加（表单）」卡片（基础 / 搜索 /
   取书 / 分章 四段，字段与 `sources/rules.py` schema 一一对应）+ 前端必填校验
   （另加写盘文件名字符集）+ 「测试（不保存）」；列表每条加「测试」按钮。后端新增
   `POST /api/sources/test`：先 `validate_rule` 逐条回错误，通过则用 `make_rule_class` 建
   **临时类**经 `DownloadManager.test_source` 试搜一次 —— **绝不写盘**（写盘唯一入口仍是
   `store.add_rule`），运行期错误转成文案而不是 500。

**契约测试**：`tests/test_metadata_providers.py` 改写为 14 家全实现口径（含
「密钥键名三处同步」「探测对缺密钥的家零外呼」「回显按注册表掩码」）+
新增 `tests/test_metasources_parsers.py`（14 家解析全离线：注入假响应断言字段映射、
空响应/异形响应回落空列表不抛、两个解析小工具）+ 新增 `tests/test_sources_test_endpoint.py`
（校验错误逐条、试搜返回命中且**不落盘**、按名字试已注册源、未知名字 404、运行期错误转文案）。
修测试时顺带修掉三个**真实缺陷**：全称语言（"english"）未归一、`_first_json` 吃不掉尾随分号、
列表里混入非对象元素会抛。

**验证**：后端全量 **870 例 / 0 failed / 0 error**（57-A 的 845 + 本期 33 - 改写 8）；
前端 `type-check` / `test:unit`（75）/ `build` / `deploy` 全绿并同步 `novelforge/static/v2`。

**C 段（本期已落地）：系列级元数据四字段编辑入口**

原计划的「系列级元数据补全」经核查发现**后端本就齐备**（`series_meta.FIELDS` 四个字段
description / publisher / first_year / tags 都有本地覆盖列、`state()` 逐字段明细、
`POST /api/series/{name}/meta` 白名单校验），缺的只是**前端入口**：`SeriesMetaPanel` 当时
只让编辑「简介」，出版社 / 首发年 / 题材是只读展示。

1. `SeriesMetaPanel.vue` 重写：一次编辑四个字段（简介 textarea + 出版社 / 首发年 / 题材
   三格），保存时**四字段一起提交**；每个字段各自显示「本地」徽标与 **↺ 恢复**（简介在头部
   「↺ 恢复在线」）—— 恢复**只提交该字段的空串**（后端 `set_local` 语义：空串 = 撤销该字段覆盖），
   绝不牵连其它字段；未覆盖时标出来源（**成员书聚合** / 在线），空值也保留恢复入口
   （否则覆盖成空后再也回不到在线值）。
2. **首发年在界面侧挡一道格式闸门**（4 位年份或空）：写坏值不如不写，库里留个永远匹配不上的
   年份没有意义。
3. `SeriesDetailView.vue` 把 `meta_state` 透传给面板（`load()` 里同步，含失败清空）。
4. 新增 `frontend/src/components/book/SeriesMetaPanel.spec.ts`（7 项，全部**盯 payload**）：
   四字段一起提交 / 题材用「、」连接 / 首发年非法不提交 / 留空合法 / **单字段恢复只发单字段** /
   简介恢复只发 description / 展示态来源标注与空态文案。
   ⚠️ 这份 spec 当场抓到一个**真回归**：我重写面板时把「简介 → 恢复在线」入口漏掉了，
   是测试先红才发现的 —— 与项目既有教训一致（展示变了不会被发现，payload 变了才会）。
5. 后端语义另做一次离线往返验证：四字段覆盖 → 单字段清除（其余字段覆盖保留）→
   题材顿号串解析成列表，与 spec 的假设逐条对齐。

**验证**：前端 `test:unit` **82**（75 + 7）/ `type-check` / `build` / `deploy` 全绿；
后端未改动（故全量 870 仍成立）。

**D 段（用户反馈后调整）：凭据搬到对应提供商**行内**（不再集中堆在底部）**

用户看页面后指出：密钥应像上游那样**挂在该提供商自己那一行**（截图里 Google Books 行内给「API 密钥」、
Hardcover 行内给琥珀警告 + 「API 密钥」、Comic Vine / Aladin 同理，且每行带「测试」）。照此改造：

1. **每行「配置 ▾」**（`hasConfigSection(p)` = 注册表 `key_field` 非空，当前 4 家）：
   展开后在**该行下方**渲染 —— 需要设置时先给琥珀警告条、密钥标签 + 输入框（`key_label` /
   `key_placeholder` 由**注册表**给，前端不另写一份）、提示行、以及「测试 / 保存 / 清除」。
2. **行内「测试」是只读的**：把**输入框里当前（可能还没保存）的凭据**用 `keys` 覆盖传给
   `POST /api/metadata/probe`，**不落盘** —— 否则只测得到「上次保存的旧值」，或者被迫为了测试
   先保存一次（把「试一下」变成写操作）。运行期仍复用既有中文错误口径。
3. **「保存」才写配置**（走既有 `setVal` + `saveSection('metadata')`）；空串 = 清除（后端语义），
   另有显式「清除」按钮。保存后重拉目录刷新「已设置 / 未设置」与警告条。
4. **删除底部集中「密钥」区** —— 同一件事不留两个入口。
5. 注册表补 `key_label` / `key_placeholder`（Google Books「API 密钥」/ Hardcover「eyJ...」/
   Aladin「TTB 密钥」），契约新增 2 项：行内测试「传 keys 用 keys、未传沿用已保存值、且都不落盘」+
   四家文案字段齐备。

**真浏览器实测**（playwright + Edge + 隔离后端）：4 个「配置 ▾」按注册表出现；展开 Hardcover →
警告条 + 输入框 + 测试/保存/提示齐全；**填草稿凭据点「测试」真的出网**（Hardcover 回 401 ⇒
「被拒绝（401）：可能需要 API Key…」）且配置**未写入**；「保存」→ 配置落库（掩码回显、
输入框清空、显示「已设置」、出现「清除」）；「清除」→ 清空并退回「未设置」+ 警告条。
（过程中我把「保存」按钮定位到了页面上另一个同名按钮，误判过一次「保存无效」——是**定位问题**，
不是代码问题，改用面板内 scoped 定位后一次通过。）

**验证**：后端 `test_metadata_providers` **13 项**全过（11 + 新增 2）；前端 `type-check` /
`test:unit`（82）/ `build` / `deploy` 全绿。

**E 段（续做）：行内配置从「一个密钥」升级为「注册表声明的配置项列表」**

D 段只支持每行一个密钥，而上游那页每家的配置项并不一样（Amazon 要 Cookie、iTunes 给封面
分辨率、Kobo 给国家/语言、Audible 给地区）。所以把机制做成通用的：

1. **注册表 `config_fields` 是唯一真值源**：每项 `{key, opt, label, type, options?, placeholder?, hint?}`
   —— `key` = `metadata_fetch` 下的配置键名，`opt` = 传给 fetcher 的 `opts` 键名
   （缺省 `api_key`），`type` ∈ `secret | select`。四家密钥家的声明照旧，只是从
   `key_field` / `key_label` / `key_placeholder` 三个散字段**收敛成一份**：
   `provider_catalog()` 把头一项派生成这三个旧字段（前端零改动），`key_field_of()` 也从它派生。
2. **新增 5 个抓取参数并让抓取器真的用上**（不是摆设）：
   - `amazon_cookie` → 真的加 `Cookie` 请求头（空串不加，避免空头更容易被拦）；
   - `itunes_cover_resolution`（high 1000×1000 / standard 100×100）→ 改 `artworkUrl100` 尺寸段；
   - `kobo_region` + `kobo_language` → 拼进搜索 URL 的「/区域/语言/」两段（缺配置回落 us/en）；
   - `audible_region` → 决定分站域名（`api.audible.com` / `.co.uk` / `.de` / `.co.jp`，未知回落 us）。
   五处配置键同步进 `config.DEFAULTS` + `server.EDITABLE`；**掩码改为遍历
   `metasources.secret_fields()`**（Cookie 也是凭据，一并掩码）。
3. `POST /api/metadata/probe` 新增 `configs`（整行字段草稿覆盖，**不落盘**；早期 `keys` 仍兼容）；
   行内「测试」把该行**所有**字段的当前值带过去。
4. 前端行内面板按 `type` 渲染：`secret` → 掩码输入（标签带「已设置/未设置」）、`select` → 下拉；
   「保存」写被改过的字段、「重置」把整行置空（secret = 删除，select = 回落默认）。
5. **修掉一处真实的不一致**（浏览器验证时发现）：行内改动原先只存在组件局部，点**页面自己的
   「保存」**不会落库（用户会以为存了）。现在 `setDraft` 同时写进页面级配置草稿 ——
   两种保存路径都生效；静默态 secret 仍是后端的掩码值，而掩码值在后端是「不修改」语义，安全。
6. 契约：`test_metadata_providers` 改为**按注册表全量比**（配置键 = DEFAULTS 键 ⊂ EDITABLE，
   掩码集合 = 全部 secret），彻底消灭「手写键名清单漏项」；`test_metasources_parsers` 新增
   4 项盯「参数真的进了请求」（Cookie 头 / 尺寸段 / URL 两段 / 分站域名）。

**真浏览器实测**（playwright + Edge + 隔离后端）：8 个「配置」按钮（= 注册表里有
`config_fields` 的家）；Amazon 面板 = COOKIE 密文输入 + 复制提示；iTunes = `high/standard` 下拉；
Kobo = 国家/语言双下拉且当前值取自配置；改国家 → **行内「保存」落库** `kobo_region=uk`；
再改 → **页面全局「保存」也落库** `ca`（第 5 条修复的直接验证）。

**验证**：后端全量 **877 例 / 0 failed**；前端 `type-check` / `test:unit`（82）/ `build` / `deploy` 全绿。

⚠️ 期间踩到两个**验证方法**上的坑（已记入记忆）：① 页面上有多个同名「保存」按钮，
必须 scoped 定位或按序 nth，否则点到页面的全局保存；② 空闲书库会弹新手引导遮罩，
会拦掉所有点击（先关掉再操作）。

## 第 58 期（2026-09-26）：跨源字段级合并（+ 一项真实联网验证抓到的缺陷修复）

**动机**：此前一直是「取匹配分最高的**一条**候选，所有字段都用它」—— 于是「A 源年份规范、
B 源简介齐全」时，落库的只有赢家那一套。本段改成**逐字段择优**。

### 一、合并本身（`core/metafetch.py`）

1. **前提是门槛，不是热情**：只有 ``score >= max(MERGE_MIN_SCORE=0.7, 0.9 × 最佳分)`` 的候选
   才允许参与 —— 合并的收益是「字段更全」，风险是**把同名不同书的字段拼起来**
   （造出一个从未出版过的组合，且写进库后不可逆）。不够格就**逐字回到旧行为**。
2. **择优规则可预期**：`FIELD_TRUST` 表给「哪个字段更信哪家」——年份/语言/ISBN 信
   Open Library（它的字段最规范）、简介/封面信 Google Books、题材信 Open Library；
   表里没有的（书名/作者）按候选分数。命中信任源者**插队**，其余按分数、同分保持源顺序。
3. **题材是合并而非择优**：多源题材按出现顺序去重拼起来（上限 8），黑名单照旧生效 ——
   各家的题材本来就不重合，取某一个源反而信息更少。
4. **逐字段记来源**：`changes[field] = {from, to, source, score}` 里的 `source/score` 现在
   是**该字段自己**的来源（合并后同一本书不同字段可能来自不同源），另有整条
   `merged_from = [源…]`（空 = 未合并）。`online_candidate`（详情页「在线建议」）走**同一套**
   规则并回传 `field_sources` —— 两处口径必须一致，否则同一条数据两种答案。
5. **可回退**：新增 `metadata_fetch.merge_sources`（默认开；关掉即回到只用最佳候选）。
   合并**只改「选值」，不改「写不写」**：字段策略 / 锁定（`meta_locks`）/ 用户覆盖三闸照旧生效。

### 二、真实联网验证（这次真的出网了）

隔离配置下用 OpenLibrary + iTunes 跑真书（`Dune`），实测结论：

- **合并确实发生**：两家各给 1.0 分候选（`openlibrary` 有出版社无简介、`iTunes` 有简介无出版社）
  ⇒ `merged_from = ['openlibrary','iTunes']`，**简介来自 iTunes、出版社/年份/语言来自 OpenLibrary**；
  **关掉开关**立刻退回「只用 OpenLibrary」且**简介为空** —— 旧行为的损失被实测复现，收益与代价都看得见。
- **两个真实世界事实**（写进文档，免得后面又以为是自己写错了）：
  ① **Google Books 匿名会 429**（本机实测），错误文案与之相符 —— 这也正是那个 Key 配置项的意义；
  ② **iTunes 的简介带 HTML**（`<b><b>Frank Herbert's…`）。
- ②是一个**真实缺陷**，已修：候选入口（`metasources._entry`）统一走新的 `_strip_html()`
  （剥标签 + 还原 `&amp;` 等实体，零依赖），书名/作者/出版社/题材一并处理；契约新增一条
  「带 HTML 的简介会被剥标签」，并**真实联网复验**：简介来源仍是 iTunes，且不再含标签。
  这一条只有真联网才抓得到 —— 单测的假响应是我自己写的，写不出「人家真的给 HTML」这件事。

**契约**：新增 `tests/test_metafetch_merge.py`（9 项：缺字段由次优源补上 / 相对门槛 /
绝对门槛 / 题材多源合并去重 / **关掉开关逐字回到旧行为** / 信任源同分插队 / 合并只改选值
（锁定与用户覆盖照旧）/ `online_candidate` 与 `plan` 同规则 / **信任表键必须是合法字段名** ——
后一条是测试抓到的真 bug：`FIELD_TRUST` 我最初写成书目的 `year`，而遍历的是字段名 `date`，
**不报错、只静默失效**（信任表形同虚设），已修并加契约钉住。

**验证**：后端全量 **887 例 / 0 failed**；前端 `type-check` / `test:unit`（82）/ `build` / `deploy` 全绿。

**界面**：预览表格逐字段标出来源（`· openlibrary`）、行上标「合并自 N 源」；
「自动抓取」页新增「跨源字段级合并」开关（含门槛说明）。

## 第 59 期（2026-09-26）：14 家元数据来源「真联网体检」工具

**动机**（用户点名）：我有能力真出网（第 57 期实测 Hardcover 回 401、第 58 期实测
OpenLibrary + iTunes 双源命中），那就别只把「谁好用」留在会话里 —— 做成**一次能跑、结论能看懂**
的工具，并且**用它去修真实问题**。

### 一、工具本体

1. `POST /api/metadata/health`（`core/metasources.health_check`）：
   - **并发 4 路 + 单家超时 12s**（14 家串行最坏要几分钟，用户会以为界面卡死；某一家卡住不拖住其它 13 家）；
   - **只读**：不改配置、不写库、不注册任何东西；
   - `GET` 同路径回**上次结果**（进程内缓存，重启即空 —— 体检结论是「此刻的真相」，
     存库会让人拿旧结论当现状；接口如实回「尚未体检过」，不假装有历史）；
   - 结论 **12 类**（`HEALTH_KINDS`）：可用（有结果）/ 能连通但没解析到结果 / 未填密钥 /
     被限流 429 / 被拒绝 401·403 / **被反爬拦截（验证码）** / **被重定向（多为反爬）** /
     **接口返回错误** / 超时 / 网络不可达 / 响应解析失败 / 其它 —— 分类的意义是**告诉用户该做什么**
     （等一会 / 降频率 / 填 Key / 等修复，四件事完全不同）。
2. **样本按家给**（`HEALTH_SAMPLES`）：地区性目录必须用当地书名，否则会把好家误报成「无结果」——
   Aladin=`채식주의자`（韩）、Lubimyczytac=`Wiedźmin`（波）、RanobeDB=`狼と香辛料`（轻小说）、
   Comic Vine=`Saga`，其余用 `Dune`。契约钉住「样本覆盖全部来源」。
3. 每条结果**回「命中的第一条：书名 · 作者」**，而不只是状态 —— 因为
   **「可用但答非所问」比「没结果」更糟**（下面 Amazon 就是这么被抓出来的）。
4. 界面：「设置 → 元数据来源」新增「联网体检」卡片 —— 关键词（留空 = 各家样本）+ 开始体检 +
   汇总（可用 / 未填密钥 / 待处理 / 耗时）+ 逐家表格（结论、耗时、条数、首条结果）+ 易失效徽标；
   刷新后自动回看上次结果。

### 二、用它体检出的真实问题（本机实测，边测边修）

首次体检：**可用 3 / 未填密钥 3 / 待处理 8**。逐条追下去修掉了三个真缺陷：

| 体检结论 | 追查结果 | 处置 |
|---|---|---|
| Amazon「能连通但没解析到结果」 | 抓下真实页面比对：书名类名早已变（旧写法**一条都匹配不到**） | 改从**结果项 `<h2>`** 取书名（实测 16/16 是真书名） |
| Amazon 第二版「可用」但首条是 **"Aug 25, 2020 ·"** | 用 `a-text-normal` 会匹配到日期等辅助 span | 记入铁律：**错字段比缺字段更糟** → 只认 `<h2>` |
| Lubimyczytac「能连通但没解析到结果」 | 真实页面用 `book-card__title/__author`（旧的 `authorAllBooks__*` 已废弃） | 按真实结构重写解析（含封面与详情链接） |
| Libro.fm「能连通但没解析到结果」 | 站点回 **HTTP 202 + 2KB 挑战页** | `_get_text` 识别 202 与验证码页 → 新增 `blocked` 分类 |
| Goodreads「网络不可达」 | 实为 **HTTP 302 重定向**（反爬验证页） | `search()` 按状态码细分 → 新增 `redirect` 分类 |
| Audible「网络不可达」 | 实为 **HTTP 400**（接口参数/被拒） | 新增 `http` 分类 |

修复后复测：**可用 5 / 未填密钥 3 / 待处理 6，耗时 27.5s** ——
Amazon 回 `Dune: Book One in the Dune Chronicles`、Lubimyczytac 回 `Wiedźmin · Andrzej Sapkowski`。

**仍然不可用且如实标注的**（这些不是 bug，是站点侧）：Google Books 匿名 429、
Kobo 403、Goodreads 302、Audible 400、AudNexus SSL 中断、Libro.fm 202 挑战页；
Open Library 偶发 SSL 握手超时（下一次就正常）。三家需密钥的家在未填密钥时**零外呼**（如实记「未填密钥」）。

**顺手修的相邻问题**：`_strip_html` 的实体还原改用标准库 `html.unescape` ——
手写对照表漏了数字实体，实测 Amazon 书名里有 `Frank Herbert&#x27;s`，会原样留在书名里。

**契约**：新增 `tests/test_metasources_health.py`（18 项：分类 13 类全覆盖、样本覆盖全部来源、
缺密钥零外呼、有结果带首条、零结果单列 `empty`、一家失败不影响其它家、关键词覆盖样本、
子集体检、端点只读（**前后对比**而非断言绝对值为空 —— 否则会依赖测试执行顺序）与「没体检过如实说没有」）；
`test_metasources_parsers.py` 同步把 Amazon fixture 换成 `<h2>` 真实结构（外加辅助 span 干扰项）、
Lubimyczytac 换成 `book-card`、新增「挑战页/验证码页判拦截」与「数字实体还原」两条。

**验证**：后端全量 **911 例 / 0 failed**；前端 `type-check` / `test:unit`（82）/ `build` / `deploy` 全绿；
真浏览器实测：体检卡渲染 → 点「开始体检」约 28s 出表（8 种结论都在页面上）→ 刷新后仍能看到上次结果。

## 第 61 期（2026-09-27）：阅读器体验八项（已完成）

用户拍板的范围：漫画库的 PDF「还能按漫画形态读」；自动续接选 **A+C+D**（滚动无缝续章 /
PDF·漫画进下一册 / 有声书接下一轨，**翻页模式预取不做**）；通知只做**后端合并 + 顶栏角标
与通知中心**（同类型 = 同 action + 状态 + 主体）；目录问题是 EPUB 点击不跳/跳错。

### 已完成并真机实测

**⑤ 目录（EPUB 点击不跳 / 跳错）**
- 改为按 `flat` **位置**跳转（`tocView` 逐项带 `pos`），不再回查后端章节序号；
- 加**请求序号守卫**（连点目录时慢响应后到会覆盖后跳的那一章 ——「跳错位置」的真因之一，
  已由 vitest 契约钉住）；
- 加「加载章节…」提示：实测点击后 0.4s 即可见，解决「点了没反应」的观感；
- 无章节序号的条目**不再渲染**成点了没反应的死项。

**⑥ 翻页模式滚轮翻页**：non-passive `wheel` 监听（累计阈值 24px + 220ms 时间锁），
滚动模式不抢滚轮；实测滚轮一格翻一页、双向都对。

**⑦ 翻页模式右侧露出下一页**：根因是位移步长用「容器宽 + 栏距」，而真实栏距是
「栏宽 + 栏距」，且正文宽度与内边距的口径叠加错了一层（我自己先修错一次：把 `width` 设成
可用宽，内容盒反而又窄掉两个内边距，右缘仍露 48px）。现在 `width` = 整屏宽（border-box
含内边距）、栏宽 = 可用宽 / 栏数、步长 = 栏宽 + 栏距 —— **实测步长 938 = 栏宽 906 + 栏距 32**，
每格滚轮恰好一页，截图右缘无残影。

**⑧ 进度实时统计 + 首页继续阅读**
- 新增 `library.patchProgress`：四个阅读器（EPUB / PDF / 漫画 / 音频）写完进度**就地回写
  store**，不重拉整库；
- 切后台（复用会话的 `visibilitychange`）与关页面（新增 `pagehide`）时把 800ms 去抖里
  没发出的那次补发，不丢最后一段位置；
- 首页「继续阅读」书架行加进度条与百分比 —— **实测 SPA 内切仪表盘即显示 10%**，未刷新页面。

**④-A 滚动到底无缝续接下一章**：`chapterCache` 把下一章**先预取**好，滚到底即就地切换
（已缓存 ⇒ 不再发请求、不闪「加载中」）；`readerPrefs.autoNextChapter` 默认开，设置面板
有开关。实测打开即取 1、2 两章；连滚到底**一路自动接了 3 章（2/6 → 5/6）**，无加载空档。
（翻页模式的末页判定按约定**未改**。）

**① 漫画库支持 PDF（含按漫画形态读）**
- `library._COMIC_EXTS` 纳入 `.pdf`（PDF 仍属电子书类型，自动归库不猜，进漫画库要放到
  漫画库的来源文件夹里）；
- `ComicReader` 新增 `source='pdf'`：pdf.js **逐页渲染成 blob 图**，交回**同一套 `<img>`
  漫画布局** ⇒ 单/双页、右到左、无间隙连续全部适用（不需要服务端光栅化，也不新开一份
  PDF 布局）；
- `comicPrefs.pdfMode` 决定默认阅读器；两个阅读器互有切换入口、**共用页进度**，选择落库。
  实测双页下渲染出 2 张 900×1273 页图，往返切换都保留当前页。

**② 通知合并（10s 窗口 + 每次新消息重置）**
- 合并键 = **动作 + 结果 + 主体**；窗口内重复并入同一条（`merged` = 次数，说明取最新）；
- 窗口**尾随**：每来一条同类型消息都从头计时；只能**延迟落盘**，故注册 `atexit` 兜底
  flush（不丢最后一次风暴）；
- 前端通知中心与顶栏浮层显示 `×N`。**实测连发 5 次同类型 → 通知中心 1 条、`merged=5`、
  角标未读 = 1（不是 5）、窗口走完后仍 1 条**。
- 配置项 `notifications.merge_enabled / merge_window`（默认 10s 开启）。
- ⚠️ 配套决定：`tests/conftest.py` 里**用例默认关闭合并** —— 合并会破坏「写一条即落一条」
  这个既有前提（日志留存 / 轮转 / 过滤类用例都依赖它）；合并本身由
  `tests/test_notification_merge.py` 的 6 条契约专门钉住。

### 待办（已收口）
- **④-C PDF 跨册续接**、**④-D 有声书跨轨 / 跨册续接**：已落地（commit `3893498`）。第 66 期把漫画 / PDF / 有声书三处重复实现**收敛到 `lib/seriesNext.ts` 单一真值源**，并统一默认值与「册」口径文案。
- **③ 打开提速（顺延，拟排第 67 期）**：3 本书的小库测不出瓶颈，需要用大书库（拟造 500+ 本合成书）或真实实例
  复现后再改；**没有指标前不动手优化**。已量化的基线（隔离实例 8143，3 本书）：
  后端 `/api/books` 5–7ms、详情 8–10ms、单章 5–7ms、封面 5–7ms、批注 4ms、书签 3ms、
  进度 7ms；前端「点开 → 详情可见」**59ms**、「点阅读器 → 正文可见」**66ms**、
  「整页刷新 → 正文可见」**119ms**。

### 验证
- 后端全量 **939 例 / 0 failed**（933 基线 + 6 条通知合并契约）；
- 前端 `type-check` / `test:unit`（10 文件全绿）/ `build` / `deploy` 全绿；
- 每一项都给了真机实测数字或截图佐证（见上）。

## 第 60 期（2026-09-26）：按书籍语种自动重排来源顺序

**动机**（用户点名）：14 家都能用之后，顿了一下顺序问题 —— 韩文书没必要先等波兰站转一圈，
中文书也没必要把韩国/波兰/轻小说三家排在前面。这是第 57 期「元数据来源」页那两条「未支持」
之一（另一条是跨源合并，已在第 58 期做掉）。

### 三条设计约束（都在测试里钉住）

1. **稳定分档、档内保序**：`专精本语种 (0) → 多语种通吃 (1) → 专精别的语种 (2)`，
   每档内**保持用户设的顺序**（`sorted` 稳定）—— 这是「重排」不是「覆盖你的配置」；
2. **只排序、不筛源**：任何启用的家都不会因为语种被丢掉（第 59 期体检也证明了「专精别的语种」
   的家偶尔真能命中）—— 只是先问相关的、后问不相关的；
3. **不猜**：语种来自书的 `language`（OPF `dc:language`）；**未知 / 空 / 占位值（「未知」「unknown」
   「n/a」）一律不重排**，开关关闭时严格按配置顺序。

### 实现

- **语种亲和表**（`metasources.LANG_AFFINITY` / `LANG_BROAD`）：专精 `aladin`(ko)、`lubimyczytac`(pl)、
  `ranobedb`(ja)，以及英语侧的 `amazon` / `goodreads` / `hardcover` / `itunes` / `comicvine` /
  `audible` / `audnexus` / `librofm`；通吃 `googlebooks` / `openlibrary` / `kobo`。
  ⚠️ 这是**人工判断**（各站主营语种 / 抓的是哪个域名），不是实测统计，注释里写明；
  契约钉 `LANG_AFFINITY ∪ LANG_BROAD == SOURCES` 且不相交 —— 新增一家源必须显式表态。
- **契约里最容易被漏的一条**：`_lang_of("未知")` 会返回非空的 `"未知"`（它原本是「写进书目时归一」
  用的），若不额外拦，重排会把这份占位值当成真实语种、把所有源判成「专精别的语种」——
  于是**凭一个占位符瞎重排**。故新增 `LANG_UNKNOWN` 只在重排路径上当「不知道」。
- **三处调用点口径一致**：`metafetch.plan`（**逐本**算，整个书库混着中英日书用一个顺序不合理）、
  `metafetch.online_candidate`（单本）、`series_meta`（系列没有自己的语种 → 由**成员书投票**，
  平票取先出现者以保证可复现）。
- **可解释**：`plan` 每本回传 `sources_order`（本次实际顺序）+ 顶层 `auto_order_by_language`；
  ISBN 路径最直接 —— 第一个命中的精确匹配就赢，所以顺序在这里真会影响结果。
- **配置**：`metadata_fetch.auto_order_by_language`（默认**开**，可被书库级覆盖），
  三处登记（`config.DEFAULTS` / `server.EDITABLE` / `GET /api/config` 走掩码函数整体回传）。

### 界面

1. 「设置 → 元数据 → 书籍自动抓取」新增开关「按书籍语种自动重排来源顺序」（与「跨源字段级合并」同款）；
2. 提供商每行加**语种徽标**（`韩语` / `波兰语` / `日语` / `多语种`），让「会怎么排」可预期；
3. 预览表格里，被重排过的书显示一行「按语种重排：aladin → googlebooks …」（没重排就不显示，不制造噪音）；
4. 顺带订正两条**陈旧文案**：未支持清单里「跨源字段级合并」「按语种重排」其实都已实现（第 58 / 本期），
   换成真正还缺的两条（跨语言检索、自定义来源权重）。

### 验证与诚实边界

- 后端全量 **933 例 / 0 failed**（新增 `tests/test_metafetch_language_order.py` 22 项：亲和表完整性、
  32 组分档参数、稳定保序、不筛源、未知/占位/关开关不重排、语种码归一、系列投票、
  plan / online_candidate / series 三处调用点顺序断言、配置键可写、目录端点回传 `langs`）。
- 前端 `type-check` / `test:unit`（82）/ `build` / `deploy` 全绿。
- 真浏览器实测：开关渲染完整（含三档说明文案）且**点击真写入**（关闭 → 服务端 `false` → 再开 → `true`）；
  提供商行语种徽标渲染正确（`多语种` / `日语`）。
- ⚠️ **未做在线验证的一处**：预览表格里那行「按语种重排」，隔离实例没有书库与来源根
  （首次向导才建），故未走完「有书 → 开始预览 → 看到顺序」的链路；该链路由 22 项单测
  （含 plan 的逐本顺序断言）覆盖。你在自己实例里点「开始预览」即可看到。

## 第 62 期（2026-09-27）：书目索引落库 / TXT 只入库不转换 / PostgreSQL 后端 / Redis 缓存 —— 从「42 秒」起底

**来源**：线上实例（`http://192.168.0.95:8992`，改造前逐接口计时）暴露的性能问题：`/api/books` **42.4s**、`/api/libraries` **41.9s**（响应体只有 1.8 KB）、`/api/books/export` **43.1s**、`/api/stats` **28.6s**、`/api/authors` **22.4s**；3 个库共 266 本，42s ÷ 266 ≈ **158 ms/本**。本地开一次 zip 读 OPF 只要几毫秒 —— 量级差只有一个解释：书库挂在 NAS 上，`probe_epub` 里几十次 syscall 每次都在付网络往返（254 KB 的 JSON 走局域网只要 0.1s）。**瓶颈 100% 在后端扫盘**：书目从不入库、每次请求现扫磁盘；`_books_of` 还先算目录指纹再查缓存（命中也要付一次全目录 stat，指纹还要递归 rglob），未命中就 `_scan_once`，而这一步在锁外、没有单飞，并发请求各自重扫。本期分 A/B/C/D 四阶段 + 三笔修正。

### A. 书目索引落库（新增 `core/catalog.py`，`95a73b3`）

- **请求路径不再扫盘**：`books()` / `by_id()` / `_book_counts()` 分别变成一条 SELECT、一条按 `book_id` 的索引查询、一次 GROUP BY。
- **增量判据 `(size, mtime)`**：条目没变就整段跳过、**不开 zip** —— 266 次 stat 与 266 次「开 zip + 读 container.xml + 读 OPF + 找封面 + 遍历 manifest」是两个量级（线上 42 秒的全部来源）。
- **单飞靠每库一把锁**：同一库的并发刷新合流；**不新起任何线程**（刷新只从请求线程与既有监听线程发生，不触发仓库「新增旁路线程必须进 conftest 收尾清单」那条纪律）。
- 删行按 `(root, rel)` 精确删；upsert 按 200 条一批提交（网络存储上不必付几百次 fsync）。
- **主键 `(library_id, root, rel)`，不是 `(library_id, rel)`**：一个库可持多个来源文件夹（第 41 期 `source_dirs`），两个根下同名文件合法；用两列会把这两本**静默合并成一本**，`by_id` 的 `BookIdConflict` 从此消失，进度 / 批注会写到错的书上。
- `library.py` 把「探测」与「拼装」拆成 `_probe_entry`（昂贵、**只依赖文件自身**）/ `_cheap_facts` / `_row_of` / `_apply_overlay` 四段；删掉 `_dir_signature` / `_entry_mtime`；遍历顺序精确复刻改造前（`_order_key` 按路径分段比较 —— 顺序有语义：`id_conflicts` 把每组 `items[0]` 当保留项）。
- `invalidate()` 改为「标脏 + 只失效涉及的库」，`_libraries_changed(lid)` 只失效一个库（改造前无参调用清空所有库，是「新建书库很慢」的一半）。
- 新增 `core/sqlcompat.py` 方言适配：后端由 `NOVELFORGE_DB` 选择，**默认 sqlite**，不设时全仓行为与第 61 期逐字节一致、离线测试零变化；`?`→`%s` 做**字面量感知**扫描，不能机械翻译的构造（`INSERT OR REPLACE` / `AUTOINCREMENT` …）撞上即大声失败、不静默放过。
- 修一个被索引化**显形**的既有缺陷：`metastore` 拿卡片「生效值」（override > online > opf）当「OPF 原值」判断「用户改过没有」，用户改过书名后判据恒假 ⇒ 刮削**静默不再内嵌任何元数据**；改从文件派生值取 OPF 原值（新增 `catalog.raw_book` / `library.by_id_raw`）。
- `api_book_detail` 由「遍历全部库比对 id」改为 `by_id` 直查并补 `library_id`（只按 name 找会在两库存在同名相对路径时翻出**另一本**的章节树）。

### B. TXT 收敛为「只入库不转换」+ 分章行首锚定 + 编码探测按字符分布（`9cf3877`）

- **D1 只入库不转换**：`pipeline.EBOOK_EXT` 纳入 `.txt`，`.txt → convert_txt` 特殊分支删除（`watcher` 里**另有一条**同类分支也删，差点漏掉）；删 `core/ebook_convert.py` 整个模块与 Calibre 依赖，`FORMAT_CHOICES` 收敛为只剩 `epub`；前端「本地转换」工具页改名「本地导入」（它做的是手动投递入库，不再是转换）。
- **D2 分章行首锚定**：消除「正文里夹一句『他说第 3 章讲过』被当边界」的误切（旧契约刻意钉住的现状用例**反转**）；补「卷单独成行、`【第1章】/（第三章）、全角句点、No.3、Chapter 3`」等形态；序章 / 番外等改**捕获整行**；`CHAPTER_RULE_VERSION` 写进 `txtcache` 指纹（规则一变即重切重转）。
- **D3 编码探测修缺陷**：旧顺序里 **big5 是死分支**（GB18030 能解绝大多数 Big5 字节序列而不抛异常，繁体书被解成乱码却「成功」）；改为按**字符分布**判据 —— 同一段 Big5 文本 `gb18030` 得 **-2.43**、`big5hkscs` 得 **+1.71**；反过来 GBK 文本 `gb18030` 得 **+1.96**、`big5hkscs` 得 **+0.55**（两个方向都不矫枉过正）。采样默认 256 KB 头部、纯 ASCII 时补 64 KB 中段、仍纯 ASCII 才读全文。

### C. 老库全量搬进 PostgreSQL（后端可选，`861156a`）

- **后端是可选、不是替换**：`NOVELFORGE_DB` 默认仍 sqlite，不设时全仓行为与第 61 期逐字节一致、离线测试照常跑；`=pg` 时 SQL 经 `sqlcompat` 翻译交给 psycopg；半配置状态（选了 pg 却没给 DSN）**直接启动失败**、不静默回落 SQLite。`db.py` 那 35 张表、198 个函数搬到 PG，**公开函数签名与 `_Conn` / `_Result` 代理一律不变**（那是 24 个模块的契约）。
- 新增 `core/pg.py`（连接层）：RETURNING id 只对确有 IDENTITY 列的表追加（本仓有一半表的 id 是 TEXT 主键）；语句失败先 rollback 再抛；关掉自动预备语句；补语句级串行 + `db._connect()` 双检锁。
- **本次最贵的一条教训 —— 事务边界对齐 sqlite3 老模型**：psycopg 对**每条语句**都隐式 BEGIN（含 SELECT），不补齐差异就留下 idle in transaction 的连接攥着 ACCESS SHARE 锁 —— 实测把 `DROP SCHEMA … CASCADE` 永久挡在 `wait_event_type=Lock` 上（事务龄 2 分 53 秒纹丝不动），全量测试跑到 4% 再也不动。
- 新增 `core/pgmigrate.py`（一次性搬迁）：逐表按**列交集**搬、500 行一批、幂等；`SKIP book_index`；幂等标记写在 PG 的 `app_state`；**顺序坑**：`auto_migrate()` 必须排在 `db.init()` 的 `_seed_user` 之前（反过来空 PG 会先冒 admin/changeme 壳，搬来的 users 行撞 `UNIQUE(username)` 被 `DO NOTHING` ⇒ 用户升级完口令被**静默重置成 changeme**）。原 SQLite 文件一个字节都不改。
- 部署：`requirements` 加 `psycopg[binary]`；compose 加 postgres 服务（healthcheck）；`docker-compose.test.yml` 刻意留在 SQLite（别把老后端变成没人跑的代码）。

### D. Redis 缓存层（可缺席的一层，`6a7f11e`）

- 新增 `core/cache.py`：`NOVELFORGE_REDIS_URL` 不设 = 整层空操作（**连客户端都不建**）；设了但连不上 = **静默降级为「每次未命中」**；**连续失败即熔断 30 秒**（否则 Redis 挂掉就从省时间变成每个请求多等 0.5 秒）；socket 超时 0.5s。挂了三处：章节正文（**唯一明显收益处**）、书目列表（收益有限、如实标注）、封面（只覆盖「从文件里读」的两条分支；服务端 `meta_cover` **不进缓存**）。失效收敛到 `catalog.invalidate()` 一处。
- **本机（SSD）实测 300 本 / 900 章：章节翻页「无缓存 2.63 ms / 命中 2.57 ms」—— 本机就是打平**（一次 zip 读与一次 Redis 往返同价），列表那处也打平（20.6 / 20.6 ms）。之所以仍接，是因为线上不是本机（书库挂 NAS）。
- 验收数据：`/api/books` 冷 20.6 ms | 热 20.6 ms（打平）；章节翻页未命中 3.95 ms（多付一次往返）；内存 900 章 ≈ 4.40 MB；命中率一次会话 0.52 / 稳态 1.0。
- **故障演练**（真 uvicorn + 真容器，中间 `docker stop nf-redis`）：停掉之后服务照常 200，代价是紧接着的两次请求各等一次超时（**1.03s / 0.52s**），随后熔断生效回到 4 ms；`docker start` 之后自动恢复并重新写键（不等重启）。

### 补：三笔修正（收尾）

- **`fe5f58e` 增量刷新每文件 3 次 stat → 1 次**：`_iter_book_entries` 改用 `os.scandir`（读目录项自带的类型，不发 syscall；`d_type` 不可用的文件系统回落一次内部 stat），`_cheap_facts` 用已经拿到的那次 stat 判目录。实测（300 本，模拟 5ms/次 syscall）：写后第一个请求 **4956.8ms / 903 次操作 → 1686.9ms / 304 次操作**；全量重探 **6740.0ms / 1201 次 → 3463.3ms / 602 次**。用例拿**计数**钉住（本机 SSD 上怎么改都是绿的，只有计数能表达「省下了什么」）。
- **`bcde7ff` PG 迁移后自增序列不推进**：`GENERATED BY DEFAULT AS IDENTITY` 在**显式给值**的 INSERT 上不推序列，搬迁把老库 `id` 一并搬来 ⇒ 搬完 N 行序列仍停在 1，第一次写入撞 `duplicate key … (id)=(1) already exists`；`_seed_user` 也不带 id ⇒ 老库账号名不叫 `admin` 时**服务直接起不来**。修法：`migrate()` 收尾 `_reset_sequences()`。老夹具 `progress` 少一列 `id`（真实老库一定有）才让 bug 一路绿过去。
- **`2308b2c` 全库失效的判据比「序号」不比「时刻」**：`time.time()` 粒度实测约 **15.6 ms**（连续调 2000 次结果全同），「写文件 → `invalidate()` → 立刻读书目」正好落在同一刻度 ⇒ 库被判成不脏 ⇒ 新文件不在书目里（偶发红灯 `test_annotation_export`）。改成单调递增序号 `_dirty_all_seq` / `_refreshed_seq`；`_is_stale` 与 `_needs_refresh` **两处判据都要改**。

### 验证

- A：新增 `tests/test_catalog.py` 17 例（与「全量扫盘」逐字段对拍、增量闸门、多根同名不合并、`by_id` 语义不变、overlay 与封面照常）。离线（sqlite）全量 **970 passed / 6 skipped**；PG 后端全量 **975 passed / 1 skipped**。
- B：后端全量 **969 例全绿**（新增 17 例 catalog + 13 例分章与编码契约，反转 1 例旧契约）；前端 `type-check` 零错误、`vitest` 10 文件 / 89 例。
- C：离线 970 / 6；PG 975 / 1。新增 `tests/test_pgmigrate.py` 7 例。
- D：新增 `tests/test_cache.py` 9 例；离线 **979 / 6**，PG **984 / 1**。用例需要**真** Redis，连不上就 skip（默认连本机 6380 的 db 15，绝不碰生产的 db 0）。
- 三笔补：`fe5f58e` 后 979 / 984；`bcde7ff` 后 SQLite **992 / 7**、PG **998 / 1**；`2308b2c` 后 SQLite **1131 / 0 / 0 / 7**、PG **1131 / 0 / 0 / 1**。
- ⚠️ 性能回归待部署后对同一实例复测（线上 42s 那一组数字是**改造前**基线）；本仓无第 62 期收尾的线上复测记录，如实标注 —— 把接口从 42 秒降到亚秒的是书目索引，不是 PG。

---

## 第 63 期（2026-09-27）：详情页对齐 BookOrbit v3.1.0（六阶段合一）

**来源**：用户给了 Book Orbit v3.1.0 详情页的五张截图作样板，要求按它完善本项目。分六个阶段推进，前段先把壳搭好，后面的阅读日志 / 文件面板 / 元数据扩展都往这个壳里填。

### 1/6 详情页骨架重做（`8d5ad68`）

- 649 行的 `BookDetailView.vue` 按标签拆到 `components/book/detail/`（6 个文件），本文件降到 211 行，只留**取数与编排**；新抽出的 hero / 概览 / 各标签一律**收 props 不自己取数**（否则同一本书请求三遍、三份副本各自过期）。`MetadataEditor` / `ReadingRecord` 保持自取数据不动。
- 新增 4 个 `ui/` 组件，都是**归并**而非新造：`TabBar` / `ProgressBar`（抽前详情页手写了一份 `h-1.5 bg-primary`，比例只留一个真值源）/ `RatingStars`（抽前有三份各写一遍；`readonly` 时渲染 span 不渲染 button）/ `StatTile`（本期尚无调用点，3/6 期的阅读日志四格是第一个消费者）。
- 排布对齐样板：进度与星级**上提 hero**；相似书**带封面 + 横向滚动**；0 星 = 未评分 → 整块不渲染（画五颗灰星会被读成「打了 0 分」）。
- **修两个静默 bug**：① 「暂无成品文件」`EmptyState` 的 `v-else` 挂在了**相似书**的 `v-if` 上 ⇒ 没有相似书的书会多渲染一块「暂无成品文件」；② 面包屑读全局 `shelfTitle` ⇒ 深链进来显示一本**别的书架**的名字。顺带修「详情拉取失败、但书架缓存兜底」被渲染成空壳 —— 改给错误提示条 + 重试。
- 验证：新增 `BookDetailView.spec.ts` 8 条（该页此前**零测试**）；**实测两条回归用例的判别力**（把 `v-else` bug / 面包屑改回去 → 对应那条红）。后端 980 passed / 6 skipped。

### 2/6 阅读追踪数据层（`cf40106`）

- 会话边界：心跳带 `session_uid`，一段只留**一行**（新增 `db.upsert_session`，`ON CONFLICT(book_id, session_uid) DO UPDATE`）；`start_*` **刻意不进 SET 子句**（起点是 `CHANGE` 列的被减数）；不做「离开时写一行」（浏览器崩了 / 关标签页，那一两小时会**凭空消失**）。
- 「未知」用 `-1` 哨兵（新增 `db.SESSION_UNKNOWN`），`_session_row()` 一次性转 `None`；`source` 空串 = **未知**不是「其他」（事后猜一个值就是造假），新增 `db.SESSION_SOURCES`。
- 前端新增 `lib/readingSession.ts`（`createSessionReporter()` 管边界与累计，可脱离网络驱动）：uid 刻意**不用 `crypto.randomUUID()`**（安全上下文限定，局域网明文访问下它直接不存在）；`stop()` 的顺序是「先同步把这一段交出去、再清空、最后才等上报」（反过来会把新段的 uid 一起抹掉）。
- **PDF / 漫画开始计时**（此前一秒都不记）：`attachReaderClock()` 是整个会话链路唯一的 DOM 接触点；音频那一路**不用它**（判据是「音频在不在播」，不是「页面可不可见」）。
- 修一个真 bug：`visibilitychange` 是在状态**已变之后**才派发的，旧写法按当前可见性结算 ⇒ 每次切标签页静默吞掉最多 30 秒。
- 接口：`GET /api/books/{bid}/stats` **一页一端点**；没读过时 `reading` 是 `null` 而非全 0 对象。与计划两处主动偏差：不做独立 `/sessions` 端点、`attempts` 不放进 `/stats`。
- 验证：新增 `tests/test_book_reading_log.py` 12 例 + `readingSession.spec.ts` 23 例；判别力实测（如把 `start_*` 加进 SET 子句 → 心跳那条红，**第一版用例无效**、改了数据才有判别力）。SQLite 992 passed / 6 skipped、PG 997 passed / 1 skipped。

### 3/6 阅读日志标签页（`076aee0`）

- 详情页第 7 个标签，四块面板（READING / SESSIONS / PROGRESS OVER TIME 双轴图 / ATTEMPTS）+ RECORDS 四格。**推翻第 30 期「按书日志不在详情页（避免与 /log 重复入口）」的旧决定** —— 判据是 `/log` 的「按书」卡只给一行摘要，会话级流水与双轴图只在详情页有（非重复入口）。
- 每块自己判空，不设一个总的「有没有读过」闸门（标过「在读」但没在网页打开过的书没有会话、却有轮次）。
- 「未知」不写成 0：`change` 为 `null` 显示「—」、`longest_streak` 为 `null` 那一格**不渲染**、`pages` 不可信则「阅读速度」不渲染。
- `lib/readingPace.ts` 抽成一份 `/log` 与详情页共用；图表懒加载必须**显式传 `active`**（标签用 `v-show`，光靠 `v-if` 拦不住 800 kB 量级的 ECharts chunk）。构建产物核对：主包 `index-*.js` 里 `echarts` **零命中**，只在 `charts-*.js`（806 kB），StatsView 从 894 kB 瘦到 88 kB。
- 验证：新增 `ReadingLogTab.spec.ts` 12 条、`readingPace.spec.ts` 6 条；判别力实测 2 处。vitest 14 文件 / 141 条。

### 4/6 进度按文件维度（`5ee741d` 后端 + `83a3eca` 前端）

- `progress` 加列 `file_rel`，唯一约束 `UNIQUE(book_id)` → `UNIQUE(book_id, file_rel)`（EPUB + PDF + 漫画的书各存各的读点，不再互相覆盖）。
- **书级进度 = `updated_at` 最新的那一行**，不另存一份；`file_rel=''` =「这本书自己 / 不知道文件」（KOReader / Komga / 标记已读完走这条，行为逐字节不变）。
- 三处硬骨头（都写在代码注释里）：改约束**只能重建表**（补一列是「看起来成功了、其实没生效」的假修复）；重建复制行**不带 `id`**（否则撞第 62 期补的 PG 序列坑）；重建**不在一笔事务里** ⇒ 有半成品自愈，判据是「**源表每一行在新表里有没有着落**」而不是比行数，判决一律「留数据」。
- 前端新增 `lib/readingProgress.ts`（**三阅读器共用**）：「先按本文件查；本文件没读点 ⇒ 回落书级，但**只认『说的不是别的文件』的回落**」（书级可能是 PDF 读出来的页码，拿去章节流会跳到毫不相干的地方）；`AudioPlayer` **刻意不带** `file_rel`。
- **诚实边界**：四个阅读器都读不到非主文件 ⇒ 详情页成品文件列表**不给继续阅读入口**（点不动的假交互），本期只把数据契约与落点先立住。
- 验证：新增 `tests/test_progress_per_file.py` 24 条；变异实测 2/2（`_progress_file` 绕过 `safe_path` → 红，证据里出现指向**库根之外**文件的 CFI）。SQLite 1023 passed / 7 skipped、PG 1023 / 1；前端 vitest 15 文件 / 149 用例。

### 5/6 文件标签重做 + 元数据编辑器扩充（`ab4ee0d` + `3238dad`）

- **文件标签（`ab4ee0d`）**：book 条目里的 `path`（**服务器上的绝对路径**）此前被**六个端点**不做投影就发了出去（前端从未消费）⇒ 决策 6「路径按访问来源区分」要真成立就必须是「服务端不给」，不是「前端不显示」。新增投影 `_card(b)` 丢掉 `path`，六处收口；新增 `GET /api/books/{bid}/local-paths`（本机 / 局域网给「库内相对路径 → 绝对路径」，响应 `no-store`）。判据 `_is_local_request` **绝不解析** `X-Forwarded-For`（客户端可随便伪造）；`FilesTab` 重做 + 目录型有声书如实说清。
- **元数据编辑器（`3238dad`）**：元数据面 11 → 21 项（`subtitle` + 9 个提供商 ID，均**无 OPF 对应物**、经 `meta_override` 落库，绝不写回书文件）；4 家源**刻意不开字段**（抓到的只是页面 URL，不是该站原生标识）；修一处既有静默失效（`_FINALIZE_FIELDS` 写 `year` 而 plan 按字段名 `date` 查 ⇒ 预设里「出版年」那一档**从来没生效过**）；`metascore` ISBN 由 **10.0 → 5.5**、9 个 ID 各 0.5（合计仍 100）；前端新增 `lib/metadataFields.ts` 收口那 21 项（原先四处各抄一遍、已抄出过事故）。
- 验证：`tests/test_local_paths.py` 28 条、`FilesTab.spec.ts` 19 条；`tests/test_provider_ids.py` 25 条、`MetadataEditor.spec.ts` 9 条；变异实测后端 4 处 / 前端 6 处。SQLite **1079 passed / 7 skipped**、PG **1079 passed / 1 skipped**；vitest 17 文件 / 177 用例。⚠️ `isbn10` / `isbn13` 分离**不在本期**（要动被 Komga / CSV / Hardcover 匹配 / 出版副本四条外部链路消费的 `isbn` 键）。

### 6/6 批注位置锚 + KOReader 导出文件导入（`cb09c20`）

- **位置锚要两个字段**：`anchor`（来源原生，如 KOReader 的 XPointer，本应用**不能**定位，只用于导入去重与溯源）+ `start_off` / `end_off`（本应用阅读器自己算的**章内字符偏移**，能定位）；取偏移与还原区间**共用同一个遍历**（`lib/textAnchor.ts`）；**验不过就不画**（偏移是位置不是内容，书文件换了老偏移仍合法、会指到无关文字，**比不画更糟**，交给文本搜索兜底）；老库补三列、存量行回落 `''/-1/-1`（回填 0 会让老批注全指到章首）。
- **导入走文件不是 kosync**：官方 kosync **没有批注端点**（客户端只有 4 个方法、服务端只同步进度），KOReader 批注跨设备同步走 `<书名>.annotations.lua` 文件；导入**幂等**（六计数相加必须等于送进来的条数）、**永不删除**、反向**不许**（本项目删掉的墓碑不会被再次导入复活 —— 删是比同步更强的意图）；`annotations(book_id, origin, anchor)` 上**故意不建唯一索引**（真建会复刻 bookmarks 那个坑 ⇒ 整本书的批注静默丢失）。
- 高亮页：导入**两步走**（先 `apply=0` 只看不写，看到条数再确认落库）；空态两张卡**不摆 Kobo**（没实现）；`lib/annotations.ts` 收口口径 + 基于 `import.meta.glob` 的回归锁（全仓再出现 `chapter + 1` 就红）。
- 验证：新增 `tests/test_koreader_anno.py` 39 条、`tests/test_annotation_anchor.py` 11 条；变异实测 `annotations.ts` 8/8、`textAnchor.ts` 8/8、ReaderView 4/4、AnnotationsView 2/2，兜住两类**真实测试缺口**。pytest SQLite **1131 / 0 / 0 / 7**、PG **1131 / 0 / 0 / 1**；vitest 20 文件 / 229 用例。

---

## 第 64 期（2026-09-27）：删书 / 书卡 ⋮ 菜单 + 快速预览 / 三项子菜单

**来源**：上游 Book Orbit 的书卡形态（提交正文引「上游图 1 的九项」）与删书需求。⚠️ 本仓无逐期记录，本段按提交正文与代码复原。

### 1/3 删书 —— 只回收不真删，关联数据一律保留（`2d85c8c`）

- `DELETE /api/books/{bid}`：文件移入回收目录（`publish.recycle`，收**绝对路径**、文件与目录都行 —— 有声书整本就是一个目录），索引标脏交给下一次增量刷新，刮削台账降级为 `source_removed` 而**不删行**，落一条「清理」审计日志。响应回 `{ok,id,name,recycled,siblings}`（`siblings` 供确认文案点名）。
- **刻意不清**进度 / 批注 / 评分 / 状态 / 收藏：`book_id` 由「库 id + 文件名」派生 ⇒ 文件从回收目录放回原路径数据就接回来，**删书因此可撤销**；清掉批注（用户手写的笔记）则不可逆。依据写在端点 docstring 里，免后人「顺手」补一个 purge。
- 顺带修一个已存在的真 bug：`/download/{name}` 写死 `OUTPUT_DIR` 拼路径（多库下必 404），且单段路由接不住 Komga 布局的库内相对路径（`三体/三体 #1.epub`）⇒ 改成 `fileops.safe_path(name, library_id)` + `{name:path}`。
- 验证：`tests/test_book_delete.py` 16 例，**每条都做了变异实测**；另加 `downloadUrl.spec.ts` 4 例钉编码口径。基线 pytest SQLite **1147** 例、PG 1147；vitest 21 文件 233 例。

### 2/3 书卡 ⋮ 菜单 + 快速预览（`4bfa345`）

- 网格 / 列表 / 表格三视图各接一个 ⋮，菜单五项：阅读（收听）/ 快速预览 / 下载 / 书籍详细信息 / 删除。上游九项里的「通过电子邮件发送」按决策**不做**（不出现、不灰置、不占位）；**缩略图点击行为一个字没改**。
- 状态放 `lib/bookMenu.ts` 单例（`openKey` 只有一个 ⇒「同时只开一个」是**数据结构的结果**）。菜单面板 **Teleport 到 body**（**全仓第一处**）—— 外壳内容卡片带 `backdrop-blur-md` + `overflow-hidden`，`backdrop-filter` 会成为 fixed 后代的包含块；表格卡 `overflow-x-auto` 又两轴裁剪，面板挂在页面内怎么定位都会被裁。
- 网格卡**必须改结构**：菜单项都是 `<button>`，HTML 解析器遇到内层 button 起始标签会直接闭合外层 button（封面与「封面下方那几行字」拆成两个按钮，`⋮` 落封面右下角，**系列行不给菜单**）。
- 新增 `BookPreviewDialog`（内容**全部取自书卡**，详情请求只补「N 章」；拉失败只在该行位置说明、绝不把真数据换成错误页）；`lib/bookOpen.ts` 作「能不能在线读、去哪儿」的唯一判据；`stores/library.ts` 加 `forgetDetail`（详情缓存无失效机制，删完书退回详情页会命中缓存渲染一本不存在的书）。
- 顺带修一个真 bug：上一段提交里 `ShelfView.vue` 少了一个 `</div>`（整个模板编译不过），而 `npx vue-tsc --build --force` 对它是 **exit 0**（把这个 `</div>` 再删掉重跑仍然 0）—— 只能靠「真去 mount 这个页面」的 spec 抓，`ShelfView.spec.ts` 是本页第一份 spec、就这么抓到的。
- 验证：`bookMenu.spec.ts` 5、`BookActionsMenu.spec.ts` 16、`BookPreviewDialog.spec.ts` 7、`ShelfView.spec.ts` 6（三视图触发器计数是「三个视图都留了入口 + 系列行不给菜单」的唯一哨兵）；变异实测 3 处。基线 SQLite 1149、PG 1149；vitest 25 文件 267 例。

### 3/3 三项子菜单 —— 收藏 / 状态 / 编辑元数据（含 `?tab=` 深链，`55b1b01`）

- 三项都是「已经存在的能力换一个入口」，无新增数据模型。子菜单用**行内手风琴**（面板已是 Teleport + fixed，再叠一层要再写一套定位与 outside-click 语义）；同一时刻只开一个，靠「只有一个变量」而不是互斥规则。
- ⚠️ 实参顺序是**收藏夹在前**（`addToCollection(collectionId, bookId)`）—— 反了不报错，只会往一个错误的收藏夹里塞书。
- 「设置状态」**绝不用 `statusLabelOf` 打勾**（它在没有状态行时按进度兜底推导，会把「从没设过状态」显示成「他标了未读」）；五态文案收敛成 `lib/readingThresholds.ts` 的 `READ_STATUS_OPTIONS`。
- 「编辑元数据」指到 `/book/:id?tab=metadata`：`?tab=` **只当初值**，切标签**不写回 URL**（写回意味着每点一次标签压一条历史、分享链接会带别人的浏览位置）；值不认识就落回概览，不抛错、不白屏。
- 验证：`BookActionsMenu.spec.ts` 扩到 28 例、`BookDetailView.spec.ts` 加 4 例深链。深链四条断言的是**面板的显隐**（查 `style.display`）而不是整页文本（七个面板全 `v-show`，按文本断言是**假哨兵**）；变异实测 2 处。`vue-tsc` 这一轮抓到 spec 里两处真问题（桩写成 `{ ok: true }`，而接口返回 `ReadingStatus`）。基线 SQLite 1149、PG 1149；vitest 25 文件 283 例。

---

## 第 65 期（2026-09-28）：Book Dock 一级入口 + 顶栏图标行 + 重命名 / 匹配书库

**来源**：两条线合并（用户 2026-09-27 拍板「并入第 65 期」）。
**线 A 导航改造**（用户原话）：「Book Dock 的入口放在首页-探索发现的下面，与探索发现一级」；「首页左侧栏，迁移任务中心、工具、数据统计、阅读记录、阅读活动、通知中心、成就的入口，放到首页截图所示的位置，与现有的图标位置并排」（图标照上游：圆形描边按钮 + 黑色气泡 tooltip + 数字角标）。
**线 B 功能**：「根据上游 Book Dock 的功能，实现上传的书可以重命名、匹配书库等功能」。

### 线 A：导航改造

- 侧栏主导航收成 **3 项**（仪表盘 / 探索发现 / **收书目录**）；Book Dock 另开一条**顶层**路由 `/book-dock`，指向与设置里 `admin/book-dock` **同一个组件** —— 不能只留设置里那条：`App.vue` 按 `path.startsWith('/settings')` 判断是否换成设置侧栏。设置里那一条按上游形态**原样保留**。
- 顶栏图标行：只留顶栏（侧栏不再有那七项）、合并去重（数据统计只保留一个按钮；通知沿用既有铃铛浮层；**任务面板照通知的浮层样式**）。新增 `ui/IconButton.vue` —— 那段 `ICON_BTN` 类原先被**逐字抄了三份**（AppHeader / NotificationBell / AppearanceMenu），本期再加四个入口就是七份。tooltip 是纯 CSS（零 JS），右对齐、颜色写死 `bg-black/85`。
- `TaskDrawer.vue` 改名 `TaskFlyout.vue`（`git rm` 旧的），骨架与交互逐字照通知浮层；`stores/ui.ts` 的 `drawerOpen` / `toggleDrawer` / `setDrawer` **一并删掉**（撤销掉的入口不能留孤儿状态，留着只会让「再塞个假按钮」变得顺手）。⚠️ 但**轮询没跟着删**（任务数据由 `App.vue` 启动时拉起 + `tasks.syncPolling()` 自管）。

### 顺带修三个真 bug（本期入口做好后用户立刻会点到的）

① `BookDockPage.vue` 同一条 `v-if` 链里两个分支条件**逐字相同** ⇒ 后一个分支永不渲染 ⇒ 条目行一条都不显示（复选框长在条目行里，于是批量按钮永远禁用）；② `library_rules.guard_conflict` 拿 **basename** 去比库内 **rel** ⇒ Komga 布局（`系列/系列 #N.ext`）下**同一本书重复入库被误拦**，平铺布局下 `rel == base` 所以既有测试全绿也压不住；③ `lib/icons.ts` 的 `iconPath()` 对未知键**静默返回空串**，而 `upload` / `folder` 两个键压根不在表里 ⇒ 拖拽遮罩大图标、书库向导文件夹图标一直是**隐形的**（已补键 + 加对表测试钉死）。

### 线 B：重命名 / 匹配书库（后端）

- `db.dock_rename` 换主键（条目 id **就是文件名**）并归零 `retries`（老计数继续拦一个已改名的条目没有道理，历史留在 `activity_log`）；`bookdock.rename` 八步校验**全部在拿锁之前**，锁内只做「改磁盘 + 一条 SQL」。
- `bookdock._reg_lock` 的不变量写在模块头：**绝不持锁调 watcher 的任何方法** —— watcher 持 `_scan_lock` 时会回调 `on_scan` → `note_scan`（要拿这把锁），反序叠加就是 **AB-BA 死锁**；于是 `reconcile` 改成「锁外快照 + 锁内写库」。
- `rescan(…, library_id, root)` 三条校验（经 `_ingest_target`）：库必须已登记 / 目标文件夹必须是**该库自己的**（否则这接口就成了「往任意目录写文件」的洞）/ 该库生效白名单必须收得了这个格式（`library.accepts_ext` 是唯一真值源）—— 收进去也扫不到 = **隐形文件**，比直接拒收更糟。⚠️ 一处刻意判断：`supported()` 的早退在**显式指定目标库**时必须让位给 `accepts_ext`，否则「待复核」条目点入库永远静默无效（假交互）。

### 线 B：重命名 / 匹配书库（前端）

- 条目行加两个动作、**只给未入库的条目**（`就绪` 一律不显示）。重命名是**行内输入框**（预填**含扩展名的完整文件名**；只认 Enter / Esc 与 ✓ / ✗，**不做失焦提交** —— 点一下别处就把名字改掉的误伤比「多点一下」贵得多；失败保持编辑态；名字清空时说一句而不是静默关掉）。
- 「入库到…」是居中弹窗（骨架照 `BookMoveDialog`）：先选库 → 该库的文件夹下拉默认**第一个** → 默认选**第一个收得了这个格式的库**；收不了的库**照列 + 写明原因**（抹掉它用户会以为库没建好）；成功后关弹窗、失败**不关**。id 就是文件名 ⇒ 改名成功后必须重载列表。
- **复核头七处**：原先多处写着「不做单点目标库 / 文件夹」，逐处写明「原先为什么不做 / 现在为什么做」—— 统一口径是那句仍然成立（设置项确实没有），被推翻的是「由它推出『不能指定目标』」这一步（现在有**按次指定**的入口）。**不新增数据模型**：目标库 / 文件夹只在入库那一刻由用户选、随即透传，不落库、不记忆。

### 验证

- 新建 `tests/test_book_dock.py` **26 例**（该链路此前**零后端测试**）；`test_library_conflicts.py` 补 3 例；前端新增 5 个 spec（`AppHeader` / `AppSidebar` / `TaskFlyout` / `nav` / `BookDockPage`，前四个此前零 spec）。契约测试新增：`BookDockPage.vue` 里那句 `v-else-if` 只许出现 **1 次**（钉住 B1 不许长回来）、图标名对表、五个新 spec 的登记。
- **变异实测逐条命中并还原**：后端 5/5（去掉 `accepts_ext` / 去掉扩展名检查 / 去掉 `lib is None` 条件 / 去掉 `is_ignored` 检查 / 把「文件夹属于该库」改成恒假）；前端 6/6（动作不按状态显隐 / 入库默认吃列表第一个库 / 提交时不带目标 / 改名失败也退出编辑态 / 收不了也放行 / 渲染文本里写 markdown 星号）。
- 基线 pytest SQLite **1182 例**（0 失败 / 0 错误 / 7 跳过）、PG **1182** 例（0 / 0 / 1）；vitest 30 文件 319 例；`vue-tsc --build --force` 退出 0。
- ⚠️ 踩坑：PG 侧只给 `NOVELFORGE_DB=pg` 而忘了 `NOVELFORGE_PG_DSN` 时，夹具会以 `PgUnavailable` 把 831 个用例判成 **error**（不是跳过），必须两个都给才算跑过 PG。

---

## 第 66 期（2026-09-28）：阅读器「自动续接」收尾 —— 三处收敛为单一真值源 + 默认值统一为开

**范围**（用户拍板）：本期只做核心/低风险项；「打开提速专项」顺延第 67 期。

### 问题（三份拷贝 = 三个真相源）
漫画 / PDF / 有声书三处**各写一份**同样的「取系列下一册」逻辑（`api.seriesDetail` → `sortBySeriesIndex` → 找当前书 → 取下一本 → `router.push`），于是：
- 文案混用（漫画「下一**本**」vs PDF「下一**册**」；有声书**没有**「无系列」提示，静默停下）；
- 有声书**缺单飞闸**（漫画 / PDF 有）；
- 三处默认值不一致（EPUB 续章默认开，三处跨册默认关）。

### 一、收敛到 `frontend/src/lib/seriesNext.ts`（唯一真值源）
- `SERIES_NEXT_MSG`：三条文案常量，统一「册」口径（无系列 / 已是末册 / 请求失败）。
- `resolveNextVolume(series, bookId, fetchSeries?)`：**纯函数**，返回 `{next, reason: ok|no_series|last|error, message?}`；异常在内部收敛为 `error`，**绝不外抛**；`fetchSeries` 可注入 ⇒ 单测完全离线。
- `useSeriesNext().goToNextVolume({enabled, series, bookId, routeBase, beforeJump})`：`enabled` 门（关着**静默返回、不弹提示**，保持既有行为）→ 解析 → 按原因弹提示（**同类提示 2s 节流**、跨因立即放行）→ 命中则先 `beforeJump` 再 `router.push`；模块级**单飞闸**。
- ⚠️ 触底闩 `autoNextArmed` **留在组件**（属滚动渲染态）；三处组件**不再各写文案 / 各拼 `seriesDetail + sortBySeriesIndex + findIndex`**。

### 二、默认值统一为「开」（只改 DEFAULTS，不迁移存量）
- `comicPrefs.autoNext` / `pdfPrefs.autoNext` / `audioPrefs.autoNextBook` 三处默认 `false → true`，对齐 EPUB 续章（`readerPrefs.autoNextChapter` 本就默认开，是「同本内续章」，另一维度）。
- 读取仍是 `{...DEFAULT, ...stored}` ⇒ 没存过拿新默认；**用户自己关过的不被偷偷打开**（不加迁移标记）。

### 三、文案统一（设置页 + 提示）
- `ComicsPage.vue` 开关标题「自动翻到下一**本**」→「自动翻到下一**册**」；PDF / 有声书页本就为「册」。
- 三处续接提示统一：无系列 →「这本没有系列信息，无法自动翻下一册」；已末册 →「已经是系列最后一册」；失败 →「找不到系列下一册：…」。
- 有声书**补上「无系列」提示**（此前静默停下）。

### 四、防刷屏（默认开之后的必要护栏）
默认开之后，在无系列 / 末册的漫画或 PDF 上翻页模式连点「下一页」会每次越界各弹一次提示 ⇒ 共享模块对**同类提示做 2s 节流**（跨因立即提示）。

### 验证
- 前端 `type-check` / `build` / `deploy` 全绿；`npm run test:unit` **334 例全过**（新增 `frontend/src/lib/seriesNext.spec.ts` 15 项：文案常量、`resolveNextVolume` 四态与寻位、`enabled` 门、单飞闸、同类节流与跨因放行、`/read` 与 `/listen` 两种 `routeBase`、落盘先于跳转）。
- 真浏览器（隔离实例 8412，Edge）实测三个设置页：开关标题均为「自动翻到下一册」且**默认 `aria-checked=true`**；把有声书开关**关掉后刷新仍是关**（证明「存过即尊重、不被新默认覆盖」）。
- ⚠️ **未做端到端浏览器续接验证**：需一本多册同系列书（漫画 / PDF / 有声书），隔离实例无书库；该链路由上述 15 项单测覆盖（含节流 / 单飞闸 / 无系列 / 末册）。
- ⚠️ **期号说明**：本条原计划编号「第 62 期」，落地时发现**其它会话已把第 62–65 期用掉**（全库失效判据、PG 迁移序列、文件维度读点、批注位置锚、书卡菜单与删书、Book Dock 入口等），故本段改排 **第 66 期**；内容与用户拍板范围不变。

## 第 67 期（2026-09-28）：提速验证与收尾 —— 响应 gzip + 并发请求去重

**动机**：第 61 期遗留的「③ 打开提速」本拟排本期，落地时发现**第 62 期已把它做完**（书目索引落库
266 本 42 s → ms、PG 可选、Redis 缓存、增量 stat 3→1）。故本期改为**验证并收尾**：自建 500+ 合成书大库
复现，核实提速真实有效、找残留热点，**只修有量化指标的**。

### 复现方法（可重跑）
- 合成库：`.venv` 的 `ebooklib` + `PIL` 生成 **600 本真实 EPUB**（元数据 / 长短不一的简介 / 封面 JPEG /
  1/3 带系列与序号），落临时目录；`LIBRARY_SOURCE_DIR` 指过去，临时实例建库 → 扫描。
- ⚠️ **计时一律用 `curl`**：PowerShell 的 `Invoke-RestMethod` 解析 1.3 MB JSON 会把 **65 ms 测成 613 ms** ——
  那是客户端解析噪声，不是服务端慢（本轮第一版基线就差点被它带偏）。

### 基线（600 本，热态，curl）
| 项目 | 数值 |
| --- | --- |
| 冷扫描（建索引）| **600 ms** |
| `GET /api/books` | **65–73 ms / 1.36 MB**（其中简介 `description` 占 **68%**）|
| `GET /api/books/{id}` | 42 ms |
| `/api/authors` | 37 ms / 61 KB |
| `/api/library-facets` | 32 ms |
| 单章 / 封面 | 5 ms / 4 ms |

结论：**后端已经不慢**，第 62 期的索引确实生效（旧基线「266 本 42 s」再没出现）。另外确认两件事：
封面是**懒加载**（仪表盘只取 18 张，不是 600 张）；全站**此前没有任何响应压缩**。

### 修一：响应 gzip（`novelforge/server.py`）
- 挂 Starlette `GZipMiddleware`（`minimum_size=1024`、`compresslevel=5`，额外排除
  `application/octet-stream` / `epub+zip` / `pdf`）。
- 安全性依据（读 Starlette 实现确认）：**206 部分响应永不压缩**（音轨 / PDF 的 Range 字节区间不受影响）、
  `audio/*` / `image/*` / `video/*` / `font/*` / `application/zip` 默认排除、≥128 KiB 的响应走**工作线程**
  压缩（不阻塞事件循环）。
- 实测体积：`/api/books` **1,363,248 B → 490,878 B（−64%）**；前端主包 JS **1,018,573 → 301,000（−70%）**、
  CSS **121,426 → 19,628（−84%）**。
- ⚠️ **两面都记**：代价是该端点服务端 **+约 45–60 ms CPU**（大响应压缩）—— **LAN 上大致打平、
  WAN/VPN 上显著更快**；小响应（<1 KiB）完全不受影响。

### 修二：并发重复请求收敛为「单飞闸」（前端三个 store）
- **根因**：各处守卫是 `if (loaded) return`，但它**在发请求之前先 `await` 了别的**（阅读阈值等）——
  这是个让步点，于是首屏同一批微任务里的调用者**全都通过守卫**。实测一次页面加载
  **`/api/books` 打了 7 次**（2.8 MB、累计 3.6 s），`/api/stats` ×3、`/api/libraries` ×3、`/api/collections` ×2。
- **做法**：`stores/library.ts`（`loadBooks` / `loadLibraries` / `loadLibraryFacets`）、
  `stores/stats.ts`（按**书库**记在飞请求）、`stores/collections.ts` 各持一个在飞 Promise，并发调用共享它。
- ⚠️ **`collections` 的 `force` 语义必须不同**：`create` / `remove` / `rename` 刚改完服务端、必须拿新数据 ⇒
  force 走「**等前一次落地、再拉一次**」而不是复用在飞请求 —— 否则会把**刚建的收藏夹吞掉**。
- 实测（同一页面加载）：`/api/books` **7 → 1**（2.8 MB → 0.49 MB）、`stats` 3 → 1、`libraries` 3 → 1、
  `collections` 2 → 1；整页首次加载 **≈4 MB → 1.04 MB / 54 个请求**。

### 契约与验证
- 新增 `frontend/src/stores/loadDedup.spec.ts`（6 项）：并发 3 次只打 1 次、已有数据短路（既有行为不回归）、
  `collections` 的 force「等前一次再拉」且最终拿到新数据。
- 后端全量 **1182 例 / 0 failed / 0 error**（163.9 s）；前端 `type-check` 0 错 + `test:unit` **340 例** +
  `build` + `deploy` 全绿。
- 真浏览器（隔离实例 8413，Edge）：gzip 生效（`transferSize` 491 KB vs `decodedBodySize` 1.36 MB）；
  去重后「重复端点」表里只剩**登录前那一次 337 B 的探测请求**（不是数据拉取）。

### 仍未做（如实记录，未修即未修）
- **`/api/library-migrations/preview` 每次打开调 2 次、每次约 300 ms**（响应只有 1 KB）—— 出处是
  `MigrationGateDialog.vue` 的全局 `onMounted(load)`。它既是**重复调用**又是**慢端点**，本轮没动。
- `GET /api/books` 的 68% 体积是简介，理论上可从列表里摘掉，但**前端两处真在用**
  （`MetadataPage.vue` 的元数据缺口筛选、`BookPreviewDialog.vue` 的快速预览）⇒ 属**契约变更**，留待有需求再议。

## 第 68 期（2026-09-28）：收掉第 67 期留下的两处 —— 列表不发简介 + 迁移预览提速去重

**来源**：用户点名把第 67 期「仍未做」的两条做掉（原话见 docs/TODO.md 的历史条目）。

### 一、`/api/books` 不再下发简介正文（改发 `has_description`）
- **做法**：`server._card()` 里把 `description` 换成布尔 `has_description`。
  `_card` 是**所有**书目列表的统一出口（`/api/books`、系列、作者、演播者、收藏夹），所以口径一处改、各处一致。
- **实测（600 本库）**：原始 **1,363,248 B → 417,189 B（−69%）**；
  **gzip 后 491 KB → 37 KB** —— 去掉高熵的简介正文后，剩下的字段重复度极高、压缩率进一步提升。
- **两处消费方同步改造**（这就是当初判「契约变更、需先确认」的原因）：
  - `views/settings/pages/MetadataPage.vue` 的「元数据缺口」筛选：`!b.description` → `!b.has_description`；
  - `components/book/BookPreviewDialog.vue` 的快速预览：简介改从**它本来就会调的详情接口**取
    （浮层原本就为了章节数调 `GET /api/books/{bid}`），列表侧的 `book.description` 不再被读。
  - `lib/api.ts` 的 `BookCard.description` 改为**可选**并新增 `has_description` ——
    这一步让 `vue-tsc` 把所有「还以为列表带正文」的地方**一次性报出来**（实测只有上面两处）。
- **契约**：新增 `tests/test_card_payload.py`（2 例）——列表里**没有** `description` 且 `has_description` 正确、
  详情仍带正文；以及系列列表同口径。⚠️ 这条必须有契约：失效时不会报任何错，只有传输体积悄悄翻三倍。

### 二、`/api/library-migrations/preview`：快 8 倍 + 调用次数减半
- **慢的根因**：`core/migrate.preview()` 对**每一本书**都调一次 `libraries_of_type(t)`（= `library.libraries()`，
  读库表 + 组装列表）。600 本的库实测仅这一项就约 200 ms（端点整体约 300 ms）。
  改为**循环外算一次**「类型 → 同类库」与「id → 库」两张映射；目标库根也按库缓存（`roots_by_lib`）。
  另把选目标库的逻辑抽成 `_pick_from(dsts, …)`，`_pick_dst` 保留为便捷包装。**口径不变**（`test_migrate.py` 全过）。
  实测 **~300 ms → 37 ms**。
- **被调 2 次的根因**：`App.vue` 里 `<MigrationGateDialog v-if="!showLogin">`，而 `showLogin` **初值是 `false`** ——
  未登录时先挂载（打一次预览）→ `auth.init()` 失败置 `showLogin=true` 卸载 → 用户登录后再挂载（再打一次）。
  改用新增的「鉴权已裁决」标记 `authChecked` 门控。
  ⚠️ **不能直接用 `auth.ready`**：它在 `auth.init()` **内部**就先变真，而 `showLogin` 要等 `await init()` 回到 App.vue
  才赋值 —— 中间那一个 tick 里 `ready=true && showLogin=false`，照样会多挂一次。实测改前 2 次 → 改后 **1 次**。

### 验证
- 后端全量 **1182 例 / 0 failed / 0 error**（163 s 级），另加本期新契约 2 例；前端 `type-check` 0 错 + `test:unit` **340 例** + `build` + `deploy` 全绿。
- 真机（600 本合成库 + 隔离实例 + Edge）：`/api/library-migrations/preview` 一次页面加载**只调 1 次**；
  `/api/books` 一次真实拉取（gzip **38 KB**）；`preview` curl 热态 37–41 ms。

### 仍未做（顺延，已记入 docs/TODO.md）
- **未登录冷访问会先渲染一次外壳、白发约 10 个 401 探测请求**（每个 337 B）。成因与本期 `MigrationGateDialog` 同源
  （外壳挂在 `v-else`，`showLogin` 初值 false）。没动的原因：这批是**廉价探测**，而把外壳也 gate 到 `authChecked`
  会让**已登录用户的冷启动**多等一次 `api.me()` —— 要先量再决定（docs/TODO.md P2）。

## 第 69 期（2026-09-28）：滚动模式改成「跨章连续流」—— 读完自然接下一章、向上滚能读回上一章

**来源**：用户原话 ——「电子书阅读时，使用滚动模式的情况下，若涉及到下一章节，切换时要求无缝切换，不能跳跃到下一章。且使用滚轮可以自由阅读上一章与下一章。」

### 问题（改造前）
`ReaderView` 的滚动模式是**单章替换**：滚到底（160px 内）→ 取下一章 → `html.value = 下一章`（整章替换）→
`el.scrollTop = 0`。于是用户看到的是「正文被换掉 + 跳回页首」；向上滚最多到本章开头，回不到上一章。

### 一、新增 `frontend/src/lib/readerFlow.ts`（连续流的唯一真值源，纯函数、有单测）
- `computeWindow(visible, total, enabled)`：窗口 = 可见章 ±1；**开关关着时不给未来章**（只给 `[v-1, v]`），
  但**历史章始终给** ——「向上滚能读回上一章」与开关无关，开关只管「要不要自动往后接」。
- `pickVisiblePos(chunks, scrollTop, clientHeight)`：以**视口中线**为基准，取「顶部不超过它的最后一块」；
  几何量全为 0（无布局环境）时**保守返回第一块**，绝不凭零值编位置。
- `localFractionIn` / `scrollCompensation` / `canTrim`（离开视口且上下各留 ≥1 屏才允许裁）。
- 30 例契约测试（`readerFlow.spec.ts`）。

### 二、`ReaderView` 的章块窗口（`chunks`）
- 仅「EPUB + 滚动模式 + 可重排」走新路径（`flowMode`）；翻页 / PDF / 漫画 / **固定版式**全部走旧路径。
- 每章一个 `<section class="nf-chunk">` + 独立 `.reader-content` root；章间有标题与分隔留白；
  **正文自带标题**时不再叠一个（`bodyHasHeading`：`chapter_html` 抽的 body 多数以 `<h2>` 开头）。
- **无缝的物理机制**：`applyChunks()` 用**锚元素实测位移**补偿 —— 追加下方天然为 0；前插 / 裁上方同量回补
  `scrollTop`。三处关键修正都是真机量出来的（不是推理出来的）：
  1. 锚必须取**正文 article**（不是外层 `<section>`）：`first:` 变体带来的 `pt-6` 不在 section 的
     border-box 里，实测漏 **24px**；
  2. 补偿必须写成**绝对值** `beforeTop + 补偿量`，不能 `+=`：浏览器自带 scroll anchoring 常常已经替我们
     调好 `scrollTop`，相对累加会把同一段位移**补两次**；
  3. 锚必须是**已存在**的章块：新补进来的章此刻还没有 DOM，拿它当锚等于没有锚（会跳一屏）。
- **并发加固**（真机踩到）：`fillFlowWindow` 与 `maintainFlowWindow` 会同时想要同一章 ⇒
  ① `chapterAt` 加**在飞请求合并**；② 合并前**重新**读当前章块集合；③ `normalizeChunks` 按 `pos` 去重
  （`:key` 重复会让 Vue patch 失去定义，实测渲染出「上一章排在中间」的错序 DOM）；④ 章块落地走
  `chunkWriteChain` 串行链（补偿是「量一次 → 改 DOM → 再量一次」，并发会让补偿量算重）。
- 进度 / 批注 / 选区 / 跳转全部切到**可见章 + 章块 root** 口径（`currentChapterRoot` / `chapterRootAt` /
  `chunkPosOfNode`），保住第 54 期的 CFI 章内精确偏移（`offset = local × 可见章 textContent.length`）；
  `applyHighlights` 改为按章块 root 渲染并**先解包再包裹**（窗口滑动会复用同一块 DOM，重复包裹会 span 套 span）。
- `chapterCache` **4 → 6**（窗口 3 章 + 一次补章余量；仍是有界缓存）。
- 窗口维护收尾会按最新可见章**再校一趟**：否则会卡在「窗口边界 + 没有新内容」——底部到头后不再有滚动事件，
  窗口也就不再补，用户得先往上滚一下才能继续。

### 三、开关语义与文案
- `readerPrefs.autoNextChapter` **默认值不变（仍是 true）**，语义改为「连续读」：开 = 滚到窗口边缘自动补下一章；
  关 = 不往后补，读到底停下并露出「下一章」按钮，**不替换、不跳变**。
- 面板文案（`flowMode` 时）：「滚动模式**连续读（跨章无缝）**（相邻章接在一起，读到底自然进下一章、
  向上滚可回上一章；关掉则读到底停下并显示「下一章」按钮）」；固定版式保留旧措辞（那里确实还是旧行为）。
- 开关一改就**立刻**校正窗口（`watch`）：否则用户正停在窗口末尾时打开开关**没有滚动事件**，会以为开关没反应。

### 验证
- 前端 `type-check` + `build` + `deploy` 全绿；`test:unit` **371 例全过**（新增 `readerFlow.spec.ts` 30 例；
  重写 ReaderView 两条续接用例为新语义、新增「向上滚回上一章」；两个 spec 里原先依赖「正文只有一章」的断言
  改为看**底栏当前位置**——连续流下下一章本来就在正文里，那正是本功能要的效果）。
- 真机（自建 6 章 EPUB + 隔离实例 8413 + Edge），逐项实测：
  - 初始窗口 `[0,1]`，两章**同时**在正文里（`fixed_layout: false` ⇒ 走连续流）；
  - **向下追加**：`scrollTop` 与探针章块的视口位置**逐字不变**，`scrollHeight` 4050 → 7691；
  - 窗口滑到 `[2,3,4]`（首两章被裁，内存有界）；
  - **向上前插**：`scrollTop` 0 → 3642（= 前插高度），探针章块与更下方章块的 `artTop` **3783 → 3783**
    （残差 1px 亚像素）；
  - 关掉开关：窗口停在 `[0,1]`、`scrollTop` 到底、不替换不跳，「下一章」按钮可用；**仅**再打开开关
    （不滚动）立即恢复补章；
  - 滚轮全程不被劫持；滚动 ↔ 翻页切换后章块结构进出干净、位置与页码保持；重载后按可见章恢复进度。

### 未做 / 取舍
- **固定版式（pre-paginated）EPUB 不走连续流**，保守沿用旧的单章替换路径：页尺寸由书本身决定、
  与 `nf-fixed` 中和样式耦合，纵向拼接风险高；面板文案在那里也保留旧措辞。
- **章块内图片的异步解码**靠浏览器自带 scroll anchoring 兜底（本项目**未**改成 `overflow-anchor: none`
  + 自管）：实测两者的关系是**互补**而非冲突（谁先生效都不会补两次），自管反而会与它叠加。
- 真机冒烟用的是每章纯文本的合成书；**插图很多的书**在前插后图片逐张解码时的手感未单独量过。

## 第 70 期（2026-09-28）：收书目录「上传」按钮 + 全站开关胶囊收敛为唯一实现

**来源**：用户点名两项前端任务（原文见下）。

### 一、收书目录工具栏新增「上传」（`views/settings/pages/BookDockPage.vue`）
- 「暂停」按钮在标题行工具栏内；新按钮紧随其后 ⇒ 顺序 `立即扫描 | 暂停·开始监听 | 上传`。
- **复用既有接口，后端零改动**：`api.convertDrop(file)` → `POST /convert`（FormData，写进 `INPUT_DIR` 后走既有管线）——
  这正是本页「整页拖拽投递」用的那条路。
- **把拖拽的投递逻辑抽成 `deliverToDock(files)`**，拖拽（N 个文件）与上传（1 个文件）共用同一份
  守卫 / 反馈 / 刷新（否则同一件事两套实现，迟早一处给明确原因、另一处静默）。0 库拦截抽成 `blockedByNoLibrary()`。
- 按钮：`variant="primary"`（用户指定强调色）、`size="sm"`、纯文字、`title` 与 `aria-label` 均为「上传」；
  `Button.vue` 未声明 `inheritAttrs:false`，`aria-label` 会落到根 `<button>`（实测 class 串与邻居逐字一致）。
- 隐藏 `input[type=file]`：**不加 `multiple`**（单文件）、**不加 `accept`**（与拖拽同口径，由后端判格式）；
  ⚠️ 处理完必须 `input.value = ''`，否则「连续两次选同一个文件」第二次不触发 `change`。
- 上传中 `disabled` + 文案「上传中…」；0 库时不禁用而是 toast 说明原因；失败文案改用 `apiErrorMessage`
  （原先拖拽直接用 `err.message`，会把后端 `{"detail":…}` 的括号原样露给用户）。
- **项目没有 i18n**（`vue-i18n|useI18n|$t(` 零命中）⇒ 文案为中文字面量。

### 二、开关胶囊抽成唯一组件 `components/ui/Switch.vue`
- 改造前实测「各写各的」：小胶囊 `h-[18px] w-8` 在 **8 个文件 11 处**，另有大胶囊
  `h-5 w-9 + transition-[left] + shadow-xs`（`MetadataPage` 书源开关，第 12 处），
  以及 7 项**原生复选框充当开关**（落在 9 个 DOM 位上）。
- 组件：`button[role=switch]` + `aria-checked` + 内嵌滑块；props `modelValue / disabled / title / ariaLabel`，
  emits `update:modelValue`。空格与回车由原生 button 保证（不必自己补键盘处理）。
  焦点环**不自写** —— 全局 `:focus-visible`（`assets/main.css`）已统一；`prefers-reduced-motion` 也由全局接管。
- 配色全部走主题变量（`--primary` / `--muted` / `--card` / `--border`），**禁写死色值**；
  滑块用 `bg-card` 而非硬编码白色：深色主题下 `--primary` 是**浅色**，写死白滑块会在浅色轨道上糊掉。
- **迁移 21 处**（收尾用 `grep '<Switch'` 数准：21 个使用点、14 个文件）：
  **12 处旧胶囊** —— `SettingsFieldRow`、`ReaderAudioPage`、`PdfPage`、`ComicsPage`×2、`BookDockPage`×2、
  `AuditLogPage`、`IntegrationPage`、`MetadataPage`（原大胶囊）、`DashboardSettingsSheet`×2；
  **9 处开关语义复选框** —— 表格隔行底色、筛选预览默认展开、系列默认折叠、归档时压缩、两端对齐×2
  （`ReaderEbookPage` 与 `ReaderView`）、断词×2、连续读。
- ⚠️ **`v-model` 与「落盘」监听器的执行顺序不由我们决定**：`v-model="x" @update:model-value="persist()"`
  可能先 persist 后赋值 ⇒ 存下旧值。所有「赋值 + 副作用」站点统一写成一条内联语句
  `:model-value="x" @update:model-value="x = $event; persist()"`。
- ⚠️ **关态圆点在两种主题下都不够清楚**（实测浅色 `--muted` 0.955 vs `--card` 0.975、深色 0.245 vs 0.18），
  故给滑块加一道 `border-border` 细边 —— 放大 6 倍对比图确认后才加的，不是凭感觉。

### 验证
- 前端 `type-check` + `build` + `deploy` 全绿；`test:unit` **384 例 / 34 文件全过**
  （新增 `components/ui/Switch.spec.ts` 8 例契约 —— 含「不许出现写死色值」「尺寸/过渡唯一口径」「disabled 样式」
  「title/aria-label 可选」；`BookDockPage.spec.ts` 新增 5 例：按钮属性、点击只开选择器、投递成功且 input 清空、
  失败带文件名与原因、0 库不投递并说明）。
- 真机（隔离实例 8414 + Edge），逐项实测：
  - 上传按钮：`title`/`aria-label` 均为「上传」、class 串与邻居逐字一致、`variant=primary`；隐藏 input
    `multiple=false`、无 `accept`；**真机投递一个 .txt 成功** —— 文件出现在 `INPUT_DIR`，随即被处理进库
    （`/api/books` 出现 `upload-smoke`），整条链路打通；
  - `role="switch"` 全仓只剩 `Switch.vue` 一处（自动化 grep 断言，杜绝再长出副本）；
  - 四个页面共 **14+12+2+2+1 处**开关实测尺寸一律 **18×32**（含原 20×36 的元数据书源开关）；
  - **空格键切换**实测生效（`aria-checked` false→true，轨道同时换 `bg-primary`、滑块 `translate-x-[16px]`）；
  - **点标签文字仍能切换**（`<label>` 包住按钮时浏览器会把点击转给控件）—— 既有行为未退化；
  - 浅/深主题下计算色分别等于 `--primary` / `--card` / `--muted`（跟随 token，不是编译期定值）。

### 明确不动（本期范围外，附理由）
- **多选/全选**：`ShelfView`×3、`BookDockPage` 条目行、`MetadataPage` 迁移行、`KomgaPage` 表行、`ScrapePanel`×3
  —— 语义是「多选」，做成胶囊会让「勾了几本」失去含义。
- **筛选**：`KomgaPage` 只看冲突、`AuditLogPage` 仅看未记录、`AnnotationsView` 仅当前书库。
- **确认勾选** `ScrapePanel`「我已知晓原文件将被移入回收站」、**只读展示** `MigrationGateDialog`、
  **菜单勾选** `BookActionsMenu`（`role=menuitemcheckbox`，不是胶囊）。
- **身份也是布尔开关、但不在用户点名清单内**（一句话即可追加）：`tools/SourcesView`（公版/合规）、
  `tools/LibrariesView`×3（自动执行 / 监听来源子目录 / 刮削出版）、`tools/LibraryWizard`×2、
  `charts/ChartConfigPanel`（显示该模块）。

### 未做
- 「上传中…」与禁用态在本机**太快**（本地投递 1 秒内完成），真机没截到那一帧；逻辑与文案由单测 + 组件契约覆盖。
- 上传失败的最新路径（例如后端拒收）只在单测里验证过（mock 抛错 ⇒ toast 带文件名与原因）。


## 第 71 期（2026-09-28）：探索发现做扎实（闸门真生效 / 逐源状态 / 同名合并 / 真分页）

**缘起，以及一条明确不做的决定**：用户最初提的是「探索发现增加对 zlibrary 的下载支持」。
查证后**维持第 57 期已拍板的结论：zlibrary 专用下载不做**（那次就写明了理由 —— 盗版分发平台，
以「通用书源 + 投递」替代，见 `README` 的合规口径与第 57 期记录）。改为把「探索发现」这条
链路本身做扎实，用户逐项拍板：闸门接真拦截、分页做真分页（改 adapter 契约）、重复结果同名合一条可展开。

### 一、修掉四处真实缺陷（前三条都是「功能坏了、但没有测试挡住」）
1. **来源字段错配 ⇒ 预览必然失败**：后端 `manager.search()` 只写 `_source`，前端 `SearchHit`
   读的是 `source` ⇒ 结果行的来源徽章空白，点「预览」传 `undefined`，被后端拒成
   502「未知书源: undefined」。修法：`_mark()` **一处**写全 `source` / `source_name` / `_source`，
   并用唯一读法 `source_of(item)`（两个键都认、新键优先）统一 `download_to` / `preview` /
   sidecar / 任务 `detail`。⚠️ 任务详情里的来源一栏此前也一直是空的（那里读的是不存在的 `source`）。
2. **「部分书源检索失败」是死 UI**：后端 `/api/search` 只回 `{count, results}`，失败原因被吞成
   `logger.warning`；前端读的 `r.errors` 永远为空。现在后端回**逐源状态**
   `sources=[{name, display_name, ok, count, error, skipped, reason, has_more}]`，
   界面顶部一行汇总（成功 / 失败 / 被跳过）+ 展开看**原因原文**；空的 `errors` 字段下线。
3. **界面写「正在并发检索各书源」，实现是逐源串行 await**：`for … await` 改成
   `asyncio.gather` + **每源** `asyncio.wait_for(SEARCH_TIMEOUT=20)`。顺带覆盖规则源
   `client.get_text` **没传 timeout** 的裸奔（一个慢站能把整轮搜索拖到超时上限之下）。
   `SEARCH_TIMEOUT` 用模块常量而非新配置键（见「未做」）。
4. **下载闸门是假开关**：设置页承诺「关闭时书源仅做规则管理，不可搜索下载」，而
   `download.enabled` / `public_only` 只在 `store.sources_status()`（展示）、
   `manager._visible_sources()`（**死代码，全仓无调用者**）与 CLI 里生效 ——
   `/api/search`、`/api/download`、`/api/preview` 谁都不检查。现在收敛到
   **唯一判定** `DownloadManager.gate_reason(source=None)`（空串 = 放行）：

   | 位置 | 行为 |
   | --- | --- |
   | `/api/search` | 闸门非空 ⇒ 400 + 原因原文（含「设置 → 网络与下载」出口） |
   | `/api/download` | 同上；**未知书源也即时 400 且不进队列**（原先先建任务再后台失败） |
   | `/api/preview` | 同上（预览也是真的外呼书源，不拦就是给闸门留了一扇窗） |
   | `store.sources_status()` | `usable` / `blocked_reason` 改由它产出 —— 界面显示的原因与接口拒绝的原因是**同一句原文** |
   | `/api/sources/test` | **刻意不拦**（管理面自检）：下载关着也要能验证「我写的规则还能不能用」，否则书源管理页的自检按钮一起瘫 |
   | 前端探索发现页 | 进页面先读 `/api/sources/status`，关着就**提前**把搜索框 / 检索 / 热词 / 预览 / 下载全部置灰 + 顶部说明 + 直达设置页的链接（不允许「点了才吃 400」） |

   `public_only=true` 时**搜索直接跳过非公版源**并在逐源状态里标 `skipped` + 原因，
   而不是「搜出来、等点下载才拒」—— 后者是一条点了才报错的死路。

### 二、真机冒烟才现形的两个缺陷（单测看不到）
5. **`httpx.CookieJar` 根本不存在**（`core/network.py`）：httpx 0.28 的 cookie 导出只有
   `Cookies` / `CookieConflict` ⇒ **每个书源一构造 `BrowserClient` 就 AttributeError**，
   搜索恒 0 条、下载恒失败。写成标准库 `http.cookiejar.CookieJar`（httpx 的 `cookies=`
   原生接受它，与既有 `_load/_save_cookies` 直接配套）。没被测试挡住的原因很典型：单测都用桩
   client（`_NoNetworkClient`），只有真机会现形 —— 也正是本期把「逐源失败原因」显示出来后才查到。
6. **规则源搜索命中的相对地址没补绝对地址**：`_extract_links`（章节目录）一直在做 `urljoin`，
   而 `_parse_search`（搜索结果）没有 ⇒ 真实站点几乎都用 `/book/123` 这种相对链接，
   于是预览与取书都以「Request URL is missing an 'http://' or 'https://' protocol.」失败，
   报错还离原因很远。新增 `_absolutize(item, base_url)`，只对相对地址生效（对绝对地址**幂等**，
   既有规则零影响），并在规则文档里写明「相对地址也可以」。

### 三、新增能力
- **同名合并成一本书**：`lib/searchResults.ts`（纯函数 + 27 例契约）做
  `normalizeTitle`（NFKC 全角→半角、去书名号/标点/空白）/ `normalizeAuthor`
  （多作者取第一个；「未知/佚名/N/A…」一律归为**不知道**）/ `groupHits` / `rankGroups` /
  `appendHits` / `keepLoadingMore` / `mergeSourceStates` / `splitSources`。
  ⚠️ **合并刻意保守**：书名与作者**都**归一化成功且分别相同才合并 —— 作者未知不并、
  卷次/副标题差异不猜（「三体」与「三体 2」不会并成一本）。结果区因此从「一行一源」
  变成「一书一行 + `N 条来源` 可展开」，展开后每个来源各自预览/下载（展开时组行那一对按钮收起，
  避免两个看起来一模一样的「下载」）。
- **匹配度排序**：书名完全相同 > 前缀/包含 > 其它；同档内有作者信息的优先；其余保持后端顺序
  （稳定，且**不就地改**入参数组）。
- **真分页**：`SourceAdapter.search_page(client, title, page=1) -> {items, has_more}`。
  基类默认实现给不支持分页的源兜底，关键是 `page > 1` 返回**空**（否则「加载更多」会把第一页
  再显示一遍）；`GutenbergSource` 用 gutendex 自带的 `next` 判 `has_more`（`page=1` **不带**
  `page` 参数，与加这个能力之前逐字节同一请求）；`RuleBasedSource` 只在 `search.url` 含
  `{page}` 时才替换、否则 `has_more=False`（不知道就说不知道）。`/api/search` 增可选 `page`，
  回 `has_more`（任一源还有下一页）；前端「加载更多」是**追加**，并在「这一页没带来新条目」时
  收起按钮（站点不认 `{page}` 会回吐同一页，留着按钮就是假交互）。
- **行内任务状态**：发起下载后按 `task_id` 走既有 tasks store，在结果行显示
  「已入队 / 下载中 / 已完成 / 失败 + 原因原文」，**不新增第二套轮询**。

### 契约与验证
- 新增后端 `tests/test_sources_gate.py`（9 例）+ `tests/test_sources_search.py`（12 例，
  零网络桩）：闸门三端点与试搜豁免、界面原因与接口拒绝原因同源、被拦下的下载**不进队列**、
  逐源状态、真并发（3 源各 0.3s ⇒ 总耗时 < 0.7s，串行会 ≥0.9s）、单源超时不拖垮全局、
  `page=1` 与现状等价、不支持分页的源第二页为空、`{page}` 只在模板写了才取下一页、相对地址补全。
  后端全量 **1195 passed / 12 skipped / 0 failed**。
- 新增前端 `lib/searchResults.spec.ts`（27 例）+ `views/ExploreView.spec.ts`（13 例，
  该页**此前零测试**）；前端 `test:unit` **424 例 / 36 文件全过**，`type-check` / `build` /
  `deploy` 全绿。
- **真机冒烟**（隔离实例 8415 + Edge + 本机桩书源站点 8414：两个规则源指向同一站点、一个坏源连不通）：
  闸门关闭 ⇒ 置灰 + 出口文案；打开 ⇒ 检索；「已查 4 个源 · 成功 2 · 失败 2」+ 明细里
  `gutenberg 搜索超时（单源超过 20 秒）` 与坏源 502 原文（后一轮 gutenberg 侥幸通了，则是
  成功 3 · 失败 1 —— 两种都实测到，逐源状态如实跟随）；4 条命中合并成 **2 本**、
  每本 `2 条来源` 可展开；预览弹窗显示目录与首段（此前必失败且弹窗恒为空）；点下载 ⇒
  行内 `已完成` + 任务 `detail=smoke-a`（此前为空）+ **真产物 `三体.epub` 落库**；
  「加载更多」后 `共 4 条命中 · 2 本` → `共 5 条命中 · 3 本`（追加不覆盖）。

### 未做 / 取舍
- **下载功能默认就是关的**（`config.py` 的 `download.enabled: False` 没动）：改完之后，默认配置
  下探索发现会**先被拒**，需要去「设置 → 网络与下载 → 开放搜索 / 下载」打开。这是用户拍板的
  结果（「与设置页承诺一致」优先），前端已提前置灰并给出出口，所以不是「点了才报错」。
- **不做「一键重试下载」**：`tasks` 表没有可重放的源数据列，TaskCenterView 已有同一句理由；
  做出来只会是假按钮。
- **`SEARCH_TIMEOUT` 用常量而非配置项**：一次性需求，不值得再扩一套设置面板 + `config` 白名单
  （将来真要调，改常量即可）。
- **`public_only` 在搜索阶段就跳过非公版源**：代价是「用户在结果里看不到它、也就无从知道为什么
  没有它」，换来的是一条没有「点了才报错」的路径。另一条（搜出来、点下载才拒）没采用。
- **分页对「不支持 `{page}` 的规则源」无从判断**：如实报 `has_more=False`，界面不出按钮 ——
  猜「也许还有」会挂一个点了没反应的按钮。站点不认 `{page}` 时靠「本页无新条目」自纠并收起按钮。
- **同名合并仍可能漏并**（例如「三体」与「三体（全集）」）：这是**故意**的保守选择，
  并错一次会让用户下到错的那一卷，比多一行糟。
- 前端仍在同一处用 `String` 拼接展示文案，未引入 i18n（本项目无 i18n，见第 70 期记录）。

### 收尾复核（本轮）
- 后端全量 `pytest`：**1207 passed / 12 skipped / 0 failed / 0 error**（计数取自 `--junitxml` 解析，不看终端汇总行）。
- 前端四连：`type-check` / `test:unit`（**424 例 / 36 文件**）/ `build` / `deploy` 全绿。
- 真机复跑闸门**关闭**路径（隔离实例 8412 + Edge，`download.enabled=false`）：
  页面顶部「下载功能当前关闭，先打开才能检索」+ 原因原文 + 出口链接 `#/settings/ext/network`；
  搜索框 / 检索 / 热词按钮**全部提前置灰**（实测 `disabled=true`）；`POST /api/search` 实测 **400**，
  且 `detail` 与前端展示**逐字一致** —— 佐证闸门原因确实只有后端 `gate_reason()` 一处产出、前端不另写措辞。
- 真机复跑逐源状态：本机网络下 Gutenberg 超时，界面如实显示「已查 1 个源 · 成功 0 · 失败 1」，
  展开明细为「gutenberg 搜索超时（单源超过 20 秒）」，与服务端日志 `书源 gutenberg 搜索超时（> 20.0s）` 一致。
  ⚠️ 复跑时踩到一个环境坑：隔离目录若残留**上一轮的 `settings.json`**（`download.enabled=true`），
  闸门自然不会触发 —— 验「关闭态」前先确认隔离 CONFIG_DIR 是干净的。

## 第 72 期（2026-09-28）：TXT 阅读全乱码 —— 编码探测「样本截断」+ 长章书分章退化

**缘起**：用户报告经**收书目录**导入的一本 TXT「阅读时已经全部乱码」，详情页显示 **3723 章**。
先排除了导入链路（`pipeline.dispatch` 只做 `shutil.copy2`，源文件与书库副本 md5 逐字节相同，
且文件**本身是合法 UTF-8**：1,111,029 B / 373,187 字符 / 无 BOM）—— 真因是**三处判据**，
而且**只修编码不够**：编码修对之后同一本书仍会是「3723 个中文标题 + 零正文」（实测）。

### 一、缺陷 A：按字节切出来的样本，被当成了「这不是 UTF-8」的证据（`core/pipeline.py`）
`_sample_bytes` 按**字节**取头 256 KiB，切点有 2/3 概率落在 3 字节汉字中间（本书正好切在
262142-262143，`e6 b7` 是一个 3 字节字符的前两字节）；老 `_detect_encoding` 拿整段样本走
`decode("utf-8-sig")` **严格**自证，尾部不完整即抛 ⇒ 掉进 gb18030/big5 打分（utf-8 不在候选里）
⇒ 判 gb18030（实测打分 **+0.4702** 胜出，而正确的 utf-8 解得分 **+1.9375**）⇒ 全文解成乱码，
**全程不报错**（调用方还叠加 `errors="ignore"`）。影响面：任何 >256 KiB 的中文 UTF-8 TXT 约
2/3 概率命中；现有夹具都远小于 256 KiB，所以从未被抓到。

修法（判据侧放宽，采样逻辑保持单一职责）：
1. 新增 `_utf8_prefix_ok(data)`：`codecs.getincrementaldecoder("utf-8")().decode(data, final=False)`
   —— 只容忍**尾部**不足一个字符的序列，**中间**任何坏字节照旧抛（实测真 GBK / Big5 样本仍判
   `False`，容错没放宽成「差不多就行」）。解码器**有状态**，每次必须新建实例。
2. 新增 `ENCODING_RULE_VERSION = 1`（判据一改就 +1，理由同 `detect.CHAPTER_RULE_VERSION`）。

### 二、缺陷 A2：两段样本拼接，接缝处自己造了个假非法字节（同族第三处）
「开头纯 ASCII（英文前言 / 版权页）」时补采中段，起点 `size // 2` 是**按字节算**的、
多半落在字符中间 ⇒ 直接拼 `data + more` 会在**中间**放一个续字节（`0x80–0xBF` 不能当字符开头），
而前缀判定只容忍尾部 ⇒ **救不了它**，一本真 UTF-8 书照样被判成 big5（本用例实测先红才补的）。
修法：`_read_from_char_boundary(f, offset, n)` —— ① 窗口内先找换行（`0x0A` 在 UTF-8 / GBK /
Big5 里都**不可能**做后继字节，换行后必是字符边界）；② 没有换行就跳过开头的续字节。
头部那段全 ASCII ⇒ 尾部必然是边界，所以**只需对齐中段起点**。

### 三、缺陷 B：长章书被误判成「没有章节」（`core/detect.py`）
老置信闸门 `len(bounds) * 2000 >= len(text)`：本书 25 章、平均 ~1.5 万字/章，`25×2000 = 50,000
< 373,187` ⇒ 判「正则无效」⇒ 退化 `_split_by_indent` ⇒ **3723 章 / 0 字正文**（阅读器里表现为
「满屏标题、点进去没有正文」）。三处口径变化（`CHAPTER_RULE_VERSION` **2 → 3**）：

1. **置信判据加绝对条数兜底**：新公开函数 `regex_confident(bounds, text)` = 密度
   `len(bounds)*2000 >= len(text)` **或** 条数 `len(bounds) >= 3`（行首锚定之后，3 条以上行首
   章标记基本不可能是巧合）。长章不是「命中太少」。
2. **降级产物全空 ⇒ 回退正则边界**：缩进降级**一章正文都没读出来**（全顶格文本恒如此）而
   正则**有**边界时，回到正则边界 —— 几个真边界好过 N 个空正文假章。
3. **缩进降级认全角空格**：`ln[:1] in (" ", "\t", "　")`，与 `_LEAD`（`[ \t　]*`）口径对齐。
   本书 3697 行正文用 `　　` 缩进、只 26 行顶格 —— 只认半角会把**每一段**当新章首。

**同一判据不许有第二份拷贝**（AGENTS.md）：`ai_detect.HybridChapterDetector` 里那份
`len(bounds) * 2000 >= len(text)` 收敛到 `detect.regex_confident`；`mode: regex` 直接委派
`detect_chapters`（老写法少写上面第 2 条保险 ⇒ 同一文本走管线与走检测器得到**不同目录**）。
**行为变更**：hybrid 模式下长章书不再触发 LLM —— 此前一本**已经切对**的书每次都要花一次钱。

### 四、缓存失效：能改正文产出的口径都得进指纹（`core/txtcache.py` / `server.py`）
第 62 期只把分章规则版本放进指纹，本期补 **编码判据版本**：`txtcache.ENC_RULE_VERSION`
（跟随 `pipeline.ENCODING_RULE_VERSION`）写进 `state.json` 的 `enc_rule` 字段与 `_SPLIT_CACHE`
键；`server.py` 原生路线的 Redis 章节缓存 `extra` 改为 `v{RULE_VERSION}:e{ENC_RULE_VERSION}`
（这条路没有派生件指纹可用）。**老 `state.json` 缺 `enc_rule` ⇒ 不命中 ⇒ 重建一次** —— 这是
「已缓存成 ok 的乱码派生件」与「失败状态永久粘住」唯一的自愈通道；少了它，改完代码用户看到的
还是老样子，且**不报错、不重建**。

### 五、可观测：正文读不出必须留痕（同前两个文件）
`derived_epub` 失败分支写一条 `ACTION_CONVERT` + `STATUS_FAIL` 活动日志（主体 = **源文件名**，
不同书不互相合并；`_log_rule_rebuild` 那种固定标签才合并）。此前整条路**静默**：只在
`state.json` 里记个 `failed`，阅读器照渲染空章，用户在界面上拿不到任何提示。**同一（源指纹,
判据版本）只写一次**（第二次请求走 state 命中失败分支直接 `return None`）。

### 契约与验证
- 新增 18 例契约：`tests/test_detect_chapters.py`（长章书不降级 / 全角缩进降级有正文 /
  降级全空回退正则 / AI 检测器读同一份置信判据 / 纯正则模式与唯一真值源逐字一致）、
  `tests/test_txt_reading.py`（ASCII 前言的中文大书不再判非 UTF-8 / 大文件样本切在字符中间
  仍判 UTF-8（用例内**显式断言切点落在续字节**，否则用例失去意义）/ >256 KiB 的 GBK 与 Big5
  不因容错被误判 / 大 UTF-8 长章书端到端读出来是正确中文 / 编码判据升级会重读重切 /
  老 state 没有 `enc_rule` 就重建 / 正文读不出留一条失败活动日志）。
- 后端全量 `pytest`：**1219 例 / 1207 passed / 12 skipped / 0 failed / 0 error**（junit 解析）。
  中途唯一那次红是**新用例自己的断言过强**（`recent()` 在内存不足时会从 jsonl 回填，而日志
  目录与内存缓冲是**全进程共享**的 ⇒ 同会话其他用例的失败条目也被数进来）：改用 `limit=0`
  （只看内存、不触发回填）+ 按源文件名收窄；「不重复写」改用 spy 钉 —— 合并开启时**数条目
  本就没有区分力**（重复写也只会合并成一条）。
- `tests/check_doc_anchors.py`：本次改动的 4 个代码文件 **硬错误 0 / 疑似漂移 0**。
- **反向抽样**（真代码路径，非桩）：临时造两份 910,615 B 的文本，**ASCII 前言盖满整个 256 KiB
  采样窗**再写中文正文 —— GBK 版判 `gb18030`、Big5 版判 `big5hkscs`，两者解出的 607,715 字符
  **U+FFFD = 0 / 私用区 = 0**，正文首行是真中文（`第一章 起风` / `第一章 起風`）。这条路径
  同时覆盖了缺陷 A 与 A2（中段补采 + 起点对齐，采样 262144+65536 = 327,680 B）。

### 真机验收（本机容器 `novelforge-test`，端口 8993；后端改动必须重启才生效）
- 修前 `state.json`：`{"status":"failed","fingerprint":"1790597330535067000:1111029","rule":2,
  "reason":"文本读不出可读内容（空文本或编码全坏）"}` —— **无 `enc_rule` 字段**，正是自愈触发条件。
- 重启后自愈：详情 **25 章**（此前 3723）；`/api/books/{bid}/chapter/0` 的 html **24,049 字符**
  / **U+FFFD = 0** / **私用区 = 0** / 常用汉字 20,036；`state.json` 变
  `{"status":"ok","rule":3,"chapters":25,"enc_rule":1}`，`derived.epub` **480,361 B**。
- 容器内探针逐章核过：25 章正文长度 `[22667, 16732, 10330, 29326, 17000, 23456, 22147, 9, 12767,
  21, 19213, 23, 16753, 21543, 15621, 8870, 16979, 11539, 5824, 18733, 22739, 12992, 9752, 19037,
  18965]`，**空正文 0 章、总正文 373,038 字**（与修复前用正确编码解码后逐章测量**完全一致**）。
- 活动日志：本次**未**新增失败条目 —— 规则 2→3 的重建痕迹不可见是**既有合并语义**（第 61 期：
  固定标签 + 10 秒窗口内合并），不是本期引入的缺陷；新写的失败日志用**源文件名**作主体，不合并。
- ⚠️ 一个验收脚本的坑（不是产品缺陷）：起初用「HTML 里能否子串命中源正文」当判据，得到 False；
  逐字符核过 `max(html_chars - source_chars) == 0` 才确认**所有 HTML 字符都来自正确解码**，
  失配来自 `preprocess` 的文本规范化，且 `split_by_offsets` **有意**丢弃第一个边界之前的内容
  （既有约定）。**子串判据对规范化过的文本无效**。

### 未做 / 取舍
- **不把 `utf-8` 放进候选打分循环**，也不给 `_score_text` 加 U+FFFD 罚分：那是第二条判据改动；
  本期容错只放宽「样本尾部被切断」这一种情形，**中间**有坏字节仍判非 UTF-8（已实测）。
- **不做 UTF-16 / UTF-32 探测**：现候选集里没有，是另一个独立缺口，无实例，如实记着不顺手扩。
- **不重写 `_split_by_indent` 的整体启发式**：只补全角空格这一处**判据不一致**；「全顶格无标记
  文本」的正解是分章 AI 兜底（`core/ai_detect.py`，需配 `llm.api_key`）。
- **不做阅读器 / 详情页的乱码提示条**：用户拍板用活动日志。
- **不回溯重转已发布的成品 EPUB**：CLI 转换出的历史成品仍是旧口径（长章书会是 3723 章）；
  源文件不动、本项目不写回文件，要改得用户手动重跑 CLI。
- **不引 chardet / charset-normalizer**：项目铁律（零第三方依赖）。
- 本期**不动前端**（用户选了活动日志而非提示条）⇒ 前端四连免跑。

## 第 73 期（2026-09-29）：漫画 / 有声书库的「序号单元」合并成书 + 连续阅读

**缘起**：用户报告漫画库 / 有声书库里，一本书的实际形态是

```text
根目录/《转生魔女宣告毁灭（1-43话）》/若干级文件夹/第1话.pdf
                                              …/第二话.pdf
                                              …/第03话.pdf
                                              …/4 第4话.pdf
```

文件名里的序号写法**不统一**（`第1话` / `第二话` / `第03话` / `4 第4话`），而扫描层是
「一个文件 = 一本书」⇒ 书架上 43 本各自独立的书（书名就是 `第1话`），既看不出同属一本，
也读不成连续的话；`_iter_book_entries` 那句「只下探一层」还让更深的文件**根本扫不到**。
需求两条：① 书库层整棵树 = 一本书、书名为《转生魔女宣告毁灭》；② 阅读层逐话连续读。
顺带修掉同族缺陷：**嵌套有声书**（`《书名》/第1卷/第1话.mp3`）此前把 `第1卷` 当成一本书
（书名就是「第1卷」），更深的则完全扫不到。

### 一、判据本体：`core/units.py`（新增 495 行）+ 17 例契约

「一棵树 = 一本书」的**唯一真值源**：`is_unit_dir` = 递归枚举媒体文件后，**≥2 个能解析出
序号、且序号不全相同**。

- `parse_unit` 的窄判据（三种形态，标记必须在**开头**）：`第12话` / `第十二話` / `第03卷`
  （标记之后可带标题，`第1话 番外` 这种常见写法算）；`4 第4话`（前缀数字**等于**单元号 ——
  不等说明那个前缀是别的东西：页数 / 批次 / 另一个编号体系）；`01` / `007`（纯数字，
  `≤ _MAX_UNIT = 999`，否则 `2024.pdf` 会被当成第 2024 话）。
- **刻意不收**（这就是「看着不像连载的目录不合并」的全部实现）：`《甲》(第1卷).cbz`
  （标记不在开头 —— 一个文件夹里几本独立漫画正是这个形状）、`作品名 第1话.pdf`（标题在前）、
  `第1-43话.pdf`（那是**范围**不是某一话）、`4x 第4话.pdf`、`vol.1.cbz`（不是中文单位词）。
- 「≥2」与「序号不全相同」是两道互补的闸：前者排除「只有一话」（说明不了是连载）；
  后者排除**把容器当成书** —— `作者/《甲》/第1话.cbz` + `作者/《乙》/第1话.cbz` 两个文件都解析
  得出序号，但那是两本书各自的第一话，只看个数会把整个作者目录粘成一本。**宁可少合并**
  （退回的是今天的行为，看得见、懂），不可错合并（用户只能靠改名目录来救）。
- 排序键 `(序号, 自然序)`；**解析不出序号的排在最后**（`序章` / `番外` / `后记` 如实按自然序排，
  不猜位置）。`units()` 的 `name` 是**相对树根**的 posix 路径（`第1卷/第1话.pdf`），不含绝对路径
  —— 这个清单要直接下发给前端。
- 上限 `_MAX_DEPTH = 4` / `_MAX_FILES = 5000`，**超限一律不合并**（保守退回；符号链接环路也靠深度兜住）。
- 「两套 exts 口径」是**有意**的，理由写在注释里：枚举侧（知道库白名单）按**库生效白名单**判；
  探测侧 `_probe_entry` 只能依赖文件自身（增量刷新的立足点）⇒ 固定 `UNIT_EXTS`。**同一份实现、两个配置**。
- 库级排除图案（`exclude`）**刻意不在树内应用**：它管的是「这些条目不进书目」，而一棵通过判据的树
  **整棵就是一个条目**；更要紧的是增量闸门拿不到图案（`_cheap_facts` 只有路径）—— 应用了就会出现
  「卡片说 4 话、阅读器里 5 话」。

三处「同一判据不许有第二份拷贝」的收敛：`shape_of`（目录型条目的**形态**，顺序是**先平铺音频、
后序号单元** —— 编号轨有声书 `01.mp3…12.mp3` 同时满足两条判据，取音频形态才能让「N 轨 + 播放器」
这套**改造前就有**的行为逐字不变）；`collected_by`（这棵树算不算一个条目、什么形态，被
`_iter_book_entries` 与搬家闸门同读）；`merges_for`（哪些库类型做合并，`migrate.compat_reason` 读同一份）。

⚠️ 与 `komga.infer` 是**两套不同判据，刻意不合并**：那套解析的是「系列名 + 册号」（要 ≥2 字的系列名），
实测对 `第1话` / `4 第4话` / `01` 一律返回空。它服务「这本书属于哪个系列」，本模块服务
「哪些文件属于同一本书的连续话」—— 输入完全不同，硬凑成一处只会同时弄坏两边。

### 二、扫描层接入 + 口径自愈 + 搬家同源（`library.py` / `catalog.py` / `migrate.py`）

- **枚举**：`_iter_book_entries` 新增 `ltype` 形参（两个调用点都拿得到库实体），在「顶层文件 →
  隐藏目录 → 音频目录」之后、下探一层之前插一支：通过 `collected_by` ⇒ 整棵树算**一个**条目，并
  `continue`（书边界 = **最外层**；不 `continue` 的话子树里的文件会被当成兄弟条目重复登记）。
- **探测**：`_probe_entry` 目录分支先问 `shape_of`；命中 ⇒ `tracks = len(units())`（话数**复用既有的
  `tracks` 列** ⇒ 零新列、零迁移）、`format = "AUDIO"`（全是音频话时仍是 AUDIO）/ `"UNITS"`、
  `pages = 0`（话数进 `tracks`，不改估算语义）；未命中 ⇒ 走今天的音频目录分支。**签名不变**。
- **增量闸门**：`_cheap_facts` 目录分支改用 `units.dir_fingerprint`（**递归**总大小 / 最大 mtime /
  文件数）。**这是本期唯一一处性能代价**（目录型条目从一次 `scandir` 变成一次递归遍历，带
  `_MAX_FILES` 上限）。`_probe_entry` 必须用**同一个**函数算 `size`/`mtime`，否则闸门恒不命中（恒重探）。
  指纹看得见树里**每一个**文件（含封面 / 扫描图），只算媒体文件的话「加了一张封面」在增量闸门上
  完全看不见（卡片一直显示旧值，且不报错）。
- **`SCAN_RULE_VERSION = 1`**（定义在 `library.py`）：凡能改变「条目边界或卡片字段口径」的改动都要 +1。
  这是**存量索引唯一的自愈通道** —— 磁盘上一个字节都没变，增量闸门永远不会重探那些旧行，改完代码
  用户看到的还是 43 本，而且不报错、不重建（第 72 期在派生件那边踩过同一个坑）。
  `catalog` 把标记写进 `app_state` 的 `book_index_rule:{lid}`，**按库分键**：记成全局的话，第一个
  刷新完的库会把标记写成新版本，**后面的库再也不全量重探** ⇒ 只有一本书被修好，比不修更难查。
  不一致 ⇒ 该库下一轮刷新**当作 force**，全量重探完再写回标记（只发生一次，之后回落增量）。
- **排序同源**：索引落库顺序必须与全量扫描顺序一致（否则书架顺序抖动）⇒ `catalog` 里那份
  「精确复刻 `_iter_book_entries` 遍历顺序」的排序键同批改，对拍用例扩一个单元目录进去。
- **搬家同源**：`migrate` 里第三份「是不是音频目录」的字面量收敛到 `collected_by`，否则
  「漫画库 → 漫画库」搬家会把一本拆成 43 本（而预览还说能搬）。

### 三、书名剥掉「范围 / 话数备注」（`core/metadata.py`）

新增 `strip_count_note`：剥**尾部**括号里的范围 / 话数备注，判据窄到只有两种形状 ——
`第?全?\d*(?:[-–~]\d+)[话話卷回册集部篇幕章]?` 与 `全?\d+[话話卷回册集部篇幕章]`。
⇒ `（1-43话）` / `（全43话）` / `（第1-43话）` / `（1-43）` 剥掉；**反例不剥**：`（0079）`
（无范围、无单位词）、`（修订版）`、`（上册）`。`from_filename` 的**两个分支**（`《》` 命中 /
未命中）都过这道函数 ⇒ 对所有书生效（含存量，靠上面的口径版本自愈重探）。
用户手工改过的书名在**覆盖层**里、优先于解析值 ⇒ 剥名不会覆盖用户编辑。

### 四、服务端：四个 `/units` 端点（`server.py`）

| 端点 | 语义 |
|---|---|
| `GET /api/books/{bid}/units` | 话清单 + `{total}`（形状照 `/audio`） |
| `GET /api/books/{bid}/units/{index}` | 单话字节流（FileResponse，音频自动带 Range） |
| `GET /api/books/{bid}/units/{index}/pages` | CBZ / CBR 话的页清单 |
| `GET /api/books/{bid}/units/{index}/page/{n}` | CBZ / CBR 话的第 n 页 |

- **注册位置**照 AGENTS.md：字面量 `/units` 在 `/units/{index}` 之前、四条都排在
  `/api/books/{bid}` 之前。越界与错配的断言在 `tests/test_units_api.py`（`/units/4`、`/units/99` → 404；
  对 PDF 话请求 `/units/0/pages` → 400）。
- `?token=` 只给**浏览器原生请求**开两张口子（`<audio src>` / `<img src>`）：`_MEDIA_TOKEN_PATHS` 增
  `books/[^/]+/units/\d+$` 与 `books/[^/]+/units/\d+/page/\d+$`；PDF 话走 pdf.js 带 Authorization。
  **列表端点仍要鉴权**（实测无 token 401）。
- **音轨与封面改走同一份判据**：`api_audio_tracks` / `api_audio_track` 委派 `units.tracks_of` /
  `units.track_at`（音频轨与话是同一份清单的两个名字）—— 嵌套有声书由此一并修好，播放器协议不变；
  详情封面改走 `units.cover_in_tree`（**能在子树里找**封面；单文件音频与平铺目录行为不变）。

### 五、前端：合集阅读器 + 进度换算唯一真值源

- **新增 `lib/unitsProgress.ts`**：`toPercent(index, within, total)` / `fromPercent(percent, total)`
  —— 「话 / 轨 ↔ 百分比」的**唯一真值源**（口径与改造前的 `AudioPlayer` 逐字相同，只是搬到一处）。
  `AudioPlayer` 里那份 `Math.floor(percent / 100 * total)` 的**第二份反推公式**一并收敛掉。
- ⚠️ **单测当场抓到一个静默错话的真缺陷**：`toPercent(i, 0, total)` 写出去的是 `i / total × 100`，
  再乘回来在二进制浮点下**不严格互逆** —— 43 话的书里第 16 话的开头反解成 `15.999999999999998`，
  `floor` 之后落到**第 15 话的末尾**：界面显示「第 16 话」的位置，重新打开却回到第 15 话的最后一页，
  全程不报错。修法：`fromPercent` 加 `BOUNDARY_EPS = 1e-9`（远大于浮点噪声、远小于任何真实的话内
  位置差）把「差一点正好落在整数上」归位；往返用例因此改成「**话号必须精确** + 话内比例只要求浮点
  容差」（下游拿 `within` 做的是 `floor(w × 页数) + 1`，那点尾巴落在第 1 页上）。
- **新增 `components/reader/UnitsReader.vue`**：左侧话目录 + 上/下一话 + 「N / M」+ 形态徽章；
  主区按这一话的 `kind` 挂 `PdfReader` / `ComicReader` / `AudioPlayer`（`:key` = 话号 ⇒ 换话**重建**，
  三个子阅读器都持有「当前文件」的内部状态）；**末话不越界**（读完仍走 `seriesNext` 翻下一册）。
- **进度由上层独占**（本期最容易写错、又完全看不出来的地方）：整本书只有 `progress` 那一行 `percent`，
  `UnitsReader` 是**唯一**写它的地方；三个子阅读器进入**单话模式**（拿到 `unit` ⇒ 数据源换成
  `/units/{index}`、进度**不读不写**、只上报 `unitPos`；读完发 `unitEnd`）。
  ① 上报载荷带 `index`，上层**核对后丢弃过期上报** —— 换话时旧话那个组件会先卸载，卸载钩子里还有
  一次收尾上报，不核对就会把「第 3 话读到一半」写成「第 4 话读到一半」；
  ② 换话两笔写入**串行**（旧话收尾 → 新话开头），并发发出去的话服务端谁后落谁赢；
  ③ 卸载时**补写**当前位置（子阅读器最后一次上报可能已隔了几秒）；
  ④ 写库**不取整**（43 话里 1 话只占 2.3%，整成整数百分比会把话内位置抹掉）。
  `UnitsReader.spec.ts` 9 例钉住的就是这套协议（含「自动续话过来的音频 autoplay，用户自己点下一话不自动播」）。
- 分流与展示：`ReaderView` 加 `isUnits`；`bookInfo.formatLabel` UNITS → 「合集」、`pagesLabel` → 「N 话」；
  `bookOpen` 的 `READER_FORMATS` / `THUMBNAIL_READER_FORMATS` 纳入 UNITS；`BookDetailView.canRead` 纳入
  UNITS（判据是**有没有话**，与 EPUB 判「有没有章节」同构）；目录型条目**不可下载**（`canDownload = !isDirEntry`）。

### 契约与验证

- 后端新增 **44 例**：`tests/test_units.py` 17 / `test_units_scan.py` 10 / `test_units_api.py` 9 /
  `test_book_title.py` 7 / `test_catalog.py` 扩 1。逐条钉住计划里的 11 条：恰好一本 / 排序 /
  不过度合并（护栏）/ 电子书库不合并（与今天逐字相同）/ 嵌套有声书 / **递归指纹**（新增一话不 force
  也看得见）/ 索引顺序 == 全量扫描顺序 / 口径版本自愈（第一次全量、第二次回增量）/ 书名四正三反 /
  端点契约与越界 404 / 搬家同源。
- 后端全量 `pytest`（junit 解析）：**1263 例收集 / 1251 passed / 12 skipped / 0 failed / 0 error**
  （本期前基线 1219 收集）。
- 前端四连：`type-check` 通过 · `test:unit` **441 例 / 38 文件全绿**（新增 17 例）· `build` 通过 ·
  `deploy` 已同步。⚠️ 组件用例里踩到一个坑：**`await router.isReady()` 不能写在 `mount` 之前** ——
  首次导航由 `app.use(router)`（即 mount）发起，先 await 它就是死等，表现是**每个用例都 5s 超时**。
  另一个：`vue-tsc` 对三个桩的**联合类型**按名字取 prop 会收成 `never` ⇒ 用例改为整取再断言。

### 真机验收（本机容器 `novelforge-test`，端口 8993；后端改动必须重启进程）

- 造树（4 个小 PDF，非真书）：`<漫画库根>/《转生魔女宣告毁灭（1-43话）》/第1卷/第1话.pdf`、
  `第二话.pdf`、`第03话.pdf`、`4 第4话.pdf`。刷新后 `GET /api/books`：**恰好 1 本**、
  `title == "转生魔女宣告毁灭"`（范围备注已剥）、`format == "UNITS"`、`tracks == 4`；
  旧的 `第1话`…`第4话` 四行**已被清掉**。
- `/units` 4 条、序号 1..4；`/units/0` → 200（PDF 字节流）；`/units/4` 与 `/units/99` → 404；
  对 PDF 话的 `/units/0/pages` → 400；`?token=<有效>` → 200、无效 token → 401、
  **列表端点不带 token → 401**。详情带 `units`；进度写 `62.5` 原样存回（**不取整**）。
- **嵌套有声书回归**：`《声之形》/第1卷/第1..3话.mp3` ⇒ 1 本、`AUDIO`、`tracks = 3`。
- **反向**：同一棵树放进 `type=ebook` 的库 ⇒ **4 本不合并**（电子书库与今天逐字相同）。
- **增量**：往单元树里加一话后**不 force** 刷新 ⇒ `tracks` 4 → 5（递归指纹生效）。
- **发布回归**：对单元书走一次发布 ⇒ `is_dir_entry = True`、逐文件 **hardlink**、`tree_shared = True`、
  逐文件 `same_file = True`；源树指纹与逐文件 `size` / `mtime` **完全未变**（源不可变铁律）。
  ⚠️ 这次是**容器内直调 publish 原语**：API 侧 `publish_path` 有「成品目录不得与库根重叠」的守卫，
  而本容器唯一的来源根 `/app/libraries` 被测试库占满 —— **不是走 API 发布的**，如实记着。
- 活动日志无本期相关异常；验收造的库与树已清理，容器回到 2 库 / 2 书。
- ⚠️ **验收改了计划的一处预期**（计划写的是「反向：同一棵树放进 ebook 库 ⇒ 仍是 4 本」）：
  计划里那棵树有「若干级文件夹」，放进 ebook 库实际是 **0 本**（深一层 ⇒ 电子书库不合并、
  「只下探一层」也收不到）—— 那是**改造前就有的边界**，不是本期回归；把 4 个 PDF **浅一层**
  放进 ebook 库才是 4 本。两个方向都实测过。

### 未做 / 取舍（需用户知情）

- ⚠️ **`watcher` 入库路径不认序号单元树**：往 `INPUT_DIR` 丢一棵树仍会被拆成 N 本散书
  （`watcher` 的目录判据走的还是 `audio.is_audio_dir`）。这与改造前逐字相同，但现在是**不一致**了：
  同一个目录放进**书库根**是一本、走**收书目录**是 N 本。修它要动入库管线（复制策略、命名、
  活动日志主体），留作独立一期。
- ⚠️ **43 本旧书的进度 / 评分 / 收藏不会自动并到新书**：合并后是新条目，旧行**原样保留**
  （不删不搬 —— 将来想补一次映射还有数据可依）。**这是本期最需要用户知情的取舍**。
- **不做 PDF 首页当封面**（PDF 渲染要 pdf.js / 第三方 ⇒ 违反零依赖）⇒ 单元书用树内图片当封面，
  没有就用占位色。**不做扫描期统计 PDF 页数** ⇒ `pages` 保持估算语义，话数进 `tracks`。
- **不做跨类型自动续话**（PDF 话 → CBZ 话要换阅读器）；同 kind 内续话做，混类型仍可逐话点。
- **不做「合集切漫画视图」**：单话模式下 PDF 话固定走 `PdfReader`（漫画视图的接线留待有需求时做）。
- **不做散图目录合并**（没归档的整页 PNG 序列）：`UNIT_EXTS` 不含图片扩展名，那是另一套渲染形态。
- **不做电子书库 / 混合库的合并**（用户明确「一般只有漫画库和有声书库会出现」）⇒ `merges_for` 只认
  `comic` / `audiobook`。这也是本期最稳的安全边界：电子书库的条目与今天逐字相同。
- **不做 `序章` / `番外` 的智能排序**：解析不出序号的按自然序排在最后，不猜位置。
- **不做 N:1 的 remap**：零新表、零新列 ⇒ AGENTS.md 的 remap 四处与三处同步点**本期均不涉及**（已核对）。

---

## 第 75 期（2026-09-29）：开关圆点固定白色 + 删除语义重定义

### 需求（用户原话）

1. 「胶囊开关颜色修改的有问题，胶囊内一个圆点，颜色需要与主题色不一致，默认为白色。」
2. 「删除书库中的书时，固定为将本地和本项目的书都删除，但是移除书库时，仅将书从项目中删除，不动本地的书」

### 术语（用户逐问确认）

| 代号 | 是什么 | 由谁定位 |
| --- | --- | --- |
| ① 本地原件 | 用户放进**收书目录**的投递件 | `book_origins`（入库时登记；就地库没有独立的 ①） |
| ② 书库内文件 | 书库根里、书卡对应的那份 | `book["path"]` |
| ③ 出版副本 | 项目按命名规则产出的副本 | 台账 `link_rel`（没有台账时才按当前规则现算） |

### 一、开关圆点（`frontend/src/components/ui/Switch.vue`）

- 圆点由随主题的 `bg-card` 改为**固定白色** `bg-white` + **半透明黑细边** `border-black/15`
  （白色在浅色轨道上对比偏弱，靠细边勾轮廓）；**轨道**仍走主题变量（`bg-primary` / `bg-muted`）。
- 文件头注释与 `Switch.spec.ts` 的旧契约（「不许出现 `bg-white`」）一并改成新口径 ——
  这是**有意推翻**第 70 期的「滑块用 `bg-card`、别写死白色」。

### 二、删除语义

- **新增持久表 `book_origins`**（`book_id` → ① 的绝对路径）：书目是磁盘扫描的**派生索引**
  （`book_index` 重扫即重建、且属「衍生不搬」），**加列留不住** ⇒ 独立成表；并进 `REMAP_TABLES`
  （改名 / 换库跟着搬）与 `ORPHAN_TABLES`（含 `book_id` 的表都要可清理）。
- **登记点**：`library.remember_origin()`，由 `watcher.handle_file`（两个复制分支）与 `/convert`、
  `/convert-path` 在**真的复制了一份**之后调用；就地库（源即成品）与判不出库 id 时静默跳过 ——
  登记失败**绝不影响入库**。
- **删书**（`api_delete_book`）：台账要**先读**（下面会把它降级、且 ③ 的路径从它取）→ 用
  `_recycle_one` 逐份回收 ② / ① / ③（**永不外抛**：一份失败不带走另外两份）→ ① 的记录
  **回收成功后立即忘掉**（失败则留着下次重试）。返回新增 `targets`（`library`/`source`/`copy`，
  各 `recycled|missing|failed`）。③ 取台账 `link_rel` 而非现算 —— 命名规则改过之后现算会算到别处，
  于是「漏掉一个还躺在成品目录里的旧副本」。
- **移除书库**（`api_delete_library`）：非空库默认仍 400，`force=1` 放行（前端在确认后传它）；
  按索引列出该库书目，逐本回收 ②③，**① 一律不动**（`book_origins` 行也留着）；返回
  `books / recycled / failed / missing`（原 `books_left_on_disk` 下线 —— 它的名字在新语义下是错的）。
- **前端**：`api.ts` 两处返回值类型；`BookActionsMenu` 确认文案点明三份 + 新增 `deleteToast()`
  （**部分失败必须说出来**，不能报「已删除」）；`LibrariesView` 确认文案由「**不会删除任何文件**」
  改为破坏性提示，非空库时传 `force=true`（否则新行为在界面上根本走不到）。

### 验证

- 后端：新增 2 例（`test_book_delete.py`：三份都回收 + 缺份照旧成功）；同步改
  `test_api_smoke.py`（force 会回收书库内文件、① 保留）与 `test_library_count_contract.py`。
  全量 **1265 例 / 1253 passed / 12 skipped / 0 failed / 0 error**（junit）。
- 前端：`type-check` 0 错；`Switch.spec` 8 例、`BookActionsMenu.spec` 29 例全过（新增「部分失败」1 例）。

### 未做 / 取舍（需用户知情）

- ⚠️ **① 只覆盖「从收书目录入库」的书**：直接放进书库文件夹的书没有独立的 ①（源即成品），
  如实记 `missing`。**刻意不猜路径** —— 猜错等于误删用户文件，比漏删严重得多。
- **存量书没有 ① 记录**（第 75 期之前入库的）：删书时记 `missing`，不会去猜。
- 移除书库**保留 `book_origins` 行**：库若再建回来还认得出；这些行会变成「库不存在」的孤儿，
  而 `_orphan_refs` 的过滤（`lib_ids`）**刻意不报**它们 —— 与进度 / 批注同一口径。
- **不做**：真删（仍只进回收站，真删只有「清空回收站」一个出口）；不扫成品目录去找「孤儿副本」。

---

## 第 76 期（2026-09-29）：EPUB 插图不显示 + 还原书内排版

### 需求（用户原话 + 追问确认）

1. 「epub书中的插图不能正确显示」→ 追问确认：症状 = **完全不出现（空位 / 破图）**；范围 = **还要还原 EPUB 自带排版**（字体 / 缩进 / 图文混排，用户明确知道改动大得多）。

### 根因（三处硬缺陷）

1. **401（插图一个都不显示的直接原因）**：`_rewrite_assets` 把插图改写成 `/api/books/{bid}/asset?p=…` 但**从不带 `?token=`**；`/asset` 虽已在 `_MEDIA_TOKEN_PATHS` 里允许 query 传令牌，而浏览器 `<img>` 带不了 `Authorization` 头 ⇒ `_auth_middleware` 一律 401。
   对照：漫画 / 有声书 / 封面 / 头像的 URL 都由**前端 helper 显式拼 `?token=`**（`api.comicPageUrl` / `unitPageUrl` / `coverUrl` …）—— 唯独 EPUB 插图的 URL 是**后端**拼的，没人补令牌。
2. **404**：`PurePosixPath` 不折叠 `..`，产出 `OEBPS/Text/../Images/x.png`；而 `/asset` 用 `namelist()` **精确相等**匹配 ⇒ 命不中（真实 EPUB 里 `../Images/…` 极常见）。
3. **取错文件**：`/asset` 用 `library.root_of(b) / b["name"]` —— 多文件夹的库里会指到**另一个根**（`api_delete_book` 的 docstring 早点名批评过这种写法）。

附带缺口：单引号属性、`srcset`、`xlink:href`、`style="…"` 与 `<style>` 块里的 `url()` 都没被改写；`<head>` 被 `_body_of` **整段丢弃**（书内 `<style>` / `<link rel=stylesheet>` 全没了）；`/asset` 与 `_rewrite_assets` **零测试**。

### 做了什么

- **加载链路**：`_rewrite_assets` 重写 —— `..` 用 `posixpath.normpath` 折叠、逃出 zip 根的**不改写**（与其造一个必然 404 的 URL，不如留着原值）、一条带反向引用的正则吃下双/单引号与 `src` / `href` / `poster` / `srcset` / `style`、章节间的链接（`.xhtml` / `.html` / `.htm` 结尾）**刻意不动**（改了会让点开变成下载 XHTML）。
  令牌由 `server._with_asset_token` 在**读完缓存之后**注入（`_chapter_cached(..., token=…)` 返回新 dict，缓存那份始终无令牌）；`/asset` 改用书目 `b["path"]`，`p` 走 `_asset_entry`（原值 / 归一 / URL 解码三种等价写法各试一次，**仍必须精确等于真实条目名** —— 安全性不变）。
- **书内样式**：新增 `library.chapter_assets(path, bid)` —— OPF manifest 里 `text/css` 的条目（`<link>` 指向的表）+ 各 spine 文档 head 里前 64 KB 的内联 `<style>`；`@import` **递归内联**（用被导入文件自己的 base 解析其 `url()`，不内联就会被浏览器按 `/asset` 基准解析、全部指错）；`@font-face` 的字体与背景图走同一个 `/asset`。
  新端点 `GET /api/books/{bid}/epub-css`（**Bearer，刻意不进 `_MEDIA_TOKEN_PATHS`**，缓存键 `nf:css:{bid}:{指纹}`），返回 `{css, sheets, fixed_layout}`；取不到一律空串，**不是错误**。
- **前端注入**：书内 CSS 由 `ReaderView` 以 `@scope (.reader-content)` 注入 `document.head`（**绝不进正文容器**）+ 正文挂 `.nf-bookcss` 让应用那套段落 / 标题 / 引用规则让位（图片「不许溢出」的安全网保留）；`@scope` 能力用 `replaceSync` **懒探测 + 缓存**，不支持时既不注入也**不让位**（否则两头空、比不做更糟）；开关 `readerPrefs.useBookLayout`（默认开，固定版式**强制**开并在阅读器与设置页两处禁用说明）。

### 硬约束（本期最重要的一条）

⚠️ **书内样式必须落在被测量的正文容器之外**。`core/epub_cfi.py` 定义「字符偏移 = 渲染正文的 `textContent.length`」（前端量 `.reader-content`，后端读 zip 里**原始 XHTML**），而 CSS 文本本身就是文本节点 —— 注入进容器会把长度顶长，让**进度 / 批注 / 高亮的偏移全线错位**，而且不报错。
新增用例 `test_chapter_assets.py::test_改写不增删文本节点` 与 `ReaderView.spec.ts` 的「绝不进被测量的正文容器」两条把这个不变量钉住。

### 验证

- 后端全量 **1290 例 / 1278 passed / 12 skipped / 0 failed / 0 error**（基线 1253 + 新增 25）。
- 前端 `type-check` 0 错；**447 例**全过（新增 3 例）。
- 新增两个契约测试文件：`tests/test_chapter_assets.py`（改写口径）、`tests/test_epub_assets_api.py`（两端点：鉴权 / 路径归一 / 多文件夹库 / 令牌只在响应期注入）。
- ⚠️ 跑之前环境缺依赖（`.venv` 缺 `numpy`、`frontend/node_modules` 缺 `vitest` / `echarts` / `@vue/test-utils`，都与改动无关），已分别 `pip install -r requirements.txt` 与 `npm install` 补齐。

### 未做 / 取舍（需用户知情）

- **书内排版关不掉「颜色」**：书里写死的深色文字碰上阅读器深色主题仍会看不清 —— 退路是那个开关；刻意**不做**「剥掉书内 `color` 声明」（那要自己写 CSS 分词器，与零依赖冲突）。
- **`<style>` 只扫每个 spine 文档的前 64 KB**（head 在文件开头）：超出窗口的样式取不到；body 里的 `<style>` **不做抽取**（那些留在正文里由 `_rewrite_assets` 就地改写）。
- **不支持 `@scope` 的浏览器**（旧 Safari / Firefox）只丢书内排版，插图仍正常；刻意**不写**「不支持就退回全局注入」的分支（那正是会漏进外壳的写法）。
- 图片的 `max-width: 100%` 安全网**优先于书内样式**（书里若写 `max-width: 200px` 会被放宽）—— 溢出比「不够还原」严重。

---

## 第 77 期（2026-09-29）：移除「按格式归库」+ 讲清入库会不会多一份文件

### 需求（用户原话 + 追问确认）

1. 「移除书库时，不应该出现『按格式归库』、『有 8085 条被拦下（同名冲突 / 需指定目标库），它们不会被迁移 —— 处理后可再次点「执行迁移」』等内容，应该直接将书库信息从本项目中删除。」
   → 追问确认：那 8085 条是**移除某个书库之后才涨上来的**（移除库 ⇒ 那批书失去归属 ⇒ 待迁移预览暴涨），用户判定「移除与归库被错误地耦合了，要解耦」；处置力度选**彻底移除**（顶部卡片 + 启动阻塞框 + 迁移台账/回滚 + 相关端点与配置键），**仅保留书库的手动建/扫/移除**；移除书库的语义**保持第 75 期不变**。
2. 「现有的入库方式：从 nas 中获取书然后复制到根目录再导入本项目的流程，是否会增加不必要的文件？考虑直接将源文件的信息导入本项目，元数据等信息在本项目中保存……」→ 追问确认：**只要分析结论 + 改用法与文档**（零后端代码改动）。

### 需求 1：删了什么（一条路，绝不动另一条）

⚠️ 本期风险不在「删得对不对」，在**删多了**：`core/migrate.py` 里「自动归库」与「用户发起的跨库移动」**共用同一台执行机器**（`server.py` 原注释逐字承认过）。所以按**函数**逐个删，而不是按文件删。

**删除**（只服务自动归库）：
- 端点 `GET /api/library-migrations/preview`、`POST /plan`、`POST /apply`、`POST /rollback`、`GET /batches`、`POST /dismiss`、`POST /reset-gate`。
- `core/migrate.py`：`preview` / `plan` / `gate_state` / `dismiss` / `reset_gate` / `suggest_specs` / `libraries_of_type` / `_pick_from` / `_pick_dst`（后者本就是**无调用者的死代码**）/ `_suggest_name` / `GATE_KEY` / `SUGGEST` / `TARGET_TYPES`，以及随之一并失效的 `json` / `time` 导入。
- 配置键 `libraries.auto_migrate`（`config.py` 默认值、`server.py` 的 `EDITABLE` 白名单与 `GET /api/config` 回显、`api.ts` 类型）。
- 前端：`components/MigrationGateDialog.vue`（整文件）、`App.vue` 的挂载与 `authChecked` 标记、书库管理页顶部卡片 + 迁移台账 + 本次明细三块与六个函数、`api.ts` 的七个方法与八个类型。

**保留（一字未改）**：`execute` / `rollback` / `last_batch` / `compat_reason` / `copy_plan` / `_after_bookmove(_back)` / `move_preview` / `move_plan` / `move_targets` / `move_batches` / `move_summary` / `TYPE_LABELS` / `target_type_of`、`library_migrations` 表与 `db.migration_*`、`/api/book-move/*`，以及**投递目录的入库路由**（`core/library_rules.py` + `watcher._target`）。

> **术语坑（后人别再删错）**：`core/migrate.py` 里被删的那条叫「**自动归库**」（把已有书按格式搬进各类型库）；`core/library_rules.py` 的「**入库归库**（来源子目录名 > 格式 > 关键词）」是**投递时选目标库**，两者毫无关系 —— 后者删了投递就无处落库。本期只动前者。

`DIR_AUTO = "move"` 作为**历史遗留常量**保留：存量台账行里还写着那个字面量，`test_book_move.py` 靠它断言「跨库移动不占用历史槽位」。

### 需求 2：分析结论（「会多一份」，且那份复制不是白占）

入库有**两条路**（都在 `watcher.py`）：

| 给法 | 磁盘 | 代价 |
|---|---|---|
| 丢进**投递目录**（`INPUT_DIR`） | `shutil.copy2` **复制**一份进书库根（`:505`；目录型有声书走 `_copy_tree`），并记 ①（`remember_origin`） | 这份复制是**命名规则 + Komga 布局**的唯一着手处（源文件绝对只读，`:491-495`），还承担**跨库同名闸门**与「源与库物理分离」这条部署取向 |
| 直接放进**库的内容来源文件夹** | `if dst.resolve() == p.resolve()` ⇒ **零复制**（`:458` / `:499`） | 文件名保持原样（应用不改源文件） |

所以用户观察到的「多一份」来自**投递那一步**，而且是**设计使然**：不复制就没地方施加命名规则。用户选了「只要结论 + 改用法与文档」，故本期**不动入库代码**，只把口径写明白：

- `docs/user-guide.md` §2 新增 **2.1「会不会在磁盘上多出一份文件？」** —— 含「从 NAS 拷进 `./input` 再导入**确实会**多一份」的直接回答、两种给法的代价对照，以及「元数据与阅读数据都在项目里、与源文件放哪无关」；
- **新建书库向导**的「内容来源」步骤加一句对照（选这里 ⇒ 原地引用、不多副本；投递 ⇒ 会复制一份）；
- **收书目录页**投递目录卡片加一句「投递会复制一份；不想多占就把该目录配成来源根、建库时选它」；
- 顺手订正该卡片里「`.txt` 会自动转成 EPUB」这句**过期文案**（第 62 期起 `.txt` 已是原样复制入库）。

### 验证

- 后端全量 **1257 passed / 12 skipped / 0 failed**（基线 1290 = 1278 passed；减少的 21 例正是本期有意删除的归库用例）。
- 前端 `type-check` 0 错 + **447 例**全过。
- **测试是改写而不是只删**：`tests/test_migrate.py` 从「按格式归库」整篇改写为「**跨库移动执行层**」5 例（逐条独立 / 重复执行不重复搬 / 台账计数 / 回滚标记 / 错误口径）；`tests/test_migrate_unify_contract.py` 从「两条路对比」收窄为「移动的账目完整度 + **存量 move 批次**回滚」（保住那两条别处没覆盖的断言）；`tests/test_api_smoke.py` 删掉三个端点用例及其夹具。⚠️ 刻意**不整文件删除** —— `execute` / `rollback` 的那几项保障（幂等、逐条独立、副本随迁、remap、回滚复原）必须继续有用例。
- 顺手给跨库移动补了它自己的返回类型 `BookMoveRollbackResult`：原先它**借用**了被删的 `MigrationRunResult` —— `type-check` 当场抓到，说明前端类型面确实收敛干净了。

### 未做 / 取舍

- **不清理存量数据**：真库 `library_migrations` 里第 77 期之前的 `direction="move"` 行、以及 `config.yaml` 里可能还写着的 `libraries.auto_migrate`，都**留着不动**。后者已无人读（`config.load_config` 是浅合并、不校验白名单，不会报错）；前者被 `move_batches` 按 direction 过滤掉，不会出现在界面上。
- **`authChecked` 一并删了**（全仓只服务那个弹窗）。连带丢掉的第 68 期教训已转录进 `.codebuddy/memory/MEMORY.md`：`showLogin` 初值是 `false`，任何挂在 `App.vue` 里、要等鉴权裁决才有意义的东西，直接用 `!showLogin` 当门都会**先挂载一次**（发出一个注定 401 的请求）。
- **投递时「按格式 / 关键词选库」的能力保留**（见上面的术语坑）—— 用户那句「项目不再做自动归库」指的是**把已有书按格式搬到对应类型库**这条搬运链。

---

## 结构精简（非功能期）· 删死代码 / 清理截图 / 归拢文档目录

**来源**：用户指令「精简一下项目结构」；澄清确认四项目标全选、删除方式为直接 `git rm`、`docs/review/` 仅删 59 张 jpg（保留评审报告与取证文本）。

**做了什么**：
- 删除无引用的 `beautifier/`（8 文件，独立「前端美化 Agent」小工具）；`git rm` `docs/review/` 下 59 张上游截图（约 7MB，保留 2 份评审报告与两份 capture 取证文本）。
- 目录归拢（`git mv` 保历史）：`DESIGN.md`→`docs/DESIGN.md`、`TODO.md`→`docs/TODO.md`、`docs/bookorbit-*.md`→`docs/bookorbit/bookorbit-*.md`；`CHANGELOG.md`/`VERSION`（运行时与 Dockerfile 读取）、`AGENTS.md`/`README.md`（入口）依约束**留根**。
- 全仓 27 个文件同步改写引用（AGENTS 文档地图、docs 交叉引用、`novelforge/*` 注释、前端注释与 AboutPage 文案、`tests/*`）；`tests/check_doc_anchors.py` 的 `ROOTS` 补 `docs/bookorbit`。
- 收敛 `docs/project-overview.md` / `docs/development.md` 与 `README.md` 的重复表述（部署 / 环境变量 / CLI 指向 README）。

**验证**：后端 **1257 passed / 12 skipped / 0 failed**；前端四连绿（447 例）；`git grep` 旧路径残留 0。⚠️ 锚点脚本既有 **4 条硬错**（`BookDetailView.vue` 经第 73 期重写后行数缩小，`bookorbit-capability-gap.md` 的历史锚点越界）—— 非本次引入，按「历史行号不改写」纪律不动。

---

## 第 79 期 · 漫画 / 有声书：一级子文件夹内「同前缀 + 尾部编号」合并为合集（V0.79.0，2026-09-29）

**来源**：用户 2026-09-29 报「漫画库里 `超人前传0904` / `1408` 这类应纳入一个合集」（漫画库与有声书库都要）；
方案先落入 `docs/TODO.md` 的 P1（标注「已定方案，待实施」），本期按该方案实施。
**不变项复述**：zlibrary 等盗版分发平台的**专用下载不做**（第 57 期决定、第 71 期复核），本期无需重提。

**需求与口径（用户已确认）**：合成一本「合集」（N 话连续读、书架占 1 条，与第 73 期序号单元同一形态）；
**只在一级子文件夹内合并**；**平铺在库根目录的散文件不合并**（用法：把同类文件放进一个子文件夹）。

### 一、判据本体（唯一真值源 `novelforge/core/units.py`）

- 新增**第四种**解析形态「前缀 + 尾部编号」（`超人前传0904` → 904、`超人前传1408` → 1408，去前导零），
  独立上界 `_MAX_TAIL_UNIT = 9999`。⚠️ **`_MAX_UNIT = 999` 一个字未动** —— 抬高它会让 `2024.pdf`（年份）
  被认成「第 2024 话」，那是明确的回归。
- 解析点收敛：新增内部 `_split_unit(stem) -> (前缀, 序号) | None` 作为**唯一实现**，`parse_unit` 委托取序号
  （公开契约不变），`is_unit_dir` 的「同前缀」闸取前缀。既有三形态（`第12话` / `4 第4话` / 纯数字）
  一律回**空串**前缀 —— 若给它们硬编一个前缀（比如把 `4 第4话` 的 `4` 当作品名），同一棵树里的
  `4 第4话` 与 `第4话` 就会被判成两种前缀、反而**不再合并**（把「支持新写法」做成回归）。
- **「同前缀」闸**（防过度合并）：判据由「≥2 个不同序号」收紧为「**前缀集合恰 1 种** **且** ≥2 个不同序号」。
  尾部编号形态只看名字分不出「同一部作品的第 904 话」与「另一部作品的第 904 话」⇒ 不合并，
  退回「一个文件一本书」。

#### ⚠️ 计划与实现的偏差（一处，写明理由）

TODO 给的形态是 `^<非空前缀>(?P<num>\d{1,4})$`，字面上**任何**前缀都收。实测它会把
**`vol.1` 解析成「第 1 话」**（`pre="vol."` + `num="1"`）—— 而 `vol.1` 是现有契约表里**明确写着 `None`**
的一条（一本漫画的第 1 卷 ≠ 一部连载的第 1 话）。故实现把前缀收紧为**末尾必须是文字字符**
（`[^\W\d_]`：字母 / 汉字，不含数字与下划线），即「编号必须**紧贴**标题文字」；形态因此也拒收
`作品名-1408` / `作品名_1408` / `作品名 1408`。取向与 TODO 完全一致（宁可少合并），差异只在**这条更严的边界**上。

另一处必须照做的写法：`_BARE_NUM_RE` 那一支在超界时**不 return**、会继续往下走，所以新正则自带
「前缀须含非数字字符」的约束 —— 否则 `1408` 会被拆成 `pre="1" + num="408"`。

### 二、存量索引自愈（`library.py` / `catalog.py`）

`library.SCAN_RULE_VERSION` **1 → 2**：条目边界口径变了（一个文件夹由 N 本变成 1 本），而 `(size, mtime)`
一个字节都没变 ⇒ 不重探就永远显示旧结果、且不报错。`catalog._rule_stale` 按**库**比对，不一致即把该库
下一轮刷新当作 `force`，跑完写回标记（**自愈只发生一次**，之后回落增量）。`catalog.py` 本身**零改动**
（它读的一直是常量）。

`units._entries()` 由三元组 `(Path, rel, 序号)` 扩为四元组 `(Path, rel, 前缀, 序号)`，同批改掉**全部**解包点
（`units` / `unit_path` / `_sorted_entries` / `first_audio` / `_numbers`，另加 `_prefixes`）。
⚠️ 最易漏的是 `_sorted_entries` 的排序键**按位置索引**（`t[2]` → `t[3]`）：错位成前缀时会拿字符串与
`_INF`（float）比元组，直接 TypeError —— 好在那是**响亮失败**，不是静默错序。

### 三、「只在一级子文件夹内合并」没有新增任何代码

`is_unit_dir` 只对**目录**调用，而 `library._iter_book_entries` 的目录分支只扫库根这一层；
库根的文件是「文件条目」、永远不走该判据 ⇒ 「平铺库根不合并」**天然成立**，没有也不该有「库根例外」分支。

### 四、验证

- 后端离线全量 **1279 例收集 / 1267 passed / 12 skipped / 0 failed / 0 error**（基线 1257 passed，**只增不减**；
  新增 10 例：`tests/test_units.py` +6 函数 / 解析表 +13 条，`tests/test_units_scan.py` +4 函数）。
  自检脚本先抓到 `vol.1` 那条回归（见上面的偏差说明），是本期最值钱的一步。
- **真机验收**（隔离实例 8419 + Edge，改动后重启过进程）：库根放一棵「同前缀」文件夹、一棵「混前缀」文件夹、
  两个平铺 `2024.pdf` / `2025.pdf` ⇒ 扫描 **5 条**：
  - `超人前传/超人前传0904.pdf` + `超人前传1408.pdf` ⇒ **`UNITS` / 2 话**，详情话清单
    `[超人前传0904.pdf, 超人前传1408.pdf]`（按**序号** 904 < 1408，不是按文件名）；
  - `两部作品/超人前传0904.pdf` + `另一部作品0905.pdf` ⇒ **各 1 本**；
  - 库根平铺的 `2024.pdf` / `2025.pdf` ⇒ **各 1 本**（`format=PDF`）；
  - 点「开始阅读」进合集阅读器：头部 **「1 / 2」**、目录两话可切；`/health` 返回 `version: 0.79.0`。
    （⚠️ 假 PDF 内容报 `Invalid PDF structure.` —— 是冒烟夹具的假文件所致，不是产品问题。）
- **存量自愈实测**：把该库的口径标记改成 `1`，再**重启进程**（= 真实升级路径：首个读触发
  `refresh_library(force=False)` → `_rule_stale` → force）⇒ 标记写回 `2`、书目仍是那 5 条（幂等）。
  ⚠️ 附带一条实测结论：**单纯 `GET /api/books` 不会自愈** —— 该路径只在库「未就绪 / 脏」时刷新，
  而「口径过期」两者都不是；生产上的触发点是监听线程的定时全量兜底（`catalog.refresh_all`，默认 60s）
  与重启预热。
- 前端**零改动**（第 73 期已支持 `format === 'UNITS'` 的徽标 / `UnitsReader` / 进度换算）⇒ 未跑前端四连、未 `deploy`。
- 版本：`VERSION` 0.78.0 → **0.79.0**；`CHANGELOG.md` 追加 `## V0.79.0 — 2026-09-29` 段（四组共 5 条），
  实测 `core/changelog.py` 解析正常；`server._read_version()` 的内置回落值与日志文案同步到 0.79.0。

### 五、已知取舍 / 未做

- ⚠️ 新形态会接受 `三体1.pdf` / `三体2.pdf`（同前缀 + 不同序号 ⇒ 合并成一本）与 `IMG_2024.pdf` /
  `IMG_2025.pdf` 这类。四道闸（**同前缀 + ≥2 个不同序号 + 前缀 ≥2 字 + 只对 comic / audiobook 库生效**）
  已把风险压到最低，取向仍是「宁可少合并」。
- 分隔符写法（`作品名-1408` / `作品名_1408` / `作品名 1408`）**刻意不收**（理由见上面的偏差说明）；
  真出现这种命名请把分隔符去掉。
- 有声书库的**平铺音频目录本来就已经是一本多轨的书**（`shape_of` 先判 `audio`）⇒ 本期对它逐字不变
  （卡片仍是「N 轨」而不是「N 话」），已用用例钉住。
- 不做：**库根平铺合并**（要改书边界 / `book_id` / 出版副本 / 跨库搬家 / remap 全链路，属独立一期）；
  `watcher` 入库路径认序号单元树（第 73 期既有的已知缺口，仍未做）。

---

## 第 80 期 · `update` 段配置从「看着有」变成「每个键都真有读点」+ 解除「零外部请求 / 零依赖」硬约束（V0.80.0，2026-09-29）

**来源**：用户指令「继续 A+B」并在问答中确认 ——
**A**：让 `update.auto_apply` / `update.image` **真正生效**（不生效就从 UI / 白名单移除，**绝不留假开关**）；
**B**：给 `core/updater.py` 补一套**完全离线**的契约测试；收尾按惯例（VERSION + CHANGELOG + 文档 + 记忆 + 前后端测试 + 按能力拆笔提交并推送）。
**补充输入（用户原话）**：「取消零外部请求和零依赖的要求」。

### 一、缺陷形态：四个键里有三个是「假配置」

`update` 段（第 78 期引入）在 `server.EDITABLE["update"]` 白名单里、`GET /api/config` 整段回显、设置页也报「已保存」，
但**后端读点残缺**：

| 键 | 第 80 期前的真实状态 |
|---|---|
| `check_enabled` | **只在 lifespan 读一次** ⇒ 改完必须重启进程；关掉后侧栏 `new` 徽标仍会重新冒出来（`_state["has_update"]` 没清） |
| `interval_hours` | 同上，只在 lifespan 读一次 |
| `image` | **只在白名单与回显里**，`apply_update()` 直读环境变量 `NOVELFORGE_UPDATE_IMAGE` ⇒ 界面上改了没用；且设置页**没有这个控件** |
| `auto_apply` | **连读点都没有** ⇒ 打开它什么都不会发生 |

这条链路的危害是**静默**的：用户改完看到「已保存」，只会在下一个版本发布时觉得「这个开关时灵时不灵」。

### 二、后端接线（`core/updater.py` + `server.py`）

- **镜像来源收敛为唯一读法** `updater.configured_image(explicit="")`：**显式入参 > 配置 `update.image` > 环境变量 `NOVELFORGE_UPDATE_IMAGE` > `_DEFAULT_IMAGE`**。
  `apply_update()` 不再直读环境变量。新 `_split_image()` 只把**最后一个** `/` 之后的冒号当 tag ⇒ `localhost:5000/ns/img` 不会被误拆。
- **自动更新** `updater.maybe_auto_apply()`：条件为 `auto_apply ∧ has_update ∧ updater_available() ∧ latest 未尝试过`；
  ⚠️ **先记后做** —— 先把 `latest` 写进新增持久化键 `auto_applied` 并落盘，再去 `apply_update()`，
  于是「pull 失败」也不会在下一轮无限重试。「未挂载 `docker.sock`」**不记**尝试（否则之后挂上也不可能自动更新了）。
  失败静默（只记日志不冒泡），挂在 `_loop` 每轮 `check(force=True)` 之后。
- **持久化键元组扩容**：`_persist()` / `_load_persisted()` 的写死键元组同批加 `auto_applied` ——
  漏改一处会让新键静默丢失，表现是「每次重启后对同一版本重新自动拉一遍」。
- **保存即生效** `server._apply_update_config()`（与既有 `_apply_watcher_config()` 并排）：`check_enabled` 关 ⇒
  `stop_background()` + `clear_has_update()`；开 / 改间隔 ⇒ 先 `stop_background()` 再 `start_background(interval_hours)`。
  在 **5 处**配置写接口（`PUT /api/config`、原始 YAML、还原备份、重置、清覆盖层）与 lifespan 处复用同一函数 ⇒ 判据只有一份。
- **`start_background` 的竞态修正**：改为**每次新建** `threading.Event` 并把 stop 作为参数传给 `_loop`
  （原实现共享同一个模块级 Event ⇒「先 stop 再 start」会让旧线程把新 Event 也置位，出现双线程 / 立即退出）。幂等保护改为
  `_thread is not None and is_alive() and not _stop.is_set()`。
- **不改既有语义**：`apply_update` 未挂载时的返回结构与 `stage` 枚举（`unavailable` / `pull_failed` / `restarting`）**逐字不变**，前端 `UpdateApplyResult` 不受影响。
- `updater.status()` 新增 `check_enabled` / `auto_apply` 两个**只读回显**键（真值源是配置，`_state` 里不另存一份，免得两处说法不一致）。

### 三、前端（4 个字段、保存即生效）

- `settingsFields.ts` 的 `UPDATE_FIELDS` 由 3 项扩为 **4 项**：新增 `update.image`（`type: 'text'`，placeholder 给默认镜像）；
  三条既有 hint 从「重启后生效」改成「保存即生效」口径，并补上「关掉即收起提示 / 自动更新只在挂了 socket 时生效」。
- `lib/api.ts` 的 `UpdateStatus` 增可选 `check_enabled` / `auto_apply`；`WhatsNewView.vue` 在「有新版本」横幅里按
  `auto_apply && updater_available` 如实加一句「已开启自动更新：下次检查会自动拉取并重建」。
- `UpdatePage.vue` / `settingsNav.ts` 文案同步（note 是**纯文本插值**，未用任何 markdown 记号）。

### 四、镜像名形状校验（写入口）

`update.image` 现在真的会进 `docker pull` 的 query，故 `PUT /api/config` 里做校验：空串合法（回落下一级）、
拒 `@`（digest）、`..`、`> 200` 字符、不匹配字符集。
⚠️ **实现比计划严了一处也松了一处**（计划只写「拒绝空白 / `..` / 非法字符」）：第一版正则
`^[A-Za-z0-9][A-Za-z0-9._/-]*(?::[A-Za-z0-9._-]+)?$` 会把 **`localhost:5000/ns/app` 这种私有仓库拒掉**
（主机后的 `:端口` 过不了字符集），而 `_split_image` 明明已按「最后一个冒号才是 tag」正确处理了它 ——
故改为 `^[A-Za-z0-9][A-Za-z0-9._-]*(?::[0-9]{1,5})?(?:/[A-Za-z0-9._-]+)*(?::[A-Za-z0-9._-]+)?$`，
即**第一段单独放行 `:端口`**。

### 五、契约测试（两新增，全部离线）

- `tests/test_updater.py`（**26 例**）：`parse_version` / `is_newer` 的数值段边界（`0.9.0` 不比 `0.80.0` 新）；
  `status` 形状与开关回显；`updater_available` 判 socket（并断言**判定本身不碰 docker**）；
  `check(force)` 三条出网路径（releases/latest 成功 / 失败回落 tags / 全失败 `error=check_failed`）；
  1 小时新鲜度缓存（非 force **不重复出网**、force 绕过缓存）；`clear_has_update` 落盘；
  `_split_image` 的端口边界；`configured_image` **四级优先级**；持久化往返（**含 `auto_applied`**）；
  `start_background` 幂等 + 换间隔得到新线程 / 新 Event；`apply_update` 未挂载 ⇒ `stage=unavailable` **且 `_docker` 从未被调用**、
  已挂载 ⇒ `fromImage`/`tag` 取自 `configured_image` 且 `_recreate` 被调用（`threading.Event` 同步，**不 monkeypatch `Thread`**）、
  pull 失败不重建；`maybe_auto_apply` 四象限 + 「先记后做」+ 「重启后不重试」。
- `tests/test_update_config_contract.py`（**9 例**）：`EDITABLE["update"]` 与前端 `UPDATE_FIELDS` 剥前缀后**集合相等**（正则解析 TS 源码）；
  `SECTION_KEYS.update` 指向 `update`；`config.DEFAULTS["update"]` 覆盖白名单（否则「恢复默认」会让控件凭空消失）；
  **每个键都有真实读点**（`READ_POINTS` 表 + `.get("<键>"` 源码片段），且**读点表必须覆盖白名单每个键**（反向闸）；
  `GET /api/config` 回显整段；保存后 `/api/update/status` 如实回显；镜像名写入口的 4 拒 4 收。

### 六、口径修订：「零外部请求 / 零依赖」降为默认取向（**本期不新增任何依赖**）

**范围**：`AGENTS.md`（硬约束那条重写为「默认自托管、默认不引；允许显式、可关、失败降级地引入；新增依赖须在
`requirements*.txt` / `frontend/package.json` 显式声明并说明理由」）、`.codebuddy/memory/MEMORY.md` 硬约定 #5、
`MEMORY-REF.md`（逐期铁律原文上方加「口径修订」总注：下文那些「零依赖」表述仍是**理由**但**不再是硬约束**）、
`docs/project-overview.md` 取向句、`docs/DESIGN.md` 字体自托管段（注明现状选择）、`docs/architecture.md` 第 6 条、
`docs/bookorbit/bookorbit-capability-gap.md` 图表条、`bookorbit-module-inventory.md` 第 57 期段（加注）、
`bookorbit-settings-inventory.md` 图标条（加注）；代码注释：`config.py` 的 update 段、`core/fonts.py`、`core/audio_meta.py`、
`core/metasources.py`、`frontend/src/lib/icons.ts`、`assets/main.css`、`assets/fonts.css`。
`tests/test_audio_narrators.py` 的 docstring「零依赖解析器」→「纯标准库解析器」。
**刻意不改写**：`docs/roadmap-gaps-remaining.md` 里各期历史记录中的同类措辞（历史留痕），以及
`frontend/src/lib/prefsBridge.ts` 的「零依赖」（那是「无 import 依赖」的**技术事实**，不是口径）。
**刻意不做**：不为「解除零依赖」顺手换掉手写实现（如 `_UnixSocketConnection`、字体 name 表解析）—— 改口径不等于必须引依赖。

### 七、验证

- 后端离线全量 `pytest`：见下方「收尾复核」。
- 前端四连：`type-check` / `test:unit` / `build` / `deploy` 全绿（本期**有前端改动**，必须跑）。

### 八、已知取舍 / 未做

- 自动更新**只对「检查发现的新版本」尝试一次**：若用户手动 `docker compose pull` 到别的版本，`auto_applied` 不认识它，
  但只要 GitHub 上的 latest 没变就不会再触发（符合预期）。
- 未做「自动更新前的二次确认 / 通知」：单用户自托管场景下 `auto_apply` 本身就是用户显式打开的动作，故不加。
- 不改 `docker-compose.yml`（用户此前已决定 compose 文件只保留两份，更新说明内联进注释与本文档）。

---

## 第 81 期 · 「移除书库」改为「只删登记」+ 长文件操作后台化 + 回收站还原（V0.81.0，2026-09-30）

**来源**：用户报告（原文一句）`http://192.168.0.95:8992   移除漫画书库失败`。只读探测线上实例得出的现场证据：

1. 移除请求**长时间不返回**（实测数百秒仍无响应）⇒ 前端只能显示「失败」；
2. 漫画库 `lib-6a0b30d3` **仍在册**，但 `book_count` 持续下降：2206 → 1947 → 1834 → 1647 → 1531；
3. 活动日志 165 条**全 success，没有一条「移除书库登记」** ⇒ `api_delete_library` 末尾那行日志从未执行到；
4. 回收目录 61 秒内 **+240 份 / +4.8 GB（≈79 MB/s）** —— 该速率是**跨卷速率**，
   证明 `shutil.move` 走了 **EXDEV 复制回退**（同盘 rename 是 O(1)、无字节吞吐）。

用户按建议 `docker compose stop` 停服止血，保留现场（库登记与已搬文件都在）。

### 一、三个根因

- **主因（请求挂死）**：`api_delete_library` 把**跨文件系统的大搬迁**放在 HTTP 请求内同步执行
  （逐本 `_recycle_one(② 书库内成品 + ③ 出版副本)`）⇒ 请求数小时不返回、无进度回调、不可取消。
- **名实不符（误搬本地原件）**：该库 `source_dirs=["/app/libraries/漫画"]`、`publish_path=""`、无 ① 记录
  ⇒ 被回收的「②」**就是用户的本地原件**，与第 75 期「移除书库保留本地的书」的字面口径矛盾。
- **次因（超长名）**：`publish.recycle` 落点名 `f"{stamp}_{p.name}"`，`stamp` 是 16 字节，
  而 Linux 单文件名上限 **255 字节（UTF-8）**；该库 ≥240 字节的名字有 **7 个**（最长 277 字节）
  ⇒ `ENAMETOOLONG` 被记成 failed；重名退让分支 `f"{stamp}_{n}_{p.name}"` 同样会溢出。

### 二、语义变更：「移除书库」默认零文件触碰

`DELETE /api/libraries/{lid}` 现在只有一个开关 `purge_files`：

- **默认（不带参）**：同步、立即返回，**只删登记**（`db.delete_library` + `db.scrape_delete_by_library`
  + `catalog.forget` + `_libraries_changed` + `activity_log`），返回 `{purge_files:false, targets:0, task_id:null}`；
- **`purge_files=1`**：连文件一起清，且**在后台任务里跑**（见第五节）。

⚠️ 第 75 期「非空库需 `force`、`force` 回收 ②③」的默认行为**作废**，`force` 参数**整个去掉**；
「删书」的第 75 期口径**一字未动**（仍是三份一起回收）。两条路径口径不一致是**刻意的**：
「删书」是用户指着某一本说「连文件一起删」，语义明确；「移除书库」只该表达「别再管这个库」。

⚠️ 待回收清单必须**在删登记之前**物化（`server._purge_paths`）：③ 的路径取自刮削台账 `link_rel`，
而台账行会随 `db.scrape_delete_by_library` 一起消失。

### 三、长文件名加固（唯一实现 `fileops.recycled_name`）

`fileops.RECYCLE_NAME_MAX = 255`；`recycled_name(name, stamp, n=0)` = `{stamp}_{n_}{name}`，
超长时按 **UTF-8 字节边界**截断（`trunc_bytes`，不切坏多字节字符）+ 追加 `~<8 位短哈希>`，
并尽量保住扩展名。**这是回收落点名的唯一实现** —— 三个调用方同批收敛：
`publish.recycle`、`fileops.recycle_items`、`bookdock.remove`（原先各写了一份 `f"{stamp}_{name}"`）。

### 四、回收台账 + 还原（新模块 `core/recycle.py`）

- 新表 `recycle_items`：`id / orig_path / recycled_name / why / size / created_at`。
  ⚠️ **刻意不含 `book_id`** —— 它记的是「磁盘上某个被移走的路径」而非「某本书的数据」，
  改名 / 换库都不会让它失效，因此**不进 remap 四处清单**（契约测试钉住）。
- 写入走 `db.recycle_note`（**永不外抛**：文件已经移走了，不能因为记不上账就把回收算失败）；
  三个移入点（`publish.recycle` / `fileops.recycle_items` / `bookdock.remove`）同批接线。
- `GET /api/recycle`：台账条目（带磁盘实况）+ 无台账孤儿（`limit` 只截条数，计数始终全量）。
- `POST /api/recycle/restore`：三种入参可组合 —— `ids`（台账行，按各自 `orig_path`）、
  `names` + `target_dir`（无台账孤儿，剥 `YYYYMMDD-HHMMSS_[n_]` 前缀落到指定目录）、`all`（全部台账条目）。
  **幂等可续跑**：成功后删台账行；目标已存在则退让改名（`名字 (2).ext`，`recycle.free_path`）**绝不覆盖**，
  回执里如实标 `renamed`。解析不出的条目进 `errors`，不静默丢。
- `POST /api/maintenance/recycle/clear` 同批清台账（`db.recycle_clear`）—— 文件都真删了，
  台账再宣称「可以还原」就是骗人。

### 五、长文件操作后台化（`server._ops_*` + 任务行）

「移除书库清理」与「回收站还原」共用一个设施：

- 两个任务类型 `librarypurge` / `recycle`（`db.task_create`），接口立即返回 `task_id`；
- 逐项回调 `db.task_update(progress=..., detail="正在清理/还原：<名>")` —— 是真进度，不是假推进；
- **刻意不写 `result`**（有它前端会渲染成「下载」按钮，而这两件事没有产物可下）；
- 全局在跑标记 `_ops_pending` / `_ops_idle` + `server.wait_background_ops(timeout)`，
  由 `tests/conftest.py::_quiesce_background` 在**夹具 `db.close()` 之前**调用
  （与 scrape / watcher / embed-refresh 同一条纪律）。

### 六、前端

- `LibrariesView.vue::remove()` 重写：改为**页内确认浮层**（不是 `window.confirm`）——
  默认文案「只移除登记、不动任何磁盘文件」+ `Switch` 勾选「连文件一起清理」（勾选后才显示该库还有多少本、
  会移入回收站、可在维护页还原）+ 受理后 toast 说明「N 份正在后台移入回收站」。
- `lib/api.ts`：`deleteLibrary(id, purgeFiles)` 语义与返回类型改；新增 `recycleList(limit)` /
  `recycleRestore(payload)`；`clearRecycle` 返回加 `ledger_cleared`；新增
  `RecycledItem` / `RecycleOrphan` / `RecycleListPayload` 类型。
- `MaintenancePage.vue`：「维护动作」之前新增「回收站还原」区块（计数 + 最近 12 条 + 逐条还原 +
  「全部按原路径还原」+ 无台账孤儿的「指定目录还原」）；「清空回收站」文案补上「连同还原台账一起清掉」。
- `data/tasks.ts`：`TaskType` 加 `librarypurge` / `recycle`；`TaskCenterView.vue`：
  `PCT_TYPES` 让这两个类型**运行中**显示真百分比 + 补图标与说明文案。

### 七、测试（后端全量 **1335 例 / 1323 passed / 12 skipped / 0 failed**）

新增：

- `tests/test_library_purge.py`（7 例）：默认路径**字节 + `mtime_ns` 逐项不变**且无新增回收件、无任务行；
  `purge_files=1` 走后台任务并回收 ②③、台账两条 `orig_path` 对得上、刮削台账已清；
  空库 + `purge_files` 不白排任务；① 本地原件在两条路径下都保留。
- `tests/test_recycle_restore.py`（10 例）：`recycled_name` 的字节上限 / 不切坏多字节 / 保扩展名 / 保哈希可辨；
  超长名真的能回收；台账表**无 `book_id` 列**且不在三份清单里；列表能给出原路径与磁盘实况；
  `all` 还原 → 字节原样回来 → 台账清空 → 再调 `task_id=null`（幂等）；目标已存在 ⇒ 退让改名不覆盖；
  台账缺失的 id 如实报错；孤儿还原必须给 `target_dir`、给了就按剥前缀名落地、`../` 名非法；
  清空回收站同批清台账；`strip_stamp` / `_safe_name` 纯函数。

改写既有旧断言（第 75 期口径作废）：

- `tests/test_api_smoke.py`：`test_非空库需force才移除_…` → `test_移除书库默认不动文件_显式purge_files才后台回收`；
- `tests/test_library_count_contract.py`：删库护栏条 → `test_删库已无书数护栏_但计数仍须是真值`；
- `tests/test_annotations.py`：删库不再需要 `?force=1`；
- `tests/test_no_defaults_contract.py`：形状正则同时认 `async def`（`api_delete_library` 已转 async）；
- `tests/conftest.py`：`_quiesce_background` 增加 `wait_background_ops`。

⚠️ **回收目录是会话级共享的**（`CACHE_DIR` 不随 `isolated` 夹具切）⇒ 断言只能看「本次有没有新增」
（前后名字快照做差集），不能看「目录里本来有没有同名文件」——那会依赖用例执行顺序，全量跑时假失败
（本期先在 `test_api_smoke` 上踩到，随后在 `test_library_purge` 上复现）。

前端四连：`type-check` / `test:unit`（447 例）/ `build` / `deploy` 全绿。

### 八、已知取舍 / 未做 / 待用户处置

- ⚠️ **线上现场需要用户处置**（本机无法代做）：升到本期后，到「设置 → 维护 → 回收站还原」点
  「全部按原路径还原」，把此前被误搬的 ~2400 份漫画搬回 `./libraries/漫画`；
  若确有 ≥240 字节的超长名当初回收失败，它们**没有**被搬走（还在原地），只是当时被记成 failed。
- 「移除书库不动文件」与「删书回收三份」的口径不一致**刻意保留**（见第二节），不擅自改删书。
- 还原**不做**「只还原本次误搬的一批」的批次筛选（台账有 `why` 与时间戳，但过滤 UI 未做）——
  现有「逐条 / 全部 / 孤儿」三种粒度已够搬回本次事故；真要按批次筛，先有用户需求再说。
- 未做「回收站自动清理 / 保留期」（与既有「不做通知清理 job」同一条理由：无实例、无判据）。

---

## 第 82 期 · 首页（仪表盘）逐项对齐上游 BookOrbit（V0.82.0，2026-10-01）

**来源**：用户「从上游获取首页的样式」。**两步走**：第一步出对照基线（`docs/bookorbit/bookorbit-dashboard-styles.md`，
上游 `735876214/bookorbit` @ `c292d6cc`，逐区块四档判定），用户确认后第二步逐项改造。**业务语义与数据来源一律不动**。

### 一、用户拍板的范围

部件行网格模型参考上游改（定宽横向卡片带）；12 件部件按上游样式做**但语义不变**（`reading-rhythm` 仍是「入库节奏」）；
卡片外壳**完全按上游**（壳上移到部件行）；加页面入场动效、问候语行、书架行外壳与表头；
12 件部件补齐 **loading / error / empty 三分支 + 骨架**；再加书架**多行（1..3）与两列布局** + 面板控件 + 首启卡片上游化。
拖拽选型经对比后**显式引入 `vue-draggable-plus@^0.6.1`**（实测打包 42 KB minified / ≈13–15 KB gzip、无运行时依赖）——
原生 HTML5 DnD 在 iOS/Android 触屏不触发 `dragstart`，而卡片拖动要触屏可用。这是第 80 期「显式引入须声明理由」口径下
第一个显式新增依赖（`package.json` + `architecture.md` 不变量第 6 条 + 组件头注释三处声明）。

**刻意不做**：整页加载/错误分支（无单一「页面加载」信号，判据不明确）；i18n；`/api/v1/dashboard/*` 批量接口；
onboarding tour；`@vueuse/core`（窄屏判定用 `matchMedia` 自实现）；`lucide-vue-next`（图标走 `lib/icons.ts` 唯一注册表）；
上游的 Tailwind 硬编码调色板（本项目保持语义 token，不为「像」而回退 `DESIGN.md` 禁令）。

### 二、实施（逐文件）

- **尺寸与配置模型**（`data/dashboard.ts`）：`WidgetSize` 从自造三档 `sm/md/lg` 收敛为上游两档 `'1x1' | '1x1.5'`
  （`WIDGET_META` 12 条按上游分配表：宽卡 5 件）；`ShelfDef` 加 `rows?: number`；新增 `SHELF_ROW_OPTIONS` /
  `ShelfLayout` / `DEFAULT_SHELF_LAYOUT` / `SHELF_LAYOUT_LABEL` / `MAX_COVERS_PER_ROW`。
  ⚠️ `WidgetId` 是 localStorage 键**一字不改**；持久化结构 `{id, enabled}` 不含 size ⇒ 三档改两档**零迁移**。
- **部件行**（`DashboardWidgetRow.vue` 重写）：横向滚动卡片带 + 壳（`h-55 rounded-2xl border-primary/40 bg-card/30
  shadow-sm backdrop-blur-[1px]`）+ 定宽映射 + 悬停滚动按钮（`scrollBy(±300)`）+ 行内拖拽（`VueDraggable`
  `handle=".widget-drag-handle"` + `localWidgets` 本地副本防松手闪回）+ 逐卡 `dashboardWidgetFadeUp` 错峰 80ms。
- **可见序 → 全量索引映射**（`stores/dashboard.ts::applyVisibleOrder`）：行内只渲染**可见子集**
  （启用 ∩ 已实现 ∩ 能力裁剪），而 `moveWidget` 用全量索引 ⇒ 直接传会排错位；取可见项在全量列表的下标集合按新序回填，
  不可见项相对次序不变。**本期最容易写错的一处**。
- **12 件部件**：根节点统一去壳（删 `rounded-lg border border-border bg-card p-4 shadow-sm`，保留
  `flex h-full flex-col[/justify-between|items-center]` + `p-3`），统一声明 `size` prop（对齐上游契约），
  接 `useWidgetState` 补三分支（骨架用 `animate-pulse`、错误带重试、空态沿用第 38 期「0 库 vs 无内容」两说）；
  `ReadingGoalWidget` 手写的铅笔 SVG 收敛到 `<Icon name="edit">`。
- **数据态唯一真值源**（新增 `composables/useWidgetState.ts`）：`{loading?, error?, empty?} → 'loading'|'error'|'empty'|'ready'`
  （优先级 loading > error > empty > ready），只读各 store 既有字段（`stats.loaded/error`、`library.loaded/hasNoLibraries`、
  批注部件本地 `failed`），**不做假数据、不加假延迟**。
- **书架行**（`DashboardShelfRow.vue` 重写）：套同款外壳 + 表头（类型图标块 `h-7 w-7` + `text-[15px] font-bold` 标题 +
  计数胶囊 + 悬停滚动按钮 `scrollBy(±560)`）+ 多行分带 + 加载骨架（按行数分带、`aspect-ratio: 2/3`）；
  数据源 / 继续阅读进度条 / 「查看全部」目标 / discover 按 id 稳定排序**全部保持**。
- **分带纯函数**（新增 `lib/shelfRows.ts`）：`effectiveShelfRows`（窄屏压 2）、`chunkIntoBands`、`shelfBookLimit`、
  `useNarrowScreen`（`matchMedia` 自实现，**不引 `@vueuse/core`**；不可用环境按宽屏降级）。
- **问候语行 + 页面**（`DashboardView.vue` 重写）：问候语行（`sparkle` 图标 + 按时段问候 + 用户名 `auth.display` +
  「自定义」按钮）；自定义入口**从面板自带 FAB 移到这里**；单列/两列容器切换；三级错峰入场（40ms / 部件行 / 书架 index×100ms）。
- **问候语纯函数**（新增 `lib/dashboardGreeting.ts`）：按时段分段（清晨/下午/晚上/深夜），优先 `auth.timezone`（IANA），
  解析失败回落本地时间；文案表可单测。
- **面板**（`DashboardSettingsSheet.vue` 重写）：改**受控组件**（`defineModel('open')`）、移除自带 FAB；
  书架 tab 顶部新增「布局」选择器（`rows`/`columns` 图标卡 + `aria-pressed`）、逐书架新增「行数 1/2/3」分段；
  散落的内联 SVG（6 点手柄 / 关闭 ×）收敛到 `lib/icons.ts`（新增 `chevronLeft/chevronRight/grip/rows/columns/sliders` 6 键，
  grip 用 `fill="currentColor"` 实心圆点）。
- **首启卡片**（`FirstRunNotice.vue` / `DashboardWelcome.vue`）：上游化（大圆角 + 主色描边 + 半透底 +
  `radial-gradient(color-mix(in oklch, var(--primary) 18%, transparent))` 光晕 + 图标块 + 大标题口径）；
  ⚠️ `DashboardWelcome` 文案「用**右下角的调节按钮**…」指向已移除的入口，同步改写为问候语行的「自定义」。

### 三、测试（前端 41 个 spec / 456 例全过；后端 `test_frontend_unit_contract` 10 passed）

- 新增 3 个 spec（并登记进 `test_frontend_unit_contract.py::EXPECTED_SPECS`，缺失即报错）：
  `lib/shelfRows.spec.ts`（夹取 / 分带 / 上限）、`lib/dashboardGreeting.spec.ts`（时段边界 / 时区 / 非法时区回落）、
  `composables/useWidgetState.spec.ts`（优先级 / 响应性 —— ⚠️ 响应性用例必须用 `ref` 当源，普通变量不是响应源）。
- 既有 dashboard spec **零覆盖**（普查确认），四连 `type-check` / `test:unit` / `build` / `deploy` 全绿；
  图标契约（模板字面量名 ⊆ `ICONS` 键 + path 非空）自动覆盖新增 6 键。

### 四、已知取舍 / 未做

- 12 件部件内部**未逐像素照抄**（只统一外壳 / 字号字重 / 进度条高度三层）：封面缩略图、趋势图标、悬停播放、
  CTA 按钮等按本项目语义保留 —— 逐像素会拉回上游业务语义（对照文档 §5 待确认 3 的口径）。
- 未做：页面整页三态分支、每书架的库范围筛选、`BookQuickView` / 加入收藏 / 删书三件套（本项目点封面进详情）、
  封面入场动画（`dashboardFadeUp`）、onboarding tour。
- 「发现新书」仍按 id 稳定排序（刻意去随机，第 32 期口径）；两列布局窄屏回落单列、行数窄屏压 2（上游同口径）。

### 五、收尾清理与文档改版（`v0.82.0` tag 之后的补记）

- **删除孤儿组件** `frontend/src/components/dashboard/DashboardScroller.vue`：第 82 期第二步把页面容器直接写进
  `DashboardView.vue`（照上游 `main` + `space-y-5 pb-8 pt-4 sm:pr-2`）之后，这个「页面级栅格容器」已**无人引用**
  （模板不用、测试不引）⇒ 连同 `DashboardView.vue` 里那行未使用导入一起删掉。
  ⚠️ 它正是对照文档 §1.3 记的「两侧同名不同物」陷阱里的本项目那一半 —— 删掉后该陷阱**不再存在**
  （上游 `DashboardScroller` 的对应实现现在是 `DashboardShelfRow.vue`，其头注释已同步说明）。
- **对照文档改为「基线 + 现状」双段式**（`docs/bookorbit/bookorbit-dashboard-styles.md`）：§2–§4 作为**改造前基线**
  不逐行改写（逐行改掉就看不出「改了什么」），新增 §7.2「逐区块现状」+ §7.4「未做与理由」+ §7.5「下次怎么续用」；
  §4 的改造顺序表补「现状」列（①–④⑥⑧ ✅ / ⑤⑦⑨ ◐ 部分 / 「不做」行里 `vue-draggable-plus` 是**唯一翻转项**）、
  §5 五条待确认各补「处置」、§1.2 清单同步增删。⇒ 下次对照上游**从 §7.2 起，不再从 §2 起**。
- 无用户可见变化（纯清理与文档）；`type-check` / `test:unit`（456 例）复跑全绿，文档锚点零新增漂移。

---

## 第 83 期 · 仪表盘余留项（库范围筛选 / 封面动画与细节 / 第 13 件部件 / 快速预览，V0.83.0，2026-10-01）

**来源**：用户指定「按 `docs/bookorbit/bookorbit-dashboard-styles.md` 的 §7.2 逐区块现状与 §5 待确认项，
出下一期计划」。规划阶段三轮问答定范围：**做**「每书架库范围筛选」+「封面入场动画与部件细节收尾」；
`reading-rhythm` 语义**另开第 13 件部件**（保留入库节奏）；书架行「点封面」**改成 QuickView 浮层**。
**不做**：整页三态分支（用户未选，且本项目没有单一「页面加载」信号）、上游截图肉眼比对。

### 一、上游核对（两处修正）

1. ⚠️ **路径修正**：上游的快速预览组件**不在 dashboard 特性下**，是
   `client/src/features/book/components/BookQuickView.vue`（同目录另有 `BookCoverCard.vue` /
   `AddToCollectionSheet.vue` / `DeleteBookDialog.vue` + `composables/useDeleteBook.ts`）。
   计划里写的 `client/src/features/dashboard/components/BookQuickView.vue` **不存在**。
2. ⚠️ **触发方式修正**：上游是**封面卡上的动作菜单 → `quick-view`**（动作集合
   `quick-view` / `edit-metadata` / `add-to-collection` / `move-to-library` / `delete`），**不是点封面**。
   本项目按用户口径改成「点封面即开预览」（少一次点击），浮层内仍可一步进完整详情。
   ⚠️ 上游该组件的**内部实现本轮没读到**（本机 web 取不回、临时目录 sparse-checkout 补检被权限弹窗挡掉）
   ⇒ 本项目**不照抄它**，而是扩展自有的 `BookPreviewDialog.vue`（第 64 期，内容更全：从书卡取全部元信息 + 详情补章节与简介）。
3. 错峰公式照上游 `coverAnimationDelay(index) = index * 35ms`（`DashboardScroller.vue`）；⚠️ 上游 `index` 是**带内序号**
   （每带从 0 重置），故实际最大延迟 ≈ 每带封面数 × 35ms，本项目再加 `min(..., 700ms)` 上限兜底。

### 二、实施（逐块）

**① 库范围筛选（`ShelfDef.library_ids`）**
- `data/dashboard.ts`：`ShelfDef` 增 `library_ids?: string[]`，注释写明与 `scope`（智能书架筛选键）是**两个维度**。
- 新增 `lib/shelfScope.ts`：`filterByLibraries(books, libraryIds, knownLibraryIds)` ——
  **空 = 全部书库**（与 `CustomFieldDef.library_ids` 同口径）；**指向已删库的 id 忽略**；
  有效项全无（库全删 / 库列表未加载）⇒ **退化回全部**（宁可多显示，也不静默清空）；缺 `library_id` 的旧书目按「不在所选库」处理。
  另有 `libraryScopeLabel` 供面板摘要（选满 = 显示「全部书库」，两者效果确实相同）。
- `stores/dashboard.ts`：`normalizeLibraryIds`（去重 + 只留非空字符串）+ `mergeShelves` 补默认 + `setShelfLibraries` + `reset` 清空。
- `DashboardShelfRow.vue`：过滤层叠在 `allBooks` **之后**（四种行类型统一生效）；空态区分「被范围筛掉」与「本来没有」并提示调整位置。
- `DashboardSettingsSheet.vue`：逐书架可折叠「库范围」区（全部书库 / 全选 / 逐库 checkbox + 书籍数）；
  两条交互约定：当前是「全部书库」时勾第一个库 ⇒ 变成只有这个库；**取消最后一个勾选直接拒绝并提示**
  （否则会静默回到「全部书库」，与用户「想少看一点」的意图相反）。

**② 第 13 件部件「阅读时长」（`reading-time`）**
- `data/dashboard.ts`：`WidgetId` 追加 + `WIDGET_META` 一条（窄卡）+ 头注释「12」→「13」；**不进** `DEFAULT_WIDGET_IDS`。
- 新增 `widgets/ReadingTimeWidget.vue`：数据取 `/api/stats` 的 `reading_28d`（每日**秒**）+ `window`，
  与统计页的节奏图同源、零新增接口；`fmtDuration` 复用 `lib/format.ts`；走 `useWidgetState` 三分支（空态 = 窗口内没有记录）。
- `registry.ts` 登记 + 头注释改 13；`composables/useWidgetState.ts` 头注释「12 件」→「13 件」。
- 新增 `tests/test_dashboard_widget_contract.py`：钉住「**前 12 个 id 与上游逐一对应 + 1 件自开**」、
  `WIDGET_META` 与联合类型逐字一致、`registry` 无漏登记且组件文件都在、新增件不默认启用、部件不许再加壳。

**③ 快速预览浮层（QuickView）**
- 新增 `lib/bookDelete.ts`：把书卡 ⋮ 菜单里的删除流程（确认文案 / 同 stem 兄弟名单 / 「部分失败」点名）
  抽成唯一真值源（`siblingNamesOf` / `deleteConfirmLines` / `deletedToast` / `confirmAndDeleteBook`）；
  `BookActionsMenu.vue` 改为调用它（**删掉了原地的第二份实现**）。
- `BookPreviewDialog.vue`：新增 `actions?: boolean`（默认 `false` ⇒ 既有调用方零影响）与 `changed(book, kind)` 事件；
  `actions` 为真时底部多一排「加入收藏（选夹 + 加入） / 删除 / 详细信息」。
  ⚠️ 边界不破：仍**不给**批注 / 阅读日志 / 文件路径 / 编辑入口。
- `DashboardShelfRow.vue`：点封面改开浮层；浮层用 `<Teleport to="body">` ——
  书架行外壳带 `backdrop-blur`，会让 `fixed` 后代以外壳为包含块（浮层会被裁进卡片）；
  删除成功后 `library.loadBooks(true)` 重拉封面带。
- 边界说明：上游 `edit-metadata`（等于开第二个详情页）与 `move-to-library`（本项目移动在书库管理里做）**不做**。

**④ 封面动画与部件细节**
- `lib/shelfRows.ts` 增 `coverDelayMs`（错峰 + 上限兜底，纯函数可测）；`DashboardShelfRow.vue` 加 scoped keyframes
  与 `prefers-reduced-motion` 降级（scoped 动画不受 `main.css` 全局降级保护）；`DashboardWidgetRow.vue` 同批补降级
  （其动画挂在内联样式上，故降级规则需 `!important`）。
- 细节收尾：`currently-reading` / `neglected-gems` / `long-wait` 补封面缩略图；后两件补「开始阅读 / 收听」；
  `year-projection` 补趋势图标（后半程 vs 前半程，升 / 降 / 平用**语义色**，差值 < 0.15 本/天算持平）；
  `lib/icons.ts` 新增 `trendingUp` / `trendingDown` / `minus` 三个键。
- ⚠️ 顺带修一处真缺陷：这三件此前打开目标写死 `/read/`（或详情页），**有声书点下去会进打不开的阅读器**；
  现统一走 `lib/bookOpen.ts` 的 `openTargetOf`。

### 三、测试与验证

- 新增前端 spec：`lib/shelfScope.spec.ts`（8 例：空 / 全选 / 部分 / 陈旧 id 忽略 / 有效项全无退化 / 缺 library_id / 不改入参 + 摘要）、
  `lib/bookDelete.spec.ts`（11 例：兄弟名单 / 确认文案两态 / 回执全成功与部分失败 / 取消不发请求 / 详情失败不影响删除 / 失败不抛）；
  两者均登记进 `tests/test_frontend_unit_contract.py::EXPECTED_SPECS`；`lib/shelfRows.spec.ts` 补错峰与上限用例。
- 既有 spec 同步：`BookPreviewDialog.spec.ts` 扩 mock（`bookCollections` / `addToCollection` / `collections` / `deleteBook`）
  并加 5 例动作区契约（默认不给动作、取消不发请求、删除成功关浮层 + 通知父组件、加入收藏、加入失败不谎报）。
- ⚠️ **实施期间**本机**命令通道不可用**（权限弹窗连续超时，`npm` / `pytest` 均无法执行）⇒ 当时四连与 `pytest` 未跑、提交待补。
  **已于同日恢复后补齐**（见本节「五」）：前端四连全绿、后端全量 **1340 例 / 0 failed**、
  四笔提交已推 `main` 并自动发 `v0.83.0`。

### 四、未做 / 取舍

- **整页三态分支**仍未做（用户本轮未选）：本项目没有单一的「页面加载」信号，硬造一个页面级 loading 只会是假的
  （与第 80 期「消灭假开关」同一口径）。
- 上游 `edit-metadata` / `move-to-library` 两个动作不做（见三、③ 的边界说明）。
- 「库范围」**不做**「按库删掉陈旧 id」的清理：指向已删库的 id 在过滤与摘要里都被忽略，留着无害；
  真要清理得等面板打开时顺手 prune，收益不足。
- 「阅读时长」部件**默认关闭**：存量用户升级后不该凭空多出一张卡。

### 五、收尾：验证补齐 + 文档锚点全仓复核（`v0.83.0` tag 之后）

**A. 验证补齐**（实施期间命令通道不可用，同日恢复后跑完）：前端四连全绿（`type-check` ✅ / `test:unit` **44 spec** ✅ /
`build` ✅ / `deploy` ✅ 已同步 `static/v2`，产物含「阅读时长 / 库范围 / 全部书库 / 已移入回收站」四个标记）；
后端全量 **1340 例（1328 passed / 12 skipped / 0 failed）**（junit 口径）；四笔提交
`3c81112`→`152c407`→`8316107`→`3944880` 已推 `main`，CI 自动打 tag **`v0.83.0`** 并建 Release。

**B. 文档锚点复核**（用户点名「修复报 51 处疑似漂移 + 4 处硬错」）：逐条按 `--suggest` 给出的**符号真实行号**改正，
**只动 `文件:行号` 引用本身**，不改叙述与结论。修后 `tests/check_doc_anchors.py` ⇒ **疑似漂移 0 / 硬错 0**
（符号命中 27 → 74）。涉及三份：`bookorbit-capability-gap.md`（17 处）、`bookorbit-module-inventory.md`（11 处）、
`roadmap-gaps-remaining.md`（20 处）。

- **两类特殊处理**：① 「**记录旧错**」的行不篡改数字 —— `BookDetailView.vue` 按标签拆分后只剩 394 行，
  文档引的 `:487-505` / `:404-415` / `:446-455` 是**旧锚点** ⇒ 补 `原引` 标记或改写成不带 `:行号` 的叙述；
  已失效的 `STEPS` 步骤条（向导早已改回「三页签」）标 `已失效`。工具对含 `原引` / `真值` / `已失效` 的行**按设计跳过**。
  ② **工具启发式误判**：`FilesTab.vue` 的裸续锚被继承成上一个全路径锚点（`lib/api.ts`）⇒ 给首个锚点补回文件名；
  「与 `watcher.ignore` 同族」把 `ignore` 算到了 `library.py` 那个锚点头上 ⇒ 在锚点后补分隔符收住小句。
- ⚠️ 仍剩 **「目标不在此仓」12 条**，**本轮不动**（不属漂移/硬错）：6 条是上游 `packages/types/*` 外部引用（正常）；
  6 条是本仓/上游**裸文件名**，其中 3 条来自 `docs/review/**` —— 那是工具在 Windows 上 `SKIP_DOCS` 前缀比对
  **没归一化路径分隔符**导致的扫描误差。
- ⚠️ 工具自带口径提醒：**「工具报 0 漂移」≠「核完了」** —— `--todo`（该句没点名符号的锚点，本轮 272 条）
  仍需人工并排看，本轮未逐条过。
- 手法：用一次性 Python 脚本改三份文档（**每条断言「恰好命中 1 处」，命中数不对就整体中止**），避免 48 处手工串改。
- 顺带记一条命令坑：该工具在 GBK 控制台打印含 `⇒` 的源码行会 `UnicodeEncodeError` ⇒ 跑它要 `$env:PYTHONIOENCODING='utf-8'`。

---

## 第 84 期 · 自动更新加固（失败退避重试 / 启动即检 / 更新前自动备份 / 引导式开启）+ UPDATES 对照纠正（V0.84.0，2026-10-01）

**来源**：用户指令「当 GitHub 上有版本时，自动更新 NAS 上部署的版本」。规划阶段逐项拍板 ——
实现路径 = **应用内自更新加固**（保留「应用自己拉镜像 + 重建自身容器」这条链，不引入外置 watchtower 容器、
不做纯文档方案）；数据安全 = **更新前自动备份**（PG 走 dump、SQLite 走文件拷贝，保留若干份，**失败即中止更新**）；
检查节奏 = **启动即检 + 每 6 小时**；失效处置 = **退避重试 + 界面显著提示**；默认**仍不挂** `docker.sock`（只把
「要自动更新：取消注释 socket 那一行 + 打开开关」写清楚）；并顺带纠正上游对照里把 UPDATES 记成「未实现」的走样。

### 一、本轮修掉的真缺陷

**自动更新「失败一次即永久卡死」**。第 80 期接通的自动更新是「**先记已尝试、再执行**」：pull 失败也算记过，
此后每轮检查都 `already_tried` ⇒ 自动更新**永久失效，只能手动介入**。而 NAS 上「镜像拉不下来」恰恰是最常见的
失败原因 —— 也就是**最需要重试、最不可能自愈**的那一种。第 84 期把判定从「同版本永久放弃」改成「同版本按
`auto_retry_at` 退避到点再试」，退避序列 **1h → 6h → 24h 封顶**。

### 二、实施（逐块）

**① 退避状态机（`core/updater.py`）**
- `_state` 由「`auto_applied` 记版本号」扩为 `auto_applied` + `auto_failures` + `auto_retry_at` +
  `last_auto_result` + `auto_message`；`_PERSIST_KEYS` 同步扩 —— **漏键 = 重启后静默丢状态**
  （重启即把退避计数清零、对同一版本重新猛拉一遍，正是要消掉的缺陷），故往返用例专门钉它。
- `maybe_auto_apply()` 的判定链重写（顺序即优先级）：`disabled` → `no_update` → 同版本且**已成功**过 ⇒
  `already_tried` → 同版本失败且**在退避窗口内** ⇒ **新 stage `defer`**（`message` 给出下次重试时间）→
  未挂 socket ⇒ `unavailable` → 其余真去 `apply_update(reason="auto")`，成功清零、失败进退避。
- 新增 `_record_auto_attempt` / `_record_auto_failure` / `_record_auto_success` 三个**唯一**写点；
  `_backoff_seconds` 封顶 24h（不封顶的话第 4 次失败要等 48h、96h…… 用户会以为「自动更新坏了」）。
- ⚠️ **未挂 socket 不记失败**（`unavailable`）：环境不具备不是失败，否则用户只是没挂 socket 就背上退避倒计时。
- ⚠️ 「退避窗口内」用**新 stage `defer`**、不复用旧的 `already_tried`（旧值语义是「永久放弃」，继续沿用会把
  界面与测试都读成「不会再试了」，正是本期要消掉的误导）。

**② 启动即检查（`start_background` / `_loop`）**
- 抽出 `_tick()` 承载「检查 + 判自动更新」的**单轮**逻辑，供**启动首轮与定时轮共用**（避免两处各写一份、
  改一处忘另一处 —— 那种形状正是本期缺陷的邻居）；`_loop` 改为**先跑一轮 `_tick()` 再 `wait(interval)`**。
- 收益：每次容器重启（含自动更新重建容器后的那次启动）都立即校验自己是否真到最新，并顺带把持久化的退避状态
  显示出来。⚠️ 出网是「可关、失败降级」的（`check` 内部吞异常），故启动即检不会拖垮启动。

**③ 更新前自动备份（新增 `core/backup.py`）**
- `snapshot(reason)`：**PostgreSQL** 走 `pg_dump -Fc`（压缩 / 单文件 / 单进程单连接，直接落盘、还原快；
  `--no-owner --no-acl`），**SQLite** 走 `shutil.copy2` 整文件拷贝；判据复用 `core/sqlcompat.is_pg()`，不新增第二份。
- 落 `config.BACKUP_DIR`（默认 `/app/config/backups`）—— 在**持久卷**上，容器被删掉重建之后备份还在；这是选它
  而不是 `/app/data` 的唯一理由。轮转同 `reason` 前缀保留最近 **5** 份（模块级常量 `_BACKUP_KEEP`，**不新增配置键**
  ⇒ 不触发「新增配置分区 = 三处同步点」铁律）。
- ⚠️ **失败即中止**是硬要求：任何环节失败都抛 `SnapshotError`，调用方把它变成 `stage="backup_failed"` 并
  **不进入拉镜像**（`pg_dump` 用 `subprocess.run(timeout=…)`，超时自动 kill，不留僵尸进程；stderr 尾段进 `message`）。
- `apply_update()` 里 **backup 在 pull 之前**、全在同一后台线程：HTTP 响应先返回（沿用既有「先返回响应、
  再后台 `_recreate`」范式），主请求不被 `pg_dump` 阻塞；备份失败则不进入 pull。

**④ 失败原因上界面（`status()` 扩展 + 页内横幅）**
- `status()` 增回显 `auto_failures` / `auto_retry_at` / `last_auto_result` / `auto_message`；
  `frontend/src/lib/api.ts` 的 `UpdateStatus` 同步扩字段（`UpdateApplyResult` 增 `backup?`）。
- 「更新」页（`ext/update`）与「新功能」页各加一条失败横幅：显示**原因** + **下次重试时间**（不再是只甩一个
  「有新版本」让用户猜为什么一直没升上去）。

**⑤ 引导式开启（更新页状态卡）**
- `UpdatePage.vue` 新增「自动更新状态」卡：`可用 = 开关开 且 socket 挂着` 两条件缺一不可；未挂时**如实标
  「不可用」+ 说明「开关不生效」+ 给出开启步骤**（取消注释 `docker-compose.yml` 的 socket 行 + 打开开关）。
- ⚠️ **不做假交互**：未挂载时只演示复制升级命令 + 开启引导，不做「看着能点其实不生效」的开关。

**⑥ 上游对照归置（维护页 UPDATES）**
- 上游 Maintenance 页 `UPDATES` 的 «Check for updates» 本项目第 78 期即已实现（且扩展出检查间隔 / 镜像拉取 /
  一键更新 / 自动更新），仓内三处却记成「⬜ 未实现，只读列出」⇒ **对照走样**，本期纠正。
- `MaintenancePage.vue`：UPDATES 分组改为「版本检查与更新」说明卡 + `RouterLink to="/settings/ext/update"`；
  `IMPLEMENTED` 数组加 `'Check for updates'`，`unsupportedGroups` 过滤掉 `UPDATES`（**两处同时漏改 = 又一个新的
  对照走样**）。**不放重复开关** —— 开关只在 `ext/update` 一处，避免两处同键不同步。
- 文档同步改口径：`settingsNav.ts`、`docs/bookorbit/bookorbit-settings-inventory.md`（§2.26 行 + 落地段 + §4 汇总行）、
  `docs/bookorbit/bookorbit-feature-flows.md`（§3.9.26）。

### 三、测试与验证

- 后端新增 `tests/test_backup.py`：`_is_pg`/`_dump_pg` 用替身只验「走到 pg 分支」与落点名 / kind 形状；SQLite 走
  `isolated` 夹具的真实库文件；轮转用 `_rotate` 喂手建文件（保留 5 份、按 reason 分组互不干扰）；失败抛 `SnapshotError`。
- `tests/test_updater.py`：夹具 `_state` 形状同步扩键；持久化往返改「带退避状态」；`pull失败` 用例改名 + 改判据
  （失败不再永久跳过而是退避到点可再试）；新增退避序列封顶 24h / `defer` / `unavailable` 不记失败 / 快照失败即中止 /
  换版本清零 / 持久化后重启不重试等用例。
- 前端新增 `views/settings/pages/UpdatePage.spec.ts`（状态卡可用性判据 / 未挂载如实提示 / 失败原因 + 重试时间 /
  备份口径）与 `views/settings/pages/MaintenancePage.spec.ts`（UPDATES 说明卡 + 跳转链接存在 / 不在未支持卡 /
  过滤不过度），两者登记进 `tests/test_frontend_unit_contract.py::EXPECTED_SPECS`。
- ⚠️ **不新增配置键** ⇒ `server.EDITABLE` / `GET /api/config` 键列表 / `settingsFields.ts` 三处同步点**不触发**；
  `test_update_config_contract.py` 只更新 docstring 口径，断言一条不改。**不新增设置页** ⇒ 契约页数 37 不变、
  `EXPECTED_OWN` 不变。

### 四、未做 / 取舍

- **不引入外置 watchtower 容器**、不做「纯文档」方案：只在应用内这条既有链上定点加固（用户明确选择）。
- **默认仍不挂** `docker.sock`：不在部署文件里默认开启（不放大攻击面），只把「取消注释 socket 行 + 打开开关」写清。
- **备份保留份数不做成配置键**：运维口味而非用户配置，弄成可配置要付「三处同步点」的代价，不值当。
- 上游 Maintenance 的 IMPORT（从其它书库工具一次性导入）/ RECOMMENDATIONS（刷新推荐索引）仍不作（容器部署口径下无对象）。

### 五、收尾

- 前端四连：`type-check` / `test:unit` / `build` / `deploy` 全绿（`deploy` 已同步 `static/v2`）。
- 后端全量 `pytest`（离线）0 failed。
- 版本 `VERSION` 0.83.0 → **0.84.0**，同批补 `CHANGELOG.md` 段；推送 `main` 后 CI 自动打 tag `v0.84.0` 并建 Release。

---

## 第 85 期 · 目录体系（本地「卷 / 段」解析 + 官方书城目录覆盖）（V0.85.0，2026-10-01）

**来源**：用户两条口径 ——
①「有的书目录看起来不清楚，比如楔子、番外，要和目录分开，不要显示成第几章，用书中实际标题」；
②「当本地目录不清楚时，去【番茄】、【起点】等官方书城下载目录（**只取目录，不取正文**）」，
规划阶段拍板「自动匹配 + 手动指定」两种取法。**分两批**：A 本地目录解析（可独立交付）→ B 官方书城目录。

### 一、批次 A：本地目录的「卷 / 段」

- **新增 `core/reading_list.py`（叶子模块）**：`build_reading_list` 是「卷 / 段 → 章」的**唯一真值源**，
  EPUB 路径（`library._reading_list`）与 TXT 路径（`txtcache.native_chapters`）都调它 ——
  此前 TXT 那条硬编码单个「正文」卷，**TXT 书完全看不到卷**。
  规则：卷首优先级 = nav 层级容器 → 标题形态（`第X卷` / `第X部` / `卷X`）；
  无编号条目（楔子 / 序章 / 番外 / 后记…）各自成段并打 `kind = front | back`、**不参与编号**。
- `detect`：卷首判据与无编号判据提升为**公开**函数（`is_volume_title` / `is_unnumbered_title`），
  词表被 `CHAPTER_PATTERNS` 那条「捕获整行」的正则引用**同一常量**（拼接后与历史正则逐字一致，
  分章行为一字未变）。
- `library._reading_list`：换**标题解析链** —— 目录（nav / NCX）→ 文档自带 `<title>` / 首个标题元素
  （只对目录没列到的文档读前 64 KB）→ 文件名（含汉字才用）→ 兜底「第 N 章」。
  缺中间两环正是**「楔子显示成第 3 章」**的根因。**`index` 一字未动**（进度 / 批注的坐标）。
- 前端：新增 `lib/chapterGroups.ts`（两处目录共用：摊平 + 位置 + 段名），ReaderView 卷可折叠、
  ChaptersTab 章节缩进、无名段按位置叫「卷前 / 卷尾 / 正文」（不再回落成「目录」）；
  无编号条目不渲染序号但保留列宽（标题不参差）。

### 二、批次 B：官方书城目录（只取目录）

- 数据库两张表：`store_toc`（一本书在一个来源上的一次抓取结果，**含负结果**）+ `toc_map`
  （书城章节 ↔ 本地 index；**未映射的本地章节不入表** ⇒ 覆盖层永远造不出「点不开的假条目」）。
  搬迁纪律：两张表进 `ORPHAN_TABLES`；**刻意不搬**并登记 `REMAP_DERIVED_TABLES` ——
  主键含来源与书城序号，通用整表 UPDATE 撞主键会被外层 `except` 吞成「搬 0 行」，
  而重建成本只是一次抓取；**不搬不会损坏任何东西，搬错才会**。
- **新增 `sources/toc_sources.py`**：注册表 + 只取目录。**绝不调用 `book.content`、不抓任何一章正文**；
  解析复用 `rules._extract_links`（CSS / regex 双通道与相对地址补全口径与「下载」完全一致）；
  出网走 `DownloadManager._client`；开关走 `gate_reason(source, feature="toc")`
  —— 第 85 期给闸门加**用途维度**（默认值 ⇒ 既有调用方行为一字不变）。
  `validate_toc_rule` = `rules.validate_rule` **只去掉 `book.content` 那一条**：
  取目录不读正文，要求它只会逼人写一段永远不用的假规则。
- 匹配与对齐全在纯函数里：`best_match`（书名归一全等 0.8 + 作者对上 0.2，低于阈值**如实说没匹配到**
  并附分数）；`build_pairs` 两趟 —— 标题归一后完全相等 → **两边剩下条数一样多**才按顺序一一对应。
  刻意不用「跳过书城卷名页再顺序配」那种更聪明的做法：**跳错一格就是全书章名整体错位**，
  比不配（保持本地名）难查得多。
- `apply_toc_override`：**本地结构是骨架**（`index` 顺序 = 读者翻页顺序，书城那份**不参与排序** ——
  两边章节数几乎不会相等），只改名与补卷名；未映射的条目一条不丢、也不改名；返回新对象。
- 接口：`GET /api/toc/sources`（清单 + 闸门，`usable` 与 `blocked_reason` 由后端算好、措辞只有一份）、
  `POST /api/toc/fetch`（**失败也落库**：`ok=0` + 原因原文，免得每次开详情页都重新外呼）、
  `DELETE /api/toc/{bid}`（还原为本地目录，两表一起清）。
  配置三同步点：`config.DEFAULTS["download"]["toc_enabled"]`（**默认关闭**）+ `server.EDITABLE`
  + 设置页 `NETWORK_FIELDS`。⚠️ **不受 `public_only` 约束** —— 那条管的是下载内容的版权，
  取目录只读一份章节标题，是另一个动作（用户点名要的正是「官方书城」）。
- 前端：新增 `components/book/detail/TocSourceCard.vue`（逐来源列出 / 可填书页地址手动指定 / 还原）；
  文案写清「**只读章节目录，不下载任何正文**」；`verified: false` 显示「未验证」徽标、
  不可用的按钮**点不动**；**失败也 emit**（负结果同样落库，不刷新用户就只剩「点了没反应」）。

### 三、诚实的边界（本期的取舍）

- 番茄 / 起点两条内置规则**未在本机联网验证**（本机对外网络受限 + 站点反爬 / 懒加载），
  故标 `verified: False` 并在说明里写清「请用『试取目录』核对后再用」；微信读书 / 掌阅 / 晋江
  **只登记、不宣称可用**。**不写成「可用」** —— 那是假交互。
- 取目录**默认关闭**且必须显式点按钮：默认开着意味着「打开详情页就可能自动外呼商业站点」，
  那不该是默认行为；取到的目录落库后，之后每次开详情页**不再重复外呼**（含负结果）。

### 四、踩坑（都靠测试才暴露）

1. **私有函数重名覆盖**：新 helper 起名 `_tag_text`，而 `library.py` 里早有 `_tag_text(xml, tag)`
   （`probe_epub` 抽 OPF 元数据用）⇒ import 期毫无征兆，跑起来 `probe_epub` 抛 `TypeError`
   又被自己的 `except` 吞掉 ⇒ 书目集体丢系列 / 出版社 / 书名，**82 条与本模块无关的测试连锁失败**。
   教训：**往老模块里加私有 helper 前先 grep 名字；并且必须跑全量**。
2. **happy-dom 下 `isVisible()` 测不出 `v-show`**：折叠用例原先断言 `isVisible() === false`，
   但它一路报 true（不把祖先的内联 `display:none` 级联进计算样式）⇒ 断言「折叠生效」的用例
   **永远绿**，真缺陷被静默放过。改成直接断言面板 `style.display`。
3. **状态清单与覆盖层共用一份数据**：给界面用的清单原先把 `entries` 从同一份 dict 上 `pop` 掉，
   于是**映射照样落库、目录却一点不生效**，而且两边看着都正常。改成另建一份清单。

### 五、收尾

- 前端四连：`type-check` / `test:unit`（**49 spec**）/ `build` / `deploy` 全绿（已同步 `static/v2`）。
- 后端全量 `pytest`（离线）：**1397 例（1385 passed / 12 skipped / 0 failed）**。
- 版本 `VERSION` 0.84.0 → **0.85.0**，同批补 `CHANGELOG.md` 段；推送 `main` 后 CI 自动打 tag `v0.85.0`。

---

## 第 86 期 · 书源体系对齐 legado / Mihon + 书籍追更（2026-10-01 ~ 10-02）

**来源**：用户要求把书源能力补齐到「能用真源站」的程度。分期推进：
`legado-core` → `ledger-import` → `channels-and-login` → `probe` → `ingest-three`
→ **`update-append`** → `online-fallback` → **`sources-ui`**。

### 一、核心与台账（前期已交付）

- 书源规则内核（legado 兼容解析）、导入台账（导入历史 / 差异 / 回滚锚点）、
  渠道与登录（Cookie / 变量 / 登录声明）、单源与全量探测。
- 接口共 16 条全部就绪并有契约测试：`POST /api/sources/import`（含 dry-run 差异表）、
  `GET /api/sources/imports`、`GET /api/sources/export`、`GET /api/sources/ledger`、
  `POST /api/sources/{name}/enabled` / `/rollback` / `/reanalyze`、`POST /api/sources/bulk`、
  `GET|POST|DELETE /api/sources/{name}/cookie`、`GET|POST /api/sources/{name}/vars`、
  `GET /api/sources/{name}/login-spec`、`POST /api/sources/{name}/probe`、
  `POST /api/sources/probe-all`、`POST /api/toc/probe`。

### 二、`update-append`：书籍**追更**（只追加，不重写）

摸底纠了一个重要误判：**章节级 API 早已落地并接线**（`core/epub_update.append_chapters`
+ `add_manifest_item` / `add_spine_itemref` / `add_nav_link` / `add_ncx_navpoint` + `verify_unchanged`），
所以本期只做真正还差的：

1. **按路径加锁**（`manager.update_lock` 包裹 `update_report`）：并发追更会各自
   「读旧内容 → 写 `.part` → replace」⇒ **后写覆盖前写 = 丢章，两边还都报成功**。
   拆法刻意**不动缩进**（原实现改名 + 新增薄入口），把 diff 压到最小。
2. **删死代码**（`manager.update` 里 `return` 之后那段旧实现）：它看起来像可恢复的备选路径，
   而它正是「重复内容 + index 漂移」两条静默错误的正身。
3. **nav 定位加固**：必须先在 `epub:type="toc"` 那个 `<nav>` 里取最后一个 `</ol>`；
   否则 landmarks / page-list 的 `<ol>` 在前时新章会被插进「地标」列表 ——
   阅读器目录里看不到，而「nav 里含这条链接」的断言照样过。
4. **新增 `core/autoupdate.py`** + `config.DEFAULTS["auto_update"]`
   （`enabled=True` / `interval_hours=12` / `max_books=50` / `request_delay=3.0`）+
   `activity_log.ACTION_UPDATE` + server lifespan 起停 + 热应用。
   三条口径：**首轮延迟一个间隔**（重启不等于全量外呼）、串行 + 限量 + 逐本节流、
   **只调 `update_report`**（并发/原子/只追加的保证仍只在一处）。
5. `auto_update` 配置**三处登记**（`server.EDITABLE` + `GET /api/config` 回显 +
   设置页 `NETWORK_FIELDS`）—— 默认开启而不可关的开关等于假开关。

### 三、`sources-ui`：把 16 条接口接上界面

- 新增「**书源工具**」页（与「书源管理」同能力键 `sources`）：导入（**默认只预览不落盘**，
  撞名/更新**逐条选**跳过/覆盖/并存，默认最保守的跳过）· 台账（启停不动文件、档位、
  不支持字段与改用建议、覆盖历史一键回滚、导出）· 登录（Cookie 只显示「有没有/几条/哪些域」，
  **不回显值**；变量留空即清除）· 全部源实探一次 · **追更卡**（状态徽章 / 一键暂停 /
  立即追更一轮）。
- `SourcesView.vue` 增强 A~E：**A** 统计条（9 徽章可点即筛选）· **B** 工具栏
  （搜索 + 五维筛选 + 四排序，状态存 sessionStorage）· **C** 批量操作（复用 `POST /api/sources/bulk`，
  逐条回报、不整批失败）· **D** 验证列（**「未验证」与「验证失败」必须分开**，title 带原因与耗时）·
  **E** 追更卡（写 `PUT /api/config` 的 `auto_update`，不另开写接口）。
- 四条关键口径（写进代码注释，避免被「简化」掉）：**选中集合按源名存**（按下标存会在
  `load()` 顺序变化后变成「选中了别的源」）· `load()` 清理已不存在的选中项 ·
  **删除二次确认**（文案写明条数与后果）· 统计数字 = **整表**口径而点它才筛
  （这条不变量由 `lib/sourceFilter.spec.ts` 钉住 —— 界面自相矛盾最伤信任）。
- 台账字段是 `group_name` 而列表用 `group`，必须转一次；**不转不会报错**，只是分组筛选永远空。
  台账请求用 `Promise.allSettled`：**台账失败不让整页失败**（它只是补维度）。

### 四、⚠️ 本期最值得记住的 bug：能力键没跟上实现 ⇒ **入口整个消失**

用户报「书源找不到在哪」。真相：书源管理是「工具」页的一个标签（`ToolsLayout`，`feature: 'sources'`），
按当前书库的能力键裁剪，而 `core/features.py` 的 `FEATURES_BY_TYPE` 里 `sources`
**只给了 `ebook` / `mixed`** —— 用户当时选中的是**漫画库**，标签直接消失。
而注释里那条判据还写着「书源下载产出 EPUB → 仅 ebook」，那是**第 86 期之前**的事实：
本期三类产物都能走书源下载（文本 EPUB / 漫画 CBZ / 有声书目录树）。
修法：`comic` / `audiobook` 都加上 `sources`，契约测试同步更新（它先红了一次 —— 护栏在正常工作）。
**纪律**：能力键的判据是「现有实现真实支持的范围」；**实现扩了而这里没扩，界面就会藏起
用户真正需要的入口**。第 87 期因此专门补了一份可执行的格式 × 能力矩阵（见下）。

### 五、踩坑

1. **测试隔离**：`isolated` 夹具只保证「不碰真实数据」，而 `SOURCES_DIR` 与会话级临时根**共享**、
   `REGISTRY` 是**进程级全局**、台账/导入历史在**共享库**里 ⇒ 跨用例敏感语义的测试要自带
   `_sandbox` 夹具（参考 `tests/test_source_ledger.py`）。
2. **建对象要用会当场抛错的入口**：用例里的源一律 `store.add_rule` 建，**不要**走
   `POST /api/sources`（返回 200 也可能是「一条都没加进去」，断言会变成永远绿的假失败）。
3. **不能让 `autoupdate._loop` 的 `stop.wait(interval)` 真等**（最小间隔 1 小时，
   真等会把整个 pytest 挂住）⇒ `monkeypatch.setattr(stop, "wait", fake_wait)`。
4. 新增 `DEFAULTS` 段是**会被配置契约测试盯上**的动作 ⇒ 除了 before/after 断言，**必须跑全量**。

### 六、收尾

- 后端全量离线 `pytest`：**1585~1602 例 / 0 failed / 0 errors / 12 skipped**（随补齐递增）。
- 前端 `type-check` 零错误、`vitest` **529 例**、`build` + `deploy` 同步 `static/v2`。
- 挂起项在本期无遗留：`online-fallback` 仍未做（本地读不了时应用内渲染源站页面）。

---

## 第 87 期 · `.zip` 内容分派 + 重名与重复判定重构 + 格式能力矩阵（2026-10-02）

**来源**：用户三条（附「同名冲突 16 组 / 已选 48 项」面板截图）——
①「书库要能识别与解析 ZIP，漫画库需支持 ZIP 内多图片的**顺序读取与展示**」；
②「大量**无意义重名**的识别逻辑有问题，要改进去重/重名判定，避免误判或冗余展示」；
③「核心能力应对**所有格式统一支持**（除格式专有功能），需**明确各格式的功能支持矩阵**」。

**规划阶段拍定的口径**（照此实现，不再改）：
- **ZIP = 按内容分派**（不是最省事的「与 `.cbz` 等价」）：里面是图片按漫画读、
  含 EPUB/PDF 按对应格式读；**混合 / 嵌套要有明确结论**，判不出**如实报「无法判定」，不许猜**。
- **重名四项全要**：判据换成「文件名 + 目录 + 体积/页数/内容哈希」综合（名字只作线索）·
  同系列**不同卷不该同组**（收紧）· 破折号/全角半角/多余空格差异**视为同一**、
  ` (1)`/` (2)` 副本后缀**不算不同书**（放宽）。
- **矩阵 = 文档 + 能力键 + 契约测试**。
- 起手顺序由实现方定 ⇒ **① ZIP 分派 → ② 矩阵（含修静默失败）→ ③ 重名判定 → ④ 前端与收尾**。
  理由：ZIP 会给矩阵新增一列（分派后的真实形态），先做完矩阵才不返工；重名判定最复杂
  （牵动入库闸门与两个前端面板、有数据迁移风险），放最后独立可回滚。

### 一、`.zip` 内容分派（容器看内容，不看后缀）

- **新增 `core/zipkind.py`**：`analyze(path)` 分档 `comic`（图片档，**可读**）/ `epub`·`pdf`
  （内含恰好一份文档）/ `nested`（内层还是压缩包）/ `multi` / `mixed` / `empty` / `broken`，
  每档给 `reason` 与 `evidence`（文件数、图片数、文档名、样本名）。判定**复用漫画那套既有判据**
  （`comics._keep` 算不算一页、`_JUNK_PARTS`、`_sniff`），坏包**不抛异常**（与 `comics.probe` 同口径）。
- **关键设计：`.zip` 的 `format` 归一成真实形态（`CBZ`），上层零分支** —— 封面接口
  （`fmt in ("CBZ","CBR")`）、逐页接口（`is_comic`）、前端阅读器（`bookOpen.ts` 的 `READER_FORMATS`）
  **全部自动生效，前端一个字都不用改**。若把 `format` 留成 `"ZIP"`，就要同步补 4 处后端 +
  3 处前端判据，且以后每加一处都要记得补 —— 那是必然漂移的形态
  （与既有 D6 CBR 的「魔数嗅探 + 后端抽象、上层零分支」原则一致）。
- **判不出的一律不假装能读，但照样入库**：`format` 保持 `ZIP` + `unparsable=True` ⇒
  出现在「待修复」分面里**看得见**。文件在盘上、书目里却找不到（隐形文件）比拒收更糟；
  而**报成 EPUB/PDF 会让前端去开一个打不开的阅读器** —— 正是第 3 条要消灭的「入口在、点了失败」。
- ⚠️ 漫画分支加了**附加判据**（`zip_v is None or zip_v["kind"] == "comic"`）**不能省**：
  `is_comic` 只看后缀，而 `.zip` 已在 `COMIC_EXTS` 里 —— 少了它，一个「内部其实是 EPUB」的 zip
  会被当成漫画去数页（数出来的是 EPUB 里的插图张数），用户看到一本假漫画。
- **展开（unwrap）成真正的书**：内含 EPUB/PDF 的容器按内容提取成真 `.epub` / `.pdf`；
  容器本身就是改了后缀的 EPUB ⇒ 整份另存为 `.epub`（EPUB 即 zip，字节复制）；
  嵌套 ⇒ 逐层提取。三条纪律：只在容器所在目录落新文件 · **原子写**（`.part` → replace）·
  **绝不覆盖已有文件**（撞名逐条如实报，不静默改名 —— 改名会换 `book_id`）·
  **默认不删源**（`remove_source=true` 才删）。另有 **zip-slip 防护**（条目名含 `..` / 绝对路径 /
  盘符一律拒绝落盘）。前端「副本与容器」面板：副本**只列不动**、待展开压缩包**一键展开**。
- **自动归库也看内容**：`_type_of_name(name, src=None)` 对容器调 `zipkind.analyze(src)` ——
  图片档 → 漫画库、内含一份文档 → 电子书库、**判不出/读不到 → 返回空**（由 `decide` 如实拒收，
  而不是猜一个库）。只有**名字**没有路径时仍然不猜：猜错的代价是书进错库，而错的库既读不了它、
  用户也难发现（比拒收糟得多）。`zipkind` 导出公开常量 `DOC_KINDS` 供归库复用，
  避免「哪些扩展名算文档」这份清单两边各写一份。

### 二、修 3 处「入口在、点了静默失败」+ 落格式能力矩阵

摸底扒出三处**静默失败**（比入口消失更难查：用户看到的离原因十万八千里）：

1. **服务端抓取的封面只对 EPUB 生效（真 bug）**：封面接口把 `db.get_cover(bid)` 的读取
   **只写在 EPUB 分支里**（`if fmt != "EPUB": 404` 在它前面），而 `library._apply_overlay`
   对**任何格式**只要库里存了抓取封面就置 `has_cover=True` ⇒ PDF/TXT/MOBI/AZW3 卡片显示「有封面」
   却永远 404 占位。修法：把服务端封面的读取**提到格式分支之前**（漫画/有声书仍优先用文件内封面
   ⇒ 这两类行为逐字不变）。
2. **OPDS 给目录型条目广告必然 404 的下载链**：`/opds/download/{bid}` 要求 `path.is_file()`，
   有声书目录 / UNITS 合集是目录 ⇒ 必然 404。前端早已按同一判据刻意隐藏下载按钮 ⇒
   补齐同一条口径：**少给一个必然失败的链接，而不是错给**。
3. **前端「无封面」分面只算 EPUB** ⇒ 与卡片显示各说各话。改成「没有封面」即命中。
- 附带文档漂移：`docs/roadmap-gaps-remaining.md` 里「手动编辑元数据仍限 EPUB」早已过期
  （第 22 期放开，`server.py` 的 `editable` 恒真）。
- **矩阵落地**：新增 `docs/format-capability-matrix.md`（「能力 × 格式」全表，格式专有与通用
  分开并写明理由）+ `tests/test_format_matrix.py`。契约闸门是：**任何「只给部分库」的能力键
  都必须在 `EXCLUSIVE` 表里登记理由**，否则测试红 —— 再加一个只给某类库的能力键时，
  **写理由这个过程本身就会暴露漏配**（第 86 期 `sources` 漏给漫画库就是这么漏的）。
  另有：通用能力四类库都有 · `mixed` 含全集 · 每条能力键都有中文名 ·
  `SETTING_CAPS` 声明的键真实存在（写错键名 ⇒ 覆盖项在所有库上被**悄悄剔除**，同类静默失败）。

### 三、重名与重复判定重构

- **判据收敛到唯一函数**：新增 `conflict_key(name)`（去目录 + **剥副本后缀** ` (N)`/`（N）`/`[N]`
  + **破折号家族统一**（`‐‑‒–—―−` → `-`）+ NFKC 全角归一 + 复用 `norm_key` 去噪声）·
  `volume_of(name)`（`第X卷` / `Vol.01` / `v2` → 卷号签名，解析不出返回空，**不猜位置**）·
  `is_copy_name(a, b)` · `conflict_kind(rels, paths, lib_ids)`（**纯函数**，便于单测）。
  ⚠️ 与 `norm_key` 的**分工不能合并**：`norm_key` 服务「重复书籍 / 搜索 / 实体」（把《书名》与书名
  当同一本），新判据服务「同名冲突 / 副本识别」（判「这两条路径说的是不是同一本书」）——
  合并会让搜索把不同卷的书也当成一本。
- **结论分级**（替代原来「一律报冲突」）：`duplicate_scan`（几条指向**同一个物理文件** ⇒
  改名是错的，该修的是库配置，**默认不勾选**）· `cross_library`（同一相对路径出现在多个库 ⇒
  真冲突，留一个改一个）· `same_name_different_dirs`（同库同名但不同目录 ⇒ 是**不同的书**，
  改名时用目录名区分才有意义）。组级结论与默认勾选一起给前端。
- ⚠️ **最大风险已规避**：`book_id` 是存储层锚点（进度 / 批注 / 标签 / 评分全挂它），
  改生成规则 = 全库迁移（前例 `db.upgrade_book_ids()`）⇒ **本期不改 `book_id` 生成规则**，
  只重构「判定 / 分级 / 默认勾选 / 展示」层。
- 口径分裂（入库侧「同库同名一律放行」vs 清单侧「已存在同名报冲突」）在注释里写明各自适用面，
  未强行统一（统一会改变真实写入路径的行为，风险大于收益）。

### 四、F：三档宽度视觉自查（360 / 768 / 1280）

- 做法：`agent-browser set viewport W H`（**注意：`viewport` 是 `set` 的子命令**，
  顶层 `agent-browser viewport` 会报 `Unknown command`；权威命令表见
  `agent-browser skills get core --full`）+ `eval` 量布局 + `screenshot`。
  已把这套封装成机器级命令 `ui-smoke`（`%APPDATA%\npm\ui-smoke.cmd` →
  `.codebuddy/tools/ui-smoke.ps1`）：打开 →（可选）登录 → 每档设视口 → 量布局 → 截图，
  含 `-CleanOnly` 清理残留进程（残留会占住 daemon socket 让后续命令**静默挂死**）。
- 度量结论：**三档均无页面级横向溢出**；8 个工具标签 / 5 个工具栏控件 / 勾选框在窄屏
  都仍在 DOM 且有尺寸（没有被 `display:none` 藏掉）；768 / 1280 布局干净。
- **360 档的真问题（已修）**：外壳**不折叠侧栏**（固定 240px），主内容区只剩 **82px** ⇒
  卡片被压到 **12px 宽**，中文**一字一行**地竖排。诊断证明这**不是**断行规则问题
  （`white-space / word-break / overflow-wrap` 全是 `normal`，纯物理挤压），
  所以给文字加 `nowrap` 一律无用 —— **要修的是容器宽度**。
  修法：`ToolsLayout.vue` 内容区包一层 `overflow-x-auto` + 内层 `min-w-[32rem]`
  （**宁可横向滚动，也不把卡片压成一字一行**；宽度充足时两层均无影响）。
  取值依据：修复前实测 **768 档在 490px 内容宽度下本来就是干净的** ⇒ 512px(=32rem) 留余量；
  先用 34rem 时 768 会多出 16px 横向滚动（`off` 2→5），收到 32rem 后恢复 `off=2`。
- 诊断产物：`.codebuddy/tools/diag-narrow.js`（**高窄盒子探测器**：抓 `width<46 && height>=60`
  的叶子盒子并报出自身与父元素的宽度与断行相关 CSS）。**必须用文件传入**：
  `$js = Get-Content -Raw .codebuddy\tools\diag-narrow.js; agent-browser eval $js`
  —— 命令文本里的双引号会被工具层吃掉。

### 五、诚实的边界

- 「窄屏外壳折叠侧栏」（抽屉/折叠）**仍未做**：现在 360 档是「**可用但要横向滚**」，
  不是优雅的移动端布局。属独立一件事。
- 视觉自查**覆盖不到行级渲染**：当时所测实例（0 书库）书源列表是空态，
  徽章 / 验证列 / 追更开关在**有数据**时的窄屏表现需另测。
- `online-fallback`（本地读不了时应用内渲染源站页面）仍未做。

### 六、踩坑

1. **`plan_create` 整晚返回 `AI_APICallError-Bad Request`**（缩到 700 字也一样）⇒ 是 planning
   服务端故障、不是内容问题；本期改用**待办清单**承载计划。
2. **`agent-browser` 视口**：`--device` 只对**启动时**生效、`headless` 忽略
   `--args --window-size`；每次连接会重置视口 ⇒ 一律用 `set viewport`。
   ⚠️ 我曾据此误判「工具不支持视口」—— **命令报错 ≠ 能力缺失，先读该版本自带命令表**。
3. **PATH 上的 `.cmd` 转发会吃掉数组参数**：`-Widths 360,1280` 到达时成了单个 `3601280`
   ⇒ 给 `.cmd` 包装的脚本不要声明 `[int[]]`，用字符串自己切分。
4. **PowerShell 5.1 按 ANSI 读「无 BOM 的 `.ps1`」**：中文/emoji 注释会搅乱字节，
   **把后续代码行吞成字符串**（表现为「变量莫名是 null、`New-Object` 那行像没执行」）
   ⇒ 临时 `.ps1` 一律**纯 ASCII**。
5. **WebSocket / 大输出**：CDP 消息会分片，必须按 `EndOfMessage` 累积，否则半截 JSON
   解析失败后下一次 `ReceiveAsync().Wait()` **永久阻塞**；另：CLI 的 `eval` 输出里引号是
   **转义过**的（`{\"w\":`），取值要匹配裸词（如 `ovf`）。
6. **工具自己也会静默失败**：`ui-smoke` 某次登录没成功却照样打印三档度量与截图 ——
   那是**登录页的数字且无任何提示**。已加**硬断言**（登录后重新探测，仍在登录表单则
   打印 `LOGIN FAILED ... NO metrics emitted` 并跳过该路由，绝不产出不可信数据）。
   **教训：凡自动化脚本，产出前必须断言「我测的是目标页面」。**

### 七、收尾

- 后端全量离线 `pytest`：**1588 例 / 0 failed / 0 errors / 12 skipped**（今日起点 1535），
  新增 `test_zip_dispatch.py` 12 + `test_zip_unpack.py` 14 + `test_format_consistency.py` 5
  + `test_format_matrix.py` 6 + `test_name_conflicts.py` 13。
- 前端 `vitest` **529 例**通过、`build` + `deploy` 同步 `static/v2`。
- **验收要点（用户侧）**：① 必须点「**重建索引**」—— `catalog.refresh_library` 对
  `(size, mtime)` 未变的条目直接跳过，早早入库的 `format="ZIP"` 老条目不会被重新探测，
  重建后才按内容分派成能读的漫画包；② 工具页 →「书源工具」（导入 / 台账 / 登录 / 验证）；
  ③ 设置 → 书库管理 →「同名冲突」面板（组级结论，`重复扫描` 默认不勾选）+「副本与容器」面板。

---

## 第 88 期 · 书库加载慢（请求路径 + 前端感知 + 分页）（V0.88.0，2026-10-03）

**来源**：用户原话「我刚将电子书导入书库，但在书库中显示加载等待时间过长。请分析可能导致延迟的原因，
并提出优化方案以缩短显示时间。请考虑书库数据量、索引机制、加载策略及界面反馈等因素。」
**范围**：用户拍定**全量**（含分页与虚拟滚动）。

### 一、诊断结论（只读探测，行号为当时 HEAD）

- **部署口径**：用户侧是 `docker-compose` 默认（Redis + PG 都在）⇒ 封面/列表缓存正常，
  「封面链」基本可排除；主犯是 **「刷新跑在请求线程里」**。
- **症状三条全中**：每次打开书库都慢 / 导入后第一次特别慢 / 显示「这个书架还是空的」很久才有书。
- **后端**：`GET /api/books`（`server.py` → `library.books()` → `catalog.books()/books_of()`）
  稳态是快的（读索引、DB 查询全批量无 N+1、有 gzip，600 本实测 65–73 ms）。真问题两处：
  ① **`catalog._settle` 在请求线程里同步跑 `refresh_library`**（整目录遍历 + 每文件一次 stat，
     必要时逐本 probe）；触发于冷启动 / 库被标脏 / 口径版本变化；NAS 上每次 syscall 毫秒级
     ⇒ 266 本即数十秒。这正是第 62 期「书架 42 秒」的同一处。
  ② **`/convert` 与 `/convert-path` 入库后不调 `library.invalidate()`**（其它写路径都调）
     ⇒ 新书只能等 watcher 全量兜底（默认 60s）。**确定性缺陷**。
- **前端**：`ShelfView.vue` 加载期**完全没有反馈**，`library.loading` 从未被视图使用，
  `sorted.length===0` 直接落进 `EmptyState`（「这个书架还是空的」）⇒ **数据在路上却告诉用户没有书**；
  `loadBooks` 把 `/api/books` 串在两个 `/api/reading-thresholds` 之后（白多一个 RTT）；
  全量 `v-for` 无虚拟化；每卡一个封面请求；`request()` 无超时无重试。

### 二、后端 A（脏库读不再扫盘）

- **脏库读不再在请求线程扫盘**：派后台刷新 + `catalog.SETTLE_WAIT=0.25` 上限等待，到点如实返回现有索引。
- 启动**后台预热** `prewarm_async`（只针对索引非空的库；不阻塞启动）。
- `GET /api/books` 追加 `scanning` 字段（只加不改）；新增 `GET /api/libraries/scan-state`。
- `refresh_library` 计时日志（>300ms 的请求才记一行）；`/convert`、`/convert-path` 补 `invalidate(lid)`。

### 三、前端 B（骨架屏与真实状态）

- 新增 `components/ui/Skeleton.vue`；**空态判据改为「非 loading 且真无数据」**；错误态与重试；
  「正在建立索引…」进度条；阈值并行；次要请求懒化（侧栏 `requestIdleCallback`、移动批次按需）；
  `request()` 超时与分类错误（GET 仅网络错重试一次）；`allTags` 用 Set；`scopeCounts` memo；
  滚动改 IntersectionObserver。
- 新增 `apiRequest.spec.ts`(7) / `ShelfView.states.spec.ts`(5) 并登记 `EXPECTED_SPECS`。

### 四、⚠️ 契约变更（有意）

- `library.invalidate()` 之后**下一次读**：由「**同步**增量刷（必然是新数据）」改成
  「**派后台刷新 + 最多等 `SETTLE_WAIT`(0.25s)**，到点如实返回现有索引」。
  - 为什么：前者正是「每次打开书库都慢」的根因（NAS 上整目录 stat 挂在请求上）。
  - 代价：**可能短暂显示稍旧数据**；可见性改由前端轮询补（`scanning` + `scan-state`，扫完自动重取）。
  - 想「一刻不等」：把 `catalog.SETTLE_WAIT` 置 0，**但必须同时**把「写后立刻读」那批用例改成轮询语义。
  - 既有测试 `tests/test_catalog.py::test_标脏后的读会看到新书` 已按此**改写并说明理由**。
- **显式扫描路径一律保持同步**（`refresh_library(force=True)` / `POST /api/libraries/{lid}/scan` /
  watcher 扫描）—— 这条是硬约束，不许动。

### 五、C 批：分页 + 无限滚动

- **后端**：`GET /api/books` 加可选 `limit` / `offset`（按**字符串**收再自己解析 —— 声明成 `int`
  会被 FastAPI 用 422 拒掉，而契约要 400 中文 detail）：**不传 `limit` ⇒ 与旧行为逐项一致（全量）**；
  追加 `limit`/`offset`/`has_more` 三个字段（只加不改）；`total` 恒为**未切片前**的总数；
  切片在**排序之后**；`limit=0` = 不限；负数/非数字 ⇒ 400；`offset` 越界 ⇒ `items=[]` + 真实 `total` + `has_more=false`。
  ⚠️ 注释已如实写明边界：**这是 Python 侧切片，省的是响应体积 + 前端渲染，不是 DB 读**。
- **前端**：书库页专属分页源 + 底部哨兵（IntersectionObserver，卸载 disconnect）+ 可点「加载更多」
  + 「已显示 N / 共 M」+ 「筛选没命中但还有更多」的**诚实分支**（自动续拉上限 5 页，到顶改按钮，
  绝不显示「没有符合条件的书」）。页大小 **120** 单点常量。
- ⚠️ **中途挡下的回归**：初版把分页状态**直接建在共享的 `books` 数组**上 ⇒ `books` 只装首页（120 条）⇒
  **侧栏计数、仪表盘四个部件、浏览页、智能书架计数全部只见前缀**（600 本的库显示成 120），
  而**没有任何既有 spec 覆盖，所以全绿**。
  修法：`loadBooks()` 回到全量（`api.books()` 不传参，注释写明「别在这里加 limit」）；
  新增 `shelfLoadedBooks` + `loadShelfFirstPage` / `loadMoreShelfBooks` / `autoLoadMoreShelf` / `resetShelfQuery`，
  **只有 `ShelfView` 读它们**；`patchProgress` **双数组回写**；数据变更后统一 `refreshBooks()`。

### 六、事故与死代码

- ⚠️ **「子代理被取消」≠「已停止」**：第一次派的后端子代理因 idle 超时被取消，但进程继续跑，
  并与随后派的第二个后端代理**并发编辑同一工作区**（文件在未调用工具时仍在变）。
  纪律：取消后先 `git status` + 看 mtime 确认工作区静止；**一个工作区同一时间只派一个会写代码的子代理**；
  给子代理的规格必须写明「不许改既有测试，冲突则停下报告」；提交前先清仓库根临时产物。
- **死代码删除**：`catalog.invalidate_and_refresh` 试过接线（`library.invalidate()` 标脏后点火），
  实测打红 4 条既有用例（含两条与契约无关的顺序用例）⇒ 属 flaky 来源，**撤回接线 + 删除函数**，
  注释写明为何退回；点火点收敛为三处：读路径 / 启动预热 / 监听线程。

### 七、踩坑 / 工具

- ⚠️ **长跑 pytest 必须后台跑**：前台会被 harness 的「长时间无输出」上限取消；
  用 `Start-Process -FilePath python -ArgumentList '-m','pytest','--junitxml',…` 后台跑 + 轮询 junit
  （轮询时每 15s 打一行，否则轮询命令自己也会被判静默超时）。
- `Remove-Item` 会被 IDE 的 **Safe-Delete shim** 拦住 ⇒ 清理临时产物时别先删、让 pytest 直接覆盖
  （`--junitxml` 会覆写）。

### 八、收尾

- 后端全量 `pytest`（离线）：**1624 例 / 0 failed / 0 errors / 12 skipped**（第 88 期 C 批后；
  起点 1605）。前端 `type-check` ✓ / `test:unit` **550 例** ✓ / `build` ✓ / `deploy` ✓。
- 版本 `VERSION` 0.87.0 → **0.88.0**，同批补 `CHANGELOG.md` 段；推送 `main` 后 CI 自动打 tag 并建 Release。

---

## 第 89 期 · TXT 上传假报错 + 正文不乱码（V0.89.0，2026-10-03）

**来源**：用户上传本地 TXT 后出现格式显示问题，要求「**读取与展示 TXT 时保持原始格式、不做转换，原样展示**」；
截图报错 `美利坚财富人生1-3059.txt: Unexpected token '�', "����������... is not valid JSON`。
**用户确认的口径**：① 报错**在上传时就弹**，但**等一会书会自动进库**（⇒ 上传其实成功了）；
② 「原样」的粒度 = **只要正文文字不被动**（空行折叠可接受），即 **字符不错、不乱码**，
**不是**保留空白/空行/行尾 ⇒ 不需要 `pre-wrap`；③ 那些 TXT 的编码 **GBK / Big5 / UTF-8 / UTF-16 等都可能**。

### 一、根因（带行号）

1. **报错文本骗人（唯一必改点）**：`BookDock` 的「上传」→ `deliverToDock` → `api.convertDrop`
   用的是 **`request()`（JSON）**；而 `POST /convert` 返回的是 **`FileResponse` 文件流** ⇒
   `await res.json()` 把文件字节按 UTF-8 解出 `�`，V8 于是抛 `Unexpected token '�'`。
   **书照常入库**（写盘 + `pipeline.dispatch` 原样复制），所以「等一会自己出现」。
   ⚠️ 对照：`LocalConvertView` 走 `convertFile` → `requestBlob`（`res.blob()`），**不会**报这个错。
2. **「字符不错」当时做不到**：解码只在**读取时**做，唯一探测实现是 `pipeline._detect_encoding`：
   先判「UTF-8 前缀是否合法」，否则在 **`gb18030` / `big5hkscs` / `big5`** 里按字符分布打分择优
   ⇒ **没有 UTF-16 / BOM 分支**（UTF-16LE 的 `FF FE` 不是合法 UTF-8 ⇒ 落到 gb18030 打分 ⇒ 整篇乱码）。
   更糟的是解码用 **`errors="ignore"`** ⇒ **静默丢弃**解不出的字节，而这些字节被丢后的文本会写进
   **派生 EPUB** 与章节缓存 ⇒ 读者看到的派生物**有洞且不报错**。
3. **展示层确实会重排**（用户已接受）：`preprocess.paragraphs_to_html` 逐行 `strip()` 且丢空行、
   每行包 `<p>`，会重新分章并插入标题 `<h2>` ⇒ 空行/缩进/行尾不保留。**按用户口径这批不改**。

### 二、交付

- **上传假报错**：`api.ts` 新增 **`requestAck()`**（与 `request()` 同一套鉴权/超时/401/错误剥壳，
  但**不解析响应体**并 `res.body?.cancel()`），`convertDrop` 改用它（注释写明「不能走 `request()`」）。
  顺带普查：全仓「返回文件流/非 JSON 的接口」前端调用点里，**只有 `convertDrop` 这一处坏点**。
- **解码不再丢字节**：`ENCODING_RULE_VERSION` **1 → 2**（`pipeline.py`，`txtcache.ENC_RULE_VERSION` 跟随
  ⇒ 存量派生件自动重建）；新增 `_choose_encoding()`（**确定性证据优先**：UTF-32/UTF-8/UTF-16 BOM →
  无 BOM 像 UTF-16 → UTF-8 前缀自证 → gb18030/big5hkscs/big5 打分）+ `decode_file()`
  （候选**逐个严格试解**，坏字节以 U+FFFD 顶替并**计数/记偏移**，返回 `{encoding, undecodable, positions}`）；
  `txtcache.decode_info()` + 派生件 `state.json` 增 `encoding`/`undecodable`；章节接口**新增** `text_encoding`
  字段（只加不改）；阅读器在 `undecodable > 0` 时显示一行低调提示。
- **测试**：新增 `tests/test_txt_encoding_bytes.py` 11 例（**修前 BOM/UTF-16 那几条是红的**）
  + `frontend/src/lib/convertUpload.spec.ts` 5 例（已登记 `EXPECTED_SPECS`）。
- **实测**：后端全量 **1635 例 / 0 failed / 0 errors / 12 skipped**；前端 `type-check` ✓ /
  `test:unit` **555 例** ✓ / `build` ✓ / `deploy` ✓。

### 三、诚实的边界

- `LocalConvertView.vue` 在「不许碰 `views/tools/`」的约束下未改（它走 blob 路径，不受本次假报错影响）。
- **无 BOM 的纯中文 UTF-16 仍不可判**（两个字节都不为 0，与随机字节无从区分）—— 已在注释与报告里如实写明，
  交给启发式并上报。
- 前端提示目前只在「有坏字节」时显示（若想总是显示所用编码，是一行改动）。

---

## 第 90 期 · 窄屏外壳侧栏对齐上游（抽屉 / 图标条 / 拖宽 / ⌘B）（V0.90.0，2026-10-03）

**需求来源**：第 86 / 87 期尾巴的实测（原 TODO 第 3 节 `ui-narrow-shell`）—— 360 档侧栏仍死占 240px，
主内容只剩百来像素、文字被挤成一字一行；`ui-smoke` 实测 `#/shelf` `off=27`、`#/tools/sources` `off=38`。
**用户确认的四条口径**：① **完整对齐上游**（窄屏抽屉 + 桌面折叠成图标条 + 拖宽 + ⌘/Ctrl+B + 边缘 Rail，
基础组件按上游补齐）；② **内部业务标记一并改写**成上游的 `SidebarMenu*` / `SidebarGroup*` 体系；
③ 断点 **≤640px**（用本仓既有的 `639.98px`，**不跟**上游的 768px —— 640–767 要继续两栏）；
④ 引入 `reka-ui` / `@vueuse/core` / `class-variance-authority` / `@lucide/vue` 四个依赖，**不引** `vue-i18n`（中文写死当字面量）。

**验收判据（用户定的）**：`ui-smoke` 在 **360 档** `off` → 0（`ovf=false` 是假象 —— 溢出被内部横滚容器吸收，**只看 `off`**）。

### 一、交付（八件事）

1. **≤640px 抽屉**：`ui/sheet`（`reka-ui` 的 `Dialog` → 右侧滑出），宽 `18rem`、遮罩用 `--scrim`、
   Esc / 点遮罩 / 点导航项都能关、关掉焦点回到触发器、内容占满整宽。
2. **桌面折叠成图标条**：`3rem`，只留图标 + 悬停 tooltip（`ui/tooltip`）。
   ⚠️ 图标条宽度的类（`data-[collapsible=icon]:w-(--sidebar-width-icon)`）必须挂在 **group 元素**上 ——
   它只匹配**自身**，挂到内层卡片上折叠不报错、只是「中间一小撮图标、两边一大片空白」。
3. **拖宽**：`224–480`，默认 **240px**（本仓既有的 `w-[15rem]`，**不跟**上游的 256 —— 跟了就是宽屏用户的视觉回归）；
   存**本机**（`nf_sidebar_width`，120ms 防抖 + 卸载补写一次）。
4. **边缘 Rail**：`3px` 阈值把两种手势分开 —— 松手时位移 <3px 算「点击开合」，≥3px 算「拖拽调宽」。
   ⚠️ 阈值**只决定松手算哪种**，不拦宽度（位移多少宽度就跟多少，否则手感是「先纹丝不动、过了 3px 突然一跳」）；
   折叠态**不认**拖拽手势（48px 宽的条上拖动看不见结果），松手退化成点击 ⇒ 先展开。
5. **⌘/Ctrl+B** 开合（窄屏开的是抽屉），与 `⌘K`（全局搜索）各管各的键 —— 写成「有 meta/ctrl 就开合」会让 ⌘K **同时**弹搜索并收侧栏。
6. **内容自适应**：`--sidebar-width` / `--sidebar-width-icon` 两根变量由 `SidebarProvider` 挂在外壳根节点上，侧栏与内容区同一帧一起动。
7. **`SettingsSidebar` 走同一套**（设置路由下同样是抽屉 / 图标条 / 拖宽）。
8. **桌面视觉不回归**：宽屏展开态仍是 240px 卡片、圆角 / 间距 / 阴影不变（默认宽度与首个按钮尺寸都逐字保持）。

### 二、单一真值源（本期收敛了四处）

| 判据 | 唯一实现 | 删掉的第二份 |
|---|---|---|
| 窄屏断点 | `lib/viewport.ts` 的 `NARROW_QUERY`（`(max-width: 639.98px)`） | `lib/shelfRows.ts` 里那份私有常量 |
| 折叠态 / 宽度 | `ui/sidebar/SidebarProvider.vue`（`useSidebar()`） | `stores/ui.ts` 的 `sidebarCollapsed` / `toggleSidebar`（**已删**） |
| 类名合并 `cn()` | `lib/utils.ts`（`clsx` + `tailwind-merge`） | 组件里各写一遍（移植来的 shadcn 组件靠「传 class 覆盖基础类」，只 `clsx` 会时灵时不灵） |
| 侧栏宽度字面量 | 只有 `useSidebarWidth.ts` 的 `SIDEBAR_WIDTH_DEFAULT_PX = 240` | 上游的 `SIDEBAR_WIDTH = '16rem'` **故意不搬**（留一个没人读的字面量就会在「默认 240 还是 256」上留下第二份答案） |

⚠️ **侧栏偏好刻意不进 `server.PREFS_BLOCKS`**：宽度与折叠是**屏幕**属性、不是人的偏好 ——
同一账号在 27 寸上拖到 420px、在平板上就该是抽屉，跟着账号同步等于把大屏宽度硬塞给小屏。
故 `lib/sidebarPrefs.ts` 走 localStorage（键 `nf_sidebar_*`，`nf_` 前缀防同域与上游撞键）。

### 三、测试

- 新增 3 个 spec（均已登记 `tests/test_frontend_unit_contract.py` 的 `EXPECTED_SPECS`）：
  `lib/viewport.spec.ts`（6）、`ui/sidebar/sidebar.spec.ts`（21）、`ui/sheet/sheet.spec.ts`（8）。
  三条都盯**静默失效**：折叠宽度的类挂错元素、折叠态/宽度没落本机存储、3px 阈值写反、
  抽屉没 Teleport 到 body（被外壳 `backdrop-blur` 裁掉）、Esc / 遮罩关不掉、遮罩拿 `--foreground` 调（深色下是浅雾）。
- 契约新增 2 条：`stores/ui.ts` 不许再长出 `sidebarCollapsed` / `toggleSidebar`；
  `PAYLOAD_BLOCKS` 里不许出现侧栏块 + `sidebarPrefs.ts` 必须走 localStorage 且键带 `nf_sidebar_`。
  （两条都**先剥注释再断言** —— 这两份文件的抬头正在逐字解释「为什么不放进同步块」，不剥会被自己的说明绊倒。）
- `AppSidebar.spec.ts` 三处选择器随「行从 `<div>` 换成真 `<button>`」改按 `data-sidebar="menu-button"` 找。
- 结果：后端全量 **1637 例（1625 passed / 12 skipped / 0 failed / 0 errors）**；
  前端 **57 spec / 590 例** + `type-check` / `test:unit` / `build` / `deploy` 四连全绿。

### 四、实测（实例 8993，`ui-smoke` 三档）

| 路由 | 360 | 768 | 1280 |
|---|---|---|---|
| `#/shelf` | **27 → 3** | 0 → 0 | 0 → 0 |
| `#/tools/sources` | **38 → 16** | – → 2 | 0 → 0 |

**残留归因（都不是本期引入的回归）**：

1. **顶栏图标行在 360 档本身就装不下**：右侧图标行固定 **375px**（10 个 33px 圆钮），
   而 360 档顶栏内容盒只有 **334px**（`360 − 2×12` 边距）⇒ 最右三个（外观 / 设置 / 头像）被外壳
   `overflow-x: clip` 静默裁掉。**本期只是把顶栏第一个按钮从自绘按钮换成 `SidebarTrigger`，尺寸逐字未变（32×32）**
   —— 已用 `git show HEAD:frontend/src/components/AppHeader.vue` 逐行核对过，该行宽度与裁切位置与改前一致。
   另外宽屏 1280 档 `off=0`，桌面无回归。
2. **`#/tools/sources` 的残留主要是工具页自己的 `min-w-[32rem]`**（第 86 期「可用但不优雅」的口径）：
   书源表单面板实测 **454px** 宽、标签条 4 项在横滚容器里（`scrollBoxes=2`，可横滑到达）；
   768 档那 2 个 `off` 也是横滚标签条内的项（可达）。

⇒ 验收判据「360 档 `off` → 0」**未完全达成**：侧栏那一半已修净（书库页从 27 降到 3，那 3 个全在顶栏），
剩下的两处（顶栏图标行、工具页 32rem）都属**独立的交互决策**，已如实记进 `docs/TODO.md` 第 3 节。

### 五、踩坑（都写进了对应文件的注释）

- **`data-slot` 会被 tooltip 触发器顶掉**：`SidebarMenuButton` 带 tooltip 时行被塞进 `TooltipTrigger as-child`，
  触发器的 `data-slot="tooltip-trigger"` 覆盖了行上同名的属性（上游同样如此）⇒ 取行认 `data-sidebar="menu-button"`。
- **`reka-ui` 的两处异步**（写 spec 时最容易误判成「功能坏了」）：点击外部的 `pointerdown` 监听器要等
  `watchEffect`（微任务）**再排一个 `setTimeout(0)`** 才挂到 document 上；卸载还要多等一拍（`usePresence` 里有一次 `await nextTick()`）
  ⇒ `sheet.spec.ts` 用三轮 `settle()`（宏任务 + 双 `nextTick`）。
- **`reka` 不写 `aria-modal`**：「模态」靠 `useHideOthers` 把 body 下其余子树标 `aria-hidden` ⇒ 断言要认这个，别认 `aria-modal`。
- **happy-dom 的 `matchMedia` 不跟着窗口尺寸触发 `change`** ⇒ 两份 spec 各自装了可控桩
  （「跟随变化」正是最该测的一条，用真实现反而测不到）。
- **`ui-smoke` 传数组要一次一条路由**：`-Routes '#/a','#/b'` 经 `.cmd` 转发后逗号被吃成一个元素，
  变出一条 `#/a,#/b` 的假路由（度量到的是 404 页）；git-bash 下还要防 MSYS 把 `#/…` 改写成 Windows 路径。

## 第 91 期 · TODO 清理 + 待办收口 + 往期尾巴结清（V0.91.0，2026-10-03）

**需求来源**：用户原话「**todo中已完成的内容删除或迁移到当日日志，完成todo中剩下的任务**」，
追加「**往期任务，若未完成也加到计划里**」（附第 86 / 88 期尾巴清单）。
病灶：`docs/TODO.md` 276 行里 **176 行是「已完成」的逐期详情** —— 这些内容在 roadmap / CHANGELOG / memory 里
都有完整记录，在 TODO 里再抄一遍只会让「**当前还剩什么要做**」淹没在历史里。

**用户拍板的五条口径**：① 第 91 期范围 = 文档三件 + 未登录 401 探测归零 + 元数据来源权重 + 真机核对番茄/起点目录规则；
② 窄屏顶栏图标行 → **收进「更多」菜单**（高频几个留在外面，顶栏不变高）；③ 跨语言检索词 → **保持「未支持」**、口径写死；
④ 第 86 期⑦ `online-fallback` → **独立立项**，本期只写口径、**不动代码**；⑤ 第 86 期⑧⑨ + 第 88 期 D 尾巴 → **本期一并收掉**，
`LocalConvertView` 改成「**投递 + 提示 + 刷新**」。

**开工前核对**：先用 `git log --oneline -12` 确认第 91 期未被并行会话占用（第 84 期被占过一次）。
用户清单里被当成「未完成」的 6 项经逐条核对**其实已完成**（第 90 期那 7 笔提交 + `v0.90.0` tag + Release），**不重复排期**。

### 一、交付（十件事）

1. **TODO.md 从「流水账」改成「待办台账」**：删掉 P0 整个第 81 期块（内容在 roadmap 第 81 期 + CHANGELOG）；
   把 `## 2. 已完成（近三期）` 的 **14 个期块 / 117 行**压成一张**交付索引表**（期号 | 一句话 | 版本/指针 —— 细节**删除不迁移**，
   roadmap + CHANGELOG + memory 已是完整真值源）；改写维护约定为「本文件只放**还没做的**」。
   **两处例外必须留下**：① 第 81 期的**用户侧遗留动作**（线上点一次「全部按原路径还原」把 ~2400 份 / 68 GB 漫画搬回）
   → 独立成「⚠️ 待用户确认」；② 「移除书库」零文件触碰 / 「删书」回收三份的**仍然生效的语义** → 已在 `AGENTS.md` 第 1 节，留一句指针。
2. **roadmap 补第 62–65 期**（本仓此前独缺这四期）：按 84 笔提交逐笔读 `git show --stat` + 提交正文复原四段，
   插在 `## 第 66 期` 之前；**材料不足处如实写「按提交正文与代码复原」，不编数字**。
3. **`docs/` 与 `README.md` 去重**：修 `docs/project-overview.md` §7 的过期数字（版本 0.6.0 / 后端 1263 例 / 前端 441 例 38 文件 / 第 73 期），
   并**改成指向真值源**的写法（版本 → `VERSION`，计数 → 测试基线，逐期 → roadmap），避免下期又过期；
   同步 `docs/development.md` 文档维护表里 `docs/TODO.md` 那一行的新口径。
4. **未登录 401 探测归零**（`App.vue`）：`showLogin = ref(!auth.authenticated)`（同步读 localStorage，零延迟）+
   抽 `bootstrapShell()` + **`@authed` 回调同批复跑** —— 见下面「防回归」第 1 条。
5. **元数据「自定义来源权重」**：配置键 `metadata_fetch.source_weights`（`dict[str,int]`，默认 `{}`），
   `metasources.weight_of()` 做**唯一归一**（缺省 / 非法 / 负数 / 未知 id 一律 → 0），`reorder_for_language(weights=…)`
   排序键 `(-weight, language_tier(...))`；三个调用点同批传参（`metafetch.py` 两处 + `series_meta.py` 一处）；
   设置页每家提供商行内加 0–9 权重框（带 `aria-label`），文案说清「权重高的永远在前，权重相同才比语种档、再比你设的顺序」。
6. **窄屏顶栏「更多」菜单**（新建 `AppMoreMenu.vue`，**复用既有 `ui/DropdownMenu.vue`**，零新依赖）：
   **留在外面**（高频）= `SidebarTrigger` / 搜索框 / 同步状态胶囊 / `NotificationBell` / `AppearanceMenu` / `UserMenu`；
   **进「更多」**= 数据统计 / 任务 / 工具 / 阅读记录 / 阅读活动 / 成就 / 设置 —— 这 **7 项是唯一入口**（第 65 期已从侧栏撤掉），
   **不能隐藏，只是换地方**。判据用 `useNarrowScreen()`（`lib/viewport.ts` 的 `639.98px`，全站唯一真值源），
   `v-if`/`v-else` 切换而**不是纯 CSS 隐藏**（面板 `Teleport` 到 body，CSS 藏不住，且会变成两份断点）；窄屏同时收掉搜索框的 `⌘K` 徽标。
7. **`LocalConvertView` 改走 ack 链路**：原先 `api.convertFile` / `api.convertPath`（blob 变体）转完把成品 `saveBlob()` **推回浏览器**，
   而收书目录页走 `convertDrop`（`requestAck`）—— 同一服务端动作、两种客户端语义，页面文案「逐个入库并下载」正是这种怪异。
   改为复刻 `BookDockPage.vue` 那条链路：**投递 → toast → `refreshInputs()`**；为 `/convert-path` 补对称的 `convertPathDrop`，
   **彻底删** `convertFile` / `convertPath` 两个 blob 变体（删前再 grep 全仓确认零残留引用）。
8. **番茄 / 起点目录规则真机核对结论落库**（只改注释 / `note` / `state_note()`，**不动 `verified` 与 `status`**）。
9. **浮层菜单键盘可达性**（本期新发现的**真缺陷**，见下面「三、实测」第 5 条）：`ui/DropdownMenu.vue` 补键盘支持。
10. **`online-fallback` 独立立项 + `美利坚财富人生1-3059.txt` 待样本登记**（都只落 TODO 条目，**本期不动代码**）。

### 二、单一真值源

| 判据 | 唯一实现 | 本期动作 |
|---|---|---|
| 窄屏断点 | `lib/viewport.ts` 的 `NARROW_QUERY` | 「更多」菜单**不另写断点**，直接 `useNarrowScreen()` |
| 来源排序 | `metasources.reorder_for_language()` | 加可选 `weights` 参数，**没有第二份排序实现**；归一只有 `weight_of()` 一处 |
| 权重配置读取 | `metasources.weight_of()` | 三个调用点不各写一份「转 int / 兜底 0」 |
| 浮层菜单 | `ui/DropdownMenu.vue` | 键盘契约写在**共享组件**里 ⇒ 书卡 ⋮ 一并受益 |
| 投递链路 | `api.convertDrop` / 新增 `convertPathDrop` | 删 blob 变体，**服务端同一个动作不再有两种客户端语义** |

### 三、实测（实例 8412，全部真机）

1. **D · 未登录 401 探测归零**：清空 `localStorage` 的新访客对 `/api/*` 的 401 探测 **13 → 0**；
   有效 token → **0 个 401**，且登录后 `api.me()` / `/api/libraries` / `/api/tasks` / `/api/books` 各走**恰好一轮**；
   篡改 token → 仍有一轮探测、**15 个 401** 之后才弹门禁。
   ⚠️ **诚实边界（未做取舍，刻意不修）**：`localStorage` 里有 token 但**已失效**时，外壳仍会先挂载并发一轮探测
   —— 修它就得让**已登录用户冷启动也等一次 `api.me()`**，正是 TODO 里记的那个权衡。
   本项达成的口径是「**从未登录过的新访客 / 清过 localStorage 的访客 = 0 个 401 探测**」。
   ⚠️ **测量方法本身踩过坑**：原计划用 `performance.getEntriesByType('resource')` 数 401 —— 该 API **拿不到 HTTP 状态码**。
   改用 **uvicorn 访问日志里数 `401` 行**。另：第一次测出 13 是因为**测的是旧 bundle**（改了 `App.vue` 没跑 `build`/`deploy`）
   —— AGENTS.md 警告的那个坑，实打实撞了一次。
2. **E · 来源权重**：`{}` → `['openlibrary','googlebooks']`；`{googlebooks:9}` → `['googlebooks','openlibrary']`；
   设回 `{}` → **逐字回到基线**（依赖 `sorted` 稳定性，见「防回归」第 2 条）。界面：14 家提供商各一个权重 `number` 输入（`min=0 max=9`）。
3. **F · 番茄 / 起点**（经本机代理，`/api/toc/probe` 复核）：

   | 站点 | 探测 | 结果 |
   |---|---|---|
   | 番茄 | 首页 | 200 / 164 KB |
   | 番茄 | `/search?query=` | **404**（9813 B，`undefined_番茄小说`）⇒ **搜索规则失效** |
   | 番茄 | `/page/<书号>` | **200 / 1.65 MB，匿名 SSR**，正文含 `<a href="/reader/<id>" class="chapter-item-title">` ⇒ **内置目录正则逐字命中**（实测一本 **550 章**全部解析） |
   | 起点 | `/so/{title}.html` 与 `/book/<id>/` | **202 + 209 B `probe.js`**（反爬 JS 挑战）⇒ **两条规则都用不了** |

   番茄是「**哪一半能用**」说不清，单一布尔 `verified` 表达不了 ⇒ **两条都保守留 `False`**，把实测结论写进 `note`。
4. **G · 窄屏顶栏**：360 档顶栏 = `["打开侧边栏","通知","更多","外观","账户菜单"]`，「更多」面板**恰好 7 项**、
   逐个点开都能跳转且面板自动收起；768 / 1280 档仍是 11 个控件的图标行、**无**「更多」、`⌘K` 徽标在。
5. **I · 键盘 Tab 实测 —— 查出并修掉一个真缺陷**：`ui/DropdownMenu.vue` **原先完全没有键盘支持**。
   面板为躲裁切 `Teleport` 到 `<body>` 末尾，代价是 **Tab 序排在整个页面之后**（键盘用户够不着），`Esc` 也**无人监听**。
   第 64 期这不算致命（⋮ 只是书卡快捷项），第 91 期把 **7 个入口（含「设置」）只**放进窄屏「更多」之后，它就是硬缺陷：
   **窄屏键盘用户进不去设置**。修法：打开即入焦第一项、`↑`/`↓` 循环移动、`Esc` 关闭并把焦点**还给触发器**、
   `Tab` 也关闭（`preventDefault` —— 否则焦点会走到浏览器 chrome）。真机全键盘走通：`Enter` 展开 → 下键 ×6 → `Enter` 进设置。
6. **冒烟（第 88 期 D 尾巴）**：12 组（4 个页面 × 360 / 768 / 1280）→ 越界元素 `off=0`、页面横向溢出 `ovf=0`、
   「被裁掉且滚不到」`clippedUnreachable=0`。⚠️ 用**两层判据**：先排除 `overflow-x: auto|scroll|hidden|clip` 祖先内的元素，
   再做更严的 `clippedUnreachable` 复核 —— 第 90 期那个顶栏缺陷正是被 `overflow-x: clip` 吃掉的，
   宽松判据会把它归成「可达」而漏掉。
7. **J · 本地导入**：`window.__dl = []`（**没有** `createObjectURL`、**没有** `<a download>`）、toast 有提示、
   `GET /api/files` 刷新后书目 **3 → 4**。
8. **文档**：`tests/check_doc_anchors.py --strict` → 20 文档 / 836 锚点 / **硬错 0**。

### 四、防回归要点

1. **D 的 `@authed` 必须重启外壳数据加载** —— 漏了不报错，只是登录后任务栏永远空着、书库永远不加载。静态契约钉住。
2. **E 的「权重全空 = 现状逐字一致」**：靠 Python `sorted` 的**稳定性**保档内顺序，写成用例，**别改成会打乱档内顺序的写法**。
3. **E 的新键三处同步点**：`config.DEFAULTS` ↔ `server.EDITABLE["metadata_fetch"]` ↔ `server._mask_metadata_fetch`；
   漏 `DEFAULTS` 会让「恢复默认」丢键。
4. **G 的七个入口一个都不能少**：这是它们**唯一**入口，`v-if` 写错就变成「窄屏没法进设置 / 任务」。
5. **F 只改注释与 `note`，不动 `verified` 布尔与 `status`** ⇒ 三条既有 toc 契约**预期零改动**（改红了说明口径跑偏）。
6. **J 删的是公开 api 方法**：删前再 grep 一次全仓（含 `*.spec.ts` 的 mock）确认零残留。
7. **A 是删文档**：`tests/check_doc_anchors.py` 扫 `docs/**`，**不动它历史记录里的旧行号**；
   全仓唯一的 `TODO.md:NN` 锚点在 `.codebuddy/memory/2026-10-03.md`，而该检查器**不扫 `.codebuddy/`** —— 顺手改成不依赖行号的引用。
8. **口径**：不加 `Math.random()` 演示数据；不新建 compose 文件；**不新增任何依赖**（G 复用 `DropdownMenu`，J 复用 `convertDrop`）。

### 五、测试

- 后端全量 **1652 例（1640 passed / 12 skipped / 0 failed / 0 errors）**，基线 1637 ⇒ **+15**。
  新增：`tests/test_unauth_probe_contract.py`（D 的静态契约）、`tests/test_metafetch_language_order.py` 扩 143 行（E 的权重四项）、
  `tests/test_toc_sources.py` 补「`note` 里不许写 markdown」。
- 前端 **60 spec / 615 例**（基线 59 / 609），`type-check` / `test:unit` / `build` / `deploy` 四连全绿。
  新增 3 个 spec 并全部登记 `EXPECTED_SPECS`：`AppMoreMenu.spec.ts`、`LocalConvertView.spec.ts`、`ui/DropdownMenu.spec.ts`。
- `tests/test_changelog_render.py` 5 例全绿（`VERSION` 0.90.0 → **0.91.0** 与 `CHANGELOG.md` `V0.91.0` 段同批）。

### 六、踩坑

- **`performance.getEntriesByType('resource')` 拿不到状态码** ⇒ 数 401 只能读访问日志（见「三、实测」第 1 条）。
- **改了前端不 deploy = 测旧 bundle**：第一次 401 计数 13 全是假象（`build` 只落 `frontend/dist`，`deploy` 才同步 `static/v2`）。
- **`window[m]('keydown', fn)` 过不了 `tsc`**：`m` 是字符串联合，推不出 `keydown` 那一重的 `KeyboardEvent` 重载
  ⇒ 拆成显式 `if (on) addEventListener(...) else removeEventListener(...)`。
- **happy-dom 下浮层 spec 必须 `attachTo: document.body`**：焦点断言（`document.activeElement`）在游离 DOM 上恒为空。
- **spec 里的 `press()` 不 await 一拍会假红**：面板还挂在 DOM 上 ⇒ 改成 async 并 await `$nextTick()`。
- **`Tab` 的语义是「关闭 + 焦点还给触发器」**（不是「留在菜单项上」）：先按「留在项上」写，测出来焦点跑到触发器，
  复核后确认**这是对的**（面板在 body 末尾，原生 Tab 会走出页面）⇒ 改的是断言，不是实现。
- **`POST /api/libraries` 用内联 `-d` 带中文必炸**（`There was an error parsing the body`）⇒ 写文件 + `--data-binary @f` + `charset=utf-8`。
- **`/api/metadata/plan` 的 `items=0`**：`names` 缺 `.txt` 后缀 + `metadata_fetch.enabled` 为假时 `plan()` 提前返回，两处都要满足。
- **`/api/books` 的键是 `items` 不是 `books`**（提取脚本写了 `d.get('books')` ⇒ 拿到空 bid，白跑一轮）。
- **`/tools/convert` 是 404 路由**（真路由是 `/tools/local`）：拿它做的冒烟测量无效，重测。
- **`json.load(sys.stdin)` 按 cp936 解码** ⇒ 中文变乱码 + 产生 `\udcXX` 孤立代理，写文件时 `UnicodeEncodeError`；
  先 `sys.stdin.reconfigure(encoding='utf-8')` 再用。
- **`nohup … &` 后台跑 pytest 中途死掉却报 exit 0**（日志只到 8%）⇒ 长跑改前台 + 足够超时。
- **`note` 是纯文本插值**：`SourceToolsView.vue` / `TocSourceCard.vue` 用 `{{ … }}` 渲染，
  写注释时顺手用的 `**…**` 会**原样**显示到界面上（第 91 期真的这么踩了一次）⇒ 补契约用例钉住「`note` 里不许有 markdown」。

### 七、未做取舍

- **D 的失效 token 场景**：仍有一轮 401 探测（15 个），**刻意不修**（理由见「三、实测」第 1 条），已记进 `docs/TODO.md`。
- **`online-fallback`**：**独立立项**，本期只写口径。触发条件 = 本地读不了（未下载 / 格式不支持 / 文件缺失损坏）；
  入口 = 书卡与详情页的「检查更新」/「在线读」；共享按源登录态必须走 `DownloadManager.gate_reason()` 这**唯一**闸门，不得绕开；
  ⚠️ **需要用户先拍板的合规边界**：应用内渲染第三方页面必须**如实标注「这是源站在线页面」**，
  **不得**让产品看起来像在托管正文，只接公版 / 授权源。为什么不在第 91 期做：范围与合规风险都不小，混进来会把本期拉长。
- **跨语言检索词**：**保持「未支持」**。理由写死在设置页：① 翻译质量不可控、会把「同名不同书」的误配率推高；
  ② 各源语言内检索语义不同；③ 已有「按语种重排 + 手动指定来源」两条退路。并登记进 TODO 的「**明确不做**」区，避免反复立项。
- **美利坚财富人生那本 TXT**：第 89 期已上线 `ENCODING_RULE_VERSION=2`（BOM 优先 + 坏字节不静默丢并计数）。
  下一步**取决于用户**：重开仍乱码就需要该文件（或前几十 KB 字节）按字节定位 —— 可能是编码不在现有候选内
  （如无 BOM 的纯中文 UTF-16，属不可判）。本期只作为「待用户输入」登记，**不预估、不改探测策略**。

## 第 92 期 · 工具页窄屏重排（V0.92.0，2026-10-03）

**需求来源**：用户「**继续做todo里未完成的任务**」，范围经确认锁定为 `docs/TODO.md` §1 的 P0 第二条
「**工具页自身的 `min-w-[32rem]`**」—— 第 86 期留下的 `#/tools/sources` 360 档 `off=16`，
当时的口径是「可用但不优雅」，要变优雅就得重排工具页布局。

**开工前实测（第 92 期基线，实例 8412，`.codebuddy/tools/ui-smoke.ps1` 的**原始** `off`）**：

| 路由 | 360 改前 | 360 改后 | 768 改前 | 768 改后 | 1280 改前/改后 |
|---|---|---|---|---|---|
| `#/tools/sources` | 13 | **0** | 2 | **0** | 0 / 0 |
| `#/tools/source-tools` | 13 | **0** | 2 | **0** | 0 / 0 |
| `#/tools/local` | 10 | **0** | 2 | **0** | 0 / 0 |
| `#/tools/entities` / `logs` | 7 / 7 | **0 / 0** | 2 / 2 | **0 / 0** | 0 / 0 |
| `#/tools/duplicates` / `missing` | 5 / 5 | **0 / 0** | 2 / 2 | **0 / 0** | 0 / 0 |
| `#/tools/output` | 4 | **0** | 2 | **0** | 0 / 0 |

`ovf` 三档全程 `false`、`scrollBoxes` 由 **2 → 0**（日志页保留 1，见「未做取舍」）。
基线实例有真实书目 **4 本**（用户提供），不是空库。

### 一、根因（两条都在**外壳自身**，不是哪个工具视图写错了）

1. **内容区 `min-w-[32rem]`（`ToolsLayout.vue`）**：外层 `overflow-x-auto` + 内层 512px 下限。
   360 档内容盒只有 ~336px ⇒ **184px 常驻在视口外**，用户得横向滚才看得到表单按钮与卡片右半
   （实测 `#/tools/sources` 360 档 `off=13`，`offSample` 之外的多数来自这一层）。
2. **标签条自身的 `overflow-x-auto`**：8 个标签（4 字 × `px-3` + `text-sm`）合计约 **672px**；
   768 档侧栏展开 240，内容盒只剩 ~492px ⇒ 尾部两项被滚出视口 —— 这正是第 90 期记的
   「768 档那 2 个 `off` 也是横滚标签条内的项」（`roadmap` 第 90 期实测表）。

**两条判据上的关键事实（决定了修法，也是这期最容易想错的地方）**：

- `ui-smoke.ps1` 的 `off` 是**原始** `getBoundingClientRect()` 与视口的比较，**不做祖先过滤** ——
  「在滚动容器里但滚出了视口」与「被 `overflow:hidden` 裁掉」**等价计入**。
  ⇒ 只要还留着横滚容器，`off` 就降不下来；「反正能横滑到」不能算达标。
- `ovf` 全程 `false`：横滚容器把溢出**吸收**了，页面本身不溢出。
  ⇒ 这个缺陷**永远不会自己暴露**（不报错、不加日志、测试全绿），只有真按 360 档量一次才看得见。
- **第 86 期加 `min-w-[32rem]` 的立论已经过期**：当时是「360 档外壳仍常驻 240px 侧栏、
  内容盒只剩 82px，中文被压成一字一行」。第 90 期起窄屏侧栏改成了抽屉（`ui/sidebar`），
  那个 82px 场景**已不存在** ⇒ 这个兜底只剩「内容比视口宽」这一个效果。

### 二、交付（五件事）

1. **内容区去掉宽度下限与横滚**（`ToolsLayout.vue`）：删外层 `overflow-x-auto` 与内层 `min-w-[32rem]`，
   内容跟着视口自适应；同时删掉会让残余溢出**暴露成 `ovf`** —— 比藏在滚动容器里诚实。
2. **标签条改成换行**（`ToolsLayout.vue`）：`overflow-x-auto` + `snap-x` → `flex-wrap`；
   `h-11` → `min-h-11`（按钮改 `py-3`，单行时仍是 44px，与改前逐字等高）。
   **不选固定断点是刻意的**：标签条要 ~672px，而侧栏宽度**用户可拖（224–480）**，
   「到某档换控件」算不准还剩多少位置；`flex-wrap` 没有魔数，任何宽度都不会溢出，
   且在装得下时**完全惰性**（≥1024 渲染与改前一致）。
3. **窄屏（<640px）把标签条换成原生下拉**（`ToolsLayout.vue` + `goByName()`）：
   与 `BrowseView.vue` 的「窄屏维度栏折叠成下拉」同一范式。为什么还要这一层：
   360 档 8 个标签换行要 **3 行 / 132px 条高**（每个 ~84px，328px 一行只放得下 3 个），
   光靠 `flex-wrap` 在手机上太占高度。
   ⚠️ 下拉是**换控件不是隐藏** —— 8 个工具页一个不少、逐个可点（第 91 期的教训是「唯一入口不许被藏掉」）。
   两态用 `sm:hidden` / `hidden sm:flex`：断点 `sm`=40rem=640px，与 `lib/viewport.ts` 的
   `NARROW_QUERY`（639.98px）同档，**不引入第二份「窄屏」定义**。
4. **`SourcesView` 窄屏收口**：`INPUT_CLS` 与粘贴用 `<textarea>` 补 `min-w-0`
   （`<input>` 的固有 min-content ≈150–180px，在 `grid-cols-2` 轨道里会撑破容器 ——
   grid item 的 `min-width:auto` 取的就是这个固有宽）；四个选择器 `grid-cols-2` → `grid-cols-1 sm:grid-cols-2`
   （360 档两列时每个只剩 ~148px，占位符全被截断）。
5. **新契约 `tests/test_tools_layout_contract.py`**（4 条）：内容区不许再出现 `min-w-[32rem]` /
   `overflow-x-auto`；标签条必须 `flex-wrap` 且不许横滚；窄屏下拉与宽屏标签条必须**同一份数据源**
   （`visibleSections` 恰好出现 2 次）且显隐只许用 `sm` 一档；`SECTIONS` 的 `routeName`
   必须都在 `router/index.ts` 里注册过、且恰好 8 条。

### 三、单一真值源

- 工具页的 8 个入口仍**只有** `ToolsLayout.vue` 的 `SECTIONS` 一份（标签条与下拉都渲染 `visibleSections`）；
  契约断言 `in visibleSections` 恰好 2 处，防「两条路各写一份列表」。
- 窄屏判据仍是 `lib/viewport.ts` 的 639.98px；本期只用了与它同档的 CSS `sm:`（40rem），
  **没有**新增 JS 断点、也没有第二份 `matchMedia`。
- 没有新依赖、没有新配置键、没有新接口 —— 纯前端布局。

### 四、实测

1. **8 个工具页 × 360 / 768 / 1280 = 24 组全部 `off=0` / `ovf=false`**（改前 360 档是 4–13）。
2. `scrollBoxes`：2 → 0；只有 `#/tools/logs` 在 360/768 保留 1（它的 46rem 数据表，见下）。
3. `act` 在 360 档下降（如 sources 39 → 32、logs 21 → 14）：标签条 8 个按钮换成了 1 个 `<select>`；
   `tabs` 字段仍是 8 是**预期**（`display:none` 的那条仍被 `querySelectorAll` 数到）。
4. **变异自检**：把 `min-w-[32rem]` / `overflow-x-auto` / `flex-wrap` 分别改回旧写法、
   把下拉层删掉，四条断言各自**都变红**（用临时副本跑的，不动仓库文件）。
5. 前端 `type-check` / `test:unit`（60 spec / 615 例）/ `build` / `deploy` 四连全绿；
   后端全量 **1656 例（1644 passed / 0 failed / 0 errors / 12 skipped）**，基线 1652 ⇒ **+4**（本期新增的 4 条契约断言）。

### 五、防回归要点

1. **`off` 是原始量、不过滤滚动容器**：以后判「窄屏有没有横向溢出」必须用它，别用「能滚到就算可达」的宽松口径。
2. **外壳不许再长出横向滚动**：工具页两条都不许 `overflow-x-auto`（契约钉住）。
   `ovf=false` 不是「没问题」的证据 —— 横滚容器会把问题吸收掉。
3. **工具页头部的显隐只许用 `sm` 一档**：混入 `md:` / `lg:` = 第二份「窄屏」定义。
4. **`<input>` / `<textarea>` 进栅格 / flex 轨道必须带 `min-w-0`**：`w-full` 单独不够，
   固有 min-content 会撑破容器（这是本期唯一一处「窄屏才暴露」的次级缺陷）。
5. **窄屏换控件 ≠ 隐藏**：下拉与标签条必须同一数据源，否则换个宽度就少几个入口，且不报错。

### 六、踩坑（都写进了对应文件的注释）

- **`re.escape(attr) + r"\b"` 永不匹配**：`role="tablist"` 的结尾是 `"`，而 `\b` 要求**词字符**边界，
  `"` 与后面的空白都不是词字符 ⇒ 断言引用的那个类永远取不到。改法：去掉 `\b`。
- **注释会绊倒自己的断言**：`ToolsLayout.vue` 的模板注释**逐字**写着「这里曾经是 `min-w-[32rem]` +
  `overflow-x-auto`」⇒ 判「不许再出现」前必须先剥 `<!--.*?-->`（同 `stores/ui.ts` 那条的取舍）。
- **`flex-wrap` 不等于「一定好看」**：它在 360 档把标签条折成 **3 行**（132px）——
  达标（`off=0`）但与「优雅」还有距离，所以才补了窄屏下拉这一层。
- **改前先量一次**：`docs/TODO.md` 记的是 `off=16`，本期实测是 **13**（数据 / bundle 不同）。
  别拿文档里的历史数字当验收基线，**开工前自己量一遍**。

### 七、未做取舍（刻意保留）

- **日志页的 46rem 宽表在窄屏仍横向滚动**（`scrollBoxes=1`）：表内只有 `th/td` 与 `Badge`，
  **没有任何交互元素** ⇒ 不计入 `off`、`ovf` 也是 false。数据表在窄屏横滚是正常形态，不做卡片化
  （`ScrapePanel` 已有 `hidden md:block` 表 + `md:hidden` 卡片二选一的先例，需要时再照做）。
- **640–1023 档标签条会折成两行**（768 档实测 5+3）：比留 2 个看不见的标签好；
  ≥1024（侧栏展开 240 时内容 ≥736 > 672）仍是**单行**，1280 验收档逐字不变。
- **`online-fallback` 仍未开工**：本期范围经用户确认只有工具页。
  形态已由用户拍板（本项目页面与环境渲染、只抓源站书籍内容），口径已写进 `docs/TODO.md` §1 P0。

## 第 93 期 · 在线阅读（接用户自己的书源）+ 章节缓存 + 跨客户端进度 + 自动下载（V0.93.0，2026-10-03 ~ 10-04）

**需求来源**：用户「继续做todo里未完成的任务」→ `docs/TODO.md` §1 P0 的最后一条（第 86 期 ⑦
`online-fallback`）；范围按用户本轮追加的四条要求重做（接「我给的书源」/ 跨客户端进度一致 /
允许落盘 / 章节缓存以便断网续读）。完整实施记录在收尾时补全，本节先记**口径变化**。

### 一、口径变化与行为变化（逐条如实记录）

1. **删掉「仅放行公版源」**（`download.public_only`，用户拍板「取消仅放行公版源的相关功能」）：
   `gate_reason()` 仍是唯一闸门，只剩 `download.enabled` 一条（外加 `toc` 用途）；
   每源的 `public` 字段**保留**但降级为纯标注（书源列表里的徽章），**不再参与任何过滤**。
   ⇒ 本工具不再区分公版 / 非公版源，后果由使用者自负。历史期段不改写。
2. **定时追更原先完全不过闸门** —— 第 71 / 80 期口径里点名的「假开关」的**第四个**调用方。
   `download.enabled` 默认 **False**，设置页也写着「关闭时书源仅做规则管理，不搜也不下」，
   而 `core/autoupdate.tick()` 枚举完 sidecar 就逐本 `manager.update_report`，**一次都不问闸门**：
   关掉下载对定时追更完全无效，它照常逐本外呼抓正文。
   现在动手之前先问 `DownloadManager.gate_reason()`，被拦就**一本都不外呼**，报告带回闸门原文
   （`blocked`、`skipped == total`），活动日志记「未执行：<闸门原文>」而不是一句假的
   「检查 N 本、新增 0 章」—— 那句与「源上真的没有新章节」一字之差都没有，而用户按
   「立即追更」唯一的疑问就是「为什么什么都没发生」。前端 toast 同样分成两句。
3. **同一笔里修掉一个此前从未被发现的漏子**：`tick()` 里写的是无参 `DownloadManager()`，
   而构造函数签名是必填的 `__init__(self, cfg: dict)` ⇒ 每轮构造必抛 `TypeError`、被 `except`
   静默吞成「构造下载器失败（本轮跳过）」—— **定时追更从来没真正跑过一本**。既有用例钉不到它
   （要么 monkeypatch 掉 `tick`、要么只测候选枚举）。改成与 `server._manager()` 同口径的
   `DownloadManager(config.load_config())`。它与第 2 条同属「追更的调度口径」，
   故合在一笔提交里（新增 `tests/test_autoupdate_gate.py` 三面钉住：拦得住 / 放得行 / 两种 0 分得开）。
4. **追更的候选枚举找错了目录**（同批修）：留档由 `manager.write_sidecar` 写在**原件旁边**，
   而下载链路把原件（txt）落在**收书目录**、把成品（epub）落在**书库根**
   （`download_to(item, out_dir, input_dir, opts)`）。第 86 期却按「书库根 + 货名去后缀」算
   ⇒ **正常部署下一本候选都找不到**（只有「收书目录恰好就是书库根」的单目录部署才碰得上，
   而第 86 期的用例正是那么造的现场，所以一直绿着）。现在收敛到 `autoupdate.sidecar_of(book)`
   一处，按 `config.INPUT_DIR` 找；「这本书来自哪个源」的读法也只有它一处。
   `config.DEFAULTS["watch"]["ignore"]` 里那条 `*.meta.json` 正是为这个位置留的（留档写在
   **被监听**的收书目录里）。测试现场同步改成「成品在库根、留档在收书目录」两个不同目录，
   并加一条反向用例钉住「按库根找 = 一本都找不到」。
