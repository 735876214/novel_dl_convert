<script setup lang="ts">
import type { HTMLAttributes, Ref } from 'vue'
import { useEventListener, useVModel } from '@vueuse/core'
import { computed, ref } from 'vue'

import { TooltipProvider } from '@/components/ui/tooltip'
import { readDeviceValue, SIDEBAR_COLLAPSED_KEY, writeDeviceValue } from '@/lib/sidebarPrefs'
import { cn } from '@/lib/utils'
import { useNarrowScreen } from '@/lib/viewport'
import { provideSidebarContext, SIDEBAR_KEYBOARD_SHORTCUT, SIDEBAR_WIDTH_ICON } from './utils'
import { useSidebarWidth } from './useSidebarWidth'

/**
 * 侧栏根（第 90 期，移植 BookOrbit 的 `ui/sidebar/SidebarProvider.vue`）。
 *
 * 一处**刻意的偏离**：断点用 `@/lib/viewport` 的 `NARROW_QUERY`（≤639.98px），
 * 不是上游写死的 `(max-width: 768px)`。理由见 `lib/viewport.ts` 的注释 ——
 * 768 档在本项目要继续保持两栏布局（用户口径），提到 768 是**行为变差**。
 *
 * 另外这个组件**不自己撑满屏**：上游根节点带 `min-h-svh w-full`，本项目的
 * 外壳高度/内边距/卡片间隙由 `App.vue` 用 class 传进来（见那里的调用）。
 * Provider 只管上下文与那两根 CSS 变量。
 */
const props = withDefaults(
  defineProps<{
    defaultOpen?: boolean
    open?: boolean
    class?: HTMLAttributes['class']
  }>(),
  {
    defaultOpen: undefined,
    open: undefined,
  },
)

const emits = defineEmits<{
  'update:open': [open: boolean]
}>()

const isMobile = useNarrowScreen()
const openMobile = ref(false)

const open = useVModel(props, 'open', emits, {
  // 折叠状态存**本机**（见 lib/sidebarPrefs.ts 的文件头），所以刷新后保持原样
  defaultValue: props.defaultOpen ?? !readDeviceValue<boolean>(SIDEBAR_COLLAPSED_KEY, false),
  passive: (props.open === undefined) as false,
}) as Ref<boolean>

function setOpen(value: boolean) {
  open.value = value
  writeDeviceValue(SIDEBAR_COLLAPSED_KEY, !value)
}

function setOpenMobile(value: boolean) {
  openMobile.value = value
}

function toggleSidebar() {
  return isMobile.value ? setOpenMobile(!openMobile.value) : setOpen(!open.value)
}

/**
 * ⌘/Ctrl + B 开合侧栏（上游同款）。
 *
 * 与 `App.vue` 的 ⌘K 各管各的键，不会互相吃掉 —— 两个 handler 都只看自己的
 * `event.key`，且都 `preventDefault()`（浏览器默认的 ⌘B 是加粗，在非富文本页面上
 * 没有意义，让给布局更合理）。
 */
useEventListener('keydown', (event: KeyboardEvent) => {
  if (event.key === SIDEBAR_KEYBOARD_SHORTCUT && (event.metaKey || event.ctrlKey)) {
    event.preventDefault()
    toggleSidebar()
  }
})

const state = computed<'expanded' | 'collapsed'>(() => (open.value ? 'expanded' : 'collapsed'))
const { widthPx, setWidth, minWidthPx, maxWidthPx } = useSidebarWidth()
const desktopSidebarWidth = computed(() => `${widthPx.value}px`)

provideSidebarContext({
  state,
  open,
  setOpen,
  isMobile,
  openMobile,
  setOpenMobile,
  toggleSidebar,
  widthPx,
  setWidth,
  minWidthPx,
  maxWidthPx,
})
</script>

<template>
  <div
    data-slot="sidebar-wrapper"
    :style="{
      '--sidebar-width': desktopSidebarWidth,
      '--sidebar-width-icon': SIDEBAR_WIDTH_ICON,
    }"
    :class="cn('group/sidebar-wrapper flex w-full', props.class)"
  >
    <!-- 延迟 0：折叠成图标条后悬停提示必须立刻出现才有用（等 700ms 用户早移开了） -->
    <TooltipProvider :delay-duration="0">
      <slot />
    </TooltipProvider>
  </div>
</template>
