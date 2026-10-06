<script setup lang="ts">
import { computed, type HTMLAttributes } from 'vue'
import { useVModel } from '@vueuse/core'

import { cn } from '@/lib/utils'

/**
 * 通用输入框（第 90 期，逐字移植 BookOrbit 的 `ui/input`）。
 *
 * 项目此前**没有通用 Input**（各处的搜索框都是就地写一串类名），本组件是为
 * `SidebarInput` 移植的，暂不替换既有页面里的输入框 —— 那是另一件事，
 * 顺手全量替换会把本期变成一次大范围视觉改动。
 */
const props = defineProps<{
  defaultValue?: string | number
  modelValue?: string | number
  /** `v-model.number` / `v-model.trim`：原生元素上由 Vue 处理，自定义组件要自己实现 */
  modelModifiers?: { number?: boolean; trim?: boolean }
  class?: HTMLAttributes['class']
}>()

const emits = defineEmits<{
  (e: 'update:modelValue', payload: string | number): void
}>()

const inner = useVModel(props, 'modelValue', emits, {
  passive: true,
  defaultValue: props.defaultValue,
})

const model = computed({
  get: () => inner.value,
  set: (value: string | number) => {
    inner.value = applyModifiers(value)
  },
})

/** 解析不出来的文本保持文本，与原生输入的 `v-model.number` 行为一致 */
function applyModifiers(value: string | number): string | number {
  if (typeof value !== 'string') return value
  const trimmed = props.modelModifiers?.trim ? value.trim() : value
  if (!props.modelModifiers?.number) return trimmed
  const parsed = Number.parseFloat(trimmed)
  return Number.isNaN(parsed) ? trimmed : parsed
}
</script>

<template>
  <input
    v-model="model"
    data-slot="input"
    :class="
      cn(
        'file:text-foreground placeholder:text-muted-foreground selection:bg-primary selection:text-primary-foreground dark:bg-input/30 border-input h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow] outline-none file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm',
        'focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px]',
        'aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 aria-invalid:border-destructive',
        props.class,
      )
    "
  >
</template>
