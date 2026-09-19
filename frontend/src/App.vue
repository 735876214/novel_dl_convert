<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import AppHeader from '@/components/AppHeader.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import SettingsSidebar from '@/components/SettingsSidebar.vue'
import AppToast from '@/components/AppToast.vue'
import TaskDrawer from '@/components/TaskDrawer.vue'
import LoginGate from '@/components/LoginGate.vue'
import MigrationGateDialog from '@/components/MigrationGateDialog.vue'
import { useTasksStore } from '@/stores/tasks'
import { useThemeStore } from '@/stores/theme'
import { useUiStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { useSettingsSearch } from '@/composables/useSettingsSearch'

const ui = useUiStore()
const tasks = useTasksStore()
const theme = useThemeStore()
const auth = useAuthStore()
const route = useRoute()
const showLogin = ref(false)

/** 设置路由下，左列渲染设置导航而非主侧栏 */
const isSettingsRoute = computed(() => route.path.startsWith('/settings'))
const settingsSearch = useSettingsSearch()

/**
 * ⌘K / Ctrl+K 聚焦全局搜索；Esc 关闭任务抽屉。
 *
 * 设置区例外：那里由 `SettingsSearchPanel` 接管（上游同样是「设置区搜设置项」），
 * 否则一次按键会同时聚焦顶栏搜索框并弹出设置搜索浮层。
 */
function onKeydown(e: KeyboardEvent): void {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    if (isSettingsRoute.value) settingsSearch.togglePanel()
    else document.getElementById('globalSearch')?.focus()
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
    <SettingsSidebar v-if="isSettingsRoute" />
    <AppSidebar v-else />

    <div class="flex min-w-0 flex-1 flex-col overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-xs backdrop-blur-md backdrop-saturate-150">
      <AppHeader />
      <main class="min-h-0 flex-1 overflow-y-auto p-[var(--shell-content-gutter)]">
        <RouterView />
      </main>
    </div>

    <TaskDrawer />
  </div>

  <!-- 首次「按格式归库」的阻塞确认（第 10 期）：登录后自己判断要不要弹 -->
  <MigrationGateDialog v-if="!showLogin" />

  <div
    v-if="ui.drawerOpen"
    class="fixed inset-0 z-35 bg-black/28 backdrop-blur-[2px]"
    @click="ui.setDrawer(false)"
  />

  <AppToast />
</template>
