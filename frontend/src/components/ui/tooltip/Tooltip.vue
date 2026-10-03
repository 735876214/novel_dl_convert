<script setup lang="ts">
import type { TooltipRootEmits, TooltipRootProps } from 'reka-ui'
import { injectTooltipProviderContext, TooltipRoot, useForwardPropsEmits } from 'reka-ui'

import TooltipProvider from './TooltipProvider.vue'

/**
 * 轻提示根（第 90 期，逐字移植 BookOrbit 的 `ui/tooltip`）。
 *
 * ⚠️ 那段 `providerInScope` 兜底是**移植的一部分，不是多余代码**：reka-ui 的每个
 * tooltip 部件都会 inject Provider 上下文，缺了就抛。App.vue 把整棵树包在一个
 * Provider 里，所以真正会走到兜底分支的只有**组件测试**（单独 mount 一个
 * 用 tooltip 的组件，没有 Provider 祖先）。有了它，那些测试照常渲染而不是炸掉；
 * 应用内仍以真正的 Provider 为准。
 */
const props = defineProps<TooltipRootProps>()
const emits = defineEmits<TooltipRootEmits>()

const forwarded = useForwardPropsEmits(props, emits)

const providerInScope = injectTooltipProviderContext(null) !== null
</script>

<template>
  <TooltipRoot v-if="providerInScope" v-slot="slotProps" data-slot="tooltip" v-bind="forwarded">
    <slot v-bind="slotProps" />
  </TooltipRoot>
  <TooltipProvider v-else>
    <TooltipRoot v-slot="slotProps" data-slot="tooltip" v-bind="forwarded">
      <slot v-bind="slotProps" />
    </TooltipRoot>
  </TooltipProvider>
</template>
