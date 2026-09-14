<script setup lang="ts">
/**
 * 按钮。主按钮是近黑底白字（浅色）/ 近白底黑字（深色）—— 由 --primary 驱动，
 * 与 BookOrbit 一致（不是品牌蓝）。
 */
withDefaults(
  defineProps<{
    variant?: 'primary' | 'secondary' | 'ghost' | 'danger'
    size?: 'sm' | 'md'
    block?: boolean
    disabled?: boolean
    title?: string
  }>(),
  { variant: 'ghost', size: 'md', block: false, disabled: false, title: '' },
)

const VARIANT: Record<string, string> = {
  primary: 'bg-primary text-primary-foreground hover:opacity-90',
  secondary: 'bg-secondary text-secondary-foreground hover:opacity-90',
  ghost: 'bg-transparent text-foreground border border-border hover:bg-muted',
  danger: 'bg-transparent text-destructive border border-destructive/40 hover:bg-destructive/10',
}

const SIZE: Record<string, string> = {
  sm: 'h-7 px-2.5 text-[12px]',
  md: 'h-8 px-3.5 text-[12.5px]',
}
</script>

<template>
  <button
    type="button"
    :title="title"
    :disabled="disabled"
    class="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md font-medium transition-all duration-150 disabled:cursor-not-allowed disabled:opacity-40"
    :class="[VARIANT[variant], SIZE[size], block ? 'w-full' : '']"
  >
    <slot />
  </button>
</template>
