<script setup lang="ts">
import Icon from '@/components/ui/Icon.vue'

/**
 * 图表卡内的空态（照搬上游 `ChartEmptyState.vue:11-22`）。
 *
 * 刻意**不复用** `ui/EmptyState.vue`：那个自带边框与圆底图标，是给页面级空态用的；
 * 嵌在已经带边框的图表卡里会套两层框。这里是无边框的纯内容。
 *
 * 两种场景共用：真的没数据，与**数据量不足**（上游各图都有最小事件数阈值，
 * 不够就显示这个而不是画一张噪声图 —— 阈值见各图组件）。
 */
withDefaults(
  defineProps<{
    icon?: string
    title: string
    description?: string
  }>(),
  { icon: 'chart', description: '' },
)
</script>

<template>
  <div
    class="animate-fade-up text-muted-foreground flex h-full flex-col items-center justify-center gap-3 text-center"
  >
    <Icon :name="icon" class="size-9 opacity-20" />
    <div class="flex max-w-[280px] flex-col items-center gap-1">
      <p class="text-sm font-medium">{{ title }}</p>
      <p v-if="description" class="text-xs opacity-70">{{ description }}</p>
    </div>
  </div>
</template>
