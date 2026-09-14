<script setup lang="ts">
import Icon from './Icon.vue'

/** 空状态：图标 + 标题 + 说明 + 可选操作槽。全站统一，不用各自写一遍。 */
withDefaults(
  defineProps<{
    icon?: string
    title: string
    desc?: string
    /** 虚线框样式（用于「可添加」的场景） */
    dashed?: boolean
  }>(),
  { icon: 'alert', desc: '', dashed: false },
)
</script>

<template>
  <div
    class="flex flex-col items-center justify-center rounded-lg px-6 py-14 text-center"
    :class="dashed ? 'border border-dashed border-border bg-card/50' : 'bg-card border border-border'"
  >
    <div class="grid h-11 w-11 place-items-center rounded-full bg-muted text-muted-foreground">
      <Icon :name="icon" class="h-5 w-5" />
    </div>
    <h3 class="mt-3.5 text-[14px] font-semibold text-foreground">{{ title }}</h3>
    <p v-if="desc" class="mt-1.5 max-w-[46ch] text-[12.5px] leading-relaxed text-muted-foreground">
      {{ desc }}
    </p>
    <div v-if="$slots.action" class="mt-5">
      <slot name="action" />
    </div>
  </div>
</template>
