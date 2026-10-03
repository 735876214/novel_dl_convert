<script setup lang="ts">
import type { SidebarProps } from '.'
import { cn } from '@/lib/utils'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { SIDEBAR_WIDTH_MOBILE, useSidebar } from './utils'

/**
 * 侧栏容器（第 90 期，移植 BookOrbit 的 `ui/sidebar/Sidebar.vue`）。
 *
 * 三个分支与上游一一对应：`none`（常驻不动）/ 窄屏抽屉 / 桌面常驻。
 *
 * ## 与上游的两处结构性差异（都是本项目外壳形态逼出来的）
 *
 * 1. **上游桌面版把卡片 `fixed` 定位**，再让 `SidebarInset` 用 `pl-(--sidebar-width)`
 *    把内容推回来。本项目的外壳本来就是「两栏 flex + 卡片间一个 `--shell-gap`」
 *    （见 `App.vue`），照搬 `fixed` 等于把整套布局重写一遍，还得让 Inset 反向
 *    补算 `--shell-gap`。所以这里让侧栏**留在文档流里**（`shrink-0` + 宽度过渡），
 *    Inset 依旧是 `flex-1`，一行 padding 都不用加。
 *    **对内的类名契约完全不变**：外层仍是 `group peer` + `data-state/collapsible/
 *    variant/side`，所以从上游逐字搬来的那些 `group-data-[collapsible=icon]:*`
 *    子孙选择器（图标条隐藏文字、组标题上浮消隐……）原样生效。
 * 2. **断点是 `sm`（640px）而不是 `md`（768px）**，与 `lib/viewport.ts` 同一口径。
 *    `hidden sm:block` 必须与 `useNarrowScreen()` 的 `NARROW_QUERY` 严丝合缝 ——
 *    差一个像素就会出现「JS 认为该显示抽屉、CSS 认为该显示常驻」的双份侧栏。
 */
defineOptions({
  inheritAttrs: false,
})

const props = withDefaults(defineProps<SidebarProps>(), {
  side: 'left',
  // 本项目的侧栏是「浮起卡片」形态（既有的 `rounded + border + bg-(--shell-surface)`），
  // 对应上游的 floating；上游默认的 sidebar（贴边 + 右侧分隔线）本项目没在用。
  variant: 'floating',
  // 桌面折叠成图标条（本期的核心诉求）。上游默认 offcanvas（整块滑走）——
  // 那个形态下面用户没有任何可见入口，得靠顶栏按钮才找得回来。
  collapsible: 'icon',
})

const { isMobile, state, openMobile, setOpenMobile } = useSidebar()
</script>

<template>
  <!-- ① 不可折叠：原样一块 -->
  <div
    v-if="collapsible === 'none'"
    data-slot="sidebar"
    :class="cn('flex h-full w-(--sidebar-width) shrink-0 flex-col bg-(--shell-surface) text-sidebar-foreground', props.class)"
    v-bind="$attrs"
  >
    <slot />
  </div>

  <!-- ② 窄屏（≤640px）：抽屉。`SheetContent` 内部 Teleport 到 body，见该文件注释 -->
  <Sheet v-else-if="isMobile" :open="openMobile" v-bind="$attrs" @update:open="setOpenMobile">
    <SheetContent
      data-sidebar="sidebar"
      data-slot="sidebar"
      data-mobile="true"
      :side="side"
      hide-close
      class="w-(--sidebar-width) border-(--shell-border) bg-(--shell-surface) p-0 backdrop-blur-xl backdrop-saturate-150"
      :style="{ '--sidebar-width': SIDEBAR_WIDTH_MOBILE }"
    >
      <!-- 无障碍名：抽屉是模态对话框，读屏需要有标题与说明 -->
      <SheetHeader class="sr-only">
        <SheetTitle>侧边栏</SheetTitle>
        <SheetDescription>导航菜单。按 Esc 或点击遮罩关闭。</SheetDescription>
      </SheetHeader>
      <div class="flex h-full w-full flex-col">
        <slot />
      </div>
    </SheetContent>
  </Sheet>

  <!-- ③ 桌面常驻：留文档流，宽度在 240px ↔ 3rem 之间过渡 -->
  <div
    v-else
    class="group peer relative hidden shrink-0 text-sidebar-foreground transition-[width] duration-200 ease-linear sm:block"
    :class="[
      side === 'right' ? 'order-last' : '',
      'w-(--sidebar-width) data-[collapsible=icon]:w-(--sidebar-width-icon) data-[collapsible=offcanvas]:w-0',
      props.class,
    ]"
    data-slot="sidebar"
    :data-state="state"
    :data-collapsible="state === 'collapsed' ? collapsible : ''"
    :data-variant="variant"
    :data-side="side"
    v-bind="$attrs"
  >
    <!--
      ⚠️ 卡片这里**故意不加 `overflow-hidden`**：`SidebarRail` 是调用方放进槽里的，
      它要 `-right-4` 探出卡片右缘 8px 去接住鼠标；加了裁剪就把它自己剪没了。
      折叠时该消失的东西（文字、角标、组标题、增删按钮）都由各自的
      `group-data-[collapsible=icon]:hidden` / `opacity-0` 关掉，不靠父级裁剪。
    -->
    <div
      data-sidebar="sidebar"
      :class="
        cn(
          'relative z-0 flex h-full w-full flex-col bg-(--shell-surface) backdrop-blur-md backdrop-saturate-150',
          variant === 'floating'
            ? 'rounded-[var(--shell-radius)] border border-[var(--shell-border)] shadow-xs'
            : 'border-r border-[var(--shell-border)]',
        )
      "
    >
      <slot />
    </div>
  </div>
</template>
