<script setup lang="ts">
import type { TooltipProviderProps } from 'reka-ui'
import { TooltipProvider } from 'reka-ui'

/**
 * 轻提示 Provider（第 90 期，逐字移植 BookOrbit 的 `ui/tooltip`）。
 * 默认 `delayDuration: 0`：侧栏折叠成图标栏后，悬停提示要**立刻**出现才有用
 * （等 700ms 的话用户早就移开了）。
 */
const props = withDefaults(defineProps<TooltipProviderProps>(), {
  delayDuration: 0,
})
</script>

<template>
  <TooltipProvider v-bind="props">
    <slot />
  </TooltipProvider>
</template>
