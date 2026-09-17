# BookOrbit 设置页功能清单（迁移用）

> 来源：`https://orbit.735876214.xyz:16666/settings`（线上实例，站点名 `BookOrbit`）
> 用途：本文件是 **novel_dl_convert 设置页「全部对齐（含占位）」迁移** 的对照基准，与 `docs/bookorbit-library-contract.md` 并列。
> 采集方式：浏览器自动化（Playwright CLI）**真实登录后逐页渲染采集**；全程只读——仅导航、展开折叠分组、读取 DOM、截图，**未点击任何保存 / 应用 / 删除 / 重置 / 启用 / 上传 / 退出 / 同步类控件**，未向任何输入框提交内容。
> 采集日期：2026-09-15 ｜ 账号角色：Superuser（该实例为单账号本地部署）
> 证据：逐页采集记录与未能采集项见 `docs/review/bookorbit-settings-capture.md`；分区截图见 `docs/review/bookorbit-settings-shots/`
> ⚠️ 截图局限：该批截图**实为 1440×1000 视口截图，仅覆盖各页首屏**（应用使用内层滚动容器，`fullPage` 未生效）。本清单的文字结论取自完整 DOM 抽取，不受此影响；但截图不可当作「整页」证据。详见 `bookorbit-settings-capture.md` 的 1.1 节。
> **脱敏**：全文不含账号、密码、邮箱、令牌、密钥等任何真实敏感值；此类字段一律只记「已设置 / 未设置」。
> **准确性约定**：未取得可信值的项一律标注「未能采集」并说明原因，**不做推测补全**。

---

## 0. 图例

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
- 共 **23 个入口** = 17 个直接链接 + 3 个可展开分组（`Display` 6 项、`Reader` 6 项、`Metadata` 7 项、`Users & Access` 4 项）
- 展开后共 **41 个叶子页**
- 侧栏底部提示 `Press Cmd K to jump to any setting`（设置项级跳转面板；本次未成功唤起，其内容未能采集）
- 面包屑格式：`Settings > <组> > <页>`；`document.title` 格式：`<页标题> · BookOrbit`
- 侧栏有折叠按钮 `Toggle Sidebar` / `Collapse sidebar`

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
| 头像 | 按钮 `Upload picture` / `Remove picture` | 已设置（PNG/JPEG/WEBP ≤5MB） | 头像位显示首字母 `Y` | 🟡 |
| Full name | 文本 | 已设置 | 显示名 | 🟡 |
| Username | 只读 | 已设置 | 「Your username cannot be changed.」 | ⬜ |
| Email | 只读 | 已设置 | 「Contact an administrator to change your email address.」 | ➖ |
| Timezone | 下拉（长列表，按洲/城市） | 未能采集（下拉未展开，仅见选项列表） | 「用于 Early Bird / All-nighter 等与时间相关的成就」 | ⬜ |
| Enable achievements | 开关 | 未能采集 | 关闭后不统计成就、不显示成就相关界面 | ➖ |
| Guided Tour | 按钮 `Take the tour again` | — | 重放新手引导 | ⬜ |
| Change password | 按钮 | — | 「Change the password you use to sign in.」 | ✅（本项目已有「修改密码」） |
| Connected Accounts | 只读 | 无 OIDC 提供者 | 「Ask an administrator to set up SSO.」 | ➖ |

**联动**：`Enable achievements` 关闭 → 成就界面隐藏（说明文字明确），但与 Notifications 里的成就通知是分开管理的。

### 2.2 YOU → Display → Theme（`/settings/appearance/theme`）

| 设置项 | 控件 | 当前值 | 说明 / 联动 | 本项目可行性 |
|---|---|---|---|---|
| **外观偏好的保存位置** | 单选卡（2 项） | `My account`（ACTIVE） | `This device only`＝存浏览器；`My account`＝存账号，多设备一致 | 🟡（本项目全部存 localStorage，无账号级同步） |
| Color scheme | 分段（3） | **System** | Light / Dark / System | ✅（本项目有浅色/深色/跟随系统） |
| Accent color | 色板（64 档，5 行×16 未满） | **存在分歧，未能确证** | 见下注 | ✅（本项目有 65 档点缀色） |
| Corner radius | 分段（4） | **Default** | Sharp / Default / Rounded / Pill | ✅（本项目有 4 档圆角） |
| Background pattern | 图形按钮（4 组共 20） | 未能采集 | 组：FUNDAMENTAL(4) / STRUCTURAL(6) / AMBIENT(5) / REFRACTIVE(5)；按钮无文本/`aria-label` | ⬜ |

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
| Default cover search provider | 分段（3） | 未能采集 | `DuckDuckGo` / `iTunes` / `All Sources`；存账号，多端一致 | ⬜ |
| Cover display mode | 分段（3） | **Fill card** | `Blurred fit`（模糊填充保完整）/ `Fill card`（裁切填满）/ `Natural bottom`（保比例底部对齐） | ⬜ |
| Book spine overlay | 分段（3） | **Subtle** | `Off` / `Subtle` / `Strong`：给封面卡加书脊+光泽效果 | ⬜ |
| Show spine on comics | 开关 | 未能采集 | 对 cbz/cbr/cb7 封面同样应用书脊效果 | ⬜ |
| Book details cover tint | 分段（3） | **Two colours** | `Off` / `One colour` / `Two colours`：详情页从封面取色做背景渐变 | ⬜ |
| Cover shadow strength | 分段（2） | 未能采集 | `Default` / `Strong`：网格、列表、表格、仪表盘缩略图的封面阴影 | ⬜ |
| Card overlays | 多选（6 项） | 未能采集 | 封面上直接叠加的元数据：`Progress bar` / `File format` / `Rating` / `Read status` / `Series number` / `Lock status` | ⬜ |

### 2.4 YOU → Display → Icons（`/settings/appearance/icons`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Upload icons | 上传区 | 未上传（0 个） | 自定义图标上传 | ➖ |
| 图标风格 | — | **未能采集** | 标题说明为「Choose the icon style used across the app.」，但页面正文仅 134 字符、控件 5 个（含上传/排序/空态），风格选项未渲染为可判定控件 | ➖ |
| 排序 | 分段 | 未能采集 | `Newest` / `Name` | ➖ |

**空态文案**：`No custom icons uploaded yet.`

### 2.5 YOU → Display → Layout（`/settings/appearance/layout`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Cover size behavior | 分段（2） | 未能采集 | `Sync all views` / `Per-view sizes`；Per-view 时在各自视图的 Display 面板调 | ⬜ |
| Portrait cover size | 滑杆/数字 | 130px | 竖向书库与视图的封面尺寸 | ⬜ |
| Square cover size | 滑杆/数字 | 150px | 方形书库与视图的封面尺寸 | ⬜ |
| Portrait grid spacing | 滑杆/数字 | 28px | 竖向封面的网格间距 | ⬜ |
| Square grid spacing | 滑杆/数字 | 28px | 方形封面的网格间距 | ⬜ |
| Card info mode | 分段（3） | **On hover** | `On hover` / `Below cover` / `Off`：网格卡上标题作者的显示位置 | ⬜ |
| Collapsed series cover | 分段（5） | **Stack** | `Stack` / `Mosaic` / `First` / `Latest` / `First Unread`：系列折叠时用哪张封面 | 🟡 |
| Author grid → Cover size | 滑杆/数字 | 120px | 作者网格封面宽度 | 🟡 |
| Author grid → Cover shape | 分段（2） | 未能采集 | `Circle` / `Square` | 🟡 |
| List and table → Zebra striping | 开关 | 未能采集 | 表格斑马纹 | ✅（本项目表格可对齐） |

### 2.6 YOU → Display → Behavior（`/settings/appearance/behavior`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Thumbnail clicks | 分段（2） | 未能采集 | `Read first`（有可读文件直接进阅读器）/ `Open details`（进详情页） | ✅（本项目已有阅读入口，可加此开关） |
| Show filter preview by default | 开关 | 未能采集 | 打开智能书架时自动展开筛选与排序摘要 | ⬜ |
| Collapse series by default | 开关 | 未能采集 | 在书库/收藏夹/智能书架中把同系列书折叠为一张卡 | 🟡 |

### 2.7 YOU → Display → Language（`/settings/appearance/language`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Language | 下拉（自定义按钮，`aria-expanded`） | `English` | 「Choose the language used across the interface.」 | ⬜（本项目为中文单语） |

**完整语言清单**（取自顶栏 Language 快捷面板，见 4.2）：SUGGESTED = `English` / `简体中文`；ALL LANGUAGES 共 25 项：`Bahasa Indonesia, Čeština, Dansk, Deutsch, English, Español, Français, Italiano, Magyar, Nederlands, Polski, Português, Română, Slovenčina, Slovenščina, Suomi, Svenska, Türkçe, Ελληνικά, Русский, Українська, 한국어, 日本語, 简体中文, 繁體中文`

> 观察：未登录的登录页为中文，登录后按账号语言显示英文（`<html lang="en">`）——即服务端有默认语言，账号语言覆盖之。

### 2.8 YOU → Reader → eBook（`/settings/reader/ebook`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| NEW BOOKS → Apply my settings to new books | 开关 | 未能采集 | 关闭时新书沿用出版方字体与排版，改动后才应用设置 | ✅（本项目的 reader-prefs 可扩展） |
| LAYOUT → Reading flow | 分段（2） | 未能采集 | `Paginated`（翻页）/ `Scrolled`（滚动） | ⬜（本项目为滚动） |
| Fixed-layout page spreads | 分段（3） | 未能采集 | `Book default` / `Single page` / `Columns`（漫画、图像型 EPUB 默认值） | ⬜ |
| Columns | 数字 | 2 | 每页文本列数 | ⬜ |
| THEME → Dark mode | 分段（13） | 未能采集 | 深色变体：`Default, Gray, Sepia, Crimson, Meadow, Rosewood, Azure, Dawnlight, Ember, Aurora, Ocean, Mist, AMOLED` | 🟡（本项目阅读主题仅 3 档） |
| TYPOGRAPHY → Font | 分段（4） | 未能采集 | `Book default` / `Serif` / `Sans-serif` / `Monospace` | ✅（本项目有 3 档字体） |
| Font style | 分段（4） | 未能采集 | `Regular` / `Bold` / `Regular Italic` / `Bold Italic` | ⬜ |
| Font size | 滑杆 | 16px | 基准字号 | ✅ |
| Line height | 滑杆 | 1.5 | 行高 | ✅ |
| Paragraph spacing | 分段 | 未能采集 | `Book default` / 自定义 | ⬜ |
| Justify text | 开关 | 未能采集 | 两端对齐 | ⬜ |
| Hyphenation | 开关 | 未能采集 | 自动断词 | ⬜ |
| ADVANCED → Letter spacing | 分段 | 未能采集 | `Book default` / `Custom` | ⬜ |
| Word spacing | 分段 | 未能采集 | `Book default` / `Custom` | ⬜ |
| First-line indent | 分段 | 未能采集 | `Book default` / `Custom` | ⬜ |
| Max content width | 滑杆 | 720px | 文本区最大宽度 | ✅（本项目有「内容宽度」，单位 rem） |
| Column gap | 滑杆 | 5% | 文本区左右内边距 | ⬜ |
| Reset to defaults | 按钮 | — | 恢复默认 | ✅ |

### 2.9 YOU → Reader → PDF（`/settings/reader/pdf`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Scroll mode | 分段（3） | **Scrolled** | `Page`（逐页翻）/ `Scrolled`（连续）/ `Horizontal`（横向） | ⬜ |
| Page spread | 分段（4） | **None** | `None` / `Odd` / `Even` / `Auto`：双页视图中起始页在哪侧 | ⬜ |
| Default fit | 分段（4） | **Fit Width** | `Fit Page` / `Fit Width` / `Automatic` / `Custom` | ⬜ |
| Reset to defaults | 按钮 | — | — | ⬜ |

### 2.10 YOU → Reader → Comics（`/settings/reader/comics`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Reading mode | 分段（3） | **Paginated** | `Paginated` / `Infinite (spaced)` / `Infinite (no gaps)`（条漫） | ⬜ |
| Page view | 分段（2） | 未能采集 | `Single` / `Two-page` | ⬜ |
| Fit mode | 分段（4） | **Page** | `Page` / `Width` / `Height` / `Actual` | ⬜ |
| Reading direction | 分段（2） | 未能采集 | `L to R`（西文漫画）/ `R to L`（日漫） | ⬜ |
| Spread alignment | 分段（2） | 未能采集 | `Normal` / `Shifted`：修正扫描件封面错位 | ⬜ |
| Spread gap | 滑杆/数字 | 0px | 双页视图页间距 | ⬜ |
| Wide-page handling | 分段（2） | 未能采集 | `Auto` / `Disable`：宽幅扫描件单独显示 | ⬜ |
| Force two-page on small screens | 开关 | 未能采集 | 小屏也强制双页 | ⬜ |
| Auto-advance to next book | 开关 | 未能采集 | 翻过最后一页打开系列下一本 | ⬜ |
| DISPLAY → Background color | 分段（3） | **Black** | `Black` / `Gray` / `White`：画布底色 | ⬜ |
| Reset to defaults | 按钮 | — | — | ⬜ |

### 2.11 YOU → Reader → Audiobook（`/settings/reader/audio`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| Default playback speed | 分段（6） | **1x** | `0.75x / 1x / 1.25x / 1.5x / 1.75x / 2x` | ➖（本项目无有声书） |
| Default volume | 滑杆 | 100% | 初始音量 0–100 | ➖ |
| Skip back duration | 分段（4） | **10s** | `5s / 10s / 15s / 30s` | ➖ |
| Skip forward duration | 分段（4） | **30s** | `10s / 15s / 30s / 60s` | ➖ |
| Reset to defaults | 按钮 | — | — | ➖ |

### 2.12 YOU → Reader → Fonts（`/settings/reader/fonts`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| UPLOAD FONTS | 拖拽/浏览上传 | 未上传 | 支持 `TTF, OTF, WOFF, WOFF2`，单个 ≤50MB | ⬜ |
| YOUR FONTS | 只读 | `0 / 50 used` | 空态：`No fonts uploaded yet` / `Drag a font file above to get started.` | ⬜ |

### 2.13 YOU → Reader → General（`/settings/reader/general`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 阅读偏好的保存位置 | 单选卡（2） | `My account`（ACTIVE） | `This device only`＝存浏览器；`My account`＝存账号，多设备一致 | 🟡（本项目 reader-prefs 仅 localStorage） |

> 该页只有这一项（与 Display→Theme 的「保存位置」同构，是全站「偏好作用域」模式的第二个实例）。

### 2.14 YOU → Notifications（`/settings/account/notifications`）

顶部汇总：`LIBRARY 11 of 11 enabled`（10 个业务条目 + 1 个总开关语义）。

**每条业务通知的控件形态**：一个通知级别分段，选项为 `Off` / `Problems` / `All`；`All` 的描述为「Notify me every time, including successes.」，`Problems` 仅失败时通知，`Off` 关闭。**采集到的当前值：LIBRARY / FILES / INTEGRATIONS 下 10 条全部为 `All`**（`★` 判定命中）。

| 分组 | 设置项 | 说明 | 本项目可行性 |
|---|---|---|---|
| LIBRARY | Library scanning | 书库扫描完成/失败/发现缺失书 | ✅（本项目有监听与任务中心） |
| LIBRARY | Metadata fetching | 元数据抓取完成或失败 | ⬜ |
| LIBRARY | Author enrichment | 作者传记与照片抓取完成 | ⬜ |
| FILES | File write-back | 编辑后的元数据写回磁盘文件 | 🔵（本项目 bulk-rename 写入能力） |
| FILES | File rename | 单本书文件按命名模式重命名 | ✅（本项目有批量重命名） |
| FILES | Bulk rename | 批量重命名或跨书库移动完成/失败 | ✅ |
| FILES | Data migration | 从其它书库工具导入完成/失败 | ⬜ |
| INTEGRATIONS | Book Dock | Book Dock 定稿完成或异常 | ⬜ |
| INTEGRATIONS | Book requests | 求书提交/审批/到货 | ⬜ |
| INTEGRATIONS | Email delivery | 送书到邮箱成功/失败 | ➖ |
| PERSONAL | Achievements | 解锁新成就（仅 `Off` / `All`，无 `Problems` 档） | ➖ |
| APP UPDATES | Show "What's New" after updates | 开关；更新后弹新功能提示，归档始终可访问 | ⬜ |

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
| 书库名 | 9 个：`漫画, 刘备, 有声书, 工具书, 插图书, 教学, 杂志, 其他, 连环画` | 列表按此展示 | 🟡（本项目单 OUTPUT_DIR） |
| 组织模式 | `Folder mode` | 另有 `File as Book` 模式（见 2.25） | 🟡 |
| 文件夹数 + 路径 | `1 folder` / `/books/<名称>` | 可多个文件夹 | 🟡 |
| 书籍数 + 占用 | 如 `55 books` / `2.4 GB` | — | ✅ |
| 格式分布 | 如 `PDF 46 / CBZ 6 / CBR 1 / EPUB 1 / MOBI 1` | 按格式计数 | 🟡 |
| Watch folders | `On` | 监听文件夹 | ✅（本项目 watcher） |
| Scheduled scan | `At 12:00 AM` | 定时扫描 | ✅（本项目有 cron 概念） |
| Write to file | `Off` | 元数据写回文件 | 🔵 |
| Rename files | `On` | 按命名模式重命名 | 🔵 |
| LAST SCAN | `Scanned 2 days ago` / `Failed 17 hours ago` + 小字（如 `Server restarted during scan`）+ 原因标签（`Schedule - no change` / `Manual - no change`） | 扫描状态与原因 | ✅ |
| 行动按钮 | `Scan` | 单库扫描 | ✅ |

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
| Combine genres from all selected providers | 开关 | 未能采集 | 对 Genres 字段收集并去重所有提供者的结果，而非首个命中即停 | ⬜ |
| Maximum genres per book | 数字 | 未能采集（留空＝不限） | 在排除与去重之后应用 | ⬜ |
| Store provider IDs on books | 开关 | 未能采集 | 保存返回的提供者 ID（ISBN/ASIN/Goodreads ID 等）以供后续更准查询 | ⬜ |
| Use existing provider IDs only | 开关 | 未能采集 | 已有书只用已存的 ID 查询，ID 查询失败也不回退到搜索（不影响手动搜索与新书发现） | ⬜ |

顶部工具条：`All / Enabled / Needs setup` 筛选；底部状态条 `No unsaved changes` + `Discard` + `Save Global defaults`。

### 2.19 LIBRARY → Metadata → Field Rules（`/settings/metadata/field-rules`）

逐字段规则矩阵（204 个控件，是设置页中控件最多的一页）。每个字段一行，每行含：

| 维度 | 取值 | 采集到的当前值 |
|---|---|---|
| 覆盖策略 | `Overwrite if provided` / `Merge with existing` 等 | 绝大多数字段为 **`Overwrite if provided`**（「Write if provider returned a value」）；`Genres` 为 **`Merge with existing`**（4 选项组） |
| 其它列 | 该页还有锁定/优先级相关列 | 未能逐列采集（矩阵列头未在正文中呈现） |

**本项目可行性**：⬜（本项目无元数据抓取体系，此页整体属占位范围）。

> ⚠️ 该页是设置页中控件最多的一页（204 个）。本次已采集完整正文与控件清单，但**截图仅为视口首屏**（原因见 `bookorbit-settings-capture.md` 的 1.1 节），整页视觉还原需另取整页截图。

### 2.20 LIBRARY → Metadata → Custom Fields（`/settings/metadata/custom-fields`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| NEW FIELD 表单 | 表单（未展开填写） | 无自定义字段 | 定义自定义元数据字段并选择适用书库 | 🟡 |
| FIELDS 列表 | 只读 | `No custom fields yet` | 「Drag to reorder, edit labels, toggle libraries, or archive fields」 | 🟡 |

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

**本项目可行性**：⬜（整体属占位；「元数据完整度」对本书库有参考价值，可作为后续独立需求）

### 2.22 LIBRARY → Metadata → Books（`/settings/metadata/auto-fetch`）

页面标题 `Book Auto-Fetch`，`<h2>` 为 `Books`。说明：「Automatically fetch covers, descriptions, and other details when new books are added to your library.」

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| GLOBAL SETTINGS → Enable auto-fetch | 开关 | 未能采集 | 对合格书籍自动抓取元数据 | ⬜ |
| Trigger on import | 开关 | 未能采集 | 首次加入书库时入队 | ⬜ |
| Eligibility conditions | 条件列表（多选/规则） | 未能逐条采集 | 文案：`A book is eligible if it matches any enabled condition.` 条件列表首项为 `Never fetched • ...` | ⬜ |

### 2.23 LIBRARY → Metadata → Authors（`/settings/metadata/authors`）

页面标题 `Author Auto-Fetch`。

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 作者元数据自动抓取相关项 | 开关/分段/按钮（26 个控件） | 未能逐项采集 | 该页为作者传记与照片的自动抓取配置；页面含 `Save` 按钮（`★` 判定命中但属误报，非设置项） | ⬜ |

> 该页正文 1303 字符已完整采集存档（正文抽取读的是完整 DOM，不受截图局限影响），但**未能逐项结构化**——原因与「未能采集」口径一致：页面未渲染出可判定的分段控件选中态。视觉参考见截图 `metadata__authors.jpg`（⚠️ 仅首屏，见 `bookorbit-settings-capture.md` 1.1）。

### 2.24 LIBRARY → Metadata → Genre Blocklist（`/settings/metadata/genre-blocklist`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 新增黑名单值 | 文本 + `Add` 按钮 | 空 | placeholder：`Add a genre value, for example Audiobook` | 🟡（本项目的题材治理可复用） |
| 过滤 | 文本 | 空 | placeholder：`Filter blocklist` | 🟡 |

**本项目可行性整体**：🟡（本项目有实体管理工具，可扩展一个「题材黑名单」）

### 2.25 LIBRARY → File Naming（`/settings/library/file-naming`）

两种组织模式各自一套命名模式：

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 各书库的模式分配 | 列表 | 9 个书库均为 `Folder as Book` | 「A library with a pattern of its own wins. Every other library follows the global default for its organization mode.」 | 🟡 |
| File as Book default 模式 | 文本 | 见下方代码块（含 13 个 token） | 「Each file is one book.」；当前无书库使用该默认 | ✅（本项目 bulk-rename 的核心规则来源） |
| 按钮 | 按钮 | — | `Examples`、`Reset to shipped default` | ✅ |
| Cross-platform path sanitization | 开关 | 未能采集 | 替换 Windows 不接受的字元，预览会反映该设置 | ✅ |
| 底部状态条 | 按钮 | `No unsaved changes` | `Discard`、`Save changes` | — |

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
| UPLOADS | Maximum upload file size limit | 数字 + `MB` + `Save` | 未能采集 | 全局上传大小上限 | ✅（本项目可加） |
| IMPORT | Import library data | 按钮 `Get Started` | — | 一次性从其它书库工具导入书籍/元数据/阅读进度 | ⬜ |
| RECOMMENDATIONS | Refresh recommendation index | 按钮 `Run` | — | 后台重建推荐索引 | ➖ |
| ACHIEVEMENTS | Backfill achievements | 按钮 `Run Backfill` | — | 重算所有用户的成就 | ➖ |
| UPDATES | Check for updates | 开关 | 未能采集 | 启动时查 GitHub 新版本，有更新时侧栏显示指示器 | ⬜ |

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

### 2.29 DEVICES → OPDS（`/settings/opds`）

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| SERVER | OPDS Catalog Server | 开关 | 未能采集 | 允许 OPDS 客户端浏览与下载书籍 | 🟡（本项目已有 /api/books，做只读 OPDS 订阅源可行） |
| ENDPOINT | 端点地址 | 只读 + `Copy` | 已生成 | 供阅读 App 填入 | 🟡 |
| OPDS ACCOUNTS | 账号列表 | 列表 + `Add` | 1 个账号 | 账号名可为个人数据，不展开 | 🟡 |
| OPDS ACCOUNTS | 排序选项 | 下拉 | 未能采集 | `Recently Added / Title (A-Z) / Title (Z-A) / Author (A-Z) / Author (Z-A) / Series (A-Z) / Series (Z-A)` | 🟡 |
| OPDS NOTES | 只读 | — | — | 「Use OPDS accounts in reader apps. Keep credentials private and rotate passwords if shared accidentally.」 | — |

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
| API TOKEN | 密码 + `Show` | **未设置** | 「Find your token at hardcover.app/account/api.」 | ⬜ |
| 动作 | 按钮 | `Validate token`、`Save` | 连接 Hardcover 账号同步阅读状态与书评 | ⬜ |

### 2.32 ACCOUNTS → Readwise（`/settings/readwise`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| ACCESS TOKEN | 密码 + `Show` | **未设置** | 「Add your Readwise access token to start syncing.」；`Find your token at readwise.io/access_token.` | ⬜ |
| Enable sync | 开关 | 未能采集 | 自动把高亮推送到 Readwise | ⬜ |
| 动作 | 按钮 | `Test`、`Save` | — | ⬜ |

### 2.33 ACCOUNTS → StoryGraph（`/settings/storygraph`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| _STORYGRAPH_SESSION | 密码 + `Show` | **未设置** | 从浏览器 Cookie 复制 | ⬜ |
| REMEMBER_USER_TOKEN | 密码 + `Show` | **未设置** | 同上 | ⬜ |
| 动作 | 按钮 | `Validate cookies`、`Save` | — | ⬜ |

**说明原文要点**：StoryGraph 无公开 API，此集成复用登录态下的两个 Cookie（社区 KOReader 插件同法），可能因对方改版失效，需偶尔重新粘贴。

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

### 2.39 SERVER → Book Dock（`/settings/admin/book-dock`）

| 分组 | 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|---|
| DROP FOLDER | Container path | 只读 | `/data/book-dock` | 把书丢进该目录即被 Book Dock 自动拾取处理，支持子目录；改路径需设 `BOOK_DOCK_PATH` 环境变量 | 🟡（与本项目「输入目录 + watcher」高度同构） |
| METADATA | Auto-fetch metadata from providers | 开关 | 未能采集 | 文件进入 Book Dock 后自动抓取元数据 | ⬜ |
| AUTO-FINALIZE | Enable auto-finalize | 开关 | 未能采集 | 元数据置信度达到阈值即自动定稿 | 🟡 |

> 该页 `<h2>` 说明写的是「Quick actions shown on book pages.」，与页内三组内容（投递目录/元数据/自动定稿）存在表述不一致，如实记录。

### 2.40 SERVER → Server Fonts（`/settings/admin/server-fonts`）

| 设置项 | 控件 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| UPLOAD FONTS | 拖拽/浏览上传 | 未上传 | `TTF, OTF, WOFF, WOFF2 - max 50 MB each` | ⬜ |
| SERVER FONTS | 只读 | `0 / 200 used` | 空态：`No server fonts yet` / 「Fonts you add here appear in every user's reader.」 | ⬜ |

### 2.41 SERVER → Audit Log（`/settings/admin/audit-log`）

| 分组 | 内容 | 当前值 | 说明 | 本项目可行性 |
|---|---|---|---|---|
| 筛选 | 多个筛选控件（107 个控件） | 未能逐项采集 | — | 🟡（本项目已有 activity_log，可升级为审计流） |
| 流水 | 表格 | 有历史记录 | 列：`时间` ｜ `操作者`（形如 `<账号>#1`）｜ `类别` ｜ `动作` ｜ `Details`（如 `Book` / `1 book` / `Library #3`） | 🟡 |

**采集到的类别枚举（有价值，供对齐）**：`Authentication`（登录）、`Books`（移动到书库、删除书、写元数据并重命名、更新元数据与锁定、刷新元数据）、`Libraries`（创建/更新/删除书库）、`Settings`（更新作者增强配置、更新作者元数据偏好）、`Integrations`（注册/重命名 Kobo 设备）。

> **脱敏说明**：审计流中的具体账号名与书目名属个人数据，本清单只记录**类别与动作形态**，不记录具体条目。

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
| 全局搜索 | 顶栏搜索框（`Search all books...`，带 `⌘K` 提示） | 全库检索 |
| 通知角标 | 顶栏铃铛 | 未读数 |
| Statistics / Achievements | 顶栏按钮 | 跳转到独立页面（`/achievements` 等） |
| Upload books | 顶栏按钮 | 上传书籍 |
| `What's New` 归档 | Help 菜单 + Notifications 开关 | 更新后弹窗可关，归档始终可访问 |
| Legal notices | 登录页页脚 / 帮助入口 | 法律声明 |

---

## 5. 与本站现有 SettingsView 的差异对照

### 5.1 结构层面（最重要的差异）

| 维度 | BookOrbit（线上实例） | 本项目现状（`frontend/src/views/SettingsView.vue`） |
|---|---|---|
| 路由形态 | **嵌套路由** `/settings/<域>/<页>`，41 个叶子页 | **单一路由** `/settings` + 8 个 `v-show` 分区（页内标签） |
| 页面数量 | 41 | 1 |
| 一级分组 | 5 组（YOU / LIBRARY / DEVICES / ACCOUNTS / SERVER） | 8 个平铺分区 |
| 分区导航 | 左侧分组导航（可折叠、带搜索） | 页内横向标签栏 |
| URL 可分享 | 是（每页独立 URL） | 否（hash 路由无二级路径，刷新回默认分区） |
| 设置项搜索 | 有（`Search settings` + Cmd+K 面板） | 无 |
| 偏好作用域 | 可见：Theme / Reader General 提供「本机 vs 账号」二选一 | 无（外观与阅读全部存 localStorage） |
| 未保存变更提示 | 有（`No unsaved changes` + Discard / Save） | 分区各自有「保存」按钮，无脏数据提示 |
| 面包屑 | 有（`Settings > 组 > 页`） | 无 |

### 5.2 分区映射建议

| BookOrbit 分区 | 本项目现有分区 | 差异判定 |
|---|---|---|
| YOU → Profile | **账户** | 命名不一致：本项目「账户」只有账号展示 + 改密码；缺头像/显示名/时区/成就开关/引导重放/已连接账号 |
| YOU → Display（Theme/Book Covers/Icons/Layout/Behavior/Language） | **外观** | 部分对齐：Type 对应 Theme 的主题/点缀色/圆角；缺 Book Covers、Icons、Layout、Behavior、Language 五页，且无「保存位置」与「Surface opacity」「背景图案」 |
| YOU → Reader（eBook/PDF/Comics/Audiobook/Fonts/General） | **阅读** | 部分对齐：eBook 的字体/字号/行高/内容宽度/主题对应得上；缺 PDF、Comics、Audiobook、Fonts、General 五页；eBook 内的 13 档深色变体、两端对齐、断词、字距/词距/首行缩进等均缺 |
| YOU → Notifications | 无 | **缺失**（本项目有消息，但无可配置项） |
| YOU → Privacy & Sharing | 无 | **缺失**（单用户场景无意义，建议占位或标注不适用） |
| YOU → Restrictions | 无 | **缺失**（同上） |
| LIBRARY → Libraries | 无（单 `OUTPUT_DIR` 模型） | **架构级差异**：本项目是单成品目录；BookOrbit 是多书库 + 多文件夹 + 每库自动化 |
| LIBRARY → Metadata（7 页） | 无（仅有实体管理工具） | **整体缺失**，且是 41 页中体量最大的一块（Providers / Field Rules / Custom Fields / Confidence Score / Books / Authors / Genre Blocklist） |
| LIBRARY → File Naming | **工具 → 批量重命名** | 🔵 能力等价但入口不同：本项目已有 tokens 概念与预览执行；**缺「配方（recipe）」与 IF-METADATA-IS-MISSING 降级预览** |
| LIBRARY → Maintenance | 部分散落在 **监听** / **工具** | 命名与分组不一致 |
| DEVICES → Kobo / KOReader / OPDS / Email | 无 | **整体缺失** |
| ACCOUNTS → Hardcover / Readwise / StoryGraph | 无 | **整体缺失** |
| SERVER → Users & Access（4 页） | **账户**（仅单用户改密） | **架构级差异**：本项目是单用户轻登录，无角色/权限/邀请/免密链接/OIDC |
| SERVER → Audit Log | 工具 → 日志（`activity_log`） | 🔵 能力形似但不含操作者/类别/Details 结构 |
| SERVER → Book Dock | **监听**（输入目录 + watcher） | 🔵 **高度同构**：`/data/book-dock` ↔ 本项目 `INPUT_DIR`；「丢进去自动处理」↔ 目录监听；「auto-finalize 置信度阈值」↔ 可扩展 |
| SERVER → Requests | 工具 → 书源管理 / 书源下载 | 🔵 部分同构（都在做「从外部获取书」），但形态不同（插件/PT indexer vs 本项目书源规则） |
| SERVER → Server Fonts | 无 | **缺失** |
| — | **转换**（分章模式/AI/LLM/繁转简/输出格式/Calibre） | **本项目独有**，BookOrbit 无对应页 |
| — | **监听**（watcher 9 项参数） | **本项目独有**（BookOrbit 的 watcher 是每书库的 `Watch folders` 开关 + `Scheduled scan`） |
| — | **网络与下载**（传输重试/开放下载/公版源/日志/域名替换） | **本项目独有**，BookOrbit 无对应页 |
| — | **高级**（config.yaml 原文编辑 / 覆盖层清除 / 备份列表与还原） | **本项目独有**，BookOrbit 无「直接编辑配置文件」入口 |

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
