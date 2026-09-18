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

- [x] ~~**C1 Requests 完整功能**~~ — **已决策不做（2026-09-18，用户决策）**。理由：本项目的「从外部获取书」由**数据驱动书源规则**覆盖（`sources/rules.py` + `sources/store.py`），插件式索引器 / 下载客户端与之形态重叠、维护成本高。**页面与接口骨架已从代码中删除**：后端 `REQUEST_SECTIONS` + `GET /api/requests/config`；前端 `RequestsPage.vue` / 路由 / 设置注册项 / API 方法（`admin/requests` 页数 48 → 47）。⚠️ 旧理由「`Add to library` 依赖多库 → 不落地」在**第 10 期多库完成后已失效**，不再引用
- [x] **C2 系列详情 Group by media** — 第 10 期完成：`GET /api/series/{name}` 增 `groups`（复用 `migrate.target_type_of` 按媒体归类，含 media/label/count/books）；`SeriesDetailView` 按组分段渲染，**仅多于一组时**才加组标题（单媒体系列不加噪音），组内仍按系列序号排序并保留首册标记与倒序切换
- [ ] **C3 SYNOPSIS 外部源** — 依赖外部系列元数据，先做可行性评估 → 排入第 10 期

### D 类 · 2026-09-18 复核后从「不做」移入排期

> 复核结论：原「已决策不做」清单里有 6 项判定已过期或过粗（详见第二节「已修正的过期记载」）。
> 其中「在线元数据抓取 / Pages」实际已实现，「作者传记/头像、有声书、多书库、CBR」现正式排期。

- [x] **D1 作者传记** — 第 8 期完成：`core/authors.py` 走 OpenLibrary 作者检索取传记；`authors` 表把**在线值 / 本地覆盖分列**，展示取「本地覆盖 > 在线」，用户改过的不被再次抓取冲掉
- [x] **D2 作者头像** — 第 8 期完成：头像下载到 `CACHE_DIR/authors/`（**零外链**），并加入 `_MEDIA_TOKEN_PATHS`（`<img src>` 只能靠 `?token=`）；无图 404 → 前端回退渐变占位；归一化名相似度 <0.5 视为不同人（宁可放弃也不给错配）
- [x] **D3 `metadata/authors` 页做实** — 第 8 期完成：作者区块改为真实开关（启用 / 抓传记 / 抓头像 / 立即抓取全部作者），不再虚高为 `ready`
- [x] **D4 抓取深化（部分完成）** — **ISBN 精确匹配**已落地（`metasources.search_by_isbn`，命中即 `score=1.0`、`exact_isbn=True`，`metafetch.plan` 与 `online_candidate` 优先采用）；⚠️ **系列级元数据仍缺**（当前只写单本）→ 顺延，未随本期关闭
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
  补勾第 8 期遗留未勾的 D1–D5（其中 **D4 的「系列级元数据」明确标注仍缺、未随本期关闭**）；
  `capability-gap.md` 修正 6 处过期记载（Requests 三处、多库两处、有声书 / Pages 各一处）；
  README 48 → 47 并新增「自动化测试」小节；`router/index.ts` 与 `settingsNav.ts` 里早已漂移的页面计数统一为 **47**。

---

## 四、验证纪律（沿用 history）

全量类型检查 → 构建 → 部署 `novelforge/static/v2` → 重启测试实例 → 端到端脚本验证「保存 → 读回 → 实际生效」→ 浏览器逐路由冒烟。
