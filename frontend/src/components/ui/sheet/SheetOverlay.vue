<script setup lang="ts">
import type { DialogOverlayProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { DialogOverlay } from 'reka-ui'

import { cn } from '@/lib/utils'

/**
 * 抽屉遮罩（第 90 期，逐字移植 BookOrbit 的 `ui/sheet`）。
 * 颜色走 `--scrim`（本期从上游 tokens.css 补进主题层）—— 深浅色主题下都是**深色**纱，
 * 拿 `--foreground` 调它会在深色主题下变成一层浅雾、盖不住下面的内容。
 */
const props = defineProps<DialogOverlayProps & { class?: HTMLAttributes['class'] }>()

const delegatedProps = reactiveOmit(props, 'class')
</script>

<template>
  <DialogOverlay
    data-slot="sheet-overlay"
    :class="cn('data-[state=open]:animate-fade-in fixed inset-0 z-50 bg-scrim', props.class)"
    v-bind="delegatedProps"
  >
    <slot />
  </DialogOverlay>
</template>
