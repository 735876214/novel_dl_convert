<script setup lang="ts">
import type { TooltipContentEmits, TooltipContentProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { TooltipArrow, TooltipContent, TooltipPortal, useForwardPropsEmits } from 'reka-ui'

import { cn } from '@/lib/utils'

/**
 * 轻提示气泡（第 90 期，逐字移植 BookOrbit 的 `ui/tooltip`）。
 *
 * `bg-foreground text-background` 是**反色**而不是写死黑/白（与项目既有
 * `ui/IconButton.vue` 的气泡同一口径）：深色主题下 `--foreground` 翻成近白，
 * 反色自动成立；写死黑会在深色卡片上糊成看不见的一团。
 */
defineOptions({
  inheritAttrs: false,
})

const props = withDefaults(defineProps<TooltipContentProps & { class?: HTMLAttributes['class'] }>(), {
  sideOffset: 4,
})

const emits = defineEmits<TooltipContentEmits>()

const delegatedProps = reactiveOmit(props, 'class')
const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <TooltipPortal>
    <TooltipContent
      data-slot="tooltip-content"
      v-bind="{ ...forwarded, ...$attrs }"
      :class="
        cn(
          // 入场动效走 `main.css` 的 keyframes（本项目未引 tw-animate-css，
          // 见该文件头；`animate-scale-in` 自带 opacity，别叠 `animate-fade-in`
          // —— 两个类都设 `animation` 简写，后生成的会整体覆盖前者）
          'bg-foreground text-background animate-scale-in z-[110] w-fit rounded-md px-3 py-1.5 text-xs text-balance',
          props.class,
        )
      "
    >
      <slot />

      <TooltipArrow class="bg-foreground fill-foreground z-[110] size-2.5 translate-y-[calc(-50%_-_2px)] rotate-45 rounded-[2px]" />
    </TooltipContent>
  </TooltipPortal>
</template>
