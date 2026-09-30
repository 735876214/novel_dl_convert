<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import DashboardSettingsSheet from '@/components/dashboard/DashboardSettingsSheet.vue'
import DashboardShelfRow from '@/components/dashboard/DashboardShelfRow.vue'
import DashboardWelcome from '@/components/dashboard/DashboardWelcome.vue'
import DashboardWidgetRow from '@/components/dashboard/DashboardWidgetRow.vue'
import FirstRunNotice from '@/components/dashboard/FirstRunNotice.vue'
import Icon from '@/components/ui/Icon.vue'
import { getDashboardGreeting } from '@/lib/dashboardGreeting'
import { useAuthStore } from '@/stores/auth'
import { useDashboardStore } from '@/stores/dashboard'
import { useLibraryStore } from '@/stores/library'
import { useStatsStore } from '@/stores/stats'

/**
 * 仪表盘（第 82 期对齐 BookOrbit）：问候语行 → 部件行（横向卡片带）→ 书架行（单列/两列）。
 *
 * 与旧版的关系：
 *   · 「自定义」入口从面板自带的右下悬浮按钮**移到问候语行右侧**（与上游一致）；
 *   · 页面级入场动效：问候语行 / 部件行 / 每个书架行依次淡入上浮（错峰）；
 *   · 书架行支持单列 / 两列总布局（面板里切换，`shelfLayout`）。
 * 业务语义不动：0 库引导（FirstRunNotice）、统计失败的统一提示、
 * 全部关掉时的空态（DashboardWelcome，其中的入口文案已随 FAB 移除同步改写）。
 */
const dashboard = useDashboardStore()
const stats = useStatsStore()
const auth = useAuthStore()
const library = useLibraryStore()

// —— 问候语：按时段分段（优先账号资料里的时区），每分钟刷一次 ——
const now = ref(new Date())
let greetingTimer: number | null = null

const greetingText = computed(() => getDashboardGreeting(now.value, auth.timezone || undefined))
const displayName = computed(() => auth.display.trim())

onMounted(() => {
  greetingTimer = window.setInterval(() => {
    now.value = new Date()
  }, 60_000)
})

onUnmounted(() => {
  if (greetingTimer !== null) {
    window.clearInterval(greetingTimer)
    greetingTimer = null
  }
})

// —— 自定义入口（问候语行右侧的按钮，取代面板自带的 FAB）——
const settingsOpen = ref(false)

// —— 书架总布局：单列排布，或宽屏下两列并排 ——
const shelfLayoutClass = computed(() =>
  dashboard.shelfLayout === 'two-columns'
    ? 'grid min-w-0 items-start gap-5 xl:grid-cols-2'
    : 'space-y-5',
)
</script>

<template>
  <div>
    <main class="relative flex-none">
      <div class="space-y-5 pb-8 pt-4 sm:pr-2">
        <!-- 0 库时的首屏引导：压在部件之上，第一个看见的就是「先建书库」（第 38 期） -->
        <FirstRunNotice class="animate-fade-up" />

        <!-- 统计拉取失败：部件会各自退化成骨架/空，这里统一给一条可重试提示（第 49 期） -->
        <Card v-if="stats.error" padding="sm">
          <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
            <span>统计加载失败，部分部件显示不完整：{{ stats.error }}</span>
            <Button size="sm" variant="secondary" class="ml-auto" @click="stats.load(true)">重试</Button>
          </div>
        </Card>

        <!-- 问候语行 + 自定义入口（0 库时不显示问候，别把引导挤出首屏） -->
        <div
          v-if="!library.hasNoLibraries"
          class="animate-fade-up flex items-center justify-between gap-3 px-1"
          style="animation-delay: 40ms"
        >
          <div class="flex min-w-0 items-center gap-2">
            <Icon name="sparkle" class="h-4 w-4 shrink-0 text-primary" />
            <p
              class="truncate text-[1.05rem] font-medium leading-tight tracking-[-0.01em] text-foreground sm:text-[1.18rem]"
            >
              <span>{{ greetingText }}</span>
              <span v-if="displayName" class="ml-1 font-semibold text-primary">{{ displayName }}</span>
            </p>
          </div>
          <button
            type="button"
            aria-label="自定义仪表盘"
            title="自定义仪表盘"
            class="inline-flex shrink-0 cursor-pointer items-center gap-1.5 rounded-md border border-primary/40 bg-card/40 px-2 py-1.5 text-sm font-medium text-foreground shadow-sm transition-colors hover:border-primary/70 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:px-2.5"
            @click="settingsOpen = true"
          >
            <Icon name="sliders" class="h-3.5 w-3.5" />
            <span class="hidden sm:inline">自定义</span>
          </button>
        </div>

        <DashboardWidgetRow class="animate-fade-up" />

        <!-- 书架行：单列 / 两列（面板里切） -->
        <div v-if="dashboard.enabledShelves.length" :class="shelfLayoutClass">
          <DashboardShelfRow
            v-for="(shelf, index) in dashboard.enabledShelves"
            :key="shelf.id"
            :shelf="shelf"
            class="animate-fade-up min-w-0"
            :style="{ animationDelay: `${index * 100}ms` }"
          />
        </div>

        <DashboardWelcome v-if="dashboard.isEmpty" />
      </div>
    </main>

    <DashboardSettingsSheet v-model:open="settingsOpen" />
  </div>
</template>
