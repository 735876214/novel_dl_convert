<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import Icon from '@/components/ui/Icon.vue'
import { isShelfGroup, type NavItem } from '@/data/nav'
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
  'tools-sources': '/tools/sources',
  'tools-output': '/tools/output',
  'tools-local': '/tools/local',
  'tools-logs': '/tools/logs',
}

function pathFor(id: string): string {
  return PATH_BY_ID[id] ?? `/placeholder/${id}`
}

/** 由路由路径反推当前高亮项 */
const PATH_TO_ID: Array<[string, string]> = [
  ['/explore', 'search'],
  ['/tasks', 'tasks'],
  ['/tools/sources', 'tools-sources'],
  ['/tools/output', 'tools-output'],
  ['/tools/local', 'tools-local'],
  ['/tools/logs', 'tools-logs'],
]

const activeId = computed(() => {
  const p = route.path
  if (p === '/') return 'dashboard'
  const hit = PATH_TO_ID.find(([prefix]) => p.startsWith(prefix))
  return hit ? hit[1] : ''
})

const isActive = computed(() => (id: string) => activeId.value === id)

function navCount(item: NavItem): number | null {
  if (item.countSource === 'running') return tasks.runningCount
  return item.count ?? null
}

function onItemClick(groupTitle: string | null, item: NavItem): void {
  if (groupTitle && isShelfGroup(groupTitle)) {
    library.openShelf(item.label)
    router.push('/shelf')
    return
  }
  router.push(pathFor(item.id))
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
        v-for="(group, gi) in nav.groups"
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
              @click.stop="nav.navAction(group.title, action)"
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
              v-show="nav.itemVisible(group.title ?? '', item)"
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
            @click="library.openShelf(group.more.label); router.push('/shelf')"
          >
            <span>{{ group.more.label }}（{{ group.items.length }}）</span>
            <Icon name="arrowRight" class="ml-auto h-[0.8125rem] w-[0.8125rem]" />
          </div>
        </div>
      </div>
    </div>
  </aside>
</template>
