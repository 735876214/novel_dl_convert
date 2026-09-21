<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Icon from '@/components/ui/Icon.vue'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { isShelfGroup, type NavGroup, type NavItem } from '@/data/nav'
import { api, apiErrorMessage, type BrowseCounts } from '@/lib/api'
import { useCollectionsStore } from '@/stores/collections'
import { useLibraryStore } from '@/stores/library'
import { useNavStore } from '@/stores/nav'
import { useTasksStore } from '@/stores/tasks'
import { useUiStore } from '@/stores/ui'

const nav = useNavStore()
const library = useLibraryStore()
const tasks = useTasksStore()
const ui = useUiStore()
const route = useRoute()
const router = useRouter()

const PATH_BY_ID: Record<string, string> = {
  dashboard: '/',
  search: '/explore',
  tasks: '/tasks',
  // 「工具」是唯一入口，8 个工具在工具页内用标签栏切换
  tools: '/tools',
  browse: '/browse',
  series: '/series',
  authors: '/authors',
  annotations: '/annotations',
  stats: '/stats',
  notify: '/notify',
  achievements: '/achievements',
  log: '/log',
  'reading-activity': '/reading-activity',
  // 帮助组（复用既有页面，不新建）
  docs: '/docs',
  whatsnew: '/whats-new',
  about: '/settings/ext/about',
}

function pathFor(id: string): string {
  return PATH_BY_ID[id] ?? `/placeholder/${id}`
}

/** 由路由路径反推当前高亮项 */
const PATH_TO_ID: Array<[string, string]> = [
  ['/explore', 'search'],
  ['/tasks', 'tasks'],
  // 前缀匹配：/tools 覆盖全部 8 个工具子路径，故任意标签下「工具」项都保持高亮
  ['/tools', 'tools'],
  ['/browse', 'browse'],
  ['/series', 'series'],
  ['/authors', 'authors'],
  ['/annotations', 'annotations'],
  ['/stats', 'stats'],
  ['/notify', 'notify'],
  ['/achievements', 'achievements'],
  ['/log', 'log'],
  ['/reading-activity', 'reading-activity'],
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
const { cfg, loadConfig } = useSettingsConfig()

/**
 * 成就开关会影响侧栏是否显示「成就」入口（上游语义：关闭后不显示成就相关界面）。
 *
 * 静默加载：读配置失败时**不弹提示**，并按「启用」处理 ——
 * 因为读不到配置就把入口藏起来，用户会以为功能没了，比多显示一个入口更糟。
 */
const achievementsEnabled = computed(() => cfg.value?.achievements?.enabled !== false)

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

onMounted(() => {
  collections.load()
  library.loadBooks()
  library.loadLibraries()
  library.loadScopes()
  // 能力清单要跟着**当前库**走（含刷新后恢复上次选中的库）
  void library.loadFeatures()
  void loadConfig(false, true)
  void loadBrowseCounts()
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
            icon: 'library',
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
      return {
        ...g,
        items: [
          ...g.items.map((it) => ({ ...it, count: library.smartCounts[it.label] ?? 0 })),
          // 自定义智能书架：smart_scopes 表里的规则书架
          ...library.scopes.map((s) => ({
            id: `scope:${s.id}`,
            label: s.name,
            icon: 'search',
            count: library.scopeCounts[`scope:${s.id}`] ?? 0,
          })),
        ],
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
  if (item.countSource === 'running') return tasks.runningCount
  if (item.countSource === 'browse') {
    const key = BROWSE_COUNT_KEYS[item.id]
    const c = browseCounts.value
    // 数字还没到 / 读失败 → null（不渲染胶囊），而不是拿 0 冒充「没有」
    return key && c ? c[key] : null
  }
  return item.count ?? null
}

function onItemClick(groupTitle: string | null, item: NavItem): void {
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
  if (groupTitle === '智能书架') {
    library.openSmart(item.label, library.smartKeyOf(item.label))
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
    // 「新增」直达书库管理页的新建弹窗（`?new=1`，见 LibrariesView 的 onMounted）；
    // 「更多」进同一页 —— 库的增删改都在那里，本项目没有第二个书库管理界面。
    router.push(action === 'add' ? '/tools/libraries?new=1' : '/tools/libraries')
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
  <aside
    class="flex w-[15rem] shrink-0 flex-col overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-xs backdrop-blur-md backdrop-saturate-150 transition-[margin-left,width] duration-150"
    :class="ui.sidebarCollapsed ? '-ml-[calc(15rem+var(--shell-gap))]' : ''"
  >
    <div class="flex shrink-0 items-center gap-2.5 px-3.5 pt-3.5 pb-3">
      <div class="grid h-[1.875rem] w-[1.875rem] shrink-0 place-items-center rounded-sm bg-primary font-serif text-[15px] leading-none font-bold text-primary-foreground">
        书
      </div>
      <div class="text-[14.5px] font-semibold tracking-[-0.01em] text-sidebar-foreground">书籍轨道</div>
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto px-2 pb-3" data-sidebar="content">
      <div
        v-for="(group, gi) in groups"
        :key="group.title ?? `main-${gi}`"
        class="relative"
        :class="gi > 0 ? '-mx-2 mt-1.5 border-t border-border px-2 pt-1.5' : ''"
      >
        <div
          v-if="group.title"
          class="flex cursor-pointer items-center gap-1.5 rounded-md px-[0.625rem] py-1.5 transition-colors select-none hover:bg-[var(--shell-accent-wash)]"
          @click="nav.toggleGroup(group.title)"
        >
          <span class="text-[11px] font-semibold tracking-[0.08em] text-muted-foreground">{{ group.title }}</span>
          <span class="ml-auto flex items-center gap-0.5">
            <button
              v-for="action in group.actions ?? []"
              :key="action"
              type="button"
              class="grid h-5 w-5 shrink-0 cursor-pointer place-items-center rounded-sm text-muted-foreground transition-colors hover:bg-muted hover:text-primary"
              :title="(action === 'add' ? '新增' : '更多') + group.title"
              :aria-label="(action === 'add' ? '新增' : '更多') + group.title"
              @click.stop="onGroupAction(group.title, action)"
            >
              <Icon :name="action === 'add' ? 'plus' : 'more'" class="h-3 w-3" />
            </button>
            <span
              class="grid place-items-center text-muted-foreground transition-transform duration-150"
              :class="nav.collapsed[group.title] ? '-rotate-90' : ''"
            >
              <Icon name="chev" class="h-3.5 w-3.5" />
            </span>
          </span>
        </div>

        <!-- 折叠只切 class，不重建 DOM；筛选只切显隐，输入焦点不丢 -->
        <div v-show="!group.title || !nav.collapsed[group.title]">
          <div v-if="group.search" class="relative px-0.5 pt-0.5 pb-1.5">
            <svg
              class="pointer-events-none absolute top-[calc(50%-0.1875rem)] left-[0.6875rem] h-[0.8125rem] w-[0.8125rem] -translate-y-1/2 text-muted-foreground"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="2"
              stroke-linecap="round"
            >
              <circle cx="11" cy="11" r="7" />
              <path d="M20 20l-3.6-3.6" />
            </svg>
            <input
              type="text"
              :value="nav.libFilter"
              :placeholder="group.search.placeholder"
              :aria-label="group.search.placeholder"
              class="h-[1.875rem] w-full rounded-md border border-border bg-muted pr-2.5 pl-[1.875rem] text-[12px] text-foreground outline-none transition-[border-color,box-shadow,background-color] placeholder:text-muted-foreground focus:border-ring focus:bg-card focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--ring)_22%,transparent)]"
              @input="nav.setLibFilter(($event.target as HTMLInputElement).value)"
            >
          </div>

          <div v-if="group.items.length">
            <div
              v-for="item in group.items"
              v-show="nav.itemVisible(group.title ?? '', item) && (item.id !== 'achievements' || achievementsEnabled)"
              :key="item.id"
              class="flex cursor-pointer items-center gap-[0.5625rem] rounded-md px-[0.625rem] py-[0.4375rem] text-[13px] transition-colors select-none"
              :class="
                isActive(item.id)
                  ? 'bg-[var(--shell-accent-tint)] font-semibold text-primary opacity-100'
                  : 'text-sidebar-foreground opacity-[0.78] hover:bg-[var(--shell-accent-wash)] hover:opacity-100'
              "
              @click="onItemClick(group.title, item)"
            >
              <Icon :name="item.icon" class="h-[0.9375rem] w-[0.9375rem] opacity-80" />
              <span class="truncate">{{ item.label }}</span>
              <span
                v-if="navCount(item) !== null"
                class="ml-auto shrink-0 rounded-full px-[0.4375rem] py-1 text-[10.5px] leading-none font-medium text-sidebar-count-foreground tabular-nums"
                :class="isActive(item.id) ? 'bg-[var(--shell-accent-line)] text-primary' : 'bg-muted'"
              >
                {{ navCount(item) }}
              </span>
            </div>
          </div>
          <div v-else-if="!group.search" class="px-[0.625rem] pt-1.5 pb-2 text-[11.5px] text-muted-foreground/70">
            {{ group.empty ?? '暂无内容' }}
          </div>

          <div
            v-if="group.more"
            class="mt-0.5 flex cursor-pointer items-center gap-1 rounded-md px-[0.625rem] py-2 text-[11.5px] text-muted-foreground transition-colors hover:bg-[var(--shell-accent-wash)] hover:text-primary"
            @click="onGroupMore(group)"
          >
            <span>{{ group.more.label }}（{{ groupMoreCount(group) }}）</span>
            <Icon name="arrowRight" class="ml-auto h-[0.8125rem] w-[0.8125rem]" />
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>
