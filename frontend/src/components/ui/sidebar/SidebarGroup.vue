<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

/** 侧栏分组（第 90 期，逐字移植 BookOrbit 的 `ui/sidebar`）。`relative` 是给 `SidebarGroupAction` 定位用的。 */
const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <div data-slot="sidebar-group" data-sidebar="group" :class="cn('relative flex w-full min-w-0 flex-col px-2 py-1.5', props.class)">
    <slot />
  </div>
</template>
