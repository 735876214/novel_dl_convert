<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import PageHead from '@/components/ui/PageHead.vue'
import { api, type FileEntry } from '@/lib/api'
import { useUiStore } from '@/stores/ui'

/** 导出目录：列出 output/ 下的成品文件，支持下载。接真实 /api/files + /download/{name} */
const ui = useUiStore()

const files = ref<FileEntry[]>([])
const loading = ref(true)

const totalSize = computed(() => files.value.reduce((s, f) => s + f.size, 0))

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(2)} MB`
}

function fmtTime(ts: number): string {
  return new Date(ts * 1000).toLocaleString('zh-CN', { hour12: false })
}

/** 从扩展名取格式标签 */
function ext(name: string): string {
  const i = name.lastIndexOf('.')
  return i < 0 ? 'FILE' : name.slice(i + 1).toUpperCase()
}

function load(): void {
  loading.value = true
  api
    .files()
    .then((r) => {
      files.value = r.output ?? []
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      loading.value = false
    })
}

onMounted(load)

function download(name: string): void {
  window.location.href = api.downloadUrl(name)
}
</script>

<template>
  <div>
    <PageHead
      title="导出目录"
      :desc="`${files.length} 个成品文件 · 合计 ${fmtSize(totalSize)}`"
    />

    <div class="mb-4 flex items-center gap-2">
      <Button variant="primary" @click="load">刷新列表</Button>
      <span class="text-[11.5px] text-muted-foreground">
        转换完成的 EPUB / MOBI / PDF 会出现在这里，点文件名即可下载。
      </span>
    </div>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">
      加载中…
    </Card>

    <Card v-else-if="files.length" padding="none">
      <div
        v-for="f in files"
        :key="f.name"
        class="flex items-center gap-3 border-b border-border px-4 py-3 last:border-b-0"
      >
        <span class="grid h-8 w-12 shrink-0 place-items-center rounded-sm bg-muted text-[10.5px] font-semibold text-foreground">
          {{ ext(f.name) }}
        </span>
        <div class="min-w-0 flex-1">
          <div class="truncate text-[12.5px] font-medium text-foreground">{{ f.name }}</div>
          <div class="text-[11px] text-muted-foreground tabular-nums">
            {{ fmtSize(f.size) }} · {{ fmtTime(f.mtime) }}
          </div>
        </div>
        <Badge v-if="ext(f.name) === 'EPUB'" tone="ok">推荐</Badge>
        <Button size="sm" @click="download(f.name)">下载</Button>
      </div>
    </Card>

    <EmptyState
      v-else
      icon="file"
      title="还没有成品文件"
      desc="到「探索发现」下载一本书，或在「本地转换」上传一个 TXT。"
    />
  </div>
</template>
