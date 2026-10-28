import type { Component } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'

import { SETTINGS_HOME, SETTINGS_PAGES } from '@/data/settingsNav'

/**
 * 设置页叶子路由 → 真实页面组件。
 *
 * 未在此表中的页一律落到 `SettingsPlaceholder`：只读展示上游该页的分组与设置项，
 * 并统一标注「未支持」（对齐 `docs/bookorbit/bookorbit-settings-inventory.md` 的迁移约定 3）。
 * 用映射表而不是在注册表里直接引用组件，是为了让 `data/settingsNav.ts` 保持纯数据、可被非 UI 代码复用。
 *
 * ⚠️ 第 152 期起默认写成 **懒加载器**（`() => import('…')`）：30 个设置页此前全部打进首屏
 * 主包（它们合计是整个 `views/settings/pages` 目录），而用户一次只会打开一页。
 * 同步写法仍然允许（`libraries` 那条沿用），类型是两者的联合。
 */
type AsyncPage = Component | (() => Promise<{ default: Component }>)

export const SETTINGS_PAGE_COMPONENTS: Record<string, AsyncPage> = {
  'account/profile': () => import('@/views/settings/pages/ProfilePage.vue'),
  'account/notifications': () => import('@/views/settings/pages/NotificationsPage.vue'),
  'appearance/theme': () => import('@/views/settings/pages/ThemePage.vue'),
  'appearance/book-covers': () => import('@/views/settings/pages/CoverPage.vue'),
  'appearance/behavior': () => import('@/views/settings/pages/BehaviorPage.vue'),
  'appearance/layout': () => import('@/views/settings/pages/LayoutPage.vue'),
  'reader/ebook': () => import('@/views/settings/pages/ReaderEbookPage.vue'),
  'reader/pdf': () => import('@/views/settings/pages/PdfPage.vue'),
  'reader/comics': () => import('@/views/settings/pages/ComicsPage.vue'),
  'reader/audio': () => import('@/views/settings/pages/ReaderAudioPage.vue'),
  'reader/general': () => import('@/views/settings/pages/PreferenceSyncPage.vue'),
  // 同一组件两种形态：本项目单用户部署下「阅读字体」与「服务端字体」是同一份库
  'reader/fonts': () => import('@/views/settings/pages/ReaderFontsPage.vue'),
  'admin/server-fonts': () => import('@/views/settings/pages/ReaderFontsPage.vue'),
  'library/file-naming': () => import('@/views/settings/pages/FileNamingPage.vue'),
  'library/maintenance': () => import('@/views/settings/pages/MaintenancePage.vue'),
  // 第 49 期：书库管理并入设置页（原「工具 → 书库管理」入口已移除）
  libraries: () => import('@/views/tools/LibrariesView.vue'),
  'admin/audit-log': () => import('@/views/settings/pages/AuditLogPage.vue'),
  'admin/book-dock': () => import('@/views/settings/pages/BookDockPage.vue'),
  'ext/conversion': () => import('@/views/settings/pages/ConversionPage.vue'),
  'ext/update': () => import('@/views/settings/pages/UpdatePage.vue'),
  'ext/watcher': () => import('@/views/settings/pages/WatcherPage.vue'),
  'ext/network': () => import('@/views/settings/pages/NetworkPage.vue'),
  'ext/advanced': () => import('@/views/settings/pages/AdvancedPage.vue'),
  'ext/about': () => import('@/views/settings/pages/AboutPage.vue'),
  opds: () => import('@/views/settings/pages/OpdsPage.vue'),
  komga: () => import('@/views/settings/pages/KomgaPage.vue'),
  koreader: () => import('@/views/settings/pages/KoreaderPage.vue'),
  // 三家外部服务共用一个组件，靠 props 区分（见下方 SETTINGS_PAGE_PROPS）
  hardcover: () => import('@/views/settings/pages/IntegrationPage.vue'),
  readwise: () => import('@/views/settings/pages/IntegrationPage.vue'),
  storygraph: () => import('@/views/settings/pages/IntegrationPage.vue'),
  // 元数据抓取的 7 页共用一个组件，props.section 决定展示哪些区块
  'metadata/providers': () => import('@/views/settings/pages/MetadataPage.vue'),
  'metadata/field-rules': () => import('@/views/settings/pages/MetadataPage.vue'),
  'metadata/custom-fields': () => import('@/views/settings/pages/MetadataPage.vue'),
  'metadata/score': () => import('@/views/settings/pages/MetadataPage.vue'),
  'metadata/auto-fetch': () => import('@/views/settings/pages/MetadataPage.vue'),
  'metadata/authors': () => import('@/views/settings/pages/MetadataPage.vue'),
  'metadata/genre-blocklist': () => import('@/views/settings/pages/MetadataPage.vue'),
}

/** 需要传 props 的设置页（当前只有字体页的两种形态） */
const SETTINGS_PAGE_PROPS: Record<string, () => Record<string, unknown>> = {
  'admin/server-fonts': () => ({ variant: 'server' }),
  // 三页共用 IntegrationPage，用 service 区分（字段定义由后端给，前端不重复维护）
  hardcover: () => ({ service: 'hardcover' }),
  readwise: () => ({ service: 'readwise' }),
  storygraph: () => ({ service: 'storygraph' }),
  // 元数据 7 页同样共用一个组件，section 决定显示哪些区块
  'metadata/providers': () => ({ section: 'providers' }),
  'metadata/field-rules': () => ({ section: 'field-rules' }),
  'metadata/custom-fields': () => ({ section: 'custom-fields' }),
  'metadata/score': () => ({ section: 'score' }),
  'metadata/auto-fetch': () => ({ section: 'auto-fetch' }),
  'metadata/authors': () => ({ section: 'authors' }),
  'metadata/genre-blocklist': () => ({ section: 'genre-blocklist' }),
}

/** 设置页的子路由，由注册表生成，避免手写路由与侧栏导航两处走样 */
const settingsChildren = SETTINGS_PAGES.map((page) => {
  const component = SETTINGS_PAGE_COMPONENTS[page.path]
  if (page.status === 'ready' && !component) {
    // 注册表声明为 ready 却没有组件：属于配置错误，让它在开发期就暴露
    console.error(`[router] 设置页 "${page.path}" 标记为 ready 但未注册组件`)
  }
  const propsFn = SETTINGS_PAGE_PROPS[page.path]
  return component
    ? { path: page.path, name: page.name, component, props: propsFn }
    : {
        path: page.path,
        name: page.name,
        component: () => import('@/views/settings/SettingsPlaceholder.vue'),
        props: () => ({ page }),
      }
})

/**
 * 使用 history 模式（第 153 期起）：URL 与上游 BookOrbit 一致（`/shelf`、`/settings/...`），
 * 深链可直达、可分享、不会被 `#` 截断。
 *
 * 依赖两端同批改动：① FastAPI 的 SPA 兜底（`server.py` 的 `/{path:path}`，
 * 非 `/api` `/opds` `/koreader` `/download` `/static` `/health` 且无扩展名时回 `index.html`）；
 * ② `index.html` 里把旧 hash 链接（`/#/shelf`）在启动前重写成 `/shelf`，老书签不失效。
 * 开发期由 Vite 自带的 history fallback 承担，无需额外配置。
 *
 * 尚未迁移的视图统一落到 PlaceholderView（含通配兜底），避免为占位创建一次性桩文件。
 */
const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('@/views/DashboardView.vue') },
    { path: '/explore', name: 'explore', component: () => import('@/views/ExploreView.vue') },
    // 「收书目录」（Book Dock）的**侧栏一级入口**（第 65 期）。
    // 与设置里那一条 `/settings/admin/book-dock` 指向**同一个组件** —— 上游也是
    // 两处都有。之所以不能只留设置里那条：`/settings*` 前缀会让整个左栏换成
    // 设置侧栏（App.vue 判断 `path.startsWith('/settings')`），而这里是从首页
    // 侧栏点进来的，左栏不该变脸。
    { path: '/book-dock', name: 'book-dock', component: () => import('@/views/settings/pages/BookDockPage.vue') },
    // 播客订阅（第 173 期）：独立子系统，顶层路由（不是书库）
    { path: '/podcasts', name: 'podcasts', component: () => import('@/views/PodcastsView.vue') },
    { path: '/tasks', name: 'tasks', component: () => import('@/views/TaskCenterView.vue') },
    { path: '/shelf', name: 'shelf', component: () => import('@/views/ShelfView.vue') },
    { path: '/smart-scopes', name: 'smart-scopes', component: () => import('@/views/SmartScopesView.vue') },
    { path: '/book/:id', name: 'book', component: () => import('@/views/BookDetailView.vue') },
    { path: '/read/:id', name: 'read', component: () => import('@/views/ReaderView.vue') },
    // 在线阅读（第 93 期）：**同一个阅读器组件**，靠 `route.name` 分模式。
    // 不复用 `/read/:id?online=1` 是刻意的 —— 查询参数不影响组件复用，
    // 「本地读着读着切成在线」不会有任何反应；两条路由各自是一份现场。
    // 主题 / 字号 / 版式 / 翻页 / 滚动 / 目录抽屉全部共用同一份实现（只换数据来源）。
    { path: '/online/:id', name: 'online', component: () => import('@/views/ReaderView.vue') },
    { path: '/listen/:id', name: 'listen', component: () => import('@/views/AudioPlayerView.vue') },
    { path: '/series', name: 'series', component: () => import('@/views/SeriesView.vue') },
    { path: '/series/:name', name: 'series-detail', component: () => import('@/views/SeriesDetailView.vue') },
    { path: '/authors', name: 'authors', component: () => import('@/views/AuthorsView.vue') },
    { path: '/authors/:name', name: 'author-detail', component: () => import('@/views/AuthorDetailView.vue') },
    // 实体总览（第 34 期）：按元数据维度浏览**本地**书目。
    // ⚠️ 与 /explore「探索发现」是两件事 —— 那个是外部书源检索（POST /api/search），
    //    路径与名字都要分开，别合并。
    { path: '/browse', name: 'browse', component: () => import('@/views/BrowseView.vue') },
    { path: '/annotations', name: 'annotations', component: () => import('@/views/AnnotationsView.vue') },
    { path: '/collections', name: 'collections', component: () => import('@/views/CollectionsView.vue') },
    { path: '/collections/:id', name: 'collection-detail', component: () => import('@/views/CollectionDetailView.vue') },
    // 统计页懒加载：它是全站唯一引 ECharts 的页面（第 32 期），动态 import 让它
    // 单独成 chunk，图表库不进主包。同属「重依赖不进主包」的思路 ——
    // 另一处是 PdfReader.vue:222 在组件内动态 import pdfjs（那个是组件级，不在路由层）。
    { path: '/stats', name: 'stats', component: () => import('@/views/StatsView.vue') },
    { path: '/log', name: 'log', component: () => import('@/views/ReadingLogView.vue') },
    { path: '/notify', name: 'notify', component: () => import('@/views/NotificationsView.vue') },
    { path: '/achievements', name: 'achievements', component: () => import('@/views/AchievementsView.vue') },
    // 阅读热力图页**懒加载**（第 152 期）：它是全站唯一在「非图表页」里 import
    // `@/lib/charts` 的地方，而那个模块会把整个 ECharts（约 300 KB gzip）拖进**首屏**
    // 包 —— 首屏因此白白多下载一个 887 KB 的 chunk。改成 `() => import()` 后
    // ECharts 只在真正的图表页（本页 / 统计页）才加载。
    { path: '/reading-activity', name: 'reading-activity', component: () => import('@/views/ReadingActivityView.vue') },
    { path: '/whats-new', name: 'whats-new', component: () => import('@/views/WhatsNewView.vue') },
    { path: '/docs', name: 'docs', component: () => import('@/views/DocumentationView.vue') },

    // 设置：嵌套路由，每个叶子页有独立 URL（可直达、可刷新、可分享）
    {
      path: '/settings',
      component: () => import('@/views/settings/SettingsLayout.vue'),
      children: [
        { path: '', redirect: SETTINGS_HOME },
        // 上游实测存在的别名：/settings/system 会被上游重定向到「文件命名」。
        // 本项目同样保留，避免从上游文档/书签跳进来时 404（见 inventory §7.1 #4）。
        { path: 'system', redirect: { name: 'settings-library-file-naming' } },
        ...settingsChildren,
      ],
    },

    // 工具：单页 + 顶部下划线标签栏（ToolsLayout），7 个子路由。
    // 子路由 name 沿用 BookOrbit 的命名（tools-entity-manager 等），便于与上游对照。
    // 第 49 期：书库管理迁到设置页（settings-libraries），不再占工具页标签。
    {
      path: '/tools',
      component: () => import('@/views/tools/ToolsLayout.vue'),
      children: [
        { path: '', redirect: { name: 'tools-entity-manager' } },
        { path: 'entities', name: 'tools-entity-manager', component: () => import('@/views/tools/EntityManagerView.vue') },
        { path: 'duplicates', name: 'tools-duplicate-books', component: () => import('@/views/tools/DuplicateBooksView.vue') },
        { path: 'missing', name: 'tools-missing-resources', component: () => import('@/views/tools/MissingResourcesView.vue') },
        { path: 'sources', name: 'tools-sources', component: () => import('@/views/tools/SourcesView.vue') },
        // 第 86 期能力的接线页（导入 / 台账 / 登录 / 验证）
        { path: 'source-tools', name: 'tools-source-tools', component: () => import('@/views/tools/SourceToolsView.vue') },
              { path: 'output', name: 'tools-output', component: () => import('@/views/tools/OutputView.vue') },
        { path: 'local', name: 'tools-local', component: () => import('@/views/tools/LocalConvertView.vue') },
        // 第 165 期：按正则从文件名 / 路径批量提取元数据
        { path: 'path-import', name: 'tools-path-import', component: () => import('@/views/tools/PathImportView.vue') },
        { path: 'logs', name: 'tools-logs', component: () => import('@/views/tools/LogsView.vue') },
      ],
    },

    // 未知路由兜底：正式视图现已全部实现，侧栏每个 id 都有真实路由（见 AppSidebar 的
    // PATH_BY_ID），这两条只是「链接写错了」时的落点，不再是「尚未实现的视图」。
    { path: '/placeholder/:id', name: 'placeholder', component: () => import('@/views/PlaceholderView.vue') },
    { path: '/:pathMatch(.*)*', name: 'fallback', component: () => import('@/views/PlaceholderView.vue') },
  ],
})

/**
 * 懒加载 chunk 失联 ⇒ **整页重载一次**（第 152 期）。
 *
 * 起因：路由全部改成 `() => import()` 之后，每个页面是一个带 hash 的 chunk；而
 * `frontend/scripts/deploy.mjs` 是「先删目标目录、再整体拷贝」—— 部署那一刻开着的
 * 旧页面，点进一个**没访问过**的路由时它的 chunk 已经不在服务器上了 ⇒ 动态 import 404、
 * 页面白屏且没有任何提示。重载会拿到新的 `index.html` 与新的 chunk，用户几乎无感。
 *
 * ⚠️ 必须防死循环：chunk 是真没了（服务端回滚 / 静态目录被清空）时无条件重载会变成
 * 刷新风暴。同一标签页 30 秒内只自动重载一次，之后把错误交给上层（控制台可见）。
 */
const CHUNK_ERR_RE = /Failed to fetch dynamically imported module|Importing a module script failed|Loading chunk .* failed|dynamically imported module/i
let chunkReloadedAt = 0
router.onError((err: unknown) => {
  const msg = err instanceof Error ? err.message : String(err ?? '')
  if (!CHUNK_ERR_RE.test(msg)) return
  const now = Date.now()
  if (now - chunkReloadedAt < 30_000) return
  chunkReloadedAt = now
  window.location.reload()
})

export default router
