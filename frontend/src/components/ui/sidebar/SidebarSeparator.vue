<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'
import { Separator } from '@/components/ui/separator'

/** 侧栏分隔线（第 90 期，逐字移植 BookOrbit 的 `ui/sidebar`）。 */
const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <Separator data-slot="sidebar-separator" data-sidebar="separator" :class="cn('my-1 w-auto bg-sidebar-border', props.class)" />
</template>
