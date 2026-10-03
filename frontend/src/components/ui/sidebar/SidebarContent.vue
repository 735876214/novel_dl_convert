<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

/**
 * 侧栏中段（滚动区）。第 90 期，逐字移植 BookOrbit 的 `ui/sidebar`。
 *
 * ⚠️ `data-sidebar="content"` **必须保留**：`main.css` 里有一条
 * `[data-sidebar='content'] { scrollbar-width: thin }`，把这里的滚动条单独收窄
 * （10px 的滚动条会明显吃掉侧栏右侧的留白，整块看起来是歪的）。
 */
const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <div
    data-slot="sidebar-content"
    data-sidebar="content"
    :class="cn('flex min-h-0 flex-1 flex-col overflow-auto group-data-[collapsible=icon]:overflow-hidden', props.class)"
  >
    <slot />
  </div>
</template>
