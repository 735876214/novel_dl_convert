/**
 * 侧栏结构。迁移自 v2 app.js 的 NAV_GROUPS（原第 100–121 行）。
 *
 * 约定（沿用 v2 注释）：
 *   · title 为 null 即「无组标题」的主导航
 *   · count 不写时**不渲染计数胶囊**，等真实数据接上再填
 *   · 库 / 智能书架 / 收藏夹 的条目点击进入书库页
 *
 * 每个 id 都在 AppSidebar 的 `PATH_BY_ID` 里有真实路由；表里没有的 id 会退到
 * `/placeholder/:id`（未知路由兜底页，不是「未实现的视图」——见 PlaceholderView.vue）。
 */
import { COLLECTIONS, LIBRARIES, SMART_SHELVES, type NavEntry } from './collections'

export interface NavItem {
  id: string
  label: string
  icon: string
  /** 静态计数；不写则不渲染胶囊 */
  count?: number
  /**
   * 动态计数来源（**不要把数字写死**，写死即假数据）：
   *   · `running` —— 任务中心的「运行中 + 排队中」；
   *   · `browse`  —— 「浏览」组三项，取 `/api/browse-counts`（第 34 期；
   *      数字与目标页同源，服务端 60 秒节流，按 id 到响应里取同名字段）。
   */
  countSource?: 'running' | 'browse'
}

export interface NavGroup {
  title: string | null
  collapsible?: boolean
  actions?: Array<'add' | 'more'>
  search?: { placeholder: string }
  items: NavItem[]
  /**
   * 组底部的「更多」行。三件必须**一起**声明，否则就会出现
   * 「括号里是书库数、点下去是书架」这种读数与去向不一致的含糊：
   *   · `label`       —— 文案；
   *   · `to`          —— 真实去向（路由路径）；
   *   · `countSource` —— 括号里的数字是什么（`libraries` = 书库实体个数）。
   */
  more?: { label: string; to?: string; countSource?: 'libraries' }
  empty?: string
}

export const NAV_GROUPS: NavGroup[] = [
  {
    title: null,
    items: [
      { id: 'dashboard', label: '仪表盘', icon: 'dash' },
      { id: 'search', label: '探索发现', icon: 'search' },
      { id: 'tasks', label: '任务中心', icon: 'task', countSource: 'running' },
      // 「工具」与任务中心**并列**（同属主导航这一层），但**不自成一块** ——
      // 它是工具页的统一入口，8 个工具在页内用标签栏切换（见 views/tools/ToolsLayout.vue）。
      { id: 'tools', label: '工具', icon: 'wrench' },
      { id: 'stats', label: '数据统计', icon: 'chart' },
      // Reading Log：reading_sessions 表的展示层（按天 / 按书 / 最近会话）
      { id: 'log', label: '阅读记录', icon: 'clock' },
      { id: 'reading-activity', label: '阅读活动', icon: 'note' },
      { id: 'notify', label: '通知中心', icon: 'bell' },
      // 成就：上游放在顶栏（`/achievements`）。本项目与「数据统计」同层并列，
      // 数据来自 /api/achievements（单用户口径，见 core/achievements.py）。
      { id: 'achievements', label: '成就', icon: 'star' },
    ],
  },
  {
    title: '浏览',
    collapsible: true,
    items: [
      // 「实体总览」= 按元数据维度浏览本地书目（第 34 期）。
      // ⚠️ 名字避开本组标题「浏览」，也避开 `/explore`「探索发现」（那是外部书源检索）。
      { id: 'browse', label: '实体总览', icon: 'shelf' },
      // 三项的计数都来自 /api/browse-counts，**与各自目标页同源**：
      // 侧栏写「作者 3」而作者页列出 12 位就是在说假话（见 core/browse_counts.py）。
      { id: 'authors', label: '作者', icon: 'users', countSource: 'browse' },
      { id: 'series', label: '系列', icon: 'layers', countSource: 'browse' },
      { id: 'annotations', label: '批注', icon: 'pencil', countSource: 'browse' },
    ],
  },
  {
    title: '库',
    collapsible: true,
    actions: ['add', 'more'],
    search: { placeholder: '筛选书库…' },
    items: LIBRARIES as NavEntry[],
    // ⚠️ 括号里原来是 `items.length`（= 真实书库数 + 1，因为「全部书库」也是一项），
    //    而点下去进的是书架 ⇒ 读的是书库数、看的是全部书。现在口径统一为
    //    「书库实体个数 + 进书库管理页」（与上游同款：`查看全部书库(9)` → /libraries）。
    more: { label: '查看全部书库', to: '/tools/libraries', countSource: 'libraries' },
  },
  {
    title: '智能书架',
    collapsible: true,
    actions: ['add'],
    items: SMART_SHELVES,
    empty: '尚无智能书架',
  },
  {
    title: '收藏夹',
    collapsible: true,
    actions: ['add'],
    items: COLLECTIONS,
    empty: '尚无收藏',
  },
  {
    title: '帮助',
    collapsible: true,
    items: [
      // 全部复用既有路由，不新建页面（说明书 / 更新日志 / 关于 三页已存在）
      { id: 'docs', label: '说明书', icon: 'book' },
      { id: 'whatsnew', label: '更新日志', icon: 'file' },
      { id: 'about', label: '关于', icon: 'user' },
    ],
  },
]

/** 「库 / 智能书架 / 收藏夹」的条目都进书库页 */
export function isShelfGroup(title: string): boolean {
  return title === '库' || title === '智能书架' || title === '收藏夹'
}
