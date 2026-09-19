import type { Component } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'

import AchievementsView from '@/views/AchievementsView.vue'
import BookDetailView from '@/views/BookDetailView.vue'
import ReaderView from '@/views/ReaderView.vue'
import AudioPlayerView from '@/views/AudioPlayerView.vue'
import AnnotationsView from '@/views/AnnotationsView.vue'
import AuthorDetailView from '@/views/AuthorDetailView.vue'
import AuthorsView from '@/views/AuthorsView.vue'
import CollectionDetailView from '@/views/CollectionDetailView.vue'
import CollectionsView from '@/views/CollectionsView.vue'
import NotificationsView from '@/views/NotificationsView.vue'
import SeriesDetailView from '@/views/SeriesDetailView.vue'
import SeriesView from '@/views/SeriesView.vue'
import StatsView from '@/views/StatsView.vue'
import ReadingLogView from '@/views/ReadingLogView.vue'
import DashboardView from '@/views/DashboardView.vue'
import DocumentationView from '@/views/DocumentationView.vue'
import ExploreView from '@/views/ExploreView.vue'
import PlaceholderView from '@/views/PlaceholderView.vue'
import LibrariesView from '@/views/tools/LibrariesView.vue'
import SettingsLayout from '@/views/settings/SettingsLayout.vue'
import SettingsPlaceholder from '@/views/settings/SettingsPlaceholder.vue'
import AboutPage from '@/views/settings/pages/AboutPage.vue'
import AdvancedPage from '@/views/settings/pages/AdvancedPage.vue'
import AuditLogPage from '@/views/settings/pages/AuditLogPage.vue'
import BookDockPage from '@/views/settings/pages/BookDockPage.vue'
import ConversionPage from '@/views/settings/pages/ConversionPage.vue'
import CoverPage from '@/views/settings/pages/CoverPage.vue'
import FileNamingPage from '@/views/settings/pages/FileNamingPage.vue'
import MaintenancePage from '@/views/settings/pages/MaintenancePage.vue'
import NetworkPage from '@/views/settings/pages/NetworkPage.vue'
import NotificationsPage from '@/views/settings/pages/NotificationsPage.vue'
import ProfilePage from '@/views/settings/pages/ProfilePage.vue'
import ReaderEbookPage from '@/views/settings/pages/ReaderEbookPage.vue'
import ThemePage from '@/views/settings/pages/ThemePage.vue'
import WatcherPage from '@/views/settings/pages/WatcherPage.vue'
import ShelfView from '@/views/ShelfView.vue'
import SmartScopesView from '@/views/SmartScopesView.vue'
import ReaderFontsPage from '@/views/settings/pages/ReaderFontsPage.vue'
import PdfPage from '@/views/settings/pages/PdfPage.vue'
import ComicsPage from '@/views/settings/pages/ComicsPage.vue'
import ReaderAudioPage from '@/views/settings/pages/ReaderAudioPage.vue'
import OpdsPage from '@/views/settings/pages/OpdsPage.vue'
import KomgaPage from '@/views/settings/pages/KomgaPage.vue'
import KoreaderPage from '@/views/settings/pages/KoreaderPage.vue'
import IntegrationPage from '@/views/settings/pages/IntegrationPage.vue'
import MetadataPage from '@/views/settings/pages/MetadataPage.vue'
import PreferenceSyncPage from '@/views/settings/pages/PreferenceSyncPage.vue'
import TaskCenterView from '@/views/TaskCenterView.vue'
import WhatsNewView from '@/views/WhatsNewView.vue'
import DuplicateBooksView from '@/views/tools/DuplicateBooksView.vue'
import EntityManagerView from '@/views/tools/EntityManagerView.vue'
import LocalConvertView from '@/views/tools/LocalConvertView.vue'
import LogsView from '@/views/tools/LogsView.vue'
import MissingResourcesView from '@/views/tools/MissingResourcesView.vue'
import OutputView from '@/views/tools/OutputView.vue'
import SourcesView from '@/views/tools/SourcesView.vue'
import ToolsLayout from '@/views/tools/ToolsLayout.vue'
import { SETTINGS_HOME, SETTINGS_PAGES } from '@/data/settingsNav'

/**
 * 设置页叶子路由 → 真实页面组件。
 *
 * 未在此表中的页一律落到 `SettingsPlaceholder`：只读展示上游该页的分组与设置项，
 * 并统一标注「未支持」（对齐 `docs/bookorbit-settings-inventory.md` 的迁移约定 3）。
 * 用映射表而不是在注册表里直接引用组件，是为了让 `data/settingsNav.ts` 保持纯数据、可被非 UI 代码复用。
 */
export const SETTINGS_PAGE_COMPONENTS: Record<string, Component> = {
  'account/profile': ProfilePage,
  'account/notifications': NotificationsPage,
  'appearance/theme': ThemePage,
  'appearance/book-covers': CoverPage,
  'reader/ebook': ReaderEbookPage,
  'reader/pdf': PdfPage,
  'reader/comics': ComicsPage,
  'reader/audio': ReaderAudioPage,
  'reader/general': PreferenceSyncPage,
  // 同一组件两种形态：本项目单用户部署下「阅读字体」与「服务端字体」是同一份库
  'reader/fonts': ReaderFontsPage,
  'admin/server-fonts': ReaderFontsPage,
  'library/file-naming': FileNamingPage,
  'library/maintenance': MaintenancePage,
  'admin/audit-log': AuditLogPage,
  'admin/book-dock': BookDockPage,
  'ext/conversion': ConversionPage,
  'ext/watcher': WatcherPage,
  'ext/network': NetworkPage,
  'ext/advanced': AdvancedPage,
  'ext/about': AboutPage,
  opds: OpdsPage,
  komga: KomgaPage,
  koreader: KoreaderPage,
  // 三家外部服务共用一个组件，靠 props 区分（见下方 SETTINGS_PAGE_PROPS）
  hardcover: IntegrationPage,
  readwise: IntegrationPage,
  storygraph: IntegrationPage,
  // 元数据抓取的 7 页共用一个组件，props.section 决定展示哪些区块
  'metadata/providers': MetadataPage,
  'metadata/field-rules': MetadataPage,
  'metadata/custom-fields': MetadataPage,
  'metadata/score': MetadataPage,
  'metadata/auto-fetch': MetadataPage,
  'metadata/authors': MetadataPage,
  'metadata/genre-blocklist': MetadataPage,
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

/** 设置页的 48 个子路由，由注册表生成，避免手写路由与侧栏导航两处走样 */
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
        component: SettingsPlaceholder,
        props: () => ({ page }),
      }
})

/**
 * 使用 hash history：FastAPI 没有 SPA 兜底路由，
 * history 模式下刷新 /dashboard 之类路径会 404。
 * hash 模式零后端改动，对内网工具完全够用。
 *
 * 尚未迁移的视图统一落到 PlaceholderView（含通配兜底），避免为占位创建一次性桩文件。
 */
const router = createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: DashboardView },
    { path: '/explore', name: 'explore', component: ExploreView },
    { path: '/tasks', name: 'tasks', component: TaskCenterView },
    { path: '/shelf', name: 'shelf', component: ShelfView },
    { path: '/smart-scopes', name: 'smart-scopes', component: SmartScopesView },
    { path: '/book/:id', name: 'book', component: BookDetailView },
    { path: '/read/:id', name: 'read', component: ReaderView },
    { path: '/listen/:id', name: 'listen', component: AudioPlayerView },
    { path: '/series', name: 'series', component: SeriesView },
    { path: '/series/:name', name: 'series-detail', component: SeriesDetailView },
    { path: '/authors', name: 'authors', component: AuthorsView },
    { path: '/authors/:name', name: 'author-detail', component: AuthorDetailView },
    { path: '/annotations', name: 'annotations', component: AnnotationsView },
    { path: '/collections', name: 'collections', component: CollectionsView },
    { path: '/collections/:id', name: 'collection-detail', component: CollectionDetailView },
    { path: '/stats', name: 'stats', component: StatsView },
    { path: '/log', name: 'log', component: ReadingLogView },
    { path: '/notify', name: 'notify', component: NotificationsView },
    { path: '/achievements', name: 'achievements', component: AchievementsView },
    { path: '/whats-new', name: 'whats-new', component: WhatsNewView },
    { path: '/docs', name: 'docs', component: DocumentationView },

    // 设置：嵌套路由，每个叶子页有独立 URL（可直达、可刷新、可分享）
    {
      path: '/settings',
      component: SettingsLayout,
      children: [
        { path: '', redirect: SETTINGS_HOME },
        // 上游实测存在的别名：/settings/system 会被上游重定向到「文件命名」。
        // 本项目同样保留，避免从上游文档/书签跳进来时 404（见 inventory §7.1 #4）。
        { path: 'system', redirect: { name: 'settings-library-file-naming' } },
        ...settingsChildren,
      ],
    },

    // 工具：单页 + 顶部下划线标签栏（ToolsLayout），8 个子路由。
    // 子路由 name 沿用 BookOrbit 的命名（tools-entity-manager 等），便于与上游对照。
    {
      path: '/tools',
      component: ToolsLayout,
      children: [
        { path: '', redirect: { name: 'tools-entity-manager' } },
        { path: 'libraries', name: 'tools-libraries', component: LibrariesView },
        { path: 'entities', name: 'tools-entity-manager', component: EntityManagerView },
        { path: 'duplicates', name: 'tools-duplicate-books', component: DuplicateBooksView },
        { path: 'missing', name: 'tools-missing-resources', component: MissingResourcesView },
        { path: 'sources', name: 'tools-sources', component: SourcesView },
              { path: 'output', name: 'tools-output', component: OutputView },
        { path: 'local', name: 'tools-local', component: LocalConvertView },
        { path: 'logs', name: 'tools-logs', component: LogsView },
      ],
    },

    // 尚未实现的视图：/placeholder/_authors、/placeholder/notify …
    { path: '/placeholder/:id', name: 'placeholder', component: PlaceholderView },
    { path: '/:pathMatch(.*)*', name: 'fallback', component: PlaceholderView },
  ],
})

export default router
