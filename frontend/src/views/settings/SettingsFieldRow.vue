<script setup lang="ts">
import Switch from '@/components/ui/Switch.vue'
import type { FieldDef } from '@/data/settingsFields'

/**
 * 单个服务端配置字段行：左标签 + 右控件。
 *
 * 从原 SettingsView.vue 的三处重复渲染（转换 / 监听 / 网络）抽成一个组件，
 * 控件分支与类串与原实现保持一致。
 */
defineProps<{ field: FieldDef; value: string | number | boolean | undefined }>()
const emit = defineEmits<{ update: [value: string | number | boolean] }>()
</script>

<template>
  <div class="flex items-center gap-4 border-b border-border px-4 py-3">
    <div class="min-w-0 flex-1">
      <div class="text-[13px] font-medium text-foreground">{{ field.label }}</div>
      <div v-if="field.hint" class="mt-0.5 text-[11.5px] text-muted-foreground">{{ field.hint }}</div>
    </div>

    <Switch
      v-if="field.type === 'bool'"
      :model-value="Boolean(value)"
      @update:model-value="emit('update', $event)"
    />

    <select
      v-else-if="field.type === 'select'"
      :value="value"
      class="h-8 shrink-0 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
      @change="emit('update', ($event.target as HTMLSelectElement).value)"
    >
      <option v-for="o in (field.options ?? [])" :key="o.value" :value="o.value">{{ o.label }}</option>
    </select>

    <input
      v-else-if="field.type === 'number'"
      type="number"
      :value="value"
      class="h-8 w-24 shrink-0 rounded-md border border-border bg-muted px-2 text-right text-[12.5px] text-foreground outline-none focus:border-ring"
      @input="emit('update', Number(($event.target as HTMLInputElement).value))"
    >

    <input
      v-else
      :type="field.type === 'password' ? 'password' : 'text'"
      :value="value"
      :placeholder="field.placeholder ?? ''"
      class="h-8 w-64 max-w-[50%] shrink-0 rounded-md border border-border bg-muted px-2.5 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
      @input="emit('update', ($event.target as HTMLInputElement).value)"
    >
  </div>
</template>
