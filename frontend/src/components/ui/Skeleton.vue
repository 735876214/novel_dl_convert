<script setup lang="ts">
/**
 * 骨架屏占位块（第 88 期）。
 *
 * 起因：书库落地页在加载期**没有任何反馈** —— 数据还在路上时页面直接落进空态，
 * 于是告诉用户「这个书架还是空的」。这个组件只做一件事：画一个会呼吸的灰块，
 * 让「正在加载」这件事**看得见**。
 *
 * ⚠️ 只用既有 token（`bg-muted`），不硬编码颜色；尺寸 / 圆角由调用方用 class 控制
 * （单根元素，父级 class 会自动合并进来，如 `<Skeleton class="aspect-3/4 w-full" />`）。
 */
</script>

<template>
  <div class="animate-pulse rounded-md bg-muted" />
</template>
