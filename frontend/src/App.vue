<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { RouterView } from 'vue-router'

import AppHeader from '@/components/AppHeader.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import AppToast from '@/components/AppToast.vue'
import TaskDrawer from '@/components/TaskDrawer.vue'
import { useTasksStore } from '@/stores/tasks'
import { useThemeStore } from '@/stores/theme'
import { useUiStore } from '@/stores/ui'

const ui = useUiStore()
const tasks = useTasksStore()
const theme = useThemeStore()

/** ⌘K / Ctrl+K 聚焦全局搜索；Esc 关闭任务抽屉 */
function onKeydown(e: KeyboardEvent): void {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    document.getElementById('globalSearch')?.focus()
    return
  }
  if (e.key === 'Escape') ui.setDrawer(false)
}

onMounted(() => {
  // 首屏预置脚本已在 index.html 内联执行；这里再跑一次是为了覆盖
  //「系统深浅色在脚本之后变化」的情况，并挂上 change 监听。
  theme.applyClasses()
  theme.watchSystem()
  tasks.startTicker()
  document.addEventListener('keydown', onKeydown)
})

onUnmounted(() => {
  tasks.stopTicker()
  document.removeEventListener('keydown', onKeydown)
})
</script>

<template>
  <!-- 卡片式外壳：三块浮起卡片，块间一个 --shell-gap -->
  <div class="flex h-[100dvh] gap-[var(--shell-gap)] overflow-hidden p-[var(--shell-gap)]">
    <AppSidebar />

    <div class="flex min-w-0 flex-1 flex-col overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-xs backdrop-blur-md backdrop-saturate-150">
      <AppHeader />
      <main class="min-h-0 flex-1 overflow-y-auto p-[var(--shell-content-gutter)]">
        <RouterView />
      </main>
    </div>

    <TaskDrawer />
  </div>

  <div
    v-if="ui.drawerOpen"
    class="fixed inset-0 z-35 bg-black/28 backdrop-blur-[2px]"
    @click="ui.setDrawer(false)"
  />

  <AppToast />
</template>
