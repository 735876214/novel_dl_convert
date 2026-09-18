<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'

import NotificationBell from '@/components/NotificationBell.vue'
import AppearanceMenu from '@/components/AppearanceMenu.vue'
import UserMenu from '@/components/UserMenu.vue'
import Icon from '@/components/ui/Icon.vue'
import { usePrefSyncStore } from '@/stores/prefSync'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const router = useRouter()
const sync = usePrefSyncStore()

/** 应用级入口：注册偏好变更回调并启动同步（幂等）。
 *
 * 放在顶栏而不是 App.vue：未登录时 App 渲染的是登录门禁、顶栏不挂载，
 * 所以这里的启动时机天然是「已登录」，不会白跑一次注定 401 的 boot。
 */
onMounted(() => sync.init())

function onSearchKeydown(e: KeyboardEvent): void {
  const input = e.target as HTMLInputElement
  if (e.key === 'Escape') {
    input.value = ''
    input.blur()
  }
  if (e.key === 'Enter' && input.value.trim()) {
    // 真实搜索：跳到书架页并把关键词带过去（书架本地过滤全量书单，所以这是真检索）。
    // 原先这里只弹一个 demo 提示 —— 属于「看起来能用、其实没接线」。
    router.push({ path: '/shelf', query: { q: input.value.trim() } })
    input.value = ''
    input.blur()
  }
}

/** 顶栏图标的统一外观：hover 抬起、当前态用主色底 */
const ICON_BTN =
  'grid h-[2.0625rem] w-[2.0625rem] cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground'
</script>

<template>
  <header class="flex h-14 shrink-0 items-center gap-3.5 border-b border-border px-[var(--shell-content-gutter)]">
    <button
      type="button"
      class="grid h-8 w-8 cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      title="切换侧边栏"
      aria-label="切换侧边栏"
      @click="ui.toggleSidebar()"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-[17px] w-[17px]">
        <rect x="3" y="4" width="18" height="16" rx="2" />
        <path d="M9 4v16" />
      </svg>
    </button>

    <div class="relative max-w-[35rem] flex-1">
      <svg class="pointer-events-none absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round">
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3.6-3.6" />
      </svg>
      <input
        id="globalSearch"
        type="text"
        placeholder="搜索全部书籍..."
        autocomplete="off"
        aria-label="搜索全部书籍"
        class="h-9 w-full rounded-md border border-transparent bg-muted pr-[4.375rem] pl-9 text-[13px] text-foreground outline-none transition-[border-color,box-shadow,background-color] placeholder:text-muted-foreground focus:border-ring focus:bg-card focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--ring)_22%,transparent)]"
        @keydown="onSearchKeydown"
      >
      <span class="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 rounded-sm border border-border bg-card px-1.5 py-px text-[10.5px] text-muted-foreground">
        ⌘K
      </span>
    </div>

    <div class="ml-auto flex items-center gap-[0.3125rem]">
      <!-- 偏好未同步（离线 / 服务端不可用）：恢复后自动消失；点击去「偏好与同步」 -->
      <button
        v-if="sync.offline"
        type="button"
        class="flex h-7 cursor-pointer items-center rounded-full bg-amber-500/15 px-2.5 text-[11.5px] text-amber-600 transition-colors hover:bg-amber-500/25 dark:text-amber-400"
        title="偏好未能同步到服务端（离线或服务端不可用）。本机改动照常生效，恢复后会自动推送"
        @click="router.push('/settings/reader/general')"
      >
        离线 · 未同步
      </button>
      <!-- 通知：浮层 + 未读角标（与整页 /notify 同数据源） -->
      <NotificationBell />
      <button :class="ICON_BTN" type="button" title="数据统计" aria-label="数据统计" @click="router.push('/stats')">
        <Icon name="chart" class="h-[17px] w-[17px]" />
      </button>
      <button
        :class="[ICON_BTN, ui.drawerOpen ? 'bg-[var(--shell-accent-tint)] text-primary hover:text-primary' : '']"
        type="button"
        title="任务面板"
        aria-label="切换任务面板"
        @click="ui.toggleDrawer()"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="h-[17px] w-[17px]">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <path d="M15 4v16" />
        </svg>
      </button>
      <AppearanceMenu />
      <button :class="ICON_BTN" type="button" title="设置" aria-label="设置" @click="router.push('/settings')">
        <Icon name="settings" class="h-[17px] w-[17px]" />
      </button>
      <UserMenu />
    </div>
  </header>
</template>
