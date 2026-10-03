<script setup lang="ts">
import type { SeparatorProps } from 'reka-ui'
import type { HTMLAttributes } from 'vue'
import { reactiveOmit } from '@vueuse/core'
import { Separator } from 'reka-ui'

import { cn } from '@/lib/utils'

/**
 * 分隔线（第 90 期，逐字移植 BookOrbit 的 `ui/separator`）。
 * 基座是 reka-ui 的 `Separator`：它负责输出 `role="separator"` /
 * `aria-orientation`，装饰性（`decorative`）时则整体 `aria-hidden`。
 */
const props = withDefaults(defineProps<SeparatorProps & { class?: HTMLAttributes['class'] }>(), {
  orientation: 'horizontal',
  decorative: true,
})

const delegatedProps = reactiveOmit(props, 'class')
</script>

<template>
  <Separator
    data-slot="separator"
    v-bind="delegatedProps"
    :class="
      cn(
        'bg-border shrink-0 data-[orientation=horizontal]:h-px data-[orientation=horizontal]:w-full data-[orientation=vertical]:h-full data-[orientation=vertical]:w-px',
        props.class,
      )
    "
  />
</template>
