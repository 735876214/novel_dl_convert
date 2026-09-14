<script setup lang="ts">
import { computed } from 'vue'

import { useDashboardStore } from '@/stores/dashboard'
import { widgetById } from './widgets/registry'

/**
 * 部件行：按 store 里的顺序渲染已启用的部件，响应式列数。
 *
 * 渲染层完全由注册表驱动 —— 部件写死在模板里的话，
 * 自定义面板的排序/开关就没法生效。
 */
const dashboard = useDashboardStore()

/** 列跨度：lg 占满整行、md 两列、sm 三列（窄屏统一切成单/双列） */
const SPAN_CLASS: Record<string, string> = {
  lg: 'lg:col-span-6',
  md: 'lg:col-span-3',
  sm: 'lg:col-span-2',
}

/** 只取「已启用且已实现」的部件（未实现的在面板里置灰，不占版面） */
const visible = computed(() =>
  dashboard.enabledWidgets
    .map((w) => widgetById(w.id))
    .filter((w): w is NonNullable<typeof w> => Boolean(w?.component)),
)
</script>

<template>
  <div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-6">
    <component
      :is="w.component"
      v-for="w in visible"
      :key="w.id"
      :class="['min-w-0', SPAN_CLASS[w.size]]"
    />
  </div>
</template>
