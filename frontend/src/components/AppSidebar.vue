<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import SidebarNavItem from '@/components/sidebar/SidebarNavItem.vue'
import SidebarSectionHeader from '@/components/sidebar/SidebarSectionHeader.vue'
import Icon from '@/components/ui/Icon.vue'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarHeader,
  SidebarInput,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
  SidebarSeparator,
  useSidebar,
} from '@/components/ui/sidebar'
import { isShelfGroup, type NavGroup, type NavItem } from '@/data/nav'
import { api, apiErrorMessage, type BrowseCounts } from '@/lib/api'
import { useCollectionsStore } from '@/stores/collections'
import { useLibraryStore } from '@/stores/library'
import { useLibraryWizardStore } from '@/stores/libraryWizard'
import { useNavStore } from '@/stores/nav'
import { useUiStore } from '@/stores/ui'

const nav = useNavStore()
const library = useLibraryStore()
const wizard = useLibraryWizardStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()
const { setOpenMobile } = useSidebar()

/**
 * 窄屏点完就走（第 90 期）：抽屉是模态浮层，选中一项后**必须自己收起来** ——
 * 不收的话用户看到的是「点了一下，什么都没变」（目标页在遮罩底下加载完了，
 * 但被抽屉盖着）。宽屏下 `setOpenMobile` 是空操作（`isMobile` 为假时抽屉根本
 * 不渲染），所以这里不必先判 `isMobile`。
 */
function closeMobileDrawer(): void {
  setOpenMobile(false)
}

/**
 * 「库」组筛选框的外观覆盖（第 90 期）。
 *
 * `ui/Input.vue` 是逐字移植的上游组件，它自带一套完整样式（`h-9`、透明底、
 * `border-input`、`md:text-sm`、focus 时一圈 ring）。这里要把它们**逐条抵掉**，
 * 才能跟替换前的就地 `<input>` 长得一模一样：
 *   · `md:text-[12px]` —— 不写的话 ≥768px 时 `md:text-sm` 会把它顶成 14px；
 *   · `dark:bg-muted` / `dark:focus:bg-card` —— 上游的 `dark:bg-input/30` 是
 *     `dark:` 变体，会盖过无变体的 `bg-muted`；
 *   · `focus-visible:ring-0` —— 上游 focus 是一圈 ring，本项目这里是 box-shadow。
 * 用 `cn` 保证「后写的赢」，顺序别调。
 */
const SIDEBAR_FILTER_CLASS =
  'h-[1.875rem] rounded-md border-border bg-muted pr-2.5 pl-[1.875rem] text-[12px] shadow-none md:text-[12px] dark:bg-muted focus-visible:ring-0 focus:border-ring focus:bg-card dark:focus:bg-card focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--ring)_22%,transparent)]'

// 第 78 期：侧栏底部版本号 + new 提示（GitHub 有新版本时挂徽标；点击进「新功能」窗口）
const version = ref('')
const hasUpdate = ref(false)

async function loadVersionInfo(): Promise<void> {
  try {
    const h = await api.health()
    version.value = h.version || ''
  } catch {
    version.value = ''
  }
  try {
    const s = await api.updateStatus()
    hasUpdate.value = s.has_update
  } catch {
    hasUpdate.value = false
  }
}

/** 底部版本号 → 「新功能」窗口（第 78 期）。先收抽屉，理由同 `onItemClick`。 */
function goWhatsNew(): void {
  closeMobileDrawer()
  router.push('/whats-new')
}

/**
 * ⚠️ 第 65 期：`tasks` / `tools` / `stats` / `log` / `reading-activity` / `notify`
 * / `achievements` **七项已不在侧栏**（搬到顶栏图标行），故这张表里对应的七个键
 * 也一并删掉 —— 留着它们只会让人以为侧栏还有那些入口。表里每个键都必须对应
 * 侧栏上真实存在的一项；反过来，侧栏每一项也必须在表里有路由（否则退到
 * `/placeholder/:id`，见 data/nav.ts 文件头）。
 */
const PATH_BY_ID: Record<string, string> = {
  dashboard: '/',
  search: '/explore',
  // 顶层路由（不是 /settings/admin/book-dock）：从侧栏点进去时左栏要保持是主侧栏
  'book-dock': '/book-dock',
  browse: '/browse',
  series: '/series',
  authors: '/authors',
  annotations: '/annotations',
  // 帮助组（复用既有页面，不新建）
  docs: '/docs',
  whatsnew: '/whats-new',
  about: '/settings/ext/about',
}

function pathFor(id: string): string {
  return PATH_BY_ID[id] ?? `/placeholder/${id}`
}

/**
 * 由路由路径反推当前高亮项。
 *
 * ⚠️ 第 65 期：原来那七条（`/tasks` `/tools` `/stats` `/notify` `/achievements`
 * `/log` `/reading-activity`）随侧栏七项一起删了 —— 侧栏上没有这些项，高亮它们
 * 也就无从谈起（那些页面现在从顶栏进，顶栏自己显示当前态）。
 */
const PATH_TO_ID: Array<[string, string]> = [
  ['/explore', 'search'],
  ['/book-dock', 'book-dock'],
  ['/browse', 'browse'],
  ['/series', 'series'],
  ['/authors', 'authors'],
  ['/annotations', 'annotations'],
  ['/docs', 'docs'],
  ['/whats-new', 'whatsnew'],
  ['/settings/ext/about', 'about'],
]

const activeId = computed(() => {
  const p = route.path
  if (p === '/') return 'dashboard'
  const hit = PATH_TO_ID.find(([prefix]) => p.startsWith(prefix))
  return hit ? hit[1] : ''
})

const isActive = computed(() => (id: string) => activeId.value === id)

const collections = useCollectionsStore()

/**
 * 原先这里按 `achievements.enabled` 决定侧栏要不要显示「成就」入口，
 * 并为此 `loadConfig(false, true)`。**第 65 期整块搬走了** —— 侧栏不再有成就项，
 * 门控改在顶栏（`AppHeader.vue` 里同一个判据、同一个「读不到也按启用」的口径）。
 */

/**
 * 「浏览」组的三计数（作者 / 系列 / 批注）。**刻意不传 library_id**：
 * 作者 / 系列 / 批注三页目前都是**跨库**的，计数也跨库才能与页面上列出的条数对得上
 * （传了当前库就会出现「侧栏 3、页面 12」）。服务端 60 秒节流，故跟着路由刷新几乎零开销。
 *
 * 读失败 ⇒ 保持 null（**不渲染胶囊**）：显示 0 是个具体的数字，会与「真的没有」混淆。
 */
const browseCounts = ref<BrowseCounts | null>(null)

async function loadBrowseCounts(): Promise<void> {
  try {
    browseCounts.value = await api.browseCounts()
  } catch {
    browseCounts.value = null
  }
}

/**
 * 把「非首屏关键」的预取推迟到浏览器空闲时再发（第 88 期）。
 *
 * 起因：侧栏一挂载就**一次性并发 6 个请求**（书目 / 库 / 书架 / 收藏夹 / 浏览计数 / 版本），
 * 首屏真正要用的那几个被自己人抢了连接 —— 这正是「打开书库等很久」的一部分。
 * 次要项（侧栏徽标 / 底部版本号）延后一个空闲帧发即可，早几百毫秒没人看得出。
 *
 * ⚠️ 优先 `requestIdleCallback`，**无则退化为一次 `setTimeout 0`**：不能「只有 ric 时才发」，
 * 否则测试环境（happy-dom 没有 ric）里这些预取永远不执行，徽标会静默消失。
 */
function whenIdle(fn: () => void): void {
  const ric = (
    window as unknown as { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number }
  ).requestIdleCallback
  if (typeof ric === 'function') ric(fn, { timeout: 2000 })
  else setTimeout(fn, 0)
}

onMounted(() => {
  // 关键路径：**全量书目**（侧栏计数 / 仪表盘 / BrowseView 等共用）+ 库列表（侧栏「库」组）—— 立刻发。
  // ⚠️ 书架页 `onMounted` 走的是**另一条**分页路（`loadShelfFirstPage`，只取第一页），与本处的
  // 全量 `loadBooks` 是两个不同请求、互不阻塞（第 88 期 C 批修正后如此）；本处仍是「全量 `books`
  // 何时到齐」的唯一关键路径（`loaded` 单飞闸拦的是**同一路**的并发调用）。
  library.loadBooks()
  library.loadLibraries()
  // 次要预取：让出首屏，等空闲再发
  whenIdle(() => {
    collections.load()
    library.loadScopes()
    // 能力清单要跟着**当前库**走（含刷新后恢复上次选中的库）
    void library.loadFeatures()
    void loadBrowseCounts()
    void loadVersionInfo()
  })
})

watch(() => route.path, () => void loadBrowseCounts())

/** 菜单项 → 所需能力（**不声明 = 通用能力**，任何库类型都显示）。菜单归前端所有，所以这张表在前端。 */
const ITEM_FEATURE: Record<string, string> = {
  // 批注只对 EPUB 有效（漫画 / 音频没有批注能力）
  annotations: 'annotations',
}

/**
 * 「库」= **真实书库实体**（含「全部书库」），点击即切库；
 * 「收藏夹」用 SQLite 数据，「智能书架」用真实阅读状态计数；其余组保持 NAV_GROUPS 原样。
 * 最后统一按**当前库的能力清单**裁剪 —— 未选库（全部书库）时不裁剪。
 */
const groups = computed(() =>
  nav.groups.map((g) => {
    if (g.title === '库') {
      return {
        ...g,
        items: [
          // 「全部书库」置顶：它是**默认态**，也必须是能随时回来的出口
          { id: 'lib:', label: '全部书库', icon: 'library', count: library.books.length },
          ...library.libraryEntities.map((x) => ({
            id: `lib:${x.id}`,
            label: x.name,
            // 第 40 期：建库时选的图标（空 = 用通用的书架图标兜底）。
            // 未知 key 由 `iconPath()` 返回空串降级，不会渲染出半个图标。
            icon: x.icon || 'library',
            count: x.book_count,
          })),
        ] as NavItem[],
      }
    }
    if (g.title === '收藏夹') {
      return {
        ...g,
        items: collections.items.map((c) => ({
          id: `col:${c.id}`,
          label: c.name,
          icon: 'star',
          count: c.count,
        })),
      }
    }
    if (g.title === '智能书架') {
      // **只有用户手建的**（smart_scopes 表）；第 37 期起不再预置那 5 条内置书架
      return {
        ...g,
        items: library.scopes.map((s) => ({
          id: `scope:${s.id}`,
          label: s.name,
          icon: 'search',
          count: library.scopeCounts[`scope:${s.id}`] ?? 0,
        })),
      }
    }
    return g
  }).map((g) => ({
    // 按当前库的能力裁剪条目（见 ITEM_FEATURE；未声明的通用项一律保留）
    ...g,
    items: g.items.filter((it) => {
      const need = ITEM_FEATURE[it.id]
      return !need || library.hasFeature(need)
    }),
  })),
)

/** 「浏览」组三项的计数键 = 菜单 id（与后端响应的字段名逐字一致，别改名） */
const BROWSE_COUNT_KEYS: Record<string, 'authors' | 'series' | 'annotations'> = {
  authors: 'authors',
  series: 'series',
  annotations: 'annotations',
}

function navCount(item: NavItem): number | null {
  // 原来还有一个 `'running'` 分支（任务中心的运行中数）—— 第 65 期随那一项
  // 搬到顶栏，计数变成顶栏任务按钮上的角标（见 TaskFlyout.vue）
  if (item.countSource === 'browse') {
    const key = BROWSE_COUNT_KEYS[item.id]
    const c = browseCounts.value
    // 数字还没到 / 读失败 → null（不渲染胶囊），而不是拿 0 冒充「没有」
    return key && c ? c[key] : null
  }
  return item.count ?? null
}

function onItemClick(groupTitle: string | null, item: NavItem): void {
  // 先收起抽屉再跳：跳转是异步的，等它完成再收会让用户盯着遮罩愣一下
  closeMobileDrawer()

  if (item.id.startsWith('col:')) {
    router.push(`/collections/${item.id.slice(4)}`)
    return
  }
  if (item.id.startsWith('scope:')) {
    // 自定义智能书架：openSmart 直接吃 scope:{id} 键，shelfBooks 里按规则求值
    library.openSmart(item.label, item.id)
    router.push('/shelf')
    return
  }
  if (item.id.startsWith('lib:')) {
    // 切库 + 进书架（`lib:` 后为空 = 全部书库）；能力清单随库类型变化
    void library.openLibraryById(item.id.slice(4), item.label)
    router.push('/shelf')
    return
  }
  if (groupTitle && isShelfGroup(groupTitle)) {
    library.openShelf(item.label)
    router.push('/shelf')
    return
  }
  router.push(pathFor(item.id))
}

/** 组底部「更多」行括号里的数字：申报了来源就用真实数，没申报才回退到本组条数 */
function groupMoreCount(group: NavGroup): number {
  if (group.more?.countSource === 'libraries') return library.libraryEntities.length
  return group.items.length
}

/** 组底部「更多」行的去向：申报了 `to` 就按路由去，否则沿用「进书架看全部」 */
function onGroupMore(group: NavGroup): void {
  closeMobileDrawer()
  const to = group.more?.to
  if (to) {
    router.push(to)
    return
  }
  library.openShelf(group.more?.label ?? '')
  router.push('/shelf')
}

/** 分组头部的「新增 / 更多」：三组各自接到真实去处，不再有演示态动作 */
async function onGroupAction(title: string, action: 'add' | 'more'): Promise<void> {
  if (title === '库') {
    // 「新增」就地弹窗（第 55 期）：不再跳 `?new=1` —— 建库在哪儿发生，向导就在哪儿打开；
    // 「更多」仍进书库管理页 —— 库的增删改都在那里，本项目没有第二个书库管理界面。
    if (action === 'add') {
      void wizard.show()
      return
    }
    router.push('/settings/libraries')
    return
  }
  if (title === '智能书架' && action === 'add') {
    router.push('/smart-scopes')
    return
  }
  if (title === '收藏夹' && action === 'add') {
    const name = window.prompt('新建收藏夹名称')
    if (name && name.trim()) {
      try {
        await collections.create(name.trim())
      } catch (e) {
        // ⚠️ 这里原本是 ui.demo(...)：真失败被套上「演示动作：」前缀，看着像在演戏
        ui.toast(apiErrorMessage(e, '创建收藏夹失败'))
      }
    }
    return
  }
  // 兜底：不再有假动作。真出现没接线的分组就如实说，不弹「演示动作」
  ui.toast(`「${title}」分组暂无对应页面`)
}
</script>

<template>
  <!--
    第 90 期：整个侧栏换成上游 BookOrbit 的 `Sidebar*` 体系（分组 / 菜单 / 折叠）。
    桌面折叠成 3rem 图标条，≤640px 变成抽屉，右缘一条可点可拖的拉手 —— 三者都由
    `Sidebar.vue` 按 `isMobile` / `state` 分派，这里只负责填内容。
  -->
  <Sidebar collapsible="icon" variant="floating">
    <!-- 品牌头。`group-data-[collapsible=icon]:px-2` 是必须的：3rem 宽的卡片减去
         `px-3.5`（28px）只剩 20px，30px 的方标会溢出去。 -->
    <SidebarHeader class="px-3.5 pt-3.5 pb-3 group-data-[collapsible=icon]:px-2 group-data-[collapsible=icon]:py-2.5">
      <RouterLink
        to="/"
        class="flex h-[1.875rem] items-center gap-2.5 rounded-md outline-hidden focus-visible:ring-2 focus-visible:ring-sidebar-ring"
        aria-label="回到仪表盘"
        @click="closeMobileDrawer"
      >
        <div class="grid h-[1.875rem] w-[1.875rem] shrink-0 place-items-center rounded-sm bg-primary font-serif text-[15px] leading-none font-bold text-primary-foreground">
          书
        </div>
        <div class="truncate text-[14.5px] font-semibold tracking-[-0.01em] text-sidebar-foreground group-data-[collapsible=icon]:hidden">
          书籍轨道
        </div>
      </RouterLink>
    </SidebarHeader>

    <SidebarContent class="pb-3">
      <template v-for="(group, gi) in groups" :key="group.title ?? `main-${gi}`">
        <!-- 组间分隔线。除第一组外都画；`SidebarSeparator` 自带 `my-1`，
             所以不再需要原来那句 `-mx-2 mt-1.5 px-2 pt-1.5` 的负边距把戏。 -->
        <SidebarSeparator v-if="gi > 0" />

        <SidebarGroup>
          <SidebarSectionHeader
            v-if="group.title"
            :label="group.title"
            :is-open="!nav.collapsed[group.title]"
            :actions="group.actions ?? []"
            @toggle="nav.toggleGroup(group.title)"
            @action="onGroupAction(group.title, $event)"
          />

          <!-- 折叠只切 v-show，不重建 DOM；筛选只切显隐，输入焦点不丢 -->
          <SidebarGroupContent v-show="!group.title || !nav.collapsed[group.title]">
            <div v-if="group.search" class="relative px-0.5 pt-0.5 pb-1.5 group-data-[collapsible=icon]:hidden">
              <svg
                class="pointer-events-none absolute top-[calc(50%-0.1875rem)] left-[0.6875rem] z-10 h-[0.8125rem] w-[0.8125rem] -translate-y-1/2 text-muted-foreground"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="2"
                stroke-linecap="round"
              >
                <circle cx="11" cy="11" r="7" />
                <path d="M20 20l-3.6-3.6" />
              </svg>
              <SidebarInput
                :model-value="nav.libFilter"
                :placeholder="group.search.placeholder"
                :aria-label="group.search.placeholder"
                :class="SIDEBAR_FILTER_CLASS"
                @update:model-value="nav.setLibFilter(String($event ?? ''))"
              />
            </div>

            <SidebarMenu v-if="group.items.length">
              <SidebarNavItem
                v-for="item in group.items"
                :key="item.id"
                :item="item"
                :is-active="isActive(item.id)"
                :count="navCount(item)"
                :visible="nav.itemVisible(group.title ?? '', item)"
                @select="onItemClick(group.title, $event)"
              />
            </SidebarMenu>
            <div v-else-if="!group.search" class="px-[0.625rem] pt-1.5 pb-2 text-[11.5px] text-muted-foreground/70 group-data-[collapsible=icon]:hidden">
              {{ group.empty ?? '暂无内容' }}
            </div>

            <!-- 「库」组**永远不为空**（恒有「全部书库」一项），所以上面的 `group.empty`
                 对它永远走不到 —— 0 库时这里单独补一行明示（第 38 期）。
                 没有它，全新部署的侧栏「库」组就只有一个筛选框和「查看全部书库（0）」。 -->
            <SidebarMenu v-if="group.title === '库' && library.hasNoLibraries">
              <SidebarMenuItem>
                <SidebarMenuButton
                  as="button"
                  type="button"
                  size="sm"
                  tooltip="新建书库"
                  class="text-[11.5px] text-muted-foreground"
                  @click="onGroupAction('库', 'add')"
                >
                  <Icon name="plus" class="h-3 w-3 shrink-0" />
                  <span class="min-w-0 flex-1 truncate group-data-[collapsible=icon]:hidden">还没有书库，先建一个</span>
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>

            <SidebarMenu v-if="group.more">
              <SidebarMenuItem>
                <SidebarMenuButton
                  as="button"
                  type="button"
                  size="sm"
                  :tooltip="group.more?.label"
                  class="text-[11.5px] text-muted-foreground"
                  @click="onGroupMore(group)"
                >
                  <span class="min-w-0 flex-1 truncate group-data-[collapsible=icon]:hidden">
                    {{ group.more.label }}（{{ groupMoreCount(group) }}）
                  </span>
                  <Icon name="arrowRight" class="h-[0.8125rem] w-[0.8125rem] shrink-0" />
                </SidebarMenuButton>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </template>
    </SidebarContent>

    <!-- 第 78 期：侧栏底部版本号 + new 提示；点击进「新功能」窗口。
         图标条态下文字被收掉，留一个 `sparkle` 代表「新功能」——否则那里会是一个
         什么都没有的 32px 方块。 -->
    <SidebarFooter class="border-t border-border px-2 py-2 group-data-[collapsible=icon]:px-1">
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            as="button"
            type="button"
            size="sm"
            :tooltip="hasUpdate ? '有新版本，查看新功能' : '新功能'"
            class="justify-center gap-1.5 text-[11.5px] text-muted-foreground"
            @click="goWhatsNew"
          >
            <span class="font-mono tabular-nums group-data-[collapsible=icon]:hidden">v{{ version || '…' }}</span>
            <span
              v-if="hasUpdate"
              class="rounded-full bg-primary px-1.5 py-0.5 text-[9.5px] leading-none font-semibold text-primary-foreground group-data-[collapsible=icon]:hidden"
            >new</span>
            <Icon name="sparkle" class="hidden h-[0.9375rem] w-[0.9375rem] shrink-0 group-data-[collapsible=icon]:block" />
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
    </SidebarFooter>

    <SidebarRail />
  </Sidebar>
</template>
