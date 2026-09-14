<script setup lang="ts">
import type { AccentOption } from '@/data/accents'

/** 点缀色网格：8 列，选中带描边环。65 档全部由 ACCENTS 驱动。 */
defineProps<{
  items: AccentOption[]
  modelValue: string
}>()

const emit = defineEmits<{ 'update:modelValue': [string] }>()
</script>

<template>
  <div class="grid grid-cols-8 gap-1.5">
    <button
      v-for="a in items"
      :key="a.name"
      type="button"
      :title="a.label"
      :aria-label="a.label"
      class="aspect-square cursor-pointer rounded-md transition-transform duration-150 hover:scale-110"
      :class="modelValue === a.name ? 'ring-2 ring-ring ring-offset-2 ring-offset-card' : ''"
      :style="{ background: a.c }"
      @click="emit('update:modelValue', a.name)"
    />
  </div>
</template>
