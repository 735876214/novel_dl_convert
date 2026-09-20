<script setup lang="ts">
import { computed } from 'vue'

import ChartEmptyState from '@/components/charts/ChartEmptyState.vue'
import Icon from '@/components/ui/Icon.vue'
import { useChartTheme } from '@/lib/charts'

/**
 * 图表卡容器（照搬上游 `ChartCard.vue`）：标题栏（图标底块 + 标题 + 右侧控件）
 * + 内容区（加载 / 出错 / 空态 / 图表四选一）+ 底部脚注。
 *
 * 两处与本项目对齐的改动：
 *
 * 1. **图标底色取 `chartPalette()`，不另立一套色相偏移**。上游用
 *    `ICON_HUE_OFFSETS=[0,45,90,…]`（`ChartCard.vue:23`）配相对颜色语法；本项目
 *    调色板已是「强调色 + 色相偏移」的 10 色，直接取同一份，图标与图表序列同色系，
 *    也免得第二张偏移表跟 `charts.ts` 漂移。
 * 2. **去掉拖拽把手**。上游靠它给 `vue-draggable-plus` 排序；本项目不引拖拽库，
 *    Configure 用上移/下移按钮，画一个拖不动的把手就是假交互。
 *
 * 外层类串与上游逐字相同（`bg-card` / `border-border` / `rounded-lg` / `shadow-sm` /
 * 悬浮微抬），不新造卡片样式。
 */
const props = withDefaults(
  defineProps<{
    title: string
    /** 图标名（本项目的 `lib/icons.ts` 常量表） */
    icon?: string
    /** 调色板序号：决定图标底色，一般传该图在列表中的位置 */
    colorIndex?: number
    loading?: boolean
    error?: boolean
    empty?: boolean
    emptyTitle?: string
    emptyDescription?: string
    /** 底部脚注：口径说明用（如「N 本没有页数记录，未计入」） */
    note?: string
  }>(),
  {
    icon: 'chart',
    colorIndex: 0,
    loading: false,
    error: false,
    empty: false,
    emptyTitle: '暂无数据',
    emptyDescription: '',
    note: '',
  },
)

const { palette } = useChartTheme()

const iconStyle = computed(() => {
  const list = palette.value
  const color = list.length ? list[props.colorIndex % list.length] : 'var(--primary)'
  // 底色是主色的 15% 混合 —— 与上游同一种做法（`ChartCard.vue:28`）
  return { backgroundColor: `color-mix(in oklch, ${color} 15%, transparent)`, color }
})
</script>

<template>
  <div
    class="bg-card text-card-foreground flex h-full min-h-[320px] flex-col overflow-hidden rounded-lg border border-border shadow-sm transition-all duration-200 hover:-translate-y-0.5 hover:shadow-md md:min-h-0"
  >
    <div class="flex min-h-0 flex-1 flex-col p-4">
      <div class="mb-3 flex items-center justify-between gap-2 border-b border-border pb-3">
        <div class="flex items-center gap-2.5">
          <div class="shrink-0 rounded-md p-2" :style="iconStyle">
            <Icon :name="icon" class="size-4" />
          </div>
          <p class="text-foreground text-sm font-semibold">{{ title }}</p>
        </div>
        <div class="flex items-center gap-2">
          <slot name="controls" />
        </div>
      </div>

      <div class="min-h-0 flex-1">
        <div v-if="loading" class="h-full w-full animate-pulse rounded-lg bg-muted" />

        <div
          v-else-if="error"
          class="text-muted-foreground flex h-full flex-col items-center justify-center gap-2"
        >
          <Icon name="alert" class="size-6" />
          <p class="text-sm">数据加载失败</p>
        </div>

        <ChartEmptyState
          v-else-if="empty"
          :icon="icon"
          :title="emptyTitle"
          :description="emptyDescription"
        />

        <slot v-else />
      </div>

      <p v-if="!loading && !error && !empty && note" class="text-muted-foreground mt-2 text-xs">
        {{ note }}
      </p>
    </div>
  </div>
</template>
