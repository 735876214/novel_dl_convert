<script setup lang="ts">
import type { DialogContentEmits, DialogContentProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { X } from '@lucide/vue'
import { reactiveOmit } from '@vueuse/core'
import { DialogClose, DialogContent, DialogPortal, useForwardPropsEmits } from 'reka-ui'

import { cn } from '@/lib/utils'
import SheetOverlay from './SheetOverlay.vue'

/**
 * 抽屉内容（第 90 期，逐字移植 BookOrbit 的 `ui/sheet`）。
 *
 * ⚠️ `DialogPortal` 默认 `to="body"` —— **必须保持**。外壳的内容卡片带
 * `backdrop-blur`，而 `backdrop-filter` 会让 `position: fixed` 的后代以它为
 * **包含块**（第 83 期 `BookPreviewDialog` 已踩过同一个坑：浮层被卡片裁掉一半）。
 * 只有把抽屉挂到 `body` 上才能真按视口定位。
 *
 * 进出场动效不用 tw-animate-css（本项目未引，见 `main.css` 文件头）：
 * 入场用本仓 `main.css` 的 `nf-slide-in-*` keyframes（自带 reduced-motion 关闭），
 * 出场交给 reka-ui 的 Presence 立即卸载 —— 抽屉关闭本就该跟手，
 * 拖一个 300ms 的退场反而像卡住。
 */
interface SheetContentProps extends DialogContentProps {
  class?: HTMLAttributes['class']
  side?: 'top' | 'right' | 'bottom' | 'left'
  /** 关掉右上角内置的关闭按钮（内容自带头部动作时用） */
  hideClose?: boolean
}

defineOptions({
  inheritAttrs: false,
})

const props = withDefaults(defineProps<SheetContentProps>(), {
  side: 'right',
})
const emits = defineEmits<DialogContentEmits>()

const delegatedProps = reactiveOmit(props, 'class', 'side', 'hideClose')

const forwarded = useForwardPropsEmits(delegatedProps, emits)
</script>

<template>
  <DialogPortal>
    <SheetOverlay />
    <DialogContent
      data-slot="sheet-content"
      :class="
        cn(
          'bg-background fixed z-50 flex flex-col gap-2 shadow-lg',
          side === 'right' && 'nf-slide-in-right inset-y-0 right-0 h-full w-3/4 border-l sm:max-w-sm',
          side === 'left' && 'nf-slide-in-left inset-y-0 left-0 h-full w-3/4 border-r sm:max-w-sm',
          side === 'top' && 'nf-slide-in-top inset-x-0 top-0 h-auto border-b',
          side === 'bottom' && 'nf-slide-in-bottom inset-x-0 bottom-0 h-auto border-t',
          props.class,
        )
      "
      v-bind="{ ...$attrs, ...forwarded }"
    >
      <slot />

      <DialogClose
        v-if="!hideClose"
        class="ring-offset-background focus:ring-ring absolute top-4 right-4 rounded-xs opacity-70 transition-opacity hover:opacity-100 focus:ring-2 focus:ring-offset-2 focus:outline-hidden disabled:pointer-events-none"
      >
        <X class="size-4" />
        <span class="sr-only">关闭</span>
      </DialogClose>
    </DialogContent>
  </DialogPortal>
</template>
