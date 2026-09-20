# BookOrbit 设置页功能清单（迁移用）

> 来源：`https://orbit.735876214.xyz:16666/settings`（线上实例，站点名 `BookOrbit`）
> 用途：本文件是 **novel_dl_convert 设置页「全部对齐（含占位）」迁移** 的对照基准，与 `docs/bookorbit-library-contract.md` 并列。
> 采集方式：浏览器自动化（Playwright CLI）**真实登录后逐页渲染采集**；全程只读——仅导航、展开折叠分组、读取 DOM、截图，**未点击任何保存 / 应用 / 删除 / 重置 / 启用 / 上传 / 退出 / 同步类控件**，未向任何输入框提交内容。
> 采集日期：2026-09-15 ｜ 账号角色：Superuser（该实例为单账号本地部署）
> **🔄 复核日期：2026-09-19**（同一实例的另一地址 `http://192.168.0.95:3400/`，账号同为 Superuser，界面此时渲染为**简体中文**）。本轮以**界面实际渲染内容**为准逐页复核，滞后项已就地修正并加 `🔄 2026-09-19` 行；汇总见 **§7 复核纪要**。功能与流程的完整描述见并列文档 `docs/bookorbit-feature-flows.md`。
> 证据：逐页采集记录与未能采集项见 `docs/review/bookorbit-settings-capture.md`；分区截图见 `docs/review/bookorbit-settings-shots/`
> ⚠️ 截图局限：该批截图**实为 1440×1000 视口截图，仅覆盖各页首屏**（应用使用内层滚动容器，`fullPage` 未生效）。本清单的文字结论取自完整 DOM 抽取，不受此影响；但截图不可当作「整页」证据。详见 `bookorbit-settings-capture.md` 的 1.1 节。
> **脱敏**：全文不含账号、密码、邮箱、令牌、密钥等任何真实敏感值；此类字段一律只记「已设置 / 未设置」。
> **准确性约定**：未取得可信值的项一律标注「未能采集」并说明原因，**不做推测补全**。
> **时效说明（第 31 期复核，2026-09-20）**：本文件是**上游 BookOrbit 侧的采集快照**，不是本项目的完成度记录 ——
> 它回答「上游有什么」，不回答「NovelForge 做到哪了」。**本项目现状一律以 `docs/bookorbit-capability-gap.md` 为准**
> （该文档第 29–31 期已逐行核验到底并附 `文件:行` 锚点）；本文件自 2026-09-19 采集后未随后续各期重取，
> 因此其中的设置页数量、页面清单等**只反映上游实例，不代表本项目现值**。第 31 期已据 capability-gap.md 复核其中与成就分类、阅读活动相关的上游形态。

---

## 0. 图例

> **权威真值源**：本文件「本项目可行性」结论以 `frontend/src/data/settingsNav.ts` 的 `status`（`ready`＝已有真实实现 / `placeholder`＝无该后端能力、页面只读展示上游结构并标注「未支持」）与每页 `note` 为准。下列符号仅作约定；§2 各表保留的上游采集控件形态 / 当前值仍作为「上游长什么样」的基线，不改动。

**「本项目可行性」列取值**

| 标记 | 含义 |
|---|---|
| ✅ | 已有对应后端能力，迁移时可直接对接 |
| 🟡 | 需新增后端能力（需在迁移轮次单独立项） |
| ⬜ | 占位：本项目无该能力，做只读展示或「未支持」标注 |
| ➖ | 不适用：本项目没有该业务域，建议不迁移该项 |
| 🔵 | 本项目已有等价能力，但**不在设置页**（在工具页 / 其它入口），建议保持现状或补一个跳转入口 |

**控件类型术语**：`开关`（`button[aria-checked]`）｜`分段`（同组按钮单选）｜`单选卡`（radio 卡片）｜`下拉`（自定义下拉按钮）｜`数字`｜`文本`｜`密码`｜`滑杆`｜`色板`｜`按钮`（动作）｜`只读`

> 说明：该站所有开关均渲染为 `<button aria-checked="true|false">` 且**无独立可访问名**（标签由邻近文本提供）；因此本清单的「当前值」对开关取自 `aria-checked`，对分段控件取自「同组样式唯一者」判定，无法判定者标注「未能采集」。

---

## 1. 设置页信息架构

### 1.1 路由形态（与本站的关键差异）

- 设置**不是「单页 + 标签栏」**，而是**嵌套路由 + 左侧分组导航**：`/settings/<域>/<页>`
- 直接访问 `/settings` 会 302 到 `/login?redirect=/settings/appearance/theme`；登录后落在 `/settings/appearance/theme`
- 左侧导航基于 `<nav aria-label="Settings sections">`，分 **5 组**：`YOU` / `LIBRARY` / `DEVICES` / `ACCOUNTS` / `SERVER`
- 共 **23 个一级入口** = 19 个直接链接 + **4 个可展开分组**（`Display` 6 项、`Reader` 6 项、`Metadata` 7 项、`Users & Access` 4 项）
- 侧栏底部提示 `Press Cmd K to jump to any setting`（设置项级跳转面板；本次未成功唤起，其内容未能采集）
- **🔄 2026-09-19 复核（设置项跳转面板已采集）**：该面板已于后续轮次成功唤起并采集，展开态共 **42 个可跳转项**（行为与清单见 `docs/bookorbit-feature-flows.md` §3.9）；上一条的「未能采集」作废。
- 面包屑格式：`Settings > <组> > <页>`；`document.title` 格式：`<页标题> · BookOrbit`
- 侧栏有折叠按钮 `Toggle Sidebar` / `Collapse sidebar`
- **🔄 2026-09-19 复核（叶子页计数与侧栏渲染规律）**：在同一页面的 DOM 中一次性抓到的 `a[href^="/settings"]` 为 **29 个**，另加只在各自域展开时才渲染的 `appearance/*` 6 个与 `reader/*` 6 个，合计 **41 个叶子页**（原结论成立）。侧栏**按当前所在域动态展开**：停在「服务器 / 用户与权限」下只会列出 `admin/*` 8 项，停在元数据页则列出 `account/* + libraries + metadata/* + library/* + 设备 + ACCOUNTS` 而不列 `admin/users`。逐页清单见 `docs/bookorbit-feature-flows.md` §3.9。
- **🔄 2026-09-19 复核（失效路由）**：`/settings/komga` **已不存在**，直连会回落到 `/settings/appearance/theme`（原 §2.42 记录的上游页已消失，见 §2.42 修订）；`/settings/system` 会被重定向到 `/settings/library/file-naming`（别名路由，非独立页）。

### 1.2 结构树

```
YOU
├── Profile                  /settings/account/profile
├── Display（可展开）
│   ├── Theme                /settings/appearance/theme
│   ├── Book Covers          /settings/appearance/book-covers
│   ├── Icons                /settings/appearance/icons
│   ├── Layout               /settings/appearance/layout
│   ├── Behavior             /settings/appearance/behavior
│   └── Language             /settings/appearance/language
├── Reader（可展开）
│   ├── eBook                /settings/reader/ebook
│   ├── PDF                  /settings/reader/pdf
│   ├── Comics               /settings/reader/comics
│   ├── Audiobook            /settings/reader/audio
│   ├── Fonts                /settings/reader/fonts
│   └── General              /settings/reader/general
├── Notifications            /settings/account/notifications
├── Privacy & Sharing        /settings/account/privacy
└── Restrictions             /settings/account/restrictions

LIBRARY
├── Libraries                /settings/libraries
├── Metadata（可展开）
│   ├── Providers            /settings/metadata/providers
│   ├── Field Rules          /settings/metadata/field-rules
│   ├── Custom Fields        /settings/metadata/custom-fields
│   ├── Confidence Score     /settings/metadata/score
│   ├── Books                /settings/metadata/auto-fetch
│   ├── Authors              /settings/metadata/authors
│   └── Genre Blocklist      /settings/metadata/genre-blocklist
├── File Naming              /settings/library/file-naming
└── Maintenance              /settings/library/maintenance

DEVICES
├── Kobo                     /settings/kobo
├── KOReader                 /settings/koreader
├── OPDS                     /settings/opds
└── Email                    /settings/email

ACCOUNTS
├── Hardcover                /settings/hardcover
├── Readwise                 /settings/readwise
└── StoryGraph               /settings/storygraph

SERVER
├── Users & Access（可展开）
│   ├── Users                /settings/admin/users
│   ├── Account Activity     /settings/admin/account-activity
│   ├── Magic Links          /settings/admin/magic-links
│   └── OIDC / SSO           /settings/admin/oidc
├── Requests                 /settings/admin/requests
├── Book Dock                /settings/admin/book-dock
├── Server Fonts             /settings/admin/server-fonts
└── Audit Log                /settings/admin/audit-log
```

> **本项目侧栏实际形态**：设置页的单一数据源是 `frontend/src/data/settingsNav.ts`，共 **6 组（比上游多一个 `本项目扩展` / EXTENSIONS）/ 48 个叶子页**，路由为 `/settings/<path>`。其中**上游 41 页逐页有落点**：已实现的走真实组件（`status: 'ready'`）；本项目不做的走**只读占位页**（`status: 'placeholder'`）——只展示上游该页的页内分组与设置项并逐条标注「未支持」，页首用中文写明本项目为何不提供，**不伪造可点开关**。另 **7 页为本项目补充**（上游**没有**这一页，标 `own: true`，界面显示「本项目补充」徽标），与上游逐页对读时不会误判为「上游也有」。故本结构树描述的是**上游 BookOrbit** 信息架构、用作对齐基线；逐页落点与「本项目可行性」一律以 settingsNav 为准（见 §2）。

### 1.3 页面清单与页内分区

| 组 | 页 | 页面 `<h2>` | 页内 `h3`/分组标题 |
|---|---|---|---|
| YOU | Profile | Profile | PREFERENCES ｜ SECURITY & ACCESS ｜ Connected Accounts |
| YOU | Theme | Theme | WHERE TO SAVE APPEARANCE PREFERENCES ｜ THEME ｜ LIBRARY BACKGROUND |
| YOU | Book Covers | Book Covers | BOOK COVERS |
| YOU | Icons | Icons | UPLOAD ICONS ｜ CUSTOM ICONS |
| YOU | Layout | Layout | LIBRARY GRID LAYOUT ｜ SERIES DISPLAY ｜ AUTHOR GRID ｜ LIST AND TABLE VIEWS |
| YOU | Behavior | Behavior | LIBRARY BEHAVIOR |
| YOU | Language | Language | LANGUAGE |
| YOU | eBook | eBook | NEW BOOKS ｜ LAYOUT ｜ THEME ｜ TYPOGRAPHY ｜ ADVANCED |
| YOU | PDF | PDF | LAYOUT ｜ ZOOM |
| YOU | Comics | Comics | VIEW ｜ DISPLAY |
| YOU | Audiobook | Audiobook | PLAYBACK ｜ SKIP CONTROLS |
| YOU | Fonts | Fonts | UPLOAD FONTS ｜ YOUR FONTS |
| YOU | Reader General | General | WHERE TO SAVE READER PREFERENCES |
| YOU | Notifications | Notifications | LIBRARY ｜ FILES ｜ INTEGRATIONS ｜ PERSONAL ｜ APP UPDATES |
| YOU | Privacy & Sharing | Privacy & Sharing | PRIVACY & SHARING ｜ Profile access history |
| YOU | Restrictions | Restrictions | （空态） |
| LIBRARY | Libraries | Libraries | LIBRARY ｜ CONTENTS ｜ AUTOMATION ｜ LAST SCAN |
| LIBRARY | Providers | Providers | GENERAL BOOK CATALOGUES ｜ AUDIOBOOKS ｜ COMICS & LIGHT NOVELS ｜ REGIONAL CATALOGUES ｜ ADVANCED FETCH BEHAVIOR |
| LIBRARY | Field Rules | Field-Level Rules | （逐字段规则矩阵） |
| LIBRARY | Custom Fields | Custom Fields | NEW FIELD ｜ FIELDS |
| LIBRARY | Confidence Score | Confidence Score | WHERE A SCORE COMES FROM ｜ COUNT TOWARDS THE SCORE ｜ NOT SCORED ｜ WHERE YOUR BOOKS LAND |
| LIBRARY | Books | Books | GLOBAL SETTINGS ｜ AUTOMATION |
| LIBRARY | Authors | Author Auto-Fetch | （作者自动抓取） |
| LIBRARY | Genre Blocklist | Genre Blocklist | （黑名单编辑） |
| LIBRARY | File Naming | File Naming | （模式编辑 + TOKENS/MODIFIERS/STRUCTURE + 配方） |
| LIBRARY | Maintenance | Maintenance | UPLOADS ｜ IMPORT ｜ RECOMMENDATIONS ｜ ACHIEVEMENTS ｜ UPDATES |
| DEVICES | Kobo | Kobo | REGISTERED DEVICES ｜ SYNC PREFERENCES ｜ Progress Thresholds ｜ KEPUB CONVERSION LIMIT |
| DEVICES | KOReader | KOReader | KOREADER STATUS ｜ SETUP ｜ DEVICES ｜ PLUGIN ACTIVITY ｜ UNMATCHED/MANUAL LINKS ｜ SETUP GUIDE ｜ DANGER ZONE |
| DEVICES | OPDS | OPDS | SERVER ｜ ENDPOINT ｜ OPDS ACCOUNTS ｜ OPDS NOTES |
| DEVICES | Email | Email | SMTP PROVIDERS ｜ PROVIDER NOTES（+ 5 个标签页） |
| ACCOUNTS | Hardcover | Hardcover | Connection ｜ API TOKEN |
| ACCOUNTS | Readwise | Readwise | Connection ｜ ACCESS TOKEN ｜ Enable sync |
| ACCOUNTS | StoryGraph | StoryGraph | Connection ｜ cookie 指引 |
| SERVER | Users | Users | DEFAULTS FOR NEW ACCOUNTS |
| SERVER | Account Activity | Account Activity | （筛选 + 账号活动表） |
| SERVER | Magic Links | Magic Links | ACTIVE LINKS |
| SERVER | OIDC / SSO | OIDC / SSO | PROVIDERS |
| SERVER | Requests | Requests | Sources ｜ Download clients ｜ Automation |
| SERVER | Book Dock | Book Dock | DROP FOLDER ｜ METADATA ｜ AUTO-FINALIZE |
| SERVER | Server Fonts | Server Fonts | UPLOAD FONTS ｜ SERVER FONTS |
| SERVER | Audit Log | Audit Log | （筛选 + 审计流水） |

---

## 2. 分区详情

### 2.1 YOU → Profile（`/settings/account/profile`）

| 设置项 | 控件 | 当前值 | 说明 / 联动 | 本项目可行性 |
|---|---|---|---|---|
| 头像 | 按钮 `上传头像` / `移除` | 未设置（占位首字母） | JPG/PNG/WEBP ≤5MB，落 `CACHE_DIR/user/avatar.<ext>` 经 `/api/account/avatar` 分发（零外链，带 `?token=`） | ✅ |
| Full name | 文本 | 未设置 | 显示名，保存后回显设置页与顶栏（回退 username） | ✅ |
| Username | 只读 | 已设置 | 「Your username cannot be changed.」—— 本项目账号名由部署配置，不可改 | ➖ |
| Email | 只读 | 无 | 本项目无邮箱体系，仅服务端可读 | ➖ |
| Timezone | 下拉（IANA 全量，含「未设置」） | 未设置 | 接通 Early Bird / All-nighter 等时间类成就（按账号时区归一，缺省用服务器本地时） | ✅ |
| Enable achievements | 开关 | 未能采集 | 关闭后不统计成就、不显示成就相关界面 | ✅（本项目已有「成就」开关） |
| Guided Tour | 按钮 `重放新手引导` | — | 轻量新手引导浮层（书架 / 阅读器 / 设置同步），离线可用 | ✅ |
| Change password | 按钮 | — | 「Change the password you use to sign in.」 | ✅（本项目已有「修改密码」） |
| Connected Accounts | 只读 | 无 OIDC 提供者 | 「Ask an administrator to set up SSO.」—— 单用户场景无意义 | ➖ |

**联动**：`Enable achievements` 关闭 → 成就界面隐藏（说明文字明确），但与 Notifications 里的成就通知是分开管理的。

### 2.2 YOU → Display → Theme（`/settings/appearance/theme`）

| 设置项 | 控件 | 当前值 | 说明 / 联动 | 本项目可行性 |
|---|---|---|---|---|
| **外观偏好的保存位置** | 单选卡（2 项） | `My account`（ACTIVE） | `This device only`＝存浏览器；`My account`＝存账号，多设备一致 | ✅（本项目「偏好与同步」页统管外观与阅读偏好的整套同步，也可按设备各用各的） |
| Color scheme | 分段（3） | **System** | Light / Dark / System | ✅（本项目有浅色/深色/跟随系统） |
| Accent color | 色板（64 档，5 行×16 未满） | **存在分歧，未能确证** | 见下注 | ✅（本项目有 65 档点缀色） |
| Corner radius | 分段（4） | **Default** | Sharp / Default / Rounded / Pill | ✅（本项目有 4 档圆角） |
| Background pattern | 图形按钮（4 组共 20） | 未能采集 | 组：FUNDAMENTAL(4) / STRUCTURAL(6) / AMBIENT(5) / REFRACTIVE(5)；按钮无文本/`aria-label` | ⬜ |

**本项目落地**：主题 / 点缀色（65 档）/ 圆角 / 外观偏好保存位置均已实现（保存位置落到「偏好与同步」页）；背景图案（20 个）为未支持项。

**点缀色当前值的分歧（如实记录）**：`<html>` 上为 `class="accent-blue"`、`--primary=oklch(48.7% .25 263)`（指向 Blue）；但 64 个色板按钮中**仅 `White` 带非空 `box-shadow`**（疑为选中环，也可能是首项聚焦环）。两个信号矛盾，**未确证**，迁移时不需要该值，仅需 64 档选项清单。

**64 档点缀色（按行）**：
`White, Orange, Copper, Amber, Marigold, Yellow, Chartreuse, Acid Green, Lime, Wasabi, Green, Malachite, Jade, Emerald, Viridian, Teal`
`Grey, Peach, Sand, Butter, Flax, Lemon, Pear, Pistachio, Celadon, Sprout, Sage, Aloe, Sea Glass, Mint, Foam, Seafoam`
`Turquoise, Cyan, Electric Blue, Ultramarine, Blue, Iris, Indigo, Purple, Violet, Amethyst, Fuchsia, Pink, Raspberry, Scarlet, Rose, Vermilion`
`Aqua, Powder, Baby Blue, Cornflower, Periwinkle, Bluebell, Wisteria, Thistle, Lavender, Mauve, Orchid, Blush, Rose Quartz, Rosewater, Coral, Salmon`

**20 个背景图案**（取自顶栏 Appearance 快捷面板，见 4.1）：`None, Dots, Cross, Millimeter, Blueprint, Brushed, Scanlines, Vinyl, Carbon, Perforated, Aurora, Horizon, Glow, Mesh, Elevation, Prism, Spectrum, Spectrum X, Spectrum Plus, Eclipse`

### 2.3 YOU → Display → Book Covers（`/settings/appearance/book-covers`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Default cover search provider | 分段（3） | 未能采集 | `DuckDuckGo` / `iTunes` / `All Sources`；存账号，多端一致 | ⬜（依赖在线封面抓取，未支持） |
| Cover display mode | 分段（3） | **Fill card** | `Blurred fit`（模糊填充保完整）/ `Fill card`（裁切填满）/ `Natural bottom`（保比例底部对齐） | ✅（本项目：填满 / 自然贴底 / 模糊底图） |
| Book spine overlay | 分段（3） | **Subtle** | `Off` / `Subtle` / `Strong`：给封面卡加书脊+光泽效果 | ✅（含第 20 期「漫画是否显示书脊」开关） |
| Show spine on comics | 开关 | 未能采集 | 对 cbz/cbr/cb7 封面同样应用书脊效果 | ✅ |
| Book details cover tint | 分段（3） | **Two colours** | `Off` / `One colour` / `Two colours`：详情页从封面取色做背景渐变 | ✅（详情页封面取色，第 20 期） |
| Cover shadow strength | 分段（2） | 未能采集 | `Default` / `Strong`：网格、列表、表格、仪表盘缩略图的封面阴影 | ✅（阴影强度） |
| Card overlays | 多选（6 项） | 未能采集 | 封面上直接叠加的元数据：`Progress bar` / `File format` / `Rating` / `Read status` / `Series number` / `Lock status` | ✅（5 种卡片叠加层） |

**本项目落地**：真实内嵌封面 + 填充方式（填满 / 自然贴底 / 模糊底图）+ 书脊（含漫画开关）+ 阴影强度 + 5 种卡片叠加层 + 详情页封面取色，存本机、改完立即生效；未支持封面搜索提供者（依赖在线封面抓取）。

### 2.4 YOU → Display → Icons（`/settings/appearance/icons`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Upload icons | 上传区 | 未上传（0 个） | 自定义图标上传 | ➖ |
| 图标风格 | — | **未能采集** | 标题说明为「Choose the icon style used across the app.」，但页面正文仅 134 字符、控件 5 个（含上传/排序/空态），风格选项未渲染为可判定控件 | ➖ |
| 排序 | 分段 | 未能采集 | `Newest` / `Name` | ➖ |

**空态文案**：`No custom icons uploaded yet.`

**本项目落地**：图标风格由设计系统统一决定，不提供自定义图标 / 上传图标风格选项；此页仅作上游对照（`settingsNav` 标 `placeholder`）。

### 2.5 YOU → Display → Layout（`/settings/appearance/layout`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Cover size behavior | 分段（2） | 未能采集 | `Sync all views` / `Per-view sizes`；Per-view 时在各自视图的 Display 面板调 | ⬜（本项目不暴露为设置） |
| Portrait cover size | 滑杆/数字 | 130px | 竖向书库与视图的封面尺寸 | ⬜（本项目不暴露为设置） |
| Square cover size | 滑杆/数字 | 150px | 方形书库与视图的封面尺寸 | ⬜（本项目不暴露为设置） |
| Portrait grid spacing | 滑杆/数字 | 28px | 竖向封面的网格间距 | ⬜（本项目不暴露为设置） |
| Square grid spacing | 滑杆/数字 | 28px | 方形封面的网格间距 | ⬜（本项目不暴露为设置） |
| Card info mode | 分段（3） | **On hover** | `On hover` / `Below cover` / `Off`：网格卡上标题作者的显示位置 | ⬜（本项目不暴露为设置） |
| Collapsed series cover | 分段（5） | **Stack** | `Stack` / `Mosaic` / `First` / `Latest` / `First Unread`：系列折叠时用哪张封面 | ⬜（本项目不暴露为设置） |
| Author grid → Cover size | 滑杆/数字 | 120px | 作者网格封面宽度 | ⬜（本项目不暴露为设置） |
| Author grid → Cover shape | 分段（2） | 未能采集 | `Circle` / `Square` | ⬜（本项目不暴露为设置） |
| List and table → Zebra striping | 开关 | 未能采集 | 表格斑马纹 | ⬜（本项目表格已实现斑马纹，但不作为设置暴露） |

**本项目落地**：书库视图密度 / 封面尺寸 / 网格间距 / 卡片信息模式 / 系列折叠 / 作者网格外观等由前端统一定制，不暴露为逐项设置；此页仅作上游对照（`settingsNav` 标 `placeholder`）。

### 2.6 YOU → Display → Behavior（`/settings/appearance/behavior`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Thumbnail clicks | 分段（2） | 未能采集 | `Read first`（有可读文件直接进阅读器）/ `Open details`（进详情页） | ⬜（本项目有阅读入口，但无此开关，不暴露为设置） |
| Show filter preview by default | 开关 | 未能采集 | 打开智能书架时自动展开筛选与排序摘要 | ⬜（本项目不暴露为设置） |
| Collapse series by default | 开关 | 未能采集 | 在书库/收藏夹/智能书架中把同系列书折叠为一张卡 | ⬜（本项目不暴露为设置） |

**本项目落地**：缩略图点击行为 / 筛选预览默认展开 / 系列默认折叠等浏览行为由前端固定，不暴露为设置；此页仅作上游对照（`settingsNav` 标 `placeholder`）。

### 2.7 YOU → Display → Language（`/settings/appearance/language`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Language | 下拉（自定义按钮，`aria-expanded`） | `English` | 「Choose the language used across the interface.」 | ⬜（本项目为中文单语） |

**完整语言清单**（取自顶栏 Language 快捷面板，见 4.2）：SUGGESTED = `English` / `简体中文`；ALL LANGUAGES 共 25 项：`Bahasa Indonesia, Čeština, Dansk, Deutsch, English, Español, Français, Italiano, Magyar, Nederlands, Polski, Português, Română, Slovenčina, Slovenščina, Suomi, Svenska, Türkçe, Ελληνικά, Русский, Українська, 한국어, 日本語, 简体中文, 繁體中文`

> 观察：未登录的登录页为中文，登录后按账号语言显示英文（`<html lang="en">`）——即服务端有默认语言，账号语言覆盖之。

### 2.8 YOU → Reader → eBook（`/settings/reader/ebook`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| NEW BOOKS → Apply my settings to new books | 开关 | 未能采集 | 关闭时新书沿用出版方字体与排版，改动后才应用设置 | ⬜（未支持） |
| LAYOUT → Reading flow | 分段（2） | 未能采集 | `Paginated`（翻页）/ `Scrolled`（滚动） | ✅（本项目阅读模式＝滚动） |
| Fixed-layout page spreads | 分段（3） | 未能采集 | `Book default` / `Single page` / `Columns`（漫画、图像型 EPUB 默认值） | ⬜（未支持） |
| Columns | 数字 | 2 | 每页文本列数 | ✅（本项目分栏） |
| THEME → Dark mode | 分段（13） | 未能采集 | 深色变体：`Default, Gray, Sepia, Crimson, Meadow, Rosewood, Azure, Dawnlight, Ember, Aurora, Ocean, Mist, AMOLED` | ✅（本项目 13 档主题） |
| TYPOGRAPHY → Font | 分段（4） | 未能采集 | `Book default` / `Serif` / `Sans-serif` / `Monospace` | ✅（本项目 3 档字体） |
| Font style | 分段（4） | 未能采集 | `Regular` / `Bold` / `Regular Italic` / `Bold Italic` | ⬜（未支持：字重样式） |
| Font size | 滑杆 | 16px | 基准字号 | ✅ |
| Line height | 滑杆 | 1.5 | 行高 | ✅ |
| Paragraph spacing | 分段 | 未能采集 | `Book default` / 自定义 | ✅（本项目段落间距） |
| Justify text | 开关 | 未能采集 | 两端对齐 | ✅（本项目两端对齐） |
| Hyphenation | 开关 | 未能采集 | 自动断词 | ✅（本项目断词） |
| ADVANCED → Letter spacing | 分段 | 未能采集 | `Book default` / `Custom` | ✅（本项目字距） |
| Word spacing | 分段 | 未能采集 | `Book default` / `Custom` | ✅（本项目词距） |
| First-line indent | 分段 | 未能采集 | `Book default` / `Custom` | ✅（本项目首行缩进） |
| Max content width | 滑杆 | 720px | 文本区最大宽度 | ✅（本项目内容宽度，单位 rem） |
| Column gap | 滑杆 | 5% | 文本区左右内边距 | ⬜（未支持：文本区左右内边距） |
| Reset to defaults | 按钮 | — | 恢复默认 | ✅ |

**本项目落地**：已实现「阅读模式 / 13 档主题 / 字体 / 字号 / 行高 / 内容宽度 / 段落间距 / 首行缩进 / 字距 / 词距 / 分栏 / 两端对齐 / 断词」共 13 项；未支持：新书套用设置（Apply my settings to new books）、固定版式页宽（Fixed-layout page spreads）、字重样式（Font style）、文本区左右内边距（Column gap）。

### 2.9 YOU → Reader → PDF（`/settings/reader/pdf`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Scroll mode | 分段（3） | **Scrolled** | `Page`（逐页翻）/ `Scrolled`（连续）/ `Horizontal`（横向） | ✅（本项目：翻页 / 纵向 / 横向） |
| Page spread | 分段（4） | **None** | `None` / `Odd` / `Even` / `Auto`：双页视图中起始页在哪侧 | ✅（本项目：单页 / 双页奇右 / 偶右 / 自动） |
| Default fit | 分段（4） | **Fit Width** | `Fit Page` / `Fit Width` / `Automatic` / `Custom` | ✅（本项目：适配方式 / 自定义缩放） |
| Reset to defaults | 按钮 | — | — | ✅ |

**本项目落地**：滚动模式（翻页 / 纵向 / 横向）、页展（单页 / 双页奇右 / 偶右 / 自动）、适配方式、自定义缩放、阅读进度均已实现；渲染用 pdf.js，懒加载（打开 PDF 才下载）。

### 2.10 YOU → Reader → Comics（`/settings/reader/comics`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Reading mode | 分段（3） | **Paginated** | `Paginated` / `Infinite (spaced)` / `Infinite (no gaps)`（条漫） | ✅（本项目：翻页 / 纵向连续） |
| Page view | 分段（2） | 未能采集 | `Single` / `Two-page` | ✅（本项目：单页 / 双页） |
| Fit mode | 分段（4） | **Page** | `Page` / `Width` / `Height` / `Actual` | ✅（本项目：页 / 宽 / 高 / 原尺寸） |
| Reading direction | 分段（2） | 未能采集 | `L to R`（西文漫画）/ `R to L`（日漫） | ✅（含日漫右→左） |
| Spread alignment | 分段（2） | 未能采集 | `Normal` / `Shifted`：修正扫描件封面错位 | ✅ |
| Spread gap | 滑杆/数字 | 0px | 双页视图页间距 | ✅（本项目页间距） |
| Wide-page handling | 分段（2） | 未能采集 | `Auto` / `Disable`：宽幅扫描件单独显示 | ✅ |
| Force two-page on small screens | 开关 | 未能采集 | 小屏也强制双页 | ✅ |
| Auto-advance to next book | 开关 | 未能采集 | 翻过最后一页打开系列下一本 | ✅ |
| DISPLAY → Background color | 分段（3） | **Black** | `Black` / `Gray` / `White`：画布底色 | ✅（本项目背景色） |
| Reset to defaults | 按钮 | — | — | ✅ |

**本项目落地**：阅读模式（翻页 / 纵向连续）、页视图（单页 / 双页）、适配方式、阅读方向（含日漫右→左）、页间距、背景色、阅读进度均已实现；**支持 CBZ 与 CBR**——CBR 由服务端 zip/rar 双后端解压（bsdtar，容器内 libarchive-tools 提供），两种格式在阅读器里体验一致。

### 2.11 YOU → Reader → Audiobook（`/settings/reader/audio`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Default playback speed | 分段（6） | **1x** | `0.75x / 1x / 1.25x / 1.5x / 1.75x / 2x` | ✅（本项目倍速 0.75x–2x） |
| Default volume | 滑杆 | 100% | 初始音量 0–100 | ✅（本项目默认音量） |
| Skip back duration | 分段（4） | **10s** | `5s / 10s / 15s / 30s` | ✅（本项目快退 5/10/15/30 秒） |
| Skip forward duration | 分段（4） | **30s** | `10s / 15s / 30s / 60s` | ✅（本项目快进 10/15/30/60 秒） |
| Reset to defaults | 按钮 | — | — | ✅ |

**本项目落地**：默认倍速（0.75x–2x）、默认音量、快退间隔（5/10/15/30 秒）、快进间隔（10/15/30/60 秒）、睡眠定时默认时长均已实现；播放器另提供轨道列表与按秒进度保存（跨设备同步）。有声书支持「一个目录 = 一本书」（一章一文件）与单个音频文件两种形态。

### 2.12 YOU → Reader → Fonts（`/settings/reader/fonts`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| UPLOAD FONTS | 拖拽/浏览上传 | 未上传 | 支持 `TTF, OTF, WOFF, WOFF2`，单个 ≤50MB | ✅（本项目上传 / 列表 / 删除 / 选用） |
| YOUR FONTS | 只读 | `0 / 50 used` | 空态：`No fonts uploaded yet` / `Drag a font file above to get started.` | ✅（族名从字体 name 表解析，回落文件名） |

**本项目落地**：字体上传 / 列表 / 删除 / 在阅读器中选用均已实现；族名从字体 name 表解析（TTF/OTF），解析不出时回落文件名并显示。本项目单用户，上限取服务端口径（200）。

### 2.13 YOU → Reader → General（`/settings/reader/general`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 阅读偏好的保存位置 | 单选卡（2） | `My account`（ACTIVE） | `This device only`＝存浏览器；`My account`＝存账号，多设备一致 | ✅（本项目扩展为「偏好与同步」） |

**本项目落地**：本项目把它扩展为「偏好与同步」——偏好可存成具名**模式**（整套快照，含外观），供不同设备套用；每台设备也可各用各的。应用模式 = 拷贝内容，别人改模式本体不会让你被动变化。已知限制：无实时推送——其它设备的改动需本机下次打开或点「立即同步」才可见。

> 该页只有这一项（与 Display→Theme 的「保存位置」同构，是全站「偏好作用域」模式的第二个实例）。

### 2.14 YOU → Notifications（`/settings/account/notifications`）

顶部汇总：`LIBRARY 11 of 11 enabled`（10 个业务条目 + 1 个总开关语义）。

**每条业务通知的控件形态**：一个通知级别分段，选项为 `Off` / `Problems` / `All`；`All` 的描述为「Notify me every time, including successes.」，`Problems` 仅失败时通知，`Off` 关闭。**采集到的当前值：LIBRARY / FILES / INTEGRATIONS 下 10 条全部为 `All`**（`★` 判定命中）。

| 分组 | 设置项 | 说明 | 本项目可行性 |
|---|---|---|---|
| LIBRARY | Library scanning | 书库扫描完成/失败/发现缺失书 | ✅（本项目有监听与任务中心） |
| LIBRARY | Metadata fetching | 元数据抓取完成或失败 | ✅ |
| LIBRARY | Author enrichment | 作者传记与照片抓取完成 | ✅ |
| FILES | File write-back | 编辑后的元数据写回磁盘文件 | ✅（本项目 bulk-rename 写入能力） |
| FILES | File rename | 单本书文件按命名模式重命名 | ✅（本项目有批量重命名） |
| FILES | Bulk rename | 批量重命名或跨书库移动完成/失败 | ✅ |
| FILES | Data migration | 从其它书库工具导入完成/失败 | ✅ |
| INTEGRATIONS | Book Dock | Book Dock 定稿完成或异常 | ✅ |
| INTEGRATIONS | Book requests | 求书提交/审批/到货 | ➖（本项目无求书系统） |
| INTEGRATIONS | Email delivery | 送书到邮箱成功/失败 | ➖（本项目无邮件投递渠道） |
| PERSONAL | Achievements | 解锁新成就（仅 `Off` / `All`，无 `Problems` 档） | ✅ |
| APP UPDATES | Show "What's New" after updates | 开关；更新后弹新功能提示，归档始终可访问 | ✅ |

**本项目落地**：按活动类别设「关闭 / 仅失败 / 全部」三档；差异——上游是服务端投递（可走邮件），本项目无投递渠道，开关为客户端过滤，生效范围是通知中心与日志。Book requests / Email delivery 在本项目无对应系统（➖）。

### 2.15 YOU → Privacy & Sharing（`/settings/account/privacy`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Reading insights sharing level | 单选（`input[type=radio]`，name=`reading-insights-sharing`） | **Private** | 三档：`Private`（仅自己可见统计）/ `Share summary`（只共享聚合习惯，不含书名作者系列）/ `Share detailed insights`（含近期与 Top 书目、作者、系列、题材） | ➖（本项目单用户） |
| Profile access history | 只读 | `No administrator has viewed your shared reading profile.` | 管理员查看记录 | ➖ |

### 2.16 YOU → Restrictions（`/settings/account/restrictions`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 内容限制 | 只读（空态） | `No content restrictions` | 「Your account has full access to all content within your assigned libraries.」；**限制项的具体形态未能采集**（该账号无限制） | ➖ |

### 2.17 LIBRARY → Libraries（`/settings/libraries`）

顶部工具条：按钮 `Scan All`、`Add Library`；输入 `Filter libraries`；`Sort` 下拉（`Default order / Name / Books / Size on disk / Last scan`）。
汇总：`9 libraries · 9 folders · 518 books · 31.63 GB on disk`。

每个书库卡片（4 列）：`LIBRARY` / `CONTENTS` / `AUTOMATION` / `LAST SCAN`，字段如下：

| 字段 | 示例 / 取值 | 说明 | 本项目可行性 |
|---|---|---|---|
| 书库名 | 9 个：`漫画, 刘备, 有声书, 工具书, 插图书, 教学, 杂志, 其他, 连环画` | 列表按此展示 | ✅ |
| 组织模式 | `Folder mode` | 另有 `File as Book` 模式（见 2.25） | ✅ |
| 文件夹数 + 路径 | `1 folder` / `/books/<名称>` | 可多个文件夹 | ✅ |
| 书籍数 + 占用 | 如 `55 books` / `2.4 GB` | — | ✅ |
| 格式分布 | 如 `PDF 46 / CBZ 6 / CBR 1 / EPUB 1 / MOBI 1` | 按格式计数 | ✅ |
| Watch folders | `On` | 监听文件夹 | ✅（本项目 watcher） |
| Scheduled scan | `At 12:00 AM` | 定时扫描 | ✅（本项目有 cron 概念） |
| Write to file | `Off` | 元数据写回文件 | 🔵（等价能力在「工具 → 批量重命名」） |
| Rename files | `On` | 按命名模式重命名 | 🔵（等价能力在「工具 → 批量重命名」） |
| LAST SCAN | `Scanned 2 days ago` / `Failed 17 hours ago` + 小字（如 `Server restarted during scan`）+ 原因标签（`Schedule - no change` / `Manual - no change`） | 扫描状态与原因 | ✅ |
| 行动按钮 | `Scan` | 单库扫描 | ✅ |

**本项目落地**：多书库实体（类型：电子书 / 漫画 / 有声书 / 混合；存放方式：就地引用 / 独立存储）、来源子目录投递、按格式迁移（逐条预览 + 台账幂等 + 一键回滚 + 同名冲突拒绝并建议改名）、自动归库、库类型→功能显隐、每库独立覆盖（第 13 期）均在「工具 → 书库管理」实现；此设置页仅作上游结构对照（`settingsNav` 标 `placeholder`，link→/tools/libraries）。

### 2.18 LIBRARY → Metadata → Providers（`/settings/metadata/providers`）

顶部：`10 of 14 sources enabled` + 筛选 `All / Enabled / Needs setup`。

**分组与提供者**：`GENERAL BOOK CATALOGUES` / `AUDIOBOOKS` / `COMICS & LIGHT NOVELS` / `REGIONAL CATALOGUES`。出现的提供者名：`Goodreads, Google, Open Lib, iTunes, RanobeDB, Amazon, Audible, Hardcover, Kobo`。

**逐字段的提供者优先级链**（每字段一条有序链，带序号、可 `Add`、可跳过、显示 `1 skipped`）：

| 字段分组 | 字段 | 链中提供者（按序） | 合并策略 |
|---|---|---|---|
| BOOK | （书名等，正文中未逐条列出） | `Goodreads → Google → ...` | `Fill gaps` / `If provided` / `Always` |
| — | Community rating | `Hardcover`（已关闭，保留在序中但跳过）→ `Goodreads → Google → Open Lib → iTunes → RanobeDB → Amazon → Audible` | 同上 |
| SERIES | Series name | `Goodreads → Google → Amazon → Kobo`（Kobo 关闭，跳过）`→ Open Lib` | 同上 |
| SERIES | Series index | 同上 | 同上 |
| CLASSIFICATION | Genres | `Goodreads → Google → iTunes`（Kobo 关闭，跳过） | `Fill gaps` / `Merge` / `If provided` / `Always` |
| AUDIOBOOK | Narrators | `Goodreads → Google → Amazon → Kobo`（跳过）`→ Open Lib` | 同上 |
| AUDIOBOOK | Duration | 同上 | 同上 |
| AUDIOBOOK | Abridged | 同上 | 同上 |

**ADVANCED FETCH BEHAVIOR**

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Combine genres from all selected providers | 开关 | 未能采集 | 对 Genres 字段收集并去重所有提供者的结果，而非首个命中即停 | ✅（本项目已实现合并策略） |
| Maximum genres per book | 数字 | 未能采集（留空＝不限） | 在排除与去重之后应用 | ✅ |
| Store provider IDs on books | 开关 | 未能采集 | 保存返回的提供者 ID（ISBN/ASIN/Goodreads ID 等）以供后续更准查询 | ✅ |
| Use existing provider IDs only | 开关 | 未能采集 | 已有书只用已存的 ID 查询，ID 查询失败也不回退到搜索（不影响手动搜索与新书发现） | ✅ |

**本项目落地**：14 个元数据源（当前 10 个启用）、逐字段的提供者优先级链、每字段合并策略（Fill gaps / Merge / If provided / Always）、Combine genres、Maximum genres、Store provider IDs、Use existing provider IDs 均已实现。

顶部工具条：`All / Enabled / Needs setup` 筛选；底部状态条 `No unsaved changes` + `Discard` + `Save Global defaults`。

### 2.19 LIBRARY → Metadata → Field Rules（`/settings/metadata/field-rules`）

逐字段规则矩阵（204 个控件，是设置页中控件最多的一页）。每个字段一行，每行含：

| 维度 | 取值 | 采集到的当前值 |
|---|---|---|
| 覆盖策略 | `Overwrite if provided` / `Merge with existing` 等 | 绝大多数字段为 **`Overwrite if provided`**（「Write if provider returned a value」）；`Genres` 为 **`Merge with existing`**（4 选项组） |
| 其它列 | 该页还有锁定/优先级相关列 | 未能逐列采集（矩阵列头未在正文中呈现） |

**本项目落地**：逐字段覆写策略（Overwrite if provided / Merge with existing 等）规则矩阵已实现（204 个控件，是设置页中控件最多的一页）。

> ⚠️ 该页是设置页中控件最多的一页（204 个）。本次已采集完整正文与控件清单，但**截图仅为视口首屏**（原因见 `bookorbit-settings-capture.md` 的 1.1 节），整页视觉还原需另取整页截图。

### 2.20 LIBRARY → Metadata → Custom Fields（`/settings/metadata/custom-fields`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| NEW FIELD 表单 | 表单（未展开填写） | 无自定义字段 | 定义自定义元数据字段并选择适用书库 | ✅ |
| FIELDS 列表 | 只读 | `No custom fields yet` | 「Drag to reorder, edit labels, toggle libraries, or archive fields」 | ✅ |

**本项目落地**：自定义字段定义表单 + 字段列表（拖拽排序 / 改标签 / 切换适用书库 / 归档）均已实现。

### 2.21 LIBRARY → Metadata → Confidence Score（`/settings/metadata/score`）

页头说明（原文要点）：每本书按元数据完整度得 0–100 分；权重只有相对意义，故每个字段显示其占满分的**百分比份额**，全部权重翻倍不改变结果。

汇总：`21 of 24 fields scoring, 78 points total`；按钮 `Recalculate all`、`Reset to defaults`。

**权重份额分布**：`Core 56.4% | Publishing 17.9% | Classification 11.5% | Provider IDs 10.3% | Enrichment 3.8%`（合计 100%）。

**计分字段与份额**（含计分条件）：

| 字段 | 计分条件 | 份额 |
|---|---|---|
| Title | 非空 | 12.8% |
| Authors | 至少一个 | 12.8% |
| Cover | 已存封面图 | 12.8% |
| Description | 非空 | 10.3% |
| ISBN-13 | 非空 | 9.0% |
| Genres | 至少一个 | 7.7% |
| Publisher | 非空 | 5.1% |
| Published year | > 0 | 5.1% |
| Language | 非空 | 5.1% |
| Page count | > 0 | 2.6% |
| ISBN-10 | 非空 | 2.6% |
| Tags | 至少一个 | 2.6% |
| Community rating | > 0 | 1.3% |
| Google Books ID / Goodreads ID / Amazon ID / Hardcover ID / Open Library ID / iTunes ID / Kobo ID / Aladin ID | 已存该 ID | 各 1.3% |

**NOT SCORED（3 项）**：`Subtitle`、`Series name`、`Series index`（「A field at zero leaves the total too, so books missing it are not marked down.」）。

**WHERE YOUR BOOKS LAND**（分布直方图）：`UNDER 50 / 50-69 / 70-89 / 90+`，刻度 0/50/70/90/100；当前 `MEDIAN 35`、`UNDER 50 = 366`、`90 AND UP = 0`（统计范围 515 本书）。

**本项目落地**：元数据完整度打分（24 计分字段 + 5 个权重分组 + 书库分布直方图 + Recalculate all / Reset to defaults）已实现。

### 2.22 LIBRARY → Metadata → Books（`/settings/metadata/auto-fetch`）

页面标题 `Book Auto-Fetch`，`<h2>` 为 `Books`。说明：「Automatically fetch covers, descriptions, and other details when new books are added to your library.」

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| GLOBAL SETTINGS → Enable auto-fetch | 开关 | 未能采集 | 对合格书籍自动抓取元数据 | ✅（本项目入库自动抓取已实现） |
| Trigger on import | 开关 | 未能采集 | 首次加入书库时入队 | ✅（本项目 watcher 旁路调用 auto_fetch，按所属库策略执行） |
| Eligibility conditions | 条件列表（多选/规则） | 未能逐条采集 | 文案：`A book is eligible if it matches any enabled condition.` 条件列表首项为 `Never fetched • ...` | ✅（本项目按置信度阈值自动定稿，低于阈值列预览等人工确认） |

**本项目落地**：Enable auto-fetch / Trigger on import / 合格条件均已实现；达到置信度阈值的字段自动定稿，低于阈值的只列在预览页等人工确认。

### 2.23 LIBRARY → Metadata → Authors（`/settings/metadata/authors`）

页面标题 `Author Auto-Fetch`。

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 作者元数据自动抓取相关项 | 开关/分段/按钮（26 个控件） | 未能逐项采集 | 该页为作者传记与照片的自动抓取配置；页面含 `Save` 按钮（`★` 判定命中但属误报，非设置项） | ✅（本项目作者抓取已实现） |

> 该页正文 1303 字符已完整采集存档（正文抽取读的是完整 DOM，不受截图局限影响），但**未能逐项结构化**——原因与「未能采集」口径一致：页面未渲染出可判定的分段控件选中态。视觉参考见截图 `metadata__authors.jpg`（⚠️ 仅首屏，见 `bookorbit-settings-capture.md` 1.1）。

### 2.24 LIBRARY → Metadata → Genre Blocklist（`/settings/metadata/genre-blocklist`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 新增黑名单值 | 文本 + `Add` 按钮 | 空 | placeholder：`Add a genre value, for example Audiobook` | ✅（本项目题材黑名单已实现） |
| 过滤 | 文本 | 空 | placeholder：`Filter blocklist` | ✅ |

**本项目落地**：题材黑名单（新增 / 过滤）已实现。

### 2.25 LIBRARY → File Naming（`/settings/library/file-naming`）

两种组织模式各自一套命名模式：

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 各书库的模式分配 | 列表 | 9 个书库均为 `Folder as Book` | 「A library with a pattern of its own wins. Every other library follows the global default for its organization mode.」 | ✅（本项目命名规则存服务端，工具页默认载入） |
| File as Book default 模式 | 文本 | 见下方代码块（含 13 个 token） | 「Each file is one book.」；当前无书库使用该默认 | ✅（本项目 bulk-rename 的核心规则来源） |
| 按钮 | 按钮 | — | `Examples`、`Reset to shipped default` | ✅ |
| Cross-platform path sanitization | 开关 | 未能采集 | 替换 Windows 不接受的字元，预览会反映该设置 | ✅ |
| 底部状态条 | 按钮 | `No unsaved changes` | `Discard`、`Save changes` | — |

**本项目落地**：命名规则存服务端（config.naming）+ 4 个配方 + 生效预览，工具页默认载入该规则；第 20 期起支持 9 个占位符（书名 / 作者 / 系列 / 系列序号 / 顺序号 / 出版年 / 出版社 / 语言 / 扩展名）。上游的 13 token / 7 修饰符 / 结构语法未支持。实际编辑入口在「工具 → 批量重命名」（🔵）。

**File as Book 默认模式（原文，含 `|` 与 `<>` 特殊字符，故以代码块呈现）**

```text
<{authors:first}|Unknown Author>/<{series}/><{seriesIndex}. ><{title}|{originalFilename}>< ({year})>
```

**TOKENS（13）**：`{title} {subtitle} {authors} {narrators} {year} {series} {seriesIndex} {publisher} {isbn} {language} {library} {originalFilename} {extension}`

**MODIFIERS（7）**：`:first :sort :initial :fixed2 :max3 :upper :lower`

**STRUCTURE（4）**：`optional`（可选段）、`fallback`（回退）、`folder`（目录分隔）、`or`（或）

**OR START FROM A RECIPE（4 个配方 + 预览）**：
- `Series shelf` → `William Gibson/Sprawl/01. Neuromancer (1984).epub`
- `Calibre style` → `William Gibson/Neuromancer (1984).epub`
- `Alphabetical` → `G/Gibson, William/Sprawl/01. Neuromancer.epub`
- `Flat, no folders` → `William Gibson - Neuromancer (1984).epub`

**IF METADATA IS MISSING 三种降级预览**：`No series` → `/William Gibson/Neuromancer (1984).epub`；`No year` → `/William Gibson/Sprawl/01. Neuromancer.epub`；`No author` → `/Unknown Author/Sprawl/01. Neuromancer (1984).epub`

**配套说明（原文要点）**：改变模式**不会移动**磁盘上已有的书；新上传自此生效。

> 本项目已有 `docs/bookorbit-library-contract.md` 记录 `Library.fileNamingPattern` / `fileRenameEnabled`，两者可对读。

### 2.26 LIBRARY → Maintenance（`/settings/library/maintenance`）

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| UPLOADS | Maximum upload file size limit | 数字 + `MB` + `Save` | 未能采集 | 全局上传大小上限 | ✅（本项目可配置且生效） |
| IMPORT | Import library data | 按钮 `Get Started` | — | 一次性从其它书库工具导入书籍/元数据/阅读进度 | ⬜（容器部署口径下未实现，页内只读列出） |
| RECOMMENDATIONS | Refresh recommendation index | 按钮 `Run` | — | 后台重建推荐索引 | ➖（本项目无推荐系统） |
| ACHIEVEMENTS | Backfill achievements | 按钮 `Run Backfill` | — | 重算所有用户的成就 | ✅（本项目成就重算 Backfill 已实现） |
| UPDATES | Check for updates | 开关 | 未能采集 | 启动时查 GitHub 新版本，有更新时侧栏显示指示器 | ⬜（容器部署口径下未实现，页内只读列出） |

**本项目落地**：UPLOADS 上传上限（可配置且生效）、ACHIEVEMENTS 的成就重算（Backfill）、书库索引重建、缓存清理、回收站清空与各目录占用统计均已实现；IMPORT（从其它书库工具一次性导入）/ RECOMMENDATIONS（刷新推荐索引）/ UPDATES（查 GitHub 新版本）在容器部署口径下未实现，页内以只读条目列出。

### 2.27 DEVICES → Kobo（`/settings/kobo`）

页内标签：`Sync Settings` ｜ `Activity Log`（只采了默认标签）。

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| REGISTERED DEVICES | 设备列表 | 列表 + `Add device` | 1 台已注册设备（`Last sync: 7d ago`） | 设备名为个人数据，**脱敏不记录**；仅记录「列表 + 添加设备 + 每设备显示名称与最后同步时间」的形态 | ➖ |
| — | 同步前置说明 | 只读 | — | 「要在 Kobo 上收书，需在收藏夹里开启 Sync to Kobo；未开启的收藏夹不会同步」 | ➖ |
| SYNC PREFERENCES | Two-way progress sync | 开关 | 未能采集 | 双向同步阅读进度；需 KEPUB 投递 | ➖ |
| SYNC PREFERENCES | Sync BookOrbit highlights to Kobo | 开关 | 未能采集 | 反向始终导入；开启后支持双向编辑/删除；需 KEPUB | ➖ |
| SYNC PREFERENCES | Include Kobo store titles | 开关 | 未能采集 | 一并投递 Kobo 商店（含 Kobo Plus 与已购）书目，不进本库 | ➖ |
| SYNC PREFERENCES | Convert to KEPUB | 开关 | 未能采集 | 符合条件的 EPUB 转 KEPUB；开启进度/高亮同步时强制保持 | ➖ |
| SYNC PREFERENCES | Force hyphenation | 开关 | 未能采集 | 统一两端对齐，会重建缓存 KEPUB | ➖ |
| Progress Thresholds | MARK AS READING | 数字(%) | **1%** | 超过该比例置为「在读」 | ✅（本项目有 readingThreshold 同构概念） |
| Progress Thresholds | MARK AS FINISHED | 数字(%) | **99%** | 达到该比例标记「已读完」 | ✅（本项目统计口径为 ≥99.5%） |
| KEPUB CONVERSION LIMIT | 大小上限 | 数字 | **100 MB** | 超限则按普通 EPUB 发送，届时不同步阅读位置 | ➖ |
| 底部 | `Save Sync Settings` | 按钮 | 提示 `Changes must be saved to take effect.` | — | — |

### 2.28 DEVICES → KOReader（`/settings/koreader`）

页内标签：`Sync Settings` ｜ `File Naming`（只采了默认标签）。

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| KOREADER STATUS | Progress sync | 开关 | 未能采集 | 允许 KOReader 设备同步进度、阅读活动、高亮与批注删除 | ➖ |
| KOREADER STATUS | Username | 只读 + `Change credentials` | 已设置 | 同步账号 | ➖ |
| KOREADER STATUS | Last sync / Synced books / Devices / Credentials created | 只读 | `Never` / `no books` / `no devices` / 日期已设置 | 状态汇总 | ➖ |
| SETUP | KOReader sync URL | 文本 + `Copy URL` | 已生成 | 兼容 BookOrbit 插件与 KOReader 内置进度同步 | ➖ |
| SETUP | Preconfigured BookOrbit plugin | 按钮 `Download Plugin` | `Latest plugin: v1.5.2` | 预置服务器地址与同步账号的 zip；解压到 `koreader/plugins/` | ➖ |
| DEVICES | 设备列表 | 只读 | `No devices have synced yet` | 「Retiring a device hides it and keeps everything it has synced. Deleting its synced data cannot be undone.」 | ➖ |
| PLUGIN ACTIVITY | 只读 | `Refresh` | `No plugin activity has been reported yet.` | — | ➖ |
| UNMATCHED KOREADER BOOKS | 只读 + `Refresh` | — | `No unmatched KOReader books.` | — | ➖ |
| MANUAL KOREADER LINKS | 只读 + `Refresh` | — | `No manual KOReader links.` | — | ➖ |
| SETUP GUIDE | KOReader setup steps | 可展开 | — | 插件用于目录浏览/下载/进度/事件/高亮；内置插件仅进度 | ➖ |
| DANGER ZONE | Delete KOReader credentials | 按钮 `Delete` | — | 删除凭据并断开所有设备，进度数据保留 | ➖ |

**本项目落地**：本页（`settingsNav` 的 `koreader-upstream`）仅对照上游 KOReader 设置页结构；真正的对接在 `koreader` 页——本项目实现 kosync 协议的服务端：`healthcheck` / `users/auth` / `users/create` / `syncs/progress`（GET+PUT）。三个必须精确的协议细节：① 鉴权头是 `x-auth-user` / `x-auth-key`，key = 密码的 MD5（不是 Basic，服务端也只存这个哈希）；② 文档标识是 partialMD5（只采样 12 个点，偏移 `1024×4^i`，`i=-1..10`，不读第 0 字节、读不满即停），另有 `checksum_method=FILENAME` 的 `md5(basename)` 变体，两种都索引；③ `percentage` 是 0–1，progress 对 EPUB 是 XPointer、PDF/漫画是页码。进度映射：`DocFragment[N]` ↔ 本项目章节序号（`N-1`），PDF/漫画用页码；反向的 XPointer 只定位到章首，准确位置由 `percentage` 兜底。未支持：多设备管理、注解/书签同步。

### 2.29 DEVICES → OPDS（`/settings/opds`）

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| SERVER | OPDS Catalog Server | 开关 | 未能采集 | 允许 OPDS 客户端浏览与下载书籍 | ✅（本项目 OPDS 目录开关已实现） |
| ENDPOINT | 端点地址 | 只读 + `Copy` | 已生成 | 供阅读 App 填入 | ✅（本项目端点地址可复制） |
| OPDS ACCOUNTS | 账号列表 | 列表 + `Add` | 1 个账号 | 账号名可为个人数据，不展开 | ✅（本项目支持账号管理） |
| OPDS ACCOUNTS | 排序选项 | 下拉 | 未能采集 | `Recently Added / Title (A-Z) / Title (Z-A) / Author (A-Z) / Author (Z-A) / Series (A-Z) / Series (Z-A)` | ✅（本项目支持排序） |
| OPDS NOTES | 只读 | — | — | 「Use OPDS accounts in reader apps. Keep credentials private and rotate passwords if shared accidentally.」 | — |

**本项目落地**：目录开关、端点地址（可复制）、全部/最近/按作者/按系列/按标签/搜索/单书详情/封面/下载、分页（`?page=`）与排序（`?sort=recent|title|author|series&order=`）均已实现。第 14 期起支持按书库分别暴露：可见库多于一个时根 feed 多一个「按书库」入口，每个书库有独立地址 `/opds/lib/<库 id>`，可在「工具 → 书库管理 → 每库设置」逐库关掉（默认全部暴露，关掉后直连返回 404）。鉴权用 HTTP Basic + 应用账号（OPDS 客户端只会发 Basic，所以 `/opds` 不走 `/api` 的 Bearer 中间件）。未支持：独立 OPDS 账号体系。

### 2.30 DEVICES → Email（`/settings/email`）

页内标签：`Providers` ｜ `Recipients` ｜ `Groups` ｜ `Templates` ｜ `Preferences` ｜ `History`。

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| SMTP PROVIDERS | SMTP 提供者列表 | 列表 + `Add provider` | **无**（空态：`No providers yet. Add an SMTP provider to start sending emails.`） | — | ➖ |
| PROVIDER NOTES | 只读 | — | — | `System` 提供者（仅超级用户）用于密码重置邮件；`Default` 用于未显式指定提供者的送书；标记 `Shared` 的提供者对所有用户可用 | ➖ |
| 其余 5 个标签页 | — | — | **未能采集**（无 SMTP 提供者时为空态） | — | ➖ |

### 2.31 ACCOUNTS → Hardcover（`/settings/hardcover`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| API TOKEN | 密码 + `Show` | **未设置** | 「Find your token at hardcover.app/account/api.」 | ✅（本项目 Token 存储，掩码回显） |
| 动作 | 按钮 | `Validate token`、`Save` | 连接 Hardcover 账号同步阅读状态与书评 | ✅（真实连通性验证已实现） |

**本项目落地**：API Token 存储（掩码回显，提交掩码 = 不修改）+ **真实连通性验证**（向 Hardcover GraphQL 发 `{ me { id username } }` 探针）。⚠️ 其鉴权失败也可能返回 200 + `errors`，所以**不能只看状态码**。未支持：状态 / 书评同步（需先做书籍匹配）。

### 2.32 ACCOUNTS → Readwise（`/settings/readwise`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| ACCESS TOKEN | 密码 + `Show` | **未设置** | 「Add your Readwise access token to start syncing.」；`Find your token at readwise.io/access_token.` | ✅（本项目 Token 存储，掩码回显） |
| Enable sync | 开关 | 未能采集 | 自动把高亮推送到 Readwise | ⬜（同步未实现） |
| 动作 | 按钮 | `Test`、`Save` | — | ✅（真实验证已实现） |

**本项目落地**：Access Token 存储 + 真实验证（`GET /api/v2/auth/`）。⚠️ Readwise **用 204 表示验证通过**（不是 200）——按 200 判定会把有效凭据误判为失败。未支持：自动推送高亮与「Enable sync」开关。

### 2.33 ACCOUNTS → StoryGraph（`/settings/storygraph`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| _STORYGRAPH_SESSION | 密码 + `Show` | **未设置** | 从浏览器 Cookie 复制 | ✅（本项目 Cookie 存储，掩码回显） |
| REMEMBER_USER_TOKEN | 密码 + `Show` | **未设置** | 同上 | ✅（本项目 Cookie 存储，掩码回显） |
| 动作 | 按钮 | `Validate cookies`、`Save` | — | ✅（存储已实现；不做自动验证与同步） |

**说明原文要点**：StoryGraph 无公开 API，此集成复用登录态下的两个 Cookie（社区 KOReader 插件同法），可能因对方改版失效，需偶尔重新粘贴。

**本项目落地**：两个 Cookie 的存储（掩码回显）已实现；**不做自动验证与同步**——StoryGraph 没有公开 API，上游自己也只能用登录态 Cookie 并注明可能失效，本项目如实标注，而不是放一个点了没用的「Validate cookies」。

### 2.34 SERVER → Users（`/settings/admin/users`）

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| 概览 | 统计 | 只读 | `1 account · 1 with administrator access` | — | ➖ |
| 工具条 | 筛选 | 分段 + 搜索 | `All users(1) / Administrators(1) / Active(1) / Inactive(0)` | 另有 `Create user` 按钮、`Search users` 输入 | ➖ |
| 账号表 | 账号行的列构成 | 表格 | 列：`User`(含显示名/账号) ｜ `Email` ｜ `ACCESS`（角色，如 `Superuser`）｜ `LIBRARIES`（如 `All 9`）｜ `Last active` ｜ `STATUS`（`Active`）｜ `ACTIONS`（`Edit`） | 邮箱列含个人数据，**脱敏不记录具体值** | ➖ |
| DEFAULTS FOR NEW ACCOUNTS | Allow self-registration | 开关 | 未能采集 | 开启后登录页出现「创建账号」入口 | ➖ |
| DEFAULTS FOR NEW ACCOUNTS | Starting libraries | 多选（9 个书库，`0 of 9`） | 0 个 | 新账号自动获得 Viewer 权限的书库 | ➖ |
| DEFAULTS FOR NEW ACCOUNTS | 保存 | 按钮 `Save` | — | 「Applies to self-registration and OIDC」 | ➖ |

### 2.35 SERVER → Account Activity（`/settings/admin/account-activity`）

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| 概览 | 统计卡 | 只读 | `1 Recently active / 0 Dormant / 0 No recorded activity / 0 Disabled` | — | ➖ |
| 筛选 | Search accounts | 文本 | — | — | ➖ |
| 筛选 | Activity state | 下拉 | `All activity states` | 选项：`Recently active / Dormant / No recorded activity / Disabled` | ➖ |
| 筛选 | Authentication method | 下拉 | `All authentication methods` | 选项：`Local / Administrator-created / OIDC / SSO / Shared magic link` | ➖ |
| 筛选 | Sort accounts | 下拉 | 未能采集 | 选项：`Most recently active / Least recently active / Most recent login / Newest accounts / Oldest accounts / Name` + `Apply` | ➖ |
| 表格 | 账号行的列构成 | 表格 | 列：`User` ｜ `Account state` ｜ `Last login` ｜ `Last authenticated` ｜ `Created` ｜ `Reading insights`（如 `Not shared`） | `Reading insights` 反映该账号的分享级别设置 | ➖ |

### 2.36 SERVER → Magic Links（`/settings/admin/magic-links`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| ACTIVE LINKS | 列表 + `Create link` | 空态 `No shared accounts found` | 「Create a shared account from the Users page first to generate magic links.」—— **免密分享/登录链接** | ➖ |

### 2.37 SERVER → OIDC / SSO（`/settings/admin/oidc`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| PROVIDERS | 列表 + `Add Provider` | 空态 `No providers yet` | 「Add an OIDC provider to enable single sign-on for your users.」（页面说明提到 provider / claims / provisioning） | ➖ |

### 2.38 SERVER → Requests（`/settings/admin/requests`）

页内标签：`Sources` ｜ `Download clients` ｜ `Automation`。

| 分组 | 内容 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 顶部警告 | 只读 | 已显示 | `BOOK_REQUEST_ENCRYPTION_KEY is not set, so a client password cannot be saved. Generate one with: openssl rand -hex 32` | ⬜ |
| Sources | 空态 + 两种接入方式 | `No sources yet` | 方式一 `Install a plugin`（单文件插件，自己提供并填配置，可 `Browse open library plugins`）；方式二 `Add an indexer`（指向自有的 Torznab / Newznab feed，每 feed 一份配置，`Add indexer`） | ⬜ |
| 免责声明 | 只读 | — | 「BookOrbit does not provide or endorse indexer sources. Every source here is one you configured...」 | — |
| Download clients / Automation | — | **未能采集**（空态） | — | ⬜ |

**本项目落地**：上游 indexers（Torznab / Newznab 形态）未做；等价能力在「网络与下载」（书源管理 / 书源下载，🔵，本项目扩展，ready）。本设置页仅作上游对照。

### 2.39 SERVER → Book Dock（`/settings/admin/book-dock`）

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| DROP FOLDER | Container path | 只读 | `/data/book-dock` | 把书丢进该目录即被 Book Dock 自动拾取处理，支持子目录；改路径需设 `BOOK_DOCK_PATH` 环境变量 | ✅（本项目投递目录＝输入目录 + 监听） |
| METADATA | Auto-fetch metadata from providers | 开关 | 未能采集 | 文件进入 Book Dock 后自动抓取元数据 | ✅（本项目 watcher 旁路调用 auto_fetch，按所属库策略执行） |
| AUTO-FINALIZE | Enable auto-finalize | 开关 | 未能采集 | 元数据置信度达到阈值即自动定稿 | ✅（本项目达到阈值的字段自动定稿，低于阈值的列预览等人工确认） |

**本项目落地**：投递目录（＝输入目录）+ 监听状态与启停 + 自动处理开关 + 处理计数 + 入库后自动抓元数据（watcher 旁路调用 auto_fetch，按所属库的策略执行；达到置信度阈值的字段自动定稿，低于阈值的只列在预览页等人工确认）均已实现。

> 该页 `<h2>` 说明写的是「Quick actions shown on book pages.」，与页内三组内容（投递目录/元数据/自动定稿）存在表述不一致，如实记录。

### 2.40 SERVER → Server Fonts（`/settings/admin/server-fonts`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| UPLOAD FONTS | 拖拽/浏览上传 | 未上传 | `TTF, OTF, WOFF, WOFF2 - max 50 MB each` | ✅（本项目上传 / 列表 / 删除 / 选用） |
| SERVER FONTS | 只读 | `0 / 200 used` | 空态：`No server fonts yet` / 「Fonts you add here appear in every user's reader.」 | ✅（本项目与「阅读字体」共用同一份字体库，上限 200） |

**本项目落地**：服务端字体与「阅读字体」共用同一份字体库（本项目单用户部署，无「每用户 / 服务端」两级），上限 200。

### 2.41 SERVER → Audit Log（`/settings/admin/audit-log`）

| 分组 | 内容 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 筛选 | 多个筛选控件（107 个控件） | 未能逐项采集 | — | ✅（本项目活动日志支持按动作/结果/关键字筛选） |
| 流水 | 表格 | 有历史记录 | 列：`时间` ｜ `操作者`（形如 `<账号>#1`）｜ `类别` ｜ `动作` ｜ `Details`（如 `Book` / `1 book` / `Library #3`） | ✅（本项目活动日志已实现，含操作者/类别/Details） |

**本项目落地**：直接读活动日志并显示操作者（actor 为本次新增，历史条目按「未记录」渲染）+ 类别归并 + 按动作/结果/关键字筛选，已实现；上游是独立审计子系统，本项目复用活动日志。

**采集到的类别枚举（有价值，供对齐）**：`Authentication`（登录）、`Books`（移动到书库、删除书、写元数据并重命名、更新元数据与锁定、刷新元数据）、`Libraries`（创建/更新/删除书库）、`Settings`（更新作者增强配置、更新作者元数据偏好）、`Integrations`（注册/重命名 Kobo 设备）。

> **脱敏说明**：审计流中的具体账号名与书目名属个人数据，本清单只记录**类别与动作形态**，不记录具体条目。

### 2.42 DEVICES → Komga（`/settings/komga`）

> **🔄 2026-09-19 复核**：**上游实例不存在 `/settings/komga` 页面**——直连该地址会回落到 `/settings/appearance/theme`（本小节标题中的「上游页」记录已失效，仅作历史保留）。因此 Komga **不属于上游任何设置分组**；下述内容全部是**本项目扩展能力**，不是 BookOrbit 的对照项。
>
> `settingsNav` 标 `ready`（本项目扩展能力，归在 DEVICES 组）。

本项目实现「输出侧」Komga 支持：

- **输出布局开关**（`output.layout`）：有系列的书落 `系列名/系列名 #N.ext`，无系列保持平铺；
- **既有库整理**：先预览、再应用；会改 basename 的条目在应用时自动迁移阅读进度 / 批注 / 评分 / 收藏（按 `book_id` 搬迁），整理库不会把进度清零；
- **系列来源**：EPUB 的 `calibre:series` 优先，判不出则从文件名推断（`系列 第01卷` / `系列 #1` / `系列 (01)` / `系列 - 01`），都判不出就原地不动；
- **逐库暴露**（第 22 期起）：在「工具 → 书库管理 → 每库设置」关掉某库的「对 Komga 暴露」，它就不进客户端书库列表，直连它的系列 / 书籍地址也一并 404（默认全部暴露）；
- **兼容服务端补齐**：客户端可按书库浏览（系列与书籍都按库过滤），系列级「全部已读 / 全部未读」（只把百分比顶到 100，不清除读者位置），CBR 拿到正确的媒体类型；
- 有声书库不进 Komga（Komga 没有音频模型）。

**本项目可行性**：✅（输出侧布局 + 逐库暴露 + 进度迁移均已实现）；未支持「接入侧」：从 Komga 拉书目 / 下载入库、双向同步进度。

---

## 3. 权限与角色差异

| 观察 | 结论 |
|---|---|
| `permissions` chunk 存在，且 SERVER 分组下有 4 个管理页 | 该版本**具备完整的多用户 + 角色权限体系** |
| 本实例仅 1 个账号，角色为 `Superuser`，`ACCESS` 列显示 `Superuser`，`LIBRARIES` 显示 `All 9` | 当前账号可见**全部 41 页**，包括 SERVER 分组 |
| 角色枚举（从筛选器推断） | `Users` 页筛选器只有 `All users / Administrators / Active / Inactive`，**未暴露完整角色清单**；`Restrictions` 页体现「按账号分配书库 + 内容限制」的存在 |
| 权限相关设置项 | `Users → DEFAULTS FOR NEW ACCOUNTS`（自注册开关 + 新账号起始书库）；`Account Activity` 的「Authentication method」枚举了 `Local / Administrator-created / OIDC / SSO / Shared magic link` 五种来源 |

**⚠️ 未验证项**：**无法验证非管理员角色（如 viewer / editor）能看到哪些设置分区** —— 本实例只有唯一一个 Superuser 账号，且创建第二个账号属于「写入操作」，为遵守只读约束**未执行**。因此：

- 「哪些页对普通用户隐藏」——**未验证**
- 「`Users & Access`、`Requests`、`Book Dock` 等管理页是否仅 Superuser 可见」——**推测为是，但未验证**
- 若迁移需要精确的权限矩阵，应另开一轮：由用户在实例上创建一个 viewer 账号后，用该账号复核

---

## 4. 全局能力（跨分区，不在 `/settings` 路由内）

### 4.1 Appearance 快捷面板（顶栏 `Appearance` 按钮）

内容：`APPEARANCE` — `Theme`（Light/Dark/System，当前 System，判定为选中）、`Accent`（64 档色板）、`Radius`（4 档，按钮可访问名为 `Sharp corners / Default corners / Rounded corners / Pill-shaped corners`）、**`Surface opacity`（`input[type=range]`，当前 92%）**、`Background`（20 个图案按钮）。

> **⚠️ 覆盖缺口**：`Surface opacity` **只存在于这个快捷面板**，`/settings/appearance/theme` 上没有。若只按 `/settings` 对齐会漏项。

### 4.2 Language 快捷面板（顶栏 `Language` 按钮）

`SUGGESTED`：English ｜ 简体中文。`ALL LANGUAGES`：25 项（清单见 2.7）。

### 4.3 Notifications 面板（顶栏铃铛，带角标）

操作：`Mark all read`、`Clear`。内容：通知流水（含时间与摘要，如「Library scan completed」「Metadata fetch completed」「<书库名> updated」）。

### 4.4 Help 菜单（顶栏 `Help` 按钮）

`Documentation` ｜ `What's New` ｜ `About BookOrbit`。

### 4.5 用户菜单（顶栏头像）

内容：显示名、账号名、`Account`、`Change Password`、`Sign out`。

### 4.6 其它跨区能力

| 能力 | 位置 | 说明 |
|---|---|---|
| 全局搜索 | 顶栏**内联输入框**（placeholder `搜索全部书籍…`） | 全库检索；输入 ≥2 字实时联想下拉（封面 + 标题 + 作者 + 格式徽章），底部「显示所有 N 条结果」；`⌘K` 实测不聚焦、不弹面板。详见 `docs/bookorbit-feature-flows.md` §4.19 |
| 通知角标 | 顶栏铃铛 | 未读数 |
| Statistics / Achievements | 顶栏按钮 | 跳转到独立页面（`/achievements` 等） |
| Upload books | 顶栏按钮 | 上传书籍 |
| `What's New` 归档 | Help 菜单 + Notifications 开关 | 更新后弹窗可关，归档始终可访问 |
| Legal notices | 登录页页脚 / 帮助入口 | 法律声明 |

---

## 5. 与本站现有设置区的差异对照

### 5.1 结构层面（最重要的差异）

> **🔄 2026-09-19 落地现状**：设置区已按本清单完成嵌套路由改造，`frontend/src/views/SettingsView.vue` 单页形态**已不存在**。下表右列随之更新为已落地现状（真值源：`frontend/src/data/settingsNav.ts` 与 `frontend/src/router/index.ts`）。

| 维度 | BookOrbit（线上实例） | 本项目现状 |
|---|---|---|
| 路由形态 | **嵌套路由** `/settings/<域>/<页>`，41 个叶子页 | 同构：`/settings/<path>` 嵌套路由，**48 个叶子页**（上游 41 页逐页有落点 + 7 页本项目补充） |
| 一级分组 | 5 组（YOU / LIBRARY / DEVICES / ACCOUNTS / SERVER） | 6 组（上述 5 组 + `本项目扩展` / EXTENSIONS，把上游没有的四块能力隔离开） |
| 分区导航 | 左侧分组导航（可折叠、按当前所在域动态展开） | 同构：`SettingsSidebar.vue` 左侧分组导航（可折叠），条目右侧按状态标「未支持」或「本项目补充」 |
| URL 可分享 | 是（每页独立 URL） | 是（每页独立 hash 路径，可分享与刷新；`/settings/system` 别名与上游一致，重定向到文件命名页） |
| 设置项搜索 | 有（`Search settings` + `Cmd+K` 面板，42 项） | 有：设置区按 `Cmd+K` 唤起 `SettingsSearchPanel.vue`；索引由 `settingsNav.ts` 派生（页面级 + 上游页内设置项），↑↓ 选择 / ↵ 跳转 / Esc 关闭，侧栏底部有入口 |
| 偏好作用域 | 可见：Theme / Reader General 提供「本机 vs 账号」二选一 | 无（外观与阅读偏好存 localStorage；「偏好与同步」页的**具名模式**是另一种语义，不等于账号级同步） |
| 未保存变更提示 | 有（`No unsaved changes` + Discard / Save） | 有：`SettingsLayout.vue` 顶部统一提示条 + 「放弃更改」；覆盖**共享配置草稿**（`useSettingsConfig`）与**页面自持草稿**（`useSettingsDirty` 通道）两类来源，各页原有保存按钮行为不变 |
| 面包屑 | 有（`Settings > 组 > 页`） | 有（`Settings / 组 / 页`，并附「未支持」或「本项目补充」徽标） |

### 5.2 分区映射建议

| BookOrbit 分区 | 本项目现有分区 | 差异判定 |
|---|---|---|
| YOU → Profile | **账户 / Profile 页** | ✅ 已实现：账号展示、改密码、头像上传/移除、显示名、时区（接通时间类成就）、成就开关、引导重放；OIDC / Email / Username（不可改）单用户无意义，不实现 |
| YOU → Display（Theme/Book Covers/Icons/Layout/Behavior/Language） | **外观**（Theme / Book Covers 已实现；Icons / Layout / Behavior / Language 为只读占位页） | ✅ Theme / Book Covers 已实现；Icons / Layout / Behavior 由设计系统统一、不暴露为设置（`placeholder` 对照）；Language 本项目中文单语，`placeholder` 对照 |
| YOU → Reader（eBook/PDF/Comics/Audiobook/Fonts/General） | **阅读**（六页均实现） | ✅ 六页均 `ready`；eBook 个别项未支持（新书套用设置 / 固定版式页宽 / 字重样式 / 文本区左右内边距） |
| YOU → Notifications | **通知** 页 | ✅ 已实现：按类 Off / Problems / All 客户端过滤（生效范围 = 通知中心与日志） |
| YOU → Privacy & Sharing | **隐私与共享** 只读占位页 | ➖ 单用户部署下没有可分享对象（无其它账号、无管理员角色），整页不提供 |
| YOU → Restrictions | **内容限制** 只读占位页 | ➖ 单用户部署下无内容限制的应用对象，整页不提供 |
| LIBRARY → Libraries | **工具 → 书库管理**（设置页仅对照） | 🔵 多书库实体 / 自动归库 / 每库覆盖均在工具页；设置页 `placeholder` 对照 |
| LIBRARY → Metadata（7 页） | **元数据**（7 页均实现） | ✅ Providers / Field Rules / Custom Fields / Confidence Score / Books / Authors / Genre Blocklist 均 `ready` |
| LIBRARY → File Naming | **工具 → 批量重命名** | 🔵 命名规则存服务端 + 4 配方 + 预览；上游 13 token / 7 修饰符 / 结构语法未支持 |
| LIBRARY → Maintenance | 部分散落 **监听** / **工具** | ✅ 上传上限 / 成就重算 / 索引重建 / 缓存 / 回收站已实现；IMPORT / RECOMMENDATIONS / UPDATES 未实现（只读列出） |
| DEVICES → Kobo | **Kobo 同步** 只读占位页 | ➖ 不做 Kobo 设备同步（注册 / 双向进度 / KEPUB 投递 / 书店书目混投）；上游的 Progress Thresholds 在本项目无可配置对应项（已读完固定口径 ≥99.5%） |
| DEVICES → KOReader | **KOReader 进度互通**（kosync 服务端）+ **KOReader 上游对照** 占位页（本项目补充） | ✅ kosync 协议服务端已实现；上游结构页为 `placeholder` 对照，该页本身标 `own: true`（上游只有一个 KOReader 页，对照页是本项目拆出来的） |
| DEVICES → OPDS | **OPDS** 页 | ✅ 已实现（目录 / 端点 / 排序 / 逐库暴露） |
| DEVICES → Komga | **Komga 库布局** 页（**本项目补充**，标 `own: true`） | ✅ 上游无此页（原 `/settings/komga` 已消失，见 §2.42 🔄）；本项目实现输出侧布局 + 逐库暴露 + 进度迁移 |
| DEVICES → Email | **邮件投递** 只读占位页 | ➖ 无邮件投递渠道 |
| ACCOUNTS → Hardcover / Readwise / StoryGraph | **Hardcover / Readwise / StoryGraph** 页 | ✅ 凭据存储 + 真实验证已实现；同步推送（书评 / 阅读状态 / 高亮）未实现 |
| SERVER → Users & Access（4 页） | **用户** / **账号活动** / **免密链接** / **OIDC / SSO** 四个只读占位页（单用户改密仍在「账户 → 资料」） | ➖ 单用户轻登录，无角色 / 权限 / 邀请 / 免密链接 / OIDC；「账号活动」页给出通往本项目**审计日志**的入口 |
| SERVER → Audit Log | **工具 → 日志**（activity_log） | ✅ 活动日志已实现，含操作者 / 类别 / Details |
| SERVER → Book Dock | **监听**（输入目录 + watcher） | ✅ 投递目录 + 监听 + 自动抓取 + 自动定稿已实现 |
| SERVER → Requests | **求书** 只读占位页 + **网络与下载**（书源管理 / 书源下载） | ➖ 上游那套 indexer（Torznab / Newznab）+ 下载客户端 + 自动化规则的求书体系**已决策不做**（2026-09-18，见 `docs/bookorbit-capability-gap.md` 第 9 节）；功能定位相同的等价能力在本项目是「网络与下载」的书源管理，入口不同、形态也不同 |
| SERVER → Server Fonts | **服务端字体** 页 | ✅ 与阅读字体共用字体库，上限 200 |
| — | **转换**（分章模式/AI/LLM/繁转简/输出格式/Calibre） | **本项目独有**，BookOrbit 无对应页 |
| — | **监听**（watcher 9 项参数） | **本项目独有**（BookOrbit 的 watcher 是每书库的 `Watch folders` 开关 + `Scheduled scan`） |
| — | **网络与下载**（传输重试/开放下载/公版源/日志/域名替换） | **本项目独有**，BookOrbit 无对应页 |
| — | **高级**（config.yaml 原文编辑 / 覆盖层清除 / 备份列表与还原） | **本项目独有**，BookOrbit 无「直接编辑配置文件」入口 |

> 本表已完成迁移对齐（以 `settingsNav.ts` 为权威真值源）。表中「只读占位页」= `status: 'placeholder'`：页面只展示上游该页的页内分组与设置项、逐条标注「未支持」，并在页首用中文写明本项目为何不提供，**没有任何可点开关**；标「**本项目补充**」的 = `own: true`，上游根本没有这一页。两者合计使上游 41 页在本项目**逐页有落点**。§5.3 为迁移时期的处置建议，现全部落地，保留为历史记录。

### 5.3 本项目现有 8 分区的处置建议

| 现分区 | 建议 |
|---|---|
| 外观 | 保留，作为 `YOU → Display → Theme` 的落点；补「保存位置」「Surface opacity」「背景图案」，其余 Display 子页按占位新建 |
| 阅读 | 保留，拆为 `YOU → Reader → eBook`；另建 PDF / Comics / Audiobook / Fonts / General 占位页 |
| 转换 | **保留为自有扩展区**（BookOrbit 无此概念），建议改挂到 `LIBRARY` 组下或保留独立组，并在迁移说明中标注为「本项目扩展」 |
| 监听 | **保留为自有扩展区**；同时把 `SERVER → Book Dock` 作为占位页接入（两者语义接近，需在 UI 上说明区别） |
| 网络与下载 | **保留为自有扩展区** |
| 高级 | **保留为自有扩展区**（config.yaml 编辑 + 备份是本项目的安全网，BookOrbit 没有对应能力） |
| 账户 | 保留；扩展 `YOU → Profile`（头像/显示名等占位），并把 `SERVER → Users & Access` 标注为「本项目单用户模式，未支持」 |
| 关于 | 保留；可把 `Help → About BookOrbit` 的形态对读（本项目「关于」已是静态信息，属对齐） |

---

## 6. 后续迁移要点

> **🔄 2026-09-19 落地现状**：下列第 1 / 2 / 3 / 5 / 7 / 8 条**均已落地**（嵌套路由、分组命名对齐、占位页统一呈现、本项目独有能力独立分组、未保存变更提示、设置项搜索），保留原文作为迁移期的决策记录。第 4 条列出的「必须新增后端能力」各项**仍未做**——本轮只补前端的只读占位页，不含任何后端改动。

1. **先定路由形态，再动内容**。BookOrbit 的 41 页依赖嵌套路由；本项目当前是单路由 + `v-show` 分区。建议先把 `/settings` 改为**嵌套子路由**（如 `/settings/appearance/theme`），否则 41 页塞进一个组件的内联标签栏会不可维护。本项目用 hash 路由，天然支持多级路径，无需后端改动。
2. **分组命名直接对齐上游**：`YOU / LIBRARY / DEVICES / ACCOUNTS / SERVER`，侧栏项名沿用英文原文（`Theme`、`Book Covers`、`Field Rules`…）或在中文界面下做对照表；**不要自创中文名**，否则后续再对读会失真。
3. **占位项的呈现方式统一**：无后端能力的页做「只读展示页面结构 + 顶部标注」——标注文案建议统一为「未支持（本项在 BookOrbit 中的能力）」，并附 1 行原文说明；**禁止**只放一个空页面，也禁止伪造交互（点了没反应比标注「未支持」更糟）。
4. **必须新增后端能力的项，单独立项**（不要混进纯前端迁移里）：
   - 元数据抓取体系（Providers 的 14 个源 + 优先级链 + Field Rules + Confidence Score 算法）——体量最大
   - 多书库模型（若要做，会动摇 `OUTPUT_DIR` 单目录假设，影响面极大）
   - 多用户与权限（角色/邀请/免密链接/OIDC）
   - 账号级偏好同步（Theme / Reader 的「本机 vs 账号」）
   - 通知的按类开关（需要通知分类体系）
   - 字体上传与分发（Reader Fonts + Server Fonts）
   - 设备同步（Kobo / KOReader / OPDS）
   - 第三方账号集成（Hardcover / Readwise / StoryGraph）
5. **本项目独有能力必须保留**：转换 / 监听 / 网络与下载 / 高级（config.yaml 编辑 + 备份）四块在上游没有对应页。迁移时不要因为「对齐上游」而把它们删掉或降级——它们是本项目相对 BookOrbit 的核心差异。建议在设置页里用**独立分组**（如 `本项目扩展`）明确隔离，避免与上游分区混淆。
6. **敏感字段一律「已设置 / 未设置」**：LLM API Key（本项目已有该模式）应沿用；新增的 Hardcover / Readwise / StoryGraph Token、SMTP 密码、OPDS 账号同理。上游在密码框旁提供 `Show` 按钮，本项目可对读。
7. **「未保存变更」提示**：上游在多个页有 `No unsaved changes + Discard + Save` 的脏状态提示。本项目各分区已有独立「保存」按钮，建议补充脏标记与「放弃更改」，否则用户改完不知道有没有生效。
8. **设置项搜索（`Search settings` + Cmd+K）**：41 页之后，没有搜索会很难用。建议在迁移时同步实现（可先做前端侧的设置项索引）。
9. **对齐时以本清单的「当前值」列为校验基线**：本清单中的当前值来自该实例的实际状态，用于验证「迁移后是否保留了同名同义设置」。标注「未能采集」的项**不要**用上游截图臆测默认值。
10. **迁移前先复核权限矩阵**：本轮因只读约束未验证非管理员视角（见第 3 节）。若迁移要把 `SERVER` 分组做进去，需先确认哪些页对普通用户隐藏。
11. **截图与文档同步更新**：迁移完成后，本清单与 `docs/review/bookorbit-settings-shots/` 的对照关系应保留（截图是「上游长什么样」的最终依据）。
12. **与既有契约文档联动**：`docs/bookorbit-library-contract.md` 已定义 `Library.fileNamingPattern` / `fileRenameEnabled` / `readingThreshold` / `markAsFinishedPercentComplete` 等字段，与本清单的 File Naming（2.25）、Kobo 进度阈值（2.27）直接对应，两文应保持同步修订。

---

## 7. 🔄 复核纪要（2026-09-19）

> 复核对象：同一线上实例的另一入口 `http://192.168.0.95:3400/`（账号角色 Superuser，界面此时渲染为**简体中文**）。方式：Playwright 真实登录后逐路由渲染采集 + 向页面注入 fetch/XHR 钩子读真实网络流量，**全程只读**（仅导航、展开折叠、读 DOM、移动鼠标唤出阅读器工具条）。功能与流程的逐域描述见并列文档 `docs/bookorbit-feature-flows.md`。

### 7.1 差异与修正（均已就地更新）

| # | 项 | 原记录 | 复核结论 | 落点 |
|---|---|---|---|---|
| 1 | `DEVICES → Komga` | 上游存在 `/settings/komga` | **上游无此页**，直连回落 `/settings/appearance/theme` | §1.1 🔄 / §2.42 🔄 |
| 2 | 侧栏分组数 | 5 组 | 实测 **5 组**：`YOU / LIBRARY / DEVICES / ACCOUNTS / SERVER`（原记录成立） | §1.1 |
| 3 | 叶子页总数 | 41 | **41**（复算成立：DOM 内 `a[href^="/settings"]` 29 + `appearance/*` 6 + `reader/*` 6） | §1.1 🔄 |
| 4 | `/settings/system` | 未记录 | 实测为**别名路由**，重定向到 `/settings/library/file-naming` | §1.1 🔄 |
| 5 | 设置项跳转面板 | 「未能采集」 | 已采集：`Cmd+K` 面板 **42 项** | §1.1 🔄 |
| 6 | 全局搜索 | 「顶栏搜索框（`Search all books...`，带 `⌘K`）」 | 实为**内联输入框**（`搜索全部书籍…`），输入 ≥2 字实时联想下拉；`⌘K` 实测不聚焦、不弹面板 | §4.6 |

**🔄 2026-09-19 落地对照**（本表结论 → 本项目实现）：

| # | 复核结论 | 本项目落实情况 |
|---|---|---|
| 1 | 上游无 `/settings/komga` | 本项目把 Komga 作为**本项目补充页**保留并标 `own: true`（不冒充上游页） |
| 2 | 上游 5 组 | 对齐 5 组 + 1 个 `本项目扩展` 组，共 6 组 |
| 3 | 上游 41 个叶子页 | 上游 41 页**逐页有落点**；本项目共 48 页（+7 页本项目补充） |
| 4 | `/settings/system` 为别名路由 | 已实现同名别名：`{ path: 'system', redirect: { name: 'settings-library-file-naming' } }`，契约测试钉住 |
| 5 | `Cmd+K` 设置项跳转面板 | 已实现：设置区 `Cmd+K` 唤起设置项搜索浮层（索引由 `settingsNav.ts` 派生，非平行清单） |
| 6 | `⌘K` 不聚焦顶栏搜索 | 本项目保留顶栏 `⌘K` 聚焦全局搜索，但**在设置路由下让位**给设置项搜索浮层，避免一次按键触发两个行为 |

### 7.2 本轮新增采集、原清单未覆盖项

- **阅读器内置设置面板**（在 `/read/*` 内，**不是** `/settings/reader/*`）：主题（亮/暗）、字号（`A` 步进，实测 16px）、**13 档页面底色**（默认主题/灰度/护眼棕/…/纯黑 AMOLED）、字体族、字重与斜体、行间距、段间距、页面宽度、阅读模式（分页/滚动）；另有「高级排版设置」：分栏数、列间距、`Letter spacing`、`Word spacing`、`First-line indent`（三者均为 `Book / Custom`）、对齐文本、连字符断字。详见 `docs/bookorbit-feature-flows.md` §4.18。
- **`/api/v1` 端点清单**：页面向 `fetch`/`XHR` 注入钩子得到的真实调用（如 `/api/v1/user-preferences/*`、`/api/v1/dashboard/widgets/batch`、`/api/v1/libraries/:id/books/jump-buckets`、`/api/v1/kobo/devices`、`/api/v1/opds-users`、`/api/v1/book-dock/summary` 等），见 `docs/bookorbit-feature-flows.md` §5。
- **前端全站路由盘**与设置组之外的管理页（`/settings/admin/metadata*`、`/settings/integrations` 等别名/落点），见 `docs/bookorbit-feature-flows.md` §2、§3.9。

### 7.3 仍未验证项（维持原判）

- **非管理员角色的可见性**：实例只有唯一一个 Superuser 账号，创建第二个账号属写操作，为遵守只读约束未执行（详见第 3 节）。
- 个别开关的当前值（如「缩略图点击行为」）仍标注「未能采集」，**未做推测补全**。
