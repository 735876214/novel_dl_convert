<script setup lang="ts">
import type { NavItem } from '@/data/nav'
import Icon from '@/components/ui/Icon.vue'
import { SidebarMenuButton, SidebarMenuItem } from '@/components/ui/sidebar'
import SidebarBadge from './SidebarBadge.vue'

/**
 * 一条侧栏导航项（第 90 期，结构照搬 BookOrbit 的 `sidebar/SidebarNavItem.vue`）。
 *
 * ⚠️ 是 `<button>` 不是 `<RouterLink>`：这些条目点下去**不一定只是跳路由** ——
 * 「库」要先切库、「智能书架」要先 `openSmart`、「收藏夹」要进 `/collections/:id`，
 * 然后才 push。做成链接就得把状态改动塞进导航守卫，那是把两件事混成一件。
 * 用按钮换来的是**键盘可达**（Tab 到、回车触发），这是本期明确要的。
 *
 * 三处状态各有各的出口，别互相顶替：
 *   · `isActive`  —— 当前路由 / 当前库（由调用方算好）
 *   · `count`     —— 真实计数，`null` 就**不渲染**胶囊
 *   · 折叠态      —— 文字与胶囊由 `group-data-[collapsible=icon]:hidden` 统一收掉
 *
 * 选中态：底色 `--shell-accent-tint` + 左缘 2px 主色竖条（上游同款）。
 * 竖条走 `before:` 伪元素而不是额外元素：它不参与布局，所以有没有选中都不会
 * 让文字左右挪一像素。
 */
const props = defineProps<{
  item: NavItem
  isActive: boolean
  count: number | null
  visible: boolean
}>()

const emit = defineEmits<{ select: [item: NavItem] }>()
</script>

<template>
  <SidebarMenuItem v-show="props.visible">
    <SidebarMenuButton
      as="button"
      type="button"
      :is-active="props.isActive"
      :tooltip="props.item.label"
      :class="
        [
          // `group/item` 必须写在 class 里，不能当裸属性 —— 模板编译器不允许属性名带 `/`
          'group/item h-8 min-w-0 gap-[0.5625rem] px-[0.625rem] text-[13px] font-normal',
          'before:absolute before:top-1/2 before:left-0 before:h-4 before:w-[2px] before:-translate-y-1/2 before:rounded-full before:bg-primary',
          'before:opacity-0 before:transition-opacity before:duration-150',
          'data-[active=true]:bg-(--shell-accent-tint) data-[active=true]:font-medium data-[active=true]:before:opacity-100',
        ].join(' ')
      "
      @click="emit('select', props.item)"
    >
      <Icon :name="props.item.icon" class="h-[0.9375rem] w-[0.9375rem] shrink-0 opacity-80" />
      <span
        class="min-w-0 flex-1 truncate text-sidebar-foreground transition-colors duration-150 group-data-[active=true]/item:font-medium group-data-[active=true]/item:text-primary group-data-[collapsible=icon]:hidden"
      >
        {{ props.item.label }}
      </span>
      <SidebarBadge v-if="props.count !== null" :count="props.count" />
    </SidebarMenuButton>
  </SidebarMenuItem>
</template>
