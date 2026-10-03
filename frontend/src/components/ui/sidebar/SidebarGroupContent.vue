<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

/** 分组内容（第 90 期，逐字移植 BookOrbit 的 `ui/sidebar`）。 */
const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <div data-slot="sidebar-group-content" data-sidebar="group-content" :class="cn('w-full text-[14px]', props.class)">
    <slot />
  </div>
</template>
