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
   *   · `browse` —— 「浏览」组三项，取 `/api/browse-counts`（第 34 期；
   *      数字与目标页同源，服务端 60 秒节流，按 id 到响应里取同名字段）。
   *
   * ⚠️ 原有一个 `running`（任务中心的「运行中 + 排队中」）**第 65 期已删** ——
   * 它唯一的消费者「任务中心」那一项从侧栏搬到了顶栏，计数改由顶栏的任务按钮
   * 自己显示角标（见 AppHeader 里的 TaskFlyout）。留在这里就是死代码。
   */
  countSource?: 'browse'
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
      // 「收书目录」（Book Dock，第 65 期）：与「探索发现」**同级**的一级入口。
      // 路由是**顶层**的 `/book-dock` 而不是 `/settings/admin/book-dock` ——
      // 后者会让整个左栏换成设置侧栏（App.vue 按 `/settings` 前缀判断），
      // 而这里是从首页侧栏点进来的，左栏不该变脸。设置里那一条**原样保留**
      //（上游也是两处都有：设置里有 Book Dock，侧栏也有一级项）。
      { id: 'book-dock', label: '收书目录', icon: 'upload' },
      // ⚠️ 任务中心 / 工具 / 数据统计 / 阅读记录 / 阅读活动 / 通知中心 / 成就
      //    **七项自第 65 期起不再在这里**，全部搬到顶栏图标行（与既有图标并排）。
      //    顶栏是它们的**唯一入口** —— 别再往回加，那会变成同一页两个入口。
      //    计数胶囊（任务运行中数）也随之搬到顶栏任务按钮的角标上。
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
    more: { label: '查看全部书库', to: '/settings/libraries', countSource: 'libraries' },
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
