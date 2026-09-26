<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import AppHeader from '@/components/AppHeader.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import SettingsSidebar from '@/components/SettingsSidebar.vue'
import AppToast from '@/components/AppToast.vue'
import TaskDrawer from '@/components/TaskDrawer.vue'
import LoginGate from '@/components/LoginGate.vue'
import MigrationGateDialog from '@/components/MigrationGateDialog.vue'
import GuidedTourModal from '@/components/settings/GuidedTourModal.vue'
import LibraryWizard from '@/components/tools/LibraryWizard.vue'
import { useTasksStore } from '@/stores/tasks'
import { useThemeStore } from '@/stores/theme'
import { useUiStore } from '@/stores/ui'
import { useAuthStore } from '@/stores/auth'
import { useLibraryStore } from '@/stores/library'
import { useLibraryWizardStore } from '@/stores/libraryWizard'
import { useSettingsSearch } from '@/composables/useSettingsSearch'

const ui = useUiStore()
const tasks = useTasksStore()
const theme = useThemeStore()
const auth = useAuthStore()
const library = useLibraryStore()
const wizard = useLibraryWizardStore()
const route = useRoute()
const showLogin = ref(false)
const showTour = ref(false)

/**
 * 首次使用引导（第 38 期）：**一个书库都没有**时弹一次。
 *
 * 「弹过就算看过」——打开即写标记，不按「是否点完」记。理由：引导里那套步骤
 * 用户可以先跳过、事后再从「设置 → 个人资料 → 新手引导」重放；反过来若按
 *「没看完就再弹」，每次刷新都糊一个弹窗，那才是打扰。**常驻指引不依赖它** ——
 * 仪表盘提示条、书架空态、侧栏与书库管理页各自都会说「先建书库」。
 */
const TOUR_SEEN_KEY = 'nf_tour_seen'

function markTourSeen(): void {
  try {
    localStorage.setItem(TOUR_SEEN_KEY, '1')
  } catch {
    /* 隐私模式下写不了：退化成「每次都弹」，不因此崩掉首屏 */
  }
}

function tourSeen(): boolean {
  try {
    return localStorage.getItem(TOUR_SEEN_KEY) === '1'
  } catch {
    // 读不到就**当已看过**：宁可少弹一次，也不要在读不了存储的环境里反复弹
    return true
  }
}

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

  // 首次使用引导：只认 `hasNoLibraries`（= **成功拉到且确实是 0 个**），拉取失败时不弹
  await library.loadLibraries()
})

/**
 * 首次使用引导的触发**必须是被动的**，不能在 `onMounted` 里采样一次。
 *
 * ⚠️ App 在**登录之前**就挂载好了（登录是覆盖层 `LoginGate`，不是路由），
 * 那时 `loadLibraries()` 拿到 401、`librariesLoaded` 仍是 false，于是
 * 「0 库」这个判断当时**根本不成立**；等用户登进来，`onMounted` 早已跑完，
 * 不会再执行第二次 —— 实测就是这个结果：引导一次都没弹过（`nf_tour_seen` 始终为空）。
 *
 * 所以改成盯 `hasNoLibraries`：它由「成功取回且确实为 0」定义，无论书库是
 * 登录后才拉到的、还是用户把最后一个库删掉才变成 0 的，都会在**成立的那一刻**触发。
 */
watch(
  () => library.hasNoLibraries,
  (noLibraries) => {
    if (noLibraries && !showLogin.value && !tourSeen()) {
      showTour.value = true
      markTourSeen()
    }
  },
  { immediate: true },
)

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

  <!-- 首次使用引导（第 38 期）：0 个书库时弹一次，见上面 showTour 的说明 -->
  <GuidedTourModal v-model:open="showTour" />

  <!-- 「新增书库」全局向导（第 55 期）：各入口就地弹窗、不再跳设置页。
       ⚠️ 全局只挂这一份 —— LibraryWizard 是 z-50 浮层，多处各自挂会叠两层
       关不掉（LibrariesView 第 40 期注释的同一条互斥约定，收拢到这里后天然只有一层）。 -->
  <LibraryWizard
    v-if="wizard.open"
    :types="wizard.types"
    :source-roots="wizard.sourceRoots"
    :libs="wizard.libs"
    @close="wizard.close()"
    @created="wizard.created"
  />

  <div
    v-if="ui.drawerOpen"
    class="fixed inset-0 z-35 bg-black/28 backdrop-blur-[2px]"
    @click="ui.setDrawer(false)"
  />

  <AppToast />
</template>
