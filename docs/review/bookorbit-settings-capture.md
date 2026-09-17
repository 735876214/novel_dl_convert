# BookOrbit 设置页 — 原始采集证据（留档）

> 本文件是 `docs/bookorbit-settings-inventory.md` 的可追溯依据，记录采集方式、逐页采集结果、未能采集项与截图索引。
> **脱敏声明**：本文件不含账号、密码、邮箱、令牌、Cookie 等任何真实敏感值。页面上出现的此类字段一律只记「已设置 / 未设置」。
> 采集日期：2026-09-15。账号角色：Superuser（该实例为单账号本地部署）。

---

## 1. 采集方式

| 项 | 内容 |
|---|---|
| 目标实例 | `https://orbit.735876214.xyz:16666`（站点名 `BookOrbit`） |
| 工具 | `playwright-cli`（Playwright CLI，Chromium 1210，无头模式） |
| 登录 | 使用用户提供的账号在 `/login` 完成真实登录（凭据不落盘、不入库、不写入本目录） |
| 渲染 | 逐页 `goto → 等待 main h2 → 等待 1.1–9s → 抽取`；SPA 懒加载，必须真实渲染 |
| 只读约束 | 仅执行导航、展开折叠分组、读取 DOM、截图。**未点击** 保存 / 应用 / 删除 / 重置 / 启用 / 上传 / 退出 / 同步 类控件；未向任何输入框提交内容 |
| 抽取内容 | 页面标题、面包屑、`h1–h4` 标题、正文全文、全部可见控件的类型/标签/ARIA/禁用态/值/同组关系 |
| 选中态识别 | 优先 `aria-checked`；无 ARIA 时用「同父兄弟按钮组中样式唯一者」判定，并以 `★` 标记；无法判定者记「未采集」 |
| 截图 | 每页 JPEG（quality 72）——⚠️ 实为**视口截图 1440×1000**，非整页，见 1.1 |
| 二次复采 | 首轮 6 页渲染超时，用更长等待复采；复采失败的空结果**不覆盖**首轮好结果（按正文字符数取最大者合并） |

采集脚本（一次性，采集完成后已清理，非仓库产物）：`nav.js`（导航发现）、`driver.js`（批量抽取）、`sel.js`（选中项识别）、`retry.js`（超时复采）、`parse.py`（日志解析）。

> 采集链路说明：`playwright-cli` 无法从页面侧访问文件系统，故采用「页面内 `console.log('NFDATA ' + JSON.stringify(负载))` → CLI 自动将页面控制台消息落盘到 `.playwright-cli/console-*.log` → 本地脚本解析日志」的方式持久化采集结果；截图由 `page.screenshot({ path, fullPage: true, type: 'jpeg', quality: 72 })` 直接写盘。此方式避免了逐页 YAML 快照带来的庞大中间产物。

### 1.1 ⚠️ 截图局限（重要，事后复核发现）

**问题**：调用时传了 `fullPage: true`，但它**未生效**。该应用使用**内层滚动容器**（`main` 元素自身带 `overflow`，外层是固定高度的 flex 布局），`document.body` 的高度恒等于视口高度，因此 fullPage 没有可扩展的内容。

**实测**：39 张截图**全部恰好为 1440×1000**（创建时的视口尺寸），**没有一张高于视口**。校验方式：逐张解析 JPEG 的 SOF 段读取宽高，尺寸分布为 `1440x1000 -> 39 张`，高度 ≠ 1000 的张数为 0。

**影响范围**：截图**只覆盖每页首屏**。页面较长时，首屏以下的内容（例如 Theme 页的背景图案区、Confidence Score 的字段权重表、Audit Log 的历史流水、Field Rules 的完整矩阵、Providers 的逐字段优先级链下半部分）**未被截取**。

**不影响什么**：本清单的**文字结论不受影响**——正文抽取读的是完整 DOM（`root.innerText`），与截图无关，因此各页的字段、取值、说明仍然是完整的。受影响的只是「视觉佐证」的完整性。

**修复方式**（若需重做）：截图前临时解除内层容器的滚动约束 —— 从 `main` 起逐级向上把 `overflow` 设为 `visible`、`height` 设为 `auto`、`max-height` 设为 `none`，并放开 `documentElement` 的 overflow，再执行 fullPage 截图，最后校验图像高度 > 1000。重做需要重新登录该实例。

## 2. 导航结构发现过程

1. 直接访问 `/settings` → 302 到 `/login?redirect=/settings/appearance/theme`，说明设置页是**嵌套路由**而非单页。
2. 登录后落在 `/settings/appearance/theme`。
3. 读取 `nav[aria-label="Settings sections"]` 得到 23 个入口。
4. `Reader`、`Metadata`、`Users & Access` 三个分组初始为 `aria-expanded="false"`，点击展开后子项才渲染 —— 补齐 18 个隐藏路由。
5. 最终得到 **41 个叶子页**，与 5 个分组逐一对账一致（16 + 10 + 4 + 3 + 8 = 41）。

## 3. 逐页采集结果

`正文` = 清理顶栏噪声后的正文字符数；`控件` = 抽取到的可见控件数。

| # | 路由 | 页面标题 | 正文 | 控件 | 截图 |
|---|---|---|---|---|---|
| 1 | `/settings/account/profile` | Account | 7670 | 9 | ⛔ 含账号/邮箱，**未归档** |
| 2 | `/settings/appearance/theme` | Display | 623 | 91 | `appearance__theme.jpg` |
| 3 | `/settings/appearance/book-covers` | Book Covers | 1693 | 19 | `appearance__book-covers.jpg` |
| 4 | `/settings/appearance/icons` | Icons | 134 | 5 | `appearance__icons.jpg` |
| 5 | `/settings/appearance/layout` | Display Layout | 1036 | 18 | `appearance__layout.jpg` |
| 6 | `/settings/appearance/behavior` | Library Behavior | 502 | 4 | `appearance__behavior.jpg` |
| 7 | `/settings/appearance/language` | Language | 122 | 1 | `appearance__language.jpg` |
| 8 | `/settings/reader/ebook` | eBook Reader | 1604 | 33 | `reader__ebook.jpg` |
| 9 | `/settings/reader/pdf` | PDF Reader | 349 | 12 | `reader__pdf.jpg` |
| 10 | `/settings/reader/comics` | Comics Reader | 927 | 24 | `reader__comics.jpg` |
| 11 | `/settings/reader/audio` | Audiobook Player | 404 | 16 | `reader__audio.jpg` |
| 12 | `/settings/reader/fonts` | Reader Fonts | 204 | 0 | `reader__fonts.jpg` |
| 13 | `/settings/reader/general` | Reader Settings | 352 | 0 | `reader__general.jpg` |
| 14 | `/settings/account/notifications` | Notifications | 1263 | 33 | `account__notifications.jpg` |
| 15 | `/settings/account/privacy` | Privacy & Sharing | 603 | 3 | `account__privacy.jpg` |
| 16 | `/settings/account/restrictions` | Content Restrictions | 161 | 0 | `account__restrictions.jpg` |
| 17 | `/settings/libraries` | Libraries | 1963 | 31 | `libraries.jpg` |
| 18 | `/settings/metadata/providers` | Providers | 1741 | 26 | `metadata__providers.jpg` |
| 19 | `/settings/metadata/field-rules` | Field-Level Rules | 4112 | 204 | `metadata__field-rules.jpg` |
| 20 | `/settings/metadata/custom-fields` | Custom Metadata | 333 | 1 | `metadata__custom-fields.jpg` |
| 21 | `/settings/metadata/score` | Confidence Score | 2322 | 82 | `metadata__score.jpg` |
| 22 | `/settings/metadata/auto-fetch` | Book Auto-Fetch | 1691 | 52 | `metadata__auto-fetch.jpg` |
| 23 | `/settings/metadata/authors` | Author Auto-Fetch | 1303 | 26 | `metadata__authors.jpg` |
| 24 | `/settings/metadata/genre-blocklist` | Genre Blocklist | 328 | 3 | `metadata__genre-blocklist.jpg` |
| 25 | `/settings/library/file-naming` | File Naming | 1978 | 47 | `library__file-naming.jpg` |
| 26 | `/settings/library/maintenance` | Maintenance | 694 | 6 | `library__maintenance.jpg` |
| 27 | `/settings/kobo` | Kobo Sync | 1920 | 14 | `kobo.jpg` |
| 28 | `/settings/koreader` | KOReader Sync | 1488 | 12 | `koreader.jpg` |
| 29 | `/settings/opds` | OPDS | 381 | 7 | `opds.jpg` |
| 30 | `/settings/email` | Providers · Email | 422 | 8 | `email.jpg` |
| 31 | `/settings/hardcover` | Hardcover | 202 | 4 | `hardcover.jpg` |
| 32 | `/settings/readwise` | Readwise | 304 | 5 | `readwise.jpg` |
| 33 | `/settings/storygraph` | StoryGraph | 693 | 5 | `storygraph.jpg` |
| 34 | `/settings/admin/users` | Users | 603 | 21 | ⛔ 含邮箱列，**未归档** |
| 35 | `/settings/admin/account-activity` | Account Activity | 610 | 9 | `admin__account-activity.jpg` |
| 36 | `/settings/admin/magic-links` | Magic Links | 172 | 1 | `admin__magic-links.jpg` |
| 37 | `/settings/admin/oidc` | OIDC / SSO | 163 | 1 | `admin__oidc.jpg` |
| 38 | `/settings/admin/requests` | Requests | 854 | 6 | `admin__requests.jpg` |
| 39 | `/settings/admin/book-dock` | Book Dock | 597 | 2 | `admin__book-dock.jpg` |
| 40 | `/settings/admin/server-fonts` | Server Fonts | 241 | 0 | `admin__server-fonts.jpg` |
| 41 | `/settings/admin/audit-log` | Audit Log | 4027 | 107 | `admin__audit-log.jpg` |

截图归档：`docs/review/bookorbit-settings-shots/`（39 张，另 2 张因含账号邮箱等个人数据主动排除）。

## 4. 采集过程中的失败与处置

| 页面 | 现象 | 处置与结果 |
|---|---|---|
| `/settings/appearance/language` | 首轮 text=0 | 加长等待后成功（正文 122） |
| `/settings/metadata/auto-fetch` | 前两轮均超时（`main h2` 45s 未出现） | 第三次 9s 等待成功；页面本身正常（标题 `Book Auto-Fetch`） |
| `/settings/library/file-naming` | 复采轮次不稳定（一轮成功一轮超时） | 合并策略保留正文最长的一次（1978） |
| `/settings/admin/users` | 首轮 text=0 | 加长等待后成功 |
| `/settings/admin/oidc` | 首轮 text=0 | 加长等待后成功 |

**结论**：41 页全部取得正文与控件，无缺失页。页面渲染耗时差异较大（部分页 >7s），需要显式等待而非固定短延时。

## 5. 未能采集 / 存在分歧的项

以下项**未取得可信值**，清单中一律标注「未能采集」，不做推测补全：

| 位置 | 项 | 原因 |
|---|---|---|
| Display → Theme | 点缀色当前值 | **信号分歧**：`<html class="accent-blue">` 与 `--primary=oklch(48.7% .25 263)` 指向 Blue；但色板 64 项中仅 `White` 带非空 `box-shadow`（疑为选中环，亦可能是首项聚焦环）。两者矛盾，未确证 |
| Display → Theme | 背景图案当前值 | 4 组共 20 个图案按钮无 `aria-label`/文本（纯图形），也无选中态信号 |
| Display → Icons | 图标风格当前值 | 页面主体是上传区，风格选项未渲染为可判定控件（正文仅 134 字符） |
| Display → Language | 语言下拉的完整选项 | 设置页只显示当前值 `English`（自定义下拉，未展开）；完整语言列表取自顶栏 Language 快捷面板 |
| Reader → eBook | Reading flow / Font / 段落间距 / 字距等分段控件的当前值 | 「同父样式唯一性」判定未命中（选项间样式差异不足以区分） |
| Reader → Fonts | 字体列表 | 未上传任何字体（`0 / 50 used`），无可采集项 |
| Reader → General | 偏好保存位置以外的项 | 该页仅一个两组单选（device/account），无其他设置 |
| Content Restrictions | 限制项列表 | 该账号「无内容限制」，页面为空态，无法采集具体限制项形态 |
| Metadata → Custom Fields | 新增字段表单 | 无自定义字段，仅空态与未展开的新增表单 |
| Email | Recipients / Groups / Templates / Preferences / History 标签页 | 6 个标签页存在，但「无任何 SMTP 提供者」，各页为空态；本次仅采集标签名与 SMTP 提供者表单 |
| Requests | Sources / Download clients / Automation 标签页 | 顶部提示 `BOOK_REQUEST_ENCRYPTION_KEY` 未设置；三个标签页均为空态 |
| KOReader | File Naming 标签页 | `Sync Settings` 与 `File Naming` 两个标签，仅采集默认标签 |
| Kobo | Activity Log 标签页 | `Sync Settings` 与 `Activity Log` 两个标签，仅采集默认标签 |
| 各页「未保存变更」提示条 | `No unsaved changes / Discard / Save` | 属未提交状态提示，非设置项本身 |

## 6. 跨分区入口（非 `/settings` 路由）

这些入口承载了 `/settings` 页面**没有**的项，需纳入对齐范围：

| 入口 | 位置 | 内容 |
|---|---|---|
| Appearance 快捷面板 | 顶栏 `Appearance` 按钮 | Theme（Light/Dark/System）、Accent（64 档）、Radius（4 档）、**Surface opacity（滑杆，当前 92%）**、Background（20 个图案：None/Dots/Cross/Millimeter/Blueprint/Brushed/Scanlines/Vinyl/Carbon/Perforated/Aurora/Horizon/Glow/Mesh/Elevation/Prism/Spectrum/Spectrum X/Spectrum Plus/Eclipse） |
| Language 快捷面板 | 顶栏 `Language` 按钮 | SUGGESTED（English / 简体中文）+ ALL LANGUAGES（共 25 个语言项） |
| Notifications 面板 | 顶栏铃铛（角标计数） | 「Mark all read」「Clear」+ 通知流水列表 |
| Help 菜单 | 顶栏 `Help` 按钮 | Documentation / What's New / About BookOrbit |
| 用户菜单 | 顶栏头像 | 显示名、账号、`Account`、`Change Password`、`Sign out` |
| Legal notices | 登录页页脚 | 法律声明弹窗入口 |

> **重点发现**：`Surface opacity` 只存在于 Appearance 快捷面板，`/settings/appearance/theme` 页面上没有该项。若只按 `/settings` 对齐会漏掉它。

## 7. chunk 线索核对（分区完整性交叉验证）

首屏 `modulepreload` 中与设置/偏好相关的 chunk，与本次采集到的分区对照：

| chunk | 对应设置域 | 是否在设置页出现 |
|---|---|---|
| `useDisplaySettings` | YOU → Display（6 页） | 是 |
| `permissions` | SERVER → Users & Access（4 页） | 是 |
| `useLibraries` | LIBRARY → Libraries | 是 |
| `useBookMetadataFetchStatus` | LIBRARY → Metadata → Books（自动抓取） | 是 |
| `useWhatsNew` | YOU → Notifications → APP UPDATES | 是 |
| `useAuth` | YOU → Profile（安全与会话）+ 用户菜单 | 是 |
| `useSmartScopes` | **未见**独立设置页 | 智能书架属书库浏览侧功能，不是设置项 |
| `useCollections` | **未见**独立设置页 | 收藏夹属侧栏实体，不是设置项 |
| `useLegalNotices` | **未见**设置页 | 仅在登录页页脚与帮助入口 |

核对结论：**不存在被遗漏的设置分区**。`useSmartScopes` / `useCollections` / `useLegalNotices` 三项均为「非设置页」能力，符合预期。

## 8. 页面环境观察（供参考）

| 项 | 值 |
|---|---|
| `<html lang>` | `en`（登录后按账号语言；未登录的登录页为中文） |
| `<html class>` | `accent-blue` |
| 根节点内联样式 | `--bg-lift: 0.0420; --shell-surface-opacity: 92%` |
| 页面标题格式 | `<页标题> · BookOrbit`（登录页为 `<标题> · BookOrbit`） |
| 侧栏持久化提示 | `Press Cmd K to jump to any setting`（Cmd+K 面板本次未成功唤起，未采集其内容） |
| API 前缀 | `/api/v1/...`（如 `/api/v1/auth/refresh`） |
| 未登录时的 401 | 打开 `/settings` 会触发一次 `/api/v1/auth/refresh` 401（登录前），属正常鉴权流程 |
