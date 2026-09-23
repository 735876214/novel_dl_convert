<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { api, type FileEntry } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useUiStore } from '@/stores/ui'

/** 导出目录：列出 output/ 下的成品文件，支持下载。接真实 /api/files + /download/{name} */
const ui = useUiStore()
const library = useLibraryStore()

/** 空态说明按真实状态分两种：0 库时「去下载/上传」是条走不通的路（第 38 期） */
const emptyDesc = computed(() =>
  library.hasNoLibraries
    ? '成品文件来自入库的书。先去「设置 → 书库管理」新建一个书库，下载与上传才会有地方落。'
    : '到「探索发现」下载一本书，或在「本地转换」上传一个 TXT。',
)

const files = ref<FileEntry[]>([])
const loading = ref(true)
/** 加载失败信息：失败不能退化成「还没有成品文件」。 */
const error = ref('')

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
  error.value = ''
  api
    .files()
    .then((r) => {
      files.value = r.output ?? []
    })
    .catch((e: Error) => {
      files.value = []
      error.value = e.message
    })
    .finally(() => {
      loading.value = false
    })
}

// 工具页子页在 KeepAlive 下不会重新挂载，所以刷新挂在 onActivated；
// 它在「首次挂载」时也会触发，因此不需要再挂 onMounted（否则会重复请求）。
onActivated(load)

function download(name: string): void {
  window.location.href = api.downloadUrl(name)
}
</script>

<template>
  <div>
    <div class="mb-4 flex items-center gap-2">
      <Button variant="primary" @click="load">刷新列表</Button>
      <span class="text-[11.5px] text-muted-foreground">
        转换完成的 EPUB / MOBI / PDF 会出现在这里，点文件名即可下载。
      </span>
    </div>

    <Card v-if="loading" class="py-10 text-center text-[12.5px] text-muted-foreground">
      加载中…
    </Card>

    <!-- 加载失败：可重试的错误态（不与「还没有成品文件」空态混淆） -->
    <Card v-else-if="error" padding="sm">
      <div class="flex flex-wrap items-center gap-2 text-[12.5px] text-destructive">
        <span>成品文件加载失败：{{ error }}</span>
        <Button size="sm" variant="secondary" class="ml-auto" @click="load">重试</Button>
      </div>
    </Card>

    <Card v-else-if="files.length" padding="none">
      <div class="flex items-center gap-2 border-b border-border px-4 py-3">
        <h3 class="text-[13px] font-semibold text-foreground">成品文件</h3>
        <span class="text-[11.5px] text-muted-foreground">
          {{ files.length }} 个 · 合计 {{ fmtSize(totalSize) }}
        </span>
      </div>

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

    <!-- 0 库时那句「到探索发现下载 / 本地转换上传」是**错的**：这两条路都要求
         先有可接收的书库，否则 400 拒收（第 38 期）。 -->
    <EmptyState v-else icon="file" title="还没有成品文件" :desc="emptyDesc" />
  </div>
</template>
