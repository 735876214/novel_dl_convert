# 组件与模块 API（component-api）

> 范围：`frontend/src` 的**组件 props/emit**、**stores 公共 API**、**lib 单一判据函数**、**composables**、**注册表结构**。
> 视觉规范见 `docs/DESIGN.md`；后端接口见 `README.md` 与 FastAPI 自带文档 `/docs`。
> ⚠️ 本文是**约定与索引**，不是自动生成文档：改公共 API 时**请同步改这里**（见 `docs/development.md` §7）。

## 1. 目录与分层

```
components/
  ui/            UI 原语（16 个）—— 新页面优先复用
  reader/        阅读器：PdfReader / ComicReader / AudioPlayer / **UnitsReader**（序号单元合集）
  book/          书籍域组件（编辑/预览/移动/记录/系列面板）+ detail/ 详情页子标签
  dashboard/     仪表盘外壳 + widgets/ 13 个部件（前 12 件对齐上游 + 1 件自开）+ registry.ts
  charts/        图表壳 + library/ 18 张 + reading/ 12 张（共 30）
  tools/         工具页共用（书库向导 / 逐库设置 / 刮削面板 …）
  settings/      引导弹窗 + 设置项搜索浮层
  （根级）       AppSidebar / AppHeader / AppToast / LoginGate / NotificationBell /
               TaskFlyout / UserMenu / AppearanceMenu / SettingsSidebar /
               MetadataScoreCard
               （`MigrationGateDialog` 已于第 77 期随「按格式归库」删除）
```

## 2. UI 原语（`components/ui/`）

| 组件 | props | emit / slot |
|---|---|---|
| `Card` | `padding?: 'none'\|'sm'\|'md'`、`muted?: boolean` | 默认 slot |
| `Button` | `variant?: 'primary'\|'secondary'\|'ghost'\|'danger'`、`size?: 'sm'\|'md'`、`block?`、`disabled?`、`title?` | `click` |
| `Badge` | `tone?: 'neutral'\|'accent'\|'ok'\|'warn'\|'err'`、`pill?: boolean` | 默认 slot |
| `Icon` | `name`（取自 `lib/icons.ts`）、`class` | — |
| `IconButton` | `label`、`tooltip?`、`active?`、`expanded?`、`badge?` | `click`（顶栏圆形按钮，含气泡与角标） |
| `DropdownMenu` | `open`、`align?`、`panelClass?`、`triggerClass?` | slot `trigger` / `panel`（内部 `Teleport` 到 body + 手动定位） |
| `BookCover` | `book`、`showTitle?`、`interactive?`、`shape?: 'portrait'\|'circle'` | —（真实内嵌封面；缺图回退 `c1/c2` 渐变占位） |
| `EmptyState` | `icon?`、`title`、`desc?`、`dashed?` | slot `action` |
| `PageHead` | `title`、`desc?` | — |
| `ProgressBar` | `value`、`max?`、`tone?: 'primary'\|'ok'`、`size?: 'sm'\|'md'` | — |
| `ProgressRing` | `value`、`max`、`size?`、`thickness?` | —（conic-gradient） |
| `RatingStars` | `modelValue`、`readonly?`、`size?: 'sm'\|'md'` | `update:modelValue` |
| `Segment` | `options`、`modelValue` | `update:modelValue`（设置页分段单选） |
| `SwatchGrid` | `items`、`modelValue` | `update:modelValue`（8 列点缀色网格） |
| `TabBar` | `tabs`、`modelValue` | `update:modelValue` |
| `StatTile` | `label`、`value`（字符串）、`hint?` | — |

## 3. 阅读器（`components/reader/`）

| 组件 | props | emit | 备注 |
|---|---|---|---|
| `PdfReader` | `bookId: string`、`title: string`、`comicLib?: boolean`、`series?: string`、`fileRel?: string`、`unit?: UnitRef` | `pdfMode: ['comic' \| 'pdf']`、`unitPos`、`unitEnd` | pdf.js **动态 import 懒加载**；滚动模式按 `IntersectionObserver` 逐页渲染；`fileRel` **不给 = 书级进度**（判据必须 `!== undefined`，空串合法） |
| `ComicReader` | `bookId`、`title`、`series?`、`source?: 'archive' \| 'pdf'`、`fileRel?`、`unit?: UnitRef` | `pdfMode`、`unitPos`、`unitEnd` | 页图按需 `/api/books/{id}/comic/{index}`（**允许 `?token=`**）；CBR 缺解压器时接口 503 |
| `AudioPlayer` | `bookId: string`、`tracks: AudioTrack[]`、`series?: string`、`unit?: UnitRef`、`autoplay?: boolean` | `unitPos`、`unitEnd` | 进度语义：`locator` = 轨内秒数、`percent` = 按轨加权全书进度；跨轨内置续接、跨册走 `seriesNext` |
| `UnitsReader` | `bookId: string`、`title: string`、`series?: string`、`units: UnitItem[]` | —（内部 `router` 跳详情） | 序号单元合集（第 73 期）：话目录 + 上/下一话 + 「N / M」；按当前话的 `kind` 挂上面三者之一（`:key` = 话号 ⇒ 换话重建） |

**共性**：四者都通过 `useSeriesNext().goToNextVolume(...)` 做「读完进系列下一册」（唯一真值源见 §6）；
会话计时都走 `lib/readingSession.ts`。

**书内排版（第 76 期）**：`ReaderView` 把 `api.epubCss(bid)` 取到的**书内 CSS**以
`@scope (.reader-content) { … }` 注入 `document.head`（**绝不放正文容器里** —— 容器的
`textContent.length` 是进度与批注偏移的尺子，CSS 文本会把长度顶长），并给正文挂 `.nf-bookcss`
让应用那套段落 / 标题 / 引用规则让位（图片「不许溢出」的安全网保留）。
开关 `readerPrefs.useBookLayout`（默认开；**固定版式强制开**）；
浏览器不支持 `@scope` 时不注入也不让位（否则会两头空 —— 见 `ReaderView` 里 `scopeSupported()` 的说明）。

**单话模式（`unit?: UnitRef`，第 73 期）**：三个复用阅读器拿到它就换数据源（`/api/books/{bid}/units/{index}…`）、
**进度不读不写**，只 `emit('unitPos', UnitPos)`（`{index, within, locator}`）与 `emit('unitEnd')`；
**进度由上层独占**——`UnitsReader` 是整本书唯一写 `progress` 的地方（换来换去只有一把尺子），
它按上报里的 `index` **丢弃过期上报**（换话时旧组件卸载还会再报一次）。不给 `unit` 则行为与以前逐字相同。

## 4. 书籍域（`components/book/`）

| 组件 | 用途 / 关键 props |
|---|---|
| `BookActionsMenu` | 书卡 ⋮ 菜单（阅读/收听 · 快速预览 · 下载 · 详情 · 删除 + 子菜单）；状态由 `lib/bookMenu.ts` 单例统一管理 |
| `BookPreviewDialog` | 快速预览浮层（内容取自书卡，详情补章节数） |
| `BookMoveDialog` | 跨库移动（选目标库 → 预检 → 确认） |
| `MetadataEditor` | 单书元数据编辑（覆盖 / 恢复在线 / 清空的分层语义） |
| `ReadingRecord` | 「我的记录」标签（状态 + 起止 + 评分 + 书评 + 轮次） |
| `SeriesMetaPanel` | 系列级元数据面板（简介/出版社/首发年/题材）；⚠️「恢复在线」**只提交那一个字段**（空串=清除该字段覆盖） |
| `SeriesRenumberDialog` | 重排系列序号（先预览再应用，不动文件） |
| `detail/DetailHero` · `OverviewTab` · `ChaptersTab` · `FilesTab` · `AnnotationsTab` · `ReadingLogTab` · `ProgressOverTimeChart` · `SimilarBooks` | 详情页各标签与子件 |

## 5. 仪表盘与图表

- `dashboard/widgets/registry.ts`：**13 个部件全部登记**（`WIDGETS`，宽度档在 `data/dashboard.ts` 的 `WIDGET_META`）；启停与顺序由 `stores/dashboard.ts`（浏览器本地）决定。
  部件清单契约由 `tests/test_dashboard_widget_contract.py` 钉住（前 12 个 id 对齐上游 + 第 13 件 `reading-time` 为自开）。
- 图表：`components/charts/ChartFrame`（ECharts 挂载壳）、`ChartCard`（标题栏 + 内容/空态/配置）、`ChartGrid`、`ChartConfigPanel`、`ChartEmptyState`。
  - **唯一注册入口是 `lib/charts.ts`**（按需 `use()` + SVGRenderer + `chartTheme()`/`chartPalette()`；ECharts 不认 oklch，故有 `oklchToHex()`）。
    组件里**不许**各自 `use()` 或自建主题。
  - 图表目录 `lib/statistics-charts.ts`：30 张的 id / 标题 / 图标 / 栅格 / 分区 + 默认顺序（书库 18 + 阅读 12）。

## 6. `lib/` 单一判据（改行为先改这里）

| 模块 | 导出（要点） | 谁是唯一真值源 |
|---|---|---|
| `api.ts` | `api.*`（全站唯一 HTTP 客户端）、`apiErrorMessage`、全部响应类型 | 前端 HTTP 契约 |
| `seriesNext.ts` | `SERIES_NEXT_MSG`、`resolveNextVolume()`、`useSeriesNext()`、`resetSeriesNextState()` | 「读完进下一册」 |
| `paths.ts` | `isAbsolutePath()`、`normalizePath()`、`pathsOverlap()` | 路径判据（含 Windows 盘符/UNC） |
| `readingThresholds.ts` | `statusFromPercent()`、`thresholdsFor()`、`ensureThresholds()`、`statusLabelOf()` | 阅读状态阈值（后端 `lib_settings.reading_thresholds`） |
| `prefsPayload.ts` | 7 个载荷块 + `normalize()` + 深比较 | 偏好同步载荷（↔ `server.PREFS_BLOCKS`） |
| `prefsBridge.ts` | `notifyPrefsChanged()`、`suppressing` | 偏好变更广播（解循环依赖） |
| `charts.ts` | `chartTheme()`、`chartPalette()`、`useChartTheme()` | 图表注册与主题 |
| `bookInfo.ts` | `seriesIndexLabel()`、`sortBySeriesIndex()`、`formatLabel()`、`tagsLabel()` | 书卡信息展示 |
| `bookOpen.ts` | `openTargetOf()`、`isAudioBook()` | 「能否在线打开 / 去哪儿读」 |
| `readingProgress.ts` | `progressForFile()` | 「恢复位置取哪行进度」（文件级优先） |
| `unitsProgress.ts` | `toPercent(index, within, total)`、`fromPercent(percent, total)` | 「话 / 轨 ↔ 百分比」换算（合集与有声书**共用一份**；含 `BOUNDARY_EPS` 浮点边界容差） |
| `readingSession.ts` | `createSessionReporter()`、`attachReaderClock()` | 阅读会话边界与累计（30s 心跳合一） |
| `metadataFields.ts` | `FIELD_LABELS`、`CATALOG_FIELDS`、`IDENTITY_FIELDS`、`DB_ONLY_FIELDS` | 元数据字段名与顺序 |
| `shelfBuckets.ts` | 首字母分桶（A–Z / `#`，不做拼音） | 书架分桶 |
| `smartScope.ts` | `evaluateScope()`、`ruleText()` | 智能书架求值 |
| `textAnchor.ts` | 章内字符偏移锚（取/还原同坐标） | 批注位置锚 |
| `annotations.ts` | `chapterLabel()`、`canJumpTo()`、`originLabel()` | 批注展示口径 |
| `format.ts` / `readingPace.ts` / `deviceInfo.ts` / `fonts.ts` / `coverTint.ts` / `icons.ts` / `notifyPrefs.ts` / `bookMenu.ts` | 见 `docs/architecture.md` §12 | — |

## 7. Stores（Pinia）

| store | 关键公共 API | 说明 |
|---|---|---|
| `ui` | `toast(msg)`、`toastMessage`、`sidebarCollapsed`、`toggleSidebar()` | 外壳 UI |
| `auth` | `token`、`user`、`displayName`、`ready`、登录/注销 | 鉴权（token 存 `nf_token`） |
| `library` | `books`、`loaded`、`loadBooks(force?)`、`loadLibraries(force?)`、`loadLibraryFacets(force?)`、`getBookDetail(id)`、`patchProgress(id, pct, at?)`、`currentLibraryId` | **各 loader 有单飞闸**（并发共享同一次请求）；`patchProgress` 就地回写不重拉整库 |
| `stats` | `data`、`error`、`load(force?)` | `/api/stats` 缓存，供 13 个部件共用；**按书库单飞** |
| `collections` | `items`、`load(force?)`、`create/remove/rename` | `force` 走「等前一次落地再拉」，避免吞掉刚建的收藏夹 |
| `tasks` | 任务列表 + 仅未结束时轮询 | `/api/tasks` |
| `prefSync` | 偏好同步模式快照、设备配置、显式保存、离线降级 | 与 `lib/prefsBridge` 配合 |
| `theme` | 主题 / 点缀色 / 圆角（写 `<html>` class + localStorage） | 见 `docs/DESIGN.md` |
| `nav` | 分组折叠、「库」组筛选、任务计数 | 侧栏 |
| `displayPrefs` / `shelfPrefs` / `coverPrefs` / `dashboard` / `statsChartPrefs` | 各类偏好（`displayPrefs` 与 `shelfPrefs.collapseSeries` 进服务端同步） | — |
| `libraryWizard` | `show()`、`created()` | 「新增书库」**全局单实例就地弹窗**（⚠️ 禁在别处再挂第二份） |
| `fonts` / `activity` | 字体列表与 `@font-face` 注入 / 阅读活动缓存 | — |

## 8. Composables（`composables/`）

| 文件 | 用途 |
|---|---|
| `useSettingsConfig.ts` | 设置页服务端配置**共享单例**（切换设置页不丢草稿；`saveSection` 才写回） |
| `useSettingsDirty.ts` | 「未保存变更」上报通道（页面把 `isDirty`/`discard` 交给 `SettingsLayout`） |
| `useSettingsSearch.ts` | 设置项搜索浮层开合单例（侧栏 / ⌘K / 布局共用） |
| `useDndSort.ts` | 原生 HTML5 拖拽排序（拖动只改视觉态，`dragend`/`drop` 才提交；附键盘上/下移） |
| `useLibraryNames.ts` | 书库 id → 名称映射（空 id 回退「未知书库」） |

## 9. 注册表（`data/`，**契约所在**）

| 文件 | 结构 | 契约 |
|---|---|---|
| `nav.ts` | `NAV_GROUPS: NavGroup[]`（主导航 + 浏览 / 库 / 智能书架 / 收藏夹 / 帮助） | 动态计数项**不许写死数字**（`countSource`）；菜单 id 全局唯一；组底部 `more` 行必须 `label`+`to`+`countSource` 三件一起声明。契约 `tests/test_nav_contract.py` |
| `settingsNav.ts` | `SETTINGS_GROUPS`（6 组）→ `SETTINGS_PAGES`（**36 页**）；`PAGE_FEATURE`、`SETTINGS_HOME`、`findSettingsPage()` | 设置页由注册表生成路由与侧栏项 ⇒ **删条目即删路由**；未注册组件者落 `SettingsPlaceholder`。契约 `tests/test_settings_nav_contract.py` |
| `whatsNew.ts` | 更新日志（静态） | `/whats-new` 数据源 |
| `collections.ts` | 库 / 智能书架 / 收藏夹的**空骨架**（运行期被后端数据覆盖） | — |
| `dashboard.ts`（`stores/`） | 部件与书架行的启用/顺序（浏览器本地） | 与 `widgets/registry.ts` 的 `WIDGETS` 对应 |

## 10. 新增/改动组件的规矩

1. **优先复用 `ui/` 原语**；不要另起一套按钮 / 卡片 / 空态。
2. 颜色/圆角/阴影一律用 token 与 Tailwind 语义类（见 `docs/DESIGN.md`），**不写死值**。
3. 新增设置页 → 同批改 `data/settingsNav.ts` + 路由组件映射（并跑设置页契约测试）。
4. 新增偏好 → 同批改 `lib/prefsPayload.ts` 与后端 `server.PREFS_BLOCKS`（含相关函数），跑 `tests/test_prefs_shelf_block.py`。
5. 新页面触达后端新接口 → 在 `lib/api.ts` 加方法（唯一 HTTP 客户端），不要组件里裸 `fetch`。
6. 组件级测试放同目录 `*.spec.ts`（显式 `import { describe, it, expect, vi } from 'vitest'`；**不开 globals**）；
   挂载前需要 `Element.prototype.scrollIntoView = vi.fn()`（happy-dom 未实现）。
7. 改完跑四连（`type-check` + `test:unit` + `build` + `deploy`）——`vitest` 不校验模块导出完整性。
