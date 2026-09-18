# 上游功能缺口跟踪基线（第 6 期起）

> 来源：`docs/bookorbit-capability-gap.md`（采集自线上实例 BookOrbit v2.10.0，2026-09-16）
> 基线日期：2026-09-18
> 已完成参考：第 0–5 期路线图（见 `docs/roadmap-verification.md`，第 0–4 期 27/27 验证，第 5 期 2026-09-17 完成）；**第 6–7 期已完成**（A1–A9 前端快赢 + B1–B4 轻后端，见第一、三节）
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

- [ ] **C1 Requests 完整功能** — 插件式索引器/下载客户端/凭据加密/下载后自动化（原"后期未定期"）→ 排入第 10 期
- [ ] **C2 系列详情 Group by media** — 需后端按媒体类型分组 → 排入第 10 期
- [ ] **C3 SYNOPSIS 外部源** — 依赖外部系列元数据，先做可行性评估 → 排入第 10 期

### D 类 · 2026-09-18 复核后从「不做」移入排期

> 复核结论：原「已决策不做」清单里有 6 项判定已过期或过粗（详见第二节「已修正的过期记载」）。
> 其中「在线元数据抓取 / Pages」实际已实现，「作者传记/头像、有声书、多书库、CBR」现正式排期。

- [ ] **D1 作者传记** — 作者级元数据抓取（复用 `metasources`/`metafetch`），落库 → 第 8 期
- [ ] **D2 作者头像** — 抓取作者照片并**本地缓存**（零外链），替换当前「拿首本书封面代替」→ 第 8 期
- [ ] **D3 `metadata/authors` 页做实** — 当前 status 虚高为 `ready`（实为通用抓取开关）→ 第 8 期
- [ ] **D4 抓取深化** — 按 ISBN 精确匹配、系列级元数据（当前只写单本）→ 第 8 期
- [ ] **D5 A2 收尾** — 作者页「Added this week」需后端 author 级 `added` 字段 → 第 8 期
- [ ] **D6 CBR 阅读** — 前置：RAR 解压依赖 → 第 9 期（无前置则维持不做）
- [ ] **D7 有声书播放器** — 前置：音频格式扩展 + 播放器 UI + 音源确认 → 第 9 期
- [ ] **D8 多书库** — 架构级，动摇单一 `OUTPUT_DIR` → 第 10 期（需单独立项）

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

### 第 9 期 · 需外部/系统依赖（周级，**有前置条件才开工**）
1. **D6 CBR 阅读** — 前置：引入 RAR 解压能力（`unrar` 二进制，或 `rarfile` + 系统解包）。**不引入依赖则维持不做** —— 宁可 `.cbr` 不显示，也不放一本永远打不开的书进书架（`comics.py` 现有取舍）
2. **D7 有声书播放器** — 前置：① `BOOK_EXTS` 扩展音频格式（mp3/m4b/flac）② 播放器 UI（进度/倍速/跳转/睡眠定时）③ **音源与版权、体积占用需先确认**。README 定位是「TXT→EPUB 工具」，此项偏离较远，需用户明确要才做

### 第 10 期 · 架构级 / 重投入（需单独立项，周级+）
1. **D8 多书库** — 动摇单一 `OUTPUT_DIR` 假设：`/libraries` 实体 + 每库独立扫描路径/挂载 + 按库筛选/批量/查重 + 侧栏「库」组接真实数据（当前 `LIBRARIES = []`）。**涉及 `library.py` / `stats.py` / 工具页全域**，改动面最大
2. **C1 Requests 完整功能** — 插件式索引器 / 下载客户端 / 凭据加密 / 下载后自动化（价值最高、成本最高）
3. **C2 系列 Group by media** — 需后端按媒体类型分组
4. **C3 SYNOPSIS 外部源** — 依赖外部系列元数据，先做可行性评估，可能并入 D1 的作者/系列级抓取

---

## 四、验证纪律（沿用 history）

全量类型检查 → 构建 → 部署 `novelforge/static/v2` → 重启测试实例 → 端到端脚本验证「保存 → 读回 → 实际生效」→ 浏览器逐路由冒烟。
