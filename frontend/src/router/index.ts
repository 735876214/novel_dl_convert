import { createRouter, createWebHashHistory } from 'vue-router'

import BookDetailView from '@/views/BookDetailView.vue'
import DashboardView from '@/views/DashboardView.vue'
import ExploreView from '@/views/ExploreView.vue'
import PlaceholderView from '@/views/PlaceholderView.vue'
import SettingsView from '@/views/SettingsView.vue'
import ShelfView from '@/views/ShelfView.vue'
import TaskCenterView from '@/views/TaskCenterView.vue'
import BulkRenameView from '@/views/tools/BulkRenameView.vue'
import DuplicateBooksView from '@/views/tools/DuplicateBooksView.vue'
import EntityManagerView from '@/views/tools/EntityManagerView.vue'
import LocalConvertView from '@/views/tools/LocalConvertView.vue'
import LogsView from '@/views/tools/LogsView.vue'
import MissingResourcesView from '@/views/tools/MissingResourcesView.vue'
import OutputView from '@/views/tools/OutputView.vue'
import SourcesView from '@/views/tools/SourcesView.vue'
import ToolsLayout from '@/views/tools/ToolsLayout.vue'

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
    { path: '/book/:id', name: 'book', component: BookDetailView },
    { path: '/settings', name: 'settings', component: SettingsView },

    // 工具：单页 + 顶部下划线标签栏（ToolsLayout），8 个子路由。
    // 子路由 name 沿用 BookOrbit 的命名（tools-entity-manager 等），便于与上游对照。
    {
      path: '/tools',
      component: ToolsLayout,
      children: [
        { path: '', redirect: { name: 'tools-entity-manager' } },
        { path: 'entities', name: 'tools-entity-manager', component: EntityManagerView },
        { path: 'rename', name: 'tools-bulk-rename', component: BulkRenameView },
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
