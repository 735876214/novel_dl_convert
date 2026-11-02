<script setup lang="ts">
import { ref } from 'vue'

import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { highlightHex as highlightColor, highlightStyleLabel } from '@/data/annotationColors'
import { canJumpTo, chapterLabel } from '@/lib/annotations'
import { api, type Annotation, type KoreaderExportPlan } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/**
 * 批注标签（第 63 期从 `BookDetailView` 抽出）。
 *
 * 取色统一来自 `data/annotationColors.ts`（唯一一份）—— 这里此前自己写了一份四色表，
 * 扩容时会把新增颜色静默渲染成黄色。
 *
 * 章节显示走 `lib/annotations` 的 `chapterLabel`：设备回传的批注章节**序号未知**
 * （后端记 -1），照 `chapter + 1` 渲染会凭空写出「第 1 章」。
 */
const props = defineProps<{ annotations: Annotation[]; bookId: string }>()

/**
 * `go` 带上这条批注：章节序号已知就跳那一章，未知就把决定权交回父级
 * （父级回落到「打开这本书」，不猜一个章节）。
 */
const emit = defineEmits<{ go: [Annotation] }>()

// ---- 导出成 KOReader 的批注文件（第 236 期）----
//
// ⚠️ **写的是用户设备上的文件** —— 所以默认**只算不改**（预览），
// 用户点了「写出」才落盘。
const ui = useUiStore()
const exportPlan = ref<KoreaderExportPlan | null>(null)
const exporting = ref(false)

async function previewExport(): Promise<void> {
  exporting.value = true
  try {
    exportPlan.value = await api.exportKoreaderAnnotations(props.bookId, false)
  } catch (e) {
    exportPlan.value = null
    ui.toast(e instanceof Error ? e.message : '预览失败')
  } finally {
    exporting.value = false
  }
}

async function confirmExport(): Promise<void> {
  exporting.value = true
  try {
    const r = await api.exportKoreaderAnnotations(props.bookId, true)
    exportPlan.value = r
    ui.toast(r.ok ? `已写出 ${r.total} 条批注` : '写出失败')
  } catch (e) {
    ui.toast(e instanceof Error ? e.message : '写出失败')
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div>
    <!-- 导出成 KOReader 的批注文件（第 236 期）：反向那一半 -->
    <Card v-if="annotations.length" class="mb-3" padding="sm">
      <div class="flex flex-wrap items-center gap-2">
        <div class="min-w-0 flex-1">
          <div class="text-[12.5px] font-medium text-foreground">导出成 KOReader 的批注文件</div>
          <div class="mt-0.5 text-[11.5px] text-muted-foreground">
            写到这本书旁边的 <code class="text-[11px]">&lt;书名&gt;.annotations.lua</code>
            —— KOReader 下次打开就能读到。先预览、再写出。
          </div>
        </div>
        <Button size="sm" :disabled="exporting" @click="previewExport">
          {{ exporting ? '处理中…' : '预览导出' }}
        </Button>
        <Button
          v-if="exportPlan"
          size="sm"
          variant="primary"
          :disabled="exporting"
          @click="confirmExport"
        >
          写出
        </Button>
      </div>
      <p v-if="exportPlan" class="mt-2 text-[11.5px] text-muted-foreground">
        将写入 <code class="text-[11px]">{{ exportPlan.path }}</code>
        ：文件里已有 <b class="text-foreground tabular-nums">{{ exportPlan.existing }}</b> 条
        （你在设备上写的，**不会**被覆盖），本次新增
        <b class="text-foreground tabular-nums">{{ exportPlan.add }}</b> 条。
        <span v-if="exportPlan.skipped" class="text-warning">
          （{{ exportPlan.skipped }} 条没有引文，导不出去）
        </span>
      </p>
    </Card>

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
