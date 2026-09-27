<script setup lang="ts">
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { highlightHex as highlightColor, highlightStyleLabel } from '@/data/annotationColors'
import { canJumpTo, chapterLabel } from '@/lib/annotations'
import type { Annotation } from '@/lib/api'

/**
 * 批注标签（第 63 期从 `BookDetailView` 抽出）。
 *
 * 取色统一来自 `data/annotationColors.ts`（唯一一份）—— 这里此前自己写了一份四色表，
 * 扩容时会把新增颜色静默渲染成黄色。
 *
 * 章节显示走 `lib/annotations` 的 `chapterLabel`：设备回传的批注章节**序号未知**
 * （后端记 -1），照 `chapter + 1` 渲染会凭空写出「第 1 章」。
 */
defineProps<{ annotations: Annotation[] }>()

/**
 * `go` 带上这条批注：章节序号已知就跳那一章，未知就把决定权交回父级
 * （父级回落到「打开这本书」，不猜一个章节）。
 */
const emit = defineEmits<{ go: [Annotation] }>()
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
          <!-- 序号未知时显示设备给的章节标题；连标题都没有就整段不渲染 -->
          <p v-if="chapterLabel(a)" class="mt-1 text-[11px] text-muted-foreground">{{ chapterLabel(a) }}</p>
        </div>
        <Button
          size="sm"
          variant="ghost"
          :title="canJumpTo(a) ? '在阅读器里打开这一章' : '这条批注没有章节序号，只能打开这本书'"
          @click="emit('go', a)"
        >
          前往
        </Button>
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
