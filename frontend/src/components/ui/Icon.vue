<script setup lang="ts">
import { computed } from 'vue'

import { iconPath } from '@/lib/icons'

const props = withDefaults(
  defineProps<{
    name: string
    /** 额外 class，用于控制尺寸与颜色 */
    class?: string
  }>(),
  { class: '' },
)

const path = computed(() => iconPath(props.name))
</script>

<template>
  <!--
    图标 path 来自内部常量表（lib/icons.ts），非用户输入，因此 v-html 是安全的。
    尺寸在 CSS 里由 .nav-item svg / .tb-icon svg 等父级规则控制，与 v2 一致。
  -->
  <svg
    :class="props.class"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.75"
    stroke-linecap="round"
    stroke-linejoin="round"
    v-html="path"
  />
</template>
