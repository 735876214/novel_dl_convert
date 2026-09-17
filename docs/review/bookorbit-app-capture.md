# BookOrbit 非设置页 — 原始采集证据（留档）

> 本文件是 `docs/bookorbit-capability-gap.md` 的可追溯依据，记录非设置页能力的采集方式、逐页结果、截图索引与未能采集项。
> **脱敏声明**：不含账号、密码、邮箱、令牌、密钥等真实敏感值；含账号显示名的页面截图**主动未归档**。
> 采集日期：2026-09-16 ｜ 账号角色：Superuser ｜ 线上版本：**v2.10.0**

---

## 1. 采集方式

| 项 | 内容 |
|---|---|
| 目标实例 | `https://orbit.735876214.xyz:16666`（站点名 `BookOrbit`） |
| 工具 | `playwright-cli`（Chromium 1210，无头） |
| 登录 | 在 `/login` 完成真实登录（凭据不落盘、不入库、不写入本目录） |
| 只读约束 | 仅导航、展开、点击进入子页、读 DOM、截图；**未点击任何保存 / 删除 / 提交 / 启用 / 重置类控件** |
| 范围 | **只补非设置页**；设置页 41 页已于上一轮完整采集（`docs/review/bookorbit-settings-capture.md`），**未重采** |
| 持久化 | 页面内 `console.log('NFDATA ' + JSON.stringify(负载))` → CLI 落盘 `.playwright-cli/console-*.log` → 本地脚本解析（避免逐页 YAML 快照产生巨量中间产物） |

## 2. 采集过程中的四个坑与处置

| 坑 | 现象 | 处置 |
|---|---|---|
| **筛选被截断** | 早期一次 `run-code` 的返回值被工具输出截断，丢掉一半页面 | 改用 console.log 落盘通道，stdout 只回一行摘要 |
| **页面内卡片不是 `<a>`** | `/library/:id` 上书籍卡、`/authors` 上作者行均非锚点，`a[href]` 只能抓到侧栏的 18 个链接 | 改用**点击后观察 `location.pathname`**；并对详情页直接做 URL 模式探测 |
| **详情页路由无规律** | `click` 未命中（返回 `clicked` 但 URL 不变） | 直接探测 URL 模式，得到 `/book/:id`、`/authors/:id`、`/series/:id` 三个可用形态 |
| **`fullPage` 截图无效** | 首次 21 张截图里 **11 张恒为 720px**（视口高），内容被裁 | 见下节 |

## 3. 截图修正（重要，纠正上一轮遗留缺陷）

**问题**：应用使用**内层滚动容器**，`document.body` 高度恒等于视口，`page.screenshot({fullPage:true})` 无内容可扩展。

**两次失败尝试**：
1. 从 `main` **向上**逐级设 `overflow:visible; height:auto; max-height:none` → 无效（11 页仍 720）
2. 把**被裁剪容器自身**的高度撑到其 `scrollHeight` → 仍无效（`docScrollH` 恒为 720）——原因是**祖先链上还有固定高度容器**

**最终有效做法**：**把视口高度撑到内容高度**，让内层容器随视口展开：

```
先量出 maxH = max(所有元素的 scrollHeight, window.innerHeight)
迭代最多 3 次设 viewport = min(maxH + 60, 20000)，每次重测 maxH
最后直接 screenshot（非 fullPage）
```

**实测结果**：11 页重截后高度 **1006px**（原先 720px，即被裁掉约 286px），图像高与内容高一致，**判定全部完整**。

> 结论：`fullPage` 对本应用**无效**；可靠做法是撑视口，而非解除容器 overflow。（该坑已写入 `docs/bookorbit-capability-gap.md` 第 15 节执行约定。）

## 4. 逐页采集结果

| 路由 | 页面 | 正文 | 截图 | 备注 |
|---|---|---|---|---|
| `/` | Dashboard | 1526 高 | ⛔ **未归档**（含账号显示名） | 12 个部件：Reading Streak / Currently Reading / Reading Goal / Reading DNA / Monthly Challenge / Highlight of the Day / Neglected Gems / Recently Added 等 |
| `/libraries` | Libraries | 185 | `libraries.jpg` | 书库列表 |
| `/library/3` | Library · 某书库 | 1159 | `library-3.jpg` | 书架页，6842px 整页 |
| `/book/301` | Book · 某书 | 507 | `book-301.jpg` | 五标签 + DETAILS + EDITIONS |
| `/authors` | Authors | 1557 | `authors.jpg` | 226 作者 |
| `/authors/1` | Author · 某作者 | 261 | `author-1.jpg` | 传记 / Actions |
| `/series` | Series | 315 | `series.jpg` | — |
| `/series/1` | Series · 某系列 | 349 | `series-1.jpg` | 排序 / Group by media |
| `/annotations` | Annotations | 360 | `annotations.jpg` | 空态 |
| `/statistics` | Statistics | 3354 | `statistics.jpg` | 两大标签 + 8 类图表 |
| `/achievements` | Achievements | 2596 | `achievements.jpg` | 3314px 整页 |
| `/collections` | Collections | 133 | `collections.jpg` | 空态 |
| `/smart-scopes` | Smart Scopes | 145 | `smart-scopes.jpg` | 空态 |
| `/book-dock` | Book Dock | 201 | `book-dock.jpg` | 5 态标签 + 拖拽投递 |
| `/requests` | Requests (Beta) | 1047 | `requests.jpg` | 完整请求表单 + 「无搜索源」提示 |
| `/tools/entity-manager` | Entity Manager | 598 | `tools-entity-manager.jpg` | — |
| `/tools/bulk-rename` | Bulk Rename | 214 | `tools-bulk-rename.jpg` | **需先选书库** |
| `/tools/duplicate-books` | Duplicate Books | 412 | `tools-duplicate-books.jpg` | 阈值 85% |
| `/tools/missing-resources` | Missing Resources | 371 | `tools-missing-resources.jpg` | Cover check |
| `/whats-new` | What's New | — | `whats-new.jpg` | **16987px 整页** |
| `/tasks` | — | 78 | `tasks.jpg` | **404（线上无任务中心）** |

截图归档：`docs/review/bookorbit-app-shots/`（**20 张**；仪表盘 1 张因含账号显示名主动排除）。

## 5. 顶栏浮层（非路由）

| 浮层 | 内容 |
|---|---|
| Notifications | `Notifications` + 「Review and manage your notifications.」 + `Mark all read` / `Clear` + 通知流水（`Library scan completed` / `Metadata fetch completed` 等，含相对时间与计数摘要） |
| Help | `Documentation` / `What's New` / `About BookOrbit` |
| Upload books | 未捕获弹层（应为系统文件选择框） |
| 用户菜单 | 显示名 / 账号 / `Account` / `Change Password` / `Sign out`（**具体值属个人数据，不记录**） |

## 6. 未能采集项（含原因）

| 项 | 原因 |
|---|---|
| **阅读器界面**（ePub / PDF / 漫画 / 有声书） | **未定位到独立路由**：`/read/:id`、`/book/:id/read`、`/reader/:id` 均返回 404；入口应在书籍详情页内（按钮渲染在原页），本次未能进入。其**能力面已在设置页采集覆盖**（四类阅读器的全部设置项，见 `docs/review/bookorbit-settings-capture.md`） |
| 书籍详情「Edit Metadata」标签内容 | 需点击标签才渲染；本次采集了标签名与 `Details` 内容，未逐标签展开 |
| 书籍详情「Files」「Highlights」标签内容 | 同上 |
| 上传弹层 | 系统文件选择框，非 DOM 浮层 |
| 求书 `Download clients` / `Automation` 段的具体字段 | 无可用索引器时为空态；设置页侧已采集其结构（`docs/bookorbit-settings-inventory.md` 2.38） |
| Kobo / KOReader 同步实际操作界面 | 属设置页范围，已在设置页采集中记录（2.27 / 2.28） |
| 智能书架 / 收藏夹的**已创建实例** | 该实例为空态（`No Smart Scopes yet` / `No collections yet`），只能采集空态与服务端返回的结构 |
| 成就具体条目 | `/achievements` 正文已采集（2596 字符），未逐条展开解锁条件 |

## 7. 页面环境观察

| 项 | 值 |
|---|---|
| 站点版本 | **v2.10.0**（侧栏底部与 `/whats-new` 一致） |
| 页面标题格式 | `<页名> · BookOrbit` |
| 侧栏结构 | 主导航 4 项 + `BROWSE` + `LIBRARIES` + `SMART SCOPES` + `COLLECTIONS`，底部版本号 / ⌘K / 通知角标 / 头像 |
| 顶栏 | Toggle Sidebar / 全局搜索（⌘K）/ Notifications / Statistics / Achievements / Upload books / Help / Appearance / Language / Settings / 头像 |
| 书籍详情标签 | `Details` / `Edit Metadata` / `Files` / `Reading Log` / `Highlights` |
| 阅读状态 | `Unread` / `Reading` / `Read`，含 `Date Started` / `Date Finished` |
| Reading Log 指标 | `Total time` / `Sessions` / `Average session` / `Active days` / `Pace` / `Last read` |
| 统计页图表 | Library Integrity / Format Distribution / Metadata Score Distribution（P50/P90）/ Metadata Freshness / Top 50 Largest Books |
| 工具页签 | 仅 4 个：Entity Manager / Bulk Rename / Duplicate Books / Missing Resources |
