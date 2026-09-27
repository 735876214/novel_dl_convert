<script setup lang="ts">
/**
 * 标签栏。抽出前是详情页里一段内联的裸 button 循环（第 63 期）。
 *
 * `count` 给「目录」那类要显示条数的标签用（`undefined` 就不显示，`0` 是个有意义的数）。
 * `title` 保留：标签多了以后窄屏会横向滚动，悬停要能看全称。
 *
 * 刻意不做成 slot 泛型 —— 全仓只有「一排文字标签 + 下方指示条」这一种用法，
 * 多一层插槽只是多一层间接。
 */
defineProps<{
  tabs: ReadonlyArray<{ id: string; label: string; count?: number }>
  modelValue: string
}>()

const emit = defineEmits<{ 'update:modelValue': [string] }>()
</script>

<template>
  <div class="no-scrollbar mb-4 flex items-center gap-1 overflow-x-auto border-b border-border">
    <button
      v-for="t in tabs"
      :key="t.id"
      type="button"
      :title="t.label"
      class="relative shrink-0 cursor-pointer px-3 py-2 text-[13px] font-medium whitespace-nowrap transition-colors"
      :class="modelValue === t.id ? 'text-foreground' : 'text-muted-foreground hover:text-foreground'"
      @click="emit('update:modelValue', t.id)"
    >
      {{ t.label }}
      <span v-if="t.count !== undefined" class="ml-1 text-[11px] text-muted-foreground tabular-nums">
        {{ t.count }}
      </span>
      <span
        v-if="modelValue === t.id"
        class="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-primary"
      />
    </button>
  </div>
</template>
