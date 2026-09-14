<script setup lang="ts">
import { useRouter } from 'vue-router'

import Icon from '@/components/ui/Icon.vue'
import { THEME_LABEL, useThemeStore } from '@/stores/theme'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const theme = useThemeStore()
const router = useRouter()

function onTheme(): void {
  const next = theme.cycleTheme()
  ui.toast(`主题：${THEME_LABEL[next]}`)
}

function onSearchKeydown(e: KeyboardEvent): void {
  const input = e.target as HTMLInputElement
  if (e.key === 'Escape') {
    input.value = ''
    input.blur()
  }
  if (e.key === 'Enter' && input.value.trim()) {
    ui.demo(`全局搜索「${input.value.trim()}」`)
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
      <button :class="ICON_BTN" type="button" title="通知中心" aria-label="通知中心" @click="router.push('/placeholder/notify')">
        <Icon name="bell" class="h-[17px] w-[17px]" />
      </button>
      <button :class="ICON_BTN" type="button" title="数据统计" aria-label="数据统计" @click="router.push('/placeholder/stats')">
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
      <button
        :class="ICON_BTN"
        type="button"
        :title="`切换主题（当前：${THEME_LABEL[theme.theme]}）`"
        aria-label="切换主题"
        @click="onTheme()"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" class="h-[17px] w-[17px]">
          <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
        </svg>
      </button>
      <button :class="ICON_BTN" type="button" title="设置" aria-label="设置" @click="router.push('/settings')">
        <Icon name="settings" class="h-[17px] w-[17px]" />
      </button>
      <div
        class="h-8 w-8 shrink-0 cursor-pointer rounded-full border border-border bg-muted shadow-[inset_0_0_0_3px_var(--card)]"
        title="本地用户"
      />
    </div>
  </header>
</template>
