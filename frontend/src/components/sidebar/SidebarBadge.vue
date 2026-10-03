<script setup lang="ts">
/**
 * 侧栏行尾的计数胶囊（第 90 期，形态照搬 BookOrbit 的 `sidebar/SidebarBadge.vue`）。
 *
 * 数字**只能来自真实接口**（`/api/browse-counts`、书库实体数、收藏夹条目数……
 * 见 `AppSidebar` 的 `navCount`）。拿不到时调用方**不渲染**它，而不是显示 0 ——
 * 0 是个具体的数字，会与「真的没有」混淆。
 *
 * ⚠️ 它必须写在 `SidebarMenuButton` **里面**（上游 `SidebarNavItem` 的 badge 槽
 * 也是这样），所以选中态靠 `group-data-[active=true]/item:` 而不是 `peer-data-*`。
 * ⚠️ 折叠成图标条时**藏起来**：48px 宽放不下图标 + 数字，两者都会变成糊在一起的
 * 十几个像素。
 */
defineProps<{
  count: number
}>()
</script>

<template>
  <span
    class="ml-auto shrink-0 rounded-full bg-muted px-[0.4375rem] py-1 text-[10.5px] leading-none font-medium text-sidebar-count-foreground tabular-nums transition-colors group-data-[active=true]/item:bg-(--shell-accent-line) group-data-[active=true]/item:text-primary group-data-[collapsible=icon]:hidden"
  >
    {{ count }}
  </span>
</template>
