<script setup lang="ts">
/** 段控（分段单选）。用于设置页的主题与圆角选择。 */
defineProps<{
  options: Array<{ value: string; label: string }>
  modelValue: string
}>()

const emit = defineEmits<{ 'update:modelValue': [string] }>()
</script>

<template>
  <div class="inline-flex gap-0.5 rounded-md border border-border bg-muted p-0.5">
    <button
      v-for="o in options"
      :key="o.value"
      type="button"
      :title="o.label"
      class="cursor-pointer rounded-sm px-3 py-1 text-[12px] font-medium transition-colors"
      :class="modelValue === o.value ? 'bg-card text-foreground shadow-xs' : 'text-muted-foreground hover:text-foreground'"
      @click="emit('update:modelValue', o.value)"
    >
      {{ o.label }}
    </button>
  </div>
</template>
