<script setup lang="ts">
/**
 * 工具页「范围」切换：**全部书库 / 当前库**（第 13 期）。
 *
 * 值语义与后端一致：**空串 = 全部书库**（= 引入库维度之前的行为，零变化），
 * 非空 = 只统计该库。
 *
 * 「当前库」复用侧栏选中的库（`store.currentLibraryId`）—— 与导航裁剪是同一个概念，
 * 不另造一套「本页的库」。侧栏没选库时（=全部书库）退化为下拉，让用户仍能指定单个库：
 * 否则这排控件会变成摆设。
 */
import { computed, watch } from 'vue'

import Segment from '@/components/ui/Segment.vue'
import { useLibraryStore } from '@/stores/library'

const props = defineProps<{
  /** 空 = 全部书库；否则 = 书库 id */
  modelValue: string
}>()
const emit = defineEmits<{ 'update:modelValue': [string] }>()

const library = useLibraryStore()

const current = computed(() => library.currentLibraryId)

const options = computed(() => [
  { value: '', label: '全部书库' },
  { value: current.value, label: `当前库 · ${library.currentLibraryName}` },
])

/** 侧栏换了当前库：本页正跟着旧「当前库」走的话一起跟过去（否则统计的是另一个库） */
watch(current, (id, old) => {
  if (props.modelValue && props.modelValue === old) emit('update:modelValue', id)
})

function pick(e: Event): void {
  emit('update:modelValue', (e.target as HTMLSelectElement).value)
}
</script>

<template>
  <div class="inline-flex items-center gap-2">
    <span class="text-[11.5px] text-muted-foreground">范围</span>
    <Segment
      v-if="current"
      :options="options"
      :model-value="modelValue"
      @update:model-value="emit('update:modelValue', $event)"
    />
    <select
      v-else
      :value="modelValue"
      aria-label="书库范围"
      class="h-8 rounded-md border border-border bg-muted px-2 text-[12.5px] text-foreground outline-none focus:border-ring"
      @change="pick"
    >
      <option value="">全部书库</option>
      <option v-for="l in library.libraryEntities" :key="l.id" :value="l.id">{{ l.name }}</option>
    </select>
  </div>
</template>
