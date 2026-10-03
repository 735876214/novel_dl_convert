<script setup lang="ts">
import type { HTMLAttributes } from 'vue'
import { computed } from 'vue'
import { PanelLeft } from '@lucide/vue'

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'
import { useSidebar } from './utils'

/**
 * 顶栏的侧栏开合按钮（第 90 期，移植 BookOrbit 的 `ui/sidebar/SidebarTrigger.vue`）。
 *
 * ⚠️ 与上游的两处差异：
 *
 * 1. 上游用它的 `ui/button`（shadcn 那套，`variant="ghost" size="icon"`）。
 *    本项目**没有** `ui/button/`，只有一个 `ui/Button.vue`，它的 `variant` 是
 *    `primary|secondary|ghost|danger` 且 ghost 自带 `border border-border` ——
 *    套上去这个按钮会多一圈描边，与它替换掉的那颗按钮长得不一样。
 *    而 `ui/Button.vue` 有 82 处引用点，本期不动它（计划里写死的红线）。
 *    所以这里保持**替换前那颗按钮的原样式**（32×32 方形圆角、hover 变底色）。
 * 2. 图标显式写死尺寸 `h-[17px] w-[17px]`：`main.css` 的 `@layer base` 里有一条
 *    `svg { width:16px; height:16px }`（元素选择器），lucide 组件自带的
 *    `width/height` 属性是**表现属性**，优先级低于任何 CSS 规则 —— 不写死就会
 *    悄悄变成 16px，与顶栏其余图标（17px）差一像素。
 *
 * ⚠️ 不套 `ui/IconButton.vue`：那是圆形（`rounded-full`）且带 `data-icon-button`
 * 包裹层，`AppHeader.spec.ts` 正卡着「恰好 9 个圆形图标按钮」这条断言。
 */
const props = defineProps<{
  class?: HTMLAttributes['class']
}>()

const { isMobile, openMobile, state, toggleSidebar } = useSidebar()

/** 提示文案跟着当前状态走：「收起 / 展开」，移动端则是「关闭 / 打开」 */
const actionLabel = computed(() => {
  if (isMobile.value) return openMobile.value ? '关闭侧边栏' : '打开侧边栏'
  return state.value === 'expanded' ? '收起侧边栏' : '展开侧边栏'
})
</script>

<template>
  <Tooltip>
    <TooltipTrigger as-child>
      <button
        type="button"
        data-sidebar="trigger"
        data-slot="sidebar-trigger"
        :class="
          cn(
            'grid h-8 w-8 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground',
            props.class,
          )
        "
        :aria-label="actionLabel"
        :aria-expanded="isMobile ? openMobile : state === 'expanded'"
        @click="toggleSidebar"
      >
        <PanelLeft aria-hidden="true" class="h-[17px] w-[17px]" />
      </button>
    </TooltipTrigger>
    <TooltipContent>{{ actionLabel }}</TooltipContent>
  </Tooltip>
</template>
