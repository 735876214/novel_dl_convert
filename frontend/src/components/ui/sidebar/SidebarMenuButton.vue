<script setup lang="ts">
import type { Component } from 'vue'
import type { SidebarMenuButtonProps } from './SidebarMenuButtonChild.vue'
import { reactiveOmit } from '@vueuse/core'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import SidebarMenuButtonChild from './SidebarMenuButtonChild.vue'
import { useSidebar } from './utils'

/**
 * 菜单行（第 90 期，逐字移植 BookOrbit 的 `ui/sidebar`）。
 *
 * `tooltip` 一给，根节点就换成 tooltip 触发器 —— 折叠成图标条后，行里只剩一个
 * 图标，**没有提示就没人知道那是什么**。
 *
 * ⚠️ `TooltipContent` 上的 `:hidden` 不是随手加的开关：提示只在**折叠态**才有
 * 意义（展开态文字本来就在旁边），移动端抽屉里更是只有长按才触发。`hidden` 是
 * HTML 布尔属性，Vue 会在值为假时**删掉**这个属性，所以这里能当显隐开关用。
 */
defineOptions({
  inheritAttrs: false,
})

const props = withDefaults(
  defineProps<
    SidebarMenuButtonProps & {
      tooltip?: string | Component
    }
  >(),
  {
    as: 'button',
    variant: 'default',
    size: 'default',
  },
)

const { isMobile, state } = useSidebar()

const delegatedProps = reactiveOmit(props, 'tooltip')
</script>

<template>
  <SidebarMenuButtonChild v-if="!tooltip" v-bind="{ ...delegatedProps, ...$attrs }">
    <slot />
  </SidebarMenuButtonChild>

  <Tooltip v-else>
    <TooltipTrigger as-child>
      <SidebarMenuButtonChild v-bind="{ ...delegatedProps, ...$attrs }">
        <slot />
      </SidebarMenuButtonChild>
    </TooltipTrigger>
    <TooltipContent side="right" align="center" :hidden="state !== 'collapsed' || isMobile">
      <template v-if="typeof tooltip === 'string'">
        {{ tooltip }}
      </template>
      <component :is="tooltip" v-else />
    </TooltipContent>
  </Tooltip>
</template>
