<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { RouterView } from 'vue-router'

import AppHeader from '@/components/AppHeader.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import AppToast from '@/components/AppToast.vue'
import TaskDrawer from '@/components/TaskDrawer.vue'
import LoginGate from '@/components/LoginGate.vue'
import { useTasksStore } from '@/stores/tasks'
import { useThemeStore } from '@/stores/theme'
import { useUiStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'

const ui = useUiStore()
const tasks = useTasksStore()
const theme = useThemeStore()
const auth = useAuthStore()
const showLogin = ref(false)

/** ⌘K / Ctrl+K 聚焦全局搜索；Esc 关闭任务抽屉 */
function onKeydown(e: KeyboardEvent): void {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    document.getElementById('globalSearch')?.focus()
    return
  }
  if (e.key === 'Escape') ui.setDrawer(false)
}

function onUnauthorized(): void {
  showLogin.value = true
}

onMounted(async () => {
  // 首屏预置脚本已在 index.html 内联执行；这里再跑一次是为了覆盖
  //「系统深浅色在脚本之后变化」的情况，并挂上 change 监听。
  theme.applyClasses()
  theme.watchSystem()
  // 任务数据来自服务端真实任务表（不是本地种子）；只在有未结束任务时才轮询，
  // 空闲时自动停止 —— 见 stores/tasks.ts。
  void tasks.refresh()
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('nf-unauthorized', onUnauthorized)
  // 鉴权初始化：有 token 则校验，无则直接弹登录门禁
  await auth.init()
  showLogin.value = !auth.authenticated
})

onUnmounted(() => {
  tasks.stopPolling()
  document.removeEventListener('keydown', onKeydown)
  window.removeEventListener('nf-unauthorized', onUnauthorized)
})
</script>

<template>
  <LoginGate v-if="showLogin" @authed="showLogin = false" />

  <!-- 卡片式外壳：三块浮起卡片，块间一个 --shell-gap -->
  <div v-else class="flex h-[100dvh] gap-[var(--shell-gap)] overflow-hidden p-[var(--shell-gap)]">
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
