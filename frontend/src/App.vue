<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { RouterView, useRoute } from 'vue-router'

import AppHeader from '@/components/AppHeader.vue'
import AppSidebar from '@/components/AppSidebar.vue'
import SettingsSidebar from '@/components/SettingsSidebar.vue'
import { SidebarInset, SidebarProvider } from '@/components/ui/sidebar'
import AppToast from '@/components/AppToast.vue'
import LoginGate from '@/components/LoginGate.vue'
import GuidedTourModal from '@/components/settings/GuidedTourModal.vue'
import LibraryWizard from '@/components/tools/LibraryWizard.vue'
import { useTasksStore } from '@/stores/tasks'
import { useThemeStore } from '@/stores/theme'
import { useAuthStore } from '@/stores/auth'
import { useLibraryStore } from '@/stores/library'
import { useLibraryWizardStore } from '@/stores/libraryWizard'
import { useSettingsSearch } from '@/composables/useSettingsSearch'

// ⚠️ 第 65 期：`useUiStore` 与 `ui` 已从这里删掉 —— 它在本文件唯一的用途是
// 「Esc 关任务抽屉」，而抽屉已改成顶栏浮层（`TaskFlyout.vue`），Esc 由浮层自管。
const tasks = useTasksStore()
const theme = useThemeStore()
const auth = useAuthStore()
const library = useLibraryStore()
const wizard = useLibraryWizardStore()
const route = useRoute()

/**
 * 登录门禁是否可见。
 *
 * ⚠️ 第 91 期：初值不再是写死的 `false`，而是**本地有没有 token**
 * （`auth.authenticated` 在 store 构造时就**同步**读好了 `localStorage`，见
 * `stores/auth.ts` 的 `token` 初始化）。理由：初值写死 `false` ⇒ **未登录的访客
 * 也会先渲染一次外壳**，外壳里的 store 各自开拉，白发一轮注定 401 的探测请求
 * （600 本库实测：`collections` / `libraries` / `smart-scopes` / `features` /
 * `browse-counts` / `notifications` / `prefs/*` / `config` 各被调 **2 次**，
 * 多出来的那次全是未带 token 的 401 探测，每个约 337 B）。
 *
 * 用本地 token 做初值是**同步且零延迟**的：已登录用户的冷启动**不会**因此多等
 * 一次 `api.me()`（那正是第 68 期权衡里被否掉的方案）。真正的裁决仍是下面
 * `auth.init()` 的结果 —— token 过期 / 被吊销时它会把门禁翻回来。
 */
const showLogin = ref(!auth.authenticated)
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

/**
 * 沉浸路由（第 108 期，用户口径「阅读时除阅读界面外其他栏自动隐藏」）。
 *
 * `/read/:id` 与 `/online/:id` 是**同一个** `ReaderView`（两条路由各自一份现场，见
 * `router/index.ts`），它们进入时**整块外壳都不渲染**：侧栏、顶栏、`SidebarInset`
 * 一起让位，整屏交给正文。退出阅读的唯一路径是阅读器工具栏那颗「返回详情」
 * （阅读器的工具栏自带返回 / 目录 / 设置）—— 所以这里不需要再留第二条退路。
 *
 * ⚠️ 按 `route.name` 判而不是路径前缀：路由表里是具名路由，改名时这里会**一起**失效
 * （路径前缀写错则静默不生效）。`/listen/:id`（听书）**刻意不在内**：那是播放器
 * 不是阅读界面，用户口径说的是阅读 —— 要收进去只需在这里加一个名字。
 */
const isImmersiveRoute = computed(() => route.name === 'read' || route.name === 'online')
const settingsSearch = useSettingsSearch()

/**
 * ⌘K / Ctrl+K 聚焦全局搜索。
 *
 * 设置区例外：那里由 `SettingsSearchPanel` 接管（上游同样是「设置区搜设置项」），
 * 否则一次按键会同时聚焦顶栏搜索框并弹出设置搜索浮层。
 *
 * 第 65 期去掉了这里原有的「Esc 关闭任务抽屉」：抽屉改成顶栏浮层后，
 * 通知 / 任务 / 外观 / 账户四个浮层各自监听 Esc，全局再抢一次按键是重复的。
 */
function onKeydown(e: KeyboardEvent): void {
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault()
    if (isSettingsRoute.value) settingsSearch.togglePanel()
    else document.getElementById('globalSearch')?.focus()
  }
}

function onUnauthorized(): void {
  showLogin.value = true
}

/**
 * 外壳级数据的首拉（任务 + 书库）。**必须在「已裁决已登录」之后调**。
 *
 * ⚠️ 第 91 期：这两处请求是 **App.vue 自己的**，不在模板 `v-if/v-else` 覆盖范围内
 * —— 只 gate 渲染拦不住它们（那正是「改了 `showLogin` 初值还剩 2 个 401」的原因）。
 * 所以它们被收进这个函数，只在已登录时执行。
 */
async function bootstrapShell(): Promise<void> {
  // 任务数据来自服务端真实任务表（不是本地种子）；只在有未结束任务时才轮询，
  // 空闲时自动停止 —— 见 stores/tasks.ts。
  void tasks.refresh()
  // 首次使用引导：只认 `hasNoLibraries`（= **成功拉到且确实是 0 个**），拉取失败时不弹
  await library.loadLibraries()
}

/**
 * 登录门禁的 `@authed`：关掉门禁**并补跑一次外壳首拉**。
 *
 * ⚠️ 漏掉这次复跑不会报错 —— 表现只是「登录进来后任务栏永远空着、书库列表不刷新」，
 * 因为 `onMounted` 早就跑完了，不会再执行第二遍。
 */
function onAuthed(): void {
  showLogin.value = false
  void bootstrapShell()
}

onMounted(async () => {
  // 首屏预置脚本已在 index.html 内联执行；这里再跑一次是为了覆盖
  //「系统深浅色在脚本之后变化」的情况，并挂上 change 监听。
  theme.applyClasses()
  theme.watchSystem()
  document.addEventListener('keydown', onKeydown)
  window.addEventListener('nf-unauthorized', onUnauthorized)
  // 鉴权初始化：有 token 则校验，无则直接弹登录门禁
  await auth.init()
  showLogin.value = !auth.authenticated

  // 已裁决为「已登录」（本地有 token 且校验通过）才拉外壳数据；
  // 未登录时门禁就是唯一界面，这些请求注定 401，一个都不该发。
  if (!showLogin.value) await bootstrapShell()
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
 * 登录后才拉到的（第 91 期起这次拉取由 `onAuthed` → `bootstrapShell()` 补跑）、
 * 还是用户把最后一个库删掉才变成 0 的，都会在**成立的那一刻**触发。
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
  <LoginGate v-if="showLogin" @authed="onAuthed" />

  <!--
    阅读器：整屏沉浸（第 108 期，用户口径）。
    与下面那层外壳是**互斥**的两条渲染路径（`v-else-if`）—— 不是把外壳藏起来，而是
    根本不渲染（藏起来仍会拉数据、仍占 DOM，还会留下一条 ⌘B 能掀开的缝）。
    高度用 `100dvh`（移动端地址栏收放时 `vh` 会跳），内边距沿用同一个
    `--shell-content-gutter`，与阅读时在外壳里的观感对齐。
  -->
  <div
    v-else-if="isImmersiveRoute"
    class="flex h-[100dvh] min-h-0 flex-col overflow-hidden p-[var(--shell-content-gutter)]"
  >
    <RouterView />
  </div>

  <!--
    卡片式外壳：两块浮起卡片（侧栏 + 内容），块间一个 --shell-gap。
    第 90 期把这一层换成 `SidebarProvider`：它在原样式之上多给两件事 ——
    ① 把折叠态 / 宽度 / 窄屏判定下发成 provide/inject 上下文（`useSidebar()`）；
    ② 在外壳根节点挂 `--sidebar-width` / `--sidebar-width-icon` 两根变量，
       侧栏卡片与内容区都从这两根变量取宽度，所以拖宽时**两边同一帧一起动**。
    高度 / 内边距 / 卡片间隙仍然写在 class 里，由这里（而不是 Provider）说了算。
  -->
  <SidebarProvider v-else class="h-[100dvh] gap-[var(--shell-gap)] overflow-hidden p-[var(--shell-gap)]">
    <!-- 任务面板（第 65 期）：从这一层的 `<TaskDrawer />` 搬进了顶栏那一行
         （`AppHeader.vue` 里的 `<TaskFlyout />`），随之删掉下面的全屏遮罩。 -->
    <SettingsSidebar v-if="isSettingsRoute" />
    <AppSidebar v-else />

    <SidebarInset>
      <AppHeader />
      <main class="min-h-0 flex-1 overflow-y-auto p-[var(--shell-content-gutter)]">
        <RouterView />
      </main>
    </SidebarInset>
  </SidebarProvider>

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

  <AppToast />
</template>
