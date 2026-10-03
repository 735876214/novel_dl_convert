import type { VariantProps } from 'class-variance-authority'
import type { HTMLAttributes } from 'vue'
import { cva } from 'class-variance-authority'

/**
 * 侧栏基础组件（第 90 期，移植 BookOrbit 的 `ui/sidebar`）。
 *
 * ⚠️ 这是一份**按需子集**，不是全量照抄。上游 `index.ts` 还导出
 * `SidebarGroupLabel` / `SidebarGroupAction` / `SidebarMenuAction` /
 * `SidebarMenuBadge` / `SidebarMenuSkeleton` / `SidebarMenuSub*` 六个 ——
 * 上游自己也没用它们做业务侧栏（分组头走 `SidebarSectionHeader.vue`，
 * 计数走 `SidebarBadge.vue`，骨架屏用的是本项目既有的 `ui/Skeleton.vue`）。
 * 搬过来只会得到「两个都能用、长得还不一样」的双份实现，所以**不搬**。
 * 真需要时按上游逐字补，别就地发明。
 */

export interface SidebarProps {
  side?: 'left' | 'right'
  variant?: 'sidebar' | 'floating' | 'inset'
  collapsible?: 'offcanvas' | 'icon' | 'none'
  class?: HTMLAttributes['class']
}

export { default as Sidebar } from './Sidebar.vue'
export { default as SidebarContent } from './SidebarContent.vue'
export { default as SidebarFooter } from './SidebarFooter.vue'
export { default as SidebarGroup } from './SidebarGroup.vue'
export { default as SidebarGroupContent } from './SidebarGroupContent.vue'
export { default as SidebarHeader } from './SidebarHeader.vue'
export { default as SidebarInput } from './SidebarInput.vue'
export { default as SidebarInset } from './SidebarInset.vue'
export { default as SidebarMenu } from './SidebarMenu.vue'
export { default as SidebarMenuButton } from './SidebarMenuButton.vue'
export { default as SidebarMenuItem } from './SidebarMenuItem.vue'
export { default as SidebarProvider } from './SidebarProvider.vue'
export { default as SidebarRail } from './SidebarRail.vue'
export { default as SidebarSeparator } from './SidebarSeparator.vue'
export { default as SidebarTrigger } from './SidebarTrigger.vue'

export { SIDEBAR_KEYBOARD_SHORTCUT, SIDEBAR_WIDTH_ICON, SIDEBAR_WIDTH_MOBILE, useSidebar } from './utils'

/**
 * 菜单行的外观（逐字照搬上游，含折叠态的三条 `group-data-[collapsible=icon]:`）。
 *
 * ⚠️ 那三条是图标条能看的关键，少一条就会「图标偏在左边 / 文字露出来」：
 *   · `size-8!`       —— 32px 见方（`!` 是要压过调用方传进来的 `h-8 w-full`）
 *   · `justify-center`—— 图标居中
 *   · `px-0!`         —— 去掉左右内边距，否则图标被挤偏
 * 文字能收进去还靠 `[&>span:last-child]:truncate`：`overflow:hidden` 让这个
 * flex 子项的自动最小尺寸变成 0，它才肯缩到没有宽度（纯 `truncate` 是不够的）。
 */
export const sidebarMenuButtonVariants = cva(
  'peer/menu-button relative flex w-full items-center gap-2 overflow-hidden rounded-md px-2 text-left outline-hidden ring-sidebar-ring transition-colors duration-150 focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50 aria-disabled:pointer-events-none aria-disabled:opacity-50 group-data-[collapsible=icon]:size-8! group-data-[collapsible=icon]:justify-center group-data-[collapsible=icon]:px-0! [&>span:last-child]:truncate [&>svg]:shrink-0',
  {
    variants: {
      variant: {
        default: 'hover:bg-(--shell-accent-wash)',
        outline: 'border border-(--shell-accent-line) hover:bg-(--shell-accent-wash)',
      },
      size: {
        default: 'h-8 text-[14px]',
        sm: 'h-7 text-[13px]',
        lg: 'h-12 text-[14px]',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  },
)

export type SidebarMenuButtonVariants = VariantProps<typeof sidebarMenuButtonVariants>
