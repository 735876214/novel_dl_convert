<script setup lang="ts">
import { computed, onActivated, ref } from 'vue'

import Badge from '@/components/ui/Badge.vue'
import Button from '@/components/ui/Button.vue'
import Card from '@/components/ui/Card.vue'
import { api, type FileEntry, type WatcherStatus } from '@/lib/api'
import { useLibraryStore } from '@/stores/library'
import { useLibraryWizardStore } from '@/stores/libraryWizard'
import { useUiStore } from '@/stores/ui'

/** 本地转换：拖拽上传 TXT → EPUB；监听目录状态与手动扫描。接真实 /convert、/api/watcher、/api/scan */
const ui = useUiStore()
const library = useLibraryStore()
const wizard = useLibraryWizardStore()

/** 0 库文案里的「新建书库」出口：就地弹窗（第 55 期），不再跳设置页 */
function openWizard(): void {
  void wizard.show()
}

const dragging = ref(false)
const busy = ref(false)
const traditionalize = ref(false)
const watcher = ref<WatcherStatus | null>(null)
const inputFiles = ref<FileEntry[]>([])
const pathValue = ref('')
const lastResult = ref('')

/**
 * 上传/拖拽允许的扩展名（与后端 `POST /convert` 的允许集一致：
 * `.txt` ∪ `core/pipeline.EBOOK_EXT`，EBOOK_EXT 含 .epub/.mobi/.azw3/.pdf/.fb2/.cbz/.cbr
 * 与 `core/audio.AUDIO_EXTS`）。这里不再写死 .txt——前端只做**预校验**（后端 400 才报错，
 * 但前端应提前给出可读提示，不留「点了没反应」）。
 */
const ALLOWED_EXT = [
  '.txt', '.epub', '.mobi', '.azw3', '.pdf', '.fb2', '.cbz', '.cbr',
  '.m4b', '.mp3', '.m4a', '.opus', '.ogg', '.flac', '.aac', '.wav',
]
const ACCEPT = ALLOWED_EXT.join(',')

function extOf(name: string): string {
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i).toLowerCase() : ''
}

const watcherRunning = computed(() => Boolean(watcher.value?.running))

function fmtSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(2)} MB`
}

function refreshWatcher(): void {
  api
    .watcherStatus()
    .then((s) => {
      watcher.value = s
    })
    .catch((e: Error) => ui.toast(e.message))
}

function refreshInputs(): void {
  api
    .files()
    .then((r) => {
      inputFiles.value = r.input ?? []
    })
    .catch((e: Error) => ui.toast(e.message))
}

// 工具页子页在 KeepAlive 下不会重新挂载，所以刷新挂在 onActivated；
// 它在「首次挂载」时也会触发，因此不需要再挂 onMounted（否则会重复请求）。
// 本页没有定时器/轮询，onActivated 反复触发也不会叠加句柄。
onActivated(() => {
  refreshWatcher()
  refreshInputs()
})

/** 用 Object URL 触发浏览器下载 */
function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}

function convertFiles(fileList: FileList | File[]): void {
  const files = Array.from(fileList)
  if (!files.length) return

  // 0 库时提前拦下（第 38 期）：`/convert` 会 400 拒收（「还没有书库…」），
  // 与其把文件读进内存再让后端退回来，不如先把话说明白。
  if (library.hasNoLibraries) {
    ui.toast('还没有书库：先新建一个书库，转换结果才有地方落')
    return
  }

  // 前端预校验：跳出不支持的格式，给可读提示（不再写死 .txt）
  const allowed = files.filter((f) => ALLOWED_EXT.includes(extOf(f.name)))
  const skipped = files.length - allowed.length
  if (skipped > 0) {
    ui.toast(`已跳过 ${skipped} 个不支持的格式（仅支持 TXT 与电子书/漫画/音频）`)
  }
  if (!allowed.length) return

  busy.value = true
  lastResult.value = ''
  let finished = 0

  allowed.forEach((file) => {
    api
      .convertFile(file, traditionalize.value)
      .then(({ blob, filename }) => {
        // 文件名用后端给的真实产物名（Content-Disposition），不再自己拼 .epub（避免 x.epub.epub）
        saveBlob(blob, filename)
        lastResult.value = `已转换 ${finished + 1} / ${allowed.length}`
      })
      .catch((e: Error) => ui.toast(`${file.name}：${e.message}`))
      .finally(() => {
        finished += 1
        if (finished === allowed.length) {
          busy.value = false
          ui.toast('转换完成')
          refreshInputs()
        }
      })
  })
}

function onDrop(e: DragEvent): void {
  dragging.value = false
  if (e.dataTransfer?.files?.length) convertFiles(e.dataTransfer.files)
}

function onPick(e: Event): void {
  const input = e.target as HTMLInputElement
  if (input.files?.length) convertFiles(input.files)
  input.value = ''
}

function convertByPath(): void {
  const p = pathValue.value.trim()
  if (!p) {
    ui.toast('请填写 input 目录下的相对路径')
    return
  }
  if (library.hasNoLibraries) {
    ui.toast('还没有书库：先新建一个书库，转换结果才有地方落')
    return
  }
  if (!ALLOWED_EXT.includes(extOf(p))) {
    ui.toast(`不支持的格式：${extOf(p) || '无扩展名'}（仅支持 TXT 与电子书/漫画/音频）`)
    return
  }
  busy.value = true
  api
    .convertPath(p, traditionalize.value)
    .then(({ blob, filename }) => {
      // /convert-path 与 /convert 同口径返回文件流，文件名由后端给（不会是 x.epub.epub）
      saveBlob(blob, filename)
      lastResult.value = `已转换 ${p}`
      ui.toast('转换完成')
      refreshInputs()
    })
    .catch((e: Error) => ui.toast(e.message))
    .finally(() => {
      busy.value = false
    })
}

function toggleWatcher(): void {
  const action = watcherRunning.value ? api.watcherStop() : api.watcherStart()
  action
    .then(() => {
      ui.toast(watcherRunning.value ? '已停止监听' : '已开启监听')
      refreshWatcher()
    })
    .catch((e: Error) => ui.toast(e.message))
}

function scan(): void {
  api
    .scanNow()
    .then(() => {
      ui.toast('已触发一轮扫描')
      refreshInputs()
    })
    .catch((e: Error) => ui.toast(e.message))
}
</script>

<template>
  <div>
    <div class="grid grid-cols-1 gap-4 lg:grid-cols-2">
      <!-- 上传区 -->
      <Card>
        <h3 class="text-[13px] font-semibold text-foreground">拖拽上传</h3>
        <p class="mt-1 mb-2.5 text-[11.5px] text-muted-foreground">
          <template v-if="library.hasNoLibraries">
            还没有书库：转换结果需要有地方落，现在上传会被拒收。请先
            <button type="button" class="underline" @click="openWizard">新建一个书库</button>。
          </template>
          <template v-else>
            把 TXT 或常见电子书/漫画/音频交给流水线；TXT 会转成带目录的 EPUB，其余格式按原样入库，或交给下方监听目录自动处理。
          </template>
        </p>

        <label
          class="flex cursor-pointer flex-col items-center justify-center rounded-lg border border-dashed px-6 py-10 text-center transition-colors"
          :class="dragging ? 'border-primary bg-[var(--shell-accent-wash)]' : 'border-border hover:border-primary/60'"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="onDrop"
        >
          <input type="file" :accept="ACCEPT" multiple class="hidden" @change="onPick">
          <span class="grid h-11 w-11 place-items-center rounded-full bg-muted text-muted-foreground">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" class="h-5 w-5">
              <path d="M12 16V4M7.5 8.5L12 4l4.5 4.5M4 20h16" />
            </svg>
          </span>
          <span class="mt-3 text-[13px] font-medium text-foreground">把文件拖到这里，或点击选择</span>
          <span class="mt-1 text-[11.5px] text-muted-foreground">支持 TXT / EPUB / MOBI / PDF / CBZ 等电子书与常见音频；支持多选，逐个转换并下载</span>
        </label>

        <label class="mt-3 flex cursor-pointer items-center gap-2 text-[12.5px] text-foreground">
          <input v-model="traditionalize" type="checkbox" class="h-3.5 w-3.5 accent-[var(--primary)]">
          转成繁体
        </label>

        <p v-if="lastResult" class="mt-2 text-[11.5px] text-success">{{ lastResult }}</p>
        <p v-if="busy" class="mt-2 text-[11.5px] text-muted-foreground">转换中…</p>
      </Card>

      <!-- 路径转换 + 监听 -->
      <div class="flex min-w-0 flex-col gap-4">
        <Card>
          <h3 class="mb-2.5 text-[13px] font-semibold text-foreground">按路径转换</h3>
          <div class="flex items-center gap-2">
            <input
              v-model="pathValue"
              type="text"
              placeholder="相对 input 目录，例如 小说/某书.txt 或 漫画.cbz"
              aria-label="待转换文件路径"
              class="h-8 min-w-0 flex-1 rounded-md border border-border bg-muted px-3 text-[12.5px] text-foreground outline-none placeholder:text-muted-foreground focus:border-ring focus:bg-card"
              @keydown.enter="convertByPath"
            >
            <Button variant="primary" :disabled="busy" @click="convertByPath">转换</Button>
          </div>

          <h3 class="mt-5 mb-2 text-[13px] font-semibold text-foreground">input 目录</h3>
          <div v-if="inputFiles.length" class="flex max-h-40 flex-col gap-1 overflow-y-auto">
            <button
              v-for="f in inputFiles"
              :key="f.name"
              type="button"
              class="flex items-center gap-2 rounded-sm px-2 py-1 text-left transition-colors hover:bg-muted"
              @click="pathValue = f.name"
            >
              <span class="min-w-0 flex-1 truncate text-[12px] text-foreground">{{ f.name }}</span>
              <span class="shrink-0 text-[11px] text-muted-foreground tabular-nums">{{ fmtSize(f.size) }}</span>
            </button>
          </div>
          <p v-else class="text-[11.5px] text-muted-foreground">目录为空，拖文件进去或放进 input/ 目录。</p>
        </Card>

        <Card>
          <div class="mb-2.5 flex items-center gap-2">
            <h3 class="text-[13px] font-semibold text-foreground">目录监听</h3>
            <Badge :tone="watcherRunning ? 'ok' : 'neutral'" class="ml-auto">
              {{ watcherRunning ? '运行中' : '已停止' }}
            </Badge>
          </div>
          <p class="mb-3 text-[11.5px] text-muted-foreground">
            开启后，放进 input/ 的 TXT 会被自动转换并输出到 output/。
          </p>
          <div class="flex items-center gap-2">
            <Button :variant="watcherRunning ? 'ghost' : 'primary'" @click="toggleWatcher">
              {{ watcherRunning ? '停止监听' : '开启监听' }}
            </Button>
            <Button @click="scan">立即扫描一轮</Button>
          </div>
        </Card>
      </div>
    </div>
  </div>
</template>
