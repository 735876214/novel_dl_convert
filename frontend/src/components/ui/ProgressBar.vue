<script setup lang="ts">
import { computed } from 'vue'

/**
 * 线性进度条。抽出前详情页、书卡、封面叠加层各写了一份同样的 `h-1.5 bg-muted` 结构
 * （第 63 期归并）。
 *
 * 比例只有**一个真值源**：由 value/max 算出宽度，不暴露给调用方（与 `ProgressRing.vue`
 * 同一条纪律 —— 那边记着「参考页 CSS 写死 151deg、JS 又覆盖一遍」的双真值源缺陷）。
 */
const props = withDefaults(
  defineProps<{
    value: number
    max?: number
    /** `ok` 用于「已读完」——颜色一律走 token，不在这里写死色值 */
    tone?: 'primary' | 'ok'
    size?: 'sm' | 'md'
  }>(),
  { max: 100, tone: 'primary', size: 'sm' },
)

const TONE: Record<string, string> = {
  primary: 'bg-primary',
  ok: 'bg-success',
}

const SIZE: Record<string, string> = {
  sm: 'h-1.5',
  md: 'h-2',
}

/** 夹到 [0,100]：上游给的 percent 偶尔会因浮点累加略超 100，超出去会让圆角溢出 */
const pct = computed(() => {
  if (!(props.max > 0)) return 0
  return Math.max(0, Math.min(100, (props.value / props.max) * 100))
})
</script>

<template>
  <div class="w-full overflow-hidden rounded-full bg-muted" :class="SIZE[size]">
    <div
      class="h-full rounded-full transition-[width] duration-300"
      :class="TONE[tone]"
      :style="{ width: `${pct}%` }"
    />
  </div>
</template>
