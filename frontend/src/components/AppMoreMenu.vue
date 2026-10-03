<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import DropdownMenu from '@/components/ui/DropdownMenu.vue'
import Icon from '@/components/ui/Icon.vue'
import IconButton from '@/components/ui/IconButton.vue'
import { useTasksStore } from '@/stores/tasks'

/**
 * 窄屏顶栏的「更多」菜单（第 91 期）。
 *
 * ## 为什么必须有它
 *
 * 顶栏右侧那一行图标在 360 档宽约 375px，而内容盒只有 334px ——
 * 溢出部分被外壳的 `overflow-x: clip` **静默裁掉**（最先消失的是最右端的头像，
 * 接着是设置、外观）。第 90 期只修了侧栏那一半（窄屏改抽屉），顶栏这一半留着。
 *
 * 裁掉的不只是「少一个按钮」：这七项（数据统计 / 任务 / 工具 / 阅读记录 /
 * 阅读活动 / 成就 / 设置）第 65 期已从侧栏**撤掉**，顶栏是它们的**唯一入口** ——
 * 被裁掉等于「窄屏用户进不了设置」。所以这里不是「隐藏」，是**换地方**。
 *
 * ## 两件刻意的选择
 *
 * 1. **判据用 `useNarrowScreen()` 做 `v-if`，不用纯 CSS 隐藏**。面板是 Teleport 到
 *    `body` 的，CSS 选择器够不着它；硬用 CSS 就得再写一套「触发器藏、面板也藏」
 *    的规则，等于把断点抄成 JS/CSS 两份（`lib/viewport.ts` 的注释里正是这条禁令）。
 * 2. **复用 `ui/DropdownMenu.vue`**，不新写浮层：Teleport、自动上下翻转、
 *    滚动/缩放即关、`@click.stop` 都已经在里面了。本组件只提供条目表与点击行为。
 *
 * ## 留在窄屏外的几项（为什么不进来）
 *
 * `NotificationBell`（有未读角标，角标藏进菜单就失去意义）、`AppearanceMenu`
 * （一次点击的开关，进菜单反而变两步）、`UserMenu` 与侧栏开合按钮（高频）。
 */

const props = defineProps<{
  /**
   * 成就门控（判据与 `AppHeader.vue` / 侧栏一字不改：读不到配置按启用处理，
   * 关闭时**整块不渲染** —— 不灰置、不占位）。
   */
  achievementsEnabled: boolean
}>()

const router = useRouter()
const tasks = useTasksStore()

const open = ref(false)

interface Entry {
  label: string
  icon: string
  path: string
  /** 只用于「任务」：运行中 + 排队中（与 `TaskFlyout` 的角标同源） */
  badge?: number
}

/**
 * 条目表是**唯一真值源**：渲染、键盘序、spec 断言的入口数全从这里派生 ——
 * 加一项只许改这一处（`v-if` 散在模板里就必然漏一处）。
 * 顺序沿用宽屏那一行的从左到右，用户换到窄屏时不必重新找位置。
 */
const entries = computed<Entry[]>(() => [
  { label: '数据统计', icon: 'chart', path: '/stats' },
  { label: '任务', icon: 'task', path: '/tasks', badge: tasks.runningCount },
  { label: '工具', icon: 'wrench', path: '/tools' },
  { label: '阅读记录', icon: 'clock', path: '/log' },
  { label: '阅读活动', icon: 'note', path: '/reading-activity' },
  // 成就：关闭时**整项不出现**（不是灰置、不是占位）
  ...(props.achievementsEnabled
    ? [{ label: '成就', icon: 'star', path: '/achievements' }]
    : []),
  { label: '设置', icon: 'settings', path: '/settings' },
])

/** 点条目：**先关面板再跳** —— 面板是 Teleport 到 body 的，不关会浮在新页面上。 */
function go(path: string): void {
  open.value = false
  router.push(path)
}
</script>

<template>
  <!--
    `data-more-menu-trigger` 是给 spec 的钩子（照 `[data-icon-button]` 的先例）：
    它随 attrs 落到本组件的根元素上，spec 里查 `[data-more-menu-trigger] > button`。
    不去动 `DropdownMenu.vue` 的 `data-book-menu*` —— 那是 `BookActionsMenu` 的契约。
  -->
  <DropdownMenu
    :open="open"
    data-more-menu-trigger
    @toggle="open = !open"
    @close="open = false"
  >
    <template #trigger>
      <!-- 角标 = 任务角标**上提**到分组触发器：`TaskFlyout` 是这七项里唯一带角标的，
           窄屏若不给信号，「有任务在跑」就彻底看不见了（它只在菜单里、得先点开）。 -->
      <IconButton
        label="更多"
        tooltip="更多入口"
        :active="open"
        :expanded="open"
        :badge="tasks.runningCount"
      >
        <Icon name="more" class="h-[17px] w-[17px]" />
      </IconButton>
    </template>

    <template #panel>
      <button
        v-for="e in entries"
        :key="e.path"
        type="button"
        role="menuitem"
        class="flex w-full cursor-pointer items-center gap-2 px-3 py-2 text-left text-[12.5px] text-foreground transition-colors hover:bg-muted/60"
        @click="go(e.path)"
      >
        <Icon :name="e.icon" class="h-4 w-4 text-muted-foreground" />
        {{ e.label }}
        <span
          v-if="e.badge"
          class="ml-auto min-w-[1rem] rounded-full bg-destructive px-1 text-center text-[9.5px] leading-4 font-semibold text-white tabular-nums"
        >
          {{ e.badge > 99 ? '99+' : e.badge }}
        </span>
      </button>
    </template>
  </DropdownMenu>
</template>
