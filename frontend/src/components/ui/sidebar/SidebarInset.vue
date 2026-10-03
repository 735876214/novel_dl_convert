<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { cn } from '@/lib/utils'

/**
 * 内容区（第 90 期）。
 *
 * ⚠️ 与上游的三处差异，都是「本项目外壳是两栏 flex」的直接后果：
 *
 * 1. 上游这里是 `<main data-slot="sidebar-inset">`，靠
 *    `md:peer-data-[variant=floating]:pl-[calc(var(--sidebar-width)-var(--shell-gap))]`
 *    等**一大串 padding 计算**把内容从 `fixed` 侧栏底下推回来，还要按
 *    expanded / icon / offcanvas 三种状态各写一条。本项目不需要：`Sidebar.vue`
 *    留在文档流里，`flex-1` 自己就把剩余宽度吃干净了，宽度过渡也是父级 flex
 *    在每帧重新分配 —— 一条 padding 都不会有「算错了差 2px」的问题。
 * 2. 元素是 `<div>` 不是 `<main>`：本项目的 `<main>` 在它**里面**（App.vue 里
 *    包着 `<RouterView />` 的那个滚动容器）。两层 `<main>` 是无效的 HTML。
 * 3. 卡片外观（圆角 / 描边 / `--shell-surface` / 模糊）原样保留 —— 这是本期的
 *    「宽屏展开态零视觉回归」红线。
 */
const props = defineProps<{
  class?: HTMLAttributes['class']
}>()
</script>

<template>
  <div
    data-slot="sidebar-inset"
    :class="
      cn(
        'flex min-w-0 flex-1 flex-col overflow-hidden rounded-[var(--shell-radius)] border border-[var(--shell-border)] bg-[var(--shell-surface)] shadow-xs backdrop-blur-md backdrop-saturate-150',
        props.class,
      )
    "
  >
    <slot />
  </div>
</template>
