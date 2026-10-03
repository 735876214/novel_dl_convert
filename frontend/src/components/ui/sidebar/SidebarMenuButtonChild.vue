<script setup lang="ts">
import type { PrimitiveProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import type { SidebarMenuButtonVariants } from '.'
import { Primitive } from 'reka-ui'
import { cn } from '@/lib/utils'
import { sidebarMenuButtonVariants } from '.'

/**
 * 菜单行的**裸**实现（第 90 期，逐字移植 BookOrbit 的 `ui/sidebar`）。
 *
 * 拆成 Child 是为了让 `SidebarMenuButton` 能把它塞进 `TooltipTrigger as-child`
 * 里 —— 带 tooltip 时根节点必须是 Tooltip 的触发器，不能再包一层。
 */
export interface SidebarMenuButtonProps extends PrimitiveProps {
  variant?: SidebarMenuButtonVariants['variant']
  size?: SidebarMenuButtonVariants['size']
  isActive?: boolean
  class?: HTMLAttributes['class']
}

const props = withDefaults(defineProps<SidebarMenuButtonProps>(), {
  as: 'button',
  variant: 'default',
  size: 'default',
})
</script>

<template>
  <Primitive
    data-slot="sidebar-menu-button"
    data-sidebar="menu-button"
    :data-size="size"
    :data-active="isActive"
    :class="cn(sidebarMenuButtonVariants({ variant, size }), props.class)"
    :as="as"
    :as-child="asChild"
    v-bind="$attrs"
  >
    <slot />
  </Primitive>
</template>
