<script setup lang="ts">
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { highlightHex as highlightColor, highlightStyleLabel } from '@/data/annotationColors'
import type { Annotation } from '@/lib/api'

/**
 * 批注标签（第 63 期从 `BookDetailView` 抽出）。
 *
 * 取色统一来自 `data/annotationColors.ts`（唯一一份）—— 这里此前自己写了一份四色表，
 * 扩容时会把新增颜色静默渲染成黄色。
 *
 * 第 63 期（6/6）会给它加「按来源筛选」与基于位置锚的精确跳章。
 */
defineProps<{ annotations: Annotation[] }>()

const emit = defineEmits<{ go: [] }>()
</script>

<template>
  <div>
    <Card v-if="annotations.length" padding="none">
      <div
        v-for="a in annotations"
        :key="a.id"
        class="flex items-start gap-2.5 border-b border-border px-4 py-3 last:border-b-0"
      >
        <span
          class="mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full"
          :style="{ background: highlightColor(a.color) }"
        />
        <span class="mt-1 text-[10.5px] text-muted-foreground">{{ highlightStyleLabel(a.style) }}</span>
        <div class="min-w-0 flex-1">
          <p class="text-[12.5px] leading-relaxed text-foreground">「{{ a.quote }}」</p>
          <p v-if="a.note" class="mt-1 text-[12px] text-muted-foreground">{{ a.note }}</p>
          <p class="mt-1 text-[11px] text-muted-foreground">第 {{ a.chapter + 1 }} 章</p>
        </div>
        <Button size="sm" variant="ghost" @click="emit('go')">前往</Button>
      </div>
    </Card>
    <EmptyState
      v-else
      icon="pencil"
      title="这本书还没有注释"
      desc="在阅读器里选中文字即可添加高亮与笔记，这里会按章节汇总。"
    />
  </div>
</template>
