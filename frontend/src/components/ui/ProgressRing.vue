<script setup lang="ts">
import { computed } from 'vue'

/**
 * 环形进度。
 *
 * 角度只有**一个真值源**：由 value/max 算出写入 `--deg`，CSS 只消费它。
 * （参考页的缺陷是 CSS 写死 151deg、JS 又按 progress*3.6 覆盖 —— 两处真值源。）
 */
const props = withDefaults(
  defineProps<{
    value: number
    max: number
    /** 环直径（px） */
    size?: number
    /** 环宽（px） */
    thickness?: number
  }>(),
  { size: 96, thickness: 8 },
)

const ratio = computed(() => {
  if (props.max <= 0) return 0
  return Math.max(0, Math.min(1, props.value / props.max))
})

/** 唯一真值源：角度由比例算出，CSS 里用 var(--deg) 消费 */
const deg = computed(() => `${(ratio.value * 360).toFixed(2)}deg`)

const percentText = computed(() => `${Math.round(ratio.value * 100)}%`)

const innerSize = computed(() => `${props.size - props.thickness * 2}px`)
</script>

<template>
  <div
    class="relative grid shrink-0 place-items-center rounded-full"
    :style="{
      width: `${size}px`,
      height: `${size}px`,
      '--deg': deg,
      background: `conic-gradient(var(--primary) var(--deg), var(--muted) var(--deg))`,
    }"
  >
    <div
      class="grid place-items-center rounded-full bg-card"
      :style="{ width: innerSize, height: innerSize }"
    >
      <slot>
        <span class="text-[15px] font-semibold tabular-nums text-foreground">{{ percentText }}</span>
      </slot>
    </div>
  </div>
</template>
