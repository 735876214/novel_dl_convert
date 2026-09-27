<script setup lang="ts">
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import type { BookFile } from '@/lib/api'

/**
 * 文件标签（第 63 期从 `BookDetailView` 抽出）。
 *
 * ⚠️ 这里列的是**这个书目条目自己带的可下载文件**（`book_detail` 的 `files`），
 * 不是书库里同名的其它书 —— 同 stem 的兄弟文件（`三体.epub` 与 `三体.mobi`）在后端
 * 是两个**独立 book_id**（`library._book_id` 取的是含扩展名的 basename），
 * 各自有自己的详情页。多文件进这一列的只有多轨有声书那种目录条目。
 *
 * 第 63 期（5/6）会把这块重做成「统计条 + 按格式分组 + THIS FILE 面板」。
 */
defineProps<{ files: BookFile[] }>()

const emit = defineEmits<{ download: [string] }>()

function fmtSize(n: number): string {
  if (!n && n !== 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtDate(ts: number): string {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
</script>

<template>
  <div>
    <Card v-if="files.length" padding="none">
      <div
        v-for="f in files"
        :key="f.name"
        class="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
      >
        <span class="grid h-8 w-11 shrink-0 place-items-center rounded-sm bg-muted text-[11px] font-semibold text-foreground">
          {{ f.format }}
        </span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[12.5px] font-medium text-foreground">{{ f.name }}</div>
          <div class="text-[11px] text-muted-foreground">{{ fmtSize(f.size) }} · {{ fmtDate(f.mtime) }}</div>
        </div>
        <Button size="sm" @click="emit('download', f.name)">下载</Button>
      </div>
    </Card>
    <EmptyState
      v-else
      icon="file"
      title="这本书还没有文件"
      desc="转换完成后这里会列出成品文件。"
    />
  </div>
</template>
