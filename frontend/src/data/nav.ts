/**
 * 侧栏结构。迁移自 v2 app.js 的 NAV_GROUPS（原第 100–121 行）。
 *
 * 约定（沿用 v2 注释）：
 *   · title 为 null 即「无组标题」的主导航
 *   · count 不写时**不渲染计数胶囊**，等真实数据接上再填
 *   · 以 _ 开头的 id 目前没有对应视图，点击落占位页
 *   · 库 / 智能书架 / 收藏夹 的条目点击进入书库页
 */
import { COLLECTIONS, LIBRARIES, SMART_SHELVES, type NavEntry } from './collections'

export interface NavItem {
  id: string
  label: string
  icon: string
  /** 静态计数；不写则不渲染胶囊 */
  count?: number
  /** 动态计数来源：目前只有任务中心用它取「运行中 + 排队中」 */
  countSource?: 'running'
}

export interface NavGroup {
  title: string | null
  collapsible?: boolean
  actions?: Array<'add' | 'more'>
  search?: { placeholder: string }
  items: NavItem[]
  more?: { label: string }
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
      { id: 'authors', label: '作者', icon: 'users' },
      { id: 'series', label: '系列', icon: 'layers' },
      { id: 'annotations', label: '批注', icon: 'pencil' },
    ],
  },
  {
    title: '库',
    collapsible: true,
    actions: ['add', 'more'],
    search: { placeholder: '筛选书库…' },
    items: LIBRARIES as NavEntry[],
    more: { label: '查看全部书库' },
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

/** 占位视图的元信息。迁移自 v2 app.js 的 VIEW_META（639–648） */
export const VIEW_META: Record<string, { icon: string; title: string; desc: string }> = {
  _authors: { icon: 'users', title: '作者', desc: '按作者浏览' },
  _series: { icon: 'layers', title: '系列', desc: '按系列浏览' },
  _notes: { icon: 'pencil', title: '批注', desc: '全部摘录与笔记' },
  notify: { icon: 'bell', title: '通知中心', desc: '任务完成与失败提醒' },
  stats: { icon: 'chart', title: '数据统计', desc: '阅读与任务统计' },
  search: { icon: 'search', title: '探索发现', desc: '跨全部已启用书源聚合检索' },
  sources: { icon: 'source', title: '书源', desc: '规则、健康度与启用开关' },
}
