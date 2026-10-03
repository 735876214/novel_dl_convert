<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import AppearanceMenu from '@/components/AppearanceMenu.vue'
import AppMoreMenu from '@/components/AppMoreMenu.vue'
import NotificationBell from '@/components/NotificationBell.vue'
import TaskFlyout from '@/components/TaskFlyout.vue'
import UserMenu from '@/components/UserMenu.vue'
import Icon from '@/components/ui/Icon.vue'
import IconButton from '@/components/ui/IconButton.vue'
import { SidebarTrigger } from '@/components/ui/sidebar'
import { useSettingsConfig } from '@/composables/useSettingsConfig'
import { useNarrowScreen } from '@/lib/viewport'
import { usePrefSyncStore } from '@/stores/prefSync'

/**
 * 顶栏（第 65 期扩成「全站入口行」）。
 *
 * 侧栏那七项（任务中心 / 工具 / 数据统计 / 阅读记录 / 阅读活动 / 通知中心 / 成就）
 * 第 65 期搬到了**这里**，与原有的铃铛 / 数据统计 / 任务面板 / 月亮 / 齿轮 / 头像
 * **并排**；侧栏不再保留它们（用户口径：「只留顶栏」）。重复的两项按用户口径合并
 * 去重：通知沿用既有的铃铛浮层、数据统计只留一个按钮、任务面板从抽屉改成浮层。
 *
 * 图标沿用它们在侧栏时的同一个 `icon`（如「工具」是 `wrench`、「阅读记录」是
 * `clock`）—— 同一件事在两个位置长得一样，用户才认得出是同一条去处的搬迁。
 *
 * `ICON_BTN` 那串类原先在本文件、`NotificationBell.vue`、`AppearanceMenu.vue`
 * 各有一份，本期统一收进 `ui/IconButton.vue`（否则再加四个入口就是七份复制）。
 *
 * ⚠️ 第 90 期：最左那颗「切换侧边栏」按钮换成 `ui/sidebar` 的 `SidebarTrigger`，
 * 它自己从 `useSidebar()` 拿状态，不再经 `useUiStore` —— 那个 store 里的
 * `sidebarCollapsed` / `toggleSidebar` 也随之删掉了（单一真值源）。
 *
 * ⚠️ 第 91 期：≤640px 时上树那七项收进 `AppMoreMenu`（用户口径「收进『更多』菜单」）。
 * 「收进」≠「隐藏」—— 它们是唯一入口，所以是换容器、不是收窄功能。
 * 宽屏那一行**一个字都没动**（顺序、图标、门控全按原样）。
 */
const router = useRouter()
const sync = usePrefSyncStore()
const { cfg, loadConfig } = useSettingsConfig()

/**
 * 成就门控（从 `AppSidebar.vue` 原样搬来，判据与口径一字不改）：
 * 上游语义是「关闭后不显示成就相关界面」。
 *
 * 静默加载：读配置失败时**不弹提示**，并按「启用」处理 ——
 * 因为读不到配置就把入口藏起来，用户会以为功能没了，比多显示一个入口更糟。
 * 关闭时整块**不渲染**（不灰置、不占位：灰置等于承认「本该有但不给你」）。
 */
const achievementsEnabled = computed(() => cfg.value?.achievements?.enabled !== false)

/**
 * 窄屏（第 91 期，用户口径：图标行**收进「更多」菜单**）。
 *
 * 判据用 `lib/viewport.ts` 的 `useNarrowScreen()` —— 全站断点**唯一真值源**，
 * 不许在这里写第二份 `matchMedia('(max-width: 639.98px)')`（改断点时必然漏一处）。
 *
 * 为什么是 `v-if` 而不是 CSS 隐藏：菜单面板 `Teleport` 到 `body`，CSS 够不着它；
 * 硬藏就得再写一套「触发器与面板都藏」的规则 ⇒ JS/CSS 两份断点。
 * `matchMedia` 不可用的环境按**宽屏**处理（与侧栏同一兜底：宁可多显示一排按钮，
 * 也不要把唯一入口藏进一个打不开的面板里）。
 */
const narrow = useNarrowScreen()

/** 应用级入口：注册偏好变更回调并启动同步（幂等）。
 *
 * 放在顶栏而不是 App.vue：未登录时 App 渲染的是登录门禁、顶栏不挂载，
 * 所以这里的启动时机天然是「已登录」，不会白跑一次注定 401 的 boot。
 */
onMounted(() => {
  sync.init()
  void loadConfig(false, true)
})

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
</script>

<template>
  <header class="flex h-14 shrink-0 items-center gap-3.5 border-b border-border px-[var(--shell-content-gutter)]">
    <!-- 侧栏开合（第 90 期）：换成上游的 `SidebarTrigger`，带悬停提示与
         `aria-expanded`；⌘/Ctrl+B 是同一个动作的键盘入口（见 SidebarProvider）。
         样式与替换前那颗按钮**逐字一致**（32×32 方形圆角）—— 见该组件的注释。 -->
    <SidebarTrigger />

    <!-- `min-w-0`：flex 子项默认 `min-width: auto`，窄屏时它**不肯让位**，
         于是溢出部分被外壳的 `overflow-x: clip` 静默裁掉（最先消失的是最右端的头像）。
         加上它，压力先落在搜索框上（它缩得下去），右侧图标行保住。
         ⚠️ 第 90 期：窄屏兜底已经**不靠这一条**了（≤640px 时侧栏是抽屉、不再占位），
         但 640–900px 这段搜索框仍会挤右侧图标行，所以这条留着。 -->
    <div class="relative max-w-[35rem] min-w-0 flex-1">
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
        class="h-9 w-full rounded-md border border-transparent bg-muted pl-9 text-[13px] text-foreground outline-none transition-[border-color,box-shadow,background-color] placeholder:text-muted-foreground focus:border-ring focus:bg-card focus:shadow-[0_0_0_3px_color-mix(in_oklab,var(--ring)_22%,transparent)]"
        :class="narrow ? 'pr-3' : 'pr-[4.375rem]'"
        @keydown="onSearchKeydown"
      >
      <!-- `⌘K` 是**徽标不是快捷键说明**（真正的快捷键在 `App.vue` 的 keydown 里）：
           窄屏既没有 ⌘ 键、也用不着那截内边距，一并收掉，把宽度让给输入本身。 -->
      <span
        v-if="!narrow"
        class="pointer-events-none absolute top-1/2 right-2.5 -translate-y-1/2 rounded-sm border border-border bg-card px-1.5 py-px text-[10.5px] text-muted-foreground"
      >
        ⌘K
      </span>
    </div>

    <div class="ml-auto flex items-center gap-[0.3125rem]">
      <!-- 其他设备更新过偏好、而本机也有未推送改动（第 56 期）：**只提示不覆盖**，
           点进去显式选择保留哪边 -->
      <button
        v-if="sync.conflict"
        type="button"
        class="flex h-7 cursor-pointer items-center rounded-full bg-amber-500/15 px-2.5 text-[11.5px] text-amber-600 transition-colors hover:bg-amber-500/25 dark:text-amber-400"
        title="另一台设备更新了偏好，而本机也有未同步的改动。点此选择保留哪边（不会自动覆盖）"
        @click="router.push('/settings/reader/general')"
      >
        偏好有更新
      </button>
      <!-- 刚静默同步了其他设备的偏好（8 秒自隐） -->
      <span
        v-else-if="sync.remoteFresh"
        class="flex h-7 items-center rounded-full bg-primary/10 px-2.5 text-[11.5px] text-primary"
      >
        已同步其他设备偏好
      </span>

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
      <!-- 通知：浮层 + 未读角标（与整页 /notify 同数据源）。**窄屏也不收进「更多」**：
           角标是它存在的意义，藏进面板就等于没有提示了。 -->
      <NotificationBell />

      <!--
        窄屏：下面这七项**换地方**（不是隐藏）—— 第 65 期已从侧栏撤掉，顶栏是它们的
        唯一入口，被 `overflow-x: clip` 裁掉就等于「窄屏进不了设置」。
        「更多」放在这一排的**起始位置**（通知之后），与它取代的那几项同位。
      -->
      <AppMoreMenu v-if="narrow" :achievements-enabled="achievementsEnabled" />

      <!--
        ⚠️ 宽屏的这七项被拆成**两段** `v-if`，因为 `AppearanceMenu` 夹在它们中间
        （第 65 期的顺序：数据统计 / 任务 / 工具 / 阅读记录 / 阅读活动 / 成就 / 外观 / 设置）。
        合成一段就得把外观挪到设置后面 —— 那是**没要求过的视觉改动**，且会让
        `AppHeader.spec.ts` 的顺序断言改成「配合实现」，把哨兵变成橡皮图章。
      -->
      <template v-if="!narrow">
        <IconButton label="数据统计" @click="router.push('/stats')">
          <Icon name="chart" class="h-[17px] w-[17px]" />
        </IconButton>
        <!-- 任务：第 65 期从「右侧滑出抽屉」改成与通知同款浮层（用户口径 2） -->
        <TaskFlyout />
        <IconButton label="工具" @click="router.push('/tools')">
          <Icon name="wrench" class="h-[17px] w-[17px]" />
        </IconButton>
        <IconButton label="阅读记录" @click="router.push('/log')">
          <Icon name="clock" class="h-[17px] w-[17px]" />
        </IconButton>
        <IconButton label="阅读活动" @click="router.push('/reading-activity')">
          <Icon name="note" class="h-[17px] w-[17px]" />
        </IconButton>
        <!-- 成就：开关关掉时**整块不渲染**（不灰置、不占位）—— 与侧栏原来的门控同一个判据 -->
        <IconButton v-if="achievementsEnabled" label="成就" @click="router.push('/achievements')">
          <Icon name="star" class="h-[17px] w-[17px]" />
        </IconButton>
      </template>

      <AppearanceMenu />

      <template v-if="!narrow">
        <IconButton label="设置" @click="router.push('/settings')">
          <Icon name="settings" class="h-[17px] w-[17px]" />
        </IconButton>
      </template>

      <UserMenu />
    </div>
  </header>
</template>
