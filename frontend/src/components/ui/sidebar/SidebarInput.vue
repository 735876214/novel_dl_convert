<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'
import { Input } from '@/components/ui/input'

/**
 * 侧栏内嵌输入框（第 90 期，逐字移植 BookOrbit 的 `ui/sidebar`）。
 * 唯一使用点：侧栏「库」组的筛选框。
 */
const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <Input data-slot="sidebar-input" data-sidebar="input" :class="cn('h-8 w-full bg-background shadow-none', props.class)" />
</template>
