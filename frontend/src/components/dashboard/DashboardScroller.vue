<script setup lang="ts">
/**
 * 仪表盘滚动容器与栅格上下文。
 *
 * 单独抽出来是因为部件与书架行需要共享同一套水平内边距与垂直间距，
 * 同时在窄屏下要保证横向滚动行不会被父级裁掉。
 */
</script>

<template>
  <div class="flex min-w-0 flex-col gap-6">
    <slot />
  </div>
</template>
