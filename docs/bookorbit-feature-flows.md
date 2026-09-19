# BookOrbit 功能与流程（实例实测 + 源码对照）

> 采集对象：`http://192.168.0.95:3400/`（自托管实例，页面标题 `BookOrbit`，版本 **v2.10.0**，界面语言 zh-CN）
> 采集时间：2026-09-19
> 采集方式：真实浏览器（Playwright + Chromium）登录后逐页走查 + 前端路由实例导出 + 运行时接口抓取
> 账号：管理员账号 `Stromboid`（凭据不落文档）
> **源码对照（本轮新增）**：上游参考仓库 `https://github.com/735876214/bookorbit`，分支 `main` @ commit `c292d6cc`（站点版本 v2.10.0）。该仓库为**只读参考镜像**，不在本项目内复制代码，仅引用文件路径与结论。
> 用途：NovelForge 对标参考

---

## 0. 采集方法与证据来源

### 0.1 证据分两类，不混写、不互相冒充

| 证据类型 | 文中标注形式 | 来源与效力 |
| --- | --- | --- |
| **历史实测** | `历史实测（2026-09-19）` | 下列「实测」各来源，采集于 2026-09-19 的内网实例快照。反映**那一刻**的实例渲染与调用；实例此后变化，本文件不追认。 |
| **源码** | `源码（<文件路径>）` | 只读镜像 `735876214/bookorbit` @ `main` @ `c292d6cc` 的文件级结论。`packages/types/src/*.ts` 是**字段级权威**，`server/src/modules/*` 是**行为语义权威**，`client/` 是**界面结构来源**。 |

**冲突处置**：源码与历史实测冲突时**以源码为准**，并在该处写明差异；仅源码可确认、实例未覆盖的，逐条标注来源文件。凡源码无法确认的（布局、交互节奏、视觉细节、运行时实际调用），一律标注「**未验证（源码无法确认）**」，**不臆测、不沿用旧印象冒充新证据**。

### 0.2 历史实测的证据来源（采集日 2026-09-19）

| 证据来源 | 说明 |
| --- | --- |
| 前端路由实例 | 从运行中的 Vue app 取 `router.getRoutes()`，得到 **97 条路由**（全站骨架，权威） |
| 逐页 DOM 走查 | 每页提取 `h2/h3/label/button aria-label/正文`，判定实际渲染出的功能项 |
| 运行时接口抓取 | 注入 `fetch`/`XHR` 记录器后逐页导航，得到 **实测调用的 API 清单**（前缀 `/api/v1`） |
| 直接接口探测 | 对 `/api/v1/libraries`、`/api/v1/books/{id}` 等取原始 JSON，得到字段级真值 |
| 重定向探测 | 对可疑路由直接访问，看是否回落，用于识别已移除页面 |

### 0.3 源码证据的可获取范围

镜像为 blobless 稀疏克隆（`--depth 1 --filter=blob:none --no-checkout`）后 `sparse-checkout set packages/types packages/plugin-api`，落盘 **76 个 `.ts`** 于 `packages/types/src/`。本轮结论的字段级依据全部来自这些文件；`server/src/modules/*` 与 `client/` **未纳入本轮取证范围**，故凡涉及服务端语义细节与界面 DOM/交互结构的判断，一律标注「未验证（源码无法确认）」。

> 采集技法（内层滚动容器撑高视口、非 `<a>` 卡片用 `location.pathname` 探测、`NFDATA` 落盘本地解析、`playwright-cli` 需 `--browser=chromium`）已归档于 `docs/review/bookorbit-app-capture.md`，**本轮未使用**，不得据此写入新的「实测」结论。

---

## 1. 应用总览

### 1.1 技术栈与部署形态（实测）

- **前端**：Vue 3 SPA（`Pinia` + `vue-router` history 模式 + `vue-i18n` + `echarts`），重度代码分割——入口 HTML 仅 16.5 KB，但引用 `assets/` 资源 **195 处**。
- **后端**：NestJS 风格（错误体 `{statusCode, message, path, timestamp, requestId}`），对外 API 前缀 **`/api/v1`**；另有若干**非 `/api` 前缀**的同端口外部服务端点（见 §3.10）。
- **主题防闪**：`<script src="/theme-init.js">` 为**阻塞式**脚本，注释原文 `Blocking theme init — must run before first paint to prevent FOUC`。
- **CSP（实测响应头，逐字）**：
  `default-src 'self'; base-uri 'self'; font-src 'self' data: blob: https://fonts.gstatic.com; form-action 'self'; frame-ancestors 'self'; img-src 'self' data: blob: https:; object-src 'none'; script-src 'self' 'wasm-unsafe-eval'; script-src-attr 'none'; style-src 'self' 'unsafe-inline' blob: https://fonts.googleapis.com; connect-src 'self' ws: wss: https://cdn.jsdelivr.net https://api.dictionaryapi.dev https://*.wiktionary.org https://translate.googleapis.com; media-src 'self' data: blob:; frame-src 'self' blob:; worker-src 'self' blob:`
  说明：外部连通白名单仅 jsdelivr / dictionaryapi / wiktionary / translate.googleapis（词典与翻译用）。另有 `Cross-Origin-Resource-Policy: same-origin`、`Referrer-Policy: no-referrer`、`x-request-id`。

### 1.2 账号与权限（实测）

- 登录页 `/login` 仅两个字段：`#username`（`autocomplete=username`）、`#password`（`autocomplete=current-password`）；页脚含「忘记密码？」「Powered by BookOrbit」「Legal notices」。
- 其他认证路由：`/register`、`/setup`（初始化向导）、`/forgot-password`、`/reset-password`、`/magic`（魔法链接登录）、`/oauth2-callback`（OIDC 回调）。
- 登录态通过 `POST /api/v1/auth/refresh` 续期；`GET /api/v1/auth/me` 取当前用户；`GET /api/v1/auth/setup-status`、`/api/v1/auth/login-options` 决定登录方式（含 OIDC/魔法链接开关）。
- 当前账号为管理员：可见「服务器」设置组与全部用户/审计类页面。

### 1.3 实例数据规模（采集时）

- 书库 **9 个**：漫画(3)、刘备(10)、有声书(2)、工具书(7)、插图书(4)、教学(5)、杂志(8)、其他(9) 等；作者 **308**、系列 **5**。
- 书库 `id` 为数字；书籍 `id` 示例 728、753；书库根路径形如 `/books/漫画`。

---

## 2. 全站信息架构

### 2.1 路由总表（97 条，来自运行中 router）

**认证类（8）**
`/login`、`/register`、`/setup`、`/forgot-password`、`/reset-password`、`/oauth2-callback`、`/magic`、`/:pathMatch(.*)*`（兜底）

**核心业务（28）**
`/`（控制台）、`/libraries`、`/library/:id`、`/books`（书目，见注）、`/book/:bookId`、`/book/:bookId/edit`、`/book/:bookId/files`、`/read/:bookId/:fileId`、`/series`、`/series/:seriesId`、`/authors`、`/authors/:id`、`/collections`、`/collection/:id`、`/smart-scopes`、`/smart-scope/:id`、`/annotations`、`/statistics`、`/achievements`、`/book-dock`、`/requests`、`/requests/:id`、`/requests/:id/releases`、`/whats-new`

**工具（6）**
`/tools`、`/tools/entity-manager`、`/tools/bulk-rename`、`/tools/duplicate-books`、`/tools/missing-resources`、`/tools/:pathMatch(.*)*`

**设置（55，见 §3.9）**

> 注：`/books` 与 `/` 均出现两次，是同一 path 的重复注册（子路由/别名），实际入口为侧栏「浏览」。

### 2.2 侧栏与顶栏入口（实测抓取）

- **左侧栏**：控制台(`/`)、Book Dock(`/book-dock`)、Requests(Beta)(`/requests`)、工具(`/tools/entity-manager`)、作者 308(`/authors`)、系列 5(`/series`)、批注(`/annotations`) + 每个书库一项（`/library/{id}`，带书计数）+ 「查看全部书库(9)」(`/libraries`) + 底部「v2.10.0」(`/whats-new`)。
- **侧栏控制**：「切换侧边栏」「Collapse sidebar」。
- **书库页内操作**：新建库、库分区设置选项、新建智能瞄准镜、新建收藏、导出元数据、筛选器、显示库控制、选择、Grid/List/Table view、快速视图、Start reading / Continue reading、跳转到 #、标题 ↑（排序）、折叠系列。
- **顶栏**：浏览、库、智能书架、收藏夹、搜索、通知（角标）、统计、成就、**上传书**、帮助、外观、界面语言、设置、用户菜单(Y)。

---

## 3. 功能域详解

### 3.9 设置（`/settings/*`）

**侧栏分组（实测，中文界面下的 5 组）**

| 分组 | 子分组 | 叶子页（路由） |
| --- | --- | --- |
| 个人 | 个人信息 | 个人信息 `/settings/account/profile`、通知 `/settings/account/notifications`、隐私与共享 `/settings/account/privacy`、限制 `/settings/account/restrictions` |
| 个人 | 显示 | 主题、书籍封面、图标、布局、行为、语言设置（`/settings/appearance/*`） |
| 个人 | 阅读器 | 概况 `/settings/reader/general`、电子书 `/settings/reader/ebook`、PDF `/settings/reader/pdf`、漫画 `/settings/reader/comics`、音频簿 `/settings/reader/audio`、字体 `/settings/reader/fonts` |
| 书库 | 库 | 库 `/settings/libraries` |
| 书库 | 元数据 | 提供商、字段规则、自定义字段、得分、自动获取、作者、Genre Blocklist `/settings/metadata/*` |
| 书库 | 文件名称 | 文件名称 `/settings/library/file-naming` |
| 书库 | 维护 | 维护 `/settings/library/maintenance` |
| 设备与同步 | — | Kobo、KOReader、OPDS、电子邮件地址 `/settings/kobo|koreader|opds|email` |
| ACCOUNTS | — | Hardcover、Readwise、StoryGraph `/settings/hardcover|readwise|storygraph` |
| 服务器 | 用户与权限 | 用户 `/settings/admin/users`、帐户活动 `/settings/admin/account-activity`、魔法链接 `/settings/admin/magic-links`、OIDC / SSO `/settings/admin/oidc` |
| 服务器 | — | Requests、Book Dock、服务端字体、审计日志 `/settings/admin/*` |

**设置侧栏叶子页合计 25 项**（在同一页面 DOM 中一次性抓取到的全部 `a[href^="/settings"]`）：
`account/profile`、`account/notifications`、`account/privacy`、`account/restrictions`、`libraries`、`metadata/providers`、`metadata/field-rules`、`metadata/custom-fields`、`metadata/score`、`metadata/auto-fetch`、`metadata/authors`、`metadata/genre-blocklist`、`library/file-naming`、`library/maintenance`、`kobo`、`koreader`、`opds`、`email`、`hardcover`、`readwise`、`storygraph`、`admin/users`、`admin/account-activity`、`admin/magic-links`、`admin/oidc`、`admin/requests`、`admin/book-dock`、`admin/server-fonts`、`admin/audit-log`。

> 侧栏**按当前所在域动态展开**：访问书库/元数据页时会附加显示 `appearance/*`、`reader/*`、`admin/account-activity` 等域；访问服务器页时只列 `admin/*`。

- 设置页自带**命令面板**：快捷键 `⌘/Cmd + K`，提示「按 Cmd K 跳转到任何设置」，采集时显示 **42** 个可跳转项。
- 组路由 `/settings/account`、`/settings/appearance`、`/settings/reader`、`/settings/metadata`、`/settings/admin` 为**跳转壳**（落到组内首页）。
- 别名路由：`/settings/notifications` → `/settings/account/notifications`；`/settings/system` → `/settings/library/file-naming`；`/settings/integrations` → `/settings/hardcover`；`/settings/admin/metadata` → `/settings/metadata/providers`；`/settings/admin/metadata-auto-fetch` → `/settings/metadata/auto-fetch`；`/settings/admin/file-naming` → `/settings/library/file-naming`；`/settings/admin/maintenance` → `/settings/library/maintenance`。
- ⚠️ **`/settings/komga` 已不存在**：直接访问会回落到 `/settings/appearance/theme`（即未匹配兜底）。Komga 服务端点本身仍在（见 §3.10）。

#### 3.9.1 个人 → 个人信息（`/settings/account/profile`）

- 说明文案：「您的名称、电子邮件、密码和活动会话。」
- 头像：本地图片上传，支持 PNG/JPEG/WEBP，**最大 5 MB**；可「上传图片」「移除图片」。
- 分区与字段：
  - **个人信息**：全名、用户名（**不可更改**）、电子邮件地址（提示「请联系管理员更改您的电子邮件地址」）
  - **首选项**：时区（完整 IANA 时区列表；文案：「时区用于处理对时间敏感的成就，例如"早鸟"和"通宵达人"」）
  - **安全和访问**：含子分区「已连接的账户」

#### 3.9.2 个人 → 显示 → 主题（`/settings/appearance/theme`）

说明文案：「主题、强调色、背景和圆角半径。」

- **外观首选项的保存位置**（二选一）：
  - 「仅此设备」— 偏好仅保存在浏览器中，适合不同设备不同外观。
  - 「我的帐户」— 已启用，偏好保存到账户，跨设备一致。
- **主题**：配色方案 — 浅色 / 深色 / 系统（文案「浅色或深色界面」）
- **主题色**：说明原文 `Controls highlights and interactive elements`
- **圆角半径**：卡片和界面元素的圆角程度 — Sharp / Default / Rounded / Pill
- **书库背景图**：背景图案（书籍网格后显示的图案）— 基础 / 结构 / 氛围 / 折射

#### 3.9.3 个人 → 显示 → 书籍封面（`/settings/appearance/book-covers`）

说明文案：「封面阴影、书脊效果和占位图。」

- **默认封面搜索源**（`label` 实测）：选择"在线查找封面"时使用的搜索源；保存到账户、跨设备生效 — `DuckDuckGo` / `iTunes` / `所有来源`
- **封面显示模式**（宽高比不一致时真实封面在书槽内的显示方式）：模糊填充 / 裁剪填充 / 自然底部
- **书脊叠加**：关闭 / 轻微 / 明显；另有开关「在漫画封面上显示书脊」（cbz、cbr、cb7）
- **书籍详情页封面色调**：在书籍详情页的艺术图和标题后方淡出封面提取色 — 关闭 / 单色 / 双色
- **封面阴影强度**：网格、列表、表格、控制面板缩略图下的阴影深度
- **卡片叠加层**（直接显示在封面卡上的元数据开关集）：进度条（底部细彩线）、文件格式（右下角 EPUB/PDF/CBZ 徽章）、评分（左下星级）、阅读进度（左上状态图标）、系列数（右上角位置徽章，如 `#3`、`#1.5`）、锁定状态（右上角元数据锁图标：锁定=橙色、解锁=绿色）

#### 3.9.4 个人 → 显示 → 图标（`/settings/appearance/icons`）

说明文案：「选择应用内使用的图标样式。」

- **上传图标** / **自定义图标**（表格：最新的 / 名称）；空态原文「尚未上传任何图标。」「尚未上传自定义图标。」

#### 3.9.5 个人 → 显示 → 布局（`/settings/appearance/layout`）

说明文案：「默认书库视图、密度和间距。」

- **库网格布局 → 封面大小行为**：控制尺寸与网格间距是全局共享还是按视图独立 — 「每个视图模式」（从每个视图的显示面板调整封面大小和间距）/「同步所有视图」
- **视图大小**：纵向封面大小（默认 **130px**）、方形封面大小（默认 **150px**）、纵向网格间距（默认 **28px**）、平方网格间距（默认 **28px**）
- **卡片信息模式**：网格卡片上显示书名和作者的位置 — 悬停时 / 低于封面 / 关闭
- **系列显示**：折叠系列封面（系列在书状网格中折叠时显示的封面）— 堆叠 / 马赛克 / 第一本 / 最新一本 / 第一本未读
- **作者网格**：封面大小（默认 **120px**）、封面形状（圆圈 / 方形）
- **列表和表视图**：斑马纹（交替行背景色，便于扫读）

#### 3.9.6 个人 → 显示 → 行为（`/settings/appearance/behavior`）

说明文案：「浏览和排序时书库的响应方式。」

- **缩略图点击**：选择从网格和列表视图打开一本书时的行为 — 「首先阅读」（存在可读文件时直接打开阅读器）/「打开详情」（缩略图进入书籍详情页）
- **默认显示过滤器预览**：打开智能书架时展开当前筛选与排序摘要
- **默认折叠系列**：`Group books in the same series into a single card in library, collection, and Smart Scope views`（文案未本地化）

#### 3.9.7 个人 → 显示 → 语言设置（`/settings/appearance/language`）

说明文案：「界面语言和地区格式。」— **语言 → 界面语言**（当前 `简体中文`）

#### 3.9.8 个人 → 阅读器 → 电子书（`/settings/reader/ebook`）

说明文案：「电子书的字体、间距和翻页行为。」

- **新书 → 应用我的设置到新的书本**：关闭后新书使用出版社字体与版式，只有阅读器中改动后才生效
- **布局**：
  - 阅读模式 — 分页（翻页面）/ 连续滚动流
  - 固定的布局页面扩展 — Manga、连环画和基于图像的 EPUBs 的默认值 — 预约默认 / 单页 / 列（每页文本列数，默认 2）
- **主题**：暗色模式（使用选中主题的黑暗变体）；内置主题 13 种 — 默认主题、灰度、护眼棕、绯红、青野、檀木红、天青、晨曦、烬橙、极光、深海蓝、薄雾灰、纯黑（AMOLED）
- **图形**：
  - 字体 — 书籍默认字体 / 衬线字体 / 无衬线字体 / 等宽字体
  - Font style — 常规 / 粗体 / 常规 Italic / 粗体 Italic（提示：书内粗体斜体相对此设置保留）
  - 字号（默认 **16px**）、行高度（默认 **1.5**）
  - Paragraph spacing（默认 `Book default`，保留出版社间距）
  - 对齐文本、连字符断字（用连字自动折叠长词）
  - **高级版**：Letter spacing、Word spacing、First-line indent（均支持 `Book default` 与自定义）

#### 3.9.9 个人 → 阅读器 → PDF（`/settings/reader/pdf`）

说明文案：「PDF 的渲染、缩放和页面适配。」

- **布局 → 滚动模式**：页（每次翻转一页）/ 已滚动（连续滚动到所有页面）/ Horizontal（横向）
- **页面扩展**：在双页视图右侧开始哪个页码 — 无 / 奇德 / 偶数 / Auto
- **缩放 → 默认适配性**：打开 PDF 时如何缩放 — Fit Page / Fit Width / Automatic / Custom；「重置为默认值」

#### 3.9.10 个人 → 阅读器 → 漫画（`/settings/reader/comics`）

说明文案：「漫画的阅读方向和对页显示。」

- **查看 → 阅读模式**：分页 / 无限(间距) / 无限的 (无间距)（原文提示 `use "Infinite (no gaps)" for webtoons`）
- **页面视图**：单一的 / 两页（并排显示一两个页面）
- **适合模式**：页 / Width / 高度 / 实际的
- **阅读方向**：左到右 / 右到左（原文「右对南加 L 到 R」为「右到左」的机器翻译痕迹）
- **扩展对齐**：普通的 / 已移转（隔一张扫描封面后移一页的配对）
- **2. 扩大差距**（`label` 实测，原文如此）：两页视图中页面间的间距，默认 **0px**
- **跨页面处理**：自动操作 / 禁用（仅在双页分页模式下自动显示宽幅扫描）
- **在小屏幕上强制使用两页**：关闭 / 开启（分页双页模式跳过移动端自动回退）
- **Auto-advance to next book**：`Turn past the last page to open the next book in the series`（开关，文案未本地化）
- **显示 → 背景颜色**：页面后面的画布颜色 — 黑色 / 灰度 / 白色的

#### 3.9.11 个人 → 阅读器 → 音频簿（`/settings/reader/audio`）

说明文案：「播放速度、跳转间隔和睡眠定时器。」

- **回放 → 默认播放速度**：0.75x / 1x / 1.25x / 1.5x / 1.75x / 2x
- **默认音量**：初始音量级别（0–100%），默认 **100%**
- **跳过控制**：跳过后退持续时间（5s / 10s / 15s / 30s）、跳过前进持续时间（10s / 15s / 30s / 60s）

#### 3.9.12 个人 → 阅读器 → 字体（`/settings/reader/fonts`）

- **上传字体**：拖拽或浏览，支持 TTF、OTF、WOFF、WOFF2，**每个最大 10 MB**
- **您的字体**：配额 `已使用：0/50`（上限 **50 个**）；空态「尚未上传字体」

#### 3.9.13 个人 → 通知（`/settings/account/notifications`）

说明文案：「控制 BookOrbit 向你发送什么通知，以及发送到哪里。」
**通知矩阵**：每项三档 `Off` / `Problems` / `All`（部分项无 `Problems`）：

| 分组 | 通知项（中文标签） | 说明原文 |
| --- | --- | --- |
| 书库（已启用 **11/11**） | 书库扫描 | 当书库扫描完成、失败或发现缺失书时 |
| | 正在获取元数据 | 当您书籍的元数据查询完成或失败 |
| | 作者信息补充 | 当作者的简历和照片完成获取 |
| 文件 | 文件回写 | 当编辑的元数据被写回书文件到磁盘上 |
| | 文件重命名 | 当单一书文件重命名以匹配您的命名模式 |
| | 批量重命名 | 当许多书籍大批重命名完成或失败 |
| | 数据迁移 | 从另一个库工具导入完成或失败 |
| 集成 | Book Dock | 当存入码头的文件准备好审查或最后定稿 |
| | Book requests | `When a book request is submitted, decided, or the book becomes available.`（未本地化） |
| 邮件发送方式 | 邮件发送方式 | 当向电子邮件地址发送一本书时成功或失败 |
| 个人资料 | 成就 | 当您解锁新的阅读成就时 |
| | 应用更新 | 「在更新后显示"新建内容"」— 在应用更新后弹出突出显示新功能（存档仍可任意方式访问） |

#### 3.9.14 个人 → 隐私与共享（`/settings/account/privacy`）

说明文案：「阅读统计、分享链接和活动可见性。」

- **阅读数据分享权限等级**（控制管理员是否能看到您阅读活动的可识别摘要）— 三档：
  - **非公开的**：「只有您可以看到您的阅读统计。」（当前设置）
  - **分享摘要**：「分享汇总后的使用习惯，但不包含书名、作者、系列或叙述者。」
  - **分享详细的看法**：「还分享最近的书籍和顶部书籍、作者、丛书、基因组和作曲家。」
- **个人资料访问历史**：最近管理员对您共享阅读资料的浏览；空态「没有管理员查看您共享的阅读资料。」

#### 3.9.15 个人 → 限制（`/settings/account/restrictions`）

说明文案：「此账户的内容年龄评级和已屏蔽内容。」— 空态「没有内容限制」：「您的帐户可以完全访问您指定的库中的所有内容。」

#### 3.9.16 个人 → 阅读器 → 概况（`/settings/reader/general`）

说明文案：「所有阅读模式共用的默认设置。」

- **保存阅读器首选项的位置**：仅此设备（浏览器本地）/ 我的帐户（当前启用，跨设备一致）

#### 3.9.17 书库 → 库（`/settings/libraries`）

说明文案：「扫描路径、监听文件夹和导入规则。」

- 顶部操作：**扫描全部**、**添加库**、**筛选书库…**、**排序**（默认排序 / 名称 / 书籍列表 / 所占磁盘大小 / 最近扫描）
- 汇总行：`9 libraries · 9 文件夹 · 613 书 · 硬盘大小 33.59 GB`
- **每库卡片**（列表视图）字段：库名、**模式**（实测均为「文件夹模式」）、`N 文件夹`、**根路径**（如 `/books/漫画`）、**书籍数**、`Move N books`（批量移动入口）、占用容量、**格式分布**（如 `PDF 48 / CBZ 6 / EPUB 2 / CBR 1 / MOBI 1`）、**查看文件夹**、**打开**、**定时扫描**（实测统一 `At 00:00`）、**写入至文件**（实测「关闭」）、**重命名文件**（实测「打开」）、**最近扫描时间**（如 `Scanned 13小时前`）、**上次日程结果**（如 `日程 - 3 updated, 1 missing`、`日程 - no change`、`手动匹配 - no change`）、**扫描** 按钮。
- 采集时 9 个书库的实际数据：

| 库 | 书籍数 | 容量 | 主要格式 |
| --- | --- | --- | --- |
| 漫画 | 58 | 2.55 GB | PDF 48 / CBZ 6 / EPUB 2 / CBR 1 / MOBI 1 |
| 刘备 | 154 | 4.21 GB | EPUB 138 / PDF 13 / MOBI 3 |
| 有声书 | 100 | 654.8 MB | M4A 71 / MP3 29 |
| 工具书 | 172 | 21.05 GB | PDF 165 / EPUB 6 / AZW3 1 |
| 插图书 | 103 | 2.57 GB | EPUB 58 / PDF 45 |
| 教学 | 17 | 2.19 GB | EPUB 14 / PDF 3 |
| 杂志 | 3 | 241.7 MB | PDF 3 |
| 其他 | 4 | 98.3 MB | PDF 3 / EPUB 1 |
| 连环画 | 2 | 55.7 MB | PDF 2 |

#### 3.9.18 书库 → 元数据 → 提供商（`/settings/metadata/providers`）

说明文案：「启用外部元数据源并配置他们的凭据。」顶部汇总 **已启用：10/14**，筛选页签「全部 / 已启用 / 需要设置」。

**分组与状态（实测）**

| 分组 | 组内进度 | 提供商 | 说明原文要点 | 状态 |
| --- | --- | --- | --- | --- |
| 一般书目目录 | 5/7 | Google Books | 覆盖更广；现在需要 API 密钥才能启用 | 启用 |
| | | Amazon | 推荐使用会话 Cookie，仅粘贴 Cookie 取值（不要带 `Cookie:` 前缀） | 启用 |
| | | Goodreads | 网络上最大的阅读社区，无需安装 | 启用 |
| | | Hardcover | 从 hardcover.app/account/api 获取的代币，`Bearer` 前缀可选 | **需要设置** |
| | | Open Library | Internet Archive 免费书库，无需设置 | 启用 |
| | | iTunes | Apple 数字书目录；可选高分辨率或标准分辨率 | 启用 |
| | | Kobo | 抓取 Kobo 公开书籍页；国家和语言必须匹配 Kobo URL 路径；机器人保护可阻止请求 | 已配置 |
| 有声读物 | 2/3 | Audible | 从音频中弹出音频簿元数据，无需额外设置 | 启用 |
| | | AudNexus | 社区驱动的音频簿元数据，无需设置 | 启用 |
| | | Libro.fm | 使用未公开端点，默认禁用 | 已配置 |
| 漫画和轻小说 | 2/2 | ComicVine | 需要 comicvine.gamespot.com 的免费 API 密钥 | 启用 |
| | | RanobeDB | 轻小说元数据，无需设置 | 启用 |
| 区域目录 | 1/2 | LubimyCzytac | 波兰书目（lubimyczytac.pl），抓取公开页 | 启用 |
| | | Aladin | 韩国书目，需要 aladin.co.kr 的 TTB 密钥 | **需要设置** |

每个提供商行右侧固定为「启用」（开关）与「配置」（凭据弹窗）两个动作。

#### 3.9.19 书库 → 元数据 → 字段规则（`/settings/metadata/field-rules`）

说明文案：「控制哪个提供商提供每个元数据字段以及如何在您的库里合并值。」
页内说明原文（未本地化）：`Providers are tried top to bottom and the first one that returns a value wins. The merge strategy decides whether that value may replace what the book already has; genres can also append new unique values. Set defaults here, then override individual fields per library.`

- 作用域切换：**Global defaults** + 每个库（漫画/刘备/有声书/工具书/插图书/教学/杂志/其他/连环画）独立覆盖页签；库页签可「使用全局默认值」。
- 顶部动作：**任何**（字段筛选）、**清除所有提供商**、**重置为默认值**。
- **字段分组与权重（实测，当前生效顺序）**：核心文件(4/4)、贡献者(1/1)、出版物(5/5)、系列(2/2)、分类(1/1)、音频簿(3/3)；每行含：字段名、编号的提供商优先顺序（可拖拽排序 + **添加**）、被跳过项提示（如 `Kobo is turned off, so it stays in the order but is skipped.`）、**合并策略**。
- **合并策略三档**：`仅补全缺失字段` / `如果已提供` / `总是`（体裁另有 `合并`，即追加去重）。
- 实测示例（标题/字幕/描述/作者/出版社/发布年份/语言/页面计数/系列名称/系列索引/叙述者/阅读时长/桥接的）：`Goodreads → Google → iTunes → Amazon → (Kobo 跳过) → Open Lib`；封面为 `Amazon → iTunes → Goodreads → Google → Open Lib`；社区评分为 `Goodreads → Google → Open Lib → iTunes → RanobeDB → Amazon → Audible`。
- **获取高级行为**：
  - 「从所有选定的提供商合并类型」— 从指定到体裁字段的每个提供商收集并合并体裁，而不是停在第一个结果
  - 「每本书的最大体裁数」— 排除与去重后生效，留空表示无限制（影响后续获取）
  - 「在书籍上存储提供商 ID」— 保存返回的 ISBN/ASIN/Goodreads ID 等，便于后续更准确的查询
  - `Use existing provider IDs only`（未本地化）— 只查询已有存储 ID 的提供商，查找失败不回落搜索；手工搜索与新书发现不受影响
- 底部操作：**Discard** / **Save Global defaults**（含未保存提示 `No unsaved changes`）。

#### 3.9.20 书库 → 元数据 → 自定义字段（`/settings/metadata/custom-fields`）

说明文案：「定义自定义元数据字段，并选择哪个库使用它们。」

- **新建字段**：定义一个自定义元数据字段，并选择哪个库使用它。
- 字段列表：拖动以重新排序、编辑标签、切换库或**存档**字段。
- 采集时空态原文：「尚无自定义字段 — 使用上面的表单来定义您的第一个自定义元数据字段。」

#### 3.9.21 书库 → 元数据 → 得分（`/settings/metadata/score`）

说明文案：「分配元数据字段的权重来计算多少信任已获取的结果。」
页内说明原文：`Every book gets a score out of 100 for how complete its metadata is. A weight is only meaningful next to the others, so each field below shows the share of a finished score it is responsible for. Doubling every weight changes nothing.`

- **评分来源构成（实测百分比）**：Core 56.4% / Publishing 17.9% / Classification 11.5% / Provider IDs 10.3% / Enrichment 3.8%；`21 of 24 fields scoring, 78 points total`。动作：**重新计算所有**、**重置为默认值**。
- **计分字段与占比（实测，共 21 项计分 + 3 项不计分）**：

| 分组 | 字段（计分条件） | 占比 |
| --- | --- | --- |
| Core | 标题 / 作者 / 封面 / 描述 | 12.8% / 12.8% / 12.8% / 10.3% |
| Core | ISBN-13 | 9.0% |
| Classification | 体裁 | 7.7% |
| Publishing | 出版社 / 发布年份 / 语言 | 5.1% / 5.1% / 5.1% |
| Core | 页面计数 / ISBN-10 / 标签 | 2.6% / 2.6% / 2.6% |
| Core | 社区评分 | 1.3% |
| Provider IDs | Google Books ID / Goodreads ID / Amazon ID / Hardcover ID / Open Library ID / iTunes ID / Kobo ID / Aladin ID | 各 1.3% |
| 不计分（3） | 字幕、系列名称、系列索引 | `Not scored` |

- **得分分布（当前书库实测）**：中值 **43**；`50 以内 376`、`90 及以上 0`；统计口径 `Across 649 books in the libraries you can access`；刻度 0 / 50 / 70 / 90 / 100，徽章档位 `在 50 以内`、`50-69`、`70-89`、`90+`。
- 底部操作：**放弃** / **保存并重定向**。

#### 3.9.22 书库 → 元数据 → 自动获取（`/settings/metadata/auto-fetch`）

说明文案：「当新书被添加到您的书库时，自动获取封面、描述和其他详细信息。」

- **全局设置**：**启用自动获取**（自动获取合格书的元数据）、**导入时触发**（书籍首次接入书库时入队）。
- **资格条件**（满足任一即合格）：**从未获取**（从未尝试过元数据）/ **低元数据分数**（低于阈值，阈值输入框 `/ 100`）/ **缺少字段**（勾选字段：标题、字幕、描述、封面、作者、出版社、发布年份、语言、页面计数、社区评分、系列名称、系列索引、体裁、叙述者、阅读时长、桥接的）。
- 摘要行示例：`从未获取 • 分值小于 60 • 缺少2 字段`；动作：**保存**、**为合格的书籍运行**（当时显示 `约 529 项符合条件`）。
- **按库覆盖**：每个库一段，可「从全局继承 / 覆盖」，覆盖时可见「内部默认设置」；每库带**立即运行**按钮与合格数（实测：漫画约 47、刘备约 154、有声书约 93、工具书约 159、插图书约 50、教学约 17、杂志约 3、其他约 4、连环画约 2）。

#### 3.9.23 书库 → 元数据 → 作者（`/settings/metadata/authors`）

说明文案：「当新作者出现在您的库中时，自动获取个人简历和个人资料照片。」
页内说明：`优先采用最先返回有效值的来源。Audnexus 仅提供传记和照片。`

- **启用作者信息自动补充**（添加或更新书籍时自动获取作者简介与头像）、**导入时触发**。
- **字段来源**（每字段 = 有序来源列表 + 合并策略，三档：`缺少填充` / `如果提供则覆盖` / `总是覆盖`）：
  - 作者简介 → `1 Goodreads → 2 AudNexus`
  - 照片 → `1 Goodreads → 2 AudNexus`
  - 出生日期 / 去世日期 / 网站 / 体裁 / 影响 → 仅 `Goodreads`
- **资格条件**（任一命中即合格）：**从未补充过** / **缺少简介** / **缺少照片**。
- 动作：**保存**、**为合格作者运行**（实测 `303 位符合条件`）、**为所有作者运行**。

#### 3.9.24 书库 → 元数据 → Genre Blocklist（`/settings/metadata/genre-blocklist`）

说明文案：「防止不想要的提供者流派值被写入书中。」

- **全局题材屏蔽列表**：此列表中的精确流派值在元数据写入之前从提供商结果中删除。
- 「流派值」输入 + **添加**；计数 `0 条目`；空态「没有屏蔽的类型」；提示原文「添加精确的值，如音频簿或成人，以使它们不再被获取的元数据。」

#### 3.9.25 书库 → 文件名称（`/settings/library/file-naming`）

说明文案：「存储文件的文件夹和文件名命名规则。」
页内规则说明（未本地化）：`A library with a pattern of its own wins. Every other library follows the global default for its organization mode. Changing a pattern does not move books already on disk; new uploads follow it from the next upload on.`

- 三个**组织模式**的全局默认：`File as Book default`、`Folder as Book default`、`Download filename`（Downloads and export ZIPs）。
- 覆盖矩阵：`LIBRARIES 1/9 CUSTOM` — 实测 8 个库为「文件夹作为书」且未自定义，仅 1 个库自定义。`No library uses this default right now` 提示「全局默认无人使用」（因为各库都跟了文件夹模式）。
- **图案（PATTERN）编辑**：
  - 默认图案：`<{authors:first}|Unknown Author>/<{series}/><{seriesIndex}. ><{title}|{originalFilename}>< ({year})>`
  - **令牌**：`{title}` `{subtitle}` `{authors}` `{narrators}` `{year}` `{series}` `{seriesIndex}` `{publisher}` `{isbn}` `{language}` `{library}` `{originalFilename}` `{extension}`
  - **修饰符**：`:first` `:sort` `:initial` `:fixed2` `:max3` `:upper` `:lower`
  - **结构语法**：`optional`（`<...>`）、`fallback`（`|`）、`folder`（`/`）
  - **配方（OR START FROM A RECIPE）**：`系列书架`（`William Gibson/Sprawl/01. Neuromancer (1984).epub`）、`Calibre style`（`William Gibson/Neuromancer (1984).epub`）、`按字母顺序`（`G/Gibson, William/Sprawl/01. Neuromancer.epub`）、`平整无文件夹`（`William Gibson - Neuromancer (1984).epub`）
  - **实时预览**：`RESULT: FILE AS BOOK DEFAULT` 展示解析出的书名/作者·年份/系列#编号/「Sample book used for every preview」的路径；并给出**元数据缺失时的回落**：`No series` / `No year` / `No author` → `/Unknown Author/Sprawl/01. Neuromancer (1984).epub`
  - **跨平台路径净化**：`Replaces characters Windows rejects. Previews reflect this setting.`
- 底部：**Discard / Save changes**（含 `No unsaved changes` 提示）。

#### 3.9.26 书库 → 维护（`/settings/library/maintenance`）

说明文案：「重新扫描、重复文件、孤立文件及缓存重建。」

| 分区 | 项 | 说明 |
| --- | --- | --- |
| 上传 | 上传文件大小限制 | 配置全系统文件上传的最大尺寸限制（输入 + `MB` + **保存**） |
| 导入 | 导入书库数据 | 从**旧版 Booklore** 安装中一次性导入书籍、元数据和阅读进度（**开始**） |
| 建议 | 刷新建议索引 | 依据最新书库变动更新推荐引擎，后台运行（**运行**） |
| 成就 | 回填成就 | 重新评估所有用户的成就（**运行回填**） |
| 更新 | 检查更新 | 启动时自动检查 GitHub 是否有新版本，有更新时在侧边栏显示提示 |

> 注：`导入书库数据` 说明中直接点名 **Booklore**，说明 BookOrbit 与 Booklore 存在谱系/数据兼容关系。

#### 3.9.27 设备与同步 → Kobo（`/settings/kobo`）

说明文案：「同步端点、存储代理和书架映射。」页内页签：**同步设置 / 活动日志 / 注册设备**。

- 设备列表：**添加设备**；采集时已有 1 台设备 `yaya`，`上次同步时间：11天前`。
- **书籍是如何同步的**（原文要点）：必须先在对应**合集**上开启「同步到 Kobo」开关（侧边栏打开任意合集 → 编辑图标 → 切换「同步到 Kobo」）；未加入已开启同步合集的书籍不会同步。
- **同步首选项**：
  - **双向进度同步**：同步 BookOrbit 与 Kobo 之间的阅读位置；需要 KEPUB 投递以获得准确位置与可靠翻页恢复
  - **同步 BookOrbit 摘录到 Kobo**：把 BookOrbit/KOReader 的高亮发送到 Kobo 摘录（即使关闭，Kobo 高亮也会导入 BookOrbit；批注删除会被同步）；需要 KEPUB 投递，且 Kobo 上的书必须是 BookOrbit 下载的 KEPUB
  - **包含 Kobo Store 标题**：把 Kobo 账户中的书（含 Kobo Plus 订阅与已购）一并投送到设备；未启用时只同步 BookOrbit 的书；商店书籍直接从 Kobo 下载，不进入 BookOrbit 书库
  - **转换为 KEPUB**：以 KEPUB 发送合格 EPUB；进度同步或摘录同步启用时会强制保持；下次同步受影响书籍会重新以 KEPUB 提供，若 Kobo 保持联网会删除旧 EPUB 副本
  - **强制连线**：确保文本说明一致，重新生成缓存的 KEPUB
- **进度阈值**：**标记为已读** 默认 `1%`、**标记为已完成** 默认 `99%`。
- **KEPUB 转换限制**：默认 `100 MB` — 超过限制的书以常规 EPUB 发送，此时不会同步阅读器位置。
- 底部：提示「更改必须保存才能生效。」+ **保存同步设置**。

#### 3.9.28 设备与同步 → KOReader（`/settings/koreader?tab=settings`）

说明文案：「进度同步和文档匹配。」页内页签：**同步设置 / 文件名称**。

- 顶部动作：**刷新**、**进度同步**开关（允许 KOReader 设备同步阅读进度、阅读动态、摘录内容及批注删除记录）。
- 状态卡：**用户名**（采集为 `yaya`）、**更改凭证**、**上次同步**（采集为「从不」）、**同步的书**（「没有书籍」）、**设备**（「没有设备」）、**证书已创建**（`2026年9月8日`）。
- **设置**：
  - **KOReader 同步 URL**：配合 BookOrbit 插件及 KOReader 内置进度同步功能使用；**复制 URL**
  - **预配置的 BookOrbit 插件**：下载带服务器 URL 与同步登录信息的 zip；含目录浏览与同步；解压到 `koreader/plugins/` 后重启 KOReader；最新插件版本 **v1.5.2**，设备更新在 KOReader 内的 BookOrbit 菜单执行；**下载插件**
- **设备**：停用设备会隐藏并保留已同步内容；删除同步数据不可撤销；空态「尚未同步设备」。
- **插件活动**、**未匹配的 KOReader 书**（可刷新）、**手动的 KOReader 链接**（可刷新）三个列表区。
- **设置指南 → KOReader 设置步骤**：使用 BookOrbit 插件进行目录浏览、下载、进度、读取事件和高亮；仅用内置插件时只做进度。
- **危险区域 → 删除 KOReader 凭据**：删除同步凭据并断开所有设备（进度数据保留）。

#### 3.9.29 设备与同步 → OPDS（`/settings/opds`）

说明文案：「供第三方阅读应用使用的目录订阅源。」

- **服务器 → OPDS 目录服务器**：允许 OPDS 客户端浏览和下载书；展示 **ENDPOINT** + **复制**。
- **OPDS 账户**：**添加**；采集时已有账户 `yaya`，其可见排序档位为：`最近添加` / `标题 (A-Z)` / `Title (Z-A)` / `作者 (A-Z)` / `作者 (Z-A)` / `系列(A-Z)` / `系列 (Z-A)`。
- 提示原文：「在阅读器应用中使用 OPDS 帐户。如果意外共享，请保持凭据私密并旋转密码。」

#### 3.9.30 设备与同步 → 电子邮件地址（`/settings/email?tab=providers`）

说明文案：「SMTP 投递和发送至设备地址。」页内页签：**提供商 / 收件人 / 群組 / 模板 / 首选项 / 历史记录**。

- **SMTP 提供商**：**添加提供商**；采集时空态「尚无提供商。添加 SMTP 提供商开始发送电子邮件。」
- **提供者备注（权限口径原文）**：`系统` 发送渠道仅超级管理员可用，用于发送密码重置邮件；未手动指定渠道推送书籍时使用 `默认设置` 默认渠道；标记为 `共享的` 的渠道对全体用户开放。

#### 3.9.31 ACCOUNTS → Hardcover（`/settings/hardcover`）

说明文案：「与 Hardcover 同步阅读状态和评论。」

- **连接**：连接您的 Hardcover 帐户以同步阅读数据。
- **API TOKEN** 输入（可 `显示`）+ 提示「查找您的令牌在 hardcover.app/account/api」+ **Validate token** + **保存**。

#### 3.9.32 ACCOUNTS → Readwise（`/settings/readwise`）

说明文案：「自动将您的摘录发送到 Readwise。」

- 页内说明（未本地化）：`Connect your Readwise account to sync your highlights.` / `Add your Readwise access token to start syncing.`
- **ACCESS TOKEN** 输入（可 `Show`）+ 提示「Find your token at readwise.io/access_token」+ **Test**。
- **Enable sync**：自动把高亮发送到 Readwise。动作：**Save**。

#### 3.9.33 ACCOUNTS → StoryGraph（`/settings/storygraph`）

说明文案：「同步您的阅读进度和状态到 StoryGraph。」
页内说明原文（未本地化，口径很重要）：`StoryGraph has no public API. This integration works by reusing two cookies from your own logged-in browser session, the same approach used by community KOReader plugins. It can break if StoryGraph changes their site, and you may occasionally need to re-paste fresh cookie values.`

- 获取步骤原文：登录 `app.thestorygraph.com` → 开发者工具（F12）→ Application/Storage → Cookies → 复制 `_storygraph_session` 与 `remember_user_token` 的值。
- 字段：`_STORYGRAPH_SESSION`、`REMEMBER_USER_TOKEN`（可 `Show`）；动作：**Validate cookies**、**Save**。

#### 3.9.34 服务器 → 用户与权限（`/settings/admin/users`）

说明文案：「帐户、角色、权限和邀请。」汇总行 `1 account · 1 with administrator access`。

- 顶部动作：**创建用户**、**搜索用户**；统计卡：`所有用户 1` / `管理员 1` / `已启用 1` / `未激活 0`。
- **用户表**列：User（头像+显示名）、电子邮件地址、**访问权限 / LIBRARIES**、Last active、状态、操作。
  实测唯一账号：显示名 `Yaya`、`@Stromboid`、`735876214@qq.com`、角色 `Superuser`、库访问 `All 9`、Last active `此刻`、状态 `已启用`、操作 **编辑**；页脚 `Showing 1 of 1 accounts`。
- **DEFAULTS FOR NEW ACCOUNTS**（Applies to self-registration and OIDC）：
  - **允许自助注册**：启用后登录页显示创建账户链接
  - **Starting libraries**（`0 of 9`）：勾选漫画/刘备/有声书/工具书/插图书/教学/杂志/其他/连环画；说明 `Viewer access granted automatically to every new account.` — 动作 **保存**。

#### 3.9.35 服务器 → Requests（`/settings/admin/requests?tab=sources`）

说明文案（未本地化）：「Sources, download clients, and what happens to a book once it downloads.」页内页签：**Sources / Download clients / Automation**。

- ⚠️ 顶部告警原文：`BOOK_REQUEST_ENCRYPTION_KEY is not set, so a client password cannot be saved. Generate one with: openssl rand -hex 32`
- **Sources**：BookOrbit 自带任何索引源；每条源都由用户自行配置，责任自负。两条接入路径：
  - **Install a plugin** — 一个文件教会 BookOrbit 搜索特定站点（用户提供，再填其设置）；动作 **Browse open library plugins** / **Install plugin**
  - **Add an indexer** — 指向已有的 Torznab 或 Newznab feed，每个 feed 一份配置；动作 **Add indexer**
  - 空态原文：`No sources yet — BookOrbit bundles no sources of its own, so a request search finds nothing until you add one.`

#### 3.9.36 服务器 → Book Dock（`/settings/admin/book-dock`）

说明文案：「在书页上显示快速操作。」

- **丢弃文件夹 → 容器路径**：`/data/book-dock` — 复制或移动书卷文件到此文件夹，将被自动提取和处理（支持子目录）；提示「要改变这条路径，请设置 `BOOK_DOCK_PATH` 在您的 `.env` 文件」。
- **元数据 → 从提供商自动获取元数据**：文件加入书架后自动从已配置提供商（Google Books、iTunes、Open Library 等）获取元数据。
- **自动完成 → 启用自动完成**：元数据**信任分**等于或高于阈值的文件将自动完成。

#### 3.9.37 服务器 → 服务端字体（`/settings/admin/server-fonts`）

说明文案：「在此服务器上为每个读者安装字体。」

- **上传字体**：拖拽或浏览，支持 TTF/OTF/WOFF/WOFF2，每个最大 **10 MB**。
- **服务端字体**：配额 `已使用：0/200`（上限 **200 个**，远高于个人字体上限 50）；空态「暂无服务端字体」；说明「在此处添加的字体将对全部用户的阅读器生效」。

#### 3.9.38 服务器 → 审计日志（`/settings/admin/audit-log`）

说明文案：「谁改变了什么，什么时候改变。」

- **筛选器**：`没有活动的过滤器`；输入/选择项：**搜索事件**、**事件类型（发生了什么）**、**执行者**、**目标类型（受影响）**、**来自**、**收件人**、**快速日期**（今天 / 7 天 / 30 天）、**搜索**。
- **事件表**列：时间、执行者、类别、事件、Target、影响；每行可展开 **详细信息**。
- 实测可观测的**事件类别与样例**：
  - `认证` — `User 'Stromboid' logged in` / `logged out`（执行者形如 `Stromboid#1`）
  - `设置` — `Updated book request automation settings`（影响 `应用程序设置`）、`Updated author enrichment configuration`、`Updated author metadata preferences`
  - `书籍` — `Deleted "《书名》" (#452)`（影响 `1 书`）、`Moved books to library #9`、`Wrote metadata to file and renamed book #301`、`Updated metadata and locks for book #324`、`Refreshed metadata for book #324`
  - `库` — `Updated library #3`（影响 `书库 #3`）
  - `集成` — `Renamed Kobo device #1`
- 采集时共渲染 274 行（含时间轴，最早可见约 11 天前）。

#### 3.9.39 服务器 → 用户与权限 → OIDC / SSO（`/settings/admin/oidc`）

说明文案：「单一签字提供者、索偿和预留。」

- **提供商** → **添加提供商**；采集时空态「尚无提供商 — 添加 OIDC 提供商，为您的用户启用单点登录。」

#### 3.9.40 服务器 → 用户与权限 → 帐户活动（`/settings/admin/account-activity`）

说明文案：「用户阅读和会话活动。」

- 统计卡：`最近激活 1` / `多曼特 0` / `没有记录的活动 0` / `已禁用 0`。
- **筛选**：搜索账户；**活动状态**（所有活动状态 / 最近激活 / 多曼特 / 没有记录的活动 / 已禁用）；**身份验证方法**（所有身份验证方法 / 本地的 / 管理员已创建 / OIDC / SSO / 共享的魔法链接）；**排序账户**（最近激活 / 最近最少激活 / 最近登录 / 最新账户 / 最早的帐户）。
- **账户表**列：名称、应用、用户、**帐户状态**、**上次登录**、**上次验证**、**已创建**、**正在读取洞察力**（可下钻到 `/settings/admin/account-activity/:userId/insights`）。
  实测唯一行：`Yaya` / `@Stromboid · 本地的` / 最近激活 / 上次登录 15 分钟前 / 上次验证 此刻 / 已创建 `2026年9月7日` / 洞察力 `未共享`。

#### 3.9.41 服务器 → 用户与权限 → 魔法链接（`/settings/admin/magic-links`）

说明文案：「无密码共享和登录链接。」

- **活动链接** + **创建链接**；采集时空态原文「未找到可共享账户 — 请先前往 `用户页面` 创建共享账号，方可生成免登录链接。」（即魔法链接只能授予「共享」性质的账号）。

### 3.10 外部集成与非 `/api` 端点

实例除 `/api/v1/*` 外还对外暴露若干**面向第三方客户端**的协议端点，均返回 200（无需前端参与）：

| 路径 | 用途 | 证据 |
| --- | --- | --- |
| `/opds` | OPDS 目录订阅源（Kobo/KOReader/第三方阅读器/Calibre 等可订阅）；账户与排序档位见 §3.9.29 | curl 200 + 设置页 ENDPOINT |
| `/komga/api/v1/libraries` 等 | **Komga API 兼容层**，可被 Komga 客户端（如 Komf、Tachiyomi 系）直接读取 | curl 200 |
| `/koreader/*` | KOReader 进度同步与 BookOrbit 插件后端 | 设置页「KOReader 同步 URL」+ curl 200 |
| `/kobo/*` | Kobo 同步端点（书架映射、存储代理、KEPUB 投递） | 设置页「同步端点」+ curl 200 |

其他集成观察：

- **无** `/api/health`、`/api/auth/me`、`/api/docs`（均 404）——健康检查与 API 文档未暴露在默认路径。
- **鉴权为 Cookie 会话**：在页面上下文中 `fetch('/api/v1/libraries', { credentials: 'include' })` 直接 200，无需 `Authorization` 头。SPA 与 OPDS/Komga 之外的调用都走这条链路。
- **CSP 白名单**（`Content-Security-Policy`）仅放行 `cdn.jsdelivr.net`、`api.dictionaryapi.dev`、`*.wiktionary.org`、`translate.googleapis.com` 等外部域；`frame-src 'self' blob:`。
- `/theme-init.js` 为**阻塞式**内联主题预置脚本，在首屏渲染前写入主题类，避免 FOUC（与「外观 → 主题」设置配套）。
- 静态资源规模：单页 HTML 引用 **195 处**静态资源，重度代码分割（路由级 chunk）。

#### 3.10.1 源码证据：外部同步集成的契约形态

上表三行（`/koreader/*`、`/kobo/*`、以及设置页的 ACCOUNTS 三项）在 `packages/types` 中有**同构的字段级契约**，可据此判定这三项集成的**真实能力边界**：

**（a）Hardcover —— 双向同步，含导入侧（源码：`packages/types/src/hardcover.ts`）**

- 同步方向是**双向**：既有推送（`HardcoverSettings.autoSyncOnStatusChange / autoSyncOnProgressUpdate / autoSyncOnRatingChange`、`bookSyncMode: "all_eligible" | "selected_only"`、`privacySettingId`），也有**从 Hardcover 导入书单/进度**（`HardcoverImportPreviewRow`、`HardcoverImportPreviewOutcome = "will_update" | "needs_review" | "conflict" | "unmatched" | "skipped"`、`ApplyHardcoverImportPayload`、`HardcoverImportApplyResult`）。
- 单书开关是**三态覆盖**：`HardcoverBookSyncOverride = "included" | "excluded" | null`；不生效的原因被枚举化：`HardcoverBookSyncEffectiveReason = "permission_denied" | "missing_token" | "user_disabled" | "global_disabled" | "not_selected" | "excluded" | "unread" | "unsupported_status"`。
- 版本关联是**一等对象**：`HardcoverEdition`（`isbn10/isbn13/pages/publisher/coverUrl` 等）+ `SetHardcoverEditionPayload`，并有 `HardcoverLinkedBook.matchMethod`。
- 匹配方式枚举：`HardcoverImportMatchMethod = "hardcover_id" | "isbn" | "title_author"`。

**（b）StoryGraph —— 凭据是「复用浏览器 Cookie」，能力明显窄于 Hardcover（源码：`packages/types/src/storygraph.ts`）**

- 凭据不是 API token，而是 **session cookie + remember token**（`UpsertStorygraphSettingsPayload.sessionCookie` / `rememberToken`），与实例文案「StoryGraph has no public API」**互相印证**（实例文案为 `历史实测（2026-09-19）`）。
- **只有推送，没有导入侧**：类型文件里不存在任何 import/preview 结构，仅 `StorygraphBookSyncNowResult` / `StorygraphActiveSyncStatus` / `StorygraphSyncFailure`。
- 不生效原因：`StorygraphBookSyncEffectiveReason = "permission_denied" | "missing_cookies" | "user_disabled" | "global_disabled" | "not_selected" | "excluded" | "unread" | "unsupported_status"`。
- 版本标识是**字符串 id**（`StorygraphEdition.id: string`），而 Hardcover 用**数字 id**——两者上游数据模型不同源，不可互相套用。

**（c）Readwise（源码：`packages/types/src/readwise.ts`，文件短）**

- 契约面最小：`ReadwiseSettings` + `disabledReason`，单向（把高亮推送到 Readwise），无导入、无版本关联、无单书覆盖。

**（d）KOReader —— 不是「一处同步」，而是四套并列通道（源码：`packages/types/src/koreader.ts`）**

| 通道 | 证据字段 | 要点 |
| --- | --- | --- |
| 进度同步 | `KoreaderBookSyncInfo.canonicalPercentage / canonicalSource: "koreader" \| "web_reader"` | **单一权威进度**，来源在 KOReader 与 Web 阅读器之间收敛 |
| 设备分歧 | `KoreaderBookSyncInfo.heldByReset`、`KoreaderResetHeldDevice` | 用户重置过位置后，落后设备的推送**被记录但不推进**（这是「设备和书明显不一致」的机制解释） |
| 插件目录/下载 | `KoreaderCatalogSection`（9 段：`libraries/collections/smart-scopes/authors/series/search/recent/all-books/continue-reading`）、`KoreaderCatalogManifestPage` | 设备端可浏览并**批量下载**；`restartRequired` + `fileHash` 支持中断续传 |
| 能力协商 | `KoreaderPluginCapability = "catalogBulkManifest" \| "catalogDashboardSections" \| "bookmarkSync"` | 插件与服务器按能力集协商，旧插件不报错只是少功能 |

- 未匹配书有独立实体：`KoreaderUnmatchedBook` + `KoreaderManualHashLink`（可手动把 hash 绑到书）；`KoreaderDeviceSweepInfo.requiresManualUpdate` 说明「插件太旧无法自更新」时服务器**不再提供更新**、要求手工装 zip。

> 本项目（NovelForge）现状：Hardcover / Readwise / StoryGraph **三项均未实现**，且本轮已明确不做（见 `docs/bookorbit-capability-gap.md` §13/§14）。上表仅用于说明上游真实形态，不代表本项目已有能力。

---

## 4. 核心业务域详解

### 4.1 控制台（`/`，页面标题「控制面板」）

首屏问候语随时刻变化（实测「晚上不错，Yaya」）；动作：**自定义面板**。以下为实测渲染的**面板小部件清单**：

| 小部件 | 实测内容要点 |
| --- | --- |
| 阅读连续记录 | `0 坚持天数`、`最佳: 2 天`、`过去 7 天` 空态 |
| 正在阅读 | 最多 10 条，每行 = 封面 + 书名 + 作者 + **进度百分比**；无书名条目显示「无标题」（实测 10 条中 3 条为 0% + 无标题） |
| 2026 年度阅读目标 | 空态「设置一个读取目标来跟踪您的进度」+ **设置目标** |
| 阅读 DNA | 空态「阅读至少5本书解锁你的阅读DNA」 |
| 每月挑战 | 示例挑战 `Genre Explorer`（`Read a book in a genre new to you this month`）`0 / 1` |
| 每日摘录 | 空态「在阅读时高亮显示在这里」 |
| 被埋没的佳作 | 「您所有的评分最高的书籍都已读完！」 |
| 阅读节奏 | 两周热力网格（S M T W T F S ×2）+ `活跃天数 4 活动日，坚持率 29%`、`日均阅读 10m` |
| 多样性得分 | 空态「阅读至少3本书以查看您的多样性分数」 |
| 最近添加 | 20 条新书卡片（含格式徽章，如 MP3/M4A/EPUB/PDF） |
| 丢失 | 标记为「丢失」的条目（实测有 3 条「丢失」） |
| 发现新鲜事 | 20 条推荐卡片 |
| 继续阅读 | 20 条，按格式徽章区分 EPUB/PDF/CBR/MOBI 等 |
| 继续收听中 | 5 条有声书（M4A） |

> 该页是**可自定义面板**（每块小部件可增删/重排），并非固定布局。

### 4.2 书库总览（`/libraries`）

- 动作：**筛选书库…**、**自定义顺序**（库排序模式）、**新建库**。
- 卡片流：每个库显示库名与 `书籍数量：N`；实测 9 个库（漫画 58 / 刘备 154 / 有声书 100 / 工具书 172 / 插图书 103 / 教学 17 / 杂志 3 / 其他 4 / 连环画 2）。

### 4.3 系列（`/series`）

- 顶部：`(5)` 总数、**名称 ↑** 排序、**No grouping**、**筛选器**。
- 状态筛选（含计数）：`All 5` / `Reading 0` / `Unread 5` / `Complete 0` / `Gaps 0`；图例项：`Read` / `Reading` / `In library` / `Missing`。
- 卡片：`系列名 Vol.01`、系列名、作者、所属库、`1 vol` 体量。实测 5 个系列（兒玉瑪利亞文學彙編、放浪男孩、星際e美眉、母乳系列、蓝之时代 ー 一期一会ー）。

### 4.4 作者（`/authors`）

- 顶部：`(308)` 总数、**名称 ↑** 排序、**选择**、快捷筛选 `All` / `No portrait` / `2+ books` / `Added this week` / `No sort name`、**所有库**范围选择。
- 列表按**首字母分组索引**（`#`、A–Z 分段，右侧字母导航），每行 = 姓名首字母徽章 + 姓名 + `N book(s)` + 最近添加时间（如 `2周前`、`2小时前`）。
- 采集时可见数据质量问题样例：作者名污染（`PDF微信：bfwz888888`、`chenjin5.com`、`ePUBw.COM`、`SoBooKs.cc`、`PDF微信…`、`<unknown>`、`Unknown`、`Various Authors`），说明实例中存在需清洗的作者实体。

### 4.5 书库详情（`/library/:libraryId`，标题「资料库・<库名>」）

- 顶部：库名 + 书籍计数（如 `漫画 (59)`，注意与设置页 `书籍数量 58` 相差 1，说明此处按「文件/条目」维度计数）、**标题 ↑** 排序、**筛选器**、**选择**（批量模式）。
- 卡片流：每张 = 格式徽章（PDF/EPUB/CBR/MOBI/M4A…）+ 标题（超长会省略）。
- 右侧**字母索引导航**（`#`、A–Z，含中文拼音首字母与汉字条目）。
- 不存在的库 id：页内提示 `未找到 书库` / `该 书库 不存在或已被删除` + **后退**。
- 实测 id 映射：`有声书=2 漫画=3 插图书=4 教学=5 连环画=6 工具书=7 杂志=8 其他=9 刘备=10`。

### 4.6 书籍详情（`/book/:bookId`，即 `?tab=details`）

顶部标题格式为 `书籍・<标题> · BookOrbit`。页签：**详细信息 / 编辑元数据 / 文件 / 阅读日志 / 高亮**。

- 头图区：封面、标题、系列/作者、**进度百分比**、`Unread` 状态徽章、**个人评论**（简述会展示在卡片上）、**阅读** 按钮。
- `YOUR REVIEW` — `Not written yet` + **Write**（个人书评）。
- `YOUR READING` — `not started` / `No reading sessions yet.`，说明原文：`Opening this book in the reader tracks time, pace and per-device progress.`
- `DETAILS` 字段表：出版社、出版日期、语言、页数、ISBN、文件大小、书库、添加日期、开始日期、完成日期。
- `EDITIONS` — 版本聚合（如 `1 · 791 MB`，逐条列格式与体积）。
- `相似书` — 相似度推荐区。

### 4.7 编辑元数据（`/book/:bookId?tab=edit`）

顶部标题 `编辑元数据・<标题> · BookOrbit`。这是本实例**最强的单书编辑工作台**：

- 操作条：`SCORE 28`（元数据得分，下方标 `8 empty fields`）、**从文件加载**、**写入文件并重命名**、**搜索**、**自动填充**、**保存**。
- 封面区：**文件** / **网址** / **选择图片…** / **在线查找封面** / **重新生成封面**。
- 分区分组：`IDENTITY`（标题、字幕、作者、系列、出版社）、`GENRES`（标签）、`CATALOG`（语言、发布日期、年份、页面计数、ISBN-13、ISBN-10、评分、提供商 ID `0/9`）、`GOOGLE BOOKS`/`GOODREADS`/`AMAZON`/`OPENLIBRARY`/`ITUNES`/`AUDIBLE`/`COMICVINE`/`RANOBEDB`/`LUBIMYCZYTAC`（逐提供商的标识字段）、**社区评分**（`没有提供者评分`）、**描述**（文本框）。
- 右侧信息栏：`SOURCE 86 files`、`LIBRARY 漫画`、`PRIMARY PDF 11.5 MB`、`WRITE-BACK Off`、`LAST WRITTEN Never`，下方为该书全部文件列表（格式 + 体积，逐条可选为主文件）。

### 4.8 文件（`/book/:bookId?tab=files`）

- 面包屑：书名 / 库名 / 上级目录集名（如 `作为恐怖游戏中的女仆生存（1-110话）`）。
- 汇总：`FILES 86` / `TOTAL 791 MB` / `FORMATS 1` / `ALL PRESENT`；动作 **添加文件**。
- 分组：`grouped by reader` → `DOCUMENT 86 · 791 MB`，逐文件行 = 格式徽章 + 文件名 + 体积 + **阅读** 按钮。
- 说明：一个「书」可以是**文件夹式多文件条目**（本实例 86 个 PDF 同属一本书）——即「条目 = 逻辑书，文件 = 物理卷/话」。

### 4.9 收藏夹（`/collections`，标题「收藏夹」）

**页面（历史实测（2026-09-19））**：动作 `筛选合集…`、`自定义顺序`、`新建收藏`；计数 `0`；空态 `尚无收藏` / `收藏群组你手上挑选的书籍。`

**数据模型（源码：`packages/types/src/collection.ts`）**：集合是一等实体，字段含 `isPublic`（公开性）、`displayOrder`（自定义顺序的依据）、`bookCount` / `memberCount`（两种计数口径并存）、以及 **`syncToKobo`**。

- `syncToKobo` 解释了实例中 Kobo 设置页的原文口径：「必须先在对应**合集**上开启『同步到 Kobo』」——**同步的粒度是集合，不是书库**（实例文案为 `历史实测（2026-09-19）`，源码字段为其机制依据）。
- 集合同时是 KOReader 插件的目录段之一：`KoreaderCatalogSection` 含 `"collections"`（源码：`packages/types/src/koreader.ts`），即集合不仅影响 Web 侧与 Kobo，也影响设备端目录。
- `isPublic` 与实例的「隐私与共享」三档（非公开的 / 分享摘要 / 分享详细的看法，见 §3.9.14）**是否直接联动**：未验证（源码无法确认，本轮未取 `server/src/modules/*` 与账号隐私模块）。

### 4.10 智能书架（`/smart-scopes`，标题「智能书架」）

**页面（历史实测（2026-09-19））**：动作 `筛选智能书架…`、`自定义顺序`、`新建智能瞄准镜`；计数 `0`；空态 `尚无智能书架` / `智能书架保存您经常使用的一组过滤器。`

**数据模型（源码：`packages/types/src/smart-scope.ts`）**：智能书架 = 「过滤条件 + 默认排序」的持久化组合：

- **过滤条件**是一个结构化的 `GroupRule`（可嵌套的条件组），不是查询字符串；这与实例页内「默认显示过滤器预览」（§3.9.6：打开智能书架时展开当前筛选与排序摘要）能对上。
- **默认排序**是 `SortSpec[]`（多级排序），即进入智能书架后看到的排序来自其自身配置，而非全局偏好。
- 同样带 **`syncToKobo` / `koboSyncEnabled`** 两个字段；且 `KoreaderCatalogSection` 含 `"smart-scopes"`（源码：`packages/types/src/koreader.ts`）——智能书架与收藏夹一样，是**跨端可见对象**（Web / Kobo / KOReader 三端）。
- 与「收藏夹」的区别（源码可确认部分）：收藏夹是**手工挑选的成员集合**（有 `bookCount` 与 `memberCount` 两个计数），智能书架是**保存的规则**（`filter` + `defaultSort`），成员由规则实时求出——这正是实例「计数 `0` 但可新建」不矛盾的原因（空规则库为空，规则本身仍存在）。
- 智能书架的**编辑界面结构**（条件组如何增删、是否支持嵌套层级 UI）：未验证（源码无法确认，本轮未取 `client/`）。

### 4.11 批注（`/annotations`）

**页面（历史实测（2026-09-19））**：空态原话 `暂无批注。突出显示您在网页上创建的内容或您的电子阅读器出现在这里。`；三张来源引导卡 **Read here**（`Select text in the reader and pick a colour.`）、**Sync a Kobo**（`Marks made on the device arrive on the next sync.`）、**Sync KOReader**（`The plugin uploads annotations with their positions.`）；另有 **Go to the library** 入口。

三张引导卡与源码的**三方来源枚举一一对应**（源码：`packages/types/src/annotation.ts`）：`AnnotationItem.origin = "web" | "koreader" | "kobo"`——即「在网页里划」「Kobo 同步来」「KOReader 插件传」，没有第四种来源。

**配色模型是三套 + 双向回退映射**（源码：`packages/types/src/annotation.ts`）：

| 常量 | 数量 | 说明 |
| --- | --- | --- |
| `KOBO_HIGHLIGHT_COLORS` | 4 | Kobo 设备原生可选色，是**最窄**的一套 |
| `KOREADER_HIGHLIGHT_COLORS` | 9 | KOReader 配色，每色带 `koboFallback`（回落到 Kobo 4 色之一） |
| `ANNOTATION_HIGHLIGHT_COLORS` | 10 | 应用内（Web 阅读器）配色，每色带 `koreaderFallback` + `koboFallback` |

- 机制含义：**应用内 10 色 → KOReader 9 色 → Kobo 4 色**是逐级收敛的投影。任何一次跨端同步都可能**降色**（例如把 Web 侧的某色映射到最接近的 Kobo 色），但不会有「颜色丢失」的空值。
- 与成就系统的交叉点：成就 `Box of Crayons — Use all 5 highlight colors`（见 §4.13）说的是 **5 色**，而应用内配色常量为 **10 色**——两者不是同一套计数口径。**成就的 5 色具体对应哪 5 个色值**：未验证（源码无法确认，需 `server/src/modules/achievement` 的判定逻辑）。

**批注中心（Hub）的结构与统计**（源码：`packages/types/src/annotation.ts`）：

- **分组模式枚举**：`ANNOTATION_HUB_GROUP_MODES = ["month", "book", "color", "source"]`——批注可按**月份 / 书 / 颜色 / 来源**四种维度分组；实例页面在空态下不渲染这些控件，故**这四种分组的 UI 形态**：未验证（源码无法确认）。
- **总览对象 `AnnotationHubOverview`** 含：`needsReview`（待复核）、`trashed`（垃圾桶）、`weeks`（周维度数据）、`longestQuietWeeks`（最长「静默周数」）、`devices`（来源设备）。
- 由此可确认三条业务语义：
  1. 批注有**待复核**状态——与 Kobo/KOReader 回传的批注可能需要对账；
  2. 删除是**软删除**（进垃圾桶，可恢复），不是直接抹除；
  3. 统计以**周**为节拍，并专门跟踪「连续多少周没有新批注」（`longestQuietWeeks`）——这是给「阅读中断」叙事用的指标，不是存储指标。
- 「按书聚合」（在某本书详情页看该书批注）：源码中 `origin` 与 `devices` 均存在，书维度的聚合由 `ANNOTATION_HUB_GROUP_MODES` 的 `"book"` 承担；**详情页内的批注页签（§4.6 的「高亮」）与 Hub 页的数据是否同源**：未验证（源码无法确认）。

### 4.12 统计（`/statistics`，标题「统计」）

页签：**知识库统计 / 我的阅读 / 所有库**；右上 **配置**。

- **总览卡**：书籍总量 `653`、作者 `308`、系列 `5`、出版社 `64`、存储 `1.41 TB`、Genres `319`、语文 `11`、已发布 `2000 - 2026`、本年 `653`、已启动 `26`、进行中 `25`、已完成 `1`、平均进度 `10.6%`。
- **库的完整性**：`Integrity 98% Present`、`94% 613/653 Primary`、`100% 653/653 Metadata`。
- **格式分布**：PDF / EPUB / M4A / MP3 / AZW3 / CBZ / MOBI / CBR。
- **元数据分数**直方图（0–9 … 80–89 分桶，含 `P50` / `P90` 参考线）。
- **元数据淡化（Freshness）**：`Total 653`、`Fresh ≤30d 392 60%`、`Never fetched 261 40%`。
- **前 50 本大书**（按体积排序，实测榜首为百科/索引类巨册，最大 1.68 GB）。
- **流派分布**（Top 列表，带百分比）；**随着时间的推移格式共享**（按月 × 格式堆叠）。
- **前 25 位作者**（双轴：Books + Cumulative %，上图为「元数据完成度」口径）。
- **获取标签（Lag (y)）**：Published 年份 vs 抓取延迟的散点图。
- **库元数据的完整性**：以库为行、以 `Title/Cover/Author/Genres/Tags/Description/Publisher/Year/Language/Page Count/Rating/Series/ISBN` 为列的完成度热力矩阵。

### 4.13 成就（`/achievements`）

- 计数：`已达成等级：9/87`；筛选：**所有的 / 已获取（8 项）/ 进行中（11 项）/ 未解锁（49 项）**。
- **稀有度档位**：`常用的`（common）/ `稀有的`（rare）/ `史诗文`（epic）/ `传奇语`（legendary）/ `秘密成就`（显示为 `???`）。
- **等级制**：多数成就为 4 级（`等级进度：1/4`，并显示「距离 <下一级名>：N/M」）。
- 四个分类及本例进度：**Reading `4 / 28`**、**Library `3 / 23`**、**Exploration `0 / 18`**，其余为第四类（合计 87）。
- 成就样例（原文条件）：
  - Reading：`Ink Initiate — Finish your first book`、`First Leaves — Read 500 pages`、`Hour Initiate — Read for 10 hours`、`Marathoner — Complete a reading session of 90 minutes or more`、`All-nighter — Read between 1am and 4am`、`Early Bird — Start a reading session between 5am and 7am`、`Story Stretch — Finish a book with 300 or more pages`、`Sprint — Finish a book in a single day`、`Binge Reader — Finish 3 or more books in a single week`、`Monthly Machine — Finish 10 books in a single calendar month`、`Slow Burn — Take over 90 days from start to finish a book`、`One Sitting — Cover 90% or more of a book in a single reading session`、`Power Hour — Read 75 or more pages in a single reading session`、`Speed Reader — Read 100 or more pages in a single day`、`Old Friend — Finish a book you were re-reading`
  - Library：`Collection Architect — Have 250 books in your library`、`Note Taker — Create 10 annotations`、`Multi-Format — Own books in 3 or more different formats`、`Curator — Create 10 or more collections`、`Note Keeper — Create 25 annotations that include a note`、`Deep Dive — Create 10 annotations in a single day`、`Bookmarked — Create your first annotation or highlight`、`First Verdict — Rate your first book`、`Fledgling Critic — Rate 10 books`、`Standing Ovation — Give a book a 5-star rating`、`Across the Board — Use all five star ratings at least once`、`Wordsmith — Write a note longer than 280 characters`、`Box of Crayons — Use all 5 highlight colors`
  - Exploration：`Genre Curious — Finish books in 5 different genres`、`Bilingual — Finish books in 2 different languages` …
- 达成时间会直接显示在卡片上（如 `获得时间：2026年9月8日`）。

#### 4.13.1 源码证据：分类、稀有度与字段语义（源码：`packages/types/src/achievement.ts`）

- **分类是 5 个，不是 4 个**：`"reading" | "library" | "exploration" | "dedication" | "devices"`。
  实例页只渲染出 **Reading / Library / Exploration** 三组标题 + 一组未列名的分类（合计 87 项）；源码给出的完整集合含 **`dedication`（坚持）** 与 **`devices`（设备）** 两类。**页面为何未渲染 `dedication` / `devices` 的分组标题**：未验证（源码无法确认，属 `client/` 界面结构问题）。
  > 这与设置页「时区用于处理对时间敏感的成就，例如『早鸟』和『通宵达人』」（§3.9.1，`历史实测（2026-09-19）`）互相印证：`All-nighter` / `Early Bird` 这类按**本地时段**判定的成就必须依赖用户时区。
- **稀有度是 4 档**：`"common" | "rare" | "epic" | "legendary"`，与实例页面中的 `常用的 / 稀有的 / 史诗文 / 传奇语`（后两者中文带机翻痕迹）**逐档对应**。
- **`AchievementItem` 字段级语义**：

| 字段 | 语义 |
| --- | --- |
| `groupKey` | 所属分类键（对应上面 5 个分类之一） |
| `tier` | 当前档位（多数成就是 4 级，对应实例 `等级进度：1/4`） |
| `threshold` | 该档位的达成阈值（对应实例「距离 <下一级名>：N/M」的 M） |
| `currentProgress` | 当前进度（对应 N）——即**进度是服务端算好的数值**，客户端只做展示 |
| `hidden` | 隐藏成就（对应实例 `秘密成就` 显示为 `???`） |
| `sortOrder` | 组内排序（页面不按字典序，按此字段） |
| `earned` / `awardedAt` | 是否达成 / 达成时间（对应实例 `获得时间：2026年9月8日`） |
| `context` | 达成上下文（如具体是哪本书/哪次会话触发）——**该字段在页面上如何呈现**：未验证（源码无法确认） |

- **回填机制**：设置页「维护 → 成就 → 回填成就 / 运行回填」（§3.9.26，`历史实测（2026-09-19）`）说明成就可**全量重算**，与 `threshold` + `currentProgress` 的服务端计算模型一致——即成就是**派生数据**，不是一次性的打卡记录。

### 4.14 Book Dock（`/book-dock`，标题「Book Dock」）

- 动作：**暂停**、**重新扫描**、**上传**。
- 计数卡：`全部 0 / 待审核 0 / 待处理 0 / 就绪 0 / 错误 0`。
- 空态：`Book Dock 中没有文件` / `上传文件或将其拖放到书签文件夹` / `或将文件拖放到这个页面的任意位置。`
- 定位：与「服务器 → Book Dock」设置配合的**上传/落库暂存区**（拖入即自动提取+按配置获取元数据）。

### 4.15 新功能（`/whats-new`，标题「新功能」）

- 结构：左侧版本列表 `v2.10.0 / v2.9.0 / v2.8.1 / v2.7.0 / v2.6.0 / v2.5.0 / v2.4.0 / v2.3.0 / v2.2.0 / v2.1.0 / v2.0.1`，当前版本标注「你在这里」，右侧为逐版本变更条目；底部 **显示完整更新日志** / **在 GitHub 上打开**。
- 已抓取的关键版本条目（原文摘要）：
  - **v2.10.0（2026年9月14日）**：`Expanded book request automation`（Usenet via Newznab/NZBGet + torrent、可定制发布评分配置、按索引器的做种目标、应用内索引器插件更新）、`Flexible "Date Added" sources`（入库时间/文件修改时间/文件创建时间，一键重算）、`Collapsible series on author pages`、`Configurable listen address`（`HOST` 环境变量绑定 IPv4/IPv6）。
  - **v2.9.0（2026年9月7日）**：`Automated book requests`（请求→审批→搜索→经 Book Dock 导入）、`PDF highlights and annotations`（Web 阅读器可创建/样式化/搜索/回访/删除 PDF 高亮与笔记）、`More control over EPUB typography`（段间距与缩进，保留出版方格式，全局默认 + 单书覆盖）、`SSO-only authentication`（要求 OIDC 登录，API/WebSocket/管理动作一并封堵密码流）、`Safer automatic metadata refreshes`（有可信提供商 ID 的书只从这些身份刷新）。
  - **v2.8.1（2026年8月29日）**：`Redesigned book detail tabs`（详细信息/编辑元数据/文件/阅读日志/高亮改为单屏布局，阅读日志与高亮在切换页签时保持挂载以避免加载闪烁）、`Bulk rename and missing-resource cleanup tools`（批量重命名提供**服务端搜索、虚拟化选择、内联文件名 diff、树形视图**）…（后续版本条目见实例页面）

**源码证据（源码：`packages/types/src/release-notes.ts`）**：

- 逐版本条目由 `ReleaseNote` / `ReleaseHighlight` 承载——**每个版本内还有「高亮条目」子结构**，对应实例页里每条变更的标题+正文两级呈现。
- 媒体是**白名单化**的：条目中的图片/视频指向 GitHub（allowlist），即更新日志的富媒体不是任意外链，而是受控来源。**白名单的具体域名与允许的媒体类型**：未验证（源码无法确认，需读取该文件中的 allowlist 常量）。
- 存在独立偏好对象 `WhatsNewPreferences` ——与「个人 → 通知 → 应用更新」（`在更新后显示"新建内容"`，§3.9.13，`历史实测（2026-09-19）`）对应，即「是否自动弹出新功能」是一个**持久化偏好**，而不是每次升级都强制弹窗。
- 「底部 **显示完整更新日志** / **在 GitHub 上打开**」两个入口指向**实例外的 GitHub 页面**，是 CSP `connect-src` 白名单之外的**普通导航**（跳转不被 CSP 拦截，因为不是 fetch）——`历史实测（2026-09-19）` 记录了两个入口存在，源码层面其 href 构造方式：未验证（源码无法确认）。

### 4.16 Requests（`/requests`，标题「Requests」，Beta）

- 标题区原文：`Ask for books the library does not have yet. This feature is experimental, expect minor bugs.`
- 无源告警原文：`No search sources are set up. Requests can be filed, but nothing will be searched for them until you add an indexer or install a source plugin.` + **Add a source**。
- 页签：**search（申请一本书）/ my requests（0）/ all requests（0）**。
- **申请表单字段**：`Title`、`Author`、`Search`、**Format**（`E-book` / `Audiobook` / `Comic`）、**Fulfillment**（`Automatic` / `Choose a release` / `Add to library`）、**目标库**（默认 `其他`，可选全部 9 库）、**Request language**（`Any language` + 67 种语言，含中文/英语/日语等）、**More options**。
- 依赖链：Requests → **服务器 → Requests → Sources/Download clients/Automation** 配置（见 §3.9.35），完成后经 **Book Dock** 入库（见 §4.14）。

#### 4.16.1 源码证据：状态机、集合语义与错误码（源码：`packages/types/src/book-request.ts`）

**（a）11 个状态**（`pending` / `approved` / `rejected` / `cancelled` / `searching` / `grabbed` / `downloading` / `importing` / `needs_review` / `available` / `failed`）并非线性管道，而是**按「谁能推进它」切成六组集合**：

| 集合 | 成员 | 语义 |
| --- | --- | --- |
| `ACTIVE`（7） | 仍在流程中的状态 | 「活跃请求」的判定依据 |
| `GRABBABLE`（3） | `approved` / `searching` / `failed` | **还能再抓一次**的状态；`failed` 可重试是显式设计 |
| `FULFILLABLE`（8） | 可由满足动作推进 | `Add to library` 这类人工满足的适用范围 |
| `CANCELLABLE`（8） | 可由用户取消 | 与 `FULFILLABLE` 并不等同 |
| `WORKER_WRITABLE`（8） | 后台 worker 可写入 | **worker 不越权**改写已结算请求的护栏 |
| `SETTLED`（4） | `rejected` / `cancelled` / `available` / `failed` | 终点；注意 **`failed` 同为「可再抓」与「已结算」**——结算指本次尝试结束，不是请求终结 |

> 实例页签 `my requests (0)` / `all requests (0)` 的计数来自 `BookRequestSummary` 的 **5 个计数字段**（`pending` / `active` / `mine` / `mineTotal` / `allTotal`）——即「我的」与「全部」是两个独立计数，且总览另有 `pending` 与 `active` 两个口径。

**（b）三类错误码，职责分离**（源码：同一文件）

| 常量 | 数量 | 回答的问题 |
| --- | --- | --- |
| `BOOK_REQUEST_SUBMIT_ERROR_CODES` | 10 | **提交**请求时为何失败 |
| `BOOK_REQUEST_ACTION_ERROR_CODES` | 5 | **对已有请求执行动作**时为何失败 |
| `BOOK_REQUEST_HANDBACK_CODES` | 12 | 请求**交还给管理员/自动化**（handback）的原因——最多的一类，说明「卡住需要人介入」的分支被枚举得最细 |

**（c）容量与排序**：`BOOK_REQUEST_BULK_LIMIT = 100`（批量操作上限）、`BOOK_REQUEST_SORT_FIELDS`（允许的排序字段白名单）——两者都是**硬编码边界**，不是前端自由发挥。

**（d）抓取侧：4 类下载客户端 + 3 种投递方式**（源码：`packages/types/src/download-client.ts`）

- `DOWNLOAD_CLIENT_TYPES = ["qbittorrent", "transmission", "deluge", "nzbget"]`；`DownloadDelivery = "torrent" | "file" | "usenet"`，且 `DOWNLOAD_CLIENT_DELIVERY` 固定映射（前三个是 torrent，nzbget 是 usenet）。
- **投递方式决定用哪个客户端**，而不是「取优先级最高且启用的那一个」——这是源码注释明写的设计意图（torrent 客户端不能取 URL，普通下载器不能入 swarm）。
- 抓取来源 4 种：`BOOK_REQUEST_DOWNLOAD_SOURCES = ["magnet", "torrent_file", "direct_url", "nzb_file"]`，各自对应一种投递方式。
- 下载尝试的**7 个状态**自成一套（`queued / downloading / completed / importing / needs_review / imported / failed`），**与请求的 11 状态不是同一枚举**：请求里写的是 `available`，下载里写的是 `imported`。
- 另有 `UNSETTLED_BOOK_REQUEST_DOWNLOAD_STATUSES`（= 在途 4 态 + `needs_review`）作为「写状态时仍可改写」的条件；`IN_FLIGHT`（4 态）用于「从客户端移除即等于放弃该尝试」。

**（e）抓取失败的「影响半径」是枚举化的**（源码：`packages/types/src/download-client.ts`）

- `GRAB_FAILURE_CODES` 6 个：`GRAB_SOURCE_REFUSED`、`GRAB_VIP_REQUIRED`、`GRAB_SOURCE_UNAVAILABLE`、`GRAB_CLIENT_REFUSED`、`GRAB_CLIENT_UNAVAILABLE`、`GRAB_RELEASE_REFUSED`。
- 其中仅 `SOURCE_WIDE_GRAB_FAILURE_CODES = ["GRAB_SOURCE_REFUSED", "GRAB_SOURCE_UNAVAILABLE"]` 会**跳过该源其余全部发布**；VIP 拒绝只影响 VIP-only 的发布；**客户端级拒绝按投递方式隔离**（`GRAB_CLIENT_*` 只对同一 `delivery` 生效，且 `file` 投递不受任何客户端故障影响）。
- 判定函数 `findGrabRefusal` 被**自动化与发布选择器共用**（源码注释明确：同一屏的同一份拒绝清单，自动化不再试、选择器不再给），避免两处逻辑漂移。

**（f）索引源：通用协议内建，具体站点一律外挂**（源码：`packages/types/src/indexer.ts`）

- `INDEXER_ADAPTER_TYPES = ["torznab", "newznab"]`——**只有通用协议**；注释原文口径：BookOrbit 只发 adapter 代码，从不内置任何 tracker、任何凭据、任何默认启用的索引源。
- 差异点：`INDEXER_SEEDS_BACK`（torznab `true` / newznab `false`）、`INDEXER_DELIVERY`（torznab `torrent` / newznab `usenet`）、两者 `credentialKind` 均为 `apiKey`、`usesCategories` 均为 `true`、`mediaKinds` 均为全部三种（ebook/audiobook/comic）。
- `INDEXER_MEDIA_KINDS` 与「按源禁用媒介」（`IndexerItem.disabledMediaKinds`）**成对**存在：一个源「声明支持三种」与「只允许被搜两种」是两件事，实例设置页的 `Sources` 文案（§3.9.35）正是这一模型的外化。
- 插件机制有**完整的供应链字段**：`PluginUpdateChannel`（`manifestUrl` + `ed25519PublicKey`）、`PluginUpdateState = "unsupported" | "unchecked" | "current" | "available" | "custom" | "failed"`、`PluginInspection`（含原文件源码 + `replaces`）、`PluginInstallResult.active`（装完即用，只有「文件在盘上但加载失败」才为 `false`，重启可重试）。
- `INDEXER_ERROR_CODES` 含 `INDEXER_URL_UNSAFE` / `INDEXER_URL_PRIVATE`（SSRF 防护）与 `REQUEST_CREDENTIAL_ERROR_CODES`（凭据加密未配置）。
- 发布评分理由是**枚举 + 带符号分值**（`RELEASE_SCORE_REASONS` 11 项，如 `isbnMatch` / `titleMatch` / `preferredFormat` / `suspiciousSize` / `freeleech` / `likelySeveralBooks`），由服务端给 `points` 与可选 `detail`、前端本地化成句——**打分过程是可解释的，不是黑盒**。
- 搜索结果**不含下载地址**：`ReleaseCandidateItem` 刻意不带 URL，抓取只提交 `indexerId` + `releaseGuid`，URL 由服务端从自己的搜索结果解析——源码注释明写目的是「客户端无法把下载器指向它自己选的地址」。

**（g）媒介与目标库（源码：`book-request-destination.ts` / `book-request-preferences.ts` / `book-request-review.ts`）**

- 目标位置是**按媒介（media kind）分别配置**的 `RequestDestination` 结构，对应实例表单里的「目标库」+「Fulfillment」组合。
- `book-request-preferences.ts` 含 `defaultLanguage`——对应实例的 `Request language`（默认 `Any language` + 67 种语言）。
- `book-request-review.ts` 定义人工复核载体（校验字段与原因），是 `needs_review` 落在**人可读的复核对象**而非裸状态字符串上的依据。

**（h）`my requests` / `all requests` 的列结构**：未验证（源码无法确认，两页的表格列由 `client/` 决定，本轮未取该目录）。

### 4.17 磁盘工具（`/tools/*`，外壳标题「实体管理器」）

工具页侧栏统一为四个工具：**实体管理器 / 批量重命名 / 复制书 / Missing Resources**。

#### 4.17.1 实体管理器（`/tools/entity-manager`）

- 子页签：**作者（浏览与管理）/ 查找重复项**；范围选择 `All / No books`。
- 表列：`Name` / `SORT NAME` / `Books` / `STATUS` / `Actions`；分页 `Rows per page 25`、`Showing 1-25 of 308`、共 13 页。
- 实测可直接暴露数据质量问题：`8082Audio`、`chenjin5.com`、`ePUBw.COM`、`by 汪远`、`liuchangshun123`、`luqi7540（无忧）`、`littlebaka（接约稿）`、带制表符的 `-\t1` 等异常作者名。

#### 4.17.2 批量重命名（`/tools/bulk-rename`）

- 先 **选择要开始的库**（9 个库平铺为按钮）。
- 说明原文：`选择上面的库来预览更改，按状态筛选，并应用批量重命名运行。`（即「先预览再应用」）

#### 4.17.3 复制书 / 重复检测（`/tools/duplicate-books`）

- 范围：`书库范围 = 所有可用库` 或单选某库；**相似标题阈值 `85%`**；动作 **运行扫描**。
- 安全口径原文：`扫描可能重复记录的文件和元数据。扫描时没有删除任何记录。`、`选择一个库的范围和相似度，然后运行扫描。在您明确确认删除之前，不修改任何书籍。`

#### 4.17.4 Missing Resources（`/tools/missing-resources`）

- 顶部 **开始扫描**；说明原文：`扫描会在磁盘上重新检查每个记录并标记任何不再存在的项目。`
- 扫描范围可勾选：书库文件 / 封面 / 阅读器（字体、插图、缓存）等资源类别。

### 4.18 阅读器（`/read/:bookId/:fileId?format=<fmt>`）

- URL 形态：`/read/{bookId}/{fileId}?format=pdf|epub|cbz|cbr|mobi|azw3|mp3|m4a`；缺 `format` 时页面尝试猜测并可能落到 `Failed to fetch EPUB info: 404` 之类的错误态（**必须带 format**）。
- **PDF 阅读器实测**（`/read/728/31189?format=pdf`，标题 `10 第10話 · BookOrbit`）：
  - 顶部工具条按钮（aria-label / title）：`后退`、`Previous page`、`Next page`、`Zoom out`、`Zoom in`、`Pan tool`、`Select text tool`、`输入全屏`、`More PDF tools`、`PDF settings`、`Pages`、`Contents`、`Search`、`注`
  - 状态区显示 `页码 / 总页数`（实测 `/ 20`）与缩放百分比（实测 `167%`）
  - `Select text tool` + v2.9.0 的「PDF highlights and annotations」说明支持选中文本后创建高亮/笔记
- **EPUB 阅读器实测**（`/read/386/7850?format=epub`，标题 `1-15章 人前你后宫 · BookOrbit`）：
  - 工具条按钮（aria-label）：`后退`、`目录`、`切换书签`、`搜索`、`循环页脚信息模式`、`键盘快捷键`、`输入全屏`、`阅读器设置`、`上一个部分`、`跳转到位置`、`下一节`；页脚显示「转至」与进度百分比（实测 `0%`）。
  - **工具条默认隐藏**：鼠标移入页面才显现；自动化直接点击会报「element is outside of the viewport」，需先 `mouse.move` 唤出。
  - **内置阅读器设置面板**（工具条 `阅读器设置`，标题「设置」）：主题 `亮色的 / 深色`；`字体大小`（`A` 步进，实测 `16 像素`）；`页面底色` **13 档**（`默认主题 / 灰度 / 护眼棕 / 绯红 / 青野 / 檀木红 / 天青 / 晨曦 / 烬橙 / 极光 / 深海蓝 / 薄雾灰 / 纯黑（AMOLED）`）；`字体`（`书籍默认字体 / 衬线字体 / 无衬线字体 / 等宽字体`）；`STYLE`（`常规 / 粗体 / 常规 Italic / 粗体 Italic`）；`行间距`、`PARAGRAPH SPACING`、`页面宽度`、`阅读模式`（`分页模式 / 滚动模式`）。
  - **高级排版设置**（同面板内展开）：`分栏数`（`− 2 +`）、`列间距`（实测 `5%`）、`Letter spacing`（`Book / Custom`）、`Word spacing`（`Book / Custom`）、`First-line indent`（`Book / Custom`）、`对齐文本`（开关）、`连字符断字`（开关）。
  - 面板内实测 **5 个 `input[type=range]`**，取值区间依次为 `0–1`、`0.8–3`（当前 `1.5`）、`0–2`（当前 `0`）、`400–1600`（当前 `720`）、`0–50`（当前 `5`）；后四项与「行间距 / 段间距 / 页面宽度 / 字距」对应。
  - 该面板与「个人 → 阅读器」六个设置页（§3.9.8–§3.9.13）**并列存在**：前者是阅读中的临时调节，后者是账号级默认值。
- 阅读器排版与行为由「个人 → 阅读器」六个设置页决定（§3.9.8–§3.9.13），首选项保存位置由 `/settings/reader/general` 决定。
- 阅读事件（时长、进度、设备、速度）由书籍详情「阅读日志」呈现；进度写入 `/api/v1/books/:id/progress`，会话列于 `/api/v1/books/:id/sessions`。

### 4.19 全局外壳（侧栏 / 顶栏 / 列表工具条）

**左侧栏**（自上而下）：`浏览`、`库`、`新建库`、`智能书架`、`新建智能瞄准镜`、`收藏夹`、`新建收藏`、页脚 `Star on GitHub`。

**顶栏**：`切换侧边栏`、`搜索`（全局搜索输入框，见下）、`通知`、`统计`、`成就`、`上传书`、`帮助`、`外观`、`界面语言`、`设置`、用户头像（`yaya`）。

**全局搜索（实测，`http://192.168.0.95:3400/`，界面简体中文）**：顶栏搜索**不是弹层命令面板**，而是**内联输入框**：

- placeholder 为 `搜索全部书籍…`；输入 **≥2 字**后**实时联想下拉**，每项形如「封面缩略图 + 标题 + 作者 + 格式徽章」（实测输入 `医本正经` 命中 `医本正经 / 懒兔子 / EPUB`，同批下拉还列出 `1-15章 人前你后宫 / Unknown / EPUB` 等；输入单字 `医` 时下拉不出现）。
- 下拉底部给出「显示所有 N 条结果」入口（该实例的中文文案带机器翻译痕迹，实测渲染为 `显示所有1场比赛`）。
- **回车不切换路由**（仍停在当前页，结果只在浮层内）；`⌘K` 提示在 Windows/Chromium 下实测**不聚焦**（`document.activeElement` 仍为 `BODY`）；点击顶栏「搜索」按钮**也不弹面板**（就是同一个输入框）。
- 与「**设置页**内的 `Cmd+K` 跳转面板」（§3.9，42 项）是两套独立机制：后者只在 `/settings/*` 下生效。
- 侧栏另有 `筛选书库`（placeholder）用于库列表就地过滤。

**库/列表页工具条**（同一套在库、系列、作者、收藏夹、智能书架复用）：`折叠系列`、`导出元数据`、`筛选器`、`显示库控制`、`选择`（批量模式）、视图切换 `Grid | List | Table`、`显示`（列/密度）、`快速视图`。

**书籍卡片悬浮动作**：`Start reading`（未开始）/ `Continue reading`（已开始）；卡片上有格式徽章、系列折叠、进度条。

**Toast 提示**：右下角通知条（实测如 `作者信息补充完成` / `125 项处理失败`）。

---

## 5. 接口对照表

### 5.1 每个页面都会触发的「引导集」（页面切换时重复出现）

`/api/v1/auth/setup-status` → `/api/v1/auth/login-options` → `/api/v1/auth/refresh` → `/api/v1/auth/me`
`/api/v1/user-preferences/theme`、`/api/v1/user-preferences/display`、`/api/v1/user-preferences/locale`、`/api/v1/user-preferences/whats-new`
`/api/v1/app-info`、`/api/v1/libraries`、`/api/v1/smart-scopes`、`/api/v1/collections`、`/api/v1/browse-counts`、`/api/v1/book-requests/summary`、`/api/v1/book-dock/summary`、`/api/v1/notifications?limit=20&offset=0`、`/api/v1/notifications/unread-count`

> 口径意义：侧栏计数、通知红点、侧栏动态列表全部来自这套接口，**换页即重新拉取**。

### 5.2 按业务域的端点

| 业务域 | 端点（实测） |
| --- | --- |
| 控制台 | `/api/v1/dashboard/widgets/batch`、`/api/v1/dashboard/scrollers/batch` |
| 库与书 | `/api/v1/libraries`、`/api/v1/libraries/:id/books`、`/api/v1/libraries/:id/books/jump-buckets`、`/api/v1/books/:id`、`/api/v1/books/:id/progress`、`/api/v1/books/:id/sessions?page&pageSize&sortBy&sortDir` |
| Book Dock | `/api/v1/book-dock/summary`（页面级） |
| Requests | `/api/v1/book-requests/summary` |
| 统计 | `/api/v1/statistics/...`（页面统计聚合，见 §4.12 各图表） |
| 批注 | `/api/v1/annotations...`（批注页为空态，未产生具体调用） |
| Kobo | `/api/v1/kobo/devices`、`/api/v1/kobo/settings`、`/api/v1/kobo/history?limit=20` |
| OPDS | `/api/v1/app-settings`、`/api/v1/opds-users` |
| 电子邮件 | `/api/v1/email/providers`、`/api/v1/email/recipients`、`/api/v1/email/templates`、`/api/v1/email/recipient-groups` |
| 用户/偏好 | `/api/v1/auth/me`、`/api/v1/user-preferences/*` |

> 端点均由页面真实网络流量注入钩子采集（见 §0）；方法/请求体未逐条记录，调用方一律 `credentials: 'include'`（Cookie 会话）。

---

## 6. 关键业务流程

### 6.1 登录与会话

1. 打开 `/` → `auth/setup-status` 判断实例是否已初始化（未初始化进引导）
2. 登录页 → `auth/login-options` 决定可用登录方式（含 OIDC / 魔法链接 / 自助注册）
3. 提交凭据 → 建立 Cookie 会话；进入 SPA 后 `auth/refresh` + `auth/me` 恢复用户与权限
4. 之后每次路由切换都会重跑 `/auth/refresh`（会话保活）

### 6.2 浏览 → 阅读（核心闭环）

1. 侧栏 `库` → `/libraries`（9 库卡片）→ 点库 → `/library/:id`
2. 库页 `Grid/List/Table` 切换 + `筛选器` + 字母索引定位 → 点书卡
3. 书卡直接进入阅读器 `/read/:bookId/:fileId?format=...`（**这一步不开详情页**）
4. 阅读器内翻页/缩放/高亮 → 进度写 `/api/v1/books/:id/progress`
5. 回到详情页 `阅读日志` 看会话明细，控制台「正在阅读 / 继续阅读 / 继续收听中」随之更新

### 6.3 元数据抓取与编辑（单书）

1. 详情页 → `编辑元数据` 页签（`/book/:id?tab=edit`）
2. `搜索` 按标题/ISBN 检索 → 候选来源为「设置 → 元数据 → 提供商」中启用的源
3. `自动填充` 按「字段规则」的**提供商顺序 + 合并策略**逐字段写入
4. 手工修订后**逐个字段加锁**（`编辑元数据` 内的锁标记，`0/9`、`8 empty fields` 之类计数）
5. `保存` → 只落数据库；`写入文件并重命名` 才会改磁盘（要求该库开启 `写入至文件` / `重命名文件`，本实例两者分别 关闭 / 打开）
6. `SCORE` 实时反映完成度，`统计 → 元数据分数` 直方图与 `元数据淡化` 随之变化

### 6.4 自动元数据获取（批量）

1. `设置 → 元数据 → 自动获取`：勾选启用 + 导入时触发 + 资格条件（从未获取 / 分数低于 N / 缺少指定字段）
2. 每库可覆盖全局设置并 `立即运行`（页面实时显示合格条数）
3. `作者` 页签名下另有作者级自动补充（条件：从未补充过 / 缺少简介 / 缺少照片）
4. 结果在右下角 toast（实测 `作者信息补充完成` / `125 项处理失败`）与审计日志中留痕（`Refreshed metadata for book #324`）

### 6.5 Book Dock 入库

1. 将文件**拖到 `/book-dock` 页面**或复制进容器路径 `/data/book-dock`
2. `重新扫描` → 文件状态从 `待处理` → `就绪`
3. 开启「自动获取元数据」与「自动完成（信任分 ≥ 阈值）」时直接成书；否则留在 Dock 里人工确认

### 6.6 Requests（求书）

1. `设置 → 服务器 → Requests` 先配 `Sources`（索引器插件 / Torznab / Newznab）与 `Download clients`、`Automation`
2. `/requests` → 填 Title/Author/Format/Fulfillment/目标库/语言 → `Search`
3. 审批后自动搜索并下载 → 落地 **Book Dock** → 入库
4. 注意：加密密钥必须配置，否则下载客户端密码无法保存（§3.9.35 的告警）

### 6.7 OPDS 接入

1. `设置 → 设备与同步 → OPDS` → 确认 ENDPOINT
2. `OPDS 账户` → `添加` → 生成账户与排序档位（最近添加 / 标题 / 作者 / 系列 各升降序）
3. 在第三方阅读器填 `http://<host>:3400/opds` + 账户凭据即可浏览与下载
4. 凭据泄露需轮换密码（页面原文提示）

### 6.8 Kobo 同步

1. `设置 → 设备与同步 → Kobo` → `添加设备` → 设备上填写同步地址
2. 在目标**合集**上开启「同步到 Kobo」（侧栏合集 → 编辑 → 开关），否则书不会同步
3. 开启双向进度同步 / 摘录同步 / 包含 Kobo Store 标题 / 转换为 KEPUB / 强制连线
4. 进度阈值（默认 1% / 99%）与 KEPUB 体积上限（默认 100 MB）决定落点
5. `活动日志` 与 `注册设备` 页签用于排障；审计日志会记录 `Renamed Kobo device #1`

### 6.9 KOReader 同步

1. `设置 → 设备与同步 → KOReader` → 复制 **同步 URL** 或 `下载插件`（v1.5.2）解压到 `koreader/plugins/`
2. 设备端在 KOReader 的 BookOrbit 菜单登录（或内置进度同步填 URL+账号）
3. 回填「已同步的书」「设备」列表；未匹配的书走 `手动的 KOReader 链接`
4. 危险操作：`删除 KOReader 凭据`（保留进度数据）与停用/删除设备

### 6.10 磁盘治理三件套

1. **实体管理器** → 合并/重命名作者（含 `查找重复项`）
2. **批量重命名** → 选库 → 预览 diff → 应用（先预览再应用的强制流程）
3. **复制书** → 选库 + 相似度阈值 → `运行扫描` → 人工确认后再删
4. **Missing Resources** → `开始扫描` → 标记磁盘上已不存在的记录

### 6.11 可观测性

- `审计日志` 覆盖 认证 / 设置 / 书籍 / 库 / 集成 五类事件，可展开 `详细信息`、按事件类型/执行者/目标/日期过滤
- `帐户活动` 提供每账号的 `正在读取洞察力` 下钻页（`/settings/admin/account-activity/:userId/insights`）
- `统计 → 库的完整性 / 元数据分数 / 元数据淡化` 构成书库健康三视图
