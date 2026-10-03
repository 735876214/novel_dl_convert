<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

/** 侧栏顶部区（第 90 期，逐字移植 BookOrbit 的 `ui/sidebar`）。 */
const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <div data-slot="sidebar-header" data-sidebar="header" :class="cn('flex shrink-0 flex-col gap-2 p-2', props.class)">
    <slot />
  </div>
</template>
