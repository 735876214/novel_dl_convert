<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

import Icon from '@/components/ui/Icon.vue'
import { useUiStore } from '@/stores/ui'
import {
  SETTINGS_GROUPS,
  findSettingsGroup,
  findSettingsPage,
  type SettingsGroupDef,
} from '@/data/settingsNav'

const route = useRoute()
const router = useRouter()
const ui = useUiStore()

/** 相对 `/settings/` 的子路径 */
const rel = computed(() => route.path.replace(/^\/settings\/?/, ''))
const currentPage = computed(() => findSettingsPage(rel.value))
const currentGroup = computed(() => findSettingsGroup(rel.value))
const activeGroupId = computed(() => currentGroup.value?.id ?? '')

/** 展开的分组：默认展开当前所在分组，并保留「本项目扩展」常驻展开 */
const open = ref<Set<string>>(new Set(['you', 'ext']))

watch(
  activeGroupId,
  (id) => {
    if (id && !open.value.has(id)) open.value = new Set([...open.value, id])
  },
  { immediate: true },
)

function toggle(g: SettingsGroupDef): void {
  const next = new Set(open.value)
  if (next.has(g.id)) next.delete(g.id)
  else next.add(g.id)
  open.value = next
}

/** 返回主界面（仪表盘） */
function goHome(): void {
  router.push('/')
}
</script>

<template>
  <aside
    class="flex w-[15rem] shrink-0 flex-col overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-xs backdrop-blur-md backdrop-saturate-150 transition-[margin-left,width] duration-150"
    :class="ui.sidebarCollapsed ? '-ml-[calc(15rem+var(--shell-gap))]' : ''"
  >
    <!-- 顶部：返回主界面 -->
    <div class="shrink-0 px-3 pt-3 pb-2">
      <button
        type="button"
        class="flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-[13px] font-medium text-sidebar-foreground transition-colors hover:bg-[var(--shell-accent-wash)] hover:text-primary"
        title="返回主界面"
        aria-label="返回主界面"
        @click="goHome"
      >
        <Icon name="arrowLeft" class="h-[1.0625rem] w-[1.0625rem] shrink-0" />
        <span>返回主界面</span>
      </button>
    </div>

    <!-- 列标题 -->
    <div class="flex shrink-0 items-center gap-2.5 border-b border-border px-3.5 pb-3">
      <div class="grid h-[1.875rem] w-[1.875rem] shrink-0 place-items-center rounded-sm bg-primary font-serif text-[15px] leading-none font-bold text-primary-foreground">
        书
      </div>
      <div class="text-[14.5px] font-semibold tracking-[-0.01em] text-sidebar-foreground">设置</div>
    </div>

    <!-- 设置分组导航 -->
    <div class="min-h-0 flex-1 overflow-y-auto px-2 py-3">
      <div
        v-for="g in SETTINGS_GROUPS"
        :key="g.id"
        class="relative"
      >
        <!-- 分组头：可折叠 -->
        <button
          type="button"
          class="flex w-full shrink-0 cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wide transition-colors"
          :class="
            activeGroupId === g.id
              ? 'text-foreground'
              : 'text-muted-foreground hover:text-foreground'
          "
          :aria-expanded="open.has(g.id)"
          @click="toggle(g)"
        >
          <Icon :name="g.icon" class="h-3.5 w-3.5 shrink-0" />
          <span class="whitespace-nowrap">{{ g.zh }}</span>
          <span class="hidden font-mono text-[10px] font-normal opacity-60 lg:inline">{{ g.label }}</span>
          <Icon
            name="chev"
            class="ml-auto hidden h-3 w-3 shrink-0 transition-transform lg:block"
            :class="open.has(g.id) ? '' : '-rotate-90'"
          />
        </button>

        <!-- 分组内页面 -->
        <div v-show="open.has(g.id)" class="mt-0.5 space-y-0.5 border-l border-border pl-2">
          <RouterLink
            v-for="pg in g.pages"
            :key="pg.path"
            :to="`/settings/${pg.path}`"
            :title="`${pg.zh} · ${pg.label}`"
            class="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-[12.5px] transition-colors"
            :class="
              currentPage?.path === pg.path
                ? 'bg-[var(--shell-accent-tint)] font-medium text-primary'
                : 'text-muted-foreground hover:bg-[var(--shell-accent-wash)] hover:text-foreground'
            "
          >
            <span class="min-w-0 flex-1 truncate">{{ pg.zh }}</span>
            <!-- 未支持页给出明确标识，避免用户点进去才发现 -->
            <span
              v-if="pg.status === 'placeholder'"
              class="hidden shrink-0 rounded bg-muted px-1 text-[10px] text-muted-foreground lg:inline"
            >未支持</span>
          </RouterLink>
        </div>
      </div>
    </div>
  </aside>
</template>
