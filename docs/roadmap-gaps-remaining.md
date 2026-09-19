# 上游功能缺口跟踪基线（第 6 期起）

> 来源：`docs/bookorbit-capability-gap.md`（采集自线上实例 BookOrbit v2.10.0，2026-09-16）
> 基线日期：2026-09-18
> 已完成参考：第 0–5 期路线图（见 `docs/roadmap-verification.md`，第 0–4 期 27/27 验证，第 5 期 2026-09-17 完成）；**第 6–9 期已完成**（第 6 期 A1–A9 前端快赢、第 7 期 B1–B4 轻后端、第 8 期 D1–D5 作者级元数据与抓取深化、第 9 期 D6–D7 CBR 阅读与有声书播放器）
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
  ⚠️ **第 27 期复核（2026-09-19）**：此处「48 → 47」只是**当次删除动作**的增量记录，不是当前页数。当前设置页为 **48 页**（41 上游 + 7 本项目补充），见 `tests/test_settings_nav_contract.py:96` 的双向断言；`admin/requests` 仍在 `EXPECTED_PLACEHOLDERS`（`:47`）里，即该页骨架被删除后**又以只读占位页形式存在**
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
- **CBR 阅读 → 移入 D6**（`comics.py` 明确只支持 CBZ，`.cbr` 不在 `BOOK_EXTS`，`library.py:31-32`）。

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

---

## 四、验证纪律（沿用 history）

全量类型检查 → 构建 → 部署 `novelforge/static/v2` → 重启测试实例 → 端到端脚本验证「保存 → 读回 → 实际生效」→ 浏览器逐路由冒烟。
