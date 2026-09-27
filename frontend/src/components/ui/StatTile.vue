<script setup lang="ts">
/**
 * 单格统计（标签在上、数值在下、可选口径小字）。详情页「我的记录 / 阅读日志」的四格用它。
 *
 * `value` 收**字符串**而不是数字，这是刻意的：格式化由调用方决定，而「未知」与「0」的
 * 区分也在调用方 —— 那是本项目「不造假数据」纪律的落点（`00:00` 与「未记录」是两个
 * 不同的结论，不能都渲染成 `0`）。
 */
withDefaults(
  defineProps<{
    label: string
    value: string
    /** 值下方的小字：口径说明或数据来源 */
    hint?: string
  }>(),
  { hint: '' },
)
</script>

<template>
  <div class="min-w-0 rounded-lg border border-border bg-card px-3 py-2.5">
    <div class="truncate text-[11px] text-muted-foreground">{{ label }}</div>
    <div class="mt-1 truncate text-[16px] font-semibold tabular-nums text-foreground" :title="value">
      {{ value }}
    </div>
    <div v-if="hint" class="mt-0.5 truncate text-[10.5px] text-muted-foreground" :title="hint">
      {{ hint }}
    </div>
  </div>
</template>
